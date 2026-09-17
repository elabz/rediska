## Why

Reddit has no push channel for private messages, so Rediska polls: `ingest.sync_inbox_fast` every 60s and `ingest.sync_delta` (inbox + sent) every 120s. Both are meant to stop after 10 already-stored messages, and most runs do, in one request. But in one observed hour, 4 runs walked the **entire inbox (220 pages)** while processing zero messages, accounting for most of ~1,200 Reddit calls that hour and running 160–300s each.

The cause is a chain of defects:

1. **The two schedules overlap.** Nothing prevents `sync_inbox_fast` and `sync_delta` from walking the inbox at the same time, so both insert the same new message and one fails with `Duplicate entry` or `Deadlock found`.
2. **One failed write poisons the session.** The per-message `except` records the error and continues without a rollback, so every later message raises too — silently, since the error only lands in the task's return value.
3. **A failing message never counts toward the early exit**, so the loop pages through the whole history.
4. **The final commit fails**, discarding everything the run did.

Reddit's OAuth quota is about 100 requests/minute averaged over 10 minutes; a full walk runs ~80/minute for ~3 minutes, and two overlapping walks exceed it. The adapter also ignores Reddit's `X-Ratelimit-*` headers and opens a new HTTP client per request.

## What Changes

- **Single-flight message sync.** Every message sync holds a per-identity Redis lock. Scheduled runs skip when it is held; on-demand syncs and backfills wait up to 60s.
- **Failure isolation.** Each message is written in a savepoint and each page commits on its own. A duplicate from a concurrent writer is re-read and counted as already stored; any other database failure stops the run, keeping earlier pages, and is logged.
- **Page caps.** Scheduled syncs read at most 5 pages; the on-demand sync at most 20 per folder. Uncapped walks remain only in the backfill tasks.
- **Split schedules.** Beat polls the inbox every 60s (`ingest.sync_inbox_fast`) and the sent folder every 300s (new `ingest.sync_sent`). `ingest.sync_delta` is no longer scheduled; it backs the "Sync now" button.
- **Quota-aware adapter.** The Reddit adapter reads `X-Ratelimit-Remaining`/`Reset`, spreads the last requests of a window evenly (≤30s per pause), waits and retries once on 429, and reuses one HTTP client per event loop.

## Capabilities

### New Capabilities

<!-- None. -->

### Modified Capabilities

- `conversation-sync`: modify "Scheduled delta syncs keep the inbox fresh" (new schedule, page caps); add single-flight locking and write-failure isolation requirements.
- `provider-reddit`: add a requirement that the adapter paces requests by Reddit's reported quota.

## Impact

**Affected code**
- `services/core/rediska_core/domain/services/message_sync.py` — lock, savepoints, per-page commit, page cap, `sync_sent_only`
- `services/core/rediska_core/providers/reddit/adapter.py` — shared client, quota pacing, 429 retry, `aclose()`
- `services/worker/rediska_worker/tasks/ingest.py` — `ingest.sync_sent`, capped/locked `sync_inbox_fast` and `sync_delta`, backfills wait for the lock
- `services/worker/rediska_worker/celery_app.py` — beat schedule

**Behavior notes**
- A message sent from another Reddit client, or a Rediska send whose Reddit id was not returned, is matched from the sent folder within 5 minutes instead of 2.
- Task results may now carry `status: "skipped"`.

**Out of scope**
- The existing `provider-reddit` requirement "Redis-backed provider rate limiting" (`PROVIDER_RATE_*`) is still not wired into the Reddit adapter; `infrastructure/rate_limiter.py` remains unused. Header-based pacing addresses the observed quota risk without it.
- `fetch_inbox_messages` drops non-`t4` children, so a listing page containing only comment replies ends the walk early. Pre-existing; unchanged here.
