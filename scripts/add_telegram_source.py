#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.telegram_user_signal_collector import enabled_sources, normalize_entity


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
    parser.add_argument("--state-key", help="Stable state key used for per-source offsets")
    parser.add_argument(
        "--allow-secondary-actions",
        action="store_true",
        help="Allow this social source to auto-apply or send secondary analysis pushes",
    )
    parser.add_argument("--disabled", action="store_true", help="Add the source with enabled=false")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    data = load_config(args.config)
    data["generated_at"] = str(date.today())

    entity_text = args.entity.strip()
    try:
        entity = normalize_entity(entity_text)
    except ValueError as exc:
        raise SystemExit("Persist only a stable numeric Telegram peer id or public username.") from exc
    if not 1 <= args.limit <= 100:
        raise SystemExit("limit must be from 1 to 100")

    updated = False
    for source in data["sources"]:
        if not isinstance(source, dict):
            continue
        if str(source.get("entity")) == str(entity) or source.get("name") == args.name:
            state_key = (args.state_key or source.get("state_key") or source.get("name") or args.name).strip()
            source.update(
                {
                    "name": args.name,
                    "entity": entity,
                    "enabled": not args.disabled,
                    "limit": args.limit,
                    "bootstrap_on_first_seen": True,
                    "state_key": state_key,
                    "evidence_layer": "social",
                    "authority": "social_discovery" if args.allow_secondary_actions else "context_only",
                    "context_only": not args.allow_secondary_actions,
                }
            )
            updated = True
            break

    if not updated:
        state_key = (args.state_key or args.name).strip()
        data["sources"].append(
            {
                "name": args.name,
                "entity": entity,
                "enabled": not args.disabled,
                "limit": args.limit,
                "bootstrap_on_first_seen": True,
                "state_key": state_key,
                "evidence_layer": "social",
                "authority": "social_discovery" if args.allow_secondary_actions else "context_only",
                "context_only": not args.allow_secondary_actions,
            }
        )

    enabled_sources(data)
    args.config.parent.mkdir(parents=True, exist_ok=True)
    with args.config.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(args.config)
    print(json.dumps({"source_count": len(data["sources"]), "updated": updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
