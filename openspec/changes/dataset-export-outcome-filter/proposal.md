## Why

The export treats every conversation as an equally good example of how to write. Of 1,052 conversations the user opened, 684 (65%) never got a reply: they consist of an intro that did not work. With the intro-context fix those contribute nothing or little, but the general problem remains — a one-line exchange that died, a conversation with a scammer, and a months-long engaged conversation all carry the same weight per turn, and the only selection tool is hand-built conversation lists.

## What Changes

- **An outcome per conversation, computed from stored state.** `no_reply` (the counterpart never wrote), `replied` (at least one incoming message), `sustained` (at least `N` exchanges, default 3 turns from each side), `engaged` (the account's `engagement_state` is `engaged`). Outcomes are ordered; each includes the ones below it.
- **`min_outcome` filter.** `any` (today's behaviour) | `replied` | `sustained` | `engaged`. Default stays `any` so existing workflows are unchanged; the dialog recommends `replied`.
- **Exclusions that are always wanted.** `exclude_banned` (default true) leaves out conversations whose counterpart is on the do-not-contact list, since a model should not learn from exchanges with scammers. `min_user_chars` drops conversations where the user's total text is below a floor.
- **Optional up-weighting without a trainer change.** `engaged_repeat` (default 1) writes conversations at outcome `engaged` that many times, the only weighting mechanism plain JSONL offers.
- **Outcome in the sample metadata.** Each line gains `"meta": {"outcome": …, "turns": …}` beside `conversations`, so a training script can filter or weight on its own. Loaders that read only the `conversations` column are unaffected; `include_meta=false` removes it.
- **Report.** Counts per outcome before and after filtering in the audit entry and the dialog.

## Non-goals

- No LLM judgement of conversation quality, and no sentiment analysis.
- No reading of message content to decide outcome beyond counting turns and characters.
- No hidden default change: `min_outcome=any` remains the default.
- No filtering by theme or content.

## Capabilities

### New Capabilities

### Modified Capabilities
- `inbox-conversations`: adds outcome classification, filters, optional repetition and per-sample metadata to the dataset export.

## Impact

- **Core**: `dataset_export.py` gains `conversation_outcome()` (shared with `voice-matched-replies`, which needs the same outcome for exemplars), filter handling, `meta`; route parameters; one batched query for counterpart state and ban status per page.
- **Web**: dialog controls with per-outcome counts from the preview endpoint when `dataset-export-streaming` is present.
- **Depends on**: `dataset-export-service-tests`. Uses the shared ban predicate from `contact-ban-list` when present, else the existing `do_not_contact` table directly.
