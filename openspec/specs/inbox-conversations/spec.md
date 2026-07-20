# inbox-conversations Specification

## Purpose
The Inbox is the primary reading surface: a cursor-paginated conversation list with filters, stars, and user-defined lists, plus a conversation detail view with infinite history scroll, live polling, and export options. In-conversation and inbox search behaviors are specified separately in `conversation-search` and `inbox-search`.

## Requirements

### Requirement: Conversation list with cursor pagination and filters

`GET /conversations` SHALL return conversations ordered by `last_activity_at` with cursor pagination. The inbox UI SHALL surface unread and send-failed badges, a star toggle per conversation, and an identity filter.

#### Scenario: Paging through the inbox

- **WHEN** the user scrolls past the current page of conversations
- **THEN** the next page is fetched via the returned cursor and appended without duplicates

#### Scenario: Filtering by identity

- **WHEN** the user selects an identity in the inbox filter
- **THEN** only conversations bound to that identity are listed

#### Scenario: Failed-send badge

- **WHEN** a conversation contains an outgoing message whose send failed
- **THEN** the conversation row shows a failure badge until the message is retried or deleted

### Requirement: User-defined conversation lists

The system SHALL support user-defined conversation lists (labels) via `GET/POST /lists`, `PUT/DELETE /lists/{listId}`, membership endpoints (`POST/DELETE /lists/{listId}/conversations/{conversationId}`), and `GET /lists/{listId}/conversation-ids`. The inbox SHALL offer a lists dropdown to assign conversations and filter by list.

#### Scenario: Assigning a conversation to a list

- **WHEN** the user adds a conversation to a list from the inbox dropdown
- **THEN** a membership row is created and the conversation appears when that list filter is active

#### Scenario: Deleting a list

- **WHEN** the user deletes a list
- **THEN** the list and its memberships are removed while the conversations themselves are untouched

### Requirement: Conversation detail with infinite scroll and polling

The conversation page SHALL load recent messages first, fetch older messages via cursor pagination when the user scrolls up ("infinite scroll"), and poll at a fast interval for new messages, appending them without disturbing scroll position.

#### Scenario: Loading older history

- **WHEN** the user scrolls to the top of the loaded message set
- **THEN** the previous page of older messages is prepended and scroll position is preserved

#### Scenario: New message arrives while reading

- **WHEN** polling detects a newly ingested incoming message
- **THEN** it is appended to the thread and the unread state updates

### Requirement: Message threading metadata is preserved

Messages SHALL store threading fields (`thread_external_id`, `parent_external_message_id`) captured from the provider, so reply structure is retained in the local archive.

#### Scenario: Threaded reply ingested

- **WHEN** a provider message that replies to an earlier message is ingested
- **THEN** its stored row references the parent's external message id and the thread id

### Requirement: Conversation export

The system SHALL export a single conversation as a standalone HTML document (`GET /conversations/{id}/export`) and export conversations as a ChatML JSONL fine-tuning dataset (`GET /conversations/export-dataset`, Unsloth-compatible), where outgoing messages map to assistant turns and incoming to user turns.

#### Scenario: HTML export of one conversation

- **WHEN** the user exports a conversation
- **THEN** an HTML file containing the full message history is produced for offline archival

#### Scenario: Dataset export for fine-tuning

- **WHEN** the user requests the dataset export
- **THEN** a JSONL file is produced with one ChatML-formatted conversation per line, suitable for Unsloth-style fine-tuning

### Requirement: Counterpart profile panel

The conversation view SHALL provide a `UserProfilePanel` for the counterpart, showing account state, profile items, and analysis actions without leaving the thread.

#### Scenario: Opening the profile panel

- **WHEN** the user opens the counterpart's profile panel from the conversation header
- **THEN** the panel shows the linked `external_accounts` record, its profile items, and contact/analyze actions
