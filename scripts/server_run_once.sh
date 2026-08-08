#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

REQUESTED_ALPHA_PROJECT_ONLY="${ALPHA_PROJECT_ONLY:-0}"
if [[ "$REQUESTED_ALPHA_PROJECT_ONLY" == "1" ]]; then
  LOCK_FILE="${SNIPER_PROJECT_ONLY_RUN_LOCK_FILE:-/tmp/sniper_server_project_only.lock}"
else
  LOCK_FILE="${SNIPER_RUN_LOCK_FILE:-/tmp/sniper_server_run_once.lock}"
fi
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "server_run_once skipped: previous run still active"
    if [[ "$REQUESTED_ALPHA_PROJECT_ONLY" == "1" ]]; then
      exit 75
    fi
    exit "${SNIPER_OVERLAP_SKIP_EXIT_CODE:-0}"
  fi
else
  echo "server_run_once warning: flock unavailable; continuing without overlap lock"
fi

REQUESTED_DISABLE_TELEGRAM="${DISABLE_TELEGRAM:-0}"

set -a
. ./.env.local
set +a

if [[ "$REQUESTED_DISABLE_TELEGRAM" == "1" ]]; then
  export DISABLE_TELEGRAM=1
fi

export MONITOR_DISABLED_PROJECTS="${MONITOR_DISABLED_PROJECTS:-O1}"
RUNTIME_HEALTH_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUNTIME_HEALTH_FAILURE_FILE="$(mktemp /tmp/sniper_runtime_failures.XXXXXX)"
trap 'rm -f "$RUNTIME_HEALTH_FAILURE_FILE"' EXIT

if [[ "${DISABLE_TELEGRAM:-0}" == "1" ]]; then
  export SNIPER_MONITOR_TELEGRAM=0
  export ALPHA_PROJECT_WATCH_TELEGRAM=0
  export ALPHA_PRELAUNCH_TELEGRAM=0
  export ALPHA_OPENING_TELEGRAM=0
  export ALPHA_PRICE_MOMENTUM_TELEGRAM=0
  export ALPHA_HOLDER_TELEGRAM=0
  export ARX_LAUNCH_TELEGRAM=0
  export ARX_OPENING_TELEGRAM=0
fi

export ALPHA_PROJECT_LOG_CHUNK_BLOCKS="${ALPHA_PROJECT_LOG_CHUNK_BLOCKS:-2000}"

LAST_STEP_STATUS=0
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
    echo "step failed with status ${status} or timed out after ${seconds}s: $*" >&2
    printf '%s\t%s\t%s\n' "$status" "$seconds" "$*" >>"$RUNTIME_HEALTH_FAILURE_FILE"
  fi
  LAST_STEP_STATUS="$status"
}

acquire_project_lock() {
  local project_lock_file="${ALPHA_PROJECT_WATCH_LOCK_FILE:-/tmp/sniper_alpha_project_watch.lock}"
  if ! command -v flock >/dev/null 2>&1; then
    return 78
  fi
  exec 7>"$project_lock_file"
  flock -w 5 7
}

release_project_lock() {
  if command -v flock >/dev/null 2>&1; then
    flock -u 7
  fi
}

run_project_step() {
  local seconds="$1"
  local lock_status=0
  shift
  acquire_project_lock || lock_status=$?
  if (( lock_status != 0 )); then
    echo "alpha project watch failed: project lock unavailable" >&2
    printf '%s\t%s\t%s\n' "$lock_status" "$seconds" "alpha project lock" >>"$RUNTIME_HEALTH_FAILURE_FILE"
    return 0
  fi
  run_step "$seconds" "$@"
  release_project_lock
}

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
    echo "server_run_once failed: curated Alpha monitoring policy is invalid" >&2
    exit 78
  fi
  if [[ -s "$runtime_watchlist" ]] \
    && (( runtime_age <= runtime_ttl )) \
    && [[ "$runtime_policy_status" == "runtime_valid" ]]; then
    export ALPHA_WATCHLIST_PATH="$runtime_watchlist"
  else
    export ALPHA_WATCHLIST_PATH="$curated_watchlist"
    echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) catalog runtime watchlist unavailable, stale, or policy-mismatched; using curated config"
  fi
else
  configured_policy_status="$(
    python3 -c 'from pathlib import Path; import sys; from scripts.binance_alpha_catalog_watch import watchlist_policy_status; print(watchlist_policy_status(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])))' \
      "$ALPHA_WATCHLIST_PATH" "config/current_alpha_watchlist.json" "$runtime_ttl" 2>/dev/null || echo "static_invalid"
  )"
  if [[ "$configured_policy_status" != "runtime_valid" ]]; then
    echo "server_run_once failed: configured Alpha watchlist violates the curated monitoring policy" >&2
    exit 78
  fi
