## Why

When the user wrote first, the dataset export invents a user turn reading `[conversation initiated]` so the sample can start with `user`. That applies to 1,052 of 1,214 conversations (87%). The first assistant turn in those samples is the user's intro — a message written in answer to a specific post — so the dataset teaches a model to produce a detailed, personal opening from a meaningless token, i.e. to make specifics up. For a model meant to write in the user's voice this is the most damaging sample in the file, and it is the majority of the file.

## What Changes

- **The opening turn is the post, when we know it.** For a conversation opened by the user, the export resolves the post the intro answered and uses it as the first user turn: a fixed header line (`[post by the other person in <location>]`), the title, a blank line, the body as stored. Sources, in order: the conversation's `origin_lead_id` post snapshot; a confirmed voice exemplar's post text; nothing else. Unconfirmed guesses are never used.
- **When the post is unknown, the intro is not trained on.** New parameter `unlinked_intro` with three values: `drop` (new default) removes the user's opening turn(s) so the sample starts at the counterpart's first message; a conversation that has nothing left is omitted; `skip` omits such conversations entirely; `placeholder` keeps today's behaviour for reproducing old datasets.
- **The export says what it did.** The audit entry and response headers carry counts: samples with a linked post, samples with the intro dropped, conversations omitted.
- **The dialog explains the choice.** The inbox export dialog gets the three-way option with a one-line explanation of each and shows the counts after export.

## Non-goals

- No guessing of posts at export time (same-author lead before the first message, fuzzy matching). Linking is a human-confirmed step owned by `voice-matched-replies`.
- No change to counterpart-first conversations.
- No rewriting, summarising or filtering of post text; it is exported verbatim.

## Capabilities

### New Capabilities

### Modified Capabilities
- `inbox-conversations`: adds the rule for how a user-opened conversation begins in the dataset.

## Impact

- **Core**: `dataset_export.py` gains `resolve_opening_post()` and the `unlinked_intro` handling; route gains the parameter; tests replace the placeholder characterisation test.
- **Web**: export dialog option + result counts; BFF proxy already forwards all params.
- **Depends on**: `dataset-export-service-tests`. Linked posts appear once `voice-matched-replies` adds `origin_lead_id` and confirmed exemplars; until then every user-opened conversation is "unlinked" and the default simply stops training on context-free intros. Column absence is tolerated.
- **Behaviour change**: default output differs from today (fewer/shorter samples). `unlinked_intro=placeholder` reproduces the old file.
