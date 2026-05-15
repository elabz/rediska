"""Integration tests for GET /conversations/search.

Focused on the `matching_message_id` field — see OpenSpec change
`inbox-search-jump-to-match`.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import LocalUser

from .factories import create_conversation, create_message


@pytest.fixture
def mock_user():
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_user"
    return user


@pytest.fixture
async def auth_client(test_app, db_session, mock_user):
    test_app.dependency_overrides[get_current_user] = lambda: mock_user
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


def _mock_search_service_returning(exact_hits, fuzzy_hits=None):
    """Build a MagicMock that mimics SearchService two-pass behavior."""
    instance = MagicMock()
    fuzzy_hits = fuzzy_hits or []

    def text_search(*args, fuzziness=None, **kwargs):
        if fuzziness is None:
            return {"total": len(exact_hits), "hits": exact_hits, "max_score": None}
        return {"total": len(fuzzy_hits), "hits": fuzzy_hits, "max_score": None}

    instance.text_search.side_effect = text_search
    return instance


class TestConversationSearchMatchingMessageId:
    """OpenSpec change: inbox-search-jump-to-match."""

    @pytest.mark.asyncio
    async def test_matching_message_id_populated_from_source_entity_id(
        self, auth_client, db_session
    ):
        """When the ES hit source has entity_id, it surfaces as matching_message_id."""
        conv = create_conversation(db_session)
        msg = create_message(db_session, conversation=conv, body_text="hello world")
        db_session.commit()

        fake_hits = [
            {
                "id": f"message:{msg.id}",
                "score": 1.0,
                "source": {
                    "doc_type": "message",
                    "entity_id": msg.id,
                    "conversation_id": conv.id,
                    "content": "hello world",
                },
            }
        ]

        mock_instance = _mock_search_service_returning(fake_hits)
        with patch(
            "rediska_core.domain.services.search.SearchService",
            return_value=mock_instance,
        ):
            resp = await auth_client.get("/conversations/search", params={"q": "hello"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1
        hit = data["conversations"][0]
        assert hit["id"] == conv.id
        assert hit["matching_message_id"] == msg.id

    @pytest.mark.asyncio
    async def test_matching_message_id_none_when_source_lacks_field(
        self, auth_client, db_session
    ):
        """If the ES source lacks entity_id and the doc id is unparseable, the field is None."""
        conv = create_conversation(db_session)
        # Ensure a message exists so the conversation is "real"
        create_message(db_session, conversation=conv, body_text="anything")
        db_session.commit()

        # Hit with no entity_id in source and a non-message-prefixed id
        fake_hits = [
            {
                "id": "weird-doc-id",
                "score": 1.0,
                "source": {
                    "doc_type": "message",
                    "conversation_id": conv.id,
                    "content": "hello",
                    # entity_id deliberately missing
                },
            }
        ]
        mock_instance = _mock_search_service_returning(fake_hits)
        with patch(
            "rediska_core.domain.services.search.SearchService",
            return_value=mock_instance,
        ):
            resp = await auth_client.get("/conversations/search", params={"q": "hello"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        hit = data["conversations"][0]
        assert hit["id"] == conv.id
        assert hit["matching_message_id"] is None

    @pytest.mark.asyncio
    async def test_matching_message_id_falls_back_to_parsing_doc_id(
        self, auth_client, db_session
    ):
        """If entity_id is missing but doc id is `message:<n>`, parse it."""
        conv = create_conversation(db_session)
        msg = create_message(db_session, conversation=conv, body_text="alpha")
        db_session.commit()

        fake_hits = [
            {
                "id": f"message:{msg.id}",
                "score": 1.0,
                "source": {
                    "doc_type": "message",
                    "conversation_id": conv.id,
                    "content": "alpha",
                    # entity_id deliberately missing
                },
            }
        ]
        mock_instance = _mock_search_service_returning(fake_hits)
        with patch(
            "rediska_core.domain.services.search.SearchService",
            return_value=mock_instance,
        ):
            resp = await auth_client.get("/conversations/search", params={"q": "alpha"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        hit = data["conversations"][0]
        assert hit["matching_message_id"] == msg.id
