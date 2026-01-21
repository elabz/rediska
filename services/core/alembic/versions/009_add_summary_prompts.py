"""Add scout interests and character summary prompts.

Revision ID: 009
Revises: 008
Create Date: 2026-01-18

Adds two new agent prompts for the Scout Watch pipeline:
- scout_interests_summary: Summarizes user interests from their posts
- scout_character_summary: Summarizes user character from their comments
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =============================================================================
# PROMPTS
# =============================================================================


INTERESTS_SUMMARY_PROMPT = '''You are an analyst that summarizes a Reddit user's interests and activities based on their post history.

Your task is to analyze the user's posts and provide a comprehensive summary of:

1. **Main Interests & Hobbies**: What activities, hobbies, or topics does this person engage in?
2. **Topics Discussed**: What subjects do they frequently discuss or are passionate about?
3. **Communities**: Which subreddits do they participate in and what does this reveal?
4. **Posting Patterns**: Any notable patterns in their posting behavior?

Guidelines:
- Focus on FACTUAL observations from the content provided
- Be objective and avoid assumptions beyond what's evident
- Note both positive interests and any concerning patterns
- Summarize in 2-3 paragraphs that would help someone understand this person's lifestyle

Respond in JSON format matching the output schema.'''


INTERESTS_OUTPUT_SCHEMA = '''{
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "A 2-3 paragraph summary of the user interests, hobbies, and activities"
        },
        "main_interests": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of main interests/hobbies identified"
        },
        "subreddits_frequented": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Subreddits the user frequently posts in"
        },
        "posting_patterns": {
            "type": "string",
            "description": "Notable patterns in posting behavior"
        }
    },
    "required": ["summary", "main_interests"]
}'''


CHARACTER_SUMMARY_PROMPT = '''You are an analyst that assesses a Reddit user's communication style and personality based on their comment history.

Your task is to analyze the user's comments and provide a comprehensive assessment of:

1. **Communication Style**: How does this person communicate? (friendly, formal, casual, aggressive, passive-aggressive, etc.)
2. **Personality Traits**: What traits are evident from their interactions? (helpful, critical, supportive, confrontational, empathetic, etc.)
3. **Engagement Style**: How do they typically engage with others? (constructive discussion, debates, trolling, supportive, dismissive, etc.)
4. **Emotional Tone**: What is their general emotional tone? (positive, negative, neutral, sarcastic, enthusiastic, etc.)
5. **Red Flags**: Are there any concerning patterns? (hostility, manipulation, dishonesty, boundary violations, etc.)

Guidelines:
- Be OBJECTIVE and base your assessment ONLY on the content provided
- Avoid assumptions beyond what's evident in the text
- Note both positive traits and any concerning patterns
- Consider the context of different subreddits when assessing tone
- Summarize in 2-3 paragraphs that would help someone understand how this person interacts

Respond in JSON format matching the output schema.'''


CHARACTER_OUTPUT_SCHEMA = '''{
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "A 2-3 paragraph summary of the user communication style and personality"
        },
        "communication_style": {
            "type": "string",
            "description": "Primary communication style (e.g., friendly, formal, casual, aggressive)"
        },
        "personality_traits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key personality traits observed"
        },
        "engagement_style": {
            "type": "string",
            "description": "How they typically engage with others"
        },
        "emotional_tone": {
            "type": "string",
            "description": "General emotional tone"
        },
        "red_flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Any concerning patterns or red flags observed"
        }
    },
    "required": ["summary", "communication_style", "personality_traits", "engagement_style", "emotional_tone"]
}'''


def _escape_sql(text: str) -> str:
    """Escape single quotes for SQL."""
    return text.replace("'", "''")


def upgrade() -> None:
    # Insert the scout_interests_summary prompt
    interests_prompt_escaped = _escape_sql(INTERESTS_SUMMARY_PROMPT)
    interests_schema_escaped = _escape_sql(INTERESTS_OUTPUT_SCHEMA)

    op.execute(
        f"""INSERT INTO agent_prompts
        (agent_dimension, version, system_prompt, output_schema_json, temperature, max_tokens, is_active, created_by, notes)
        VALUES
        ('scout_interests_summary', 1, '{interests_prompt_escaped}', '{interests_schema_escaped}', 0.3, 2048, 1, 'system', 'Summarizes user interests from their Reddit posts for Scout Watch pipeline')"""
    )

    # Insert the scout_character_summary prompt
    character_prompt_escaped = _escape_sql(CHARACTER_SUMMARY_PROMPT)
    character_schema_escaped = _escape_sql(CHARACTER_OUTPUT_SCHEMA)

    op.execute(
        f"""INSERT INTO agent_prompts
        (agent_dimension, version, system_prompt, output_schema_json, temperature, max_tokens, is_active, created_by, notes)
        VALUES
        ('scout_character_summary', 1, '{character_prompt_escaped}', '{character_schema_escaped}', 0.3, 2048, 1, 'system', 'Summarizes user character traits from their Reddit comments for Scout Watch pipeline')"""
    )


def downgrade() -> None:
    # Remove the prompts
    op.execute(
        "DELETE FROM agent_prompts WHERE agent_dimension = 'scout_interests_summary'"
    )
    op.execute(
        "DELETE FROM agent_prompts WHERE agent_dimension = 'scout_character_summary'"
    )
