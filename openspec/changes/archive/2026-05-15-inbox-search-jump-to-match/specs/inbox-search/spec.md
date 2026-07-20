## ADDED Requirements

### Requirement: Search results identify the matching message

The conversation search API SHALL include the identifier of the message that produced the snippet for each result, so that callers can deep-link directly to it.

#### Scenario: Search hit returns the matching message id

- **WHEN** a client calls `GET /conversations/search?q=<query>` and Elasticsearch returns at least one matching message in a conversation
- **THEN** the corresponding `ConversationSearchHit` in the response includes a non-null `matching_message_id` field that equals the id of the highest-scoring message in that conversation for the query

#### Scenario: No matching message found

- **WHEN** a conversation appears in the search response without a discoverable matching message id (e.g. the indexed document has been removed since the hit was scored)
- **THEN** the hit's `matching_message_id` is `null`
- **AND** the response is otherwise unchanged (snippet, counterpart, recency are still populated)

#### Scenario: Field is additive for legacy clients

- **WHEN** a client that does not request or read `matching_message_id` consumes the search response
- **THEN** the response remains valid against the prior contract — all previously documented fields are still present with their previous types

### Requirement: Inbox search results deep-link to the matching message

The inbox search results UI SHALL link each result to the conversation detail page in a way that identifies the matching message.

#### Scenario: Click a search result with a known matching message

- **WHEN** the user clicks a search result whose `matching_message_id` is non-null
- **THEN** the browser navigates to `/inbox/<conversationId>?m=<matchingMessageId>`

#### Scenario: Click a search result with no matching message id

- **WHEN** the user clicks a search result whose `matching_message_id` is null
- **THEN** the browser navigates to `/inbox/<conversationId>` with no `m` parameter
- **AND** the conversation page behaves the same as a non-search navigation (scrolls to the most recent message)

### Requirement: Conversation page jumps to the matching message on deep-link

The conversation detail page SHALL honor the `m` query parameter on initial load by scrolling to and visually highlighting the matching message instead of scrolling to the bottom.

#### Scenario: Matching message is in the loaded set

- **WHEN** the user lands on `/inbox/<conversationId>?m=<id>` and the message with that id is included in the initial page load
- **THEN** after messages finish loading, that message is scrolled into view (centered)
- **AND** that message bubble receives a brief highlight effect lasting roughly 1.5 seconds
- **AND** the page does NOT also auto-scroll to the bottom

#### Scenario: Matching message is not in the loaded set

- **WHEN** the user lands on `/inbox/<conversationId>?m=<id>` and the message with that id is not in the initial page load (e.g. it falls outside the safety cap or has been deleted)
- **THEN** the page falls back to its normal initial behavior (scrolls to the most recent message)
- **AND** an inline notice is shown above the message list indicating the jump could not be performed and pointing the user toward **Load more messages**
- **AND** no error toast is raised and no retry is attempted

#### Scenario: Jump runs once per mount

- **WHEN** a deep-link jump has already been performed (or attempted) on this mount and the message-polling tick or a sent message updates the message list
- **THEN** the page does NOT re-trigger the scroll-to-message or the highlight
- **AND** subsequent navigation away and back to the same conversation without `?m=` does not jump

#### Scenario: Invalid m parameter

- **WHEN** the `m` parameter is present but cannot be parsed as a positive integer
- **THEN** the page ignores the parameter and behaves as if it were absent (scroll to most recent message; no notice)
