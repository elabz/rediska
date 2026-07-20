## Why

Users composing a message in the conversation view can lose all typed content if they accidentally trigger browser back-navigation — trivial to do on an Apple Magic Mouse (two-finger horizontal swipe) or via the back button on other mice. There is currently no recovery: the in-memory `messageText` state is destroyed when the page unmounts, and nothing is persisted.

## What Changes

- Persist the in-progress message draft for each conversation to `localStorage` while the user is typing.
- Restore the draft into the compose box automatically when the user returns to the same conversation.
- Clear the persisted draft when the message is successfully posted (status from the POST `/messages` endpoint is non-error), scoped to that conversation only — other conversations' drafts remain untouched.
- Do not clear the draft on transient send errors; the user must be able to retry without losing text.
- Scope storage per `conversationId` using a stable key prefix so drafts cannot bleed between conversations.

## Capabilities

### New Capabilities
- `message-drafts`: Client-side persistence of in-progress message text per conversation, with restore-on-return and clear-on-send semantics.

### Modified Capabilities
<!-- None — no existing spec-level behavior changes. -->

## Impact

- **Code**: `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` (compose box state and `sendMessage` handler).
- **APIs**: None — purely client-side persistence; no backend changes.
- **Storage**: New `localStorage` keys under the namespace `rediska:draft:conversation:<conversationId>`.
- **Privacy**: Drafts live in the browser's `localStorage` and are not synced anywhere; they remain visible to anyone with access to the same browser profile until cleared.
