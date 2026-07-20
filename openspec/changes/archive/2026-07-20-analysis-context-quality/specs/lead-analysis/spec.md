# lead-analysis Specification (delta)

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Per-dimension execution tracking

Each dimension execution SHALL be recorded in `analysis_dimensions`, including the input actually sent to the model (an excerpt truncated for storage, plus the list of included sections and total input size), structured output, raw LLM response, and model info, so failed or surprising results can be inspected and re-run.

#### Scenario: Inspecting a dimension run

- **WHEN** a dimension agent has executed for an analysis
- **THEN** an `analysis_dimensions` row exists with an excerpt of the actual model input, the included section names, the total input size, the parsed output, raw response, and model info

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
