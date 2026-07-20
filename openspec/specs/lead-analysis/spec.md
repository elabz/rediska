# lead-analysis Specification

## Purpose
Lead-analysis evaluates a saved lead's author using local LLM inference. It comprises a single-pass analysis pipeline, a multi-dimensional multi-agent analysis (five specialized dimension agents plus a meta-analysis coordinator), versioned editable agent prompts, and resilience rules ensuring analysis proceeds even when the provider returns no profile items. All analysis runs against the locally configured llama.cpp inference endpoint; results are stored locally.

## Requirements

### Requirement: Single-pass analysis

`POST /leads/{lead_id}/analyze` SHALL run the single-pass analysis pipeline: fetch the author's profile metadata, create/update a `profile_snapshots` row, fetch and store profile items, index and embed content, and update the account's `analysis_state`.

#### Scenario: Analyze a saved lead

- **WHEN** the client calls `POST /leads/{lead_id}/analyze`
- **THEN** a profile snapshot is created or updated for the lead's author
- **AND** the author's `analysis_state` is updated when the pipeline completes

### Requirement: Multi-agent analysis runs six agents

`POST /leads/{lead_id}/analyze-multi` SHALL enqueue the `multi_agent_analysis.analyze_lead` Celery task, which runs five dimension agents — Demographics (age, gender, location), Preferences (hobbies, kinks, compatibility), Relationship Goals (intent, partner criteria, deal-breakers), Risk Flags (scam/seller detection, authenticity, red flags), and Sexual Preferences (orientation, intimacy/kink preferences) — followed by a Meta-Analysis coordinator that is **advisory only**: it synthesizes reasoning, strengths, concerns, and a priority level, but the `final_recommendation` (`suitable`, `not_recommended`, `needs_review`) and the gating confidence score SHALL be computed deterministically by the code gate evaluator from the structured dimension outputs. Results are stored in `lead_analyses`.

#### Scenario: Completed multi-agent analysis

- **WHEN** `multi_agent_analysis.analyze_lead` completes for a lead
- **THEN** a `lead_analyses` row holds each dimension's structured result, the advisory meta-analysis output, the code-computed final recommendation, and the code-computed confidence score

#### Scenario: Meta agent cannot flip a gate verdict

- **WHEN** the code gate evaluator produces a recommendation and the LLM meta agent's own output disagrees
- **THEN** the stored `final_recommendation` is the gate evaluator's verdict
- **AND** the meta agent's disagreeing output remains available as advisory context only

#### Scenario: Demographics location classification is offline

- **WHEN** the Demographics agent produces a location for the subject
- **THEN** the location classification is computed by the offline geocoder (haversine distance from the configured home coordinates against `LOCATION_NEAR_THRESHOLD_MILES`) as one of `near`, `far`, or `unclear`
- **AND** no external geocoding API is called

### Requirement: Hard gates are evaluated deterministically and fail closed

The system SHALL evaluate the five hard gates — gender, location, D/s compatibility, partner max age against the configured user age, and authenticity/red flags — in code, as a pure function over the structured dimension outputs, identically for the API and scout entry points. Each gate SHALL yield `pass`, `fail`, or `unclear`; a missing, failed, or unparseable gate input SHALL yield `unclear`, never `pass`. The verdict SHALL be: any gate `fail` → `not_recommended`; otherwise any gate `unclear` → `needs_review`; otherwise `suitable`. Per-gate results and reasons SHALL be stored with the analysis.

#### Scenario: Failed relationship_goals dimension no longer passes the age gate

- **WHEN** the relationship_goals dimension fails (or returns no parseable `partner_max_age`) and all other gates pass
- **THEN** the age gate is `unclear` and the final recommendation is `needs_review`
- **AND** the analysis is not marked `suitable`

#### Scenario: Author rejects the user's age

- **WHEN** the relationship_goals output contains `partner_max_age` lower than the configured user age
- **THEN** the age gate fails and the final recommendation is `not_recommended` with the age gate cited as the reason

#### Scenario: Prompt drift produces unparseable fields

- **WHEN** an edited dimension prompt yields output whose gate-relevant field is missing or has an unrecognized value
- **THEN** the affected gate is `unclear` (fail-closed) and the per-gate reason identifies the missing field

### Requirement: Virtual and un-geocodable locations are unclear, not near or far

The offline location classifier SHALL classify virtual and country-scale tokens (`online`, `remote`, `anywhere`, `us`, `usa`) and un-geocodable strings — including timezone strings such as `EST` — as `unclear`. Only a concretely geocoded location within the distance threshold SHALL classify as `near`; a concretely geocoded location beyond the threshold SHALL classify as `far`.

#### Scenario: Online-only post no longer hard-passes

- **WHEN** the extracted location is `online` (or `anywhere`, `US`, `USA`, `remote`)
- **THEN** the location state is `unclear` and the location gate yields `needs_review` rather than passing

#### Scenario: Timezone string no longer hard-fails

- **WHEN** the extracted location is a timezone string such as `EST`
- **THEN** the location state is `unclear` (not `far`) and the final recommendation for an otherwise-passing analysis is `needs_review`

### Requirement: Failed dimension agents are retried once

When a dimension agent execution fails, the system SHALL automatically re-run that dimension once before recording the failure. Both attempts SHALL be recorded in `analysis_dimensions`. If the retry also fails, gates depending on that dimension are `unclear` (fail-closed).

#### Scenario: Transient dimension failure recovers

