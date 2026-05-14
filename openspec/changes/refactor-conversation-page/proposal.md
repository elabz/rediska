## Why

`apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` has grown to ~1700 lines and holds 30+ pieces of state inside a single component. The file mixes: message rendering, compose box, polling, fast-poll machinery, search, image gallery, conversation lists, star/scrub UI, profile panel orchestration, and three confirmation dialogs. Adding the next feature, or even fixing the pre-existing `existingMap` unused-variable warning, requires reading the whole file. We have momentum from `autosave-message-drafts` and a clean baseline; a pre-emptive refactor pays back the next several changes.

## What Changes

- Split the single conversation page into a thin orchestrator plus a tree of focused components and hooks under `inbox/[conversationId]/_components/` and `_hooks/` (Next.js private folders, not routable).
- Move pure utilities (time formatting, send-error explanations, draft helpers) into `_utils/`.
- No behavior changes, no API changes, no spec-level requirement changes.
- Refactor in dependency order, one module per commit, smoke-testing each step.

## Capabilities

### New Capabilities
<!-- None — refactor with no spec-level behavior changes. -->

### Modified Capabilities
<!-- None. -->

## Impact

- **Code**: `apps/web/src/app/(authenticated)/inbox/[conversationId]/page.tsx` split into ~10 smaller files.
- **APIs**: None.
- **Tests**: Existing manual verification checklist from `autosave-message-drafts` doubles as a regression suite — re-run after each extraction step.
- **Dependencies**: None added.
- **Follow-ups unblocked**: `persist-draft-attachments` will be easier to land, future ComposeBox features (rich text, mentions, @-completion) become local concerns.
