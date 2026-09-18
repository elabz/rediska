## Context

An import audit on 2026-09-18 found code that no production path reaches:

| Item | Size | Referenced by |
|---|---|---|
| `worker/tasks/agent.py` (`agent.profile_summary`, `agent.lead_scoring`, `agent.draft_intro`) | 25 lines | Celery include list, `agent.*` route, routing test. No `send_task`, no beat entry, no API dispatch. Bodies return `not_implemented`. |
| `domain/services/lead_scoring.py` | 416 lines | 2 test files only |
| `domain/services/profile_summary.py` | 461 lines | 2 test files only |
| `domain/services/draft_intro.py` | 523 lines | 2 test files only |
| `domain/services/duplicate_detection.py` | 838 lines | 2 test files only |
| `domain/services/sync_status.py` | 255 lines | 1 test file only |
| `domain/services/data_safety.py` | 542 lines | 1 test file only, **but normative in `ops-jobs`** |
| `nginx/` | 44 KB | README + CLAUDE.md "legacy reference" notes |
| `scripts/tasks/` | 2 shell scripts | nothing |
| `tasks/` (13 files), `prd/*_v0.*` (4 files) | 250 KB | CLAUDE.md doc map (2 design docs cited) |

Modules that look legacy but are live and stay: `analysis.py` (profile fetch pipeline, used by `leads.py` and `ingest.py`), `agent.py` (the agent harness every dimension agent builds on), `character_summary.py`, `interests_summary.py`, `remote_status.py`.

Constraints: the core (1770) and worker (102) suites are fully green in Docker, so any failure after this change is a real regression. Task names are a public contract (jobs ledger, `send_task`), so removing one needs proof that nothing sends it.

## Goals / Non-Goals

**Goals:**
- Every module left in `domain/services/` and every registered Celery task is reachable from a route, a task, or beat.
- One obvious answer to "where are leads scored": `lead_gates.py` + `lead_priority.py`.
- Docs describe only what exists.

**Non-Goals:**
- Behaviour changes, migrations, data deletion, deployment decisions, frontend pruning (see proposal).

## Decisions

**1. Two tiers: certain removals and audited removals.**
Tier A (stub tasks, `lead_scoring.py`, `nginx/`, `scripts/tasks/`) is removed outright; the evidence is already conclusive. Tier B (`profile_summary.py`, `draft_intro.py`, `duplicate_detection.py`, `sync_status.py`) is removed only after a fresh audit at apply time that checks more than static imports: string-based `send_task`/`importlib` references, `__init__.py` re-exports, the web app, `scripts/`, and the OpenSpec specs. *Alternative considered:* delete everything test-only in one sweep. Rejected because `data_safety.py` shows that "test-only" and "unwanted" are different things.

**2. Tier B modules default to delete, not park.**
Git history preserves them; a parked module still rots against model changes and still costs test time. The exception is an explicit user call to keep one as a building block. `draft_intro.py` and `duplicate_detection.py` are the two most likely to be wanted back (see Open Questions). *Alternative:* move to an `attic/` package. Rejected: it keeps the import graph confusing, which is the problem being solved.

**3. `data_safety.py` stays and gets a follow-up note, not a deletion.**
Its audit behaviour was specified in `ops-jobs` on 2026-09-18. A spec'd service with no caller is a wiring gap, not dead weight. The task list records it as a finding for a separate change.

**4. Remove the `agent` queue entirely.**
With the three stubs gone, no task routes to `agent`. The route, the `-Q` entry, and the CLAUDE.md queue list entry go together, so `test_task_routing_unit.py` (which fails on dead patterns) stays meaningful. Before deploy, confirm the Redis list for the `agent` queue is empty. Queue length only is inspected, never message bodies.

**5. History moves, it is not deleted.**
`tasks/` and `prd/*_v0.*` go to `docs/history/` via `git mv` so blame survives. CLAUDE.md's doc map is updated to the new paths. `prd/Rediska_PRD_v1.0.md` stays in place.

**6. One commit per tier.**
Tier A, each Tier B module, and the docs move land as separate commits so any single removal can be reverted alone.

## Risks / Trade-offs

- [A dynamic reference the static audit missed] → Tier B audit greps string literals and task names, then the full core + worker suites run in Docker, then the stack is started and the worker log checked for import errors and unregistered-task warnings.
- [A message already queued for a removed task] → queue-length check before deploy; the stubs did nothing, so a dropped message loses no work.
- [Test count drops and hides a regression] → record the before/after counts per removed test file in the commit message; the delta must equal the tests deleted.
- [Moved docs break links] → grep for `tasks/` and `prd/` paths across `*.md` and `openspec/` after the move.
- [Removing something the user planned to revive] → Open Questions below are answered before Tier B starts.

## Migration Plan

1. Land Tier A, run both suites, rebuild and restart `rediska-worker` and `rediska-beat`.
2. Land Tier B module by module, suites after each.
3. Land the docs move and spec sync.
Rollback is `git revert` of the relevant commit plus a worker restart. No data or schema is involved.

## Open Questions

- Keep `draft_intro.py` as the seed for an LLM-drafted first message in the inbox, or delete and rebuild when that feature is proposed?
- Keep `duplicate_detection.py` (username and image-hash account matching)? It is unrelated to the lead dedupe merge that already ran, and nothing surfaces its output.
- Is `sync_status.py` dead because `ingest.py` reimplemented the no-remote-delete updates inline, or because the behaviour is missing? If missing, that is a bug to file, not a deletion.
