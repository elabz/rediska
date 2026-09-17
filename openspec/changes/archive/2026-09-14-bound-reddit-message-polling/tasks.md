## 1. Failure isolation and page caps (message_sync)

- [x] 1.1 Write each message in a savepoint; retry once on `IntegrityError` so a concurrent duplicate is re-read as already stored
- [x] 1.2 Stop the run on any other `SQLAlchemyError` (rollback, `aborted`, logged error) instead of paging on with a broken session
- [x] 1.3 Commit per page; log per-message failures instead of only returning them
- [x] 1.4 Add `max_pages` and an `endpoints` override; add `sync_sent_only`
- [x] 1.5 Unit tests against SQLite with a fake adapter: early exit, page cap, uncapped walk, sent-only, concurrent duplicate, deadlock mid-page, unparseable message

## 2. Single-flight lock

- [x] 2.1 Per-identity redis-py lock (660s timeout, renewed per page, released in `finally`); run unlocked if Redis is unreachable
- [x] 2.2 `skipped` result when the lock is held; `lock_wait_seconds` for on-demand callers
- [x] 2.3 Unit tests: skip while held, renew + release, unreachable Redis

## 3. Worker tasks and schedule

- [x] 3.1 `ingest.sync_inbox_fast` and new `ingest.sync_sent` run page-capped (5) through a shared helper
- [x] 3.2 `ingest.sync_delta` capped at 20 pages and waits up to 60s for the lock; backfills wait for the lock and stay uncapped
- [x] 3.3 Beat: inbox every 60s, sent every 300s, `sync_delta` removed from the schedule
- [x] 3.4 Task results report `skipped` / `error` (aborted) and queue indexing only when messages arrived
- [x] 3.5 Worker unit tests for the schedule and result mapping

## 4. Reddit adapter

- [x] 4.1 Shared HTTP client per event loop with `aclose()`; sync service closes it
- [x] 4.2 Record `X-Ratelimit-*`; pace below 10 remaining (≤30s, window-aware); 429 waits and retries once
- [x] 4.3 Unit tests: client reuse, aclose, healthy/low/capped/reset pacing, 429 retry, second 429, malformed headers
- [x] 4.4 Existing adapter/OAuth unit tests still pass

## 5. Rollout

- [x] 5.1 Update CLAUDE.md Celery task list
- [x] 5.2 Rebuild core + worker images; recreate core, worker, beat
- [x] 5.3 Confirm in worker logs: routine runs make one request, no full-inbox walks, `ingest.sync_sent` runs every 5 minutes
