## Context

Present state, verified 2026-09-18: index mapping has `embedding` (768 dims, cosine, `int8_hnsw`); `EmbeddingService` and `embed.*` tasks exist; `embed.generate_for_entity` handles only `message` (others are a commented stub); no code path dispatches any embed task; `IndexingService.lead_post_to_document` exists but only `AnalysisService._index_content` (profile snapshot/items) and message sync call `upsert_content`. `SearchService.hybrid_search` catches the missing vectors and returns BM25 results.

Measurements on `heartcode-embed` via LiteLLM: 42.7 docs/s at ≤ 1,400 chars in batches of 16–32; inputs above ~512 tokens return HTTP 500 ("input too large to process"); cosine between unrelated posts in this corpus: median 0.60, max 0.77; near-identical copies: median 1.00; 5,936 vectors cost 93.8 MB with the vector in `_source`; kNN 11 ms per query.

Privacy constraint: AI agents working on the repo must not read inbox content. Embedding messages is an in-system function of the local stack and is allowed; tests use synthetic `test_` data.

## Goals / Non-Goals

**Goals:** real semantic search; a general similarity primitive other features can call; honest degradation; bounded storage; no interference with live analysis on the shared GPU host.

**Non-Goals:** firehose-scale vectors, ranking changes, new infrastructure.

## Decisions

**1. Keep Elasticsearch as the only vector store.**
It is already deployed, already has the mapping, supports filtered kNN, and search needs BM25 and vectors in one place. *Alternatives:* MySQL 8.4 has no vector index; FAISS/Qdrant add a service and a second copy to keep consistent.

**2. Embed after index, as a chained task with a sweeper.**
`index.upsert_content` succeeds → enqueue `embed.generate_for_entity`. A document without a vector is still text-searchable. `embed.sweep_missing` (beat) picks documents where `embedding` is missing or `embedding_model != EMBEDDINGS_MODEL`, bounded per run. *Alternative:* embed inline during indexing — rejected: couples indexing to GPU availability, the failure mode that produced the 2026-09-16 outage pattern.

**3. Text prep: head + chunk mean.**
`title + "\n\n" + body`, whitespace-collapsed. If ≤ `EMBED_MAX_CHARS` (1,400): one vector. Else: split on paragraph boundaries into chunks ≤ 1,400 chars, embed up to 4, store the L2-normalised mean. One vector per document keeps kNN simple. *Alternatives:* raise the llama.cpp `--ubatch-size` on the GPU host to take whole posts (operator action, worth doing, but the code must not depend on it); nested per-chunk vectors (better recall on long profiles, 4× storage and nested kNN complexity — revisit if long-document recall disappoints). The external-listing details block is included, consistent with `lead-affinity-signal`.

**3a. Task prefixes, because the model is nomic-embed-text-v1.5.**
`heartcode-embed` routes to `nomic-embed-text-v1.5.Q8_0`, which is trained with task prefixes. Stored documents are embedded as `search_document: <text>`; search-box queries as `search_query: <text>`; `/similar` by raw text uses `search_document:` because it compares like with like. The prefix scheme is part of `embedding_prep`, so changing it triggers re-embedding. The 2026-09-18 calibration was measured without prefixes; thresholds (0.80 default, 0.95 rewrite) are re-measured during rollout on synthetic and known-copy pairs before being fixed. The model itself accepts 8,192 tokens; the ~512-token rejection is the llama.cpp server's batch setting, which is why raising `--ubatch-size` is an operator option and not a model limit. The model also supports Matryoshka truncation to 256 dimensions (about a third of the storage); not needed at the current corpus size, recorded as the first lever if the index grows past a million vectors.

**3b. Comments are embedded per account, merged (user decision).**
Comments average 108 characters; 105,215 of them as single vectors would more than double the index while each vector says almost nothing. Instead one `account_comments:<account_id>` document per account (3,029 accounts today) holds the comments merged newest first, each line prefixed with its community (`r/<sub>: <text>`), filled up to `EMBED_MAX_CHARS`; older comments beyond the limit are left out rather than averaged in, because recent behaviour is what the reviewer cares about. The vector describes how the person talks and where, which is what "more like this person" needs. The document is rebuilt when profile ingest stores new comments and re-embedded only if its text hash changed. Individual comments stay in the index as text-only `profile_item` documents, so keyword search still finds them. *Alternative considered:* embed only comments ≥ 200 characters — rejected by the user: it drops most comments entirely. If the embeddings server's batch size is raised (open question), the limit and therefore the number of comments covered rises with it, with no code change.

