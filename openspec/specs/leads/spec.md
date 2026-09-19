# leads Specification

## Purpose
Leads are provider posts the user has saved as potential contacts. The capability covers saving posts as `lead_posts`, the lead status lifecycle, listing/filtering leads, lead detail with author context, initiating contact from a lead, and the guarantee that every saved lead's content is also persisted as a `profile_item` so analysis always has at least one item to work from.
## Requirements
### Requirement: Saving a lead persists the post and a profile item atomically

`POST /leads/save` SHALL create or upsert a `lead_posts` row (unique by `(provider_id, external_post_id)`) and, in the same database transaction, upsert a `profile_item` for the post linked to the author's `external_accounts` row (`item_type='post'`, keyed by `(account_id, item_type, external_item_id)`). The profile item's `text_content` is the post title and body combined, `subreddit` is the source location, `link_title` is the title, and `remote_visibility` is `visible`. The save response SHALL include the created `profile_item_id`.

#### Scenario: Save a lead with body text

- **WHEN** the client calls `POST /leads/save` with a post that has a title and body
- **THEN** a `lead_posts` row exists for the post
- **AND** a `profile_item` of type `post` exists for the author's account containing the combined title and body
- **AND** the response includes a non-null `profile_item_id`

#### Scenario: Re-saving the same post

- **WHEN** `POST /leads/save` is called again for an already-saved post
- **THEN** the existing `lead_posts` row and `profile_item` are updated in place, not duplicated

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

### Requirement: Lead detail exposes post content and author context

`GET /leads/{lead_id}` SHALL return the lead's post content (title, body, source location, post URL, remote visibility) along with author account information, so the lead detail page can render the post together with the author's profile panel and analysis results.

#### Scenario: View a lead

- **WHEN** the user opens `/leads/<id>`
- **THEN** the post body and title are displayed
- **AND** the author's profile panel and any existing analysis are available on the same page

### Requirement: Contact can be initiated from a lead

`POST /conversations/initiate/from-lead/{lead_id}` SHALL start (or route to) a conversation with the lead's author. The flow SHALL check the `do_not_contact` list and block contact for listed usernames, and SHALL never send a message without an explicit user action.

#### Scenario: Contacting a lead's author

- **WHEN** the user triggers contact from a lead whose author is not on the do-not-contact list
- **THEN** an existing conversation with the author is opened if one exists, otherwise a compose flow for a new conversation is presented

#### Scenario: Author is on the do-not-contact list

- **WHEN** the user triggers contact for an author present in `do_not_contact`
- **THEN** the request is rejected and no conversation or message is created

### Requirement: Auto-analyze on save

After a successful save, the frontend SHALL trigger lead analysis fire-and-forget (`POST /leads/{id}/analyze`). Because the save already persisted the lead post as a profile item, the analysis pipeline SHALL find at least one profile item for the account and SHALL NOT report "no posts available" for a saved lead.

#### Scenario: Analysis right after save

- **WHEN** analysis starts immediately after `POST /leads/save` returns
- **THEN** at least the lead post itself is available to the analysis pipeline as a `profile_item`

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

### Requirement: At most one active lead per author

The system SHALL maintain at most one active lead per `(provider_id, author account)`, where an active lead is one whose status is not `ignored` and which is not locally deleted. When a post is saved (manually or by scout promotion) for an author who already has an active lead, the system SHALL attach the post to that lead — upserting the post as a `profile_item`, refreshing the lead's `updated_at`, and returning the existing lead — instead of creating a new `lead_posts` row. The save response SHALL indicate that an existing lead was updated rather than created.

#### Scenario: Saving a second post by the same author

- **WHEN** `POST /leads/save` is called for a post whose author already has an active lead (saved from a different post)
- **THEN** no new `lead_posts` row is created
- **AND** the post is upserted as a `profile_item` for the author's account
- **AND** the response returns the existing lead, marked as attached/updated

#### Scenario: Author's only lead is ignored

