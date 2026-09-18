## MODIFIED Requirements

### Requirement: Hard gates are evaluated deterministically and fail closed

The system SHALL evaluate the hard gates in code, as a pure function over the structured dimension outputs and the active match profile, identically for the API and scout entry points. The five standing gates are gender (the author's gender against the profile's accepted genders), location, D/s compatibility against the profile's orientation, partner max age against the profile's user age, and authenticity/red flags. Two optional gates SHALL be evaluated only when enabled in the profile: `author_age` (the author's stated age against the profile's author age range) and `deal_breaker` (extracted interests, partner criteria, and deal-breakers against the profile's deal-breaker labels and aliases). Each gate SHALL yield `pass`, `fail`, or `unclear`; a missing, failed, or unparseable gate input SHALL yield `unclear`, never `pass`. A recognised gender that is not in the accepted list SHALL fail; an unrecognised gender value SHALL be `unclear`. The verdict SHALL be: any gate `fail` → `not_recommended`; otherwise any gate `unclear` → `needs_review`; otherwise `suitable`. Per-gate results and reasons SHALL be stored with the analysis, and no gate constraint SHALL be read from prompt text or from a code literal.

#### Scenario: Failed relationship_goals dimension no longer passes the age gate

- **WHEN** the relationship_goals dimension fails (or returns no parseable `partner_max_age`) and all other gates pass
- **THEN** the age gate is `unclear` and the final recommendation is `needs_review`
- **AND** the analysis is not marked `suitable`

#### Scenario: Author rejects the user's age

- **WHEN** the relationship_goals output contains `partner_max_age` lower than the profile's user age
- **THEN** the age gate fails and the final recommendation is `not_recommended` with the age gate cited as the reason

#### Scenario: Prompt drift produces unparseable fields

- **WHEN** an edited dimension prompt yields output whose gate-relevant field is missing or has an unrecognized value
- **THEN** the affected gate is `unclear` (fail-closed) and the per-gate reason identifies the missing field

#### Scenario: Accepted genders come from the profile

- **WHEN** the profile's accepted genders are changed to include `male` and a post author is male
- **THEN** the gender gate passes without any code or prompt change

#### Scenario: Disabled optional gate is not evaluated

- **WHEN** the `author_age` gate is disabled and the author's age is unknown
- **THEN** no `author_age` result is stored and the verdict is unaffected

#### Scenario: Deal-breaker match fails the gate

- **WHEN** the `deal_breaker` gate is enabled and an extracted term matches a profile deal-breaker
- **THEN** the gate fails, the reason names the matched deal-breaker, and the recommendation is `not_recommended`
