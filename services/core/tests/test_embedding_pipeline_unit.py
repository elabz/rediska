"""Embedding pipeline: per-type text, hash-aware embedding, merged comments.

Fake Elasticsearch and embeddings clients; synthetic `test_` data only.
"""

from datetime import datetime, timedelta

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
)
from rediska_core.domain.services.embedding import EmbeddingService
from rediska_core.domain.services.embedding_text import PREP_VERSION, text_hash
from rediska_core.domain.services.indexing import (
    EMBEDDABLE_DOC_TYPES,
    SUPPORTED_DOC_TYPES,
    IndexingService,
)

NOW = datetime(2026, 9, 19, 12, 0, 0)
MODEL = "test-embed-model"


class FakeES:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.updates: list[tuple[str, dict]] = []

    def index_document(self, index, doc_id, document):
        self.docs[doc_id] = dict(document)
        return True

    def get_document(self, index, doc_id):
        return self.docs.get(doc_id)

    def update_document(self, index, doc_id, updates):
        self.updates.append((doc_id, updates))
        self.docs.setdefault(doc_id, {}).update(updates)
        return True

    def delete_document(self, index, doc_id):
        return self.docs.pop(doc_id, None) is not None


class FakeEmbeddings:
    def __init__(self, dims=4):
        self.calls: list[str] = []
        self.dims = dims

    def embed_document(self, text):
        self.calls.append(text)
        return [1.0] + [0.0] * (self.dims - 1)


