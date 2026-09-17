# ops-jobs Specification

## Purpose
All background work in Rediska is tracked through a `jobs` ledger that enforces idempotency across Celery retries, surfaced to the operator through the `/ops` API and Ops console. Every mutating action — user, system, or agent initiated — is recorded in an append-only `audit_log`. Metrics endpoints expose liveness, readiness, and queue/sync health.
## Requirements
### Requirement: Jobs ledger enforces idempotency

The `jobs` table SHALL act as the idempotency ledger for background work: each job carries a `job_type`, JSON payload, a unique `dedupe_key`, `attempts`/`max_attempts` counters, and a status in `queued`, `running`, `retrying`, `failed`, `done`, or `cancelled`. Celery tasks SHALL register in this ledger so that duplicate enqueues of the same logical work are deduplicated.

#### Scenario: Duplicate enqueue is deduplicated

- **WHEN** a task is enqueued whose computed `dedupe_key` matches an existing non-terminal job
- **THEN** no second job row is created and the existing job continues to represent the work

#### Scenario: Retry exhaustion

- **WHEN** a job fails and its `attempts` reaches `max_attempts`
- **THEN** the job status becomes `failed` with `last_error` recorded
- **AND** the job remains queryable through the ops API for manual retry

### Requirement: Ops API exposes job and sync operations

The core API SHALL expose under `/ops`: job listing (`GET /ops/jobs`), status counts (`GET /ops/jobs/counts`), job detail (`GET /ops/jobs/{id}`), manual retry (`POST /ops/jobs/{id}/retry`), conversation backfill (`POST /ops/backfill/conversations`, `GET /ops/backfill/{job_id}`), a consistency check (`POST /ops/consistency/check`), attachment re-download (`POST /ops/redownload/attachments`), and per-identity sync status (`GET /ops/sync/status`).

#### Scenario: Operator retries a failed job

- **WHEN** the operator calls `POST /ops/jobs/{id}/retry` for a `failed` job
- **THEN** the job is re-enqueued and its status returns to `queued`/`retrying`
- **AND** the retry is written to the audit log

#### Scenario: Sync status per identity

- **WHEN** the operator calls `GET /ops/sync/status`
- **THEN** the response reports sync state for each configured identity

### Requirement: Ops console surfaces the ledger

The web app SHALL provide an `/ops` page showing the job queue table with per-status counts (queued/running/retrying/failed/done/cancelled), per-job retry actions, manual conversation sync with result details, backfill triggers, attachment re-download, and per-identity sync status.

#### Scenario: Viewing queue health

- **WHEN** the operator opens `/ops`
- **THEN** current job counts by status and the recent job list are displayed without requiring CLI access

### Requirement: Metrics endpoints report service health

The core API SHALL expose `GET /api/health` (liveness), `GET /api/ready` (readiness), and `GET /api/metrics` with sub-resources `/api/metrics/queues` (Celery queue depths), `/api/metrics/sync`, and `/api/metrics/application`.

#### Scenario: Readiness gate

- **WHEN** a dependency required to serve traffic is unavailable
- **THEN** `GET /api/ready` reports not-ready while `GET /api/health` still reports process liveness

### Requirement: Every mutating endpoint writes the audit log

Every endpoint that mutates state SHALL append an `audit_log` row recording the actor (`user`, `system`, or `agent`), the acting identity where applicable, the action type, entity type/id, request and response JSON, and the result (`ok`/`error` with error detail). The audit log SHALL be append-only: no API deletes or rewrites entries.

#### Scenario: Mutation is audited

- **WHEN** any mutating request completes (success or failure)
- **THEN** exactly one audit row exists for it with actor, action_type, and result populated

#### Scenario: No deletion path

- **WHEN** any client attempts to remove or alter an existing audit entry via the API
- **THEN** no such endpoint exists and the entry is preserved

### Requirement: Audit viewer with filters

The system SHALL expose `GET /audit` with cursor pagination and filters (actor, action type, result, identity), and the web app SHALL render it at `/audit` with expandable request/response JSON per entry.

#### Scenario: Filtering by actor

- **WHEN** the user filters the audit page by actor `agent`
- **THEN** only entries recorded with actor `agent` are listed, newest first, with cursor-based paging

### Requirement: Weekly calibration report

A weekly beat task (`maintenance.generate_calibration_report`) SHALL compute a calibration snapshot from already-recorded data (`lead_posts` statuses, `external_accounts` engagement state, `analysis_dimensions`, scout post triage markers, `audit_log`) and store it as a `calibration_reports` row (period, JSON payload). The payload SHALL include, per watch and overall: suitable→ignored rate, suitable→contacted rate, contacted→engaged rate, needs-review promote/dismiss counts and queue size, gate-failure distribution (best-effort until structured gate results exist), and per-dimension failure rates. The report SHALL involve no LLM calls.

#### Scenario: Weekly snapshot is stored

- **WHEN** the weekly beat fires
- **THEN** a new `calibration_reports` row exists covering the elapsed period with per-watch and overall metrics

#### Scenario: Report reflects user verdicts

- **WHEN** the user ignored most leads a watch produced during the period
- **THEN** that watch's suitable→ignored rate in the report reflects it

### Requirement: Calibration reports are exposed via the ops API and console

The core API SHALL expose `GET /ops/calibration-reports` (list, newest first) and `POST /ops/calibration-reports/generate` (queue a report for the period ending now; audit-logged; at most one stored report per day via the `jobs` ledger). The latest report SHALL be rendered as a panel on the `/ops` page, showing overall and per-watch precision signals, gate outcomes, and dimension failure rates so threshold and prompt tuning is evidence-driven, with a selector for earlier reports and empty and error states.

#### Scenario: Operator reviews the latest report

- **WHEN** the operator opens `/ops`
- **THEN** the latest calibration report panel shows overall and per-watch rates without requiring database access

