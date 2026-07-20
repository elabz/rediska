## ADDED Requirements

### Requirement: Import inbox content from JSON dump file
The system SHALL import and restore inbox content from a previously exported JSON dump file.

#### Scenario: Successful import
- **WHEN** user provides a valid JSON dump file
- **THEN** system restores all messages, conversations, attachments, and their properties

### Requirement: Reconstruct all relationships during import
The system SHALL reconstruct conversation threads and message relationships as they were in the original export.

#### Scenario: Import maintains conversation structure
- **WHEN** messages are imported
- **THEN** conversation threads are recreated with correct message ordering and relationships

### Requirement: Validate dump file structure
The system SHALL validate the JSON dump file structure before attempting import.

#### Scenario: Reject invalid dump file
- **WHEN** provided file is not a valid JSON dump format
- **THEN** system rejects import with clear error message

### Requirement: Handle missing referenced files
The system SHALL check for missing file references during import and report warnings.

#### Scenario: Import with missing files
- **WHEN** dump references files that don't exist on disk
- **THEN** import completes with warnings listing missing files, but messages are still restored

### Requirement: Import is atomic operation
The system SHALL perform import as an atomic operation that either completes fully or rolls back completely.

#### Scenario: Import failure rolls back
- **WHEN** import fails midway
- **THEN** all changes are rolled back, leaving inbox in original state

### Requirement: Handle duplicate content
The system SHALL handle cases where import content already exists in the inbox.

#### Scenario: Import detects duplicates
- **WHEN** importing content that already exists
- **THEN** system skips duplicate content and imports only new items

### Requirement: Provide import progress tracking
The system SHALL track and report progress during import operations.

#### Scenario: Monitor import progress
- **WHEN** import is in progress
- **THEN** system provides status updates with percentage complete
