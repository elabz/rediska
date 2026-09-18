## 1. Estimation

- [ ] 1.1 `estimate_tokens()` character-ratio estimator with the 0.95 margin
- [ ] 1.2 Optional exact mode via llama.cpp `/tokenize` (batched, timeout, fallback); `TOKENIZE_URL` in config, `.env.example`, compose blocks

## 2. Windowing

- [ ] 2.1 `window_sample()`: split at turn boundaries, overlap, windows start on `user` and end on `assistant`
- [ ] 2.2 Oversize user turn truncation at paragraph/sentence boundary with marker; oversize assistant exchange dropped
- [ ] 2.3 Shortened opening post for later windows
- [ ] 2.4 `overflow` = `split` | `truncate` | `skip`; counters

## 3. API and UI

- [ ] 3.1 Route parameters `overflow`, `overlap_turns`; validation of `max_tokens` range; counts in audit and headers
- [ ] 3.2 Dialog: sequence length, overflow mode, result counts

## 4. Tests

- [ ] 4.1 Replace the "max_tokens has no effect" characterisation test
- [ ] 4.2 Property-style test: for random synthetic conversations every sample is within budget and satisfies the output contract
- [ ] 4.3 Edge cases: single huge user turn, single huge assistant turn, overlap 0, budget smaller than system prompt (rejected with 422)
