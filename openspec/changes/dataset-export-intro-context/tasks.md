## 1. Service

- [ ] 1.1 `resolve_opening_post(conversation)`: origin snapshot, then confirmed exemplar; tolerate missing columns/tables; batched per export, not per conversation
- [ ] 1.2 `unlinked_intro` handling in `shape_sample` (`drop` default, `skip`, `placeholder`); re-apply shape rules after dropping
- [ ] 1.3 Header formatting function; no username in the header
- [ ] 1.4 Counters returned by the orchestrator

## 2. API and UI

- [ ] 2.1 Route parameter with validation; counts in the audit entry and in response headers
- [ ] 2.2 Export dialog: three-way option with explanations; show counts after export

## 3. Tests

- [ ] 3.1 Replace the placeholder characterisation test: linked post, drop, drop-leaves-nothing, skip, placeholder, counterpart-first unchanged
- [ ] 3.2 Output contract test still passes for every mode
- [ ] 3.3 Vitest for the dialog option
