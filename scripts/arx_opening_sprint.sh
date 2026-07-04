#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

interval="${ARX_OPENING_SPRINT_INTERVAL_SECONDS:-20}"
window="${ARX_OPENING_SPRINT_WINDOW_SECONDS:-600}"
max_runs="${ARX_OPENING_SPRINT_MAX_RUNS:-40}"

run_once() {
  ARX_OPENING_MAX_TXS="${ARX_OPENING_SPRINT_MAX_TXS:-8}" \
    ARX_OPENING_TRACE_BUYERS="${ARX_OPENING_SPRINT_TRACE_BUYERS:-3}" \
    python3 scripts/arx_opening_block_watch.py
}

seconds_until() {
  python3 - <<'PY'
import json
from pathlib import Path

path = Path("output/arx_opening_block_watch/latest.json")
if not path.exists():
    print("999999")
    raise SystemExit
payload = json.loads(path.read_text(encoding="utf-8"))
print(int(payload.get("seconds_until_start") or 0))
PY
}

status_value() {
  python3 - <<'PY'
import json
from pathlib import Path

path = Path("output/arx_opening_block_watch/latest.json")
if not path.exists():
    print("")
    raise SystemExit
payload = json.loads(path.read_text(encoding="utf-8"))
print(str(payload.get("status") or ""))
PY
}

run_once

for ((i = 1; i < max_runs; i++)); do
  secs="$(seconds_until)"
  status="$(status_value)"
  if [[ "$status" == "opened" ]]; then
    break
  fi
  if (( secs <= 0 || secs > window )); then
    break
  fi
  sleep "$interval"
  run_once
done
