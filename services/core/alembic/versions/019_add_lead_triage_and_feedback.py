"""Add lead triage: priority, expiry, needs-review triage markers, calibration reports.

Adds:
- lead_posts.priority (high/medium/low) and lead_posts.compatibility_score
- 'expired' to lead_posts.status
- index on lead_posts (status, priority, created_at) for the ranked list
- scout_watch_posts.dismissed_at / triaged_at (+ index) for the needs-review queue
- calibration_reports: weekly computed precision snapshots

Revision ID: 019
Revises: 018
"""

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL requires ALTER TABLE to modify ENUM columns
    op.execute(
        "ALTER TABLE lead_posts MODIFY COLUMN status "
        "ENUM('new', 'saved', 'ignored', 'contact_queued', 'contacted', 'expired') "
        "NOT NULL DEFAULT 'new'"
    )
    op.add_column(
        "lead_posts",
        sa.Column(
            "priority",
            sa.Enum("high", "medium", "low", name="lead_priority_enum"),
            nullable=True,
        ),
    )
    op.add_column(
        "lead_posts",
        sa.Column("compatibility_score", sa.Float, nullable=True),
    )
    op.create_index(
        "idx_lead_status_priority_created",
        "lead_posts",
        ["status", "priority", "created_at"],
    )

    op.add_column(
        "scout_watch_posts",
        sa.Column("dismissed_at", sa.DateTime, nullable=True),
    )
    op.add_column(
        "scout_watch_posts",
        sa.Column("triaged_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_scout_post_review_queue",
        "scout_watch_posts",
        ["analysis_recommendation", "dismissed_at", "first_seen_at"],
    )

    op.create_table(
        "calibration_reports",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("period_start", sa.DateTime, nullable=False),
        sa.Column("period_end", sa.DateTime, nullable=False),
        sa.Column("report_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "idx_calibration_period_end", "calibration_reports", ["period_end"]
    )


def downgrade() -> None:
    op.drop_index("idx_calibration_period_end", table_name="calibration_reports")
    op.drop_table("calibration_reports")

    op.drop_index("idx_scout_post_review_queue", table_name="scout_watch_posts")
    op.drop_column("scout_watch_posts", "triaged_at")
    op.drop_column("scout_watch_posts", "dismissed_at")

    op.drop_index("idx_lead_status_priority_created", table_name="lead_posts")
    op.drop_column("lead_posts", "compatibility_score")
    op.drop_column("lead_posts", "priority")

    op.execute("UPDATE lead_posts SET status = 'new' WHERE status = 'expired'")
    op.execute(
        "ALTER TABLE lead_posts MODIFY COLUMN status "
        "ENUM('new', 'saved', 'ignored', 'contact_queued', 'contacted') "
        "NOT NULL DEFAULT 'new'"
    )
