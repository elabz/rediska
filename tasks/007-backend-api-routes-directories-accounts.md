# Task 007: Backend API Routes - Directories & Accounts

## Priority: HIGH (Prerequisite for UI tasks)

## Current State
The backend has services for directories and accounts but may be missing API routes to expose them to the frontend.

## Required Endpoints

### 1. Directory Endpoints
```python
# /api/routes/directories.py

GET /directories/analyzed
  Query params:
    - provider_id: Optional[str]
    - offset: int = 0
    - limit: int = 20
    - sort: str = "analyzed_at_desc"
  Response:
    - entries: List[DirectoryEntry]
    - total: int
    - next_cursor: Optional[str]

GET /directories/contacted
  Query params: (same as above, sort by contacted_at)
  Response: (same structure)

GET /directories/engaged
  Query params: (same as above, sort by engagement date)
  Response: (same structure)
```

### 2. Account Endpoints
```python
# /api/routes/accounts.py

GET /accounts/{account_id}
  Response:
    - id, provider_id, external_username
    - remote_status, remote_status_last_seen_at
    - analysis_state, contact_state, engagement_state
    - first_analyzed_at, first_contacted_at
    - latest_snapshot: Optional[ProfileSnapshot]

GET /accounts/{account_id}/profile-items
  Query params:
    - item_type: Optional[str] (post, comment, image)
    - offset: int = 0
    - limit: int = 20
  Response:
    - items: List[ProfileItem]
    - total: int

GET /accounts/{account_id}/snapshots
  Query params:
    - offset: int = 0
    - limit: int = 10
  Response:
    - snapshots: List[ProfileSnapshot]

GET /accounts/{account_id}/conversations
  Response:
    - conversations: List[ConversationSummary]

POST /accounts/{account_id}/analyze
  Triggers profile analysis
  Response:
    - job_id: str
    - status: str
```

### 3. Ops Endpoints
```python
# /api/routes/ops.py

GET /ops/jobs
  Query params:
    - status: Optional[str]
    - job_type: Optional[str]
    - offset: int = 0
    - limit: int = 20
  Response:
    - jobs: List[Job]
    - total: int

GET /ops/jobs/{job_id}
  Response: Job details

POST /ops/jobs/{job_id}/retry
  Response: { success: bool, new_job_id: str }

POST /ops/backfill/conversations
  Body: { provider_id: str, identity_id: Optional[int] }
  Response: { job_id: str }

POST /ops/backfill/messages
  Body: { conversation_id: int }
  Response: { job_id: str }

GET /ops/sync/status
  Response:
    - identities: List[IdentitySyncStatus]
    - last_global_sync: Optional[datetime]

GET /ops/backup/status
  Response:
    - last_backup_at: Optional[datetime]
    - last_backup_size_bytes: Optional[int]
    - last_restore_test_at: Optional[datetime]
    - last_restore_test_result: Optional[str]
```

## Files to Create

### Backend
- `/services/core/rediska_core/api/routes/directories.py`
- `/services/core/rediska_core/api/routes/accounts.py`
- `/services/core/rediska_core/api/routes/ops.py`
- `/services/core/rediska_core/api/schemas/directories.py`
- `/services/core/rediska_core/api/schemas/accounts.py`
- `/services/core/rediska_core/api/schemas/ops.py`

### Update
- `/services/core/rediska_core/main.py` - Register new routers

## Schema Definitions

### DirectoryEntry
```python
class DirectoryEntry(BaseModel):
    account_id: int
    provider_id: str
    external_username: str
    remote_status: str
    analysis_state: str
    summary_snippet: Optional[str]
    latest_snapshot_id: Optional[int]
    analyzed_at: Optional[datetime]
    contacted_at: Optional[datetime]
    engaged_at: Optional[datetime]
```

### ProfileItem
```python
class ProfileItem(BaseModel):
    id: int
    item_type: str
    external_item_id: str
    item_created_at: Optional[datetime]
    text_content: Optional[str]
    attachment_id: Optional[int]
    remote_visibility: str
```

### Job
```python
class Job(BaseModel):
    id: int
    queue_name: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    next_run_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime
```

## Acceptance Criteria
- [ ] All directory endpoints return correct data
- [ ] Account endpoints return profile with snapshots
- [ ] Profile items are paginated correctly
- [ ] Ops endpoints list and manage jobs
- [ ] Backfill endpoints trigger correct Celery tasks
- [ ] Proper error handling and validation
- [ ] Audit logging for mutating operations

## Estimated Scope
- Routes: ~3 hours
- Schemas: ~1 hour
- Service integration: ~1 hour
- Testing: ~1 hour

## Dependencies
- DirectoryService (implemented)
- JobService (implemented)
- BackupService (implemented)

## Related Specs
- Spec Pack v0.4: Section 5 (Database tables)
- PRD Epics 7.3, 9.5, 9.6
