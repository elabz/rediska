# Task 002: Implement Browse Page

## Priority: HIGH (Core Feature)

## Current State
The Browse page (`/browse`) is just an empty state placeholder with no functionality.

## Required Functionality

### 1. Location Selector
- Provider dropdown (currently Reddit only)
- Location/subreddit input field with validation
- Recent locations history (stored in localStorage)
- Popular/suggested locations (optional)

### 2. Post List
- Fetch posts from selected location via `/sources/{provider_id}/locations/{location}/posts`
- Display post cards with:
  - Title
  - Author username
  - Post date/time
  - Snippet of body text
  - Score/upvotes (if available from provider)
  - Comment count (if available)
- Cursor-based pagination ("Load more" button)
- Sort options: Hot, New, Top

### 3. Post Actions
- "Save as Lead" button on each post
- Clicking post shows expanded preview
- Link to original post on provider

### 4. UI/UX
- Loading states during fetch
- Error handling with retry option
- Empty state when no posts found
- Responsive design for mobile

## API Endpoints Needed

### Backend (already implemented)
```
GET /sources/{provider_id}/locations/{location}/posts
  Query params: cursor, limit, sort

POST /leads/save
  Body: provider_id, source_location, external_post_id, post_url, title, body_text, author_username, author_external_id, post_created_at
```

### Frontend API Route
```
/api/core/sources/[providerId]/locations/[location]/posts
/api/core/leads/save
```

## Files to Create/Modify

### Create
- `/apps/web/src/app/api/core/sources/[providerId]/locations/[location]/posts/route.ts`
- `/apps/web/src/components/browse/LocationSelector.tsx`
- `/apps/web/src/components/browse/PostCard.tsx`
- `/apps/web/src/components/browse/PostList.tsx`

### Modify
- `/apps/web/src/app/(authenticated)/browse/page.tsx` - Complete rewrite

## Component Structure
```
BrowsePage
├── LocationSelector
│   ├── ProviderDropdown
│   ├── LocationInput
│   └── RecentLocations
├── SortControls
└── PostList
    ├── PostCard (multiple)
    │   ├── PostHeader (author, date)
    │   ├── PostContent (title, preview)
    │   └── PostActions (Save as Lead)
    └── LoadMoreButton
```

## Acceptance Criteria
- [ ] User can enter a subreddit name
- [ ] Posts are fetched and displayed with pagination
- [ ] User can save a post as a lead
- [ ] Saved posts show visual indicator
- [ ] Sort options work correctly
- [ ] Error states are handled gracefully
- [ ] Loading states provide user feedback

## Estimated Scope
- API routes: ~30 minutes
- Components: ~2 hours
- Page integration: ~1 hour
- Testing: ~30 minutes

## Dependencies
- Backend browse endpoint (implemented)
- Backend leads save endpoint (implemented)

## Related Specs
- Spec Pack v0.4: Section 7 (Celery tasks - ingest.browse_location)
- PRD Epic 7.1: Manual browse UI + API
