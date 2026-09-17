# Inbox Backup & Restore

Export the inbox to a portable JSON dump, restore from one, or clear the inbox.

UI: **`/ops/backup`** (linked from the Operations page).
API prefix: `/inbox`. All endpoints require an authenticated session.

---

## 1. What is in scope

"Inbox" means **conversations, conversation list memberships, messages, and
message-linked attachments**.

Identities and external accounts are *included in the dump* so that an import can
rebuild foreign keys, but a clear never deletes them — lead posts, profile
snapshots, and profile items reference the same accounts.

| Entity | Exported | Deleted by clear |
|---|---|---|
| `conversations` | yes | yes |
| `messages` | yes | yes |
| `attachments` (message-linked) | metadata only | row only, file kept |
| `conversation_list_members` | yes | yes |
| `conversation_lists` (definitions) | yes | no — labels survive |
| `identities`, `external_accounts` | yes | no |
| `providers`, `provider_credentials` | no | no |
| `lead_posts`, `profile_*`, `agent_prompts` | no | no |

Two consequences worth being explicit about:

- **Attachment file content is never embedded.** The dump carries `storage_key`,
  `sha256`, `mime_type`, and dimensions. The files themselves stay under
  `ATTACHMENTS_PATH`.
- **Clear does not delete attachment files.** That is what makes clear reversible:
  a dump taken beforehand restores working references, because the bytes never
  left the disk.

---

## 2. Dump format

```jsonc
{
  "format": "rediska.inbox",
  "version": 1,
  "exported_at": "2026-07-20T18:04:11.482391+00:00",
  "counts": { "conversations": 12, "messages": 480, "attachments": 31, "...": 0 },

  "identities":        [ { "provider_id": "reddit", "external_username": "...", "..." } ],
  "external_accounts": [ { "provider_id": "reddit", "external_username": "...", "..." } ],
  "conversations":     [ { "provider_id": "reddit",
                           "external_conversation_id": "abc123",
                           "counterpart_username": "someone",
                           "identity_username": "my_account", "..." } ],
  "conversation_lists":        [ { "name": "Followups", "..." } ],
  "conversation_list_members": [ { "list_name": "Followups",
                                   "conversation_key": "reddit:abc123", "..." } ],
  "messages":    [ { "dump_key": "t4_xyz", "conversation_key": "reddit:abc123", "..." } ],
  "attachments": [ { "message_key": "t4_xyz", "storage_key": "ab/cd/file.png",
                     "file_present": true, "..." } ],

  "warnings": { "missing_files": [] }
}
```

Rows reference each other by **natural key, never by database row id**, so a dump
restores cleanly into an instance whose auto-increment counters differ:

- conversation → `"{provider_id}:{external_conversation_id}"`
- message → `external_message_id` when present; otherwise a SHA-256 fingerprint of
  `(conversation key, sent_at, direction, body)`. Unsent drafts have no external id,
  and this fingerprint is what makes duplicate detection work for them.
- attachment → its parent message's key plus `sha256`.

---

## 3. API

### `POST /inbox/export`

Queue an export. Returns `202`.

```bash
curl -sS -b "session=$SESSION" -X POST https://rediska.local/api/core/inbox/export \
  -H 'Content-Type: application/json' -d '{}'
```

```json
{ "job_id": "5b1e...", "status": "queued", "message": "Export job queued. ..." }
```

Optional body field `filename` overrides the default timestamped name. Any
directory component is stripped.

### `GET /inbox/exports`

List available dumps, newest first.

```json
{ "exports": [ { "filename": "inbox_2026-07-20_180411.json",
                 "size_bytes": 2481022,
                 "created_at": "2026-07-20T18:04:11+00:00" } ] }
```

### `GET /inbox/exports/{filename}`

Download a dump. Filenames containing a path separator are rejected with `400`,
and the resolved path is verified to stay inside the export directory.

