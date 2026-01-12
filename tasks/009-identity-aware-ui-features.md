# Task 009: Identity-Aware UI Features

## Priority: LOW (Enhancement)

## Current State
The UI doesn't fully leverage the identity system:
- Inbox doesn't show/filter by identity
- Ops doesn't show per-identity sync status
- Audit log doesn't filter by identity

## Required Features

### 1. Inbox Identity Features
- Identity indicator on each conversation
- Filter conversations by identity
- Group/sort conversations by identity
- Identity selector when starting new conversation

### 2. Ops Identity Features
- Per-identity sync status
- Per-identity sync button
- Per-identity backfill button
- Identity health indicator (credential status)

### 3. Audit Log Identity Features
- Filter by identity_id
- Show identity info in audit entries

### 4. Global Identity Selector
- Add identity selector to header/sidebar
- Quick switch between identities
- Show current default identity

## UI Components

### IdentityBadge
```tsx
// Shows identity name with provider icon
<IdentityBadge identity={identity} />
```

### IdentitySelector
```tsx
// Dropdown to select/switch identity
<IdentitySelector
  identities={identities}
  selected={selectedId}
  onChange={(id) => ...}
/>
```

### IdentityFilter
```tsx
// Filter control for lists
<IdentityFilter
  identities={identities}
  value={filterId}
  onChange={(id) => ...}
  showAll={true}
/>
```

## Files to Create/Modify

### Create
- `/apps/web/src/components/identity/IdentityBadge.tsx`
- `/apps/web/src/components/identity/IdentitySelector.tsx`
- `/apps/web/src/components/identity/IdentityFilter.tsx`
- `/apps/web/src/hooks/useIdentities.ts`

### Modify
- `/apps/web/src/app/(authenticated)/inbox/page.tsx` - Add filter
- `/apps/web/src/app/(authenticated)/ops/page.tsx` - Add per-identity status
- `/apps/web/src/app/(authenticated)/audit/page.tsx` - Add filter
- `/apps/web/src/components/Sidebar.tsx` or layout - Add global selector

## API Updates Needed

### Add identity_id to responses
- Conversation list should include identity_id
- Audit entries already have identity_id

### Add identity_id filter params
- `GET /conversations?identity_id=X`
- `GET /audit?identity_id=X`

## Acceptance Criteria
- [ ] Conversations show which identity they belong to
- [ ] User can filter inbox by identity
- [ ] Ops shows sync status per identity
- [ ] Audit log can be filtered by identity
- [ ] Identity badge shows provider icon

## Estimated Scope
- Components: ~2 hours
- Inbox updates: ~1 hour
- Ops updates: ~1 hour
- Audit updates: ~30 minutes
- Backend updates: ~1 hour

## Dependencies
- Identity management (implemented)
- Multiple identities created by user

## Related Specs
- Spec Pack v0.4: Section 0.1 (Identity Concept)
- PRD Epics 9.3, 9.6 (Identity-aware UI)
