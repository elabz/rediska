## ADDED Requirements

### Requirement: Outgoing messages record their origin
Every outgoing message SHALL record `origin` as `manual`, `draft_edited`, or `draft_as_is`, and the reply draft it came from when there is one. `draft_as_is` SHALL mean the sent text equals the draft text after whitespace normalisation. Recording origin SHALL NOT change how a message is sent: every send SHALL remain an explicit user action through the existing send path.

#### Scenario: Draft sent unchanged
- **WHEN** the user uses a reply draft and sends it without changes
- **THEN** the message has `origin=draft_as_is` and links the draft

#### Scenario: Typed by hand
- **WHEN** the user writes and sends a message with no reply draft involved
- **THEN** the message has `origin=manual` and no draft link
