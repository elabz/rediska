## Context

`apps/web/` has `npm run lint` in its `package.json` (which delegates to `next lint`), but no `.eslintrc*` file. On invocation, Next.js prompts the user interactively to pick a preset. Because of the prompt, the command never runs in non-interactive contexts (CI, agent sessions, scripts).

We hit this during `autosave-message-drafts`: `npm run lint` could not be used as a quality gate, and a pre-existing `existingMap` unused-variable warning slipped through because no automated check enforces it. (TypeScript's `noUnusedLocals` is off in `tsconfig.json`, so `tsc` doesn't flag it either.)

## Goals / Non-Goals

**Goals:**
- Make `npm run lint` runnable non-interactively and useful.
- Pick a sensible default rule set without bikeshedding.
- Resolve the small backlog of pre-existing warnings the new config surfaces.

**Non-Goals:**
- Adding Prettier integration in this change.
- Adding pre-commit hooks (separate concern; trivial follow-up).
- Wiring lint into a CI pipeline (depends on `github-action-deployment` or a separate CI change).
- Migrating the whole repo to a stricter rule set (e.g., `no-explicit-any`) — would generate too much noise on existing files.

## Decisions

### Preset: `next/core-web-vitals` + `next/typescript`

- **Chosen**: Both, via `extends`.
- **Rationale**: Strict is the recommended Next.js preset for new apps. It adds `react-hooks/exhaustive-deps` and `react-hooks/rules-of-hooks`, both genuinely useful for this codebase given its heavy hook usage. `next/typescript` layers in the TypeScript-aware rules.
- **Alternative**: `next/core-web-vitals` only (no TypeScript-aware rules). Rejected — most of our findings will be TS-specific.

### Config format: `.eslintrc.json`

- **Chosen**: `.eslintrc.json` (legacy config).
- **Rationale**: Next.js's `next lint` command uses legacy ESLint config discovery in current stable releases. Flat config (`eslint.config.mjs`) is not yet officially supported by `next lint`. Keep it simple and compatible.
- **Re-evaluate later** when Next.js fully supports flat config.

### Auto-fix policy

- Run `npm run lint -- --fix` once to auto-format anything trivial during this change. Going forward, developers run `--fix` at will; no enforcement.

### Resolving findings

- For each finding, prefer **deleting dead code** over disabling the rule. The `existingMap` warning, for example, is dead — the line was leftover from a refactor and the symbol is never read. Just remove it.
- If a rule generates noise on a file that needs careful refactor, add a single-line `// eslint-disable-next-line <rule>` with a short comment explaining why, and open a follow-up. **Do not** add file-level or repo-level disables in this change.

## Risks / Trade-offs

- **Finding volume unknown**: Until we run lint, we don't know how many existing issues will surface. If the count is dramatic (hundreds), we may need to scope this change tighter — perhaps a temporary `overrides` block that downgrades a rule to `warn` for legacy files. Mitigation: run lint first, see, then decide.
- **CI not yet wired up**: This change makes lint useful but doesn't enforce it. That's a deliberate split — enforcement belongs in CI.

## Open Questions

- Should we keep `@next/next/no-img-element` enabled? It's currently being disabled inline in several places via `// eslint-disable-next-line`. Default: keep enabled (it's a real perf hint), accept the inline disables.
