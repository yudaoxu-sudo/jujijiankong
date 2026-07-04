#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

interval="${ALPHA_OPENING_SPRINT_INTERVAL_SECONDS:-20}"
window="${ALPHA_OPENING_SPRINT_WINDOW_SECONDS:-600}"
max_runs="${ALPHA_OPENING_SPRINT_MAX_RUNS:-40}"

run_once() {
  ALPHA_OPENING_MAX_TXS="${ALPHA_OPENING_SPRINT_MAX_TXS:-8}" \
    ALPHA_OPENING_TRACE_BUYERS="${ALPHA_OPENING_SPRINT_TRACE_BUYERS:-4}" \
    python3 scripts/alpha_opening_block_watch.py
}

min_seconds_until() {
  python3 - <<'PY'
import json
from pathlib import Path

path = Path("output/alpha_opening_block_watch/latest.json")
if not path.exists():
    print("999999")
    raise SystemExit
payload = json.loads(path.read_text(encoding="utf-8"))
values = [
    int(event.get("seconds_until_start") or 0)
    for event in payload.get("events", [])
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
  sleep "$interval"
  run_once
done
