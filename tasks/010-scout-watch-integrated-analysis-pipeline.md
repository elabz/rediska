# Task 010: Scout Watch Integrated Analysis Pipeline

**Priority**: HIGH
**Status**: Pending
**Created**: January 18, 2026

---

## Overview

Refactor the Scout Watch auto-analyze workflow to run the full 6-agent multi-agent analysis pipeline **BEFORE** deciding whether to create a lead. Currently, the system uses a lightweight "quick analysis" and creates leads before fetching profile data. The corrected design fetches profile data, summarizes interests/character, and runs the full analysis to make the lead decision.

**Key Change**: The 6-agent multi-agent analysis now **decides** if a contact is worthy of being a lead, rather than just providing additional information after lead creation.

---

## Design Reference

See updated design: [SCOUT_WATCH_DESIGN.md](./SCOUT_WATCH_DESIGN.md)

---

## What Already Exists

### Fully Implemented (Reuse)
- [x] Scout Watch CRUD (ScoutWatchService)
- [x] Scout Watch API routes
- [x] Scout Watch UI (Settings page)
- [x] Periodic task execution (Celery Beat every 5 min)
- [x] Post deduplication (scout_watch_posts table)
- [x] Multi-agent analysis service (6 agents + coordinator)
- [x] Agent prompt management (CRUD, versioning)
- [x] Profile fetching (Reddit adapter)
- [x] Profile items fetching (posts/comments via adapter)
- [x] Lead creation service
- [x] QuickAnalysisService infrastructure (can be repurposed)

### Needs Modification
- [ ] `scout.py` Celery tasks - change workflow
- [ ] Profile fetching - add limits (20 posts, 100 comments)
- [ ] Multi-agent input context - add summaries
- [ ] scout_watch_posts table - add new columns

### Needs Creation
- [ ] Database migration for new columns
- [ ] InterestsSummaryService
- [ ] CharacterSummaryService
- [ ] Two new agent prompts (scout_interests_summary, scout_character_summary)
- [ ] Updated `analyze_and_decide` task

---

## Implementation Tasks

### Phase 1: Database Schema Update

**Task 1.1**: Create Alembic migration for scout_watch_posts updates

```python
# alembic/versions/XXX_scout_watch_summaries.py

def upgrade():
    # Add new columns to scout_watch_posts
    op.add_column('scout_watch_posts',
        sa.Column('user_interests', sa.Text(), nullable=True))
    op.add_column('scout_watch_posts',
        sa.Column('user_character', sa.Text(), nullable=True))
    op.add_column('scout_watch_posts',
        sa.Column('profile_fetched_at', sa.DateTime(), nullable=True))
    op.add_column('scout_watch_posts',
        sa.Column('analysis_id', sa.BigInteger(), nullable=True))

    # Add foreign key for analysis_id
    op.create_foreign_key(
        'fk_scout_post_analysis',
        'scout_watch_posts', 'lead_analyses',
        ['analysis_id'], ['id']
    )

    # Update analysis_status enum to include new states
    # pending, fetching_profile, summarizing, analyzing, completed, failed
```

**Files to modify**:
- `services/core/alembic/versions/` - new migration file
- `services/core/rediska_core/domain/models/__init__.py` - update ScoutWatchPost model

**AC**:
- [ ] Migration runs without errors
- [ ] New columns visible in database
- [ ] ORM model reflects new fields

---

### Phase 2: Summary Services

**Task 2.1**: Create InterestsSummaryService

```python
# services/core/rediska_core/domain/services/interests_summary.py

class InterestsSummaryService:
    """Summarizes user interests from their Reddit posts."""

    async def summarize(
        self,
        posts: list[ProfileItem],
        max_posts: int = 20,
    ) -> str:
        """
        Analyze up to 20 posts and return a summary of interests.

        Returns:
            Text summary of user's interests, hobbies, activities.
        """
```

**Task 2.2**: Create CharacterSummaryService

```python
# services/core/rediska_core/domain/services/character_summary.py

class CharacterSummaryService:
    """Summarizes user character traits from their Reddit comments."""

    async def summarize(
        self,
        comments: list[ProfileItem],
        max_comments: int = 100,
    ) -> str:
        """
        Analyze up to 100 comments and return character assessment.

        Returns:
            Text summary of communication style and personality traits.
        """
```

