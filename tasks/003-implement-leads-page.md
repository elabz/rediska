# Task 003: Implement Leads Page

## Priority: HIGH (Core Feature)

## Current State
The Leads page (`/leads`) is just an empty state placeholder with no functionality.

## Required Functionality

### 1. Lead List
- Fetch leads via `GET /leads` with filters
- Display lead cards with:
  - Post title
  - Author username (with link to profile)
  - Source location (e.g., r/subreddit)
  - Post date
  - Current status badge (new, saved, ignored, contact_queued, contacted)
  - Lead score (if analyzed)
  - Snippet of post body
- Cursor-based pagination

### 2. Filters & Sorting
- Filter by status (New, Saved, Ignored, etc.)
- Filter by provider
- Filter by source location
- Sort by: Date saved, Lead score, Post date

### 3. Lead Actions
- View full post content (expand/modal)
- Update status (dropdown or buttons)
- "Analyze" button to trigger profile analysis
- "Start Conversation" to initiate outreach
- Link to original post on provider

### 4. Lead Detail View
When clicking a lead, show:
- Full post content
- Author profile summary (if analyzed)
- Lead score with reasoning (if scored)
- Action buttons

### 5. Bulk Actions (optional for v1)
- Select multiple leads
- Bulk status update
- Bulk analyze

## API Endpoints

### Backend (already implemented)
```
GET /leads
  Query params: provider_id, source_location, status, offset, limit

GET /leads/{id}

PATCH /leads/{id}/status
  Body: { status: string }

POST /leads/{id}/analyze
```

### Frontend API Routes Needed
```
/api/core/leads/route.ts (GET, POST for save)
/api/core/leads/[leadId]/route.ts (GET)
/api/core/leads/[leadId]/status/route.ts (PATCH)
/api/core/leads/[leadId]/analyze/route.ts (POST)
```

## Files to Create/Modify

### Create
- `/apps/web/src/app/api/core/leads/route.ts`
- `/apps/web/src/app/api/core/leads/[leadId]/route.ts`
- `/apps/web/src/app/api/core/leads/[leadId]/status/route.ts`
- `/apps/web/src/app/api/core/leads/[leadId]/analyze/route.ts`
- `/apps/web/src/components/leads/LeadCard.tsx`
- `/apps/web/src/components/leads/LeadFilters.tsx`
- `/apps/web/src/components/leads/LeadDetailModal.tsx`
- `/apps/web/src/components/leads/StatusBadge.tsx`

### Modify
- `/apps/web/src/app/(authenticated)/leads/page.tsx` - Complete rewrite

## Component Structure
```
LeadsPage
├── LeadFilters
│   ├── StatusFilter
│   ├── ProviderFilter
│   └── SortSelect
├── LeadStats (count by status)
└── LeadList
    ├── LeadCard (multiple)
    │   ├── LeadHeader (title, source)
    │   ├── LeadMeta (author, date, score)
    │   ├── StatusBadge
    │   └── LeadActions (Analyze, Status, View)
    └── Pagination
└── LeadDetailModal (when lead selected)
```

## Acceptance Criteria
- [ ] User can view list of saved leads
- [ ] Leads display status, source, author info
- [ ] User can filter leads by status
- [ ] User can update lead status
- [ ] User can trigger analysis on a lead
- [ ] Analysis results are displayed after completion
- [ ] Pagination works correctly
- [ ] Empty states for no leads / no matches

## Estimated Scope
- API routes: ~1 hour
- Components: ~3 hours
- Page integration: ~1 hour
- Testing: ~30 minutes

## Dependencies
- Task 002 (Browse page for creating leads)
- Backend leads endpoints (implemented)
- Backend analysis endpoint (implemented)

## Related Specs
- Spec Pack v0.4: Section 5 (lead_posts table)
- PRD Epic 7.1: Save post as lead
- PRD Epic 7.2: Lead analysis pipeline
