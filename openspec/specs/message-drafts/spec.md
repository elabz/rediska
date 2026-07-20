# message-drafts Specification

## Purpose
Defines autosaved per-conversation message drafts: compose text and pending attachment ids persist to `localStorage` (debounced, keyed per conversation), restore on re-entry, clear on successful send, and degrade gracefully when storage is unavailable.
## Requirements
### Requirement: Draft persistence while typing

The system SHALL persist the current value of the message compose input to the browser's `localStorage`, keyed per conversation, whenever the user modifies the input. Persistence MUST be debounced to avoid blocking the UI thread on every keystroke.

#### Scenario: User types in the compose box

- **WHEN** the user types text into the conversation compose textarea
- **THEN** the text is written to `localStorage` under the key `rediska:draft:conversation:<conversationId>` within 500ms of the last keystroke

#### Scenario: User edits text in the compose box

- **WHEN** the user modifies existing draft text (insert, delete, paste)
- **THEN** the persisted value is updated to match the latest input state within 500ms

#### Scenario: Draft is empty

- **WHEN** the compose box value is empty (zero-length string or only whitespace)
- **THEN** the corresponding `localStorage` entry MUST be removed so empty drafts do not accumulate

### Requirement: Draft restoration on conversation entry

The system SHALL restore the persisted draft into the compose input when the user opens or re-opens the conversation view, so accidental back-navigation does not lose typed content.

#### Scenario: User returns to conversation after accidental back-navigation

- **WHEN** the conversation detail page mounts for `<conversationId>` and a non-empty draft exists in `localStorage` for that conversation
- **THEN** the compose textarea is initialised with the persisted draft text before the user can begin typing

#### Scenario: No prior draft exists

- **WHEN** the conversation detail page mounts and no `localStorage` entry exists for `<conversationId>`
- **THEN** the compose textarea is initialised to an empty string

#### Scenario: Persisted value is corrupted or unreadable

- **WHEN** the conversation detail page mounts and reading the `localStorage` entry throws or returns a non-string value
- **THEN** the compose textarea is initialised to an empty string and the corrupted entry is removed

### Requirement: Draft isolation per conversation

The system SHALL scope draft storage to a single conversation, so a draft in one conversation MUST NOT appear in any other conversation.

#### Scenario: Drafts exist in multiple conversations

- **WHEN** the user has unsent drafts in conversations A and B and navigates to conversation A
- **THEN** the compose box shows only conversation A's draft; conversation B's draft remains untouched

### Requirement: Draft cleared on successful send

The system SHALL remove the persisted draft for a conversation from `localStorage` immediately after the message-send request to that conversation returns a successful response.

#### Scenario: Message send succeeds

- **WHEN** the POST to `/api/core/conversations/<conversationId>/messages` returns an HTTP success status
- **THEN** the `localStorage` entry for `rediska:draft:conversation:<conversationId>` is removed

#### Scenario: Message send fails

- **WHEN** the POST to `/api/core/conversations/<conversationId>/messages` returns an error or throws a network exception
- **THEN** the `localStorage` entry for that conversation is NOT removed, so the user can retry without re-typing

#### Scenario: Clear affects only the current conversation

- **WHEN** the user successfully sends a message in conversation A while a draft also exists in conversation B
- **THEN** only conversation A's `localStorage` entry is removed; conversation B's draft is preserved

### Requirement: Graceful degradation when storage is unavailable

The system SHALL continue to function when `localStorage` is unavailable (private-browsing limits, quota exceeded, disabled by the user) without surfacing errors that block the user from composing or sending messages.

#### Scenario: localStorage write throws

- **WHEN** writing the draft to `localStorage` throws (e.g., `QuotaExceededError`, security exception)
- **THEN** the compose box continues to function normally and the failure is logged to the console but not surfaced as a user-facing error

#### Scenario: localStorage is not defined

- **WHEN** the runtime environment does not expose `window.localStorage` (e.g., during server-side rendering)
- **THEN** draft persistence is silently skipped and the compose box operates as if no draft were stored

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

