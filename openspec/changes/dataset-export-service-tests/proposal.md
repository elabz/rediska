## Why

The fine-tuning dataset export is about 140 lines of logic written directly inside the `GET /conversations/export-dataset` route handler, with no test anywhere. Message filtering, thread ordering, turn merging and role rules can only be exercised by calling the live endpoint against real private conversations, which is exactly what tests and AI coding agents must not do. Four behaviour fixes are queued behind it (`dataset-export-intro-context`, `-token-limit`, `-streaming`, `-outcome-filter`); none can be made safely until today's behaviour is pinned down.

## What Changes

- **Extract, do not change.** The route body moves into `domain/services/dataset_export.py` as small pure functions — select conversations, select valid messages, order by thread, map roles, merge consecutive turns, trim to a valid ChatML shape, serialise — plus one orchestrating function. The route keeps parameter parsing, the audit entry and the response.
- **Characterisation tests first.** Tests are written against the current behaviour, on synthetic `test_` conversations only, and must pass both before and after the extraction. They cover every rule the code implements today, including the ones later changes will alter (the `[conversation initiated]` placeholder, the unused `max_tokens`).
- **An output contract test.** Every emitted line is valid JSON with a `conversations` array that starts with `system`, alternates `user`/`assistant`, and ends with `assistant`.
- **Proxy and audit covered.** A Vitest test for the BFF proxy (auth, param forwarding, error passthrough) and a test that the export writes its `dataset.export` audit entry.

## Non-goals

- No behaviour change of any kind: same parameters, same output bytes for the same data, same audit entry.
- No fix for the placeholder, token limit, memory use or outcome weighting — those are the four follow-up changes.
- No test reads real inbox data; fixtures are synthetic.

## Capabilities

### New Capabilities

### Modified Capabilities
- `inbox-conversations`: adds the output-shape contract and the rule that export logic lives in a testable service covered by synthetic-data tests. Existing export behaviour is unchanged.

## Impact

- **Core**: new `domain/services/dataset_export.py`; `api/routes/conversation.py` `export_dataset` shrinks to a wrapper; new `tests/unit/test_dataset_export_unit.py` and an integration test.
- **Web**: new Vitest file for `api/core/conversations/export-dataset/route.ts`.
- **Order**: this change lands first; the four follow-ups build on the service and extend its tests.
