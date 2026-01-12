"""Integration tests for profile summary agent.

Tests the full flow:
1. Loading account data from database
2. Running the profile summary agent
3. Saving snapshot to database
4. Verifying stored data
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    ProfileItem,
    ProfileSnapshot,
    Provider,
)
from rediska_core.domain.services.agent import VoiceConfig
from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)
from rediska_core.domain.services.profile_summary import (
    ProfileSummaryAgent,
    ProfileSummaryInput,
    ProfileSummaryService,
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
    """Set up an external account for testing."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="tech_founder",
        external_user_id="t2_tech",
        analysis_state="not_analyzed",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def setup_profile_items(db_session, setup_account):
    """Set up profile items for the account."""
    items = []

    # Post 1 - startup announcement
    item1 = ProfileItem(
        account_id=setup_account.id,
        item_type="post",
        external_item_id="post_startup",
        text_content="Excited to announce our AI startup just raised $2M seed round! "
        "We're building tools for developers to ship faster.",
        item_created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    db_session.add(item1)
    items.append(item1)

    # Post 2 - looking for team
    item2 = ProfileItem(
        account_id=setup_account.id,
        item_type="post",
        external_item_id="post_hiring",
        text_content="Looking for a senior backend engineer to join our team. "
        "Experience with Python and distributed systems preferred.",
        item_created_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
    )
    db_session.add(item2)
    items.append(item2)

    # Comment 1 - technical discussion
    item3 = ProfileItem(
        account_id=setup_account.id,
        item_type="comment",
        external_item_id="comment_tech",
        text_content="We've been using FastAPI in production for 2 years now. "
        "The async support and automatic docs are game changers.",
        item_created_at=datetime(2024, 1, 18, tzinfo=timezone.utc),
    )
    db_session.add(item3)
    items.append(item3)

    # Comment 2 - advice
    item4 = ProfileItem(
        account_id=setup_account.id,
        item_type="comment",
        external_item_id="comment_advice",
        text_content="For early-stage startups, focus on customer conversations first. "
        "We spent 3 months just talking to potential users before writing code.",
        item_created_at=datetime(2024, 1, 22, tzinfo=timezone.utc),
    )
    db_session.add(item4)
    items.append(item4)

    db_session.flush()
    return items


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


# =============================================================================
# SERVICE INTEGRATION TESTS
# =============================================================================


class TestProfileSummaryServiceIntegration:
    """Tests for ProfileSummaryService with database."""

    @pytest.mark.asyncio
    async def test_summarize_account_creates_snapshot(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Service should create a profile snapshot in the database."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Tech startup founder focused on developer tools. Recently raised $2M seed round and actively hiring.",
                "signals": [
                    {"name": "role", "value": "founder", "confidence": 0.95},
                    {"name": "industry", "value": "developer tools", "confidence": 0.9},
                    {"name": "stage", "value": "seed", "confidence": 0.85},
                    {"name": "tech_stack", "value": ["Python", "FastAPI"], "confidence": 0.8}
                ],
                "risk_flags": [],
                "citations": [
                    {"item_id": 1, "quote": "AI startup just raised $2M seed round", "relevance": "funding stage"}
                ]
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=150,
                latency_ms=800,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(setup_account.id)

        assert result.success
        assert result.output is not None

        # Verify snapshot was created
        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=setup_account.id)
            .first()
        )
        assert snapshot is not None
        assert "founder" in snapshot.summary_text.lower()
        assert snapshot.signals_json is not None
        assert snapshot.model_info_json is not None

    @pytest.mark.asyncio
    async def test_summarize_account_stores_signals(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Service should store extracted signals in the snapshot."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Active startup founder.",
                "signals": [
                    {"name": "interests", "value": ["AI", "Python", "startups"], "confidence": 0.9},
                    {"name": "hiring", "value": true, "confidence": 0.95}
                ],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=80,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(setup_account.id)

        assert result.success

        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=setup_account.id)
            .first()
        )

        # Verify signals were stored
        signals = snapshot.signals_json
        assert isinstance(signals, list)
        assert len(signals) >= 2

        signal_names = [s["name"] for s in signals]
        assert "interests" in signal_names

    @pytest.mark.asyncio
    async def test_summarize_account_stores_risk_flags(
        self, db_session, setup_provider, mock_inference_client
    ):
        """Service should store risk flags in the snapshot."""
        # Create suspicious account
        suspicious_account = ExternalAccount(
            provider_id="reddit",
            external_username="spam_account",
            external_user_id="t2_spam",
        )
        db_session.add(suspicious_account)
        db_session.flush()

        # Add suspicious content
        item = ProfileItem(
            account_id=suspicious_account.id,
            item_type="post",
            external_item_id="spam_post",
            text_content="BUY NOW! AMAZING DEAL! LIMITED TIME! CLICK HERE!",
            item_created_at=datetime.now(timezone.utc),
        )
        db_session.add(item)
        db_session.flush()

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Account showing spam-like behavior patterns.",
                "signals": [],
                "risk_flags": [
                    {
                        "type": "spam_behavior",
                        "severity": "high",
                        "description": "Promotional language with urgency tactics",
                        "evidence_item_ids": [1]
                    }
                ],
                "citations": []
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

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(suspicious_account.id)

        assert result.success

        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=suspicious_account.id)
            .first()
        )

        # Verify risk flags were stored
        risk_flags = snapshot.risk_flags_json
        assert isinstance(risk_flags, list)
        assert len(risk_flags) >= 1
        assert risk_flags[0]["type"] == "spam_behavior"

    @pytest.mark.asyncio
    async def test_summarize_account_stores_model_info(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Service should store model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Test summary.",
                "signals": [],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=350,
                output_tokens=50,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(setup_account.id)

        assert result.success

        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=setup_account.id)
            .first()
        )

        # Verify model info was stored
        model_info = snapshot.model_info_json
        assert model_info["model_name"] == "llama-3.2-8b"
        assert model_info["input_tokens"] == 350
        assert model_info["output_tokens"] == 50
        assert model_info["latency_ms"] == 600

    @pytest.mark.asyncio
    async def test_summarize_nonexistent_account(
        self, db_session, mock_inference_client
    ):
        """Service should handle nonexistent account gracefully."""
        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(99999)

        assert not result.success
        assert "not found" in result.error.lower()


