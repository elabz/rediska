# CLAUDE.md - Rediska Project Guide

## Project Overview

**Rediska** is a local-first conversation management and lead discovery system that integrates with social platforms (starting with Reddit). It provides hybrid search, LLM-assisted analysis, and manual outreach capabilities while prioritizing data preservation and user privacy.

### Research Context & Content Policy

This project is a **social studies research** effort dealing with issues of **human sexuality**. The themes the system handles are of a sensitive, adult nature and are **allowed within the scope of this research**:

- **No censorship requirements of any kind**: content is ingested, stored, indexed, analyzed, and displayed **verbatim**. Do not add content filtering, moderation, redaction, or refusal layers to any part of the system (ingest, storage, search, LLM analysis, UI).
- **Never online**: the project is not accessible online and **must never be made accessible online**. Access is LAN/private-VPN (Tailscale) only; LLM inference and embeddings run on locally-hosted llama.cpp endpoints — never cloud AI APIs.
- Safety comes from isolation and human control (no autosend, do-not-contact list, audit log, local-only custody) — not from filtering.
- Normative version: `openspec/specs/research-content-policy/spec.md`.

### Core Principles
- **Local storage only (v1)**: DB/search/queue are Docker volumes; attachments and backups are local filesystem
- **Provider-agnostic core**: "reddit" appears only inside provider module/endpoints
- **No remote deletes**: Provider deletions never remove local records/files; only mark status + show badges
- **No autosend (v1)**: Sending requires explicit user click from UI
- **Single user**: Admin username/password with session cookies

### Agent Restrictions (AI assistants / automation)
AI agents working on this project are **explicitly forbidden** from reading the content of the Inbox or the content of individual messages. This means:
- Do NOT open, fetch, or browse `https://rediska.local/inbox` or any individual message/conversation page matching `https://rediska.local/inbox/[0-9]+`
- Do NOT read inbox/message content through any other channel (API calls, database queries, logs) — these are live, private conversations
- Working on inbox-related *code* is fine; inspecting inbox *data* is not

---

## Documentation Map

| Document | Role |
|---|---|
| `prd/Rediska_PRD_v1.0.md` | **Single consolidated PRD** — product scope, principles, functional areas |
| `openspec/specs/<capability>/spec.md` | **Normative capability specs** (OpenSpec) — source of truth for behavior |
| `openspec/changes/` | OpenSpec change proposals (use the `opsx:*` skills to propose/apply/archive) |
| `docs/deploy.md` | Operator deploy, migration, smoke test, troubleshooting |
| `prd/Rediska_Spec_Pack_v0.5.md` + older plans | Historical — superseded by PRD v1.0 + OpenSpec |
| `tasks/` | Historical task files + design docs (SCOUT_WATCH_DESIGN, MULTI_AGENT_ANALYSIS_IMPLEMENTATION) |

New feature work should go through the OpenSpec workflow (propose → apply → archive), updating the relevant capability spec.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Reverse Proxy / TLS | External **dev-proxy** stack (`~/Web/dev-proxy`, separate repo) serving `rediska.local` — the in-repo nginx service is retired |
| Web Frontend | Next.js 14 (App Router) + React 18, Tailwind CSS v4, Radix/shadcn-style UI, Vitest |
| Core API | Python FastAPI (SQLAlchemy, Pydantic v2, Alembic) |
| Async Jobs | Celery (worker + beat) |
| Broker/Cache | Redis 7 |
| Database | MySQL 8.4 |
| Search/Vectors | Elasticsearch 8.14 (BM25 + dense_vector kNN) |
| LLM Runtime | llama.cpp endpoints (inference + embeddings), configurable chat template (llama3 / qwen_thinking / mistral / chatml) |

---

## Repository Structure

