## Context

`MessageSyncService.sync_reddit_messages` walks Reddit listing endpoints newest-first and early-exits after 10 consecutive already-stored messages. It is called by two beat tasks, the "Sync now" route (`ingest.sync_delta`), and both backfill tasks. The worker runs 4 concurrent processes. MySQL (InnoDB) resolves a deadlock by rolling back the victim's entire transaction, not just a savepoint.

## Goals / Non-Goals

**Goals:** a routine poll costs one request; a broken run costs a bounded number of requests; concurrent syncs cannot collide; a write failure never silently degrades into a full-history walk.

**Non-Goals:** wiring the dormant `RateLimiter`/`PROVIDER_RATE_*` settings; changing backfill semantics beyond lock waiting.

## Decisions

**Lock in the service, not the tasks.** All five callers go through `sync_reddit_messages`, so the lock lives there (`rediska:lock:message_sync:reddit:<identity_id>`, redis-py `Lock`). Timeout 660s outlives Celery's 600s hard limit, so a killed worker cannot wedge polling; the lock is renewed after every page for long backfills. If Redis is unreachable the sync runs unlocked — savepoints make that safe, only less efficient. Alternative considered: Celery-level `jobs` dedupe keys — rejected because beat tasks do not use the ledger today and the collision is between *different* task types.

**Savepoint per message + commit per page.** A duplicate `IntegrityError` rolls back only that message's savepoint; the item is retried once so the lookup finds the committed row and it counts toward the early exit. Any other `SQLAlchemyError` (deadlock, lost connection) may have discarded the whole transaction, so the run rolls back and stops. Per-page commits bound that loss to one page. Alternative: rollback-and-continue — rejected because after a MySQL deadlock the cached conversation objects for the page are no longer valid.

**Separate caps for scheduled vs on-demand.** 5 pages (500 messages) covers any realistic gap between 60s polls. "Sync now" gets 20 so it can catch up after downtime. Backfills stay uncapped.

**Header pacing rather than a token bucket.** Reddit's headers describe the real, shared quota across all processes, which a local limiter cannot see. Pacing starts only below 10 remaining, spreading the rest over the time left in the window (reset countdown adjusted for elapsed time), capped at 30s per pause so pacing cannot push a task past its soft time limit. 429 waits `min(reset, 30s)` and retries once.

**Client per event loop.** Each Celery task runs its own `asyncio.run`; an httpx client is loop-bound. The adapter opens a client lazily, reopens it if the running loop changed, and `aclose()` is called by the sync service. Other adapter callers that never call `aclose()` leave the client to be garbage-collected with its loop, same as before.

## Risks / Trade-offs

- [Sent folder polled every 5 min] → a send whose Reddit id was not returned is reconciled later; remote delete of such a message may need to wait for the next sent sync.
- [Scheduled run skipped behind a long backfill] → intended; the backfill ingests the same messages.
- [Per-page commits] → a run can now partially succeed; its task result reports `status: "error"` with the committed counts.
