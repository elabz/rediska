# conversation-search Specification

## Purpose
Defines the in-conversation search experience on the conversation detail page: a highlight-only SearchBox that marks every occurrence of the query without filtering messages, a match counter with prev/next navigation between occurrences, and pre-filling from the `?q=` deep-link parameter used by inbox search results.
## Requirements
### Requirement: In-conversation search highlights matches without filtering

The in-conversation `SearchBox` SHALL operate in highlight-only mode: while a query is active, all messages in the conversation remain rendered, and every occurrence of the query inside any message body is visually marked.

#### Scenario: Typing a query keeps all messages visible

- **WHEN** the user types a non-empty query into the in-conversation `SearchBox` while viewing a conversation with N messages
- **THEN** all N messages remain rendered in their original order
- **AND** the previous "filter to matching messages only" behavior is not applied
- **AND** every textual occurrence of the query within any message body is wrapped in a highlight marker

#### Scenario: Clearing the query removes highlights

- **WHEN** the user clears the `SearchBox` (via the clear button or by deleting all characters)
- **THEN** all highlight markers are removed
- **AND** the message list renders identically to a conversation with no active search

#### Scenario: Highlight color is the unified accent

- **WHEN** any highlight is rendered (whether from the local `SearchBox` or from a `?q=` deep-link)
- **THEN** the highlight uses the project accent `#FF2056` as its background, in both light and dark themes

### Requirement: Match counter reports total occurrences and current position

The in-conversation `SearchBox` SHALL display a counter that reports the total number of textual occurrences of the query across all loaded messages and the user's current position within that ordered list.

#### Scenario: Counter shows current and total

- **WHEN** the query produces M total occurrences across all loaded messages and the user's current position is the K-th occurrence (1-indexed)
- **THEN** the counter renders as "K of M matches" (or an equivalent compact form) in the `SearchBox` row
- **AND** M counts individual occurrences, not the number of message bubbles containing matches

#### Scenario: No matches found

- **WHEN** the query is non-empty but produces zero occurrences
- **THEN** the counter renders as "0 of 0" (or an equivalent empty-state form)
- **AND** the prev/next controls are disabled
- **AND** no message in the list is marked as the current match

#### Scenario: Counter is hidden when no query is active

- **WHEN** the `SearchBox` is empty
- **THEN** the counter is not rendered
- **AND** the prev/next controls are not rendered

### Requirement: Prev/Next controls navigate between matches

The in-conversation `SearchBox` SHALL provide prev/next controls that move the user between adjacent matches, scroll the targeted match into view, and visually emphasize it.

#### Scenario: Next moves forward and centers the next match

- **WHEN** at least one match exists, the user clicks the **Next** control, and the current position is K
- **THEN** the current position advances to K+1 (or wraps to 1 if K was already the last match)
- **AND** the newly-current match is scrolled into the viewport, centered vertically
- **AND** the newly-current match is rendered with a stronger emphasis style than the other (non-current) matches
- **AND** the counter updates to reflect the new K

#### Scenario: Prev moves backward and centers the previous match

- **WHEN** at least one match exists, the user clicks the **Prev** control, and the current position is K
- **THEN** the current position moves to K-1 (or wraps to the total M if K was 1)
- **AND** the newly-current match is scrolled into the viewport, centered vertically
- **AND** the newly-current match is rendered with the stronger emphasis style
- **AND** the counter updates to reflect the new K

#### Scenario: Initial match is selected when a query becomes non-empty

- **WHEN** the user types a query that produces at least one match (transitioning from zero matches to one or more)
- **THEN** the first match (in document order) is set as the current match
- **AND** that match is scrolled into view and rendered with the stronger emphasis style
- **AND** the counter renders as "1 of M matches"

### Requirement: `?q=<query>` pre-fills the local SearchBox on entry

The conversation detail page SHALL, on initial mount, treat the URL `?q=<query>` parameter as the initial value of the in-conversation `SearchBox`, then defer all subsequent highlight behavior to the local `SearchBox` state.

#### Scenario: Deep-link from inbox pre-fills the SearchBox

- **WHEN** the user lands on `/inbox/<conversationId>?q=<query>` (with or without `?m=<id>`)
- **THEN** the in-conversation `SearchBox` is rendered with `<query>` as its value
- **AND** highlights, the match counter, and prev/next controls behave as if the user had typed `<query>` locally

#### Scenario: Editing the SearchBox does not rewrite the URL

- **WHEN** the user changes the value of the `SearchBox` after the initial pre-fill
- **THEN** highlights, counter, and prev/next reflect the new local value immediately
- **AND** the URL `?q=` parameter is not rewritten to match the edited value
- **AND** a subsequent refresh of the page would still use the original URL `?q=` value as the initial pre-fill

#### Scenario: Missing or empty `?q=` leaves the SearchBox empty

- **WHEN** the user lands on a conversation URL without a `?q=` parameter (or with `?q=` empty)
- **THEN** the in-conversation `SearchBox` is empty on entry
- **AND** no highlights or counter are rendered until the user types a query