- **WHEN** a dimension agent fails once and its automatic retry succeeds
- **THEN** the retry's structured output feeds the gate evaluation and both attempts are visible in `analysis_dimensions`

### Requirement: Confidence score is computed, not model-reported

The gating confidence score SHALL be computed deterministically from the gate verdict and dimension outputs (banded by recommendation, with weighted margins such as the preferences compatibility score and per-dimension confidences). Model-reported confidence SHALL be stored as advisory only and SHALL NOT be compared against any threshold. No default confidence value SHALL substitute for a missing model confidence.

#### Scenario: Missing model confidence no longer meets the threshold

- **WHEN** the meta agent returns no usable confidence value
- **THEN** the stored confidence score is the computed score
- **AND** no 0.7-style default is applied

### Requirement: Dimension agents receive budgeted, dimension-specific context

Each dimension agent SHALL receive the lead title and full lead body, plus only the context sections relevant to its dimension, assembled per a per-dimension context specification: demographics receives the profile summary; preferences and sexual_preferences receive the interests summary and a bounded set of newest posts (per-item character cap); relationship_goals receives the interests summary; risk_flags receives account metadata (karma, account age, bio, verification status) and the character summary. Raw concatenated comment dumps SHALL NOT be sent to any dimension agent. The total assembled input SHALL be capped by a configurable character budget; when trimming is required, oldest items are dropped first and the lead title/body are never trimmed.

#### Scenario: Author with a large history

- **WHEN** a lead's author has 20 stored posts and 100 stored comments and multi-agent analysis runs
- **THEN** each dimension agent's input stays within the configured character budget
- **AND** the lead title and full body are present in every dimension's input
- **AND** no dimension receives the raw concatenated comments

#### Scenario: Risk agent sees account metadata

- **WHEN** the Risk Flags agent runs for an author whose profile metadata (karma, account creation date, bio, verification) has been fetched
- **THEN** that metadata is included in the Risk Flags agent's model input

#### Scenario: Budget trimming preserves the lead post

- **WHEN** the assembled context for a dimension exceeds the configured budget
- **THEN** the oldest included posts are dropped first until the input fits
- **AND** the lead title and body remain intact

### Requirement: Per-dimension execution tracking

Each dimension execution SHALL be recorded in `analysis_dimensions`, including the input actually sent to the model (an excerpt truncated for storage, plus the list of included sections and total input size), structured output, raw LLM response, and model info, so failed or surprising results can be inspected and re-run.

#### Scenario: Inspecting a dimension run

- **WHEN** a dimension agent has executed for an analysis
- **THEN** an `analysis_dimensions` row exists with an excerpt of the actual model input, the included section names, the total input size, the parsed output, raw response, and model info

### Requirement: Analysis is resilient to missing provider data

The analysis pipeline SHALL merge provider-fetched profile items with locally stored `profile_items` (union deduplicated by `external_item_id`), SHALL ensure the lead post itself is present as a profile item before analysis, and SHALL NOT fail solely because the provider returns zero profile items — it proceeds with whatever data is available, minimally the lead post.

#### Scenario: Provider hides the author's posts

- **WHEN** the provider's profile item fetch returns zero items for a lead's author (e.g. NSFW posts hidden from the public profile)
- **THEN** the analysis proceeds using locally stored profile items, which include at least the lead post
- **AND** the interests summary does not return an empty "no posts available" result for a saved lead

### Requirement: Analysis history is queryable

The API SHALL expose the latest analysis (`GET /leads/{id}/analysis`), the analysis history (`GET /leads/{id}/analysis/history`), and any specific analysis by id (`GET /leads/{id}/analysis/{analysis_id}`), so prior runs remain comparable after re-analysis.

#### Scenario: Re-analysis preserves history

- **WHEN** a lead is analyzed a second time
- **THEN** both analyses are retrievable via the history endpoints

### Requirement: Agent prompts are versioned and editable

Each analysis dimension SHALL have a versioned prompt (`agent_prompts`: system prompt, output schema, temperature, max_tokens). `PUT /agent-prompts/{dimension}` SHALL create a new active version rather than overwriting, `GET .../versions` SHALL list history, and `POST .../rollback` SHALL restore a prior version. The settings UI (`/settings/agents`) SHALL expose editing and rollback.

#### Scenario: Editing a prompt creates a version

- **WHEN** the user saves a modified system prompt for a dimension
- **THEN** a new prompt version becomes active
- **AND** the previous version remains in the version history

#### Scenario: Rolling back a prompt

- **WHEN** the user rolls back a dimension to a prior version
- **THEN** that version's content becomes the active prompt for subsequent analyses

### Requirement: Interests and character summaries

The system SHALL provide LLM summary services over an account's stored content: an interests summary derived from the account's posts and a character summary derived from the account's comments. These summaries SHALL be included in the input context of the dimension agents per the per-dimension context specification (interests → preferences, sexual_preferences, relationship_goals; character → risk_flags), so their generation cost contributes to analysis quality. The character summary MAY be empty when no comments exist; the interests summary SHALL always have at least the lead post for a saved lead.

#### Scenario: Author with no comments

- **WHEN** summaries run for an account that has posts but no comments
- **THEN** the interests summary is produced from the posts
- **AND** an empty character summary is acceptable and does not fail the pipeline

#### Scenario: Summaries reach the agents

- **WHEN** multi-agent analysis runs after summaries have been generated
- **THEN** the interests summary text appears in the input of the preferences, sexual_preferences, and relationship_goals agents
- **AND** the character summary text appears in the input of the risk_flags agent
