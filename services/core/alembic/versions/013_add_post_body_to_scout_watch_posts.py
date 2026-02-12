"""Add post_body column to scout_watch_posts.

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scout_watch_posts", sa.Column("post_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("scout_watch_posts", "post_body")
