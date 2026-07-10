#!/usr/bin/env bash
set -euo pipefail

cd "${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"

set -a
. ./.env.local
set +a

if command -v timeout >/dev/null 2>&1; then
  timeout "${RUNTIME_HEALTH_WATCHDOG_TIMEOUT_SECONDS:-45}" python3 scripts/runtime_health_watch.py --mode watchdog
else
  python3 scripts/runtime_health_watch.py --mode watchdog
fi
