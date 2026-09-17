# conversation-sync Specification

## Purpose
Conversations and messages are continuously mirrored from providers into the local database by Celery ingest tasks, with beat-scheduled delta syncs, on-demand backfills, and a job ledger guaranteeing idempotency. Local data is preserved regardless of what happens remotely.

## Requirements

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

### Requirement: Backfill tasks import full history

The system SHALL provide `ingest.backfill_conversations` (all conversations for a provider/identity) and `ingest.backfill_messages` (full history of one conversation), triggerable from the Ops console (`POST /ops/backfill/conversations`) with job status readable via `GET /ops/backfill/{job_id}`.

#### Scenario: Operator triggers a backfill

- **WHEN** the operator starts a conversation backfill from the Ops page
- **THEN** a job row is created and the backfill task runs asynchronously
- **AND** the operator can poll the job's status until it completes or fails

### Requirement: On-demand sync with job tracking

`POST /conversations/sync` SHALL enqueue a sync and return a job id; `GET /conversations/sync/{job_id}` SHALL report its progress. `GET /ops/sync/status` SHALL report per-identity sync status.

#### Scenario: Manual sync from the UI

- **WHEN** the user clicks manual sync in the Ops or Inbox UI
- **THEN** a sync job is enqueued and its result details (counts, errors) are shown when polling completes

### Requirement: Jobs are idempotent with dedupe keys and retry policies

Every ingest task SHALL register in the `jobs` table with a dedupe key computed from task type and payload, so retries and duplicate triggers do not double-ingest. Tasks SHALL use bounded retries with backoff (Celery defaults: max 10 retries, late acks).

#### Scenario: Duplicate trigger is deduplicated

- **WHEN** the same sync/backfill is enqueued twice with an identical payload while the first is still pending
- **THEN** the second is deduplicated via the jobs-table dedupe key rather than run concurrently

#### Scenario: Transient provider failure retries

- **WHEN** an ingest task fails with a transient provider error
- **THEN** it is retried with backoff up to its retry limit, and the job row records attempts and last error

### Requirement: Provider deletions never delete local data

Sync SHALL NEVER delete local records or files in response to remote deletion. Remote deletions or removals SHALL only update status columns (`remote_status` on accounts, `remote_visibility` / `remote_deleted_at` on messages, posts, and profile items), which the UI surfaces as badges.

#### Scenario: Message deleted on the provider

- **WHEN** a previously ingested message is found deleted or removed on the provider
- **THEN** the local row's `remote_visibility` is updated (e.g. `deleted_by_author`) and `remote_deleted_at` set
- **AND** the local body text and attachments remain stored and viewable

#### Scenario: Account deleted on the provider

- **WHEN** a counterpart account is deleted or suspended remotely
- **THEN** the `external_accounts.remote_status` is updated and shown as a badge, with all local history intact

### Requirement: Attachment re-download recovers missing files

The system SHALL provide `ingest.redownload_attachments`, triggerable via `POST /ops/redownload/attachments`, which re-downloads images referenced in message bodies that are missing from local attachment storage.

#### Scenario: Missing attachment files

- **WHEN** the operator triggers attachment re-download
- **THEN** messages whose referenced images are absent from `ATTACHMENTS_PATH` have them fetched and stored again where still available remotely
