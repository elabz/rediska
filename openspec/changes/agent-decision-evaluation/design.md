# Design: agent-decision-evaluation

## Context

Every analysis already persists what is needed to judge it: `lead_analyses` holds the final recommendation, computed confidence, gate verdict (`meta_analysis_json.gate_verdict`) and per-dimension JSON; `analysis_dimensions` holds the exact model input (`input_data_json`), parsed output, raw response, model info and `prompt_version`; scout posts that never became leads hold the equivalent in `scout_watch_posts.dimension_results_json`. `agent_prompts` is versioned per dimension and `prompt_versions_json` on each analysis records which versions produced it. What is missing is a place to store the human's opinion, a way to serve cases for judgment that are not biased toward the leads the user already looks at, and a way to test a prompt edit against those judgments before it goes live.

Constraints: single user; local-only inference through the new inference concurrency gate (one request at a time by default); analysis results are never deleted (retention policy memory); content is stored and shown verbatim; every mutation is audit-logged; the sibling change `lead-triage-and-feedback` will add implicit behavioural metrics (calibration report) and its own retention exemption for `needs_review` posts — this design must not conflict with it at archive time.

## Goals / Non-Goals

**Goals:**
- Capture explicit, structured human verdicts on final and per-dimension agent decisions with enough snapshot to remain meaningful after re-analysis or prompt changes.
- Serve a review queue that samples all recommendation classes and surfaces behaviour/agent contradictions first.
- Compute agreement, tag distribution, confusion matrix and missing-information aggregates per dimension and per prompt version.
- Turn evaluated cases into a replayable dataset so prompt edits are measured, not guessed.

**Non-Goals:**
- Auto-tuning prompts or thresholds; multi-reviewer workflows; LLM-as-judge; evaluating conversations/drafts.

## Decisions

1. **One append-only table, polymorphic subject.**
   `analysis_evaluations(id, subject_type ENUM('lead_analysis','scout_post'), subject_id BIGINT, account_id, dimension VARCHAR(64) NULL, human_verdict ENUM('agree','partial','disagree'), corrected_value_json JSON NULL, reason_tags_json JSON NOT NULL, missing_info TEXT NULL, notes TEXT NULL, agent_snapshot_json JSON NOT NULL, prompt_versions_json JSON NOT NULL, model_name VARCHAR(128) NULL, created_at, created_by)` with index `(subject_type, subject_id, dimension, created_at)` and `(dimension, created_at)`. "Effective" = latest row per `(subject, dimension)`, resolved with a window query in the service. *Alternative rejected:* mutable one-row-per-subject upsert — loses the history of the user changing their mind, which is itself signal about ambiguous cases. *Alternative rejected:* separate tables for lead analyses and scout posts — doubles every query; the subject columns plus a snapshot make the row self-describing.

2. **Snapshot at evaluation time, not join at read time.**
   `agent_snapshot_json` copies the judged recommendation/confidence/gate verdict (final) or the dimension's parsed output, and `prompt_versions_json` copies the analysis's `prompt_versions_json`. Metrics per prompt version read the snapshot's version, so a later re-analysis of the same lead does not retroactively move an evaluation to a different version. Scout posts have no `prompt_versions_json`; the service resolves the active versions at evaluation time from `agent_prompts` and records them (documented approximation).

3. **Controlled tag vocabulary in code, not a table.**
   `REASON_TAGS` constant in `domain/services/analysis_evaluation.py` (mirrored in the web app), validated by Pydantic. `missing_context` requires `missing_info`. Adding a tag is a code change and a spec update; this keeps aggregation trivial and avoids free-text drift. `other` + `notes` is the escape hatch.

4. **Queue ordering in SQL with two passes.**
   Pass 1 (contradictions): `lead_posts.status='ignored'` AND latest analysis `suitable`; scout posts with `lead_id IS NOT NULL` AND recommendation IN (`not_recommended`,`needs_review`) — each `LEFT JOIN`ed to the effective final-verdict evaluation and filtered `IS NULL`. Pass 2: per-class queries merged round-robin in Python; `needs_review` ordered by `score DESC, unclear_gate_count ASC` (cursor `(class, score, id)`), the others newest first (cursor `(class, created_at, id)`). Rationale: after the 2026-09-16 recovery, cleanly analysed r/bdsmpersonals posts cluster at 0.49-0.58 blocked only by `location: unclear`; those are the decisions a human can actually settle, and they are also the evidence for whether the location gate or the listing parser needs work. Filters apply to both passes. *Alternative rejected:* a materialised `evaluation_queue` table — the source tables already carry indexes on recommendation; the queue is read by one user.

