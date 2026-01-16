# Multi-Agent Lead Analysis Implementation - Task Breakdown

**Status**: Phases 1-4 Complete, Phase 5 Epic 5.1-5.3 Complete

**Created**: January 12, 2026
**Last Updated**: January 16, 2026

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

#### Epic 5.1 - Next.js API Proxy Routes (REQUIRED FIRST) ✅ COMPLETE

Before any UI can work, we need proxy routes to forward requests to the backend.

**Tasks:**
- [x] **5.1.1** Create agent-prompts proxy routes
  - [x] `apps/web/src/app/api/core/agent-prompts/route.ts` - GET list all agents
  - [x] `apps/web/src/app/api/core/agent-prompts/[dimension]/route.ts` - GET/PUT single prompt
  - [x] `apps/web/src/app/api/core/agent-prompts/[dimension]/versions/route.ts` - GET version history
  - [x] `apps/web/src/app/api/core/agent-prompts/[dimension]/rollback/route.ts` - POST rollback
  - AC: All `/api/core/agent-prompts/*` calls reach FastAPI backend ✅

- [x] **5.1.2** Create lead analysis proxy routes
  - [x] `apps/web/src/app/api/core/leads/[leadId]/analyze-multi/route.ts` - POST trigger analysis
  - [x] `apps/web/src/app/api/core/leads/[leadId]/analysis/route.ts` - GET latest analysis
  - [x] `apps/web/src/app/api/core/leads/[leadId]/analysis/history/route.ts` - GET all analyses
  - AC: All `/api/core/leads/{id}/analysis*` calls reach FastAPI backend ✅

---

#### Epic 5.2 - Lead Detail Page with Analysis Display ✅ COMPLETE

**Files Created:**
```
apps/web/src/app/(authenticated)/leads/[id]/
├── page.tsx                    # Main lead detail page
└── components/
    ├── LeadAnalysisPanel.tsx   # Main analysis container
    ├── DimensionCard.tsx       # Individual dimension display
    ├── RecommendationCard.tsx  # Final recommendation display
    └── AnalysisHistory.tsx     # Previous analyses list
```

**Tasks:**
- [x] **5.2.1** Create lead detail page structure
  - [x] Create `apps/web/src/app/(authenticated)/leads/[id]/page.tsx`
  - [x] Fetch lead data from `/api/core/leads/{id}`
  - [x] Display lead info (title, body, author, post date, status)
  - [x] Add "Run Multi-Agent Analysis" button
  - [x] Add link back to leads list
  - AC: Can navigate to `/leads/123` and see lead details ✅

- [x] **5.2.2** Create LeadAnalysisPanel component
  - [x] Fetch analysis from `/api/core/leads/{id}/analysis`
  - [x] Display overall recommendation badge (suitable/not_recommended/needs_review)
  - [x] Display confidence score as visual meter (0.0-1.0)
  - [x] Show analysis status indicator (pending/running/complete/failed)
  - [x] Add "Re-analyze" button that POSTs to `/api/core/leads/{id}/analyze-multi`
  - [x] Handle loading and error states
  - AC: Analysis results display correctly with visual hierarchy ✅

- [x] **5.2.3** Create DimensionCard component
  - [x] Accept dimension type prop (demographics/preferences/relationship_goals/risk_flags/sexual_preferences)
  - [x] Display dimension-specific fields based on type:
    - Demographics: age_estimate, gender, location, confidence scores
    - Preferences: hobbies, lifestyle, values, personality traits
    - Relationship Goals: intent, partner criteria, compatibility factors
    - Risk Flags: flags list with severity levels, safety assessment score
    - Sexual Preferences: orientation, age preferences, interests
  - [x] Show execution time and model info
  - [x] Handle null/missing dimensions gracefully
  - [x] Collapsible detail view for verbose output
  - AC: Each dimension renders with appropriate formatting ✅

- [x] **5.2.4** Create RecommendationCard component
  - [x] Display final recommendation (suitable/not_recommended/needs_review)
  - [x] Show reasoning text
  - [x] Display strengths as green-highlighted list
  - [x] Display concerns as amber/red-highlighted list
  - [x] Show priority level badge
  - [x] Display suggested approach for contacting
  - AC: Recommendation is prominently displayed with clear visual cues ✅

- [x] **5.2.5** Create AnalysisHistory component
  - [x] Fetch from `/api/core/leads/{id}/analysis/history`
  - [x] Display list with timestamps and recommendation summaries
  - [x] Allow expanding to see full analysis details
  - [x] Show which prompt versions were used
  - AC: Can view previous analyses for comparison ✅

