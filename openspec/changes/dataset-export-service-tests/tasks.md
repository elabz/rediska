## 1. Pin current behaviour

- [ ] 1.1 Synthetic fixture builder: conversations with threads, unthreaded messages, failed/deleted/empty/hidden messages, user-first and counterpart-first openings, `[TEST]` ids, list membership
- [ ] 1.2 Integration tests against the current route: filters, ordering, merging, placeholder, trailing-user trim, both-roles rule, system prompt, audit entry, filename
- [ ] 1.3 Output contract test (valid JSON per line, alternation, ends with assistant)

## 2. Extract

- [ ] 2.1 `domain/services/dataset_export.py`: `ExportMessage`, `select_conversations`, `valid_messages`, `thread_order`, `to_turns`, `merge_turns`, `shape_sample`, `export_lines` (iterator)
- [ ] 2.2 Route becomes a wrapper; byte-for-byte comparison on the multi-thread fixture
- [ ] 2.3 Table-driven unit tests for the pure functions; mark the placeholder and `max_tokens` tests with the follow-up change names

## 3. Web

- [ ] 3.1 Vitest for the BFF proxy: 401 without session, params forwarded, error passthrough, content-disposition preserved

## 4. Verify

- [ ] 4.1 Core suite green in Docker; web lint clean
