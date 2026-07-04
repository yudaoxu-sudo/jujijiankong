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
