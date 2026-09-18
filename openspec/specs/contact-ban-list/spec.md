# contact-ban-list Specification

## Purpose
One reversible, audited contact ban list (`do_not_contact`) that every outreach path checks through a single shared predicate. Bans are set only by explicit user action (copy-ring suspects are suggested, never auto-banned), withdraw the author from lead work queues, and never delete or hide stored content.

## Requirements

### Requirement: Ban entries have a source, a reason and a reversible lifecycle
Each `do_not_contact` row SHALL carry `source` (`manual`, `copy_ring`, `import`), a required `reason`, optional `notes`, optional `cluster_id`, and `status` (`active`, `lifted`). Rows SHALL never be deleted. Banning a username whose row is `lifted` SHALL reactivate that row. Usernames SHALL be matched case-insensitively. Every create, bulk create, lift and suggestion dismissal SHALL write `audit_log`.

#### Scenario: Manual ban
- **WHEN** the user bans `Some_User` with reason `scam`
- **THEN** an active row exists for `some_user` with `source=manual` and an audit entry is written

#### Scenario: Lift keeps history
- **WHEN** the user lifts a ban
- **THEN** the row's status is `lifted` with `lifted_at` set, and the username is contactable again

### Requirement: Ban list is manageable through the API and a directory view
The core API SHALL expose `GET /ban-list` (cursor pagination; filters `status`, `source`, `q`), `POST /ban-list`, `POST /ban-list/{id}/lift`, and `POST /ban-list/bulk`. The web app SHALL provide a Banned view under `/directories` listing entries with reason, source, date, linked cluster and linked leads, with search, lift, and empty and error states. The UI SHALL call these through `/api/core/ban-list` proxies.

#### Scenario: Empty list
- **WHEN** no bans exist
- **THEN** the Banned view shows an empty state explaining how to ban an account

### Requirement: An account can be banned from every surface where it is judged
A Ban action requiring a reason SHALL be available on the conversation header, the account profile page, lead detail, scout history posts, needs-review items, and the copy-cluster drawer. The action SHALL work for a username that has no `external_accounts` row.

#### Scenario: Ban from a conversation
- **WHEN** the user bans the counterpart from the conversation header
- **THEN** the conversation shows a banned banner and the compose box is disabled with a Lift link

### Requirement: Ring suspects are suggested, never banned automatically
`GET /ban-list/suggestions` SHALL list authors who belong to a copy cluster whose effective kind is `ring_suspect` or `confirmed_ring`, who are not actively banned and whose suggestion was not dismissed, with cluster evidence (authors, post times, account states, earliest poster marked). The system SHALL NOT create a ban without an explicit user action. `POST /ban-list/bulk` SHALL ban all authors of a cluster except those listed in `exclude_usernames`, as one audited batch.

#### Scenario: New member joins a confirmed ring
- **WHEN** a new account posts text belonging to a `confirmed_ring` cluster whose other authors are banned
- **THEN** the new author appears as a suggestion and is not banned

#### Scenario: Bulk ban with an exclusion
- **WHEN** the user bulk-bans a five-author cluster excluding the earliest poster
- **THEN** four active rows with `source=copy_ring` and the cluster id are created and one audit entry lists them

### Requirement: A ban withdraws the author from the work queues without deleting anything
When a ban becomes active, leads of that author with status `new`, `saved` or `contact_queued` SHALL move to `ignored` with the prior status remembered, and SHALL be restored when the ban is lifted. `GET /leads` and the needs-review queue SHALL exclude banned authors unless `include_banned=true`. Analyses, evaluations, conversations, messages and attachments SHALL NOT be modified or hidden. Incoming messages from a banned account SHALL continue to sync and display verbatim.

#### Scenario: Banned author's saved lead
- **WHEN** an author with a `saved` lead is banned and later un-banned
- **THEN** the lead is `ignored` while the ban is active and `saved` again after the lift

#### Scenario: Banned account writes in
- **WHEN** a banned account sends a message
- **THEN** the message is stored and shown in the inbox, with the banned banner on the conversation
