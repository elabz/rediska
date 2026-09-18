## Context

Current flow: `conv_query.all()` → per conversation `msg_query.all()` → `output_lines.append(...)` → `"\n".join(...)` → `io.BytesIO(content.encode())` → `StreamingResponse`. Proxy: `await response.text()` → `new NextResponse(body)`. Browser: `response.blob()`. The audit row is added before the response is built, inside the request session.

Scale today: 1,214 conversations, ~55k messages, a file of a few tens of MB. Not an emergency; the fix is cheap once the service exists and removes a cliff before the corpus or the windowing multiplies output.

## Goals / Non-Goals

**Goals:** memory bounded by page size in core and proxy; O(pages) queries; truthful audit; no behavioural difference in the file.

**Non-Goals:** async job, stored artefacts, resumable downloads.

## Decisions

**1. Page conversations by id, one message query per page.** `WHERE conversation_id IN (…200 ids…) ORDER BY conversation_id, sent_at, id`, grouped with `itertools.groupby`. Keyset paging (`id > last_id`) avoids offset scans. *Alternative:* a single join over everything with server-side cursor — PyMySQL buffers unless `SSCursor` is used, and one long transaction is worse than many short ones.

**2. Sync generator in a threadpool-backed `StreamingResponse`.** The service is synchronous SQLAlchemy; Starlette iterates sync generators in a worker thread, so the event loop is not blocked. The generator owns its own session (the request-scoped one may be closed once the handler returns).

**3. Audit at completion.** `try/finally` around the generator: on normal exhaustion write `ok` with counts; on `GeneratorExit` (client disconnect) write `aborted`; on exception write `error` and re-raise. One row per export, as now. *Alternative:* a start row and an end row — two rows per action is noise in an append-only log.

**4. Totals via a last-export endpoint, not trailers.** HTTP trailers are unreliable through proxies and unreadable from `fetch`. The dialog calls `/export-dataset/last` after the blob completes and shows the payload of the newest `dataset.export` audit row.

**5. Proxy passes the stream through.** `new NextResponse(response.body, { headers })`; error responses are still read as JSON because they are small.

**6. Browser still uses a blob.** Streaming to disk from the browser needs the File System Access API or a service worker; not worth it at tens of MB. The preview tells the user the size first.

## Risks / Trade-offs

- [Error after the 200 status is sent] → the file ends early; the audit row says `error`, the dialog compares the last-export result and shows a failure instead of success.
- [Generator session leaks] → session opened and closed inside the generator's `try/finally`; test asserts closure on abort.
- [Ordering differs from the unbatched version] → byte-for-byte test against the pre-change output on the multi-thread fixture.
