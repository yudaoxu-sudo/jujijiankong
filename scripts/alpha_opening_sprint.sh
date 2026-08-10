#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

interval="${ALPHA_OPENING_SPRINT_INTERVAL_SECONDS:-20}"
window="${ALPHA_OPENING_SPRINT_WINDOW_SECONDS:-600}"
max_runs="${ALPHA_OPENING_SPRINT_MAX_RUNS:-40}"
total_seconds="${ALPHA_OPENING_SPRINT_TOTAL_SECONDS:-660}"
post_seconds="${ALPHA_OPENING_SPRINT_POST_SECONDS:-30}"
started_seconds="$SECONDS"

run_once() {
  local remaining trace_budget hard_timeout status
  local -a command
  remaining=$((total_seconds - (SECONDS - started_seconds)))
  if (( remaining <= post_seconds )); then
    return 0
  fi
  trace_budget="${ALPHA_OPENING_SPRINT_TRACE_DEADLINE_SECONDS:-300}"
  if (( trace_budget > remaining - post_seconds )); then
    trace_budget=$((remaining - post_seconds))
  fi
  hard_timeout=$((trace_budget + post_seconds))
  command=(
    env
    "ALPHA_OPENING_MAX_TXS=${ALPHA_OPENING_SPRINT_MAX_TXS:-8}"
    "ALPHA_OPENING_TRACE_BUYERS=${ALPHA_OPENING_SPRINT_TRACE_BUYERS:-4}"
    "ALPHA_OPENING_CLASSIFY_OUT_TXS=${ALPHA_OPENING_SPRINT_CLASSIFY_OUT_TXS:-2}"
    "ALPHA_OPENING_NEXT_HOP_RECIPIENTS=${ALPHA_OPENING_SPRINT_NEXT_HOP_RECIPIENTS:-1}"
    "ALPHA_OPENING_NEXT_HOP_CLASSIFY_TXS=${ALPHA_OPENING_SPRINT_NEXT_HOP_CLASSIFY_TXS:-2}"
    "ALPHA_OPENING_TRACE_DEADLINE_SECONDS=$trace_budget"
    "ALPHA_OPENING_REUSE_OPENED_CACHE=${ALPHA_OPENING_SPRINT_REUSE_OPENED_CACHE:-1}"
    python3
    scripts/alpha_opening_block_watch.py
  )
  if ! command -v timeout >/dev/null 2>&1; then
    "${command[@]}"
    return
  fi
  if timeout "${hard_timeout}s" "${command[@]}"; then
    return 0
  else
    status=$?
  fi
  if (( status == 124 )); then
    echo "opening sprint inner hard timeout after ${hard_timeout}s" >&2
    return 75
  fi
  return "$status"
}

min_seconds_until() {
  python3 - <<'PY'
import json
from pathlib import Path
from scripts.alpha_opening_block_watch import opening_coverage_complete

path = Path("output/alpha_opening_block_watch/latest.json")
if not path.exists():
    print("999999")
    raise SystemExit
payload = json.loads(path.read_text(encoding="utf-8"))
events = [
    event
    for event in payload.get("events", [])
    if isinstance(event, dict)
]
if any(
    event.get("status") == "opened"
    and not opening_coverage_complete(event)
    for event in events
):
    print("1")
    raise SystemExit
values = [
    int(event.get("seconds_until_start") or 0)
    for event in events
    if event.get("status") == "waiting"
]
print(min(values) if values else "999999")
PY
}

run_once

for ((i = 1; i < max_runs; i++)); do
  secs="$(min_seconds_until)"
  if (( secs <= 0 || secs > window )); then
    break
  fi
  remaining=$((total_seconds - (SECONDS - started_seconds)))
  if (( remaining <= interval + post_seconds )); then
    break
  fi
  sleep "$interval"
  run_once
done
