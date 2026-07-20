# lead-analysis Specification (delta)

## MODIFIED Requirements

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

## ADDED Requirements

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
