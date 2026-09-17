# scout-watch Specification (delta)

## ADDED Requirements

### Requirement: Needs-review posts are listable and dismissible across watches

The system SHALL expose a cross-watch, cursor-paginated listing of analysed scout posts whose recommendation is `needs_review` and which have not been triaged — no `dismissed_at`, no `triaged_at`, no linked lead (`GET /scout-watches/needs-review`, newest first, optional `watch_id`), including watch context, stored dimension results with the gate verdict, effective evaluations, and the queue total. A dismiss action (`POST /scout-watches/posts/{post_id}/dismiss`) SHALL mark the post triaged-away (`dismissed_at`) without creating a lead, SHALL be refused for a post already promoted to a lead, and SHALL be audit-logged. Promoting a needs-review post via the existing add-to-leads endpoint SHALL mark it triaged (`triaged_at`) and SHALL give a new lead the priority tier and compatibility score derived from the post's stored analysis.

#### Scenario: Queue lists untriaged needs-review posts

- **WHEN** the client calls `GET /scout-watches/needs-review`
- **THEN** posts with recommendation `needs_review` and no `dismissed_at` are returned newest-first across all watches

#### Scenario: Dismissal removes a post from the queue

- **WHEN** the user dismisses a needs-review post
- **THEN** its `dismissed_at` is set, it no longer appears in the queue, and an audit entry records the dismissal

#### Scenario: Promotion removes a post from the queue

- **WHEN** the user adds a needs-review post to leads
- **THEN** its `triaged_at` is set, the created lead carries a priority tier, and the post no longer appears in the queue

## MODIFIED Requirements

### Requirement: Auto-promotion to leads by confidence

When an analyzed post's **code-computed** recommendation is `suitable` and its **code-computed** confidence score is greater than or equal to the watch's `min_confidence`, the system SHALL automatically create a lead with `lead_source='scout_watch'` linked back to the scout post — unless the author already has an active lead, in which case the post and its analysis SHALL be attached to the existing lead (the new `LeadAnalysis` is linked to it and the scout post's `lead_id` references it) and no new lead row is created. Model-reported confidence SHALL NOT be used for promotion. The created (or attached-to) lead SHALL persist the analysis-derived priority tier and `compatibility_score` (see the `leads` capability). Posts whose recommendation is `needs_review` or `not_recommended`, or whose computed score is below the threshold, remain in history without a lead, with their per-gate results visible.

#### Scenario: High-scoring suitable post becomes a lead

- **WHEN** the gate evaluator yields `suitable` with a computed score ≥ `min_confidence` for a watch with auto-analyze on and the author has no active lead
- **THEN** a `lead_posts` row with `lead_source='scout_watch'` is created and linked to the scout post
- **AND** the lead carries a priority tier and compatibility score from the analysis

#### Scenario: Qualifying post by an author with an existing lead

- **WHEN** the gate evaluator yields `suitable` with a computed score ≥ `min_confidence` and the author already has an active lead
- **THEN** no new lead is created
- **AND** the analysis record and the scout post are linked to the existing lead
- **AND** the existing lead's `updated_at` is refreshed and its priority tier reflects the new analysis

#### Scenario: needs_review never auto-promotes

- **WHEN** the gate evaluator yields `needs_review` for a post, regardless of its computed score
- **THEN** no lead is created automatically
- **AND** the post remains in watch history with its per-gate reasons and appears in the needs-review queue

### Requirement: History retention cleanup

The `maintenance.cleanup_scout_watch_history` task SHALL run daily via beat and delete scout watch runs older than the retention window (default 3 days), keeping the history tables bounded. Analysis results are never deleted: posts that carry analysis output are detached from an expiring run and retained, and only analysis-free sightings are deleted with it. Consequently a `needs_review` post stays available to the needs-review queue regardless of age until a human triages it, and a dismissed or promoted post keeps its analysis.

#### Scenario: Old runs are purged

- **WHEN** the daily cleanup runs with a 3-day retention
- **THEN** runs older than 3 days and their analysis-free sightings are deleted while newer history is preserved

#### Scenario: Untriaged needs-review post survives retention

- **WHEN** the daily cleanup runs and a 5-day-old post has recommendation `needs_review` with no `dismissed_at`/`triaged_at`
- **THEN** the post is retained and still listed in the needs-review queue

#### Scenario: Dismissed needs-review post keeps its analysis

- **WHEN** a needs-review post was dismissed more than 3 days ago and the cleanup runs
- **THEN** the post and its stored analysis are retained, and it does not reappear in the queue
