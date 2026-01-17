"""Change analysis_recommendation from ENUM to TEXT.

Revision ID: 006
Revises: 005
Create Date: 2026-01-17

The LLM may output various recommendation values beyond the original
"suitable", "not_recommended", "needs_review" enum. This migration
changes the column to TEXT to allow flexible recommendation values.

Also removes the index on this column since TEXT columns cannot be
indexed in MySQL without a prefix length.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First, drop the index on analysis_recommendation
    # MySQL doesn't allow TEXT columns in indexes without a key length
    op.drop_index('idx_lead_analysis_recommendation', table_name='lead_posts')

    # Change analysis_recommendation from ENUM to TEXT
    op.alter_column(
        'lead_posts',
        'analysis_recommendation',
        existing_type=sa.Enum('suitable', 'not_recommended', 'needs_review', name='lead_recommendation_enum'),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Convert TEXT back to ENUM (this may lose data if values don't match)
    op.alter_column(
        'lead_posts',
        'analysis_recommendation',
        existing_type=sa.Text(),
        type_=sa.Enum('suitable', 'not_recommended', 'needs_review', name='lead_recommendation_enum'),
        existing_nullable=True,
    )

    # Re-create the index
    op.create_index('idx_lead_analysis_recommendation', 'lead_posts', ['analysis_recommendation'])
