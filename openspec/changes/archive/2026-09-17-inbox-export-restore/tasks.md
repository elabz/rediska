## 1. Backend API Routes

- [x] 1.1 Create export endpoint in `services/core/rediska_core/api/routes/inbox.py`
- [x] 1.2 Create import endpoint in `services/core/rediska_core/api/routes/inbox.py`
- [x] 1.3 Create clear endpoint in `services/core/rediska_core/api/routes/inbox.py`
- [x] 1.4 Add progress tracking endpoints for background operations

## 2. Celery Background Tasks

- [x] 2.1 Create `export_inbox` task in `services/worker/rediska_worker/tasks/inbox_export.py`
- [x] 2.2 Create `import_inbox` task in `services/worker/rediska_worker/tasks/inbox_import.py`
      (renamed from `import.py` — `import` is a reserved keyword and cannot be a module path)
- [x] 2.3 Create `clear_inbox` task in `services/worker/rediska_worker/tasks/inbox_clear.py`
- [x] 2.4 Register new tasks in Celery app configuration (new `transfer` queue, added to worker `-Q`)

## 3. Export Implementation

- [x] 3.1 Implement JSON serialization for messages with all properties
- [x] 3.2 Implement conversation relationship export
- [x] 3.3 Implement attachment metadata export with file references
- [x] 3.4 Add file existence validation during export
- [x] 3.5 Create export file storage and download mechanism

## 4. Import Implementation

- [x] 4.1 Implement JSON parsing and validation
- [x] 4.2 Implement message restoration with relationship reconstruction
- [x] 4.3 Implement conversation thread recreation
- [x] 4.4 Add duplicate detection and handling
- [x] 4.5 Implement atomic import with transaction rollback
- [x] 4.6 Add missing file reference warnings

## 5. Clear Implementation

- [x] 5.1 Implement message deletion while preserving system config
- [x] 5.2 Add confirmation requirement for clear operation
- [x] 5.3 Implement audit logging for clear operations

## 6. Frontend Integration

- [x] 6.1 Create export UI in `apps/web/src/app/(authenticated)/ops/backup/page.tsx`
- [x] 6.2 Create import UI (same page — one `/ops/backup` page with three sections,
      matching the existing `/ops` information architecture)
- [x] 6.3 Create clear UI (same page, typed-confirmation gated)
- [x] 6.4 Add progress tracking display for background operations
- [x] 6.5 Create Next.js proxy routes for new API endpoints

## 7. Testing

- [x] 7.1 Write unit tests for export functionality
- [x] 7.2 Write unit tests for import functionality
- [x] 7.3 Write unit tests for clear functionality
- [x] 7.4 Write integration tests for end-to-end export/import flow
- [x] 7.5 Test error handling and edge cases

## 8. Documentation

- [x] 8.1 Update API documentation with new endpoints (`docs/inbox-backup.md`)
- [x] 8.2 Add usage examples for export/import operations

## Decisions taken during implementation

Recorded here because they resolve ambiguities the artifacts left open:

1. **Scope of "inbox"** — conversations, conversation list memberships, messages, and
   message-linked attachments. Identities and external accounts are exported (so
   imports can rebuild FKs) but never deleted by clear, because `lead_posts`,
   `profile_snapshots`, and `profile_items` reference the same accounts.
2. **Clear keeps attachment files on disk** — deletes rows only. This is what makes
   the spec's "clear is reversible via import" requirement actually hold, given
   design decision #1 (dumps carry references, not content).
3. **Single `/ops/backup` page** instead of three separate top-level pages, matching
   the existing `/ops` IA and sharing one progress display.
4. **`transfer` Celery queue** rather than reusing `maintenance`, so a long export
   cannot queue behind the nightly backups. Required adding `transfer` to the
   worker's `-Q` list in `services/worker/Dockerfile` (needs an image rebuild).
