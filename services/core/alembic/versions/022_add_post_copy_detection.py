"""Add post copy detection: fingerprints, sketch bands, copy clusters.

Adds:
- post_fingerprints: one row per provider post seen (exact hash + MinHash
  sketch, no text), so copies are detectable after scout history cleanup
- post_fingerprint_bands: the smallest sketch values as band keys for lookup
- copy_clusters: posts of the same text by different authors, with a computed
  kind and a sticky human decision
- copy_cluster_members: fingerprint -> cluster (a fingerprint is in at most one)
- copy_cluster_suppressions: fingerprints of texts the human marked as a
  coincidence (templates, quotes); they never form a cluster again

Revision ID: 022
Revises: 021
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_fingerprints",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("external_post_id", sa.String(128), nullable=False),
        sa.Column("author_username", sa.String(255), nullable=True),
        sa.Column(
            "account_id",
            sa.BigInteger,
            sa.ForeignKey("external_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("char_len", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exact_hash", sa.BINARY(16), nullable=False),
        sa.Column("sketch", sa.VARBINARY(512), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "scout", "trial", "browse", "lead", "profile_item",
                name="post_fingerprint_source_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "repost_of_id",
            sa.BigInteger,
            sa.ForeignKey("post_fingerprints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("provider_id", "external_post_id", name="uq_post_fingerprint"),
    )
    op.create_index("idx_post_fp_external_post", "post_fingerprints", ["external_post_id"])
    op.create_index("idx_post_fp_author", "post_fingerprints", ["author_username"])
    op.create_index("idx_post_fp_exact_hash", "post_fingerprints", ["exact_hash"])

    op.create_table(
        "post_fingerprint_bands",
        sa.Column("band_hash", sa.BigInteger, nullable=False),
        sa.Column(
            "fingerprint_id",
            sa.BigInteger,
            sa.ForeignKey("post_fingerprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("band_hash", "fingerprint_id"),
    )
    op.create_index("idx_post_fp_band_fp", "post_fingerprint_bands", ["fingerprint_id"])

    op.create_table(
        "copy_clusters",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "ring_suspect", "returning_author", "unclassified",
                name="copy_cluster_kind_enum",
            ),
            nullable=False,
            server_default="unclassified",
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "confirmed_ring", "same_person", "coincidence",
                name="copy_cluster_decision_enum",
            ),
            nullable=True,
        ),
        sa.Column("decision_notes", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("author_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("member_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_posted_at", sa.DateTime, nullable=True),
        sa.Column("last_posted_at", sa.DateTime, nullable=True),
        sa.Column("classified_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("idx_copy_cluster_kind", "copy_clusters", ["kind", "decision"])
    op.create_index("idx_copy_cluster_last_posted", "copy_clusters", ["last_posted_at"])

    op.create_table(
        "copy_cluster_members",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "cluster_id",
            sa.BigInteger,
            sa.ForeignKey("copy_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fingerprint_id",
            sa.BigInteger,
            sa.ForeignKey("post_fingerprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float, nullable=True),
        sa.Column("joined_at", sa.DateTime, nullable=False),
        sa.Column("ban_suggestion_dismissed_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("fingerprint_id", name="uq_copy_cluster_member_fp"),
    )
    op.create_index("idx_copy_cluster_member_cluster", "copy_cluster_members", ["cluster_id"])

    op.create_table(
        "copy_cluster_suppressions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fingerprint_id",
            sa.BigInteger,
            sa.ForeignKey("post_fingerprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exact_hash", sa.BINARY(16), nullable=False),
        sa.Column("cluster_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("fingerprint_id", name="uq_copy_suppression_fp"),
    )
    op.create_index("idx_copy_suppression_hash", "copy_cluster_suppressions", ["exact_hash"])


def downgrade() -> None:
    op.drop_table("copy_cluster_suppressions")
    op.drop_table("copy_cluster_members")
    op.drop_table("copy_clusters")
    op.drop_table("post_fingerprint_bands")
    op.drop_table("post_fingerprints")
