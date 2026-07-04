#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "telegram_user_sources.json"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": str(date.today()), "sources": []}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"Config must be a JSON object: {path}")
    sources = data.setdefault("sources", [])
    if not isinstance(sources, list):
        raise SystemExit(f"Config sources must be a list: {path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Add or update one Telegram user API source.")
    parser.add_argument("name", help="Human readable source name, for example: alpha news")
    parser.add_argument("entity", help="Telegram entity: t.me link, @username, channel id, or group id")
    parser.add_argument("--limit", type=int, default=30, help="Messages to scan per run")
    parser.add_argument("--disabled", action="store_true", help="Add the source with enabled=false")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    data = load_config(args.config)
    data["generated_at"] = str(date.today())

    entity_text = args.entity.strip()
    entity: str | int = int(entity_text) if entity_text.lstrip("-").isdigit() else entity_text
    if not entity:
        raise SystemExit("entity is required")

    updated = False
    for source in data["sources"]:
        if not isinstance(source, dict):
            continue
        if str(source.get("entity")) == str(entity) or source.get("name") == args.name:
            source.update(
                {
                    "name": args.name,
                    "entity": entity,
                    "enabled": not args.disabled,
                    "limit": args.limit,
                }
            )
            updated = True
            break

    if not updated:
        data["sources"].append(
            {
                "name": args.name,
                "entity": entity,
                "enabled": not args.disabled,
                "limit": args.limit,
            }
        )

    args.config.parent.mkdir(parents=True, exist_ok=True)
    with args.config.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(args.config)
    print(json.dumps({"source_count": len(data["sources"]), "updated": updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
