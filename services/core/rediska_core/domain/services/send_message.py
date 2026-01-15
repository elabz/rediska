"""Send message service for manual message sending.

This service handles:
1. Validation of send requests (counterpart status, body validation)
2. Job creation for asynchronous message sending
3. At-most-once delivery semantics
4. Message state management

Usage:
    service = SendMessageService(db=session)

    # Validate and enqueue a message for sending
    result = service.enqueue_send(
        conversation_id=123,
        body_text="Hello!",
    )
    print(f"Job ID: {result.job_id}, Message ID: {result.message_id}")

    # After successful send, mark as sent
    service.mark_message_sent(message_id, external_id="t4_abc")

    # After ambiguous failure, mark appropriately
    service.handle_send_failure(job_id, message_id, error, is_ambiguous=True)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Job,
    Message,
    ProviderCredential,
)
from rediska_core.domain.services.jobs import JobService


# =============================================================================
# EXCEPTIONS
# =============================================================================


class SendMessageError(Exception):
    """Base exception for send message operations."""
    pass


class ConversationNotFoundError(SendMessageError):
    """Raised when conversation does not exist."""
    pass


class CounterpartStatusError(SendMessageError):
    """Raised when counterpart status prevents sending."""
    pass


class EmptyMessageError(SendMessageError):
    """Raised when message body is empty."""
    pass


class MissingCredentialsError(SendMessageError):
    """Raised when identity credentials are missing."""
    pass


class MessageNotFoundError(SendMessageError):
    """Raised when message does not exist."""
    pass


class MessageNotPendingError(SendMessageError):
    """Raised when message is not in pending state."""
    pass


class MessageAccessDeniedError(SendMessageError):
    """Raised when user doesn't own the message."""
    pass


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class SendValidationResult:
    """Result of send validation."""

    conversation_id: int
    identity_id: int
    counterpart_account_id: int
    provider_id: str


@dataclass
class EnqueueResult:
    """Result of enqueuing a message for sending."""

    job_id: int
    message_id: int
    status: str = "queued"


@dataclass
class RetryResult:
    """Result of retrying a failed send."""

    job_id: int
    message_id: int
    status: str = "queued"


# =============================================================================
# CONSTANTS
# =============================================================================


# Counterpart statuses that block sending
BLOCKED_COUNTERPART_STATUSES = {"deleted", "suspended"}

# Job queue for send operations
SEND_JOB_QUEUE = "messages"

# Job type for manual sends
SEND_JOB_TYPE = "message.send_manual"


# =============================================================================
# SERVICE
# =============================================================================