5. **Metrics are SQL aggregates over effective evaluations.**
   `GET /evaluations/summary` builds the effective-row CTE once and computes counts by `(dimension, human_verdict)`, by `(dimension, prompt_version)` (extracted from `prompt_versions_json ->> '$.<dimension>'`, or the snapshot's `prompt_version` for the final verdict → meta), tag counts by exploding `reason_tags_json` in Python (JSON_TABLE is avoided to stay portable to the SQLite test DB), confusion matrix from `agent_snapshot_json.recommendation` × `COALESCE(corrected_value_json.recommendation, agent recommendation when agree)`, weekly trend by `YEARWEEK(created_at)`, missing-info grouped by `LOWER(TRIM(missing_info))`. Cached nothing — the row count is small (hundreds to low thousands).

6. **Replay is a Celery task that reuses the dimension agents unchanged.**
   `evaluation.replay_prompt(replay_id)` loads `prompt_replays` (id, dimension, candidate_system_prompt, candidate_version NULL, status, case_count, completed_count, agreement, results_json, error, created_at, finished_at), selects the most recent N effective evaluations for the dimension whose subject has a stored `analysis_dimensions.input_data_json` (scout-only subjects are skipped and counted as `skipped_no_input`), and for each calls `agent.analyze()` with a transient `AgentPrompt` built from the candidate text and the active version's output schema/temperature/max_tokens, `db=None` so nothing is persisted. Comparison: per-dimension `compare_fields(expected, produced)` in the service — exact match on categorical fields (recommendation, gender, orientation, intent), tolerance for numeric age (±2), set overlap ≥ 0.5 for list fields (interests, risk flags), `location_state` exact. A case "agrees" when all compared fields agree. Expected value = `corrected_value_json` merged over the snapshot for `disagree`/`partial`, the snapshot itself for `agree`. Progress is written every case so the UI can poll. Uses `jobs` idempotency keyed on `replay_id`, `max_retries=0` (a replay is cheap to restart), honours cancellation via the existing `jobs.status='cancelled'` check between cases. The inference gate serialises it behind live scout analyses automatically. *Alternative rejected:* running replay inline in the API request — 50 cases × ~10 s blocks the request far past any timeout.

7. **Retention exemption is additive.**
   `scout_watch_posts.evaluated_at` (set on any evaluation of that subject) and `delete_old_runs()` adds `AND evaluated_at IS NULL` on the post delete and excludes runs that still own posts. This is written as an ADDED requirement so it composes with `lead-triage-and-feedback`'s MODIFIED retention requirement regardless of archive order.

8. **UI: one dialog component, three mount points.**
   `EvaluationDialog` (verdict segmented control, tag multi-select, dimension-aware correction form, missing-info textarea shown when `missing_context` is selected, notes) is mounted from `RecommendationCard`, `DimensionCard`, and the `/evaluations` queue item. Cards render an `EvaluationBadge` from the `evaluation` field already present in the analysis payload. `/evaluations` is a tabbed page (`queue` | `dashboard`) with the export button in the header; charts follow the existing dashboard/bento styling. `/settings/agents` gains a `ReplayPanel` under the prompt editor that posts the *current editor text* as the draft. BFF routes mirror the core paths under `/api/core/evaluations/*` and `/api/core/agent-prompts/[dimension]/replay*`.

## Risks / Trade-offs

- [Evaluations on scout posts lack stored model input] → replay skips them and reports the skip count; the lead-analysis path stores inputs, and `needs_review` posts promoted to leads get full inputs on their next analysis.
- [Snapshot drift: dimension output shapes change with prompt edits] → comparison rules operate on a fixed set of canonical fields per dimension; unknown fields are ignored, and `unparseable_output` tag captures schema breakage.
- [Replay cost on the single local GPU] → hard cap `EVALUATION_REPLAY_MAX_CASES` (default 50), one replay at a time (reject if a replay for any dimension is `running`), inference gate ensures no concurrency with scout analyses.
- [Queue ordering starves nothing but may show very old items] → `since` filter and default window of 30 days on the stratified pass; contradictions have no window.
- [Sibling change touches the same scout retention function] → additive predicate on a separate column; both can land in either order.
- [Content policy] → export and UI show stored content verbatim; no redaction anywhere.

## Migration Plan

One alembic migration `018_add_analysis_evaluations`: create `analysis_evaluations`, `prompt_replays`, add `scout_watch_posts.evaluated_at` (+ index). Deploy core + worker + web together (worker needs the new task and the retention predicate; web needs the new BFF routes). Rollback: revert code; the tables are inert and can be dropped by the down migration.

## Open Questions

- Whether the final-verdict evaluation should also be offered on the Leads list row (quick agree/disagree) — deferred; the lead detail page and the queue cover it.
- Exact replay comparison tolerances per field (age ±2, list overlap 0.5) are initial values to revisit after the first replay runs.
