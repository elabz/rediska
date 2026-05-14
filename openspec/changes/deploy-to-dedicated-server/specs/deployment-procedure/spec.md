## ADDED Requirements

### Requirement: Operator-facing deploy guide

The repository SHALL contain a single canonical deploy document at `docs/deploy.md` that walks an operator through bringing Rediska up on a fresh internal Linux server from cold start to a passing smoke test.

#### Scenario: Fresh-server bring-up

- **WHEN** an operator with shell access to a blank Linux server (Docker not yet installed) follows `docs/deploy.md` end-to-end
- **THEN** Rediska is reachable at the documented internal hostname over HTTPS and all smoke-test items pass without referencing any source outside the repo

#### Scenario: Operator turnover

- **WHEN** a new operator (not the original deployer) follows the same doc against an identical fresh server
- **THEN** they reach the same passing-smoke-test state without needing direct help from the original deployer

### Requirement: Smoke-test checklist

The deploy doc SHALL include a smoke-test checklist with no more than 10 items, completable in approximately 5 minutes, each item a clear pass/fail signal. The checklist MUST verify, at minimum, container health, HTTPS reachability, login, worker liveness, and Alembic at the head revision.

#### Scenario: Smoke test after fresh deploy

- **WHEN** the operator finishes the deploy procedure on a blank server and runs the smoke-test checklist
- **THEN** every item passes, or any failing item points back to a specific troubleshooting section in the doc

#### Scenario: Smoke test as ongoing health probe

- **WHEN** the operator runs the smoke test on an already-deployed server (e.g., after a docker compose pull)
- **THEN** the same checklist is reusable and produces the same pass/fail signals without setup

### Requirement: Full-data migration from dev to new server

The deploy doc SHALL describe a reversible procedure to migrate the operator's existing dev-box state (MySQL database, `/var/lib/rediska/attachments`, and Elasticsearch content) to the new server, with a clearly-marked rollback path if the new server fails its smoke test.

#### Scenario: Successful migration

- **WHEN** the operator follows the migration section and the new server passes the smoke test
- **THEN** the new server contains all dev-box conversation, attachment, and search data, and the dev box remains untouched as a safety net

#### Scenario: Migration fails smoke test

- **WHEN** the new server fails any smoke-test item after migration
- **THEN** the doc directs the operator to a rollback procedure that returns to using the dev box without any state loss

### Requirement: Idempotent procedure

Each command shown in the deploy doc SHALL be safe to re-run on a partially-set-up host without corrupting state, OR be clearly flagged as one-shot with a guard the operator can check before re-running.

#### Scenario: Re-running compose up after partial install

- **WHEN** the operator re-runs `docker compose up -d` after a previous run was interrupted
- **THEN** the stack converges to the documented state without losing data
