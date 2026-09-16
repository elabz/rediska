"""Scout Watch service for automatic subreddit monitoring.

This service provides:
1. Scout watch CRUD operations
2. Watch execution (fetching posts, deduplication, analysis triggering)
3. Run history tracking
4. Stats aggregation

Usage:
    service = ScoutWatchService(db=session)

    # Create a watch
    watch = service.create_watch(
        source_location="r/r4r",
        search_query="looking for AND dom",
    )

    # Run a watch
    run = await service.run_watch(watch.id)
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    Identity,
    LeadPost,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
)
from rediska_core.domain.services.external_listing import maybe_resolve_post_body
from rediska_core.domain.services.profile_item_utils import upsert_profile_item_from_post


# =============================================================================
# EXCEPTIONS
# =============================================================================


class ScoutWatchError(Exception):
    """Exception raised for scout watch errors."""

    pass


class ScoutWatchNotFoundError(ScoutWatchError):
    """Exception raised when a watch is not found."""

    pass


# =============================================================================
# CONSTANTS
# =============================================================================


VALID_SORTS = {"hot", "new", "top", "rising", "relevance"}
VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
DEFAULT_LOOKBACK_MINUTES = 30
MAX_POSTS_PER_RUN = 100

# Standing verdicts that make analysing an author's new post pointless.
# Checked before the profile-fetch/summarize/analyze pipeline runs.
SKIP_DO_NOT_CONTACT = "do_not_contact"
SKIP_ALREADY_CONTACTED = "already_contacted"
SKIP_ALREADY_ENGAGED = "already_engaged"
SKIP_LEAD_IGNORED = "lead_ignored"

SKIP_REASON_TEXT = {
    SKIP_DO_NOT_CONTACT: "Skipped: author is on the do-not-contact list",
    SKIP_ALREADY_CONTACTED: "Skipped: author has already been contacted",
    SKIP_ALREADY_ENGAGED: "Skipped: author is already engaged in a conversation",
    SKIP_LEAD_IGNORED: (
        "Skipped: author's lead was previously ignored and this post's content "
        "was already analysed"
    ),
}


# =============================================================================
# CONTENT FINGERPRINT
# =============================================================================


def content_fingerprint(
    title: Optional[str],
    body_text: Optional[str],
) -> Optional[str]:
    """Fingerprint a post's analysable content.

    Used to tell "the same post surfacing again" (skip) from "this author
    posted something new" (re-analyse). Normalisation is deliberately coarse —
    case and whitespace differences are not content changes — so that a
    crosspost of identical text fingerprints identically.

    Args:
        title: The post title.
        body_text: The post body.

    Returns:
        A hex digest, or None when there is no content to compare.
    """
    combined = " ".join(part for part in (title, body_text) if part)
    normalized = " ".join(combined.lower().split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# =============================================================================
# SERVICE
# =============================================================================


class ScoutWatchService:
    """Service for managing scout watches.

    Provides CRUD operations and execution for automatic
    subreddit monitoring.
    """

    def __init__(self, db: Session):
        """Initialize the scout watch service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    # =========================================================================
    # CREATE WATCH
    # =========================================================================

    def create_watch(
        self,
        source_location: str,
        search_query: Optional[str] = None,
        sort_by: str = "new",
        time_filter: str = "day",
        identity_id: Optional[int] = None,
        auto_analyze: bool = True,
        min_confidence: float = 0.7,
        provider_id: str = "reddit",
    ) -> ScoutWatch:
        """Create a new scout watch.

        Args:
            source_location: Location to monitor (e.g., 'r/r4r').
            search_query: Reddit search query (optional).
            sort_by: Sort order for posts.
            time_filter: Time filter for search.
            identity_id: Identity to use for API calls.
            auto_analyze: Whether to auto-analyze posts.
            min_confidence: Minimum confidence for lead creation.
            provider_id: Provider ID (default 'reddit').

        Returns:
            The created ScoutWatch.

        Raises:
            ScoutWatchError: If validation fails.
        """
        # Validate sort_by
        if sort_by not in VALID_SORTS:
            raise ScoutWatchError(f"Invalid sort_by: {sort_by}. Must be one of {VALID_SORTS}")

        # Validate time_filter
        if time_filter not in VALID_TIME_FILTERS:
            raise ScoutWatchError(
                f"Invalid time_filter: {time_filter}. Must be one of {VALID_TIME_FILTERS}"
            )

        # Validate identity if provided
        if identity_id:
            identity = self.db.query(Identity).filter(Identity.id == identity_id).first()
            if not identity:
                raise ScoutWatchError(f"Identity not found: {identity_id}")

        # Check for duplicate watch
        existing = (
            self.db.query(ScoutWatch)
            .filter(
                ScoutWatch.provider_id == provider_id,
                ScoutWatch.source_location == source_location,
                ScoutWatch.search_query == search_query,
            )
            .first()
        )
        if existing:
            raise ScoutWatchError(
                f"Watch already exists for {source_location} with this search query"
            )

        watch = ScoutWatch(
            provider_id=provider_id,
            source_location=source_location,
            search_query=search_query,
            sort_by=sort_by,
            time_filter=time_filter,
            identity_id=identity_id,
            auto_analyze=auto_analyze,
            min_confidence=min_confidence,
            is_active=True,
        )
        self.db.add(watch)
        self.db.flush()
        return watch

    # =========================================================================
    # GET WATCH
    # =========================================================================

    def get_watch(self, watch_id: int) -> Optional[ScoutWatch]:
        """Get a watch by ID.

        Args:
            watch_id: The watch ID.

        Returns:
            The ScoutWatch or None if not found.
        """
        return self.db.query(ScoutWatch).filter(ScoutWatch.id == watch_id).first()

    def get_watch_or_raise(self, watch_id: int) -> ScoutWatch:
        """Get a watch by ID or raise an error.

        Args:
            watch_id: The watch ID.

        Returns:
            The ScoutWatch.

        Raises:
            ScoutWatchNotFoundError: If not found.
        """
        watch = self.get_watch(watch_id)
        if not watch:
            raise ScoutWatchNotFoundError(f"Watch not found: {watch_id}")
        return watch

    # =========================================================================
    # LIST WATCHES
    # =========================================================================

    def list_watches(
        self,
        is_active: Optional[bool] = None,
        provider_id: Optional[str] = None,
    ) -> list[ScoutWatch]:
        """List all watches.

        Args:
            is_active: Filter by active status (optional).
            provider_id: Filter by provider (optional).

        Returns:
            List of ScoutWatch objects.
        """
        query = self.db.query(ScoutWatch)

        if is_active is not None:
            query = query.filter(ScoutWatch.is_active == is_active)

        if provider_id:
            query = query.filter(ScoutWatch.provider_id == provider_id)

        return query.order_by(desc(ScoutWatch.created_at)).all()

    # =========================================================================
    # UPDATE WATCH
    # =========================================================================

    def update_watch(
        self,
        watch_id: int,
        search_query: Optional[str] = None,
        sort_by: Optional[str] = None,
        time_filter: Optional[str] = None,
        identity_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        auto_analyze: Optional[bool] = None,
        min_confidence: Optional[float] = None,
    ) -> ScoutWatch:
        """Update a watch.

        Args:
            watch_id: The watch ID.
            search_query: New search query (optional).
            sort_by: New sort order (optional).
            time_filter: New time filter (optional).
            identity_id: New identity ID (optional).
            is_active: New active status (optional).
            auto_analyze: New auto-analyze setting (optional).
            min_confidence: New minimum confidence (optional).

        Returns:
            The updated ScoutWatch.

        Raises:
            ScoutWatchNotFoundError: If watch not found.
            ScoutWatchError: If validation fails.
        """
        watch = self.get_watch_or_raise(watch_id)

        if sort_by is not None:
            if sort_by not in VALID_SORTS:
                raise ScoutWatchError(f"Invalid sort_by: {sort_by}")
            watch.sort_by = sort_by

        if time_filter is not None:
            if time_filter not in VALID_TIME_FILTERS:
                raise ScoutWatchError(f"Invalid time_filter: {time_filter}")
            watch.time_filter = time_filter

        if search_query is not None:
            watch.search_query = search_query

        if identity_id is not None:
            identity = self.db.query(Identity).filter(Identity.id == identity_id).first()
            if not identity:
                raise ScoutWatchError(f"Identity not found: {identity_id}")
            watch.identity_id = identity_id

        if is_active is not None:
            watch.is_active = is_active

        if auto_analyze is not None:
            watch.auto_analyze = auto_analyze

        if min_confidence is not None:
            watch.min_confidence = min_confidence

        self.db.flush()
        return watch

    # =========================================================================
    # DELETE WATCH
    # =========================================================================

    def delete_watch(self, watch_id: int) -> None:
        """Delete a watch and all related data.

        Args:
            watch_id: The watch ID.

        Raises:
            ScoutWatchNotFoundError: If watch not found.
        """
        watch = self.get_watch_or_raise(watch_id)
        self.db.delete(watch)
        self.db.flush()

    # =========================================================================
    # RUN MANAGEMENT
    # =========================================================================

    def create_run(self, watch_id: int, search_url: Optional[str] = None) -> ScoutWatchRun:
        """Create a new run record for a watch.

        Args:
            watch_id: The watch ID.
            search_url: The Reddit search URL used (for debugging).

        Returns:
            The created ScoutWatchRun.
        """
        run = ScoutWatchRun(
            watch_id=watch_id,
            started_at=datetime.now(timezone.utc),
            status="running",
            search_url=search_url,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def update_run_search_url(self, run: ScoutWatchRun, search_url: str) -> None:
        """Update the search URL on a run record.

        Args:
            run: The run to update.
            search_url: The Reddit search URL.
        """
        run.search_url = search_url
        self.db.flush()

    def complete_run(
        self,
        run: ScoutWatchRun,
        posts_fetched: int,
        posts_new: int,
        posts_analyzed: int,
        leads_created: int,
        error_message: Optional[str] = None,
    ) -> ScoutWatchRun:
        """Complete a run with results.

        Args:
            run: The run to complete.
            posts_fetched: Number of posts fetched.
            posts_new: Number of new (unseen) posts.
            posts_analyzed: Number of posts analyzed.
            leads_created: Number of leads created.
            error_message: Error message if failed.

        Returns:
            The updated ScoutWatchRun.
        """
        run.completed_at = datetime.now(timezone.utc)
        run.posts_fetched = posts_fetched
        run.posts_new = posts_new
        run.posts_analyzed = posts_analyzed
        run.leads_created = leads_created

        if error_message:
            run.status = "failed"
            run.error_message = error_message
        else:
            run.status = "completed"

        # Update watch stats
        watch = run.watch
        watch.last_run_at = run.completed_at
        watch.total_posts_seen += posts_new  # Only count unique/new posts
        watch.total_matches += posts_new
        watch.total_leads_created += leads_created

        if leads_created > 0:
            watch.last_match_at = run.completed_at

        self.db.flush()
        return run

    def get_run_history(
        self,
        watch_id: int,
        limit: int = 10,
        offset: int = 0,
        has_new_posts: bool = False,
        has_leads: bool = False,
    ) -> list[ScoutWatchRun]:
        """Get run history for a watch.

        Args:
            watch_id: The watch ID.
            limit: Maximum runs to return.
            offset: Number of runs to skip.
            has_new_posts: If True, only return runs where posts_new > 0.
            has_leads: If True, only return runs where leads_created > 0.

        Returns:
            List of ScoutWatchRun objects.
        """
        query = self.db.query(ScoutWatchRun).filter(ScoutWatchRun.watch_id == watch_id)

        if has_new_posts:
            query = query.filter(ScoutWatchRun.posts_new > 0)

        if has_leads:
            query = query.filter(ScoutWatchRun.leads_created > 0)

        return (
            query
            .order_by(desc(ScoutWatchRun.started_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_runs(self, watch_id: int, has_new_posts: bool = False, has_leads: bool = False) -> int:
        """Count total runs for a watch.

        Args:
            watch_id: The watch ID.
            has_new_posts: If True, only count runs where posts_new > 0.
            has_leads: If True, only count runs where leads_created > 0.

        Returns:
            Total number of runs.
        """
        query = self.db.query(ScoutWatchRun).filter(ScoutWatchRun.watch_id == watch_id)

        if has_new_posts:
            query = query.filter(ScoutWatchRun.posts_new > 0)

        if has_leads:
            query = query.filter(ScoutWatchRun.leads_created > 0)

        return query.count()

    def get_run(self, run_id: int) -> Optional[ScoutWatchRun]:
        """Get a run by ID.

        Args:
            run_id: The run ID.

        Returns:
            The ScoutWatchRun or None if not found.
        """
        return self.db.query(ScoutWatchRun).filter(ScoutWatchRun.id == run_id).first()

    def get_posts_for_run(self, run_id: int) -> list[ScoutWatchPost]:
        """Get all posts for a specific run.

        Args:
            run_id: The run ID.

        Returns:
            List of ScoutWatchPost objects.
        """
        return (
            self.db.query(ScoutWatchPost)
            .filter(ScoutWatchPost.run_id == run_id)
            .order_by(desc(ScoutWatchPost.first_seen_at))
            .all()
        )

    def get_post(self, post_id: int) -> Optional[ScoutWatchPost]:
        """Get a post by ID.

        Args:
            post_id: The post ID.

        Returns:
            The ScoutWatchPost or None if not found.
        """
        return self.db.query(ScoutWatchPost).filter(ScoutWatchPost.id == post_id).first()

    def reset_post_for_reanalysis(self, post: ScoutWatchPost) -> ScoutWatchPost:
        """Reset a post for re-analysis.

        Args:
            post: The post to reset.

        Returns:
            The updated ScoutWatchPost.
        """
        post.analysis_status = "pending"
        post.analysis_id = None
        post.analysis_recommendation = None
        post.analysis_confidence = None
        post.analysis_reasoning = None
        self.db.flush()
        return post

    def delete_old_runs(self, retention_days: int = 3) -> dict:
        """Delete run records older than retention_days.

        Posts that carry analysis output are NEVER deleted — their
        `dimension_results_json` is often the only record of an analysis for a
        post that was never promoted to a lead, and re-deriving it costs a full
        agent pipeline run. Those posts are detached from the expiring run
        (`run_id` set to NULL) so they survive; only analysis-free sightings
        are removed along with the run.

        Posts with a human evaluation (`evaluated_at` set) are never deleted
        and are NOT detached either: they stay attached, and a run that still
        owns any post after the sweep is kept so watch history keeps showing
        the evaluated post in context (analysis-evaluation).

        Args:
            retention_days: Number of days to retain.

        Returns:
            Dict with runs_deleted, posts_deleted and posts_retained counts.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        expiring_run_ids = [
            row[0]
            for row in self.db.query(ScoutWatchRun.id)
            .filter(ScoutWatchRun.started_at < cutoff)
            .all()
        ]

        if not expiring_run_ids:
            return {"runs_deleted": 0, "posts_deleted": 0, "posts_retained": 0}

        has_analysis = or_(
            ScoutWatchPost.dimension_results_json.isnot(None),
            ScoutWatchPost.analysis_id.isnot(None),
            ScoutWatchPost.analysis_recommendation.isnot(None),
            ScoutWatchPost.lead_id.isnot(None),
        )
        not_evaluated = ScoutWatchPost.evaluated_at.is_(None)

        # Detach the posts worth keeping before their run disappears.
        # Evaluated posts keep their run instead (see docstring).
        posts_retained = (
            self.db.query(ScoutWatchPost)
            .filter(ScoutWatchPost.run_id.in_(expiring_run_ids), has_analysis, not_evaluated)
            .update({ScoutWatchPost.run_id: None}, synchronize_session=False)
        )

        posts_deleted = (
            self.db.query(ScoutWatchPost)
            .filter(ScoutWatchPost.run_id.in_(expiring_run_ids), not_evaluated)
            .delete(synchronize_session=False)
        )

        # Runs that still own a (retained, evaluated) post survive.
        runs_with_posts = {
            row[0]
            for row in self.db.query(ScoutWatchPost.run_id)
            .filter(ScoutWatchPost.run_id.in_(expiring_run_ids))
            .distinct()
            .all()
        }
        deletable_run_ids = [r for r in expiring_run_ids if r not in runs_with_posts]

        runs_deleted = 0
        if deletable_run_ids:
            runs_deleted = (
                self.db.query(ScoutWatchRun)
                .filter(ScoutWatchRun.id.in_(deletable_run_ids))
                .delete(synchronize_session=False)
            )

        self.db.flush()
        return {
            "runs_deleted": runs_deleted,
            "posts_deleted": posts_deleted,
            "posts_retained": posts_retained,
        }

    # =========================================================================
    # POST TRACKING (DEDUPLICATION)
    # =========================================================================

    def is_post_seen(self, watch_id: int, external_post_id: str) -> bool:
        """Check if a post has been seen by this watch.

        Args:
            watch_id: The watch ID.
            external_post_id: The external post ID.

        Returns:
            True if post has been seen.
        """
        existing = (
            self.db.query(ScoutWatchPost)
            .filter(
                ScoutWatchPost.watch_id == watch_id,
                ScoutWatchPost.external_post_id == external_post_id,
            )
            .first()
        )
        return existing is not None

    def record_post(
        self,
        watch_id: int,
        run_id: int,
        external_post_id: str,
        post_title: Optional[str] = None,
        post_body: Optional[str] = None,
        post_author: Optional[str] = None,
        post_url: Optional[str] = None,
    ) -> ScoutWatchPost:
        """Record a post as seen by this watch.

        Also saves the post as a profile_item for the author if they
        already exist in external_accounts, ensuring analysis has the
        post content even if the provider API hides it later.

        If the body is link-only and ``post_url`` points at a registered
        external listing host, the listing content is resolved before
        persisting, so every caller of this method (and therefore anything
        downstream of it) sees resolved content. Callers that must act on
        the resolved text themselves may resolve first; the second call is
        a no-op because the body is no longer link-only.

        Args:
            watch_id: The watch ID.
            run_id: The current run ID.
            external_post_id: The external post ID.
            post_title: The post title (for audit display).
            post_body: The post body text.
            post_author: The post author (for audit display).
            post_url: The post URL, used to resolve external listing content.

        Returns:
            The created ScoutWatchPost.
        """
        post_body = maybe_resolve_post_body(post_body, post_url)

        post = ScoutWatchPost(
            watch_id=watch_id,
            run_id=run_id,
            external_post_id=external_post_id,
            post_title=post_title[:500] if post_title else None,  # Truncate to column limit
            post_body=post_body,
            post_author=post_author,
            first_seen_at=datetime.now(timezone.utc),
            analysis_status="pending",
        )
        self.db.add(post)
        self.db.flush()

        # If the author already has an ExternalAccount, save this post as
        # a profile_item so it's available for analysis even if the author's
        # profile is hidden (NSFW).
        if post_author and (post_body or post_title):
            # Look up the watch to get provider_id and source_location
            watch = self.db.query(ScoutWatch).filter(ScoutWatch.id == watch_id).first()
            provider_id = watch.provider_id if watch else "reddit"
            source_location = watch.source_location if watch else None

            # Only create profile_item if author is already known
            account = (
                self.db.query(ExternalAccount)
                .filter(
                    ExternalAccount.provider_id == provider_id,
                    ExternalAccount.external_username == post_author,
                )
                .first()
            )
            if account:
                upsert_profile_item_from_post(
                    db=self.db,
                    account_id=account.id,
                    external_post_id=external_post_id,
                    title=post_title,
                    body_text=post_body,
                    source_location=source_location,
                )

        return post

    def update_post_analysis(
        self,
        watch_id: int,
        external_post_id: str,
        recommendation: Optional[str],
        confidence: Optional[float],
        lead_id: Optional[int] = None,
        status: str = "analyzed",
        reasoning: Optional[str] = None,
    ) -> Optional[ScoutWatchPost]:
        """Update a post with analysis results.

        Args:
            watch_id: The watch ID.
            external_post_id: The external post ID.
            recommendation: The analysis recommendation.
            confidence: The analysis confidence.
            lead_id: The created lead ID (optional).
            status: Analysis status.
            reasoning: The agent's reasoning for the recommendation.

        Returns:
            The updated ScoutWatchPost or None.
        """
        post = (
            self.db.query(ScoutWatchPost)
            .filter(
                ScoutWatchPost.watch_id == watch_id,
                ScoutWatchPost.external_post_id == external_post_id,
            )
            .first()
        )

        if not post:
            return None

        post.analysis_status = status
        post.analysis_recommendation = recommendation
        post.analysis_confidence = confidence
        post.analysis_reasoning = reasoning
        post.lead_id = lead_id
        self.db.flush()
        return post

    # =========================================================================
    # PRE-PIPELINE VERDICT GATE
    # =========================================================================

    def check_author_verdict(
        self,
        provider_id: str,
        username: str,
        post_title: Optional[str] = None,
        post_body: Optional[str] = None,
    ) -> Optional[str]:
        """Check whether a standing verdict makes analysing this author pointless.

        Evaluated in order: do-not-contact listing, then an account already
        contacted or engaged, then an author whose only lead was ignored. An
        author with an *active* lead has no standing verdict — new posts attach
        to that lead, so the pipeline still runs.

        The `ignored` verdict is content-sensitive: it only suppresses content
        we have already analysed. When `post_title`/`post_body` are supplied and
        their fingerprint does not match anything analysed for this author, the
        post is genuinely new — the author may have changed what they are
        looking for — so it is analysed again. Do-not-contact and
        contacted/engaged are unconditional; they are about the relationship,
        not the post.

        Args:
            provider_id: Provider ID.
            username: The post author's username.
            post_title: The incoming post's title, for the content check.
            post_body: The incoming post's body, for the content check.

        Returns:
            A skip reason code (see SKIP_REASON_TEXT) or None to proceed.
        """
        from rediska_core.domain.models import DoNotContact
        from rediska_core.domain.services.leads import INACTIVE_STATUSES, LeadsService

        on_dnc = (
            self.db.query(DoNotContact)
            .filter(
                DoNotContact.provider_id == provider_id,
                DoNotContact.external_username == username,
            )
            .first()
        )
        if on_dnc:
            return SKIP_DO_NOT_CONTACT

        account = (
            self.db.query(ExternalAccount)
            .filter(
                ExternalAccount.provider_id == provider_id,
                ExternalAccount.external_username == username,
            )
            .first()
        )
        if not account:
            # Unknown author: no prior verdict of any kind.
            return None

        if account.contact_state == "contacted":
            return SKIP_ALREADY_CONTACTED

        if account.engagement_state == "engaged":
            return SKIP_ALREADY_ENGAGED

        leads_service = LeadsService(self.db)
        if leads_service.get_active_lead_for_author(provider_id, account.id):
            return None

        ignored_lead = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.provider_id == provider_id,
                LeadPost.author_account_id == account.id,
                LeadPost.status.in_(INACTIVE_STATUSES),
                LeadPost.deleted_at.is_(None),
            )
            .first()
        )
        if not ignored_lead:
            return None

        fingerprint = content_fingerprint(post_title, post_body)
        if fingerprint is None:
            # No content to compare (e.g. manual paths that don't carry a body):
            # fall back to the author-level verdict.
            return SKIP_LEAD_IGNORED

        if fingerprint in self._analysed_fingerprints(provider_id, account.id):
            return SKIP_LEAD_IGNORED

        # New content from a previously rejected author — worth another look.
        return None

    def _analysed_fingerprints(self, provider_id: str, account_id: int) -> set[str]:
        """Fingerprints of every post already analysed for an author.

        Covers both saved leads and scout sightings that carry analysis output,
        so a post already judged under one watch is not re-analysed when a
        second watch surfaces the same text.
        """
        fingerprints = set()

        leads = (
            self.db.query(LeadPost.title, LeadPost.body_text)
            .filter(
                LeadPost.provider_id == provider_id,
                LeadPost.author_account_id == account_id,
            )
            .all()
        )
        for title, body in leads:
            fingerprints.add(content_fingerprint(title, body))

        account = self.db.query(ExternalAccount).filter(
            ExternalAccount.id == account_id
        ).first()
        if account:
            posts = (
                self.db.query(ScoutWatchPost.post_title, ScoutWatchPost.post_body)
                .filter(
                    ScoutWatchPost.post_author == account.external_username,
                    ScoutWatchPost.analysis_recommendation.isnot(None),
                )
                .all()
            )
            for title, body in posts:
                fingerprints.add(content_fingerprint(title, body))

        fingerprints.discard(None)
        return fingerprints

    # =========================================================================
    # HELPER: SAVE LEAD FROM WATCH
    # =========================================================================

    def save_lead_from_watch(
        self,
        watch: ScoutWatch,
        post_data: dict[str, Any],
        user_interests_summary: Optional[str] = None,
        user_character_summary: Optional[str] = None,
    ) -> LeadPost:
        """Save a post as a lead from a scout watch.

        Args:
            watch: The scout watch.
            post_data: Normalized post data.
            user_interests_summary: Summary of user interests from their posts.
            user_character_summary: Summary of user character from their comments.

        Returns:
            The created LeadPost, or the author's existing active lead when the
            post was attached to it (flagged via the transient `_attached`).
        """
        from rediska_core.domain.services.leads import LeadsService

        leads_service = LeadsService(self.db)

        # Check if lead already exists
        existing = leads_service.get_lead_by_external_id(
            provider_id=post_data["provider_id"],
            external_post_id=post_data["external_post_id"],
        )

        if existing:
            # Update summaries if they're provided and not already set
            if user_interests_summary and not existing.user_interests_summary:
                existing.user_interests_summary = user_interests_summary
            if user_character_summary and not existing.user_character_summary:
                existing.user_character_summary = user_character_summary
            self.db.flush()
            existing._attached = False  # type: ignore[attr-defined]
            return existing

        # Resolve the author up front: an author with an active lead gets this
        # post attached to it rather than a duplicate sibling lead.
        author_account_id = None
        author_username = post_data.get("author_username")
        if author_username:
            author_account_id = leads_service._get_or_create_author_account(
                provider_id=post_data["provider_id"],
                username=author_username,
                external_id=post_data.get("author_external_id"),
            )

        if author_account_id:
            author_lead = leads_service.get_active_lead_for_author(
                post_data["provider_id"], author_account_id
            )
            if author_lead:
                if user_interests_summary and not author_lead.user_interests_summary:
                    author_lead.user_interests_summary = user_interests_summary
                if user_character_summary and not author_lead.user_character_summary:
                    author_lead.user_character_summary = user_character_summary
                # Preserve the attached post's content for analysis.
                if post_data.get("body_text") or post_data.get("title"):
                    upsert_profile_item_from_post(
                        db=self.db,
                        account_id=author_account_id,
                        external_post_id=post_data["external_post_id"],
                        title=post_data.get("title"),
                        body_text=post_data.get("body_text"),
                        source_location=post_data.get("source_location"),
                    )
                author_lead.updated_at = datetime.utcnow()
                self.db.flush()
                author_lead._attached = True  # type: ignore[attr-defined]
                return author_lead

        # Parse post_created_at if it's a string
        post_created_at = post_data.get("post_created_at")
        if isinstance(post_created_at, str):
            post_created_at = datetime.fromisoformat(post_created_at.replace("Z", "+00:00"))

        # Create new lead with scout_watch source
        lead = LeadPost(
            provider_id=post_data["provider_id"],
            source_location=post_data["source_location"],
            external_post_id=post_data["external_post_id"],
            post_url=post_data["post_url"],
            title=post_data.get("title"),
            body_text=post_data.get("body_text"),
            post_created_at=post_created_at,
            status="new",
            remote_visibility="unknown",
            lead_source="scout_watch",
            scout_watch_id=watch.id,
            user_interests_summary=user_interests_summary,
            user_character_summary=user_character_summary,
        )

        lead.author_account_id = author_account_id

        self.db.add(lead)
        self.db.flush()
        lead._attached = False  # type: ignore[attr-defined]
        return lead


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "ScoutWatchService",
    "ScoutWatchError",
    "ScoutWatchNotFoundError",
    "VALID_SORTS",
    "VALID_TIME_FILTERS",
    "DEFAULT_LOOKBACK_MINUTES",
    "MAX_POSTS_PER_RUN",
    "SKIP_DO_NOT_CONTACT",
    "SKIP_ALREADY_CONTACTED",
    "SKIP_ALREADY_ENGAGED",
    "SKIP_LEAD_IGNORED",
    "SKIP_REASON_TEXT",
    "content_fingerprint",
]
