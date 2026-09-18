## ADDED Requirements

### Requirement: Outbound notifications carry no stored content
Notifications sent to any third-party service SHALL contain only operational metadata (event type, counts, internal ids, scores, status) and links to the LAN/VPN-only application. They SHALL NOT contain ingested content, message or draft text, or identifiers of counterparts. A notification integration SHALL be outbound-only; no integration may require the system to accept connections from the internet.

#### Scenario: Notification feature proposes to include a preview
- **WHEN** a change proposes including post or draft text in a Slack, email or push notification
- **THEN** the proposal is out of policy; the notification links to the application instead

#### Scenario: Interactive approval proposed
- **WHEN** a change proposes approving or sending from inside a third-party chat tool
- **THEN** the proposal is out of policy because it requires inbound reachability
