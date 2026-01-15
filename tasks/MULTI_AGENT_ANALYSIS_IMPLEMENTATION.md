# Multi-Agent Lead Analysis Implementation - Task Breakdown

**Status**: Phases 1-4 Complete, Phases 5-7 Ready for Implementation

**Created**: January 12, 2026

---

## Overview

This document outlines the complete implementation of the multi-agent lead analysis system for the Rediska project. The system enables sophisticated multi-dimensional analysis of user profiles using specialized LLM agents that evaluate demographics, preferences, relationship goals, risk factors, and sexual compatibility.

### Key Features

- **6 Specialized Agents**: Demographics, Preferences, Relationship Goals, Risk Flags, Sexual Preferences, and Meta-Analysis Coordinator
- **Database-Backed Prompts**: Versioned prompt storage with runtime editing capability
- **Parallel Execution**: All 5 dimension agents run concurrently for performance
- **Comprehensive Suitability Recommendations**: Final recommendation (suitable/not_recommended/needs_review) with detailed reasoning
- **Full Audit Trail**: All analyses and prompt changes logged

---

## Completed Work (Phases 1-4)

### ✅ Phase 1: Foundation

**Files Created:**
- `services/core/alembic/versions/002_multi_agent_analysis.py` - Database migration with 3 tables
- `services/core/rediska_core/domain/schemas/multi_agent_analysis.py` - 6 Pydantic schemas + response models
- `services/core/rediska_core/domain/models/__init__.py` - ORM models + enums (updated)
- `services/core/rediska_core/domain/services/agent_prompt.py` - Prompt CRUD service
- `services/core/rediska_core/domain/services/agents/default_prompts.py` - 6 comprehensive system prompts

**Deliverables:**
- [x] 3 new database tables: `agent_prompts`, `lead_analyses`, `analysis_dimensions`
- [x] Updated `lead_posts` table with analysis fields
- [x] ORM models for all tables with relationships
- [x] Pydantic schemas for all agent outputs
- [x] AgentPromptService with full CRUD + versioning + rollback
- [x] Default prompts for all 6 agents

**Database Tables:**
```
agent_prompts         - Versioned LLM agent prompts
lead_analyses         - Multi-dimensional analysis results
analysis_dimensions   - Individual dimension execution tracking
lead_posts (updated)  - Added latest_analysis_id, analysis_recommendation, analysis_confidence
```

---

### ✅ Phase 2: Agent Framework & Implementations

**Files Created:**
- `services/core/rediska_core/domain/services/agents/__init__.py` - Base agent framework
- `services/core/rediska_core/domain/services/agents/demographics.py` - Demographics agent
- `services/core/rediska_core/domain/services/agents/agent_implementations.py` - Remaining 5 agents
- `services/core/rediska_core/domain/services/agents/default_prompts.py` - Default prompts

**Deliverables:**
- [x] BaseAnalysisAgent abstract class with common patterns
- [x] 5 specialized dimension agents (demographics, preferences, relationship_goals, risk_flags, sexual_preferences)
- [x] Meta-analysis coordinator agent
- [x] Agent harness integration
- [x] Database result storage for each dimension

**Agent Pattern:**
Each agent inherits from `BaseAnalysisAgent` and implements:
- Input context processing
- LLM agent execution via AgentHarness
- Output validation with Pydantic schemas
- Database result storage

---

### ✅ Phase 3: Core Orchestration Service

**Files Created:**
- `services/core/rediska_core/domain/services/multi_agent_analysis.py` - Main orchestration service

**Deliverables:**
- [x] MultiAgentAnalysisService with complete pipeline
- [x] Parallel dimension agent execution (asyncio.gather)
- [x] Meta-analysis coordination
- [x] Input context building from lead + profile data
- [x] Result aggregation and storage
- [x] Error handling and fallbacks

**Pipeline:**
1. Create analysis record
2. Fetch lead and profile data
3. Build unified input context
4. Run 5 dimension agents in parallel
5. Run meta-analysis coordinator
6. Update lead with final recommendation
7. Return comprehensive analysis

---

### ✅ Phase 4: API Endpoints

**Files Created:**
- `services/core/rediska_core/api/schemas/agent_prompts.py` - Prompt API schemas
- `services/core/rediska_core/api/routes/agent_prompts.py` - Prompt management endpoints
- `services/core/rediska_core/api/routes/leads.py` (updated) - Added 3 analysis endpoints

**API Endpoints Created:**

#### Agent Prompt Management
```
GET    /agent-prompts              - List all agents with active prompts
GET    /agent-prompts/{dimension}  - Get active prompt for dimension
GET    /agent-prompts/{dimension}/versions - List prompt version history
PUT    /agent-prompts/{dimension}  - Update prompt (creates new version)
POST   /agent-prompts/{dimension}/rollback - Rollback to previous version
```