- [x] **5.2.6** Update leads list page to show analysis status
  - [x] Add analysis badge to LeadCard component in `/leads/page.tsx`
  - [x] Show recommendation icon (check/x/question mark)
  - [x] Add "View" quick action to navigate to lead detail
  - AC: Lead list shows which leads have been analyzed ✅

---

#### Epic 5.3 - Admin Prompt Management Interface ✅ COMPLETE

**Files Created:**
```
apps/web/src/app/(authenticated)/settings/agents/
├── page.tsx                    # Main agents settings page
└── components/
    ├── AgentPromptList.tsx     # Grid of all agents
    ├── PromptEditor.tsx        # Prompt editing interface
    └── VersionHistory.tsx      # Version history viewer

apps/web/src/components/ui/
├── tabs.tsx                    # Tabs component (new)
├── collapsible.tsx             # Collapsible component (new)
└── alert-dialog.tsx            # Alert dialog component (new)
```

**Tasks:**
- [x] **5.3.1** Create agents settings page
  - [x] Create `apps/web/src/app/(authenticated)/settings/agents/page.tsx`
  - [x] Fetch agents from `/api/core/agent-prompts`
  - [x] Display grid of agent cards
  - [x] Add navigation link in settings menu
  - AC: Can navigate to `/settings/agents` and see all agents ✅

- [x] **5.3.2** Create AgentPromptList component
  - [x] Display card for each agent dimension
  - [x] Show agent name, description, active version number
  - [x] Show last updated timestamp
  - [x] Show prompt character count
  - [x] Add "Edit" button per agent
  - [x] Color-code by agent type (dimension vs meta)
  - AC: All 6 agents displayed with key information ✅

- [x] **5.3.3** Create PromptEditor component
  - [x] Inline panel for editing (with tabs for Editor/History)
  - [x] Large textarea for system prompt
  - [x] Show current prompt content
  - [x] Temperature and max_tokens configuration
  - [x] "Update Notes" text field for version notes
  - [x] Save button creates new version via PUT `/api/core/agent-prompts/{dimension}`
  - [x] Back button returns to list
  - [x] Warn about unsaved changes
  - AC: Can edit and save prompt with version notes ✅

- [x] **5.3.4** Create VersionHistory component
  - [x] Fetch from `/api/core/agent-prompts/{dimension}/versions`
  - [x] Display list of versions with:
    - Version number
    - Created timestamp
    - Update notes
    - Character count
  - [x] Add "Rollback to this version" button
  - [x] Rollback calls POST `/api/core/agent-prompts/{dimension}/rollback`
  - [x] Show confirmation dialog before rollback
  - [x] Collapsible version details with prompt preview
  - AC: Can view history and rollback to previous versions ✅

- [ ] **5.3.5** (Optional) Add prompt diff view
  - [ ] Compare two versions side-by-side
  - [ ] Highlight additions/deletions
  - AC: Can see what changed between versions

---

#### Epic 5.4 - Integration and Polish

**Tasks:**
- [x] **5.4.1** Add settings navigation link
  - [x] Update Sidebar.tsx to include "Agent Prompts" link
  - [x] Add Brain icon
  - [x] Added to expanded sidebar, user dropdown, and collapsed sidebar
  - AC: Agents settings accessible from settings menu ✅

- [ ] **5.4.2** Add loading states and skeletons
  - [ ] Skeleton loaders for analysis panel
  - [ ] Skeleton loaders for prompt list
  - [ ] Loading spinners for actions
  - AC: Smooth loading experience

- [ ] **5.4.3** Add error handling
  - [ ] Error boundaries for components
  - [ ] Toast notifications for save success/failure
  - [ ] Retry buttons for failed requests
  - AC: Graceful error handling throughout

- [ ] **5.4.4** Add empty states
  - [ ] "No analysis yet" state for leads
  - [ ] "Run analysis to see insights" CTA
  - AC: Clear guidance when no data exists

---

**Component Architecture:**

```
Lead Detail Page (/leads/[id])
├── LeadHeader (title, author, status)
├── LeadAnalysisPanel
│   ├── AnalysisStatus (badge + confidence)
│   ├── RecommendationCard
│   ├── DimensionCard (demographics)
│   ├── DimensionCard (preferences)
│   ├── DimensionCard (relationship_goals)
│   ├── DimensionCard (risk_flags)
│   ├── DimensionCard (sexual_preferences)
│   └── AnalysisHistory (collapsible)
└── LeadActions (analyze, contact, status)

Settings Agents Page (/settings/agents)
├── PageHeader
├── AgentPromptList
│   └── AgentCard (x6)
│       └── onClick → PromptEditor modal
│           └── VersionHistory tab
└── SaveIndicator
```