**Files to create**:
- `services/core/rediska_core/domain/services/interests_summary.py`
- `services/core/rediska_core/domain/services/character_summary.py`

**AC**:
- [ ] Services use AgentHarness for LLM calls
- [ ] Services load prompts from agent_prompts table
- [ ] Services handle empty input gracefully
- [ ] Services respect post/comment limits

---

### Phase 3: Agent Prompts

**Task 3.1**: Add migration to seed new agent prompts

```python
# Add to migration or create new one

# Interests summary prompt
INSERT INTO agent_prompts (dimension, version, system_prompt, is_active)
VALUES ('scout_interests_summary', 1, '...prompt text...', TRUE);

# Character summary prompt
INSERT INTO agent_prompts (dimension, version, system_prompt, is_active)
VALUES ('scout_character_summary', 1, '...prompt text...', TRUE);
```

**Task 3.2**: Create default prompts in code

```python
# services/core/rediska_core/domain/services/agents/default_prompts.py

SCOUT_INTERESTS_SUMMARY_PROMPT = """
Analyze this Reddit user's posts to understand their interests and activities.

Posts:
{posts_text}

Provide a concise summary (2-3 paragraphs) covering:
1. Main hobbies and activities they engage in
2. Topics they frequently discuss or are passionate about
3. Communities/subreddits they participate in
4. Any notable patterns in their posting behavior

Focus on factual observations from their content. Be objective.
"""

SCOUT_CHARACTER_SUMMARY_PROMPT = """
Analyze this Reddit user's comments to understand their communication style.

Comments:
{comments_text}

Provide a concise summary (2-3 paragraphs) covering:
1. Communication style (friendly, formal, casual, aggressive, etc.)
2. Personality traits evident from interactions
3. How they typically engage with others
4. General emotional tone

Be objective. Base assessment only on content provided.
"""
```

**Files to modify**:
- `services/core/rediska_core/domain/services/agents/default_prompts.py`
- `services/core/alembic/versions/` - migration to seed prompts

**AC**:
- [ ] Prompts seeded in database after migration
- [ ] Prompts editable via Admin UI (/settings/agents)
- [ ] Default prompts defined in code as fallback

---

### Phase 4: Update Profile Fetching

**Task 4.1**: Add fetch limits to Reddit adapter

```python
# services/core/rediska_core/providers/reddit/adapter.py

MAX_PROFILE_POSTS = 20
MAX_PROFILE_COMMENTS = 100

async def fetch_profile_items(
    self,
    user_id: str,
    item_type: str = "overview",  # or "submitted" or "comments"
    limit: int = 100,
    max_items: int | None = None,  # NEW: hard cap
) -> ProfileItemsResult:
    """
    Fetch profile items with optional hard cap.

    When max_items is set, stop fetching even if more pages exist.
    """
```

**Task 4.2**: Create dedicated profile fetch methods

```python
async def fetch_user_posts(self, user_id: str, limit: int = 20) -> list[ProfileItem]:
    """Fetch user's submitted posts (max 20)."""

async def fetch_user_comments(self, user_id: str, limit: int = 100) -> list[ProfileItem]:
    """Fetch user's comments (max 100)."""
```

**Files to modify**:
- `services/core/rediska_core/providers/reddit/adapter.py`

**AC**:
- [ ] Posts limited to 20 maximum
- [ ] Comments limited to 100 maximum
- [ ] Pagination stops when limit reached
- [ ] Existing unlimited behavior unchanged for manual analysis

---

### Phase 5: Update Scout Watch Task

**Task 5.1**: Refactor `analyze_and_decide` task

This is the core change - implement the full pipeline:

