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
    EXPIRED = "expired"


class LeadPriority(str):
    """Lead priority tier values (derived from analysis signals)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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

    # Starred/favorite
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

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
    list_memberships: Mapped[list["ConversationListMember"]] = relationship(
        back_populates="conversation"
    )


class ConversationList(Base):
    """User-defined conversation lists (e.g. by topic)."""

    __tablename__ = "conversation_lists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    members: Mapped[list["ConversationListMember"]] = relationship(
        back_populates="conversation_list", cascade="all, delete-orphan"
    )


class ConversationListMember(Base):
    """Junction table: conversation <-> list membership."""

    __tablename__ = "conversation_list_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversation_lists.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("list_id", "conversation_id", name="uq_list_conv"),
        Index("idx_list_member_list", "list_id"),
        Index("idx_list_member_conv", "conversation_id"),
    )

    # Relationships
    conversation_list: Mapped["ConversationList"] = relationship(back_populates="members")
    conversation: Mapped["Conversation"] = relationship(back_populates="list_memberships")


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
            "visible", "deleted_by_author", "removed", "unknown", "send_failed",
            name="remote_visibility_enum"
        ),
        nullable=False,
        default="unknown",
    )
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    send_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Threading: Reddit thread root ID and direct parent message ID
    thread_external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    parent_external_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_message_id", name="uq_msg_ext"),
        Index("idx_msg_conv_time", "conversation_id", "sent_at"),
        Index("idx_msg_identity", "identity_id"),
        Index("idx_msg_thread", "thread_external_id"),
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
            "new", "saved", "ignored", "contact_queued", "contacted", "expired",
            name="lead_post_status_enum"
        ),
        nullable=False,
        default="new",
    )

    # Triage ranking derived in code from analysis signals (lead_priority.py);
    # NULL for leads never analysed or analysed before tiering existed.
    priority: Mapped[Optional[str]] = mapped_column(
        Enum("high", "medium", "low", name="lead_priority_enum"),
        nullable=True,
    )
    compatibility_score: Mapped[Optional[float]] = mapped_column(nullable=True)

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
    # lead_posts <-> lead_analyses is a genuine FK cycle (a lead points at its
    # latest analysis; an analysis points back at its lead). use_alter tells
    # SQLAlchemy to add/drop this constraint separately so metadata.create_all
    # and drop_all can order the tables -- without it, drop_all cannot sort them
    # and test teardown fails.
    latest_analysis_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(
            "lead_analyses.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_lead_posts_latest_analysis_id",
        ),
        nullable=True,
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

    # Status the lead had when its author was banned; restored on lift.
    status_before_ban: Mapped[Optional[str]] = mapped_column(
        Enum(
            "new", "saved", "ignored", "contact_queued", "contacted", "expired",
            name="lead_post_status_before_ban_enum"
        ),
        nullable=True,
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
        Index("idx_lead_status_priority_created", "status", "priority", "created_at"),
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

    subreddit: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    link_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    link_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

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
    # Always stored lower-cased; matched case-insensitively (ban_list.py).
    external_username: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(
        Enum("manual", "copy_ring", "import", name="dnc_source_enum"),
        nullable=False,
        default="manual",
    )
    # Rows are never deleted: lifting keeps history, re-banning reactivates.
    status: Mapped[str] = mapped_column(
        Enum("active", "lifted", name="dnc_status_enum"),
        nullable=False,
        default="active",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Copy cluster the ban came from (post-fingerprint-dedupe); no FK so the
    # ban list stands alone when the copy tables are absent.
    cluster_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    lifted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider_id", "external_username", name="uq_dnc"),
        Index("idx_dnc_status", "provider_id", "status"),
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

    # A trial watch backs a source-discovery trial: hidden from the watch list,
    # never scheduled, and never auto-promotes (source-discovery).
    is_trial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    post_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    dimension_results_json: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="Full dimension results from multi-agent analysis"
    )

    # Lead creation
    lead_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("lead_posts.id"), nullable=True
    )

    # Set when a human evaluation is recorded against this post; evaluated
    # posts (and the run that owns them) are exempt from history retention.
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Needs-review triage: dismissed without a lead, or promoted by a human.
    # Either one takes the post out of the needs-review queue.
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    triaged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("watch_id", "external_post_id", name="uq_scout_watch_post"),
        Index("idx_scout_post_pending", "watch_id", "analysis_status"),
        Index("idx_scout_post_evaluated", "evaluated_at"),
        Index(
            "idx_scout_post_review_queue",
            "analysis_recommendation", "dismissed_at", "first_seen_at",
        ),
    )

    # Relationships
    watch: Mapped["ScoutWatch"] = relationship(back_populates="posts")
    run: Mapped[Optional["ScoutWatchRun"]] = relationship(back_populates="posts")
    lead: Mapped[Optional["LeadPost"]] = relationship()
    analysis: Mapped[Optional["LeadAnalysis"]] = relationship()


# =============================================================================
# Analysis Evaluation Models
# =============================================================================


class EvaluationSubjectType(str):
    """Evaluation subject type values."""

    LEAD_ANALYSIS = "lead_analysis"
    SCOUT_POST = "scout_post"


class HumanVerdict(str):
    """Human verdict values."""

    AGREE = "agree"
    PARTIAL = "partial"
    DISAGREE = "disagree"


class ReplayStatus(str):
    """Prompt replay status values."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisEvaluation(Base):
    """Append-only human verdicts on agent decisions.

    One row per (subject, dimension) evaluation; the latest row for a pair is
    the effective verdict. ``dimension`` is NULL for the final recommendation.
    """

    __tablename__ = "analysis_evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    subject_type: Mapped[str] = mapped_column(
        Enum("lead_analysis", "scout_post", name="evaluation_subject_type_enum"),
        nullable=False,
    )
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("external_accounts.id"), nullable=True
    )
    dimension: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    human_verdict: Mapped[str] = mapped_column(
        Enum("agree", "partial", "disagree", name="human_verdict_enum"),
        nullable=False,
    )
    corrected_value_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason_tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot of what was judged, so later re-analysis / prompt edits do not
    # move the evaluation.
    agent_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    prompt_versions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="user")

    __table_args__ = (
        Index(
            "idx_eval_subject",
            "subject_type",
            "subject_id",
            "dimension",
            "created_at",
        ),
        Index("idx_eval_dimension_created", "dimension", "created_at"),
    )


