"""Add user summary columns to lead_posts.

Revision ID: 010
Revises: 009
Create Date: 2026-01-18

Adds columns to store user interest and character summaries directly on
lead_posts, so they can be reused when re-running multi-agent analysis.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add summary columns to lead_posts
    op.add_column('lead_posts',
        sa.Column('user_interests_summary', sa.Text(), nullable=True,
                  comment='Summary of user interests from their posts'))
    op.add_column('lead_posts',
        sa.Column('user_character_summary', sa.Text(), nullable=True,
                  comment='Summary of user character from their comments'))


def downgrade() -> None:
    op.drop_column('lead_posts', 'user_character_summary')
    op.drop_column('lead_posts', 'user_interests_summary')
