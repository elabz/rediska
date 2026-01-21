"""Add summary fields and analysis link to scout_watch_posts.

Revision ID: 008
Revises: 007
Create Date: 2026-01-18

This migration adds fields to support the integrated analysis pipeline:
- user_interests: LLM-summarized interests from poster's posts
- user_character: LLM-summarized character traits from comments
- profile_fetched_at: When profile data was fetched
- analysis_id: Link to full multi-agent analysis result

Also updates the analysis_status enum to include new pipeline states:
- fetching_profile: Fetching user's posts and comments
- summarizing: Generating interest/character summaries
- analyzing: Running 6-agent multi-agent analysis
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to scout_watch_posts
    op.add_column(
        'scout_watch_posts',
        sa.Column('user_interests', sa.Text(), nullable=True,
                  comment='LLM-summarized interests from poster posts')
    )
    op.add_column(
        'scout_watch_posts',
        sa.Column('user_character', sa.Text(), nullable=True,
                  comment='LLM-summarized character traits from comments')
    )
    op.add_column(
        'scout_watch_posts',
        sa.Column('profile_fetched_at', sa.DateTime(), nullable=True,
                  comment='When profile data was fetched')
    )
    op.add_column(
        'scout_watch_posts',
        sa.Column('analysis_id', sa.BigInteger(), nullable=True,
                  comment='Link to full multi-agent analysis result')
    )

    # Add foreign key for analysis_id -> lead_analyses
    op.create_foreign_key(
        'fk_scout_post_analysis',
        'scout_watch_posts',
        'lead_analyses',
        ['analysis_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Update the analysis_status enum to include new pipeline states
    # For MySQL, we need to modify the column with a new enum definition
    # The new states are: pending, fetching_profile, summarizing, analyzing, completed, failed, skipped
    op.execute("""
        ALTER TABLE scout_watch_posts
        MODIFY COLUMN analysis_status
        ENUM('pending', 'fetching_profile', 'summarizing', 'analyzing', 'analyzed', 'skipped', 'failed')
        NOT NULL DEFAULT 'pending'
    """)


def downgrade() -> None:
    # Revert the enum back to original values
    # First, update any rows with new status values to 'pending'
    op.execute("""
        UPDATE scout_watch_posts
        SET analysis_status = 'pending'
        WHERE analysis_status IN ('fetching_profile', 'summarizing', 'analyzing')
    """)

    # Then modify the column back to original enum
    op.execute("""
        ALTER TABLE scout_watch_posts
        MODIFY COLUMN analysis_status
        ENUM('pending', 'analyzed', 'skipped', 'failed')
        NOT NULL DEFAULT 'pending'
    """)

    # Drop foreign key and column
    op.drop_constraint('fk_scout_post_analysis', 'scout_watch_posts', type_='foreignkey')
    op.drop_column('scout_watch_posts', 'analysis_id')
    op.drop_column('scout_watch_posts', 'profile_fetched_at')
    op.drop_column('scout_watch_posts', 'user_character')
    op.drop_column('scout_watch_posts', 'user_interests')
