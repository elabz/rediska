## 1. Outcome

- [ ] 1.1 `conversation_outcome()` pure function over validity-filtered turns + engagement state; table-driven tests
- [ ] 1.2 Batched per-page lookup of counterpart engagement state and ban status (shared ban predicate when available)

## 2. Filters and output

- [ ] 2.1 `min_outcome`, `sustained_turns`, `exclude_banned`, `min_user_chars`, `engaged_repeat` (validated 1–5), `include_meta`
- [ ] 2.2 `meta` on each line; repetition applied after windowing
- [ ] 2.3 Per-outcome counts before/after filtering in the audit entry (and the summary/preview endpoints when present)

## 3. UI

- [ ] 3.1 Dialog controls with `replied` labelled recommended and live counts; empty-result state

## 4. Tests

- [ ] 4.1 Default export unchanged on the characterisation fixture
- [ ] 4.2 Each outcome level, banned exclusion, char floor, repetition, `include_meta=false`
- [ ] 4.3 Output contract test passes with `meta` present