class PromptReplay(Base):
    """A replay of a candidate prompt against labelled evaluation cases."""

    __tablename__ = "prompt_replays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(nullable=True)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "queued", "running", "completed", "failed", "cancelled",
            name="prompt_replay_status_enum",
        ),
        nullable=False,
        default="queued",
    )
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agreed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_no_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agreement: Mapped[Optional[float]] = mapped_column(nullable=True)
    results_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_replay_dimension_created", "dimension", "created_at"),
        Index("idx_replay_status", "status"),
    )


# =============================================================================
# Calibration Report Models
# =============================================================================


class CalibrationReport(Base):
    """Weekly computed snapshot comparing analysis output with user verdicts."""

    __tablename__ = "calibration_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (Index("idx_calibration_period_end", "period_end"),)


# =============================================================================
# Source Discovery Models
# =============================================================================


class SourceCandidateStatus(str):
    """Source candidate lifecycle values."""

    NEW = "new"
    TRIALLED = "trialled"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"


class SourceTrialStatus(str):
    """Source trial status values."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceCandidate(Base):
    """A location or external host proposed as a new lead source."""

    __tablename__ = "source_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("providers.provider_id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        Enum("location", "external_host", name="source_candidate_kind_enum"),
        nullable=False,
    )
    # Normalized location name (e.g. 'r/foo') or lower-cased host.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(
        Enum("mined", "manual", name="source_candidate_origin_enum"),
        nullable=False,
        default="mined",
    )

    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    lift: Mapped[Optional[float]] = mapped_column(nullable=True)
    # Qualified authors (locations) or distinct URLs (hosts); secondary sort key.
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        Enum(
            "new", "trialled", "accepted", "dismissed", "snoozed",
            name="source_candidate_status_enum",
        ),
        nullable=False,
        default="new",
    )
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    location_info_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    location_info_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # The trial watch while trialling; the real watch once accepted.
    watch_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scout_watches.id", ondelete="SET NULL"), nullable=True
    )

    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "kind", "name", name="uq_source_candidate"),
        Index("idx_source_candidate_status_lift", "status", "lift"),
    )

    watch: Mapped[Optional["ScoutWatch"]] = relationship()
    trials: Mapped[list["SourceTrial"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="SourceTrial.id",
    )


class SourceTrial(Base):
    """A bounded trial run of a location candidate through the scout pipeline."""

    __tablename__ = "source_trials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_candidates.id", ondelete="CASCADE"), nullable=False
    )
    watch_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scout_watches.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scout_watch_runs.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        Enum(
            "queued", "running", "completed", "failed", "cancelled",
            name="source_trial_status_enum",
        ),
        nullable=False,
        default="queued",
    )
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    posts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    yield_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_source_trial_candidate", "candidate_id", "created_at"),
        Index("idx_source_trial_status", "status"),
    )

    candidate: Mapped["SourceCandidate"] = relationship(back_populates="trials")


class SourceLinkSighting(Base):
    """An outbound URL seen on a link-only post (host tally input).

    Metadata only: the URL is recorded, never fetched, unless its host is a
    registered external-listing host (which has its own resolver).
    """

    __tablename__ = "source_link_sightings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "external_post_id", name="uq_source_link_sighting"),
        Index("idx_source_link_sighting_host_seen", "host", "seen_at"),
    )


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
    "AnalysisEvaluation",
    "PromptReplay",
    "CalibrationReport",
    "SourceCandidate",
    "SourceTrial",
    "SourceLinkSighting",
    # Enums
    "SourceCandidateStatus",
    "SourceTrialStatus",
    "EvaluationSubjectType",
    "HumanVerdict",
    "ReplayStatus",
    "LeadSource",
    "LeadPostStatus",
    "LeadPriority",
    "ScoutRunStatus",
    "ScoutPostStatus",
]
