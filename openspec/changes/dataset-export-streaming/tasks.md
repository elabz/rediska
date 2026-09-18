## 1. Query layer

- [ ] 1.1 Keyset-paged conversation ids honouring all filters
- [ ] 1.2 One message query per page, grouped by conversation; page size constant with a test override
- [ ] 1.3 Byte-for-byte equivalence test against the unbatched output on the synthetic multi-thread fixture; query-count assertion

## 2. Streaming and audit

- [ ] 2.1 Generator with its own session; `StreamingResponse` over it; media type and filename unchanged
- [ ] 2.2 Completion audit (`ok` / `aborted` / `error`) in `finally`; tests for each, including session closure on abort
- [ ] 2.3 `GET /conversations/export-dataset/last` and `/preview` (declared before `/{conversation_id}`)

## 3. Web

- [ ] 3.1 Proxy passes `response.body` through; Vitest asserts no `.text()` buffering on success
- [ ] 3.2 Proxies for `last` and `preview`
- [ ] 3.3 Dialog: preview line, final counts, failure state when the last export is not `ok`

## 4. Verify

- [ ] 4.1 Memory check on a large synthetic fixture (e.g. 5,000 conversations): peak RSS does not scale with dataset size
