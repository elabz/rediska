# Rediska – Spec Pack v0.5
**Date:** 2026-02-13
**Purpose:** Engineering-level specification pack (near "build plan") for implementing Rediska, with concrete schemas, mappings, task contracts, retry/idempotency rules, and repository scaffolding.

> **Local storage only (v1):** DB/search/queue are Docker volumes; attachments and backups are local filesystem paths on the host. NAS integration is deferred but the design keeps backup targets pluggable.

---

## 0) Decisions locked in
- Reverse proxy: **Nginx**
- Web: **Next.js (React)** + BFF API routes
- Core API: **Python FastAPI**
- Async jobs: **Celery**
- Broker/Rate-limit store: **Redis**
- Source of truth DB: **MySQL**
- Hybrid search + vectors: **Elasticsearch**
- LLM + embeddings runtime: **llama.cpp**, configured with `.env`:
  - `INFERENCE_URL`, `INFERENCE_MODEL`, `INFERENCE_API_KEY`
  - `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL`, `EMBEDDINGS_API_KEY`
- **Provider-agnostic core**: "reddit" appears only inside provider module / endpoints.
- **One user** (admin): username/password; session cookies.
- **Multiple identities per provider**: user can represent themselves as different personas.
- **No remote deletes**: provider deletions never remove local records/files; only mark status + show badges.
- **No autosend (v1)**: sending requires explicit user click from UI.
- **TDD approach**: Tests written before implementation; every feature has unit and functional tests.

---

## 0.1) Identity Concept

The system supports **multiple identities per provider**. An identity represents a persona the user can use when interacting through a provider (e.g., different Reddit accounts).

### Key Rules
1. **At least one identity required**: User must configure at least one identity before using the system.
2. **One default identity per provider**: Each provider has exactly one default identity for new conversations.
3. **Identity-bound conversations**: Every conversation is associated with a specific identity.
4. **Identity-bound messages**: Outgoing messages are sent using the conversation's identity.
5. **Voice/persona per identity**: Each identity can have its own "voice" (LLM system prompt) for generating drafts.
6. **Identity switching**: User can start new conversations with any active identity; cannot change identity mid-conversation.

### Identity Lifecycle
1. User creates identity with provider credentials (OAuth)
2. User optionally configures voice/persona settings
3. User sets one identity as default per provider
4. Conversations are created using selected identity
5. Identity can be deactivated (existing conversations remain readable)

---

## 0.2) Testing Requirements (TDD)

All code must follow Test-Driven Development principles:

### Test Categories
1. **Unit Tests**: Test individual functions/methods in isolation
   - Location: `tests/unit/` in each service
   - Coverage target: 80%+ line coverage
   - Mocking: External dependencies mocked

2. **Integration Tests**: Test component interactions
   - Location: `tests/integration/` in each service
   - Database: Use test database or in-memory SQLite where possible
   - External services: Use test containers or mocks

3. **Functional/E2E Tests**: Test complete user flows
   - Location: `tests/e2e/` at monorepo root
   - Run against full stack in Docker

### TDD Workflow
1. Write failing test that describes expected behavior
2. Implement minimum code to make test pass
3. Refactor while keeping tests green
4. Document test coverage in PR

### Test Structure per Feature
```
feature/
  test_feature_unit.py      # Unit tests (written first)
  test_feature_integration.py  # Integration tests
  feature.py                # Implementation
```

---

## 1) Repository scaffolding

### 1.1 Monorepo layout
```
rediska/
  docker-compose.yml
  .env.example
  README.md

  nginx/
    rediska.conf
    certs/
      tls.crt
      tls.key

  apps/
    web/                       # Next.js app
      package.json
      next.config.js
      src/
        app/                   # (App Router) pages + layouts
        components/
        lib/
        server/                # server-only helpers
        api/                   # (optional) shared API client types
      __tests__/               # Jest/Vitest tests
        unit/
        integration/

  services/
    core/                      # FastAPI service
      pyproject.toml
      rediska_core/
        main.py
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

      tests/                   # pytest tests
        unit/
        integration/
        conftest.py            # shared fixtures

    worker/                    # Celery worker (imports core)
      pyproject.toml
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

      tests/                   # pytest tests
        unit/
        integration/
        conftest.py

  tests/                       # E2E tests
    e2e/
      conftest.py
      test_auth_flow.py
      test_identity_setup.py
      test_conversation_flow.py

  specs/
    Rediska_Tech_Spec_v0.2.md
    Rediska_Spec_Pack_v0.4.md

  scripts/
    local_backup/
      backup.sh
      restore_test.sh
```

### 1.2 Router choice
This spec assumes **Next.js App Router** (`apps/web/src/app`). If you prefer Pages Router, only file locations change; API contracts stay identical.

---

## 2) Runtime topology & trust boundaries

