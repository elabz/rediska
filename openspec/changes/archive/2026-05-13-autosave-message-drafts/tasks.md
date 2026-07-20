## 1. Draft storage helpers

- [x] 1.1 In `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` (or a new sibling helper module if it grows past ~30 lines), add three pure helpers: `draftKey(conversationId)`, `readDraft(conversationId)`, `writeDraft(conversationId, value)`, `clearDraft(conversationId)`.
- [x] 1.2 Wrap every `localStorage` access in `try/catch`; on failure, log via `console.warn` and return a safe default. Guard with `typeof window === 'undefined'` for SSR.
- [x] 1.3 In `writeDraft`, treat any value whose `trim()` is empty as a signal to `removeItem` rather than `setItem`.

## 2. Restore on mount

- [x] 2.1 Change the `messageText` `useState` initialization at `page.tsx:389` to a lazy initializer that calls `readDraft(conversationId)` and falls back to `''`.
- [x] 2.2 Verify the textarea (`page.tsx:1452`) shows the restored value on first paint, with no flicker.

## 3. Persist while typing

- [x] 3.1 Add a `useEffect` keyed on `[messageText, conversationId]` that schedules `writeDraft(conversationId, messageText)` via `setTimeout` with a 400ms debounce.
- [x] 3.2 In the effect's cleanup, `clearTimeout` the pending write and call `writeDraft` synchronously with the latest value so unmount during the debounce window does not lose keystrokes.

## 4. Clear on successful send

- [x] 4.1 In `sendMessage` (`page.tsx:602`), immediately after the successful `setMessageText('')` call (around `page.tsx:642`), invoke `clearDraft(conversationId)`.
- [x] 4.2 Confirm no draft clearing happens on the error branch of `sendMessage` so failed sends preserve the draft for retry.

## 5. Manual verification (user-driven on live system)

> Browser automation against `rediska.local` is off-limits (live data). The
> rebuilt `rediska-web` container is up; the user verifies these scenarios.

- [x] 5.1 Type a multi-line message, trigger browser back (or two-finger swipe), return to the conversation: draft is restored.
- [x] 5.2 Type a draft in conversation A, navigate to conversation B: A's draft is gone from B's compose; navigate back: A's draft is still there.
- [x] 5.3 Type a draft and successfully send: `localStorage` key for that conversation is removed (verify in DevTools → Application → Local Storage).
- [x] 5.4 Type a draft, trigger a send error (e.g., disconnect network or send to a deleted user): draft remains in `localStorage` and in the textarea after refresh.
- [x] 5.5 In a private-browsing window where `localStorage` is restricted, confirm the compose box still accepts input and sends without surfacing errors.
- [x] 5.6 Type, clear the textarea to whitespace only, refresh: textarea is empty and no stale `localStorage` entry remains.

## 6. Type-check and lint

- [x] 6.1 Run `npm run lint` from `apps/web/` and resolve any new findings. (Skipped — ESLint not configured in repo; `next lint` only offers an interactive setup wizard.)
- [x] 6.2 Run `npm run build` from `apps/web/` to confirm there are no TypeScript regressions.
