"""Similarity service: neighbours, filters, enrichment, honest degradation.

Fake Elasticsearch and embeddings clients; synthetic `test_` data only.
"""

from datetime import datetime

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    Provider,
)
from rediska_core.domain.services.similarity import (
    METHOD_TEXT,
    METHOD_VECTOR,
    SimilarityService,
    SimilarityError,
    SourceNotFound,
)
from rediska_core.infrastructure.elasticsearch import UnsupportedFilterError

NOW = datetime(2026, 9, 20, 12, 0, 0)
MODEL = "test-embed-model"


def hit(doc_id: str, score: float, **source):
    """An ES hit; score 0.9 means cosine 0.8 (ES reports (1 + cos) / 2)."""
    return {"id": doc_id, "score": score, "source": {**source}}


class FakeES:
    """Records the query it was asked to run and replays canned hits."""

    def __init__(self, docs=None, knn_hits=None, text_hits=None, knn_error=None):
        self.docs = docs or {}
        self.knn_hits = knn_hits or []
        self.text_hits = text_hits or []
        self.knn_error = knn_error
        self.knn_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def get_document(self, index, doc_id):
        return self.docs.get(doc_id)

    def knn_search(self, index, vector, k, num_candidates, filters=None,
                   must_not=None, ranges=None):
        self.knn_calls.append(
            {"k": k, "filters": filters or {}, "must_not": must_not or {},
             "ranges": ranges or {}}
        )
        if self.knn_error:
            return {"total": 0, "hits": [], "error": self.knn_error}
        return {"total": len(self.knn_hits), "hits": list(self.knn_hits)}

    def search(self, index, query, filters=None, must_not=None, ranges=None,
               size=10, **kwargs):
        self.search_calls.append(
            {"query": query, "filters": filters or {}, "must_not": must_not or {},
             "ranges": ranges or {}}
        )
        return {"total": len(self.text_hits), "hits": list(self.text_hits)}


_UNSET = object()


