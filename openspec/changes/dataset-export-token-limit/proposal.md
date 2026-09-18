## Why

The export accepts `max_tokens` (default 4096, described as a "max sequence length hint") and never reads it. Samples of any length are written out, so the trainer silently truncates them at its own sequence length — cutting mid-turn, usually removing the end of the conversation, and leaving samples that no longer end with an assistant turn. A parameter that does nothing is also a trap: it reads as a guarantee.

## What Changes

- **`max_tokens` is enforced.** No emitted sample exceeds it, measured by a token estimator.
- **Long conversations are split, not lost.** Default `overflow=split`: a conversation over the limit becomes several samples cut at turn boundaries, each valid on its own (system, then user…assistant), with a configurable overlap of preceding turns for context. Alternatives: `truncate` (keep the first window only) and `skip`.
- **The opening context travels with every window.** When the sample begins with a linked post (`dataset-export-intro-context`), later windows carry a shortened form of it so the model still knows what the conversation is about.
- **One oversize turn cannot break the rule.** A single turn longer than the budget is truncated at a sentence or paragraph boundary with a visible marker counted in the report; a sample whose assistant turn would be truncated is dropped instead, because a half message is a bad target.
- **Estimation is explicit.** Default estimator is characters ÷ 3.5 (conservative for English on Llama-family tokenizers). An exact mode asks the local llama.cpp server's `/tokenize` endpoint when `TOKENIZE_URL` is configured. The estimator used is recorded.
- **The export reports it.** Counts of samples split, truncated, skipped, plus the longest sample, in the audit entry, response headers and the dialog. The dialog gets a sequence-length field (it has none today).

## Non-goals

- No bundled tokenizer library or model files in the core image.
- No cloud tokenizer service.
- No packing of multiple conversations into one sequence (a trainer concern).
- No summarising of overflow.

## Capabilities

### New Capabilities

### Modified Capabilities
- `inbox-conversations`: adds the sequence-length guarantee and overflow behaviour of the dataset export.

## Impact

- **Core**: `dataset_export.py` gains `estimate_tokens`, `window_sample`; route gains `overflow`, `overlap_turns`; optional `TOKENIZE_URL` in config, `.env.example` and compose blocks.
- **Web**: dialog fields for sequence length and overflow mode, result counts.
- **Depends on**: `dataset-export-service-tests`. Works with or without `dataset-export-intro-context`.
- **Behaviour change**: long conversations now yield several lines; line count is no longer equal to conversation count (the audit entry reports both).