### 2.1 Traffic flow
1. Browser → `rediska-nginx` (HTTPS)
2. Nginx → `rediska-web` (HTTP, internal Docker network)
3. `rediska-web` BFF API routes → `rediska-core` (HTTP, internal Docker network)
4. `rediska-core` reads/writes MySQL, ES, Redis; enqueues Celery jobs
5. `rediska-worker` consumes Celery jobs; calls providers, llama.cpp endpoints; writes DB/ES/files

### 2.2 Security posture (local subnet)
- Nginx is the only LAN-exposed service.
- Everything else is Docker-network internal.
- Recommend host firewall allowlisting workstation IPs.

---

## 3) Compose file (production-ish baseline with healthchecks)

> **Container naming:** every container is prefixed `rediska-`
> **Storage:** volumes for DB/ES/Redis; host paths for attachments/backups.

```yaml
version: "3.9"

x-health-defaults: &health_defaults
  interval: 10s
  timeout: 5s
  retries: 10
  start_period: 20s

services:
  rediska-nginx:
    image: nginx:1.27-alpine
    container_name: rediska-nginx
    depends_on:
      rediska-web:
        condition: service_started
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx/rediska.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    networks: [rediska-net]
    restart: unless-stopped

  rediska-web:
    build: ./apps/web
    container_name: rediska-web
    environment:
      - CORE_API_URL=http://rediska-core:8000
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - BASE_URL=${BASE_URL}
    networks: [rediska-net]
    restart: unless-stopped
    healthcheck:
      <<: *health_defaults
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/"]

  rediska-core:
    build: ./services/core
    container_name: rediska-core
    environment:
      - MYSQL_URL=${MYSQL_URL}
      - REDIS_URL=${REDIS_URL}
      - ELASTIC_URL=${ELASTIC_URL}
      - ATTACHMENTS_PATH=${ATTACHMENTS_PATH}
      - BACKUPS_PATH=${BACKUPS_PATH}

      - INFERENCE_URL=${INFERENCE_URL}
      - INFERENCE_MODEL=${INFERENCE_MODEL}
      - INFERENCE_API_KEY=${INFERENCE_API_KEY}
      - EMBEDDINGS_URL=${EMBEDDINGS_URL}
      - EMBEDDINGS_MODEL=${EMBEDDINGS_MODEL}
      - EMBEDDINGS_API_KEY=${EMBEDDINGS_API_KEY}

      - PROVIDER_REDDIT_ENABLED=${PROVIDER_REDDIT_ENABLED}
      - PROVIDER_REDDIT_CLIENT_ID=${PROVIDER_REDDIT_CLIENT_ID}
      - PROVIDER_REDDIT_CLIENT_SECRET=${PROVIDER_REDDIT_CLIENT_SECRET}
      - PROVIDER_REDDIT_REDIRECT_URI=${PROVIDER_REDDIT_REDIRECT_URI}
      - PROVIDER_REDDIT_USER_AGENT=${PROVIDER_REDDIT_USER_AGENT}

      - PROVIDER_RATE_QPM_DEFAULT=${PROVIDER_RATE_QPM_DEFAULT}
      - PROVIDER_RATE_CONCURRENCY_DEFAULT=${PROVIDER_RATE_CONCURRENCY_DEFAULT}
      - PROVIDER_RATE_BURST_FACTOR=${PROVIDER_RATE_BURST_FACTOR}
    volumes:
      - ${ATTACHMENTS_PATH}:${ATTACHMENTS_PATH}
      - ${BACKUPS_PATH}:${BACKUPS_PATH}
    networks: [rediska-net]
    restart: unless-stopped
    depends_on:
      rediska-mysql:
        condition: service_healthy
      rediska-redis:
        condition: service_healthy
      rediska-elasticsearch:
        condition: service_healthy
    healthcheck:
      <<: *health_defaults
      test: ["CMD", "wget", "-qO-", "http://localhost:8000/healthz"]

  rediska-worker:
    build: ./services/worker
    container_name: rediska-worker
    depends_on:
      rediska-core:
        condition: service_healthy
      rediska-redis:
        condition: service_healthy
    environment:
      - MYSQL_URL=${MYSQL_URL}
      - REDIS_URL=${REDIS_URL}
      - ELASTIC_URL=${ELASTIC_URL}
      - ATTACHMENTS_PATH=${ATTACHMENTS_PATH}
      - BACKUPS_PATH=${BACKUPS_PATH}

      - INFERENCE_URL=${INFERENCE_URL}
      - INFERENCE_MODEL=${INFERENCE_MODEL}
      - INFERENCE_API_KEY=${INFERENCE_API_KEY}
      - EMBEDDINGS_URL=${EMBEDDINGS_URL}
      - EMBEDDINGS_MODEL=${EMBEDDINGS_MODEL}
      - EMBEDDINGS_API_KEY=${EMBEDDINGS_API_KEY}

      - CELERY_BROKER_URL=${CELERY_BROKER_URL}
      - CELERY_RESULT_BACKEND=${CELERY_RESULT_BACKEND}

      - PROVIDER_RATE_QPM_DEFAULT=${PROVIDER_RATE_QPM_DEFAULT}
      - PROVIDER_RATE_CONCURRENCY_DEFAULT=${PROVIDER_RATE_CONCURRENCY_DEFAULT}
      - PROVIDER_RATE_BURST_FACTOR=${PROVIDER_RATE_BURST_FACTOR}
    volumes:
      - ${ATTACHMENTS_PATH}:${ATTACHMENTS_PATH}
      - ${BACKUPS_PATH}:${BACKUPS_PATH}
    networks: [rediska-net]
    restart: unless-stopped

  rediska-beat:
    build: ./services/worker
    container_name: rediska-beat
    command: ["celery", "-A", "rediska_worker.celery_app", "beat", "-l", "INFO"]
    depends_on:
      rediska-redis:
        condition: service_healthy
      rediska-core:
        condition: service_healthy
    environment:
      - CELERY_BROKER_URL=${CELERY_BROKER_URL}
      - CELERY_RESULT_BACKEND=${CELERY_RESULT_BACKEND}
      - MYSQL_URL=${MYSQL_URL}
      - REDIS_URL=${REDIS_URL}
      - ELASTIC_URL=${ELASTIC_URL}
      - ATTACHMENTS_PATH=${ATTACHMENTS_PATH}
      - BACKUPS_PATH=${BACKUPS_PATH}
    volumes:
      - ${ATTACHMENTS_PATH}:${ATTACHMENTS_PATH}
      - ${BACKUPS_PATH}:${BACKUPS_PATH}
    networks: [rediska-net]
    restart: unless-stopped

  rediska-redis:
    image: redis:7-alpine
    container_name: rediska-redis
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - rediska_redis_data:/data
    networks: [rediska-net]
    restart: unless-stopped
    healthcheck:
      <<: *health_defaults
      test: ["CMD", "redis-cli", "ping"]

  rediska-mysql:
    image: mysql:8.4
    container_name: rediska-mysql
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=${MYSQL_DATABASE}
      - MYSQL_USER=${MYSQL_USER}
      - MYSQL_PASSWORD=${MYSQL_PASSWORD}
    volumes:
      - rediska_mysql_data:/var/lib/mysql
    networks: [rediska-net]
    restart: unless-stopped
    healthcheck:
      <<: *health_defaults
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-p${MYSQL_ROOT_PASSWORD}"]

  rediska-elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.14.3
    container_name: rediska-elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms1g -Xmx1g
    volumes:
      - rediska_es_data:/usr/share/elasticsearch/data
    networks: [rediska-net]
    restart: unless-stopped
    healthcheck:
      <<: *health_defaults
      test: ["CMD", "wget", "-qO-", "http://localhost:9200/"]

networks:
  rediska-net:

volumes:
  rediska_mysql_data:
  rediska_es_data:
  rediska_redis_data:
```

