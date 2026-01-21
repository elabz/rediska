# Scout Watch System Design

## Overview

Scout Watch is an automatic subreddit monitoring system that:
1. Periodically scans configured subreddits for new posts matching search criteria
2. **Fetches poster's profile data** (posts + comments) for context
3. **Summarizes user interests and character traits** from their content
4. **Runs full 6-agent multi-agent analysis** to determine suitability
5. **Automatically creates leads** ONLY for posters that pass analysis
6. Tracks source (manual vs automatic) for all leads

**Key Principle**: The entire pipeline runs automatically with no manual interaction until leads appear in the Leads list.

---

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
```

---

## Complete Analysis Pipeline (Auto-Analyze Workflow)

When `auto_analyze` is enabled for a Scout Watch, matching posts go through this **fully automated pipeline**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Scout Watch Auto-Analyze Pipeline                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  scout.run_all_watches (every 5 minutes)                                 │
│       │                                                                  │
│       └──► For each active watch with auto_analyze=true:                 │
│               │                                                          │
│               └──► scout.run_single_watch(watch_id)                      │
│                       │                                                  │
│                       ├── 1. FETCH POSTS                                 │
│                       │      - Reddit API: search subreddit              │
│                       │      - Filter by time (created_utc > cutoff)     │
│                       │      - Limit: 100 posts per run                  │
│                       │                                                  │
│                       ├── 2. DEDUPLICATE                                 │
│                       │      - Check scout_watch_posts table             │
│                       │      - Skip already-seen posts                   │
│                       │      - Record new posts                          │
│                       │                                                  │
│                       └── 3. For each NEW post, queue analysis:          │
│                              │                                           │
│                              └──► scout.analyze_and_decide(watch_id,     │
│                                                           post_data)     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     scout.analyze_and_decide Task                        │
│                   (Runs for EACH new matching post)                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  STEP 1: FETCH POSTER'S PROFILE DATA                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ► Fetch poster's Reddit profile (bio, karma, account age)           ││
│  │ ► Fetch poster's LAST 20 POSTS (submissions)                        ││
│  │ ► Fetch poster's LAST 100 COMMENTS                                  ││
│  │ ► Store in ProfileSnapshot + ProfileItem tables                     ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                             │                                            │
│                             ▼                                            │
│  STEP 2: SUMMARIZE USER INTERESTS (from posts)                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ► Use LLM to analyze poster's 20 posts                              ││
│  │ ► Extract: hobbies, activities, subreddits frequented, topics       ││
│  │ ► Output: user_interests text field                                 ││
│  │ ► Store in scout_watch_posts.user_interests                         ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                             │                                            │
│                             ▼                                            │
│  STEP 3: SUMMARIZE USER CHARACTER (from comments)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ► Use LLM to analyze poster's 100 comments                          ││
│  │ ► Extract: communication style, personality traits, tone            ││
│  │ ► Traits: friendly, hostile, sarcastic, helpful, aggressive, etc.   ││
│  │ ► Output: user_character text field                                 ││
│  │ ► Store in scout_watch_posts.user_character                         ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                             │                                            │
│                             ▼                                            │
│  STEP 4: RUN 6-AGENT MULTI-AGENT ANALYSIS                                │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ Input Context:                                                      ││
│  │   - Original post (title + body)                                    ││
│  │   - user_interests summary                                          ││
│  │   - user_character summary                                          ││
│  │   - Profile snapshot (bio, karma, account age)                      ││
│  │                                                                     ││
│  │ ► Run 5 dimension agents IN PARALLEL:                               ││
│  │   ├── Demographics Agent (age, gender, location)                    ││
│  │   ├── Preferences Agent (hobbies, lifestyle, values)                ││
│  │   ├── Relationship Goals Agent (intent, partner criteria)           ││
│  │   ├── Risk Flags Agent (red flags, safety assessment)               ││
│  │   └── Sexual Preferences Agent (orientation, interests)             ││
│  │                                                                     ││
│  │ ► Run Meta-Analysis Coordinator:                                    ││
│  │   - Synthesizes all 5 dimension results                             ││
│  │   - Produces final_recommendation: suitable/not_recommended         ││
│  │   - Produces confidence_score: 0.0 - 1.0                            ││
│  │   - Produces reasoning and suggested approach                       ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                             │                                            │
│                             ▼                                            │
│  STEP 5: DECIDE - CREATE LEAD OR NOT                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ IF final_recommendation == "suitable"                               ││
│  │    AND confidence_score >= watch.min_confidence:                    ││
│  │                                                                     ││
│  │    ✓ CREATE LEAD:                                                   ││
│  │      - Create lead_posts record                                     ││
│  │      - Set lead_source = "scout_watch"                              ││
│  │      - Set scout_watch_id = watch.id                                ││
│  │      - Link lead_analyses record                                    ││
│  │      - Update watch stats (leads_created++)                         ││
│  │                                                                     ││
│  │ ELSE:                                                               ││
│  │    ✗ DO NOT CREATE LEAD                                             ││
│  │      - Post remains in scout_watch_posts for tracking               ││
│  │      - Analysis results stored for audit                            ││
│  │      - Update watch stats (posts_analyzed++)                        ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ► Lead appears in Leads list - ready for user review                    │
│  ► No manual interaction required until this point                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Profile Data Limits

To balance thoroughness with API rate limits and processing time:

| Data Type | Limit | Rationale |
|-----------|-------|-----------|
| Posts (submissions) | **20** | Enough to understand interests without overwhelming |
| Comments | **100** | Sufficient to assess character/communication style |
| Profile bio | Full | Always fetched |
| Karma/account age | Full | Always fetched |

These limits are **hardcoded constants** in the analysis task:

```python
# services/worker/rediska_worker/tasks/scout.py
MAX_PROFILE_POSTS = 20
MAX_PROFILE_COMMENTS = 100
```

---

## New Database Fields

### scout_watch_posts Table (Updated)

```sql
ALTER TABLE scout_watch_posts ADD COLUMN user_interests TEXT;
ALTER TABLE scout_watch_posts ADD COLUMN user_character TEXT;
ALTER TABLE scout_watch_posts ADD COLUMN profile_fetched_at DATETIME;
ALTER TABLE scout_watch_posts ADD COLUMN analysis_id BIGINT;
ALTER TABLE scout_watch_posts ADD FOREIGN KEY (analysis_id) REFERENCES lead_analyses(id);
```

| Column | Type | Description |
|--------|------|-------------|
| `user_interests` | TEXT | LLM-summarized interests from poster's posts |
| `user_character` | TEXT | LLM-summarized character traits from comments |
| `profile_fetched_at` | DATETIME | When profile data was fetched |
| `analysis_id` | BIGINT FK | Link to full multi-agent analysis result |

---

## Summary Services

Two new LLM-powered summarization services extract structured insights:

### InterestsSummaryService

Analyzes a user's posts to extract their interests, hobbies, and activities.

**Input**: Up to 20 posts (title + body + subreddit)
**Output**: `user_interests` text summary

**Prompt (stored in `agent_prompts` as `scout_interests_summary`):**
```
Analyze this Reddit user's posts to understand their interests and activities.

