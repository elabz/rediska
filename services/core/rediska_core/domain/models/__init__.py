"""Domain models for Rediska.

This module defines the SQLAlchemy ORM models based on the v0.4 schema.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# =============================================================================
# ENUMS
# =============================================================================


class RemoteStatus(str):
    """Remote account status values."""

    ACTIVE = "active"
    DELETED = "deleted"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class RemoteVisibility(str):
    """Remote content visibility values."""

    VISIBLE = "visible"
    DELETED_BY_AUTHOR = "deleted_by_author"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class AnalysisState(str):
    """Analysis state values."""

    NOT_ANALYZED = "not_analyzed"
    ANALYZED = "analyzed"
    NEEDS_REFRESH = "needs_refresh"


class ContactState(str):
    """Contact state values."""

    NOT_CONTACTED = "not_contacted"
    CONTACTED = "contacted"


class EngagementState(str):
    """Engagement state values."""

    NOT_ENGAGED = "not_engaged"
    ENGAGED = "engaged"


class MessageDirection(str):
    """Message direction values."""

    IN = "in"
    OUT = "out"
    SYSTEM = "system"


class LeadPostStatus(str):
    """Lead post status values."""

    NEW = "new"
    SAVED = "saved"
    IGNORED = "ignored"
    CONTACT_QUEUED = "contact_queued"
    CONTACTED = "contacted"


class ProfileItemType(str):
    """Profile item type values."""

    POST = "post"
    COMMENT = "comment"
    IMAGE = "image"


class JobStatus(str):
    """Job status values."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    FAILED = "failed"
    DONE = "done"


class AnalysisStatus(str):
    """Lead analysis status values."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RecommendationStatus(str):
    """Lead suitability recommendation values."""

    SUITABLE = "suitable"
    NOT_RECOMMENDED = "not_recommended"
    NEEDS_REVIEW = "needs_review"


class DimensionStatus(str):
    """Individual analysis dimension status values."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditActor(str):
    """Audit actor values."""

    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"


class AuditResult(str):
    """Audit result values."""

    OK = "ok"
    ERROR = "error"


class StorageBackend(str):
    """Storage backend values."""

    FS = "fs"


class LeadSource(str):
    """Lead source values."""

    MANUAL = "manual"
    SCOUT_WATCH = "scout_watch"


class ScoutRunStatus(str):
    """Scout watch run status values."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScoutPostStatus(str):
    """Scout watch post analysis status values."""

    PENDING = "pending"
    ANALYZED = "analyzed"
    SKIPPED = "skipped"
    FAILED = "failed"


# =============================================================================
# MODELS
# =============================================================================


class Provider(Base):
    """Registered providers (reddit, etc.)."""

    __tablename__ = "providers"

    provider_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # Relationships
    identities: Mapped[list["Identity"]] = relationship(back_populates="provider")
    external_accounts: Mapped[list["ExternalAccount"]] = relationship(
        back_populates="provider"
    )
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="provider")
    messages: Mapped[list["Message"]] = relationship(back_populates="provider")
    lead_posts: Mapped[list["LeadPost"]] = relationship(back_populates="provider")
    credentials: Mapped[list["ProviderCredential"]] = relationship(
        back_populates="provider"
    )
    do_not_contact: Mapped[list["DoNotContact"]] = relationship(back_populates="provider")


class LocalUser(Base):
    """Single-user auth (local-only)."""

    __tablename__ = "local_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Session(Base):
    """Server-side session store."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("local_users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    data_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["LocalUser"] = relationship(back_populates="sessions")


