# Task 005: Enhance Ops Page

## Priority: MEDIUM (Operations)

## Current State
The Ops page (`/ops`) only has Reddit Sync functionality. It's missing:
- Backfill controls
- Job status monitoring
- Backup/restore status
- Per-identity sync status

## Required Functionality

### 1. Backfill Controls
- **Backfill Conversations** - Full history import
  - Trigger `ingest.backfill_conversations` task
  - Show progress/status
  - Per-identity backfill option
- **Backfill Messages** - Per-conversation message import
  - Select conversation to backfill
  - Trigger `ingest.backfill_messages` task

### 2. Job Status Monitoring
- List of recent/active jobs
  - Job type
  - Status (queued, running, retrying, failed, done)
  - Created/updated timestamps
  - Attempt count
  - Error details (for failed jobs)
- Filter by status
- Retry failed jobs button
- Cancel running jobs (if supported)

### 3. Sync Status Dashboard
- Last sync timestamp per identity
- Messages synced count
- Next scheduled sync time (when beat is configured)
- Sync health indicator

### 4. Backup Status (when implemented)
- Last backup timestamp
- Backup size
- Last restore test result (pass/fail)
- Manual backup trigger button
- Backup history

### 5. Identity-Specific Controls
- List connected identities
- Per-identity sync button
- Per-identity backfill button
- Identity health status (credential status)

## API Endpoints

### Backend (some may need creation)
```
# Existing
POST /conversations/sync - Trigger sync

# Need to create
GET /ops/jobs - List recent jobs
GET /ops/jobs/{id} - Get job details
POST /ops/jobs/{id}/retry - Retry failed job

POST /ops/backfill/conversations - Trigger conversation backfill
POST /ops/backfill/messages - Trigger message backfill

GET /ops/sync/status - Get sync status per identity
GET /ops/backup/status - Get backup status
POST /ops/backup/trigger - Trigger manual backup
```

### Frontend API Routes Needed
```
/api/core/ops/jobs/route.ts
/api/core/ops/jobs/[jobId]/route.ts
/api/core/ops/jobs/[jobId]/retry/route.ts
/api/core/ops/backfill/conversations/route.ts
/api/core/ops/backfill/messages/route.ts
/api/core/ops/sync/status/route.ts
/api/core/ops/backup/status/route.ts
/api/core/ops/backup/trigger/route.ts
```

## Files to Create/Modify

### Create
- Multiple API routes (see above)
- `/apps/web/src/components/ops/JobsTable.tsx`
- `/apps/web/src/components/ops/BackfillControls.tsx`
- `/apps/web/src/components/ops/SyncStatusPanel.tsx`
- `/apps/web/src/components/ops/BackupStatusPanel.tsx`
- `/apps/web/src/components/ops/IdentitySyncPanel.tsx`

### Create Backend Routes
- `/services/core/rediska_core/api/routes/ops.py`

### Modify
- `/apps/web/src/app/(authenticated)/ops/page.tsx` - Expand with new panels

## Component Structure
```
OpsPage
├── SyncPanel (existing, enhanced)
│   ├── IdentitySelector
│   ├── SyncButton
│   └── LastSyncInfo
├── BackfillPanel
│   ├── BackfillConversationsButton
│   ├── BackfillMessagesSection
│   └── BackfillProgress
├── JobsPanel
│   ├── JobFilters
│   ├── JobsTable
│   │   ├── JobRow (status, type, attempts, error)
│   │   └── RetryButton
│   └── Pagination
├── SyncStatusDashboard
│   ├── IdentitySyncStatus (per identity)
│   └── OverallHealth
└── BackupPanel
    ├── LastBackupInfo
    ├── RestoreTestResult
    └── TriggerBackupButton
```

## Acceptance Criteria
- [ ] User can trigger full conversation backfill
- [ ] User can view list of jobs with status
- [ ] User can retry failed jobs
- [ ] Sync status shows last sync per identity
- [ ] Backfill progress is visible
- [ ] Error details are displayed for failed jobs
- [ ] Backup status shows when backups are configured

## Estimated Scope
- Backend ops routes: ~2 hours
- API routes: ~1 hour
- Components: ~3 hours
- Page integration: ~1 hour
- Testing: ~30 minutes

## Dependencies
- Backend jobs table (implemented)
- Backend backfill tasks (implemented)
- Celery worker running

## Related Specs
- Spec Pack v0.4: Section 5 (jobs table), Section 7 (Celery tasks)
- PRD Epic 9.6: Ops UI
- PRD Epic 10: Backups & restore tests
