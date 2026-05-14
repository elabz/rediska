## Context

Current state:
- The whole stack runs via `docker compose` from the project root.
- Containers: `rediska-nginx`, `-web`, `-core`, `-worker`, `-beat`, `-redis`, `-mysql`, `-elasticsearch`.
- Bind-mounted host paths for persistence: `/var/lib/rediska/attachments`, `/var/lib/rediska/backups`. (See `CLAUDE.md` "Environment Variables".)
- TLS terminates at `rediska-nginx` with a self-signed cert under `nginx/certs/`. Only nginx is exposed to LAN.
- Config lives in `.env` at the project root.
- Single admin user, sessions in MySQL, no SSO.
- Backups: `scripts/local_backup/backup.sh` and `restore_test.sh` already exist for the dev box.

Target state:
- A separate Linux box on the operator's internal network, reachable only via the VPN (Tailscale/WireGuard/LAN). No public exposure.
- Self-signed cert remains acceptable; we don't pay for a public CA.
- Dev box can be retired after the new server passes its smoke test.

This change is purely procedural — no application code changes. The deliverable is the doc + supporting scripts. The "tests" are the smoke-test items.

## Goals / Non-Goals

**Goals:**
- A new operator with shell access and the repo can deploy Rediska from a blank Linux host in under an hour.
- Smoke test runs in ≤5 minutes, ≤10 items, each a clear pass/fail.
- Full data migration from the dev box is reproducible and reversible (the dev box stays untouched until smoke test passes).
- The procedure is idempotent — re-running on a partially-set-up host doesn't corrupt state.

**Non-Goals:**
- Cloud-provider-specific instructions (the user picked on-prem).
- Public-internet exposure (the user picked VPN-only).
- Zero-downtime deploys (single-user system; ~30s of unavailability during compose restart is fine).
- Automated deploy — that's `github-action-deployment`.
- High availability, multi-server, blue/green.

## Decisions

### Doc location: `docs/deploy.md`

- **Chosen**: A new top-level `docs/` directory, with `deploy.md` as the first inhabitant.
- **Rationale**: Project has `specs/` (product/PRD docs) and `openspec/` (in-progress changes), but no operator-facing docs. Future docs (runbooks, on-call, schema migrations) belong here too.
- **Alternative**: Put it in `README.md`. Rejected — README is for project overview; deploy procedures are long and benefit from their own page.

### Smoke-test items

Aim for ≤10 items. Each must be a single command or a single page-load with a clear pass/fail. Proposed set (final list nailed down in tasks):

1. `docker compose ps` — every container `Up (healthy)` or just `Up` for stateless ones.
2. `curl -sk https://<host>/ -o /dev/null -w "%{http_code}"` returns `200` or `302`.
3. Log into the web UI as the admin user.
4. Inbox page renders without error (empty state OK).
5. Settings → Identities lists the configured Reddit identity.
6. `docker compose logs rediska-worker --tail 50` shows no `ERROR`/`Traceback` in the last 5 minutes.
7. `docker compose exec rediska-core alembic current` shows the latest revision (no pending migrations).
8. Celery beat heartbeat: `docker compose exec rediska-redis redis-cli --scan --pattern 'celery-beat*'` returns at least one key.
9. Trigger a small ingest task (e.g., fetch a single known post) and confirm it succeeds in `jobs` table within 60s.
10. Send a test message to a known-good test user (manual; can be skipped on day-1 if no test user exists).

Items 1–8 are scriptable and good candidates for `scripts/deploy/smoke_test.sh`. Items 9–10 stay manual.

### Migration strategy

The user wants full data migration:

- **MySQL**: `mysqldump --single-transaction --routines --triggers` on the dev box, scp the dump to the new server, `mysql < dump.sql` inside the running `rediska-mysql` container. Schema must match (run `alembic upgrade head` first on the new box, then load data). Document the ordering carefully.
- **Attachments**: `rsync -avzh /var/lib/rediska/attachments/ user@new-host:/var/lib/rediska/attachments/`. Stop the worker first to avoid a moving target; restart after.
- **Elasticsearch**: two options, document both, recommend (a):
  - **(a) Worker reindex from MySQL** — leave ES empty; run a task that walks the `content` tables and re-emits `index.upsert_content`. Simpler, no fs-repo setup. Trades a few minutes of background work for setup simplicity.
  - **(b) Snapshot + restore** — fs-based ES snapshot on the dev box, copy over, restore. Faster but requires aligned ES versions and a configured fs repo.
- **Redis**: not migrated. It holds transient broker state; redrain at switchover. Document acceptance of in-flight task loss (jobs table re-queues anything important via idempotency).

### Idempotency

Each step in the doc should be re-runnable without harm:
- `docker compose up -d` is idempotent.
- `alembic upgrade head` is idempotent (no-op when at head).
- `mysqldump` import: warn the operator that re-importing on top of existing data will fail; provide a clean "wipe and reload" command (`DROP DATABASE rediska; CREATE DATABASE rediska;`).
- `rsync` is idempotent by design.

### Self-signed cert distribution

- Generate the cert once on the operator's workstation using `mkcert` (already in repo workflow). Copy `tls.crt` + `tls.key` to `nginx/certs/` on the server.
- Document the workflow for trusting the mkcert root CA on each device that accesses Rediska. This is the actual annoying part of self-signed TLS; the doc should not gloss over it.

### Backup destination on the new server

- `BACKUPS_PATH=/var/lib/rediska/backups` (same as dev). Doc recommends an off-server backup sync (rclone to S3-compat, restic to a NAS, etc.) but does not prescribe one — operator's choice.

## Risks / Trade-offs

- **Secrets in `.env` plain-text on disk**: acceptable for an internal box, but document the recommendation to restrict permissions (`chmod 600 .env`) and run regular off-server backups encrypted.
- **Doc rot**: the doc will go stale as the stack evolves. Mitigation: include a smoke test that, when it fails, points back at the doc. Make doc updates part of "Definition of Done" for any change touching docker-compose.yml, .env.example, or `alembic/versions/`.
- **Migration timing**: workers running during MySQL dump can produce inconsistent state. Mitigation: doc instructs the operator to `docker compose stop rediska-worker rediska-beat rediska-web` before dumping.
- **mkcert root CA distribution**: every device that accesses Rediska must trust the root. Friction scales with device count. Acceptable for a single-user system.

## Migration Plan (for the change itself)

This is a doc-only change. "Rollout" = merging the doc and pointing folks at it. There is no production cutover.

## Open Questions

- Should the deploy doc include a systemd unit example to manage the docker-compose stack across reboots, or rely entirely on Docker's `restart: unless-stopped` policy + auto-start-on-boot at the Docker daemon level? Default: lean on Docker; mention systemd as optional appendix.
- Should `scripts/deploy/smoke_test.sh` be runnable inside CI (against a temporary stack) as a future enhancement? Not in scope here, but worth flagging.
- Where should the `mkcert` root CA itself be stored? Doc currently assumes the operator has it locally. We may want a 1Password / Bitwarden recommendation.
