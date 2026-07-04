#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

set_key() {
  local key_name="$1"
  local prompt="$2"
  printf "%s\n" "$prompt"
  printf "> "
  IFS= read -rs value
  printf "\n"
  if [ -z "$value" ]; then
    printf "skip %s\n" "$key_name"
    return
  fi
  if grep -q "^${key_name}=" "$ENV_FILE"; then
    tmp_file="${ENV_FILE}.tmp"
    awk -v k="$key_name" -v v="$value" 'BEGIN{done=0} $0 ~ "^" k "=" {print k "=" v; done=1; next} {print} END{if(done==0) print k "=" v}' "$ENV_FILE" > "$tmp_file"
    mv "$tmp_file" "$ENV_FILE"
  else
    printf "%s=%s\n" "$key_name" "$value" >> "$ENV_FILE"
  fi
  printf "saved %s\n" "$key_name"
}

printf "This writes local API keys to %s\n" "$ENV_FILE"
printf "This file is ignored by git.\n\n"

set_key "NODEREAL_API_KEY" "Paste NodeReal / MegaNode API key. Press Enter to skip."
set_key "TELEGRAM_BOT_TOKEN" "Paste Telegram bot token. Press Enter to skip."
set_key "TELEGRAM_CHAT_ID" "Paste Telegram chat id. Press Enter to skip."
set_key "ETHERSCAN_API_KEY" "Paste Etherscan API key. Press Enter to skip."

printf "\nDone. Current saved key names:\n"
cut -d= -f1 "$ENV_FILE" | sed '/^$/d'
