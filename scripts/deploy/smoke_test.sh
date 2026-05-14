#!/usr/bin/env bash
# Rediska smoke test — automatable subset of docs/deploy.md §4.
#
# Runs items 1, 2, 6, 7, 8 from the smoke-test checklist. Manual items
# (3, 4, 5, 9, 10) are operator-driven and not covered here.
#
# Exits non-zero on the first failure with a pointer to the relevant
# section of docs/deploy.md. Safe to re-run.

set -euo pipefail

# Resolve repo root from the script location so the user can invoke
# this from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

BASE_URL="${BASE_URL:-https://rediska.local}"
WORKER_LOG_WINDOW="${WORKER_LOG_WINDOW:-5m}"

PASS=0
FAIL=0

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
note()  { printf '   %s\n' "$*"; }

pass() { green "PASS  $1"; PASS=$((PASS + 1)); }
fail() {
  red "FAIL  $1"
  note "$2"
  FAIL=$((FAIL + 1))
  exit 1
}

# -----------------------------------------------------------------------------
# Item 1: every container Up; healthchecked ones healthy.
# -----------------------------------------------------------------------------
check_compose_ps() {
  local title="Item 1 (compose ps): every container Up; healthchecked ones healthy"
  local ps_out
  ps_out="$(docker compose ps --format json 2>/dev/null || true)"
  if [ -z "${ps_out}" ]; then
    fail "${title}" "No containers running. See docs/deploy.md §3.1 (Start the stack)."
  fi

  # `docker compose ps --format json` emits one JSON object per line in
  # recent versions; tolerate both single-array and NDJSON forms.
  local bad
  bad="$(printf '%s\n' "${ps_out}" | python3 - <<'PY' 2>/dev/null || true
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)
docs = []
try:
    parsed = json.loads(raw)
    docs = parsed if isinstance(parsed, list) else [parsed]
except json.JSONDecodeError:
    for line in raw.splitlines():
        line = line.strip()
        if line:
            docs.append(json.loads(line))
bad = []
for d in docs:
    name = d.get("Name") or d.get("Service") or "?"
    state = d.get("State", "")
    health = d.get("Health", "")
    if state != "running":
        bad.append(f"{name}: state={state}")
    elif health and health not in ("healthy", ""):
        bad.append(f"{name}: health={health}")
print("\n".join(bad))
PY
)"
  if [ -n "${bad}" ]; then
    fail "${title}" "Not all containers healthy:
${bad}
See docs/deploy.md §3.2 (Wait for healthchecks) and §6.2 (Where to look)."
  fi
  pass "${title}"
}

# -----------------------------------------------------------------------------
# Item 2: HTTPS reachability at BASE_URL.
# -----------------------------------------------------------------------------
check_https_reachable() {
  local title="Item 2 (https reach): ${BASE_URL}/ returns 200 or 302"
  local code
  code="$(curl -sk -o /dev/null -w '%{http_code}' "${BASE_URL}/" || echo "000")"
  case "${code}" in
    200|302) pass "${title} (HTTP ${code})" ;;
    *) fail "${title}" "Got HTTP ${code}. See docs/deploy.md §6.2 (smoke item 2)." ;;
  esac
}

# -----------------------------------------------------------------------------
# Item 6: no ERROR/Traceback in the worker log window.
# -----------------------------------------------------------------------------
check_worker_logs() {
  local title="Item 6 (worker logs): no ERROR/Traceback in last ${WORKER_LOG_WINDOW}"
  local logs
  logs="$(docker compose logs rediska-worker --since "${WORKER_LOG_WINDOW}" 2>/dev/null || true)"
  if printf '%s' "${logs}" | grep -E -q '(ERROR|Traceback)'; then
    fail "${title}" "Worker has ERROR/Traceback in the last ${WORKER_LOG_WINDOW}.
Run: docker compose logs rediska-worker --since ${WORKER_LOG_WINDOW}
See docs/deploy.md §6.2 (smoke item 6)."
  fi
  pass "${title}"
}

# -----------------------------------------------------------------------------
# Item 7: alembic at head.
# -----------------------------------------------------------------------------
check_alembic_head() {
  local title="Item 7 (alembic): current revision is head"
  local out
  out="$(docker compose exec -T rediska-core alembic current 2>&1 || true)"
  if printf '%s' "${out}" | grep -q '(head)'; then
    pass "${title}"
  else
    fail "${title}" "alembic current did not report (head). Output:
${out}
Run: docker compose exec rediska-core alembic upgrade head
See docs/deploy.md §3.3 (Run database migrations)."
  fi
}

# -----------------------------------------------------------------------------
# Item 8: celery-beat heartbeat keys in Redis.
# -----------------------------------------------------------------------------
check_beat_heartbeat() {
  local title="Item 8 (beat): celery-beat* keys present in Redis"
  local keys
  keys="$(docker compose exec -T rediska-redis redis-cli --scan --pattern 'celery-beat*' 2>/dev/null || true)"
  if [ -n "${keys}" ]; then
    pass "${title}"
  else
    fail "${title}" "No celery-beat* keys in Redis. Beat may be down.
Run: docker compose logs rediska-beat --tail 100
See docs/deploy.md §6.2 (smoke item 8)."
  fi
}

# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
echo "Rediska smoke test"
echo "  repo:      ${REPO_ROOT}"
echo "  base url:  ${BASE_URL}"
echo

check_compose_ps
check_https_reachable
check_worker_logs
check_alembic_head
check_beat_heartbeat

echo
green "All scripted smoke items passed (${PASS}/${PASS})."
echo "Run the manual items (3, 4, 5, 9, 10) per docs/deploy.md §4 to fully validate."
