## Context

The current `page.tsx` is a single client component containing:

- ~12 helpers and constants at module scope (time formatting, error explanations, draft helpers, initial calculator).
- `MessageBubble` and `MessagesSkeleton` components (~200 lines combined).
- `ConversationDetailPage` (~1300 lines) with ~30 `useState`/`useRef` calls, ~12 `useEffect` blocks, ~15 `useCallback` handlers, and the JSX for: header, profile panel, image gallery, posts panel, search box, message list, compose box, three confirmation dialogs.

State that genuinely interacts:
- Messages + polling + fast-polling: tightly coupled, lives together.
- Compose text + attachments + draft persistence + send: cohesive.
- Conversation lists membership + dropdown UI: cohesive.
- Per-message actions (delete, retry, remote-delete) flow from list → bubble → dialog.

State that does NOT meaningfully interact across features:
- Search query is independent of compose, polling, lists.
- Image gallery state is independent of everything except messages (read-only).
- Star state lives on `conversation.counterpart.is_starred`.

This natural cohesion suggests the boundary lines.

## Goals / Non-Goals

**Goals:**
- Reduce `page.tsx` to <300 lines of orchestration only.
- Each new module is < ~250 lines and owns a single feature.
- No behavior changes — same manual smoke test still passes after the refactor.
- Keep PR-able chunks: each extraction in its own commit, build green at every step.

**Non-Goals:**
- Adopting a state management library (Redux, Zustand, Jotai). `useState` + prop drilling is fine at this size.
- Migrating to React Server Components. The page is inherently client-side (polling, drafts, optimistic UI).
- Changing the data-fetching strategy (no SWR/React Query introduction).
- Fixing the `existingMap` pre-existing warning here — that's covered by `configure-eslint`.

## Decisions

### Folder layout

```
apps/web/src/app/(authenticated)/inbox/[conversationId]/
  page.tsx                          # orchestrator only
  _components/
    ConversationHeader.tsx          # avatar, star, lists, scrub, export, send-via-reddit
    MessageList.tsx                 # rendering loop, search filter, scroll, load-older
    MessageBubble.tsx               # single bubble (already exists in-file)
    MessagesSkeleton.tsx            # already exists in-file
    ImageGallery.tsx                # collapsible gallery
    SearchBox.tsx
    ListsDropdown.tsx
    ComposeBox.tsx                  # textarea, attachments, send, draft autosave
    DeleteMessageDialog.tsx
    RemoteDeleteDialog.tsx
    ScrubConversationDialog.tsx
  _hooks/
    useMessages.ts                  # initial fetch, polling, fast-poll, load-older
    useConversationLists.ts         # list fetch + membership toggling
  _utils/
    drafts.ts                       # draftKey/readDraft/writeDraft/clearDraft
    timeFormat.ts                   # normalizeUtc, formatMessageTime, getInitials
    sendErrors.ts                   # getSendErrorExplanation
```

Rationale: split by feature (cohesive UI + state + handlers), not by layer. Each module is independently understandable.

### State boundaries

- **ComposeBox** owns `messageText`, `attachmentIds`, `sending`, `sendError`, `uploadingAttachment`, `fileInputRef`. Receives `onSent` callback to trigger fast-polling in parent.
- **MessageList** owns `messagesContainerRef`, `messagesEndRef`, `searchQuery`, `galleryExpanded`. Receives messages via prop (from `useMessages` in parent).
- **ConversationHeader** owns `showListDropdown` and `newListName` (via `ListsDropdown` sub-component), `showBatchDeleteDialog`. Receives `conversation` + counts.
- **useMessages** hook returns `{ messages, loading, error, loadOlder, startFastPoll }`. Owns the polling timers and fast-poll lifecycle.
- **useConversationLists** hook returns `{ lists, memberOf, toggle, createAndAdd }`.
- **page.tsx** wires hooks together, owns the three dialogs' open/closed booleans (they cut across MessageList and ComposeBox).

### Refactor order

Extract leaves first, root last. Each commit must `npm run build` cleanly.

1. **Pure utilities** (no React, no state) — lowest risk, highest payoff for line-count reduction.
2. **Leaf components** with no shared state (`MessageBubble`, `MessagesSkeleton`).
3. **Self-contained features** (`ImageGallery`, `SearchBox`, `ListsDropdown` + `useConversationLists`).
4. **Feature clusters** (`MessageList` + `useMessages`).
5. **Largest cluster** (`ComposeBox`).
6. **Slim the orchestrator** — `page.tsx` becomes glue.

### Prop drilling vs Context

At most 2 levels deep. Prefer explicit props over Context. If a third level emerges, revisit; for now, props.

## Risks / Trade-offs

- **Regression risk during extraction**: the file is doing a lot, and the manual test surface is wide. Mitigation: extract leaves first, smoke-test after each, keep commits granular for easy bisect.
- **Scroll-to-bottom mechanism**: `messagesEndRef` is referenced in multiple places. Moving it into `MessageList` means `sendMessage` (now in `ComposeBox`) can no longer call `scrollToBottom` directly. Mitigation: lift the scroll trigger to a callback exposed via `forwardRef` on `MessageList`, or via a shared ref/state in the orchestrator.
- **Polling lifecycle coupling**: `pollMessages` reads `messages` state for `hasPendingMessages`. Moving polling into `useMessages` is straightforward, but the fast-poll-trigger-on-send signal needs a clean cross-component path. Plan: `useMessages` exposes `startFastPoll()`; `ComposeBox` calls a prop `onSent` provided by the parent; the parent forwards to `startFastPoll`.
- **Test coverage**: there is no automated test suite for this page. Refactor relies on manual verification. Mitigation: keep PR small (commit-per-extraction); user runs the smoke checklist after each.

## Migration Plan

One commit per extraction, in the order listed under "Refactor order". The orchestrator file remains importable from the same URL at every step. No data migration. No environment variable changes. No Docker-compose changes.

## Open Questions

- Should `_utils/` be promoted to `apps/web/src/lib/conversation/` so its helpers can be reused on the conversation export route or other places? Default: keep them private to this route until a second consumer appears.
- Are `getSendErrorExplanation` strings worth pulling into an i18n module? Out of scope.
