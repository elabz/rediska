# scout-watch Specification (delta)

## ADDED Requirements

### Requirement: Needs-review posts are listable and dismissible across watches

The system SHALL expose a cross-watch, cursor-paginated listing of scout posts whose analysis recommendation is `needs_review` and which have not been dismissed (`GET /scout-watches/needs-review`), including watch context and dimension results for display. A dismiss action (`POST /scout-watches/posts/{post_id}/dismiss`) SHALL mark the post triaged-away (`dismissed_at`) without creating a lead, and SHALL be audit-logged. Promoting a needs-review post via the existing add-to-leads endpoint SHALL mark it triaged (`triaged_at`).

#### Scenario: Queue lists untriaged needs-review posts

- **WHEN** the client calls `GET /scout-watches/needs-review`
- **THEN** posts with recommendation `needs_review` and no `dismissed_at` are returned newest-first across all watches

#### Scenario: Dismissal removes a post from the queue

- **WHEN** the user dismisses a needs-review post
- **THEN** its `dismissed_at` is set, it no longer appears in the queue, and an audit entry records the dismissal

## MODIFIED Requirements

### Requirement: Auto-promotion to leads by confidence

When an analyzed post's final confidence is greater than or equal to the watch's `min_confidence`, the system SHALL automatically create a lead with `lead_source='scout_watch'` linked back to the scout post. The created lead SHALL persist the analysis-derived priority tier and `compatibility_score` (see the `leads` capability). Posts below the threshold remain in history without a lead.

#### Scenario: High-confidence post becomes a lead

- **WHEN** analysis yields confidence ≥ `min_confidence` for a watch with auto-analyze on
- **THEN** a `lead_posts` row with `lead_source='scout_watch'` is created and linked to the scout post
- **AND** the lead carries a priority tier and compatibility score from the analysis

### Requirement: History retention cleanup

The `maintenance.cleanup_scout_watch_history` task SHALL run daily via beat and delete scout watch runs and posts older than the retention window (default 3 days), keeping the history tables bounded — with one exemption: posts with recommendation `needs_review` that have not been dismissed or promoted SHALL be retained for a longer window (`SCOUT_NEEDS_REVIEW_RETENTION_DAYS`, default 14) so the triage queue is not purged before a human sees it. Once dismissed or promoted, such posts follow the normal window measured from their triage time.

#### Scenario: Old runs are purged

- **WHEN** the daily cleanup runs with a 3-day retention
- **THEN** runs and posts older than 3 days are deleted while newer history is preserved

#### Scenario: Untriaged needs-review post survives normal retention

- **WHEN** the daily cleanup runs and a 5-day-old post has recommendation `needs_review` with no `dismissed_at`/`triaged_at`
- **THEN** the post is retained

#### Scenario: Dismissed needs-review post is purged normally

- **WHEN** a needs-review post was dismissed more than 3 days ago
- **THEN** the cleanup deletes it
