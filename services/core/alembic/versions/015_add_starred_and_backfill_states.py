"""Add starred columns and backfill contact/engagement states.

Adds:
- is_starred BOOLEAN NOT NULL DEFAULT FALSE to external_accounts
- starred_at DATETIME NULL to external_accounts

Backfills:
- contact_state='contacted' for accounts with outgoing visible messages
- engagement_state='engaged' for contacted accounts with incoming messages after contact

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add starred columns
    op.add_column(
        "external_accounts",
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "external_accounts",
        sa.Column("starred_at", sa.DateTime(), nullable=True),
    )

    # Backfill contact_state for accounts that have outgoing visible messages
    op.execute("""
        UPDATE external_accounts ea
        JOIN conversations c ON c.counterpart_account_id = ea.id
        JOIN messages m ON m.conversation_id = c.id
            AND m.direction = 'out'
            AND m.remote_visibility = 'visible'
            AND m.deleted_at IS NULL
        SET ea.contact_state = 'contacted',
            ea.first_contacted_at = COALESCE(
                ea.first_contacted_at,
                (
                    SELECT MIN(m2.sent_at)
                    FROM messages m2
                    JOIN conversations c2 ON c2.id = m2.conversation_id
                    WHERE c2.counterpart_account_id = ea.id
                      AND m2.direction = 'out'
                      AND m2.remote_visibility = 'visible'
                      AND m2.deleted_at IS NULL
                )
            )
        WHERE ea.contact_state = 'not_contacted'
    """)

    # Backfill engagement_state for contacted accounts with incoming messages
    # after first_contacted_at
    op.execute("""
        UPDATE external_accounts ea
        JOIN conversations c ON c.counterpart_account_id = ea.id
        JOIN messages m ON m.conversation_id = c.id
            AND m.direction = 'in'
            AND m.deleted_at IS NULL
            AND m.sent_at > ea.first_contacted_at
        SET ea.engagement_state = 'engaged',
            ea.first_inbound_after_contact_at = COALESCE(
                ea.first_inbound_after_contact_at,
                (
                    SELECT MIN(m2.sent_at)
                    FROM messages m2
                    JOIN conversations c2 ON c2.id = m2.conversation_id
                    WHERE c2.counterpart_account_id = ea.id
                      AND m2.direction = 'in'
                      AND m2.deleted_at IS NULL
                      AND m2.sent_at > ea.first_contacted_at
                )
            )
        WHERE ea.contact_state = 'contacted'
          AND ea.engagement_state = 'not_engaged'
    """)


def downgrade() -> None:
    op.drop_column("external_accounts", "starred_at")
    op.drop_column("external_accounts", "is_starred")
