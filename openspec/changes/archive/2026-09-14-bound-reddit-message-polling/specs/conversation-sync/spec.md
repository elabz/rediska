## MODIFIED Requirements

### Requirement: Scheduled delta syncs keep the inbox fresh

Celery beat SHALL run `ingest.sync_inbox_fast` (inbox only) every 60 seconds and `ingest.sync_sent` (sent folder only) every 300 seconds. Both SHALL stop paging after 10 consecutive already-stored messages and SHALL request at most 5 listing pages per run.

`ingest.sync_delta` (inbox and sent) SHALL NOT be beat-scheduled; it serves on-demand sync and SHALL request at most 20 listing pages per folder. Walking a provider's full message history without a page cap SHALL be reserved for the backfill tasks.

#### Scenario: New incoming message arrives on the provider

- **WHEN** a counterpart sends a message on the provider
- **THEN** within roughly one fast-sync interval the message is ingested as a local `messages` row with `direction='in'`
- **AND** the owning conversation's `last_activity_at` is updated

#### Scenario: A routine poll costs one request

- **WHEN** a scheduled inbox sync runs and the newest listing page begins with already-stored messages
- **THEN** the sync stops after that single page request

#### Scenario: A run that does not reach stored messages is bounded

- **WHEN** a scheduled sync keeps receiving pages without reaching 10 consecutive already-stored messages
- **THEN** it stops after 5 pages instead of walking the provider's entire message history

## ADDED Requirements

### Requirement: Message syncs for an identity run one at a time

Every message sync — scheduled, on-demand, or backfill — SHALL hold a per-identity Redis lock while it runs. A scheduled sync that finds the lock held SHALL end immediately and report `skipped`. On-demand syncs and backfills SHALL wait up to 60 seconds for the lock before reporting `skipped`.

The lock SHALL expire on its own after a timeout longer than the Celery hard time limit, and SHALL be renewed after each page. If Redis is unreachable, the sync SHALL proceed without the lock.

#### Scenario: Scheduled syncs overlap

- **WHEN** a scheduled sync starts while another message sync for the same identity is still running
- **THEN** the new run makes no provider requests and reports `skipped`

#### Scenario: A worker dies mid-sync

- **WHEN** the process holding the lock is killed
- **THEN** the lock expires within its timeout and later scheduled syncs run normally

### Requirement: A failed message write never poisons the rest of a sync

Each message SHALL be written inside its own savepoint, and each listing page SHALL be committed separately.

A uniqueness conflict caused by a concurrent writer SHALL roll back only that message's writes; the message SHALL then be looked up again and treated as already stored. Any other database failure SHALL roll back the current page, stop the sync without requesting further pages, and report the run as `error` — pages committed earlier SHALL be kept. Per-message failures SHALL be written to the log, not only returned in the task result.

#### Scenario: Concurrent duplicate insert

- **WHEN** another writer stores the same message between the sync's existence check and its insert
- **THEN** the sync counts that message as already stored and continues with the remaining messages
- **AND** exactly one local row exists for the message

#### Scenario: Deadlock mid-page

- **WHEN** a database deadlock occurs while writing a message on the second page
- **THEN** the sync stops without requesting a third page
- **AND** the first page's messages remain stored and the run reports `error` with the failure recorded
