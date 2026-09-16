"""Add analysis evaluations, prompt replays, and scout post evaluated_at.

Adds:
- analysis_evaluations: append-only human verdicts on agent decisions
- prompt_replays: candidate prompt replays against labelled cases
- scout_watch_posts.evaluated_at (+ index) for the retention exemption

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_evaluations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "subject_type",
            sa.Enum("lead_analysis", "scout_post", name="evaluation_subject_type_enum"),
            nullable=False,
        ),
        sa.Column("subject_id", sa.BigInteger, nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger,
            sa.ForeignKey("external_accounts.id"),
            nullable=True,
        ),
        sa.Column("dimension", sa.String(64), nullable=True),
        sa.Column(
            "human_verdict",
            sa.Enum("agree", "partial", "disagree", name="human_verdict_enum"),
            nullable=False,
        ),
        sa.Column("corrected_value_json", sa.JSON, nullable=True),
        sa.Column("reason_tags_json", sa.JSON, nullable=False),
        sa.Column("missing_info", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("agent_snapshot_json", sa.JSON, nullable=False),
        sa.Column("prompt_versions_json", sa.JSON, nullable=False),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="user"),
    )
    op.create_index(
        "idx_eval_subject",
        "analysis_evaluations",
        ["subject_type", "subject_id", "dimension", "created_at"],
    )
    op.create_index(
        "idx_eval_dimension_created",
        "analysis_evaluations",
        ["dimension", "created_at"],
    )

    op.create_table(
        "prompt_replays",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("candidate_system_prompt", sa.Text, nullable=False),
        sa.Column("candidate_version", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "completed", "failed", "cancelled",
                name="prompt_replay_status_enum",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("case_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agreed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_no_input", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agreement", sa.Float, nullable=True),
        sa.Column("results_json", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_replay_dimension_created", "prompt_replays", ["dimension", "created_at"]
    )
    op.create_index("idx_replay_status", "prompt_replays", ["status"])

    op.add_column(
        "scout_watch_posts",
        sa.Column("evaluated_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_scout_post_evaluated", "scout_watch_posts", ["evaluated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_scout_post_evaluated", table_name="scout_watch_posts")
    op.drop_column("scout_watch_posts", "evaluated_at")

    op.drop_index("idx_replay_status", table_name="prompt_replays")
    op.drop_index("idx_replay_dimension_created", table_name="prompt_replays")
    op.drop_table("prompt_replays")

    op.drop_index("idx_eval_dimension_created", table_name="analysis_evaluations")
    op.drop_index("idx_eval_subject", table_name="analysis_evaluations")
    op.drop_table("analysis_evaluations")
