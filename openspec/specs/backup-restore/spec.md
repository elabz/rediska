# backup-restore Specification

## Purpose
Rediska preserves all local data through scheduled local-filesystem backups: MySQL dumps and attachment snapshots written to `BACKUPS_PATH` with checksums, plus a recurring restore test that proves the dumps are actually restorable. Backups are local-only in v1; remote/NAS targets are deferred but the design keeps targets pluggable.

## Requirements

### Requirement: Scheduled backups run automatically

Celery beat SHALL schedule `maintenance.mysql_dump_local` daily at 03:00 UTC and `maintenance.attachments_snapshot_local` daily at 04:00 UTC. Both tasks SHALL be retryable (up to 3 attempts) and register in the jobs ledger.

#### Scenario: Nightly database dump

- **WHEN** the 03:00 UTC beat entry fires
- **THEN** a MySQL dump of the `rediska` database is written under `BACKUPS_PATH`
- **AND** a companion `.sha256` checksum file is written alongside it

#### Scenario: Nightly attachments snapshot

- **WHEN** the 04:00 UTC beat entry fires
- **THEN** a tar.gz snapshot of the attachments tree is written under `BACKUPS_PATH` with a checksum file

### Requirement: Restore is verified weekly

`maintenance.restore_test_local` SHALL run weekly (Sunday 05:00 UTC), restoring the latest dump into an ephemeral MySQL container and running sanity checks (tables present, key row counts) so a corrupt backup is detected before it is needed.

#### Scenario: Restore test passes

- **WHEN** the weekly restore test runs against a valid latest dump
- **THEN** the ephemeral container restores it, sanity queries succeed, and the test is recorded as done

#### Scenario: Restore test fails

- **WHEN** the latest dump cannot be restored or sanity checks fail
- **THEN** the task records a failure in the jobs ledger so the operator can see it in the Ops console

### Requirement: Backups are local filesystem only

All backup artifacts SHALL be written to the host-mounted `BACKUPS_PATH` directory. No backup path SHALL transmit data to cloud or remote storage in v1; the backup service design SHALL keep the target pluggable for later NAS integration.

#### Scenario: No remote transmission

- **WHEN** any backup task completes
- **THEN** every artifact it produced resides under `BACKUPS_PATH` on the local host and no network upload occurred

### Requirement: Manual backup and restore-test scripts exist

The repository SHALL provide operator scripts `scripts/local_backup/backup.sh` (dump + attachments copy) and `scripts/local_backup/restore_test.sh` (restore latest dump into an ephemeral container) that work without the web UI.

#### Scenario: Operator runs a manual backup

- **WHEN** the operator runs `scripts/local_backup/backup.sh`
- **THEN** a dated MySQL dump and attachments snapshot appear under `BACKUPS_PATH` with checksums

### Requirement: Backup integrity is checksummed

Every dump and snapshot SHALL have a sha256 checksum recorded at creation time, and the restore/verify path SHALL validate the checksum before attempting a restore.

#### Scenario: Checksum mismatch detected

- **WHEN** a backup artifact's content no longer matches its recorded sha256
- **THEN** verification fails and the artifact is not treated as a valid restore source
