## Why

Searching from the inbox returns one result per conversation with a snippet of the matching message, but clicking the result lands the user at the **bottom** of the conversation — not at the message they searched for. With long conversations (hundreds or thousands of messages), the user then has to scroll up and re-find the snippet manually. The matching message id is already known on the server (it's the ES hit) and is the obvious thing to deep-link to.

## What Changes

- Backend `/conversations/search` includes `matching_message_id` in each `ConversationSearchHit` (the id of the best-scoring message that produced the snippet).
- Inbox-list search results link to `/inbox/<conversationId>?m=<messageId>` instead of `/inbox/<conversationId>`.
- Conversation detail page reads the `m` query param. When present and non-empty, after the initial message load it scrolls the matching message into view (centered) and applies a brief highlight pulse — instead of running the default scroll-to-bottom.
- If the matching message id is not found in the loaded message set (e.g. it sits beyond the 5000-message safety cap or was deleted between search and click), the page falls back to scroll-to-bottom and shows a small inline "Could not jump to message" notice. No error toast, no retry loop.
- The `m` param is consumed once per mount: subsequent normal navigation, polling, and sends do not re-trigger the jump.

## Capabilities

### New Capabilities
- `inbox-search`: behavior of the inbox-level search box, the `/conversations/search` API contract, and the deep-link handoff from a search result into the conversation detail page.

### Modified Capabilities
<!-- None — `inbox-search` is being introduced as a new capability rather than amending an existing one. The conversation detail page's existing scroll-to-bottom-on-mount is implementation; no spec covers it today. -->

## Impact

- **Code**:
  - `services/core/rediska_core/api/schemas/conversation.py` — add `matching_message_id` to `ConversationSearchHit`.
  - `services/core/rediska_core/api/routes/conversation.py` — populate it from the ES hit's `source.message_id` (or doc id) in `build_hit`.
  - `apps/web/src/app/(authenticated)/inbox/page.tsx` — extend `SearchConversation` type and the `<Link>` href in `ConversationItem`.
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` — read `?m=`, suppress default scroll-to-bottom on first load when present, hand off to `MessageList`.
  - `apps/web/src/app/(authenticated)/inbox/[conversationId]/_components/MessageList.tsx` — expose a `scrollToMessage(id)` imperative method, render a `data-message-id` (or attach a per-id ref), and play the highlight pulse.
- **APIs**: Additive only. Response gains an optional `matching_message_id: int | null`. Existing clients ignore it.
- **Dependencies**: None added.
- **Storage**: None.
- **Privacy**: None new — the message id is already returned indirectly via the snippet.
- **Known limitation**: If the matching message lies above the initial-load safety cap (5000 messages), no automatic "load until found" walk is added in v1; the inline notice points the user at the existing **Load more messages** button.
