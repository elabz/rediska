"""Integration tests for manual promotion of a scout watch post to leads.

Manual add-to-leads is an explicit user action: it overrides an `ignored`
author verdict but never the do-not-contact list.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    DoNotContact,
    LocalUser,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_user():
    """Create a mock user for authentication."""
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_user"
    return user


@pytest.fixture
async def auth_client(test_app, db_session, mock_user):
    """Create an authenticated client with auth dependency override."""
    test_app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.commit()
    return provider


@pytest.fixture
def watch_with_post(db_session, setup_provider):
    """Set up a watch with one recorded post."""
    watch = ScoutWatch(
        provider_id="reddit",
        source_location="r/watched",
        sort_by="new",
        time_filter="day",
        auto_analyze=True,
        min_confidence=0.7,
        is_active=True,
    )
    db_session.add(watch)
    db_session.flush()

    post = ScoutWatchPost(
        watch_id=watch.id,
        external_post_id="manual_post",
        post_title="A manually promoted post",
        post_author="manual_author",
        first_seen_at=datetime.now(timezone.utc),
        analysis_status="analyzed",
    )
    db_session.add(post)
    db_session.commit()
    return watch, post


# =============================================================================
# TESTS
# =============================================================================


class TestAddPostToLeadsVerdicts:
    """Tests for standing verdicts on the manual promotion path."""

    @pytest.mark.asyncio
    async def test_do_not_contact_author_is_blocked(
        self, auth_client, db_session, watch_with_post
    ):
        """Do-not-contact is a hard boundary even for an explicit user action."""
        watch, post = watch_with_post
        db_session.add(
            DoNotContact(provider_id="reddit", external_username="manual_author")
        )
        db_session.commit()

        response = await auth_client.post(
            f"/scout-watches/{watch.id}/posts/{post.id}/add-to-leads"
        )

        assert response.status_code == 403
        assert "do-not-contact" in response.json()["detail"]
        db_session.refresh(post)
        assert post.lead_id is None

    @pytest.mark.asyncio
    async def test_ignored_author_verdict_is_overridden(
        self, auth_client, db_session, watch_with_post
    ):
        """An explicit user action outranks a previously ignored lead."""
        from rediska_core.domain.services.leads import LeadsService

        watch, post = watch_with_post

        leads_service = LeadsService(db_session)
        old = leads_service.save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="previously_ignored",
            post_url="https://reddit.com/comments/previously_ignored",
            author_username="manual_author",
        )
        leads_service.update_status(old.id, "ignored")
        db_session.commit()

        response = await auth_client.post(
            f"/scout-watches/{watch.id}/posts/{post.id}/add-to-leads"
        )

        assert response.status_code == 200
        lead_id = response.json()["lead_id"]
        assert lead_id != old.id

    @pytest.mark.asyncio
    async def test_promotion_attaches_to_an_active_author_lead(
        self, auth_client, db_session, watch_with_post
    ):
        """Manual promotion joins the author's active lead instead of duplicating."""
        from rediska_core.domain.services.leads import LeadsService

        watch, post = watch_with_post

        active = LeadsService(db_session).save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="already_active",
            post_url="https://reddit.com/comments/already_active",
            author_username="manual_author",
        )
        db_session.commit()

        response = await auth_client.post(
            f"/scout-watches/{watch.id}/posts/{post.id}/add-to-leads"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["lead_id"] == active.id
        # The promotion created nothing; saying "added to leads" would send the
        # user looking for a new entry that does not exist.
        assert body["attached"] is True
        assert body["lead_author"] == "manual_author"
        assert "Attached to existing" in body["message"]

    @pytest.mark.asyncio
    async def test_author_without_verdict_is_promoted(
        self, auth_client, db_session, watch_with_post
    ):
        """A clean author promotes normally."""
        watch, post = watch_with_post

        response = await auth_client.post(
            f"/scout-watches/{watch.id}/posts/{post.id}/add-to-leads"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["lead_id"] is not None
        assert body["attached"] is False
        assert "added to leads" in body["message"]
