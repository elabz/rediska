# Rediska Deploy Guide

Canonical procedure for bringing Rediska up on a fresh internal Linux server, from cold start to a passing smoke test, and for migrating dev-box state to the new server.

This is the **operator-facing** guide. For day-to-day development, see `CLAUDE.md`.

> **Scope.** On-prem, VPN-only deploy, self-signed TLS, single admin user. Cloud-provider specifics, public-internet exposure, and HA are out of scope.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Bootstrap](#2-bootstrap)
3. [First Boot](#3-first-boot)
4. [Smoke Test](#4-smoke-test)
5. [Data Migration from Dev](#5-data-migration-from-dev)
6. [Troubleshooting](#6-troubleshooting)
7. [Appendix](#7-appendix)

---

## 1. Prerequisites

### 1.1 Target host

- **OS**: Ubuntu 22.04 LTS or Debian 12 (other systemd-based Linux distros likely work; commands below assume `apt`).
- **Architecture**: x86_64.
- **CPU**: 2 vCPU minimum, 4+ recommended (Elasticsearch is the heaviest).
- **RAM**: 4 GB minimum, 8 GB recommended. Elasticsearch alone needs ≥1 GB heap.
- **Disk**: 20 GB free for images + working set; attachments and DB grow over time — size for your data.
- **Network**: only reachable over the operator's VPN (Tailscale / WireGuard / LAN). The server itself should **not** be exposed to the public internet.

### 1.2 Software (host packages)

Install on the server before cloning the repo:

```bash
sudo apt update
sudo apt install -y git openssl ca-certificates curl gnupg
```

Docker Engine + the compose plugin are installed in [§2.1](#21-docker-engine).

On the **operator's workstation** (the machine you use to access the UI), install [`mkcert`](https://github.com/FiloSottile/mkcert) so you can mint and trust a self-signed cert. It is not needed on the server itself.

### 1.3 VPN reachability

Before touching the server, confirm:

```bash
# From your workstation
ssh <user>@<server-hostname>   # succeeds
ping rediska.internal           # resolves to the server (once /etc/hosts is set, see below)
```

If you cannot SSH in over the VPN, fix that first; the rest of this guide assumes you have shell access.

### 1.4 `/etc/hosts` pattern

Rediska serves at a single internal hostname (defaults to `rediska.local` in `.env.example`; the cert and `BASE_URL` must agree). Every machine that accesses the UI needs the hostname to resolve to the server's VPN IP. Add a line to `/etc/hosts` (or your VPN provider's DNS) on every operator device:

```text
100.x.y.z   rediska.local
```

Use the server's VPN IP, not its LAN IP, so the routing is unambiguous.

---

## 2. Bootstrap

All commands below run on the **new server** unless noted.

### 2.1 Docker Engine

Install Docker and the compose plugin per the [official Docker docs](https://docs.docker.com/engine/install/):

```bash
# Docker's official repo for Ubuntu/Debian
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify
docker --version
docker compose version
docker run --rm hello-world
```

Add your user to the `docker` group so you don't need `sudo` for compose commands:

```bash
sudo usermod -aG docker $USER
# Log out and back in (or `newgrp docker`) for the new group to take effect.
```

### 2.2 Data directories

Create the bind-mount targets used by the compose file:

```bash
sudo mkdir -p /var/lib/rediska/attachments /var/lib/rediska/backups
sudo chown -R $USER:$USER /var/lib/rediska
```

These hold attachment files and database backups. They survive container rebuilds.

### 2.3 Clone the repo

```bash
sudo mkdir -p /opt/rediska
sudo chown $USER:$USER /opt/rediska
git clone git@github.com:elabz/rediska.git /opt/rediska
cd /opt/rediska
```

`/opt/rediska` is the recommended path; the rest of this guide assumes it.

### 2.4 Configure `.env`

```bash
cp .env.example .env
chmod 600 .env   # secrets — keep the file readable only by you
```

Edit `.env` and fill in the values. Variables you **MUST** change before first boot:

| Variable | Why |
|---|---|
| `MYSQL_ROOT_PASSWORD` | Strong password; MySQL root. |
| `MYSQL_PASSWORD` | Strong password for the `rediska` DB user. **Must match** the password embedded in `MYSQL_URL`. |
| `MYSQL_URL` | Update the embedded password to match `MYSQL_PASSWORD`. |
| `NEXTAUTH_SECRET` | `openssl rand -hex 32`. Used to sign session cookies. |
| `BASE_URL` | The HTTPS URL the UI is served from. Must match the cert CN (e.g., `https://rediska.local`). |
| `PROVIDER_REDDIT_CLIENT_ID` | From the Reddit app you registered (see [§3.5](#35-configure-reddit-oauth)). |
| `PROVIDER_REDDIT_CLIENT_SECRET` | Same as above. |
| `PROVIDER_REDDIT_REDIRECT_URI` | Must match what you set on Reddit's app page; default points at `BASE_URL`. |

Variables with sensible defaults (leave as-is unless you have a reason): `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `ELASTIC_URL`, `ATTACHMENTS_PATH`, `BACKUPS_PATH`, `PROVIDER_REDDIT_USER_AGENT`, the `PROVIDER_RATE_*` values.

LLM endpoints (`INFERENCE_URL`, `INFERENCE_MODEL`, `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL`) point at your llama.cpp instance. Leave them blank for first boot if LLM features aren't needed yet; the smoke test does not require them.

### 2.5 TLS certificate

Rediska's nginx expects `nginx/certs/tls.crt` and `nginx/certs/tls.key`. The recommended workflow uses [`mkcert`](https://github.com/FiloSottile/mkcert) so every operator device can trust the same root.

**One-time on your workstation:**

```bash
mkcert -install                       # installs the mkcert root into your system trust store
mkcert -cert-file tls.crt -key-file tls.key rediska.local "*.rediska.local"
```

**Copy the cert + key onto the server:**

```bash
scp tls.crt tls.key <user>@<server>:/opt/rediska/nginx/certs/
ssh <user>@<server> 'chmod 600 /opt/rediska/nginx/certs/tls.key'
```

**Trust the mkcert root on every device that accesses the UI:**

- macOS/Linux: copy `~/.local/share/mkcert/rootCA.pem` (Linux) or `~/Library/Application Support/mkcert/rootCA.pem` (macOS) from your workstation to the device, then `mkcert -install` on that device, or import the root into the system trust store manually.
- iOS/Android: email or AirDrop the `rootCA.pem` to the device, install it as a profile, then enable full trust in Settings.

> Until the mkcert root is trusted, browsers will warn on every page load. That is the single most common day-1 friction point. See [§6](#6-troubleshooting) if you get cert errors.

---

## 3. First Boot

### 3.1 Start the stack

From `/opt/rediska`:

```bash
docker compose up -d
```

Expected output: each service starts, with explicit `Started` lines for `rediska-nginx`, `-web`, `-core`, `-worker`, `-beat`, `-redis`, `-mysql`, `-elasticsearch`.

### 3.2 Wait for healthchecks

The dependent services come up gated on healthchecks; give them ~30 seconds. Check:

```bash
docker compose ps
```

Every container should be `Up` and the ones with healthchecks (`rediska-mysql`, `-redis`, `-elasticsearch`, `-core`, `-web`) should show `healthy`. If one is still starting, wait another 30 seconds.

To inspect a single container's health detail:

```bash
docker inspect rediska-mysql --format '{{json .State.Health}}' | jq
```

### 3.3 Run database migrations

```bash
docker compose exec rediska-core alembic upgrade head
```

Expected: a list of revisions ending at `head`. Re-running is a no-op once at head — safe.

### 3.4 Create the admin user

Rediska is single-user. Bootstrap the admin via the `/setup/bootstrap` endpoint; this endpoint refuses once any user exists, so it is one-shot:

```bash
curl -sk -X POST "https://rediska.local/api/core/setup/bootstrap" \
  -H "Content-Type: application/json" \
  -d '{"username":"<your-admin-username>","password":"<strong-password>"}'
```

A `200` with the new user payload means success. A `403` means an admin already exists — use `/auth/login` instead.

### 3.5 Configure Reddit OAuth

1. On [Reddit's app prefs](https://www.reddit.com/prefs/apps), create a `web app`. Set the redirect URI to exactly what you put in `PROVIDER_REDDIT_REDIRECT_URI` (default `https://rediska.local/api/providers/reddit/callback`).
2. Copy the client ID + secret into `.env` (`PROVIDER_REDDIT_CLIENT_ID`, `PROVIDER_REDDIT_CLIENT_SECRET`).
3. Restart the core so it picks up the new env:
   ```bash
   docker compose up -d rediska-core
   ```
4. Log into the UI at `BASE_URL`, navigate to **Settings → Identities → Connect Reddit**, and complete the OAuth handshake. Reddit redirects back via the URI from step 1; if the URI doesn't match, you'll see "invalid redirect_uri" — fix and retry.

---

## 4. Smoke Test

Run after every deploy or migration. ≤10 items, ≤5 minutes.

| # | Check | Pass criterion |
|---|---|---|
| 1 | `docker compose ps` | Every container `Up`; healthchecked ones show `healthy`. |
| 2 | `curl -sk -o /dev/null -w "%{http_code}\n" https://<host>/` | `200` or `302`. |
| 3 | Log into the web UI as the admin user. | Inbox loads. (manual) |
| 4 | Inbox page renders. | Empty state OK; no error toast. (manual) |
| 5 | Settings → Identities lists the configured Reddit identity. | At least one identity row. (manual) |
| 6 | `docker compose logs rediska-worker --tail 50` | No `ERROR`/`Traceback` in the last 5 minutes. |
| 7 | `docker compose exec rediska-core alembic current` | Output ends with `(head)`. |
| 8 | `docker compose exec rediska-redis redis-cli --scan --pattern 'celery-beat*'` | At least one key (beat is alive). |
| 9 | Trigger a small ingest task (e.g., fetch a single known post) and confirm `jobs` table records success within 60s. | (manual / day-2) |
| 10 | Send a test message to a known-good test user. | (manual; skip on day-1 if no test counterpart exists yet) |

Items 1, 2, 6, 7, 8 are scripted in `scripts/deploy/smoke_test.sh`. Run it from `/opt/rediska`:

```bash
./scripts/deploy/smoke_test.sh
```

It exits non-zero on the first failure with a pointer to the relevant section of this doc.

Items 3, 4, 5 require a browser session; do them by hand. Items 9 and 10 are day-2 sanity checks and can be skipped on the very first deploy if you have not yet wired up a Reddit identity or counterpart.

---

## 5. Data Migration from Dev

Use this section when moving an existing Rediska from a dev box to the new server. The dev box stays **untouched** until the new server passes its smoke test — this is the rollback path.

### 5.1 Pre-migration freeze (on the dev box)

Stop write paths but keep MySQL and ES running so you can dump them:

```bash
# On the dev box
docker compose stop rediska-worker rediska-beat rediska-web
```

`rediska-core`, `-mysql`, `-elasticsearch`, `-redis`, and `-nginx` keep running; they are needed for the dump.

### 5.2 MySQL: dump + transfer + import

On the dev box:

```bash
docker compose exec -T rediska-mysql \
  mysqldump --single-transaction --routines --triggers \
            -u root -p"$MYSQL_ROOT_PASSWORD" rediska \
  > /tmp/rediska-dump.sql
scp /tmp/rediska-dump.sql <user>@<new-host>:/tmp/rediska-dump.sql
```

On the new server (after [§3.3](#33-run-database-migrations) has already brought the schema to head — migration aligns before data loads):

```bash
# Wipe the empty schema and reload from the dump.
# WARNING: destructive on the new box only. The dev box is unaffected.
docker compose exec -T rediska-mysql \
  mysql -u root -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE rediska; CREATE DATABASE rediska;"
docker compose exec -T rediska-mysql \
  mysql -u root -p"$MYSQL_ROOT_PASSWORD" rediska < /tmp/rediska-dump.sql

# Re-apply alembic in case the dump was taken on an older schema.
docker compose exec rediska-core alembic upgrade head
```

If the import fails partway, re-run the `DROP DATABASE … CREATE DATABASE …` then the `mysql < dump` — both are safe to re-run.

### 5.3 Attachments

Run on the dev box (with the worker still stopped from §5.1):

```bash
rsync -avzh /var/lib/rediska/attachments/ \
  <user>@<new-host>:/var/lib/rediska/attachments/
```

`rsync` is idempotent; rerun if interrupted.

### 5.4 Elasticsearch

**Recommended path: reindex from MySQL.** Leave ES empty on the new server, then have the worker rebuild the index from the source of truth (`messages`, `profile_items`, etc.). The worker exposes an `index.upsert_content` task that the maintenance code path enqueues per-row. Trigger this either via the Ops UI (Operations → Reindex) or, if no UI control exists, manually enqueue per-table reindex jobs. Pros: no fs-repo setup; aligns with the "MySQL is source of truth" invariant. Cons: a few minutes of background CPU while it catches up.

**Fallback path: snapshot + restore.** Requires aligned ES major versions between dev and new server, plus a configured filesystem snapshot repo on both sides. Use this only if reindex is too slow for your dataset. See [§7.2](#72-elasticsearch-snapshotrestore-fallback).

### 5.5 Redis

Not migrated. Redis holds transient broker + cache state; you start fresh on the new server. Any in-flight task is re-queued by the worker on next tick (the `jobs` table provides idempotency keys), so this is safe.

### 5.6 Cutover

1. Run the smoke test on the new server (§4). Every item must pass.
2. Point operator devices' `/etc/hosts` (or VPN DNS) entries for `rediska.local` at the new server's VPN IP.
3. Log in via the UI on at least one device to confirm.

### 5.7 Rollback

If the new server fails any smoke item that you can't quickly resolve:

```bash
# On the new server
docker compose stop

# On the dev box
docker compose up -d
```

Restore `/etc/hosts` entries to point back at the dev box. **No state was lost** on the dev box during migration because we never wrote to it (the dev box was frozen at §5.1; we only read from it). The new server's data can be discarded and the migration re-tried.

### 5.8 Helper script (optional)

`scripts/deploy/migrate_from_dev.sh` chains the dump → scp → import → restart sequence with safety prompts. Run with `--help` for usage; recommended to read it through once before invoking on real data.

---

## 6. Troubleshooting

### 6.1 Top failure modes

| Symptom | Likely cause | First fix |
|---|---|---|
| `docker compose ps` shows a container restarting | Healthcheck failing repeatedly | `docker compose logs <service> --tail 100` |
| MySQL "Can't connect" from core | DB still initializing, or `MYSQL_URL` password mismatches `MYSQL_PASSWORD` | Wait 30s; otherwise re-check `.env` |
| ES container exits with `max virtual memory areas vm.max_map_count too low` | Host `vm.max_map_count` < 262144 | `sudo sysctl -w vm.max_map_count=262144` and persist in `/etc/sysctl.d/` |
| ES container OOMs | Heap > available RAM | Reduce `ES_JAVA_OPTS` in compose or add RAM |
| Redis port conflict (`bind: address already in use`) | Another Redis running on the host | `sudo lsof -i :6379` to identify; stop it or change host's redis |
| nginx "no such file" for cert | `tls.crt`/`tls.key` missing from `nginx/certs/` | Copy them per [§2.5](#25-tls-certificate) |
| Browser shows "Not Secure" or refuses to connect | mkcert root not trusted on this device | Re-run [§2.5](#25-tls-certificate) trust step on the device |
| `/api/core/setup/bootstrap` returns 403 | Admin already exists | Use `/auth/login`; if the password is lost, reset via DB directly |
| Worker logs `no credential` for Reddit | OAuth not completed for that identity | Settings → Identities → Connect Reddit |

### 6.2 Where to look first when a smoke item fails

| Smoke item | Look here |
|---|---|
| 1 (compose ps) | `docker compose logs <unhealthy-service> --tail 200`. |
| 2 (https reach) | `docker compose logs rediska-nginx`. Then `docker compose logs rediska-web`. |
| 3–5 (UI) | Browser devtools network tab + `docker compose logs rediska-web rediska-core`. |
| 6 (worker errors) | `docker compose logs rediska-worker --since 10m`. Look for the first `Traceback`. |
| 7 (alembic head) | `docker compose exec rediska-core alembic history` and `alembic current` — compare. |
| 8 (beat keys) | `docker compose logs rediska-beat --tail 50` — beat may have crashed. |
| 9 (ingest task) | `docker compose logs rediska-worker --tail 200` + `SELECT * FROM jobs ORDER BY id DESC LIMIT 10`. |

### 6.3 Useful one-liners

```bash
# Tail every service at once
docker compose logs -f --tail 50

# Open a MySQL shell
docker compose exec rediska-mysql mysql -u root -p"$MYSQL_ROOT_PASSWORD" rediska

# Open a Redis shell
docker compose exec rediska-redis redis-cli

# Inspect a single container's healthcheck output
docker inspect rediska-core --format '{{json .State.Health}}' | jq

# Restart a single service without touching others
docker compose up -d rediska-core
```

---

## 7. Appendix

### 7.1 Backups

Backup scripts live in `scripts/local_backup/`:

- `backup.sh` — MySQL dump + attachments tarball, written to `$BACKUPS_PATH`.
- `restore_test.sh` — re-import a backup into a scratch container to verify it round-trips.

`BACKUPS_PATH=/var/lib/rediska/backups` by default. Off-server backup is **strongly recommended** but operator's choice — common options include `rclone` to an S3-compatible target, `restic` to a NAS, or `borg` to a remote SSH host. Whatever you pick, encrypt before leaving the box and test the restore quarterly.

### 7.2 Elasticsearch snapshot/restore fallback

If you opt for snapshot/restore over the reindex path in [§5.4](#54-elasticsearch):

1. **On the dev box**, add a `path.repo` setting to the ES container and mount a host directory for snapshots.
2. Create a snapshot repository and take a snapshot:
   ```bash
   curl -X PUT 'http://localhost:9200/_snapshot/local_backup' -H 'Content-Type: application/json' -d '{"type":"fs","settings":{"location":"/usr/share/elasticsearch/backup"}}'
   curl -X PUT 'http://localhost:9200/_snapshot/local_backup/migration?wait_for_completion=true'
   ```
3. Copy the snapshot directory to the new server via `rsync`.
4. **On the new server**, mount the same path, register the repo, and `POST /_snapshot/local_backup/migration/_restore`.

Major-version skew between source and target ES will break restore — verify versions match first.

### 7.3 systemd (optional)

Docker's `restart: unless-stopped` policy plus enabling Docker at boot (`sudo systemctl enable docker`) is enough to bring Rediska back after a reboot. A dedicated systemd unit is unnecessary for this stack, but if you want one for an explicit "rediska target" managed via `systemctl`, see the Docker docs for `docker compose up` wrapped in a unit file.

### 7.4 Security posture

- `.env` is world-readable by default until you `chmod 600` it; do so on every server.
- Self-signed TLS is only as good as the trust store of each device; treat the mkcert root CA as a moderately-sensitive secret.
- Rediska has no SSO and no per-user authz; the admin password is the only auth boundary. Pick a strong one and rotate if compromised.

---

## Pointers

- Day-to-day developer commands: `CLAUDE.md` (top-level project guide).
- Architecture overview: `CLAUDE.md` → "Architecture Patterns".
- Continuous deployment via GitHub Actions: see the `github-action-deployment` change (when shipped, this section will link to its workflow doc).
