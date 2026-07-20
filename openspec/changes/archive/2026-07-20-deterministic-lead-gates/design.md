# Design: deterministic-lead-gates

## Context

Today the meta-analysis LLM agent both synthesizes dimension results *and* applies the decision rules, via `META_ANALYSIS_PROMPT` (default_prompts.py). `MultiAgentAnalysisService._normalize_meta_output` then papers over model variance (PASS/FAIL synonyms, missing confidence → 0.7/0.5 defaults). `MetaAnalysisAgent._format_dimension_results` fills gaps optimistically (`goals.get('partner_max_age', 'no_max_age')`), so the ~24% failure rate of the `relationship_goals` dimension silently disables the age gate. `classify_location` is binary and treats virtual/country tokens as near and un-geocodable strings as far. Both analysis entry points — `MultiAgentAnalysisService.analyze_lead` (API path) and `scout.analyze_and_decide` (worker path, which calls `_run_dimension_agents`/`_run_meta_analysis` directly) — share these components.

## Goals / Non-Goals

**Goals:**
- Hard gates are pure, tested code over structured dimension outputs; identical behavior in both entry points.
- Fail closed: missing/failed/unparseable gate inputs → `needs_review`.
- One automatic retry for a failed dimension agent.
- Deterministic, meaningful confidence score; model confidence is advisory.
- Three-state location classification (`near`/`far`/`unclear`).

**Non-Goals:**
- Discovery/query changes, author dedupe, funnel UX, context assembly changes, migration of stored analyses.

## Decisions

1. **Gate evaluator as a pure function.** New module `domain/services/lead_gates.py`:
   `evaluate_gates(dimension_results: dict, user_constraints: UserConstraints) -> GateVerdict`
   where `GateVerdict = {recommendation, score, gate_results: [{gate, status: pass|fail|unclear, reason}]}`.
   Pure function over already-parsed dimension outputs → trivially unit-testable, no DB/LLM access. `MultiAgentAnalysisService` calls it after dimensions complete; scout's step 8 uses the returned verdict/score. *Alternative considered*: folding gates into `_normalize_meta_output` — rejected; that function's job is coping with model output variance, gates must not depend on model output at all.

2. **Gate semantics (fail-closed).** Each gate reads specific fields and maps to pass/fail/unclear:
   - Gender: `demographics.gender` — `female|non-binary` pass, `male` fail, `unclear`/missing → unclear.
   - Location: `demographics.location_state` — `near` pass, `far` fail, `unclear`/missing → unclear.
   - D/s: `sexual_preferences.ds_orientation` — `submissive|switch` pass, `dominant` fail, null/missing → unclear.
   - Age acceptance: `relationship_goals.partner_max_age` — `no_max_age` or ≥ user age pass, < user age fail, missing/unparseable → unclear.
   - Authenticity: `risk_flags.is_authentic` true AND no `red_flags` pass; `is_authentic` false or red flags present fail; missing → unclear.
   Verdict: any fail → `not_recommended`; else any unclear → `needs_review`; else `suitable`. Unparseable field values (prompt-drift risk from DB-edited `agent_prompts`) are treated as missing → unclear, never pass.

3. **User constraints from config, not prompt text.** `UserConstraints` (age=45, orientation=dominant, plus existing `HOME_*` for geocoding) sourced from settings with env overrides (`USER_AGE`, `USER_DS_ORIENTATION`). The meta prompt no longer embeds them as decision inputs. *Alternative*: a settings table/UI — deferred; env is sufficient for a single-user system.

4. **Computed score.** `score = base(recommendation) + weighted margins`, sketch:
   - `not_recommended` → 0.0–0.3 band, `needs_review` → 0.3–0.6, `suitable` → 0.6–1.0.
   - Within the suitable band, add weighted contributions: preferences `compatibility_score` (0.15), dimension self-reported confidences for the five gates (0.05 each), authenticity cleanliness (0.1). Clamp to band.
   Deterministic given dimension outputs; comparable against `min_confidence` (0.5–0.7 thresholds keep working: a gate-passing lead starts at 0.6). Model-reported confidence is stored (`meta` advisory output) but never gates.

5. **Dimension retry.** In `_run_dimension_agents`, a dimension whose result has `success=False` is re-run once (same prompt/context) before the failure is recorded. Both attempts are stored in `analysis_dimensions` (attempt annotated in `input_data`). No retry for the meta agent — it is advisory.

6. **Meta agent demotion.** `META_ANALYSIS_PROMPT` rewritten: it receives dimension results *and* the code-computed `GateVerdict`, and produces reasoning, strengths, concerns, `priority_level`. Its output is stored as the `meta_analysis` dimension result; `final_recommendation`/`confidence_score` on `lead_analyses` come from the gate evaluator. `_format_dimension_results` loses all optimistic defaults (renders `MISSING` explicitly). Meta-agent failure does not block the verdict — analysis completes with empty advisory fields.

7. **Three-state geocoding.** `classify_location` returns `{location_state: "near"|"far"|"unclear", distance_miles, geocoded}`; `location_near` retained as a derived boolean for backward compatibility (`state == "near"`). Always-near token list becomes the *unclear* token list (`online`, `remote`, `anywhere`, `us`, `usa`, plus timezone strings `est/cst/mst/pst/edt/cdt/mdt/pdt`); un-geocodable → `unclear`. Mixed strings: any concrete near part → near; concrete parts all far → far; no concrete parts → unclear (a follow-the-existing-splitting rule).

## Risks / Trade-offs

- [Suitable volume drops sharply; wanted leads land in needs_review] → `needs_review` posts stay visible in watch history with per-gate reasons (`gate_results` stored in `dimension_results_json`); manual add-to-leads remains. Thresholds/weights are constants in one module for easy tuning.
- [Prompt drift: DB-edited prompts change output field names, starving gates] → gates treat unparseable/missing as unclear (fail closed); per-gate `reason` strings make drift visible immediately in the UI.
- [Retry doubles LLM latency on failing dimensions] → only failed dimensions retry, once; scout runs are background tasks.
- [Score bands feel arbitrary] → they are explicitly a calibration starting point; the separate feedback-loop proposal measures them against user verdicts.
- [Existing `min_confidence` values (0.5/0.7) interact with new bands] → suitable band starts at 0.6, so a 0.7 threshold now demands genuine margin; documented in tasks as an operator note.

## Migration Plan

Deploy core+worker together (worker imports core). No schema migration. Stored analyses keep their old values; only new analyses use the deterministic path. Rollback = revert images; no data cleanup needed.

## Open Questions

- Exact score weights (start with the sketch in Decision 4; tune via the feedback-loop work).
- Whether `needs_review` posts should auto-promote at very high computed scores — out of scope here; default is they never auto-promote.
