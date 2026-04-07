"""Add threading columns to messages.

Adds:
- thread_external_id VARCHAR(128) NULL — Reddit's first_message_name (thread root)
- parent_external_message_id VARCHAR(128) NULL — Reddit's parent_id (direct parent)
- Index on thread_external_id for grouping queries

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("thread_external_id", sa.String(128), nullable=True))
    op.add_column("messages", sa.Column("parent_external_message_id", sa.String(128), nullable=True))
    op.create_index("idx_msg_thread", "messages", ["thread_external_id"])


def downgrade() -> None:
    op.drop_index("idx_msg_thread", table_name="messages")
    op.drop_column("messages", "parent_external_message_id")
    op.drop_column("messages", "thread_external_id")
