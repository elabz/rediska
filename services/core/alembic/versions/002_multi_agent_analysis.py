"""Add multi-agent lead analysis tables

Revision ID: 002
Revises: 001
Create Date: 2026-01-12

Creates tables for multi-dimensional lead analysis:
- agent_prompts: Versioned prompt storage for all 6 agents
- lead_analyses: Multi-dimensional analysis results per lead
- analysis_dimensions: Individual dimension execution tracking
- Updates to lead_posts: latest_analysis_id, analysis_recommendation, analysis_confidence
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_prompts table - Versioned prompt storage
    op.create_table(
        "agent_prompts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("agent_dimension", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("output_schema_json", sa.JSON, nullable=False),
        sa.Column("temperature", sa.Float, nullable=False, server_default="0.7"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="2048"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "agent_dimension", "version", name="uq_agent_prompt_version"
        ),
    )
    op.create_index(
        "idx_agent_prompt_active",
        "agent_prompts",
        ["agent_dimension", "is_active"],
    )

    # Seed default agent prompts for all 6 agents
    op.execute(
        """INSERT INTO agent_prompts
        (agent_dimension, version, system_prompt, output_schema_json, temperature, max_tokens, is_active, created_by, notes)
        VALUES
        ('demographics', 1, 'Analyze the post to extract demographic information including age, gender, and location.', '{}', 0.7, 2048, 1, 'system', 'Initial demographics agent'),
        ('preferences', 1, 'Analyze the post to extract personal preferences, interests, hobbies, and lifestyle indicators.', '{}', 0.7, 2048, 1, 'system', 'Initial preferences agent'),
        ('relationship_goals', 1, 'Analyze the post to extract relationship intentions, goals, partner criteria, and deal-breakers.', '{}', 0.7, 2048, 1, 'system', 'Initial relationship goals agent'),
        ('risk_flags', 1, 'Analyze the post to identify red flags, safety concerns, and authenticity issues.', '{}', 0.7, 2048, 1, 'system', 'Initial risk flags agent'),
        ('sexual_preferences', 1, 'Analyze the post to extract sexual orientation, preferences, and desired partner age range.', '{}', 0.7, 2048, 1, 'system', 'Initial sexual preferences agent'),
        ('meta_analysis', 1, 'Synthesize multi-dimensional analysis results into a final suitability recommendation.', '{}', 0.7, 2048, 1, 'system', 'Initial meta-analysis coordinator')"""
    )

    # lead_analyses table - Multi-dimensional analysis results
    op.create_table(
        "lead_analyses",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.BigInteger, nullable=False),
        sa.Column("account_id", sa.BigInteger, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "completed", "failed", name="analysis_status_enum"
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_detail", sa.Text, nullable=True),
        # Dimension results (JSON storage)
        sa.Column("demographics_json", sa.JSON, nullable=True),
        sa.Column("preferences_json", sa.JSON, nullable=True),
        sa.Column("relationship_goals_json", sa.JSON, nullable=True),
        sa.Column("risk_flags_json", sa.JSON, nullable=True),
        sa.Column("sexual_preferences_json", sa.JSON, nullable=True),
        # Meta-analysis result
        sa.Column("meta_analysis_json", sa.JSON, nullable=True),
        sa.Column(
            "final_recommendation",
            sa.Enum(
                "suitable", "not_recommended", "needs_review",
                name="recommendation_enum"
            ),
            nullable=True,
        ),
        sa.Column("recommendation_reasoning", sa.Text, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        # Metadata
        sa.Column("prompt_versions_json", sa.JSON, nullable=False),
        sa.Column("model_info_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead_posts.id"], name="fk_analysis_lead"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["external_accounts.id"], name="fk_analysis_account"
        ),
    )
    op.create_index("idx_analysis_lead_completed", "lead_analyses", ["lead_id", "completed_at"])
    op.create_index("idx_analysis_status", "lead_analyses", ["status"])
    op.create_index("idx_analysis_recommendation", "lead_analyses", ["final_recommendation"])

    # analysis_dimensions table - Individual dimension execution tracking
    op.create_table(
        "analysis_dimensions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.BigInteger, nullable=False),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "completed", "failed", name="dimension_status_enum"
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("input_data_json", sa.JSON, nullable=False),
        sa.Column("output_json", sa.JSON, nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("model_info_json", sa.JSON, nullable=True),
        sa.Column("prompt_version", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["lead_analyses.id"], name="fk_dimension_analysis", ondelete="CASCADE"
        ),
    )
    op.create_index("idx_dimension_analysis", "analysis_dimensions", ["analysis_id", "dimension"])
    op.create_index("idx_dimension_status", "analysis_dimensions", ["status"])

    # Update lead_posts table with analysis fields
    op.add_column("lead_posts", sa.Column("latest_analysis_id", sa.BigInteger, nullable=True))
    op.add_column(
        "lead_posts",
        sa.Column(
            "analysis_recommendation",
            sa.Enum(
                "suitable", "not_recommended", "needs_review", name="lead_recommendation_enum"
            ),
            nullable=True,
        ),
    )
    op.add_column("lead_posts", sa.Column("analysis_confidence", sa.Float, nullable=True))

    # Add foreign key for latest_analysis_id
    op.create_foreign_key(
        "fk_lead_latest_analysis",
        "lead_posts",
        "lead_analyses",
        ["latest_analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add index on analysis_recommendation
    op.create_index("idx_lead_analysis_recommendation", "lead_posts", ["analysis_recommendation"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_lead_analysis_recommendation", table_name="lead_posts")

    # Drop foreign key from lead_posts to lead_analyses
    op.drop_constraint("fk_lead_latest_analysis", "lead_posts", type_="foreignkey")

    # Drop columns from lead_posts
    op.drop_column("lead_posts", "analysis_confidence")
    op.drop_column("lead_posts", "analysis_recommendation")
    op.drop_column("lead_posts", "latest_analysis_id")

    # Drop tables
    op.drop_table("analysis_dimensions")
    op.drop_table("lead_analyses")
    op.drop_table("agent_prompts")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS dimension_status_enum")
    op.execute("DROP TYPE IF EXISTS lead_recommendation_enum")
    op.execute("DROP TYPE IF EXISTS recommendation_enum")
    op.execute("DROP TYPE IF EXISTS analysis_status_enum")
