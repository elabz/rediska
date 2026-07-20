## Context

`autosave-message-drafts` introduced four helpers in `inbox/[conversationId]/page.tsx`: `draftKey`, `readDraft`, `writeDraft`, `clearDraft`. All operate on a plain `string`. The conversation page also tracks `attachmentIds: number[]` state (alongside `messageText`) for files the user has uploaded but not yet sent. That state is not persisted, so a back-press loses it.

The simplest fix — a parallel `localStorage` key for attachment IDs — would split a single logical "draft" across two keys, opening up consistency bugs (text saved, IDs not saved; clear races; partial restores). A single combined value is cleaner.

## Goals / Non-Goals

**Goals:**
- Restore the user's full in-progress message — text AND attachments — across accidental navigation.
- Maintain the existing single-key-per-conversation model so `clearDraft` stays a one-shot `removeItem`.
- Migrate legacy drafts (plain strings written by the previous version) without surfacing errors.

**Non-Goals:**
- Validating that restored attachment IDs still exist on the server before showing them. Invalid IDs are caught by the existing send error path; pre-validation would add a network round-trip per restore for negligible benefit.
- Persisting partially-uploaded attachments (the upload itself is in-flight when the page unmounts). The upload aborts; user must re-upload.
- Orphan-attachment cleanup on the server. That's a separate concern (`maintenance.*` worker territory) — out of scope here.

## Decisions

### Single JSON value under the existing key

- **Chosen**: `localStorage.setItem(draftKey, JSON.stringify({ text, attachmentIds }))`.
- **Rationale**: One read, one write, atomic clear. The key namespace is unchanged so no migration coordination is needed at the storage layer.
- **Alternative considered**: Separate key `rediska:draft:conversation:<id>:attachments`. Rejected — two keys means two failure modes per operation and a non-atomic clear (text could be wiped while IDs linger).

### Transparent legacy migration on read

- **Chosen**: `readDraft` attempts `JSON.parse`. On parse failure, OR on parsed result that is a string / lacks the expected shape, treat the raw `localStorage` value as `{ text: <raw string>, attachmentIds: [] }`. Do not rewrite immediately — let the next debounced write take care of it.
- **Rationale**: Zero-touch for the user. Legacy drafts written days/weeks ago still work.
- **Edge case**: If `JSON.parse` succeeds but returns something weird (number, null, array), fall back to the same legacy shape with `text: ''`.

### Empty-state semantics unchanged

- A draft is considered "empty" (and the `localStorage` entry is removed) when BOTH `text.trim() === ''` AND `attachmentIds.length === 0`. Keeps the existing "no empty drafts in storage" invariant.

### Restore order

- On mount, the lazy `useState` initializers for `messageText` and `attachmentIds` both read from the same parsed draft object. To avoid parsing twice, read once into a local variable in a memoized helper, or pass the parsed object into both initializers.
- **Implementation note**: simplest is to parse on first call and cache on `window.__rediska_draft_cache` for the lifetime of the page. Overkill. Just call `readDraft` twice; the second call hits a different state initializer but `JSON.parse` of a small string is cheap.

## Risks / Trade-offs

- **Legacy entries with malformed-looking JSON-like strings** (e.g., a user typed `{"foo": 1}` as their actual message) → parsed as JSON, returns an unexpected shape, fallback path treats it as `{ text: '', attachmentIds: [] }`, **losing the user's typed text**. Mitigation: when the parsed result is an object but does NOT have a `text` string field, treat the raw value as legacy text rather than as a structured draft. This handles the false-positive parse.
- **Schema evolution**: adding new fields later (e.g., `editingMessageId` for reply-to) needs another migration path. Mitigation: defensive read code already tolerates missing fields; new fields default to undefined.
- **Storage size**: each draft is still <5KB, attachment IDs are small ints. No quota concern.

## Open Questions

- Should the user see a small "Restored: 2 attachments, X seconds ago" hint on restore so they know the attachment chips aren't from a current session? Default: silent restore, same as text.
