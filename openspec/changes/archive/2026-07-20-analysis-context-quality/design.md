# Design: analysis-context-quality

## Context

`BaseAnalysisAgent._build_input_prompt` (agents/`__init__.py`) builds one string — `<title>`, `<body>`, `<profile_summary>`, `<recent_posts>` (all posts joined), `<comments>` (all comments joined) — used verbatim by all five dimension agents. There is no size limit; a scout post with 20 posts + 100 comments can exceed a local model's context window, in which case llama.cpp silently truncates and the model may never see the parts that matter. `input_context["summaries"]` (interests/character, generated at real inference cost per scout post) is dead data, and the scout path's `profile` dict carries `bio`/`karma`/`created_at`/`is_verified` that no prompt reads.

## Goals / Non-Goals

**Goals:**
- Bounded, dimension-appropriate model input; the lead post is always fully present.
- Summaries and account metadata reach the agents that need them.
- Audit rows reflect the true model input.

**Non-Goals:**
- Prompt-content (system prompt) changes, new dimensions, model/template changes, summary-generation changes.

## Decisions

1. **Per-dimension assembly via a context-spec table, not per-agent overrides.** Add a module-level `DIMENSION_CONTEXT_SPECS: dict[str, ContextSpec]` in `agents/__init__.py`; `_build_input_prompt(dimension, input_context)` consults it. A `ContextSpec` names which sections to include (`profile_summary`, `interests_summary`, `character_summary`, `account_metadata`, `recent_posts`, `comments`) and per-section limits (`max_posts`, `per_item_chars`). Keeps the change in one file instead of five overridden methods; agents keep calling the same helper.
   - demographics: `profile_summary` only
   - preferences, sexual_preferences: `interests_summary` + `recent_posts` (N=10 newest, 800 chars/item)
   - relationship_goals: `interests_summary`
   - risk_flags: `account_metadata` + `character_summary`
   - Raw `<comments>` dumps are no longer sent to any dimension (character summary replaces them for risk_flags; others never needed them).
2. **Budget enforcement in chars, newest-first.** A global cap (`ANALYSIS_CONTEXT_MAX_CHARS`, default ~24000 ≈ 6k tokens) applied after assembly: sections are trimmed from the oldest post backwards; `<title>`/`<body>` are never trimmed. Chars, not tokens — no tokenizer dependency, and the ratio is stable enough for a safety cap. Configurable via `config.py` so operators with larger context windows can raise it.
3. **Account metadata as a structured block.** `<account_metadata>karma=…, account_age_days=…, verified=…, bio=…</account_metadata>` computed from `input_context["profile"]`. The core path's `_build_input_context` (multi_agent_analysis.py) is extended to include bio/karma/created_at from the latest `profile_snapshots`/`external_accounts` data so the non-scout path gets parity with the scout path.
4. **Summaries flow through both entry paths.** Scout path already places them in `input_context["summaries"]`; the core `analyze_lead` path already generates-or-reuses them — only the prompt assembly changes.
5. **Audit truthfulness.** `_run_agent_harness` (or the agents' `_store_dimension_result` call sites) passes `input_data={"prompt_excerpt": actual_prompt[:2000], "sections": [...names...], "total_chars": n}` instead of today's unrelated slices.
6. **Sequencing.** `deterministic-lead-gates` (sibling in-flight change) also edits `multi_agent_analysis.py`. Implement this change after it lands to avoid conflict churn; the two are functionally independent (gates consume dimension *outputs*; this changes dimension *inputs*).

## Risks / Trade-offs

- [Narrower context could starve an agent of a signal it used to find in raw comments] → summaries are generated from exactly those comments; if a regression is suspected, per-dimension specs are one-line edits, and A/B comparison is possible via `analysis_dimensions` history.
- [Char budget mis-tuned for a given model] → configurable; default chosen well under an 8k-token window.
- [Existing prompt text references `<recent_posts>`/`<comments>` tags] → review the versioned system prompts for tag references before removing a section from a dimension (risk_flags prompt mentions "profile"); adjust specs, not prompts.

## Migration Plan

Code-only; no schema or data migration. Deploy core + worker together (worker imports core agents). Rollback = revert. Existing stored analyses are unaffected; new analyses simply record the new input format.

## Open Questions

- Exact N and per-item caps for `recent_posts` (start 10 × 800 chars; tune with the feedback data once `lead-quality-feedback` lands).
- Whether `relationship_goals` also benefits from a small newest-posts slice (start without; its 24% failure rate is addressed by `deterministic-lead-gates`' retry work, not context size).
