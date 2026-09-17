# scout-watch Specification (delta)

## ADDED Requirements

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
