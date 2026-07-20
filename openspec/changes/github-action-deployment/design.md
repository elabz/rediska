## Context

Constraints established by the user's deploy choices:
- Target server is on-prem and VPN-only — not reachable from GitHub-hosted runners over the public internet.
- Image distribution via GHCR — the runner builds and pushes; the server pulls.
- Repo: `git@github.com:elabz/rediska.git`.
- The manual deploy procedure (defined in `deploy-to-dedicated-server`) is the source of truth for what a deploy *means*; this change automates that procedure.

The fundamental connectivity problem: GitHub-hosted runners cannot SSH directly into a VPN-only host. Three viable patterns:

1. **Tailscale ephemeral node on the runner** — `tailscale/github-action` joins the runner to the tailnet for the duration of the job; standard SSH works.
2. **Self-hosted runner on the prod server** — runner lives on the box that will be deployed to; no network glue needed.
3. **Server polls GHCR** — cron-based, no inbound needed, but adds latency and complicates "did my push deploy?" feedback.

The user explicitly did not pick the self-hosted runner option, and the GHCR-image-pull description in the question explicitly mentioned SSH or webhook. Pattern (1) is the cleanest fit.

## Goals / Non-Goals

**Goals:**
- Single workflow file. On push to `main`: build → push → deploy → smoke test, end-to-end.
- Tag every deployed image with the commit SHA. `latest` is a moving tag; SHA tags are immutable references for rollback.
- Run database migrations as part of the deploy step (after pull, before serving traffic if practical).
- Run the smoke test on the server and fail the workflow if it fails (operator gets a GitHub notification, can investigate).
- Support manual re-deploys via `workflow_dispatch` with a specific tag input.

**Non-Goals:**
- Multi-environment promotion (no staging in v1).
- Blue-green / zero-downtime deploys. Brief unavailability (~30s) during compose restart is acceptable for a single-user system.
- Auto-rollback on smoke-test failure. Operator handles rollbacks; the action just surfaces the failure.
- Building images for non-amd64 architectures (the on-prem server is x86_64).

## Decisions

### Connectivity: Tailscale GitHub Action

- **Chosen**: `tailscale/github-action@v2` with an OAuth client granting the runner an ephemeral key. The runner joins the tailnet as a tagged ephemeral node, gains DNS for `rediska-prod`, runs SSH, then drops off.
- **Rationale**: First-class GitHub Action, no inbound ports on the server, ephemeral nodes keep the tailnet clean. OAuth credentials rotate independently of long-lived auth keys.
- **Alternative**: Self-hosted runner on the server. Rejected (user pick) — adds runner-lifecycle ops to the prod box.
- **Alternative**: Server polls GHCR for new `latest` tags every N minutes. Rejected — slow feedback, no clean rollback signal from the GitHub side, complicates "did my merge deploy?" answer.

### Image strategy

- **Three images**: `rediska-web`, `rediska-core`, `rediska-worker`. Beat reuses the worker image. Nginx, Redis, MySQL, Elasticsearch use upstream public images.
- **Tagging**: each push tags with `<sha>` (immutable) and `latest` (moving). Releases (via `git tag v*`) additionally tag `v<version>`.
- **Build context**: docker buildx with layer caching via `type=gha` (GitHub Actions cache).
- **Registry**: `ghcr.io/elabz/rediska-<service>`. Private to start. Server auths via a token stored in `~/.docker/config.json` (NOT in `.env` — avoids leaking through compose env vars to other services).

### Compose file: parametrize image vs. build context

- **Today**: `docker-compose.yml` builds locally (`build: ./services/core`).
- **Needed**: compose pulls the image when running on prod, builds locally when running on dev.
- **Chosen**: introduce `image: ghcr.io/elabz/rediska-core:${TAG:-latest}` alongside the existing `build:` block. On the server, set `TAG=<sha>` in `.env` before `docker compose pull`; locally, ignore `image:` and `docker compose build` continues to work. Compose semantics: when both are present, `docker compose up` uses `image` if it can pull, otherwise falls back to `build`.
- **Alternative**: a separate `docker-compose.prod.yml` overlay. Cleaner separation, more files to keep in sync. Acceptable, but the single-file approach is lighter for v1.

### Deploy step on the server

