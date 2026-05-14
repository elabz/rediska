## 1. Extract pure utilities

- [x] 1.1 Create `inbox/[conversationId]/_utils/timeFormat.ts` and move `normalizeUtc`, `formatMessageTime`, `getInitials` into it. Update imports in `page.tsx`.
- [x] 1.2 Create `inbox/[conversationId]/_utils/sendErrors.ts` and move `getSendErrorExplanation` into it.
- [x] 1.3 Create `inbox/[conversationId]/_utils/drafts.ts` and move `draftKey`, `readDraft`, `writeDraft`, `clearDraft` into it.
- [x] 1.4 Build clean.

## 2. Extract leaf components

- [x] 2.1 Move `MessageBubble` to `_components/MessageBubble.tsx`. Export the props interface. Import in `page.tsx`.
- [x] 2.2 Move `MessagesSkeleton` to `_components/MessagesSkeleton.tsx`.
- [x] 2.3 Build clean.

## 3. Extract self-contained features

- [x] 3.1 Extract `ImageGallery` (the collapsible gallery between the sticky header and the search box) to `_components/ImageGallery.tsx`. Props: `images: Array<{ attachment, messageId, sentAt }>`, `expanded`, `onToggle`.
- [x] 3.2 Extract `SearchBox` to `_components/SearchBox.tsx`. Props: `value`, `onChange`, `filteredCount`, `totalCount`.
- [x] 3.3 Extract `_hooks/useConversationLists.ts` exposing `{ lists, memberOf, toggle, createAndAdd }`. Move `fetchLists`, `toggleListMembership`, `createListAndAdd` and their state into the hook.
- [x] 3.4 Extract `ListsDropdown` to `_components/ListsDropdown.tsx` using the hook above.
- [x] 3.5 Build clean after each.

## 4. Extract MessageList + useMessages

- [x] 4.1 Create `_hooks/useMessages.ts` exposing `{ messages, loading, error, hasMore, loadOlder, startFastPoll }`. Move `fetchMessagesPage`, `fetchAllMessages`, `loadOlderMessages`, `pollMessages`, `startFastPolling`, `stopFastPolling`, the messages state, and the polling effect into it.
- [x] 4.2 Fix the pre-existing dead `existingMap` Map construction in `pollMessages` while you're in there (or, if `configure-eslint` is landing in parallel, defer to that change). _(N/A — dead code was already gone in the current baseline; pollMessages now uses `find` only.)_
- [x] 4.3 Create `_components/MessageList.tsx` containing the rendering loop, filtered-messages memo, scroll-to-bottom logic, load-older button, sticky header containing `ImageGallery` + `PostsPanel` + `SearchBox`. Forward a `scrollToBottom` ref method so the parent can trigger it after send.
- [x] 4.4 Build clean.

## 5. Extract ComposeBox

- [x] 5.1 Create `_components/ComposeBox.tsx` containing the textarea, attachment input, send button, attachments-attached preview, draft autosave effect, send/upload handlers, send-error UI. Props include `conversationId`, `counterpart`, `redditComposeUrl`, `onSent` (called on success to trigger parent's fast-poll).
- [x] 5.2 Verify the autosave behavior from `autosave-message-drafts` still works inside the new component. _(Hook moved verbatim from page.tsx; identical localStorage key + debounced write + unmount flush.)_
- [x] 5.3 Build clean.

## 6. Extract dialogs

- [x] 6.1 Move `Delete Message?` dialog into `_components/DeleteMessageDialog.tsx`.
- [x] 6.2 Move `Delete from Reddit?` dialog into `_components/RemoteDeleteDialog.tsx`.
- [x] 6.3 Move `Scrub this conversation?` dialog into `_components/ScrubConversationDialog.tsx`.
- [x] 6.4 Build clean.

## 7. Slim `page.tsx`

- [x] 7.1 `page.tsx` becomes the orchestrator: read params, fetch the conversation, glue header + profile-panel + message-list + compose-box + dialogs, own the cross-component dialog open/closed state.
- [x] 7.2 Confirm `page.tsx` is under 300 lines. _(268 lines.)_
- [x] 7.3 Build + lint clean. _(npx tsc --noEmit + npx next lint + npx next build all green.)_

## 8. Regression verification (manual)

- [ ] 8.1 Send a message → optimistic bubble appears, status updates via fast-poll.
- [ ] 8.2 Retry a failed message.
- [ ] 8.3 Remote-delete a message; scrub a conversation.
- [ ] 8.4 Add/remove conversation from a list; create a new list and add.
- [ ] 8.5 Star/unstar conversation.
- [ ] 8.6 Search messages; toggle gallery.
- [ ] 8.7 Draft autosave: type, navigate away, return → restored; send → cleared.
- [ ] 8.8 Load older messages when the 5000-message cap is hit.
