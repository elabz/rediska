## ADDED Requirements

### Requirement: Lead posts become labelled exemplars from recorded outcomes

The system SHALL derive an outcome label for a lead post from recorded behaviour only. It SHALL be **positive** when the lead's status is `contacted`, or the author account's contact state is contacted or its engagement state is engaged after the lead was saved, or an effective human evaluation agrees with a `suitable` final verdict on that lead's analysis. It SHALL be **negative** when the lead's status is `ignored`, or the scout post it came from was dismissed from the needs-review queue, or an effective human evaluation disagrees with a `suitable` final verdict. When both apply, the most recent signal SHALL win, except that engaged SHALL always be positive. Leads that are `new`, `saved`, `contact_queued`, or `expired` with no evaluation SHALL be unlabelled. Soft-deleted leads and leads of authors on the do-not-contact list SHALL NOT be exemplars. The label SHALL be written to the lead's search document and SHALL be updated when any of those inputs change. Deriving labels SHALL NOT read conversation or message content.

#### Scenario: Ignoring a lead creates a negative exemplar

- **WHEN** the user sets a lead to `ignored`
- **THEN** its search document carries a negative outcome label

#### Scenario: Reviving a lead removes the label

- **WHEN** an `ignored` lead is set back to `saved` and has no evaluation
- **THEN** its outcome label is cleared

#### Scenario: Expired is not a verdict

- **WHEN** a lead expires untouched
- **THEN** it carries no outcome label

#### Scenario: Engagement outranks an earlier ignore

- **WHEN** a lead was once ignored and its author later became engaged
- **THEN** the exemplar is positive

### Requirement: Analysed posts receive an affinity score with an explanation

When the feature is enabled, after a multi-agent analysis completes for a lead or a scout post, the system SHALL embed the post's title and resolved body with the local embeddings endpoint and retrieve its `k` nearest labelled exemplars (default 15) by cosine similarity, excluding the post itself and other posts by the same author. Each exemplar SHALL carry an outcome weight (engaged 1.0; contacted and evaluation-agree 0.7; negatives 1.0 unless configured otherwise). The affinity score SHALL be the sum of similarity × weight over positive neighbours divided by the same sum over all retrieved neighbours, rounded to three decimals. The system SHALL store the score together with the three most similar exemplars (lead id, label, similarity), the exemplar counts at computation time, the embeddings model name, and the computation time. When fewer than the configured minimum of positive exemplars or of negative exemplars exist (`LEAD_AFFINITY_MIN_EXEMPLARS`, default 30 each), the score SHALL be null with reason `insufficient_history`. An embedding or search failure SHALL leave the score null with a reason and SHALL NOT fail or delay the analysis result.

#### Scenario: Post resembling contacted leads

- **WHEN** most of a post's nearest exemplars are positive
- **THEN** its affinity is close to 1 and the explanation lists the three most similar exemplar leads

#### Scenario: Not enough history

- **WHEN** only 12 positive exemplars exist
- **THEN** the affinity is null with reason `insufficient_history` and the UI says so

#### Scenario: Same author is excluded

- **WHEN** the author of the post being scored also wrote a labelled exemplar
- **THEN** that exemplar is not among the neighbours used

#### Scenario: Embeddings endpoint unavailable

- **WHEN** the embeddings endpoint times out during scoring
- **THEN** the analysis is stored normally and the affinity is null with reason `embedding_unavailable`

### Requirement: Affinity never decides

The affinity score SHALL NOT be an input to any hard gate, the final recommendation, the computed confidence score, the priority tier, scout auto-promotion, lead expiry, or any filter that hides a lead or post. It SHALL only be displayed and offered as an explicit sort order.

#### Scenario: High affinity on a failed gate

- **WHEN** a post has affinity 0.95 and a failed gate
- **THEN** its recommendation is `not_recommended` and it is not promoted

#### Scenario: Low affinity on a suitable post

- **WHEN** a post passes every gate above the watch's `min_confidence` and has affinity 0.05
- **THEN** it is promoted exactly as it would be without the feature

### Requirement: The feature can be switched off and recomputed

`LEAD_AFFINITY_ENABLED=false` SHALL stop all affinity computation and hide affinity UI while keeping stored values. A backfill task SHALL recompute affinity for active leads and untriaged needs-review posts, using the `jobs` ledger, a retry policy, and a dry run by default; it SHALL be the supported way to refresh scores after the exemplar set has grown or the embeddings model changed.

#### Scenario: Disabled

- **WHEN** the feature is disabled
- **THEN** analyses compute no affinity, lists offer no affinity sort, and no badge is shown

#### Scenario: Model change

- **WHEN** stored scores were computed with a different embeddings model name than the configured one
- **THEN** they are shown as stale until the backfill recomputes them

### Requirement: The calibration report shows whether affinity predicts outcomes

The calibration report SHALL include, for leads in its cohort that had a non-null affinity at analysis time, the counts and rates of contacted, engaged, and ignored outcomes per affinity band (0–0.25, 0.25–0.5, 0.5–0.75, 0.75–1), computed by plain aggregation. A lead's own later label SHALL NOT have contributed to the affinity value used for it.

#### Scenario: Predictive signal

- **WHEN** the report is generated after a month of use
- **THEN** it shows outcome rates per band so the user can see whether higher bands were contacted more often

#### Scenario: No leakage

- **WHEN** a lead was scored on Monday and ignored on Tuesday
- **THEN** the band it is counted in is the one from Monday's stored score
