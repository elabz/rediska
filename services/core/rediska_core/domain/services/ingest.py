"""Ingestion service for backfilling conversations and messages.

This service handles:
1. Backfilling conversations from a provider
2. Backfilling messages for specific conversations
3. Fan-out orchestration (enqueue message backfill per conversation)
4. Incremental sync (delta sync since last sync time)
5. Idempotent upserts (no duplicates)

The "no remote delete" policy is enforced - remote deletions only update
visibility fields, never delete local rows.

Usage:
    ingest = IngestService(db=session, adapter=reddit_adapter, identity_id=1)

    # Backfill all conversations
    result = await ingest.backfill_conversations()

    # Backfill messages for a specific conversation
    result = await ingest.backfill_messages("conv_123")

    # Full backfill with fan-out
    result = await ingest.backfill_all()

    # Incremental sync
    result = await ingest.sync_delta(since_ts=last_sync_time)

    # Check if sync is needed
    if ingest.should_sync():
        await ingest.sync_delta()
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Job,
    Message,
)
from rediska_core.domain.services.jobs import JobService
from rediska_core.domain.services.remote_status import ContentVisibility, RemoteStatusMapper
from rediska_core.providers.base import (
    ProviderAdapter,
    ProviderConversation,
    ProviderMessage,
    RemoteVisibility as ProviderVisibility,
)


@dataclass
class BackfillConversationsResult:
    """Result of backfill_conversations operation."""

    conversations_created: int
    conversations_updated: int
    accounts_created: int
    pages_processed: int


@dataclass
class BackfillMessagesResult:
    """Result of backfill_messages operation."""

    messages_created: int
    messages_updated: int
    pages_processed: int
    next_cursor: Optional[str] = None


@dataclass
class BackfillResult:
    """Result of full backfill_all operation."""

    conversations_processed: int
    message_jobs_enqueued: int
    conversations_result: Optional[BackfillConversationsResult] = None


@dataclass
class SyncDeltaResult:
    """Result of sync_delta operation."""

    conversations_checked: int
    conversations_created: int
    conversations_skipped: int
    messages_created: int
    messages_updated: int
    errors: int
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SyncState:
    """Represents the current sync state for a provider/identity."""

    provider_id: str
    identity_id: int
    last_sync_at: Optional[datetime]
    last_sync_result: Optional[str] = None


# Default sync interval (in minutes)
DEFAULT_SYNC_INTERVAL_MINUTES = 10


class IngestService:
    """Service for ingesting data from providers.

    Handles backfilling conversations and messages with:
    - Idempotent upserts (no duplicates)
    - Cursor-based pagination
    - "No remote delete" policy enforcement
    - Fan-out job creation for message backfills
    """

    # Job constants
    JOB_QUEUE = "ingest"
    JOB_TYPE_BACKFILL_MESSAGES = "ingest.backfill_messages"
    JOB_TYPE_SYNC_DELTA = "ingest.sync_delta"

    def __init__(
        self,
        db: Session,
        adapter: ProviderAdapter,
        identity_id: int,
        sync_interval_minutes: int = DEFAULT_SYNC_INTERVAL_MINUTES,
    ):
        """Initialize the ingest service.

        Args:
            db: SQLAlchemy database session.
            adapter: Provider adapter for API calls.
            identity_id: Identity ID to use for conversations.
            sync_interval_minutes: Interval between syncs (default 10).
        """
        self.db = db
        self.adapter = adapter
        self.identity_id = identity_id
        self.provider_id = adapter.provider_id
        self.sync_interval_minutes = sync_interval_minutes
        self.job_service = JobService(db)
        self.status_mapper = RemoteStatusMapper()

    async def backfill_conversations(
        self,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> BackfillConversationsResult:
        """Backfill conversations from the provider.

        Fetches all conversations and creates/updates them in the database.
        Creates ExternalAccount records for counterparts as needed.

        Args:
            cursor: Optional starting cursor for pagination.
            limit: Maximum conversations per page.

        Returns:
            BackfillConversationsResult with counts of work done.
        """
        created = 0
        updated = 0
        accounts_created = 0
        pages = 0

        current_cursor = cursor
        has_more = True

        while has_more:
            # Fetch page from provider
            result = await self.adapter.list_conversations(
                cursor=current_cursor,
                limit=limit,
            )

            pages += 1

            for conv in result.items:
                # Get or create external account for counterpart
                account, is_new_account = self._get_or_create_account(conv)
                if is_new_account:
                    accounts_created += 1

                # Get or create conversation
                is_created = self._upsert_conversation(conv, account)
                if is_created:
                    created += 1
                else:
                    updated += 1

            # Commit after each page
            self.db.flush()

            # Continue pagination
            current_cursor = result.next_cursor
            has_more = result.has_more and result.next_cursor is not None

        return BackfillConversationsResult(
            conversations_created=created,
            conversations_updated=updated,
            accounts_created=accounts_created,
            pages_processed=pages,
        )

    async def backfill_messages(
        self,
        conversation_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> BackfillMessagesResult:
        """Backfill messages for a specific conversation.

        Fetches all messages and creates/updates them in the database.
        Preserves original content when remote is deleted.

        Args:
            conversation_id: External conversation ID.
            cursor: Optional starting cursor for pagination.
            limit: Maximum messages per page.

        Returns:
            BackfillMessagesResult with counts of work done.

        Raises:
            ValueError: If conversation not found in database.
        """
        # Find conversation in database
        conversation = self.db.query(Conversation).filter_by(
            provider_id=self.provider_id,
            external_conversation_id=conversation_id,
        ).first()

        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        created = 0
        updated = 0
        pages = 0
        latest_sent_at: Optional[datetime] = None

        current_cursor = cursor
        has_more = True

        while has_more:
            # Fetch page from provider
            result = await self.adapter.list_messages(
                conversation_id=conversation_id,
                cursor=current_cursor,
                limit=limit,
            )

            pages += 1

            for msg in result.items:
                is_created, sent_at = self._upsert_message(msg, conversation)
                if is_created:
                    created += 1
                else:
                    updated += 1

                # Track latest message time
                if sent_at and (latest_sent_at is None or sent_at > latest_sent_at):
                    latest_sent_at = sent_at

            # Commit after each page
            self.db.flush()

            # Continue pagination
            current_cursor = result.next_cursor
            has_more = result.has_more and result.next_cursor is not None

        # Update conversation last_activity_at
        if latest_sent_at:
            if conversation.last_activity_at is None or latest_sent_at > conversation.last_activity_at:
                conversation.last_activity_at = latest_sent_at
                self.db.flush()

        return BackfillMessagesResult(
            messages_created=created,
            messages_updated=updated,
            pages_processed=pages,
            next_cursor=current_cursor,
        )

    async def backfill_all(self) -> BackfillResult:
        """Backfill conversations and enqueue message backfill jobs.

        This is the main fan-out orchestration method:
        1. Backfill all conversations
        2. Enqueue a message backfill job for each conversation

        Returns:
            BackfillResult with summary of work done.
        """
        # First backfill conversations
        conv_result = await self.backfill_conversations()

        # Get all conversations and enqueue message backfill jobs
        conversations = self.db.query(Conversation).filter_by(
            provider_id=self.provider_id,
            identity_id=self.identity_id,
        ).all()

        jobs_enqueued = 0
        for conv in conversations:
            self.enqueue_message_backfill(conv.external_conversation_id)
            jobs_enqueued += 1

        self.db.flush()

        return BackfillResult(
            conversations_processed=len(conversations),
            message_jobs_enqueued=jobs_enqueued,
            conversations_result=conv_result,
        )

    def enqueue_message_backfill(
        self,
        conversation_id: str,
        cursor: Optional[str] = None,
    ) -> Job:
        """Enqueue a job to backfill messages for a conversation.

        Uses the job service for deduplication - identical jobs won't
        be created twice.

        Args:
            conversation_id: External conversation ID.
            cursor: Optional starting cursor.

        Returns:
            The created or existing Job.
        """
        payload = {
            "provider_id": self.provider_id,
            "identity_id": self.identity_id,
            "conversation_id": conversation_id,
        }
        if cursor:
            payload["cursor"] = cursor

        return self.job_service.create_job(
            queue_name=self.JOB_QUEUE,
            job_type=self.JOB_TYPE_BACKFILL_MESSAGES,
            payload=payload,
            dedupe=True,
        )

    # =========================================================================
    # INCREMENTAL SYNC
    # =========================================================================

    async def sync_delta(
        self,
        since_ts: Optional[datetime] = None,
    ) -> SyncDeltaResult:
        """Sync new/updated content since a timestamp.

        This method:
        1. Fetches conversations from provider
        2. For conversations with activity after since_ts, fetches messages
        3. Creates new records and updates visibility for changed content
        4. Records sync completion time

        Args:
            since_ts: Only sync content after this time. If None, uses last sync time.

        Returns:
            SyncDeltaResult with counts of work done.
        """
        # Use last sync time if not provided
        if since_ts is None:
            state = self.get_sync_state()
            if state and state.last_sync_at:
                since_ts = state.last_sync_at
            else:
                # Default to 24 hours ago if never synced
                since_ts = datetime.now(timezone.utc) - timedelta(hours=24)

        conversations_checked = 0
        conversations_created = 0
        conversations_skipped = 0
        messages_created = 0
        messages_updated = 0
        errors = 0

        # Fetch conversations
        current_cursor: Optional[str] = None
        has_more = True

        while has_more:
            result = await self.adapter.list_conversations(
                cursor=current_cursor,
                limit=50,
            )

            for conv in result.items:
                conversations_checked += 1

                # Check if conversation has new activity
                if conv.last_message_at and conv.last_message_at <= since_ts:
                    # No new activity, skip
                    conversations_skipped += 1
                    continue

                # Get or create account and conversation
                account, _ = self._get_or_create_account(conv)
                is_new_conv = self._upsert_conversation(conv, account)
                if is_new_conv:
                    conversations_created += 1
                    self.db.flush()  # Ensure conversation is visible for message sync

                # Fetch messages for this conversation
                try:
                    msg_result = await self._sync_conversation_messages(
                        conv.external_id, since_ts
                    )
                    messages_created += msg_result[0]
                    messages_updated += msg_result[1]
                except Exception:
                    errors += 1
                    # Continue with other conversations

            self.db.flush()

            current_cursor = result.next_cursor
            has_more = result.has_more and result.next_cursor is not None

        # Record sync completion
        completed_at = datetime.now(timezone.utc)
        self._record_sync_completion(completed_at)

        return SyncDeltaResult(
            conversations_checked=conversations_checked,
            conversations_created=conversations_created,
            conversations_skipped=conversations_skipped,
            messages_created=messages_created,
            messages_updated=messages_updated,
            errors=errors,
            completed_at=completed_at,
        )

    async def _sync_conversation_messages(
        self,
        conversation_id: str,
        since_ts: datetime,
    ) -> tuple[int, int]:
        """Sync messages for a single conversation.

        Args:
            conversation_id: External conversation ID.
            since_ts: Only sync messages after this time.

        Returns:
            Tuple of (created_count, updated_count).
        """
        conversation = self.db.query(Conversation).filter_by(
            provider_id=self.provider_id,
            external_conversation_id=conversation_id,
        ).first()

        if not conversation:
            return 0, 0

        created = 0
        updated = 0
        latest_sent_at: Optional[datetime] = None

        current_cursor: Optional[str] = None
        has_more = True

        while has_more:
            result = await self.adapter.list_messages(
                conversation_id=conversation_id,
                cursor=current_cursor,
                limit=100,
            )

            for msg in result.items:
                is_created, sent_at = self._upsert_message(msg, conversation)
                if is_created:
                    created += 1
                else:
                    updated += 1

                if sent_at and (latest_sent_at is None or sent_at > latest_sent_at):
                    latest_sent_at = sent_at

            self.db.flush()

            current_cursor = result.next_cursor
            has_more = result.has_more and result.next_cursor is not None

        # Update conversation last_activity_at
        if latest_sent_at:
            # Normalize for comparison (DB stores naive datetimes)
            sent_naive = latest_sent_at.replace(tzinfo=None) if latest_sent_at.tzinfo else latest_sent_at
            if conversation.last_activity_at is None or sent_naive > conversation.last_activity_at:
                conversation.last_activity_at = sent_naive

        return created, updated

    def get_sync_state(self) -> Optional[SyncState]:
        """Get the current sync state for this provider/identity.

        Returns:
            SyncState if sync has been run, None otherwise.
        """
        # Look for the most recent completed sync job
        job = self.db.query(Job).filter(
            Job.job_type == self.JOB_TYPE_SYNC_DELTA,
            Job.status == "done",
            Job.payload_json["provider_id"].as_string() == self.provider_id,
            Job.payload_json["identity_id"].as_integer() == self.identity_id,
        ).order_by(desc(Job.updated_at)).first()

        if not job:
            return None

        return SyncState(
            provider_id=self.provider_id,
            identity_id=self.identity_id,
            last_sync_at=job.updated_at,
            last_sync_result="done",
        )

    def should_sync(self) -> bool:
        """Check if a sync is due based on the interval.

        Returns:
            True if sync should run, False otherwise.
        """
        state = self.get_sync_state()

        if state is None or state.last_sync_at is None:
            return True

        # Check if enough time has passed
        elapsed = datetime.now(timezone.utc) - state.last_sync_at.replace(tzinfo=timezone.utc)
        return elapsed >= timedelta(minutes=self.sync_interval_minutes)

    def enqueue_sync(
        self,
        run_at: Optional[datetime] = None,
    ) -> Job:
        """Enqueue a sync job.

        Uses job deduplication to prevent duplicate sync jobs.

        Args:
            run_at: Optional scheduled execution time.

        Returns:
            The created or existing Job.
        """
        payload = {
            "provider_id": self.provider_id,
            "identity_id": self.identity_id,
        }

        return self.job_service.create_job(
            queue_name=self.JOB_QUEUE,
            job_type=self.JOB_TYPE_SYNC_DELTA,
            payload=payload,
            run_at=run_at,
            dedupe=True,
        )

    def _record_sync_completion(self, completed_at: datetime) -> None:
        """Record that a sync completed successfully.

        Creates or updates a sync job to track the completion time.

        Args:
            completed_at: When the sync completed.
        """
        # Create a completed job to track sync state
        job = self.enqueue_sync()
        job.status = "done"
        job.updated_at = completed_at
        self.db.flush()

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _get_or_create_account(
        self,
        conv: ProviderConversation,
    ) -> tuple[ExternalAccount, bool]:
        """Get or create an ExternalAccount for a conversation counterpart.

        Args:
            conv: Provider conversation data.

        Returns:
            Tuple of (account, is_new).
        """
        account = self.db.query(ExternalAccount).filter_by(
            provider_id=self.provider_id,
            external_username=conv.counterpart_username,
        ).first()

        if account:
            # Update external_user_id if we have it now
            if conv.counterpart_id and not account.external_user_id:
                account.external_user_id = conv.counterpart_id
            return account, False

        # Create new account
        account = ExternalAccount(
            provider_id=self.provider_id,
            external_username=conv.counterpart_username,
            external_user_id=conv.counterpart_id,
            remote_status="unknown",
        )
        self.db.add(account)
        self.db.flush()

        return account, True

    def _upsert_conversation(
        self,
        conv: ProviderConversation,
        account: ExternalAccount,
    ) -> bool:
        """Upsert a conversation record.

        Args:
            conv: Provider conversation data.
            account: ExternalAccount for counterpart.

        Returns:
            True if created, False if updated.
        """
        existing = self.db.query(Conversation).filter_by(
            provider_id=self.provider_id,
            external_conversation_id=conv.external_id,
        ).first()

        if existing:
            # Update fields
            if conv.last_message_at:
                # Normalize for comparison (DB stores naive datetimes)
                conv_time = conv.last_message_at.replace(tzinfo=None) if conv.last_message_at.tzinfo else conv.last_message_at
                if existing.last_activity_at is None or conv_time > existing.last_activity_at:
                    existing.last_activity_at = conv_time
            return False

        # Create new conversation
        last_activity = None
        if conv.last_message_at:
            last_activity = conv.last_message_at.replace(tzinfo=None) if conv.last_message_at.tzinfo else conv.last_message_at

        conversation = Conversation(
            provider_id=self.provider_id,
            external_conversation_id=conv.external_id,
            counterpart_account_id=account.id,
            identity_id=self.identity_id,
            last_activity_at=last_activity,
        )
        self.db.add(conversation)

        return True

    def _upsert_message(
        self,
        msg: ProviderMessage,
        conversation: Conversation,
    ) -> tuple[bool, Optional[datetime]]:
        """Upsert a message record.

        Preserves original content when remote is deleted (no remote delete policy).

        Args:
            msg: Provider message data.
            conversation: Local Conversation record.

        Returns:
            Tuple of (is_created, sent_at).
        """
        existing = self.db.query(Message).filter_by(
            provider_id=self.provider_id,
            external_message_id=msg.external_id,
        ).first()

        if existing:
            # Update visibility only (preserve original content)
            new_visibility = self.status_mapper.from_provider_visibility(
                msg.remote_visibility
            )

            try:
                current_visibility = ContentVisibility(existing.remote_visibility)
            except ValueError:
                current_visibility = ContentVisibility.UNKNOWN

            if self.status_mapper.should_update_visibility(current_visibility, new_visibility):
                existing.remote_visibility = new_visibility.value
                if new_visibility != ContentVisibility.VISIBLE:
                    existing.remote_deleted_at = datetime.now(timezone.utc)

            return False, existing.sent_at

        # Create new message
        direction = msg.direction.value if hasattr(msg.direction, 'value') else str(msg.direction)
        visibility = self.status_mapper.from_provider_visibility(msg.remote_visibility)

        # Normalize datetime (DB stores naive datetimes, sent_at is NOT NULL)
        if msg.sent_at:
            sent_at_naive = msg.sent_at.replace(tzinfo=None) if msg.sent_at.tzinfo else msg.sent_at
        else:
            # Use current time as fallback when provider doesn't provide timestamp
            sent_at_naive = datetime.now()

        message = Message(
            provider_id=self.provider_id,
            external_message_id=msg.external_id,
            conversation_id=conversation.id,
            direction=direction,
            sent_at=sent_at_naive,
            body_text=msg.body_text,
            remote_visibility=visibility.value,
            identity_id=self.identity_id if direction == "out" else None,
        )
        self.db.add(message)

        return True, sent_at_naive


# Export public interface
__all__ = [
    "IngestService",
    "BackfillConversationsResult",
    "BackfillMessagesResult",
    "BackfillResult",
]
