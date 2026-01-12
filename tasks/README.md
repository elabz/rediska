# Rediska Tasks

This folder contains discrete task files for implementing remaining features.

## Task Priority Legend
- **HIGH** - Core functionality, blocking other work
- **MEDIUM** - Important feature, can be parallelized
- **LOW** - Enhancement, can be deferred

## Task List

### Bug Fixes
| Task | Title | Priority | Status |
|------|-------|----------|--------|
| 001 | [Fix Conversation Message Pagination](./001-fix-conversation-message-pagination.md) | HIGH | **Complete** |

### Core Features
| Task | Title | Priority | Status |
|------|-------|----------|--------|
| 002 | [Implement Browse Page](./002-implement-browse-page.md) | HIGH | **Complete** |
| 003 | [Implement Leads Page](./003-implement-leads-page.md) | HIGH | **Complete** |
| 004 | [Implement Directories Page](./004-implement-directories-page.md) | MEDIUM | **Complete** |
| 006 | [Implement Profile Page](./006-implement-profile-page.md) | MEDIUM | **Complete** |

### Operations
| Task | Title | Priority | Status |
|------|-------|----------|--------|
| 005 | [Enhance Ops Page](./005-enhance-ops-page.md) | MEDIUM | **Complete** |

### Backend Prerequisites
| Task | Title | Priority | Status |
|------|-------|----------|--------|
| 007 | [Backend API Routes - Directories & Accounts](./007-backend-api-routes-directories-accounts.md) | HIGH | **Complete** |
| 008 | [Backend Browse Endpoint Verification](./008-backend-browse-endpoint.md) | HIGH | **Complete** |

### Enhancements
| Task | Title | Priority | Status |
|------|-------|----------|--------|
| 009 | [Identity-Aware UI Features](./009-identity-aware-ui-features.md) | LOW | **Complete** |

## Recommended Implementation Order

### Phase 1: Prerequisites & Bug Fixes
1. **001** - Fix conversation message pagination (bug affecting users now)
2. **008** - Verify/implement browse endpoint (prerequisite for Browse UI)
3. **007** - Backend directory/account routes (prerequisite for UI)

### Phase 2: Core UI Features
4. **002** - Browse page (entry point for lead discovery)
5. **003** - Leads page (manage saved leads)
6. **004** - Directories page (manage analyzed contacts)
7. **006** - Profile page (view contact details)

### Phase 3: Operations & Enhancements
8. **005** - Enhanced Ops page
9. **009** - Identity-aware UI features

## Implementation Notes

### Existing Implementations (Already Done)
- Search page (`/search`) - Fully functional with hybrid search
- Audit page (`/audit`) - Fully functional with filters
- Inbox page (`/inbox`) - Functional with messaging
- Settings/Identity pages - Functional

### Backend Services Available
- LeadsService - CRUD for leads
- DirectoryService - Analyzed/Contacted/Engaged directories
- BrowseService - Provider location browsing
- AnalysisService - Profile analysis pipeline
- JobService - Job ledger management
- BackupService - Backup/restore functionality

### Frontend Components Available
- UI primitives (Card, Button, Badge, Select, Input, etc.)
- EmptyState component
- Navigation/Sidebar
- Auth handling

## File Naming Convention
```
{3-digit-number}-{short-description}.md
```

## Updating Task Status
When completing a task, update the status in this README:
- Pending → In Progress → Complete
