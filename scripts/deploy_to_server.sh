#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

server="${SNIPER_DEPLOY_TARGET:-ubuntu@43.156.45.133:/home/ubuntu/sniper/}"
ssh_cmd=(
  ssh
  -i .deploy/sniper_server_ed25519
  -o UserKnownHostsFile=.deploy/known_hosts
  -o StrictHostKeyChecking=yes
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=40
)

rsync -az \
  --exclude '.env.local' \
  --exclude '.deploy/' \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.session' \
  --exclude '*.session-journal' \
  --exclude 'logs/' \
  --exclude 'output/' \
  --exclude 'reports/' \
  -e "${ssh_cmd[*]}" \
  ./ "$server"

remote_target="${server%%:*}"
remote_dir="${server#*:}"
printf -v remote_dir_quoted '%q' "$remote_dir"

if ! "${ssh_cmd[@]}" "$remote_target" \
  "cd $remote_dir_quoted && bash scripts/install_server_cron.sh" \
  >/dev/null 2>&1; then
  printf '%s\n' 'remote cron installation failed' >&2
  exit 1
fi

if [[ "${SNIPER_DEPLOY_RUN_NO_TELEGRAM:-0}" == "1" ]]; then
  grvt_replay_acceptance="${SNIPER_DEPLOY_RUN_GRVT_REPLAY_ACCEPTANCE:-0}"
  if [[ "$grvt_replay_acceptance" != "0" && "$grvt_replay_acceptance" != "1" ]]; then
    printf '%s\n' 'remote_no_telegram_cycle=fail invalid_grvt_replay_acceptance_flag=1' >&2
    exit 64
  fi
  heartbeat_command="cd $remote_dir_quoted && python3 -c 'import json; print(json.load(open(\"output/runtime_health/last_cycle.json\")).get(\"generated_at\", \"\"))'"
  health_status_command="cd $remote_dir_quoted && python3 -c 'import json; print(json.load(open(\"output/runtime_health/last_cycle.json\")).get(\"status\", \"\"))'"
  replay_revision_command="cd $remote_dir_quoted && python3 -c 'from pathlib import Path; p=Path(\"output/grvt_liquidity_replay_acceptance/latest.json\"); print(p.stat().st_mtime_ns if p.exists() else \"\")'"
  heartbeat_before=$("${ssh_cmd[@]}" "$remote_target" "$heartbeat_command" 2>/dev/null) || {
    printf '%s\n' 'remote_no_telegram_cycle=fail' >&2
    exit 1
  }
  replay_revision_before=""
  if [[ "$grvt_replay_acceptance" == "1" ]]; then
    replay_revision_before=$("${ssh_cmd[@]}" "$remote_target" "$replay_revision_command" 2>/dev/null) || {
      printf '%s\n' 'remote_no_telegram_cycle=fail replay_probe_before_failed=1' >&2
      exit 1
    }
  fi
  project_only_cycle_limit="${SNIPER_DEPLOY_PROJECT_ONLY_CYCLES:-12}"
  if [[ ! "$project_only_cycle_limit" =~ ^[1-9][0-9]*$ ]] \
    || (( 10#$project_only_cycle_limit > 64 )); then
    printf '%s\n' 'remote_no_telegram_cycle=fail invalid_project_only_cycle_limit=1' >&2
    exit 64
  fi
  project_only_cycle_limit="$((10#$project_only_cycle_limit))"
  overlap_attempt_limit=12
  project_only_status=75
  project_only_attempt=0
  while (( project_only_status == 75 && project_only_attempt < overlap_attempt_limit )); do
    project_only_attempt=$((project_only_attempt + 1))
    project_only_status=0
    "${ssh_cmd[@]}" "$remote_target" \
      "cd $remote_dir_quoted && DISABLE_TELEGRAM=1 ALPHA_PROJECT_ONLY=1 ALPHA_PROJECT_ONLY_CYCLES=$project_only_cycle_limit SNIPER_PROJECT_ONLY_RUN_LOCK_FILE=/tmp/sniper_server_run_once.lock bash scripts/server_run_once.sh" \
      >/dev/null 2>&1 || project_only_status=$?
    if (( project_only_status == 75 && project_only_attempt < overlap_attempt_limit )); then
      sleep 10
    fi
  done
  if (( project_only_status == 75 )); then
    printf '%s\n' "remote_no_telegram_cycle=fail project_watch_overlap_lock_busy=1 attempts=$project_only_attempt" >&2
    exit 1
  fi
  if (( project_only_status != 0 )); then
    printf '%s\n' "remote_no_telegram_cycle=fail project_watch_incomplete=1 status=$project_only_status" >&2
    exit 1
  fi
  remote_cycle_status=75
  overlap_attempt=0
  while (( remote_cycle_status == 75 && overlap_attempt < overlap_attempt_limit )); do
    overlap_attempt=$((overlap_attempt + 1))
    remote_cycle_status=0
    "${ssh_cmd[@]}" "$remote_target" \
      "cd $remote_dir_quoted && DISABLE_TELEGRAM=1 RUN_GRVT_LIQUIDITY_REPLAY_ACCEPTANCE=$grvt_replay_acceptance SNIPER_OVERLAP_SKIP_EXIT_CODE=75 bash scripts/server_run_once.sh" \
      >/dev/null 2>&1 || remote_cycle_status=$?
    if (( remote_cycle_status == 75 && overlap_attempt < overlap_attempt_limit )); then
      sleep 10
    fi
  done
  if (( remote_cycle_status == 75 )); then
    printf '%s\n' "remote_no_telegram_cycle=fail overlap_lock_busy=1 attempts=$overlap_attempt" >&2
    exit 1
  fi
  heartbeat_after=$("${ssh_cmd[@]}" "$remote_target" "$heartbeat_command" 2>/dev/null) || {
    printf '%s\n' 'remote_no_telegram_cycle=fail' >&2
    exit 1
  }
  health_status_after=$("${ssh_cmd[@]}" "$remote_target" "$health_status_command" 2>/dev/null) || {
    printf '%s\n' 'remote_no_telegram_cycle=fail health_probe_failed=1' >&2
    exit 1
  }
  if [[ -z "$heartbeat_after" || "$heartbeat_after" == "$heartbeat_before" ]]; then
    printf '%s\n' "remote_no_telegram_cycle=fail heartbeat_unchanged=1 cycle_status=$remote_cycle_status" >&2
    exit 1
  fi
  if (( remote_cycle_status != 0 )); then
    printf '%s\n' "remote_no_telegram_cycle=fail heartbeat_unchanged=0 cycle_status=$remote_cycle_status" >&2
    exit 1
  fi
  if [[ "$health_status_after" != "healthy" ]]; then
    printf '%s\n' 'remote_no_telegram_cycle=fail runtime_status_unhealthy=1' >&2
    exit 1
  fi
  if [[ "$grvt_replay_acceptance" == "1" ]]; then
    replay_revision_after=$("${ssh_cmd[@]}" "$remote_target" "$replay_revision_command" 2>/dev/null) || {
      printf '%s\n' 'remote_no_telegram_cycle=fail replay_probe_after_failed=1' >&2
      exit 1
    }
    if [[ -z "$replay_revision_after" || "$replay_revision_after" == "$replay_revision_before" ]]; then
      printf '%s\n' 'remote_no_telegram_cycle=fail replay_artifact_not_refreshed=1' >&2
      exit 1
    fi
  fi
  printf '%s\n' "deploy=pass cron_install=pass remote_no_telegram_cycle=pass overlap_attempts=$overlap_attempt"
else
  printf '%s\n' 'deploy=pass cron_install=pass'
fi
