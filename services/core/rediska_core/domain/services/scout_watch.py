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

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Identity,
    LeadPost,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
)


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
    ) -> list[ScoutWatchRun]:
        """Get run history for a watch.

        Args:
            watch_id: The watch ID.
            limit: Maximum runs to return.

        Returns:
            List of ScoutWatchRun objects.
        """
        return (
            self.db.query(ScoutWatchRun)
            .filter(ScoutWatchRun.watch_id == watch_id)
            .order_by(desc(ScoutWatchRun.started_at))
            .limit(limit)
            .all()
        )

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
        post_author: Optional[str] = None,
    ) -> ScoutWatchPost:
        """Record a post as seen by this watch.

        Args:
            watch_id: The watch ID.
            run_id: The current run ID.
            external_post_id: The external post ID.
            post_title: The post title (for audit display).
            post_author: The post author (for audit display).

        Returns:
            The created ScoutWatchPost.
        """
        post = ScoutWatchPost(
            watch_id=watch_id,
            run_id=run_id,
            external_post_id=external_post_id,
            post_title=post_title[:500] if post_title else None,  # Truncate to column limit
            post_author=post_author,
            first_seen_at=datetime.now(timezone.utc),
            analysis_status="pending",
        )
        self.db.add(post)
        self.db.flush()
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
            The created LeadPost.
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
            return existing

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

        # Handle author account
        author_username = post_data.get("author_username")
        if author_username:
            lead.author_account_id = leads_service._get_or_create_author_account(
                provider_id=post_data["provider_id"],
                username=author_username,
                external_id=post_data.get("author_external_id"),
            )

        self.db.add(lead)
        self.db.flush()
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
]
