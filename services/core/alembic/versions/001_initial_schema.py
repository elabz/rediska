"""Initial schema v0.4

Revision ID: 001
Revises:
Create Date: 2026-01-09

Creates all tables for Rediska v0.4 schema:
- providers
- local_users
- sessions
- identities (NEW in v0.4)
- external_accounts
- conversations (with identity_id)
- messages (with identity_id)
- attachments
- lead_posts
- profile_snapshots
- profile_items
- provider_credentials (with identity_id)
- do_not_contact
- audit_log (with identity_id)
- jobs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Providers table
    op.create_table(
        "providers",
        sa.Column("provider_id", sa.String(32), primary_key=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, default=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
    )

    # Seed default providers
    op.execute(
        "INSERT INTO providers (provider_id, display_name, enabled) VALUES ('reddit', 'Reddit', 1)"
    )

    # Local users table
    op.create_table(
        "local_users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )

    # Sessions table
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("data_json", sa.JSON, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["local_users.id"], name="fk_sessions_user"),
    )

    # Identities table (NEW in v0.4)
    op.create_table(
        "identities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("external_username", sa.String(128), nullable=False),
        sa.Column("external_user_id", sa.String(128), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("voice_config_json", sa.JSON, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_identity_provider"
        ),
        sa.UniqueConstraint("provider_id", "external_username", name="uq_identity"),
    )
    op.create_index("idx_identity_default", "identities", ["provider_id", "is_default"])

    # External accounts table
    op.create_table(
        "external_accounts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("external_user_id", sa.String(128), nullable=True),
        sa.Column("external_username", sa.String(128), nullable=False),
        sa.Column(
            "remote_status",
            sa.Enum("active", "deleted", "suspended", "unknown", name="remote_status_enum"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("remote_status_last_seen_at", sa.DateTime, nullable=True),
        sa.Column(
            "analysis_state",
            sa.Enum("not_analyzed", "analyzed", "needs_refresh", name="analysis_state_enum"),
            nullable=False,
            server_default="not_analyzed",
        ),
        sa.Column(
            "contact_state",
            sa.Enum("not_contacted", "contacted", name="contact_state_enum"),
            nullable=False,
            server_default="not_contacted",
        ),
        sa.Column(
            "engagement_state",
            sa.Enum("not_engaged", "engaged", name="engagement_state_enum"),
            nullable=False,
            server_default="not_engaged",
        ),
        sa.Column("first_analyzed_at", sa.DateTime, nullable=True),
        sa.Column("first_contacted_at", sa.DateTime, nullable=True),
        sa.Column("first_inbound_after_contact_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("purged_at", sa.DateTime, nullable=True),
        sa.Column("last_fetched_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_account_provider"
        ),
        sa.UniqueConstraint("provider_id", "external_username", name="uq_account"),
    )
    op.create_index("idx_remote_status", "external_accounts", ["provider_id", "remote_status"])
    op.create_index(
        "idx_states",
        "external_accounts",
        ["analysis_state", "contact_state", "engagement_state"],
    )

    # Conversations table (with identity_id)
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("identity_id", sa.BigInteger, nullable=False),  # NEW in v0.4
        sa.Column("external_conversation_id", sa.String(128), nullable=False),
        sa.Column("counterpart_account_id", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("last_activity_at", sa.DateTime, nullable=True),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_conv_provider"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["identities.id"], name="fk_conv_identity"
        ),
        sa.ForeignKeyConstraint(
            ["counterpart_account_id"], ["external_accounts.id"], name="fk_conv_account"
        ),
        sa.UniqueConstraint("provider_id", "external_conversation_id", name="uq_conv"),
    )
    op.create_index("idx_conv_identity", "conversations", ["identity_id"])
    op.create_index("idx_conv_counterpart", "conversations", ["counterpart_account_id"])
    op.create_index("idx_conv_last_activity", "conversations", ["last_activity_at"])

    # Messages table (with identity_id)
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("identity_id", sa.BigInteger, nullable=True),  # NEW in v0.4 (nullable for incoming)
        sa.Column("external_message_id", sa.String(128), nullable=True),
        sa.Column("conversation_id", sa.BigInteger, nullable=False),
        sa.Column(
            "direction",
            sa.Enum("in", "out", "system", name="message_direction_enum"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime, nullable=False),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column(
            "remote_visibility",
            sa.Enum(
                "visible", "deleted_by_author", "removed", "unknown",
                name="remote_visibility_enum"
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("remote_deleted_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_msg_provider"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["identities.id"], name="fk_msg_identity"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name="fk_msg_conv"
        ),
        sa.UniqueConstraint("provider_id", "external_message_id", name="uq_msg_ext"),
    )
    op.create_index("idx_msg_conv_time", "messages", ["conversation_id", "sent_at"])
    op.create_index("idx_msg_identity", "messages", ["identity_id"])

    # Attachments table
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.BigInteger, nullable=True),
        sa.Column(
            "storage_backend",
            sa.Enum("fs", name="storage_backend_enum"),
            nullable=False,
            server_default="fs",
        ),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("width_px", sa.Integer, nullable=True),
        sa.Column("height_px", sa.Integer, nullable=True),
        sa.Column(
            "remote_visibility",
            sa.Enum(
                "visible", "deleted_by_author", "removed", "unknown",
                name="attachment_visibility_enum"
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("remote_deleted_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_attach_msg"),
    )
    op.create_index("idx_attach_msg", "attachments", ["message_id"])
    op.create_index("idx_attach_sha", "attachments", ["sha256"])

    # Lead posts table
    op.create_table(
        "lead_posts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("source_location", sa.String(128), nullable=False),
        sa.Column("external_post_id", sa.String(128), nullable=False),
        sa.Column("post_url", sa.String(512), nullable=False),
        sa.Column("author_account_id", sa.BigInteger, nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("post_created_at", sa.DateTime, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new", "saved", "ignored", "contact_queued", "contacted",
                name="lead_post_status_enum"
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "remote_visibility",
            sa.Enum(
                "visible", "deleted_by_author", "removed", "unknown",
                name="lead_visibility_enum"
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("remote_deleted_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_lead_provider"
        ),
        sa.ForeignKeyConstraint(
            ["author_account_id"], ["external_accounts.id"], name="fk_lead_author"
        ),
        sa.UniqueConstraint("provider_id", "external_post_id", name="uq_lead"),
    )
    op.create_index("idx_source", "lead_posts", ["provider_id", "source_location"])
    op.create_index("idx_author", "lead_posts", ["author_account_id"])
    op.create_index("idx_status", "lead_posts", ["status"])

    # Profile snapshots table
    op.create_table(
        "profile_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("summary_text", sa.Text, nullable=True),
        sa.Column("signals_json", sa.JSON, nullable=True),
        sa.Column("risk_flags_json", sa.JSON, nullable=True),
        sa.Column("model_info_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["external_accounts.id"], name="fk_snap_account"
        ),
    )
    op.create_index(
        "idx_snap_account_fetched", "profile_snapshots", ["account_id", "fetched_at"]
    )

    # Profile items table
    op.create_table(
        "profile_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, nullable=False),
        sa.Column(
            "item_type",
            sa.Enum("post", "comment", "image", name="profile_item_type_enum"),
            nullable=False,
        ),
        sa.Column("external_item_id", sa.String(128), nullable=False),
        sa.Column("item_created_at", sa.DateTime, nullable=True),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("attachment_id", sa.BigInteger, nullable=True),
        sa.Column(
            "remote_visibility",
            sa.Enum(
                "visible", "deleted_by_author", "removed", "unknown",
                name="profile_item_visibility_enum"
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("remote_deleted_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["external_accounts.id"], name="fk_item_account"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["attachments.id"], name="fk_item_attachment"
        ),
        sa.UniqueConstraint("account_id", "item_type", "external_item_id", name="uq_item"),
    )
    op.create_index("idx_item_type", "profile_items", ["account_id", "item_type"])

    # Provider credentials table (with identity_id)
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("identity_id", sa.BigInteger, nullable=True),  # NEW in v0.4
        sa.Column("credential_type", sa.String(64), nullable=False),
        sa.Column("secret_encrypted", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column("rotated_at", sa.DateTime, nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_cred_provider"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["identities.id"], name="fk_cred_identity"
        ),
        sa.UniqueConstraint("provider_id", "identity_id", "credential_type", name="uq_cred"),
    )
    op.create_index("idx_cred_identity", "provider_credentials", ["identity_id"])

    # Do not contact table
    op.create_table(
        "do_not_contact",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("external_username", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], name="fk_dnc_provider"
        ),
        sa.UniqueConstraint("provider_id", "external_username", name="uq_dnc"),
    )

    # Audit log table (with identity_id)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "actor",
            sa.Enum("user", "system", "agent", name="audit_actor_enum"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(128), nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=True),
        sa.Column("identity_id", sa.BigInteger, nullable=True),  # NEW in v0.4
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.BigInteger, nullable=True),
        sa.Column("request_json", sa.JSON, nullable=True),
        sa.Column("response_json", sa.JSON, nullable=True),
        sa.Column(
            "result",
            sa.Enum("ok", "error", name="audit_result_enum"),
            nullable=False,
        ),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["identities.id"], name="fk_audit_identity"
        ),
    )
    op.create_index("idx_audit_ts", "audit_log", ["ts"])
    op.create_index("idx_audit_action", "audit_log", ["action_type"])
    op.create_index("idx_audit_provider", "audit_log", ["provider_id"])
    op.create_index("idx_audit_identity", "audit_log", ["identity_id"])

    # Jobs table
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("queue_name", sa.String(64), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "retrying", "failed", "done", name="job_status_enum"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="10"),
        sa.Column("next_run_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("dedupe_key", sa.String(256), nullable=True, unique=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("idx_jobs_status", "jobs", ["status", "next_run_at"])


def downgrade() -> None:
    # Drop tables in reverse order of creation (respecting foreign keys)
    op.drop_table("jobs")
    op.drop_table("audit_log")
    op.drop_table("do_not_contact")
    op.drop_table("provider_credentials")
    op.drop_table("profile_items")
    op.drop_table("profile_snapshots")
    op.drop_table("lead_posts")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("external_accounts")
    op.drop_table("identities")
    op.drop_table("sessions")
    op.drop_table("local_users")
    op.drop_table("providers")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS job_status_enum")
    op.execute("DROP TYPE IF EXISTS audit_result_enum")
    op.execute("DROP TYPE IF EXISTS audit_actor_enum")
    op.execute("DROP TYPE IF EXISTS profile_item_visibility_enum")
    op.execute("DROP TYPE IF EXISTS profile_item_type_enum")
    op.execute("DROP TYPE IF EXISTS lead_visibility_enum")
    op.execute("DROP TYPE IF EXISTS lead_post_status_enum")
    op.execute("DROP TYPE IF EXISTS attachment_visibility_enum")
    op.execute("DROP TYPE IF EXISTS storage_backend_enum")
    op.execute("DROP TYPE IF EXISTS remote_visibility_enum")
    op.execute("DROP TYPE IF EXISTS message_direction_enum")
    op.execute("DROP TYPE IF EXISTS engagement_state_enum")
    op.execute("DROP TYPE IF EXISTS contact_state_enum")
    op.execute("DROP TYPE IF EXISTS analysis_state_enum")
    op.execute("DROP TYPE IF EXISTS remote_status_enum")
