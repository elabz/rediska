"""Add scout watch tables and lead source tracking.

Revision ID: 004
Revises: 003
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create scout_watches table
    op.create_table(
        "scout_watches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=False, server_default="reddit"),
        sa.Column("source_location", sa.String(255), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("sort_by", sa.String(20), nullable=False, server_default="new"),
        sa.Column("time_filter", sa.String(20), nullable=False, server_default="day"),
        sa.Column("identity_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("auto_analyze", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("total_posts_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_matches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_leads_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_match_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["identity_id"], ["identities.id"]),
    )
    op.create_index("idx_scout_watch_active", "scout_watches", ["is_active", "last_run_at"])
    op.create_index("idx_scout_watch_location", "scout_watches", ["provider_id", "source_location"])

    # Create scout_watch_runs table
    op.create_table(
        "scout_watch_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("watch_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="scout_run_status_enum"),
            nullable=False,
            server_default="running",
        ),
        sa.Column("posts_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leads_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["watch_id"], ["scout_watches.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_scout_watch_runs", "scout_watch_runs", ["watch_id", "started_at"])

    # Create scout_watch_posts table for deduplication
    op.create_table(
        "scout_watch_posts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("watch_id", sa.BigInteger(), nullable=False),
        sa.Column("external_post_id", sa.String(100), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "analysis_status",
            sa.Enum("pending", "analyzed", "skipped", "failed", name="scout_post_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("analysis_recommendation", sa.String(50), nullable=True),
        sa.Column("analysis_confidence", sa.Float(), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["watch_id"], ["scout_watches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["scout_watch_runs.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead_posts.id"]),
        sa.UniqueConstraint("watch_id", "external_post_id", name="uq_scout_watch_post"),
    )
    op.create_index("idx_scout_post_pending", "scout_watch_posts", ["watch_id", "analysis_status"])

    # Add lead_source and scout_watch_id to lead_posts
    op.add_column(
        "lead_posts",
        sa.Column(
            "lead_source",
            sa.Enum("manual", "scout_watch", name="lead_source_enum"),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "lead_posts",
        sa.Column("scout_watch_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_lead_scout_watch",
        "lead_posts",
        "scout_watches",
        ["scout_watch_id"],
        ["id"],
    )
    op.create_index("idx_lead_source", "lead_posts", ["lead_source"])


def downgrade() -> None:
    # Remove columns from lead_posts
    op.drop_index("idx_lead_source", table_name="lead_posts")
    op.drop_constraint("fk_lead_scout_watch", "lead_posts", type_="foreignkey")
    op.drop_column("lead_posts", "scout_watch_id")
    op.drop_column("lead_posts", "lead_source")

    # Drop tables in reverse order
    op.drop_index("idx_scout_post_pending", table_name="scout_watch_posts")
    op.drop_table("scout_watch_posts")

    op.drop_index("idx_scout_watch_runs", table_name="scout_watch_runs")
    op.drop_table("scout_watch_runs")

    op.drop_index("idx_scout_watch_active", table_name="scout_watches")
    op.drop_index("idx_scout_watch_location", table_name="scout_watches")
    op.drop_table("scout_watches")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS scout_run_status_enum")
    op.execute("DROP TYPE IF EXISTS scout_post_status_enum")
    op.execute("DROP TYPE IF EXISTS lead_source_enum")