Posts:
{posts_text}

Provide a concise summary (2-3 paragraphs) covering:
1. Main hobbies and activities they engage in
2. Topics they frequently discuss or are passionate about
3. Communities/subreddits they participate in
4. Any notable patterns in their posting behavior

Focus on factual observations from their content. Be objective.
```

### CharacterSummaryService

Analyzes a user's comments to assess their communication style and personality.

**Input**: Up to 100 comments (body + context)
**Output**: `user_character` text summary

**Prompt (stored in `agent_prompts` as `scout_character_summary`):**
```
Analyze this Reddit user's comments to understand their communication style and personality.

Comments:
{comments_text}

Provide a concise summary (2-3 paragraphs) covering:
1. Communication style (friendly, formal, casual, aggressive, etc.)
2. Personality traits evident from interactions (helpful, critical, supportive, etc.)
3. How they typically engage with others (constructive, confrontational, etc.)
4. General emotional tone (positive, negative, neutral, sarcastic, etc.)

Be objective and base your assessment only on the content provided.
Avoid assumptions beyond what's evident in the text.
```

---

## Database Schema

### Complete Schema (Updated)

#### `scout_watches` - Watch configurations

```sql
CREATE TABLE scout_watches (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- Provider and location
    provider_id VARCHAR(50) NOT NULL DEFAULT 'reddit',
    source_location VARCHAR(255) NOT NULL,  -- e.g., "r/r4r"

    -- Search criteria (matches Browse page params)
    search_query TEXT,                       -- Reddit search syntax
    sort_by VARCHAR(20) DEFAULT 'new',       -- hot, new, top, rising
    time_filter VARCHAR(20) DEFAULT 'day',   -- hour, day, week, month, year, all

    -- Identity to use for API calls
    identity_id BIGINT,
    FOREIGN KEY (identity_id) REFERENCES identities(id),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Analysis settings
    auto_analyze BOOLEAN DEFAULT TRUE,       -- Run full pipeline on matches
    min_confidence FLOAT DEFAULT 0.7,        -- Minimum confidence to create lead

    -- Stats (denormalized for performance)
    total_posts_seen INT DEFAULT 0,
    total_posts_analyzed INT DEFAULT 0,
    total_leads_created INT DEFAULT 0,

    -- Timestamps
    last_run_at DATETIME,
    last_match_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Constraints
    INDEX idx_active (is_active, last_run_at)
);
```

#### `scout_watch_runs` - Run history

```sql
CREATE TABLE scout_watch_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    watch_id BIGINT NOT NULL,
    FOREIGN KEY (watch_id) REFERENCES scout_watches(id) ON DELETE CASCADE,

    -- Run details
    started_at DATETIME NOT NULL,
    completed_at DATETIME,

    -- Results
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    posts_fetched INT DEFAULT 0,
    posts_new INT DEFAULT 0,           -- Not seen before
    posts_analyzed INT DEFAULT 0,      -- Full pipeline completed
    leads_created INT DEFAULT 0,

    -- Error tracking
    error_message TEXT,
    search_url TEXT,                   -- Browser-friendly Reddit URL

    INDEX idx_watch_runs (watch_id, started_at DESC)
);
```

#### `scout_watch_posts` - Post tracking with summaries

```sql
CREATE TABLE scout_watch_posts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    watch_id BIGINT NOT NULL,
    FOREIGN KEY (watch_id) REFERENCES scout_watches(id) ON DELETE CASCADE,

    -- Post identification
    external_post_id VARCHAR(100) NOT NULL,
    post_title TEXT,
    post_author VARCHAR(100),

    -- Tracking
    first_seen_at DATETIME NOT NULL,
    run_id BIGINT,
    FOREIGN KEY (run_id) REFERENCES scout_watch_runs(id),

    -- Profile data (fetched for analysis)
    profile_fetched_at DATETIME,
    user_interests TEXT,               -- LLM summary of poster's interests
    user_character TEXT,               -- LLM summary of poster's character

    -- Analysis result
    analysis_status ENUM('pending', 'fetching_profile', 'summarizing',
                         'analyzing', 'completed', 'failed') DEFAULT 'pending',
    analysis_id BIGINT,
    FOREIGN KEY (analysis_id) REFERENCES lead_analyses(id),
    analysis_recommendation VARCHAR(50),    -- suitable, not_recommended
    analysis_confidence FLOAT,
    analysis_reasoning TEXT,

    -- Lead creation (if approved by analysis)
    lead_id BIGINT,
    FOREIGN KEY (lead_id) REFERENCES lead_posts(id),

    -- Constraints
    UNIQUE KEY idx_watch_post (watch_id, external_post_id),
    INDEX idx_status (watch_id, analysis_status)
);
```

---

## Celery Tasks

### Task Definitions

```python
# services/worker/rediska_worker/tasks/scout.py

