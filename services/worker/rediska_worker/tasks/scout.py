"""Scout Watch tasks for automatic subreddit monitoring.

Provides background processing for:
1. Running all active watches periodically
2. Running a single watch (fetch, dedupe, queue analysis)
3. Analyzing posts with full pipeline (profile fetch, summaries, 6-agent analysis)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

MAX_PROFILE_POSTS = 20
MAX_PROFILE_COMMENTS = 100


# =============================================================================
# HELPERS
# =============================================================================


def _now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def _get_db_session() -> Any:
    """Get database session for task execution."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os

        database_url = os.getenv("MYSQL_URL")
        if not database_url:
            raise RuntimeError("MYSQL_URL not configured")

        engine = create_engine(database_url)
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        raise


def _get_reddit_adapter(db: Any, identity_id: Optional[int] = None) -> Any:
    """Create a Reddit adapter with credentials from database.

    Args:
        db: Database session.
        identity_id: Optional identity ID to use. If None, uses default.

    Returns:
        RedditAdapter instance.
    """
    import json
    from rediska_core.domain.models import Identity
    from rediska_core.providers.reddit.adapter import RedditAdapter
    from rediska_core.config import get_settings
    from rediska_core.domain.services.credentials import CredentialsService
    from rediska_core.infrastructure.crypto import CryptoService

    settings = get_settings()

    # Get identity
    if identity_id:
        identity = db.query(Identity).filter(Identity.id == identity_id).first()
    else:
        identity = db.query(Identity).filter(
            Identity.provider_id == "reddit",
            Identity.is_default == True,
        ).first()

    if not identity:
        raise RuntimeError("No identity found for Reddit")

    # Get decrypted credentials using CredentialsService
    crypto = CryptoService(settings.encryption_key)
    creds_service = CredentialsService(db, crypto)

    tokens_json = creds_service.get_credential_decrypted(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_tokens",
    )

    if not tokens_json:
        raise RuntimeError(f"No credentials found for identity {identity.id}")

    tokens = json.loads(tokens_json)

    return RedditAdapter(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        client_id=settings.provider_reddit_client_id,
        client_secret=settings.provider_reddit_client_secret,
        user_agent=settings.provider_reddit_user_agent,
    )


# =============================================================================
# TASKS
# =============================================================================


@app.task(
    bind=True,
    name="scout.run_all_watches",
    max_retries=2,
    default_retry_delay=60,
)
def run_all_watches(self) -> dict:
    """Run all active scout watches.

    This is the periodic task that runs every 5 minutes.
    It queues individual watch runs for each active watch.

    Returns:
        dict: Summary with queued watch count and task IDs.
    """
    db = None

    try:
        db = _get_db_session()

        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db)
        watches = service.list_watches(is_active=True)

        if not watches:
            logger.info("No active watches to run")
            return {
                "status": "success",
                "message": "No active watches",
                "queued": 0,
            }

        logger.info(f"Running {len(watches)} active watches")

        task_ids = []
        for watch in watches:
            task = run_single_watch.delay(watch_id=watch.id)
            task_ids.append({
                "watch_id": watch.id,
                "task_id": task.id,
                "source_location": watch.source_location,
            })
            logger.debug(f"Queued watch {watch.id} ({watch.source_location}): {task.id}")

        return {
            "status": "success",
            "queued": len(task_ids),
            "tasks": task_ids,
        }

    except Exception as exc:
        logger.error(f"Failed to run all watches: {str(exc)}", exc_info=True)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60)
        else:
            return {
                "status": "failed",
                "error": str(exc),
            }

    finally:
        if db:
            db.close()


