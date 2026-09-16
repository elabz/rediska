## 1. Data model and migration

- [x] 1.1 Add `AnalysisEvaluation` and `PromptReplay` ORM models and `ScoutWatchPost.evaluated_at` in `domain/models/__init__.py`
- [x] 1.2 Write alembic migration `018_add_analysis_evaluations` (both tables, `evaluated_at` column, indexes) with a working downgrade
- [x] 1.3 Add `REASON_TAGS`, verdict/recommendation enums and Pydantic schemas (`EvaluationCreate`, `EvaluationResponse`, `EvaluationSummary`, `QueueItem`, `ReplayCreate`, `ReplayResponse`) in `api/schemas/evaluations.py`

## 2. Evaluation service (core)

- [x] 2.1 Create `domain/services/analysis_evaluation.py` with `record()` (snapshot agent output + prompt versions for both subject types, `missing_info` validation, sets `scout_watch_posts.evaluated_at`, writes `audit_log` `evaluation.record`)
- [x] 2.2 Implement `effective_for_subject()` (latest row per dimension) and a helper to attach `evaluation` fields to analysis and scout post read models
- [x] 2.3 Implement `queue()` — contradictions pass, stratified round-robin pass, filters, cursor pagination
- [x] 2.4 Implement `summary()` — per-dimension verdict counts and agreement, per-prompt-version metrics, tag distribution, confusion matrix, weekly trend, missing-info aggregation
- [x] 2.5 Implement `export_jsonl()` (verbatim content, audit `evaluation.export`)
- [x] 2.6 Unit tests for record/effective/queue/summary/export against synthetic analyses and scout posts (SQLite fixtures; no real scraped content)

## 3. Evaluation API (core)

- [x] 3.1 Add `api/routes/evaluations.py`: `POST /evaluations`, `GET /evaluations` (list by subject), `GET /evaluations/queue`, `GET /evaluations/summary`, `GET /evaluations/export`; register in `main.py`
- [x] 3.2 Extend lead analysis responses (`/leads/{id}/analysis`, `/analysis/{analysis_id}`, `/analysis/history`) with `evaluation` fields via the helper from 2.2
- [x] 3.3 Extend scout watch run detail / history post responses with `evaluation` fields
- [x] 3.4 Integration tests for the routes (auth, validation, audit rows, evaluation fields present in analysis payloads)

## 4. Prompt metrics and replay

- [x] 4.1 Add per-version `evaluations` and `agreement` to `GET /agent-prompts/{dimension}/versions`
- [x] 4.2 Implement `compare_fields()` per dimension (categorical exact, age ±2, list overlap ≥ 0.5, `location_state` exact) with unit tests
- [x] 4.3 Add `POST /agent-prompts/{dimension}/replay`, `GET .../replays`, `GET .../replays/{id}`, `POST .../replays/{id}/cancel` (reject when no labelled cases or a replay is already running; audit `prompt.replay`)
- [x] 4.4 Add worker task `evaluation.replay_prompt` (queue `multi_agent_analysis`, `jobs` idempotency, `max_retries=0`, per-case progress, cancellation check, transient prompt with `db=None`, `EVALUATION_REPLAY_MAX_CASES` setting wired through `config.py`, `docker-compose.yml` and `.env.example`)
- [x] 4.5 Worker unit test for replay with a mocked inference client (agreement computed, skipped-no-input counted, nothing persisted to analyses/prompts)

## 5. Scout retention exemption

- [x] 5.1 Update `ScoutWatchService.delete_old_runs()` to skip posts with `evaluated_at` and runs that still own posts
- [x] 5.2 Unit test: evaluated old post and its run survive cleanup, unevaluated old post is deleted

## 6. Web: BFF routes

- [x] 6.1 Add `/api/core/evaluations/{route,queue,summary,export}` proxy routes
- [x] 6.2 Add `/api/core/agent-prompts/[dimension]/replay`, `/replays`, `/replays/[id]`, `/replays/[id]/cancel` proxy routes

## 7. Web: inline evaluation on analysis views

- [x] 7.1 Build `EvaluationDialog` (verdict control, tag multi-select with `missing_context` → required missing-info field, dimension-aware correction form, notes) and `EvaluationBadge`
- [x] 7.2 Mount badge + dialog in `RecommendationCard` and `DimensionCard`; refresh analysis state on save without reload
- [x] 7.3 Mount badge + dialog on scout watch history post detail
- [x] 7.4 Vitest coverage for the dialog validation and badge rendering

## 8. Web: /evaluations page and replay panel

- [x] 8.1 Create `/evaluations` page with Review queue tab (item context, controls, skip, filters, empty/error states) and sidebar entry
- [x] 8.2 Dashboard tab: agreement per dimension and per prompt version, confusion matrix, tag distribution, weekly trend, missing-info list (empty state when no evaluations)
- [x] 8.3 Export action (per-dimension JSONL download)
- [x] 8.4 `ReplayPanel` on `/settings/agents`: replay history, "Replay draft against labelled cases", progress polling, per-case results table, cancel; per-version metrics beside version history
- [x] 8.5 Lint clean (`npm run lint`) and vitest passing for new components

## 9. Docs and wrap-up

- [x] 9.1 Update `CLAUDE.md` (pages table, tables table, Celery tasks, env vars) and `.env.example`
- [x] 9.2 Rebuild core + worker + web, run migration, verify new task symbol in the running worker, smoke-check `/evaluations` empty states with synthetic `test_` data only
