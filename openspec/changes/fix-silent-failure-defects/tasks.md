## 0. Already remediated (verify only)

- [x] 0.1 Confirm `data_safety._create_audit_log` uses real `AuditLog` columns (`ts`/`actor`/`action_type`/`request_json`/`result`) and logs on failure
- [x] 0.2 Confirm `test_soft_delete_creates_audit_log` and `test_purge_creates_audit_log` assert the `AuditLog` row, and fail when the old kwargs are restored
- [x] 0.3 Confirm `StructuredLogger._log` passes `stacklevel=3` and `test_log_error_with_exception` asserts the caller's file/function

## 1. Search honors `exclude_visibility`

- [x] 1.1 Add negative-clause support to `ElasticsearchClient.search` (a `must_not` list alongside the existing `filters`), placed in the `bool` query beside `must`/`filter`
- [x] 1.2 Unit-test the client builds `must_not` with a `terms` clause for a multi-value exclusion and omits the key entirely when nothing is excluded
- [x] 1.3 Apply `exclude_visibility` in `SearchService._build_filters` (or a sibling that returns negative clauses) and thread it through `text_search`, `vector_search`, and `hybrid_search`
- [x] 1.4 Verify a document with no `remote_visibility` field is NOT excluded — assert this explicitly, it is the reason `must_not` was chosen over enumerating the complement
- [x] 1.5 Make the default-exclusion path real: confirm the existing "Remote-deleted content excluded by default" scenario now holds end-to-end, since it does not today
- [x] 1.6 Convert the two strict-`xfail` tests in `tests/test_search_unit.py` to normal assertions and confirm they fail against the pre-fix code
- [x] 1.7 Make an inapplicable filter fail the request rather than return unfiltered results (confirmed decision). Raise at the point the filter is found to be unusable, and assert the request errors instead of silently widening the result set

## 2. Celery queue routing becomes effective

- [x] 2.1 Rewrite each `rediska_worker.tasks.<module>.*` key in `celery_app.py` `task_routes` to the registered short-name form (`ingest.*`, `index.*`, `embed.*`, `agent.*`, `maintenance.*`, `message.*`, `multi_agent_analysis.*`)
- [x] 2.2 Assert against the LIVE router, not the declared dict: for each registered task name, resolve its route and assert the expected queue
- [x] 2.3 Add a guard test that every routing pattern matches at least one registered task, so a future dead pattern fails
- [x] 2.4 Update the worker routing tests that currently assert the declared config with a "does not actually match" comment
- [x] 2.5 Confirm `services/worker/Dockerfile`'s `-Q` list covers every queue now reachable, so no task becomes unconsumed
- [x] 2.6 Sanity-check beat-scheduled tasks still land on their intended queues

## 3. Send dedupe key becomes stable

Decided: keep `dedupe=True`, make the key stable, no time window. Terminal jobs
already release the key (`complete_job` / `fail_job` set `dedupe_key = None`),
so in-flight resubmits collide while later repeats do not.

- [x] 3.1 Compute the dedupe key in `enqueue_send` from caller-stable inputs only — conversation id, identity id, body fingerprint — before the `Message` row is created
- [x] 3.2 Confirm no minted identifier (`message_id`, job id, timestamp) enters the key; that is precisely what makes the current key unable to collide
- [x] 3.3 Comment the call site with the reasoning, so a future reader does not re-derive whether a time window is needed
- [x] 3.4 Test the double-submit case: two identical `enqueue_send` calls while the first is in flight produce exactly one `Job` and one `Message`
- [x] 3.5 Test the legitimate-repeat case: after the first job reaches a terminal state, an identical send creates a NEW job and message. This is the test that would have caught a naive always-dedupe implementation
- [x] 3.6 Assert (don't assume) that `handle_send_failure` and `delete_pending_message` free the key, so a failed or user-deleted send can be resent immediately
- [x] 3.7 Confirm at-most-once still holds: one explicit POST produces exactly one Celery dispatch and one `Message` row
- [x] 3.8 Confirm manual retry still creates a new job with `max_attempts=1` and exactly one additional dispatch
- [x] 3.9 Check the send route's response shape against the web client — a deduplicated resubmit now returns the ORIGINAL job/message rather than a new one

## 4. Regression guards for the shared root cause

- [x] 4.1 For every fix above, verify by mutation that the new test fails against the old behavior — inspection is not sufficient, this is how all five defects survived
- [x] 4.2 Keep the AST scan for statement-free and assertion-free tests at zero (`services/*/tests/test_*.py`)
- [x] 4.3 Grep for other `except Exception` handlers that `return None`/`pass` without logging, and list them — do not fix them here, that is a non-goal, but the list informs a follow-up

## 5. Verification

- [x] 5.1 Full core suite green with no new skips or xfails
- [x] 5.2 Full worker suite green
- [x] 5.3 `npm run lint` and `npx tsc --noEmit` clean in `apps/web`
- [x] 5.4 Rebuild the worker image if the `-Q` list changed, and confirm each queue is consumed
- [x] 5.5 Update `CLAUDE.md` if the queue-routing description no longer matches reality

## Resolved decisions

Both open questions from the original proposal are settled; recorded here so
implementation does not re-litigate them.

- **1.7 — an inapplicable filter fails the request.** Returning unfiltered results when a supplied filter cannot be applied is not acceptable; the request errors instead. This is the same failure mode as the bug being fixed, one layer up.
- **3.1 — keep dedupe, with a stable key.** Two identical sends into one conversation are rare; double-submits are not. No time window is needed: `complete_job` and `fail_job` already null the `dedupe_key`, so the guard only ever matches a live job.
