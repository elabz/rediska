## ADDED Requirements

### Requirement: Dataset export can select conversations by outcome
The dataset export SHALL classify each conversation, from the messages that pass its validity filter and the counterpart's stored state, as `no_reply`, `replied` (at least one incoming message), `sustained` (at least `sustained_turns` turns from each side, default 3), or `engaged` (counterpart engagement state is engaged), each outcome including those below it. Parameter `min_outcome` (`any` default, `replied`, `sustained`, `engaged`) SHALL restrict the export to conversations at or above that outcome. `exclude_banned` (default true) SHALL omit conversations whose counterpart has an active do-not-contact entry, and `min_user_chars` SHALL omit conversations where the user's text is shorter than the floor. Outcome SHALL be derived from counts and stored state only, never from an LLM or from message themes. The audit entry and dialog SHALL report conversation counts per outcome before and after filtering.

#### Scenario: Only conversations that got a reply
- **WHEN** the export runs with `min_outcome=replied`
- **THEN** no emitted sample comes from a conversation in which the counterpart never wrote

#### Scenario: Default is unchanged
- **WHEN** the export runs without `min_outcome` and no counterpart is banned
- **THEN** the same conversations are exported as before this change

#### Scenario: Banned counterpart
- **WHEN** a conversation's counterpart is on the do-not-contact list and `exclude_banned` is not disabled
- **THEN** the conversation is omitted and counted as excluded

### Requirement: Dataset samples carry their outcome and can be repeated
Each emitted line SHALL include a `meta` object with the conversation's outcome and turn count beside `conversations`, unless `include_meta=false`. `engaged_repeat` (1 to 5, default 1) SHALL write each sample from an `engaged` conversation that many times.

#### Scenario: Metadata for the trainer
- **WHEN** a sample from a conversation with several exchanges is exported
- **THEN** its line contains `meta.outcome` and `meta.turns`

#### Scenario: Up-weighting engaged conversations
- **WHEN** the export runs with `engaged_repeat=3`
- **THEN** every sample from an engaged conversation appears three times and other samples once