---

## 4) Nginx TLS config (LAN-safe defaults)

```nginx
server {
  listen 80;
  server_name rediska.local;
  return 301 https://$host$request_uri;
}

server {
  listen 443 ssl http2;
  server_name rediska.local;

  ssl_certificate     /etc/nginx/certs/tls.crt;
  ssl_certificate_key /etc/nginx/certs/tls.key;

  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_prefer_server_ciphers off;

  add_header Strict-Transport-Security "max-age=31536000" always;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy no-referrer always;

  client_max_body_size 12m;

  location / {
    proxy_pass http://rediska-web:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
```

---

## 5) MySQL DDL (canonical, v0.4)

> **Principle:** core tables are provider-agnostic. Provider-specific external IDs are stored as `external_*`.
> **No remote deletes:** provider deletion only updates status columns (`remote_status`, `remote_visibility`).
> **Identity-aware:** conversations and outgoing operations are bound to identities.

```sql
-- Providers
CREATE TABLE providers (
  provider_id VARCHAR(32) PRIMARY KEY,
  display_name VARCHAR(64) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Single-user auth (local-only)
CREATE TABLE local_users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL, -- Argon2
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at DATETIME NULL
);

-- Session store (server-side sessions, optional; otherwise use signed cookies)
CREATE TABLE sessions (
  id CHAR(36) PRIMARY KEY,              -- uuid
  user_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  data_json JSON NULL,
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES local_users(id)
);

-- User identities per provider (NEW in v0.4)
-- Represents the personas/accounts the user can use to interact through a provider
CREATE TABLE identities (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,

  -- Provider-specific identifier (e.g., Reddit username)
  external_username VARCHAR(128) NOT NULL,
  external_user_id VARCHAR(128) NULL,

  -- Display name for UI (user-defined, can differ from external_username)
  display_name VARCHAR(128) NOT NULL,

  -- Voice/persona configuration for LLM-generated content
  voice_config_json JSON NULL,  -- { "system_prompt": "...", "tone": "...", "style": "..." }

  -- Default identity for this provider (exactly one per provider must be true)
  is_default BOOLEAN NOT NULL DEFAULT FALSE,

  -- Status
  is_active BOOLEAN NOT NULL DEFAULT TRUE,

  -- Timestamps
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_identity (provider_id, external_username),
  KEY idx_identity_provider (provider_id),
  KEY idx_identity_default (provider_id, is_default),
  CONSTRAINT fk_identity_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

-- Counterpart identities on providers (people we interact with)
CREATE TABLE external_accounts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,
  external_user_id VARCHAR(128) NULL,
  external_username VARCHAR(128) NOT NULL,

  remote_status ENUM('active','deleted','suspended','unknown') NOT NULL DEFAULT 'unknown',
  remote_status_last_seen_at DATETIME NULL,

  analysis_state ENUM('not_analyzed','analyzed','needs_refresh') NOT NULL DEFAULT 'not_analyzed',
  contact_state ENUM('not_contacted','contacted') NOT NULL DEFAULT 'not_contacted',
  engagement_state ENUM('not_engaged','engaged') NOT NULL DEFAULT 'not_engaged',

  first_analyzed_at DATETIME NULL,
  first_contacted_at DATETIME NULL,
  first_inbound_after_contact_at DATETIME NULL,

  -- local delete/purge controls (local delete is permitted)
  deleted_at DATETIME NULL,
  purged_at DATETIME NULL,

  -- optional: last time we synced/fetched anything for the account
  last_fetched_at DATETIME NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_account (provider_id, external_username),
  KEY idx_remote_status (provider_id, remote_status),
  KEY idx_states (analysis_state, contact_state, engagement_state),
  CONSTRAINT fk_account_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

-- Conversations/threads (now identity-aware)
CREATE TABLE conversations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,
  external_conversation_id VARCHAR(128) NOT NULL,
  counterpart_account_id BIGINT NOT NULL,

  -- Identity used for this conversation (required)
  identity_id BIGINT NOT NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  last_activity_at DATETIME NULL,
  archived_at DATETIME NULL,

  -- local delete (hide) only
  deleted_at DATETIME NULL,

  UNIQUE KEY uq_conv (provider_id, external_conversation_id),
  KEY idx_conv_counterpart (counterpart_account_id),
  KEY idx_conv_identity (identity_id),
  KEY idx_conv_last_activity (last_activity_at),
  CONSTRAINT fk_conv_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
  CONSTRAINT fk_conv_account FOREIGN KEY (counterpart_account_id) REFERENCES external_accounts(id),
  CONSTRAINT fk_conv_identity FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- Messages within conversations (identity tracked for outgoing)
CREATE TABLE messages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,
  external_message_id VARCHAR(128) NULL, -- may be null if provider lacks stable IDs for some events
  conversation_id BIGINT NOT NULL,

  -- Identity that sent this message (NULL for incoming messages)
  identity_id BIGINT NULL,

  direction ENUM('in','out','system') NOT NULL,
  sent_at DATETIME NOT NULL,

  body_text MEDIUMTEXT NULL,

  remote_visibility ENUM('visible','deleted_by_author','removed','unknown') NOT NULL DEFAULT 'unknown',
  remote_deleted_at DATETIME NULL,

  -- local delete (hide)
  deleted_at DATETIME NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uq_msg_ext (provider_id, external_message_id),
  KEY idx_msg_conv_time (conversation_id, sent_at),
  KEY idx_msg_identity (identity_id),
  CONSTRAINT fk_msg_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
  CONSTRAINT fk_msg_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  CONSTRAINT fk_msg_identity FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- Attachments (local filesystem)
CREATE TABLE attachments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  message_id BIGINT NULL,

  storage_backend ENUM('fs') NOT NULL DEFAULT 'fs',
  storage_key VARCHAR(512) NOT NULL, -- relative key under ATTACHMENTS_PATH recommended

  sha256 CHAR(64) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,
  size_bytes BIGINT NOT NULL,

  width_px INT NULL,
  height_px INT NULL,

  remote_visibility ENUM('visible','deleted_by_author','removed','unknown') NOT NULL DEFAULT 'unknown',
  remote_deleted_at DATETIME NULL,

  deleted_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  KEY idx_attach_msg (message_id),
  KEY idx_attach_sha (sha256),
  CONSTRAINT fk_attach_msg FOREIGN KEY (message_id) REFERENCES messages(id)
);

-- Saved posts/leads from provider locations (e.g., subreddits)
CREATE TABLE lead_posts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,

  source_location VARCHAR(128) NOT NULL, -- "location" = subreddit / channel / etc.
  external_post_id VARCHAR(128) NOT NULL,
  post_url VARCHAR(512) NOT NULL,

  author_account_id BIGINT NULL,

  title VARCHAR(512) NULL,
  body_text MEDIUMTEXT NULL,
  post_created_at DATETIME NULL,

  status ENUM('new','saved','ignored','contact_queued','contacted') NOT NULL DEFAULT 'new',

  remote_visibility ENUM('visible','deleted_by_author','removed','unknown') NOT NULL DEFAULT 'unknown',
  remote_deleted_at DATETIME NULL,

  deleted_at DATETIME NULL, -- local hide
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_lead (provider_id, external_post_id),
  KEY idx_source (provider_id, source_location),
  KEY idx_author (author_account_id),
  KEY idx_status (status),
  CONSTRAINT fk_lead_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
  CONSTRAINT fk_lead_author FOREIGN KEY (author_account_id) REFERENCES external_accounts(id)
);

-- Profile snapshots (LLM outputs + extracted structured signals)
CREATE TABLE profile_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id BIGINT NOT NULL,
  fetched_at DATETIME NOT NULL,

  summary_text MEDIUMTEXT NULL,
  signals_json JSON NULL,
  risk_flags_json JSON NULL,

  model_info_json JSON NULL, -- which models/params used
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  KEY idx_snap_account_fetched (account_id, fetched_at),
  CONSTRAINT fk_snap_account FOREIGN KEY (account_id) REFERENCES external_accounts(id)
);

-- Public content items for accounts (posts/comments/images)
CREATE TABLE profile_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id BIGINT NOT NULL,

  item_type ENUM('post','comment','image') NOT NULL,
  external_item_id VARCHAR(128) NOT NULL,

  item_created_at DATETIME NULL,
  text_content MEDIUMTEXT NULL,
  attachment_id BIGINT NULL,

  remote_visibility ENUM('visible','deleted_by_author','removed','unknown') NOT NULL DEFAULT 'unknown',
  remote_deleted_at DATETIME NULL,

  deleted_at DATETIME NULL, -- local hide
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uq_item (account_id, item_type, external_item_id),
  KEY idx_item_type (account_id, item_type),
  CONSTRAINT fk_item_account FOREIGN KEY (account_id) REFERENCES external_accounts(id),
  CONSTRAINT fk_item_attachment FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);

-- OAuth/provider credentials (encrypted secrets) - now linked to identities
CREATE TABLE provider_credentials (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,
  identity_id BIGINT NULL,  -- NULL for app-level credentials, set for identity-specific
  credential_type VARCHAR(64) NOT NULL, -- e.g. oauth_refresh_token
  secret_encrypted MEDIUMTEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  rotated_at DATETIME NULL,
  CONSTRAINT fk_cred_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
  CONSTRAINT fk_cred_identity FOREIGN KEY (identity_id) REFERENCES identities(id),
  UNIQUE KEY uq_cred (provider_id, identity_id, credential_type)
);

-- Do-not-contact list (local-only safety)
CREATE TABLE do_not_contact (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_id VARCHAR(32) NOT NULL,
  external_username VARCHAR(128) NOT NULL,
  reason VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dnc (provider_id, external_username),
  CONSTRAINT fk_dnc_provider FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

-- Append-only audit log
CREATE TABLE audit_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  actor ENUM('user','system','agent') NOT NULL,
  action_type VARCHAR(128) NOT NULL,

  provider_id VARCHAR(32) NULL,
  identity_id BIGINT NULL,  -- Track which identity was used for the action
  entity_type VARCHAR(64) NULL,
  entity_id BIGINT NULL,

  request_json JSON NULL,
  response_json JSON NULL,

  result ENUM('ok','error') NOT NULL,
  error_detail MEDIUMTEXT NULL,

  KEY idx_audit_ts (ts),
  KEY idx_audit_action (action_type),
  KEY idx_audit_provider (provider_id),
  KEY idx_audit_identity (identity_id)
);

-- Job ledger to enforce idempotency/dedupe across Celery retries
CREATE TABLE jobs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  queue_name VARCHAR(64) NOT NULL,
  job_type VARCHAR(64) NOT NULL,
  payload_json JSON NOT NULL,

  status ENUM('queued','running','retrying','failed','done') NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 10,
  next_run_at DATETIME NULL,
  last_error MEDIUMTEXT NULL,

  dedupe_key VARCHAR(256) NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_dedupe (dedupe_key),
  KEY idx_jobs_status (status, next_run_at)
);
```

