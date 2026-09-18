## Context

`max_tokens: int = Query(4096, …)` is declared and unused. First messages average 683 characters and conversations can run to hundreds of turns; an 8B model fine-tuned with Unsloth at 4096 tokens will truncate anything longer on the right.

## Goals / Non-Goals

**Goals:** a hard upper bound per sample; keep the training value of long conversations; every emitted sample still satisfies the output contract.

**Non-Goals:** exact token counts without a tokenizer; sequence packing.

## Decisions

**1. Split at turn boundaries with overlap.** Walk the turns accumulating estimated tokens (system prompt and opening context included); when the next user+assistant pair would exceed the budget, close the window after the last assistant turn and start the next one `overlap_turns` (default 2) earlier, beginning on a `user` turn. *Alternatives:* truncate only — wastes the later, often best, part of long conversations; skip — wastes all of it.

**2. Character-ratio estimator by default.** 3.5 chars/token underestimates capacity slightly, which is the safe direction. Exact mode calls llama.cpp `/tokenize` directly (LiteLLM does not proxy it), batched, local network only; any failure falls back to the estimator and says so in the report. *Alternative:* add `tokenizers`/`transformers` to the image — heavy, and needs model files that live on the GPU host.

**3. Never truncate a target.** Truncating a `user` turn loses context; truncating an `assistant` turn teaches the model to stop mid-thought. Oversize user turn → truncate at the last paragraph/sentence boundary under budget, append ` […]`. Oversize assistant turn → the pair is dropped and the window closes before it.

**4. Opening context in later windows.** First window: full post. Later windows: header + title + first 400 characters + ` […]`. Counted in the budget.

**5. Safety margin.** Effective budget = `max_tokens` × 0.95 to absorb chat-template tokens the trainer adds.

## Risks / Trade-offs

- [Estimator wrong for non-English or emoji-heavy text] → conservative ratio, margin, exact mode available, longest-sample figure reported so the user can check against the trainer's own count.
- [Overlap duplicates text across samples] → small default, configurable to 0.
- [Line count changes confuse] → audit and dialog report conversations and samples separately.
