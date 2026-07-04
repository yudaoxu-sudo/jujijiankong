#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
SURF_BIN="${SURF_BIN:-$HOME/.local/bin/surf}"
SKILL_DIR="$HOME/.codex/skills/hertzflow"
ENV_FILE="$ROOT_DIR/.env.local"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

fail() {
  printf "INSUFFICIENT_DATA: %s\n" "$1"
  exit 1
}

[ -d "$SKILL_DIR" ] || fail "HertzFlow skill missing. Install with Codex skill-installer."
[ -x "$PYTHON_BIN" ] || fail "project .venv missing. Run setup first."
command -v jq >/dev/null 2>&1 || fail "jq missing."
[ -x "$SURF_BIN" ] || fail "surf CLI missing. Install Surf CLI first."

"$PYTHON_BIN" - <<'PY'
import jinja2
import yaml
print("python deps ok")
PY

"$SURF_BIN" --version
if [ "${SURF_API_KEY:-}" != "" ]; then
  printf "surf auth ok via SURF_API_KEY\n"
elif "$SURF_BIN" auth 2>&1 | grep -q "api-key: sk-"; then
  printf "surf auth ok\n"
else
  fail "Surf API key missing. Register at http://agents.asksurf.ai/?coupon=hertzflow, then run scripts/setup_surf_key.sh."
fi

printf "HertzFlow preflight ok\n"
