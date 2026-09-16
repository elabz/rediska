## ADDED Requirements

### Requirement: Analysis responses carry human evaluations

The analysis read models (`GET /leads/{id}/analysis`, `GET /leads/{id}/analysis/{analysis_id}`, `GET /leads/{id}/analysis/history`) SHALL include the effective human evaluation for the final recommendation and for each dimension as defined in the `analysis-evaluation` capability, or `null` where none exists.

#### Scenario: Latest analysis includes evaluation state

- **WHEN** the final verdict of a lead's latest analysis has been evaluated `disagree`
- **THEN** `GET /leads/{id}/analysis` returns `evaluation.human_verdict = disagree` at the top level and per-dimension `evaluation` fields

### Requirement: Prompt versions expose evaluation metrics and can be replayed

`GET /agent-prompts/{dimension}/versions` SHALL include, per version, the number of effective evaluations of outputs produced under that version and their agreement rate. `POST /agent-prompts/{dimension}/replay` SHALL replay a draft or existing prompt against the dimension's labelled cases as defined in `analysis-evaluation`, without changing the active version. The `/settings/agents` UI SHALL show per-version metrics beside the version history and expose the replay action.

#### Scenario: Version history shows agreement

- **WHEN** version 2 of `risk_flags` produced outputs that received 8 evaluations with agreement 0.75
- **THEN** the versions list shows `evaluations = 8` and `agreement = 0.75` for version 2 and `evaluations = 0` for versions with no evaluated outputs

#### Scenario: Replay does not activate

- **WHEN** a draft prompt is replayed and scores higher than the active version
- **THEN** the active version is unchanged until the user explicitly saves the draft via `PUT /agent-prompts/{dimension}`
