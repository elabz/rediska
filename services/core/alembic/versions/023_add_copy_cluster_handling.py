"""Automatic handling of spam-ring copy clusters.

Adds to copy_clusters:
- avg_char_len: average body length of the cluster's posts (short templates
  must not be treated as rings automatically)
- handled: computed flag — a confirmed ring, or a ring suspect with enough
  authors and long enough posts. Handled clusters are skipped by the scout and
  hidden from the lead list and needs-review queue (never deleted or banned).

Revision ID: 023
Revises: 022
"""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "copy_clusters",
        sa.Column("avg_char_len", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "copy_clusters",
        sa.Column("handled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("idx_copy_cluster_handled", "copy_clusters", ["handled"])


def downgrade() -> None:
    op.drop_index("idx_copy_cluster_handled", table_name="copy_clusters")
    op.drop_column("copy_clusters", "handled")
    op.drop_column("copy_clusters", "avg_char_len")