# =============================================================================
# FULL FLOW TESTS
# =============================================================================


class TestProfileSummaryFullFlow:
    """End-to-end tests for profile summary flow."""

    @pytest.mark.asyncio
    async def test_full_summary_flow(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Test complete flow from account to stored snapshot."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Experienced tech startup founder building AI-powered developer tools. Recently raised seed funding and actively scaling the team. Strong technical background with Python and FastAPI expertise.",
                "signals": [
                    {"name": "role", "value": "founder/CEO", "confidence": 0.95},
                    {"name": "industry", "value": "developer tools", "confidence": 0.9},
                    {"name": "funding_stage", "value": "seed", "confidence": 0.85},
                    {"name": "tech_stack", "value": ["Python", "FastAPI"], "confidence": 0.9},
                    {"name": "team_size", "value": "growing", "confidence": 0.7},
                    {"name": "focus_areas", "value": ["AI", "developer experience"], "confidence": 0.85}
                ],
                "risk_flags": [],
                "citations": [
                    {"item_id": 1, "quote": "AI startup just raised $2M seed round", "relevance": "funding confirmation"},
                    {"item_id": 2, "quote": "Looking for a senior backend engineer", "relevance": "hiring activity"},
                    {"item_id": 3, "quote": "using FastAPI in production for 2 years", "relevance": "technical expertise"}
                ]
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=200,
                latency_ms=1000,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        # Run summary
        result = await service.summarize_account(setup_account.id)

        # Verify success
        assert result.success
        assert result.output is not None

        # Verify output structure
        assert "founder" in result.output.summary.lower()
        assert len(result.output.signals) >= 4
        assert len(result.output.citations) >= 2

        # Verify database storage
        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=setup_account.id)
            .first()
        )

        assert snapshot is not None
        assert snapshot.summary_text is not None
        assert len(snapshot.signals_json) >= 4
        assert snapshot.model_info_json["model_name"] == "llama-3.2-8b"

    @pytest.mark.asyncio
    async def test_summary_with_voice_config(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Test summary generation with voice configuration."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "A promising lead - tech founder with recent funding.",
                "signals": [{"name": "lead_quality", "value": "high", "confidence": 0.9}],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=60,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        voice_config = VoiceConfig(
            system_prompt="You are evaluating leads for a B2B SaaS product.",
            tone="professional",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(
            setup_account.id,
            voice_config=voice_config,
        )

        assert result.success

        # Verify voice config was passed to agent
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        system_prompt = messages[0].content

        # Should include voice config additions
        assert "B2B SaaS" in system_prompt or "professional" in system_prompt.lower()


# =============================================================================
# ACCOUNT WITH NO ITEMS TESTS
# =============================================================================


class TestProfileSummaryEmptyProfile:
    """Tests for handling accounts with no profile items."""

    @pytest.mark.asyncio
    async def test_summary_for_account_with_no_items(
        self, db_session, setup_account, mock_inference_client
    ):
        """Service should handle accounts with no profile items."""
        # setup_account exists but has no items

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "New account with no public activity yet.",
                "signals": [
                    {"name": "activity_level", "value": "none", "confidence": 1.0}
                ],
                "risk_flags": [
                    {"type": "new_account", "severity": "low", "description": "No public content available"}
                ],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=80,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        result = await service.summarize_account(setup_account.id)

        assert result.success
        assert "no" in result.output.summary.lower() or "new" in result.output.summary.lower()

        # Should flag as new account
        flag_types = [f.type for f in result.output.risk_flags]
        assert "new_account" in flag_types


# =============================================================================
# MULTIPLE SNAPSHOTS TESTS
# =============================================================================


class TestMultipleSnapshots:
    """Tests for handling multiple snapshots over time."""

    @pytest.mark.asyncio
    async def test_creates_new_snapshot_each_time(
        self, db_session, setup_account, setup_profile_items, mock_inference_client
    ):
        """Each summarize call should create a new snapshot."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Test summary.",
                "signals": [],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=30,
                latency_ms=200,
            ),
            finish_reason="stop",
        )

        service = ProfileSummaryService(
            db=db_session,
            inference_client=mock_inference_client,
        )

        # Run summary twice
        await service.summarize_account(setup_account.id)
        await service.summarize_account(setup_account.id)

        # Should have 2 snapshots
        snapshots = (
            db_session.query(ProfileSnapshot)
            .filter_by(account_id=setup_account.id)
            .all()
        )
        assert len(snapshots) == 2