---

## 6) Elasticsearch index spec

### 6.1 Index creation JSON
```json
{
  "settings": {
    "analysis": {
      "analyzer": {
        "default": { "type": "standard" }
      }
    }
  },
  "mappings": {
    "properties": {
      "doc_type":        { "type": "keyword" },
      "provider_id":     { "type": "keyword" },
      "identity_id":     { "type": "keyword" },
      "account_id":      { "type": "keyword" },
      "conversation_id": { "type": "keyword" },
      "message_id":      { "type": "keyword" },
      "lead_post_id":    { "type": "keyword" },
      "source_location": { "type": "keyword" },

      "remote_status":     { "type": "keyword" },
      "remote_visibility": { "type": "keyword" },
      "local_deleted":     { "type": "boolean" },

      "created_at": { "type": "date" },
      "text":       { "type": "text" },

      "embedding": {
        "type": "dense_vector",
        "dims": 1024,
        "index": true,
        "similarity": "cosine"
      }
    }
  }
}
```

### 6.2 Example BM25 query (with filters)
```json
{
  "size": 25,
  "query": {
    "bool": {
      "must": [{ "match": { "text": "looking for hiking buddy" } }],
      "filter": [
        { "term": { "provider_id": "reddit" } },
        { "term": { "identity_id": "123" } },
        { "term": { "local_deleted": false } }
      ],
      "must_not": [
        { "terms": { "remote_status": ["deleted","suspended"] } }
      ]
    }
  }
}
```