#### Lead Analysis
```
POST   /leads/{id}/analyze-multi   - Run multi-agent analysis
GET    /leads/{id}/analysis        - Get latest analysis
GET    /leads/{id}/analysis/history - Get all analyses for lead
```

**Features:**
- [x] Full CRUD for agent prompts
- [x] Version management with rollback
- [x] Analysis trigger and retrieval
- [x] Analysis history tracking
- [x] Audit logging for all operations

---

## Remaining Work (Phases 5-7)

### 📋 Phase 5: UI Components

**Lead Analysis Display** (`/leads/[id]/page.tsx`)
```
- LeadAnalysisPanel: Main analysis display
  - Overall recommendation badge (suitable/not_recommended/needs_review)
  - Confidence score meter (0.0-1.0)
  - Re-analyze button
  - Analysis status indicator

- DimensionCard (x5): Per-dimension insights
  - Demographics: Age, gender, location, confidence scores
  - Preferences: Hobbies, lifestyle, values, personality traits
  - Relationship Goals: Intent, partner criteria, compatibility factors
  - Risk Flags: Red flags, severity levels, safety assessment
  - Sexual Preferences: Orientation, age preferences, interests

- RecommendationCard: Final recommendation
  - Recommendation text
  - Reasoning explanation
  - Strengths list
  - Concerns list
  - Priority level
  - Suggested approach for contacting

- AnalysisHistory: Previous analyses
  - List with timestamps
  - Re-analysis button per entry
  - Comparison view (optional)
```

**Admin Prompt Management** (`/settings/agents/page.tsx`)
```
- AgentPromptList: All agents
  - Grid of agent cards
  - Active version indicator
  - Last updated timestamp
  - Edit button per agent

- PromptEditor: Monaco editor for system prompt
  - Syntax highlighting
  - Full prompt editing
  - Save creates new version
  - Test with sample data button

- VersionHistory: Prompt versions
  - List with versions
  - Diffs between versions
  - Rollback button
  - View notes for each version
  - Date created, created_by
```

**Files to Create:**
- `apps/web/src/app/(authenticated)/leads/[id]/components/LeadAnalysisPanel.tsx`
- `apps/web/src/app/(authenticated)/leads/[id]/components/DimensionCard.tsx`
- `apps/web/src/app/(authenticated)/leads/[id]/components/RecommendationCard.tsx`
- `apps/web/src/app/(authenticated)/leads/[id]/components/AnalysisHistory.tsx`
- `apps/web/src/app/(authenticated)/settings/agents/page.tsx`
- `apps/web/src/app/(authenticated)/settings/agents/components/AgentPromptList.tsx`
- `apps/web/src/app/(authenticated)/settings/agents/components/PromptEditor.tsx`
- `apps/web/src/app/(authenticated)/settings/agents/components/VersionHistory.tsx`

**Tasks:**
- [ ] Create lead analysis display components
- [ ] Implement dimension card rendering for each agent output
- [ ] Create recommendation display with visual hierarchy
- [ ] Build admin prompt management interface
- [ ] Implement Monaco editor for prompt editing
- [ ] Create version history viewer with diff display
- [ ] Add analysis history timeline
- [ ] Integrate with lead list page (show analysis status badge)

### 📋 Phase 6: Background Task Processing

**Celery Task** (`services/worker/rediska_worker/tasks/multi_agent_analysis.py`)
```python
@celery_app.task(
    bind=True,
    name="multi_agent_analysis.analyze_lead",
    max_retries=3,
    default_retry_delay=300,
)
def analyze_lead_task(self, lead_id: int) -> dict:
    """Background task for multi-agent lead analysis."""
    # Uses jobs table for idempotency
    # Retries with exponential backoff
    # Updates lead_analyses table with progress
```

**Features:**
- [ ] Async analysis execution via Celery
- [ ] Job idempotency using jobs table
- [ ] Exponential backoff retry policy
- [ ] Progress tracking
- [ ] Error notification
- [ ] Batch analysis support

**Tasks:**
- [ ] Create multi_agent_analysis.py task module
- [ ] Implement analyze_lead_task with job tracking
- [ ] Implement batch_analyze_leads task
- [ ] Add task scheduling (beat)
- [ ] Create progress monitoring
- [ ] Add error notifications

### 📋 Phase 7: Testing & Documentation

**Test Coverage:**
```
Unit Tests:
- Agent input/output validation
- Prompt service CRUD operations
- Schema validation
- Error handling

Integration Tests:
- Full analysis pipeline
- Parallel agent execution
- Database persistence
- API endpoint responses
- Celery task execution

E2E Tests:
- Lead analysis workflow
- Prompt editing workflow
- Re-analysis with updated prompts
```

