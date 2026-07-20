## Why

`deploy-to-dedicated-server` documents the manual procedure for bringing Rediska up on an internal box. As soon as that is in place, every code change requires manually SSHing in, pulling, rebuilding, and restarting — error-prone and slow. A GitHub Action that builds images on push, pushes to GitHub Container Registry, and triggers the on-prem server to pull and restart turns each merge into a single automated deploy with clean version-tagged rollbacks.

## What Changes

- Add a GitHub Actions workflow that, on push to `main` (and on manual `workflow_dispatch`):
  - Builds `rediska-web`, `rediska-core`, and `rediska-worker` images using docker buildx.
  - Tags each image with the commit SHA and `latest`.
  - Pushes them to GHCR under `ghcr.io/elabz/rediska-{web,core,worker}`.
- Add a deploy step that reaches the VPN-only on-prem server through Tailscale (via `tailscale/github-action`), then SSHes into the server and runs a deploy script.
- Add `scripts/deploy/update.sh` on the server side: `docker compose pull` + `up -d` + `alembic upgrade head` + run `smoke_test.sh` (from `deploy-to-dedicated-server`).
- Add per-component Dockerfiles' build args so the build is hermetic and reproducible from a tag.
- Document the required GitHub secrets and the one-time on-prem setup (Tailscale machine on the runner side, SSH key, GHCR pull credentials on the server).

## Capabilities

### New Capabilities
- `deployment-automation`: Requirements for the CI/CD pipeline that builds, publishes, and applies new versions to the on-prem server.

### Modified Capabilities
<!-- None. -->

## Impact

- **New files**: `.github/workflows/deploy.yml`, `scripts/deploy/update.sh` (server-side), possibly small additions to `services/core/Dockerfile` and `services/worker/Dockerfile` for build-arg version stamping.
- **New external dependencies**: GitHub Actions runner (hosted), GHCR (free for public/private repos at our usage level), Tailscale (already in scope as the VPN).
- **Secrets**: requires three GitHub secrets — `TAILSCALE_OAUTH_CLIENT_ID`, `TAILSCALE_OAUTH_SECRET`, and `DEPLOY_SSH_KEY`. Server needs a GHCR pull token (stored in `.env` or `~/.docker/config.json`).
- **Coupling**: depends on `deploy-to-dedicated-server` shipping first (the manual procedure must work before automation wraps it).
- **Risk**: an auto-deploy on every merge to `main` increases blast radius. Smoke test in the deploy script provides a guard; rollback is `docker compose down && docker compose up -d --no-deps <service>` with the previous tag.
