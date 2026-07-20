## 1. Pre-requisites

- [ ] 1.1 Confirm `deploy-to-dedicated-server` has shipped and the on-prem server is up.
- [ ] 1.2 In Tailscale admin: create an OAuth client with permission to mint ephemeral keys for a new tag (e.g., `tag:github-actions`); record the client ID + secret.
- [ ] 1.3 On Tailscale: add a tailnet ACL rule allowing nodes with `tag:github-actions` to SSH to the prod server only.
- [ ] 1.4 On the prod server: create a GHCR pull token (a GitHub Personal Access Token with `read:packages` scope) and run `docker login ghcr.io -u <username> --password-stdin` so the daemon caches the credentials under `~/.docker/config.json`.
- [ ] 1.5 In the GitHub repo settings: add secrets `TAILSCALE_OAUTH_CLIENT_ID`, `TAILSCALE_OAUTH_SECRET`, `DEPLOY_SSH_KEY` (private key matching an authorized_keys entry on the server), and a variable `DEPLOY_HOST` (the server's tailnet hostname).

## 2. Compose changes

- [x] 2.1 In `docker-compose.yml`, add `image: ghcr.io/elabz/rediska-web:${TAG:-latest}` to the `rediska-web` service (keep the existing `build:` block alongside it). Repeat for `rediska-core` and `rediska-worker` and `rediska-beat`. Beat reuses the worker image.
- [x] 2.2 Document the `TAG` env var in `.env.example` with a default of `latest`.
- [ ] 2.3 Manually test on the dev box: `TAG=latest docker compose pull` (after pushing test images from a branch) succeeds and `docker compose up -d` rolls containers correctly.

## 3. Server-side deploy script

- [x] 3.1 Write `scripts/deploy/update.sh <sha>`. Steps: refuse if working tree dirty; `git fetch origin`; `git checkout <sha>`; update `TAG=<sha>` in `.env`; `docker compose pull` (only the rediska-* services, leave nginx/redis/mysql/es alone); `docker compose up -d`; `docker compose exec -T rediska-core alembic upgrade head`; `./scripts/deploy/smoke_test.sh`. Exit non-zero on any step failure.
- [x] 3.2 Make the script idempotent: re-running with the same SHA is a no-op (or just re-runs the smoke test).
- [x] 3.3 Add a `--force-checkout` flag for emergency overrides when working tree is dirty (with a confirmation prompt unless `--yes` is also supplied).

## 4. GitHub Actions workflow

- [x] 4.1 Create `.github/workflows/deploy.yml`. Triggers: `push` to `main` with `paths-ignore: ['openspec/**', 'docs/**', '**/*.md']`, and `workflow_dispatch` with inputs `tag` (default `latest`) and `skip_smoke_test` (default `false`).
- [x] 4.2 Job `build-and-push`: matrix over the three services (`web`, `core`, `worker`). Uses `docker/login-action` for GHCR, `docker/setup-buildx-action` for buildx, `docker/build-push-action` to build + push with tags `<sha>` and `latest`. Cache via `type=gha`.
- [x] 4.3 Job `deploy`, needs `build-and-push`. Steps: checkout (sparse), `tailscale/github-action@v2` with the OAuth secrets and `tag:github-actions`, install SSH key via `webfactory/ssh-agent` or equivalent, then `ssh ${{ vars.DEPLOY_HOST }} "cd /opt/rediska && ./scripts/deploy/update.sh ${{ github.sha }}"`. Honor `skip_smoke_test` by passing a flag to the script.
- [x] 4.4 Ensure the workflow fails loudly if any step errors and surfaces the remote script's stdout/stderr in the job log.

## 5. First deploy

- [ ] 5.1 Merge to a feature branch first; trigger `workflow_dispatch` to validate the build path without auto-deploying.
- [ ] 5.2 Once a build is verified, merge to `main` and watch the first automated deploy.
- [ ] 5.3 Verify on the prod server: `docker compose images` shows the SHA-tagged digests matching the workflow output.

## 6. Documentation updates

- [x] 6.1 Add a "Continuous Deployment" section to `docs/deploy.md` (created in `deploy-to-dedicated-server`) describing the workflow, the secrets, manual re-deploy, and rollback (`workflow_dispatch` with an older SHA).
- [x] 6.2 Update `CLAUDE.md` to mention `.github/workflows/deploy.yml` in the architecture / development sections.

## 7. Optional follow-ups (not required for this change)

- [x] 7.1 Note in design.md the future enhancement: scheduled workflow to prune old SHA tags from GHCR after 30 days.
- [x] 7.2 Note the future enhancement: separate `ci.yml` for running `pytest` on PRs before merge.