@pytest.fixture
def world(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    account = ExternalAccount(provider_id="reddit", external_username="test_author")
    db_session.add(account)
    db_session.flush()
    return account


def service(db_session, es=None, embeddings=None):
    svc = EmbeddingService(
        db=db_session,
        embeddings_url="http://embeddings.invalid",
        embeddings_model=MODEL,
        es_url="http://es.invalid",
    )
    svc._es_client = es or FakeES()  # type: ignore[assignment]
    svc._embeddings_client = embeddings or FakeEmbeddings()  # type: ignore[assignment]
    return svc


def indexing(db_session, es):
    svc = IndexingService(db=db_session, es_url="http://es.invalid")
    svc._es_client = es  # type: ignore[assignment]
    return svc


class TestDocumentTypes:
    def test_embeddable_types_exclude_conversations(self):
        assert "conversation" in SUPPORTED_DOC_TYPES
        assert "conversation" not in EMBEDDABLE_DOC_TYPES
        assert {"lead_post", "scout_post", "account_comments"} <= EMBEDDABLE_DOC_TYPES

    def test_scout_post_document(self, db_session, world):
        watch = ScoutWatch(provider_id="reddit", source_location="r/test", search_query="x")
        db_session.add(watch)
        db_session.flush()
        post = ScoutWatchPost(
            watch_id=watch.id, external_post_id="p1", post_title="Title",
            post_body="Body text", post_author="Test_Author", first_seen_at=NOW,
            analysis_status="analyzed", analysis_recommendation="needs_review",
        )
        db_session.add(post)
        db_session.flush()

        doc = indexing(db_session, FakeES()).scout_post_to_document(post)
        assert doc["doc_type"] == "scout_post" and doc["entity_id"] == post.id
        assert doc["author_username"] == "test_author"  # lower-cased for filters
        assert doc["location"] == "r/test" and doc["content"] == "Body text"

    def test_unanalysed_scout_post_is_not_indexed(self, db_session, world):
        watch = ScoutWatch(provider_id="reddit", source_location="r/test", search_query="x")
        db_session.add(watch)
        db_session.flush()
        post = ScoutWatchPost(
            watch_id=watch.id, external_post_id="p2", post_body="Body",
            first_seen_at=NOW, analysis_status="pending",
        )
        db_session.add(post)
        db_session.flush()
        es = FakeES()
        assert indexing(db_session, es).upsert_content("scout_post", post.id) is False
        assert es.docs == {}

    def test_lead_and_profile_documents_carry_author_and_location(self, db_session, world):
        lead = LeadPost(
            provider_id="reddit", source_location="r/test", external_post_id="p3",
            post_url="https://x/p3", author_account_id=world.id, title="T", body_text="B",
            status="saved",
        )
        item = ProfileItem(
            account_id=world.id, item_type="post", external_item_id="i1",
            text_content="Item body", link_title="Item title", subreddit="test",
        )
        snapshot = ProfileSnapshot(account_id=world.id, fetched_at=NOW, summary_text="Summary")
        db_session.add_all([lead, item, snapshot])
        db_session.flush()

        svc = indexing(db_session, FakeES())
        assert svc.lead_post_to_document(lead)["author_username"] == "test_author"
        assert svc.lead_post_to_document(lead)["location"] == "r/test"
        assert svc.profile_item_to_document(item)["location"] == "r/test"
        assert svc.profile_snapshot_to_document(snapshot)["author_username"] == "test_author"


class TestAccountComments:
    def _comments(self, db, account, n, text="a comment about things", sub="test"):
        for i in range(n):
            db.add(ProfileItem(
                account_id=account.id, item_type="comment", external_item_id=f"c{i}",
                text_content=f"{text} {i}", subreddit=sub,
                item_created_at=NOW - timedelta(hours=i),
            ))
        db.flush()

    def test_merges_newest_first_with_community_prefix(self, db_session, world):
        self._comments(db_session, world, 5)
        doc = indexing(db_session, FakeES()).account_comments_to_document(world.id)
        assert doc is not None
        assert doc["doc_type"] == "account_comments" and doc["entity_id"] == world.id
        lines = doc["content"].split("\n")
        assert lines[0].startswith("r/test: ") and lines[0].endswith(" 0")  # newest first
        assert len(lines) == 5 and doc["metadata"]["comment_count"] == 5
        assert doc["author_username"] == "test_author"

    def test_stops_at_the_input_budget(self, db_session, world):
        self._comments(db_session, world, 300, text="x" * 100)
        doc = indexing(db_session, FakeES()).account_comments_to_document(world.id)
        assert doc is not None
        from rediska_core.config import get_settings

        assert len(doc["content"]) <= get_settings().embed_max_chars
        assert doc["metadata"]["comment_count"] < 300  # only the recent ones

    def test_no_comments_means_no_document(self, db_session, world):
        assert indexing(db_session, FakeES()).account_comments_to_document(world.id) is None

    def test_upsert_removes_a_stale_document_when_comments_are_gone(self, db_session, world):
        es = FakeES()
        es.docs[f"account_comments:{world.id}"] = {"doc_type": "account_comments"}
        assert indexing(db_session, es).upsert_content("account_comments", world.id) is False
        assert es.docs == {}

    def test_individual_comments_stay_text_only(self, db_session, world):
        self._comments(db_session, world, 2)
        item = db_session.query(ProfileItem).first()
        doc = indexing(db_session, FakeES()).profile_item_to_document(item)
        assert doc["doc_type"] == "profile_item" and "embedding" not in doc


class TestTextForEntity:
    def test_unknown_type_and_missing_row_return_none(self, db_session, world):
        svc = service(db_session)
        assert svc.text_for_entity("lead_post", 999) is None
        assert svc.text_for_entity("unknown_type", 1) is None

    def test_lead_post_text_is_title_then_body(self, db_session, world):
        lead = LeadPost(
            provider_id="reddit", source_location="r/test", external_post_id="p4",
            post_url="https://x/p4", title="A title", body_text="A body", status="saved",
        )
        db_session.add(lead)
        db_session.flush()
        assert service(db_session).text_for_entity("lead_post", lead.id) == "A title\n\nA body"

    def test_scout_post_only_when_analysed(self, db_session, world):
        watch = ScoutWatch(provider_id="reddit", source_location="r/test", search_query="x")
        db_session.add(watch)
        db_session.flush()
        post = ScoutWatchPost(
            watch_id=watch.id, external_post_id="p5", post_title="T", post_body="B",
            first_seen_at=NOW, analysis_status="pending",
        )
        db_session.add(post)
        db_session.flush()
        svc = service(db_session)
        assert svc.text_for_entity("scout_post", post.id) is None
        post.analysis_status = "analyzed"
        db_session.flush()
        assert svc.text_for_entity("scout_post", post.id) == "T\n\nB"

    def test_account_comments_text(self, db_session, world):
        db_session.add(ProfileItem(
            account_id=world.id, item_type="comment", external_item_id="c1",
            text_content="hello there", subreddit="test", item_created_at=NOW,
        ))
        db_session.flush()
        assert service(db_session).text_for_entity("account_comments", world.id) == (
            "r/test: hello there"
        )


class TestEmbedEntity:
    def _lead(self, db, **kw):
        lead = LeadPost(
            provider_id="reddit", source_location="r/test", external_post_id="p6",
            post_url="https://x/p6", title="T", body_text="Body", status="saved", **kw
        )
        db.add(lead)
        db.flush()
        return lead

    def test_embeds_and_stamps_provenance(self, db_session, world):
        lead = self._lead(db_session)
        es, emb = FakeES(), FakeEmbeddings()
        result = service(db_session, es, emb).embed_entity("lead_post", lead.id)

        assert result["status"] == "embedded" and result["dimensions"] == 4
        doc_id, updates = es.updates[0]
        assert doc_id == f"lead_post:{lead.id}"
        assert updates["embedding_model"] == MODEL
        assert updates["embedding_prep"] == PREP_VERSION
        assert updates["embedding_text_hash"] == text_hash("T\n\nBody")
        assert updates["embedded_at"] and updates["embedding"]

    def test_unchanged_text_is_not_re_embedded(self, db_session, world):
        lead = self._lead(db_session)
        es, emb = FakeES(), FakeEmbeddings()
        svc = service(db_session, es, emb)
        svc.embed_entity("lead_post", lead.id)
        again = svc.embed_entity("lead_post", lead.id)

        assert again["status"] == "skipped" and "Unchanged" in again["reason"]
        assert len(emb.calls) == 1

    def test_changed_text_is_re_embedded(self, db_session, world):
        lead = self._lead(db_session)
        es, emb = FakeES(), FakeEmbeddings()
        svc = service(db_session, es, emb)
        svc.embed_entity("lead_post", lead.id)
        lead.body_text = "Something else entirely"
        db_session.flush()
        assert svc.embed_entity("lead_post", lead.id)["status"] == "embedded"
        assert len(emb.calls) == 2

    def test_force_re_embeds(self, db_session, world):
        lead = self._lead(db_session)
        es, emb = FakeES(), FakeEmbeddings()
        svc = service(db_session, es, emb)
        svc.embed_entity("lead_post", lead.id)
        assert svc.embed_entity("lead_post", lead.id, force=True)["status"] == "embedded"
        assert len(emb.calls) == 2

    def test_another_model_re_embeds(self, db_session, world):
        lead = self._lead(db_session)
        es, emb = FakeES(), FakeEmbeddings()
        service(db_session, es, emb).embed_entity("lead_post", lead.id)
        other = service(db_session, es, emb)
        other._embeddings_model = "different-model"
        assert other.embed_entity("lead_post", lead.id)["status"] == "embedded"

    def test_no_text_is_skipped_without_calling_the_endpoint(self, db_session, world):
        lead = LeadPost(
            provider_id="reddit", source_location="r/test", external_post_id="p7",
            post_url="https://x/p7", status="saved",
        )
        db_session.add(lead)
        db_session.flush()
        emb = FakeEmbeddings()
        result = service(db_session, FakeES(), emb).embed_entity("lead_post", lead.id)
        assert result["status"] == "skipped" and emb.calls == []

    def test_endpoint_failure_is_reported_not_raised(self, db_session, world):
        from rediska_core.infrastructure.embeddings import EmbeddingsError

        class Broken(FakeEmbeddings):
            def embed_document(self, text):
                raise EmbeddingsError("endpoint down")

        lead = self._lead(db_session)
        result = service(db_session, FakeES(), Broken()).embed_entity("lead_post", lead.id)
        assert result["success"] is False and "endpoint down" in result["error"]
