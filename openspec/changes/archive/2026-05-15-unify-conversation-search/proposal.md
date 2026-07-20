## Why

The in-conversation search box (top of a conversation) and the global inbox search currently behave inconsistently: a hit from the global search highlights matches inside every bubble (with the new `?q=` deep-link), but typing the same phrase into the in-conversation search box only **filters** which messages are visible — it does not highlight matches inside the surviving bubbles, gives no count of how many matches were actually found, and offers no way to step from one match to the next. Users entering through the two paths end up with two very different reading experiences for the same query, which is jarring and undercuts the global-search feature we just shipped.

## What Changes

- In-conversation `SearchBox` switches from **filter mode** to **highlight-only mode** (browser Cmd-F style): all messages remain rendered, matches are highlighted inline using the new accent color `#FF2056`. **BREAKING** (UX): the old "X of N messages match" filter behavior goes away.
- Add an inline **match counter** to the right of the search input: `current of total matches` (e.g. `3 of 47`). Counts total occurrences across all loaded messages, not message bubbles.
- Add inline **prev/next** controls (chevron-up / chevron-down) next to the counter that scroll the next/previous occurrence into view (centered) and pulse it briefly. Counter updates to reflect current position; wraps around at the ends.
- The conversation page reads `?q=<query>` once on mount and uses it to **pre-fill** the `SearchBox`. The local `SearchBox` state then becomes the single source of truth for highlighting; the URL is initial-value only and is not auto-updated as the user edits.
- The highlight color used by the global-search deep-link (currently a yellow `<mark>`) is updated to `#FF2056` for both light and dark themes, so the global and local paths render identically once the URL handoff completes.

## Capabilities

### New Capabilities
- `conversation-search`: the in-conversation `SearchBox` contract — what it filters or doesn't, how matches are counted, how the user navigates between them, and how it consumes `?q=` from the URL on entry.

### Modified Capabilities
<!-- None. `inbox-search` already specifies the URL handoff and is unchanged; only how the conversation page consumes `?q=` is changing, and that consumption is part of the new `conversation-search` capability. -->

## Impact

- **Code**:
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/SearchBox.tsx` — replace "filtered/total messages" footer with "current of total matches" + prev/next chevron buttons; accept `onPrev`/`onNext`/`currentIndex`/`totalMatches` props.
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/MessageList.tsx` — drop filter (`filteredMessages` use); compute per-message match offsets so the parent (or the `MessageList`) can navigate by index; expose `scrollToMatch(index)` via `MessageListHandle`; promote `searchQuery` to drive highlighting on every bubble; pre-fill `searchQuery` from `?q=` once on mount via initializer.
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/MessageBubble.tsx` — change highlight class from yellow to `bg-[#FF2056]/85 text-white` (or equivalent); accept an `activeMatchIndex` / `firstMatchIndex` prop so the bubble can mark *the* currently-targeted match with a stronger style.
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` — stop passing `highlightQuery` reactively from the URL; instead pass the initial `?q=` once into `MessageList` as `initialQuery`. (The `?m=` deep-link behavior is unchanged.)
- **APIs**: None. Pure frontend.
- **Dependencies**: None added.
- **Storage**: None.
- **Privacy**: None new.
- **Known limitations**:
  - Match navigation is bounded by what's loaded in the page (the existing 5000-message cap and the "Load more messages" pagination). If the user navigates past the last loaded match, prev/next wraps within the loaded set; we do NOT auto-fetch older history to chase a match. (Same fallback model as the existing `?m=` deep-link.)
  - The first-paint highlight when arriving via `?q=` depends on `useSearchParams` resolving on the client; this is already the case for `?m=`.
