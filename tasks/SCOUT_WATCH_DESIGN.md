# Scout Watch System Design

## Overview

Scout Watch is an automatic subreddit monitoring system that:
1. Periodically scans configured subreddits for new posts matching search criteria
2. Runs multi-agent analysis on matching posts
3. Automatically creates leads for posts that pass analysis thresholds
4. Tracks source (manual vs automatic) for all leads

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              UI Layer                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  Settings > Scout Watches                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ + Add Watch                                                         ││
│  │ ┌─────────────────────────────────────────────────────────────────┐ ││
│  │ │ r/r4r                                                           │ ││
│  │ │ Query: "looking for" AND ("dom" OR "daddy")                     │ ││
│  │ │ Status: Active  |  Last run: 2 min ago  |  Matches: 142         │ ││
│  │ │ [Edit] [Pause] [Delete]                                         │ ││
│  │ └─────────────────────────────────────────────────────────────────┘ ││
│  │ ┌─────────────────────────────────────────────────────────────────┐ ││
│  │ │ r/dirtyr4r                                                      │ ││
│  │ │ Query: flair:F4M AND "sub"                                      │ ││
│  │ │ Status: Active  |  Last run: 2 min ago  |  Matches: 89          │ ││
│  │ └─────────────────────────────────────────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  Browse Page: [+ Add to Scout Watch] button when search criteria active  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           API Layer                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  POST   /scout-watches              - Create watch                       │
│  GET    /scout-watches              - List all watches                   │
│  GET    /scout-watches/{id}         - Get watch details                  │
│  PUT    /scout-watches/{id}         - Update watch                       │
│  DELETE /scout-watches/{id}         - Delete watch                       │
│  POST   /scout-watches/{id}/run     - Trigger manual run                 │
│  GET    /scout-watches/{id}/runs    - List run history                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Service Layer                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  ScoutWatchService                                                       │
│  ├── create_watch(location, query, filters, identity_id)                 │
│  ├── update_watch(watch_id, ...)                                         │
│  ├── delete_watch(watch_id)                                              │
│  ├── list_watches(include_stats=True)                                    │
│  ├── run_watch(watch_id) -> ScoutWatchRun                                │
│  └── get_run_history(watch_id, limit)                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Celery Beat                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  "scout-watch-periodic": {                                               │
│      "task": "scout.run_all_watches",                                    │
│      "schedule": 300.0,  # Every 5 minutes                               │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Task Flow                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  scout.run_all_watches                                                   │
│       │                                                                  │
│       ├──► For each active watch:                                        │
│       │       │                                                          │
│       │       └──► scout.run_single_watch(watch_id)                      │
│       │               │                                                  │
│       │               ├── 1. Fetch posts from Reddit (last 30 min)       │
│       │               │      - Use BrowseService with search query       │
│       │               │      - Filter by time (created_utc > cutoff)     │
│       │               │                                                  │
│       │               ├── 2. Deduplicate                                 │
│       │               │      - Check scout_watch_posts table             │
│       │               │      - Skip already-processed posts              │
│       │               │                                                  │
│       │               ├── 3. For each new post:                          │
│       │               │      - Record in scout_watch_posts               │
│       │               │      - Enqueue analysis task                     │
│       │               │                                                  │
│       │               └── 4. Update watch stats                          │
│       │                                                                  │
│       └──► scout.analyze_and_create_lead(watch_id, post_data)            │
│               │                                                          │
│               ├── 1. Run quick Meta-Analysis (single agent)              │
│               │      - Uses existing MetaAnalysisAgent                   │
│               │      - Input: post title + body only                     │
│               │                                                          │
│               ├── 2. If recommendation == "suitable":                    │
│               │      - Create lead via LeadsService.save_lead()          │
│               │      - Set lead_source = "scout_watch"                   │
│               │      - Set scout_watch_id = watch.id                     │
│               │      - Status = "new"                                    │
│               │                                                          │
│               └── 3. Update scout_watch_posts with result                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### New Tables

#### `scout_watches` - Watch configurations

```sql
CREATE TABLE scout_watches (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Provider and location
    provider_id VARCHAR(50) NOT NULL DEFAULT 'reddit',
    source_location VARCHAR(255) NOT NULL,  -- e.g., "r/r4r"

    -- Search criteria (matches Browse page params)
    search_query TEXT,                       -- Reddit search syntax
    sort_by VARCHAR(20) DEFAULT 'new',       -- hot, new, top, rising
    time_filter VARCHAR(20) DEFAULT 'day',   -- hour, day, week, month, year, all

    -- Identity to use for API calls
    identity_id INT,
    FOREIGN KEY (identity_id) REFERENCES identities(id),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Analysis settings
    auto_analyze BOOLEAN DEFAULT TRUE,       -- Run analysis on matches
    min_confidence FLOAT DEFAULT 0.7,        -- Minimum confidence to create lead

    -- Stats (denormalized for performance)
    total_posts_seen INT DEFAULT 0,
    total_matches INT DEFAULT 0,
    total_leads_created INT DEFAULT 0,

    -- Timestamps
    last_run_at DATETIME,
    last_match_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE KEY idx_watch_location (provider_id, source_location, search_query(255)),
    INDEX idx_active (is_active, last_run_at)
);
```

#### `scout_watch_runs` - Run history

```sql
CREATE TABLE scout_watch_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,

    watch_id INT NOT NULL,
    FOREIGN KEY (watch_id) REFERENCES scout_watches(id) ON DELETE CASCADE,

    -- Run details
    started_at DATETIME NOT NULL,
    completed_at DATETIME,

    -- Results
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    posts_fetched INT DEFAULT 0,
    posts_new INT DEFAULT 0,           -- Not seen before
    posts_analyzed INT DEFAULT 0,
    leads_created INT DEFAULT 0,

    -- Error tracking
    error_message TEXT,

    INDEX idx_watch_runs (watch_id, started_at DESC)
);
```

#### `scout_watch_posts` - Deduplication & tracking

```sql
CREATE TABLE scout_watch_posts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    watch_id INT NOT NULL,
    FOREIGN KEY (watch_id) REFERENCES scout_watches(id) ON DELETE CASCADE,

    -- Post identification
    external_post_id VARCHAR(100) NOT NULL,

    -- Tracking
    first_seen_at DATETIME NOT NULL,
    run_id INT,
    FOREIGN KEY (run_id) REFERENCES scout_watch_runs(id),

    -- Analysis result
    analysis_status ENUM('pending', 'analyzed', 'skipped', 'failed') DEFAULT 'pending',
    analysis_recommendation VARCHAR(50),    -- suitable, not_recommended, needs_review
    analysis_confidence FLOAT,

    -- Lead creation
    lead_id INT,
    FOREIGN KEY (lead_id) REFERENCES lead_posts(id),

    -- Constraints (each post seen once per watch)
    UNIQUE KEY idx_watch_post (watch_id, external_post_id),
    INDEX idx_pending (watch_id, analysis_status)
);
```

### Modified Tables

#### `lead_posts` - Add source tracking

```sql
ALTER TABLE lead_posts ADD COLUMN lead_source ENUM('manual', 'scout_watch') DEFAULT 'manual';
ALTER TABLE lead_posts ADD COLUMN scout_watch_id INT NULL;
ALTER TABLE lead_posts ADD FOREIGN KEY (scout_watch_id) REFERENCES scout_watches(id);
ALTER TABLE lead_posts ADD INDEX idx_lead_source (lead_source);
```

---

## API Design

### Endpoints

#### Create Watch
```
POST /scout-watches

Request:
{
    "source_location": "r/r4r",
    "search_query": "looking for AND (dom OR daddy)",
    "sort_by": "new",
    "time_filter": "day",
    "identity_id": 1,
    "auto_analyze": true,
    "min_confidence": 0.7
}

Response: 201 Created
{
    "id": 1,
    "provider_id": "reddit",
    "source_location": "r/r4r",
    "search_query": "looking for AND (dom OR daddy)",
    "sort_by": "new",
    "time_filter": "day",
    "identity_id": 1,
    "is_active": true,
    "auto_analyze": true,
    "min_confidence": 0.7,
    "total_posts_seen": 0,
    "total_matches": 0,
    "total_leads_created": 0,
    "last_run_at": null,
    "created_at": "2026-01-16T10:00:00Z"
}
```

#### List Watches
```
GET /scout-watches?include_stats=true

Response: 200 OK
{
    "watches": [
        {
            "id": 1,
            "source_location": "r/r4r",
            "search_query": "looking for AND (dom OR daddy)",
            "is_active": true,
            "stats": {
                "total_posts_seen": 1420,
                "total_matches": 142,
                "total_leads_created": 89,
                "last_run_at": "2026-01-16T10:05:00Z",
                "last_match_at": "2026-01-16T10:05:00Z"
            }
        }
    ]
}
```

#### Update Watch
```
PUT /scout-watches/{id}

Request:
{
    "search_query": "updated query",
    "is_active": false
}

Response: 200 OK
{ ...updated watch... }
```

#### Delete Watch
```
DELETE /scout-watches/{id}

Response: 204 No Content
```

#### Manual Run
```
POST /scout-watches/{id}/run

Response: 202 Accepted
{
    "run_id": 123,
    "status": "running",
    "message": "Watch run started"
}
```

#### Run History
```
GET /scout-watches/{id}/runs?limit=10

Response: 200 OK
{
    "runs": [
        {
            "id": 123,
            "started_at": "2026-01-16T10:05:00Z",
            "completed_at": "2026-01-16T10:05:32Z",
            "status": "completed",
            "posts_fetched": 25,
            "posts_new": 8,
            "posts_analyzed": 8,
            "leads_created": 3
        }
    ]
}
```

---

## Celery Tasks

### Task Definitions

```python
# services/worker/rediska_worker/tasks/scout.py

@app.task(name="scout.run_all_watches")
def run_all_watches() -> dict:
    """
    Periodic task that runs all active watches.
    Spawns individual tasks for each watch.
    """
    pass

@app.task(name="scout.run_single_watch", bind=True)
def run_single_watch(self, watch_id: int) -> dict:
    """
    Run a single watch:
    1. Fetch posts from last 30 minutes
    2. Deduplicate against scout_watch_posts
    3. Enqueue analysis for new posts
    """
    pass

@app.task(name="scout.analyze_post", bind=True)
def analyze_post(self, watch_id: int, post_data: dict) -> dict:
    """
    Analyze a single post:
    1. Run quick Meta-Analysis
    2. If suitable, create lead
    3. Update scout_watch_posts
    """
    pass
```

### Beat Schedule Addition

```python
# In celery_app.py beat_schedule

"scout-watch-periodic": {
    "task": "scout.run_all_watches",
    "schedule": 300.0,  # Every 5 minutes
},
```

### Task Routing

```python
# In celery_app.py task_routes

"rediska_worker.tasks.scout.*": {"queue": "scout"},
```

---

## Service Layer

### ScoutWatchService

```python
# services/core/rediska_core/domain/services/scout_watch.py

class ScoutWatchService:
    def __init__(self, db: Session):
        self.db = db
        self.browse_service = BrowseService(db)
        self.leads_service = LeadsService(db)

    def create_watch(
        self,
        source_location: str,
        search_query: Optional[str] = None,
        sort_by: str = "new",
        time_filter: str = "day",
        identity_id: Optional[int] = None,
        auto_analyze: bool = True,
        min_confidence: float = 0.7,
    ) -> ScoutWatch:
        """Create a new watch configuration."""
        pass

    def update_watch(self, watch_id: int, **kwargs) -> ScoutWatch:
        """Update watch configuration."""
        pass

    def delete_watch(self, watch_id: int) -> None:
        """Delete a watch and its history."""
        pass

    def list_watches(
        self,
        is_active: Optional[bool] = None,
        include_stats: bool = False,
    ) -> list[ScoutWatch]:
        """List all watches with optional stats."""
        pass

    def run_watch(self, watch_id: int) -> ScoutWatchRun:
        """
        Execute a single watch run:
        1. Create run record
        2. Fetch posts from Reddit
        3. Filter by time (last 30 min)
        4. Deduplicate
        5. Enqueue analysis tasks
        """
        pass

    def is_post_seen(self, watch_id: int, external_post_id: str) -> bool:
        """Check if post was already processed."""
        pass

    def record_post(
        self,
        watch_id: int,
        run_id: int,
        external_post_id: str,
    ) -> ScoutWatchPost:
        """Record a post as seen."""
        pass

    def update_post_analysis(
        self,
        watch_id: int,
        external_post_id: str,
        recommendation: str,
        confidence: float,
        lead_id: Optional[int] = None,
    ) -> None:
        """Update post with analysis results."""
        pass
```

---

## UI Components

### Settings > Scout Watches Page

**Location:** `apps/web/src/app/(authenticated)/settings/scout-watches/page.tsx`

```tsx
// Main page showing list of watches
export default function ScoutWatchesPage() {
    // State: watches list, loading, error
    // Actions: add, edit, delete, toggle active, manual run

    return (
        <div>
            <PageHeader>
                <h1>Scout Watches</h1>
                <Button onClick={openAddDialog}>+ Add Watch</Button>
            </PageHeader>

            <WatchesList>
                {watches.map(watch => (
                    <WatchCard
                        key={watch.id}
                        watch={watch}
                        onEdit={...}
                        onDelete={...}
                        onToggle={...}
                        onRun={...}
                    />
                ))}
            </WatchesList>

            <AddWatchDialog open={...} onClose={...} onSave={...} />
        </div>
    );
}
```

### Watch Card Component

```tsx
function WatchCard({ watch, onEdit, onDelete, onToggle, onRun }) {
    return (
        <Card>
            <CardHeader>
                <div className="flex items-center justify-between">
                    <div>
                        <h3>{watch.source_location}</h3>
                        <p className="text-muted-foreground">
                            {watch.search_query || "No search filter"}
                        </p>
                    </div>
                    <Switch
                        checked={watch.is_active}
                        onCheckedChange={onToggle}
                    />
                </div>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-3 gap-4 text-sm">
                    <Stat label="Posts Seen" value={watch.total_posts_seen} />
                    <Stat label="Matches" value={watch.total_matches} />
                    <Stat label="Leads Created" value={watch.total_leads_created} />
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                    Last run: {formatRelativeTime(watch.last_run_at)}
                </div>
            </CardContent>
            <CardFooter>
                <Button variant="outline" size="sm" onClick={onRun}>
                    Run Now
                </Button>
                <Button variant="ghost" size="sm" onClick={onEdit}>
                    Edit
                </Button>
                <Button variant="ghost" size="sm" onClick={onDelete}>
                    Delete
                </Button>
            </CardFooter>
        </Card>
    );
}
```

### Add/Edit Watch Dialog

```tsx
function AddWatchDialog({ open, onClose, onSave, initialData }) {
    const [formData, setFormData] = useState({
        source_location: initialData?.source_location || "",
        search_query: initialData?.search_query || "",
        sort_by: initialData?.sort_by || "new",
        time_filter: initialData?.time_filter || "day",
        auto_analyze: initialData?.auto_analyze ?? true,
        min_confidence: initialData?.min_confidence || 0.7,
    });

    return (
        <Dialog open={open} onOpenChange={onClose}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {initialData ? "Edit Watch" : "Add Watch"}
                    </DialogTitle>
                </DialogHeader>

                <form onSubmit={handleSubmit}>
                    <div className="space-y-4">
                        <Input
                            label="Subreddit"
                            placeholder="r/r4r"
                            value={formData.source_location}
                            onChange={...}
                        />

                        <Textarea
                            label="Search Query (Reddit syntax)"
                            placeholder='flair:F4M AND "looking for"'
                            value={formData.search_query}
                            onChange={...}
                        />

                        <div className="grid grid-cols-2 gap-4">
                            <Select
                                label="Sort By"
                                value={formData.sort_by}
                                options={[
                                    { value: "new", label: "New" },
                                    { value: "hot", label: "Hot" },
                                    { value: "top", label: "Top" },
                                    { value: "rising", label: "Rising" },
                                ]}
                            />
                            <Select
                                label="Time Filter"
                                value={formData.time_filter}
                                options={[
                                    { value: "hour", label: "Past Hour" },
                                    { value: "day", label: "Past 24 Hours" },
                                    { value: "week", label: "Past Week" },
                                ]}
                            />
                        </div>

                        <div className="flex items-center gap-2">
                            <Switch
                                id="auto-analyze"
                                checked={formData.auto_analyze}
                            />
                            <Label htmlFor="auto-analyze">
                                Auto-analyze and create leads
                            </Label>
                        </div>

                        {formData.auto_analyze && (
                            <Slider
                                label="Minimum Confidence"
                                min={0}
                                max={1}
                                step={0.1}
                                value={formData.min_confidence}
                            />
                        )}
                    </div>

                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={onClose}>
                            Cancel
                        </Button>
                        <Button type="submit">Save</Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
```

### Browse Page Integration

Add a button to the Browse page to quickly create a watch from current search:

```tsx
// In browse/page.tsx

function BrowseHeader({ location, searchQuery, sortBy, timeFilter }) {
    const [showAddWatch, setShowAddWatch] = useState(false);

    return (
        <div className="flex items-center justify-between">
            <h1>Browse {location}</h1>

            {searchQuery && (
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowAddWatch(true)}
                >
                    <Eye className="h-4 w-4 mr-2" />
                    Add to Scout Watch
                </Button>
            )}

            <AddWatchDialog
                open={showAddWatch}
                onClose={() => setShowAddWatch(false)}
                initialData={{
                    source_location: location,
                    search_query: searchQuery,
                    sort_by: sortBy,
                    time_filter: timeFilter,
                }}
            />
        </div>
    );
}
```

### Leads Page - Source Filter

Add filter to distinguish manual vs automatic leads:

```tsx
// In leads/page.tsx

<Select
    label="Source"
    value={sourceFilter}
    onChange={setSourceFilter}
    options={[
        { value: "all", label: "All Sources" },
        { value: "manual", label: "Manual" },
        { value: "scout_watch", label: "Scout Watch" },
    ]}
/>

// Lead card shows source badge
<Badge variant={lead.lead_source === "scout_watch" ? "secondary" : "default"}>
    {lead.lead_source === "scout_watch" ? "Auto" : "Manual"}
</Badge>
```

---

## Quick Analysis vs Full Analysis

For Scout Watch, we use a **quick analysis** that only runs the Meta-Analysis agent on the post content alone (without fetching profile data). This is much faster and suitable for initial screening.

```python
class QuickAnalysisService:
    """Lightweight analysis for scout watch screening."""

    async def analyze_post(
        self,
        title: str,
        body: str,
        author_username: str,
    ) -> QuickAnalysisResult:
        """
        Run quick Meta-Analysis on post content only.
        Does NOT fetch profile data - just evaluates the post.

        Returns:
            QuickAnalysisResult with recommendation and confidence.
        """
        # Build minimal input context
        input_context = {
            "lead": {
                "title": title,
                "body": body,
            },
            "profile": {
                "post_text": "",
                "comment_text": "",
                "summary": f"Author: u/{author_username}",
            },
            "items_by_type": {},
        }

        # Run only Meta-Analysis agent
        agent = MetaAnalysisAgent(inference_client=self.client)
        result = await agent.analyze(
            dimension="meta_analysis_quick",
            input_context=input_context,
            prompt=self._get_quick_prompt(),
        )

        return QuickAnalysisResult(
            recommendation=result.get("recommendation"),
            confidence=result.get("confidence", 0.0),
            reasoning=result.get("reasoning", ""),
        )
```

---

## Deduplication Strategy

Posts are deduplicated at multiple levels:

1. **Within Scout Watch** - `scout_watch_posts` table prevents reprocessing
2. **Across Watches** - Different watches can have the same post (intentional)
3. **Lead Creation** - `lead_posts` unique constraint on `(provider_id, external_post_id)` prevents duplicate leads

```python
def run_watch(self, watch_id: int) -> ScoutWatchRun:
    watch = self.get_watch(watch_id)
    run = self.create_run(watch_id)

    # Fetch posts
    posts = self.browse_service.browse_location(
        provider_id=watch.provider_id,
        location=watch.source_location,
        sort=watch.sort_by,
        query=watch.search_query,
        time_filter=watch.time_filter,
        limit=100,
    )

    # Filter by time (last 30 minutes)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    recent_posts = [p for p in posts if p.post_created_at > cutoff]

    # Deduplicate
    new_posts = []
    for post in recent_posts:
        if not self.is_post_seen(watch_id, post.external_post_id):
            self.record_post(watch_id, run.id, post.external_post_id)
            new_posts.append(post)

    # Enqueue analysis tasks
    for post in new_posts:
        analyze_post.delay(watch_id, post.to_dict())

    run.posts_fetched = len(posts)
    run.posts_new = len(new_posts)
    self.db.commit()

    return run
```

---

## File Structure

```
services/core/rediska_core/
├── domain/
│   ├── models/
│   │   └── __init__.py          # Add ScoutWatch, ScoutWatchRun, ScoutWatchPost
│   └── services/
│       ├── scout_watch.py       # NEW: ScoutWatchService
│       └── quick_analysis.py    # NEW: QuickAnalysisService
├── api/
│   ├── routes/
│   │   └── scout_watches.py     # NEW: API endpoints
│   └── schemas/
│       └── scout_watch.py       # NEW: Pydantic schemas
├── alembic/
│   └── versions/
│       └── XXX_add_scout_watch.py  # NEW: Migration

services/worker/rediska_worker/
├── tasks/
│   └── scout.py                 # NEW: Celery tasks
└── celery_app.py                # Update: Add beat schedule + task routes

apps/web/src/app/
├── (authenticated)/
│   ├── settings/
│   │   └── scout-watches/
│   │       └── page.tsx         # NEW: Settings page
│   ├── browse/
│   │   └── page.tsx             # UPDATE: Add "Add to Scout Watch" button
│   └── leads/
│       └── page.tsx             # UPDATE: Add source filter
└── api/core/
    └── scout-watches/
        ├── route.ts             # NEW: Proxy routes
        └── [id]/
            ├── route.ts
            └── run/
                └── route.ts
```

---

## Implementation Order

1. **Database Migration** - Add new tables and columns
2. **Domain Models** - Add ScoutWatch, ScoutWatchRun, ScoutWatchPost to models
3. **Services** - Implement ScoutWatchService and QuickAnalysisService
4. **API Routes** - Create scout_watches.py routes
5. **Celery Tasks** - Implement scout.py tasks
6. **Beat Schedule** - Add periodic task
7. **Next.js Proxy** - Add proxy routes
8. **Settings UI** - Build Scout Watches settings page
9. **Browse Integration** - Add "Add to Scout Watch" button
10. **Leads Filter** - Add source filter to leads page

---

## Acceptance Criteria

- [ ] Users can add/edit/delete scout watches via Settings UI
- [ ] Each watch has its own subreddit + search criteria
- [ ] Watches run automatically every 5 minutes
- [ ] Posts are fetched for the last 30 minutes only
- [ ] Posts are never processed more than once per watch
- [ ] Quick analysis runs on new posts
- [ ] Leads are auto-created for suitable posts (confidence >= threshold)
- [ ] Leads show source (manual vs scout_watch)
- [ ] Browse page has "Add to Scout Watch" button when search is active
- [ ] Run history is viewable per watch
- [ ] Watches can be paused/resumed
- [ ] Manual run can be triggered for testing