**Files to Create:**
- `services/core/tests/unit/services/test_agent_prompt.py`
- `services/core/tests/unit/services/test_multi_agent_analysis.py`
- `services/core/tests/unit/agents/test_demographics.py` (and 4 more)
- `services/core/tests/integration/test_multi_agent_pipeline.py`
- `services/core/tests/integration/test_api_endpoints.py`
- `apps/web/tests/e2e/lead-analysis.spec.ts`

**Tasks:**
- [ ] Create unit tests for all agents
- [ ] Create integration tests for pipeline
- [ ] Create API endpoint tests
- [ ] Create E2E tests for UI workflows
- [ ] Add test fixtures and mocks
- [ ] Achieve 80%+ code coverage
- [ ] Document testing approach
- [ ] Create README for maintenance

---

## Configuration

### Environment Variables

Add to `.env`:
```bash
# Multi-Agent Analysis
MULTI_AGENT_ANALYSIS_ENABLED=true
MULTI_AGENT_PARALLEL_EXECUTION=true
MULTI_AGENT_TIMEOUT_SECONDS=120
MULTI_AGENT_MIN_DIMENSIONS_FOR_META=3

# LLM Inference (required for analysis to work)
INFERENCE_URL=http://rediska-inference:8000
INFERENCE_MODEL=model_name
INFERENCE_API_KEY=api_key
```

### Database Migration

```bash
# Run migration to create tables
docker compose exec rediska-core alembic upgrade head

# This will create:
# - agent_prompts table with 6 default agents
# - lead_analyses table
# - analysis_dimensions table
# - Updates to lead_posts
```

---

## Integration Points

### Existing Services Used
- **AgentHarness** (`domain/services/agent.py`) - LLM execution framework
- **AuditLog** - All actions logged
- **Jobs Table** - Idempotency for async tasks
- **InferenceClient** - LLM API client
- **ProfileSnapshot** - Cached profile data
- **ProfileItem** - Individual profile items

### API Route Integration
- Prompts endpoint at `/agent-prompts`
- Analysis endpoints at `/leads/{id}/analyze-multi`, etc.
- All endpoints require authentication
- All mutations audit logged

### Database Relationships
```
LeadPost
  ├─ latest_analysis_id → LeadAnalysis
  └─ author_account_id → ExternalAccount

LeadAnalysis
  ├─ lead_id → LeadPost
  ├─ account_id → ExternalAccount
  └─ dimensions → [AnalysisDimension]

AnalysisDimension
  └─ analysis_id → LeadAnalysis

AgentPrompt
  └─ (standalone versioned storage)
```

---

## Success Criteria

### Phase 1-4: Foundation & API ✅ COMPLETED
- [x] Database migration runs successfully
- [x] ORM models defined and relationships correct
- [x] AgentPromptService fully functional
- [x] All 6 agents implemented
- [x] API endpoints created and documented
- [x] MultiAgentAnalysisService orchestrates pipeline

### Phase 5: UI
- [ ] Admin can edit agent prompts via UI
- [ ] Lead detail page displays analysis results
- [ ] Dimension insights are clearly presented
- [ ] Recommendation is highlighted
- [ ] Version history accessible

### Phase 6: Background Tasks
- [ ] Analysis can run asynchronously
- [ ] Idempotency prevents duplicate analysis
- [ ] Progress is trackable
- [ ] Errors are reported

### Phase 7: Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] E2E tests pass
- [ ] 80%+ code coverage achieved

---

## Implementation Order

**Immediate Next Steps:**

1. **Run Migration**
   ```bash
   docker compose exec rediska-core alembic upgrade head
   ```

2. **Create Missing Imports**
   - Ensure agent files export properly
   - Fix any import circular dependencies

3. **Implement Phase 5 (UI)**
   - Start with lead analysis display
   - Then admin prompt editor
   - Add to existing lead list page

4. **Implement Phase 6 (Celery)**
   - Create background task
   - Test idempotency
   - Monitor execution

5. **Implement Phase 7 (Tests)**
   - Write comprehensive test suite
   - Ensure all code paths covered
   - Document testing approach

---

## Critical Files Reference

### Core Files (Completed)
- `alembic/versions/002_multi_agent_analysis.py` - Schema
- `domain/models/__init__.py` - ORM models
- `domain/schemas/multi_agent_analysis.py` - Response schemas
- `domain/services/agent_prompt.py` - Prompt management
- `domain/services/multi_agent_analysis.py` - Orchestration
- `domain/services/agents/__init__.py` - Base framework
- `domain/services/agents/demographics.py` - Demographics agent
- `domain/services/agents/agent_implementations.py` - Remaining agents
- `api/schemas/agent_prompts.py` - API schemas
- `api/routes/agent_prompts.py` - Prompt endpoints
- `api/routes/leads.py` - Analysis endpoints (updated)

