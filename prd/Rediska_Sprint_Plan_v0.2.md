# Rediska – Sprint Plan v0.2
**Date:** 2026-01-09
**Cadence assumption:** 2-week sprints (adjustable)
**Goal:** Ship a working, end-to-end local system in vertical slices, minimizing "platform first" risk.

> This plan assumes you're building solo (or small team) and prioritizing an early working spine: **Auth → Identity Setup → Sync → Inbox → Search → Leads → Agent**.

---

## Global Definition of Done (applies to every sprint)
- [ ] Runs via `docker compose up -d` on a clean host following README.
- [ ] Nginx terminates HTTPS, and only Nginx is exposed to LAN.
- [ ] Any new endpoint that mutates state writes to `audit_log`.
- [ ] Any new Celery task uses `jobs` idempotency and has retry policy.
- [ ] Provider sync never deletes local records/files (only marks status/visibility).
- [ ] Every UI page has empty states and error states (no blank screens).
- [ ] **All new features have unit tests written BEFORE implementation (TDD).**
- [ ] **Integration tests verify feature works with real dependencies.**
- [ ] **Test coverage for new code >= 80%.**

---

## Sprint 0 (pre-sprint / 1–2 days): "Bootstrap"
**Objective:** establish a reproducible dev environment and skeleton services.

### Scope (checklist)
- [x] Repo scaffolding created (per Spec Pack v0.4)
- [x] `.env.example` + `.gitignore`
- [x] Nginx config in place + local certs guidance
- [x] `docker-compose.yml` baseline starts all containers
- [x] Core service skeleton (`/healthz`)
- [x] Web app skeleton (landing + login route placeholder)
- [ ] **Test infrastructure setup (pytest for Python, Jest/Vitest for JS)**
- [ ] **CI configuration for running tests**

### Deliverable
- **Bring-up success:** `https://rediska.local` loads a placeholder page.
- **Tests run:** `pytest` and `npm test` execute without errors.

### Risks / Notes
- Cert UX in browsers can slow iteration. Use a simple internal CA or mkcert approach locally.

---

## Sprint 1 (2 weeks): "Working spine: Auth + Identity Setup + DB + Inbox (mock data)"
**Objective:** Implement the foundational platform with identity management, usable UI reading from DB, without touching provider APIs yet.

### Sprint goal
A user can log in, **set up at least one identity**, see Inbox and Conversations populated from seeded data, and browse audit logs.

### Dependencies
- Sprint 0 complete (compose, TLS, skeleton services, test infrastructure)

### Scope (checklist)

#### Platform foundation
- [ ] Core config loader with strict env validation
- [ ] Alembic migrations for v0.4 schema (providers, users, **identities**, conversations, messages, audit, jobs, attachments table stub ok)
- [ ] Admin bootstrap method (one-time create user)
- [ ] Auth:
  - [ ] `POST /auth/login` (with tests)
  - [ ] `POST /auth/logout` (with tests)
  - [ ] auth middleware to protect endpoints (with tests)
- [ ] Audit writer utility + `GET /audit` paging endpoint (with tests)

#### Identity Management (NEW)
- [ ] Identity model and service layer (with tests)
- [ ] Identity CRUD endpoints:
  - [ ] `GET /identities` (with tests)
  - [ ] `POST /identities` (with tests)
  - [ ] `GET /identities/{id}` (with tests)
  - [ ] `PATCH /identities/{id}` (with tests)
  - [ ] `DELETE /identities/{id}` (with tests)
  - [ ] `POST /identities/{id}/set-default` (with tests)
- [ ] Setup status endpoint: `GET /setup/status` (with tests)
- [ ] Onboarding gate middleware (requires identity before inbox access)
- [ ] Seed script to create test identity for development

