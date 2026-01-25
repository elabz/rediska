"""Add dimension_results_json to scout_watch_posts.

Revision ID: 011
Revises: 010
Create Date: 2026-01-25

Adds a JSON column to store full dimension analysis results for all posts,
not just those that become leads. This enables auditing of analysis results
for rejected posts.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'scout_watch_posts',
        sa.Column(
            'dimension_results_json',
            sa.JSON(),
            nullable=True,
            comment='Full dimension results from multi-agent analysis'
        )
    )


def downgrade() -> None:
    op.drop_column('scout_watch_posts', 'dimension_results_json')
