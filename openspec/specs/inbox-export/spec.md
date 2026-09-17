# inbox-export Specification

## Purpose
TBD - created by archiving change inbox-export-restore. Update Purpose after archive.
## Requirements
### Requirement: Export inbox content to JSON dump file
The system SHALL export all inbox content (messages, conversations, attachments, images, and all properties) to a structured JSON dump file.

#### Scenario: Successful export
- **WHEN** user triggers export operation
- **THEN** system creates a JSON file containing all messages with their properties, conversation relationships, attachment metadata, and file references

### Requirement: Preserve all message properties during export
The system SHALL preserve all message properties including sender, receiver, timestamp, content, read status, and any custom fields in the export.

#### Scenario: Export preserves message metadata
- **WHEN** messages are exported
- **THEN** each message retains all its original properties in the JSON structure

### Requirement: Export attachment metadata with file references
The system SHALL include attachment metadata and file path references in the export, not the actual file content.

#### Scenario: Export includes attachment references
- **WHEN** messages have attachments
- **THEN** export includes attachment metadata (filename, type, size, path) without embedding the actual file content

### Requirement: Export handles large datasets
The system SHALL handle large inbox content using background processing to avoid HTTP timeouts.

#### Scenario: Large export completes successfully
- **WHEN** inbox contains thousands of messages
- **THEN** export operation completes via background task with progress tracking

### Requirement: Validate file existence during export
The system SHALL validate that referenced files exist on disk before completing export.

#### Scenario: Export warns about missing files
- **WHEN** some referenced files are missing
- **THEN** export completes with warnings listing missing files

### Requirement: Export creates downloadable file
The system SHALL provide the exported JSON file for download after completion.

#### Scenario: Download exported file
- **WHEN** export operation completes
- **THEN** system provides a download link for the JSON dump file

