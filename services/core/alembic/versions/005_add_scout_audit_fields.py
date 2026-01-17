"""Add scout audit fields for debugging.

Revision ID: 005
Revises: 004
Create Date: 2026-01-16

Adds:
- search_url to scout_watch_runs for debugging which URL was called
- post_title to scout_watch_posts for display in audit
- analysis_reasoning to scout_watch_posts for agent output

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add search_url to scout_watch_runs
    op.add_column(
        'scout_watch_runs',
        sa.Column('search_url', sa.Text(), nullable=True)
    )

    # Add post_title and analysis_reasoning to scout_watch_posts
    op.add_column(
        'scout_watch_posts',
        sa.Column('post_title', sa.String(500), nullable=True)
    )
    op.add_column(
        'scout_watch_posts',
        sa.Column('post_author', sa.String(100), nullable=True)
    )
    op.add_column(
        'scout_watch_posts',
        sa.Column('analysis_reasoning', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('scout_watch_posts', 'analysis_reasoning')
    op.drop_column('scout_watch_posts', 'post_author')
    op.drop_column('scout_watch_posts', 'post_title')
    op.drop_column('scout_watch_runs', 'search_url')
