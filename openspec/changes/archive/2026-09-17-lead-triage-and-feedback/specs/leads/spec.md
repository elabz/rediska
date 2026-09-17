# leads Specification (delta)

## ADDED Requirements

### Requirement: Leads carry a priority tier derived from analysis signals

Leads created from analysis (scout auto-promotion and multi-agent analysis of saved leads) SHALL persist a priority tier (`high`, `medium`, `low`) and the preferences `compatibility_score` on the `lead_posts` row. The tier SHALL be derived in code from the meta agent's `priority_level`, the compatibility score, and gate outcomes — not by an additional LLM call. Leads created before this capability existed MAY have a null priority.

#### Scenario: Scout promotion stores priority

- **WHEN** a scout-analyzed post is auto-promoted to a lead
- **THEN** the created `lead_posts` row has a non-null priority tier and `compatibility_score`

#### Scenario: High compatibility promotes

- **WHEN** an analysis yields `compatibility_score >= 0.7` and all decision gates passed
- **THEN** the lead's priority tier is `high`

### Requirement: Stale scout leads auto-expire

A daily maintenance task (`maintenance.expire_stale_leads`) SHALL set scout-sourced, non-deleted leads still at status `new` more than a configurable number of days after creation (env `LEAD_EXPIRY_DAYS`; 0 disables and is the default — leads are kept and the list is filtered by date instead) to status `expired`. Expiry SHALL be audit-logged in batches of lead ids, SHALL never delete rows, and SHALL NOT apply to manually saved leads. The task SHALL support a dry-run mode that reports the would-expire count without mutating (audit-logged as a dry run), and SHALL refuse any live run — scheduled or manual — until a dry run has completed at least once, so the pre-existing backlog is always reviewed first. An expired lead is not an active lead for author-level dedupe and is not a rejection verdict.

#### Scenario: Old untouched scout lead expires

- **WHEN** the expiry task runs and a `lead_source='scout_watch'` lead has been at status `new` for more than `LEAD_EXPIRY_DAYS`
- **THEN** its status becomes `expired`
- **AND** an audit log entry records the expiry

#### Scenario: Manual leads are never auto-expired

- **WHEN** the expiry task runs
- **THEN** no lead with `lead_source='manual'` changes status

#### Scenario: Dry run reports without mutating

- **WHEN** the task is invoked with dry-run enabled
- **THEN** it returns the count of leads that would expire and no statuses change

#### Scenario: Live run before any dry run is refused

- **WHEN** the task runs live and no dry run has ever completed
- **THEN** no statuses change and the result reports that a dry run is required

### Requirement: Needs-review triage tab on the Leads page

The Leads page SHALL include a "Needs review" tab showing the cross-watch needs-review queue (scout posts whose analysis recommendation is `needs_review` and which have not been triaged), newest first with the first-seen time, watch, author, gate results and non-passing gate reasons, and post body visible, with its count, and per-entry one-click actions: promote to lead (existing add-to-leads flow), dismiss, and a final-verdict evaluation control. The tab SHALL have loading, empty, and error states.

#### Scenario: Triage from the tab

- **WHEN** the user opens the Needs review tab and promotes one post and dismisses another
- **THEN** the promoted post becomes a lead and leaves the queue
- **AND** the dismissed post leaves the queue without creating a lead

## MODIFIED Requirements

### Requirement: Lead status lifecycle

Each lead SHALL carry a status in `new`, `saved`, `ignored`, `contact_queued`, `contacted`, `expired`, updated via `PATCH /leads/{lead_id}/status`. Status mutations SHALL write to the audit log. `expired` is set by the auto-expiry task (or manually) and is reversible like any other status.

#### Scenario: Marking a lead ignored

- **WHEN** the user updates a lead's status to `ignored`
- **THEN** the lead's status is `ignored`
- **AND** an audit log entry records the change

#### Scenario: Reviving an expired lead

- **WHEN** the user updates an `expired` lead's status to `saved`
- **THEN** the lead returns to the active list and the change is audit-logged

### Requirement: Lead listing supports status and source filters

`GET /leads` SHALL return leads with cursor pagination and support filtering by status and by `lead_source` (`manual` or `scout_watch`). By default the listing SHALL exclude `expired` leads (they are returned only when `status=expired` is requested) and SHALL order by priority tier (high → medium → low → null) and then recency; `sort=newest` SHALL order by recency alone. `posted_within_days=N` SHALL restrict the listing (and its total) to leads whose post date — or, when unknown, save date — falls within the last N days. Soft-deleted leads SHALL never be listed or counted. List entries SHALL include author information (analysis state and available profile metadata), the latest analysis recommendation and confidence, and the priority tier and `compatibility_score` so the list can badge and rank leads.

#### Scenario: Leads page defaults to the last 14 days

- **WHEN** the user opens the Leads page
- **THEN** the Posted filter is "Last 14 days" and the list requests `posted_within_days=14`
- **AND** the filter offers last 7 days, 14 days, 30 days, and all time

#### Scenario: Filter to scout-watch leads

- **WHEN** the client calls `GET /leads?lead_source=scout_watch`
- **THEN** only leads created by scout watch runs are returned

#### Scenario: Default listing hides expired and ranks by priority

- **WHEN** the client calls `GET /leads` with no status filter
- **THEN** no `expired` leads are included
- **AND** leads with priority `high` appear before `medium`, `low`, and null-priority leads of similar recency