fi
if [[ "$REQUESTED_ALPHA_PROJECT_ONLY" == "1" ]]; then
  project_only_cycles="${ALPHA_PROJECT_ONLY_CYCLES:-1}"
  if [[ ! "$project_only_cycles" =~ ^[1-9][0-9]*$ ]] \
    || (( 10#$project_only_cycles > 64 )); then
    echo "server_run_once failed: invalid project-only cycle count" >&2
    exit 64
  fi
  project_only_cycles="$((10#$project_only_cycles))"
  project_lock_status=0
  acquire_project_lock || project_lock_status=$?
  if (( project_lock_status != 0 )); then
    echo "alpha project watch failed: project lock unavailable" >&2
    exit "$project_lock_status"
  fi
  project_only_status=1
  for ((project_cycle = 1; project_cycle <= project_only_cycles; project_cycle++)); do
    echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) project-only cycle ${project_cycle}/${project_only_cycles}"
    run_step "${ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS:-120}" python3 scripts/alpha_project_watch.py
    project_only_status="$LAST_STEP_STATUS"
    if [[ ! -s output/alpha_project_watch/progress.json ]]; then
      break
    fi
  done
  release_project_lock
  if [[ -s output/alpha_project_watch/progress.json ]]; then
    echo "alpha project watch incomplete after ${project_only_cycles} cycles" >&2
    exit 1
  fi
  exit "$project_only_status"
fi
run_step "${SNIPER_MONITOR_TIMEOUT_SECONDS:-180}" python3 scripts/sniper_monitor.py
run_project_step "${ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS:-120}" python3 scripts/alpha_project_watch.py
run_step "${ALPHA_INTRADAY_TIMEOUT_SECONDS:-480}" python3 scripts/alpha_intraday_flow_watch.py
run_step "${ALPHA_OPENING_TIMEOUT_SECONDS:-720}" bash scripts/alpha_opening_sprint.sh
run_step "${ALPHA_INTRADAY_POST_OPENING_TIMEOUT_SECONDS:-360}" env ALPHA_INTRADAY_REQUIRED_ONLY=1 ALPHA_INTRADAY_WATCHER_BUDGET_SECONDS="${ALPHA_INTRADAY_POST_OPENING_WATCHER_BUDGET_SECONDS:-330}" python3 scripts/alpha_intraday_flow_watch.py
run_step "${OPENING_COHORT_FUNDER_TIMEOUT_SECONDS:-90}" python3 scripts/review_opening_cohort_funders.py --lookback-blocks "${OPENING_COHORT_FUNDER_LOOKBACK_BLOCKS:-120}" --max-scan-seconds "${OPENING_COHORT_FUNDER_MAX_SCAN_SECONDS:-25}"
run_step "${ALPHA_HOLDER_TIMEOUT_SECONDS:-240}" python3 scripts/alpha_holder_concentration_watch.py
if [[ "${RUN_GRVT_LIQUIDITY_REPLAY_ACCEPTANCE:-0}" == "1" ]]; then
  run_step "${GRVT_LIQUIDITY_REPLAY_ACCEPTANCE_TIMEOUT_SECONDS:-240}" \
    python3 scripts/grvt_liquidity_replay_acceptance.py \
      --rpc-mode runtime \
      --output output/grvt_liquidity_replay_acceptance/latest.json
fi
run_step "${SURF_AUX_MARKET_TIMEOUT_SECONDS:-180}" python3 scripts/surf_aux_market_watch.py
if [[ "${RUN_ARX_OPENING_REFRESH:-0}" == "1" || ! -s output/arx_opening_block_watch/latest.json ]]; then
  run_step "${ARX_OPENING_TIMEOUT_SECONDS:-720}" bash scripts/arx_opening_sprint.sh
else
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped ARX opening refresh; RUN_ARX_OPENING_REFRESH=1 to enable"
fi
if [[ "${RUN_ARX_LAUNCH_WATCH:-0}" == "1" ]]; then
  run_step "${ARX_LAUNCH_TIMEOUT_SECONDS:-120}" python3 scripts/arx_launch_watch.py
else
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped ARX launch watch; RUN_ARX_LAUNCH_WATCH=1 to enable"
fi
run_step "${EXTERNAL_AUX_SOURCE_TIMEOUT_SECONDS:-45}" python3 scripts/external_aux_source_readiness.py
if [[ "${RUN_EXTERNAL_AUX_LIVE_PROBE:-0}" == "1" ]]; then
  run_step "${EXTERNAL_AUX_LIVE_PROBE_TIMEOUT_SECONDS:-60}" python3 scripts/external_aux_live_probe.py
else
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped external aux live probe; RUN_EXTERNAL_AUX_LIVE_PROBE=1 to enable"
fi
if [[ "${RUN_O1_ATTRIBUTION:-0}" == "1" ]]; then
  run_step "${ATTRIBUTION_TIMEOUT_SECONDS:-90}" python3 scripts/o1_address_attribution.py
else
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped O1 attribution; RUN_O1_ATTRIBUTION=1 to enable"
fi
run_step "${POSITION_COST_TIMEOUT_SECONDS:-45}" python3 scripts/position_cost_watch.py
run_step "${DAILY_REPORT_TIMEOUT_SECONDS:-90}" python3 scripts/build_alpha_daily_report.py
run_step "${VERIFY_TIMEOUT_SECONDS:-120}" python3 scripts/verify_sniper_engine.py
python3 scripts/runtime_health_watch.py --mode cycle --failure-file "$RUNTIME_HEALTH_FAILURE_FILE" --started-at "$RUNTIME_HEALTH_STARTED_AT"
