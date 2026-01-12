# Rediska – Task Breakdown v0.2
**Date:** 2026-01-09
**Format:** Markdown checklists for implementation tracking
**Assumptions:** Spec Pack v0.4 is source-of-truth; local-only storage; no autosend (v1); provider-agnostic core; identity-aware conversations; TDD approach; initial provider integration for Reddit.

---

## Legend
- **[ ]** not started
- **[x]** done
- **(D)** dependency note
- **(T)** test requirement
- **AC:** acceptance criteria

---

## Global Testing Requirements

Every feature implementation must follow TDD:
1. Write failing unit tests first
2. Implement feature to pass tests
3. Write integration tests
4. Refactor while keeping tests green

Test file naming:
- `test_{feature}_unit.py` - Unit tests
- `test_{feature}_integration.py` - Integration tests

---

## Phase 0 — Project setup & developer ergonomics

### Epic 0.1 — Repo scaffolding
- [x] Create monorepo folder structure (`apps/web`, `services/core`, `services/worker`, `nginx`, `scripts`, `specs`)
  - AC: Structure matches Spec Pack v0.4 and builds without missing paths.
- [x] Add `README.md` with local dev instructions (compose up, certs, env)
  - AC: A new machine can get to login screen following README.
- [x] Add `.env.example` and `.gitignore` (ignore certs, local data dirs, `.env`)
  - AC: `cp .env.example .env` is sufficient to start (with placeholder values).

### Epic 0.2 — Local TLS & hostnames
- [x] Create local TLS cert approach (self-signed or internal CA) and document
  - AC: Browser can access `https://rediska.local` (even if warning accepted).
- [x] Add Nginx config `nginx/rediska.conf` and `nginx/certs/` placeholders
  - AC: Nginx container starts and reverse-proxies to web.

### Epic 0.3 — Docker Compose baseline
- [x] Implement `docker-compose.yml` with all `rediska-*` container names
  - AC: `docker compose up -d` starts all services.
- [x] Add healthchecks and dependency ordering
  - AC: Core waits for MySQL/Redis/ES health before reporting healthy.
- [x] Create local host directories for `ATTACHMENTS_PATH` and `BACKUPS_PATH` and bind-mount
  - AC: Upload path and backup path exist and are writable from containers.

### Epic 0.4 — Test Infrastructure (NEW)
- [x] Set up pytest for `services/core` with conftest.py
  - [x] Database fixtures (test DB or SQLite)
  - [x] HTTP client fixtures
  - [x] Mock fixtures for external services
  - AC: `pytest` runs and discovers tests.
- [ ] Set up pytest for `services/worker` with conftest.py
  - AC: Worker tests can run without Redis/Celery.
- [ ] Set up Jest/Vitest for `apps/web`
  - [ ] Component test utilities
  - [ ] API mock utilities
  - AC: `npm test` runs and discovers tests.
- [x] Configure test coverage reporting
  - AC: Coverage reports generated on test run.
- [ ] Add CI configuration (GitHub Actions or similar)
  - AC: Tests run automatically on push/PR.

---

## Phase 1 — Core platform (auth, DB, API, audit, jobs)

### Epic 1.1 — Core service skeleton (FastAPI)
- [x] Create Python project for `services/core` (pyproject, dependencies)
  - Suggested deps: fastapi, uvicorn, sqlalchemy, alembic, pymysql, redis, httpx, elasticsearch, argon2-cffi, python-multipart
  - AC: `GET /healthz` returns `{ "ok": true }`.
- [x] Implement configuration loader (env var validation, typed config)
  - AC: Core fails fast with clear error when required env missing.

### Epic 1.2 — DB migrations (Alembic) + canonical schema
- [x] Initialize Alembic and create initial migration for v0.4 schema
  - Tables: providers, local_users, sessions (optional), **identities**, external_accounts, conversations (with identity_id), messages (with identity_id), attachments, lead_posts, profile_snapshots, profile_items, provider_credentials (with identity_id), do_not_contact, audit_log (with identity_id), jobs
  - AC: `alembic upgrade head` creates all tables in MySQL.
