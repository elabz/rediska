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
- If agent needs to work on inbox message, a temporary thread with a fake user should be created. The user should have a name starting with "test_"

---

## Documentation Map

| Document | Role |
|---|---|
| `prd/Rediska_PRD_v1.0.md` | **Single consolidated PRD** — product scope, principles, functional areas |
| `openspec/specs/<capability>/spec.md` | **Normative capability specs** (OpenSpec) — source of truth for behavior |
| `openspec/changes/` | OpenSpec change proposals (use the `opsx:*` skills to propose/apply/archive) |
| `docs/deploy.md` | Operator deploy, migration, smoke test, troubleshooting |
| `docs/inbox-backup.md` | Inbox export/import/clear — dump format, API, operational notes |
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
| HTML Parsing | `beautifulsoup4` (external listing resolution — see below) |

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
      alembic/versions/        # head: 018_add_analysis_evaluations

    worker/                    # Celery worker (imports core)
      rediska_worker/
        celery_app.py          # queues, beat schedule
        tasks/                 # ingest, index, embed, agent, message,
                               # multi_agent_analysis, scout, maintenance, evaluation
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

### Human Evaluation of Agent Decisions
Explicit, append-only human verdicts on analysis output (`/evaluations` UI, `/evaluations` API, `domain/services/analysis_evaluation.py`, `domain/services/prompt_replay.py`):
- A subject is a `lead_analyses` row or an analysed `scout_watch_posts` row; an evaluation targets the **final recommendation** (`dimension = NULL`) or **one dimension**, with verdict agree / partial / disagree, optional corrected value, controlled reason tags (`REASON_TAGS` in `api/schemas/evaluations.py`, mirrored in `apps/web/src/lib/evaluations.ts`), `missing_info` (required for `missing_context`), and notes. Each row snapshots the judged agent output and prompt versions; the latest row per (subject, dimension) is the effective verdict
- Evaluations never change an analysis, a lead status, or a scout post; every record/export writes `audit_log` (`evaluation.record`, `evaluation.export`)
- **Review queue** (`GET /evaluations/queue`): contradictions first (a `suitable` lead marked `ignored`, a non-suitable scout post manually promoted), then `suitable` / `needs_review` / `not_recommended` interleaved round-robin; `needs_review` ordered by score desc then fewest unclear gates so near-misses come first. Sample pass defaults to a 30-day window; contradictions have none
- **Summary** (`GET /evaluations/summary`): agreement per dimension and per prompt version, tag distribution, final-verdict confusion matrix, weekly trend, missing-info aggregation. Plain Python over effective rows (no LLM)
- **Export** (`GET /evaluations/export?dimension=`): JSONL, content verbatim
- **Prompt replay** (`POST /agent-prompts/{dimension}/replay`, worker task `evaluation.replay_prompt`): re-runs one dimension agent on labelled cases with a transient prompt (`db=None`, nothing persisted) and compares to the human-corrected value via `compare_fields()` (categorical exact, age ±2, list overlap ≥ 0.5). Uses the stored full input prompt (`analysis_dimensions.input_data_json.prompt`, recorded since this feature), rebuilds context from the lead when only an excerpt exists, and counts scout-only cases as `skipped_no_input`. One replay at a time; capped by `EVALUATION_REPLAY_MAX_CASES`; cancellable via the `jobs` ledger. `GET /agent-prompts/{dimension}/versions` carries per-version `evaluations` / `agreement`
- Evaluated scout posts (`evaluated_at`) and the runs that own them are exempt from history cleanup
- Analysis read models (`/leads/{id}/analysis*`, scout run detail) carry `evaluation` fields; the UI mounts `EvaluationControl` on the recommendation card, dimension cards, scout history posts, and the review queue