```python
# services/worker/rediska_worker/tasks/scout.py

@celery_app.task(
    bind=True,
    name="scout.analyze_and_decide",
    max_retries=3,
    default_retry_delay=120,
)
def analyze_and_decide(self, watch_id: int, post_id: int, post_data: dict) -> dict:
    """
    Full analysis pipeline for a Scout Watch post.

    Steps:
    1. Update status to 'fetching_profile'
    2. Fetch poster's profile (bio, karma, age)
    3. Fetch poster's last 20 posts
    4. Fetch poster's last 100 comments
    5. Update status to 'summarizing'
    6. Generate user_interests summary
    7. Generate user_character summary
    8. Store summaries in scout_watch_posts
    9. Update status to 'analyzing'
    10. Run 6-agent multi-agent analysis
    11. Store analysis results
    12. If suitable + confident: create lead
    13. Update status to 'completed'

    Returns:
        dict with analysis results and lead_id (if created)
    """
```

**Task 5.2**: Update `run_single_watch` to use new pipeline

```python
@celery_app.task(...)
def run_single_watch(self, watch_id: int) -> dict:
    # ... fetch posts, deduplicate ...

    # For each new post, queue FULL analysis (not quick)
    if watch.auto_analyze:
        for post in new_posts:
            analyze_and_decide.delay(
                watch_id=watch_id,
                post_id=scout_post.id,
                post_data=post.to_dict(),
            )
```

**Task 5.3**: Remove or deprecate quick analysis call

The old flow called QuickAnalysisService inline. Remove this:

```python
# REMOVE this block from run_single_watch:
if watch.auto_analyze and new_posts:
    async def analyze_all_posts():
        inference_client = get_inference_client()
        analysis_service = QuickAnalysisService(...)  # <-- REMOVE
        for post in new_posts:
            result = await analysis_service.analyze_post(...)
```

**Files to modify**:
- `services/worker/rediska_worker/tasks/scout.py`

**AC**:
- [ ] Each new post triggers full pipeline task
- [ ] Pipeline fetches profile data BEFORE analysis
- [ ] Pipeline generates interest/character summaries
- [ ] Pipeline runs 6-agent analysis
- [ ] Lead created ONLY if analysis says suitable
- [ ] Quick analysis removed from watch run flow

---

### Phase 6: Update Multi-Agent Analysis Input

**Task 6.1**: Extend input context with summaries

```python
# services/core/rediska_core/domain/services/multi_agent_analysis.py

def _build_input_context(
    self,
    lead: LeadPost | None,
    profile: ProfileSnapshot | None,
    items: list[ProfileItem],
    # NEW parameters:
    user_interests: str | None = None,
    user_character: str | None = None,
) -> dict:
    """Build unified input context for agents."""

    context = {
        "lead": {...},
        "profile": {...},
        "items_by_type": {...},
        # NEW: Add summaries
        "summaries": {
            "user_interests": user_interests or "",
            "user_character": user_character or "",
        },
    }
    return context
```

**Task 6.2**: Create analysis method for scout watch posts

```python
async def analyze_scout_post(
    self,
    scout_post_id: int,
    post_data: dict,
    profile: ProfileSnapshot,
    posts: list[ProfileItem],
    comments: list[ProfileItem],
    user_interests: str,
    user_character: str,
) -> LeadAnalysis:
    """
    Run multi-agent analysis for a scout watch post.

    This is called BEFORE lead creation - the analysis
    determines whether a lead should be created.
    """
```

**Files to modify**:
- `services/core/rediska_core/domain/services/multi_agent_analysis.py`

**AC**:
- [ ] Input context includes summaries section
- [ ] All 6 agents can access user_interests and user_character
- [ ] Analysis can run without existing lead record
- [ ] Analysis result determines lead creation

---

### Phase 7: Update Agent Prompts to Use Summaries

**Task 7.1**: Update dimension agent prompts to reference summaries

The existing agent prompts should be updated to use the new summary fields. This is done via the Admin UI or migration, not code changes.

Example update to Demographics agent prompt:
```
In addition to the post content, you have access to:
- User Interests Summary: {summaries.user_interests}
- User Character Summary: {summaries.user_character}

Use these summaries to inform your demographic analysis...
```

**AC**:
- [ ] Agent prompts updated via Admin UI
- [ ] Prompts reference summaries.user_interests
- [ ] Prompts reference summaries.user_character
- [ ] Template variables work in agent harness

---

### Phase 8: Testing

**Task 8.1**: Unit tests for summary services

