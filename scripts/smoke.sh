#!/usr/bin/env bash
# Smoke test against the real runtime containers.
#
# Runs under its own Compose project (dashbite-smoke), so it never touches the
# containers or the data volume of the normal "dashbite" project, and removes
# its own containers, network and volume on exit.
#
# Usage:   bash scripts/smoke.sh
# Exit:    0 when every check passes, 1 otherwise.
# Env:     DASHBOARD_PORT (default 8501), SMOKE_START_TIMEOUT (default 120),
#          SMOKE_OUTPUT_TIMEOUT (default 90), both in seconds.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROJECT=dashbite-smoke
PORT="${DASHBOARD_PORT:-8501}"
START_TIMEOUT="${SMOKE_START_TIMEOUT:-120}"
OUTPUT_TIMEOUT="${SMOKE_OUTPUT_TIMEOUT:-90}"
WORKERS="simulator preprocess train infer"
SERVICES="$WORKERS dashboard"

# Fixed demo tunables, so the result does not depend on the caller's shell.
export DASHBOARD_PORT="$PORT"
export TRAIN_EVERY_N_EVENTS=50 BATCH_SIZE=20 POLL_INTERVAL_SECONDS=2
export CORRUPT_BATCH_RATE=0.25 RANDOM_SEED=42 HEALTH_MAX_AGE_SECONDS=30

compose() { docker compose --progress quiet -p "$PROJECT" "$@"; }
in_service() { local service="$1"; shift; compose exec -T "$service" "$@"; }

failures=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; failures=$((failures + 1)); }
# check "<description>" <command...>: PASS when the command succeeds.
check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
}

# --- Preflight: fail fast, before anything is started ------------------------
command -v docker >/dev/null || { echo "smoke: docker not found" >&2; exit 1; }
command -v curl >/dev/null || { echo "smoke: curl not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "smoke: Docker is not running" >&2; exit 1; }
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "smoke: port $PORT is already in use." >&2
  echo "smoke: stop what is using it (for example 'docker compose down') or set DASHBOARD_PORT." >&2
  exit 1
fi

cleanup() {
  local status=$?
  trap - EXIT
  if [ "$status" -ne 0 ]; then
    echo "--- last log lines ---"
    compose logs --tail 15 2>/dev/null || true
  fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

# --- Helpers used by the checks ----------------------------------------------
service_is_healthy() {
  local id
  id="$(compose ps -q "$1")"
  [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id")" = healthy ]
}
runs_as_uid_10001() { [ "$(in_service simulator id -u)" = 10001 ]; }
pytest_is_absent() { ! in_service simulator python -c "import pytest"; }
health_endpoint_ok() { [ "$(curl -fsS "http://127.0.0.1:$PORT/_stcore/health")" = ok ]; }
# What `streamlit run` needs: `pipeline` importable without the working directory.
dashboard_imports() {
  in_service dashboard sh -c 'cd / && python -P -c "import pipeline.dashboard.app"'
}
has_all_outputs() {
  in_service infer sh -c 'ls /data/raw/orders_*.csv /data/features/features_*.csv \
    /data/quality/batch_quality.csv /data/models/checkpoint_*.joblib \
    /data/predictions/predictions_*.csv'
}
data_owned_by_uid_10001() { [ "$(in_service infer stat -c %u /data/predictions)" = 10001 ]; }
heartbeats_off_the_volume() { [ -z "$(in_service infer find /data -name '*.heartbeat')" ]; }
raw_count() { in_service preprocess sh -c 'ls /data/raw | wc -l'; }
# wait_for <seconds> <command...>: retry until the command succeeds or time is up.
wait_for() {
  local deadline=$((SECONDS + $1)); shift
  until "$@" >/dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 2
  done
}
all_exited_zero() {
  local codes
  codes="$(compose ps -a --format '{{.Service}} {{.ExitCode}}')"
  [ "$(echo "$codes" | wc -l)" -eq 5 ] && ! echo "$codes" | grep -qv ' 0$'
}

# --- Start -------------------------------------------------------------------
echo "== build and start (project $PROJECT, port $PORT)"
compose down -v --remove-orphans >/dev/null 2>&1 || true
compose build --quiet
compose up -d --wait --wait-timeout "$START_TIMEOUT"

# --- Checks ------------------------------------------------------------------
echo "== checks"
for service in $SERVICES; do
  check "$service is healthy" service_is_healthy "$service"
done
check "containers run as uid 10001" runs_as_uid_10001
check "pytest is not in the runtime image" pytest_is_absent
check "dashboard answers on http://127.0.0.1:$PORT/_stcore/health" health_endpoint_ok
check "dashboard app imports without the working directory on sys.path" dashboard_imports
check "raw, features, quality log, checkpoint and predictions exist within ${OUTPUT_TIMEOUT}s" \
  wait_for "$OUTPUT_TIMEOUT" has_all_outputs
check "data is owned by uid 10001" data_owned_by_uid_10001
check "heartbeat files are not on the data volume" heartbeats_off_the_volume

echo "== persistence: down (volume kept), then up"
before="$(raw_count)"
compose down >/dev/null 2>&1
compose up -d --wait --wait-timeout "$START_TIMEOUT" >/dev/null 2>&1
after="$(raw_count)"
if [ "$before" -gt 0 ] && [ "$after" -ge "$before" ]; then
  pass "raw files survive down/up ($before before, $after after)"
else
  fail "raw files survive down/up ($before before, $after after)"
fi

echo "== graceful shutdown: stop after startup"
compose stop >/dev/null 2>&1
compose ps -a --format '      {{.Service}}: {{.State}}, exit code {{.ExitCode}}'
check "all five services exited with code 0" all_exited_zero

# --- Result ------------------------------------------------------------------
if [ "$failures" -gt 0 ]; then
  echo "SMOKE FAILED: $failures check(s) failed"
  exit 1
fi
echo "SMOKE PASSED"
