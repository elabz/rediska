## Context

Today, the conversation page has two parallel search surfaces:

1. **Global / inbox search**: typing into the inbox `SearchBox` runs ES-backed `/conversations/search`, returns hits with `matching_message_id`, and a click lands on `/inbox/<conversationId>?m=<id>&q=<query>`. The conversation page reads `?q=` reactively and passes it down to `MessageBubble`, which wraps token matches in a yellow `<mark>`. This was just shipped under `inbox-search-jump-to-match`.
2. **Local / in-conversation search**: the `SearchBox` rendered above the message list maintains its own `searchQuery` state in `MessageList`. While set, `MessageList` computes a `filteredMessages` array (case-insensitive `body_text.includes(query)`) and renders only those messages. There is no in-bubble highlighting, no occurrence count, and no way to step between matches — only a "K of N messages match" footer.

So a user searching for the same word via the two paths gets two very different views: the global path keeps every message in place and visually marks matches, while the local path silently hides everything that doesn't match and gives no visual cue inside the surviving bubbles. The new accent color `#FF2056` is also a chance to unify the highlight look across both paths.

Constraints inherited from prior decisions:

- The conversation page already caps the initial load at 5000 messages (`useMessages.fetchAllMessages`); we will not introduce on-demand fetching to chase a match beyond the cap.
- Polling runs every 10 s (2 s in fast-poll). Highlights and counter must update if new messages arrive that contain the query, but should not yank the user's current match position or steal scroll while a match is being read.
- `MessageBubble` renders plain `body_text` inside a `<p whitespace-pre-wrap>`. No markdown rendering complicates the highlight injection.
- The recently-added URL-driven `highlightQuery` prop (passed from the orchestrator to `MessageList` to `MessageBubble`) becomes redundant once the local `SearchBox` is the single source of truth — we'll remove the reactive wiring and replace it with a one-shot initializer.

## Goals / Non-Goals

**Goals:**

- One visual / interaction model for both global and local conversation searches: highlight matches in place, count them, step through them.
- Accent the highlight color to `#FF2056` everywhere a match is rendered.
- Make arriving via `?q=` indistinguishable (for the user) from typing the query locally — the SearchBox is the unified state.
- Keep all existing `?m=<id>` deep-link behavior intact (pulse the targeted message; the `jumpFailed` fallback still applies).
- Zero new backend round-trips.

**Non-Goals:**

- Auto-fetching older history when prev/next would otherwise wrap past the loaded range. v1 wraps within the loaded set; users still use **Load more messages** explicitly to bring older matches into range.
- Two-way URL sync (auto-updating `?q=` as the user edits the SearchBox). Initial value only, per user preference.
- "Match-only view" toggle. Filter behavior is being removed, not made optional, to keep the UI compact and the model predictable.
- Highlighting matches inside attachments, image filenames, or counterpart usernames. Body-text only.
- Fuzzy matching inside the conversation. Local highlighting uses the same plain-substring, whitespace-tokenized, len-≥-2 rule as the existing global highlight helper, so behavior is consistent.

## Decisions

### Single source of truth: local SearchBox state

