# source-discovery Specification

## Purpose
Proposes new lead sources from data already stored and lets the user test them before watching. It mines communities over-represented in qualified authors' history and recurring unregistered external hosts. Candidates have a human-controlled lifecycle, can be previewed and trialled on a bounded sample through the normal scout pipeline without auto-promotion, and are shown with the same yield metrics as existing watches. Nothing is watched or fetched without an explicit user action.

## Requirements

### Requirement: Candidate locations are mined from stored author history

A scheduled task SHALL compute candidate locations from data already stored, without calling the provider. For each location name present in `profile_items`, it SHALL count distinct **qualified** authors (an author with a lead whose latest analysis is `suitable`, or whose account is contacted or engaged, or whose suitable verdict has an effective human `agree`) and distinct **analysed** authors overall, and SHALL compute a lift score as the location's share among qualified authors divided by its share among all analysed authors. A location SHALL become a candidate only when it has at least the configured minimum number of distinct qualified authors (`DISCOVERY_MIN_QUALIFIED_AUTHORS`, default 3), is not the `source_location` of an existing scout watch, and is not dismissed. Authors on the do-not-contact list and soft-deleted leads SHALL NOT count as qualified. Each candidate SHALL store its evidence: both counts, the lift, and the computation time. Recomputation SHALL update existing candidates in place and SHALL NOT resurrect dismissed ones.

#### Scenario: Over-represented community becomes a candidate

- **WHEN** a community appears in the history of 6 qualified authors and 9 analysed authors overall, and is not watched
- **THEN** a candidate of kind `location` exists with those counts and a lift above 1

#### Scenario: Thin evidence is not surfaced

- **WHEN** a community appears in the history of only 1 qualified author
- **THEN** no candidate is created for it

#### Scenario: Already watched community is excluded

- **WHEN** a community is the source location of an active or inactive scout watch
- **THEN** it is not listed as a candidate

#### Scenario: Popular but uninformative community ranks low

- **WHEN** a large general community appears equally often among qualified and non-qualified authors
- **THEN** its lift is about 1 and it sorts below communities specific to qualified authors

### Requirement: Recurring external hosts are surfaced as parser candidates

The same task SHALL tally the hosts of outbound URLs found on link-only posts seen by scout watches and browse, and on stored items of qualified authors, after stripping tracking parameters. A host that recurs at least the configured minimum number of times and is not in the external-listing registry SHALL become a candidate of kind `external_host`, carrying the count and up to five example URLs. The system SHALL NOT fetch any URL on an unregistered host as part of discovery.

#### Scenario: Unknown listing site recurs

- **WHEN** twelve link-only posts in a month point at the same unregistered host
- **THEN** an `external_host` candidate lists that host with its count and example URLs, and no request is made to the host

#### Scenario: Registered host is not a candidate

- **WHEN** link-only posts point at a host already in the external-listing registry
- **THEN** no candidate is created for that host

### Requirement: Candidates have a human-controlled lifecycle

A candidate SHALL be in one of `new`, `trialled`, `accepted`, `dismissed`, or `snoozed`. `GET /source-candidates` SHALL list candidates with kind, evidence, location info when available, latest trial yield, and status, filterable by kind and status, sorted by lift descending by default, with cursor pagination. `POST /source-candidates/{id}/dismiss` SHALL set `dismissed` permanently until the user restores it; `POST /source-candidates/{id}/snooze` SHALL hide it until a given date; `POST /source-candidates/{id}/accept` SHALL create a scout watch pre-filled with the location and the settings supplied by the user, link the watch to the candidate, and set `accepted`. The system SHALL NOT create, activate, or modify a scout watch from a candidate without that explicit request. Every one of these mutations SHALL write `audit_log`.

#### Scenario: Dismissed candidate stays dismissed

- **WHEN** the user dismisses a candidate and the mining task runs again with stronger evidence for it
- **THEN** its evidence is updated but its status stays `dismissed` and it is absent from the default list

#### Scenario: Accept creates a watch once

- **WHEN** the user accepts a location candidate with a query and sort order
- **THEN** one scout watch is created for that location, the candidate becomes `accepted` and links to the watch, and an `audit_log` row records the action

#### Scenario: Nothing is watched automatically

- **WHEN** the mining task finds a candidate with very high lift
- **THEN** no scout watch is created and no posts are fetched until the user acts

### Requirement: A candidate can be trialled on a bounded sample

`POST /source-candidates/{id}/trial` SHALL enqueue a trial for a `location` candidate: fetch up to the configured sample size of recent posts (`DISCOVERY_TRIAL_SAMPLE`, default 25, hard cap 50), resolve link-only bodies through the external-listing resolver, and run each post through the same per-post analysis pipeline as a scout watch, recorded under the trial so they are distinguishable from regular watch posts. Trial posts SHALL NOT be auto-promoted to leads regardless of score, SHALL be excluded from the cross-watch needs-review queue by default, and SHALL honour prior author verdicts and the do-not-contact list exactly as scout runs do. The trial SHALL use the `jobs` ledger, SHALL be cancellable between posts, SHALL share the inference concurrency gate, and only one trial SHALL run at a time. On completion the trial SHALL store a yield report: posts fetched, skipped empty, link-only resolved, counts per recommendation, the most frequent failing gate, and median post age. The candidate SHALL become `trialled`. The user MAY promote an individual trial post to a lead through the existing manual add-to-leads action.

