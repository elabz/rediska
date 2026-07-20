# Rediska

Local-first conversation management and lead discovery system with provider integrations (Reddit first).

Rediska is a **social-studies research instrument** studying human sexuality and online relationship-seeking behavior. The content it handles is sensitive/adult by nature and in scope for the research; the system applies **no content censorship of any kind** and is instead kept strictly offline-private: it is **not accessible from the internet and must never be made accessible online** (LAN/private VPN only, local LLMs only). See [openspec/specs/research-content-policy/spec.md](./openspec/specs/research-content-policy/spec.md).

## Quick Start

### Prerequisites
- Docker and Docker Compose v2
- Node.js 20+ (for local web development)
- Python 3.11+ (for local API development)
- The shared `dev-proxy` stack (separate repo at `~/Web/dev-proxy`) for TLS and the `rediska.local` vhost

### 1. Clone and Configure

```bash
git clone <repository-url>
cd rediska

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# At minimum: strong MySQL passwords, ENCRYPTION_KEY, NEXTAUTH_SECRET,
# INFERENCE_URL / EMBEDDINGS_URL for your local llama.cpp endpoints
```

### 2. TLS / Reverse Proxy

The stack publishes **no host ports**. HTTPS for `https://rediska.local` is terminated by the external **dev-proxy** stack, which attaches to the `rediska-net` Docker network. Bring up dev-proxy (it holds the vhost config `nginx/conf.d/rediska.local.conf` and the mkcert certificates), and add the host entry:

```bash
echo "127.0.0.1 rediska.local" | sudo tee -a /etc/hosts
```

> The in-repo `nginx/` directory is legacy reference only — the `rediska-nginx` service was retired from docker-compose.

### 3. Create Local Storage Directories

```bash
sudo mkdir -p /var/lib/rediska/{attachments,backups}
sudo chown -R $(whoami) /var/lib/rediska
```

### 4. Start Services

```bash
docker compose up -d
```

### 5. Run Database Migrations

```bash
docker compose exec rediska-core alembic upgrade head
```

### 6. Create the Admin User & Log In

Bootstrap the single admin user via `POST /setup/bootstrap` (see `docs/deploy.md §3.4`), then open https://rediska.local, log in, and connect a Reddit identity via OAuth (`/setup/identity`).

## Architecture

```
Browser (LAN/VPN) → dev-proxy (TLS, external stack) → Next.js Web (BFF) → FastAPI Core → MySQL/ES/Redis
                                                                              ↓
                                                             Celery Worker/Beat → Reddit API, llama.cpp (LLM + embeddings)
```

### Services (docker-compose)

| Service | Description |
|---------|-------------|
| rediska-web | Next.js 14 frontend + BFF proxy routes (internal :3000) |
| rediska-core | FastAPI backend (internal :8000) |
| rediska-worker | Celery task worker (ingest, index, embed, agents, scout, maintenance) |
| rediska-beat | Celery scheduler (sync every 60/120s, scout watches every 5m, nightly backups) |
| rediska-mysql | MySQL 8.4 (internal) |
| rediska-redis | Redis 7 broker/cache (internal) |
| rediska-elasticsearch | Elasticsearch 8.14 hybrid search + vectors (internal) |

No service publishes ports to the host; the external dev-proxy is the only entry point. Images are published to GHCR and deployed by CI (see `docs/deploy.md §8`).

## Development

### Web Frontend
```bash
cd apps/web
npm install
npm run dev
npm test          # Vitest
npm run lint
```

### Core API
```bash
cd services/core
pip install -e ".[dev]"
uvicorn rediska_core.main:app --reload
pytest
```

### Worker
```bash
cd services/worker
pip install -e ".[dev]"
celery -A rediska_worker.celery_app worker -l INFO
```

## Documentation

- [PRD v1.0](./prd/Rediska_PRD_v1.0.md) — consolidated product requirements (single source for product scope)
- [openspec/specs/](./openspec/specs/) — normative capability specifications (OpenSpec)
- [CLAUDE.md](./CLAUDE.md) — development guide (codebase map, commands, conventions)
- [docs/deploy.md](./docs/deploy.md) — operator deploy + migration + smoke-test guide
- `prd/Rediska_Spec_Pack_v0.5.md` and earlier plans — historical, superseded by the PRD + OpenSpec
- `tasks/` — historical task files and design docs (Scout Watch, multi-agent analysis)

## Key Principles

1. **Local Storage Only**: all data stays on your machine; LLM inference and embeddings run on local llama.cpp endpoints
2. **Never Online**: LAN/private-VPN access only; must never be exposed to the public internet
3. **No Censorship**: research content is stored, indexed, analyzed, and displayed verbatim (see research-content-policy spec)
4. **No Remote Deletes**: provider deletions never remove local data — only status/visibility flags
5. **No Auto-send**: all outgoing messages require explicit user action
6. **Provider Agnostic**: core system is decoupled from specific providers
7. **Audited**: every mutation writes the append-only audit log; background jobs are idempotent

## License

Private/Proprietary
