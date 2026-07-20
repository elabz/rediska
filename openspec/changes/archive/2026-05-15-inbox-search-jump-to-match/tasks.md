## 1. Backend: surface the matching message id

- [x] 1.1 Read `services/core/rediska_core/domain/services/indexing.py` to confirm what value is used as the ES `_id` for message documents and whether `message_id` is also written into `_source`. Pick the canonical field (`source.message_id` if present, else `_id`) and note the choice in the implementation comment.
- [x] 1.2 Add `matching_message_id: Optional[int] = None` to `ConversationSearchHit` in `services/core/rediska_core/api/schemas/conversation.py`.
- [x] 1.3 In `services/core/rediska_core/api/routes/conversation.py` `build_hit`, extract the message id from the chosen field on the ES hit; coerce to `int`; pass it to the `ConversationSearchHit` constructor. If extraction fails, leave it `None`.
- [x] 1.4 Add/extend a backend test for `/conversations/search` that asserts `matching_message_id` is populated for a normal hit and is `None` when the ES hit lacks the field.

## 2. Frontend: deep-link from the inbox row

- [x] 2.1 Extend the `SearchConversation` type in `apps/web/src/app/(authenticated)/inbox/page.tsx` with `matching_message_id?: number | null`.
- [x] 2.2 In `ConversationItem`, when rendered in search mode and `matching_message_id` is a positive integer, change the `<Link>` href to `\`/inbox/${conversation.id}?m=${matching_message_id}\``. Keep the plain `/inbox/${conversation.id}` href in all other cases.
- [x] 2.3 Build clean (`npm run build` from `apps/web/`) and lint clean (`npm run lint`).

## 3. MessageList: scroll-to-message + highlight + fallback notice

- [x] 3.1 In `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/MessageList.tsx`, add `messageRefs = useRef(new Map<number, HTMLDivElement>())` and attach `ref={(el) => { if (el) messageRefs.current.set(msg.id, el); else messageRefs.current.delete(msg.id); }}` to a wrapping `<div>` around each `MessageBubble` (don't change `MessageBubble`'s own DOM).
- [x] 3.2 Add `highlightedId: number | null` state. Render the wrapping div with a conditional class `bg-primary/15 transition-colors duration-1000 rounded-md` when `msg.id === highlightedId`.
- [x] 3.3 Extend `MessageListHandle` with `scrollToMessage(id: number): boolean`. Implementation: look up the ref; if missing, return `false`. Otherwise call `requestAnimationFrame(() => el.scrollIntoView({ block: 'center', behavior: 'smooth' }))`, set `highlightedId = id`, schedule `setTimeout(() => setHighlightedId(null), 1500)`, return `true`.
- [x] 3.4 Add a `jumpFailed: boolean` prop and (when true) render a dismissible inline notice above the message list: "Could not jump to the matching message — it may be older than the loaded range. Use **Load more messages** to fetch earlier history." Provide an `onDismissJumpFailed` callback prop. The notice also auto-clears the next time `searchQuery` changes or `loadOlder` is invoked.

## 4. Conversation page orchestrator: wire the param

- [x] 4.1 In `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx`, read `?m=` via `useSearchParams`. Parse to a positive integer or treat as absent.
- [x] 4.2 Capture the parsed id once into `const initialJumpId = useRef<number | null>(parsedM)` so polls/sends cannot re-trigger it.
- [x] 4.3 Replace the existing post-load `setTimeout(() => messageListRef.current?.scrollToBottom(), 100)` with: if `initialJumpId.current` is a number, call `messageListRef.current?.scrollToMessage(initialJumpId.current)`; if it returns `false`, set local state `jumpFailed = true` and fall through to `scrollToBottom()`. If `initialJumpId.current` is null, behave as today (scroll to bottom). Set `initialJumpId.current = null` after the attempt.
- [x] 4.4 Pass `jumpFailed` and an `onDismissJumpFailed` setter into `MessageList`.
- [x] 4.5 Confirm that re-renders triggered by `useMessages` polling do NOT cause the jump to repeat. Manual: open with `?m=`, wait 15s, observe no second scroll. (Verified by code inspection: post-load effect depends on `[loading]` only — polling mutates `messages`/poll-state, not `loading`; `initialJumpId.current` is also nulled after the first attempt, so re-firing would be a no-op anyway.)

## 5. Build, lint, type-check

- [x] 5.1 `cd apps/web && npx tsc --noEmit` clean.
- [x] 5.2 `cd apps/web && npm run lint` clean.
- [x] 5.3 `cd apps/web && npm run build` clean.
- [x] 5.4 `cd services/core && pytest tests/ -k "search" -q` passes (including the new assertion from 1.4). (3 new tests pass; the 22 teardown errors and 2 failures are pre-existing — verified by re-running on a clean tree via `git stash`.)

## 6. Manual regression verification

- [x] 6.1 Search for a phrase known to match a message in the middle of a long conversation; click the result; matching message is centered and pulses; URL shows `?m=<id>`.
- [x] 6.2 Refresh the same URL; jump still works on cold load.
- [x] 6.3 Click a result whose match lies before the 5000-cap (use a very long conversation); fallback notice appears and the page scrolls to the bottom; clicking **Load more messages** until the matching range is loaded does not re-trigger the jump.
- [x] 6.4 Manually craft `?m=999999999` (non-existent id); fallback notice appears; no console error.
- [x] 6.5 Manually craft `?m=abc` (unparseable); page behaves identically to no `m` param; no notice.
- [x] 6.6 Open a conversation without `?m`; verify behavior is unchanged from today (scroll to bottom on load, scroll to bottom on send).
- [x] 6.7 Send a message and let fast-poll run while a successful jump is on screen; the highlighted bubble does not re-pulse and the scroll position is not reset.
