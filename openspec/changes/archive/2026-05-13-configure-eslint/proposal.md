## Why

`npm run lint` in `apps/web/` currently launches an interactive Next.js setup wizard because ESLint has never been configured. The lint command is effectively non-functional: it cannot run in CI, can't be invoked from pre-commit hooks, and developers (including coding agents) skip it. Pre-existing warnings — like the dead `existingMap` Map construction in `inbox/[conversationId]/page.tsx` — go unnoticed.

## What Changes

- Initialize ESLint with the Next.js strict preset (`next/core-web-vitals` + `next/typescript`).
- Add a minimal `.eslintrc.json` under `apps/web/`.
- Run `npm run lint` and resolve any findings on existing files (including the `existingMap` dead-code warning).
- Update `CLAUDE.md` so the "Web Development" section references the now-working lint command.

## Capabilities

### New Capabilities
<!-- None — tooling. -->

### Modified Capabilities
<!-- None. -->

## Impact

- **New file**: `apps/web/.eslintrc.json`.
- **Modified files**: any source touched to resolve a finding (expected to be small — most known issue is the `existingMap` unused variable).
- **CLAUDE.md**: short update under "Web Development" / "Development Commands".
- **No new runtime dependencies** — Next.js already ships the necessary ESLint plugins as transitive deps.
- **Follow-ups unblocked**: pre-commit hook (husky/lint-staged) and CI lint step both become trivial to add later.