- [ ] Add migration runner step in compose/startup (manual is fine for now)
  - AC: Fresh DB can be migrated deterministically.

### Epic 1.3 — Authentication (single user)
- [x] (T) Write unit tests for password hashing and verification
- [x] Implement password hashing (Argon2) and admin bootstrap method
  - Bootstrap options: env-based init, CLI command, or "create first user" endpoint guarded by local-only token
  - AC: One admin user exists and can authenticate.
- [x] (T) Write unit tests for session creation/validation/expiry
- [x] Implement session mechanism (choose one)
  - [x] Server-side sessions in DB (`sessions` table)
  - AC: Auth cookie is HttpOnly + Secure; requests without session are rejected.
- [x] (T) Write integration tests for auth endpoints
- [x] Implement Core auth endpoints:
  - [x] `POST /auth/login`
  - [x] `POST /auth/logout`
  - [x] `GET /auth/me` (current user info)
  - AC: login sets session; logout invalidates session.

### Epic 1.4 — Identity Management (NEW)
- [x] (T) Write unit tests for identity CRUD operations
- [x] Implement Identity model and repository (IdentityService)
  - AC: Can create, read, update, delete identities.
- [x] (T) Write unit tests for default identity logic
- [x] Implement default identity business rules
  - [x] Exactly one default per provider
  - [x] Auto-set first identity as default
  - AC: Cannot have zero or multiple defaults per provider.
- [x] (T) Write unit tests for voice config validation
- [x] Implement voice_config_json schema validation
  - AC: Invalid voice configs are rejected.
- [x] (T) Write integration tests for identity endpoints
- [x] Implement Identity API endpoints:
  - [x] `GET /identities` - list all, optionally grouped by provider
  - [x] `POST /identities` - create new
  - [x] `GET /identities/{id}` - get details
  - [x] `PATCH /identities/{id}` - update display_name, voice_config, is_active
  - [x] `DELETE /identities/{id}` - soft delete (deactivate)
  - [x] `POST /identities/{id}/set-default` - set as default for provider
  - AC: All CRUD operations work with proper validation.
- [x] (T) Write integration tests for onboarding gate
- [x] Implement onboarding gate middleware
  - [x] `GET /setup/status` returns onboarding state
  - [x] Middleware blocks inbox/conversation access without identity
  - AC: New users must create identity before using system.

### Epic 1.5 — Audit log (append-only)
- [x] (T) Write unit tests for audit entry creation
- [x] Implement audit writer utility (DB insert only; never update)
  - [x] Include identity_id in audit entries where applicable
  - AC: All mutating endpoints write an audit entry with actor/action/result/identity.
- [x] (T) Write integration tests for audit query
- [x] Implement audit query endpoint: `GET /audit?cursor=&limit=&action_type=&identity_id=`
  - AC: UI can page through audit entries, filter by identity.
- [x] Add audit coverage to mutating endpoints:
  - [x] conversation.py: send_message, retry_message, trigger_sync
  - [x] leads.py: save_lead, update_lead_status, analyze_lead
  - [x] attachment.py: upload_attachment
  - [x] auth.py: login, logout (already had)
  - [x] identity.py: create (already had)

### Epic 1.6 — Jobs ledger & idempotency utilities
- [x] (T) Write unit tests for dedupe_key computation
- [x] Implement `jobs` helper:
  - [x] compute `dedupe_key`
  - [x] atomic insert/upsert of job row
  - [x] lock/claim job for execution
  - [x] update status transitions and attempt counters
  - AC: Re-running same job payload does not duplicate work.
- [x] (T) Write unit tests for error serialization
- [x] Implement consistent error serialization for `last_error`
  - AC: Ops view can display meaningful failure reasons.

---

## Phase 2 — Worker platform (Celery) + rate limiter

### Epic 2.1 — Worker skeleton (Celery)
- [x] Create Python project for `services/worker` that imports core modules
  - AC: Worker container starts and registers tasks.
