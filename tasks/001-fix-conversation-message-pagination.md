# Task 001: Fix Conversation Message Pagination

## Priority: HIGH (Bug Fix)

## Problem
Conversations with large numbers of messages only load the most recent messages. The beginning of the conversation is cut off, and there's no way to load older messages from the start of the conversation.

## Current Behavior
- Only recent messages are fetched (limited by default API pagination)
- "Load older messages" exists but starts from current view, not from oldest
- Users cannot see the full conversation history

## Expected Behavior
- Conversations should load ALL messages, starting from oldest
- Or: Load from newest with ability to page backward through entire history
- Users should be able to read the complete conversation

## Technical Analysis

### Backend Changes Needed
1. Review `/api/core/conversations/{id}/messages` endpoint
2. Ensure cursor-based pagination supports loading from oldest OR newest
3. Consider adding `direction` parameter: "oldest_first" or "newest_first"
4. Ensure `limit` can be increased or removed for full fetch

### Frontend Changes Needed
1. **Option A - Load all on initial fetch:**
   - Increase default limit significantly
   - Or: Auto-paginate through all messages on load

2. **Option B - Bidirectional pagination:**
   - Add "Load from beginning" button
   - Support scrolling up to load older messages
   - Support scrolling down to load newer messages

### Files to Modify
- `/apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx`
- `/services/core/rediska_core/api/routes/conversation.py`
- `/services/core/rediska_core/api/schemas/conversation.py` (if needed)

## Acceptance Criteria
- [x] User can view ALL messages in a conversation, regardless of length
- [x] Message order is correct (chronological)
- [x] Performance is acceptable for conversations with 100+ messages
- [x] UI indicates when more messages are available to load

## Implementation Notes (Completed 2026-01-12)
- Modified `fetchAllMessages` to auto-paginate through all messages on initial load
- Messages are fetched in batches of 100 until all are retrieved
- Safety limit of 5000 messages to prevent infinite loops
- "Load more" button only appears when safety limit is hit
- Messages are reversed to display oldest-first (chronological order)

## Estimated Scope
- Backend: ~30 minutes
- Frontend: ~1 hour
- Testing: ~30 minutes

## Dependencies
None

## Related Specs
- Spec Pack v0.4: Section 5 (Messages table, cursor-based pagination)
- PRD Epic 9.3: Inbox & conversation view
