from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_LABELS_PATH = ROOT / "config" / "global_address_labels.json"


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_address(value: str | None) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def global_address_labels(chain: str) -> dict[str, dict[str, Any]]:
    payload = read_json(GLOBAL_LABELS_PATH, {"chains": {}})
    rows: dict[str, dict[str, Any]] = {}
    for row in payload.get("chains", {}).get(chain.lower(), []):
        address = norm(row.get("address"))
        if is_address(address):
            rows[address] = dict(row, address=address)
    return rows


def global_address_label(chain: str, address: str) -> dict[str, Any] | None:
    return global_address_labels(chain).get(norm(address))

