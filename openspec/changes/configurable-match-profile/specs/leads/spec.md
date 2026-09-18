## MODIFIED Requirements

### Requirement: Leads carry a priority tier derived from analysis signals

Leads created from analysis (scout auto-promotion and multi-agent analysis of saved leads) SHALL persist a priority tier (`high`, `medium`, `low`) and the code-computed `compatibility_score` on the `lead_posts` row. The tier SHALL be derived in code from the meta agent's `priority_level`, the compatibility score, and gate outcomes — not by an additional LLM call — using the promote and demote thresholds of the active match profile (seeded as 0.7 and 0.5). Leads created before this capability existed MAY have a null priority.

#### Scenario: Scout promotion stores priority

- **WHEN** a scout-analyzed post is auto-promoted to a lead
- **THEN** the created `lead_posts` row has a non-null priority tier and `compatibility_score`

#### Scenario: High compatibility promotes

- **WHEN** an analysis yields a compatibility score at or above the profile's promote threshold and all decision gates passed
- **THEN** the lead's priority tier is `high`

#### Scenario: Threshold change applies to new analyses only

- **WHEN** the promote threshold is lowered in a new profile version
- **THEN** analyses run afterwards use the new threshold and previously stored priority tiers are unchanged