@app.task(
    bind=True,
    name="scout.run_single_watch",
    max_retries=3,
    default_retry_delay=120,
)
def run_single_watch(self, watch_id: int) -> dict:
    """Run a single scout watch.

    This task:
    1. Fetches posts from the subreddit (with search if configured)
    2. Deduplicates posts (skips already-seen posts)
    3. For new posts with auto_analyze enabled, queues analyze_and_decide task

    Args:
        watch_id: ID of the watch to run.

    Returns:
        dict: Task result with run stats.
    """
    db = None
    run = None

    try:
        db = _get_db_session()

        from rediska_core.domain.services.scout_watch import (
            ScoutWatchService,
            ScoutWatchNotFoundError,
        )

        service = ScoutWatchService(db)

        # Get watch
        try:
            watch = service.get_watch_or_raise(watch_id)
        except ScoutWatchNotFoundError:
            logger.error(f"Watch not found: {watch_id}")
            return {
                "status": "error",
                "error": f"Watch not found: {watch_id}",
                "watch_id": watch_id,
            }

        if not watch.is_active:
            logger.info(f"Watch {watch_id} is not active, skipping")
            return {
                "status": "skipped",
                "reason": "Watch not active",
                "watch_id": watch_id,
            }

        # Create run record
        run = service.create_run(watch_id)
        db.commit()

        logger.info(
            f"Starting watch run {run.id} for watch {watch_id} "
            f"({watch.source_location})"
        )

        # Get Reddit adapter
        try:
            adapter = _get_reddit_adapter(db, watch.identity_id)
        except Exception as e:
            logger.error(f"Failed to get Reddit adapter: {e}")
            service.complete_run(
                run=run,
                posts_fetched=0,
                posts_new=0,
                posts_analyzed=0,
                leads_created=0,
                error_message=f"Failed to get Reddit adapter: {e}",
            )
            db.commit()
            return {
                "status": "error",
                "error": str(e),
                "watch_id": watch_id,
                "run_id": run.id,
            }

        # Fetch posts
        posts_fetched = 0
        posts_new = 0
        analysis_tasks_queued = 0
        search_url = None

        try:
            result = asyncio.run(
                adapter.browse_location(
                    location=watch.source_location,
                    sort=watch.sort_by,
                    time_filter=watch.time_filter,
                    query=watch.search_query,
                    limit=100,  # Fetch more posts to find new ones
                )
            )

            posts = result.items
            posts_fetched = len(posts)

            # Extract and store the browser-friendly search URL for debugging
            if result.metadata:
                search_url = result.metadata.get("browser_url") or result.metadata.get("request_url")
                service.update_run_search_url(run, search_url)
                db.commit()

            logger.info(f"Fetched {posts_fetched} posts from {watch.source_location} (URL: {search_url})")

        except Exception as e:
            logger.error(f"Failed to fetch posts: {e}")
            service.complete_run(
                run=run,
                posts_fetched=0,
                posts_new=0,
                posts_analyzed=0,
                leads_created=0,
                error_message=f"Failed to fetch posts: {e}",
            )
            db.commit()
            return {
                "status": "error",
                "error": str(e),
                "watch_id": watch_id,
                "run_id": run.id,
            }

        # Process each post
        posts_skipped_empty = 0
        for post in posts:
            external_post_id = post.external_id

            # Check if already seen
            if service.is_post_seen(watch_id, external_post_id):
                continue

            # Skip posts with empty body (user may have hidden content)
            if not post.body_text or not post.body_text.strip():
                posts_skipped_empty += 1
                logger.debug(f"Skipping post {external_post_id} - empty body (content hidden)")
                continue

            posts_new += 1

            # Record post with title and author for audit
            scout_post = service.record_post(
                watch_id=watch_id,
                run_id=run.id,
                external_post_id=external_post_id,
                post_title=post.title,
                post_author=post.author_username,
            )
            db.commit()

            # Queue full analysis pipeline if auto_analyze is enabled
            if watch.auto_analyze:
                try:
                    # Prepare post data for the analysis task
                    post_data = {
                        "provider_id": "reddit",
                        "source_location": watch.source_location,
                        "external_post_id": external_post_id,
                        "post_url": f"https://reddit.com{post.url}" if post.url and not post.url.startswith("http") else post.url,
                        "title": post.title,
                        "body_text": post.body_text,
                        "author_username": post.author_username,
                        "author_external_id": post.author_id,
                        "post_created_at": post.created_at.isoformat() if post.created_at else None,
                    }

                    # Queue the full analysis pipeline
                    task = analyze_and_decide.delay(
                        watch_id=watch_id,
                        scout_post_id=scout_post.id,
                        post_data=post_data,
                    )
                    analysis_tasks_queued += 1

                    logger.debug(
                        f"Queued analyze_and_decide for post {external_post_id}: task_id={task.id}"
                    )

                except Exception as e:
                    logger.error(f"Failed to queue analysis for {external_post_id}: {e}")
                    # Mark as failed
                    service.update_post_analysis(
                        watch_id=watch_id,
                        external_post_id=external_post_id,
                        recommendation=None,
                        confidence=None,
                        lead_id=None,
                        status="failed",
                        reasoning=f"Failed to queue analysis: {e}",
                    )
                    db.commit()

        # Complete run (posts_analyzed and leads_created will be updated by analyze_and_decide tasks)
        service.complete_run(
            run=run,
            posts_fetched=posts_fetched,
            posts_new=posts_new,
            posts_analyzed=0,  # Will be updated by child tasks
            leads_created=0,   # Will be updated by child tasks
            error_message=None,
        )
        db.commit()

        logger.info(
            f"Completed watch run {run.id}: "
            f"fetched={posts_fetched}, new={posts_new}, "
            f"skipped_empty={posts_skipped_empty}, "
            f"analysis_tasks_queued={analysis_tasks_queued}"
        )

        return {
            "status": "success",
            "watch_id": watch_id,
            "run_id": run.id,
            "search_url": search_url,
            "posts_fetched": posts_fetched,
            "posts_new": posts_new,
            "posts_skipped_empty": posts_skipped_empty,
            "analysis_tasks_queued": analysis_tasks_queued,
        }

    except Exception as exc:
        logger.error(f"Watch run failed: {str(exc)}", exc_info=True)

        # Try to complete run with error
        if run and db:
            try:
                from rediska_core.domain.services.scout_watch import ScoutWatchService
                service = ScoutWatchService(db)
                service.complete_run(
                    run=run,
                    posts_fetched=0,
                    posts_new=0,
                    posts_analyzed=0,
                    leads_created=0,
                    error_message=str(exc),
                )
                db.commit()
            except Exception:
                pass

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))
        else:
            return {
                "status": "failed",
                "error": str(exc),
                "watch_id": watch_id,
                "run_id": run.id if run else None,
            }

    finally:
        if db:
            db.close()


