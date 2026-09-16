# Proposal: agent-decision-evaluation

## Why

The six analysis agents decide which contacts become leads, but nothing records whether a human agreed with them: a wrong `not_recommended` silently discards a good contact, a wrong `suitable` costs outreach time, and per-dimension mistakes (missed location, misread intent, hallucinated age) are only ever noticed in passing. Prompt edits in `/settings/agents` are therefore made on anecdote, with no way to measure whether a new prompt version does better or worse on cases the user has already judged. A structured, human-labelled evaluation loop is the prerequisite for improving prompts, agents, or the information collected about a contact.

## What Changes

- **Human evaluations of agent decisions**: the user can record, on any completed analysis (lead detail or scout `needs_review` post), a verdict on the **final recommendation** and on **each dimension**: agree / disagree / partially, an optional corrected value, a set of controlled **reason tags** (e.g. `missed_location`, `wrong_age`, `misread_intent`, `hallucinated_fact`, `missing_context`, `too_strict`, `too_lenient`, `unparseable_output`), a free-text note, and for `missing_context` a statement of *what information would have been needed*. Evaluations are append-only, audit-logged, and snapshot the agent output and prompt versions they judged.
- **Review queue**: a dedicated page that serves unevaluated analyses for judgment, stratified by recommendation so `not_recommended` and `needs_review` cases are sampled and not only the `suitable` leads the user already sees. Cases where behaviour already contradicts the agent (a `suitable` lead marked `ignored`, a `not_recommended` post manually promoted) are surfaced first.
- **Evaluation dashboard**: agreement rate, tag distribution and a recommendation confusion matrix (agent vs human), broken down per dimension and per **prompt version**, with trend over time and a list of "what information was missing" statements. This is where the user learns which agent to fix and how.
- **Labelled dataset + prompt replay**: evaluations with their stored dimension inputs form a labelled set. From `/settings/agents` the user can **replay** a draft prompt version for one dimension against that set (locally, via the inference gate) and see agreement with human labels before activating it. Datasets are exportable as JSONL for offline work.
- **Prompt version scorecard**: each `agent_prompts` version shows its live agreement rate and evaluated-case count, so rollback decisions are informed.

## Capabilities

### New Capabilities

- `analysis-evaluation`: recording human verdicts on agent decisions, the review queue, evaluation metrics/dashboard, labelled dataset export, and prompt replay against labelled cases.

### Modified Capabilities

- `lead-analysis`: analysis and dimension read models expose the latest human evaluation; prompt version history exposes evaluation metrics per version; a prompt version can be replayed against labelled cases before activation.
- `scout-watch`: a scout post's analysis (including `needs_review`/`not_recommended` outcomes that never became leads) can be evaluated, and evaluable posts are exempt from history retention cleanup.

## Impact

- **DB / migration**: new `analysis_evaluations` table (subject = lead analysis or scout post, dimension nullable for the final verdict, human verdict, corrected value JSON, tags JSON, missing-info text, agent snapshot JSON, prompt versions JSON, model, notes, timestamps); new `prompt_replays` table (dimension, candidate prompt text/version, case count, agreement, per-case results JSON, status). `scout_watch_posts` gains `evaluated_at` so retention skips evaluated posts.
- **Core**: new `evaluations` router + `AnalysisEvaluationService` (create, list, summary metrics, queue, export); `agent_prompts` routes gain replay endpoints and per-version metrics; `scout_watch` retention query excludes evaluated posts. All mutating endpoints write `audit_log`.
- **Worker**: new `evaluation.replay_prompt` task (queue `multi_agent_analysis`, `jobs` idempotency, runs through the inference gate).
- **Web**: evaluation controls in `RecommendationCard` and `DimensionCard`; new `/evaluations` page (queue + dashboard + export); replay panel on `/settings/agents`; BFF proxy routes.
- **Related change**: complements `lead-triage-and-feedback`, whose calibration report aggregates *implicit* behavioural signals; this change records *explicit* human labels. The two reports are designed to be shown side by side but neither depends on the other.
- **No new external dependencies.**

## Non-goals

- No automatic prompt rewriting or fine-tuning; humans edit prompts, the system measures them.
- No changes to decision gates, thresholds, or agent set; evaluations inform those changes but do not apply them.
- No multi-reviewer workflow or inter-rater agreement (single-user system).
- No cloud/LLM-as-judge grading; replay uses the same local inference endpoint and compares against human labels only.
- No evaluation of inbox conversations or message drafts; scope is lead-suitability analysis output.