#### Inbox/Conversation API (DB-backed, identity-aware)
- [ ] `GET /conversations?cursor&limit&identity_id` (with tests)
- [ ] `GET /conversations/{id}/messages?cursor&limit` (with tests)
- [ ] Cursor strategy documented (e.g., `(last_activity_at,id)` for conversations; `(sent_at,id)` for messages)
- [ ] Seed script to generate:
  - [ ] provider row (`provider_id='reddit'` but in core it's just a provider id)
  - [ ] identity row for testing
  - [ ] N conversations + M messages for UI testing
- [ ] Ensure indexes for paging are present (`messages(conversation_id, sent_at)` etc.)

#### Web UI (minimal but usable)
- [ ] Login page (username/password)
- [ ] **Identity setup page (onboarding flow)**
  - [ ] Create identity form
  - [ ] Voice configuration panel
  - [ ] Set default identity
- [ ] App shell nav: Inbox, Search, Ops, Audit (placeholders ok)
- [ ] Inbox page:
  - [ ] **Identity selector/filter**
  - [ ] conversation list with last_activity, counterpart name, badges placeholder
  - [ ] paging "Load more"
- [ ] Conversation page:
  - [ ] **Shows which identity is being used**
  - [ ] message list with pagination
  - [ ] basic "compose" box disabled (send later)

#### Observability basics
- [ ] Structured logs (at least request logs + error logs) in core and web

### Acceptance Criteria
- [ ] You can log in and browse seeded conversations/messages in UI.
- [ ] **You must set up at least one identity before accessing inbox.**
- [ ] **Conversations are filtered/grouped by identity.**
- [ ] Audit page shows audit events for login/logout and any DB mutations (seed can also write audit).
- [ ] Pagination works and doesn't time out with hundreds of seeded chats.
- [ ] **All features have passing unit and integration tests.**

### Out of scope (explicit)
- Provider OAuth/sync
- Elasticsearch + embeddings
- Attachments upload
- Sending messages

---

## Sprint 2 (2 weeks): "Real data: Provider OAuth + Identity OAuth + Backfill + Delta Sync + Inbox"
**Objective:** Replace mocked/seeded data with real provider data ingestion while respecting API limits and no-delete policy. Identity OAuth flow connects real accounts.

### Sprint goal
After OAuth, the system backfills conversations/messages into MySQL and keeps syncing incrementally; Inbox reflects real chats for each identity.

### Dependencies
- Sprint 1 complete (auth, identity setup, DB, inbox UI + APIs)

### Scope (checklist)

#### Provider OAuth (reddit module) - Identity-aware
- [ ] Provider credentials storage (`provider_credentials`) linked to identity, with encryption (at-rest)
- [ ] OAuth endpoints:
  - [ ] `GET /providers/reddit/oauth/start?identity_id` (with tests)
  - [ ] `GET /providers/reddit/oauth/callback` (with tests)
- [ ] Ops UI control: "Connect Identity" + connection status per identity

#### Worker platform
- [ ] Celery app configured (routing per queues)
- [ ] Jobs ledger utilities enforced for all tasks (dedupe_key required)
- [ ] Redis-backed rate limiter implemented and used for all provider calls
- [ ] Retry/backoff helper for 429/5xx/network timeouts

#### Ingest pipeline (MySQL only) - Identity-aware
- [ ] Tasks:
  - [ ] `ingest.backfill_conversations(identity_id)` (with tests)
  - [ ] `ingest.backfill_messages` (cursor-driven, per conversation) (with tests)
  - [ ] `ingest.sync_delta(identity_id)` (with tests)
- [ ] Fan-out orchestration:
  - [ ] backfill conversations enqueues per-conversation message backfills
- [ ] Delta schedule (beat):
  - [ ] configurable interval per identity
- [ ] "No remote delete" mapping:
  - [ ] external_accounts.remote_status set based on provider signals
  - [ ] messages.remote_visibility set based on provider signals
  - [ ] never set `deleted_at` during sync

#### Ops visibility
- [ ] Core endpoints:
  - [ ] `POST /ops/backfill/start` (identity_id)
  - [ ] `POST /ops/sync/start`
  - [ ] `GET /jobs` (filter by status/type)
- [ ] Ops UI:
  - [ ] Backfill progress per identity (counts + latest job statuses)
  - [ ] Last sync time and result summary per identity

#### Inbox UI (real data)
- [ ] Conversation list reflects imported data, grouped by identity
- [ ] Badges:
  - [ ] counterpart deleted/suspended
  - [ ] message deleted/removed
- [ ] Search in Inbox list (client-side string filter ok; real search later)

### Acceptance Criteria
- [ ] OAuth connects successfully and is persisted per identity.
- [ ] Backfill runs to completion on a large history without violating rate limits.
- [ ] Delta sync updates new messages and remote deletion statuses, without deleting anything locally.
- [ ] Inbox UI shows real conversations/messages grouped by identity.
- [ ] **All features have passing unit and integration tests.**

### Out of scope (explicit)
- Elasticsearch + embeddings + hybrid search
- Leads/browse workflow
- Attachments and sending messages

---

## Sprint 3 (2 weeks): "Search + Leads + Analysis pipeline (ES + embeddings)"
**Objective:** Add hybrid search and the "find candidates" workflow: browse location → save post → fetch profile/items → index/embed → searchable.

### Sprint goal
User can browse a location, save a post, run analysis, and then find the content via hybrid search. All content is identity-aware.

### Dependencies
- Sprint 2 complete (provider data ingestion stable)

### Scope (checklist)

#### Elasticsearch
- [ ] Create ES index `rediska_content_docs_v1` (admin op or startup)
- [ ] Implement `index.upsert_content` task for:
  - [ ] messages (with identity_id)
  - [ ] lead_posts
  - [ ] profile_items
  - [ ] profile_snapshots (optional this sprint)
- [ ] Implement mapping finalization (set `dense_vector.dims` to match embedding model)

#### Embeddings
- [ ] Embeddings client wrapper (llama.cpp)
- [ ] Implement `embed.generate` task that:
  - [ ] generates embedding for `text`
  - [ ] updates ES doc
- [ ] Backfill embeddings for existing messages in batches (throttled)

#### Hybrid search API + UI
- [ ] Core `POST /search`:
  - [ ] BM25 query + kNN query + weighted merge
  - [ ] filters: provider_id, **identity_id**, remote_status exclusions, local_deleted
- [ ] Web Search page:
  - [ ] **Identity filter**
  - [ ] query box, filters, results grouped by doc_type
  - [ ] click-through to conversation/profile/lead

#### Leads: browse + save + analyze
- [ ] Core browse endpoint:
  - [ ] `GET /sources/{provider_id}/locations/{location}/posts`
- [ ] Lead saving:
  - [ ] `POST /leads/save`
- [ ] Lead analysis orchestration:
  - [ ] `POST /leads/{id}/analyze` enqueues:
    - fetch post (if needed)
    - fetch author profile + items (posts/comments/images list; images may be URLs only for now)
    - persist to DB
    - index + embed
- [ ] Directories:
  - [ ] analyzed/contacted/engaged endpoints (even if "engaged" stays empty)

#### Ops improvements
- [ ] Ops shows ES indexing/embedding backlog and failures
- [ ] Audit entries for lead save/analyze actions

### Acceptance Criteria
- [ ] Hybrid search returns results across messages and leads (at minimum).
- [ ] **Search can filter by identity.**
- [ ] User can browse a location, save a post, analyze it, and later find it in search.
- [ ] Indexing + embeddings pipeline is stable and resumes after restarts.
- [ ] **All features have passing unit and integration tests.**

### Out of scope (explicit)
- Agent summaries/scoring (next sprint)
- Attachments upload and message sending
- Backups/restore tests automation (next sprint)

---

## Sprint 4 (2 weeks): "Agents + Attachments + Manual Send + Backups"
**Objective:** Add the LLM-assisted experience (summaries/scoring/drafts using identity voice) and the core safety/ops features (attachments, manual sending, backups).

### Sprint goal
User can analyze profiles with summaries/scoring and draft intros **using identity's voice configuration**; optionally attach an image and manually send a message; backups run daily with restore tests weekly.

### Dependencies
- Sprint 3 complete (ES + embeddings + leads pipeline)

### Scope (checklist)

#### Agent infrastructure (PydanticAI) - Voice-aware
- [ ] Inference client wrapper (llama.cpp chat/completions)
- [ ] Agent harness:
  - [ ] structured outputs (Pydantic)
  - [ ] model_info_json capture
  - [ ] tool allowlist (no send tool)
  - [ ] **voice_config injection from identity**
- [ ] `agent.profile_summary(account_id)` → writes `profile_snapshots`
- [ ] `agent.lead_scoring(lead_post_id)` → stores score/reasons (json fields or separate table later)
- [ ] `agent.draft_intro(target, identity_id)` → returns/store draft text using identity voice (does not send)

#### UI: profile + draft flows
- [ ] Profile page with:
  - [ ] summary + evidence sections
  - [ ] posts/comments/images tabs
- [ ] Draft intro UI:
  - [ ] **Identity selector for drafting**
  - [ ] "Generate draft" button
  - [ ] editable text area
  - [ ] "Send" button triggers manual send endpoint

#### Attachments (local FS)
- [ ] `POST /attachments/upload` + `GET /attachments/{id}` (with tests)
- [ ] UI upload component integrated into compose box

#### Manual send message (v1 only) - Identity-aware
- [ ] Provider send implementation in reddit adapter
- [ ] Core `POST /conversations/{id}/messages` enqueues `message.send_manual`
  - [ ] **Uses conversation's identity for sending**
- [ ] At-most-once policy enforced:
  - [ ] do not auto-retry ambiguous outcomes
  - [ ] surface "unknown" state in UI for manual resolution

#### Backups + restore tests (local-only)
- [ ] Maintenance tasks:
  - [ ] `maintenance.mysql_dump_local`
  - [ ] `maintenance.attachments_snapshot_local`
  - [ ] `maintenance.restore_test_local`
- [ ] Beat schedule:
  - [ ] daily backups
  - [ ] weekly restore test
- [ ] Ops UI shows last backup and last restore test status

### Acceptance Criteria
- [ ] Profile summary and lead scoring are generated and persisted with model info.
- [ ] **Draft intro uses the selected identity's voice configuration.**
- [ ] Draft intro can be generated and manually sent (no autosend).
- [ ] Attachments up to 10MB can be uploaded and attached to a message.
- [ ] Backups are created automatically; restore tests run and are visible in Ops + Audit.
- [ ] **All features have passing unit and integration tests.**

---

## Recommended "stop points" (ship-ready checkpoints)
- **After Sprint 1:** "Identity Setup + Mock Inbox" (auth + identity + seeded chats)
- **After Sprint 2:** "Inbox replacement" (real synced chats per identity)
- **After Sprint 3:** "Discovery + Search" (find leads + search everything)
- **After Sprint 4:** "Full v1 experience" (agents + manual outreach + backups)

---

## Risk register (keep an eye on these)
- [ ] Provider API quirks / lack of stable IDs → invest in robust dedupe keys.
- [ ] Backfill duration + rate limiting → implement safe fan-out + job resume.
- [ ] ES vector dims mismatch with embedding model → lock dims early.
- [ ] Manual send ambiguity → keep strict at-most-once and UI reconciliation.
- [ ] Sensitive local data → confirm filesystem permissions and host firewall.
- [ ] **Identity OAuth complexity → test OAuth flows thoroughly for each identity.**
- [ ] **Voice config conflicts → validate voice_config_json schema strictly.**

---

**End of Sprint Plan v0.2**
