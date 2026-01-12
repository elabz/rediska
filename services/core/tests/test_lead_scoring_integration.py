"""Integration tests for lead scoring agent.

Tests the full flow:
1. Loading lead data from database
2. Fetching author profile summary
3. Running the lead scoring agent
4. Returning structured scoring results
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileSnapshot,
    Provider,
)
from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)
from rediska_core.domain.services.lead_scoring import (
    LeadScoringAgent,
    LeadScoringInput,
    LeadScoringService,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_account(db_session, setup_provider):
    """Set up an external account."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="startup_ceo",
        external_user_id="t2_startup",
        analysis_state="analyzed",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def setup_profile_snapshot(db_session, setup_account):
    """Set up a profile snapshot for the account."""
    snapshot = ProfileSnapshot(
        account_id=setup_account.id,
        fetched_at=datetime.now(timezone.utc),
        summary_text="Tech startup founder building B2B SaaS products. Active in startup communities.",
        signals_json=[
            {"name": "role", "value": "founder", "confidence": 0.95},
            {"name": "industry", "value": "B2B SaaS", "confidence": 0.9},
            {"name": "company_stage", "value": "Series A", "confidence": 0.85},
        ],
        risk_flags_json=[],
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


@pytest.fixture
def setup_lead(db_session, setup_provider, setup_account):
    """Set up a lead post."""
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/startups",
        external_post_id="lead_abc123",
        post_url="https://reddit.com/r/startups/comments/abc123",
        author_account_id=setup_account.id,
        title="Looking for a CRM solution for our growing team",
        body_text="We're a 25-person B2B SaaS company that just closed Series A. "
        "Our current spreadsheet system isn't scaling. Need something with "
        "good Slack integration and automation capabilities. Budget around $500/month.",
        status="saved",
        post_created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def setup_lead_without_author(db_session, setup_provider):
    """Set up a lead post without an author account."""
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/smallbusiness",
        external_post_id="lead_no_author",
        post_url="https://reddit.com/r/smallbusiness/comments/xyz",
        author_account_id=None,
        title="Need help choosing accounting software",
        body_text="Small business looking for affordable accounting software.",
        status="saved",
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


# =============================================================================
# SERVICE INTEGRATION TESTS
# =============================================================================


class TestLeadScoringServiceIntegration:
    """Tests for LeadScoringService with database."""

    @pytest.mark.asyncio
    async def test_score_lead_with_profile(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Service should score lead using profile data."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 88,
                "reasons": [
                    {"factor": "budget_fit", "impact": "positive", "description": "$500/month aligns with pricing", "weight": 0.3},
                    {"factor": "company_stage", "impact": "positive", "description": "Series A = growth potential", "weight": 0.25},
                    {"factor": "clear_need", "impact": "positive", "description": "Explicit CRM need stated", "weight": 0.25},
                    {"factor": "decision_maker", "impact": "positive", "description": "Founder/CEO has authority", "weight": 0.2}
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
                input_tokens=500,
                output_tokens=150,
                latency_ms=700,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead.id)

        assert result.success
        assert result.output is not None
        assert result.output.score == 88
        assert result.output.recommended_action == "prioritize"
        assert len(result.output.reasons) >= 3

    @pytest.mark.asyncio
    async def test_score_lead_includes_profile_signals(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Service should include profile signals in scoring."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 82,
                "reasons": [
                    {"factor": "profile_fit", "impact": "positive", "description": "Founder profile matches ICP", "weight": 0.3}
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
                input_tokens=450,
                output_tokens=80,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead.id)

        assert result.success

        # Verify profile data was included in prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        user_message = messages[1].content

        assert "founder" in user_message.lower()
        assert "B2B SaaS" in user_message

    @pytest.mark.asyncio
    async def test_score_lead_without_profile(
        self, db_session, setup_lead_without_author, mock_inference_client
    ):
        """Service should handle leads without author profile."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 55,
                "reasons": [
                    {"factor": "unclear_authority", "impact": "neutral", "description": "No profile to verify authority", "weight": 0.2}
                ],
                "flags": [
                    {"type": "missing_profile", "severity": "low", "description": "No author profile available"}
                ],
                "recommended_action": "review",
                "confidence": 0.6
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=200,
                output_tokens=100,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead_without_author.id)

        assert result.success
        assert result.output.recommended_action == "review"

    @pytest.mark.asyncio
    async def test_score_nonexistent_lead(
        self, db_session, mock_inference_client
    ):
        """Service should handle nonexistent lead."""
        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(99999)

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_score_lead_returns_model_info(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Service should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 75,
                "reasons": [],
                "flags": [],
                "recommended_action": "contact",
                "confidence": 0.75
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=50,
                latency_ms=350,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead.id)

        assert result.success
        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"


# =============================================================================
# SCORING CRITERIA TESTS
# =============================================================================


class TestLeadScoringWithCriteria:
    """Tests for lead scoring with custom criteria."""

    @pytest.mark.asyncio
    async def test_score_with_custom_criteria(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Service should accept custom scoring criteria."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 90,
                "reasons": [
                    {"factor": "industry_match", "impact": "positive", "description": "B2B SaaS matches target", "weight": 0.35}
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
                input_tokens=450,
                output_tokens=80,
                latency_ms=450,
            ),
            finish_reason="stop",
        )

        criteria = {
            "target_industries": ["B2B SaaS", "fintech"],
            "min_company_size": 10,
            "min_budget": 300,
        }

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(
            setup_lead.id,
            scoring_criteria=criteria,
        )

        assert result.success
        assert result.output.score >= 85

        # Verify criteria was included in prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        user_message = messages[1].content

        assert "B2B SaaS" in user_message
        assert "fintech" in user_message


# =============================================================================
# FULL FLOW TESTS
# =============================================================================


class TestLeadScoringFullFlow:
    """End-to-end tests for lead scoring flow."""

    @pytest.mark.asyncio
    async def test_full_scoring_flow(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Test complete flow from lead to score."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 92,
                "reasons": [
                    {"factor": "high_intent", "impact": "positive", "description": "Actively seeking solution", "weight": 0.3},
                    {"factor": "budget_stated", "impact": "positive", "description": "$500/month budget mentioned", "weight": 0.25},
                    {"factor": "decision_maker", "impact": "positive", "description": "Founder has buying authority", "weight": 0.25},
                    {"factor": "urgency", "impact": "positive", "description": "Current system not scaling", "weight": 0.2}
                ],
                "flags": [],
                "recommended_action": "prioritize",
                "confidence": 0.92
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=600,
                output_tokens=180,
                latency_ms=900,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead.id)

        # Verify success
        assert result.success
        assert result.output is not None

        # Verify score
        assert result.output.score == 92
        assert result.output.confidence >= 0.9

        # Verify reasons
        assert len(result.output.reasons) >= 3
        reason_factors = [r.factor for r in result.output.reasons]
        assert "high_intent" in reason_factors

        # Verify action
        assert result.output.recommended_action == "prioritize"

        # Verify model info
        assert result.model_info["model_name"] == "llama-3.2-8b"

    @pytest.mark.asyncio
    async def test_low_quality_lead_scoring(
        self, db_session, setup_provider, mock_inference_client
    ):
        """Test scoring of low quality lead."""
        # Create a low quality lead
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/freebies",
            external_post_id="lead_cheap",
            post_url="https://reddit.com/r/freebies/comments/cheap",
            title="Looking for free CRM",
            body_text="Need something completely free, no budget at all.",
            status="saved",
        )
        db_session.add(lead)
        db_session.flush()

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 15,
                "reasons": [
                    {"factor": "no_budget", "impact": "negative", "description": "Explicitly seeking free solution", "weight": 0.5}
                ],
                "flags": [
                    {"type": "no_budget", "severity": "high", "description": "No willingness to pay"}
                ],
                "recommended_action": "skip",
                "confidence": 0.85
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=150,
                output_tokens=80,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(lead.id)

        assert result.success
        assert result.output.score < 30
        assert result.output.recommended_action == "skip"
        assert len(result.output.flags) >= 1


# =============================================================================
# ACTION RECOMMENDATION TESTS
# =============================================================================


class TestActionRecommendations:
    """Tests for action recommendation logic."""

    @pytest.mark.asyncio
    async def test_prioritize_action_for_hot_lead(
        self, db_session, setup_lead, setup_profile_snapshot, mock_inference_client
    ):
        """Hot leads should get prioritize action."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 95,
                "reasons": [{"factor": "hot_lead", "impact": "positive", "description": "All signals strong", "weight": 0.5}],
                "flags": [],
                "recommended_action": "prioritize",
                "confidence": 0.95
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=60,
                latency_ms=350,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(setup_lead.id)

        assert result.success
        assert result.output.recommended_action == "prioritize"

    @pytest.mark.asyncio
    async def test_nurture_action_for_cool_lead(
        self, db_session, setup_provider, mock_inference_client
    ):
        """Cool leads should get nurture action."""
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/startups",
            external_post_id="lead_cool",
            post_url="https://reddit.com/r/startups/comments/cool",
            title="Might need CRM someday",
            body_text="Just exploring options for the future, no immediate need.",
            status="saved",
        )
        db_session.add(lead)
        db_session.flush()

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "score": 40,
                "reasons": [{"factor": "future_interest", "impact": "neutral", "description": "No immediate need", "weight": 0.4}],
                "flags": [],
                "recommended_action": "nurture",
                "confidence": 0.7
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=200,
                output_tokens=60,
                latency_ms=280,
            ),
            finish_reason="stop",
        )

        service = LeadScoringService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.score_lead(lead.id)

        assert result.success
        assert result.output.recommended_action == "nurture"
