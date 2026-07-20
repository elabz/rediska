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