### Files to Create (Phase 5-7)
- `apps/web/src/app/(authenticated)/leads/[id]/page.tsx` - Lead detail
- `apps/web/src/app/(authenticated)/settings/agents/page.tsx` - Admin prompt editor
- `services/worker/rediska_worker/tasks/multi_agent_analysis.py` - Celery task
- `tests/` - Comprehensive test suite

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                          User/UI                             │
├──────────────────────┬──────────────────────────────────────┤
│ Prompt Management    │ Lead Analysis Display               │
│ - List agents        │ - Demographics                      │
│ - Edit prompts       │ - Preferences                       │
│ - View history       │ - Relationship goals                │
│ - Rollback version   │ - Risk flags                        │
│                      │ - Sexual preferences                │
│                      │ - Meta-analysis recommendation     │
└──────────────────────┴──────────────────────────────────────┘
         │                              │
         └──────────────┬───────────────┘
                        │
    ┌───────────────────▼────────────────────┐
    │     FastAPI Routes                     │
    │ GET  /agent-prompts                    │
    │ PUT  /agent-prompts/{dim}              │
    │ POST /leads/{id}/analyze-multi         │
    │ GET  /leads/{id}/analysis              │
    └───────────────────┬────────────────────┘
                        │
    ┌───────────────────▼────────────────────┐
    │  Service Layer                         │
    │ - AgentPromptService                   │
    │ - MultiAgentAnalysisService            │
    │ - Individual Agent services            │
    └───────────────────┬────────────────────┘
                        │
    ┌───────────────────┼────────────────────┐
    │                   │                    │
┌───▼────────┐  ┌──────▼──────┐  ┌──────────▼──────┐
│ Database   │  │   LLM       │  │ Parallel        │
│ - Prompts  │  │ Inference   │  │ Agent Execution │
│ - Results  │  │   Client    │  │  via asyncio    │
└────────────┘  └─────────────┘  └─────────────────┘
```

---

## Notes & Considerations

### Performance
- Dimension agents run in parallel for 5x speedup
- Meta-analysis runs after all dimensions complete
- Typical analysis takes 30-60 seconds with LLM inference
- Consider caching profile data across analyses

### Error Handling
- Individual dimension failures don't stop pipeline
- Meta-analysis can proceed with 3/5+ dimensions
- All errors logged to audit trail
- User gets clear error messages

### Security
- All operations require authentication
- All mutations audited
- Prompts can only be edited by admins (add auth check)
- LLM API keys never exposed to client

### Scalability
- Celery allows scaling analysis to background workers
- Database indexes optimize query performance
- JSON storage allows schema flexibility
- Version control enables prompt experimentation

---

## File Organization

```
services/core/
├── alembic/versions/
│   └── 002_multi_agent_analysis.py
├── rediska_core/
│   ├── domain/
│   │   ├── models/
│   │   │   └── __init__.py (updated)
│   │   ├── schemas/
│   │   │   └── multi_agent_analysis.py
│   │   └── services/
│   │       ├── agent_prompt.py
│   │       ├── multi_agent_analysis.py
│   │       └── agents/
│   │           ├── __init__.py
│   │           ├── default_prompts.py
│   │           ├── demographics.py
│   │           └── agent_implementations.py
│   └── api/
│       ├── schemas/
│       │   └── agent_prompts.py
│       └── routes/
│           ├── agent_prompts.py
│           └── leads.py (updated)

services/worker/
└── rediska_worker/
    └── tasks/
        └── multi_agent_analysis.py (TODO)

apps/web/
└── src/app/(authenticated)/
    ├── leads/
    │   ├── [id]/
    │   │   ├── page.tsx (TODO)
    │   │   └── components/
    │   │       ├── LeadAnalysisPanel.tsx (TODO)
    │   │       ├── DimensionCard.tsx (TODO)
    │   │       ├── RecommendationCard.tsx (TODO)
    │   │       └── AnalysisHistory.tsx (TODO)
    │   └── page.tsx (update)
    └── settings/
        └── agents/
            ├── page.tsx (TODO)
            └── components/
                ├── AgentPromptList.tsx (TODO)
                ├── PromptEditor.tsx (TODO)
                └── VersionHistory.tsx (TODO)
```

---

## Deployment Checklist

Before going to production:

- [ ] Database migration tested and verified
- [ ] All API endpoints tested with real leads
- [ ] LLM inference service configured and tested
- [ ] UI components tested with real data
- [ ] Celery tasks configured and monitoring enabled
- [ ] Error handling tested
- [ ] Audit logging verified
- [ ] Performance tested with realistic data volume
- [ ] Security review completed
- [ ] Documentation updated
- [ ] Team trained on new features

---

**Last Updated**: January 12, 2026
**Phase Completion**: 1-4 DONE, 5-7 READY
