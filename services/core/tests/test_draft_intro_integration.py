"""Integration tests for draft intro agent.

Tests the full flow:
1. Loading lead/account data from database
2. Loading identity voice config
3. Running the draft intro agent
4. Returning personalized draft messages
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    Identity,
    LeadPost,
    ProfileSnapshot,
    Provider,
)
from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)
from rediska_core.domain.services.draft_intro import (
    DraftIntroAgent,
    DraftIntroInput,
    DraftIntroService,
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
def setup_identity(db_session, setup_provider):
    """Set up an identity with voice config."""
    identity = Identity(
        provider_id="reddit",
        external_username="sales_rep",
        display_name="Sales Rep",
        voice_config_json={
            "system_prompt": "You are a friendly sales representative for a CRM company.",
            "tone": "helpful and professional",
            "style": "conversational",
            "persona_name": "Alex from CRMCo",
        },
    )
    db_session.add(identity)
    db_session.flush()
    return identity


@pytest.fixture
def setup_identity_minimal(db_session, setup_provider):
    """Set up an identity with minimal voice config."""
    identity = Identity(
        provider_id="reddit",
        external_username="basic_bot",
        display_name="Basic Bot",
        voice_config_json={},
    )
    db_session.add(identity)
    db_session.flush()
    return identity


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
            {"name": "interests", "value": "productivity tools", "confidence": 0.85},
        ],
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
        "good Slack integration and automation capabilities.",
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
# SERVICE INTEGRATION TESTS - DRAFT FOR LEAD
# =============================================================================


class TestDraftIntroServiceForLead:
    """Tests for DraftIntroService.draft_for_lead with database."""

    @pytest.mark.asyncio
    async def test_draft_for_lead_with_profile(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should draft intro using lead and profile data."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": null,
                    "body": "Hey! I noticed your post about needing a CRM that scales with your team. As a fellow B2B SaaS person, I totally get the spreadsheet struggle. We've helped several Series A companies make that transition smoothly. Would love to chat about what you're looking for - no pressure, just happy to share what's worked for others in your situation.",
                    "tone_used": "friendly and professional",
                    "personalization_notes": ["Referenced their CRM need", "Mentioned B2B SaaS background", "Series A stage"]
                },
                "alternatives": [
                    {
                        "subject": null,
                        "body": "Hi there! Your post caught my eye - sounds like you're at that exciting growth stage where spreadsheets just don't cut it anymore. I've worked with teams your size on CRM implementations. Happy to share some quick wins that might help. Let me know if you'd like to chat!",
                        "tone_used": "casual and helpful",
                        "personalization_notes": ["Growth stage reference", "Team size acknowledgment"]
                    }
                ],
                "personalization_used": ["company size", "current pain point", "Series A stage"],
                "reasoning": "Focused on empathy and shared experience rather than hard sell"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=600,
                output_tokens=280,
                latency_ms=1200,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
        )

        assert result.success
        assert result.output is not None
        assert "CRM" in result.output.primary_draft.body
        assert len(result.output.alternatives) >= 1
        assert result.output.primary_draft.tone_used is not None

    @pytest.mark.asyncio
    async def test_draft_includes_voice_config(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should include voice config in system prompt."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hi! Alex from CRMCo here.",
                    "tone_used": "helpful",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Used persona name"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=80,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
        )

        assert result.success

        # Verify voice config was included in system prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        system_prompt = messages[0].content

        assert "Alex from CRMCo" in system_prompt
        assert "helpful and professional" in system_prompt

    @pytest.mark.asyncio
    async def test_draft_for_lead_without_author(
        self, db_session, setup_lead_without_author, setup_identity, mock_inference_client
    ):
        """Service should handle leads without author profile."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hey! Saw your post about accounting software. Happy to help point you in the right direction if you want to chat.",
                    "tone_used": "friendly",
                    "personalization_notes": ["Referenced their post topic"]
                },
                "alternatives": [],
                "personalization_used": ["post topic"],
                "reasoning": "Limited personalization without profile data"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=100,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead_without_author.id,
            identity_id=setup_identity.id,
        )

        assert result.success
        assert result.output.primary_draft.body is not None

    @pytest.mark.asyncio
    async def test_draft_nonexistent_lead(
        self, db_session, setup_identity, mock_inference_client
    ):
        """Service should handle nonexistent lead."""
        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=99999,
            identity_id=setup_identity.id,
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_draft_nonexistent_identity(
        self, db_session, setup_lead, mock_inference_client
    ):
        """Service should handle nonexistent identity."""
        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=99999,
        )

        assert not result.success
        assert "not found" in result.error.lower()


# =============================================================================
# SERVICE INTEGRATION TESTS - DRAFT FOR ACCOUNT
# =============================================================================


class TestDraftIntroServiceForAccount:
    """Tests for DraftIntroService.draft_for_account with database."""

    @pytest.mark.asyncio
    async def test_draft_for_account_with_profile(
        self, db_session, setup_account, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should draft intro for account using profile data."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hey startup_ceo! I noticed you're in the B2B SaaS space - always great to connect with fellow founders. Would love to hear more about what you're building!",
                    "tone_used": "casual and friendly",
                    "personalization_notes": ["Username", "Industry", "Role"]
                },
                "alternatives": [],
                "personalization_used": ["username", "industry", "role"],
                "reasoning": "Opening with shared founder experience"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=120,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_account(
            account_id=setup_account.id,
            identity_id=setup_identity.id,
        )

        assert result.success
        assert result.output is not None
        assert "startup_ceo" in result.output.primary_draft.body

    @pytest.mark.asyncio
    async def test_draft_for_account_nonexistent(
        self, db_session, setup_identity, mock_inference_client
    ):
        """Service should handle nonexistent account."""
        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_account(
            account_id=99999,
            identity_id=setup_identity.id,
        )

        assert not result.success
        assert "not found" in result.error.lower()


