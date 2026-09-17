## ADDED Requirements

### Requirement: Scout post analyses can be evaluated and evaluated posts are retained

A scout watch post that carries analysis results (`dimension_results_json` with a recommendation) SHALL be an evaluation subject per the `analysis-evaluation` capability regardless of whether it was promoted to a lead. Recording any evaluation on a scout post SHALL set `scout_watch_posts.evaluated_at`. The `maintenance.cleanup_scout_watch_history` task SHALL NOT delete posts with `evaluated_at` set, and SHALL NOT delete a run while any of its posts is retained. Scout watch history post responses SHALL include the effective evaluations.

#### Scenario: Evaluated not_recommended post survives cleanup

- **WHEN** a 10-day-old scout post with recommendation `not_recommended` has an evaluation and the daily cleanup runs with 3-day retention
- **THEN** the post and its run are retained while unevaluated 10-day-old posts are deleted

#### Scenario: Evaluation from watch history

- **WHEN** the user evaluates the final verdict of a post from a watch's history page
- **THEN** the evaluation is stored against the scout post and the history response shows the evaluated state