### External Listing Resolution
Some subreddits (e.g. r/bdsmpersonals) now post link-only submissions whose `selftext` is empty and whose URL points to an external listing page. `domain/services/external_listing.py` fetches such pages and substitutes the listing's About text as the post body, so browse cards and the LLM analysis pipeline see real content:
- Registry of supported hosts (initially `weheartbdsm.com/listings/<id>`) maps URL pattern → parser; unregistered hosts are never fetched (no generic scraping)
- `maybe_resolve_post_body(body_text, url)` is called **synchronously before persistence** in `LeadsService.save_lead`, `ScoutWatchService.record_post`, `profile-items/ingest-browse-posts`, and `BrowseService` — resolution always completes before any analysis is enqueued
- `tasks/scout.py` also resolves *before* calling `record_post`, because it needs the resolved text for its own empty-body skip and for the `analyze_and_decide` payload. Double resolution is safe and free: `maybe_resolve_post_body` short-circuits on a body that is no longer link-only, so the second call never fetches
- `ensure_lead_listing_content()` is a defensive re-check in the analysis path for leads stored before this existed
- Best-effort: fetch/parse failures keep the original body, log a warning, and never fail ingestion
- Polite: 10s timeout, identifying UA, per-host rate limit (30/min), Redis cache (resolved ~7d, negative ~1h) keyed by canonical URL with tracking params stripped
- Parsing uses `beautifulsoup4`; per-host parsers are unit-tested against synthetic HTML fixtures

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
| `/evaluations` | Human evaluation of agent decisions: review queue (contradictions first, stratified), dashboard (agreement per dimension / prompt version, confusion matrix, tags, trend, missing info), JSONL export |
| `/search` | Global hybrid search across messages/leads/profiles/conversations |
| `/profile/[accountId]` | Account profile: snapshot, signals, risk flags, posts/comments/images |
| `/ops` | Job queue, sync, backfills, attachment re-download |
| `/ops/backup` | Inbox export / import / clear with progress tracking |
| `/audit` | Audit log viewer |
| `/settings/connection`, `/settings/personas`, `/settings/agents`, `/settings/scout-watches` (+ `/[watchId]/history`) | Reddit connection, voice personas, agent prompts (with per-version evaluation metrics and a Replay tab), scout watches (history posts carry evaluation controls) |

---

## Key Database Tables

Head migration: `018_add_analysis_evaluations`.

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
| `scout_watches`, `scout_watch_runs`, `scout_watch_posts` | Scout watch config, run history, seen-post pipeline (`evaluated_at` exempts a post from cleanup) |
| `analysis_evaluations` | Append-only human verdicts on a lead analysis or scout post (final or per dimension), with agent snapshot + prompt versions |
| `prompt_replays` | Candidate-prompt replays against labelled cases: status, progress, agreement, per-case results |
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

# Human evaluation: cap on labelled cases per prompt replay
EVALUATION_REPLAY_MAX_CASES=50
```

---

## Celery Tasks

Queues: `ingest`, `index`, `embed`, `agent`, `messages`, `multi_agent_analysis`, `scout`, `maintenance`, `transfer`.

### Ingest
- `ingest.backfill_conversations` / `ingest.backfill_messages` — history import
- `ingest.sync_inbox_fast` — inbox-only sync (beat: every 60s, max 5 pages)
- `ingest.sync_sent` — sent-folder sync (beat: every 300s, max 5 pages)
- `ingest.sync_delta` — inbox + sent, on-demand "Sync now" only (not scheduled, max 20 pages)
- All message syncs hold a per-identity Redis lock (`rediska:lock:message_sync:reddit:<id>`); a scheduled run that finds it held returns `skipped`. The Reddit adapter paces requests from `X-Ratelimit-*` headers
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

### Prompt Replay (queue: `multi_agent_analysis`)
- `evaluation.replay_prompt` — replays a candidate prompt against labelled evaluation cases; `jobs` idempotency keyed on the replay id, `max_retries=0`, cancellable between cases, shares the inference gate with live analyses

### Messaging
- `message.send_manual` — manual trigger only; `max_retries=0` (at-most-once)

### Inbox Backup / Restore (queue: `transfer`)
- `inbox.export` — dump conversations/messages/attachment metadata to JSON
- `inbox.import` — atomic restore from a dump (skips existing content)
- `inbox.clear` — delete inbox rows; keeps accounts, leads, profiles, and attachment files

### Maintenance (beat-scheduled)
- `maintenance.mysql_dump_local` (daily 03:00 UTC)
- `maintenance.attachments_snapshot_local` (daily 04:00 UTC)
- `maintenance.restore_test_local` (weekly, Sun 05:00 UTC)
- `maintenance.cleanup_scout_watch_history` (daily 02:00 UTC, 3-day retention; skips evaluated posts and the runs that own them)

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
