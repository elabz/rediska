## 1. Measure first

- [ ] 1.1 From the most recent calibration reports, compute the share of analysed scout posts that failed the gender or location gate, and the share failing only other gates; record the numbers in this change's design.md
- [ ] 1.2 Go / no-go: continue only if the gender-or-location fail share makes the saving worthwhile (suggested floor 30%)

## 2. Schema and config

- [ ] 2.1 Alembic migration: add `skipped` to `dimension_status_enum`; nullable `early_exit_gate`, `llm_calls_made`, `llm_calls_skipped`, `title_tag_json` on `lead_analyses` and `scout_watch_posts`; upgrade and downgrade tested on MySQL
- [ ] 2.2 `ANALYSIS_STAGED_ENABLED`, `ANALYSIS_TITLE_TAG_MODE` in `config.py`, `.env.example`, and the compose environment blocks for core and worker

## 3. Gates

- [ ] 3.1 `evaluate_gates_partial()` reusing the existing gate functions; `not_evaluated` marker for gates whose dimension was skipped
- [ ] 3.2 `compute_score` tolerates skipped dimensions and stays inside the `not_recommended` band
- [ ] 3.3 Property test: staged verdict equals full `evaluate_gates` verdict over the enumerated space of gate inputs
- [ ] 3.4 Test that `not_evaluated` never appears without a `fail`, and is never read as `pass` or `unclear`

## 4. Staged orchestration

- [ ] 4.1 Refactor `_run_dimension_agents` into stage 1 (demographics with its retry, offline location classification) and stage 2 (remaining four with retries)
- [ ] 4.2 Early exit on gender or location `fail`: record skipped dimensions in `analysis_dimensions`, skip the meta agent, set `early_exit_gate`, call counters
- [ ] 4.3 `full` parameter bypassing staging; flag-off path identical to current behaviour
- [ ] 4.4 Tests: gender fail makes one call, location unclear runs all, demographics double failure runs all, flag off runs all, counters correct

## 5. Entry points

- [ ] 5.1 `POST /leads/{id}/analyze-multi` accepts `full`; lead detail sends `full=true`; auto-analyse on save uses staging
- [ ] 5.2 `scout.analyze_and_decide` and `reanalyze_post`: store skipped markers in `dimension_results_json`, null compatibility and priority inputs, early-exit fields on the post
- [ ] 5.3 "Run full analysis" for early-exited leads and scout posts, stored as a new analysis; `audit_log` entry
- [ ] 5.4 Integration tests on both paths

## 6. Title tag stage

- [ ] 6.1 `title_tag.py`: strict parser for bracketed or parenthesised tags with optional age; no result on ambiguity, conflict, or unknown tags
- [ ] 6.2 Unit tests on synthetic titles: standard tags, age forms, couples and unknown tags, conflicting tags, tags in the middle of titles, joined hashtags
- [ ] 6.3 Shadow mode: store the parsed result, no influence on the analysis
- [ ] 6.4 Active mode: gender fail ends the analysis before any agent, reason cites the title tag; a passing tag changes nothing
- [ ] 6.5 Tests for all three modes

## 7. Consumers of dimension data

- [ ] 7.1 Audit every reader of `dimension_results_json` and `analysis_dimensions` (calibration report, evaluation queue and summary, prompt replay case selection, lead detail and scout history read models, priority from stored results)
- [ ] 7.2 Calibration report: exclude skipped dimensions from failure rates; add calls made and skipped, early exits by gate and stage, title-tag coverage, agreement, and disagreement list
- [ ] 7.3 Evaluation queue and controls: gate counts ignore `not_evaluated`; no evaluation control on skipped dimensions
- [ ] 7.4 Prompt replay counts early-exited subjects as skipped for dimensions that did not run
- [ ] 7.5 Tests for each consumer with an early-exited fixture

## 8. Web

- [ ] 8.1 Early-exit banner with the failing gate and "Run full analysis" on lead detail and scout post detail
- [ ] 8.2 Skipped dimension cards (neutral, not error)
- [ ] 8.3 Calibration panel sections for savings and title-tag agreement
- [ ] 8.4 Vitest and lint clean

## 9. Rollout

- [ ] 9.1 Full core and worker suites green in Docker
- [ ] 9.2 Deploy with staging on and tag mode `shadow`; confirm the worker log shows single-call analyses for failing posts
- [ ] 9.3 After the next weekly calibration report, record savings and tag agreement; decide on `active`
- [ ] 9.4 Update CLAUDE.md (multi-agent section, env vars, tables) and README; sync specs, diff, archive
