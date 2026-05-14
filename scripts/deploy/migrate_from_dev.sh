#!/usr/bin/env bash
# Rediska migration helper — chains the dev → new-server migration steps
# from docs/deploy.md §5 with safety prompts.
#
# WHAT IT DOES
#   1. Stops worker/beat/web on the dev box.
#   2. mysqldumps the rediska database on the dev box.
#   3. scps the dump to the new server.
#   4. Wipes + reloads the rediska DB on the new server, then runs
#      alembic upgrade head.
#   5. rsyncs /var/lib/rediska/attachments/ to the new server.
#   6. Restarts worker/beat/web on the dev box (so you can roll back).
#
# WHAT IT DOES NOT DO
#   * Elasticsearch — reindex from the worker on the new server (see §5.4).
#   * Smoke test — run scripts/deploy/smoke_test.sh on the new server after.
#   * Cutover — change /etc/hosts entries by hand (§5.6).
#
# This script is meant to be run on the DEV BOX. It SSHes into the new
# server for the import + rsync target side.
#
# USAGE
#   ./scripts/deploy/migrate_from_dev.sh <user@new-host> [--yes]
#
# OPTIONS
#   --yes            Skip every confirmation prompt. Use with care.
#   --no-attachments Skip the rsync step (DB migration only).
#   -h, --help       Show this help.
#
# REQUIREMENTS
#   * Dev box: docker compose stack is running, MYSQL_ROOT_PASSWORD set in .env.
#   * New server: docker compose stack is running with an empty rediska DB
#     (i.e. alembic upgrade head has been run per docs/deploy.md §3.3).
#   * SSH key auth from dev to new server.

set -euo pipefail

show_help() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

ASSUME_YES=0
SKIP_ATTACHMENTS=0
REMOTE=""

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) show_help ;;
    --yes) ASSUME_YES=1 ;;
    --no-attachments) SKIP_ATTACHMENTS=1 ;;
    -*)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
    *)
      if [ -z "${REMOTE}" ]; then
        REMOTE="$1"
      else
        echo "Unexpected positional argument: $1" >&2
        exit 2
      fi
      ;;
  esac
  shift
done

if [ -z "${REMOTE}" ]; then
  echo "Usage: $0 <user@new-host> [--yes] [--no-attachments]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -f .env ]; then
  echo "No .env at ${REPO_ROOT}/.env — are you running this on the dev box?" >&2
  exit 1
fi

# Pull MYSQL_ROOT_PASSWORD from .env without sourcing the whole file.
MYSQL_ROOT_PASSWORD="$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | head -n1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [ -z "${MYSQL_ROOT_PASSWORD}" ]; then
  echo "MYSQL_ROOT_PASSWORD missing from .env" >&2
  exit 1
fi

confirm() {
  if [ "${ASSUME_YES}" -eq 1 ]; then
    return 0
  fi
  local prompt="$1"
  printf '%s [y/N] ' "${prompt}"
  read -r reply
  case "${reply}" in
    y|Y|yes|YES) return 0 ;;
    *) echo "Aborted."; exit 1 ;;
  esac
}

step() { printf '\n=== %s ===\n' "$*"; }

DUMP_LOCAL="/tmp/rediska-dump-$(date +%Y%m%d-%H%M%S).sql"
DUMP_REMOTE="/tmp/$(basename "${DUMP_LOCAL}")"

echo "Migration plan:"
echo "  Source:      $(hostname) (dev box, repo at ${REPO_ROOT})"
echo "  Destination: ${REMOTE}"
echo "  Dump file:   ${DUMP_LOCAL} -> ${REMOTE}:${DUMP_REMOTE}"
echo "  Attachments: $([ ${SKIP_ATTACHMENTS} -eq 1 ] && echo SKIPPED || echo "rsync /var/lib/rediska/attachments/")"
echo "  ES:          NOT migrated by this script (reindex on new server per docs/deploy.md §5.4)"
echo
confirm "Proceed with migration?"

step "1/6 — Freeze write paths on dev box"
docker compose stop rediska-worker rediska-beat rediska-web
trap 'echo; echo "Restarting frozen dev services..."; docker compose up -d rediska-worker rediska-beat rediska-web' EXIT

step "2/6 — Dump MySQL"
docker compose exec -T rediska-mysql \
  mysqldump --single-transaction --routines --triggers \
            -u root -p"${MYSQL_ROOT_PASSWORD}" rediska \
  > "${DUMP_LOCAL}"
ls -lh "${DUMP_LOCAL}"

step "3/6 — Transfer dump to ${REMOTE}"
scp "${DUMP_LOCAL}" "${REMOTE}:${DUMP_REMOTE}"

step "4/6 — Wipe + reload MySQL on new server, run alembic"
confirm "About to DROP DATABASE rediska on ${REMOTE} and reload from dump. Confirm?"
ssh "${REMOTE}" "set -euo pipefail
cd /opt/rediska
ROOT_PW=\"\$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | head -n1 | cut -d= -f2- | tr -d '\"' | tr -d \"'\")\"
docker compose exec -T rediska-mysql mysql -u root -p\"\${ROOT_PW}\" -e 'DROP DATABASE rediska; CREATE DATABASE rediska;'
docker compose exec -T rediska-mysql mysql -u root -p\"\${ROOT_PW}\" rediska < ${DUMP_REMOTE}
docker compose exec rediska-core alembic upgrade head
rm -f ${DUMP_REMOTE}
"

if [ "${SKIP_ATTACHMENTS}" -eq 0 ]; then
  step "5/6 — rsync attachments"
  rsync -avzh /var/lib/rediska/attachments/ "${REMOTE}:/var/lib/rediska/attachments/"
else
  step "5/6 — Attachments SKIPPED (--no-attachments)"
fi

step "6/6 — Restart frozen services on dev box"
docker compose up -d rediska-worker rediska-beat rediska-web
trap - EXIT

echo
echo "Migration data copy complete."
echo "Next steps (manual):"
echo "  1. SSH to ${REMOTE} and run scripts/deploy/smoke_test.sh."
echo "  2. Trigger an ES reindex on the new server (see docs/deploy.md §5.4)."
echo "  3. Repoint operator devices' /etc/hosts entries (§5.6)."
echo "  4. Keep the dev box untouched until smoke passes (rollback path is §5.7)."