#### Scenario: Trial produces a yield report

- **WHEN** a trial of 25 posts completes with 4 suitable, 6 needs_review, and 15 not_recommended
- **THEN** the candidate shows that breakdown, the top failing gate, and status `trialled`, and no lead was created

#### Scenario: High-scoring trial post is not auto-promoted

- **WHEN** a trial post scores above every watch's `min_confidence`
- **THEN** it remains a trial post until the user manually adds it to leads

#### Scenario: Second trial is refused while one runs

- **WHEN** a trial is requested while another trial is `running`
- **THEN** the request is rejected with a conflict and no job is enqueued

#### Scenario: External host cannot be trialled

- **WHEN** a trial is requested for an `external_host` candidate
- **THEN** the request is rejected, because unregistered hosts are never fetched

### Requirement: Location search supports manual exploration

`GET /source-candidates/search?q=` SHALL call the provider's location search through the selected identity and return normalized location summaries, each annotated with whether it is already watched, already a candidate, or dismissed. `POST /source-candidates` SHALL let the user add a searched location as a candidate of origin `manual`, after which it follows the same lifecycle including trial. Results SHALL NOT be filtered by NSFW status.

#### Scenario: Search result added as candidate

- **WHEN** the user searches a keyword and adds one result
- **THEN** a `manual` candidate is created with the provider's location info and can be trialled

#### Scenario: Watched location is marked

- **WHEN** a search result is already a scout watch's location
- **THEN** it is returned marked as watched and cannot be added again

### Requirement: Existing watches report yield on the same terms

The scout-watch read model SHALL include, per watch over a trailing window (default 30 days), the same yield metrics a trial reports: posts seen, counts per recommendation, leads created, and leads that reached contacted or engaged. The metrics SHALL be computed by plain aggregation with no LLM call.

#### Scenario: Low-yield watch is visible

- **WHEN** a watch saw 400 posts in 30 days and produced no suitable verdicts
- **THEN** the watch list shows that yield next to the watch so it can be compared with candidates

### Requirement: Discover tab on the scout watches page

`/settings/scout-watches` SHALL offer a **Discover** tab listing candidates with their evidence, location info, and latest trial yield, with actions to run or cancel a trial, create a watch, snooze, dismiss, and restore a dismissed candidate, plus the keyword search. A running trial SHALL show progress. The tab SHALL have empty, loading, and error states, and SHALL explain in the empty state that candidates appear once enough analysed authors exist.

#### Scenario: Empty state

- **WHEN** no candidate meets the evidence floor
- **THEN** the tab shows an explanatory empty state and the keyword search remains usable

#### Scenario: Trial progress

- **WHEN** a trial is running
- **THEN** the candidate row shows posts analysed out of the sample size and a cancel action

### Requirement: Locations that forbid contact or no longer exist are not proposed as usable

When location info is fetched, the provider SHALL also return the community's rules. The system SHALL flag a location whose rules or description forbid approaching posters for dating, hookups, or private messages. The flag SHALL store the matching rule verbatim, and the Discover tab SHALL show it. The match SHALL be conservative: rules that only restrict how contact happens SHALL NOT flag, e.g. no personal info, no unsolicited messages, no paid solicitation. The candidate list SHALL hide locations that are private, banned, or missing from every view except `status=all`. It SHALL hide flagged locations when `hide_restricted` is requested; the UI requests this by default.

#### Scenario: Community forbids personals

- **WHEN** a candidate community has the rule "No personals: seeking meetups will get you banned"
- **THEN** the candidate is flagged with that rule quoted and is hidden while "hide restricted" is on

#### Scenario: Personals community with a privacy rule is not flagged

- **WHEN** a personals community has the rule "No personal info: no phone numbers or usernames"
- **THEN** the candidate is not flagged

#### Scenario: Banned community disappears

- **WHEN** the location lookup finds a candidate community banned or missing
- **THEN** the candidate no longer appears in the default candidate list

### Requirement: A candidate can be previewed with the watches' search before any trial

The Discover tab SHALL offer a "Preview search" action on location candidates and search results. It SHALL open the Browse page in a new tab, on that location, with the watches' longest search query, sorted by new. The Browse page SHALL run a search given by `location`, `q`, `sort`, and `t` URL parameters on load. A watch created from a candidate SHALL be pre-filled with the same query.

#### Scenario: Preview opens Browse with the match string

- **WHEN** the user clicks "Preview search" on r/example
- **THEN** a new tab opens `/browse?location=r/example&q=<longest watch query>&sort=new&t=month` and the search runs without further input
