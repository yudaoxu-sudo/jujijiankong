#!/usr/bin/env bash
set -euo pipefail

SURF_BIN="${SURF_BIN:-$HOME/.local/bin/surf}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"

[ -x "$SURF_BIN" ] || {
  printf "surf CLI missing. Install Surf CLI first.\n"
  exit 1
}

printf "Paste Surf API key. It should start with sk-. Input is hidden.\n"
printf "> "
IFS= read -rs SURF_KEY
printf "\n"

case "$SURF_KEY" in
  sk-*) ;;
  *)
    printf "Invalid format. Expected a key starting with sk-.\n"
    exit 1
    ;;
esac

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

tmp_file="${ENV_FILE}.tmp"
if grep -q "^SURF_API_KEY=" "$ENV_FILE"; then
  awk -v v="$SURF_KEY" 'BEGIN{done=0} /^SURF_API_KEY=/ {print "SURF_API_KEY=" v; done=1; next} {print} END{if(done==0) print "SURF_API_KEY=" v}' "$ENV_FILE" > "$tmp_file"
  mv "$tmp_file" "$ENV_FILE"
else
  printf "SURF_API_KEY=%s\n" "$SURF_KEY" >> "$ENV_FILE"
fi

"$SURF_BIN" auth --api-key "$SURF_KEY" >/dev/null 2>&1 || true

if SURF_API_KEY="$SURF_KEY" "$SURF_BIN" auth 2>&1 | grep -q "api-key: sk-"; then
  printf "Surf authenticated.\n"
else
  printf "Surf authentication failed.\n"
  exit 1
fi
