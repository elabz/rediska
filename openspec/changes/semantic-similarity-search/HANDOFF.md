# Handoff — semantic-similarity-search

**State:** 11 of 27 tasks done (groups 1 and 2). Nothing committed, nothing enabled
in the running system. Written 2026-09-20.

Read [proposal.md](./proposal.md), [design.md](./design.md), `specs/*/spec.md` and
[tasks.md](./tasks.md) first — this file
only covers what is built, what bit us, and what is left.

---

## 1. Where the work stands

**Done (groups 1–2):** the index version, the alias, and the whole embedding
pipeline, all behind `EMBEDDINGS_ENABLED=false`.

**Not started:** group 3 (search honesty), 4 (`/similar` API), 5 (UI),
6 (probable rewrites), 7 (rollout). Task 2.1a is code-complete but its
threshold re-measurement belongs to rollout (see §5).

**Tests:** core 1998 passed / 9 skipped, worker 111 passed. Run them in Docker —
no host Python can import `rediska_core`:

```bash
docker run --rm -u 0 \
  -v /Users/boss/Web/rediska/services/core:/core \
  -v /Users/boss/Web/rediska/services/worker:/worker \
  -w /core --entrypoint sh ghcr.io/elabz/rediska-worker:latest -c \
  "pip install -q pytest pytest-asyncio aiosqlite; pip install -q --no-deps -e /core -e /worker; \
   python -m pytest tests -q -p no:cacheprovider"
```

Mount **both** core and worker even for the core suite (two tests import
`rediska_worker`). Web: `npx tsc --noEmit`, `npm run lint`, `npx vitest run`
(48 pre-existing failures in 4 files — `settings/identities`, `setup/identity`,
`AppShell`, `EmptyState` — are harness rot, not yours).

---

## 2. What is built, and where

### Index version and alias (`infrastructure/elasticsearch.py`)
- `CONTENT_DOCS_MAPPING` now has `_source.excludes: ["embedding"]` and the fields
  `embedding_model`, `embedding_prep`, `embedding_text_hash`, `embedded_at`,
  `author_username`, `location`, `outcome_label`.
- `CONTENT_DOCS_INDEX` **is the alias** (`rediska_content_docs`). Versioned names
  are `CONTENT_DOCS_INDEX_V1` / `_V2` / `_CURRENT`. Every reader and writer
  already addresses the alias because they all use `CONTENT_DOCS_INDEX`.
- New helpers: `alias_exists`, `get_alias_indices`, `switch_alias`, `count`,
  `refresh`. `ensure_index()` creates v2 + alias on a clean host.
- **The live cluster still has only `rediska_content_docs_v1` and no alias.**
  Nothing has been reindexed yet. Until §5 step 2 runs, a live `ensure_index()`
  would create an empty v2 and alias it — which is why hooks are off.

### Text preparation (`domain/services/embedding_text.py`, new)
`prepare_embedding_text(title, body)`, `chunk_text` (≤ `EMBED_MAX_CHARS`, ≤ 4
chunks), `mean_vector` (L2-normalised), `as_document` / `as_query` prefixes,
`text_hash` (covers `PREP_VERSION`, so changing prep invalidates every vector).
Tests: `tests/test_embedding_text_unit.py` (18).

### Embeddings client (`infrastructure/embeddings.py`)
- `_check_size` refuses over-budget input locally; `EmbeddingsInputTooLargeError`
  types the server's HTTP 500 "input too large".
- `embed_document(text)` = chunk → embed → mean (one vector per document).
  `embed_query(text)` uses the query prefix.

### Embedding pipeline (`domain/services/embedding.py`)
- `text_for_entity(doc_type, entity_id)` — one rule per type: `message`,
  `lead_post`, `scout_post` (analysed only), `profile_item`, `profile_snapshot`,
  `account_comments`.
- `embed_entity(...)` — skips when `embedding_text_hash` and `embedding_model`
  are unchanged, else embeds and writes the vector with a partial update that
  never reads it back, stamping model/prep/hash/`embedded_at`. `force=True`
  overrides. Endpoint failure is returned, never raised.
- Legacy `generate_embedding` / `generate_embeddings_batch` are untouched.

