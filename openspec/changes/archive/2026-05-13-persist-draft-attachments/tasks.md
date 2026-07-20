## 1. Update draft helpers

- [x] 1.1 Change `readDraft(conversationId)` in `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` to return `{ text: string, attachmentIds: number[] }`. Try `JSON.parse`; if it fails OR the result is not an object with a `text` string field, return `{ text: <raw value>, attachmentIds: [] }` (legacy migration).
- [x] 1.2 Change `writeDraft(conversationId, value)` to accept the same object shape and persist `JSON.stringify(value)`. Treat "empty" as `value.text.trim() === '' && value.attachmentIds.length === 0` — call `removeItem` in that case.
- [x] 1.3 Leave `clearDraft` unchanged (it removes the whole key, which still works).

## 2. Wire restoration into the page

- [x] 2.1 Update the `messageText` lazy `useState` initializer to read from the structured draft (`readDraft(conversationId).text`).
- [x] 2.2 Update the `attachmentIds` `useState` initializer (currently `useState<number[]>([])`) to read from `readDraft(conversationId).attachmentIds`.
- [x] 2.3 Update the debounced persist `useEffect` to depend on `[conversationId, messageText, attachmentIds]` and write the structured value.
- [x] 2.4 Confirm `sendMessage` success branch still clears via `clearDraft(conversationId)` — no change needed.

## 3. Manual verification

- [x] 3.1 Upload an image, back-navigate, return: image attachment badge is restored along with text.
- [x] 3.2 Manually set a plain-string draft in `localStorage` via DevTools, reload: text restored, attachments empty, next keystroke upgrades the entry to structured JSON.
- [x] 3.3 Send successfully: `localStorage` key is removed.
- [x] 3.4 Send error: both text and attachments preserved in `localStorage`.

## 4. Build

- [x] 4.1 Run `npm run build` from `apps/web/` — clean.
