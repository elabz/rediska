## Context

`shape_sample` (after `dataset-export-service-tests`) inserts `{"role": "user", "content": "[conversation initiated]"}` whenever the first merged turn is the assistant's. 1,052 of 1,214 conversations start that way; only 192 of those intros can currently be paired with stored post text, and none of those pairs is human-confirmed yet.

## Goals / Non-Goals

**Goals:** never train an intro without its referent; use the real post when it is known; keep old datasets reproducible.

**Non-Goals:** discovering links; changing anything after the opening.

## Decisions

**1. Default `drop`, not `placeholder` and not `skip`.** Dropping the opening assistant turn keeps the rest of the conversation — the back-and-forth, which is most of the voice signal — and removes only the part that teaches invention. `skip` would discard 87% of conversations. `placeholder` stays available because someone may need to regenerate an earlier dataset. *Alternative:* keep the intro but mask it from the loss — that is a trainer feature, not expressible in ChatML JSONL.

**2. After dropping, re-apply the shape rules.** Removing the leading assistant turn leaves a sample starting with `user`; the existing trailing-trim and both-roles rules then decide whether anything is left. A conversation where the counterpart never replied yields nothing, which is correct: it contained only the intro.

**3. Only confirmed links.** Sources: `conversations.origin_post_snapshot` (written at initiate-from-lead, certain by construction) and `voice_exemplars` with `mark=exemplar` and post text (confirmed by the user). The resolver checks for the columns/tables and returns nothing when they do not exist, so this change can ship before `voice-matched-replies`.

**4. Fixed, recognisable header.** `[post by the other person in <location>]` on its own line lets a trainer or a later prompt reproduce the same framing at inference time. No username in the header: the dataset should not teach the model to address people by handle.

**5. Post length is bounded by the token-limit change, not here.** This change emits the full post; `dataset-export-token-limit` owns truncation rules so there is one place for them.

## Risks / Trade-offs

- [Users of the old default get a different file] → parameter restores it; dialog explains; counts shown.
- [Few linked posts at first] → expected; the value today is the `drop` default, the linked-post path starts paying as links accumulate.
