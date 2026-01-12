# CLAUDE.md - Rediska Project Guide

## Project Overview

**Rediska** is a local-first conversation management and lead discovery system that integrates with social platforms (starting with Reddit). It provides hybrid search, LLM-assisted analysis, and manual outreach capabilities while prioritizing data preservation and user privacy.

### Core Principles
- **Local storage only (v1)**: DB/search/queue are Docker volumes; attachments and backups are local filesystem
- **Provider-agnostic core**: "reddit" appears only inside provider module/endpoints
- **No remote deletes**: Provider deletions never remove local records/files; only mark status + show badges
- **No autosend (v1)**: Sending requires explicit user click from UI
- **Single user**: Admin username/password with session cookies

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Reverse Proxy | Nginx |
| Web Frontend | Next.js (App Router) + React |
| Core API | Python FastAPI |
| Async Jobs | Celery |
| Broker/Cache | Redis |
| Database | MySQL 8.4 |
| Search/Vectors | Elasticsearch 8.x |
| LLM Runtime | llama.cpp (inference + embeddings) |

---

## Repository Structure

```
rediska/
  docker-compose.yml
  .env.example
  README.md
  CLAUDE.md

  nginx/
    rediska.conf
    certs/
      tls.crt
      tls.key

  apps/
    web/                       # Next.js app
      package.json
      next.config.js
      Dockerfile
      src/
        app/                   # App Router pages + layouts
        components/
        lib/
        server/                # server-only helpers
        api/                   # shared API client types

  services/
    core/                      # FastAPI service
      pyproject.toml
      Dockerfile
      rediska_core/
        main.py
        config.py
        api/
          routes/
          schemas/
          auth/
        domain/
          models/
          services/
          policies/
        providers/
          reddit/              # provider-specific integration
            client.py
            oauth.py
            mappers.py
        infra/
          db.py
          es.py
          redis.py
          attachments.py
          audit.py
          rate_limit.py

      alembic/
        versions/

    worker/                    # Celery worker (imports core)
      pyproject.toml
      Dockerfile
      rediska_worker/
        celery_app.py
        tasks/
          ingest.py
          index.py
          embed.py
          agent.py
          maintenance.py
        util/
          idempotency.py
          retry.py

  scripts/
    local_backup/
      backup.sh
      restore_test.sh

  specs/                       # Project documentation
    Rediska_Spec_Pack_v0.3.md
    Rediska_Sprint_Plan_v0.1.md
    Rediska_Task_Breakdown_v0.1.md
```

---

## Development Commands

### Docker Compose
```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f [service-name]

# Rebuild specific service
docker compose build rediska-core
docker compose up -d rediska-core

# Stop all services
docker compose down

# Reset volumes (DESTRUCTIVE)
docker compose down -v
```

### Database Migrations (Alembic)
```bash
# Run migrations
docker compose exec rediska-core alembic upgrade head

# Create new migration
docker compose exec rediska-core alembic revision --autogenerate -m "description"

# Rollback
docker compose exec rediska-core alembic downgrade -1
```

### Web Development
```bash
cd apps/web
npm install
npm run dev      # Development server
npm run build    # Production build
npm run lint     # Linting
```

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
1. Browser → `rediska-nginx` (HTTPS, port 443)
2. Nginx → `rediska-web` (HTTP, internal Docker network)
3. `rediska-web` BFF API routes → `rediska-core` (HTTP, internal)
4. `rediska-core` reads/writes MySQL, ES, Redis; enqueues Celery jobs
5. `rediska-worker` consumes Celery jobs; calls providers, llama.cpp; writes DB/ES/files

### Container Naming
All containers use `rediska-` prefix:
- `rediska-nginx`
- `rediska-web`
- `rediska-core`
- `rediska-worker`
- `rediska-beat`
- `rediska-redis`
- `rediska-mysql`
- `rediska-elasticsearch`

### API Design
- Core API endpoints are RESTful
- Cursor-based pagination: `?cursor=&limit=`
- All mutating endpoints write to `audit_log`
- All Celery tasks use `jobs` table for idempotency

### Provider Integration
Provider-specific code lives in `services/core/rediska_core/providers/{provider_name}/`
- `client.py` - API client
- `oauth.py` - OAuth flow
- `mappers.py` - Map provider responses to domain models

---

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `providers` | Registered providers (reddit, etc.) |
| `local_users` | Single admin user authentication |
| `sessions` | Server-side session storage |
| `external_accounts` | Counterpart identities on providers |
| `conversations` | Chat threads |
| `messages` | Individual messages |
| `attachments` | Local file references |
| `lead_posts` | Saved posts from provider locations |
| `profile_snapshots` | LLM-generated profile summaries |
| `profile_items` | Public content items (posts/comments/images) |
| `provider_credentials` | Encrypted OAuth tokens |
| `do_not_contact` | Safety blocklist |
| `audit_log` | Append-only action log |
| `jobs` | Celery task idempotency ledger |

---

## Environment Variables

