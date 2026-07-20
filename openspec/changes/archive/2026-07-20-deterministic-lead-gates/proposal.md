# Proposal: deterministic-lead-gates

## Why

The lead-quality review found that the suitability gates are effectively decorative: the hard decision rules (gender, location, D/s compatibility, partner max age, authenticity) are executed by the LLM meta agent as prompt instructions, and their inputs fail open — a failed `relationship_goals` dimension (currently ~24% of runs: 677/2781) silently defaults `partner_max_age` to `no_max_age`, and a missing confidence defaults to 0.7, exactly meeting the 0.7 `min_confidence` gate. The location gate leaks in both directions: `online`/`remote`/`anywhere`/`us`/`usa` count as always-near (hard-pass) while un-geocodable strings (including timezone strings like "EST") hard-fail. The result: 21% of analyzed scout posts marked `suitable` (2,754 leads created), with 72% of confidences piled at 0.9.

## What Changes

- **Deterministic gate evaluation**: move the five hard gates (gender, location, D/s compatibility, partner max age vs the configured user age, authenticity/red flags) out of the LLM meta prompt into pure code in `MultiAgentAnalysisService`, applied to the structured dimension outputs. Both entry points (`POST /leads/{id}/analyze-multi` and scout `analyze_and_decide`) share the same code path.
- **LLM meta agent demoted to advisory**: it still produces reasoning, strengths, concerns, and `priority_level`, but it can no longer flip a code-gate verdict. **BREAKING** for stored expectations: `final_recommendation` is now computed by code; the meta agent's own recommendation is stored as advisory context only.
- **Fail-closed defaults**: any failed or missing dimension result required by a gate yields `needs_review` — never a silent pass. The `partner_max_age` default-open path is removed. A failed dimension agent is retried once automatically before falling back to `needs_review`.
- **Deterministic confidence score**: replace model-reported confidence as the gating value with a computed score derived from gate margins and dimension confidences; the model-reported number is stored as advisory. The 0.7-on-missing default is removed. Scout auto-promotion compares the computed score against `min_confidence`.
- **Three-state location semantics**: `classify_location` returns `near` / `far` / `unclear`. Virtual and country-scale tokens (`online`, `remote`, `anywhere`, `us`, `usa`) and un-geocodable strings (including timezone strings) are `unclear` → `needs_review`. Only concretely geocoded near locations pass the gate; concretely geocoded far locations fail it.

## Capabilities

### New Capabilities

_None — this hardens existing behavior._

### Modified Capabilities

- `lead-analysis`: the "Multi-agent analysis runs six agents" requirement changes — final recommendation and confidence become deterministic code outputs over dimension results, with fail-closed handling, one automatic dimension retry, and three-state offline location classification (the "Demographics location classification is offline" scenario gains the `unclear` state).
- `scout-watch`: the "Auto-promotion to leads by confidence" requirement changes — promotion compares the deterministic computed score (not model-reported confidence) against `min_confidence`, and only code-gated `suitable` posts are eligible.

## Impact

- **Core**: `domain/services/multi_agent_analysis.py` (gate evaluator, computed score, retry, `_normalize_meta_output` demoted), `domain/services/agents/agent_implementations.py` (`_format_dimension_results` default-open removal, meta prompt input), `domain/services/agents/default_prompts.py` (meta prompt rewritten to advisory role), `domain/services/geocoding.py` (three-state classification), `domain/services/agents/demographics.py` (consume three-state result).
- **Worker**: `tasks/scout.py` step 8 promotion decision consumes the computed verdict/score (shared service code; minimal task change).
- **Data**: no schema changes — `lead_analyses.final_recommendation`/`confidence_score` keep their columns with new provenance; advisory meta output continues to live in the stored meta dimension result. Existing stored analyses are not migrated or recomputed.
- **Config**: the user's own constraints used by gates (user age 45+, dominant orientation, home location) currently live inside the meta prompt text; gates read them from configuration (settings/env) instead.
- **Prompt drift risk**: `agent_prompts` DB edits can change dimension output shapes that gates depend on; gates must treat unparseable fields as missing (→ `needs_review`).

## Non-goals

- No changes to discovery queries, watch configuration, or Reddit search behavior.
- No author deduplication or lead-funnel/UX changes (separate proposals).
- No changes to analysis context assembly or summary usage (separate proposal).
- No recomputation or migration of already-stored analyses.
- No content filtering of any kind (per research-content-policy).
