## Why

Users need a way to backup their entire inbox content (messages, images, connections, and all properties) to a portable dump file, then restore it later. This enables data portability, safe experimentation with bulk operations, and disaster recovery. Currently, there's no way to export or restore inbox content as a complete unit.

## What Changes

- Add new API endpoints for exporting inbox content to a JSON dump file
- Add new API endpoints for importing/restoring from a dump file
- Add new API endpoint for clearing the entire inbox
- Preserve all message properties, images, connections, and metadata during export/import
- Include progress tracking for large export/import operations

## Capabilities

### New Capabilities

- `inbox-export`: Export all inbox content (messages, images, attachments, conversations) to a structured JSON dump file with full property preservation
- `inbox-import`: Restore inbox content from a previously exported dump file, reconstructing all relationships and properties
- `inbox-clear`: Delete all messages and related content from the inbox while preserving system configuration

### Modified Capabilities

<!-- No existing capabilities are being modified -->

## Impact

- **Backend API**: New FastAPI routes in `services/core/rediska_core/api/routes/` for export, import, and clear operations
- **Database**: Read operations for export, write operations for import/clear (uses existing tables)
- **File System**: New export storage location, temporary file handling for imports
- **Celery Tasks**: Background tasks for large export/import operations to avoid timeouts
- **Frontend**: New UI pages for managing exports/imports and viewing progress
- **Dependencies**: No new external dependencies required