```bash
curl -sS -b "session=$SESSION" -OJ \
  https://rediska.local/api/core/inbox/exports/inbox_2026-07-20_180411.json
```

### `POST /inbox/import`

Upload a dump (`multipart/form-data`, field `file`) and queue a restore.

```bash
curl -sS -b "session=$SESSION" -X POST https://rediska.local/api/core/inbox/import \
  -F "file=@inbox_2026-07-20_180411.json"
```

The dump is **validated synchronously** before the job is queued, so a malformed
file comes back as `400` immediately rather than failing later in the background:

```json
{ "detail": "Invalid dump file: Unrecognized dump format 'something-else'; expected 'rediska.inbox'" }
```

### `POST /inbox/clear`

Destructive. Requires the exact confirmation phrase.

```bash
curl -sS -b "session=$SESSION" -X POST https://rediska.local/api/core/inbox/clear \
  -H 'Content-Type: application/json' \
  -d '{"confirmation": "CLEAR MY INBOX"}'
```

Anything other than `CLEAR MY INBOX` returns `400` and is written to `audit_log`
with `result="error"`.

### `GET /inbox/jobs/{job_id}`

Poll any of the three operations.

```json
{ "job_id": "5b1e...", "status": "running", "stage": "messages",
  "done": 240, "total": 480, "percent": 50.0 }
```

`status` is one of `pending`, `running`, `completed`, `failed`. On completion the
task's summary is returned under `result`.

---

## 4. Typical flows

**Back up before a risky bulk operation**

```bash
JOB=$(curl -sS -b "session=$SESSION" -X POST .../inbox/export \
        -H 'Content-Type: application/json' -d '{}' | jq -r .job_id)

# poll until completed
until [ "$(curl -sS -b "session=$SESSION" .../inbox/jobs/$JOB | jq -r .status)" = completed ]; do
  sleep 2
done

curl -sS -b "session=$SESSION" .../inbox/exports | jq -r '.exports[0].filename'
```

**Reset and restore**

1. `POST /inbox/export` → wait for `completed` → download the dump.
2. `POST /inbox/clear` with the confirmation phrase.
3. `POST /inbox/import` with the dump from step 1.

Because attachment files are never deleted, step 3 restores working image
references.

**Re-running an import is safe.** Existing conversations and messages are detected
by natural key and skipped, so importing the same dump twice does not duplicate
anything.

---

## 5. Operational notes

- **Queue**: all three tasks run on the dedicated `transfer` Celery queue
  (`inbox.export`, `inbox.import`, `inbox.clear`), so a long export does not sit
  behind the nightly maintenance backups. The queue is in the worker's `-Q` list in
  `services/worker/Dockerfile` — adding it required a worker image rebuild.
- **Time limits**: export and import override the global 5/10-minute Celery limits
  with 60/65 minutes.
- **Retries**: export retries twice. Import and clear use `max_retries=0` — silently
  re-running a destructive or destructive-adjacent operation is worse than
  surfacing the failure.
- **Atomicity**: import runs in a single transaction. A failure rolls back
  everything, including conversations created earlier in the same run.
- **Storage**: dumps live in `$BACKUPS_PATH/inbox-exports/`, uploads stage in
  `$BACKUPS_PATH/inbox-exports/incoming/`. Both `rediska-core` and `rediska-worker`
  mount `BACKUPS_PATH`, which is what lets core serve a file the worker wrote.
- **Audit**: `inbox.export.trigger`, `inbox.import.trigger`, and
  `inbox.clear.trigger` are written by the API; the clear service writes its own
  `inbox.clear` entry with the deletion counts.

## 6. Missing-file warnings

Both export and import report referenced attachment files that are absent from
disk, under `warnings.missing_files`. Neither operation fails because of them —
export still records the metadata, and import still restores the messages. The UI
surfaces the count; `/ops` → "Redownload missing attachments" can refill them.
