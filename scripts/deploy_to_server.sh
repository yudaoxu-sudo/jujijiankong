#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

server="${SNIPER_DEPLOY_TARGET:-ubuntu@43.156.45.133:/home/ubuntu/sniper/}"
ssh_cmd=(
  ssh
  -i .deploy/sniper_server_ed25519
  -o UserKnownHostsFile=.deploy/known_hosts
  -o StrictHostKeyChecking=yes
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
  if ! "${ssh_cmd[@]}" "$remote_target" \
    "cd $remote_dir_quoted && DISABLE_TELEGRAM=1 bash scripts/server_run_once.sh" \
    >/dev/null 2>&1; then
    printf '%s\n' 'remote_no_telegram_cycle=fail' >&2
    exit 1
  fi
  printf '%s\n' 'deploy=pass cron_install=pass remote_no_telegram_cycle=pass'
else
  printf '%s\n' 'deploy=pass cron_install=pass'
fi
