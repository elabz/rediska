## MODIFIED Requirements

### Requirement: Multi-agent analysis runs six agents

`POST /leads/{lead_id}/analyze-multi` SHALL enqueue the `multi_agent_analysis.analyze_lead` Celery task, which runs up to five dimension agents — Demographics (age, gender, location), Preferences (hobbies, kinks, compatibility), Relationship Goals (intent, partner criteria, deal-breakers), Risk Flags (scam/seller detection, authenticity, red flags), and Sexual Preferences (orientation, intimacy/kink preferences) — in stages, followed by a Meta-Analysis coordinator that is **advisory only**: it synthesizes reasoning, strengths, concerns, and a priority level, but the `final_recommendation` (`suitable`, `not_recommended`, `needs_review`) and the gating confidence score SHALL be computed deterministically by the code gate evaluator from the structured dimension outputs. When staging ends an analysis early, the agents of later stages and the Meta-Analysis coordinator SHALL NOT run. Results are stored in `lead_analyses`.

#### Scenario: Completed multi-agent analysis

- **WHEN** `multi_agent_analysis.analyze_lead` completes for a lead without an early exit
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

### Requirement: Dimension agents run in stages and stop on a hard gate failure

When staging is enabled, the analysis SHALL run the Demographics agent first (including its single automatic retry on failure) and SHALL evaluate the gender and location gates on its output. If either gate is `fail`, the analysis SHALL end: the final recommendation SHALL be `not_recommended`, the failing gate SHALL be recorded as the early-exit gate, and no further agent SHALL run. If neither gate fails — including when either is `unclear` or the Demographics agent failed — the remaining four dimension agents and then the Meta-Analysis coordinator SHALL run and the full gate evaluation SHALL apply unchanged. Staging SHALL behave identically for the API and scout entry points, and the verdict of a staged analysis SHALL always equal the verdict the unstaged analysis would have produced for the same dimension outputs.

#### Scenario: Gender gate fails at stage 1

- **WHEN** the Demographics agent reports a gender that fails the gender gate
- **THEN** the analysis ends as `not_recommended` citing the gender gate, and exactly one dimension agent call was made

#### Scenario: Unclear location does not stop the analysis

- **WHEN** the location gate is `unclear` and the gender gate passes
- **THEN** all remaining agents run and the post can reach `needs_review` with its full context

#### Scenario: Demographics agent fails twice

- **WHEN** the Demographics agent fails and its retry fails
- **THEN** the remaining agents run, and the gender and location gates are `unclear`

#### Scenario: Staging never changes a verdict

- **WHEN** the same dimension outputs are evaluated with staging on and off
- **THEN** the final recommendation is identical

### Requirement: Skipped dimensions are recorded as skipped, not failed

A dimension that did not run because of an early exit SHALL be recorded in `analysis_dimensions` with status `skipped` and the early-exit gate as its reason, SHALL NOT be retried, and SHALL be represented by an explicit skipped marker in a scout post's stored dimension results. Gates whose inputs were skipped SHALL be recorded as `not_evaluated`; `not_evaluated` SHALL occur only in an analysis that already has a failed gate and SHALL NOT be treated as `pass` or `unclear` anywhere. The calibration report's dimension failure rates and the evaluation review queue's gate counts SHALL exclude skipped dimensions and `not_evaluated` gates. The compatibility score and priority inputs of an early-exited analysis SHALL be null.

#### Scenario: Calibration ignores skipped dimensions

- **WHEN** a week's scout posts include 300 early exits
- **THEN** the dimension failure rates for the four skipped dimensions are computed only over posts where those dimensions actually ran

#### Scenario: Early-exited analysis in the UI

- **WHEN** the user opens an early-exited analysis
- **THEN** the Demographics card shows its result, the other cards show "skipped: gender gate failed", and no card shows an error

### Requirement: Title tags are parsed as a zero-cost stage, in shadow mode by default

The system SHALL parse the author's gender, and age when present, from an unambiguous bracketed or parenthesised personals tag in the post title (for example `[F4M]`, `(M4F)`, `35 [F4M]`), using a strict pattern that yields no result for anything ambiguous, malformed, or repeated with conflicting values. In `shadow` mode (the default) the parsed result SHALL be stored with the analysis and SHALL NOT influence it. In `active` mode, a parsed gender that fails the gender gate SHALL end the analysis before any agent runs, with the gate reason stating that it came from the title tag; a parsed gender that passes SHALL NOT replace the Demographics agent. In `off` mode the parser SHALL NOT run. The calibration report SHALL show, over its period, how often the tag parser produced a result and how often that result agreed with the Demographics agent's gender, and SHALL list disagreements.

#### Scenario: Shadow mode records without deciding

- **WHEN** a title contains `[M4F]` in shadow mode
- **THEN** the parsed gender is stored, the Demographics agent still runs, and the verdict comes from the agent's output

#### Scenario: Ambiguous title yields nothing

- **WHEN** a title contains `[M4F] [F4M]` or an unknown tag
- **THEN** the parser returns no result in every mode

#### Scenario: Active mode skips all agents on a failing tag

- **WHEN** the mode is `active` and the tag gender fails the gender gate
- **THEN** no agent call is made and the analysis is `not_recommended` citing the gender gate from the title tag

#### Scenario: Agreement is reported

- **WHEN** the calibration report is generated
- **THEN** it shows the tag parser's coverage and its agreement rate with the Demographics agent, with the disagreeing posts listed

### Requirement: A full analysis can be forced

`POST /leads/{lead_id}/analyze-multi` SHALL accept `full=true`, which runs every dimension agent and the Meta-Analysis coordinator regardless of gate outcomes and regardless of the title tag. A manual analysis started from the lead detail page SHALL use it by default. Early-exited analyses of leads and scout posts SHALL offer a "Run full analysis" action that performs a forced full analysis and stores it as a new analysis without altering the early-exited one. Scout runs, scout re-analysis, and auto-analyse on save SHALL use staging.

#### Scenario: Manual analysis is complete

- **WHEN** the user clicks analyse on a lead whose author fails the gender gate
- **THEN** all five dimension results and the meta output are produced and the verdict is still `not_recommended`

#### Scenario: Upgrading an early exit

- **WHEN** the user runs a full analysis on an early-exited scout post
- **THEN** a new full analysis is stored and the original early-exited result remains in history

### Requirement: Inference savings are recorded and reported

Each analysis SHALL record the number of LLM agent calls made and the number skipped by staging. The calibration report SHALL total calls made and skipped for its period, overall and per watch, and SHALL break early exits down by gate and stage.

#### Scenario: Savings visible

- **WHEN** the weekly calibration report is generated
- **THEN** it shows calls made, calls skipped, the share of analyses that exited early, and the split between gender and location exits
