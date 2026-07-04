#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  printf "Usage: %s <evm_contract_address> [case_name]\n" "$0"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
SKILL_ALPHA_DIR="$HOME/.codex/skills/hertzflow/alpha"
CA_INPUT="$1"
CASE_NAME="${2:-$CA_INPUT}"
OUT_DIR="$ROOT_DIR/output/hertzflow_${CASE_NAME}"

if [[ ! "$CA_INPUT" =~ ^0x[0-9a-fA-F]{40}$ ]]; then
  printf "INSUFFICIENT_DATA: expected EVM CA as 0x + 40 hex chars\n"
  exit 1
fi

[ -f "$ENV_FILE" ] || {
  printf "INSUFFICIENT_DATA: missing .env.local\n"
  exit 1
}

[ -x "$PYTHON_BIN" ] || {
  printf "INSUFFICIENT_DATA: missing project .venv\n"
  exit 1
}

[ -d "$SKILL_ALPHA_DIR" ] || {
  printf "INSUFFICIENT_DATA: missing hertzflow skill alpha dir\n"
  exit 1
}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export PATH="$HOME/.local/bin:$PATH"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

mkdir -p "$OUT_DIR"
cd "$SKILL_ALPHA_DIR"

exec "$PYTHON_BIN" v06/forensic_pipeline.py "$CA_INPUT" --lang zh --out "$OUT_DIR/skeleton.json"