# Profile limits
MAX_PROFILE_POSTS = 20
MAX_PROFILE_COMMENTS = 100


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
    1. Fetch posts from Reddit
    2. Deduplicate against scout_watch_posts
    3. For each new post: queue full analysis pipeline
    """
    pass


@app.task(name="scout.analyze_and_decide", bind=True)
def analyze_and_decide(self, watch_id: int, post_data: dict) -> dict:
    """
    Full analysis pipeline for a single post:

    1. Fetch poster's profile (bio, karma, account age)
    2. Fetch poster's last 20 posts
    3. Fetch poster's last 100 comments
    4. Summarize user_interests from posts
    5. Summarize user_character from comments
    6. Run 6-agent multi-agent analysis
    7. If suitable + confident: create lead
    8. Update scout_watch_posts with results

    This is the ONLY place where lead creation happens for scout watches.
    The decision is made by the multi-agent analysis, not by quick screening.
    """
    pass
```

### Beat Schedule

```python
# In celery_app.py beat_schedule

"scout-watch-periodic": {
    "task": "scout.run_all_watches",
    "schedule": 300.0,  # Every 5 minutes
},
```

---

## Agent Prompts

Two new agent prompts for the summary stages:

### scout_interests_summary

Stored in `agent_prompts` table, dimension = `scout_interests_summary`

Purpose: Summarize user interests from their posts

### scout_character_summary

Stored in `agent_prompts` table, dimension = `scout_character_summary`

Purpose: Summarize user character from their comments

These are **separate from the quick analysis prompt** and serve as input to the full 6-agent analysis.

---

## Input Context for Multi-Agent Analysis

When running the 6-agent analysis for scout watch posts, the input context is enriched:

```python
input_context = {
    "lead": {
        "title": post_title,
        "body": post_body,
        "subreddit": source_location,
        "flair": post_flair,
        "created_utc": post_created_at,
    },
    "profile": {
        "username": author_username,
        "bio": profile_bio,
        "karma": profile_karma,
        "account_age_days": account_age,
        "verified": is_verified,
    },
    "summaries": {
        "user_interests": user_interests_summary,   # From posts
        "user_character": user_character_summary,   # From comments
    },
    "items_by_type": {
        "posts": [...],      # Raw posts data (up to 20)
        "comments": [...],   # Raw comments data (up to 100)
    },
}
```

---

## UI Components

### Settings > Scout Watches Page

**Location:** `apps/web/src/app/(authenticated)/settings/scout-watches/page.tsx`

```tsx
// Main page showing list of watches
export default function ScoutWatchesPage() {
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

### Watch Card with Pipeline Status

```tsx
function WatchCard({ watch }) {
    return (
        <Card>
            <CardHeader>
                <h3>{watch.source_location}</h3>
                <p>{watch.search_query || "No search filter"}</p>
                <Switch checked={watch.is_active} />
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-3 gap-4">
                    <Stat label="Posts Seen" value={watch.total_posts_seen} />
                    <Stat label="Analyzed" value={watch.total_posts_analyzed} />
                    <Stat label="Leads Created" value={watch.total_leads_created} />
                </div>
                {watch.auto_analyze && (
                    <Badge variant="outline">
                        Auto-Analyze Enabled (min {watch.min_confidence * 100}% confidence)
                    </Badge>
                )}
            </CardContent>
        </Card>
    );
}
```

### Leads Page - Source Badge

Leads created by Scout Watch show their source:

```tsx
<Badge variant={lead.lead_source === "scout_watch" ? "secondary" : "default"}>
    {lead.lead_source === "scout_watch" ? "Auto" : "Manual"}
</Badge>
```

---

## Deduplication Strategy

Posts are deduplicated at multiple levels:

1. **Within Scout Watch** - `scout_watch_posts` table prevents reprocessing
2. **Across Watches** - Different watches can see the same post (intentional)
3. **Lead Creation** - Duplicate leads prevented by unique constraint on `external_post_id`

---

## Error Handling

The pipeline handles errors gracefully:

| Stage | Error Handling |
|-------|---------------|
| Profile Fetch | Retry 3x, then mark post as failed |
| Interests Summary | Use empty string, continue pipeline |
| Character Summary | Use empty string, continue pipeline |
| Agent Execution | Individual agent failure doesn't stop others |
| Meta-Analysis | Requires 3/5 dimension results minimum |
| Lead Creation | Idempotent, safe to retry |

---

## File Structure

```
services/core/rediska_core/
├── domain/
│   ├── models/
│   │   └── __init__.py          # ScoutWatch, ScoutWatchRun, ScoutWatchPost
│   └── services/
│       ├── scout_watch.py       # ScoutWatchService
│       ├── interests_summary.py # InterestsSummaryService (NEW)
│       ├── character_summary.py # CharacterSummaryService (NEW)
│       └── multi_agent_analysis.py
├── api/
│   ├── routes/
│   │   └── scout_watches.py     # API endpoints
│   └── schemas/
│       └── scout_watch.py       # Pydantic schemas
├── alembic/
│   └── versions/
│       └── XXX_update_scout_watch_summaries.py  # Migration

services/worker/rediska_worker/
├── tasks/
│   └── scout.py                 # Updated tasks with full pipeline
└── celery_app.py                # Beat schedule

apps/web/src/app/
├── (authenticated)/
│   ├── settings/
│   │   └── scout-watches/
│   │       └── page.tsx         # Settings page
│   └── leads/
│       └── page.tsx             # Shows source badge
└── api/core/
    └── scout-watches/
        └── ...                  # Proxy routes
```

---

## Implementation Order

1. **Database Migration** - Add new columns to scout_watch_posts
2. **Summary Services** - Create InterestsSummaryService, CharacterSummaryService
3. **Agent Prompts** - Add scout_interests_summary, scout_character_summary prompts
4. **Update analyze_and_decide Task** - Implement full pipeline
5. **Update Profile Fetching** - Add limits (20 posts, 100 comments)
6. **Update Multi-Agent Input** - Include summaries in context
7. **UI Updates** - Show pipeline status and source badges
8. **Testing** - End-to-end pipeline testing

---

## Acceptance Criteria

- [ ] Scout Watch finds matching posts automatically
- [ ] Poster's last 20 posts are fetched
- [ ] Poster's last 100 comments are fetched
- [ ] User interests are summarized from posts
- [ ] User character is summarized from comments
- [ ] Full 6-agent analysis runs with enriched context
- [ ] Leads are created ONLY when analysis says "suitable"
- [ ] Leads show source (manual vs scout_watch)
- [ ] No manual interaction required until leads appear
- [ ] Pipeline status is visible in Scout Watch settings
- [ ] Failed analyses are retried with exponential backoff

---

## Key Differences from Previous Design

| Aspect | Previous Design | Current Design |
|--------|-----------------|----------------|
| **Profile Fetch** | After lead creation | Before lead decision |
| **Lead Decision** | Quick analysis (post only) | Full 6-agent analysis |
| **Posts Fetched** | Unlimited | Limited to 20 |
| **Comments Fetched** | Unlimited | Limited to 100 |
| **Summary Fields** | None | user_interests, user_character |
| **Analysis Input** | Post title + body only | Post + profile + summaries |
| **Automation** | Semi-automated | Fully automated |