### Documents (`domain/services/indexing.py`)
- New types: `scout_post` (analysed only) and `account_comments`
  (`entity_id` = account id; comments merged newest first, each line prefixed
  `r/<sub>: `, filled to `EMBED_MAX_CHARS`).
- `EMBEDDABLE_DOC_TYPES` (everything but `conversation`) and `POST_DOC_TYPES`.
- `author_username` (lower-cased) and `location` added to lead, scout, profile
  item, snapshot and comments documents — these are the `/similar` filters.
- `upsert_content` handles the new types and **chains embedding** on success.

### Worker tasks
- `embed.generate_for_entity(doc_type, entity_id, force=False)` — real, all types.
- `embed.sweep_missing(limit=200)` — beat every 10 min (`celery_app.py`); picks
  documents with no vector or another model's vector; stops after 5 failures.
- `embed.backfill(dry_run=True, batch_size=200, max_docs=0)` — `jobs` ledger per
  mode, resumable, cancellable (set the job row to `cancelled`), own semaphore,
  waits while the inference gate is saturated.
- `index.reindex_to_version(target_index="", switch_alias=False, batch_size=500)`
  — rebuilds from MySQL per type, refreshes, compares counts, switches the alias
  only when every type matches.
- Routing expectations for all of these are in
  `worker/tests/test_task_routing_unit.py`.

### Hooks (all queued, never inline)
| Where | What |
|---|---|
| `LeadsService.save_lead` | index `lead_post` |
| `ScoutWatchService.save_lead_from_watch` | index `lead_post`, delete the `scout_post` document |
| `scout.analyze_and_decide` (step 9) | index `scout_post` when it did not become a lead |
| `MessageSyncService._create_message_if_not_exists` | index `message` |
| `AnalysisService._index_content` | snapshot + items, plus `account_comments` when any item is a comment |

### Settings (`config.py`, `.env.example`, compose core + worker)
`EMBEDDINGS_ENABLED` (false), `EMBED_MAX_CHARS` (1400), `EMBED_MAX_CONCURRENT`
(1), `EMBED_BATCH_SIZE` (16). A setting not listed in the compose `environment:`
blocks never reaches the container — check both services.

---

## 3. Things that bit us (do not rediscover)

1. **Queuing from write paths can hang the test suite.** The test settings use the
   production broker hostname, which does not resolve in the throwaway container;
   the suite went from 90 s to > 10 min. `indexing._dispatch` now uses a cached
   Celery app, 1 s socket timeouts, `retry=False`, and a 60 s circuit breaker
   after a failure. Keep every new dispatch going through `_dispatch`.
2. **MySQL cannot index a BLOB.** `sa.LargeBinary` → BLOB; use `BINARY(n)` /
   `VARBINARY(n)` for anything indexed (this cost a failed migration in the
   previous change). MySQL DDL is not transactional — a half-applied migration
   leaves tables behind that you must drop by hand before re-running.
3. **`ElasticsearchClient.search()` returns a normalised shape** —
   `{"total", "hits": [{"id", "score", "source"}], "max_score"}` — not the raw ES
   response, and it has no `source_includes`. `get_document()` returns `_source`
   directly.
4. **`_source.excludes` cannot be changed in place.** That is the whole reason for
   v2 + alias. Do not try to "fix" v1.
5. **The `catenary diagnostics` gate rejects the entire next bash command** when
   unpaid, so a chained `python3 - <<EOF ... && catenary` silently runs nothing.
   Run diagnostics bare, as the sole command. `reportMissingImports` for
   `rediska_core.*` (from worker, and for any *new* core module) is stale-resolver
   noise, not a real error.
6. **`rediska-core` hot-reloads the working tree, but the worker and beat do not.**
   Always rebuild core **and** worker together, and beat too when `celery_app.py`
   or a task module changed. See [the rebuild-containers skill](../../../.claude/skills/rebuild-containers.md), including
   waiting for an idle worker and clearing `rediska:inference:inflight` after.
7. **Privacy rules apply.** Do not read inbox or message content (code is fine,
   data is not), and do not drive a browser against the live app. Tests use
   synthetic `test_` data only.

