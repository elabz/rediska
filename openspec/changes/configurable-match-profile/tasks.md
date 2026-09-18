## 1. Schema and profile service

- [ ] 1.1 Alembic migration: `match_profiles` table (unique `version`), nullable `match_profile_version` on `lead_analyses` and `scout_watch_posts`; upgrade and downgrade tested
- [ ] 1.2 Pydantic `MatchProfile` model with validation (weights, label/alias collisions, recognised genders, coordinates, radius, threshold ordering)
- [ ] 1.3 `MatchProfileService`: get_active, save (new version), list versions, restore, seed-if-empty with concurrency guard
- [ ] 1.4 Startup seeding from env, gate literals, default prompt lists, and current thresholds; one-time env/profile difference log
- [ ] 1.5 Unit tests: versioning, restore, validation failures, seeding idempotence under concurrent start

## 2. Matching and scoring

- [ ] 2.1 `interest_matching.py`: term normalisation, label/alias match, distinct-interest dedupe, noisy-OR score, result structure (matched with weights, unmatched terms)
- [ ] 2.2 Unit tests: alias match, case and punctuation, whole-word boundaries, duplicate terms count once, no match equals base, determinism
- [ ] 2.3 Seed-weight table test reproducing the five cases in design.md

## 3. Gates, priority, geocoding

- [ ] 3.1 `evaluate_gates(dimension_results, profile)`: accepted genders from profile; age, D/s, location constraints from profile; remove `UserConstraints.from_settings()`
- [ ] 3.2 Optional `author_age` and `deal_breaker` gates, evaluated and stored only when enabled; `GATES` and `_MAX_MARGIN` handle a variable gate set without changing scores when both are off
- [ ] 3.3 `derive_priority` thresholds from profile; geocoder home point and radius from profile
- [ ] 3.4 Golden test: fixture dimension outputs judged by pre-change and post-change code give identical recommendations and gate results with the seeded profile; confidence scores equal within 0.005 (compatibility 0.704 vs 0.7), and no fixture crosses a scout `min_confidence` boundary
- [ ] 3.5 Update existing gate, priority, and geocoding tests to pass a profile

## 4. Pipeline integration

- [ ] 4.1 Resolve the active profile once per analysis in `MultiAgentAnalysisService` and in `scout.analyze_and_decide` / `reanalyze_post`; pass it down
- [ ] 4.2 Post-process the preferences result: attach matched/unmatched interests, computed `compatibility_score`, profile version; ignore any model-reported score
- [ ] 4.3 Store `match_profile_version` on the analysis and scout post; include it in evaluation snapshots
- [ ] 4.4 Meta-agent input: matched interests and computed score
- [ ] 4.5 Manual add-to-leads (`priority_from_stored_results`) uses stored computed values
- [ ] 4.6 Integration tests for API path and scout path: same post, same verdict, version recorded

## 5. Prompt and replay

- [ ] 5.1 Extract-only default preferences prompt; data migration creating a new active version from the current active prompt with the preferred lists, scoring block, and three output fields removed; diff logged
- [ ] 5.2 Preferences output schema: drop required `compatibility_score` / `preferred_*_found`; tolerate them when present
- [ ] 5.3 `compare_fields` for preferences compares extracted lists only; replay tests updated

## 6. API and preview

- [ ] 6.1 Routes `/match-profile` (GET, PUT), `/versions`, `/versions/{version}/restore`, `/preview`; `audit_log` on save and restore
- [ ] 6.2 Preview service reusing matching, gates, and priority over stored outputs; counts by from→to, tier changes, examples, "not recomputable"; location recomputed only when home or radius changed
- [ ] 6.3 Tests: preview persists nothing, widened genders scenario, cap enforced, audit rows written
- [ ] 6.4 Evaluation summary and calibration report group by profile version

## 7. Web

- [ ] 7.1 BFF proxies under `/api/core/match-profile`
- [ ] 7.2 `/settings/match-profile`: interest editor (category, weight presets plus custom, aliases), deal-breakers, genders, age, orientation, home and radius, optional gates, thresholds
- [ ] 7.3 Preview panel and version history with restore; loading, empty, error states; error state never renders an empty editable form
- [ ] 7.4 Matched-interest chips on lead list and detail; unmatched terms on detail; sidebar entry
- [ ] 7.5 Vitest for editor validation, preview, restore; `npm run lint` clean

## 8. Config, docs, rollout

- [ ] 8.1 Mark the five env vars seed-only in `config.py`, `.env.example`, `docker-compose.yml`, CLAUDE.md, README
- [ ] 8.2 Update CLAUDE.md: architecture section, tables, pages, agent description
- [ ] 8.3 Full core and worker suites green in Docker
- [ ] 8.4 Deploy; confirm seeded version 1 matches env; run preview with the unchanged profile and confirm zero changes
- [ ] 8.5 Sync delta specs, diff the synced specs, archive
