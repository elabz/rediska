## Context

Today's flow:

1. User types in the inbox `SearchBox` → debounced → `GET /api/core/conversations/search?q=...`.
2. Backend `search_conversations` runs two ES passes (exact, then fuzzy) over the `message` doc type, then keeps the **best-scoring hit per conversation** in `exact_per_conv` / `fuzzy_per_conv`. Each hit carries `source.conversation_id` and `source.content`. The matching message id is in the ES doc id (and may also be in the source) but is **dropped** by `build_hit`, which only returns a 150-char snippet of `source.content`.
3. Frontend `ConversationItem` wraps the row in `<Link href={\`/inbox/${conversation.id}\`}>`.
4. The conversation page orchestrator (`page.tsx`) calls `messageListRef.current?.scrollToBottom()` 100 ms after the initial load completes. This produces the "lands at the very end" symptom the user reported.

Constraints:

- The conversation page already loads all messages up to a 5000-message safety cap via `useMessages.fetchAllMessages`. We do NOT need an extra "fetch the page that contains message N" round-trip in v1.
- The page polls every 10 s (or 2 s in fast-poll) and merges incoming messages; the jump-and-highlight must NOT replay on every poll tick.
- `MessageList` already owns the message-rendering loop, the search-filter state, and `messagesEndRef`. Adding per-message refs there is local; touching the orchestrator is also fine.
- The codebase pattern for cross-component imperative actions on `MessageList` is `forwardRef` + `useImperativeHandle` (already used for `scrollToBottom`). Stick with that.

## Goals / Non-Goals

**Goals:**
- One click in inbox search → conversation page opens scrolled to the matching message, with a brief visual cue.
- Zero new round-trips on the conversation page (reuse the existing initial fetch).
- Backend response change is purely additive — clients that ignore `matching_message_id` keep working.
- Falls back gracefully (scroll-to-bottom + small inline notice) if the matching id is not in the loaded set.

**Non-Goals:**
- "Jump to next match" / "highlight all matches" inside a conversation. The existing `SearchBox` inside `MessageList` already filters; deep-link is single-target.
- Walking pagination until the matching message is found (would require a `from-message-id` cursor parameter and is deferred to a follow-up).
- Persisting the jump target in the URL across reloads — the param is consumed once on mount and intentionally not re-applied on subsequent navigation.
- Highlighting / underlining the matching substring inside the message bubble. Out of scope; the snippet on the inbox row already shows the match context.

## Decisions

### Source of `matching_message_id`

Take it from the ES `_id` field of the best hit. The message indexer in `services/core/rediska_core/domain/services/indexing.py` uses the message id as the doc id (verified before implementation — task 1.1 confirms). If the source also carries `message_id`, prefer that for explicitness; otherwise parse the doc id. Decision recorded in tasks so the implementation step double-checks.

Alternative considered: re-query MySQL by `(conversation_id, content)` to find the matching message. Rejected — the snippet is truncated and could match multiple messages; the ES hit already knows exactly which message scored best.

### URL convention: `?m=<id>` query param

Use `?m=<messageId>` rather than the fragment `#m-<id>`.

- Next.js `useSearchParams` is the existing idiom in this route (`inbox/page.tsx:192` already uses it for `attachments`/`replies`/`identity`/`list` filters).
- Query params survive the existing `router.replace(... { scroll: false })` patterns and are easy to read in a `useEffect` on mount.
- Fragments would require either `window.location.hash` reads (ugly in Next.js client components) or a hash-router shim.
- Single-letter key `m` is intentional — search results are the only producer; the URL bar will frequently show this when a user shares a link, and `?m=12345` reads cleaner than `?messageId=12345`.

### Per-message refs in `MessageList`

Maintain a `Map<number, HTMLDivElement>` populated via `ref={(el) => { if (el) refs.set(id, el); else refs.delete(id); }}` on each `MessageBubble` wrapper. Expose `scrollToMessage(id: number): boolean` via `useImperativeHandle` (returns `true` if found, `false` if the id is unknown so the orchestrator can show the fallback notice).

Alternative considered: `document.querySelector(\`[data-message-id="${id}"]\`)`. Works but couples to DOM attributes that don't otherwise exist; the ref map is more idiomatic React and equally cheap.

### Suppressing the default scroll-to-bottom

The orchestrator's `setTimeout(() => messageListRef.current?.scrollToBottom(), 100)` runs once when `loading` flips false. Make it conditional: if the URL has `?m=<id>`, call `scrollToMessage(id)` instead; if `scrollToMessage` returns `false`, fall through to `scrollToBottom()` and set a transient `jumpFailed` flag that renders a small inline notice in the message-list area.

The `m` param is read once into a `useRef` on mount (`initialJumpId.current = m`) and cleared after the first attempt. This guarantees polls and sends do not re-trigger the jump.

### Highlight pulse

Add a CSS class `bg-primary/15 transition-colors duration-1000` on the targeted bubble for ~1.5 s, then remove. Implemented in `MessageList` state: `highlightedId: number | null`, set by `scrollToMessage`, cleared by a `setTimeout`. No new dependencies.

Alternative considered: framer-motion / a one-shot animation library. Rejected — single transient effect, plain Tailwind is enough.

### Fallback notice

When `scrollToMessage` returns `false`, the orchestrator sets a one-shot state `jumpFailed: true`. `MessageList` renders a dismissible inline banner above the message list:

> *"Could not jump to the matching message — it may be older than the loaded range. Use **Load more messages** to fetch earlier history."*

The banner auto-clears after the next user-initiated action (search, scroll, send) or on dismiss. Out of scope: actively walking the load-more cursor on the user's behalf.

## Risks / Trade-offs

- **ES doc id vs source message id mismatch** → Mitigation: task 1.1 explicitly verifies the indexer's id strategy before populating the response, and prefers `source.message_id` if present.
- **Initial-load cap (5000 msgs)** means the matching message can be missing from the rendered set for very long conversations → Mitigation: graceful fallback notice + scroll-to-bottom; explicit non-goal to fetch on demand.
- **Ref map memory** for very long conversations (~5000 entries) → negligible; refs are removed on unmount and the map is per-mount.
- **Highlight after scroll behavior** when the page is still doing image layout (avatars, attachments) — `scrollIntoView({ block: 'center' })` may be slightly off if heights settle later → Mitigation: trigger inside a `requestAnimationFrame` after the messages render, then highlight; if still misaligned in practice, add a single follow-up `scrollIntoView` after a short delay.
- **Polling clobber**: if a poll merges in messages while the user is reading, we don't want to re-jump → Mitigation: `initialJumpId` is consumed on first apply; polls cannot re-trigger.

## Migration Plan

Single PR, three files touched on the frontend, two on the backend. Deploy in either order — the backend field is additive, and the frontend tolerates `matching_message_id == null` (just renders today's link). No data migration. No env changes.

Rollback: revert the PR; the conversation page returns to its pre-change scroll-to-bottom behavior; the additive backend field is harmless if left in place.

## Open Questions

- Should the highlight stay on while the user scrolls away (until first interaction), or auto-clear on a timer? Default: timer (~1.5 s). Trivial to flip if the user prefers persistent.
- Should the inbox row also link directly to a search-results-filtered view of the conversation (i.e. pre-fill the in-conversation `SearchBox` with the same query)? Out of scope — easy to layer on later by adding `?q=<query>` alongside `?m=<id>`.
