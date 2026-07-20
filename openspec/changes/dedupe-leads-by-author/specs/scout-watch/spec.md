# scout-watch Specification (delta)

## ADDED Requirements

### Requirement: Prior verdicts skip the analysis pipeline

Before starting the profile-fetch stage of `scout.analyze_and_decide`, the system SHALL check the post author's standing verdicts and skip the pipeline entirely when any of the following hold: the author is on the `do_not_contact` list; the author's account is already `contacted` or `engaged`; or the author has an existing lead with status `ignored`. Skipped posts SHALL be recorded with `analysis_status='skipped'` and a stored reason, remain visible in watch history, and consume no provider-profile fetches or LLM calls.

#### Scenario: Ignored author re-posts

- **WHEN** a watch records a new post by an author whose existing lead is `ignored`
- **THEN** `analyze_and_decide` marks the scout post `skipped` with the reason before fetching the profile
- **AND** no summary or agent inference calls are made for the post

#### Scenario: Do-not-contact author

- **WHEN** a recorded post's author is on `do_not_contact`
- **THEN** the scout post is skipped with a do-not-contact reason and no analysis runs

## MODIFIED Requirements

### Requirement: Post deduplication

Posts seen by a watch SHALL be recorded in `scout_watch_posts` and deduplicated, so a post surfaced by multiple runs is processed at most once per watch. In addition, lead creation SHALL be deduplicated at the author level across all watches: qualifying posts by an author who already has an active lead attach to that lead rather than creating a new one, so cross-posting to multiple watched subreddits yields a single lead.

#### Scenario: Same post in consecutive runs

- **WHEN** a run fetches a post already recorded for the watch
- **THEN** no duplicate `scout_watch_posts` row is created and the post is not re-analyzed

#### Scenario: Same author across two watches

- **WHEN** two different watches each surface a (different) qualifying post by the same author
- **THEN** at most one active lead exists for that author
- **AND** both scout posts link to that single lead

### Requirement: Auto-promotion to leads by confidence

When an analyzed post's final confidence is greater than or equal to the watch's `min_confidence`, the system SHALL automatically create a lead with `lead_source='scout_watch'` linked back to the scout post — unless the author already has an active lead, in which case the post and its analysis SHALL be attached to the existing lead (the new `LeadAnalysis` is linked to it and the scout post's `lead_id` references it) and no new lead row is created. Posts below the threshold remain in history without a lead.

#### Scenario: High-confidence post becomes a lead

- **WHEN** analysis yields confidence ≥ `min_confidence` for a watch with auto-analyze on and the author has no active lead
- **THEN** a `lead_posts` row with `lead_source='scout_watch'` is created and linked to the scout post

#### Scenario: High-confidence post by an author with an existing lead

- **WHEN** analysis yields confidence ≥ `min_confidence` and the author already has an active lead
- **THEN** no new lead is created
- **AND** the analysis record and the scout post are linked to the existing lead
- **AND** the existing lead's `updated_at` is refreshed
