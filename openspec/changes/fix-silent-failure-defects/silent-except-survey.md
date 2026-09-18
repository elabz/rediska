# Silent broad-except handlers (survey only — not fixed here)

Task 4.3 output. Reworking the `except Exception` best-effort style generally
is an explicit **non-goal** of this change; only the `data_safety` audit path
was in scope. This list exists so a follow-up has a starting point rather than
a fresh hunt.

Criterion: a bare `except` or `except Exception` whose whole body is `pass`,
`continue`, or `return None`, with no logging call anywhere in the handler.
Produced by an AST scan over `services/*/rediska_*/**/*.py`, excluding tests.

Many of these are legitimately best-effort (cache reads, cleanup paths,
optional metrics). The defect is not the catch — it is that a failure leaves
no trace, which is what let the `data_safety` audit bug live indefinitely.
Triage should ask, per site: *if this silently did nothing forever, how would
anyone find out?*

- `services/core/rediska_core/api/middleware/onboarding.py:79` — `dispatch()` → `pass`
- `services/core/rediska_core/domain/services/attachment.py:486` — `_extract_dimensions_manual()` → `pass`
- `services/core/rediska_core/domain/services/audit.py:246` — `_decode_cursor()` → `return None`
- `services/core/rediska_core/domain/services/data_safety.py:438` — `purge()` → `pass`
- `services/core/rediska_core/domain/services/external_listing.py:331` — `_cache_get()` → `return None`
- `services/core/rediska_core/domain/services/external_listing.py:340` — `_cache_set()` → `pass`
- `services/core/rediska_core/domain/services/message_sync.py:211` — `_download_image()` → `return None`
- `services/core/rediska_core/domain/services/restore_service.py:225` — `_cleanup_container()` → `pass`
- `services/core/rediska_core/domain/services/restore_service.py:230` — `_cleanup_container()` → `pass`
- `services/core/rediska_core/domain/services/restore_service.py:399` — `_sample_attachments()` → `pass`
- `services/core/rediska_core/infrastructure/elasticsearch.py:349` — `get_document()` → `return None`
- `services/core/rediska_core/observability/metrics.py:260` — `_get_redis()` → `return None`
- `services/core/rediska_core/observability/metrics.py:309` — `collect_sync_times()` → `pass`
- `services/worker/rediska_worker/tasks/maintenance.py:421` — `restore_test_local()` → `pass`
- `services/worker/rediska_worker/tasks/maintenance.py:423` — `restore_test_local()` → `pass`
- `services/worker/rediska_worker/tasks/maintenance.py:458` — `restore_test_local()` → `pass`
- `services/worker/rediska_worker/tasks/maintenance.py:462` — `restore_test_local()` → `pass`
- `services/worker/rediska_worker/tasks/scout.py:480` — `run_single_watch()` → `pass`
- `services/worker/rediska_worker/tasks/scout.py:1230` — `analyze_and_decide()` → `pass`
- `services/worker/rediska_worker/tasks/scout.py:1371` — `reanalyze_post()` → `pass`

## Suggested triage order

1. `data_safety.py:438` — `purge()` file removal. A destructive operation
   whose file-deletion failures vanish; the sibling of the bug this change
   fixed.
2. `scout.py:1230`, `scout.py:1371` — inside the analysis pipeline, where a
   swallowed failure looks like "no result" rather than "it broke".
3. `message_sync.py:211` — `_download_image()` returning `None` is
   indistinguishable from "no image was there".
4. The rest (caches, metrics, restore-test cleanup, onboarding middleware) are
   low-stakes best-effort and may be fine as they are, but should at least be
   confirmed deliberate.
