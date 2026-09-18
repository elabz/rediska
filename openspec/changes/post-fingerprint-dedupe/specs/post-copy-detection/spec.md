## ADDED Requirements

### Requirement: Every post seen is fingerprinted
The system SHALL store one `post_fingerprints` row per provider post that reaches it through scout runs (including posts later skipped or filtered), source-discovery trials, browse ingest, saved leads, and profile items of type post. The row SHALL hold the author, post time, first-seen time, an exact hash of the normalised body, and a MinHash sketch over 5-word shingles. The row SHALL NOT hold post text. Bodies shorter than `COPY_MIN_CHARS` SHALL get an exact hash only. The fingerprint SHALL be computed on the resolved body, excluding any structured details block prepended for external listings, and SHALL be computed over verbatim text without any content filtering.

#### Scenario: Scout post is fingerprinted before analysis
- **WHEN** a scout run records a post with a 900-character body
- **THEN** a `post_fingerprints` row with exact hash and sketch exists before `scout.analyze_and_decide` starts

#### Scenario: Same post arrives through two paths
- **WHEN** a post already fingerprinted by a scout run is later saved as a lead
- **THEN** no second fingerprint row is created for that `external_post_id`

#### Scenario: Fingerprint outlives history cleanup
- **WHEN** `maintenance.cleanup_scout_watch_history` deletes a scout post older than the retention window
- **THEN** its `post_fingerprints` row and cluster membership remain

### Requirement: Copies by other authors are detected at ingest
When a fingerprint is created, the system SHALL look up stored fingerprints sharing a sketch band, estimate Jaccard similarity from the sketches, and treat a post by a different author with estimated similarity at or above `COPY_JACCARD_THRESHOLD` (default 0.5) as a copy. The lookup SHALL make no LLM, embeddings, or provider call. Matches by the same author SHALL be recorded as reposts and SHALL NOT form a cluster. Bands shared by more than 200 fingerprints SHALL be ignored for candidate generation.

#### Scenario: Identical text from a second account
- **WHEN** account B posts a body whose normalised text equals a body posted earlier by account A
- **THEN** both fingerprints belong to the same copy cluster with two distinct authors

#### Scenario: Lightly edited copy
- **WHEN** account B posts A's text with one paragraph changed so that about 70% of 5-word shingles are shared
- **THEN** the posts are clustered

#### Scenario: Author reposts their own ad
- **WHEN** account A posts the same text again a week later
- **THEN** the new fingerprint references the earlier one as a repost and no cluster is created

### Requirement: Copy clusters are classified from stored facts
Each cluster SHALL carry a computed kind. It SHALL be `ring_suspect` when two or more authors whose accounts are not deleted or suspended posted the copy within `COPY_RING_WINDOW_DAYS` of each other, or when the cluster has three or more distinct authors. It SHALL be `returning_author` when it has exactly two authors, the gap exceeds the window, and the earlier account is deleted, suspended, or has no stored activity after the later account's first activity. Otherwise it SHALL be `unclassified`. The kind SHALL be recomputed whenever membership or a member account's remote status changes.

#### Scenario: Two live accounts, two days apart
- **WHEN** live accounts A and B post the same text two days apart
- **THEN** the cluster kind is `ring_suspect`

#### Scenario: Deleted account comes back
- **WHEN** account A (now deleted) posted a text 60 days before account B posts a lightly edited copy
- **THEN** the cluster kind is `returning_author`

### Requirement: The human decides what a cluster means
`POST /copy-clusters/{id}/decision` SHALL accept `confirmed_ring`, `same_person`, or `coincidence` with optional notes, SHALL override the computed kind until changed, and SHALL write `audit_log`. `coincidence` SHALL dissolve the cluster and record a suppression so the same texts do not cluster again. No decision SHALL change any lead status, analysis, or ban entry by itself.

#### Scenario: Template text marked as coincidence
- **WHEN** the user marks a cluster as `coincidence`
- **THEN** the cluster no longer appears in any view and a later post with the same text does not re-create it

### Requirement: Copy clusters are listable and inspectable
`GET /copy-clusters` SHALL list clusters with kind, decision, distinct author count, first and last post time, and cursor pagination, filterable by kind and decision. `GET /copy-clusters/{id}` SHALL return members with author, account remote status, post time, source, and links to any lead, scout post, analysis, lead status, human evaluation, and do-not-contact entry for that author. The Leads page SHALL provide a Copies tab over these endpoints with empty and error states.

#### Scenario: Inspecting a ring
- **WHEN** the user opens a `ring_suspect` cluster
- **THEN** every member author is listed with post time, account state, and the verdicts already held for them

### Requirement: Stored posts are backfilled
`copy.backfill_fingerprints` SHALL fingerprint all stored post bodies (scout posts, lead posts, profile items of type post), deduplicated by provider post id, build clusters, use the `jobs` ledger for idempotency, default to a dry run that reports counts, and write one batch audit entry on a live run.

#### Scenario: Dry run
- **WHEN** the task runs with `dry_run=true`
- **THEN** it reports fingerprints and clusters it would create and writes nothing
