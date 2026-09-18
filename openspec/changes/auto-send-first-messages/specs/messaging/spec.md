## MODIFIED Requirements

### Requirement: No autosend — sending requires explicit user action

The system SHALL NOT send any outgoing message without an explicit user action in the UI, with exactly one exception: the first message to a lead's author MAY be sent automatically when the sending identity's draft mode is `auto_send`, as specified by the `auto-send` capability, and only after its unlock criteria, guards, hold window and caps are satisfied. That exception SHALL be off by default, enabled only by an explicit audited user action per identity, and disabled globally by `AUTO_SEND_ENABLED=false`. Every other message — any message in an existing conversation, any reply, any message for an identity in another draft mode — SHALL require an explicit send action. LLM-generated drafts are suggestions only; outside the exception nothing is transmitted until the user clicks send.

#### Scenario: Draft generated but not sent

- **WHEN** an LLM draft (e.g. intro draft) is generated for a conversation or lead and the identity's draft mode is not `auto_send`
- **THEN** no provider send occurs
- **AND** the draft is only transmitted if the user explicitly sends it

#### Scenario: Replies are never automatic

- **WHEN** a counterpart replies in a conversation opened by an automatic first message
- **THEN** no further message is sent without an explicit user action

## ADDED Requirements

### Requirement: Automatic sends are recorded with their own origin
Outgoing messages sent under the `auto-send` capability SHALL record `origin=auto` and the reply draft they came from.

#### Scenario: Origin of an automatic send
- **WHEN** a first message is sent automatically
- **THEN** the message has `origin=auto` and links its draft