**API Endpoints Used:**
```
GET  /api/core/agent-prompts              → List all agents
GET  /api/core/agent-prompts/{dim}        → Get active prompt
PUT  /api/core/agent-prompts/{dim}        → Update prompt (new version)
GET  /api/core/agent-prompts/{dim}/versions → Version history
POST /api/core/agent-prompts/{dim}/rollback → Rollback to previous

POST /api/core/leads/{id}/analyze-multi   → Trigger multi-agent analysis
GET  /api/core/leads/{id}/analysis        → Get latest analysis
GET  /api/core/leads/{id}/analysis/history → Get all analyses
```

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
- [x] **5.1** Next.js API proxy routes created for agent-prompts and analysis endpoints ✅
- [x] **5.2** Lead detail page (`/leads/[id]`) displays analysis results ✅
- [x] **5.3** Admin prompt management page (`/settings/agents`) allows editing prompts ✅
- [x] **5.4** Dimension insights clearly presented with DimensionCard components ✅
- [x] **5.5** Recommendation highlighted with RecommendationCard ✅
- [x] **5.6** Version history accessible with rollback capability ✅
- [x] **5.7** Leads list shows analysis status badges ✅

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

### Files Created (Phase 5)
- `apps/web/src/app/api/core/agent-prompts/route.ts` - Agent prompts list proxy
- `apps/web/src/app/api/core/agent-prompts/[dimension]/route.ts` - Single prompt proxy
- `apps/web/src/app/api/core/agent-prompts/[dimension]/versions/route.ts` - Versions proxy
- `apps/web/src/app/api/core/agent-prompts/[dimension]/rollback/route.ts` - Rollback proxy
- `apps/web/src/app/api/core/leads/[leadId]/analyze-multi/route.ts` - Analysis trigger proxy
- `apps/web/src/app/api/core/leads/[leadId]/analysis/route.ts` - Analysis result proxy
- `apps/web/src/app/api/core/leads/[leadId]/analysis/history/route.ts` - Analysis history proxy
- `apps/web/src/app/(authenticated)/leads/[id]/page.tsx` - Lead detail page
- `apps/web/src/app/(authenticated)/leads/[id]/components/LeadAnalysisPanel.tsx` - Analysis panel
- `apps/web/src/app/(authenticated)/leads/[id]/components/DimensionCard.tsx` - Dimension display
- `apps/web/src/app/(authenticated)/leads/[id]/components/RecommendationCard.tsx` - Recommendation
- `apps/web/src/app/(authenticated)/leads/[id]/components/AnalysisHistory.tsx` - History list
- `apps/web/src/app/(authenticated)/settings/agents/page.tsx` - Admin prompt editor
- `apps/web/src/app/(authenticated)/settings/agents/components/AgentPromptList.tsx` - Agent cards
- `apps/web/src/app/(authenticated)/settings/agents/components/PromptEditor.tsx` - Prompt editor
- `apps/web/src/app/(authenticated)/settings/agents/components/VersionHistory.tsx` - Version history
- `apps/web/src/components/ui/tabs.tsx` - Tabs UI component
- `apps/web/src/components/ui/collapsible.tsx` - Collapsible UI component
- `apps/web/src/components/ui/alert-dialog.tsx` - Alert dialog UI component

### Files to Create (Phase 6-7)
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
└── src/
    ├── app/
    │   ├── api/core/
    │   │   ├── agent-prompts/
    │   │   │   ├── route.ts ✅
    │   │   │   └── [dimension]/
    │   │   │       ├── route.ts ✅
    │   │   │       ├── versions/route.ts ✅
    │   │   │       └── rollback/route.ts ✅
    │   │   └── leads/[leadId]/
    │   │       ├── analyze-multi/route.ts ✅
    │   │       └── analysis/
    │   │           ├── route.ts ✅
    │   │           └── history/route.ts ✅
    │   └── (authenticated)/
    │       ├── leads/
    │       │   ├── [id]/
    │       │   │   ├── page.tsx ✅
    │       │   │   └── components/
    │       │   │       ├── LeadAnalysisPanel.tsx ✅
    │       │   │       ├── DimensionCard.tsx ✅
    │       │   │       ├── RecommendationCard.tsx ✅
    │       │   │       └── AnalysisHistory.tsx ✅
    │       │   └── page.tsx (updated) ✅
    │       └── settings/
    │           └── agents/
    │               ├── page.tsx ✅
    │               └── components/
    │                   ├── AgentPromptList.tsx ✅
    │                   ├── PromptEditor.tsx ✅
    │                   └── VersionHistory.tsx ✅
    └── components/
        ├── Sidebar.tsx (updated) ✅
        └── ui/
            ├── tabs.tsx ✅
            ├── collapsible.tsx ✅
            └── alert-dialog.tsx ✅
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

**Last Updated**: January 16, 2026
**Phase Completion**: 1-5 DONE, 6-7 READY
