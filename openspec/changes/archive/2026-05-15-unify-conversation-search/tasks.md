## 1. SearchBox: counter + prev/next controls

- [x] 1.1 In `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/SearchBox.tsx`, replace the `filteredCount`/`totalCount` props with `currentMatch: number` (1-indexed), `totalMatches: number`, `onPrev: () => void`, `onNext: () => void`. Keep `value`/`onChange` unchanged.
- [x] 1.2 Replace the "X of N messages match" footer with an inline group rendered on the same row as the input: `K of M matches` text plus two icon buttons (ChevronUp/ChevronDown from `lucide-react`) for Prev/Next.
- [x] 1.3 Hide the counter and the prev/next group entirely when `value` is empty. When `totalMatches === 0` and `value` is non-empty, render "0 of 0" and disable both buttons.
- [x] 1.4 Use `aria-label="Previous match"` / `aria-label="Next match"` on the buttons. Buttons are `type="button"` so they don't submit forms.

## 2. MessageList: match computation + active state + scrollToMatch

- [x] 2.1 In `MessageList.tsx`, remove the `filteredMessages` derivation and any code that switched to a "no messages match your search" empty state. The rendering loop iterates `messages` directly.
- [x] 2.2 Change the `searchQuery` state initializer to a lazy form: `useState<string>(() => initialQuery ?? '')`. Add `initialQuery?: string | null` to `MessageListProps`.
- [x] 2.3 Add a memoized `matches: { messageId: number; occurrenceIndex: number }[]` derived from `[messages, searchQuery]`. The match-finding logic reuses the same tokenization rule as the existing `highlightMatches` helper (lower-cased, whitespace-split, deduped, len ≥ 2 tokens; regex with escaped alternation). (Tokenizer extracted to `_utils/searchTokens.ts` and shared with `MessageBubble`.)
- [x] 2.4 Add `currentMatchIndex: number | null` state (global index into `matches`). When `matches` recomputes, preserve the active match by `(messageId, occurrenceIndex)` if still present; clamp to a valid index otherwise; reset to `0` when the query transitions from empty to non-empty with at least one match; set to `null` when `matches.length === 0`. (Stored as `activeMatch: { messageId, occurrenceIndex } | null`; the index is derived via `useMemo`. Empty → non-empty transition auto-scrolls; poll-induced re-alignment does not.)
- [x] 2.5 Extend `MessageListHandle` with `scrollToMatch(index: number): boolean`. Implementation: resolve the match's `messageId` via the `matches` array, look up the existing per-message ref map, and reuse the same `requestAnimationFrame` + `scrollIntoView({ block: 'center', behavior: 'smooth' })` flow as `scrollToMessage`. Returns `false` if the index is out of range or the bubble's ref is missing.
- [x] 2.6 Wire `onPrev`/`onNext` handlers that decrement/increment `currentMatchIndex` with wrap-around and call `scrollToMatch` for the new index. `onPrev` from index 0 wraps to `totalMatches - 1`; `onNext` from `totalMatches - 1` wraps to 0.
- [x] 2.7 Pass the recomputed `currentMatch = currentMatchIndex + 1` (or 0 when null) and `totalMatches` into `<SearchBox>`. Pass the handlers.

## 3. MessageBubble: highlight color + active-match emphasis

- [x] 3.1 In `MessageBubble.tsx`, change the highlight class inside `highlightMatches()` from the yellow Tailwind utilities to `bg-[#FF2056]/85 text-white rounded px-0.5`.
- [x] 3.2 Extend `highlightMatches()` to accept an optional `activeOccurrence: number | null` parameter (zero-indexed, counted across the matches *within the same bubble*). When the n-th rendered `<mark>` equals `activeOccurrence`, render it with the stronger `bg-[#FF2056] text-white ring-2 ring-[#FF2056]/40` class instead of the default highlight class.
- [x] 3.3 Add an `activeOccurrenceInBubble?: number | null` prop to `MessageBubble` and forward it to `highlightMatches()` for the two call sites (system text and body text).

## 4. Orchestrator: pre-fill from `?q=`; drop reactive `highlightQuery`

- [x] 4.1 In `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx`, remove the `highlightQuery` constant and stop passing `highlightQuery` to `<MessageList>`.
- [x] 4.2 Read `?q=` via `useSearchParams` once at the top of the component (no useRef needed — the value is only forwarded as `initialQuery`, never read again).
- [x] 4.3 Pass `initialQuery={qParam ?? null}` to `<MessageList>`. Keep `?m=` parsing/jumping logic unchanged.

## 5. Wire active-match prop through MessageList → MessageBubble

- [x] 5.1 In `MessageList`, when iterating messages, compute the per-bubble active occurrence: if `currentMatchIndex` is not null AND `matches[currentMatchIndex].messageId === msg.id`, derive the within-bubble occurrence by counting how many matches with this same `messageId` precede `currentMatchIndex` in the `matches` array. Otherwise pass `null`. (Implemented via the `activeOccurrenceByMessageId` derivation in the render loop, using the per-bubble `occurrenceIndex` already stored on each `MatchPosition`.)
- [x] 5.2 Pass `activeOccurrenceInBubble={...}` to each `MessageBubble`. Also pass `highlightQuery={searchQuery}` (replacing the old `highlightQuery` plumbing from the orchestrator).

## 6. Build, lint, type-check

- [x] 6.1 `cd apps/web && npx tsc --noEmit` clean.
- [x] 6.2 `cd apps/web && npm run lint` clean.
- [x] 6.3 `cd apps/web && npm run build` clean.

## 7. Manual regression verification (user)

- [x] 7.1 Open a conversation and type a phrase into the in-conversation `SearchBox`: all messages stay visible, every occurrence is highlighted in `#FF2056`, the counter reads "1 of N", and the first match is centered and emphasized.
- [x] 7.2 Click **Next** repeatedly: the active match advances each click, the page scrolls to it, the counter updates, and after the last match it wraps to 1.
- [x] 7.3 Click **Prev** repeatedly: the active match steps backward with wrap-around to N.
- [x] 7.4 Clear the `SearchBox`: highlights, counter, and prev/next disappear; all messages remain rendered.
- [x] 7.5 Land via inbox global search (`/inbox/<id>?m=<id>&q=<query>`): the SearchBox is pre-filled with `<query>`, highlights and counter render immediately, the `?m=` deep-link target is the active match.
- [x] 7.6 Edit the SearchBox after the pre-fill: highlights update, counter updates, the URL's `?q=` value does NOT change.
- [x] 7.7 Refresh the same URL: behavior matches 7.5 (cold load uses URL value).
- [x] 7.8 Query that produces zero matches: counter renders "0 of 0", prev/next are disabled, no message is emphasized.
- [x] 7.9 With fast-poll active (send a message and watch the poll tick): if an incoming message brings new matches into the conversation, the counter total grows and existing highlights stay in place; the user's active match position is NOT yanked.
- [x] 7.10 Verify `#FF2056` highlights are legible on both outgoing (primary-colored) and incoming (muted-colored) bubbles in both light and dark mode.
