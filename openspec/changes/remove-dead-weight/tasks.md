## 1. Baseline

- [ ] 1.1 Run the core and worker suites in Docker and record the passing counts (expected 1770 / 102)
- [ ] 1.2 Record the number of tests in each test file slated for deletion
- [ ] 1.3 Check the `agent` queue length in Redis db 1 is zero (length only, never message bodies)

## 2. Tier A: certain removals

- [ ] 2.1 Delete `services/worker/rediska_worker/tasks/agent.py`; remove it from the `include` list and drop the `agent.*` entry from `task_routes` in `celery_app.py`
- [ ] 2.2 Remove `agent` from the `-Q` list in `services/worker/Dockerfile` (and any compose override that repeats it)
- [ ] 2.3 Remove the three `agent.*` rows from `services/worker/tests/test_task_routing_unit.py`; confirm the dead-pattern check still passes
- [ ] 2.4 Delete `domain/services/lead_scoring.py`, `tests/test_lead_scoring_agent_unit.py`, `tests/test_lead_scoring_integration.py`
- [ ] 2.5 Delete `nginx/` and `scripts/tasks/`
- [ ] 2.6 Run both suites; confirm the count delta equals the deleted tests; commit

## 3. Tier B: audited removals

- [ ] 3.1 Resolve the three Open Questions in design.md with the user (keep or delete `draft_intro.py`, `duplicate_detection.py`; confirm `sync_status.py` behaviour exists elsewhere)
- [ ] 3.2 For each of `profile_summary.py`, `draft_intro.py`, `duplicate_detection.py`, `sync_status.py`: grep class names, function names, and module name as string literals across `services/`, `apps/web/src`, `scripts/`, `openspec/specs/`; record the result in the commit message
- [ ] 3.3 Delete each module that passed the audit together with its test files, one commit per module, suites green after each
- [ ] 3.4 If `sync_status.py` turns out to cover behaviour nothing else implements, stop, keep it, and file the gap as a separate change
- [ ] 3.5 Record `data_safety.py` as "spec'd in ops-jobs, no production caller" in a follow-up note under `openspec/changes/` or an issue; do not delete it

## 4. Docs and history

- [ ] 4.1 `git mv tasks/ docs/history/tasks/` and `git mv` the four `prd/*_v0.*` files to `docs/history/prd/`
- [ ] 4.2 Update CLAUDE.md: documentation map paths, repository structure tree (no `nginx/`, no `scripts/tasks/`), Celery queue list (no `agent`), remove the `agent.profile_summary` / `agent.lead_scoring` / `agent.draft_intro` line
- [ ] 4.3 Update README.md: drop the legacy `nginx/` note and fix the `tasks/` path
- [ ] 4.4 Grep all `*.md` and `openspec/` for `nginx/`, `scripts/tasks`, `tasks/`, `prd/` paths and fix or remove stale links

## 5. Verify and ship

- [ ] 5.1 Full core + worker suites green in Docker; `npm run lint` and `npm test` green in `apps/web`
- [ ] 5.2 Rebuild and restart `rediska-worker` and `rediska-beat`; confirm the worker log lists no `agent.*` tasks, no import errors, and beat schedules normally
- [ ] 5.3 Sync the `deployment-platform` delta into `openspec/specs/`, diff the synced spec, then archive the change
