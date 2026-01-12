# Task 008: Backend Browse Endpoint Verification

## Priority: HIGH (Prerequisite for Browse UI)

## Current State
Need to verify the browse endpoint exists and works correctly for the Browse UI.

## Required Endpoint

```python
GET /sources/{provider_id}/locations/{location}/posts

Path params:
  - provider_id: str (e.g., "reddit")
  - location: str (e.g., "subreddit_name")

Query params:
  - cursor: Optional[str] - Pagination cursor
  - limit: int = 25 - Max posts to return
  - sort: str = "hot" - Sort order (hot, new, top)

Response:
{
  "posts": [
    {
      "external_post_id": "abc123",
      "post_url": "https://reddit.com/r/...",
      "title": "Post title",
      "body_text": "Post content...",
      "author_username": "username",
      "author_external_id": "user_id",
      "post_created_at": "2024-01-15T10:30:00Z",
      "score": 150,
      "num_comments": 42,
      "source_location": "subreddit_name",
      "provider_id": "reddit"
    }
  ],
  "next_cursor": "cursor_string_or_null",
  "has_more": true
}
```

## Tasks

### 1. Check Existing Implementation
- Verify `/services/core/rediska_core/api/routes/sources.py` exists
- Check if endpoint is implemented
- Verify provider adapter integration

### 2. Implement if Missing
```python
# /api/routes/sources.py

router = APIRouter(prefix="/sources", tags=["sources"])

@router.get("/{provider_id}/locations/{location}/posts")
async def browse_location(
    provider_id: str,
    location: str,
    cursor: Optional[str] = None,
    limit: int = Query(default=25, ge=1, le=100),
    sort: str = Query(default="hot", regex="^(hot|new|top)$"),
    current_user: CurrentUser,
    db: DBSession,
):
    """Browse posts from a provider location."""
    # Get provider adapter
    # Call browse_location method
    # Return normalized posts
```

### 3. Provider Adapter Method
Verify `RedditAdapter.browse_location()` method:
- Fetches posts from subreddit
- Handles pagination with cursor
- Returns normalized post DTOs
- Handles errors gracefully

## Files to Check/Create

### Check
- `/services/core/rediska_core/api/routes/sources.py`
- `/services/core/rediska_core/providers/reddit/adapter.py`

### Create if needed
- `/services/core/rediska_core/api/routes/sources.py`
- `/services/core/rediska_core/api/schemas/sources.py`

## Acceptance Criteria
- [ ] Endpoint returns posts for valid subreddit
- [ ] Pagination works with cursor
- [ ] Sort options work (hot, new, top)
- [ ] Error handling for invalid subreddit
- [ ] Error handling for rate limits
- [ ] Posts include all required fields

## Estimated Scope
- Verification: ~30 minutes
- Implementation (if needed): ~2 hours
- Testing: ~30 minutes

## Dependencies
- Reddit provider adapter (implemented)
- Reddit OAuth credentials configured

## Related Specs
- Spec Pack v0.4: Section 7 (ingest.browse_location task)
- PRD Epic 7.1: Manual browse UI
