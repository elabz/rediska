# Task 004: Implement Directories Page

## Priority: MEDIUM (Core Feature)

## Current State
The Directories page (`/directories`) is just an empty state placeholder with no functionality.

## Required Functionality

### 1. Directory Tabs
Three main directories based on contact state:
- **Analyzed** - Accounts with completed profile analysis
- **Contacted** - Accounts we've sent messages to
- **Engaged** - Accounts that replied after our contact

### 2. Directory Entry Display
Each entry shows:
- Username (link to profile page)
- Provider badge
- Profile summary snippet (from latest snapshot)
- Analysis date / Contact date / Engagement date
- Lead score (if available)
- Quick action buttons

### 3. Directory Filters
- Filter by provider
- Filter by date range
- Search by username
- Sort by: Date, Score, Username

### 4. Profile Preview
Clicking an entry shows:
- Full profile summary
- Signals and risk flags
- Conversation history link
- Original lead post (if applicable)

### 5. Directory Stats
- Total count per directory
- Counts per provider
- Conversion funnel visualization (optional)

## API Endpoints

### Backend (needs to be created or verified)
```
GET /directories/analyzed
  Query params: provider_id, offset, limit, sort

GET /directories/contacted
  Query params: provider_id, offset, limit, sort

GET /directories/engaged
  Query params: provider_id, offset, limit, sort

GET /accounts/{id}/profile
  Returns: Account details with latest snapshot
```

### Frontend API Routes Needed
```
/api/core/directories/analyzed/route.ts
/api/core/directories/contacted/route.ts
/api/core/directories/engaged/route.ts
/api/core/accounts/[accountId]/route.ts
```

## Files to Create/Modify

### Create
- `/apps/web/src/app/api/core/directories/analyzed/route.ts`
- `/apps/web/src/app/api/core/directories/contacted/route.ts`
- `/apps/web/src/app/api/core/directories/engaged/route.ts`
- `/apps/web/src/app/api/core/accounts/[accountId]/route.ts`
- `/apps/web/src/components/directories/DirectoryTabs.tsx`
- `/apps/web/src/components/directories/DirectoryEntry.tsx`
- `/apps/web/src/components/directories/DirectoryFilters.tsx`
- `/apps/web/src/components/directories/ProfilePreview.tsx`

### Modify
- `/apps/web/src/app/(authenticated)/directories/page.tsx` - Complete rewrite

## Component Structure
```
DirectoriesPage
├── DirectoryStats (total counts)
├── DirectoryTabs (Analyzed | Contacted | Engaged)
├── DirectoryFilters
│   ├── ProviderFilter
│   ├── DateRangeFilter
│   ├── SearchInput
│   └── SortSelect
└── DirectoryList
    ├── DirectoryEntry (multiple)
    │   ├── Avatar/Icon
    │   ├── Username + Provider
    │   ├── SummarySnippet
    │   ├── DateInfo
    │   └── ActionButtons
    └── Pagination
└── ProfilePreview (sidebar or modal)
```

## Acceptance Criteria
- [ ] User can view Analyzed directory with profile summaries
- [ ] User can view Contacted directory with contact dates
- [ ] User can view Engaged directory with engagement dates
- [ ] Tabs show correct counts
- [ ] Filters work across all directories
- [ ] Clicking entry shows profile preview
- [ ] Link to conversation works from entry
- [ ] Empty states when directories are empty

## Estimated Scope
- API routes: ~1 hour
- Backend endpoints (if needed): ~2 hours
- Components: ~3 hours
- Page integration: ~1 hour
- Testing: ~30 minutes

## Dependencies
- Task 003 (Leads page for triggering analysis)
- Backend directory endpoints (may need to be created)
- Backend account/profile endpoints

## Related Specs
- Spec Pack v0.4: Section 5 (external_accounts table - analysis_state, contact_state, engagement_state)
- PRD Epic 7.3: Directories
