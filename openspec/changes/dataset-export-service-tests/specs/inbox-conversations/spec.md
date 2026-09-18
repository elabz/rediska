## ADDED Requirements

### Requirement: Dataset export emits a valid, alternating ChatML shape
Every line produced by `GET /conversations/export-dataset` SHALL be a JSON object with a `conversations` array whose first element has role `system`, whose remaining elements alternate between `user` and `assistant` starting with `user`, and whose last element has role `assistant`. Messages that are deleted, failed to send, empty, or not visible SHALL be excluded; consecutive messages of one side SHALL be merged into one turn; conversations without at least one turn from each side SHALL be omitted.

#### Scenario: Consecutive messages from one side
- **WHEN** a counterpart sent three messages in a row before the user answered
- **THEN** the sample contains one `user` turn holding the three texts and then one `assistant` turn

#### Scenario: Conversation with no reply from the user
- **WHEN** a conversation contains only incoming messages
- **THEN** no line is emitted for it

#### Scenario: Failed message
- **WHEN** an outgoing message has a send error
- **THEN** its text does not appear in the sample

### Requirement: Dataset export logic is a tested service
The export's selection, ordering, role mapping, merging, trimming and serialisation SHALL be implemented in a domain service callable without HTTP, and SHALL be covered by automated tests that use only synthetic conversations. The route SHALL be limited to parameter handling, auditing and the response.

#### Scenario: Export rules verified without live data
- **WHEN** the test suite runs
- **THEN** each export rule is exercised against synthetic `test_` conversations and no test reads stored inbox content
