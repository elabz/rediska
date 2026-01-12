"""Unit tests for the lead scoring agent.

Tests the agent that scores leads and provides:
1. Score (0-100) - Quality/fit score for the lead
2. Reasons - Why the lead received this score
3. Flags - Any concerns or special considerations
4. Recommended action - What to do next with this lead
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)
from rediska_core.domain.services.lead_scoring import (
    LeadScoringAgent,
    LeadScoringInput,
    LeadScoringOutput,
    LeadScoringService,
    ScoringFlag,
    ScoringReason,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


@pytest.fixture
def sample_lead_data():
    """Create sample lead post data."""
    return {
        "id": 1,
        "provider_id": "reddit",
        "source_location": "r/startups",
        "external_post_id": "abc123",
        "title": "Looking for a CRM solution for our growing startup",
        "body_text": "We're a 20-person B2B SaaS company that just raised Series A. "
        "Our current spreadsheet-based system isn't scaling. "
        "Need something that integrates with Slack and has good automation. "
        "Budget is around $500/month. Any recommendations?",
        "post_created_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        "author_username": "startup_ceo",
    }


@pytest.fixture
def sample_profile_summary():
    """Create sample profile summary data."""
    return {
        "summary": "Tech startup founder building a B2B SaaS product. Active in startup communities.",
        "signals": [
            {"name": "role", "value": "founder/CEO", "confidence": 0.95},
            {"name": "company_stage", "value": "Series A", "confidence": 0.9},
            {"name": "industry", "value": "B2B SaaS", "confidence": 0.85},
        ],
        "risk_flags": [],
    }


# =============================================================================
# LEAD SCORING OUTPUT TESTS
# =============================================================================


class TestLeadScoringOutput:
    """Tests for LeadScoringOutput schema."""

    def test_output_schema_fields(self):
        """Output should have all required fields."""
        output = LeadScoringOutput(
            score=85,
            reasons=[
                ScoringReason(
                    factor="budget_fit",
                    impact="positive",
                    description="Budget of $500/month aligns with our pricing",
                    weight=0.3,
                ),
            ],
            flags=[],
            recommended_action="contact",
            confidence=0.85,
        )

        assert output.score == 85
        assert len(output.reasons) == 1
        assert output.recommended_action == "contact"
        assert output.confidence == 0.85

    def test_score_bounds(self):
        """Score should be between 0 and 100."""
        output = LeadScoringOutput(
            score=50,
            reasons=[],
            flags=[],
            recommended_action="review",
            confidence=0.5,
        )

        assert 0 <= output.score <= 100

    def test_scoring_reason_structure(self):
        """ScoringReason should capture why score was given."""
        reason = ScoringReason(
            factor="company_size",
            impact="positive",
            description="20-person company is in our target segment",
            weight=0.25,
        )

        assert reason.factor == "company_size"
        assert reason.impact == "positive"
        assert reason.weight == 0.25

    def test_scoring_flag_structure(self):
        """ScoringFlag should capture concerns."""
        flag = ScoringFlag(
            type="competitor_mention",
            severity="medium",
            description="Post mentions considering competitor products",
        )

        assert flag.type == "competitor_mention"
        assert flag.severity == "medium"

    def test_recommended_actions(self):
        """Output should have valid recommended actions."""
        valid_actions = ["contact", "review", "nurture", "skip", "prioritize"]

        for action in valid_actions:
            output = LeadScoringOutput(
                score=50,
                reasons=[],
                flags=[],
                recommended_action=action,
                confidence=0.5,
            )
            assert output.recommended_action == action


# =============================================================================
# LEAD SCORING INPUT TESTS
# =============================================================================


class TestLeadScoringInput:
    """Tests for LeadScoringInput."""

    def test_input_from_lead_data(self, sample_lead_data):
        """Input should accept lead post data."""
        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
        )

        assert input_data.lead_data["title"] is not None
        assert "CRM" in input_data.lead_data["title"]

    def test_input_with_profile_summary(self, sample_lead_data, sample_profile_summary):
        """Input should accept optional profile summary."""
        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
            profile_summary=sample_profile_summary,
        )

        assert input_data.profile_summary is not None
        assert "founder" in input_data.profile_summary["summary"]

    def test_input_with_scoring_criteria(self, sample_lead_data):
        """Input should accept custom scoring criteria."""
        criteria = {
            "target_industries": ["B2B SaaS", "fintech"],
            "min_company_size": 10,
            "max_company_size": 500,
            "budget_range": {"min": 200, "max": 2000},
        }

        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
            scoring_criteria=criteria,
        )

        assert input_data.scoring_criteria["min_company_size"] == 10

    def test_input_to_prompt(self, sample_lead_data, sample_profile_summary):
        """Input should generate a prompt for the agent."""
        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
            profile_summary=sample_profile_summary,
        )

        prompt = input_data.to_prompt()

        assert "CRM" in prompt
        assert "startup" in prompt.lower()
        assert "founder" in prompt.lower()


# =============================================================================
# LEAD SCORING AGENT TESTS
# =============================================================================


class TestLeadScoringAgent:
    """Tests for LeadScoringAgent."""

    @pytest.mark.asyncio
    async def test_agent_scores_lead(
        self, mock_inference_client, sample_lead_data, sample_profile_summary
    ):
        """Agent should score a lead."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 85,
                "reasons": [
                    {"factor": "budget_fit", "impact": "positive", "description": "$500/month budget fits our pricing", "weight": 0.3},
                    {"factor": "company_stage", "impact": "positive", "description": "Series A company with growth potential", "weight": 0.25},
                    {"factor": "clear_need", "impact": "positive", "description": "Explicitly looking for CRM solution", "weight": 0.25}
                ],
                "flags": [],
                "recommended_action": "contact",
                "confidence": 0.85
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=150,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
            profile_summary=sample_profile_summary,
        )

        result = await agent.score(input_data)

        assert result.success
        assert result.output is not None
        assert result.output.score == 85
        assert result.output.recommended_action == "contact"

    @pytest.mark.asyncio
    async def test_agent_provides_reasons(
        self, mock_inference_client, sample_lead_data
    ):
        """Agent should provide reasons for the score."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 75,
                "reasons": [
                    {"factor": "intent_signal", "impact": "positive", "description": "Clear buying intent", "weight": 0.3},
                    {"factor": "timeline", "impact": "neutral", "description": "No specific timeline mentioned", "weight": 0.1},
                    {"factor": "authority", "impact": "positive", "description": "Appears to be decision maker", "weight": 0.2}
                ],
                "flags": [],
                "recommended_action": "contact",
                "confidence": 0.8
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=120,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(lead_data=sample_lead_data)

        result = await agent.score(input_data)

        assert result.success
        assert len(result.output.reasons) >= 2

        # Check reason structure
        reason = result.output.reasons[0]
        assert reason.factor is not None
        assert reason.impact in ["positive", "negative", "neutral"]

    @pytest.mark.asyncio
    async def test_agent_identifies_flags(self, mock_inference_client):
        """Agent should identify concerns/flags."""
        # Lead with potential concerns
        lead_data = {
            "id": 2,
            "title": "Need cheap CRM, considering HubSpot free tier",
            "body_text": "We're bootstrapped and need something free or very cheap. "
            "Currently looking at HubSpot's free tier and Zoho.",
            "source_location": "r/smallbusiness",
        }

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 35,
                "reasons": [
                    {"factor": "budget", "impact": "negative", "description": "Looking for free/cheap solutions", "weight": 0.4}
                ],
                "flags": [
                    {"type": "low_budget", "severity": "high", "description": "Explicitly seeking free solutions"},
                    {"type": "competitor_evaluation", "severity": "medium", "description": "Already considering HubSpot and Zoho"}
                ],
                "recommended_action": "nurture",
                "confidence": 0.75
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=250,
                output_tokens=100,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(lead_data=lead_data)

        result = await agent.score(input_data)

        assert result.success
        assert result.output.score < 50  # Low score
        assert len(result.output.flags) >= 1
        assert result.output.recommended_action in ["nurture", "skip"]

    @pytest.mark.asyncio
    async def test_agent_recommends_action(
        self, mock_inference_client, sample_lead_data
    ):
        """Agent should recommend appropriate action."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 90,
                "reasons": [
                    {"factor": "high_intent", "impact": "positive", "description": "Strong buying signals", "weight": 0.4}
                ],
                "flags": [],
                "recommended_action": "prioritize",
                "confidence": 0.9
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=80,
                latency_ms=350,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(lead_data=sample_lead_data)

        result = await agent.score(input_data)

        assert result.success
        assert result.output.recommended_action == "prioritize"

    @pytest.mark.asyncio
    async def test_agent_returns_model_info(
        self, mock_inference_client, sample_lead_data
    ):
        """Agent should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 70,
                "reasons": [],
                "flags": [],
                "recommended_action": "review",
                "confidence": 0.7
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=350,
                output_tokens=60,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(lead_data=sample_lead_data)

        result = await agent.score(input_data)

        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"

    @pytest.mark.asyncio
    async def test_agent_uses_scoring_criteria(
        self, mock_inference_client, sample_lead_data
    ):
        """Agent should incorporate custom scoring criteria."""
        criteria = {
            "target_industries": ["B2B SaaS"],
            "ideal_company_size": "10-100",
            "budget_min": 300,
        }

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 80,
                "reasons": [
                    {"factor": "industry_match", "impact": "positive", "description": "B2B SaaS matches target", "weight": 0.3}
                ],
                "flags": [],
                "recommended_action": "contact",
                "confidence": 0.8
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=80,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(
            lead_data=sample_lead_data,
            scoring_criteria=criteria,
        )

        result = await agent.score(input_data)

        assert result.success

        # Verify criteria was included in prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        user_message = messages[1].content
        assert "B2B SaaS" in user_message


# =============================================================================
# AGENT ERROR HANDLING TESTS
# =============================================================================


class TestLeadScoringAgentErrors:
    """Tests for error handling in LeadScoringAgent."""

    @pytest.mark.asyncio
    async def test_agent_handles_invalid_json(self, mock_inference_client):
        """Agent should handle invalid JSON response."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="Not valid JSON at all",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=10,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(
            lead_data={"id": 1, "title": "Test", "body_text": "Test"},
        )

        result = await agent.score(input_data)

        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_agent_handles_missing_score(self, mock_inference_client):
        """Agent should handle response missing required score field."""
        mock_inference_client.chat.return_value = ChatResponse(
            content='{"reasons": [], "flags": [], "recommended_action": "review"}',
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=30,
                latency_ms=150,
            ),
            finish_reason="stop",
        )

        agent = LeadScoringAgent(inference_client=mock_inference_client)

        input_data = LeadScoringInput(
            lead_data={"id": 1, "title": "Test", "body_text": "Test"},
        )

        result = await agent.score(input_data)

        # Should fail validation
        assert not result.success


# =============================================================================
# SYSTEM PROMPT TESTS
# =============================================================================


class TestLeadScoringSystemPrompt:
    """Tests for the lead scoring system prompt."""

    def test_system_prompt_includes_scoring_guidance(self):
        """System prompt should include scoring guidance."""
        agent = LeadScoringAgent(inference_client=AsyncMock())

        prompt = agent.get_system_prompt()

        assert "score" in prompt.lower()
        assert "0" in prompt and "100" in prompt

    def test_system_prompt_defines_actions(self):
        """System prompt should define recommended actions."""
        agent = LeadScoringAgent(inference_client=AsyncMock())

        prompt = agent.get_system_prompt()

        # Should mention possible actions
        assert "contact" in prompt.lower() or "action" in prompt.lower()

    def test_system_prompt_specifies_output_format(self):
        """System prompt should specify JSON output format."""
        agent = LeadScoringAgent(inference_client=AsyncMock())

        prompt = agent.get_system_prompt()

        assert "json" in prompt.lower()
