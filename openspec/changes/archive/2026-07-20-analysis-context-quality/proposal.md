# Proposal: analysis-context-quality

## Why

Every dimension agent currently receives the identical, unbounded context: lead title + body + profile summary + all ~20 fetched posts + all ~100 comments concatenated by `BaseAnalysisAgent._build_input_prompt`. On local llama.cpp models this risks silent context-window overflow, and comment noise drowns the personals post the analysis is actually about. Meanwhile the two LLM summaries generated per scout post (interests, character) are never included in any prompt — pure wasted inference — and profile bio/karma/account age, the strongest scam signals, never reach the Risk Flags agent. (The `[:1000]` slices in `agent_implementations.py` only truncate what is *stored for audit*, not what the model sees.)

## What Changes

- **Per-dimension context assembly**: each agent gets the lead title + body always, plus a bounded, dimension-appropriate slice instead of the whole dump:
  - demographics: title + body + profile summary only
  - preferences, sexual_preferences: title + body + interests summary + N newest posts (per-item char cap)
  - relationship_goals: title + body + interests summary
  - risk_flags: title + body + account metadata (karma, account age, bio, is_verified) + character summary
- **Total input budget**: overall input capped to a configurable char/token budget; truncation drops oldest items first and never drops the lead body.
- **Summaries become useful**: interests/character summaries feed the prompts; where a summary suffices, the raw comment dump is no longer sent.
- **Honest audit records**: `analysis_dimensions.input_data_json` stores what was actually sent to the model (truncated for storage), not an unrelated excerpt.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `lead-analysis`: dimension agents receive budgeted, dimension-specific input context (new requirement); per-dimension execution tracking records the actual model input; interests/character summaries are consumed by the dimension agents rather than generated-and-ignored.

## Impact

- **Core service**: `domain/services/agents/__init__.py` (`_build_input_prompt` becomes per-dimension), `agent_implementations.py` + `demographics.py` (input_data audit args), `multi_agent_analysis.py` `_build_input_context` (carry account metadata + summaries), scout task input_context already carries bio/karma — now consumed.
- **Config**: new budget settings (e.g. `ANALYSIS_CONTEXT_MAX_CHARS`, per-item caps) with sensible defaults.
- **No schema changes**; no API changes; no UI changes.
- **Coordination**: the in-flight `deterministic-lead-gates` change touches `multi_agent_analysis.py` too — implement after it (see design).

## Non-goals

- No changes to models, chat templates, or inference parameters.
- No new analysis dimensions and no rewrites of the versioned system prompts in `agent_prompts` (only the *input* assembly changes).
- No changes to how summaries are generated (only to how they are consumed).
- No re-analysis/backfill of existing analyses.
