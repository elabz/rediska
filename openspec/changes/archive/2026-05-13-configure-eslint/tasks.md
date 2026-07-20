## 1. Add config

- [x] 1.1 Create `apps/web/.eslintrc.json` with `{ "extends": ["next/core-web-vitals", "next/typescript"] }`.
- [x] 1.2 Run `npm run lint` from `apps/web/` non-interactively (no wizard prompt). Confirm it executes and produces output.

## 2. Resolve findings

- [x] 2.1 Record the full list of findings.
- [x] 2.2 Run `npm run lint -- --fix` to apply trivial auto-fixes.
- [x] 2.3 Manually fix the pre-existing dead `existingMap` Map construction in `inbox/[conversationId]/page.tsx` (drop the unused `new Map(...)` line in `pollMessages`).
- [x] 2.4 For each remaining finding: either fix it directly, or — if it requires non-trivial work — add an inline `// eslint-disable-next-line <rule>` with a short explanatory comment, and note it in this tasks file as a follow-up.
- [x] 2.5 Confirm `npm run lint` exits clean (zero findings).

## 3. Documentation

- [x] 3.1 Update `CLAUDE.md` "Web Development" section so it references the working `npm run lint` command (currently doesn't mention lint).
- [x] 3.2 Confirm `npm run build` still passes.