---

## 7) Celery: canonical task list

### 7.1 Task names (stable API)
- `ingest.backfill_conversations`
- `ingest.backfill_messages`
- `ingest.sync_delta`
- `ingest.browse_location`
- `ingest.fetch_post`
- `ingest.fetch_profile`
- `ingest.fetch_profile_items`

- `index.upsert_content`

- `embed.generate`

- `agent.profile_summary`
- `agent.lead_scoring`
- `agent.draft_intro`

- `message.send_manual`

- `maintenance.mysql_dump_local`
- `maintenance.attachments_snapshot_local`
- `maintenance.restore_test_local`

---

## 8) Backup scripts (local-only stubs)

### 8.1 `scripts/local_backup/backup.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

DATE=$(date +%F)
ROOT="${BACKUPS_PATH:-/var/lib/rediska/backups}"
MYSQL_DUMP_DIR="$ROOT/mysql"
ATTACH_DIR="$ROOT/attachments/$DATE"

mkdir -p "$MYSQL_DUMP_DIR" "$ATTACH_DIR"

# DB dump
docker exec rediska-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'   | gzip > "$MYSQL_DUMP_DIR/$DATE.sql.gz"

sha256sum "$MYSQL_DUMP_DIR/$DATE.sql.gz" > "$MYSQL_DUMP_DIR/$DATE.sql.gz.sha256"