- [x] Configure Celery app:
  - [x] broker/result backend from env
  - [x] queue routing
  - [x] task time limits defaults (soft/hard)
  - AC: a test task can be queued and executed.

### Epic 2.2 — Redis-backed rate limiter (provider calls)
- [x] (T) Write unit tests for token bucket algorithm
- [x] Implement token bucket + inflight concurrency limiter using Redis keys
  - Keys: `rate:{provider_id}:tokens`, `rate:{provider_id}:last_refill_ts`, `rate:{provider_id}:inflight`
  - AC: Under load, provider calls do not exceed QPM/concurrency settings.
- [x] (T) Write unit tests for backoff strategy
- [x] Implement backoff strategy helper (429/5xx aware)
  - AC: 429 triggers throttled retries, not hot loops.

---

## Phase 3 — Provider integration v1 (Reddit) (isolated module)

> Provider-specific code may use "reddit" in filenames/classes.

### Epic 3.1 — OAuth setup (Reddit) - Identity-aware
- [x] (T) Write unit tests for credential encryption/decryption
- [x] Implement provider credentials storage (encrypt refresh token) linked to identity
  - AC: Refresh token stored encrypted; can be rotated; linked to identity.
- [x] (T) Write integration tests for OAuth flow
- [x] Implement OAuth endpoints:
  - [x] `GET /providers/reddit/oauth/start?identity_id`
  - [x] `GET /providers/reddit/oauth/callback`
  - AC: User can authorize identity; credentials persist; audit entry written with identity.

### Epic 3.2 — Provider adapter interface + mappers
- [x] (T) Write unit tests for provider interface methods
- [x] Define provider-agnostic interface in core (`ProviderClient` / service layer)
  - AC: Core can call provider methods through interface.
- [x] (T) Write unit tests for Reddit adapter with mocked responses
- [x] Implement Reddit adapter methods (minimum):
  - [x] list conversations (for identity)
  - [x] list messages for a conversation
  - [x] browse location (subreddit)
  - [x] fetch post
  - [x] fetch user profile
  - [x] fetch user items (posts/comments/images)
  - [x] send message (using identity credentials)
  - AC: Each method returns normalized DTOs with stable IDs when available.

### Epic 3.3 — "No remote delete" mapping rules
- [x] (T) Write unit tests for status mapping logic
- [x] Map provider deletion states to:
  - `external_accounts.remote_status`
  - `messages/lead_posts/profile_items.remote_visibility`
  - AC: Sync never deletes local rows; UI can show "deleted/removed" badges.

---

## Phase 4 — Ingestion pipelines (backfill + delta sync) within API limits

### Epic 4.1 — Backfill orchestration (conversations → messages) - Identity-aware
- [x] (T) Write unit tests for backfill task logic
- [x] Implement task: `ingest.backfill_conversations(identity_id)`
  - AC: Creates conversations in DB without duplicates, linked to identity.
- [x] (T) Write unit tests for message backfill
- [x] Implement task: `ingest.backfill_messages(provider_id, conversation_id, identity_id)`
  - AC: Ingests full history for that conversation; cursor-driven; idempotent.
- [ ] (T) Write integration tests for fan-out
- [ ] Implement fan-out strategy:
  - backfill conversations then enqueue per-conversation message backfill tasks
  - AC: Large accounts complete without violating rate limits.

### Epic 4.2 — Incremental sync - Identity-aware
- [ ] (T) Write unit tests for delta sync logic
- [ ] Implement task: `ingest.sync_delta(identity_id, since_ts)`
  - AC: New messages and edits/deletes reflected via status fields; identity tracked.
- [ ] (T) Write integration tests for beat scheduling
- [ ] Implement periodic schedule via beat:
  - e.g. every 5–15 minutes (configurable per identity)
  - AC: system stays up to date while user also uses native app.

### Epic 4.3 — Ingest persistence rules
- [ ] (T) Write unit tests for upsert logic
- [ ] Conversation upsert rules (with identity_id)
- [ ] Message upsert rules (external_message_id uniqueness when present, identity_id for outgoing)
- [ ] Derive `last_activity_at` updates
- AC: Multiple sync runs do not create duplicates; timestamps correct; identity tracked.

