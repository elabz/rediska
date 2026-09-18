## ADDED Requirements

### Requirement: Dataset export samples respect the sequence length
No sample emitted by the dataset export SHALL exceed `max_tokens` as measured by the export's token estimator, including the system prompt and any opening post. Parameter `overflow` SHALL control conversations that exceed it: `split` (default) SHALL emit consecutive windows cut at turn boundaries, each starting with `system` then `user` and ending with `assistant`, with `overlap_turns` preceding turns repeated for context and a shortened opening post carried into later windows; `truncate` SHALL emit only the first window; `skip` SHALL omit the conversation. A single `user` turn larger than the budget SHALL be truncated at a paragraph or sentence boundary with a visible marker; an `assistant` turn SHALL never be truncated — the exchange containing it SHALL be left out instead. The default estimator SHALL be a conservative character ratio; when `TOKENIZE_URL` is configured the export SHALL use the local tokenizer endpoint and fall back to the estimator on failure. The audit entry and response SHALL report conversations exported, samples emitted, samples split, turns truncated, conversations skipped, the longest sample, and the estimator used.

#### Scenario: Long conversation is split
- **WHEN** a conversation of about 10,000 estimated tokens is exported with `max_tokens=4096`
- **THEN** several samples are emitted, none above 4096 estimated tokens, each ending with an assistant turn

#### Scenario: Oversize reply from the user
- **WHEN** one assistant turn alone exceeds the budget
- **THEN** that exchange is left out and no emitted sample contains a cut assistant turn

#### Scenario: Parameter has an effect
- **WHEN** the same data is exported with `max_tokens=2048` and with `max_tokens=8192`
- **THEN** the first export has more, shorter samples than the second

#### Scenario: Tokenizer endpoint down
- **WHEN** `TOKENIZE_URL` is configured but unreachable
- **THEN** the export completes using the character estimator and reports that it did