class FakeEmbeddings:
    def __init__(self, vector=_UNSET, error=None):
        # `vector=None` means "this text produced no vector", which is a case
        # the service has to handle, so it must survive the default.
        self.vector = [1.0, 0.0, 0.0, 0.0] if vector is _UNSET else vector
        self.error = error
        self.calls: list[str] = []

    def embed_document(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.vector


def service(db_session, es, embeddings=None):
    svc = SimilarityService(
        db=db_session,
        es_url="http://es.invalid",
        embeddings_url="http://embeddings.invalid",
        embeddings_model=MODEL,
    )
    svc._es_client = es  # type: ignore[assignment]
    svc._embeddings_client = embeddings or FakeEmbeddings()  # type: ignore[assignment]
    return svc


SOURCE_DOC = {
    "doc_type": "lead_post",
    "entity_id": 1,
    "title": "test_title",
    "content": "looking for a long walk and a longer conversation",
    "author_username": "test_author",
    "location": "test_sub",
}


@pytest.fixture
def world(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    account = ExternalAccount(provider_id="reddit", external_username="test_author")
    db_session.add(account)
    db_session.flush()
    return account


class TestByReference:
    def test_returns_neighbours_without_the_source(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            knn_hits=[
                hit("lead_post:1", 1.0, doc_type="lead_post", content="itself"),
                hit("lead_post:2", 0.975, doc_type="lead_post", content="test_other"),
            ],
        )
        found = service(db_session, es).find_similar(doc_type="lead_post", entity_id=1)

        assert found["method"] == METHOD_VECTOR
        assert [r["id"] for r in found["results"]] == ["lead_post:2"]
        assert found["results"][0]["similarity"] == pytest.approx(0.95)

    def test_missing_source_is_not_an_empty_answer(self, db_session):
        es = FakeES(docs={})
        with pytest.raises(SourceNotFound):
            service(db_session, es).find_similar(doc_type="lead_post", entity_id=404)

    def test_below_min_score_is_dropped(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            knn_hits=[
                hit("lead_post:2", 0.9, doc_type="lead_post"),   # cosine 0.80
                hit("lead_post:3", 0.85, doc_type="lead_post"),  # cosine 0.70
            ],
        )
        found = service(db_session, es).find_similar(doc_type="lead_post", entity_id=1)

        assert [r["id"] for r in found["results"]] == ["lead_post:2"]

    def test_neither_reference_nor_text_is_refused(self, db_session):
        with pytest.raises(SimilarityError):
            service(db_session, FakeES()).find_similar()


class TestFilters:
    def test_author_other_excludes_the_source_author(self, db_session):
        es = FakeES(docs={"lead_post:1": dict(SOURCE_DOC)})
        service(db_session, es).find_similar(
            doc_type="lead_post", entity_id=1, author="other"
        )

        assert es.knn_calls[0]["must_not"]["author_username"] == ["test_author"]
        assert "author_username" not in es.knn_calls[0]["filters"]

    def test_author_same_filters_to_the_source_author(self, db_session):
        es = FakeES(docs={"lead_post:1": dict(SOURCE_DOC)})
        service(db_session, es).find_similar(
            doc_type="lead_post", entity_id=1, author="same"
        )

        assert es.knn_calls[0]["filters"]["author_username"] == "test_author"

    def test_author_filter_without_a_known_author_is_refused(self, db_session):
        """Better to refuse than to answer a wider question than was asked."""
        es = FakeES(docs={"lead_post:1": {"title": "t", "content": "c"}})
        with pytest.raises(UnsupportedFilterError):
            service(db_session, es).find_similar(
                doc_type="lead_post", entity_id=1, author="other"
            )

    def test_unknown_author_mode_is_refused(self, db_session):
        with pytest.raises(UnsupportedFilterError):
            service(db_session, FakeES()).find_similar(text="hello", author="sideways")

    def test_dates_become_range_filters(self, db_session):
        es = FakeES(docs={"lead_post:1": dict(SOURCE_DOC)})
        service(db_session, es).find_similar(
            doc_type="lead_post",
            entity_id=1,
            since=datetime(2026, 1, 1),
            until=datetime(2026, 2, 1),
        )

        bounds = es.knn_calls[0]["ranges"]["created_at"]
        assert bounds["gte"].startswith("2026-01-01")
        assert bounds["lte"].startswith("2026-02-01")

    def test_model_filter_keeps_other_vector_spaces_out(self, db_session):
        es = FakeES(docs={"lead_post:1": dict(SOURCE_DOC)})
        service(db_session, es).find_similar(doc_type="lead_post", entity_id=1)

        assert es.knn_calls[0]["filters"]["embedding_model"] == MODEL

    def test_deleted_documents_are_excluded_by_default(self, db_session):
        es = FakeES(docs={"lead_post:1": dict(SOURCE_DOC)})
        service(db_session, es).find_similar(doc_type="lead_post", entity_id=1)

        assert es.knn_calls[0]["filters"]["local_deleted"] is False


class TestTextFallback:
    def test_no_vector_falls_back_to_text(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            text_hits=[hit("lead_post:2", 4.2, doc_type="lead_post", content="test")],
        )
        svc = service(db_session, es, FakeEmbeddings(vector=None))
        found = svc.find_similar(doc_type="lead_post", entity_id=1)

        assert found["method"] == METHOD_TEXT
        assert [r["id"] for r in found["results"]] == ["lead_post:2"]
        # A BM25 score is not a cosine and is not dressed up as one.
        assert found["results"][0]["similarity"] is None

    def test_failed_knn_falls_back_to_text(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            knn_error="search_phase_execution_exception",
            text_hits=[hit("lead_post:2", 1.0, doc_type="lead_post")],
        )
        found = service(db_session, es).find_similar(doc_type="lead_post", entity_id=1)

        assert found["method"] == METHOD_TEXT
        assert found["results"]

    def test_endpoint_error_falls_back_rather_than_raising(self, db_session):
        from rediska_core.infrastructure.embeddings import EmbeddingsError

        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            text_hits=[hit("lead_post:2", 1.0, doc_type="lead_post")],
        )
        svc = service(db_session, es, FakeEmbeddings(error=EmbeddingsError("down")))
        found = svc.find_similar(doc_type="lead_post", entity_id=1)

        assert found["method"] == METHOD_TEXT


class TestEnrichment:
    def _lead(self, db_session, account, status="ignored"):
        lead = LeadPost(
            provider_id="reddit",
            source_location="test_sub",
            external_post_id="test_post_2",
            post_url="https://example.invalid/test_post_2",
            author_account_id=account.id,
            title="test_title",
            body_text="test body",
            status=status,
            analysis_recommendation="suitable",
            remote_visibility="visible",
        )
        db_session.add(lead)
        db_session.flush()
        return lead

    def test_results_carry_what_became_of_the_lead(self, db_session, world):
        lead = self._lead(db_session, world)
        es = FakeES(
            # The source is a different document than the neighbour, or the
            # neighbour would be dropped as "itself".
            docs={"lead_post:999": dict(SOURCE_DOC)},
            knn_hits=[hit(f"lead_post:{lead.id}", 0.99, doc_type="lead_post")],
        )
        found = service(db_session, es).find_similar(doc_type="lead_post", entity_id=999)

        row = found["results"][0]
        assert row["lead_status"] == "ignored"
        assert row["recommendation"] == "suitable"

    def test_lead_status_filter_is_applied_to_live_rows(self, db_session, world):
        """Status lives in MySQL, so the index cannot be trusted for it."""
        lead = self._lead(db_session, world, status="ignored")
        es = FakeES(
            docs={"lead_post:999": dict(SOURCE_DOC)},
            knn_hits=[hit(f"lead_post:{lead.id}", 0.99, doc_type="lead_post")],
        )
        svc = service(db_session, es)

        kept = svc.find_similar(
            doc_type="lead_post", entity_id=999, lead_status=["ignored"]
        )
        dropped = svc.find_similar(
            doc_type="lead_post", entity_id=999, lead_status=["contacted"]
        )

        assert [r["id"] for r in kept["results"]] == [f"lead_post:{lead.id}"]
        assert dropped["results"] == []


class TestProbableRewrites:
    def test_only_vector_matches_count_as_rewrites(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            text_hits=[hit("lead_post:2", 9.0, doc_type="lead_post")],
        )
        svc = service(db_session, es, FakeEmbeddings(vector=None))

        assert svc.probable_rewrites("lead_post", 1) == []

    def test_rewrite_threshold_is_strict(self, db_session):
        es = FakeES(
            docs={"lead_post:1": dict(SOURCE_DOC)},
            knn_hits=[
                hit("lead_post:2", 0.98, doc_type="lead_post"),   # cosine 0.96
                hit("lead_post:3", 0.96, doc_type="lead_post"),   # cosine 0.92
            ],
        )
        found = service(db_session, es).probable_rewrites("lead_post", 1)

        assert [r["id"] for r in found] == ["lead_post:2"]

    def test_non_post_types_have_no_rewrites(self, db_session):
        es = FakeES(docs={"message:1": {"title": "", "content": "hi"}})
        assert service(db_session, es).probable_rewrites("message", 1) == []
