# analysis-evaluation Specification

## Purpose

Human-in-the-loop evaluation of the decisions the analysis agents make about a contact's suitability as a lead. Records explicit human verdicts on the final recommendation and on each dimension, serves a review queue, computes agreement metrics per dimension and per prompt version, and turns the labelled cases into a dataset that candidate prompts can be replayed against before activation. Evaluations inform prompt, agent, and data-collection improvements; they never change an analysis result or a lead's status by themselves.

## ADDED Requirements

### Requirement: Human verdicts are recorded on agent decisions

The system SHALL let the user record an evaluation against a completed analysis subject — a `lead_analyses` row or a `scout_watch_posts` row that carries dimension results — for the **final recommendation** (`dimension = NULL`) or for **one dimension** (`demographics`, `preferences`, `relationship_goals`, `risk_flags`, `sexual_preferences`). An evaluation SHALL contain: `human_verdict` ∈ {`agree`, `disagree`, `partial`}; optional `corrected_value_json` (for the final verdict: a recommendation in {`suitable`, `not_recommended`, `needs_review`}; for a dimension: the corrected field values); `reason_tags` drawn from the controlled vocabulary {`missed_location`, `wrong_age`, `wrong_gender`, `misread_intent`, `misread_orientation`, `hallucinated_fact`, `missing_context`, `stale_context`, `too_strict`, `too_lenient`, `unparseable_output`, `risk_missed`, `risk_overcalled`, `other`}; optional `missing_info` text (required when `missing_context` is tagged); optional free-text `notes`. The system SHALL snapshot into the evaluation the agent output being judged (`agent_snapshot_json`: recommendation, computed confidence, gate verdict, and the dimension's parsed output), the `prompt_versions_json` and model name in force for that analysis, and the timestamp. Evaluations SHALL be append-only: re-evaluating the same subject and dimension creates a new row and the latest row is the effective verdict. Every create SHALL write an `audit_log` entry (`evaluation.record`). Recording an evaluation SHALL NOT alter the analysis row, the lead status, or the scout post status.

#### Scenario: Disagreeing with a final verdict

- **WHEN** the user marks the final recommendation of a lead analysis as `disagree`, corrects it to `suitable`, and tags `too_strict`
- **THEN** an `analysis_evaluations` row exists with `dimension = NULL`, `human_verdict = disagree`, `corrected_value_json.recommendation = suitable`, `reason_tags = [too_strict]`, a snapshot of the agent's recommendation, confidence and gate verdict, and the prompt versions used
- **AND** an `audit_log` entry `evaluation.record` references the evaluation
- **AND** `lead_analyses.final_recommendation` and `lead_posts.status` are unchanged

#### Scenario: Missing context requires a statement of what was missing

- **WHEN** the user tags a dimension evaluation with `missing_context` and leaves `missing_info` empty
- **THEN** the request is rejected with a validation error naming `missing_info`

#### Scenario: Re-evaluation keeps history

- **WHEN** the user evaluates the `demographics` dimension of the same analysis twice
- **THEN** both rows are retained and the later one is reported as the effective evaluation for that dimension

#### Scenario: Evaluating a scout post that never became a lead

- **WHEN** the user evaluates the final verdict of a scout post with recommendation `not_recommended` and no `lead_id`
- **THEN** the evaluation is stored against the scout post subject with the snapshot taken from `dimension_results_json`

### Requirement: Analysis read models expose the effective evaluation

The analysis read models (`GET /leads/{id}/analysis`, `.../analysis/{analysis_id}`, `.../analysis/history`, and scout watch post history/detail responses) SHALL include, for the final verdict and for each dimension, the effective evaluation (verdict, tags, corrected value, timestamp) or `null` when none exists, so the UI can show evaluated state inline without a second request.

#### Scenario: Evaluated dimension shown in analysis payload

- **WHEN** `GET /leads/{id}/analysis` is called for a lead whose `risk_flags` dimension was evaluated `partial` with tag `risk_overcalled`
- **THEN** the response's `risk_flags` entry carries `evaluation.human_verdict = partial` and `evaluation.reason_tags = [risk_overcalled]`
- **AND** dimensions without evaluations carry `evaluation = null`

### Requirement: Review queue serves unevaluated decisions

`GET /evaluations/queue` SHALL return analysis subjects that have no effective final-verdict evaluation, ordered so that (1) subjects whose recorded behaviour contradicts the agent come first — a `suitable` lead whose status is `ignored`, or a `not_recommended`/`needs_review` scout post that was manually promoted to a lead — then (2) a stratified sample across `suitable`, `needs_review`, and `not_recommended` recommendations in round-robin so no class is starved. Within `needs_review` the order SHALL be by computed score descending and then by fewest non-passing gates, so posts that missed the threshold on a single `unclear` gate (typically location) come first; within the other classes, newest first. Each queue item SHALL show the gate results (gate, status, reason) so the reviewer sees exactly why the post is there. The endpoint SHALL support `recommendation`, `dimension_failed`, `watch_id`, `since`, and `limit` filters and cursor pagination. Each item SHALL carry enough context to judge it: the post title/body, the author, the analysis summary (recommendation, confidence, gate verdict, per-dimension parsed outputs and any dimension errors), and the interests/character summaries.

#### Scenario: Behavioural contradictions surface first

- **WHEN** the queue is requested with no filters and there exists a `suitable` lead with status `ignored` that has no evaluation
- **THEN** that lead appears before any non-contradicted item

#### Scenario: Near-miss needs_review posts come first

- **WHEN** the `needs_review` class contains a post scored 0.57 blocked only by an unclear location and a post scored 0.30 with four unclear gates
- **THEN** the 0.57 post is served before the 0.30 post and its item shows `location: unclear` as the sole non-passing gate

#### Scenario: Classes are interleaved

- **WHEN** the queue is requested with `limit = 6` and unevaluated subjects exist in all three recommendation classes
- **THEN** the result contains items from each class rather than six of the most recent class

#### Scenario: Evaluated items leave the queue

- **WHEN** a final-verdict evaluation is recorded for a queued subject
- **THEN** the subject no longer appears in the queue

### Requirement: Evaluation metrics are computed per dimension and prompt version

`GET /evaluations/summary` SHALL compute from the effective evaluations, for a requested period (default: all time) and optional `watch_id`: overall and per-dimension counts of `agree`/`partial`/`disagree` and an agreement rate (`agree + 0.5·partial`) / total; the distribution of `reason_tags` per dimension; a final-recommendation confusion matrix of agent recommendation × human corrected recommendation (agreements on the diagonal); the same metrics grouped by the prompt version that produced the judged output; a weekly trend of agreement rate per dimension; and the list of `missing_info` statements with counts. Metrics SHALL be plain SQL/Python aggregation over stored rows with no LLM involvement.

#### Scenario: Agreement per prompt version

- **WHEN** `demographics` prompt version 3 has 10 evaluations (7 agree, 2 partial, 1 disagree) and version 4 has 4 (2 agree, 2 disagree)
- **THEN** the summary reports version 3 agreement 0.80 over 10 cases and version 4 agreement 0.50 over 4 cases

#### Scenario: Confusion matrix reflects corrections

- **WHEN** three final-verdict evaluations disagree with agent `not_recommended` and correct it to `suitable`
- **THEN** the confusion matrix cell (`not_recommended` → `suitable`) equals 3

#### Scenario: Missing information is aggregated

- **WHEN** five evaluations tag `missing_context` with `missing_info` texts, two of which are identical after trimming and case-folding
- **THEN** the summary lists four distinct statements with the duplicated one counted twice

### Requirement: Labelled dataset export

`GET /evaluations/export?dimension=<d>` SHALL stream JSONL where each line is one evaluated case for that dimension (or the final verdict when `dimension` is omitted): the exact stored model input (`analysis_dimensions.input_data_json` for lead analyses; the reconstructed input for scout posts when a dimension row exists), the agent's parsed output, the prompt version, the human verdict, corrected value, tags, and notes. The export SHALL include content verbatim and SHALL NOT redact or filter it (see research-content-policy). The export SHALL be audit-logged (`evaluation.export`).

#### Scenario: Exporting a dimension dataset

- **WHEN** the user exports `relationship_goals` with 12 effective evaluations
- **THEN** 12 JSONL lines are returned, each containing `input`, `agent_output`, `prompt_version`, `human_verdict`, `corrected_value`, `reason_tags`
- **AND** an `audit_log` entry `evaluation.export` records the dimension and count

### Requirement: Candidate prompts can be replayed against labelled cases

The system SHALL let the user replay a candidate prompt (a draft system prompt for one dimension, not yet saved as a version, or an existing version) against the labelled cases for that dimension. `POST /agent-prompts/{dimension}/replay` SHALL create a `prompt_replays` row (`status = queued`) and enqueue `evaluation.replay_prompt`; the task SHALL re-run the dimension agent on each case's stored input through the local inference endpoint (subject to the inference concurrency gate), compare the new parsed output to the human-corrected value (or, on `agree`, to the original agent output) using the dimension's field-level comparison rules, and store per-case results and an aggregate agreement rate. Replays SHALL use the `jobs` idempotency ledger, SHALL be cancellable, SHALL cap the case count (`EVALUATION_REPLAY_MAX_CASES`, default 50, most recent first), and SHALL NOT modify any analysis, evaluation, or active prompt. `GET /agent-prompts/{dimension}/replays` and `/replays/{id}` SHALL expose status, progress, aggregate, and per-case rows. Starting a replay SHALL be audit-logged (`prompt.replay`).

#### Scenario: Replaying a draft prompt

- **WHEN** the user submits a draft `demographics` prompt for replay and 20 labelled cases exist
- **THEN** a replay row is created and, when complete, reports agreement over 20 cases with a per-case table of expected vs produced values
- **AND** the active `demographics` prompt version is unchanged

#### Scenario: Replay honours the inference gate

- **WHEN** a replay runs while scout analyses are in flight
- **THEN** replay inference calls wait for the shared inference slot rather than issuing concurrent requests

#### Scenario: Replay with no labelled cases

- **WHEN** a replay is requested for a dimension with zero effective evaluations
- **THEN** the request is rejected with a clear error and no task is enqueued

### Requirement: Evaluation UI

The web app SHALL provide: (1) inline evaluation controls on the lead detail analysis panel — on the recommendation card for the final verdict and on each dimension card — showing the effective verdict and allowing agree/disagree/partial, tag selection, correction, and notes in at most one dialog; (2) the same controls on scout watch history post detail; (3) an `/evaluations` page with a **Review queue** tab (next item with full context and the same controls, filters, skip), a **Dashboard** tab (agreement per dimension, per prompt version, confusion matrix, tag distribution, trend, missing-info list), and an **Export** action; (4) a **Replay** panel on `/settings/agents` for the selected dimension showing replay history and a "Replay draft against labelled cases" action with progress and per-case results. All views SHALL have empty and error states. The `/evaluations` page SHALL be reachable from the sidebar.

#### Scenario: Evaluating from the lead detail page

- **WHEN** the user opens a lead with a completed analysis and clicks "Disagree" on the demographics card, picks `wrong_age`, enters a corrected age and saves
- **THEN** the card shows the evaluated state without a page reload and the evaluation is retrievable via the API

#### Scenario: Empty review queue

- **WHEN** every analysis subject has an effective final-verdict evaluation
- **THEN** the Review queue tab shows an empty state explaining that there is nothing left to review and how new items arrive

#### Scenario: Dashboard with no evaluations

- **WHEN** no evaluations exist
- **THEN** the Dashboard tab shows an empty state pointing to the Review queue rather than blank charts
