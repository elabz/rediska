## Why

The export loads every conversation, runs one message query per conversation (1,214 today, over 55,000 messages), builds the entire JSONL file as a Python list, joins it into one string, encodes it, and wraps it in a `StreamingResponse` that therefore streams nothing. The Next.js proxy then reads the whole body into a string before answering, and the browser holds it a third time as a blob. It works at today's size; it grows linearly in three processes at once, ties up an API worker for the whole run, and gives the user no progress and no way to cancel.

## What Changes

- **Batched reads.** Conversations are paged by id; messages for a page are fetched in one ordered query and grouped in memory. Query count drops from one per conversation to one per page (default 200 conversations).
- **Real streaming, end to end.** The service yields lines as it produces them; the route streams them; the BFF proxy pipes the upstream body through instead of buffering it. Peak memory is bounded by one page of conversations, not by the dataset.
- **Audit that reflects what happened.** Because counts are only known at the end, the `dataset.export` audit entry is written when the stream finishes, from its own database session, with result `ok`, `aborted` (client went away) or `error`, and the counts reached.
- **Counts without headers.** Headers are sent before the body, so totals move to a final summary available from `GET /conversations/export-dataset/last` (the audit entry's payload), which the dialog reads after the download completes.
- **A size preview.** `GET /conversations/export-dataset/preview` returns, for the chosen filters, the number of conversations and messages that would be exported, from two count queries, so the dialog can show what is about to happen.

## Non-goals

- No move to a background job with a stored file: the export stays a direct download, and no dataset file is left on disk.
- No compression, no pagination of the output, no caching.
- No change to what is exported; output is byte-identical to the non-streaming version for the same parameters.

## Capabilities

### New Capabilities

### Modified Capabilities
- `inbox-conversations`: adds bounded-memory streaming, completion-time auditing and the preview for the dataset export.

## Impact

- **Core**: `dataset_export.py` query layer (paged conversations, one message query per page, `yield_per`); route returns a generator-backed `StreamingResponse`; completion audit in a `finally` block with a fresh session; two small endpoints.
- **Web**: `api/core/conversations/export-dataset/route.ts` returns `new NextResponse(upstream.body, …)`; two new proxies; dialog shows the preview and the final counts.
- **Depends on**: `dataset-export-service-tests` (the orchestrator already returns an iterator). Independent of the other three follow-ups; if they land first, their header counts move into the summary here.