# =============================================================================
# CUSTOM INSTRUCTIONS TESTS
# =============================================================================


class TestDraftIntroWithCustomInstructions:
    """Tests for draft intro with custom instructions."""

    @pytest.mark.asyncio
    async def test_draft_with_custom_instructions(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should include custom instructions in prompt."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hey! Quick question about your CRM search - are you looking for something with strong API integrations?",
                    "tone_used": "direct and curious",
                    "personalization_notes": ["Followed instruction to lead with a question"]
                },
                "alternatives": [],
                "personalization_used": ["CRM search context"],
                "reasoning": "Following custom instruction to start with a question"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=100,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
            custom_instructions="Start with a question to spark engagement.",
        )

        assert result.success

        # Verify custom instructions in prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        user_message = messages[1].content

        assert "question" in user_message.lower()

    @pytest.mark.asyncio
    async def test_draft_with_product_context(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should include product context in prompt."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hey! I saw your post about CRM needs. We specialize in Slack integrations which seemed to be on your list. Our enterprise plan might be a good fit for your team size.",
                    "tone_used": "helpful",
                    "personalization_notes": ["Mentioned Slack integration", "Enterprise plan for team size"]
                },
                "alternatives": [],
                "personalization_used": ["Slack integration need", "team size"],
                "reasoning": "Connected product features to stated needs"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=550,
                output_tokens=120,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        product_context = {
            "product_name": "CRMCo",
            "key_features": ["Slack integration", "automation", "reporting"],
            "pricing_tiers": ["starter", "professional", "enterprise"],
        }

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
            product_context=product_context,
        )

        assert result.success

        # Verify product context in prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        user_message = messages[1].content

        assert "CRMCo" in user_message
        assert "Slack" in user_message


# =============================================================================
# FULL FLOW TESTS
# =============================================================================


class TestDraftIntroFullFlow:
    """End-to-end tests for draft intro flow."""

    @pytest.mark.asyncio
    async def test_full_draft_flow(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Test complete flow from lead to draft."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": null,
                    "body": "Hey there! I came across your post in r/startups about looking for a CRM. The spreadsheet struggle is real - we've helped several B2B SaaS companies at your stage make that transition. Would be happy to share what's worked for others if you're interested!",
                    "tone_used": "friendly and empathetic",
                    "personalization_notes": ["Referenced their subreddit", "Acknowledged pain point", "Mentioned similar companies helped"]
                },
                "alternatives": [
                    {
                        "subject": null,
                        "body": "Hi! Your CRM post resonated with me - 25-person teams definitely outgrow spreadsheets fast. Quick question: is the Slack integration the must-have, or is automation the bigger priority? Might help narrow down options.",
                        "tone_used": "helpful and inquisitive",
                        "personalization_notes": ["Specific team size", "Mentioned their requirements"]
                    }
                ],
                "personalization_used": ["subreddit source", "team size", "pain point", "specific requirements"],
                "reasoning": "Led with empathy, showed relevance without being salesy, gave easy CTA"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=700,
                output_tokens=300,
                latency_ms=1500,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
        )

        # Verify success
        assert result.success
        assert result.output is not None

        # Verify primary draft
        primary = result.output.primary_draft
        assert primary.body is not None
        assert len(primary.body) > 50
        assert primary.tone_used is not None
        assert len(primary.personalization_notes) >= 1

        # Verify alternatives
        assert len(result.output.alternatives) >= 1
        alt = result.output.alternatives[0]
        assert alt.body is not None
        assert alt.body != primary.body

        # Verify reasoning
        assert result.output.reasoning is not None

        # Verify model info
        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"

    @pytest.mark.asyncio
    async def test_draft_with_minimal_voice_config(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity_minimal, mock_inference_client
    ):
        """Test drafting with minimal/empty voice config."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Hi! Saw your post about CRM needs. Happy to chat if you'd like some recommendations.",
                    "tone_used": "neutral",
                    "personalization_notes": ["Referenced post topic"]
                },
                "alternatives": [],
                "personalization_used": ["post topic"],
                "reasoning": "Simple and direct without specific persona"
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

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity_minimal.id,
        )

        assert result.success
        assert result.output.primary_draft.body is not None


# =============================================================================
# MODEL INFO TESTS
# =============================================================================


class TestDraftIntroModelInfo:
    """Tests for model info recording."""

    @pytest.mark.asyncio
    async def test_returns_model_info(
        self, db_session, setup_lead, setup_profile_snapshot, setup_identity, mock_inference_client
    ):
        """Service should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "body": "Test message",
                    "tone_used": "neutral",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Test"
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=50,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        service = DraftIntroService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.draft_for_lead(
            lead_id=setup_lead.id,
            identity_id=setup_identity.id,
        )

        assert result.success
        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"
        assert result.model_info["provider"] == "llama.cpp"
        assert "input_tokens" in result.model_info
        assert "output_tokens" in result.model_info
        assert "latency_ms" in result.model_info
