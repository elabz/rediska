"""Add subreddit, link_title, link_id to profile_items.

Revision ID: 012
Revises: 011
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profile_items", sa.Column("subreddit", sa.String(128), nullable=True))
    op.add_column("profile_items", sa.Column("link_title", sa.String(512), nullable=True))
    op.add_column("profile_items", sa.Column("link_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("profile_items", "link_id")
    op.drop_column("profile_items", "link_title")
    op.drop_column("profile_items", "subreddit")
