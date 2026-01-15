"""Add 'cancelled' to job_status_enum

Revision ID: 003
Revises: 002
Create Date: 2026-01-14

Adds 'cancelled' status to the job_status_enum for tracking
manually cancelled message send jobs.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL requires ALTER TABLE to modify ENUM columns
    # Add 'cancelled' to the job_status_enum
    op.execute(
        "ALTER TABLE jobs MODIFY COLUMN status "
        "ENUM('queued', 'running', 'retrying', 'failed', 'done', 'cancelled') "
        "NOT NULL DEFAULT 'queued'"
    )

    # Update existing cancelled jobs (those with CANCELLED_BY_USER error) to use the new status
    op.execute(
        "UPDATE jobs SET status = 'cancelled' "
        "WHERE status = 'failed' AND last_error = 'CANCELLED_BY_USER'"
    )


def downgrade() -> None:
    # Revert cancelled jobs back to failed status
    op.execute(
        "UPDATE jobs SET status = 'failed' "
        "WHERE status = 'cancelled'"
    )

    # Remove 'cancelled' from the enum
    op.execute(
        "ALTER TABLE jobs MODIFY COLUMN status "
        "ENUM('queued', 'running', 'retrying', 'failed', 'done') "
        "NOT NULL DEFAULT 'queued'"
    )
