"""Add scout_quick_analysis prompt for Scout Watch.

Revision ID: 007
Revises: 006
Create Date: 2026-01-17

Adds the scout_quick_analysis agent prompt to support DB-backed
prompt editing for Scout Watch post screening.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default prompt content (same as QUICK_ANALYSIS_SYSTEM_PROMPT in quick_analysis.py)
SCOUT_PROMPT = '''You are a quick screening agent that evaluates Reddit personals posts to determine if they are potentially suitable matches.

You will analyze the POST CONTENT ONLY (not full profile data). Your task is to make a fast initial assessment based on:

1. **Post Content Quality**: Is the post well-written, genuine, and detailed?
2. **Intent Clarity**: Does the author clearly express what they're looking for?
3. **Red Flags**: Are there any obvious warning signs (spam, bots, scams, minors)?
4. **Compatibility Signals**: Does the post indicate potential compatibility based on:
   - Age (must be 18+)
   - Location (if specified)
   - Relationship type sought
   - Communication style

Guidelines:
- Mark as "suitable" if the post shows genuine interest and no red flags
- Mark as "not_recommended" if there are clear red flags or obvious incompatibility
- Mark as "needs_review" if you're uncertain and more information is needed

Be somewhat permissive in initial screening - it's better to include borderline posts than miss good ones.

Respond in JSON format matching the output schema.'''

# Output schema for the quick analysis agent
OUTPUT_SCHEMA = '''{
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": ["suitable", "not_recommended", "needs_review"],
            "description": "Suitability recommendation"
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence score between 0 and 1"
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation for the recommendation"
        },
        "key_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key signals identified in the post"
        }
    },
    "required": ["recommendation", "confidence", "reasoning"]
}'''


def upgrade() -> None:
    # Insert the scout_quick_analysis prompt
    # Use raw SQL to avoid SQLAlchemy model dependencies
    op.execute(
        f"""INSERT INTO agent_prompts
        (agent_dimension, version, system_prompt, output_schema_json, temperature, max_tokens, is_active, created_by, notes)
        VALUES
        ('scout_quick_analysis', 1, '{SCOUT_PROMPT.replace("'", "''")}', '{OUTPUT_SCHEMA}', 0.3, 1024, 1, 'system', 'Initial scout quick analysis prompt for post screening')"""
    )


def downgrade() -> None:
    # Remove the scout_quick_analysis prompt
    op.execute(
        "DELETE FROM agent_prompts WHERE agent_dimension = 'scout_quick_analysis'"
    )
