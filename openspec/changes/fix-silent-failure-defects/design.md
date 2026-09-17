## Context

Five defects surfaced from a test-quality audit. Two are already fixed in the working tree; three remain. They are grouped into one change because they share a root cause worth addressing as a class: **a code path that reports success while performing no work, paired with a test that asserted the return value rather than the effect.**

Current state of each:

| # | Defect | Status | Spec position |
|---|---|---|---|
| 1 | `data_safety` audit writes raise `TypeError` into a bare `except` | fixed | violated `ops-jobs` audit requirement |
| 2 | `StructuredLogger` omits `stacklevel` | fixed | unspecified |
| 3 | `exclude_visibility` dropped in search | open | violates `search-indexing` default-exclusion scenario |
| 4 | `task_routes` module-path globs never match | open | unspecified |
| 5 | `enqueue_send` dedupe key can never collide | open | violates `ops-jobs` idempotency requirement |

Relevant constraints: the ES client (`infrastructure/elasticsearch.py`) builds only positive filter clauses today; the worker consumes every declared queue via `-Q`, so routing changes cannot strand work; sends already require an explicit user POST, so #5 is not an at-most-once hole.

## Goals / Non-Goals

**Goals:**
- Make `exclude_visibility` actually filter, including satisfying the existing default-exclusion scenario.
- Make declared queue routing effective, so `task_routes` describes reality.
- Make the send dedupe key stable across identical enqueues, so `dedupe=True` is either meaningful or removed.
- Ensure a best-effort audit write that fails is *loud* — logged, never silently dropped.
- Convert the two strict-`xfail` tests pinning the search defects into normal assertions.

**Non-Goals:**
- A codebase-wide policy on `except Exception` swallowing.
- Any schema migration, API surface change, or new dependency.
- Changing messaging delivery guarantees.
- Fixing the latent `AgentHarness` max-turns path (unreachable until tool-calling lands).
- Reordering `send_manual`'s imports so its validation branch runs off-container.

## Decisions

### 1. Add `must_not` support to the ES client rather than inverting filters at the call site

`exclude_visibility` is a *negative* constraint and the client only speaks positive `term`/`terms`. Two options:

- **(a) Enumerate the complement** — translate "exclude removed, deleted_by_author" into `terms: {remote_visibility: [visible, unknown]}` at the service layer.
- **(b) Add a `must_not` clause list to `ElasticsearchClient.search`.** *(chosen)*

(a) is fragile: it silently breaks whenever a new visibility value is added, and it excludes documents where the field is absent. (b) matches the caller's intent literally, handles missing fields correctly, and gives the client a capability it will need again. The cost is a widened client signature, which is contained — `search()` already takes a `filters` dict, so this adds a sibling parameter.

### 2. Fix routing by making the pattern keys match registered names, not by renaming tasks

Task names are a public contract: they appear in `send_task` calls from the core API, in the beat schedule, and in the `jobs` ledger. Renaming tasks to match the globs would ripple through all of those. Rewriting the globs (`rediska_worker.tasks.ingest.*` → `ingest.*`) is a one-line-per-entry change confined to `celery_app.py`, and matches the two entries that already work.

### 3. Compute the send dedupe key before the message row exists — keep dedupe, no time window

**Decided: keep `dedupe=True` and make the key stable.** Sending the same text twice into the same conversation is rare enough that deduplicating it is the right default; the double-submit it prevents is the more common event.

The key is derived from caller-stable inputs — conversation id, identity id, and a body fingerprint. The `message_id` cannot participate, because it is minted inside the same call, which is exactly what makes today's key unable to collide.

**No time window is needed**, which was the design's open worry. The existing ledger already gives the desired semantics for free: `JobService.complete_job` and `fail_job` both set `dedupe_key = None` on reaching a terminal state ("Allow re-queuing"), and `get_job_by_dedupe_key` therefore only ever matches a job that is still live. So:

- Resubmitting while a send is in flight (`queued`/`running`/`retrying`) collides and is deduplicated — the double-click case.
- Sending the same text again after the first completed or failed creates a new job, because the key was released — the legitimate-repeat case.

This means the fix is confined to key composition. No windowing logic, no new state, no change to `JobService`.

One consequence to verify rather than assume: `handle_send_failure` and `delete_pending_message` also null the key, so a failed or user-deleted send frees the text for immediate resend. That is the intended behavior, but it should be asserted, not inferred.

### 4. Keep best-effort audit writes, but make failure observable

The `except` around `_create_audit_log` is deliberate: an audit-logging failure must not abort a user's delete. That stays. What changes is that the handler logs the exception with context instead of returning `None` silently — the property that let this bug live indefinitely. This is the generalizable lesson: *best-effort* is a legitimate choice, *silent* is not.

### 5. Fix the tests alongside, not afterward

Every defect here outlived a passing test. Each fix lands with an assertion that fails against the old behavior — verified by mutation, not by inspection. The two existing strict-`xfail` tests become normal assertions rather than being deleted, so the transition is visible in the diff.

## Risks / Trade-offs

**[Risk] Search result sets shrink for callers passing `exclude_visibility`.** Intended — those callers asked for exclusion and were being ignored. Anything depending on the current output depends on a spec violation. No known caller does; the UI passes the default.

**[Risk] Queue routing changes runtime task distribution.** Tasks currently pile onto the default `celery` queue; after the fix they spread across their declared queues. The worker's `-Q` covers all of them so nothing becomes unconsumed, but concurrency characteristics shift — notably, long analysis work stops sharing a queue with fast ingest work. That is the intent, and is why the change is worth making rather than deleting the routes.

**[Trade-off] Widening the ES client signature vs. complement enumeration.** Chosen for correctness on absent fields and resilience to new visibility values, at the cost of one more parameter.

**[Trade-off] Grouping five defects in one change.** They touch four subsystems and could be split. Kept together because the shared root cause is the most valuable finding, and splitting would scatter it across changes that each look like an isolated typo.

**[Risk] Dedupe becomes active where it never was.** With a stable key, a resubmit during an in-flight send now returns the existing job instead of creating a second one. That is the point, but it is a live behavior change on the send path: any UI that resubmits optimistically and expects a fresh `message_id` back will now receive the original. Worth checking the send route's response shape against the client before shipping.

**[Trade-off] Deduplicating identical text vs. allowing deliberate repeats.** Resolved in favor of deduplicating, on the judgment that two identical sends into one conversation are rare while double-submits are not. The window in which this bites is narrow — only while a send is in flight — because terminal jobs release the key.
