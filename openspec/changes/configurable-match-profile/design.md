## Context

Matching criteria today:

| Criterion | Where it lives | How to change it |
|---|---|---|
| Preferred hobbies and kinks, scoring rule | text of the preferences prompt (`default_prompts.py`, or the active `agent_prompts` row) | edit the prompt, replay, activate |
| Accepted genders | literal tuple in `lead_gates._gate_gender` | code change |
| User age, D/s orientation | `USER_AGE`, `USER_DS_ORIENTATION` via `UserConstraints.from_settings()` | `.env` + compose + restart |
| Home point and radius | `HOME_LATITUDE`, `HOME_LONGITUDE`, `LOCATION_NEAR_THRESHOLD_MILES` | `.env` + compose + restart |
| Priority thresholds | `PROMOTE_THRESHOLD`, `DEMOTE_THRESHOLD` in `lead_priority.py` | code change |

The compatibility score is produced by the LLM following a rule in the prompt, then consumed by `compute_score` (weight 0.15) and `derive_priority`. Both the API path and scout go through `MultiAgentAnalysisService._run_dimension_agents`, and there is a precedent for code post-processing of an agent's output: `location_near` is computed by the offline geocoder after the demographics agent extracts the location text.

Constraints: gates are fail-closed and that must not weaken; analysis results are never deleted or rewritten; env vars only work if wired through `docker-compose.yml`, which has bitten before; the evaluation dataset must stay interpretable across the switch.

## Goals / Non-Goals

**Goals:**
- One place, editable at runtime, for everything that defines a match.
- A compatibility score that is reproducible, explainable, and tunable without an LLM.
- Zero verdict drift at migration.
- Every analysis attributable to the profile version that judged it.

**Non-Goals:**
- Per-identity profiles, semantic matching, learned weights, rewriting history (see proposal).

## Decisions

**1. Profile as one JSON document per version, not normalised tables.**
`match_profiles(id, version, is_active, profile_json, notes, created_at)`, validated by a Pydantic model. The profile is read whole, edited whole, and versioned whole, exactly like `agent_prompts`. Normalised interest tables would make versioning and restore a multi-table copy for no query benefit. *Alternative:* a YAML file in the repo. Rejected: not editable from the UI, no audit, needs a restart.

**2. Extract with the LLM, match and score in Python.**
The model is good at reading a post and listing what the author likes; it is poor at applying "if 2+ then 0.9" consistently. Moving the list out of the prompt also means changing interests never invalidates a prompt version or its evaluation metrics. *Alternative:* render the profile's interests into the prompt with a template placeholder. Rejected: keeps arithmetic in the model, makes every profile edit a de facto prompt change, and makes preview impossible without inference.

**3. Noisy-OR scoring with a base value.**
`score = 1 - (1 - base) × Π(1 - w_i)`. It rises with every additional match, saturates below 1, is order-independent, and one formula covers any number of interests. Seed values are chosen so the common cases land on the same side of both thresholds as today:

| Case | Today | Seeded (base 0.2, kink 0.63, hobby 0.21) |
|---|---|---|
| no match | 0.2 | 0.200 |
| one preferred kink | 0.7 (promotes) | 0.704 (promotes) |
| two preferred kinks | 0.9 | 0.890 |
| two hobbies, no kink | 0.5 (not demoted) | 0.501 (not demoted) |
| one hobby, no kink | 0.5 (not demoted) | 0.368 (demoted one tier) |

The last row is a deliberate, documented difference: a single generic hobby such as "reading" no longer holds a lead's tier. *Alternative:* a lookup table reproducing the tiers exactly. Rejected: does not generalise beyond the seeded lists.

**4. Matching in this change is exact on normalised labels and aliases.**
Lowercase, trim, collapse whitespace, strip punctuation, then whole-term or whole-word match against label and aliases. It is predictable and testable. Its known weakness (free-text variation) is the subject of `interest-normalization`, which plugs into the same `match_interests()` function.

**5. Profile resolution happens once per analysis, not per gate.**
`MatchProfileService.get_active()` is read at the start of an analysis and passed down (`evaluate_gates(dimension_results, profile)`, `derive_priority(..., profile)`, geocoder). This keeps gates pure functions, keeps a mid-analysis save from splitting one analysis across two versions, and gives the version to record. `UserConstraints.from_settings()` is removed so no path can silently fall back to env values.

**6. Seed once, then env is inert.**
Seeding runs at startup when the table is empty, inside a transaction guarded by a unique constraint on `version`, so two containers starting together cannot both seed. A startup log line reports env/profile differences to prevent the "I changed `.env` and nothing happened" confusion.

**7. Optional gates ship disabled.**
`author_age` and `deal_breaker` add real power but also push more posts to `needs_review` when inputs are unknown. Shipping them off keeps migration drift at zero; the preview shows the cost of turning them on before the user commits.

**8. Preview reuses the real functions.**
Preview loads stored dimension outputs, runs the same `match_interests`, `evaluate_gates`, and `derive_priority` with the candidate profile, and diffs against stored verdicts. No second implementation. Location is recomputed only when home point or radius changed, using the stored extracted location text and the offline geocoder.

**9. Prompt migration is a new version, not an overwrite.**
A new extract-only preferences prompt version is created and activated. If the user's active prompt was customised, its extraction guidance is preserved by only removing the preferred lists, the scoring block, and the three output fields; the migration logs a diff. Rolling back to an old prompt is harmless because the model's score is ignored.

**10. Evaluation continuity.**
`analysis_evaluations` snapshots gain the profile version. `compare_fields` for the preferences dimension drops `compatibility_score` and the `preferred_*_found` fields, which the agent no longer emits, and compares extracted lists only. The dashboard groups preferences agreement by "before / after match profile".

## Risks / Trade-offs

- [Verdict drift at migration] → golden test: a fixture set of stored dimension outputs is judged by old and new code and must produce identical recommendations, and identical tiers except the documented one-hobby case.
- [Exact matching misses variants, so scores drop versus an LLM that matched loosely] → seed aliases generously from the current prompt lists; preview quantifies the effect on recent analyses before activation; `interest-normalization` follows.
- [A bad profile edit silently changes what gets promoted] → validation, preview, version history, audit, profile version on every analysis, calibration report grouped by version.
- [Deal-breaker gate misread as content filtering] → it affects only the verdict; ingestion, storage, display, and search are untouched, stated in the spec and the UI copy.
- [Customised preferences prompt loses user edits] → migration edits rather than replaces, keeps the old version, logs the diff.
- [Env confusion] → startup difference log; docs updated; variables marked seed-only in `.env.example`.

## Migration Plan

1. Migration: `match_profiles`, `match_profile_version` columns. Additive.
2. Deploy code with seeding; verify version 1 equals current env and literals; run the golden test on production-shaped fixtures.
3. Activate the extract-only preferences prompt version.
4. Ship the settings page.
Rollback: revert the code and roll the preferences prompt back one version; the table and columns can stay unused.

## Open Questions

- Should unknown author age yield `unclear` (consistent with fail-closed) or `pass` when the `author_age` gate is on? Proposed: `unclear`, with the preview showing the resulting needs-review volume.
- Should a profile save offer to recompute `priority` and `compatibility_score` on active, uncontacted leads (not the recommendation, not the stored analysis)? Proposed: defer; decide after using preview for a while.
- Is a weight scale of three named levels (must-have, strong, nice) friendlier than a number? Proposed: store numbers, present three presets plus a custom value.
