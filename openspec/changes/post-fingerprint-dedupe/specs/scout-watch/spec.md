## ADDED Requirements

### Requirement: Ring-suspect copies skip the analysis pipeline
Before the profile-fetch stage of `scout.analyze_and_decide`, and after the do-not-contact check, the system SHALL check the post's copy cluster. When `COPY_SKIP_RING_SUSPECTS` is true and the cluster's effective kind is `ring_suspect` or `confirmed_ring`, the post SHALL be recorded with `analysis_status='skipped'` and reason `copy_ring_suspect`, remain visible in watch history with its cluster link, consume no profile fetch or LLM call, and never be auto-promoted. Manual add-to-leads and manual re-analysis SHALL still work. Clusters of kind `returning_author` or `unclassified` SHALL NOT skip. Source-discovery trials SHALL NOT apply the skip but SHALL count ring-suspect posts in the yield report.

#### Scenario: Second account of a ring posts
- **WHEN** a watch records a post whose text matches a post made three days earlier by another live account
- **THEN** the scout post is `skipped` with reason `copy_ring_suspect` and no inference call is made

#### Scenario: Returning author is analysed normally
- **WHEN** a watch records a post whose cluster kind is `returning_author`
- **THEN** the pipeline runs normally and the scout post carries the cluster link

#### Scenario: Skip disabled
- **WHEN** `COPY_SKIP_RING_SUSPECTS` is false
- **THEN** ring-suspect posts are analysed and carry the copy badge, and are still never auto-promoted

### Requirement: Scout read models carry copy information
Scout run detail, watch history posts and the needs-review queue SHALL include, per post, `copy` fields (cluster id, effective kind, distinct author count, earliest other post time), attached with batched queries per page.

#### Scenario: Needs-review post with a copy
- **WHEN** a needs-review post belongs to a cluster
- **THEN** the queue item shows the copy badge with kind and author count
