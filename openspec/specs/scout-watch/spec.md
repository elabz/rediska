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

Posts seen by a watch SHALL be recorded in `scout_watch_posts` and deduplicated, so a post surfaced by multiple runs is processed at most once per watch.

#### Scenario: Same post in consecutive runs

- **WHEN** a run fetches a post already recorded for the watch
- **THEN** no duplicate `scout_watch_posts` row is created and the post is not re-analyzed

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

When an analyzed post's **code-computed** recommendation is `suitable` and its **code-computed** confidence score is greater than or equal to the watch's `min_confidence`, the system SHALL automatically create a lead with `lead_source='scout_watch'` linked back to the scout post. Model-reported confidence SHALL NOT be used for promotion. Posts whose recommendation is `needs_review` or `not_recommended`, or whose computed score is below the threshold, remain in history without a lead, with their per-gate results visible.

#### Scenario: High-scoring suitable post becomes a lead

- **WHEN** the gate evaluator yields `suitable` with a computed score ≥ `min_confidence` for a watch with auto-analyze on
- **THEN** a `lead_posts` row with `lead_source='scout_watch'` is created and linked to the scout post

#### Scenario: needs_review never auto-promotes

- **WHEN** the gate evaluator yields `needs_review` for a post, regardless of its computed score
- **THEN** no lead is created automatically
- **AND** the post remains in watch history with its per-gate reasons, available for manual add-to-leads

### Requirement: Manual promotion and re-analysis

The watch history UI SHALL allow manually adding any recorded post to leads (`POST .../posts/{post_id}/add-to-leads`) and re-analyzing a post with fresh provider data (`POST .../posts/{post_id}/reanalyze`), regardless of the auto-analyze outcome.

#### Scenario: Manually promoting a below-threshold post

- **WHEN** the user clicks add-to-leads on a post that did not meet `min_confidence`
- **THEN** a lead is created for the post with `lead_source='scout_watch'`

### Requirement: History retention cleanup

The `maintenance.cleanup_scout_watch_history` task SHALL run daily via beat and delete scout watch runs and posts older than the retention window (default 3 days), keeping the history tables bounded.

#### Scenario: Old runs are purged

- **WHEN** the daily cleanup runs with a 3-day retention
- **THEN** runs and posts older than 3 days are deleted while newer history is preserved
