## ADDED Requirements

### Requirement: Spam-ring copies skip the analysis pipeline
Before the profile-fetch stage of `scout.analyze_and_decide`, and after the do-not-contact check, the system SHALL check the post's copy cluster. When `COPY_SKIP_RING_SUSPECTS` is true and the cluster is handled as a spam ring (see post-copy-detection), the post SHALL be recorded with `analysis_status='skipped'` and reason `copy_ring_suspect`, remain visible in watch history with its cluster link, and consume no profile fetch or LLM call. A post in any `ring_suspect` or `confirmed_ring` cluster SHALL never be auto-promoted, handled or not. Manual add-to-leads and manual re-analysis SHALL still work. Clusters of kind `returning_author` or `unclassified` SHALL NOT skip. Source-discovery trials SHALL NOT apply the skip but SHALL count ring-suspect posts in the yield report.

#### Scenario: Third account of a ring posts
- **WHEN** a watch records a 900-character post whose text two other live accounts posted in the last three days
- **THEN** the scout post is `skipped` with reason `copy_ring_suspect` and no inference call is made

#### Scenario: Two accounts or a short template
- **WHEN** a post's ring-suspect cluster has two authors, or its posts average under `COPY_RING_MIN_CHARS`
- **THEN** the post is analysed and carries the copy badge, and is never auto-promoted

#### Scenario: Returning author is analysed normally
- **WHEN** a watch records a post whose cluster kind is `returning_author`
- **THEN** the pipeline runs normally and the scout post carries the cluster link

#### Scenario: Skip disabled
- **WHEN** `COPY_SKIP_RING_SUSPECTS` is false
- **THEN** ring-suspect posts are analysed and carry the copy badge, and are still never auto-promoted

### Requirement: Scout read models carry copy information
Scout run detail, watch history posts and the needs-review queue SHALL include, per post, `copy` fields (cluster id, effective kind, distinct author count, whether the cluster is handled, earliest other post time), attached with batched queries per page. The needs-review queue SHALL exclude posts of handled spam rings unless `include_copies=true`.

#### Scenario: Needs-review post with a copy
- **WHEN** a needs-review post belongs to a cluster
- **THEN** the queue item shows the copy badge with kind and author count