- **Script**: `scripts/deploy/update.sh` (server-side, checked into the repo at `/opt/rediska` on prod).
- **Steps**:
  1. `cd /opt/rediska && git fetch && git checkout <sha>` — gets the matching compose file and migrations.
  2. Update `.env` `TAG=<sha>`.
  3. `docker compose pull rediska-web rediska-core rediska-worker rediska-beat`.
  4. `docker compose up -d` — recreates only changed containers.
  5. `docker compose exec rediska-core alembic upgrade head`.
  6. `./scripts/deploy/smoke_test.sh` (from `deploy-to-dedicated-server`).

Idempotency: re-running with the same SHA is a no-op. Re-running with a new SHA is a normal deploy.

### Migrations: order with rolling updates

- For a single-server, single-replica deploy, the simplest order is: pull → up -d (rolls containers) → migrate. This means migrations run after the new core is already serving requests; backwards-incompatible migrations require an "expand → contract" pattern (release N adds new column nullable, release N+1 uses it, release N+2 drops the old column).
- **Decision**: document expand/contract as a release convention; do not gate the workflow on schema-compat checking. Operator discipline.
- **Alternative considered**: migrate before up. Risk: old running core sees a new schema. With Alembic's `op.add_column` + nullable defaults this is fine, but `op.drop_column` would break the running version. Same conclusion: expand/contract.

### Manual workflow_dispatch

- Inputs: `tag` (default `latest`) and optional `skip_smoke_test` (default false).
- Use case: deploying an older SHA for rollback, or redeploying without rebuilding.

### Secrets and one-time setup

Documented in tasks.md and in the deploy doc. Three repo secrets needed; one server-side config (GHCR token).

## Risks / Trade-offs

- **Tailscale OAuth credential leak** → Mitigation: scoped to ephemeral keys with a tag that maps to a tailnet ACL allowing only SSH-to-rediska-prod. Even on leak, the blast radius is "can SSH to one box during their token lifetime."
- **Server-side git working tree diverges** → Operator might have local edits in `/opt/rediska`. Mitigation: deploy script does `git fetch` + `git checkout <sha>` (detached HEAD), refusing if working tree is dirty. Force-checkout is opt-in via a workflow input.
- **Smoke test false-negative kills a good deploy** → The workflow marks the deploy "failed" but the new version is already running. Document this: failure means "investigate", not "auto-rollback."
- **Auto-deploy on every push to main** → Some commits don't deserve a deploy (docs-only, openspec-only). Mitigation: use a path filter on `paths-ignore: ['openspec/**', 'docs/**', '**/*.md']` in the workflow. Operator can still force a deploy via dispatch.
- **GHCR free tier limits** → Private packages have storage limits on the free tier. Mitigation: prune old SHA tags after N days via a separate scheduled workflow (future enhancement, noted).

## Migration Plan

This change ships after `deploy-to-dedicated-server` is merged AND the on-prem server is up. Order:

1. Merge `deploy-to-dedicated-server`, bring server up manually.
2. Configure Tailscale OAuth client + tag.
3. Provision GHCR access token on the server.
4. Add GitHub secrets.
5. Merge this change. The next push to `main` triggers the first automated deploy.
6. Verify in the GH Actions tab; spot-check that the SHA tag matches running containers (`docker compose images`).

Rollback (of this change itself): disable the workflow via the GitHub UI, return to manual deploys per the deploy doc.

## Open Questions

- Should the workflow also run a build of the python services' tests (`pytest`) before deploying? Default: no — out of scope. A separate CI workflow for tests is a clean follow-up.
- Should `latest` always equal `main`'s head, or should we move it explicitly on tagged releases? Default: `latest` = `main` HEAD, release tags are explicit.
- Where do we store the smoke-test failure context for postmortems? Default: GitHub Actions logs are sufficient for v1.

## Future Enhancements (out of scope here)

- **Prune old SHA tags from GHCR.** A scheduled workflow (e.g., `.github/workflows/ghcr-prune.yml`, weekly) that deletes image tags older than 30 days, keeping the most recent N regardless of age. Useful once the SHA-tag set grows large enough to matter against GHCR's free-tier storage cap. Implementation hint: `actions/delete-package-versions` or the GHCR REST API.
- **Separate `ci.yml` for PR validation.** A workflow that runs `pytest` (in `services/core` and `services/worker`) and `npm run lint` + `npm run build` (in `apps/web`) on every pull request before merge. Catches regressions before `deploy.yml` ever runs on `main`. Keep it independent of `deploy.yml` so a flaky test never blocks a hotfix deploy via `workflow_dispatch`.