class Identity(Base):
    """User identities per provider.

    Represents the personas/accounts the user can use to interact through a provider
    (e.g., different Reddit accounts).
    """

    __tablename__ = "identities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )

    # Provider-specific identifier (e.g., Reddit username)
    external_username: Mapped[str] = mapped_column(String(128), nullable=False)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Display name for UI (user-defined, can differ from external_username)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Voice/persona configuration for LLM-generated content
    # { "system_prompt": "...", "tone": "...", "style": "..." }
    voice_config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Default identity for this provider (exactly one per provider must be true)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_username", name="uq_identity"),
        Index("idx_identity_provider", "provider_id"),
        Index("idx_identity_default", "provider_id", "is_default"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="identities")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="identity")
    messages: Mapped[list["Message"]] = relationship(back_populates="identity")
    credentials: Mapped[list["ProviderCredential"]] = relationship(
        back_populates="identity"
    )


class ExternalAccount(Base):
    """Counterpart identities on providers (people we interact with)."""

    __tablename__ = "external_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    external_user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    external_username: Mapped[str] = mapped_column(String(128), nullable=False)

    remote_status: Mapped[str] = mapped_column(
        Enum("active", "deleted", "suspended", "unknown", name="remote_status_enum"),
        nullable=False,
        default="unknown",
    )
    remote_status_last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    analysis_state: Mapped[str] = mapped_column(
        Enum("not_analyzed", "analyzed", "needs_refresh", name="analysis_state_enum"),
        nullable=False,
        default="not_analyzed",
    )
    contact_state: Mapped[str] = mapped_column(
        Enum("not_contacted", "contacted", name="contact_state_enum"),
        nullable=False,
        default="not_contacted",
    )
    engagement_state: Mapped[str] = mapped_column(
        Enum("not_engaged", "engaged", name="engagement_state_enum"),
        nullable=False,
        default="not_engaged",
    )

    first_analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_inbound_after_contact_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_username", name="uq_account"),
        Index("idx_remote_status", "provider_id", "remote_status"),
        Index("idx_states", "analysis_state", "contact_state", "engagement_state"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="external_accounts")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="counterpart_account"
    )
    lead_posts: Mapped[list["LeadPost"]] = relationship(back_populates="author_account")
    profile_snapshots: Mapped[list["ProfileSnapshot"]] = relationship(
        back_populates="account"
    )
    profile_items: Mapped[list["ProfileItem"]] = relationship(back_populates="account")


