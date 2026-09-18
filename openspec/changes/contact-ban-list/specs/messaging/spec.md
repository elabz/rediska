## ADDED Requirements

### Requirement: Sending to a banned counterpart is refused at every step
Both initiation routes, `POST /conversations/{id}/messages`, the pending-message retry endpoint, and the `message.send_manual` task immediately before the provider call SHALL check the ban list through one shared predicate and refuse when the counterpart has an active ban. API refusals SHALL return HTTP 409 with code `counterpart_banned`; the task SHALL mark the message `send_failed` with that error and make no provider call. No outgoing message SHALL reach the provider for a banned counterpart.

#### Scenario: Ban lands while a message is queued
- **WHEN** a message is enqueued and the counterpart is banned before the worker picks it up
- **THEN** the worker makes no provider call and the message is `send_failed` with `counterpart_banned`

#### Scenario: Sending in an existing conversation
- **WHEN** the user sends in a conversation whose counterpart is banned
- **THEN** the API returns 409 `counterpart_banned` and no message row is created

#### Scenario: Initiating from a lead
- **WHEN** the user triggers contact for a lead whose author is banned, with different letter case than the stored ban
- **THEN** the request is refused and no conversation is created
