## Why

Rediska currently runs on the development workstation. We need to relocate it to a dedicated on-prem server (VPN-reachable, self-signed TLS) and have the procedure written down so it is repeatable, auditable, and survives operator turnover. Existing dev-box data (DB, attachments, optionally the Elasticsearch index) must come with it. There is no checklist today for verifying the system is healthy after a move; the implicit smoke test lives only in our heads.

## What Changes

- Introduce a new top-level `docs/` directory and create `docs/deploy.md` — the canonical operator-facing guide.
- Document the full bring-up of a new internal server: prerequisites, bootstrap, first boot, smoke test, troubleshooting.
- Define a ≤10-item smoke-test checklist that an operator can run in ~5 minutes after any deploy or migration.
- Document a migration procedure for moving full data (MySQL dump, attachments rsync, Elasticsearch via worker reindex by default; snapshot/restore as alternative) from the dev box.
- Add supporting scripts under `scripts/deploy/` only where the procedure benefits from a one-shot helper (smoke test runner, migration helpers).
- Update `CLAUDE.md` so the project guide references `docs/deploy.md` as the deploy source of truth.

## Capabilities

### New Capabilities
- `deployment-procedure`: Operator-facing requirements for the manual deployment + smoke-test + migration procedure to an on-prem server.

### Modified Capabilities
<!-- None. -->

## Impact

- **New directory**: `docs/`.
- **New files**: `docs/deploy.md`, possibly `scripts/deploy/smoke_test.sh`, `scripts/deploy/migrate_from_dev.sh`.
- **Modified files**: `CLAUDE.md` (cross-reference).
- **Out-of-scope but adjacent**: GitHub Action automation lives in change `github-action-deployment` (parallel proposal).
- **Risk surface**: this is a procedural change — the doc is the deliverable. The risk is the doc going stale; mitigation is to keep it executable (operator should be able to follow it verbatim).
