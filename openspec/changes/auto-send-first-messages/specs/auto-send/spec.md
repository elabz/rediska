## ADDED Requirements

### Requirement: Automatic sending is a mode that must be earned
An identity's `draft_mode` SHALL accept `auto_send` only when: at least `AUTO_UNLOCK_MIN_SENDS` reply drafts were sent; over the last 30 sent drafts the median edit ratio is 0.15 or lower and at least 60% were sent unchanged; the contact ban list and copy detection are deployed; and `AUTO_SEND_ENABLED` is true. A refused change SHALL list each criterion with its current value. Selecting the mode SHALL be an explicit audited user action. The criteria SHALL be re-evaluated daily.

#### Scenario: Not yet earned
- **WHEN** the user selects `auto_send` with 12 sent drafts
- **THEN** the change is refused and the unmet criteria are listed with their values

#### Scenario: Earned
- **WHEN** all criteria hold and the user selects `auto_send`
- **THEN** the mode changes and an audit entry records the criteria values

### Requirement: Automatic first messages wait out a cancellable hold
In `auto_send`, a prepared draft with status `ready` for a lead passing the automatic-send guards SHALL be `scheduled` with `send_after` set `AUTO_HOLD_MINUTES` ahead (default 30, 0 allowed), and a content-free notification SHALL be queued. Lead detail and the dashboard SHALL show the scheduled send with Cancel, Edit and Send now. Cancel SHALL prevent sending and SHALL NOT reschedule the lead. Drafts with status `needs_edit` SHALL never be scheduled.

#### Scenario: Cancelled during the hold
- **WHEN** the user cancels a scheduled send
- **THEN** nothing is sent and the draft is `cancelled`

#### Scenario: Draft needing edits
- **WHEN** a prepared draft failed verification
- **THEN** it is notified as a normal draft and not scheduled

### Requirement: Guards are evaluated at scheduling and again at send time
The automatic-send guards SHALL be the shared reply-draft guards with compatibility at or above `AUTO_MIN_COMPATIBILITY`, post age at most `AUTO_MAX_POST_AGE_HOURS`, every guard capability available, the post confirmed still visible at the provider, the daily cap and any configured quiet hours satisfied, the circuit breaker closed and the kill switch on. `AUTO_DAILY_CAP` SHALL default to 20 and SHALL NOT exceed 20. No minimum interval between automatic sends SHALL be imposed beyond the provider rate limiter, and no author SHALL ever receive more than one automatic message. A failure at send time SHALL cancel the send and return the draft to `notified`.

#### Scenario: Author banned during the hold
- **WHEN** the author is banned between scheduling and the send time
- **THEN** nothing is sent and the draft expires

#### Scenario: Two leads at once
- **WHEN** two eligible drafts reach their send time in the same minute
- **THEN** both are sent without an imposed delay between them

#### Scenario: Daily cap reached
- **WHEN** the cap is 20 and twenty automatic sends happened today
- **THEN** further eligible drafts remain notified drafts for manual sending

### Requirement: Automatic sends use the manual send path and are attributable
An automatic send SHALL initiate the conversation through the same service as the manual route and enqueue `message.send_manual` with `max_retries=0` and `origin=auto`, and SHALL write `audit_log` with actor `agent`, the lead, the draft and the guards evaluated. No message other than the first message to a lead's author SHALL ever be sent automatically.

#### Scenario: Counterpart replies
- **WHEN** the author replies to an automatically sent first message
- **THEN** no further message is sent without an explicit user action

### Requirement: A circuit breaker and a kill switch fail towards manual
The system SHALL return an identity to `prepare_and_notify`, cancel its scheduled sends, write `audit_log` and notify the user when: an automatic send ends `send_failed`; the provider answers a send with a rate-limit or forbidden response; the identity is reported restricted; the unlock criteria stop holding; the reply rate of at least 20 automatic sends is below half the manual baseline; or three consecutive scheduled sends were cancelled. Returning to `auto_send` SHALL require a manual action that re-evaluates the unlock criteria. With `AUTO_SEND_ENABLED=false`, `auto_send` SHALL behave as `prepare_and_notify`.

#### Scenario: Provider refuses a send
- **WHEN** an automatic send receives a 403 from the provider
- **THEN** the identity drops to `prepare_and_notify` and remaining scheduled sends are cancelled

#### Scenario: Kill switch
- **WHEN** `AUTO_SEND_ENABLED` is false
- **THEN** no draft is scheduled or sent automatically, whatever the identity's mode
