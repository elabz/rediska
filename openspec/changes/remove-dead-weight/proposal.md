## Why

The repo carries code and documents that were superseded but never removed: three Celery tasks that only return `not_implemented`, a single-agent lead scorer replaced by the multi-agent pipeline, several services that nothing but their own tests import, a retired nginx config, and task-tracking scripts from before OpenSpec. They cost test time, mislead anyone (human or AI) reading the code for "how leads are scored", and make every future change on the matching pipeline harder to reason about. The upcoming match-profile work touches exactly this area, so the ground should be cleared first.

## What Changes

- **Remove the three stub Celery tasks** `agent.profile_summary`, `agent.lead_scoring`, `agent.draft_intro` (`services/worker/rediska_worker/tasks/agent.py`). Nothing dispatches them; each returns `{"status": "not_implemented"}`. Remove the module from the Celery `include` list, the `agent.*` route, the `agent` queue from the worker `-Q` list, and their rows in `test_task_routing_unit.py`. **BREAKING** only for a caller that does not exist.
- **Remove the legacy single-agent lead scorer** `domain/services/lead_scoring.py` and its two test files. Lead scoring is done by `lead_gates.py` + `lead_priority.py` over the multi-agent output.
- **Remove test-only services after a per-module reference audit** (each is imported by nothing except its own tests): `profile_summary.py`, `draft_intro.py`, `duplicate_detection.py`, `sync_status.py`, with their tests. Each removal is gated on the audit in design.md; a module that turns out to be referenced, or that the user wants kept as a future building block, is kept and recorded as such.
- **Keep `data_safety.py`** even though only tests import it: its soft-delete/purge audit behaviour is normative in `ops-jobs` (added by `fix-silent-failure-defects`). It is listed here only so the audit records the decision.
- **Delete the retired `nginx/` directory** and the README/CLAUDE.md sentences that call it "legacy reference". The live vhost config lives in the dev-proxy repo.
- **Delete `scripts/tasks/`** (pre-OpenSpec task helpers) and move `tasks/` and the superseded `prd/*_v0.*` files under `docs/history/`, keeping the two design docs that CLAUDE.md still cites reachable.
- **Correct the docs to match reality**: CLAUDE.md, README and the Celery task list no longer mention the removed tasks, queue, or directories.

## Non-goals

- No behaviour change to analysis, gating, scoring, scout, inbox, or search. This change deletes unreachable code only.
- No database migration and no data deletion. Tables, rows, attachments, and backups are untouched.
- Not resolving the two open deployment changes (`deploy-to-dedicated-server`, `github-action-deployment`) or the CD workflow; whether the on-prem deployment is still wanted is a separate decision.
- Not refactoring the `infra/` vs `infrastructure/` split, and not pruning unused frontend components (candidate for a follow-up).
- Not introducing the configurable match profile; that is its own change.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `deployment-platform`: the "TLS terminates at the external dev-proxy" requirement stops describing an in-repo `nginx/` directory, because the directory is deleted.

## Impact

- **Worker**: `tasks/agent.py` deleted; `celery_app.py` include list and `task_routes`; `services/worker/Dockerfile` `-Q` list; `tests/test_task_routing_unit.py`.
- **Core**: up to five modules under `domain/services/` (about 2,500 lines) and their tests (about nine test files). Core suite count drops; it must stay fully green.
- **Repo layout**: `nginx/`, `scripts/tasks/` removed; `tasks/` and old PRD files moved to `docs/history/`.
- **Docs**: `CLAUDE.md`, `README.md`, `openspec/specs/deployment-platform/spec.md`.
- **Operations**: a worker restart picks up the new queue list. Any message left on the `agent` queue would be orphaned; the queue is checked empty before deploy.
