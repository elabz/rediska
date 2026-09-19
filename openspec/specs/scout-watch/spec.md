# scout-watch Specification

## Purpose
Scout Watch automates lead discovery: saved provider searches ("watches") run periodically in the background, record newly seen posts, optionally push each post through the full profile-fetch → summarize → multi-agent-analysis pipeline, and auto-promote posts that score above a confidence threshold into leads. Run history and per-post pipeline status are visible and manageable from the settings UI.
## Requirements
### Requirement: Watch configuration

A scout watch SHALL be configurable with a location/search query, sort, time filter, associated identity, `auto_analyze` toggle, `min_confidence` threshold, and an active flag, via the `/scout-watches` CRUD API and the `/settings/scout-watches` UI. Watches SHALL carry denormalized run statistics for display.

#### Scenario: Creating a watch

- **WHEN** the user creates a watch with a query, sort, time filter, and identity
- **THEN** the watch is persisted in `scout_watches` and appears in the watch list with its configuration and stats

### Requirement: Scheduled and manual runs

The `scout.run_all_watches` Celery task SHALL run every 300 seconds via beat and execute all active watches; `POST /scout-watches/{watch_id}/run` SHALL trigger a single watch immediately. Each run SHALL be recorded in `scout_watch_runs` with statistics (posts fetched, new posts, analyzed, leads created) and the provider `search_url` used.

#### Scenario: Periodic execution

- **WHEN** the beat schedule fires `scout.run_all_watches`
- **THEN** every active watch executes and a `scout_watch_runs` row records each run's stats

#### Scenario: Inactive watch is skipped

- **WHEN** a watch's active flag is off
- **THEN** scheduled runs do not execute it

### Requirement: Post deduplication

Posts seen by a watch SHALL be recorded in `scout_watch_posts` and deduplicated, so a post surfaced by multiple runs is processed at most once per watch. In addition, lead creation SHALL be deduplicated at the author level across all watches: qualifying posts by an author who already has an active lead attach to that lead rather than creating a new one, so cross-posting to multiple watched subreddits yields a single lead.

#### Scenario: Same post in consecutive runs

- **WHEN** a run fetches a post already recorded for the watch
- **THEN** no duplicate `scout_watch_posts` row is created and the post is not re-analyzed

#### Scenario: Same author across two watches

- **WHEN** two different watches each surface a (different) qualifying post by the same author
- **THEN** at most one active lead exists for that author
- **AND** both scout posts link to that single lead

### Requirement: Recorded posts create profile items

When `record_post` creates a `scout_watch_posts` row with an associated author account, it SHALL also upsert the post's content as a `profile_item` for that account, so downstream analysis has the post text even if the author's public profile hides it.

#### Scenario: Watch records a post by a known author

- **WHEN** a watch records a post whose author has an `external_accounts` row
- **THEN** a `profile_item` of type `post` containing the post body exists for that account

### Requirement: Per-post analysis pipeline with visible states

With `auto_analyze` enabled, each new post SHALL move through the pipeline states `pending` → `fetching_profile` → `summarizing` → `analyzing` → terminal `analyzed`, `skipped`, or `failed` (task `scout.analyze_and_decide`). Profile fetching SHALL be limited to at most 20 posts and 100 comments per author. Dimension results SHALL be stored on the post (`dimension_results_json`) alongside interests/character summaries.

#### Scenario: Post completes the pipeline

- **WHEN** auto-analysis finishes for a recorded post
- **THEN** the post's status is `analyzed` and its dimension results and summaries are stored and visible in the watch history UI

#### Scenario: Pipeline failure is terminal and visible

- **WHEN** a pipeline stage fails after retries
- **THEN** the post's status is `failed` and the failure is visible in the run history

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

### Requirement: Manual promotion and re-analysis

The watch history UI SHALL allow manually adding any recorded post to leads (`POST .../posts/{post_id}/add-to-leads`) and re-analyzing a post with fresh provider data (`POST .../posts/{post_id}/reanalyze`), regardless of the auto-analyze outcome.

#### Scenario: Manually promoting a below-threshold post

- **WHEN** the user clicks add-to-leads on a post that did not meet `min_confidence`
- **THEN** a lead is created for the post with `lead_source='scout_watch'`

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

### Requirement: Scout post analyses can be evaluated and evaluated posts are retained

A scout watch post that carries analysis results (`dimension_results_json` with a recommendation) SHALL be an evaluation subject per the `analysis-evaluation` capability regardless of whether it was promoted to a lead. Recording any evaluation on a scout post SHALL set `scout_watch_posts.evaluated_at`. The `maintenance.cleanup_scout_watch_history` task SHALL NOT delete posts with `evaluated_at` set, and SHALL NOT delete a run while any of its posts is retained. Scout watch history post responses SHALL include the effective evaluations.

#### Scenario: Evaluated not_recommended post survives cleanup

- **WHEN** a 10-day-old scout post with recommendation `not_recommended` has an evaluation and the daily cleanup runs with 3-day retention
- **THEN** the post and its run are retained while unevaluated 10-day-old posts are deleted

#### Scenario: Evaluation from watch history

- **WHEN** the user evaluates the final verdict of a post from a watch's history page
- **THEN** the evaluation is stored against the scout post and the history response shows the evaluated state

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

### Requirement: Prior verdicts skip the analysis pipeline

Before starting the profile-fetch stage of `scout.analyze_and_decide`, the system SHALL check the post author's standing verdicts and skip the pipeline entirely when any of the following hold: the author is on the `do_not_contact` list; the author's account is already `contacted` or `engaged`; or the author has an existing lead with status `ignored` **and the incoming post's content has already been analysed for that author**. Skipped posts SHALL be recorded with `analysis_status='skipped'` and a stored reason, remain visible in watch history, and consume no provider-profile fetches or LLM calls.

The `ignored` verdict is content-sensitive: it suppresses content already judged, not the author permanently. Content identity SHALL be determined by a fingerprint of the post's title and body, normalised for case and whitespace so that trivial reformatting is not treated as a change. The `do_not_contact`, `contacted`, and `engaged` verdicts are unconditional — they concern the relationship, not the post — and SHALL skip regardless of content.

#### Scenario: Ignored author re-posts the same content

- **WHEN** a watch records a post by an author whose existing lead is `ignored`, and the post's content fingerprint matches content already analysed for that author
- **THEN** `analyze_and_decide` marks the scout post `skipped` with the reason before fetching the profile
- **AND** no summary or agent inference calls are made for the post

#### Scenario: Ignored author posts new content

- **WHEN** a watch records a post by an author whose existing lead is `ignored`, and the post's content fingerprint matches nothing previously analysed for that author
- **THEN** the pipeline runs normally and the post is analysed again
- **AND** the earlier `ignored` verdict does not suppress it

#### Scenario: Do-not-contact author

- **WHEN** a recorded post's author is on `do_not_contact`
- **THEN** the scout post is skipped with a do-not-contact reason and no analysis runs
- **AND** this holds regardless of whether the post's content is new


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
