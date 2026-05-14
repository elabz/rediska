## 1. Scaffolding

- [x] 1.1 Create `docs/` directory at the repo root.
- [x] 1.2 Create `docs/deploy.md` with a top-level outline (Prerequisites → Bootstrap → First Boot → Smoke Test → Data Migration → Troubleshooting → Appendix).
- [x] 1.3 Create `scripts/deploy/` directory.

## 2. Prerequisites section

- [x] 2.1 Document target OS expectations (Ubuntu 22.04 LTS or Debian 12; other systemd Linux distros likely fine).
- [x] 2.2 List hardware minimums (CPU/RAM/disk; ES needs ≥1GB heap).
- [x] 2.3 List required software to install before clone (Docker Engine + compose plugin, git, openssl, optionally mkcert on the operator's workstation).
- [x] 2.4 Document the VPN reachability assumption and how to confirm it (`ssh user@server` succeeds, `ping rediska.internal` resolves).
- [x] 2.5 Document the `/etc/hosts` entry pattern for the internal hostname.

## 3. Bootstrap section

- [x] 3.1 Document Docker install + verification commands.
- [x] 3.2 Document creating `/var/lib/rediska/{attachments,backups}` with correct ownership.
- [x] 3.3 Document cloning the repo (recommend `/opt/rediska`) and ownership.
- [x] 3.4 Document creating `.env` from `.env.example`; list each variable that MUST be set vs. has a sensible default.
- [x] 3.5 Document generating or copying the TLS cert into `nginx/certs/{tls.crt,tls.key}`; include the mkcert workflow + how to trust the mkcert root CA on operator devices.

## 4. First-boot section

- [x] 4.1 Document `docker compose up -d` and the expected output.
- [x] 4.2 Document waiting for healthchecks; commands to inspect health (`docker compose ps`, `docker inspect <container> --format '{{json .State.Health}}'`).
- [x] 4.3 Document running migrations: `docker compose exec rediska-core alembic upgrade head`.
- [x] 4.4 Document creating the initial admin user (via `POST /api/core/setup/bootstrap` — endpoint refuses after first use; see `services/core/rediska_core/api/routes/setup.py`).
- [x] 4.5 Document configuring the Reddit provider (OAuth credentials in .env, restart core, complete OAuth flow via the UI).

## 5. Smoke test

- [x] 5.1 Finalize the smoke-test checklist (10 items max; see design.md).
- [x] 5.2 Write `scripts/deploy/smoke_test.sh` that runs the automatable subset (items 1–8 from the design's draft list). Exit non-zero on first failure with a pointer to the relevant doc section. _(Script covers items 1, 2, 6, 7, 8 — the strictly scriptable ones. Items 3–5 are UI-driven and items 9–10 are operational.)_
- [x] 5.3 Document the manual items (login UI, send test message) and how to skip them on day-1 if no test counterpart exists yet.

## 6. Data migration section

- [x] 6.1 Document the pre-migration freeze: `docker compose stop rediska-worker rediska-beat rediska-web` on the dev box.
- [x] 6.2 Document MySQL dump on dev (`mysqldump --single-transaction --routines --triggers`), transfer via scp, import on new server. Include the "wipe and reload" command for re-running.
- [x] 6.3 Document `rsync -avzh /var/lib/rediska/attachments/` for attachment migration.
- [x] 6.4 Document the recommended Elasticsearch path: leave ES empty on new server, then trigger the worker reindex from MySQL. Document the fallback snapshot/restore path as appendix.
- [x] 6.5 Document the rollback: stop the new server, restart services on the dev box, no state was lost because we never wrote to the dev box during migration.
- [x] 6.6 Optional helper: `scripts/deploy/migrate_from_dev.sh` to chain the dump/scp/import steps with safety prompts.

## 7. Troubleshooting

- [x] 7.1 Top failure modes with their fixes (drawing from CLAUDE.md "Troubleshooting" section as a baseline and expanding): MySQL not reachable, ES slow to start / OOM, Redis port conflict, nginx cert errors, mkcert root not trusted.
- [x] 7.2 Where to look first when each smoke-test item fails.

## 8. Cross-reference

- [x] 8.1 Update `CLAUDE.md` "Troubleshooting" and "Development Commands" sections to point to `docs/deploy.md` for production deployment specifically (vs. local dev).
- [x] 8.2 Add a one-line README link to the deploy doc.

## 9. Dry-run

- [ ] 9.1 Either spin up a scratch VM and follow the doc end-to-end to validate it, OR document a "doc review" pass where a second person walks through the procedure on a non-production host. Record any corrections. _(Operator-owned: requires a scratch VM or a second pair of eyes — not implementable from this side.)_
