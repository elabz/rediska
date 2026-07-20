## ADDED Requirements

### Requirement: Attachment IDs persisted with draft

The system SHALL persist the conversation's pending `attachmentIds` array alongside the draft text under the same `localStorage` key, so that both are restored together on conversation entry.

#### Scenario: User uploads attachments then back-navigates

- **WHEN** the user uploads one or more attachments to a conversation and triggers browser back-navigation (or otherwise unmounts the conversation page) before sending
- **THEN** on returning to the same conversation, both the draft text and the previously-uploaded `attachmentIds` are restored into state

#### Scenario: Draft is empty if both fields are empty

- **WHEN** the user clears the textarea AND has no pending attachments
- **THEN** the `localStorage` entry for the conversation is removed

#### Scenario: Send clears attachments alongside text

- **WHEN** a message-send request returns success
- **THEN** the `localStorage` entry is removed in one operation, clearing both text and attachment IDs

### Requirement: Legacy draft migration

The system SHALL transparently treat any `localStorage` draft value that is not a valid structured object (e.g., a plain string written by a previous version) as `{ text: <raw value>, attachmentIds: [] }`, so older drafts are not lost.

#### Scenario: Plain-string legacy entry

- **WHEN** the conversation page mounts and reads a `localStorage` entry whose value is a plain string (not JSON-parseable as an object, or parseable but lacking a `text` string field)
- **THEN** the draft text is initialized from the raw value, `attachmentIds` is initialized to an empty array, and the entry is rewritten in the structured shape on the next persist

#### Scenario: Corrupted entry

- **WHEN** the entry contains JSON that parses to a non-object (number, array, null, boolean)
- **THEN** the entry is treated as a legacy plain-string draft with the raw value as text