- **WHEN** a save or promotion occurs for an author whose only lead has status `ignored`
- **THEN** the ignored lead is not resurrected and no new lead is created via automated paths
- **AND** an explicit manual add-to-leads action MAY override the ignored verdict

#### Scenario: Authorless post

- **WHEN** a post with no resolvable author account is saved
- **THEN** the existing per-post upsert semantics (keyed by `provider_id`, `external_post_id`) apply unchanged

### Requirement: Historical duplicate leads can be merged

A maintenance task SHALL merge pre-existing duplicate-author leads: grouping active leads by `(provider_id, author account)`, keeping the lead with the newest post as the survivor, repointing analysis history and scout-post linkage to the survivor, and soft-deleting the losers (`deleted_at`; never hard-deleting, per the data-preservation principle). The task SHALL default to a dry run that reports the merge plan without mutating, and every applied merge SHALL be audit-logged.

#### Scenario: Dry run reports without mutating

- **WHEN** the merge task runs with dry_run enabled
- **THEN** a report of merge groups (survivor and losers per author) is produced
- **AND** no rows are modified

#### Scenario: Applied merge preserves history

- **WHEN** the merge task runs with dry_run disabled for an author with three duplicate leads
- **THEN** one lead (newest post) survives, the other two are soft-deleted
- **AND** all `lead_analyses` and scout-post links point at the survivor
- **AND** an audit entry records the merge group

### Requirement: Analysis results are retained permanently

Analysis output SHALL never be deleted by any retention, cleanup, or merge process, because re-deriving it costs a full agent pipeline run. This covers `lead_analyses` rows (including those with status `failed`, which may still own completed `analysis_dimensions` rows), `analysis_dimensions` rows, and the `dimension_results_json` stored on `scout_watch_posts` — which is often the only record of an analysis for a post that was never promoted to a lead.

Scout watch history retention MAY delete run records and sightings that carry no analysis output; sightings that do carry analysis SHALL be detached from the expiring run and retained.

#### Scenario: Failed analysis is retained

- **WHEN** the failed-analysis cleanup task runs against analyses older than its threshold
- **THEN** no `lead_analyses` or `analysis_dimensions` rows are deleted
- **AND** the task reports the count it would previously have removed

#### Scenario: History cleanup preserves analysed sightings

- **WHEN** scout watch history retention expires a run containing one analysed post and one analysis-free post
- **THEN** the analysed post is retained with its `dimension_results_json` intact
- **AND** the analysis-free post and the run record are deleted

#### Scenario: Merge preserves every analysis

- **WHEN** duplicate-author leads are merged
- **THEN** the total count of `lead_analyses` rows is unchanged
- **AND** every analysis is reachable from the surviving lead


### Requirement: Leads expose copies and prior knowledge of the same text
`GET /leads` items and `GET /leads/{id}` SHALL carry `copy` fields (cluster id, effective kind, distinct author count). Lead detail SHALL list the other authors of the same text with post time, account state, lead status, latest recommendation, effective human verdict, and links to their lead and profile. For `returning_author` clusters the earlier author's analysis SHALL be shown as context; it SHALL NOT change the lead's recommendation, priority, or status. `GET /leads` SHALL exclude leads whose post belongs to a handled spam ring unless `include_copies=true`; excluded leads are hidden, never deleted or changed. List queries SHALL remain batched per page.

#### Scenario: Spam-ring lead is hidden
- **WHEN** a saved lead's text belongs to a handled spam ring
- **THEN** the lead list and its count omit it, the lead keeps its status, and `include_copies=true` lists it again

#### Scenario: Lead written by a returning author
- **WHEN** the user opens a lead whose text was posted 60 days earlier by a now-deleted account that was `ignored`
- **THEN** lead detail shows that earlier account, its `ignored` status and its analysis, and the current lead's own analysis is unchanged

#### Scenario: Lead without copies
- **WHEN** a lead's fingerprint belongs to no cluster
- **THEN** `copy` is null and no badge is rendered
