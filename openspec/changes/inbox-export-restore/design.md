## Context

The Rediska inbox currently stores messages, conversations, attachments, and related metadata in MySQL with file references to local storage. There's no mechanism to export this data as a portable backup or restore from one. Users need this capability for data portability, disaster recovery, and safe experimentation with bulk operations.

The system uses a BFF architecture where UI calls Next.js proxy routes, which forward to FastAPI backend. All mutating operations write to audit_log, and Celery handles background tasks.

## Goals / Non-Goals

**Goals:**
- Export complete inbox content (messages, conversations, attachments, images, all properties) to a JSON dump file
- Import/restore from a dump file, reconstructing all relationships and properties
- Clear the inbox while preserving system configuration (providers, identities, etc.)
- Handle large datasets without timeouts using background tasks
- Preserve file references and attachment metadata during export/import
- Include progress tracking for long-running operations

**Non-Goals:**
- Incremental sync or differential backups (full dump only)
- Cross-user or cross-instance migration (single-user system)
- Real-time export/import streaming (batch operations)
- Encryption of export files (can be added later)

## Decisions

### 1. JSON Dump Format with Embedded File References
**Decision**: Use a structured JSON format that includes all database records and file path references (not embedded file content).

**Rationale**: 
- JSON is human-readable and easy to debug
- File references keep dump files small; actual files remain in filesystem
- Simpler implementation than binary formats
- Alternative considered: SQLite database dump (rejected - less portable, harder to inspect)

### 2. Celery Background Tasks for Large Operations
**Decision**: Use Celery tasks for export/import operations to avoid HTTP timeouts.

**Rationale**:
- Large inboxes could have thousands of messages
- Background tasks provide progress tracking via job status
- Consistent with existing pattern for long-running operations
- Alternative considered: Synchronous endpoints with streaming (rejected - complex, still risky for very large datasets)

### 3. Atomic Import with Rollback
**Decision**: Import operations should be atomic - either complete fully or roll back completely.

**Rationale**:
- Prevents partial imports that leave inbox in inconsistent state
- Uses database transactions for atomicity
- Alternative considered: Partial import with error reporting (rejected - complexity, potential for orphaned data)

### 4. Separate Clear Operation
**Decision**: Clear operation is separate from import, not part of import flow.

**Rationale**:
- Explicit clear prevents accidental data loss
- Can be used independently for testing or cleanup
- Import can optionally clear before restoring

### 5. File Reference Validation
**Decision**: Export validates file existence; import checks for missing files and reports warnings.

**Rationale**:
- Ensures dump files are complete and restorable
- Provides clear feedback if files are missing
- Alternative considered: Embed file content in dump (rejected - dump files become very large)

## Risks / Trade-offs

**[Risk] Large dump files could be slow to generate** → Use streaming JSON serialization, progress tracking, and chunked processing.

**[Risk] Import could fail midway leaving partial data** → Use database transactions with rollback on failure.

**[Risk] File references could become invalid if files are moved/deleted** → Validate file existence during export, report missing files during import.

**[Risk] Clear operation is destructive** → Require explicit confirmation, log to audit_log, consider soft-delete option.

**[Trade-off] JSON vs binary format** → JSON chosen for readability/debuggability over smaller file size.

**[Trade-off] Full dump vs incremental** → Full dump chosen for simplicity; incremental can be added later if needed.