class Conversation(Base):
    """Conversations/threads (identity-aware)."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    external_conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    counterpart_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=False
    )

    # Identity used for this conversation (required)
    identity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("identities.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider_id", "external_conversation_id", name="uq_conv"),
        Index("idx_conv_counterpart", "counterpart_account_id"),
        Index("idx_conv_identity", "identity_id"),
        Index("idx_conv_last_activity", "last_activity_at"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="conversations")
    identity: Mapped["Identity"] = relationship(back_populates="conversations")
    counterpart_account: Mapped["ExternalAccount"] = relationship(
        back_populates="conversations"
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    """Messages within conversations (identity tracked for outgoing)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    external_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False
    )

    # Identity that sent this message (NULL for incoming messages)
    identity_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("identities.id"), nullable=True
    )

    direction: Mapped[str] = mapped_column(
        Enum("in", "out", "system", name="message_direction_enum"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    remote_visibility: Mapped[str] = mapped_column(
        Enum(
            "visible", "deleted_by_author", "removed", "unknown",
            name="remote_visibility_enum"
        ),
        nullable=False,
        default="unknown",
    )
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_message_id", name="uq_msg_ext"),
        Index("idx_msg_conv_time", "conversation_id", "sent_at"),
        Index("idx_msg_identity", "identity_id"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="messages")
    identity: Mapped[Optional["Identity"]] = relationship(back_populates="messages")
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message")


class Attachment(Base):
    """Attachments (local filesystem)."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=True
    )

    storage_backend: Mapped[str] = mapped_column(
        Enum("fs", name="storage_backend_enum"), nullable=False, default="fs"
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    width_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    remote_visibility: Mapped[str] = mapped_column(
        Enum(
            "visible", "deleted_by_author", "removed", "unknown",
            name="attachment_visibility_enum"
        ),
        nullable=False,
        default="unknown",
    )
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_attach_msg", "message_id"),
        Index("idx_attach_sha", "sha256"),
    )

    # Relationships
    message: Mapped[Optional["Message"]] = relationship(back_populates="attachments")
    profile_items: Mapped[list["ProfileItem"]] = relationship(back_populates="attachment")


class LeadPost(Base):
    """Saved posts/leads from provider locations."""

    __tablename__ = "lead_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )

    source_location: Mapped[str] = mapped_column(String(128), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    post_url: Mapped[str] = mapped_column(String(512), nullable=False)

    author_account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=True
    )

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "new", "saved", "ignored", "contact_queued", "contacted",
            name="lead_post_status_enum"
        ),
        nullable=False,
        default="new",
    )

    remote_visibility: Mapped[str] = mapped_column(
        Enum(
            "visible", "deleted_by_author", "removed", "unknown",
            name="lead_visibility_enum"
        ),
        nullable=False,
        default="unknown",
    )
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Multi-agent analysis fields
    latest_analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("lead_analyses.id", ondelete="SET NULL"), nullable=True
    )
    analysis_recommendation: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    analysis_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    # User summaries (persisted for reuse in subsequent analysis runs)
    user_interests_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Summary of user interests from their posts"
    )
    user_character_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Summary of user character from their comments"
    )

    # Lead source tracking (manual vs scout_watch)
    lead_source: Mapped[str] = mapped_column(
        Enum("manual", "scout_watch", name="lead_source_enum"),
        nullable=False,
        default="manual",
    )
    scout_watch_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scout_watches.id"), nullable=True
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_post_id", name="uq_lead"),
        Index("idx_source", "provider_id", "source_location"),
        Index("idx_author", "author_account_id"),
        Index("idx_status", "status"),
        Index("idx_lead_source", "lead_source"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="lead_posts")
    author_account: Mapped[Optional["ExternalAccount"]] = relationship(
        back_populates="lead_posts"
    )
    latest_analysis: Mapped[Optional["LeadAnalysis"]] = relationship(
        uselist=False,
        foreign_keys=[latest_analysis_id],
        lazy="selectin",
        viewonly=True,
    )
    scout_watch: Mapped[Optional["ScoutWatch"]] = relationship(
        back_populates="lead_posts",
        foreign_keys=[scout_watch_id],
    )


class ProfileSnapshot(Base):
    """Profile snapshots (LLM outputs + extracted structured signals)."""

    __tablename__ = "profile_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signals_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    risk_flags_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    model_info_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (Index("idx_snap_account_fetched", "account_id", "fetched_at"),)

    # Relationships
    account: Mapped["ExternalAccount"] = relationship(back_populates="profile_snapshots")


class ProfileItem(Base):
    """Public content items for accounts (posts/comments/images)."""

    __tablename__ = "profile_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=False
    )

    item_type: Mapped[str] = mapped_column(
        Enum("post", "comment", "image", name="profile_item_type_enum"), nullable=False
    )
    external_item_id: Mapped[str] = mapped_column(String(128), nullable=False)

    item_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("attachments.id"), nullable=True
    )

    remote_visibility: Mapped[str] = mapped_column(
        Enum(
            "visible", "deleted_by_author", "removed", "unknown",
            name="profile_item_visibility_enum"
        ),
        nullable=False,
        default="unknown",
    )
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("account_id", "item_type", "external_item_id", name="uq_item"),
        Index("idx_item_type", "account_id", "item_type"),
    )

    # Relationships
    account: Mapped["ExternalAccount"] = relationship(back_populates="profile_items")
    attachment: Mapped[Optional["Attachment"]] = relationship(
        back_populates="profile_items"
    )


class ProviderCredential(Base):
    """OAuth/provider credentials (encrypted secrets) - linked to identities."""

    __tablename__ = "provider_credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    # NULL for app-level credentials, set for identity-specific
    identity_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("identities.id"), nullable=True
    )
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider_id", "identity_id", "credential_type", name="uq_cred"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="credentials")
    identity: Mapped[Optional["Identity"]] = relationship(back_populates="credentials")


class DoNotContact(Base):
    """Do-not-contact list (local-only safety)."""

    __tablename__ = "do_not_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    external_username: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_username", name="uq_dnc"),
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(back_populates="do_not_contact")


class AuditLog(Base):
    """Append-only audit log (identity-aware)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    actor: Mapped[str] = mapped_column(
        Enum("user", "system", "agent", name="audit_actor_enum"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)

    provider_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Track which identity was used for the action
    identity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    request_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    response_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    result: Mapped[str] = mapped_column(
        Enum("ok", "error", name="audit_result_enum"), nullable=False
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_audit_ts", "ts"),
        Index("idx_audit_action", "action_type"),
        Index("idx_audit_provider", "provider_id"),
        Index("idx_audit_identity", "identity_id"),
    )


class Job(Base):
    """Job ledger to enforce idempotency/dedupe across Celery retries."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("queued", "running", "retrying", "failed", "done", "cancelled", name="job_status_enum"),
        nullable=False,
        default="queued",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    dedupe_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (Index("idx_jobs_status", "status", "next_run_at"),)


# =============================================================================
# Multi-Agent Analysis Models
# =============================================================================


class AgentPrompt(Base):
    """Versioned prompts for analysis agents."""

    __tablename__ = "agent_prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_dimension", "version", name="uq_agent_prompt_version"),
        Index("idx_agent_prompt_active", "agent_dimension", "is_active"),
    )


class LeadAnalysis(Base):
    """Multi-dimensional analysis results for leads."""

    __tablename__ = "lead_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lead_posts.id"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "running", "completed", "failed",
            name="analysis_status_enum"
        ),
        nullable=False,
        default="pending",
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Dimension results (JSON storage)
    demographics_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    preferences_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    relationship_goals_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    risk_flags_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    sexual_preferences_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Meta-analysis result
    meta_analysis_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    final_recommendation: Mapped[Optional[str]] = mapped_column(
        Enum(
            "suitable", "not_recommended", "needs_review",
            name="recommendation_enum"
        ),
        nullable=True,
    )
    recommendation_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Metadata
    prompt_versions_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_info_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_analysis_lead_completed", "lead_id", "completed_at"),
        Index("idx_analysis_status", "status"),
        Index("idx_analysis_recommendation", "final_recommendation"),
    )

    # Relationships
    lead_post: Mapped["LeadPost"] = relationship(
        foreign_keys=[lead_id],
    )
    account: Mapped["ExternalAccount"] = relationship()
    dimensions: Mapped[list["AnalysisDimension"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
    )


class AnalysisDimension(Base):
    """Individual dimension execution tracking for analyses."""

    __tablename__ = "analysis_dimensions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lead_analyses.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "running", "completed", "failed",
            name="dimension_status_enum"
        ),
        nullable=False,
        default="pending",
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    input_data_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_info_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_dimension_analysis", "analysis_id", "dimension"),
        Index("idx_dimension_status", "status"),
    )

    # Relationships
    analysis: Mapped["LeadAnalysis"] = relationship(back_populates="dimensions")


# =============================================================================
# Scout Watch Models
# =============================================================================


class ScoutWatch(Base):
    """Scout watch configurations for automatic subreddit monitoring."""

    __tablename__ = "scout_watches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Provider and location
    provider_id: Mapped[str] = mapped_column(String(32), nullable=False, default="reddit")
    source_location: Mapped[str] = mapped_column(String(255), nullable=False)

    # Search criteria
    search_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_by: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    time_filter: Mapped[str] = mapped_column(String(20), nullable=False, default="day")

    # Identity to use for API calls
    identity_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("identities.id"), nullable=True
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Analysis settings
    auto_analyze: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_confidence: Mapped[float] = mapped_column(nullable=False, default=0.7)

    # Stats (denormalized for performance)
    total_posts_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_leads_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_match_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_scout_watch_active", "is_active", "last_run_at"),
        Index("idx_scout_watch_location", "provider_id", "source_location"),
    )

    # Relationships
    identity: Mapped[Optional["Identity"]] = relationship()
    runs: Mapped[list["ScoutWatchRun"]] = relationship(
        back_populates="watch",
        cascade="all, delete-orphan",
    )
    posts: Mapped[list["ScoutWatchPost"]] = relationship(
        back_populates="watch",
        cascade="all, delete-orphan",
    )
    lead_posts: Mapped[list["LeadPost"]] = relationship(
        back_populates="scout_watch",
        foreign_keys="LeadPost.scout_watch_id",
    )


class ScoutWatchRun(Base):
    """Scout watch run history."""

    __tablename__ = "scout_watch_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scout_watches.id", ondelete="CASCADE"), nullable=False
    )

    # Run details
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Results
    status: Mapped[str] = mapped_column(
        Enum("running", "completed", "failed", name="scout_run_status_enum"),
        nullable=False,
        default="running",
    )
    posts_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    posts_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    posts_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leads_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Debug/audit info
    search_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_scout_watch_runs", "watch_id", "started_at"),
    )

    # Relationships
    watch: Mapped["ScoutWatch"] = relationship(back_populates="runs")
    posts: Mapped[list["ScoutWatchPost"]] = relationship(back_populates="run")


class ScoutWatchPost(Base):
    """Scout watch post tracking for deduplication."""

    __tablename__ = "scout_watch_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scout_watches.id", ondelete="CASCADE"), nullable=False
    )

    # Post identification
    external_post_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Post details for audit display
    post_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    post_author: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Tracking
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scout_watch_runs.id"), nullable=True
    )

    # Profile data (fetched for analysis pipeline)
    profile_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_interests: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="LLM-summarized interests from poster posts"
    )
    user_character: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="LLM-summarized character traits from comments"
    )

    # Analysis result
    analysis_status: Mapped[str] = mapped_column(
        Enum(
            "pending", "fetching_profile", "summarizing", "analyzing",
            "analyzed", "skipped", "failed",
            name="scout_post_status_enum"
        ),
        nullable=False,
        default="pending",
    )
    analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("lead_analyses.id", ondelete="SET NULL"), nullable=True,
        comment="Link to full multi-agent analysis result"
    )
    analysis_recommendation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    analysis_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    analysis_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lead creation
    lead_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("lead_posts.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("watch_id", "external_post_id", name="uq_scout_watch_post"),
        Index("idx_scout_post_pending", "watch_id", "analysis_status"),
    )

    # Relationships
    watch: Mapped["ScoutWatch"] = relationship(back_populates="posts")
    run: Mapped[Optional["ScoutWatchRun"]] = relationship(back_populates="posts")
    lead: Mapped[Optional["LeadPost"]] = relationship()
    analysis: Mapped[Optional["LeadAnalysis"]] = relationship()


# Export all models
__all__ = [
    "Base",
    "Provider",
    "LocalUser",
    "Session",
    "Identity",
    "ExternalAccount",
    "Conversation",
    "Message",
    "Attachment",
    "LeadPost",
    "ProfileSnapshot",
    "ProfileItem",
    "ProviderCredential",
    "DoNotContact",
    "AuditLog",
    "Job",
    "AgentPrompt",
    "LeadAnalysis",
    "AnalysisDimension",
    "ScoutWatch",
    "ScoutWatchRun",
    "ScoutWatchPost",
    # Enums
    "LeadSource",
    "ScoutRunStatus",
    "ScoutPostStatus",
]
