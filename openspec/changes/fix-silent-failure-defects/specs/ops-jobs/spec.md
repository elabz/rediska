## MODIFIED Requirements

### Requirement: Jobs ledger enforces idempotency

The `jobs` table SHALL act as the idempotency ledger for background work: each job carries a `job_type`, JSON payload, a unique `dedupe_key`, `attempts`/`max_attempts` counters, and a status in `queued`, `running`, `retrying`, `failed`, `done`, or `cancelled`. Celery tasks SHALL register in this ledger so that duplicate enqueues of the same logical work are deduplicated.

A `dedupe_key` SHALL be derived only from inputs that are stable across repeated enqueues of the same logical work. It SHALL NOT incorporate an identifier minted during the enqueue itself (such as a row id created moments earlier), because such a key can never collide and renders the guard inert while appearing active.

Where a call site opts into deduplication, that opt-in SHALL be effective: a call site that cannot produce a stable key SHALL NOT request deduplication.

#### Scenario: Duplicate enqueue is deduplicated

- **WHEN** a task is enqueued whose computed `dedupe_key` matches an existing non-terminal job
- **THEN** no second job row is created and the existing job continues to represent the work

#### Scenario: Retry exhaustion

- **WHEN** a job fails and its `attempts` reaches `max_attempts`
- **THEN** the job status becomes `failed` with `last_error` recorded
- **AND** the job remains queryable through the ops API for manual retry

#### Scenario: Dedupe key is stable across identical enqueues

- **WHEN** the same logical work is enqueued twice with identical caller-supplied inputs
- **THEN** both enqueues compute the same `dedupe_key`
- **AND** exactly one job row exists

#### Scenario: Repeating the same work after it finishes is allowed

- **WHEN** a job reaches a terminal state and its `dedupe_key` is released
- **AND** identical work is enqueued again
- **THEN** a new job row is created rather than returning the finished one

## ADDED Requirements

### Requirement: Declared queue routing is effective

Task routing configuration SHALL match the names under which tasks are actually registered, so that each task is dispatched to its declared queue. A routing pattern that matches no registered task SHALL NOT be retained, since it expresses an isolation guarantee the system does not provide.

#### Scenario: Declared route reaches its queue

- **WHEN** a task with a declared route is dispatched
- **THEN** it is delivered to the queue named in that route, not to the default queue

#### Scenario: No dead routing patterns

- **WHEN** the routing configuration is inspected against the registered task names
- **THEN** every routing pattern matches at least one registered task

### Requirement: Best-effort side effects report their failures

Where a side effect is deliberately best-effort — permitted to fail without aborting the primary operation, such as writing an audit row during a delete — its failure handler SHALL record the failure with enough context to identify the operation. A best-effort path SHALL NOT discard an error silently.

This applies to the destructive data-safety operations specifically: a soft-delete or purge SHALL attempt an `audit_log` row recording the action, entity type, entity id, actor, and reason, and SHALL surface any failure to write it.

#### Scenario: Destructive operation is audited

- **WHEN** a soft-delete or purge completes
- **THEN** an `audit_log` row exists naming the action, entity type, entity id, and actor

#### Scenario: Audit failure does not abort the operation but is visible

- **WHEN** the audit write fails during a delete
- **THEN** the delete still completes
- **AND** the failure is logged with the action and entity it belonged to

### Requirement: Diagnostic logs identify their origin

Structured log records at WARNING level and above SHALL attribute their source location to the application code that emitted them, not to the logging helper that formatted them.

#### Scenario: Source points at the caller

- **WHEN** application code emits a warning or error through the structured logger
- **THEN** the record's source file, line, and function identify that call site
