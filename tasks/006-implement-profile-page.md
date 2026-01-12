# Task 006: Implement Profile Page

## Priority: MEDIUM (Core Feature)

## Current State
There is no dedicated profile page for viewing analyzed account details.

## Required Functionality

### 1. Profile Header
- Username with provider badge
- Account status (active, deleted, suspended) with badges
- Analysis state indicator
- First analyzed date
- Action buttons (Start Conversation, Re-analyze)

### 2. Profile Summary Section
- AI-generated summary text
- Signals extracted (interests, topics, etc.)
- Risk flags (if any)
- Model info (which LLM generated the summary)
- Last updated timestamp

### 3. Content Tabs
- **Posts** - User's public posts
- **Comments** - User's comments
- **Images** - Media content (if any)

Each tab shows:
- Item preview with date
- Remote visibility badge (if deleted/removed)
- Link to original content
- Pagination

### 4. Conversation History
- List of conversations with this account
- Quick link to each conversation
- Message count per conversation

### 5. Lead Association
- Link to original lead post (if came from lead)
- Lead status and score

## API Endpoints

### Backend (may need creation)
```
GET /accounts/{id}
  Returns: Account details with latest snapshot

GET /accounts/{id}/profile-items
  Query params: item_type, offset, limit
  Returns: Posts, comments, or images

GET /accounts/{id}/snapshots
  Returns: All profile snapshots for history

GET /accounts/{id}/conversations
  Returns: Conversations with this account

POST /accounts/{id}/analyze
  Triggers re-analysis
```

### Frontend API Routes Needed
```
/api/core/accounts/[accountId]/route.ts
/api/core/accounts/[accountId]/profile-items/route.ts
/api/core/accounts/[accountId]/snapshots/route.ts
/api/core/accounts/[accountId]/conversations/route.ts
/api/core/accounts/[accountId]/analyze/route.ts
```

## Files to Create

### Pages
- `/apps/web/src/app/(authenticated)/profile/[accountId]/page.tsx`

### API Routes
- `/apps/web/src/app/api/core/accounts/[accountId]/route.ts`
- `/apps/web/src/app/api/core/accounts/[accountId]/profile-items/route.ts`
- `/apps/web/src/app/api/core/accounts/[accountId]/conversations/route.ts`
- `/apps/web/src/app/api/core/accounts/[accountId]/analyze/route.ts`

### Components
- `/apps/web/src/components/profile/ProfileHeader.tsx`
- `/apps/web/src/components/profile/ProfileSummary.tsx`
- `/apps/web/src/components/profile/ProfileTabs.tsx`
- `/apps/web/src/components/profile/PostsList.tsx`
- `/apps/web/src/components/profile/CommentsList.tsx`
- `/apps/web/src/components/profile/ImageGallery.tsx`
- `/apps/web/src/components/profile/ConversationsList.tsx`
- `/apps/web/src/components/profile/RemoteStatusBadge.tsx`

### Backend (if not exists)
- `/services/core/rediska_core/api/routes/accounts.py`

## Component Structure
```
ProfilePage
├── ProfileHeader
│   ├── Username + Provider
│   ├── StatusBadges
│   ├── AnalysisState
│   └── ActionButtons (Analyze, Start Conversation)
├── ProfileSummary
│   ├── SummaryText
│   ├── SignalsList
│   ├── RiskFlags
│   └── ModelInfo
├── ProfileTabs
│   ├── PostsTab
│   │   └── PostsList with pagination
│   ├── CommentsTab
│   │   └── CommentsList with pagination
│   └── ImagesTab
│       └── ImageGallery with pagination
└── ConversationHistory
    └── ConversationsList with links
```

## Acceptance Criteria
- [ ] Profile page loads for analyzed accounts
- [ ] Summary and signals are displayed
- [ ] Risk flags are highlighted appropriately
- [ ] Posts/Comments/Images tabs work with pagination
- [ ] Remote deleted items show appropriate badges
- [ ] User can trigger re-analysis
- [ ] User can start conversation from profile
- [ ] Conversation history links work

## Estimated Scope
- Backend routes: ~2 hours
- API routes: ~1 hour
- Components: ~4 hours
- Page integration: ~1 hour
- Testing: ~30 minutes

## Dependencies
- Backend account/profile endpoints
- Analysis service (implemented)
- Profile items storage (implemented)

## Related Specs
- Spec Pack v0.4: Section 5 (external_accounts, profile_snapshots, profile_items tables)
- PRD Epic 9.5: Profile page + directories
- PRD Epic 8.2: Profile summary agent
