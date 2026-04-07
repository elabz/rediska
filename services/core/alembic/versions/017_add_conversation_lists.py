"""Add conversation lists and membership tables.

Adds:
- conversation_lists table (id, name, created_at, updated_at)
- conversation_list_members junction table (id, list_id, conversation_id, added_at)

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_lists",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "conversation_list_members",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "list_id",
            sa.BigInteger,
            sa.ForeignKey("conversation_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.BigInteger,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("added_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("list_id", "conversation_id", name="uq_list_conv"),
        sa.Index("idx_list_member_list", "list_id"),
        sa.Index("idx_list_member_conv", "conversation_id"),
    )


def downgrade() -> None:
    op.drop_table("conversation_list_members")
    op.drop_table("conversation_lists")