---

## Phase 5 — Attachments (local filesystem) + message sending (manual only)

### Epic 5.1 — Local attachment store
- [x] (T) Write unit tests for file validation and storage
- [x] Implement `POST /attachments/upload` (multipart)
  - validations: size <= 10MB, mime allowlist, sha256, (optional) width/height
  - AC: Returns attachment_id; file exists at computed storage key.
- [x] (T) Write integration tests for attachment download
- [x] Implement `GET /attachments/{id}` streaming download with auth
  - AC: Browser can view/download attachments.
- [x] Implement automatic image download during message sync
  - Detects image URLs in message bodies (Reddit images, Imgur, common formats)
  - Downloads and stores as attachments linked to message
  - AC: Images from messages are stored locally and displayed in UI.

### Epic 5.2 — Manual send message (v1) - Identity-aware
- [x] (T) Write unit tests for send validation logic
- [x] Implement Core endpoint: `POST /conversations/{id}/messages`
  - enqueues `message.send_manual`
  - Uses conversation's identity for sending
  - AC: Endpoint refuses if counterpart remote_status is deleted/suspended (unless override flag later).
- [x] (T) Write integration tests for send task
- [x] Implement worker task: `message.send_manual`
  - (D) provider adapter must support send with identity credentials
  - AC: Message appears in provider and gets synced back into DB with identity.
- [x] (T) Write unit tests for at-most-once semantics
- [x] Implement at-most-once semantics & "unknown" state handling
  - AC: Ambiguous failures never auto-retry; user can manually reconcile.

---

## Phase 6 — Elasticsearch + embeddings + hybrid search

### Epic 6.1 — ES index creation & client
- [x] (T) Write unit tests for ES client wrapper
- [x] Implement ES client in core and create index `rediska_content_docs_v1`
  - Include identity_id in mapping
  - AC: Index exists on startup or via admin op.
- [x] (T) Write unit tests for upsert_content
- [x] Implement `index.upsert_content(doc_type, entity_id)` task
  - AC: DB entity becomes ES doc with correct IDs and filters including identity_id.

### Epic 6.2 — Embeddings pipeline
- [x] (T) Write unit tests for embeddings client
- [x] Implement llama.cpp embeddings client wrapper
- [x] (T) Write unit tests for embed.generate task
- [x] Implement `embed.generate(doc_type, entity_id, text)` task
  - AC: Stores embedding in ES doc and/or updates doc with embedding.
- [x] Decide embeddings dimension and finalize mapping
  - AC: Mapping dims match model output; no ES errors.

### Epic 6.3 — Hybrid search API
- [x] (T) Write unit tests for search logic
- [x] Implement `POST /search` in core
  - BM25 + kNN + score blending
  - filters: provider_id, **identity_id**, remote_status exclusions, local_deleted
  - AC: Search returns stable, relevant results across doc types, filterable by identity.

---

## Phase 7 — Leads workflow: browse, save, analyze, directories

### Epic 7.1 — Manual browse UI + API
- [x] (T) Write unit tests for browse endpoint
- [x] Implement Core endpoint for browsing provider location posts:
  - `GET /sources/{provider_id}/locations/{location}/posts`
  - AC: Pagination/cursors work; posts render in UI.
- [x] (T) Write unit tests for lead save
- [x] Implement "save post":
  - `POST /leads/save`
  - AC: lead_posts row created/upserted; status=saved.

### Epic 7.2 — Lead analysis pipeline (profile fetch + agent)
- [x] (T) Write integration tests for analysis pipeline
- [x] Implement `POST /leads/{id}/analyze`:
  - enqueue: fetch post (if needed) → fetch author profile/items → embeddings/index → agent summary/scoring
  - AC: One click results in populated profile + scoring + searchable content.

### Epic 7.3 — Directories
- [x] (T) Write unit tests for directory filters
- [x] Implement directory endpoints:
  - analyzed/contacted/engaged filters based on state fields
  - AC: Directory lists update as workflow progresses.

