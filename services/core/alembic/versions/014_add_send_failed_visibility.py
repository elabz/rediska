"""Add send_failed to remote_visibility_enum and send_error column.

When a message send clearly fails (e.g. recipient blocks messages),
the message should be marked as 'send_failed' with the error reason,
instead of staying as 'unknown' (shown as "Pending" in the UI).

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'send_failed' to the remote_visibility_enum
    # MySQL requires ALTER TABLE ... MODIFY COLUMN to change enum values
    op.execute(
        "ALTER TABLE messages MODIFY COLUMN remote_visibility "
        "ENUM('visible', 'deleted_by_author', 'removed', 'unknown', 'send_failed') "
        "NOT NULL DEFAULT 'unknown'"
    )

    # Add send_error column to store the failure reason
    op.add_column("messages", sa.Column("send_error", sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove send_error column
    op.drop_column("messages", "send_error")

    # Revert enum (move any send_failed back to unknown first)
    op.execute(
        "UPDATE messages SET remote_visibility = 'unknown' "
        "WHERE remote_visibility = 'send_failed'"
    )
    op.execute(
        "ALTER TABLE messages MODIFY COLUMN remote_visibility "
        "ENUM('visible', 'deleted_by_author', 'removed', 'unknown') "
        "NOT NULL DEFAULT 'unknown'"
    )
