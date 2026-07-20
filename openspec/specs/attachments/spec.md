# attachments Specification

## Purpose
Attachments (chiefly images from conversations and profiles) are stored exclusively on the local filesystem under `ATTACHMENTS_PATH`, with content hashes and metadata recorded in the `attachments` table. Local files are never removed because of remote deletions, and missing images can be re-downloaded from message bodies.

## Requirements

### Requirement: Local filesystem is the only storage backend

Every attachment SHALL be stored with `storage_backend = 'fs'` under the host-mounted `ATTACHMENTS_PATH`, keyed by a relative `storage_key`. The database row SHALL record `sha256`, `mime_type`, `size_bytes`, and image dimensions (`width_px`/`height_px`) where applicable. No attachment SHALL be written to cloud or remote storage.

#### Scenario: Upload persists locally with metadata

- **WHEN** a client uploads a file via `POST /attachments/upload`
- **THEN** the bytes are written under `ATTACHMENTS_PATH` and a row is created with sha256, mime type, and size recorded

### Requirement: Attachments can be uploaded to a conversation

The API SHALL support attaching files to a conversation via `POST /conversations/{conversation_id}/attachments`, producing attachment records that can be referenced by an outgoing message. Pending attachment IDs SHALL persist with the compose draft per the `message-drafts` capability.

#### Scenario: Attach then send

- **WHEN** the user uploads an attachment in a conversation and sends a message referencing it
- **THEN** the sent message links the attachment record and the file remains under `ATTACHMENTS_PATH`

### Requirement: Attachments are retrievable with metadata

The API SHALL serve attachment binaries via `GET /attachments/{attachment_id}` and metadata via `GET /attachments/{attachment_id}/meta`, with access restricted to the authenticated session like all other endpoints.

#### Scenario: Rendering an image in the UI

- **WHEN** the conversation view renders an image message
- **THEN** the image bytes are fetched from `GET /api/core/attachments/{id}` (BFF proxy) and served from local storage

### Requirement: Missing attachments can be re-downloaded

The system SHALL provide `ingest.redownload_attachments` (triggered via `POST /ops/redownload/attachments`) which scans message bodies for referenced image URLs whose local files are missing and re-downloads them into `ATTACHMENTS_PATH`.

#### Scenario: Recovering lost files

- **WHEN** the operator triggers attachment re-download and some messages reference images with no local file
- **THEN** those images are fetched again from their source URLs and stored locally, with records updated

### Requirement: Remote deletion never removes local files

When a provider reports an attachment's source as deleted or removed, the system SHALL only update `remote_visibility` (and `remote_deleted_at`) on the record. The local file and database row SHALL be preserved; only an explicit local delete marks `deleted_at`, and even that SHALL NOT purge the file as a side effect of provider sync.

#### Scenario: Source image deleted on the provider

- **WHEN** sync detects that an attachment's remote source is gone
- **THEN** the record's `remote_visibility` becomes `deleted_by_author` or `removed`
- **AND** the local file under `ATTACHMENTS_PATH` is untouched and still served by the download endpoint