```
rediska/
  docker-compose.yml           # no host ports; external dev-proxy attaches to rediska-net
  docker-compose.override.yml  # dev hot-reload for core/worker
  .env.example
  README.md
  CLAUDE.md

  nginx/                       # LEGACY (retired service; kept as reference only)

  apps/
    web/                       # Next.js app (BFF)
      src/
        app/                   # App Router pages + /api/core/* proxy routes
        components/            # AppShell, Sidebar, UserProfilePanel, ui/ primitives...
        hooks/                 # useIdentities, useSetupStatus
        contexts/, lib/

  services/
    core/                      # FastAPI service
      rediska_core/
        main.py                # 18 routers, OnboardingGateMiddleware, CORS
        config.py
        api/{routes,schemas,middleware,deps}
        domain/{models,services,schemas,policies}
        domain/services/agents/  # multi-agent analysis implementations
        providers/{base.py,reddit/}
        infra/                 # db engines/sessions
        infrastructure/        # crypto (Fernet), elasticsearch, embeddings, rate_limiter
        observability/
      alembic/versions/        # head: 017_add_conversation_lists

    worker/                    # Celery worker (imports core)
      rediska_worker/
        celery_app.py          # queues, beat schedule
        tasks/                 # ingest, index, embed, agent, message,
                               # multi_agent_analysis, scout, maintenance
        util/                  # idempotency (jobs table), retry

  scripts/
    local_backup/              # backup.sh, restore_test.sh
    deploy/                    # update.sh (CD entrypoint), smoke_test.sh, migrate_from_dev.sh
    tasks/                     # legacy task-tracking helpers

  .github/workflows/deploy.yml # build → GHCR → Tailscale SSH → update.sh

  openspec/                    # OpenSpec: specs/ (capabilities) + changes/
  prd/                         # PRD v1.0 + historical spec packs/plans
  tasks/                       # historical task files + design docs
  docs/deploy.md
  data/                        # local attachments + backups (NEVER read contents)
```

---

## Development Commands