```python
# tests/unit/services/test_interests_summary.py
# tests/unit/services/test_character_summary.py
```

**Task 8.2**: Integration test for full pipeline

```python
# tests/integration/test_scout_analysis_pipeline.py

async def test_full_pipeline():
    """Test complete flow from post to lead."""
    # 1. Create watch
    # 2. Mock Reddit API responses
    # 3. Run analyze_and_decide task
    # 4. Verify profile fetched
    # 5. Verify summaries generated
    # 6. Verify 6-agent analysis ran
    # 7. Verify lead created (if suitable)
```

**Task 8.3**: End-to-end test

```python
# tests/e2e/test_scout_watch_e2e.py

def test_scout_watch_creates_lead_automatically():
    """Test that Scout Watch creates leads without manual intervention."""
```

**AC**:
- [ ] Summary services have unit tests
- [ ] Full pipeline has integration test
- [ ] E2E test verifies no manual interaction needed

---

## Dependencies

| Task | Depends On |
|------|------------|
| 2.1, 2.2 (Summary Services) | 1.1 (Migration) |
| 3.1 (Prompt Migration) | 2.1, 2.2 (Services exist) |
| 5.1 (Task Refactor) | 2.1, 2.2, 3.1, 4.1 |
| 6.1 (Input Context) | 2.1, 2.2 |
| 7.1 (Prompt Updates) | 6.1 |
| 8.x (Testing) | All previous |

---

## Implementation Order

1. **Phase 1**: Database migration (new columns)
2. **Phase 2**: Summary services (InterestsSummary, CharacterSummary)
3. **Phase 3**: Agent prompts (seed new prompts)
4. **Phase 4**: Profile fetching (add limits)
5. **Phase 5**: Scout task refactor (main change)
6. **Phase 6**: Multi-agent input context update
7. **Phase 7**: Update agent prompts via UI
8. **Phase 8**: Testing

---

## Files Summary

### New Files
```
services/core/
├── alembic/versions/
│   └── XXX_scout_watch_summaries.py
├── rediska_core/domain/services/
│   ├── interests_summary.py
│   └── character_summary.py

services/core/tests/
├── unit/services/
│   ├── test_interests_summary.py
│   └── test_character_summary.py
├── integration/
│   └── test_scout_analysis_pipeline.py
```

### Modified Files
```
services/core/rediska_core/
├── domain/
│   ├── models/__init__.py              # ScoutWatchPost model
│   └── services/
│       ├── multi_agent_analysis.py     # Input context
│       └── agents/default_prompts.py   # New prompts
├── providers/reddit/
│   └── adapter.py                      # Fetch limits

services/worker/rediska_worker/
└── tasks/
    └── scout.py                        # Main task refactor
```

---

## Acceptance Criteria (Full Task)

- [ ] Scout Watch finds matching posts automatically every 5 minutes
- [ ] For each new post, poster's profile is fetched
- [ ] Poster's last 20 posts are fetched
- [ ] Poster's last 100 comments are fetched
- [ ] User interests summary is generated from posts
- [ ] User character summary is generated from comments
- [ ] Full 6-agent multi-agent analysis runs
- [ ] Analysis receives enriched context (post + profile + summaries)
- [ ] Lead is created ONLY when final_recommendation = "suitable"
- [ ] Lead is created ONLY when confidence >= min_confidence
- [ ] No manual interaction required until leads appear in Leads list
- [ ] Failed analyses retry with exponential backoff
- [ ] Pipeline status visible in Scout Watch settings
- [ ] All new code has test coverage

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| LLM latency (multiple calls per post) | Run summaries in parallel; consider batching |
| Rate limits on Reddit API | Respect existing rate limiting; queue posts |
| Failed summaries block pipeline | Use empty string fallback; continue anyway |
| Analysis takes too long | Set timeouts; mark failed after 5 min |
| Too many posts to analyze | Natural throttling via 5-min interval |

---

## Notes

- The existing QuickAnalysisService can be repurposed for the summary services
- The existing multi-agent analysis infrastructure is fully functional
- Profile fetching already works; just need to add limits
- UI already shows lead source badges (manual vs scout_watch)
