# messaging Specification

## Purpose
All outbound communication is manual: the user explicitly composes and sends every message, the system sends it at most once through the provider, and every mutating action is audited. This capability covers sending, retry/delete of pending messages, conversation initiation, attachments, and remote deletion.

## Requirements

### Requirement: No autosend — sending requires explicit user action

The system SHALL NOT send any outgoing message without an explicit user action in the UI. LLM-generated drafts are suggestions only; nothing is transmitted until the user clicks send.

#### Scenario: Draft generated but not sent

- **WHEN** an LLM draft (e.g. intro draft) is generated for a conversation or lead
- **THEN** no provider send occurs
- **AND** the draft is only transmitted if the user explicitly sends it

### Requirement: Compose box sends only on an explicit shortcut

The conversation compose textarea SHALL be 7 lines tall by default (user-resizable). Plain Enter SHALL insert a newline; only Cmd+Enter (Ctrl+Enter on non-macOS keyboards) or the Send button SHALL send.

#### Scenario: Enter inserts a newline

- **WHEN** the user presses Enter (with or without Shift) in the compose box
- **THEN** a newline is inserted and nothing is sent

#### Scenario: Cmd+Enter sends

- **WHEN** the user presses Cmd+Enter (or Ctrl+Enter) with non-empty text
- **THEN** the message is sent exactly as if the Send button had been clicked

### Requirement: Manual send with at-most-once semantics

`POST /conversations/{id}/messages` SHALL create a local outgoing message record and enqueue the `message.send_manual` Celery task. The task SHALL run with `max_retries=0`: ambiguous failures (e.g. timeouts) fail without automatic retry so a message can never be delivered twice; only the user can retry.

#### Scenario: Successful send

- **WHEN** the user sends a message in a conversation
- **THEN** a local `messages` row with `direction='out'` and the conversation's identity is created
- **AND** `message.send_manual` delivers it through the provider adapter exactly once

#### Scenario: Ambiguous failure does not auto-retry

- **WHEN** the send task hits an ambiguous failure such as a timeout
- **THEN** the message is marked failed (`send_failed` visibility with `send_error` recorded) without any automatic retry

### Requirement: Pending and failed messages are user-manageable

The system SHALL list pending/unsent messages (`GET /conversations/{id}/pending`), support explicit retry of a failed send (`POST .../messages/{messageId}/retry`), and support deleting a pending message (`DELETE .../messages/{messageId}`) before it is sent.

#### Scenario: User retries a failed message

- **WHEN** the user clicks retry on a failed message
- **THEN** the send task is enqueued again for that message and its failure state clears on success

#### Scenario: User deletes a pending message

- **WHEN** the user deletes a message that has not been delivered
- **THEN** it is removed from the pending queue and never sent

### Requirement: Conversation initiation honors safety checks

`POST /conversations/initiate/by-username` and `POST /conversations/initiate/from-lead/{leadId}` SHALL get-or-create the counterpart `external_accounts` row, check the `do_not_contact` list and refuse to initiate when the counterpart is listed, bind the conversation to the requested identity (or the provider default when omitted), and write the action to the audit log.

#### Scenario: Counterpart is on the do-not-contact list

- **WHEN** the user attempts to initiate a conversation with a username present in `do_not_contact`
- **THEN** the request is rejected and no conversation or message is created

#### Scenario: Initiating from a lead

- **WHEN** the user contacts a lead's author from the lead detail page
- **THEN** an existing open conversation with that author is reused if present, otherwise a new identity-bound conversation is created

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

### Requirement: Attachments on outgoing messages

`POST /conversations/{id}/attachments` SHALL store uploaded files on the local filesystem under `ATTACHMENTS_PATH` with sha256, mime type, and size recorded, and associate them with the composed message.

#### Scenario: Uploading an image to a conversation

- **WHEN** the user uploads an image while composing
- **THEN** an `attachments` row is created with checksum and metadata, and the file is stored locally

### Requirement: Remote delete preserves local records

`POST .../messages/{messageId}/remote-delete` and `POST .../messages/remote-delete-batch` SHALL delete the message(s) on the provider via the adapter while preserving the local record, updating only remote visibility fields.

#### Scenario: Batch scrub of sent messages

- **WHEN** the user batch remote-deletes selected sent messages
- **THEN** each is deleted on the provider and its local `remote_visibility` updated
- **AND** local body text and attachments remain stored

### Requirement: Mutations are audited

Every mutating messaging endpoint (send, retry, delete, initiate, remote-delete, attachment upload) SHALL write an `audit_log` entry recording actor, action type, identity, entity, and result.

#### Scenario: Audit trail of a send

- **WHEN** a message send is triggered and completes (or fails)
- **THEN** audit entries exist for the action with `result` reflecting the outcome
