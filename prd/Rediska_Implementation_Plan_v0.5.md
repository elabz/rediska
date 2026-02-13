# Rediska v0.5 – Implementation Plan
**Date:** 2026-02-13
**Spec Reference:** `prd/Rediska_Spec_Pack_v0.5.md` §11–12

---

## Overview

This plan addresses six interconnected features from Spec v0.5:

| # | Feature | Spec § | Priority |
|---|---------|--------|----------|
| 1 | Lead post → profile_item persistence | §11.1 | **P0** (root cause fix) |
| 2 | Analysis resilience (merge local + provider items) | §11.3 | **P0** (root cause fix) |
| 3 | Auto-analyze on save (enhancement) | §11.6 | **P0** (depends on #1) |
| 4 | Auto-accumulate posts for known users | §11.2 | **P1** |
| 5 | Contact author from any screen | §11.4 | **P1** |
| 6 | Posts panel in message compose | §11.5 | **P2** |

---

## Phase 1: Post Content Persistence (P0 — fixes "No posts to analyze")

### 1A. Save lead post as profile_item

**Goal:** When `save_lead()` is called, also upsert a `profile_item` for the post.

**File:** `services/core/rediska_core/domain/services/leads.py`

**Changes:**

1. Add `from rediska_core.domain.models import ProfileItem` import.

2. Add new method `_save_post_as_profile_item()` to `LeadsService`:

```python
def _save_post_as_profile_item(
    self,
    account_id: int,
    external_post_id: str,
    title: Optional[str],
    body_text: Optional[str],
    source_location: Optional[str],
    post_created_at: Optional[datetime],
) -> Optional[int]:
    """Save/upsert a lead post as a profile_item for the author.

    Returns profile_item ID or None if no body_text.
    """
    if not body_text and not title:
        return None

    # Combine title + body for text_content
    text_parts = []
    if title:
        text_parts.append(title)
    if body_text:
        text_parts.append(body_text)
    text_content = "\n\n".join(text_parts)

    # Upsert by (account_id, item_type, external_item_id)
    existing = (
        self.db.query(ProfileItem)
        .filter(
            ProfileItem.account_id == account_id,
            ProfileItem.item_type == "post",
            ProfileItem.external_item_id == external_post_id,
        )
        .first()
    )

    if existing:
        existing.text_content = text_content
        if post_created_at:
            existing.item_created_at = post_created_at
        if source_location:
            existing.subreddit = source_location
        if title:
            existing.link_title = title
        existing.remote_visibility = "visible"
        self.db.flush()
        return existing.id

    item = ProfileItem(
        account_id=account_id,
        item_type="post",
        external_item_id=external_post_id,
        text_content=text_content,
        item_created_at=post_created_at,
        subreddit=source_location,
        link_title=title,
        remote_visibility="visible",
    )
    self.db.add(item)
    self.db.flush()
    return item.id
```

3. Call `_save_post_as_profile_item()` at the end of `save_lead()`, after the lead row is created/updated:

```python
# After creating/updating lead:
profile_item_id = None
if author_account_id and (body_text or title):
    profile_item_id = self._save_post_as_profile_item(
        account_id=author_account_id,
        external_post_id=external_post_id,
        title=title,
        body_text=body_text,
        source_location=source_location,
        post_created_at=post_created_at,
    )
```

4. Return the `profile_item_id` by attaching it as a transient attribute on the returned lead (or update the response schema).

**File:** `services/core/rediska_core/api/schemas/leads.py`

5. Add `profile_item_id: Optional[int] = None` to `LeadResponse` schema.

**File:** `services/core/rediska_core/api/routes/leads.py`

6. Update `build_lead_response()` to include `profile_item_id` if available.

---

### 1B. Scout Watch → profile_item

**Goal:** When Scout Watch stores a post via `record_post()`, also create a profile_item.

**File:** `services/core/rediska_core/domain/services/scout_watch.py`

**Changes:**

1. In `record_post()` method, after creating the `ScoutWatchPost` row, call the same profile_item upsert logic. Since `ScoutWatchPost` stores `post_author`, look up the ExternalAccount and create a profile_item.

2. Factor out the profile_item creation into a shared utility:

**New file:** `services/core/rediska_core/domain/services/profile_item_utils.py`

```python
def upsert_profile_item_from_post(
    db: Session,
    account_id: int,
    external_post_id: str,
    title: Optional[str],
    body_text: Optional[str],
    source_location: Optional[str],
    post_created_at: Optional[datetime],
) -> Optional[int]:
    """Upsert a profile_item from a browse/scout post.
    Shared by LeadsService and ScoutWatchService.
    Returns profile_item ID or None.
    """
    # (same logic as _save_post_as_profile_item above)
```

3. Both `LeadsService.save_lead()` and `ScoutWatchService.record_post()` call this utility.

---

## Phase 2: Analysis Resilience (P0)

### 2A. Merge local + provider profile items

**Goal:** Analysis should union locally-stored profile_items with provider-fetched items, not replace them.

**File:** `services/core/rediska_core/domain/services/analysis.py`

**Changes to `analyze_lead()`:**

Replace current step 3–4 with:

```python
# Step 3: Fetch profile items from provider (may return 0 if NSFW hidden)
provider_items = await self._fetch_profile_items(account)

# Step 4: Query existing local profile_items (from prior saves, browse, scout)
local_items = (
    self.db.query(ProfileItem)
    .filter(ProfileItem.account_id == account.id)
    .all()
)

# Step 5: Merge — provider items take precedence, local items fill gaps
merged_items = self._merge_profile_items(account, provider_items, local_items)

# Step 6: Store merged items
stored_items = self._store_profile_items(account, merged_items)
```

**New method `_merge_profile_items()`:**

```python
def _merge_profile_items(
    self,
    account: ExternalAccount,
    provider_items: list[ProviderProfileItem],
    local_items: list[ProfileItem],
) -> list[ProviderProfileItem]:
    """Merge provider-fetched items with locally-stored items.

    Provider items take precedence. Local items fill in gaps
    (e.g., posts hidden from profile but captured from search).
    """
    # Build set of provider external IDs
    provider_ids = {item.external_id for item in provider_items}

    # Convert local items not in provider set to ProviderProfileItem format
    for local_item in local_items:
        if local_item.external_item_id not in provider_ids:
            provider_items.append(ProviderProfileItem(
                external_id=local_item.external_item_id,
                item_type=ProfileItemType(local_item.item_type),
                body_text=local_item.text_content,
                created_at=local_item.item_created_at,
                subreddit=getattr(local_item, 'subreddit', None),
                link_title=getattr(local_item, 'link_title', None),
            ))

    return provider_items
```

### 2B. Ensure lead post is a profile_item before analysis

**File:** `services/core/rediska_core/api/routes/leads.py`

**Change in `analyze_lead()` endpoint (line ~500):**

Before creating the `AnalysisService`, ensure the lead post itself is persisted as a profile_item:

```python
# Ensure lead post is saved as profile_item before analysis
from rediska_core.domain.services.profile_item_utils import upsert_profile_item_from_post

upsert_profile_item_from_post(
    db=db,
    account_id=lead.author_account_id,
    external_post_id=lead.external_post_id,
    title=lead.title,
    body_text=lead.body_text,
    source_location=lead.source_location,
    post_created_at=lead.post_created_at,
)
db.flush()
```

This guarantees at least one profile_item exists before analysis runs, even for leads saved before v0.5.

---

## Phase 3: Auto-Accumulate Posts for Known Users (P1)

### 3A. Backend: Batch ingest endpoint

**New file:** `services/core/rediska_core/api/routes/profile_items.py`

```python
router = APIRouter(prefix="/profile-items", tags=["profile-items"])

@router.post("/ingest-browse-posts")
async def ingest_browse_posts(
    request: IngestBrowsePostsRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> IngestBrowsePostsResponse:
    """Ingest posts from browse/scout results for known authors.

    For each post, checks if the author has an ExternalAccount.
    If yes, upserts a profile_item for the post.
    """
```

**New schemas:** `services/core/rediska_core/api/schemas/profile_items.py`

```python
class BrowsePostForIngest(BaseModel):
    provider_id: str
    external_post_id: str
    author_username: str
    title: Optional[str] = None
    body_text: Optional[str] = None
    source_location: Optional[str] = None
    post_created_at: Optional[datetime] = None

class IngestBrowsePostsRequest(BaseModel):
    posts: list[BrowsePostForIngest]

class IngestBrowsePostsResponse(BaseModel):
    ingested_count: int
    new_items_count: int
    known_authors: list[str]
```

**Logic:**
1. Batch-query `external_accounts` for all unique author_usernames in the request.
2. For each post whose author IS known, call `upsert_profile_item_from_post()`.
3. Return counts + list of known authors.

**Register router:** Add to `main.py` router includes.

### 3B. BFF proxy route

**New file:** `apps/web/src/app/api/core/profile-items/ingest-browse-posts/route.ts`

Standard proxy to `CORE_API_URL/profile-items/ingest-browse-posts`.

### 3C. Frontend integration

**File:** `apps/web/src/app/(authenticated)/browse/page.tsx`

After `fetchPosts()` returns results, fire a background call:

```typescript
// After posts are loaded, ingest for known users (fire-and-forget)
if (data.posts.length > 0) {
  fetch('/api/core/profile-items/ingest-browse-posts', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      posts: data.posts.map(p => ({
        provider_id: p.provider_id,
        external_post_id: p.external_post_id,
        author_username: p.author_username,
        title: p.title,
        body_text: p.body_text,
        source_location: p.source_location,
        post_created_at: p.post_created_at,
      })),
    }),
  }).then(res => res.json()).then(result => {
    // Optionally: mark known authors in UI with a badge
    if (result.known_authors?.length) {
      setKnownAuthors(new Set(result.known_authors));
    }
  }).catch(() => {});
}
```

Optional: Show a small badge/indicator on PostCards for known authors.

---

## Phase 4: Contact Author from Any Screen (P1)

### 4A. Backend: Initiate conversation by username

The existing `POST /conversations/initiate/from-lead/{lead_id}` requires a lead_id. For contacting from Browse (before saving as lead), we need a username-based endpoint.

**File:** `services/core/rediska_core/api/routes/conversation.py`

**New endpoint:**

```python
@router.post("/initiate/by-username")
async def initiate_conversation_by_username(
    request: InitiateByUsernameRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ConversationSummaryResponse:
    """Initiate a conversation with a user by username.

    Creates ExternalAccount if needed, then gets/creates conversation.
    """
```

**New schema:**

```python
class InitiateByUsernameRequest(BaseModel):
    provider_id: str = "reddit"
    username: str
    identity_id: Optional[int] = None  # uses default if omitted
```

**Logic:**
1. Get or create ExternalAccount for username
2. Check do_not_contact list
3. Get identity (from request or default)
4. Get or create Conversation
5. Return ConversationSummaryResponse
6. Audit log

### 4B. BFF proxy route

**New file:** `apps/web/src/app/api/core/conversations/initiate/by-username/route.ts`

### 4C. Shared `ContactButton` component

**New file:** `apps/web/src/components/ContactButton.tsx`

```tsx
interface ContactButtonProps {
  username: string;
  providerId?: string;
  variant?: 'icon' | 'button';  // icon for compact, button for full
  size?: 'sm' | 'default';
  className?: string;
}

export function ContactButton({ username, providerId = 'reddit', variant = 'icon', ...props }: ContactButtonProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const handleContact = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/core/conversations/initiate/by-username', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: providerId, username }),
      });
      const data = await res.json();
      if (res.ok) {
        router.push(`/inbox/${data.id}`);
      }
    } finally {
      setLoading(false);
    }
  };

  // Render button or icon based on variant
}
```

### 4D. Add ContactButton to existing screens

| File | Location | Change |
|------|----------|--------|
| `browse/page.tsx` → `PostCard` | Next to "Save Lead" button | Add `<ContactButton username={post.author_username} variant="button" size="sm" />` |
| `UserProfilePanel.tsx` | Header row, next to Analyze button | Add `<ContactButton username={username} variant="icon" />` |
| `leads/page.tsx` | Lead row actions | Add `<ContactButton>` icon |
| `leads/[id]/page.tsx` | Lead detail header | Add `<ContactButton>` button |
| `directories/page.tsx` | Account row | Add `<ContactButton>` icon |
| `profile/[accountId]/page.tsx` | Profile header | Add `<ContactButton>` button |
| Scout Watch history pages | Post row | Add `<ContactButton>` icon |

---

## Phase 5: Posts Panel in Message Compose (P2)

### 5A. `PostsPanel` component

**New file:** `apps/web/src/components/PostsPanel.tsx`

```tsx
interface PostsPanelProps {
  accountId: number;
  defaultExpanded?: boolean;
}

export function PostsPanel({ accountId, defaultExpanded = false }: PostsPanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [posts, setPosts] = useState<ProfileItem[]>([]);
  const [loading, setLoading] = useState(false);

  // Lazy-load posts when expanded
  useEffect(() => {
    if (expanded && posts.length === 0) {
      fetchPosts();
    }
  }, [expanded]);

  const fetchPosts = async () => {
    setLoading(true);
    const res = await fetch(
      `/api/core/accounts/${accountId}/profile-items?item_type=post&limit=50`,
      { credentials: 'include' }
    );
    const data = await res.json();
    setPosts(data.items || []);
    setLoading(false);
  };

  return (
    <div className="border rounded-lg">
      <button onClick={() => setExpanded(!expanded)} className="...">
        Posts ({posts.length}) <ChevronDown />
      </button>
      {expanded && (
        <div className="max-h-96 overflow-y-auto space-y-2 p-2">
          {posts.map(post => (
            <PostItem key={post.id} post={post} />
          ))}
        </div>
      )}
    </div>
  );
}
```

### 5B. Integrate into conversation view

**File:** `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx`

Add `<PostsPanel>` below the existing image gallery in the sidebar/panel area. The `accountId` comes from the conversation's counterpart account.

```tsx
{/* Existing image gallery */}
<MessageGallery ... />

{/* New posts panel */}
{conversation?.counterpart?.id && (
  <PostsPanel accountId={conversation.counterpart.id} />
)}
```

---

## File Change Summary

### New Files (6)

| File | Purpose |
|------|---------|
| `services/core/rediska_core/domain/services/profile_item_utils.py` | Shared upsert utility |
| `services/core/rediska_core/api/routes/profile_items.py` | Batch ingest endpoint |
| `services/core/rediska_core/api/schemas/profile_items.py` | Ingest request/response schemas |
| `apps/web/src/app/api/core/profile-items/ingest-browse-posts/route.ts` | BFF proxy |
| `apps/web/src/components/ContactButton.tsx` | Reusable contact action |
| `apps/web/src/components/PostsPanel.tsx` | Posts panel for compose view |

### Modified Files (10+)

| File | Changes |
|------|---------|
| `services/core/rediska_core/domain/services/leads.py` | Call `upsert_profile_item_from_post` in `save_lead()` |
| `services/core/rediska_core/domain/services/analysis.py` | Merge local+provider items, add `_merge_profile_items()` |
| `services/core/rediska_core/domain/services/scout_watch.py` | Call `upsert_profile_item_from_post` in `record_post()` |
| `services/core/rediska_core/api/routes/leads.py` | Ensure profile_item before analysis; update response |
| `services/core/rediska_core/api/routes/conversation.py` | Add `initiate/by-username` endpoint |
| `services/core/rediska_core/api/schemas/leads.py` | Add `profile_item_id` to response |
| `services/core/rediska_core/main.py` | Register `profile_items` router |
| `apps/web/src/app/(authenticated)/browse/page.tsx` | Add ContactButton, auto-ingest for known users |
| `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` | Add PostsPanel |
| `apps/web/src/components/UserProfilePanel.tsx` | Add ContactButton |
| `apps/web/src/app/(authenticated)/leads/page.tsx` | Add ContactButton |
| `apps/web/src/app/(authenticated)/directories/page.tsx` | Add ContactButton |
| `apps/web/src/app/api/core/conversations/initiate/by-username/route.ts` | BFF proxy (new) |

### No Schema/Migration Changes

All features use existing tables. The `profile_items` table already has `subreddit`, `link_title` columns (migration 013). No DDL changes needed.

---

## Implementation Order

```
Phase 1A: leads.py + profile_item_utils.py     (fixes core issue)
Phase 1B: scout_watch.py integration            (extends fix to scout)
Phase 2A: analysis.py merge logic               (resilience)
Phase 2B: leads.py ensure profile_item before analyze  (belt + suspenders)
    ↓ ---- at this point, "No posts to analyze" is fixed ----
Phase 3A: profile_items.py route + schemas       (backend)
Phase 3B: BFF proxy route                        (proxy)
Phase 3C: browse/page.tsx auto-ingest            (frontend)
    ↓ ---- auto-accumulate working ----
Phase 4A: conversation.py by-username endpoint   (backend)
Phase 4B: BFF proxy route                        (proxy)
Phase 4C: ContactButton component                (component)
Phase 4D: Integrate ContactButton across screens (UI)
    ↓ ---- contact from anywhere working ----
Phase 5A: PostsPanel component                   (component)
Phase 5B: Integrate into conversation view       (UI)
    ↓ ---- all v0.5 features complete ----
```

---

## Testing Strategy

| Phase | Test Type | Description |
|-------|-----------|-------------|
| 1A | Unit | `test_save_lead_creates_profile_item` — verify profile_item is created alongside lead |
| 1A | Unit | `test_save_lead_upserts_profile_item` — verify no duplicate on re-save |
| 2A | Unit | `test_merge_profile_items_union` — verify local items fill provider gaps |
| 2A | Unit | `test_merge_profile_items_provider_wins` — verify provider items take precedence |
| 2B | Integration | `test_analyze_lead_with_zero_provider_items` — verify analysis succeeds with only local items |
| 3A | Unit | `test_ingest_browse_posts_known_authors` — verify only known authors get items |
| 3A | Unit | `test_ingest_browse_posts_unknown_authors_skipped` |
| 4A | Integration | `test_initiate_by_username_creates_conversation` |
| 4A | Integration | `test_initiate_by_username_returns_existing` |
| 4A | Unit | `test_initiate_by_username_dnc_blocked` — verify do_not_contact check |

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Profile item duplicates from multiple sources | Upsert by `(account_id, item_type, external_item_id)` unique key |
| Performance of batch ingest on large browse results | Batch DB queries (IN clause for author lookup), limit to 100 posts per request |
| Race condition: analysis starts before profile_item commit | Phase 2B adds explicit ensure-profile_item step in analyze_lead() endpoint |
| Conversation creation for unknown users | get_or_create ExternalAccount in initiate-by-username ensures account exists |

---

**End of Implementation Plan v0.5**
