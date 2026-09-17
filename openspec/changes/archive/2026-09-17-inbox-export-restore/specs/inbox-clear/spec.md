## ADDED Requirements

### Requirement: Clear all inbox content
The system SHALL delete all messages and related content from the inbox while preserving system configuration.

#### Scenario: Successful clear operation
- **WHEN** user triggers clear operation
- **THEN** all messages, conversations, and attachments are removed from inbox

### Requirement: Preserve system configuration during clear
The system SHALL preserve providers, identities, credentials, and other system configuration during clear operations.

#### Scenario: Clear preserves system data
- **WHEN** inbox is cleared
- **THEN** provider settings, user identities, and system configuration remain intact

### Requirement: Require explicit confirmation for clear
The system SHALL require explicit user confirmation before executing clear operation.

#### Scenario: Clear requires confirmation
- **WHEN** user initiates clear operation
- **THEN** system prompts for confirmation before proceeding

### Requirement: Log clear operation to audit trail
The system SHALL log all clear operations to the audit_log table.

#### Scenario: Clear is audited
- **WHEN** clear operation completes
- **THEN** system writes entry to audit_log with timestamp and user information

### Requirement: Clear operation is reversible via import
The system SHALL allow users to restore cleared content by importing from a previously created dump file.

#### Scenario: Restore after clear
- **WHEN** user imports from dump file after clearing inbox
- **THEN** all previously cleared content is restored
