"""Add source discovery: candidates, trials, outbound link sightings, trial watches.

Adds:
- source_candidates: mined/manual candidate locations and external hosts
- source_trials: bounded trial runs of a candidate, with a yield report
- source_link_sightings: outbound URLs seen on link-only posts (metadata only;
  unregistered hosts are never fetched)
- scout_watches.is_trial: a trial is backed by a hidden, never-scheduled watch

Revision ID: 020
Revises: 019
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scout_watches",
        sa.Column("is_trial", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "source_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "provider_id",
            sa.String(32),
            sa.ForeignKey("providers.provider_id"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("location", "external_host", name="source_candidate_kind_enum"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "origin",
            sa.Enum("mined", "manual", name="source_candidate_origin_enum"),
            nullable=False,
            server_default="mined",
        ),
        sa.Column("evidence_json", sa.JSON, nullable=True),
        sa.Column("lift", sa.Float, nullable=True),
        sa.Column("evidence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "new", "trialled", "accepted", "dismissed", "snoozed",
                name="source_candidate_status_enum",
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column("snoozed_until", sa.DateTime, nullable=True),
        sa.Column("location_info_json", sa.JSON, nullable=True),
        sa.Column("location_info_fetched_at", sa.DateTime, nullable=True),
        sa.Column(
            "watch_id",
            sa.BigInteger,
            sa.ForeignKey("scout_watches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("computed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("provider_id", "kind", "name", name="uq_source_candidate"),
    )
    op.create_index(
        "idx_source_candidate_status_lift", "source_candidates", ["status", "lift"]
    )

    op.create_table(
        "source_trials",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "candidate_id",
            sa.BigInteger,
            sa.ForeignKey("source_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "watch_id",
            sa.BigInteger,
            sa.ForeignKey("scout_watches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("scout_watch_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.BigInteger,
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "completed", "failed", "cancelled",
                name="source_trial_status_enum",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("posts_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("yield_json", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_source_trial_candidate", "source_trials", ["candidate_id", "created_at"]
    )
    op.create_index("idx_source_trial_status", "source_trials", ["status"])

    op.create_table(
        "source_link_sightings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("external_post_id", sa.String(128), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("seen_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "provider_id", "external_post_id", name="uq_source_link_sighting"
        ),
    )
    op.create_index(
        "idx_source_link_sighting_host_seen", "source_link_sightings", ["host", "seen_at"]
    )


def downgrade() -> None:
    # Dropping a table drops its indexes; MySQL refuses to drop an index that
    # backs a foreign key on its own, so the tables go directly.
    op.drop_table("source_link_sightings")
    op.drop_table("source_trials")
    op.drop_table("source_candidates")

    op.drop_column("scout_watches", "is_trial")
