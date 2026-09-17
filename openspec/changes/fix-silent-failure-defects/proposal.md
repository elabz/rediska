## Why

A test-quality audit of the whole suite found five production defects that share one shape: **code that reports success while doing nothing**. Each was masked by a test that asserted the happy-path return value instead of the effect, so all five sat green in CI. Two are already remediated in the working tree; three remain. Three of the five violate requirements the specs already state.

The unifying failure mode matters more than any single bug: a swallowed exception, a dropped parameter, and two never-matching pattern lists all produced "working" code paths that silently did nothing. Where the system chooses best-effort behavior, that choice must be *observable* rather than silent.

## What Changes

- **Search honors caller-supplied visibility exclusions.** `SearchService._build_filters` accepts `exclude_visibility` and never reads it. The parameter is plumbed from `api/routes/search.py` through all three search modes and then discarded, so remote-deleted and removed content is returned to callers who explicitly asked to exclude it. Requires `must_not` support in the Elasticsearch client, which today builds only positive `term`/`terms` filter clauses. **This also means the existing "Remote-deleted content excluded by default" scenario is not currently satisfied.**
- **Celery queue routing becomes effective.** Every `rediska_worker.tasks.<module>.*` key in `task_routes` is dead: tasks register under short names (`ingest.sync_delta`, `message.send_manual`), which those module-path globs never match. All such tasks fall through to the default `celery` queue, so the per-queue isolation the config expresses does not happen. Only the name-shaped `scout.*` and `inbox.*` entries work.
- **Send dedupe keys become stable.** `enqueue_send` passes `dedupe=True`, but creates the `Message` row first and then hashes a payload containing that freshly-generated `message_id`. Two identical calls therefore always produce different keys, so the dedupe guard can never fire. The guard itself works; it is simply unreachable from this call site.
- **Audit-log writes for destructive operations are correct and observable.** *(Already remediated.)* `DataSafetyService._create_audit_log` constructed `AuditLog` with column names the model does not have (`action`/`actor_id`/`details`/`created_at` vs `action_type`/`actor`/`request_json`/`ts`), raising `TypeError` into a bare `except: return None`. No soft-delete and no purge had ever been audited. The best-effort catch is retained so a logging failure cannot abort a delete, but it now logs the exception rather than failing silently.
- **Structured logs attribute their real call site.** *(Already remediated.)* `StructuredLogger._log` called `.log()` without `stacklevel`, so `JsonFormatter`'s `source` block reported `observability/logging.py` in `_log` for every WARNING-and-above record in the codebase.

## Capabilities

### New Capabilities

<!-- None. Every defect violates or refines an existing capability. -->

### Modified Capabilities

- `search-indexing`: strengthen "Search results are filterable by document type and visibility" — an explicit caller-supplied visibility exclusion list SHALL be applied to the query, and the existing default-exclusion scenario SHALL actually hold.
- `ops-jobs`: strengthen "Jobs ledger enforces idempotency" — a dedupe key SHALL be derived only from caller-stable inputs, never from identifiers minted during the same enqueue. Add a requirement that declared queue routing is effective, and that best-effort audit-log writes surface their failures instead of passing silently.

## Impact

**Affected code**
- `services/core/rediska_core/domain/services/search.py` — `_build_filters` must apply `exclude_visibility`
- `services/core/rediska_core/infrastructure/elasticsearch.py` — `search()` must support negative (`must_not`) clauses; today it builds only `term`/`terms` filters
- `services/worker/rediska_worker/celery_app.py` — `task_routes` keys must match registered task names
- `services/core/rediska_core/domain/services/send_message.py` — `enqueue_send` dedupe key composition
- `services/core/rediska_core/domain/services/data_safety.py` — *(done)* `_create_audit_log` column names + exception visibility
- `services/core/rediska_core/observability/logging.py` — *(done)* `stacklevel=3`

**Behavioral impact**
- Search result sets change for any caller passing `exclude_visibility` — previously-returned deleted/removed documents will disappear. This is the intended contract; callers relying on the buggy output would be relying on a spec violation.
- Fixing queue routing moves tasks off the default `celery` queue onto their declared queues. The worker's `-Q` list already includes every queue, so no task becomes unconsumed, but relative throughput and contention change.
- Send dedupe becomes active. Because sends already require an explicit user POST and dispatch exactly once, at-most-once semantics are unaffected either way; the change removes dead protection rather than adding a new guarantee.

**Tests**
- Two strict-`xfail` tests in `services/core/tests/test_search_unit.py` currently pin the search defects and will fail (as designed) once fixed — they must be converted to normal assertions.
- Worker routing tests assert the declared config with a comment noting it is ineffective; they should assert against the live router instead.

**Not affected**: no schema migration, no API surface change, no new dependency.

## Non-goals

- **Auditing the rest of the suite for this pattern.** The completed audit covered every test file; this change fixes what it found and does not open a broader hunt.
- **Reworking the `except Exception` best-effort style generally.** Only the data-safety audit path is in scope. A codebase-wide policy on swallowed exceptions is a separate discussion.
- **Adding retry or delivery guarantees to messaging.** At-most-once and no-autosend already hold and are unchanged here.
- **Restructuring `send_manual`'s imports.** The worker task imports `rediska_core` symbols above its payload validation, which makes that branch unreachable off-container; tests now stub the modules instead. Reordering the source is deferred.
- **Fixing the latent `AgentHarness` max-turns path**, which returns `success=True` without running `_parse_structured_output`. It is unreachable today because the loop body ends in an unconditional `break`, and becomes live only when tool-call continuation is implemented.
