# Tasks: lead-triage-and-feedback

## 1. Schema & model

- [x] 1.1 Alembic migration: `lead_posts.priority` ENUM('high','medium','low') NULL, `lead_posts.compatibility_score` FLOAT NULL, extend `lead_posts.status` enum with `expired`, `scout_watch_posts.dismissed_at`/`triaged_at` DATETIME NULL, new `calibration_reports` table, index on `lead_posts (status, priority, created_at)`
- [x] 1.2 Update SQLAlchemy models to match; unit tests for new fields

## 2. Priority tiering

- [x] 2.1 Code-side priority derivation helper (meta `priority_level` + `compatibility_score` + gate outcomes → tier) with unit tests for the promote/demote thresholds
- [x] 2.2 Persist priority + compatibility in `scout.analyze_and_decide` lead creation and in `MultiAgentAnalysisService.analyze_lead` when updating a lead; tests
- [x] 2.3 `GET /leads`: default ordering priority→recency, expose `priority`/`compatibility_score` in responses; tests
- [x] 2.4 Leads page UI: priority badge + compatibility badge, default sort; keep explicit sort override

## 3. Auto-expiry

- [x] 3.1 `maintenance.expire_stale_leads` task (daily beat) with `LEAD_EXPIRY_DAYS` env (default 14, 0 disables), scout-only, dry-run mode, batch audit logging; unit tests
- [x] 3.2 `GET /leads` excludes `expired` by default; `status=expired` filter returns them; PATCH status accepts `expired` and revival; tests
- [x] 3.3 Leads page: expired hidden by default, filter option to show; revive action
- [x] 3.4 Backfill runbook: invoke task dry-run, review count (~2.7k expected), then live run; record both in audit — *superseded 2026-09-17: dry run done (1,876 would expire), live run never executed; expiry disabled by default in favour of a 14d posted-date filter*

## 4. Needs-review queue

- [x] 4.1 `GET /scout-watches/needs-review` cross-watch listing (cursor, watch context, dimension results); `POST /scout-watches/posts/{post_id}/dismiss` setting `dismissed_at` with audit; add-to-leads sets `triaged_at`; tests
- [x] 4.2 Retention exemption in `maintenance.cleanup_scout_watch_history` (`SCOUT_NEEDS_REVIEW_RETENTION_DAYS`, default 14; dismissed/triaged follow normal window from triage time); tests
- [x] 4.3 BFF proxy routes for the two new endpoints
- [x] 4.4 Leads page "Needs review" tab with queue count, promote/dismiss actions; empty & error states

## 5. Calibration report

- [x] 5.1 Report computation service (SQL aggregation: suitable→ignored/contacted rates, contacted→engaged, needs-review promote/dismiss + queue size, gate-failure distribution best-effort, dimension failure rates; per watch + overall); unit tests with seeded data
- [x] 5.2 `maintenance.generate_calibration_report` weekly beat task storing `calibration_reports` row; jobs-ledger idempotency; tests
- [x] 5.3 `GET /ops/calibration-reports` endpoint + BFF proxy; tests
- [x] 5.4 Ops page panel rendering the latest report (per-watch table, overall summary); empty & error states

## 6. Verification & docs

- [x] 6.1 Run pytest (core + worker) and `npm run lint`; verify no regressions in leads/scout/ops suites
- [x] 6.2 Verify end-to-end on dev data: priority ordering visible, needs-review tab populated, dry-run expiry count sane, first report generated manually
- [x] 6.3 Archive change: merge deltas into `openspec/specs/{leads,scout-watch,ops-jobs}/spec.md`; update CLAUDE.md task list (new maintenance tasks) and env docs (`LEAD_EXPIRY_DAYS`, `SCOUT_NEEDS_REVIEW_RETENTION_DAYS`)
