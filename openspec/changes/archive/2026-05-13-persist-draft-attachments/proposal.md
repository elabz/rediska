## Why

The recently-shipped `autosave-message-drafts` (archived 2026-05-13) preserves draft text across accidental back-navigation, but it does not preserve the list of `attachmentIds` that the user has uploaded for the same draft. Result: a user who uploads images, accidentally navigates back, and returns sees their text restored but no attachments — and the uploaded files are now orphans on the server with no UI to recover them.

## What Changes

- Extend the `localStorage` draft schema for each conversation from a plain string to a JSON object `{ text: string, attachmentIds: number[] }`.
- Restore both `messageText` and `attachmentIds` from the persisted draft when the conversation view mounts.
- Clear both fields on successful send (same single-key removal already in place).
- **BREAKING (transparent)**: existing legacy entries stored as plain strings are migrated on read — treated as `{ text: <raw value>, attachmentIds: [] }` and rewritten in the new shape on the next persist.

## Capabilities

### New Capabilities
<!-- None — this is an extension of an existing capability. -->

### Modified Capabilities
- `message-drafts`: add requirements for persisting and restoring attachment IDs alongside draft text, and for transparent migration of legacy plain-string entries.

## Impact

- **Code**: `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` — draft helpers and the state hooks that read/write them.
- **APIs**: None.
- **Storage**: `localStorage` value shape changes from `string` to JSON-encoded object under the existing key prefix `rediska:draft:conversation:<conversationId>`. Migration is silent on first read.
- **Privacy**: No new exposure. Attachment IDs are server-issued integers, not files themselves; they're already in the conversation history once sent.
- **Known limitation**: An attachment ID restored from `localStorage` may point to a file that has since been deleted on the server. Surfaced at send time by the existing error path; no additional validation is added in v1.
