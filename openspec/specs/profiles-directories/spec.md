# profiles-directories Specification

## Purpose
Every counterpart person is tracked as an `external_accounts` row that accumulates profile data (snapshots, public content items) and moves through a contact workflow (analyzed → contacted → engaged, plus starring). Directories present these workflow states as browsable views; the profile page presents everything known about one account. Local data is preserved regardless of what happens to the account remotely.

## Requirements

### Requirement: Accounts carry workflow states

Each external account SHALL carry `analysis_state` (`not_analyzed`, `analyzed`, `needs_refresh`), `contact_state` (`not_contacted`, `contacted`), `engagement_state` (`not_engaged`, `engaged`), a starred flag, and `remote_status` (`active`, `deleted`, `suspended`, `unknown`), with first-transition timestamps (first analyzed, first contacted, first inbound after contact).

#### Scenario: Engagement is recorded on first reply

- **WHEN** a contacted account sends its first inbound message after contact
- **THEN** the account's `engagement_state` becomes `engaged`
- **AND** `first_inbound_after_contact_at` is set

### Requirement: Directory views by state

The API SHALL expose `GET /directories/analyzed`, `/contacted`, `/engaged`, and `/starred` returning accounts in the corresponding state with sort and search, `GET /directories/counts` returning per-state counts, and `POST /directories/{account_id}/star` toggling the star. The Directories page SHALL render these as tabs with counts, per-entry state badges, latest AI summary, and a contact action.

#### Scenario: Browsing engaged contacts

- **WHEN** the user opens the Engaged tab
- **THEN** only accounts with `engagement_state='engaged'` are listed, with their states and latest summary

#### Scenario: Starring from a directory

- **WHEN** the user toggles the star on an account
- **THEN** the account appears in (or leaves) the Starred directory immediately

### Requirement: Profile page aggregates account knowledge

`/profile/{accountId}` SHALL display the latest `profile_snapshots` entry (summary text, structured signals, risk flags, model info), tabbed `profile_items` (posts, comments, images), the account's linked conversations, and actions to contact and re-analyze the account.

#### Scenario: Viewing a profile

- **WHEN** the user opens an account's profile page
- **THEN** the latest snapshot summary, signals, and risk flags are shown
- **AND** the account's posts, comments, and images are browsable in tabs
- **AND** conversations with the account are linked

### Requirement: Analysis by account or by username

The system SHALL support triggering analysis for an existing account (`POST /accounts/{account_id}/analyze`) and for an arbitrary username not yet tracked (`POST /accounts/analyze-username`), which creates the account record as needed. Accounts SHALL also be resolvable by username via `GET /accounts/by-username/{provider_id}/{username}`.

#### Scenario: Analyzing a username seen elsewhere

- **WHEN** the user triggers analyze on a username with no existing account row
- **THEN** an `external_accounts` row is created and the analysis pipeline runs for it

### Requirement: Duplicate detection

The system SHALL provide a duplicate-detection service that flags external accounts likely belonging to the same person, so the user can recognize alternate accounts.

#### Scenario: Possible duplicate is surfaced

- **WHEN** two accounts show strong similarity signals
- **THEN** the duplicate-detection service reports them as a possible duplicate pair

### Requirement: Do-not-contact list blocks outreach

The `do_not_contact` table SHALL store provider + username pairs that must never be contacted. Any contact-initiation path SHALL check this list and refuse to create a conversation or send a message to a listed username.

#### Scenario: Contact attempt against a listed username

- **WHEN** any contact flow targets a username on the do-not-contact list
- **THEN** the attempt is blocked and no outgoing message is created

### Requirement: Local preservation and local-only deletion

Provider-side deletion or suspension SHALL only update `remote_status` / `remote_visibility` fields and display badges — it SHALL never delete local records or files. Local deletion (hide) and purge of an account are user-initiated actions with their own timestamps (`deleted_at`, `purged_at`).

#### Scenario: Account deleted on the provider

- **WHEN** sync observes that a counterpart account was deleted remotely
- **THEN** `remote_status` becomes `deleted` and the UI shows a badge
- **AND** all locally stored snapshots, items, conversations, and attachments remain intact
