#!/usr/bin/env bash
set -euo pipefail

project_dir="${SNIPER_PROJECT_DIR:-/home/ubuntu/sniper}"
current="$(mktemp)"
next="$(mktemp)"
trap 'rm -f "$current" "$next"' EXIT

mkdir -p "$project_dir/logs"
crontab -l >"$current" 2>/dev/null || true

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    *"$project_dir/scripts/server_run_once.sh"*|*"$project_dir/scripts/server_health_watchdog.sh"*)
      continue
      ;;
  esac
  printf '%s\n' "$line" >>"$next"
done <"$current"

printf '%s\n' "*/5 * * * * $project_dir/scripts/server_run_once.sh >> $project_dir/logs/server_run_once.log 2>&1" >>"$next"
printf '%s\n' "*/10 * * * * $project_dir/scripts/server_health_watchdog.sh >> $project_dir/logs/server_health_watchdog.log 2>&1" >>"$next"

crontab "$next"
crontab -l
