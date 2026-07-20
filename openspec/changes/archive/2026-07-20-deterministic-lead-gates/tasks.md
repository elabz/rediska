# Tasks: deterministic-lead-gates

## 1. Gate evaluator

- [x] 1.1 Create `rediska_core/domain/services/lead_gates.py`: `UserConstraints` (age, D/s orientation; sourced from settings with `USER_AGE`, `USER_DS_ORIENTATION` env, defaults 45/dominant), `GateVerdict` dataclass, pure `evaluate_gates(dimension_results, constraints)` implementing the five gates with pass/fail/unclear semantics and verdict rule (fail → not_recommended; unclear → needs_review; else suitable)
- [x] 1.2 Implement the computed confidence score (banded by recommendation: ≤0.3 / 0.3–0.6 / 0.6–1.0, weighted margins from compatibility_score and dimension confidences) as constants in the same module
- [x] 1.3 Unit tests per gate: pass/fail/unclear for gender, location state, D/s, partner_max_age (incl. numeric strings, `no_max_age`, garbage values → unclear), authenticity/red flags; verdict combination rules; score banding and determinism

## 2. Three-state geocoding

- [x] 2.1 Change `geocoding.classify_location` to return `location_state: near|far|unclear` (+ keep derived `location_near` bool); move always-near tokens to the unclear list and add timezone tokens (est/cst/mst/pst/edt/cdt/mdt/pdt); un-geocodable → unclear; mixed-part rules per design
- [x] 2.2 Update `DemographicsAgent` post-processing to store `location_state` in the dimension output (keep `location_near` for UI compatibility)
- [x] 2.3 Update geocoding unit tests: online/US/EST → unclear; concrete near/far unchanged; mixed strings

## 3. Wire into analysis paths

- [x] 3.1 `MultiAgentAnalysisService.analyze_lead`: run gate evaluator after dimensions; persist `final_recommendation`/`confidence_score` from the verdict; store `gate_results` with the analysis; model outputs stored as advisory
- [x] 3.2 Add one automatic retry in `_run_dimension_agents` for a failed dimension (both attempts recorded in `analysis_dimensions`, attempt annotated in input_data)
- [x] 3.3 Demote meta agent: rewrite `META_ANALYSIS_PROMPT` to advisory role (receives dimension results + GateVerdict; outputs reasoning/strengths/concerns/priority_level); remove decision rules and user constraints from the prompt; `_format_dimension_results` renders MISSING explicitly (no `no_max_age` default); `_normalize_meta_output` no longer supplies default confidences or a recommendation used for gating; meta failure does not block the verdict
- [x] 3.4 `scout.analyze_and_decide` step 8: promotion uses gate verdict `suitable` AND computed score ≥ `min_confidence`; store per-gate results in `dimension_results_json`; needs_review/not_recommended never auto-promote
- [x] 3.5 Tests: service-level test that a failed relationship_goals (after retry) → needs_review; meta-disagreement cannot flip verdict; scout promotion test on computed score; missing model confidence applies no default

## 4. Verification & docs

- [x] 4.1 Run `pytest` (core + worker) — new tests green, no regressions beyond known pre-existing failures
- [x] 4.2 Operator note: document score bands vs existing `min_confidence` values (0.5/0.7) and the new `USER_AGE`/`USER_DS_ORIENTATION` env vars in `.env.example`
- [x] 4.3 Archive change to update `openspec/specs/lead-analysis` and `openspec/specs/scout-watch`
