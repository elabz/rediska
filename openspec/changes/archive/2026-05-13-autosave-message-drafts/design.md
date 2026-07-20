## Context

The conversation detail page at `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` keeps the in-progress message in a `useState` hook (`messageText`). The state lives only in memory; any unmount — including accidental browser back-navigation (very easy to trigger via two-finger swipe on an Apple Magic Mouse or the side button on most other mice) — destroys it without recovery.

The user has reported losing fully-typed messages this way. There is no backend draft API and v1 of Rediska is local-first, so persistence belongs in the browser. `localStorage` is the natural fit: synchronous, per-origin, survives reloads and tab close.

Relevant code references:
- `messageText` state declaration: `inbox/[conversationId]/page.tsx:389`
- Textarea bound to state: `inbox/[conversationId]/page.tsx:1452-1464`
- Success branch where `setMessageText('')` runs today: `inbox/[conversationId]/page.tsx:642-643`

## Goals / Non-Goals

**Goals:**
- Preserve the in-progress message text across page unmounts/navigations for a given conversation.
- Restore the draft seamlessly when the user returns to the same conversation.
- Clear the draft exactly when (and only when) the message is successfully sent, scoped to that conversation.
- Add no backend coupling — purely client-side.

**Non-Goals:**
- Cross-device/cross-browser sync of drafts (drafts are local to the browser profile, by design — matches v1 local-first principle).
- Persisting uploaded `attachmentIds`. Attachments already live on the server (uploaded via `POST /attachments`), but their IDs in client state would still be lost on unmount. Tracked as an open question; out of scope for this change unless the user opts in.
- Multiple named drafts per conversation, draft history, or undo of an autosave wipe.
- Server-side draft API.

## Decisions

### Storage backend: `localStorage` over `sessionStorage` or IndexedDB

- **Chosen**: `localStorage`.
- **Rationale**: Survives full tab close (sessionStorage does not — which would not protect against the back-button case if it triggers a tab restore). Synchronous API keeps restore logic trivial (no async hydration flicker). Quotas (~5MB per origin) are far beyond what a single text draft needs.
- **Alternatives**: `sessionStorage` — rejected because back-navigation that goes to a different origin then returns may clear the session for that tab; `IndexedDB` — overkill for a single string per conversation and would force async restore logic that introduces an empty-then-populated flash in the textarea.

### Key namespace: `rediska:draft:conversation:<conversationId>`

- **Chosen**: Single flat key per conversation, prefixed to avoid collisions with anything else the app may store.
- **Rationale**: `conversationId` from the URL params is already a stable identifier. Flat keys mean delete-on-send is one `removeItem` call.
- **Alternative considered**: One JSON-encoded object holding all drafts. Rejected because it forces read-modify-write on every keystroke and complicates the "clear only this conversation" semantic.

### Write strategy: debounced on change

- **Chosen**: Debounce writes by ~300–500ms after the last `onChange`.
- **Rationale**: A keystroke-per-write pattern is acceptable for `localStorage` performance, but debouncing reduces churn and produces a more sensible "last input" snapshot. The debounce window is short enough that any realistic accidental-navigation gesture lands after a flush.
- **Implementation**: A small `useEffect` keyed on `messageText` with a `setTimeout` that writes after the delay; cancelled on the next change. An alternative `useDebouncedCallback` hook from a library is unnecessary for one call site.
- **Edge case**: On unmount, fire one final synchronous write of the latest `messageText` (in the effect cleanup) so a back-press during the debounce window does not lose the last keystrokes.

### Restore strategy: lazy initializer in `useState`

- **Chosen**: Pass a lazy initializer to `useState(() => readDraft(conversationId) ?? '')` so the textarea hydrates with the stored value on the very first render. No post-mount flicker.
- **Rationale**: Reading `localStorage` is synchronous and cheap. Doing it inside the initializer avoids an empty-then-restored flash that a `useEffect`-based restore would cause.
- **SSR safeguard**: `typeof window === 'undefined'` short-circuits to `''` to support Next.js server rendering.

### Clear-on-success location

- **Chosen**: Inside `sendMessage`, on the success branch, right next to the existing `setMessageText('')` call (`page.tsx:642-643`). Same condition that already resets the in-memory state.
- **Rationale**: This is the single point where "send confirmed" is known. Putting clear logic anywhere else (e.g., on a status-change effect) risks clearing on transient states.

### Empty drafts are removed, not stored as `""`

- Storing an empty string is wasteful and makes a future "do I have a draft?" check harder. When `messageText.trim() === ''`, the writer calls `removeItem` instead of `setItem`.

### Error handling

- All `localStorage` access wrapped in `try/catch`. On failure: `console.warn` and continue. The compose box must never appear broken because `localStorage` is full or disabled.

## Risks / Trade-offs

- **Stale draft after long absence** → Mitigation: out of scope to expire automatically; the draft is overwritten by new typing and cleared by send. A future enhancement could add a "discard draft" affordance if users report confusion.
- **Privacy: draft visible to anyone sharing the browser profile** → Mitigation: documented in proposal. Matches existing v1 privacy posture (local-first, single-user). No new exposure beyond what session cookies already imply.
- **`localStorage` quota exhaustion** → Mitigation: write errors are swallowed; user can still type and send. Each draft is small (kilobytes), so practical exhaustion would require thousands of drafts.
- **Multiple tabs of the same conversation** → Both tabs write to the same key; last-write-wins. Acceptable: this is consistent with how users would expect a shared draft to behave, and the "storage" event could be wired up later if cross-tab sync becomes desirable.
- **Attachment IDs not persisted** → A user who uploads files, then back-navigates and returns, will see their text but no attachments in state (the files remain on the server as orphans). Documented as a known limitation; a follow-up change can extend the schema to `{ text, attachmentIds }`.

## Migration Plan

No migration required — purely additive client-side behavior. Old conversations simply have no stored draft.

## Open Questions

- Should attachment IDs be persisted alongside the text? (Out of scope unless the user requests it; tracked in Risks above.)
- Should a small "Draft restored" hint appear briefly when a draft is loaded, or should restoration be silent? Default: silent, matching common email/chat client behavior.