The `MessageList` already owns `searchQuery`. We promote it to drive everything: filtering goes away, highlighting reads it, the match counter reads it, prev/next reads it. The orchestrator no longer passes a reactive `highlightQuery` from `?q=` — it passes an `initialQuery` (one-shot, captured into the `MessageList`'s state initializer).

Alternative considered: lift `searchQuery` to the orchestrator and treat the URL as the canonical store via `router.replace({ q })`. Rejected — two-way URL sync is more state machinery for marginal benefit (the user explicitly chose pre-fill-only). Keeping the existing in-component state is also a smaller diff.

### Match indexing strategy

Computing the (messageId, charStart, charEnd) of every occurrence on every keystroke is fine at the scale we have (5000 messages cap, body text typically <2 KB each). We build a memoized `matches: Match[]` array in `MessageList` keyed by `[messages, searchQuery]`, where each `Match` is `{ messageId, occurrenceIndex }`. Total = `matches.length`. Each `MessageBubble` receives the subset of indices that target it plus an optional `activeMatchIndexWithinBubble` so it can apply a stronger style to the currently-targeted occurrence.

We render highlight markup via the existing `highlightMatches()` helper in `MessageBubble`, but enrich it to accept a per-bubble "current occurrence index" so the helper can apply a different `<mark>` class to just that one.

Alternative considered: render every match as a DOM-level data attribute and use `querySelectorAll` to walk them on prev/next. Rejected — couples imperative DOM lookup with React's render cycle and is fragile when messages re-render on poll.

### Prev/Next, scroll, and the active-match emphasis

`MessageList` exposes `scrollToMatch(globalIndex: number): boolean` via `useImperativeHandle`. The `SearchBox` `Prev` / `Next` buttons compute the new global index (wrapping at the ends), pass it to `scrollToMatch`, and update the displayed `K of M`. The handle behaves like `scrollToMessage` already does: `requestAnimationFrame` + `scrollIntoView({ block: 'center', behavior: 'smooth' })`, plus setting `activeMatchIndex` state so the bubble can render that single occurrence with a stronger style for ~1.5 s before reverting to the standard highlight.

Keyboard shortcuts (Enter / Shift+Enter inside the SearchBox advancing through matches) are a nice-to-have follow-up but not in scope here. Out of scope for v1 to keep the surface area focused.

### Highlight color: `#FF2056`

We will use the literal hex as a Tailwind arbitrary class: `bg-[#FF2056]/85 text-white rounded px-0.5`. For the "currently active" match, we go fully opaque: `bg-[#FF2056] text-white ring-2 ring-[#FF2056]/40`. Both modes render legibly on the message bubble's gray/primary backgrounds — verified by mental contrast check; will confirm visually post-build.

Alternative considered: register `#FF2056` as a Tailwind theme color (`accent-search` etc.). Rejected for v1 — one-off color, two usages, not worth the config churn.

### `useEffect` shape for `?q=` pre-fill

`MessageList`'s `useState('')` becomes `useState(() => initialQuery ?? '')`. This is a lazy initializer; it runs once on mount and never again, satisfying the "pre-fill only, no rewrite" requirement without needing a `useEffect`. The orchestrator reads `?q=` from `useSearchParams` and passes it as `initialQuery`. The orchestrator also drops the reactive `highlightQuery` prop pass-through.

Alternative considered: `useEffect(() => setSearchQuery(initialQuery), [])`. Rejected — lazy initializer is the idiomatic React way; an effect creates a one-frame "empty SearchBox" flash before the URL value is applied.

### Removing the filter behavior

`MessageList` currently does `filteredMessages = messages.filter(...)`. We remove that derivation; the rendering loop iterates `messages` directly. The "no messages match your search" empty-state branch is replaced by a "0 of 0 matches" rendering in the counter while the message list keeps rendering messages.

We also drop the `filteredCount` / `totalCount` props from `SearchBox` in favor of `currentMatch`, `totalMatches`, `onPrev`, `onNext`. This is a small, internal API rename — only `MessageList` consumes `SearchBox`.

### Polling interaction

When a poll merges in new messages, the memoized `matches` array recomputes. We preserve `currentMatchIndex` if it still points to a real match; otherwise we clamp it to `Math.min(currentMatchIndex, totalMatches - 1)` or 0 when no matches remain. We do NOT auto-scroll on poll — the user only moves when they click prev/next. This avoids the "you read a match, then a poll shifts your scroll" anti-pattern.

## Risks / Trade-offs

- **Performance on very long conversations (~5000 messages)**: building the match array on every keystroke walks all message bodies. Mitigation: the work is per-keystroke and trivially memoizable on `[messages, searchQuery]`; substring searching 5000 × ~1 KB strings in JS is sub-millisecond on modern hardware. If profiling shows otherwise, we can debounce the query (e.g., 100 ms) — but we don't preemptively do so.
- **`#FF2056` contrast on outgoing bubbles (which use `bg-primary`)**: the primary color in the project's default theme is a saturated brand color; `#FF2056` may clash. Mitigation: post-build visual check; if it reads poorly we can switch to an outline-style highlight (`ring`) on outgoing bubbles only, leaving the fill for incoming.
- **Breaking the "show only matching messages" muscle memory**: users relying on the old filter mode to triage long conversations lose that. Mitigation: the counter and prev/next collectively replace the use case (jump from match to match instead of skim a filtered list); ship a brief release note.
- **Match position drift during polling**: if a new incoming message contains a match that orders before the user's current match, the global index of the user's current match shifts. Mitigation: track the active match by `(messageId, occurrenceIndex)` rather than by global index, recompute the global index after each recomputation; if the active match is gone (message deleted), fall back to the closest preceding match or 0.
- **`?q=` pre-fill with an empty string**: a malformed URL like `?q=` (empty value) would initialize the SearchBox to `''`. That's the same as having no `?q=` at all — acceptable.

## Migration Plan

Single PR, frontend-only. No backend changes, no API contract changes, no env vars. Deploy by rebuilding `rediska-web` and recreating the container.

Rollback: revert the PR. The local SearchBox returns to filter mode; the global highlight feature (yellow `<mark>`s driven by `?q=`) still works because its plumbing is independent in the `MessageBubble` helper.

## Open Questions

- Should `Enter` / `Shift+Enter` inside the SearchBox advance through matches like a browser? Default for v1: no — only click on the chevrons. Easy follow-up.
- Should we scroll *all* matches into a visible "stripe" overlay (like VS Code minimap), or just rely on prev/next? Default: prev/next is sufficient for the requested use case; minimap is a larger UI investment.
- Should we surface the same counter UI when the user arrives via `?q=` but never edits the SearchBox? Yes — because the URL pre-fills the SearchBox to the same non-empty value, the same counter renders.
