#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

LOCK_FILE="${SNIPER_RUN_LOCK_FILE:-/tmp/sniper_server_run_once.lock}"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "server_run_once skipped: previous run still active"
    exit 0
  fi
else
  echo "server_run_once warning: flock unavailable; continuing without overlap lock"
fi

set -a
. ./.env.local
set +a

export MONITOR_DISABLED_PROJECTS="${MONITOR_DISABLED_PROJECTS:-O1}"

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

run_step() {
  local seconds="$1"
  shift
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  if command -v timeout >/dev/null 2>&1; then
    if ! timeout "$seconds" "$@"; then
      echo "step failed or timed out after ${seconds}s: $*" >&2
    fi
  else
    if ! "$@"; then
      echo "step failed: $*" >&2
    fi
  fi
}

run_step "${SNIPER_MONITOR_TIMEOUT_SECONDS:-180}" python3 scripts/sniper_monitor.py
run_step "${ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS:-120}" python3 scripts/alpha_project_watch.py
run_step "${ALPHA_PRELAUNCH_TIMEOUT_SECONDS:-60}" python3 scripts/alpha_prelaunch_watch.py
run_step "${ALPHA_OPENING_TIMEOUT_SECONDS:-720}" bash scripts/alpha_opening_sprint.sh
run_step "${OPENING_COHORT_FUNDER_TIMEOUT_SECONDS:-90}" python3 scripts/review_opening_cohort_funders.py --lookback-blocks "${OPENING_COHORT_FUNDER_LOOKBACK_BLOCKS:-120}" --max-scan-seconds "${OPENING_COHORT_FUNDER_MAX_SCAN_SECONDS:-25}"
run_step "${ALPHA_INTRADAY_TIMEOUT_SECONDS:-180}" python3 scripts/alpha_intraday_flow_watch.py
run_step "${PERP_OI_FUNDING_TIMEOUT_SECONDS:-90}" python3 scripts/perp_oi_funding_watch.py
run_step "${ALPHA_PRICE_MOMENTUM_TIMEOUT_SECONDS:-90}" python3 scripts/alpha_price_momentum_watch.py
run_step "${ALPHA_HOLDER_TIMEOUT_SECONDS:-240}" python3 scripts/alpha_holder_concentration_watch.py
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
run_step "${TELEGRAM_COLLECTOR_TIMEOUT_SECONDS:-90}" python3 scripts/telegram_signal_collector.py
run_step "${TELEGRAM_USER_COLLECTOR_TIMEOUT_SECONDS:-120}" python3 scripts/telegram_user_signal_collector.py
run_step "${PREDICTION_MARKET_TIMEOUT_SECONDS:-90}" python3 scripts/prediction_market_watch.py
run_step "${EXTERNAL_AUX_SOURCE_TIMEOUT_SECONDS:-45}" python3 scripts/external_aux_source_readiness.py
if [[ "${RUN_O1_ATTRIBUTION:-0}" == "1" ]]; then
  run_step "${ATTRIBUTION_TIMEOUT_SECONDS:-90}" python3 scripts/o1_address_attribution.py
else
  echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) skipped O1 attribution; RUN_O1_ATTRIBUTION=1 to enable"
fi
run_step "${DAILY_REPORT_TIMEOUT_SECONDS:-90}" python3 scripts/build_alpha_daily_report.py
run_step "${VERIFY_TIMEOUT_SECONDS:-120}" python3 scripts/verify_sniper_engine.py
