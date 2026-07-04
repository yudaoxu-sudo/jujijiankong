#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  printf "Usage: %s <ticker-or-token-name>\n" "$0"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"
SURF_BIN="${SURF_BIN:-$HOME/.local/bin/surf}"
QUERY="$1"

[ -f "$ENV_FILE" ] || {
  printf "INSUFFICIENT_DATA: missing .env.local\n"
  exit 1
}

[ -x "$SURF_BIN" ] || {
  printf "INSUFFICIENT_DATA: missing surf CLI\n"
  exit 1
}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

exec "$SURF_BIN" search-token --q "$QUERY" --json