---

## Phase 8 — Agent workflows (PydanticAI) + evidence + safety rails

### Epic 8.1 — Agent infrastructure - Voice-aware
- [x] (T) Write unit tests for inference client
- [x] Implement llama.cpp inference wrapper (chat/completion)
- [x] (T) Write unit tests for agent harness
- [x] Implement agent runner harness with:
  - tool allowlist
  - structured outputs (Pydantic models)
  - model_info_json recording
  - **voice_config injection from identity**
  - AC: agent runs are reproducible and logged; use identity's voice.

### Epic 8.2 — Profile summary agent
- [x] (T) Write unit tests for profile summary generation
- [x] Implement `agent.profile_summary(account_id)`
  - inputs: profile items + key metadata
  - outputs: summary_text + signals_json + risk_flags_json + citations/evidence references
  - AC: profile_snapshots row created; UI renders summary + evidence.

### Epic 8.3 — Lead scoring agent
- [x] (T) Write unit tests for lead scoring
- [x] Implement `agent.lead_scoring(lead_post_id)`
  - output: score + reasons + flags + recommended next action
  - AC: stored in lead or snapshot structures; used for sorting.

### Epic 8.4 — Draft intro agent (manual only) - Voice-aware
- [x] (T) Write unit tests for draft generation with voice config
- [x] Implement `agent.draft_intro(target, identity_id)`
  - produces draft text using identity's voice_config; does **not** send
  - AC: UI shows draft + "Send" button requiring explicit click; voice matches identity.

### Epic 8.5 — Duplicate detection suggestions (optional v1.1)
- [x] (T) Write unit tests for duplicate detection
- [x] Implement "possible duplicates" heuristic:
  - same/similar username, overlapping image hashes, etc.
  - AC: UI shows suggestions; no automatic merges.

---

## Phase 9 — Web UI (Next.js) implementation

### Epic 9.1 — Auth & app shell
- [ ] (T) Write component tests for login page
- [ ] Implement login page + session handling via BFF routes
  - AC: Unauthorized users redirected to login.
- [ ] (T) Write component tests for navigation
- [ ] Build navigation layout: Inbox, Leads, Browse, Directories, Search, Ops, Audit
  - AC: All routes load and show empty-state messaging.

### Epic 9.2 — Identity Setup UI (NEW)
- [ ] (T) Write component tests for identity setup
- [ ] Implement identity setup/onboarding page
  - [ ] Create identity form
  - [ ] Connect provider (OAuth trigger)
  - [ ] Voice configuration panel
  - [ ] Set default identity toggle
  - AC: New users can set up identity before accessing main app.
- [ ] (T) Write component tests for identity management
- [ ] Implement identity management page (settings)
  - [ ] List identities by provider
  - [ ] Edit voice config
  - [ ] Activate/deactivate identities
  - AC: Users can manage multiple identities.

### Epic 9.3 — Inbox & conversation view - Identity-aware
- [x] (T) Write component tests for inbox
- [x] Inbox list with search/filter/badges
  - [x] Search field to filter by username or message content
  - [x] Conversation time shows actual last message timestamp
  - [ ] **Identity filter/selector**
  - [ ] Group/sort conversations by identity
- [x] (T) Write component tests for conversation view
- [x] Conversation view with pagination, attachment display, compose box
  - [x] Load older messages button with cursor-based pagination
  - [x] Display attachments/images inline in message bubbles
  - [x] Compose box with manual send functionality
  - [x] Disabled compose for deleted/suspended users
  - [ ] **Display which identity is used**
- [ ] Draft suggestion panel (agent output)
  - AC: User can find chats and read history quickly; identity is always visible.

### Epic 9.4 — Leads & browse
- [ ] (T) Write component tests for lead finder
- [ ] Lead Finder page: list + sort by score + save/analyze actions
- [ ] (T) Write component tests for browse page
- [ ] Manual Browse page: location selector + post list + post detail
  - AC: User can browse and save posts manually.

