#!/usr/bin/env bash
# Rediska deploy update — server-side workhorse invoked by .github/workflows/deploy.yml.
#
# Usage: ./scripts/deploy/update.sh <sha> [--force-checkout] [--yes] [--skip-smoke-test]
#
# Steps (in order):
#   1. Refuse if working tree is dirty (unless --force-checkout is supplied).
#   2. git fetch origin && git checkout <sha> (detached HEAD).
#   3. Update TAG=<sha> in .env.
#   4. docker compose pull rediska-{web,core,worker,beat} (leaves nginx/redis/mysql/es alone).
#   5. docker compose up -d (recreates only changed containers).
#   6. docker compose exec -T rediska-core alembic upgrade head.
#   7. ./scripts/deploy/smoke_test.sh (skippable via --skip-smoke-test).
#
# Idempotent: re-running with the same SHA re-runs migrations + smoke test only;
# `docker compose pull` is a no-op when images are already up to date.

set -euo pipefail

SHA=""
FORCE_CHECKOUT=0
ASSUME_YES=0
SKIP_SMOKE=0

usage() {
  cat <<EOF
Usage: $0 <sha> [--force-checkout] [--yes] [--skip-smoke-test]

  <sha>                 Commit SHA (or tag) to deploy. Must exist in origin.
  --force-checkout      Allow checkout even if the working tree is dirty.
                        Will discard local changes — prompts unless --yes.
  --yes                 Skip the --force-checkout confirmation prompt.
  --skip-smoke-test     Skip the smoke-test step (use sparingly).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --force-checkout) FORCE_CHECKOUT=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --skip-smoke-test) SKIP_SMOKE=1; shift ;;
    -*) echo "unknown flag: $1" >&2; usage; exit 2 ;;
    *)
      if [ -z "${SHA}" ]; then
        SHA="$1"; shift
      else
        echo "unexpected extra argument: $1" >&2; usage; exit 2
      fi
      ;;
  esac
done

if [ -z "${SHA}" ]; then
  echo "error: <sha> is required" >&2
  usage
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 1. Working-tree check
# -----------------------------------------------------------------------------
if [ -n "$(git status --porcelain)" ]; then
  if [ "${FORCE_CHECKOUT}" -ne 1 ]; then
    die "working tree is dirty. Commit/stash changes or re-run with --force-checkout."
  fi
  if [ "${ASSUME_YES}" -ne 1 ]; then
    printf '[deploy] WARNING: --force-checkout will discard local changes.\n'
    printf '[deploy] Continue? [y/N] '
    read -r ans
    case "${ans}" in
      y|Y|yes|YES) ;;
      *) die "aborted by operator." ;;
    esac
  fi
  log "force-checkout requested — discarding local changes"
  git reset --hard
  git clean -fd
fi

# -----------------------------------------------------------------------------
# 2. Fetch and check out
# -----------------------------------------------------------------------------
CURRENT_SHA="$(git rev-parse HEAD)"
log "fetching origin"
git fetch origin --tags --prune

# Resolve SHA to an actual object before checking out, so we fail early
# on a typo'd input.
if ! git rev-parse --verify --quiet "${SHA}^{commit}" >/dev/null; then
  die "ref/sha '${SHA}' not found after fetch."
fi
TARGET_SHA="$(git rev-parse "${SHA}^{commit}")"

if [ "${CURRENT_SHA}" = "${TARGET_SHA}" ]; then
  log "already at ${TARGET_SHA} — skipping checkout"
else
  log "checking out ${TARGET_SHA}"
  git checkout --detach "${TARGET_SHA}"
fi

# -----------------------------------------------------------------------------
# 3. Update TAG in .env
# -----------------------------------------------------------------------------
if [ ! -f .env ]; then
  die ".env not found at ${REPO_ROOT}/.env — bootstrap the server per docs/deploy.md §2."
fi

if grep -q '^TAG=' .env; then
  # Portable in-place edit (GNU + BSD sed). Write to a tmp file then move.
  tmp="$(mktemp)"
  awk -v tag="${TARGET_SHA}" '
    /^TAG=/ { print "TAG=" tag; next }
    { print }
  ' .env > "${tmp}"
  mv "${tmp}" .env
else
  printf '\nTAG=%s\n' "${TARGET_SHA}" >> .env
fi
log "set TAG=${TARGET_SHA} in .env"

# -----------------------------------------------------------------------------
# 4. Pull rediska-* images
# -----------------------------------------------------------------------------
log "pulling rediska-* images"
docker compose pull rediska-web rediska-core rediska-worker rediska-beat

# -----------------------------------------------------------------------------
# 5. Recreate containers
# -----------------------------------------------------------------------------
log "rolling containers (docker compose up -d)"
docker compose up -d

# -----------------------------------------------------------------------------
# 6. Migrations
# -----------------------------------------------------------------------------
log "running alembic upgrade head"
# Wait briefly for rediska-core to become healthy before exec'ing into it.
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if docker compose exec -T rediska-core true 2>/dev/null; then
    break
  fi
  log "  waiting for rediska-core to accept exec (${attempt}/10)"
  sleep 3
done
docker compose exec -T rediska-core alembic upgrade head

# -----------------------------------------------------------------------------
# 7. Smoke test
# -----------------------------------------------------------------------------
if [ "${SKIP_SMOKE}" -eq 1 ]; then
  log "smoke test skipped (--skip-smoke-test)"
else
  log "running smoke test"
  "${SCRIPT_DIR}/smoke_test.sh"
fi

log "deploy of ${TARGET_SHA} complete"