class SendMessageService:
    """Service for sending messages through providers.

    Implements at-most-once delivery semantics:
    - Message is created with 'unknown' visibility before sending
    - On success, visibility is updated to 'visible'
    - On ambiguous failure (timeout, etc.), job is marked failed without retry
    - On clear failure (rate limit, etc.), job can retry
    - User can manually retry ambiguous failures

    This ensures messages are never accidentally sent twice.
    """

    def __init__(self, db: Session):
        """Initialize the send message service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db
        self.job_service = JobService(db)

    def validate_send(
        self,
        conversation_id: int,
        body_text: str,
    ) -> SendValidationResult:
        """Validate that a message can be sent to a conversation.

        Args:
            conversation_id: The conversation ID.
            body_text: The message body text.

        Returns:
            SendValidationResult with conversation details.

        Raises:
            ConversationNotFoundError: If conversation doesn't exist.
            CounterpartStatusError: If counterpart is deleted/suspended.
            EmptyMessageError: If message body is empty.
        """
        # Validate body is not empty
        if not body_text or not body_text.strip():
            raise EmptyMessageError("Message body cannot be empty")

        # Get conversation with counterpart
        conversation = (
            self.db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )

        if not conversation:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found"
            )

        # Get counterpart account
        counterpart = (
            self.db.query(ExternalAccount)
            .filter(ExternalAccount.id == conversation.counterpart_account_id)
            .first()
        )

        if not counterpart:
            raise ConversationNotFoundError(
                f"Counterpart account not found for conversation {conversation_id}"
            )

        # Check counterpart status
        if counterpart.remote_status in BLOCKED_COUNTERPART_STATUSES:
            raise CounterpartStatusError(
                f"Cannot send to counterpart with status '{counterpart.remote_status}'"
            )

        return SendValidationResult(
            conversation_id=conversation.id,
            identity_id=conversation.identity_id,
            counterpart_account_id=counterpart.id,
            provider_id=conversation.provider_id,
        )

    def enqueue_send(
        self,
        conversation_id: int,
        body_text: str,
        attachment_ids: Optional[list[int]] = None,
    ) -> EnqueueResult:
        """Validate and enqueue a message for sending.

        Creates a pending message record and a job to send it.
        The message is created with 'unknown' visibility until
        sending is confirmed.

        Args:
            conversation_id: The conversation ID.
            body_text: The message body text.
            attachment_ids: Optional list of attachment IDs to include.

        Returns:
            EnqueueResult with job and message IDs.

        Raises:
            ConversationNotFoundError: If conversation doesn't exist.
            CounterpartStatusError: If counterpart is deleted/suspended.
            EmptyMessageError: If message body is empty.
            MissingCredentialsError: If identity has no credentials.
        """
        # Validate the send request
        validation = self.validate_send(conversation_id, body_text)

        # Check identity has credentials
        credentials = (
            self.db.query(ProviderCredential)
            .filter(
                ProviderCredential.provider_id == validation.provider_id,
                ProviderCredential.identity_id == validation.identity_id,
            )
            .first()
        )

        if not credentials:
            raise MissingCredentialsError(
                f"No credentials found for identity {validation.identity_id}"
            )

        # Create pending message
        message = Message(
            provider_id=validation.provider_id,
            conversation_id=conversation_id,
            identity_id=validation.identity_id,
            direction="out",
            sent_at=datetime.now(timezone.utc),
            body_text=body_text.strip(),
            remote_visibility="unknown",  # Unknown until confirmed sent
        )
        self.db.add(message)
        self.db.flush()

        # Create job to send the message
        # We set max_attempts > 1 to allow retries for clear failures (rate limit).
        # Ambiguous failures are handled specially in handle_send_failure to
        # immediately mark as failed (at-most-once semantics).
        job = self.job_service.create_job(
            queue_name=SEND_JOB_QUEUE,
            job_type=SEND_JOB_TYPE,
            payload={
                "message_id": message.id,
                "conversation_id": conversation_id,
                "identity_id": validation.identity_id,
                "provider_id": validation.provider_id,
                "body_text": body_text.strip(),
                "attachment_ids": attachment_ids or [],
            },
            max_attempts=3,  # Allow retries for clear failures; ambiguous failures bypass this
            dedupe=True,
        )

        return EnqueueResult(
            job_id=job.id,
            message_id=message.id,
            status="queued",
        )

    def mark_message_sent(
        self,
        message_id: int,
        external_message_id: str,
    ) -> None:
        """Mark a message as successfully sent.

        Updates the message visibility to 'visible' and records
        the external message ID from the provider.

        Also marks the associated job as 'done'.

        Args:
            message_id: The local message ID.
            external_message_id: The provider's message ID.
        """
        self.db.query(Message).filter(Message.id == message_id).update(
            {
                Message.external_message_id: external_message_id,
                Message.remote_visibility: "visible",
            },
            synchronize_session=False,
        )

        # Mark associated job as done
        jobs = (
            self.db.query(Job)
            .filter(
                Job.job_type == SEND_JOB_TYPE,
                Job.queue_name == SEND_JOB_QUEUE,
                Job.status.in_(["queued", "running"]),
            )
            .all()
        )

        for job in jobs:
            if job.payload_json and job.payload_json.get("message_id") == message_id:
                job.status = "done"
                break

        self.db.flush()

    def mark_message_failed(
        self,
        message_id: int,
        error: str,
        is_ambiguous: bool = True,
    ) -> None:
        """Mark a message send as failed.

        For ambiguous failures, visibility remains 'unknown'.
        For clear failures, we may want to delete the message.

        Args:
            message_id: The local message ID.
            error: The error message.
            is_ambiguous: Whether failure is ambiguous (unknown if sent).
        """
        if is_ambiguous:
            # Keep visibility as 'unknown' - user must reconcile
            pass
        else:
            # Clear failure - message was definitely not sent
            # Keep the message but could mark differently if needed
            pass

    def handle_send_failure(
        self,
        job_id: int,
        message_id: int,
        error: str,
        is_ambiguous: bool = True,
    ) -> None:
        """Handle a send failure with proper at-most-once semantics.

        Ambiguous failures (timeout, network error) are marked as
        failed with no automatic retry. Clear failures (rate limit,
        validation error) can retry.

        Args:
            job_id: The job ID.
            message_id: The message ID.
            error: The error message.
            is_ambiguous: Whether failure is ambiguous.
        """
        # Update message state
        self.mark_message_failed(message_id, error, is_ambiguous)

        # Update job state
        if is_ambiguous:
            # Ambiguous failure: mark as failed immediately (at-most-once)
            self.db.query(Job).filter(Job.id == job_id).update(
                {
                    Job.status: "failed",
                    Job.last_error: f"AMBIGUOUS: {error}",
                    Job.dedupe_key: None,  # Allow manual retry
                },
                synchronize_session=False,
            )
        else:
            # Clear failure: use normal retry logic
            self.job_service.fail_job(job_id, error)

        self.db.flush()

    def retry_failed_send(
        self,
        message_id: int,
    ) -> Optional[RetryResult]:
        """Manually retry a failed send.

        Creates a new job to retry sending the message.
        Only allowed for messages with 'unknown' visibility.

        Args:
            message_id: The message ID to retry.

        Returns:
            RetryResult with new job ID, or None if retry not allowed.
        """
        message = self.db.query(Message).filter(Message.id == message_id).first()

        if not message:
            return None

        if message.remote_visibility != "unknown":
            return None  # Already sent or known status

        # Get conversation for identity info
        conversation = (
            self.db.query(Conversation)
            .filter(Conversation.id == message.conversation_id)
            .first()
        )

        if not conversation:
            return None

        # Create new job for retry
        job = self.job_service.create_job(
            queue_name=SEND_JOB_QUEUE,
            job_type=SEND_JOB_TYPE,
            payload={
                "message_id": message.id,
                "conversation_id": conversation.id,
                "identity_id": conversation.identity_id,
                "provider_id": conversation.provider_id,
                "body_text": message.body_text,
                "attachment_ids": [],
                "is_retry": True,
            },
            max_attempts=1,  # Still at-most-once
            dedupe=False,  # Allow retry of same message
        )

        return RetryResult(
            job_id=job.id,
            message_id=message.id,
            status="queued",
        )

    def get_pending_messages(
        self,
        conversation_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[Message]:
        """Get messages with unknown send status.

        These are messages that were queued but we don't know
        if they were successfully sent.

        Args:
            conversation_id: Optional filter by conversation.
            limit: Maximum number to return.

        Returns:
            List of messages with unknown visibility.
        """
        query = self.db.query(Message).filter(
            Message.direction == "out",
            Message.remote_visibility == "unknown",
        )

        if conversation_id:
            query = query.filter(Message.conversation_id == conversation_id)

        return query.order_by(Message.sent_at.desc()).limit(limit).all()

    def delete_pending_message(
        self,
        message_id: int,
    ) -> dict:
        """Delete a pending (unsent) message.

        Soft-deletes the message by setting deleted_at timestamp.
        Attempts to cancel the associated Celery job if still queued.

        Args:
            message_id: The message ID to delete.

        Returns:
            Dict with deletion details:
            {
                "message_id": int,
                "job_id": Optional[int],
                "job_cancelled": bool,
                "reason": str (if job wasn't cancelled)
            }

        Raises:
            MessageNotFoundError: If message doesn't exist.
            MessageNotPendingError: If message is not pending (already sent or incoming).
            MessageAccessDeniedError: If message doesn't belong to an active identity.
        """
        # Get message with conversation
        message = (
            self.db.query(Message)
            .filter(Message.id == message_id)
            .first()
        )

        if not message:
            raise MessageNotFoundError(f"Message {message_id} not found")

        # Check if already deleted
        if message.deleted_at is not None:
            raise MessageNotFoundError(f"Message {message_id} already deleted")

        # Check that it's an outgoing message
        if message.direction != "out":
            raise MessageNotPendingError(
                "Only pending outgoing messages can be deleted"
            )

        # Check that it's still pending (not already sent)
        if message.remote_visibility != "unknown":
            raise MessageNotPendingError(
                f"Message has already been sent (status: {message.remote_visibility})"
            )

        # Verify message belongs to an active identity (authorization)
        from rediska_core.domain.models import Identity

        identity = (
            self.db.query(Identity)
            .filter(
                Identity.id == message.conversation.identity_id,
                Identity.is_active == True,
            )
            .first()
        )

        if not identity:
            raise MessageAccessDeniedError("Access denied")

        # Perform soft delete
        message.deleted_at = datetime.now(timezone.utc)
        self.db.flush()

        # Try to cancel associated job
        job_id = None
        job_cancelled = False
        reason = None

        # Find job by searching for message_id in payload
        jobs = (
            self.db.query(Job)
            .filter(
                Job.job_type == SEND_JOB_TYPE,
                Job.queue_name == SEND_JOB_QUEUE,
            )
            .all()
        )

        for job in jobs:
            if job.payload_json and job.payload_json.get("message_id") == message_id:
                job_id = job.id
                # Check job status and attempt cancellation
                if job.status in ["queued", "retrying"]:
                    # Mark job as cancelled to prevent execution
                    job.status = "cancelled"
                    job.last_error = "Cancelled by user"
                    job.dedupe_key = None
                    self.db.flush()
                    job_cancelled = True
                elif job.status == "running":
                    reason = "Job is currently executing"
                else:
                    reason = f"Job already {job.status}"
                break

        return {
            "message_id": message_id,
            "job_id": job_id,
            "job_cancelled": job_cancelled,
            "reason": reason,
        }

    def ensure_cancelled_jobs_consistency(self) -> dict:
        """Ensure consistency between cancelled jobs and deleted messages.

        This method enforces the invariant that if a send_manual job is cancelled,
        its associated message must also be marked as deleted to prevent accidental
        resending.

        Returns:
            Dict with consistency check results:
            {
                "checked_jobs": int,
                "fixed_messages": int,
                "messages_fixed": List[int] (message IDs fixed)
            }
        """
        results = {
            "checked_jobs": 0,
            "fixed_messages": 0,
            "messages_fixed": [],
        }

        # Find all cancelled send_manual jobs
        failed_jobs = (
            self.db.query(Job)
            .filter(
                Job.job_type == SEND_JOB_TYPE,
                Job.queue_name == SEND_JOB_QUEUE,
                Job.status == "cancelled",
            )
            .all()
        )

        for job in failed_jobs:
            results["checked_jobs"] += 1

            if job.payload_json and "message_id" in job.payload_json:
                message_id = job.payload_json["message_id"]
                message = (
                    self.db.query(Message)
                    .filter(Message.id == message_id)
                    .first()
                )

                # If message exists and is not deleted, delete it
                if message and message.deleted_at is None:
                    message.deleted_at = datetime.now(timezone.utc)
                    self.db.flush()
                    results["fixed_messages"] += 1
                    results["messages_fixed"].append(message_id)

        return results


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "SendMessageService",
    "SendValidationResult",
    "EnqueueResult",
    "RetryResult",
    "SendMessageError",
    "ConversationNotFoundError",
    "CounterpartStatusError",
    "EmptyMessageError",
    "MissingCredentialsError",
    "MessageNotFoundError",
    "MessageNotPendingError",
    "MessageAccessDeniedError",
    "SEND_JOB_QUEUE",
    "SEND_JOB_TYPE",
]
