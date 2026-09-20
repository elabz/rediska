# Handoff — semantic-similarity-search

**State:** 24 of 27 tasks done. Groups 1–6 are implemented, committed and **live**.
Rewritten 2026-09-20 (supersedes the 2026-09-19 version).

Read [proposal.md](./proposal.md), [design.md](./design.md), `specs/*/spec.md` and
[tasks.md](./tasks.md) first — this file only covers state, what bit us, and
what is left.

---

## 1. Where the work stands

**Done:** groups 1–6, on commits `3b92126` (groundwork), `9c89a30` (search
honesty, `/similar`, UI, probable rewrites) and `edab60d` (oversize-input fix).

**Deployed.** `EMBEDDINGS_ENABLED=true`; the alias `rediska_content_docs` points
at `rediska_content_docs_v2` (252,692 documents, all seven types at parity); v1
is still there as the rollback target.

**Not done:** task 2.1a (re-measure the thresholds), 7.2 (coverage ≥ 99%), 7.3
(drop v1; make `lead-affinity-signal` depend on this change).

**Tests:** core 2032 passed / 9 skipped, worker 111 passed. Run them in Docker —
no host Python can import `rediska_core`:

```bash
docker run --rm -u 0 \
  -v /Users/boss/Web/rediska/services/core:/core \
  -v /Users/boss/Web/rediska/services/worker:/worker \
  -w /core --entrypoint sh ghcr.io/elabz/rediska-worker:latest -c \
  "pip install -q pytest pytest-asyncio aiosqlite; pip install -q --no-deps -e /core -e /worker; \
   python -m pytest tests -q -p no:cacheprovider"
```

Mount **both** core and worker even for the core suite. Web: `npx tsc --noEmit`,
`npm run lint`, `npx vitest run` (48 pre-existing failures in 4 files —
`settings/identities`, `setup/identity`, `AppShell`, `EmptyState` — are harness
rot, not yours; `src/components/similar/similar.test.tsx` passes, 9 tests).

---

## 2. What is left, in order

### 2.1 Finish the backfill (task 7.2)

At the time of writing it is running and roughly 3% through: ~251k documents at
about 20 docs/s, so several hours. It is resumable and skips what is already
embedded, so just re-dispatch if it stops:

```bash
docker compose exec -T rediska-worker python -c "
from rediska_worker.celery_app import app
print(app.send_task('embed.backfill', kwargs={'dry_run': False}, queue='embed').id)"
```

It stops itself after 20 failures. Check coverage on the `/ops` card or
directly:

```bash
docker compose exec -T rediska-elasticsearch curl -s \
  'localhost:9200/rediska_content_docs/_count' -H 'Content-Type: application/json' \
  -d '{"query":{"exists":{"field":"embedding"}}}'
```

### 2.2 Re-measure the thresholds (task 2.1a) — do this before trusting any number

The 0.80 `min_score` default and the 0.95 rewrite threshold were calibrated
*without* task prefixes and against no real corpus. **First evidence says 0.80
is too high:** on partially-embedded data, the nearest neighbours of a real
document scored 0.69–0.78, and a plain-text query's best match was 0.78. If that
holds after the backfill, `/similar` will look empty and `probable_rewrites`
will never fire.

Measure, do not guess: take the known copies out of `copy_clusters` (same text,
different authors — ground truth that *should* score high) and a sample of
unrelated pairs, and pick the threshold that separates them. Then fix
`DEFAULT_MIN_SCORE` and `REWRITE_MIN_SCORE` in
`domain/services/similarity.py`.

### 2.3 Drop v1 and update the sibling change (task 7.3)

Once search and `/similar` are confirmed working on v2:
`curl -X DELETE localhost:9200/rediska_content_docs_v1`. Then drop the "lead
posts get embeddings" tasks from `lead-affinity-signal` so it depends on this
change instead of repeating it.

---

## 3. Things that bit us (do not rediscover)

1. **An alias and an index cannot share a name.** Core hot-reloads the working
   tree, so the moment `CONTENT_DOCS_INDEX` became the alias name, live writes
   went to a name that was not yet an alias and Elasticsearch auto-created a
   concrete, dynamically-mapped index called `rediska_content_docs` (55k docs).
   It had to be deleted before the alias could be switched. Nothing was lost —
   the rebuild reads MySQL — but check `_cat/aliases` before assuming.
2. **MySQL has no `NULLS LAST`.** SQLAlchemy renders `nullslast()` literally, so
   the SQLite-backed tests accepted a statement MySQL rejects with a syntax
   error. It aborted a full rebuild part-way through the `account_comments`
   pass. Use `column.is_(None)` as the first sort key instead; there is a test
   that compiles the ordering against the MySQL dialect.
3. **Character budgets are not token budgets.** The embeddings server refuses
   anything over ~512 tokens (`--ubatch-size`), and dense text can be 1.25
   chars/token where prose is 4. The 1,400-char budget therefore stranded
   documents with HTTP 500 and killed the first backfill at 5,234 documents.
   `EmbeddingsClient._embed_chunked` now halves the budget and retries. Do not
   "fix" this by guessing a ratio.
4. **A 500 storm cools LiteLLM into 429s** (`cooldown_list=['heartcode-embed1',
   'heartcode-embed2']`), same shape as the chat-side outage. If 429s appear,
   look for a 500 storm upstream, not at the gateway.
5. **Queuing from write paths can hang the test suite.** The test settings use
   the production broker hostname, which does not resolve in the throwaway
   container. `indexing._dispatch` uses a cached Celery app, 1 s socket
   timeouts, `retry=False` and a 60 s circuit breaker. Keep every new dispatch
   going through `_dispatch`.
6. **`ElasticsearchClient.search()` returns a normalised shape** —
   `{"total", "hits": [{"id", "score", "source"}], "max_score"}` — not the raw
   ES response. `get_document()` returns `_source` directly. `knn_search`
   swallows ES errors into an `"error"` key rather than raising.
7. **`rediska-core` hot-reloads the working tree, but the worker and beat do
   not.** Rebuild core **and** worker together, and beat too when
   `celery_app.py` or a task module changed. `docker compose restart` does not
   re-read `.env`; use `up -d`.
8. **Privacy rules apply.** Do not read inbox or message content (code is fine,
   data is not), and do not drive a browser against the live app. Tests use
   synthetic `test_` data only.

---

## 4. Open question for the user

Raise `--ubatch-size` to 2048 on the embeddings server so whole posts embed in
one call instead of being chunked and averaged? Recommended in
[design.md](./design.md); it is an operator action on the GPU host, and the code
deliberately does not depend on it. With the shrink-retry in place this is now a
quality-and-throughput improvement rather than a correctness one.

---

## 5. Rollback

Point the alias back at v1 and set `EMBEDDINGS_ENABLED=false` (a copy of the
pre-rollout `.env` is at `.env.bak.pre-embeddings`). Nothing is lost either way:
documents are rebuilt from MySQL and vectors are derived.
