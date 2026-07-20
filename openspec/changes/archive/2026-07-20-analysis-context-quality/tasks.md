# Tasks: analysis-context-quality

> Sequence after `deterministic-lead-gates` lands (both edit `multi_agent_analysis.py`).

## 1. Context specification

- [x] 1.1 Add `ContextSpec` dataclass and `DIMENSION_CONTEXT_SPECS` table to `agents/__init__.py` (sections + per-section limits per dimension: demographics→profile_summary; preferences/sexual_preferences→interests_summary + recent_posts(N,cap); relationship_goals→interests_summary; risk_flags→account_metadata + character_summary)
- [x] 1.2 Add budget config to `config.py` (`ANALYSIS_CONTEXT_MAX_CHARS` default ~24000, `ANALYSIS_MAX_RECENT_POSTS` default 10, `ANALYSIS_POST_ITEM_CHARS` default 800)

## 2. Prompt assembly

- [x] 2.1 Rewrite `_build_input_prompt(dimension, input_context)` to consult the spec: always include `<title>`/`<body>`; include summary/metadata/posts sections per spec; render `<account_metadata>` from `input_context["profile"]` (karma, account_age_days from created_at, bio, is_verified)
- [x] 2.2 Enforce the global char budget after assembly — trim oldest posts first, never trim title/body
- [x] 2.3 Stop emitting raw `<comments>` dumps; verify each versioned system prompt does not depend on a removed tag (adjust the spec, not the prompt, if it does)

## 3. Context carriers

- [x] 3.1 Extend `MultiAgentAnalysisService._build_input_context` to include account metadata (bio/karma/created_at/is_verified from snapshot/account) so the core `analyze_lead` path reaches parity with the scout path
- [x] 3.2 Confirm scout path (`analyze_and_decide`) already populates `profile` + `summaries`; no change expected beyond consumption

## 4. Audit truthfulness

- [x] 4.1 Change dimension agents' `_store_dimension_result` input_data to `{prompt_excerpt: prompt[:2000], sections: [...], total_chars: n}` reflecting the actual model input

## 5. Tests & verification

- [x] 5.1 Unit: `_build_input_prompt` per dimension includes only spec'd sections; title+body always present; comments never present
- [x] 5.2 Unit: budget trimming drops oldest posts first and preserves title/body when over budget
- [x] 5.3 Unit: risk_flags input contains account metadata; preferences/relationship_goals/sexual_preferences inputs contain the interests summary; risk_flags contains the character summary
- [x] 5.4 Run core `pytest` (agents + multi_agent_analysis suites) green; `catenary diagnostics` clean
- [x] 5.5 Update `openspec/specs/lead-analysis/spec.md` via archive flow when done