---

## 4. What is left

**Group 3 — search honesty (`domain/services/search.py`, `api/schemas/search.py`,
web `/search`).** Add `semantic_used` and `semantic_unavailable_reason` to the
response; `vector` mode must error rather than return BM25; filter kNN on
`embedding_model` so a model change cannot mix vector spaces; embed the query
with `embed_query` (query prefix); UI mode switch (hybrid / text / meaning) and a
quiet notice when semantic ranking was unavailable.

**Group 4 — `/similar` (new `domain/services/similarity.py`, `api/routes/similar.py`,
BFF `apps/web/src/app/api/core/similar`).** Input `{doc_type, entity_id}` or
`{text}`; filtered kNN; `min_score` default 0.80, `limit` 10; exclude the source
document; filters `doc_types`, `author` (same/other/any), `location`,
`since`/`until`, `lead_status`, `include_deleted` — an accepted filter must never
be silently dropped (`UnsupportedFilterError` exists for that); cosine =
`_score * 2 - 1`; `more_like_this` fallback with `method: "text"`. Test with a
fake ES client, as `tests/test_embedding_pipeline_unit.py` does.

**Group 5 — UI.** `SimilarPanel` (filters, outcome badges, empty and error
states) mounted on lead card/detail, scout history, needs-review, profile items,
conversation messages, search results; `/ops` coverage card backed by a new
`GET /ops/embeddings/status`. Follow `components/copy/` for the drawer/panel
pattern and its Vitest file.

**Group 6 — probable rewrites.** After a post-like document is embedded, one kNN
(`author=other`, `min_score` 0.95); hits not already in the same copy cluster
become `copy_suggestions` the user accepts (audited, joins the cluster) or
rejects. The copy tables exist (migrations 022/023, change archived as
`2026-09-19-post-fingerprint-dedupe`); `post_copy.py` has the cluster helpers.
Nothing may create or merge a cluster from similarity alone.

**Group 7 — rollout.** See §5. Includes docs (CLAUDE.md, [docs/deploy.md](../../../docs/deploy.md) sizing:
~1 GB page cache and ~4 GB disk per million vectors, plus the `--ubatch-size`
operator note) and dropping the "lead posts get embeddings" tasks from
`lead-affinity-signal` so it depends on this change.

---

## 5. Rollout procedure (group 7, in order)

1. **Deploy dark.** `EMBEDDINGS_ENABLED=false` in `.env` (already the default).
   Rebuild core + worker + beat; verify the new symbols are really in the worker
   (a stale worker looks healthy).
2. **Build v2 and switch the alias.**
   ```bash
   docker compose exec -T rediska-worker python -c "
   from rediska_worker.tasks.index import reindex_to_version as t
   print(t.apply(kwargs={'switch_alias': False}).result)"
   ```
   Check `parity` per type, then re-run with `switch_alias=True` (or call
   `switch_alias` directly). Keep v1 until search is confirmed working.
3. **Enable hooks:** `EMBEDDINGS_ENABLED=true`, recreate core/worker/beat
   (`docker compose up -d` — a restart does not re-read `.env`).
4. **Backfill:** `embed.backfill` with `dry_run=True` first (per-type counts),
   then live. Roughly 45 min for ~110k documents at the measured 43 docs/s.
   Watch that live analysis is not starved.
5. **Re-measure the thresholds (task 2.1a).** The 0.80 similarity default and the
   0.95 rewrite threshold were calibrated *without* task prefixes. Re-measure on
   synthetic pairs and known copies from the copy clusters, then fix the numbers.
6. **Verify** coverage ≥ 99% on the `/ops` card, run a smoke similarity query,
   then drop v1.

**Rollback:** point the alias back at v1 and set `EMBEDDINGS_ENABLED=false`.

---

## 6. Open questions for the user

- Raise `--ubatch-size` to 2048 on the embeddings server so whole posts embed in
  one call? Recommended in [design.md](./design.md); it is an operator action on the GPU host,
  and the code deliberately does not depend on it.
- The embed pipeline was dead before this change (0 vectors), so nobody has ever
  seen semantic results from this corpus. Expect to tune `min_score` after step 5.