@app.task(
    bind=True,
    name="scout.analyze_and_decide",
    max_retries=3,
    default_retry_delay=120,
)
def analyze_and_decide(
    self,
    watch_id: int,
    scout_post_id: int,
    post_data: dict,
) -> dict:
    """Full analysis pipeline for a Scout Watch post.

    This task implements the complete analysis pipeline:
    1. Fetch poster's profile (bio, karma, account age)
    2. Fetch poster's last 20 posts
    3. Fetch poster's last 100 comments
    4. Generate user_interests summary from posts
    5. Generate user_character summary from comments
    6. Run 6-agent multi-agent analysis
    7. If suitable + confident: create lead
    8. Update scout_watch_posts with results

    The multi-agent analysis DECIDES whether to create a lead.
    This is the only place where leads are created for scout watches.

    Args:
        watch_id: ID of the watch.
        scout_post_id: ID of the scout_watch_posts record.
        post_data: Normalized post data dict.

    Returns:
        dict: Analysis results and lead_id (if created).
    """
    db = None

    try:
        db = _get_db_session()

        from rediska_core.domain.services.scout_watch import ScoutWatchService
        from rediska_core.domain.services.inference import get_inference_client
        from rediska_core.domain.services.interests_summary import InterestsSummaryService
        from rediska_core.domain.services.character_summary import CharacterSummaryService
        from rediska_core.domain.models import ScoutWatchPost, ScoutWatch

        service = ScoutWatchService(db)

        # Get watch and scout_post records
        watch = db.query(ScoutWatch).filter(ScoutWatch.id == watch_id).first()
        if not watch:
            raise ValueError(f"Watch not found: {watch_id}")

        scout_post = db.query(ScoutWatchPost).filter(ScoutWatchPost.id == scout_post_id).first()
        if not scout_post:
            raise ValueError(f"Scout post not found: {scout_post_id}")

        author_username = post_data.get("author_username")
        if not author_username:
            raise ValueError("Post has no author_username")

        external_post_id = post_data.get("external_post_id")

        logger.info(
            f"Starting analyze_and_decide for post {external_post_id} "
            f"by u/{author_username}"
        )

        # Get Reddit adapter
        adapter = _get_reddit_adapter(db, watch.identity_id)

        # =================================================================
        # STEP 1: Update status to fetching_profile
        # =================================================================
        scout_post.analysis_status = "fetching_profile"
        db.commit()

        # =================================================================
        # STEP 2: Fetch profile data
        # =================================================================
        async def fetch_profile_data():
            """Fetch profile, posts, and comments in parallel."""
            profile = await adapter.fetch_profile(author_username)

            # Fetch posts and comments with limits
            posts = await adapter.fetch_user_posts(author_username, limit=MAX_PROFILE_POSTS)
            comments = await adapter.fetch_user_comments(author_username, limit=MAX_PROFILE_COMMENTS)

            return profile, posts, comments

        try:
            profile, user_posts, user_comments = asyncio.run(fetch_profile_data())
            scout_post.profile_fetched_at = _now_utc()
            db.commit()

            logger.info(
                f"Fetched profile for u/{author_username}: "
                f"posts={len(user_posts)}, comments={len(user_comments)}"
            )

        except Exception as e:
            logger.error(f"Failed to fetch profile for u/{author_username}: {e}")
            scout_post.analysis_status = "failed"
            scout_post.analysis_reasoning = f"Failed to fetch profile: {e}"
            db.commit()
            return {
                "status": "failed",
                "error": f"Profile fetch failed: {e}",
                "watch_id": watch_id,
                "scout_post_id": scout_post_id,
            }

        # =================================================================
        # STEP 3: Update status to summarizing
        # =================================================================
        scout_post.analysis_status = "summarizing"
        db.commit()

        # =================================================================
        # STEP 4: Generate summaries
        # =================================================================
        async def generate_summaries():
            """Generate interests and character summaries."""
            inference_client = get_inference_client()

            try:
                # Create summary services
                interests_service = InterestsSummaryService(
                    inference_client=inference_client,
                    db=db,
                )
                character_service = CharacterSummaryService(
                    inference_client=inference_client,
                    db=db,
                )

                # Convert ProviderProfileItem to ProfileItem-like objects for summaries
                # The summary services expect ProfileItem objects with item_type and text_content
                class ProfileItemLike:
                    def __init__(self, item_type: str, text_content: str, item_created_at=None):
                        self.item_type = item_type
                        self.text_content = text_content
                        self.item_created_at = item_created_at

                posts_for_summary = [
                    ProfileItemLike("post", p.body_text or p.title or "", p.created_at)
                    for p in user_posts
                    if p.body_text or p.title
                ]

                comments_for_summary = [
                    ProfileItemLike("comment", c.body_text or "", c.created_at)
                    for c in user_comments
                    if c.body_text
                ]

                # Run summaries in parallel
                interests_result, character_result = await asyncio.gather(
                    interests_service.summarize(posts_for_summary),
                    character_service.summarize(comments_for_summary),
                )

                return interests_result, character_result

            finally:
                await inference_client.close()

        try:
            interests_result, character_result = asyncio.run(generate_summaries())

            # Store summaries
            scout_post.user_interests = interests_result.summary if interests_result.success else ""
            scout_post.user_character = character_result.summary if character_result.success else ""
            db.commit()

            logger.info(
                f"Generated summaries for u/{author_username}: "
                f"interests_success={interests_result.success}, "
                f"character_success={character_result.success}"
            )

        except Exception as e:
            logger.error(f"Failed to generate summaries for u/{author_username}: {e}")
            # Continue anyway - summaries are helpful but not required
            scout_post.user_interests = ""
            scout_post.user_character = ""
            db.commit()

        # =================================================================
        # STEP 5: Update status to analyzing
        # =================================================================
        scout_post.analysis_status = "analyzing"
        db.commit()

        # =================================================================
        # STEP 6: Run 6-agent multi-agent analysis
        # =================================================================
        async def run_multi_agent_analysis():
            """Run the 6-agent analysis pipeline."""
            from rediska_core.domain.services.multi_agent_analysis import MultiAgentAnalysisService
            from rediska_core.domain.services.agent_prompt import AgentPromptService

            inference_client = get_inference_client()

            try:
                prompt_service = AgentPromptService(db)
                analysis_service = MultiAgentAnalysisService(
                    db=db,
                    inference_client=inference_client,
                    prompt_service=prompt_service,
                )

                # Build input context for agents (without requiring a LeadPost)
                items_by_type = {
                    "post": [
                        {
                            "text": p.body_text or p.title or "",
                            "created_at": p.created_at.isoformat() if p.created_at else None,
                        }
                        for p in user_posts
                        if p.body_text or p.title
                    ],
                    "comment": [
                        {
                            "text": c.body_text or "",
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                        }
                        for c in user_comments
                        if c.body_text
                    ],
                }

                input_context = {
                    "lead": {
                        "title": post_data.get("title", ""),
                        "body": post_data.get("body_text", ""),
                        "url": post_data.get("post_url", ""),
                        "created_at": post_data.get("post_created_at"),
                        "source_location": post_data.get("source_location", ""),
                    },
                    "profile": {
                        "username": author_username,
                        "bio": profile.bio if profile else "",
                        "karma": profile.karma if profile else 0,
                        "created_at": profile.created_at.isoformat() if profile and profile.created_at else None,
                        "is_verified": profile.is_verified if profile else False,
                        "post_text": " ".join([
                            item.get("text", "") for item in items_by_type.get("post", [])
                        ]),
                        "comment_text": " ".join([
                            item.get("text", "") for item in items_by_type.get("comment", [])
                        ]),
                    },
                    "summaries": {
                        "user_interests": scout_post.user_interests or "",
                        "user_character": scout_post.user_character or "",
                    },
                    "items_by_type": items_by_type,
                }

                # Run dimension agents in parallel
                dimension_results = await analysis_service._run_dimension_agents(
                    analysis_id=None,  # No analysis record yet
                    input_context=input_context,
                    dimensions=analysis_service.DIMENSIONS,
                )

                # Run meta-analysis coordinator
                meta_result = await analysis_service._run_meta_analysis(
                    analysis_id=None,
                    dimension_results=dimension_results,
                )

                return dimension_results, meta_result

            finally:
                await inference_client.close()

        try:
            dimension_results, meta_result = asyncio.run(run_multi_agent_analysis())

            # Extract recommendation from meta-analysis
            meta_output = meta_result.get("parsed_output", {}) or {}

            # Normalize the recommendation (handle various LLM output formats)
            recommendation = None
            for field in ["recommendation", "suitability_recommendation", "final_recommendation"]:
                if field in meta_output and meta_output[field]:
                    rec = meta_output[field]
                    if isinstance(rec, dict):
                        rec = rec.get("overall_suitability") or rec.get("recommendation")
                    recommendation = rec
                    break

            # Map common values to our expected values
            if recommendation:
                recommendation = recommendation.lower().strip()
                if recommendation in ["pass", "suitable", "yes", "true", "approved"]:
                    recommendation = "suitable"
                elif recommendation in ["fail", "not_recommended", "no", "false", "rejected"]:
                    recommendation = "not_recommended"
                else:
                    recommendation = "needs_review"
            else:
                recommendation = "needs_review"

            # Extract confidence
            confidence = None
            for field in ["confidence", "confidence_score", "overall_confidence"]:
                if field in meta_output and meta_output[field] is not None:
                    try:
                        confidence = float(meta_output[field])
                        break
                    except (ValueError, TypeError):
                        pass

            if confidence is None:
                confidence = 0.5  # Default confidence if not provided

            # Extract reasoning
            reasoning = meta_output.get("reasoning") or meta_output.get("recommendation_reasoning") or ""

            logger.info(
                f"Multi-agent analysis for u/{author_username}: "
                f"recommendation={recommendation}, confidence={confidence:.2f}"
            )

        except Exception as e:
            logger.error(f"Multi-agent analysis failed for u/{author_username}: {e}")
            scout_post.analysis_status = "failed"
            scout_post.analysis_reasoning = f"Multi-agent analysis failed: {e}"
            db.commit()
            return {
                "status": "failed",
                "error": f"Analysis failed: {e}",
                "watch_id": watch_id,
                "scout_post_id": scout_post_id,
            }

        # =================================================================
        # STEP 7: Decide - Create lead or not
        # =================================================================
        lead_id = None
        analysis_id = None

        if recommendation == "suitable" and confidence >= watch.min_confidence:
            try:
                from rediska_core.domain.models import LeadAnalysis, AnalysisDimension
                from rediska_core.domain.services.agent_prompt import AgentPromptService

                # Get summaries from scout_post
                interests_summary = scout_post.user_interests or ""
                character_summary = scout_post.user_character or ""

                # Create lead with summaries
                lead = service.save_lead_from_watch(
                    watch,
                    post_data,
                    user_interests_summary=interests_summary,
                    user_character_summary=character_summary,
                )
                lead_id = lead.id

                # Build prompt versions dict first (needed for LeadAnalysis)
                prompt_service = AgentPromptService(db)
                prompt_versions = {}
                for dim_name in list(dimension_results.keys()) + ["meta_analysis"]:
                    try:
                        prompt = prompt_service.get_active_prompt(dim_name)
                        prompt_versions[dim_name] = prompt.version
                    except Exception:
                        prompt_versions[dim_name] = 1

                # Create LeadAnalysis record
                analysis = LeadAnalysis(
                    lead_id=lead_id,
                    account_id=lead.author_account_id,  # Required field
                    status="completed",
                    started_at=_now_utc(),
                    completed_at=_now_utc(),
                    final_recommendation=recommendation,
                    recommendation_reasoning=reasoning[:2000] if reasoning else None,
                    confidence_score=confidence,
                    prompt_versions_json=prompt_versions,  # Required field
                )
                db.add(analysis)
                db.flush()  # Get the analysis.id
                analysis_id = analysis.id

                # Store dimension results
                for dim_name, dim_result in dimension_results.items():
                    dim_record = AnalysisDimension(
                        analysis_id=analysis_id,
                        dimension=dim_name,
                        started_at=_now_utc(),
                        completed_at=_now_utc(),
                        status="completed" if dim_result.get("success") else "failed",
                        input_data_json={},
                        output_json=dim_result.get("parsed_output"),
                        prompt_version=prompt_versions.get(dim_name, 1),
                        error_detail=dim_result.get("error"),
                    )
                    db.add(dim_record)

                # Store meta-analysis dimension
                meta_dim_record = AnalysisDimension(
                    analysis_id=analysis_id,
                    dimension="meta_analysis",
                    started_at=_now_utc(),
                    completed_at=_now_utc(),
                    status="completed" if meta_result.get("success") else "failed",
                    input_data_json={},
                    output_json=meta_output,
                    prompt_version=prompt_versions.get("meta_analysis", 1),
                    error_detail=meta_result.get("error"),
                )
                db.add(meta_dim_record)

                # Link analysis to lead
                lead.latest_analysis_id = analysis_id
                lead.analysis_recommendation = recommendation
                lead.analysis_confidence = confidence

                # Update scout_post with analysis link
                scout_post.analysis_id = analysis_id

                logger.info(
                    f"Created lead {lead_id} with analysis {analysis_id} from post {external_post_id} "
                    f"(recommendation={recommendation}, confidence={confidence:.2f})"
                )

                # Update watch stats
                watch.total_leads_created = (watch.total_leads_created or 0) + 1
                watch.last_match_at = _now_utc()
                db.commit()

            except Exception as e:
                logger.error(f"Failed to create lead for {external_post_id}: {e}")
                reasoning = f"{reasoning}; Lead creation failed: {e}"

        else:
            logger.info(
                f"Post {external_post_id} did not qualify for lead: "
                f"recommendation={recommendation}, confidence={confidence:.2f}, "
                f"min_confidence={watch.min_confidence}"
            )

        # =================================================================
        # STEP 8: Update scout_watch_posts with results
        # =================================================================
        scout_post.analysis_status = "analyzed"
        scout_post.analysis_recommendation = recommendation
        scout_post.analysis_confidence = confidence
        scout_post.analysis_reasoning = reasoning[:2000] if reasoning else None  # Truncate if too long
        scout_post.lead_id = lead_id
        db.commit()

        # Update watch stats
        watch.total_posts_seen = (watch.total_posts_seen or 0) + 1
        db.commit()

        return {
            "status": "success",
            "watch_id": watch_id,
            "scout_post_id": scout_post_id,
            "external_post_id": external_post_id,
            "author_username": author_username,
            "recommendation": recommendation,
            "confidence": confidence,
            "lead_id": lead_id,
            "lead_created": lead_id is not None,
        }

    except Exception as exc:
        logger.error(f"analyze_and_decide failed: {str(exc)}", exc_info=True)

        # Try to mark as failed
        if db:
            try:
                scout_post = db.query(ScoutWatchPost).filter(
                    ScoutWatchPost.id == scout_post_id
                ).first()
                if scout_post:
                    scout_post.analysis_status = "failed"
                    scout_post.analysis_reasoning = str(exc)[:2000]
                    db.commit()
            except Exception:
                pass

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))
        else:
            return {
                "status": "failed",
                "error": str(exc),
                "watch_id": watch_id,
                "scout_post_id": scout_post_id,
            }

    finally:
        if db:
            db.close()


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "run_all_watches",
    "run_single_watch",
    "analyze_and_decide",
]
