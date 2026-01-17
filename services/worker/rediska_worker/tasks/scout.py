"""Scout Watch tasks for automatic subreddit monitoring.

Provides background processing for:
1. Running all active watches periodically
2. Running a single watch (fetch, dedupe, analyze, create leads)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)


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
    3. For new posts, runs quick analysis
    4. Creates leads for posts that pass analysis

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
        from rediska_core.domain.services.quick_analysis import QuickAnalysisService
        from rediska_core.domain.services.inference import InferenceClient, InferenceConfig
        from rediska_core.config import get_settings

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
        posts_analyzed = 0
        leads_created = 0
        errors = []
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
                # Use browser_url (www.reddit.com) instead of request_url (oauth.reddit.com)
                # so users can click and view the same search in their browser
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

        # Process posts
        if watch.auto_analyze:
            # Set up analysis service
            settings = get_settings()
            inference_config = InferenceConfig(
                base_url=settings.inference_url,
                model_name=settings.inference_model or "default",
                timeout=settings.inference_timeout,
            )
            inference_client = InferenceClient(config=inference_config)
            analysis_service = QuickAnalysisService(
                inference_client=inference_client,
            )
        else:
            analysis_service = None

        for post in posts:
            external_post_id = post.external_id

            # Check if post already seen
            if service.is_post_seen(watch_id, external_post_id):
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

            # Analyze post if enabled
            recommendation = None
            confidence = None
            reasoning = None

            if analysis_service:
                try:
                    analysis_result = asyncio.run(
                        analysis_service.analyze_post(
                            title=post.title or "",
                            body=post.body_text or "",
                            author_username=post.author_username or "",
                            source_location=watch.source_location,
                        )
                    )

                    posts_analyzed += 1
                    recommendation = analysis_result.recommendation
                    confidence = analysis_result.confidence
                    reasoning = analysis_result.reasoning

                    logger.debug(
                        f"Post {external_post_id}: {recommendation} "
                        f"(confidence: {confidence:.2f}) - {reasoning}"
                    )

                except Exception as e:
                    logger.error(f"Failed to analyze post {external_post_id}: {e}")
                    errors.append(f"Analysis failed for {external_post_id}: {e}")
                    recommendation = "needs_review"
                    confidence = 0.0
                    reasoning = f"Analysis failed: {str(e)}"
            else:
                # No analysis - mark as suitable by default
                recommendation = "suitable"
                confidence = 1.0
                reasoning = "Auto-analyze disabled - passed by default"

            # Create lead if suitable and meets confidence threshold
            lead_id = None
            if recommendation == "suitable" and confidence >= watch.min_confidence:
                try:
                    # Normalize post data for lead creation
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

                    lead = service.save_lead_from_watch(watch, post_data)
                    lead_id = lead.id
                    leads_created += 1

                    logger.info(
                        f"Created lead {lead_id} from post {external_post_id}"
                    )

                except Exception as e:
                    logger.error(f"Failed to create lead for {external_post_id}: {e}")
                    errors.append(f"Lead creation failed for {external_post_id}: {e}")

            # Update post with analysis results
            service.update_post_analysis(
                watch_id=watch_id,
                external_post_id=external_post_id,
                recommendation=recommendation,
                confidence=confidence,
                lead_id=lead_id,
                status="analyzed" if recommendation else "pending",
                reasoning=reasoning,
            )

        # Complete run
        error_message = "; ".join(errors) if errors else None
        service.complete_run(
            run=run,
            posts_fetched=posts_fetched,
            posts_new=posts_new,
            posts_analyzed=posts_analyzed,
            leads_created=leads_created,
            error_message=error_message,
        )
        db.commit()

        logger.info(
            f"Completed watch run {run.id}: "
            f"fetched={posts_fetched}, new={posts_new}, "
            f"analyzed={posts_analyzed}, leads={leads_created}"
        )

        return {
            "status": "success",
            "watch_id": watch_id,
            "run_id": run.id,
            "search_url": search_url,
            "posts_fetched": posts_fetched,
            "posts_new": posts_new,
            "posts_analyzed": posts_analyzed,
            "leads_created": leads_created,
            "errors": errors,
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


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "run_all_watches",
    "run_single_watch",
]