### Required
```env
# Database
MYSQL_URL=mysql+pymysql://user:pass@rediska-mysql:3306/rediska
MYSQL_ROOT_PASSWORD=
MYSQL_DATABASE=rediska
MYSQL_USER=
MYSQL_PASSWORD=

# Redis
REDIS_URL=redis://rediska-redis:6379/0
CELERY_BROKER_URL=redis://rediska-redis:6379/1
CELERY_RESULT_BACKEND=redis://rediska-redis:6379/2

# Elasticsearch
ELASTIC_URL=http://rediska-elasticsearch:9200

# Storage paths (host paths mounted to containers)
ATTACHMENTS_PATH=/var/lib/rediska/attachments
BACKUPS_PATH=/var/lib/rediska/backups

# LLM endpoints
INFERENCE_URL=
INFERENCE_MODEL=
INFERENCE_API_KEY=
EMBEDDINGS_URL=
EMBEDDINGS_MODEL=
EMBEDDINGS_API_KEY=

# Web
BASE_URL=https://rediska.local
NEXTAUTH_SECRET=

# Provider: Reddit
PROVIDER_REDDIT_ENABLED=true
PROVIDER_REDDIT_CLIENT_ID=
PROVIDER_REDDIT_CLIENT_SECRET=
PROVIDER_REDDIT_REDIRECT_URI=
PROVIDER_REDDIT_USER_AGENT=

# Rate limiting
PROVIDER_RATE_QPM_DEFAULT=60
PROVIDER_RATE_CONCURRENCY_DEFAULT=2
PROVIDER_RATE_BURST_FACTOR=1.5
```

---

## Celery Tasks

### Ingest Pipeline
- `ingest.backfill_conversations` - Full conversation history import
- `ingest.backfill_messages` - Per-conversation message import
- `ingest.sync_delta` - Incremental sync
- `ingest.browse_location` - Browse subreddit/channel
- `ingest.fetch_post` - Fetch single post
- `ingest.fetch_profile` - Fetch user profile
- `ingest.fetch_profile_items` - Fetch user posts/comments/images

### Indexing
- `index.upsert_content` - Index content to Elasticsearch

### Embeddings
- `embed.generate` - Generate embeddings for text

### Agent Tasks
- `agent.profile_summary` - Generate profile summary
- `agent.lead_scoring` - Score lead posts
- `agent.draft_intro` - Draft introduction message

### Messaging
- `message.send_manual` - Send message (manual trigger only)

### Maintenance
- `maintenance.mysql_dump_local` - Database backup
- `maintenance.attachments_snapshot_local` - Attachments backup
- `maintenance.restore_test_local` - Test backup restoration

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

### JavaScript (Jest/Vitest)
```bash
cd apps/web
npm test                         # All tests
npm test -- --watch              # Watch mode
```

### E2E Tests
```bash
# TBD - Playwright or Cypress
```

---

## Code Style

### Python
- Use type hints everywhere
- Follow PEP 8 with 100 char line limit
- Use Pydantic for schemas and validation
- Async functions for I/O operations

### TypeScript/JavaScript
- Use TypeScript for all new code
- Follow ESLint configuration
- Use React Server Components where appropriate
- Prefer named exports

---

## Security Considerations

- Nginx is the only LAN-exposed service
- All other services are Docker-network internal
- OAuth tokens are encrypted at rest in `provider_credentials`
- Passwords hashed with Argon2
- Session cookies are HttpOnly + Secure
- Audit all mutating actions
- No autosend - all sends require explicit user action

---

## Sprint Progress Tracking

Progress is tracked in `prd/Rediska_Task_Breakdown_v0.1.md`. When completing tasks:
1. Mark the checkbox as done: `- [x]`
2. Verify acceptance criteria (AC) are met
3. Ensure tests pass
4. Update audit log if applicable

### Current Sprint Status
See `prd/Rediska_Sprint_Plan_v0.1.md` for sprint objectives and acceptance criteria.

---

## Troubleshooting

### Common Issues

**MySQL connection refused**
- Check `rediska-mysql` is healthy: `docker compose ps`
- Verify `MYSQL_URL` format in `.env`

**Elasticsearch not responding**
- ES needs time to start (~30s)
- Check memory: ES requires at least 1GB heap

**Redis connection issues**
- Verify Redis is running: `docker compose exec rediska-redis redis-cli ping`

**Worker not processing tasks**
- Check worker logs: `docker compose logs rediska-worker`
- Verify broker URL matches

**TLS certificate errors**
- Regenerate certs or use mkcert for local development
- Add exception in browser for self-signed certs

---

## Definition of Done (Global)

Every feature/sprint must satisfy:
- [ ] Runs via `docker compose up -d` on a clean host following README
- [ ] Nginx terminates HTTPS, and only Nginx is exposed to LAN
- [ ] Any new endpoint that mutates state writes to `audit_log`
- [ ] Any new Celery task uses `jobs` idempotency and has retry policy
- [ ] Provider sync never deletes local records/files (only marks status/visibility)
- [ ] Every UI page has empty states and error states (no blank screens)
