## ADDED Requirements

### Requirement: Outbound notifications go through one content-free channel interface
The system SHALL send notifications through a notifier interface whose first implementation posts to a Slack incoming webhook configured by `SLACK_WEBHOOK_URL`. Notification payloads SHALL be assembled only from an allow-list of fields: event type, counts, lead id, draft id, priority, compatibility score, draft status, and links under `BASE_URL`. Payloads SHALL NOT contain post titles or bodies, draft or message text, usernames, community names, or external URLs. `NOTIFY_DETAIL=minimal` (default) SHALL send only a fixed sentence and a link to the draft; `lead` SHALL add the allow-listed fields. With no webhook configured, notifications SHALL be disabled without error.

#### Scenario: Minimal notification
- **WHEN** a draft becomes ready and detail is `minimal`
- **THEN** one Slack message says a reply draft is waiting and links to it, and contains nothing else about it

#### Scenario: Payload contains no content
- **WHEN** a notification is built for a draft at detail `lead`
- **THEN** the serialised payload contains none of the lead's title, body, author username, location, or the draft text

### Requirement: Notifications are immediate and isolated from the work they describe
A notification SHALL be sent as soon as its event occurs, one message per event, with no minimum interval between messages. Optional quiet hours per identity, disabled by default, SHALL hold notifications and release them when the window ends, dropping events whose draft is no longer live. Every attempt SHALL be recorded in `notification_log` with status and HTTP result. A failed delivery SHALL be retried by a scheduled task with a capped number of attempts and SHALL NOT fail, delay or roll back draft generation or any other task.

#### Scenario: Draft becomes ready
- **WHEN** a prepared draft reaches `ready`
- **THEN** a notification for it is sent without waiting for other drafts

#### Scenario: Several drafts in a minute
- **WHEN** three drafts become ready within one minute
- **THEN** three notifications are sent

#### Scenario: Slack unreachable
- **WHEN** the webhook call fails
- **THEN** the draft remains `ready`, the failure is logged, and delivery is retried later

### Requirement: The notification channel is outbound only and its secret is protected
The system SHALL NOT expose any endpoint, port or callback for a notification provider, and SHALL NOT support actions initiated from the provider. The webhook URL SHALL NOT be returned by any API, written to `audit_log`, or logged. `/settings/voice` SHALL show whether a channel is configured and SHALL offer a Test action that sends a fixed test message and reports the result; enabling, disabling and testing SHALL write `audit_log`.

#### Scenario: Test button
- **WHEN** the user presses Test with a configured webhook
- **THEN** a fixed test message is delivered and the page reports success without revealing the URL
