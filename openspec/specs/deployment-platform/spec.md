# deployment-platform Specification

## Purpose
Rediska runs as a Docker Compose stack of `rediska-*` containers on a private network, reachable only through an external reverse proxy on the LAN/VPN — never the public internet. Images are built and published to GHCR by CI and deployed to the on-prem server over Tailscale SSH. LLM inference and embeddings are external llama.cpp endpoints configured by environment.

## Requirements

### Requirement: Compose stack with no published host ports

The stack SHALL consist of `rediska-web` (Next.js), `rediska-core` (FastAPI), `rediska-worker` and `rediska-beat` (Celery), `rediska-redis` (redis:7-alpine), `rediska-mysql` (mysql:8.4), and `rediska-elasticsearch` (elasticsearch 8.14.3), all attached to the `rediska-net` network with `restart: unless-stopped` and healthchecks. No service SHALL publish a port to the host; the stack is reached only via a proxy container that joins `rediska-net`.

#### Scenario: Clean bring-up

- **WHEN** an operator runs `docker compose up -d` on a configured host
- **THEN** all seven services start, dependency ordering waits on MySQL/Redis/ES health, and `docker ps` shows no host port bindings for any `rediska-*` container

### Requirement: TLS terminates at the external dev-proxy

The in-repo `rediska-nginx` service is retired. The `rediska.local` vhost and TLS termination SHALL be provided by the external dev-proxy stack (separate repo, e.g. `~/Web/dev-proxy`), which attaches to `rediska-net` and proxies to `rediska-web:3000`. The `nginx/` directory in this repo is legacy reference only and SHALL NOT be wired into the compose stack.

#### Scenario: Browser reaches the app

- **WHEN** a browser on the LAN/VPN opens `https://rediska.local`
- **THEN** the dev-proxy terminates TLS and forwards to `rediska-web` over the internal Docker network

### Requirement: The system is never exposed to the public internet

Rediska SHALL be reachable only from the local network or a private VPN (Tailscale). No configuration, deployment step, or feature SHALL expose any Rediska service to the public internet.

#### Scenario: Deployment review

- **WHEN** any deployment or configuration change is made
- **THEN** all Rediska services remain bound to internal networks only, with access limited to LAN/VPN clients

### Requirement: Images are pinned by commit SHA

CI SHALL publish `ghcr.io/elabz/rediska-web`, `-core`, and `-worker` images tagged with the immutable commit SHA (plus `latest` on push to main). The compose file SHALL select the running version via the `TAG` env var, enabling pin and rollback by setting `TAG=<sha>`.

#### Scenario: Rollback

- **WHEN** the operator sets `TAG` to a previous known-good SHA and runs `docker compose up -d`
- **THEN** the stack runs that exact image set without rebuilding

### Requirement: Continuous deployment on push to main

A push to `main` (excluding `openspec/**`, `docs/**`, and `**/*.md`) SHALL trigger the deploy workflow: build and push the three images, then connect to the deploy host over Tailscale SSH and run `scripts/deploy/update.sh <sha>`, which checks out the SHA, sets `TAG`, pulls images, runs `docker compose up -d`, applies `alembic upgrade head`, and runs the smoke test. `workflow_dispatch` SHALL allow manual re-deploys of a chosen tag with an optional smoke-test skip.

#### Scenario: Docs-only push does not deploy

- **WHEN** a push to `main` touches only files under `openspec/`, `docs/`, or `*.md`
- **THEN** no build or deploy runs

#### Scenario: Deploy applies migrations

- **WHEN** `update.sh` completes a deploy
- **THEN** alembic has been upgraded to head inside `rediska-core` (currently `017_add_conversation_lists`)

### Requirement: Development override enables hot reload

A `docker-compose.override.yml` SHALL mount `rediska_core` and `rediska_worker` source read-only into the core and worker containers and switch core to `uvicorn --reload`, so local code edits take effect without image rebuilds.

#### Scenario: Editing core code locally

- **WHEN** a developer edits a file under `services/core/rediska_core` with the dev override active
- **THEN** the running core service reloads and serves the change

### Requirement: LLM runtimes are external and configurable

Inference and embeddings SHALL be external llama.cpp-compatible HTTP endpoints configured via `INFERENCE_URL`/`INFERENCE_MODEL`/`INFERENCE_API_KEY` and `EMBEDDINGS_URL`/`EMBEDDINGS_MODEL`/`EMBEDDINGS_API_KEY`. The chat template SHALL be selectable via `INFERENCE_CHAT_TEMPLATE` (`llama3` default; `qwen_thinking`, `mistral`, `chatml` supported).

#### Scenario: Switching model family

- **WHEN** the operator points `INFERENCE_URL` at a Qwen-served endpoint and sets `INFERENCE_CHAT_TEMPLATE=qwen_thinking`
- **THEN** agent prompts are formatted with the Qwen thinking template without code changes
