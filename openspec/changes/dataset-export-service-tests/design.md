## Context

`export_dataset` in `api/routes/conversation.py` (lines ~516–660) queries conversations (filters: `identity_id`, `test_only` via `[TEST]%` external id, `list_id`), then per conversation queries messages (not deleted, no `send_error`, non-empty body, visibility `visible`/`unknown`), groups by `thread_external_id` when any message has one (threads ordered by first message, unthreaded last), maps `out`→`assistant` / `in`→`user` (skipping `system`), merges consecutive same-role turns with a blank line, inserts a `[conversation initiated]` user turn when the first turn is the assistant's, drops trailing user turns, requires at least one turn of each role, prepends the system prompt, and emits `{"conversations": [...]}` per line. It writes an `AuditLog` row (`dataset.export`) and returns the whole file. No test references it.

## Goals / Non-Goals

**Goals:** identical behaviour, provable; logic reachable from unit tests without HTTP or a database where possible.

**Non-Goals:** any improvement.

## Decisions

**1. Characterisation tests before the move.** Written against the route first (integration, SQLite fixtures with synthetic conversations), then the extraction is done under them. *Alternative:* extract then test — rejected, it cannot show equivalence.

**2. Pure functions over dataclasses, not ORM rows.** `ExportMessage(direction, body, sent_at, thread_id, id)`; the query layer converts rows. Ordering, mapping, merging and trimming become table-driven unit tests with no DB.

**3. One orchestrator returning an iterator of lines.** The route joins it today; `dataset-export-streaming` will stream it. Returning an iterator now costs nothing and avoids a second refactor.

**4. Keep questionable behaviour and name it.** Tests for the placeholder and for `max_tokens` having no effect are marked with a comment pointing at the follow-up change that will replace them, so the intent to change is visible and the diff in the follow-up is small.

## Risks / Trade-offs

- [Subtle ordering difference after extraction] → byte-for-byte comparison of output on a multi-thread synthetic fixture.
- [SQLite vs MySQL ordering of equal timestamps] → fixtures use distinct `sent_at`; tie-break by id is asserted explicitly.