# Attachments snapshot (simple; replace with rsync/incremental later)
cp -a "${ATTACHMENTS_PATH:-/var/lib/rediska/attachments}/." "$ATTACH_DIR/"
```

### 8.2 `scripts/local_backup/restore_test.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="${BACKUPS_PATH:-/var/lib/rediska/backups}"
LATEST=$(ls -1 "$ROOT/mysql"/*.sql.gz | tail -n 1)

echo "Using dump: $LATEST"

# Spin up ephemeral restore container (customize as needed)
docker run --rm --name rediska-mysql-restoretest -e MYSQL_ROOT_PASSWORD=test -e MYSQL_DATABASE=rediska -d mysql:8.4
sleep 20

gunzip -c "$LATEST" | docker exec -i rediska-mysql-restoretest mysql -uroot -ptest rediska

# Simple sanity checks
docker exec rediska-mysql-restoretest mysql -uroot -ptest rediska -e "SHOW TABLES;"
docker exec rediska-mysql-restoretest mysql -uroot -ptest rediska -e "SELECT COUNT(*) FROM external_accounts;"

docker stop rediska-mysql-restoretest
```

---

## 9) Identity API Endpoints

### 9.1 Identity Management
- `GET /identities` - List all identities (grouped by provider)
- `POST /identities` - Create new identity (triggers OAuth flow)
- `GET /identities/{id}` - Get identity details
- `PATCH /identities/{id}` - Update identity (display_name, voice_config, is_default)
- `DELETE /identities/{id}` - Deactivate identity (soft delete)
- `POST /identities/{id}/set-default` - Set as default for provider

### 9.2 Identity Setup Flow
1. User creates identity via `POST /identities` with provider_id
2. System redirects to OAuth flow
3. On OAuth callback, identity is activated
4. User configures voice settings via `PATCH /identities/{id}`
5. If first identity for provider, automatically set as default

### 9.3 Onboarding Gate
- System requires at least one active identity before allowing:
  - Viewing inbox
  - Starting conversations
  - Sending messages
- Endpoint `GET /setup/status` returns onboarding completion state

---

## 10) "Next step" checklist (ready for task breakdown)
- Confirm embeddings dimension (from chosen embeddings model) to finalize ES mapping
- Decide session storage approach:
  - server-side sessions in DB/Redis **or**
  - signed JWT cookies (still HttpOnly/Secure)
- Decide whether `rediska-web` uses NextAuth or custom login page (both workable)
- Identify exact provider endpoints as implementation details inside `providers/reddit/`
- Set up test infrastructure (pytest, jest) before implementing features

---

---

## 11) Post Content Persistence & Analysis Resilience (v0.5)

### 11.0 Problem Statement

Browse and Scout searches surface posts via Reddit's search API, which returns posts matching search criteria regardless of the author's profile visibility settings. Many users hide NSFW posts from their public profile. When "Analyze" is triggered, the system fetches the author's profile items via their user page API (`/user/{username}/submitted`), which respects visibility settings and may return zero results. This causes the `InterestsSummaryService` to return "No posts available for analysis" and the `CharacterSummaryService` to produce empty results, despite having the post content readily available from the search that surfaced the user in the first place.

**Root cause chain:**
1. Browse/Scout returns posts from Reddit search → posts displayed in UI with full body_text
2. User clicks "Save Lead" → `lead_posts` row created with body_text, `ExternalAccount` created
3. Auto-analysis triggers → `AnalysisService.analyze_lead()` runs
4. `_fetch_profile_items()` calls Reddit's user page API → returns 0 items (NSFW hidden)
5. `_store_profile_items()` stores 0 items
6. `InterestsSummaryService.summarize()` sees 0 posts → returns `InterestsSummaryResult.empty()`
7. `MultiAgentAnalysisService` runs with empty context → poor/useless results

**Fix:** The post content we already have from the search must be saved as a `profile_item` linked to the author's `ExternalAccount` **before** analysis runs. Analysis must merge locally-stored items with provider-fetched items and proceed even when the provider returns nothing.

---

### 11.1 Lead Post → Profile Item Linking

When saving a lead (via "Save Lead" button or Scout Watch auto-save), the post content **must also** be stored as a `profile_item` record linked to the author's `ExternalAccount`.

#### Rules
1. `LeadsService.save_lead()` must call a new method `_save_post_as_profile_item()` after creating/upserting the `lead_posts` row.
2. The profile_item is upserted by `(account_id, item_type='post', external_item_id)`.
3. Fields mapped from lead post data:
   - `account_id` ← `lead.author_account_id`
   - `item_type` ← `'post'`
   - `external_item_id` ← `lead.external_post_id`
   - `text_content` ← `lead.body_text` (full text, including title prepended)
   - `item_created_at` ← `lead.post_created_at`
   - `subreddit` ← `lead.source_location`
   - `link_title` ← `lead.title`
   - `remote_visibility` ← `'visible'` (we just saw it in search results)
4. This ensures at minimum one profile_item exists for every saved lead.

#### Scout Watch Integration
`ScoutWatchService.record_post()` must also create a profile_item when it creates a `ScoutWatchPost` with an associated author. The `post_body` field on `ScoutWatchPost` is already populated; this must be propagated to `profile_items`.

---

### 11.2 Auto-Accumulate Posts for Known Users

When Browse or Scout encounters a post from a user who already has an `ExternalAccount` record, the new post should be automatically saved as a `profile_item` — even without the user explicitly clicking "Save Lead".

#### Approach: Batch Upsert Endpoint

```
POST /api/core/profile-items/ingest-browse-posts
Content-Type: application/json

{
  "posts": [
    {
      "provider_id": "reddit",
      "external_post_id": "abc123",
      "author_username": "some_user",
      "title": "Post title",
      "body_text": "Full text",
      "source_location": "subreddit_name",
      "post_created_at": "2026-02-13T10:00:00Z"
    },
    ...
  ]
}
```

**Response:**
```json
{
  "ingested_count": 3,
  "new_items_count": 2,
  "known_authors": ["user1", "user2"]
}
```

#### Backend Logic
1. For each post in the batch, check if `author_username` exists in `external_accounts` for the given `provider_id`.
2. If the author IS known: upsert a `profile_item` record for this post.
3. If the author is NOT known: skip (no ExternalAccount to link to).
4. Return which authors were known (for UI to show indicators).

#### Frontend Integration
- After `fetchPosts()` returns browse results, fire a background `POST /profile-items/ingest-browse-posts` with all posts.
- Response tells the UI which authors are already known (show badge/indicator on PostCard).
- Scout Watch runs already create posts via `record_post()` — enhance that path to also create profile_items (§11.1).

---

### 11.3 Analysis Resilience

The analysis pipeline must work even when the provider's profile item fetch returns zero results.

#### Changes to `AnalysisService.analyze_lead()`

1. **Before fetching from provider**, query locally-stored `profile_items` for the account.
2. **After fetching from provider**, merge provider items with local items (union by `external_item_id`; local items fill gaps).
3. **Ensure the lead post itself** is present as a profile_item. If not, create it inline before proceeding.
4. **Never fail** due to zero profile items. The analysis pipeline should proceed with whatever data is available (even just one post).

#### Updated Step Sequence
```
Step 1: Get lead + author account
Step 2: Ensure lead post is saved as profile_item (§11.1)
Step 3: Fetch profile from provider (metadata: karma, age, bio)
Step 4: Create/update ProfileSnapshot
Step 5: Fetch profile items from provider (may return 0)
Step 6: Query existing local profile_items for this account
Step 7: Merge: provider items ∪ local items (dedupe by external_item_id)
Step 8: Store merged items
Step 9: Index + embed
Step 10: Update analysis_state
```

#### Impact on Multi-Agent Analysis
- `InterestsSummaryService` will now always have at least the lead post → never returns empty.
- `CharacterSummaryService` may still return empty if no comments are found — this is acceptable.
- `MultiAgentAnalysisService` context will include at least one post's text.

---

### 11.4 Contact Author from Any Screen

Users must be able to initiate contact with a post's author from any screen where the username appears.

#### UI Touchpoints

| Screen | Component | Action |
|--------|-----------|--------|
| Browse | `PostCard` | "Message" button next to "Save Lead" |
| Leads list | `LeadRow` | "Message" icon button |
| Lead detail | `LeadDetail` | "Contact Author" button |
| UserProfilePanel | Panel header | "Message" action button |
| Scout Watch history | `WatchPostRow` | "Message" icon button |
| Directories | `AccountRow` | "Message" icon button |
| Profile page | Profile header | "Contact" button |

#### New Conversation Flow

Clicking "Message" / "Contact" triggers:

1. **Check existing conversation**: Query `GET /api/core/conversations?counterpart_username={username}` to find if an open conversation already exists with this author.
2. **If conversation exists**: Navigate to `/inbox/{conversationId}` — open existing thread.
3. **If no conversation**: Navigate to `/inbox/new?to={username}&provider=reddit` — open compose view for new conversation.

#### New Compose Page: `/inbox/new`

A new page for composing the first message to a new contact:
- Header shows recipient username, profile panel (collapsed by default)
- Message compose box (same as existing conversation compose)
- Posts panel on the side (§11.5)
- On send: creates conversation + sends first message via `POST /api/core/conversations` (new endpoint or enhanced existing)

#### Backend: Create Conversation + First Message

```
POST /api/core/conversations
{
  "provider_id": "reddit",
  "counterpart_username": "target_user",
  "identity_id": 123,        // optional, uses default if omitted
  "initial_message": "Hello..."
}
```

Returns:
```json
{
  "conversation_id": 456,
  "message_id": 789,
  "status": "queued"
}
```

Backend steps:
1. Get or create `ExternalAccount` for counterpart
2. Check `do_not_contact` list — block if listed
3. Create `Conversation` row (identity_id from request or default)
4. Enqueue `message.send_manual` task with message text
5. Create local `Message` record with `direction='out'`
6. Write audit log

---

### 11.5 Posts Panel in Message Compose

When composing a message (both new conversation and existing thread), an expandable side panel shows the counterpart's saved posts.

#### UI Specification

- **Location**: Right side panel in conversation view, below existing image gallery
- **Toggle**: Collapsible section header: "Posts ({count})" with expand/collapse chevron
- **Default state**: Collapsed (same as image gallery behavior)
- **Content**: Scrollable list of posts from `profile_items` where `item_type='post'` for the counterpart's `ExternalAccount`

#### Post Item Display
```
┌─────────────────────────────────────────┐
│ r/subreddit_name · 3d ago               │
│ Post Title Here                         │
│ First 200 chars of body text...         │
│ [View full ↗]                           │
└─────────────────────────────────────────┘
```

#### Data Source
```
GET /api/core/accounts/{account_id}/profile-items?item_type=post&limit=50
```

This endpoint already exists via the profile items query in `UserProfilePanel`. Reuse the same API.

#### Benefits
- User can reference specific posts when composing personalized messages
- Posts from browse, scout, and provider fetches are all visible
- As more posts accumulate (§11.2), the panel gets richer over time

---

### 11.6 Auto-Analyze on Save Lead (Enhancement)

The current auto-analyze on save (fire-and-forget from browse page) has a race condition: analysis may start before the lead post is saved as a profile_item.

#### Enhanced Flow

1. `POST /api/core/leads/save` now also creates profile_item (§11.1) — synchronous, within same DB transaction
2. Response includes `profile_item_id` in addition to existing fields
3. Frontend fires `POST /api/core/leads/{id}/analyze` as before (fire-and-forget)
4. Backend `analyze_lead()` now finds at least 1 profile_item for the account (the lead post itself)
5. Analysis never returns "No posts available" for a saved lead

#### Schema Change: `SaveLeadResponse`
Add field:
```python
profile_item_id: Optional[int] = Field(default=None, description="Profile item created for this post")
```

---

## 12) DDL Additions (v0.5)

No new tables required. All changes use existing tables:

- `profile_items` — already supports posts, comments, images with `subreddit`, `link_title` metadata columns (added in migration 013)
- `lead_posts` — no schema changes
- `external_accounts` — no schema changes
- `conversations` — may need a new creation path but schema unchanged

---

**End of Spec Pack v0.5**
