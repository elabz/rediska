"""Make the do-not-contact list a real ban list.

Adds to do_not_contact:
- source: manual / copy_ring / import
- status: active / lifted (rows are never deleted; lifting keeps history)
- notes, cluster_id, created_by, lifted_at
Usernames are lower-cased so the (provider_id, external_username) unique key
matches case-insensitively (Reddit usernames are case-insensitive).

Adds lead_posts.status_before_ban: a ban moves an active lead to `ignored` and
remembers the prior status so lifting the ban can restore it.

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "do_not_contact",
        sa.Column(
            "source",
            sa.Enum("manual", "copy_ring", "import", name="dnc_source_enum"),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "do_not_contact",
        sa.Column(
            "status",
            sa.Enum("active", "lifted", name="dnc_status_enum"),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column("do_not_contact", sa.Column("notes", sa.Text, nullable=True))
    op.add_column("do_not_contact", sa.Column("cluster_id", sa.BigInteger, nullable=True))
    op.add_column("do_not_contact", sa.Column("created_by", sa.String(64), nullable=True))
    op.add_column("do_not_contact", sa.Column("lifted_at", sa.DateTime, nullable=True))
    op.create_index("idx_dnc_status", "do_not_contact", ["provider_id", "status"])

    # The table has been write-less since 001, so this is a no-op in practice.
    op.execute("UPDATE do_not_contact SET external_username = LOWER(external_username)")

    op.add_column(
        "lead_posts",
        sa.Column(
            "status_before_ban",
            sa.Enum(
                "new", "saved", "ignored", "contact_queued", "contacted", "expired",
                name="lead_post_status_before_ban_enum",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_posts", "status_before_ban")
    op.drop_index("idx_dnc_status", table_name="do_not_contact")
    op.drop_column("do_not_contact", "lifted_at")
    op.drop_column("do_not_contact", "created_by")
    op.drop_column("do_not_contact", "cluster_id")
    op.drop_column("do_not_contact", "notes")
    op.drop_column("do_not_contact", "status")
    op.drop_column("do_not_contact", "source")
