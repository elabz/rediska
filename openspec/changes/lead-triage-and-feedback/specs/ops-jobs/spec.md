# ops-jobs Specification (delta)

## ADDED Requirements

### Requirement: Weekly calibration report

A weekly beat task (`maintenance.generate_calibration_report`) SHALL compute a calibration snapshot from already-recorded data (`lead_posts` statuses, `external_accounts` engagement state, `analysis_dimensions`, scout post triage markers, `audit_log`) and store it as a `calibration_reports` row (period, JSON payload). The payload SHALL include, per watch and overall: suitable→ignored rate, suitable→contacted rate, contacted→engaged rate, needs-review promote/dismiss counts and queue size, gate-failure distribution (best-effort until structured gate results exist), and per-dimension failure rates. The report SHALL involve no LLM calls.

#### Scenario: Weekly snapshot is stored

- **WHEN** the weekly beat fires
- **THEN** a new `calibration_reports` row exists covering the elapsed period with per-watch and overall metrics

#### Scenario: Report reflects user verdicts

- **WHEN** the user ignored most leads a watch produced during the period
- **THEN** that watch's suitable→ignored rate in the report reflects it

### Requirement: Calibration reports are exposed via the ops API and console

The core API SHALL expose `GET /ops/calibration-reports` (list, newest first) and the latest report SHALL be rendered as a panel on the `/ops` page, showing per-watch precision signals and dimension failure rates so threshold and prompt tuning is evidence-driven.

#### Scenario: Operator reviews the latest report

- **WHEN** the operator opens `/ops`
- **THEN** the latest calibration report panel shows overall and per-watch rates without requiring database access