**4. Embedding calls go through the embeddings endpoint only, not the inference gate.**
Embeddings are a different model and slot. They get their own small Redis semaphore (`EMBED_MAX_CONCURRENT`, default 1) and batch size 16, with backfill sleeping between batches when the inference gate is busy, so lead analysis keeps priority.

**5. New index version with `_source.excludes: ["embedding"]`.**
Excluding a field from `_source` cannot be changed in place. Create `v2`, reindex text fields from MySQL (the source of truth; not ES-to-ES, since v1 has no vectors worth copying), switch the alias, keep v1 until a smoke check passes. Consequence: update-by-partial-doc cannot round-trip the vector, so the embed task writes the vector with a scripted/partial update that never reads it back, and re-indexing a document re-enqueues embedding only when the prepared-text hash changed (`embedding_text_hash`).

**6. `/similar` is one filtered kNN, with a declared fallback.**
Input: `{doc_type, entity_id}` or `{text}`. If the source document has a vector, use it; if only text, embed it (one call); if the embeddings endpoint is down or the source is un-embedded, run `more_like_this` on `text` and return `method: "text"`. Filters compile to the kNN `filter` clause: `doc_types`, `author: same|other|any`, `location`, `since/until`, `lead_status`, `exclude_deleted`. Scores are returned as cosine (ES `_score*2-1`). `min_score` defaults to 0.80 because unrelated posts here sit at 0.5–0.77.

**7. Scout posts: index analysed ones only.**
Analysed scout posts are kept permanently (detached on cleanup), so they are safe to index as `scout_post`. Unanalysed/skipped posts are deleted after 3 days and are never indexed. On promotion to a lead the `scout_post` document is removed in favour of `lead_post` to avoid double hits.

**8. Probable rewrite pass is a read-time query plus a stored suggestion.**
After a post is embedded, one kNN (`author: other`, `min_score: 0.95`, doc types post-like) runs; hits not already in the same copy cluster are stored as `copy_suggestions` rows when the copy tables exist. Measured yield is small (~7% beyond fingerprints), so it is a suggestion for the human, never a cluster by itself.

**9. Search tells the truth.**
`POST /search` returns `semantic_used: bool` and `semantic_unavailable_reason`. The UI shows a quiet notice in hybrid/meaning mode when false. Meaning mode with no embeddings endpoint returns an explicit error instead of BM25 results.

## Risks / Trade-offs

- [Embedding model weak on this vocabulary] → calibration numbers above show clean separation; `/ops` card includes a self-check (known-copy pair vs random pair).
- [Backfill competes with analysis for the GPU host] → own semaphore, inference-gate-aware pacing, resumable, cancellable via `jobs`.
- [Reindex mistakes lose search] → alias switch only after doc-count parity per type; v1 kept until confirmed.
- [Mean-of-chunks blurs long documents] → acceptable for posts (avg 1,200 chars); revisit for profiles.
- [Model swap silently mixes vector spaces] → `embedding_model` on every document; kNN filters on the current model; sweeper re-embeds.
- [ES heap] → int8 HNSW lives off-heap; 1 GB heap holds to several hundred thousand vectors; sizing documented.

## Migration Plan

1. Deploy code with enqueue hooks off (`EMBEDDINGS_ENABLED=false`).
2. Create v2, reindex from MySQL, parity check, switch alias.
3. Enable hooks; run `embed.backfill` dry run, then live (≈ 45 min GPU).
4. Verify coverage card ≥ 99%, run smoke similarity on a synthetic pair; drop v1.
Rollback: point the alias back to v1, disable hooks.

## Open Questions

- Raise `--ubatch-size` on the embeddings server to 2048 so whole posts embed in one call? Recommended; operator decision on the GPU host.