### Epic 9.5 — Profile page + directories
- [ ] (T) Write component tests for profile page
- [ ] Profile page: summary, tabs for posts/comments/images, deleted badges
- [ ] (T) Write component tests for directories
- [ ] Directories pages (analyzed/contacted/engaged)
  - AC: User can manage large sets of chats/counterparts.

### Epic 9.6 — Ops + Audit UIs
- [x] (T) Write component tests for ops page
- [x] Ops page: sync/backfill controls, job statuses, last backup/restore test status
  - [ ] **Per-identity sync status**
- [x] (T) Write component tests for audit page
- [x] Audit page: filterable list of audit_log events
  - [x] Filter by action_type, actor, result
  - [x] Expandable entries showing request/response JSON
  - [x] Cursor-based pagination
  - [ ] **Filter by identity**
  - AC: user can audit system actions by identity.

### Epic 9.7 — Search UI (NEW)
- [x] Implement search page with hybrid search
  - [x] Query input with search button
  - [x] Search mode selector (hybrid/text/vector)
  - [x] Document type filter
  - [x] Search results with relevance scores
  - [x] Click-through to conversations/messages
  - AC: user can search across all indexed content.

---

## Phase 10 — Backups & restore tests (local-only)

### Epic 10.1 — Local backup job + scripts
- [x] (T) Write unit tests for backup task
- [x] Implement maintenance tasks:
  - `maintenance.mysql_dump_local`
  - `maintenance.attachments_snapshot_local`
  - AC: Creates dated dumps + checksums; snapshots attachments.
- [ ] (T) Write integration tests for beat scheduling
- [ ] Add Celery beat schedules (daily backups)
  - AC: backups run without manual intervention.

### Epic 10.2 — Restore test automation
- [x] (T) Write integration tests for restore flow
- [x] Implement `maintenance.restore_test_local`
  - spins ephemeral MySQL container, imports latest dump, runs integrity queries, samples attachments
  - AC: Records pass/fail in audit_log and surfaces in Ops UI.

---

## Phase 11 — Hardening, QA, and "done" criteria

### Epic 11.1 — Data safety & correctness
- [x] (T) Write E2E tests for no-remote-delete policy
- [x] Verify **no remote deletes** end-to-end
  - AC: deleted users/messages remain locally accessible with badge.
- [ ] (T) Write E2E tests for local delete/purge
- [ ] Verify local delete/purge flows work and are audited
  - AC: user can delete counterpart and content; optional purge removes files.

### Epic 11.2 — Performance & scaling (single host)
- [x] Add pagination everywhere (inbox, messages, posts, audit)
- [ ] Add DB indexes as needed from slow query logs
- [ ] Add ES query limits/timeouts
  - AC: UI remains responsive with "hundreds of chats".

### Epic 11.3 — Observability (local)
- [x] Add structured logs for core and worker (JSON logs recommended)
- [x] Add basic metrics endpoints (optional): queue depth, last sync times
  - AC: troubleshooting is possible without external tooling.

### Epic 11.4 — Test Coverage Review
- [x] Review and fill gaps in unit test coverage (target 80%+)
- [ ] Review and fill gaps in integration test coverage
- [ ] Add E2E tests for critical user flows
  - AC: Comprehensive test suite provides confidence for releases.

---

## Optional Phase 2 (explicitly deferred)
- [ ] VLM image tagging/NSFW classification for public images (separate endpoint and model)
- [ ] Autosend with guardrails + explicit confirmation flows + rate caps (feature-flagged)
- [ ] Multiple local users (multi-tenant)

---

## Suggested first sprint (smallest vertical slice)
- [ ] Set up test infrastructure (pytest, jest)
- [ ] Bring up compose + TLS + login page
- [ ] DB migrations + core CRUD for **identities**/conversations/messages (mock provider data)
- [ ] Identity setup UI (onboarding gate)
- [ ] Celery worker + jobs ledger + test task
- [ ] ES index creation + indexing for messages
- [ ] Basic search UI over messages (with identity filter)

---

**End of Task Breakdown v0.2**
