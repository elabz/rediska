"""Embedding generation tasks.

Vectors for content (messages, posts, profiles, merged account comments) are
generated here and written to the Elasticsearch document, which is what makes
search semantic and `/similar` possible.

Embedding is chained after indexing and never inline: a document without a
vector is still text-searchable, and `embed.sweep_missing` picks up whatever
the endpoint could not take. Calls go through the embeddings endpoint and its
own small semaphore — never the inference gate — and the backfill waits while
live analysis is using the GPU host.
"""

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

# Slots for concurrent embedding calls, so a backfill cannot saturate the host.
EMBED_INFLIGHT_KEY = "rediska:embed:inflight"
EMBED_SLOT_TTL_SECONDS = 600
# How long the backfill waits for live analysis to free the GPU host.
INFERENCE_IDLE_TIMEOUT_SECONDS = 600


def _session():
    from rediska_core.infra.db import get_sync_session_factory

    return get_sync_session_factory()()


def _service(session, settings):
    from rediska_core.domain.services.embedding import EmbeddingService

    return EmbeddingService(
        db=session,
        embeddings_url=settings.embeddings_url,
        embeddings_model=settings.embeddings_model,
        embeddings_api_key=settings.embeddings_api_key,
        es_url=settings.elastic_url,
    )


def _redis(settings):
    """Sync Redis client, or None when Redis is unreachable (fail open)."""
    try:
        import redis

        return redis.Redis.from_url(
            os.getenv("REDIS_URL", settings.redis_url),
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    except Exception as e:  # noqa: BLE001 - pacing is best-effort
        logger.debug(f"Redis unavailable for embed pacing: {e}")
        return None


@contextmanager
def _embed_slot(settings) -> Iterator[None]:
    """Hold one of `EMBED_MAX_CONCURRENT` embedding slots.

    Fails open: if Redis is unavailable or every slot looks taken for longer
    than the wait window, the call proceeds rather than stalling the pipeline.
    """
    client = _redis(settings)
    held = False
    if client is not None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                count = int(client.incr(EMBED_INFLIGHT_KEY))  # type: ignore[arg-type]
                client.expire(EMBED_INFLIGHT_KEY, EMBED_SLOT_TTL_SECONDS)
                if count <= max(1, settings.embed_max_concurrent):
                    held = True
                    break
                client.decr(EMBED_INFLIGHT_KEY)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Embed slot unavailable: {e}")
                break
            time.sleep(1.0)
    try:
        yield
    finally:
        if held and client is not None:
            try:
                if int(client.decr(EMBED_INFLIGHT_KEY)) < 0:  # type: ignore[arg-type]
                    client.set(EMBED_INFLIGHT_KEY, 0)
            except Exception:  # noqa: BLE001
                pass


def _wait_for_inference(settings) -> None:
    """Pause while live analysis is saturating the shared GPU host."""
    client = _redis(settings)
    if client is None:
        return
    from rediska_core.infrastructure.inference_gate import INFLIGHT_KEY

    deadline = time.monotonic() + INFERENCE_IDLE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            raw = client.get(INFLIGHT_KEY)
            inflight = int(raw) if raw else 0  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return
        if inflight < max(1, settings.inference_max_concurrent):
            return
        time.sleep(5.0)


@app.task(name="embed.generate")
def generate(doc_type: str, entity_id: int, text: str) -> dict[str, Any]:
    """Generate embedding for text content and store in ES.

    Fetches text, generates embedding via llama.cpp, and updates
    the corresponding ES document with the embedding vector.

    Args:
        doc_type: Type of document (message, conversation, profile, lead_post).
        entity_id: ID of the entity.
        text: Text content to embed.

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()

    # Check if embeddings are configured
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "reason": "Embeddings not configured",
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = EmbeddingService(
            db=session,
            embeddings_url=settings.embeddings_url,
            embeddings_model=settings.embeddings_model,
            embeddings_api_key=settings.embeddings_api_key,
            es_url=settings.elastic_url,
        )

        result = service.generate_embedding(
            doc_type=doc_type,
            entity_id=entity_id,
            text=text,
        )

        return {
            "status": "success" if result.get("success") else "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            **result,
        }

    except Exception as e:
        return {
            "status": "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="embed.generate_batch")
def generate_batch(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate embeddings for multiple items in batch.

    More efficient for bulk embedding operations.

    Args:
        items: List of dicts with doc_type, entity_id, and text.

    Returns:
        Dictionary with batch processing results.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()

    # Check if embeddings are configured
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "reason": "Embeddings not configured",
            "processed": 0,
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = EmbeddingService(
            db=session,
            embeddings_url=settings.embeddings_url,
            embeddings_model=settings.embeddings_model,
            embeddings_api_key=settings.embeddings_api_key,
            es_url=settings.elastic_url,
        )

        result = service.generate_embeddings_batch(items)

        return {
            "status": "success" if result.get("success") else "partial",
            **result,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "processed": 0,
        }
    finally:
        session.close()


@app.task(name="embed.generate_for_entity")
def generate_for_entity(doc_type: str, entity_id: int, force: bool = False) -> dict[str, Any]:
    """Embed one indexed entity, fetching and preparing its text from the DB.

    Chained after `index.upsert_content`. Skips silently when the prepared text
    is unchanged and already embedded with the configured model.

    Args:
        doc_type: message, lead_post, scout_post, profile_item,
            profile_snapshot or account_comments.
        entity_id: The entity's id (the account id for account_comments).
        force: Re-embed even when the text hash and model are unchanged.
    """
    from rediska_core.config import get_settings

    settings = get_settings()
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "reason": "Embeddings not configured",
        }

    session = _session()
    try:
        with _embed_slot(settings):
            result = _service(session, settings).embed_entity(
                doc_type=doc_type, entity_id=entity_id, force=force
            )
        return {
            "status": "success" if result.get("success") else "error",
            **result,
        }
    except Exception as e:
        logger.warning(f"embed.generate_for_entity {doc_type}:{entity_id} failed: {e}")
        return {
            "status": "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "error": str(e),
        }
    finally:
        session.close()


# =============================================================================
# SWEEP / BACKFILL
# =============================================================================


def _missing_vector_query(model: str) -> dict[str, Any]:
    """Documents of an embeddable type with no vector, or one from another model."""
    from rediska_core.domain.services.indexing import EMBEDDABLE_DOC_TYPES

    return {
        "bool": {
            "filter": [{"terms": {"doc_type": sorted(EMBEDDABLE_DOC_TYPES)}}],
            "should": [
                {"bool": {"must_not": {"exists": {"field": "embedding"}}}},
                {"bool": {"must_not": {"term": {"embedding_model": model}}}},
            ],
            "minimum_should_match": 1,
        }
    }


def _pending(es_client, model: str, size: int) -> list[tuple[str, int]]:
    """A bounded page of (doc_type, entity_id) still needing a vector."""
    from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_INDEX

    result = es_client.search(
        index=CONTENT_DOCS_INDEX,
        query=_missing_vector_query(model),
        size=size,
    )
    out: list[tuple[str, int]] = []
    for hit in result.get("hits", []):
        source = hit.get("source") or {}
        doc_type, entity_id = source.get("doc_type"), source.get("entity_id")
        if doc_type and entity_id is not None:
            out.append((doc_type, int(entity_id)))
    return out


@app.task(name="embed.sweep_missing", bind=True, max_retries=0)
def sweep_missing(self, limit: int = 200) -> dict[str, Any]:
    """Embed a bounded batch of documents whose vector is missing or stale.

    The safety net behind the index -> embed chain: a document whose embedding
    call failed (endpoint down, GPU busy) is picked up here, and a model change
    re-embeds everything over time.
    """
    from rediska_core.config import get_settings

    settings = get_settings()
    if not settings.embeddings_enabled:
        return {"status": "disabled", "embedded": 0}
    if not settings.embeddings_url or not settings.embeddings_model:
        return {"status": "skipped", "reason": "Embeddings not configured", "embedded": 0}

    session = _session()
    try:
        service = _service(session, settings)
        pending = _pending(service.es_client, settings.embeddings_model, limit)
        embedded = failed = skipped = 0
        for doc_type, entity_id in pending:
            with _embed_slot(settings):
                result = service.embed_entity(doc_type, entity_id)
            if not result.get("success"):
                failed += 1
            elif result.get("status") == "embedded":
                embedded += 1
            else:
                skipped += 1
            if failed >= 5:
                # The endpoint is down; leave the rest for the next run.
                break
        return {
            "status": "success",
            "candidates": len(pending),
            "embedded": embedded,
            "skipped": skipped,
            "failed": failed,
        }
    except Exception as e:
        logger.warning(f"embed.sweep_missing failed: {e}")
        return {"status": "error", "error": str(e), "embedded": 0}
    finally:
        session.close()


BACKFILL_DRY_RUN_KEY = "embed.backfill:dry_run"
BACKFILL_LIVE_KEY = "embed.backfill:live"


@app.task(
    name="embed.backfill",
    bind=True,
    max_retries=0,
    soft_time_limit=7200,
    time_limit=7500,
)
def backfill(self, dry_run: bool = True, batch_size: int = 200, max_docs: int = 0) -> dict[str, Any]:
    """Embed every indexed document that has no current vector.

    Dry run by default: reports what it would embed, per document type, and
    writes nothing. A live run is resumable (it re-queries what is still
    missing), cancellable through the `jobs` ledger, and paces itself so live
    analysis keeps the GPU host.

    Args:
        dry_run: Report only (the default).
        batch_size: Documents per query page.
        max_docs: Stop after this many documents (0 = no limit).
    """
    from sqlalchemy import select

    from rediska_core.config import get_settings
    from rediska_core.domain.models import Job

    settings = get_settings()
    if not settings.embeddings_url or not settings.embeddings_model:
        return {"status": "skipped", "reason": "Embeddings not configured"}

    key = BACKFILL_DRY_RUN_KEY if dry_run else BACKFILL_LIVE_KEY
    session = _session()
    job = None
    try:
        service = _service(session, settings)
        model = settings.embeddings_model

        job = session.execute(select(Job).where(Job.dedupe_key == key)).scalar()
        if job is not None and job.status == "running" and not dry_run:
            return {"status": "already_running", "dry_run": dry_run}
        if job is None:
            job = Job(
                queue_name="embed",
                job_type="embed_backfill",
                payload_json={"dry_run": dry_run},
                dedupe_key=key,
                status="running",
                attempts=1,
            )
            session.add(job)
        else:
            job.status = "running"
            job.attempts = (job.attempts or 0) + 1
        session.commit()

        if dry_run:
            from rediska_core.domain.services.indexing import EMBEDDABLE_DOC_TYPES
            from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_INDEX

            per_type = {}
            for doc_type in sorted(EMBEDDABLE_DOC_TYPES):
                query = _missing_vector_query(model)
                query["bool"]["filter"] = [{"term": {"doc_type": doc_type}}]
                per_type[doc_type] = service.es_client.count(CONTENT_DOCS_INDEX, query)
            report = {
                "status": "success",
                "dry_run": True,
                "would_embed": sum(v for v in per_type.values() if v > 0),
                "by_doc_type": per_type,
            }
            job.status = "done"
            job.payload_json = {"dry_run": True, "report": report}
            session.commit()
            return report

        embedded = failed = skipped = 0
        cancelled = False
        while True:
            session.expire_all()
            job = session.execute(select(Job).where(Job.dedupe_key == key)).scalar()
            if job is not None and job.status == "cancelled":
                cancelled = True
                break
            pending = _pending(service.es_client, model, batch_size)
            if not pending:
                break
            _wait_for_inference(settings)
            for doc_type, entity_id in pending:
                with _embed_slot(settings):
                    result = service.embed_entity(doc_type, entity_id)
                if not result.get("success"):
                    failed += 1
                elif result.get("status") == "embedded":
                    embedded += 1
                else:
                    skipped += 1
                if max_docs and embedded + skipped + failed >= max_docs:
                    break
            if failed >= 20 or (max_docs and embedded + skipped + failed >= max_docs):
                break
            if skipped >= len(pending) and embedded == 0:
                # Everything in this page reported "unchanged": nothing to do.
                break

        report = {
            "status": "cancelled" if cancelled else "success",
            "dry_run": False,
            "embedded": embedded,
            "skipped": skipped,
            "failed": failed,
        }
        if job is not None:
            job.status = "cancelled" if cancelled else "done"
            job.payload_json = {"dry_run": False, "report": report}
            session.commit()
        return report

    except Exception as e:
        logger.error(f"embed.backfill failed: {e}", exc_info=True)
        if job is not None:
            session.rollback()
            job.status = "failed"
            job.last_error = str(e)[:2000]
            session.commit()
        return {"status": "error", "error": str(e), "dry_run": dry_run}
    finally:
        session.close()
