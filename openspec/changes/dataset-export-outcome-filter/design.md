## Context

Measured 2026-09-18 by aggregate query: 1,052 user-opened conversations, 368 with at least one reply (35%). `external_accounts.engagement_state` (`not_engaged` / `engaged`) is maintained by the app. `do_not_contact` exists (empty today). Conversation lists are the only existing curation mechanism and remain available as `list_id`.

## Goals / Non-Goals

**Goals:** let the dataset favour conversations that worked, using facts already stored; give trainers the label; change nothing unless asked.

**Non-Goals:** quality scoring, content-based selection.

## Decisions

**1. Four ordered outcomes from counts and one state field.** Cheap, explainable, stable. `sustained` exists because "replied once with 'no thanks'" and "talked for weeks" are different teachers. *Alternative:* a continuous score — harder to explain and to filter on.

**2. Outcome is computed after message validity filtering.** A reply that was later deleted locally does not count; this keeps the label consistent with what is actually in the sample.

**3. Default unchanged, recommendation in the UI.** The user asked for the capability, not for their old exports to change. The dialog preselects nothing but labels `replied` as recommended and shows the counts each choice would produce.

**4. Repetition as the weighting mechanism.** JSONL has no weights; duplicating lines is what trainers do anyway. Capped at 5 to avoid memorisation; applied after windowing so long conversations are not multiplied twice over.

**5. `meta` beside `conversations`.** Additive key; loaders that select the `conversations` column ignore it, which is to be confirmed against the training script in use; `include_meta=false` removes it for strict consumers.

**6. One shared outcome function.** `voice-matched-replies` stores `no_reply / replied / engaged` on exemplars; both use `conversation_outcome()` so the two never disagree.

**7. Banned counterparts excluded by default.** This is the one default that changes output, and only once bans exist; it is reported in the counts and can be turned off.

## Risks / Trade-offs

- [Survivorship bias: training only on what worked narrows the voice] → default stays `any`; `replied` is a recommendation; `meta` lets the trainer decide.
- [Engagement state is set by hand and may lag] → `sustained` gives a purely mechanical alternative.
- [Small filtered datasets] → counts shown before export.
