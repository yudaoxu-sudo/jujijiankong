#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

LOCK_FILE="${SNIPER_FAST_LANE_LOCK_FILE:-/tmp/sniper_server_fast_lane.lock}"
if command -v flock >/dev/null 2>&1; then
  exec 8>"$LOCK_FILE"
  if ! flock -n 8; then
    echo "server_fast_lane skipped: previous fast lane still active"
    exit 0
  fi
else
  echo "server_fast_lane failed: flock is required for overlap protection" >&2
  exit 78
fi

REQUESTED_DISABLE_TELEGRAM="${DISABLE_TELEGRAM:-0}"
set -a
. ./.env.local
set +a
if [[ "$REQUESTED_DISABLE_TELEGRAM" == "1" ]]; then
  export DISABLE_TELEGRAM=1
fi

if [[ "${DISABLE_TELEGRAM:-0}" == "1" ]]; then
  export ALPHA_PRELAUNCH_TELEGRAM=0
  export ALPHA_PRICE_MOMENTUM_TELEGRAM=0
  export ALPHA_HOLDER_TELEGRAM=0
fi

export ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS=8
export ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS="${ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS:-512}"
export ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS=1

FAST_LANE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
FAST_LANE_FAILURE_FILE="$(mktemp /tmp/sniper_fast_lane_failures.XXXXXX)"
trap 'rm -f "$FAST_LANE_FAILURE_FILE"' EXIT

run_step() {
  local seconds="$1"
  local status=0
  shift
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  if command -v timeout >/dev/null 2>&1; then
    timeout "$seconds" "$@" || status=$?
  else
    "$@" || status=$?
  fi
  if (( status != 0 )); then
    echo "fast-lane step failed with status ${status} or timed out after ${seconds}s: $*" >&2
    printf '%s\t%s\t%s\n' "$status" "$seconds" "$*" >>"$FAST_LANE_FAILURE_FILE"
  fi
}

run_step "${FAST_TELEGRAM_COLLECTOR_TIMEOUT_SECONDS:-20}" python3 scripts/telegram_signal_collector.py --defer-analysis &
collector_pid=$!
run_step "${FAST_TELEGRAM_USER_COLLECTOR_TIMEOUT_SECONDS:-25}" env SIGNAL_RUNTIME_CONTEXT=0 python3 scripts/telegram_user_signal_collector.py &
user_collector_pid=$!
wait "$collector_pid"
wait "$user_collector_pid"
run_step "${FAST_BINANCE_ALPHA_CATALOG_TIMEOUT_SECONDS:-20}" python3 scripts/binance_alpha_catalog_watch.py

runtime_ttl="${BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS:-21600}"
if [[ -z "${ALPHA_WATCHLIST_PATH:-}" ]]; then
  runtime_watchlist="output/binance_alpha_catalog_watch/current_watchlist.json"
  curated_watchlist="config/current_alpha_watchlist.json"
  runtime_age="$(
    python3 -c 'import os, sys, time; print(max(0, int(time.time() - os.path.getmtime(sys.argv[1]))))' \
      "$runtime_watchlist" 2>/dev/null || echo "$((runtime_ttl + 1))"
  )"
  runtime_policy_status="$(
    python3 -c 'from pathlib import Path; import sys; from scripts.binance_alpha_catalog_watch import watchlist_policy_status; print(watchlist_policy_status(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])))' \
      "$runtime_watchlist" "$curated_watchlist" "$runtime_ttl" 2>/dev/null || echo "static_invalid"
  )"
  if [[ "$runtime_policy_status" == "static_invalid" ]]; then
    echo "server_fast_lane failed: curated Alpha monitoring policy is invalid" >&2
    exit 78
  fi
  if [[ -s "$runtime_watchlist" ]] \
    && (( runtime_age <= runtime_ttl )) \
    && [[ "$runtime_policy_status" == "runtime_valid" ]]; then
    export ALPHA_WATCHLIST_PATH="$runtime_watchlist"
  else
    export ALPHA_WATCHLIST_PATH="$curated_watchlist"
    echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) fast lane using curated watchlist fallback after runtime policy check"
  fi
else
  configured_policy_status="$(
    python3 -c 'from pathlib import Path; import sys; from scripts.binance_alpha_catalog_watch import watchlist_policy_status; print(watchlist_policy_status(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])))' \
      "$ALPHA_WATCHLIST_PATH" "config/current_alpha_watchlist.json" "$runtime_ttl" 2>/dev/null || echo "static_invalid"
  )"
  if [[ "$configured_policy_status" != "runtime_valid" ]]; then
    echo "server_fast_lane failed: configured Alpha watchlist violates the curated monitoring policy" >&2
    exit 78
  fi
fi

run_step "${FAST_PREDICTION_MARKET_TIMEOUT_SECONDS:-20}" python3 scripts/prediction_market_watch.py &
prediction_pid=$!
run_step "${FAST_ALPHA_PRELAUNCH_TIMEOUT_SECONDS:-15}" python3 scripts/alpha_prelaunch_watch.py &
prelaunch_pid=$!
run_step "${FAST_PERP_OI_FUNDING_TIMEOUT_SECONDS:-25}" python3 scripts/perp_oi_funding_watch.py &
perp_pid=$!
run_step "${FAST_ALPHA_LIQUIDITY_TIMEOUT_SECONDS:-40}" python3 scripts/alpha_liquidity_retention_watch.py &
liquidity_pid=$!
wait "$prediction_pid"
wait "$prelaunch_pid"
wait "$perp_pid"
run_step "${FAST_ALPHA_PRICE_MOMENTUM_TIMEOUT_SECONDS:-25}" python3 scripts/alpha_price_momentum_watch.py
wait "$liquidity_pid"
run_step "${FAST_TELEGRAM_FLUSH_TIMEOUT_SECONDS:-15}" python3 scripts/telegram_signal_collector.py --flush-pending
python3 scripts/fast_lane_health.py \
  --failure-file "$FAST_LANE_FAILURE_FILE" \
  --started-at "$FAST_LANE_STARTED_AT"
