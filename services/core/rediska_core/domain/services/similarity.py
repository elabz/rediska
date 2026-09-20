"""Nearest-neighbour lookup over the content index ("more like this").

One question, asked two ways: *what else reads like this?* — either about a
document already indexed (`doc_type` + `entity_id`) or about a piece of text
typed in. The answer is the nearest documents by cosine similarity, enriched
from MySQL with what actually happened to them (lead status, the latest agent
recommendation, the human's effective verdict, whether the author is banned),
because that outcome is the reason anyone asks.

Two decisions worth knowing about:

* **The source vector is re-derived, not read back.** The v2 index excludes
  `embedding` from `_source` (a vector per document is a lot of JSON nobody
  reads), so a reference lookup rebuilds the source's prepared text from the
  indexed `title`/`content` and embeds it again with the same rule. One extra
  embeddings call per request buys a much smaller index.
* **`lead_status` is a MySQL fact, not an index field.** Lead status changes
  without the document being rewritten, so filtering on the index would filter
  on a stale value. Instead the kNN query over-fetches and the filter is
  applied against the live rows — see `OVERFETCH`.

Failure is visible, never silent: when the source cannot be embedded the
service answers with a `more_like_this` text query and says `method="text"`,
and a filter it cannot apply raises `UnsupportedFilterError` rather than
quietly widening the result set.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from rediska_core.domain.services.embedding_text import prepare_embedding_text
from rediska_core.infrastructure.elasticsearch import (
    CONTENT_DOCS_INDEX,
    ElasticsearchClient,
    UnsupportedFilterError,
)
from rediska_core.infrastructure.embeddings import EmbeddingsClient, EmbeddingsError


# =============================================================================
# CONSTANTS
# =============================================================================


DEFAULT_MIN_SCORE = 0.80
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# Cosine at or above which two posts by different authors are treated as the
# same text reworded. Suggestion only — nothing clusters without a human.
REWRITE_MIN_SCORE = 0.95

# How many neighbours to ask ES for per requested result. The margin exists so
# that `lead_status`, which can only be applied against live MySQL rows, still
# returns a full page when enough matching documents exist.
OVERFETCH = 5
MAX_CANDIDATES = 500

AUTHOR_MODES = ("any", "same", "other")

# Document types that describe a post, i.e. the ones a rewrite can involve.
POST_LIKE_DOC_TYPES = ("lead_post", "scout_post", "profile_item")

METHOD_VECTOR = "vector"
METHOD_TEXT = "text"


class SimilarityError(Exception):
    """Raised when a similarity request cannot be answered at all."""


class SourceNotFound(SimilarityError):
    """Raised when the referenced document is not in the index."""


# =============================================================================
# SERVICE
# =============================================================================


class SimilarityService:
    """Find indexed documents that read like a given document or text."""

    def __init__(
        self,
        db: Session,
        es_url: str,
        embeddings_url: Optional[str] = None,
        embeddings_model: Optional[str] = None,
        embeddings_api_key: Optional[str] = None,
        es_api_key: Optional[str] = None,
    ):
        self.db = db
        self._es_url = es_url
        self._es_api_key = es_api_key
        self._embeddings_url = embeddings_url
        self._embeddings_model = embeddings_model
        self._embeddings_api_key = embeddings_api_key

        self._es_client: Optional[ElasticsearchClient] = None
        self._embeddings_client: Optional[EmbeddingsClient] = None

    # -- clients ----------------------------------------------------------

    @property
    def es_client(self) -> ElasticsearchClient:
        if self._es_client is None:
            self._es_client = ElasticsearchClient(
                url=self._es_url, api_key=self._es_api_key
            )
        return self._es_client

    @property
    def embeddings_client(self) -> Optional[EmbeddingsClient]:
        if self._embeddings_url and self._embeddings_model:
            if self._embeddings_client is None:
                self._embeddings_client = EmbeddingsClient(
                    url=self._embeddings_url,
                    model=self._embeddings_model,
                    api_key=self._embeddings_api_key,
                )
            return self._embeddings_client
        return None

    # -- source resolution ------------------------------------------------

    def _load_source(self, doc_type: str, entity_id: int) -> dict[str, Any]:
        """Read the indexed document that the caller is asking about."""
        document = self.es_client.get_document(
            index=CONTENT_DOCS_INDEX, doc_id=f"{doc_type}:{entity_id}"
        )
        if not document:
            raise SourceNotFound(
                f"{doc_type}:{entity_id} is not in the content index"
            )
        return document

    def _source_text(self, document: dict[str, Any]) -> str:
        """The prepared text of an indexed document, by the embedding rule."""
        return prepare_embedding_text(
            document.get("title") or "", document.get("content") or ""
        )

    def _embed(self, text: str) -> Optional[list[float]]:
        """Embed prepared text as a document, or return None if we cannot."""
        client = self.embeddings_client
        if client is None or not text.strip():
            return None
        try:
            return client.embed_document(text)
        except EmbeddingsError:
            return None

    # -- filters ----------------------------------------------------------

    def _filters(
        self,
        doc_types: Optional[list[str]],
        location: Optional[str],
        include_deleted: bool,
        author_username: Optional[str],
        author_mode: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Positive filters and exclusions for the neighbour query."""
        filters: dict[str, Any] = {}
        must_not: dict[str, Any] = {}

        if doc_types:
            filters["doc_type"] = doc_types
        if location:
            filters["location"] = location
        if not include_deleted:
            filters["local_deleted"] = False
        if self._embeddings_model:
            # Vectors from another model live in another space.
            filters["embedding_model"] = self._embeddings_model

        if author_mode == "same":
            filters["author_username"] = author_username
        elif author_mode == "other":
            must_not["author_username"] = [author_username]

        return filters, must_not

    @staticmethod
    def _ranges(
        since: Optional[datetime], until: Optional[datetime]
    ) -> dict[str, dict[str, Any]]:
        bounds: dict[str, Any] = {}
        if since is not None:
            bounds["gte"] = since.isoformat()
        if until is not None:
            bounds["lte"] = until.isoformat()
        return {"created_at": bounds} if bounds else {}

    # -- the query --------------------------------------------------------

    def find_similar(
        self,
        doc_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        text: Optional[str] = None,
        doc_types: Optional[list[str]] = None,
        author: str = "any",
        location: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        lead_status: Optional[list[str]] = None,
        include_deleted: bool = False,
        min_score: float = DEFAULT_MIN_SCORE,
        limit: int = DEFAULT_LIMIT,
        vector: Optional[list[float]] = None,
    ) -> dict[str, Any]:
        """Return the nearest documents to a reference document or to text.

        Args:
            doc_type: Type of the reference document.
            entity_id: Id of the reference document.
            text: Raw text to compare against, instead of a reference.
            doc_types: Restrict neighbours to these document types.
            author: `any`, `same` or `other`, relative to the source's author.
            location: Restrict to one community / location.
            since: Only documents created at or after this time.
            until: Only documents created at or before this time.
            lead_status: Keep only leads in these statuses (applied on the
                live rows, so non-lead documents cannot satisfy it).
            include_deleted: Include locally deleted documents.
            min_score: Minimum cosine similarity, default 0.80.
            limit: Maximum results, default 10.
            vector: A vector already computed for this source, to be used
                instead of embedding its text again.

        Returns:
            `{"method", "min_score", "source", "results"}`.

        Raises:
            SourceNotFound: The reference document is not indexed.
            SimilarityError: Neither a reference nor text was given.
            UnsupportedFilterError: A filter could not be applied.
        """
        if author not in AUTHOR_MODES:
            raise UnsupportedFilterError(
                f"author must be one of {AUTHOR_MODES}, not {author!r}"
            )
        limit = max(1, min(limit, MAX_LIMIT))

        source_doc: dict[str, Any] = {}
        source_id: Optional[str] = None
        if doc_type and entity_id is not None:
            source_doc = self._load_source(doc_type, entity_id)
            source_id = f"{doc_type}:{entity_id}"
            query_text = self._source_text(source_doc)
        elif text and text.strip():
            query_text = prepare_embedding_text("", text)
        else:
            raise SimilarityError(
                "Provide either a reference (doc_type and entity_id) or text"
            )

        author_username = (source_doc.get("author_username") or None) if source_doc else None
        if author != "any" and not author_username:
            # Silently ignoring it would answer a different question.
            raise UnsupportedFilterError(
                "author filtering needs a source document with a known author"
            )

        filters, must_not = self._filters(
            doc_types=doc_types,
            location=location,
            include_deleted=include_deleted,
            author_username=author_username,
            author_mode=author,
        )
        ranges = self._ranges(since, until)

        # Over-fetch so the MySQL-side lead_status filter and the exclusion of
        # the source document itself still leave a full page.
        k = min(limit * OVERFETCH, MAX_CANDIDATES)

        method = METHOD_TEXT
        if vector is None:
            vector = self._embed(query_text)
        if vector:
            result = self.es_client.knn_search(
                index=CONTENT_DOCS_INDEX,
                vector=vector,
                k=k,
                num_candidates=max(k * 2, 100),
                filters=filters,
                must_not=must_not,
                ranges=ranges,
            )
            method = METHOD_VECTOR
        else:
            result = {}

        if not vector or result.get("error"):
            # No vector, or the vector query failed: answer with text rather
            # than with an empty list that would read as "nothing is similar".
            filters.pop("embedding_model", None)
            result = self.es_client.search(
                index=CONTENT_DOCS_INDEX,
                query={
                    "more_like_this": {
                        "fields": ["title", "content"],
                        "like": query_text,
                        "min_term_freq": 1,
                        "min_doc_freq": 1,
                    }
                },
                filters=filters,
                must_not=must_not,
                ranges=ranges,
                size=k,
            )
            method = METHOD_TEXT
            if result.get("error"):
                raise SimilarityError(f"Similarity search failed: {result['error']}")

        hits = [hit for hit in result.get("hits", []) if hit.get("id") != source_id]
        results = self._to_results(hits, method=method, min_score=min_score)
        self._enrich(results)
        if lead_status:
            wanted = set(lead_status)
            results = [
                item
                for item in results
                if item.get("lead_status") in wanted
            ]

        return {
            "method": method,
            "min_score": min_score,
            "source": {
                "doc_type": doc_type,
                "entity_id": entity_id,
                "author_username": author_username,
            },
            "results": results[:limit],
        }

    # -- result shaping ---------------------------------------------------

    def _to_results(
        self, hits: list[dict[str, Any]], method: str, min_score: float
    ) -> list[dict[str, Any]]:
        """Turn ES hits into result rows, dropping ones below `min_score`.

        Elasticsearch reports cosine similarity as `(1 + cosine) / 2` so that
        scores stay positive; `score * 2 - 1` puts it back on the familiar
        -1..1 scale. A `more_like_this` score is a BM25 score, not a cosine,
        and is reported as-is with `similarity` left empty.
        """
        results: list[dict[str, Any]] = []
        for hit in hits:
            source = hit.get("source") or {}
            raw_score = hit.get("score") or 0.0
            similarity: Optional[float] = None
            if method == METHOD_VECTOR:
                similarity = round(raw_score * 2 - 1, 4)
                if similarity < min_score:
                    continue
            doc_id = hit.get("id") or ""
            doc_type, _, entity = doc_id.partition(":")
            results.append(
                {
                    "id": doc_id,
                    "doc_type": source.get("doc_type") or doc_type,
                    "entity_id": int(entity) if entity.isdigit() else None,
                    "score": round(raw_score, 4),
                    "similarity": similarity,
                    "title": source.get("title") or None,
                    "excerpt": _excerpt(source.get("content")),
                    "author_username": source.get("author_username"),
                    "account_id": source.get("account_id"),
                    "location": source.get("location"),
                    "created_at": source.get("created_at"),
                    "post_url": source.get("post_url"),
                    "lead_status": None,
                    "recommendation": None,
                    "human_verdict": None,
                    "author_banned": False,
                }
            )
        return results

    # -- enrichment -------------------------------------------------------

    def _enrich(self, results: list[dict[str, Any]]) -> None:
        """Fill in what happened to each neighbour, in batched queries."""
        if not results:
            return
        self._enrich_leads(results)
        self._enrich_scout_posts(results)
        self._enrich_bans(results)

    def _enrich_leads(self, results: list[dict[str, Any]]) -> None:
        from rediska_core.domain.models import LeadPost

        rows_by_id = self._rows_for(results, "lead_post", LeadPost)
        if not rows_by_id:
            return
        verdicts = self._lead_verdicts(list(rows_by_id.values()))
        for item in results:
            lead = rows_by_id.get(item["entity_id"]) if item["doc_type"] == "lead_post" else None
            if lead is None:
                continue
            item["lead_status"] = lead.status
            item["recommendation"] = lead.analysis_recommendation
            item["priority"] = lead.priority
            item["compatibility_score"] = lead.compatibility_score
            item["human_verdict"] = verdicts.get(lead.id)
            if not item.get("author_username") and lead.author_account is not None:
                item["author_username"] = (
                    lead.author_account.external_username or ""
                ).lower() or None

    def _enrich_scout_posts(self, results: list[dict[str, Any]]) -> None:
        from rediska_core.domain.models import ScoutWatchPost

        rows_by_id = self._rows_for(results, "scout_post", ScoutWatchPost)
        if not rows_by_id:
            return
        verdicts = self._final_verdicts("scout_post", list(rows_by_id))
        for item in results:
            post = rows_by_id.get(item["entity_id"]) if item["doc_type"] == "scout_post" else None
            if post is None:
                continue
            item["recommendation"] = post.analysis_recommendation
            item["human_verdict"] = verdicts.get(post.id)

    def _rows_for(self, results: list[dict[str, Any]], doc_type: str, model) -> dict[int, Any]:
        ids = [
            item["entity_id"]
            for item in results
            if item["doc_type"] == doc_type and item["entity_id"] is not None
        ]
        if not ids:
            return {}
        rows = self.db.scalars(select(model).where(model.id.in_(ids))).all()
        return {row.id: row for row in rows}

    def _final_verdicts(self, subject_type: str, subject_ids: list[int]) -> dict[int, Optional[str]]:
        """Effective human final verdict per subject, when the table is there.

        The latest row per subject with `dimension IS NULL` wins — the same
        rule `analysis_evaluation.effective_for_subjects` applies.
        """
        from rediska_core.domain.models import AnalysisEvaluation

        if not subject_ids:
            return {}
        try:
            rows = self.db.scalars(
                select(AnalysisEvaluation)
                .where(
                    AnalysisEvaluation.subject_type == subject_type,
                    AnalysisEvaluation.subject_id.in_(subject_ids),
                    AnalysisEvaluation.dimension.is_(None),
                )
                .order_by(
                    AnalysisEvaluation.created_at.desc(),
                    AnalysisEvaluation.id.desc(),
                )
            ).all()
        except Exception:
            return {}
        verdicts: dict[int, Optional[str]] = {}
        for row in rows:
            verdicts.setdefault(row.subject_id, row.human_verdict)
        return verdicts

    def _lead_verdicts(self, leads: list[Any]) -> dict[int, Optional[str]]:
        """Final human verdicts for leads, via their latest analysis row.

        An evaluation hangs off a `lead_analyses` row, not off the lead, so
        the lead's `latest_analysis_id` is the subject to look up.
        """
        latest = {
            lead.id: lead.latest_analysis_id
            for lead in leads
            if lead.latest_analysis_id is not None
        }
        if not latest:
            return {}
        by_analysis = self._final_verdicts("lead_analysis", list(latest.values()))
        return {
            lead_id: by_analysis.get(analysis_id)
            for lead_id, analysis_id in latest.items()
        }

    def _enrich_bans(self, results: list[dict[str, Any]]) -> None:
        from rediska_core.domain.services import ban_list

        usernames = [item["author_username"] for item in results if item.get("author_username")]
        if not usernames:
            return
        try:
            banned = ban_list.banned_usernames(self.db, "reddit", usernames)
        except Exception:
            return
        for item in results:
            username = item.get("author_username")
            if username:
                item["author_banned"] = username in banned

    # -- rewrites ---------------------------------------------------------

    def probable_rewrites(
        self,
        doc_type: str,
        entity_id: int,
        min_score: float = REWRITE_MIN_SCORE,
        limit: int = 5,
        vector: Optional[list[float]] = None,
    ) -> list[dict[str, Any]]:
        """Posts by other authors that read like a rewording of this one.

        A suggestion, nothing more: joining posts into a copy cluster is the
        user's decision, never this function's.
        """
        if doc_type not in POST_LIKE_DOC_TYPES:
            return []
        try:
            found = self.find_similar(
                doc_type=doc_type,
                entity_id=entity_id,
                doc_types=list(POST_LIKE_DOC_TYPES),
                author="other",
                min_score=min_score,
                limit=limit,
                vector=vector,
            )
        except (SourceNotFound, SimilarityError, UnsupportedFilterError):
            return []
        if found["method"] != METHOD_VECTOR:
            # A text match at "rewrite" confidence is not evidence of one.
            return []
        return found["results"]


def _excerpt(content: Optional[str], length: int = 280) -> Optional[str]:
    """A short, verbatim excerpt of the document's text."""
    if not content:
        return None
    text = " ".join(content.split())
    return text if len(text) <= length else text[:length].rstrip() + "…"


__all__ = [
    "SimilarityService",
    "SimilarityError",
    "SourceNotFound",
    "UnsupportedFilterError",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "REWRITE_MIN_SCORE",
    "AUTHOR_MODES",
    "POST_LIKE_DOC_TYPES",
]