> For **production deployment** to the on-prem server (bring-up, smoke test, dev-to-prod migration, troubleshooting), see [docs/deploy.md](./docs/deploy.md). The commands below cover local development only.
>
> Pushes to `main` (excluding `openspec/**`, `docs/**`, and `**/*.md`) trigger `.github/workflows/deploy.yml`, which builds images, pushes them to GHCR (`ghcr.io/elabz/rediska-*`, tagged by commit SHA + `latest`), and auto-deploys to the on-prem server over Tailscale SSH via `scripts/deploy/update.sh`. See [docs/deploy.md §8](./docs/deploy.md#8-continuous-deployment).

### Docker Compose
```bash
docker compose up -d                     # start all services
docker compose logs -f [service-name]    # logs
docker compose build rediska-core && docker compose up -d rediska-core
docker compose down                      # stop
docker compose down -v                   # reset volumes (DESTRUCTIVE)
```

Note: HTTPS access requires the external dev-proxy stack to be running (it owns the `rediska.local` vhost + TLS certs and joins `rediska-net`).

### Database Migrations (Alembic)
```bash
docker compose exec rediska-core alembic upgrade head
docker compose exec rediska-core alembic revision --autogenerate -m "description"
docker compose exec rediska-core alembic downgrade -1
```

### Web Development
```bash
cd apps/web
npm install
npm run dev          # Development server
npm run build        # Production build
npm test             # Vitest
npm run lint         # Linting (next/core-web-vitals + next/typescript preset)
npm run lint -- --fix
```

ESLint config: `apps/web/.eslintrc.json`. Lint must be clean before merging.

### Core API Development
```bash
cd services/core
pip install -e ".[dev]"
uvicorn rediska_core.main:app --reload --host 0.0.0.0 --port 8000
pytest
```

### Worker Development
```bash
cd services/worker
pip install -e ".[dev]"
celery -A rediska_worker.celery_app worker -l INFO
celery -A rediska_worker.celery_app beat -l INFO  # Scheduler
```

---

## Architecture Patterns

### Traffic Flow
1. Browser (LAN/VPN) → external **dev-proxy** (HTTPS, `rediska.local` vhost, attaches to `rediska-net`)
2. dev-proxy → `rediska-web` (HTTP, internal Docker network)
3. `rediska-web` BFF API routes (`/api/core/*`) → `rediska-core` (HTTP, internal), forwarding the `session` cookie
4. `rediska-core` reads/writes MySQL, ES, Redis; enqueues Celery jobs
5. `rediska-worker` consumes Celery jobs; calls providers, llama.cpp; writes DB/ES/files

### Container Naming
All containers use the `rediska-` prefix: `rediska-web`, `rediska-core`, `rediska-worker`, `rediska-beat`, `rediska-redis`, `rediska-mysql`, `rediska-elasticsearch`. (`rediska-nginx` is retired.) **No container publishes host ports.**

### API Design
- Core API endpoints are RESTful; cursor-based pagination (`?cursor=&limit=`)
- All mutating endpoints write to `audit_log`
- All Celery tasks use the `jobs` table for idempotency (statuses include `cancelled`)
- `OnboardingGateMiddleware` returns 403 on non-bypass routes until at least one identity exists

### Provider Integration
Provider-specific code lives in `services/core/rediska_core/providers/{provider_name}/`. `providers/base.py` defines the abstract `ProviderAdapter` + normalized DTOs. Reddit (`providers/reddit/`) implements `adapter.py` (API client + mappers, token auto-refresh, remote delete) and `oauth.py`.

### BFF (Backend-for-Frontend) Architecture
The UI never calls the Python backend directly. All requests go through Next.js proxy routes:
```
UI (page.tsx) → Next.js Proxy (api/core/.../route.ts) → FastAPI Backend (routes/*.py)
```

When adding new API endpoints:
1. Create backend route in `services/core/rediska_core/api/routes/`
2. Create Next.js proxy in `apps/web/src/app/api/core/`
3. Call `/api/core/...` from UI components

### Multi-Agent Analysis System
6 specialized LLM agents analyze leads (5 dimension agents run in parallel + a coordinator):
- **Demographics Agent** — age, gender, location (with offline geocoding → `location_near` via `HOME_LATITUDE`/`HOME_LONGITUDE`)
- **Preferences Agent** — hobbies, lifestyle, compatibility
- **Relationship Goals Agent** — intent, partner criteria, deal-breakers
- **Risk Flags Agent** — scam/seller detection, authenticity, red flags
- **Sexual Preferences Agent** — orientation, interests
- **Meta-Analysis Coordinator** — synthesizes dimensions → final recommendation (suitable / not_recommended / needs_review) + confidence

Files:
- `domain/services/agents/` — agent implementations (+ `default_prompts.py` registry)
- `domain/services/multi_agent_analysis.py` — orchestration
- `domain/services/agent_prompt.py` — prompt versioning (editable per-dimension with rollback via `/agent-prompts` + `/settings/agents` UI)
- `api/routes/leads.py` — analysis trigger endpoints (`analyze`, `analyze-multi`, history)

### Scout Watch System
Automated saved Reddit searches (`/settings/scout-watches` UI, `/scout-watches` API, `scout_watch.py` service, `tasks/scout.py`):
- Beat runs `scout.run_all_watches` every 5 minutes; watches configure query/sort/time_filter/identity, auto_analyze, min_confidence
- Per-post pipeline: pending → fetching_profile → summarizing → analyzing → analyzed/skipped/failed (dimension results stored on the post)
- Qualifying posts auto-promote to leads (`lead_source=scout_watch`); manual add-to-leads and reanalyze also available
- History cleaned up daily (3-day retention)

---

## Web App Pages (apps/web)

| Route | Purpose |
|---|---|
| `/` | Dashboard (bento grid) or welcome/login card |
| `/login`, `/setup/identity`, `/oauth/reddit/callback` | Auth + onboarding (OAuth popup) |
| `/inbox`, `/inbox/[conversationId]` | Conversation list + thread (drafts, search, lists/labels, star, attachments, remote-delete/scrub, profile panel) |
| `/browse` | Browse subreddit feeds (sort/time/query presets), save leads |
| `/leads`, `/leads/[id]` | Lead list + detail with multi-dimension AI analysis panels |
| `/directories` | Analyzed / Contacted / Engaged / Starred contact directories |
| `/search` | Global hybrid search across messages/leads/profiles/conversations |
| `/profile/[accountId]` | Account profile: snapshot, signals, risk flags, posts/comments/images |
| `/ops` | Job queue, sync, backfills, attachment re-download |
| `/audit` | Audit log viewer |
| `/settings/connection`, `/settings/personas`, `/settings/agents`, `/settings/scout-watches` (+ `/[watchId]/history`) | Reddit connection, voice personas, agent prompts, scout watches |

---

## Key Database Tables

Head migration: `017_add_conversation_lists`.

| Table | Purpose |
|-------|---------|
| `providers` | Registered providers (reddit, etc.) |
| `local_users` | Single admin user authentication (Argon2) |
| `sessions` | Server-side session storage |
| `identities` | User identities per provider with voice/persona config (`voice_config_json`, `is_default`) |
| `external_accounts` | Counterpart identities; analysis/contact/engagement states + starred |
| `conversations` | Chat threads (identity-bound) |
| `conversation_lists`, `conversation_list_members` | User-defined conversation lists (labels) |
| `messages` | Messages (threading fields, `send_failed` visibility, `send_error`) |
| `attachments` | Local file references (sha256, mime, dimensions) |
| `lead_posts` | Saved posts; recommendation/confidence, summaries, `lead_source` (manual/scout_watch) |
| `lead_analyses` | Multi-agent analysis results (per-dimension JSON + meta) |
| `analysis_dimensions` | Per-dimension execution tracking (raw responses, model info) |
| `agent_prompts` | Versioned LLM agent prompts |
| `scout_watches`, `scout_watch_runs`, `scout_watch_posts` | Scout watch config, run history, seen-post pipeline |
| `profile_snapshots` | LLM-generated profile summaries + signals/risk flags |
| `profile_items` | Public content items (posts/comments/images) per account |
| `provider_credentials` | Encrypted OAuth tokens (Fernet) |
| `do_not_contact` | Safety blocklist |
| `audit_log` | Append-only action log (actor: user/system/agent, identity-aware) |
| `jobs` | Celery task idempotency ledger (incl. `cancelled`) |

---

## Environment Variables

See `.env.example` for the full list. Notable:

```env
# Image tag for GHCR images (pin to a SHA to roll back)
TAG=latest

# Database
MYSQL_URL=mysql+pymysql://user:pass@rediska-mysql:3306/rediska
MYSQL_ROOT_PASSWORD= / MYSQL_DATABASE=rediska / MYSQL_USER= / MYSQL_PASSWORD=

# Redis / Celery (db 0 / 1 / 2)
REDIS_URL=redis://rediska-redis:6379/0
CELERY_BROKER_URL=redis://rediska-redis:6379/1
CELERY_RESULT_BACKEND=redis://rediska-redis:6379/2

# Elasticsearch
ELASTIC_URL=http://rediska-elasticsearch:9200

# Storage paths (host paths mounted into containers)
ATTACHMENTS_PATH=/var/lib/rediska/attachments
BACKUPS_PATH=/var/lib/rediska/backups

# LLM endpoints (local llama.cpp — never cloud APIs)
INFERENCE_URL= / INFERENCE_MODEL= / INFERENCE_API_KEY=
INFERENCE_TIMEOUT=300
INFERENCE_CHAT_TEMPLATE=llama3   # llama3 | qwen_thinking | mistral | chatml
EMBEDDINGS_URL= / EMBEDDINGS_MODEL= / EMBEDDINGS_API_KEY=

# Web / security
BASE_URL=https://rediska.local
NEXTAUTH_SECRET=
SECRET_KEY=
ENCRYPTION_KEY=                  # Fernet key for provider_credentials
SESSION_EXPIRE_HOURS=168

# Provider: Reddit
PROVIDER_REDDIT_ENABLED=true
PROVIDER_REDDIT_CLIENT_ID= / PROVIDER_REDDIT_CLIENT_SECRET=
PROVIDER_REDDIT_REDIRECT_URI=https://rediska.local/api/providers/reddit/callback
PROVIDER_REDDIT_USER_AGENT=Rediska/1.0

# Rate limiting
PROVIDER_RATE_QPM_DEFAULT=60
PROVIDER_RATE_CONCURRENCY_DEFAULT=2
PROVIDER_RATE_BURST_FACTOR=1.5

# Demographics geocoding (offline, for location_near classification)
HOME_LATITUDE=40.0 / HOME_LONGITUDE=-75.2 / LOCATION_NEAR_THRESHOLD_MILES=200
```

---

## Celery Tasks

Queues: `ingest`, `index`, `embed`, `agent`, `messages`, `multi_agent_analysis`, `scout`, `maintenance`.

### Ingest
- `ingest.backfill_conversations` / `ingest.backfill_messages` — history import
- `ingest.sync_delta` — incremental sync (beat: every 120s)
- `ingest.sync_inbox_fast` — fast inbox-only sync (beat: every 60s)
- `ingest.browse_location`, `ingest.fetch_post`, `ingest.fetch_profile`, `ingest.fetch_profile_items`
- `ingest.analyze_reddit_user`, `ingest.analyze_lead_profile`
- `ingest.redownload_attachments` — re-download missing images from message bodies

### Indexing / Embeddings
- `index.upsert_content`, `index.delete_content`, `index.bulk_index_all_messages`, `index.bulk_index_conversation`
- `embed.generate`, `embed.generate_batch`, `embed.generate_for_entity`

### Agents / Analysis
- `agent.profile_summary`, `agent.lead_scoring`, `agent.draft_intro`
- `multi_agent_analysis.analyze_lead` (6-agent pipeline), `.batch_analyze`, `.check_analysis_status`, `.cleanup_failed_analyses`

### Scout Watch
- `scout.run_all_watches` (beat: every 300s), `scout.run_single_watch`, `scout.analyze_and_decide`, `scout.reanalyze_post`

### Messaging
- `message.send_manual` — manual trigger only; `max_retries=0` (at-most-once)

### Maintenance (beat-scheduled)
- `maintenance.mysql_dump_local` (daily 03:00 UTC)
- `maintenance.attachments_snapshot_local` (daily 04:00 UTC)
- `maintenance.restore_test_local` (weekly, Sun 05:00 UTC)
- `maintenance.cleanup_scout_watch_history` (daily 02:00 UTC, 3-day retention)

---

## Testing Guidelines

### Python (pytest)
```bash
cd services/core
pytest                           # All tests
pytest tests/unit/               # Unit tests only
pytest tests/integration/        # Integration tests
pytest -v -k "test_name"         # Specific test
```

### JavaScript (Vitest)
```bash
cd apps/web
npm test                         # All tests
npm test -- --watch              # Watch mode
```

Do NOT test against the live app/data (see Agent Restrictions) — use unit/integration tests and synthetic data.

---

## Code Style

### Python
- Type hints everywhere; PEP 8 with 100 char line limit
- Pydantic for schemas/validation; async for I/O
- Note: infra is split across `infra/` (db) and `infrastructure/` (crypto/es/embeddings/rate_limiter) — follow existing placement

### TypeScript/JavaScript
- TypeScript for all new code; follow ESLint config
- React Server Components where appropriate; prefer named exports

---

## Security Considerations

- The external dev-proxy is the only LAN-exposed entry point; no compose service publishes host ports
- The system must NEVER be exposed to the public internet (see Research Context & Content Policy)
- OAuth tokens encrypted at rest (Fernet) in `provider_credentials`
- Passwords hashed with Argon2; session cookies HttpOnly + Secure
- Audit all mutating actions
- No autosend — all sends require explicit user action

---

## Troubleshooting

> Production-server troubleshooting lives in [docs/deploy.md §6](./docs/deploy.md#6-troubleshooting). Local-dev quick reference:

**MySQL connection refused** — check `rediska-mysql` health (`docker compose ps`); verify `MYSQL_URL` in `.env`

**Elasticsearch not responding** — ES needs ~30s to start; requires at least 1GB heap

**Redis issues** — `docker compose exec rediska-redis redis-cli ping`

**Worker not processing tasks** — `docker compose logs rediska-worker`; verify broker URL

**https://rediska.local unreachable** — ensure the external dev-proxy stack is up and attached to `rediska-net`; check its vhost config and mkcert trust

---

## Definition of Done (Global)

Every feature must satisfy:
- [ ] Runs via `docker compose up -d` on a clean host following README
- [ ] Only the external dev-proxy is LAN-exposed; no new host ports published
- [ ] Any new endpoint that mutates state writes to `audit_log`
- [ ] Any new Celery task uses `jobs` idempotency and has a retry policy
- [ ] Provider sync never deletes local records/files (only marks status/visibility)
- [ ] Every UI page has empty states and error states (no blank screens)
- [ ] The relevant OpenSpec capability spec (`openspec/specs/`) is updated via the OpenSpec change workflow
