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
runtime_watchlist="output/binance_alpha_catalog_watch/current_watchlist.json"
curated_watchlist="config/current_alpha_watchlist.json"
configured_watchlist="${ALPHA_WATCHLIST_PATH:-}"
materialized_watchlist_status=0
materialized_watchlist="$(
  python3 -c 'from pathlib import Path; import sys; from scripts.alpha_onboarding_preflight import select_and_materialize_watchlist; configured = Path(sys.argv[4]) if sys.argv[4] else None; print(select_and_materialize_watchlist(runtime_path=Path(sys.argv[1]), static_path=Path(sys.argv[2]), max_age_seconds=int(sys.argv[3]), configured_path=configured))' \
    "$runtime_watchlist" "$curated_watchlist" "$runtime_ttl" "$configured_watchlist"
)" || materialized_watchlist_status=$?
if (( materialized_watchlist_status != 0 )) || [[ -z "$materialized_watchlist" ]]; then
  echo "server_run_once failed: policy-checked Alpha watchlist cycle snapshot unavailable" >&2
  exit 78
fi
export ALPHA_WATCHLIST_PATH="$materialized_watchlist"
onboarding_preflight_status=0
python3 scripts/alpha_onboarding_preflight.py \
  --watchlist "$ALPHA_WATCHLIST_PATH" \
  --profile "binance_alpha_bsc.v1" || onboarding_preflight_status=$?
if (( onboarding_preflight_status != 0 )); then
  echo "server_run_once failed: Alpha onboarding preflight blocked" >&2
  exit 78
fi
grvt_replay_scope_status=0
grvt_replay_scope="$(
  python3 -c 'import json, sys; rows = [row for row in json.load(open(sys.argv[1], encoding="utf-8")).get("items", []) if str(row.get("symbol") or "").upper() == "GRVT"]; assert len(rows) == 1; state = rows[0].get("active_monitoring"); assert state is True or state is False; print("active" if state else "inactive")' \
    "$ALPHA_WATCHLIST_PATH"
)" || grvt_replay_scope_status=$?
if (( grvt_replay_scope_status != 0 )) \
  || [[ "$grvt_replay_scope" != "active" && "$grvt_replay_scope" != "inactive" ]]; then
  echo "server_run_once failed: GRVT replay scope unavailable" >&2
  exit 78
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
if [[ "${ALPHA_PROJECT_WATCH_PREFLIGHT_COMPLETE:-0}" == "1" ]]; then
  if [[ -s output/alpha_project_watch/progress.json ]]; then
    echo "alpha project watch failed: project preflight progress still present" >&2
    printf '%s\t%s\t%s\n' "1" "0" "alpha project preflight" >>"$RUNTIME_HEALTH_FAILURE_FILE"
  else
    echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) reused completed alpha project preflight"
  fi
else
  run_project_step "${ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS:-120}" python3 scripts/alpha_project_watch.py
fi
run_step "${ALPHA_INTRADAY_TIMEOUT_SECONDS:-480}" python3 scripts/alpha_intraday_flow_watch.py
run_step "${ALPHA_OPENING_TIMEOUT_SECONDS:-720}" bash scripts/alpha_opening_sprint.sh
run_step "${ALPHA_INTRADAY_POST_OPENING_TIMEOUT_SECONDS:-360}" env ALPHA_INTRADAY_REQUIRED_ONLY=1 ALPHA_INTRADAY_WATCHER_BUDGET_SECONDS="${ALPHA_INTRADAY_POST_OPENING_WATCHER_BUDGET_SECONDS:-330}" python3 scripts/alpha_intraday_flow_watch.py
run_step "${OPENING_COHORT_FUNDER_TIMEOUT_SECONDS:-90}" python3 scripts/review_opening_cohort_funders.py --lookback-blocks "${OPENING_COHORT_FUNDER_LOOKBACK_BLOCKS:-120}" --max-scan-seconds "${OPENING_COHORT_FUNDER_MAX_SCAN_SECONDS:-25}"
run_step "${ALPHA_HOLDER_TIMEOUT_SECONDS:-240}" python3 scripts/alpha_holder_concentration_watch.py
if [[ "$grvt_replay_scope" == "inactive" ]]; then
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped inactive GRVT replay refresh"
elif [[ "${RUN_GRVT_LIQUIDITY_REPLAY_ACCEPTANCE:-0}" == "1" ]]; then
  run_step "${GRVT_LIQUIDITY_REPLAY_ACCEPTANCE_TIMEOUT_SECONDS:-240}" \
    python3 scripts/grvt_liquidity_replay_acceptance.py \
      --rpc-mode runtime \
      --output output/grvt_liquidity_replay_acceptance/latest.json
else
  run_step "${GRVT_LIQUIDITY_REPLAY_ACCEPTANCE_TIMEOUT_SECONDS:-240}" \
    env DISABLE_TELEGRAM=1 \
    python3 scripts/grvt_liquidity_replay_acceptance.py \
      --rpc-mode runtime \
      --output output/grvt_liquidity_replay_acceptance/latest.json \
      --refresh-if-runtime-coverage-missing
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
