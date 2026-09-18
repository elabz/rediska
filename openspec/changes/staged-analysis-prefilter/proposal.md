## Why

Every analysed post costs five dimension-agent calls plus a meta call, and inference concurrency is pinned at one to keep the local llama.cpp gateway stable. The five dimension agents are launched together but execute one after another behind that gate, so a post takes six sequential LLM calls no matter what the first one finds. Two of the five hard gates, gender and location, depend on the demographics agent alone, and any gate `fail` fixes the verdict at `not_recommended`. For every post that fails one of them, the other five calls change nothing. The share of such posts is not assumed here: the first task measures it from the existing calibration report's gate outcomes, and the change is only worth shipping if that share is large. That wasted inference is what limits how many watches can run, delays the good leads queued behind the bad ones, and would make source-discovery trials slow.

## What Changes

- **Dimension agents run in stages.** Stage 1 runs the demographics agent. The gender and location gates are evaluated immediately. If either **fails**, the analysis stops: the remaining dimensions and the meta agent are not run, and the verdict is `not_recommended` with the failing gate as the reason. If both pass or either is `unclear`, stage 2 runs the remaining four agents and then the meta agent, exactly as today.
- **Only a `fail` stops early, never `unclear`.** Unclear posts go to a human, and the human needs the full picture, so they always get the full analysis.
- **Skipped is not failed.** Dimensions not run are recorded as `skipped` with the reason, are not retried, do not count as dimension failures in the calibration report, and their gates are recorded as `not_evaluated` rather than `unclear`.
- **A free stage 0 from the title tag, in shadow mode first.** Personals titles carry tags like `[M4F]` and `35 [F4M]`. A strict parser reads the author's gender from an unambiguous bracketed tag with zero LLM calls. It ships in shadow mode: it records what it would have decided next to the demographics agent's answer, and the calibration report shows their agreement. It can be switched to active (skipping even the demographics call on a gender fail) only by a setting, once agreement is demonstrated.
- **Full analysis on request.** A manual analyse from the lead detail page runs every stage regardless, and an early-exited result offers "Run full analysis". Scout runs, scout re-analysis, and auto-analyse on save use staging.
- **Savings are measured.** Each analysis records the calls made and the calls skipped; the calibration report totals them and breaks early exits down by gate.

## Non-goals

- No change to gate logic, the verdict rule, fail-closed behaviour, score bands, or `min_confidence`.
- No early exit on `unclear`, on low compatibility, or on anything other than a hard gate `fail`.
- No keyword or regex pre-filter on post bodies, and no content filtering of any kind; stage 0 reads only the structured title tag and only to decide the gender gate.
- No raising of `INFERENCE_MAX_CONCURRENT` and no change to the inference gate or retry policy.
- No reordering based on learned statistics in this change; the stage order is fixed, with the calibration data collected to revisit it.
- No deletion or rewriting of existing analyses.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `lead-analysis`: the six-agent requirement becomes staged with early exit on a hard gate failure; new requirements cover skipped-dimension recording, the title-tag stage in shadow and active modes, forced full analysis, and savings metrics.

## Impact

- **Database**: `dimension_status_enum` gains `skipped`; `lead_analyses` and `scout_watch_posts` gain nullable `early_exit_gate`, `llm_calls_made`, `llm_calls_skipped`, and `title_tag_json` (shadow result).
- **Core**: `MultiAgentAnalysisService._run_dimension_agents` becomes staged (both the API and scout paths already go through it); `lead_gates.py` gains a partial-evaluation entry point and the `not_evaluated` marker; new `title_tag.py`; `calibration_report.py` stops counting skipped dimensions as failures and adds savings and tag-agreement sections; evaluation queue and read models tolerate analyses with one dimension.
- **Worker**: `scout.analyze_and_decide` and `reanalyze_post` store skipped markers in `dimension_results_json` so "missing" keeps meaning "failed".
- **Web**: early-exit banner and "Run full analysis" on lead detail and scout post detail; skipped dimension cards; calibration panel sections.
- **Config**: `ANALYSIS_STAGED_ENABLED` (default true), `ANALYSIS_TITLE_TAG_MODE` (`off` | `shadow` | `active`, default `shadow`), wired through `docker-compose.yml`.
- **Interaction with other changes**: independent of `configurable-match-profile`, but the gender gate it short-circuits on reads accepted genders from wherever the gate reads them, so it works before and after that change.
