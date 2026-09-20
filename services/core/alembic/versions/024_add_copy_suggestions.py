"""Probable rewrites: semantic copy suggestions awaiting a human decision.

A post that reads like an older post by a different author, at a cosine the
fingerprint matcher would never catch (different words, same offer), becomes a
suggestion here. Accepting one joins the posts into a copy cluster; rejecting
one records that the user looked and said no. Nothing clusters on similarity
alone, so this table is the whole mechanism.

Revision ID: 024
Revises: 023
"""

from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copy_suggestions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "provider_id",
            sa.String(32),
            sa.ForeignKey("providers.provider_id"),
            nullable=False,
        ),
        sa.Column("source_external_post_id", sa.String(128), nullable=False),
        sa.Column("source_doc_type", sa.String(32), nullable=False),
        sa.Column("source_entity_id", sa.BigInteger, nullable=False),
        sa.Column("source_author", sa.String(128), nullable=True),
        sa.Column("match_external_post_id", sa.String(128), nullable=False),
        sa.Column("match_doc_type", sa.String(32), nullable=False),
        sa.Column("match_entity_id", sa.BigInteger, nullable=False),
        sa.Column("match_author", sa.String(128), nullable=True),
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column(
            "status",
            sa.Enum("new", "accepted", "rejected", name="copy_suggestion_status_enum"),
            nullable=False,
            server_default="new",
        ),
        sa.Column("cluster_id", sa.BigInteger, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "provider_id",
            "source_external_post_id",
            "match_external_post_id",
            name="uq_copy_suggestion_pair",
        ),
    )
    op.create_index(
        "idx_copy_suggestion_status", "copy_suggestions", ["status", "created_at"]
    )
    op.create_index(
        "idx_copy_suggestion_source",
        "copy_suggestions",
        ["provider_id", "source_external_post_id"],
    )
    op.create_index(
        "idx_copy_suggestion_match",
        "copy_suggestions",
        ["provider_id", "match_external_post_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_copy_suggestion_match", table_name="copy_suggestions")
    op.drop_index("idx_copy_suggestion_source", table_name="copy_suggestions")
    op.drop_index("idx_copy_suggestion_status", table_name="copy_suggestions")
    op.drop_table("copy_suggestions")
