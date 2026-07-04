#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_alpha_signal import apply_proposals, parse_signal, render_markdown, write_json
from scripts.telegram_signal_collector import analysis_message, maybe_enrich_chain, send_message, should_ignore, should_push
from sniper_engine.project_registry import merge_signal
from sniper_engine.token_aliases import apply_token_aliases


CONFIG_PATH = ROOT / "config" / "telegram_user_sources.json"
STATE_PATH = ROOT / "output" / "telegram_user_signals" / "state.json"
OUT_DIR = ROOT / "output" / "telegram_user_signals"
SIGNAL_DIR = ROOT / "input" / "signals" / "telegram_user"
DEFAULT_SESSION = ROOT / ".secrets" / "telegram_user.session"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def enabled_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in config.get("sources", []) if source.get("enabled", True)]


def normalize_entity(entity: Any) -> Any:
    if isinstance(entity, int):
        return entity
    text = str(entity or "").strip()
    if text.startswith("https://t.me/"):
        text = text.rstrip("/").split("/")[-1]
    if text.startswith("t.me/"):
        text = text.rstrip("/").split("/")[-1]
    if text.startswith("@"):
        text = text[1:]
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def message_text(message: Any) -> str:
    return str(getattr(message, "message", "") or "").strip()


def message_link(source: dict[str, Any], message_id: int) -> str:
    entity = str(source.get("entity", "")).strip()
    if entity.startswith("https://t.me/"):
        return entity.rstrip("/") + f"/{message_id}"
    if entity.startswith("@"):
        return f"https://t.me/{entity[1:]}/{message_id}"
    if entity and not entity.startswith("-") and not entity.isdigit():
        return f"https://t.me/{entity}/{message_id}"
    return ""


def source_key(source: dict[str, Any]) -> str:
    return str(source.get("name") or source.get("entity") or "").strip()


def save_signal(source: dict[str, Any], message: Any, text: str) -> Path:
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    key = safe_name(source_key(source))
    message_id = int(getattr(message, "id", 0))
    path = SIGNAL_DIR / f"{key}_{message_id}.txt"
    header = [
        f"source_name: {source.get('name', '')}",
        f"source_entity: {source.get('entity', '')}",
        f"telegram_message_id: {message_id}",
        f"telegram_message_link: {message_link(source, message_id)}",
        f"date_utc: {now_iso()}",
        "",
    ]
    path.write_text("\n".join(header) + text + "\n", encoding="utf-8")
    return path


def safe_name(value: str) -> str:
    out = []
    for ch in value:
        out.append(ch if ch.isalnum() else "_")
    text = "".join(out).strip("_")
    return text[:80] or "source"


def should_auto_apply(parsed: dict[str, Any]) -> bool:
    if os.environ.get("SIGNAL_AUTO_APPLY", "0") != "1":
        return False
    priority = parsed.get("priority")
    if priority not in {"P0_DEEP_REVIEW", "P1_MONITOR"}:
        return False
    if not parsed.get("symbol"):
        return False
    return bool(parsed.get("addresses") or parsed.get("txs") or parsed.get("prediction_urls"))


def write_status_preserving_sources(state: dict[str, Any], status: str, reason: str) -> None:
    payload = dict(state or {})
    payload.update({"updated_at": now_iso(), "status": status, "reason": reason, "processed": []})
    payload.setdefault("sources", {})
    write_json(STATE_PATH, payload)


async def collect(args: argparse.Namespace) -> int:
    config = read_json(CONFIG_PATH, {"sources": []})
    sources = enabled_sources(config)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE_PATH, {"sources": {}})
    if not sources:
        write_status_preserving_sources(state, "skipped", "no enabled sources")
        print(STATE_PATH)
        print(json.dumps({"status": "skipped", "reason": "no enabled sources"}, ensure_ascii=False))
        return 0

    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        write_status_preserving_sources(state, "skipped", "missing TELEGRAM_API_ID or TELEGRAM_API_HASH")
        print(STATE_PATH)
        print(json.dumps({"status": "skipped", "reason": "missing TELEGRAM_API_ID or TELEGRAM_API_HASH"}, ensure_ascii=False))
        return 0

    try:
        from telethon import TelegramClient
    except Exception as exc:
        write_status_preserving_sources(state, "failed", f"missing telethon: {exc}")
        print(STATE_PATH)
        return 0

    session_path = Path(os.environ.get("TELEGRAM_USER_SESSION", str(DEFAULT_SESSION)))
    session_path.parent.mkdir(parents=True, exist_ok=True)
    source_state = state.get("sources", {})
    processed = []

    async with TelegramClient(str(session_path), int(api_id), api_hash) as client:
        if not await client.is_user_authorized():
            write_status_preserving_sources(state, "skipped", "telegram user session is not authorized")
            print(STATE_PATH)
            print(json.dumps({"status": "skipped", "reason": "telegram user session is not authorized"}, ensure_ascii=False))
            return 0

        for source in sources:
            key = source_key(source)
            entity_value = normalize_entity(source.get("entity"))
            last_id = int(source_state.get(key, {}).get("last_id", 0) or 0)
            limit = int(source.get("limit", 30))
            try:
                entity = await client.get_entity(entity_value)
                messages = []
                async for message in client.iter_messages(entity, limit=limit, min_id=0 if args.bootstrap else last_id):
                    messages.append(message)
                messages = sorted(messages, key=lambda item: int(getattr(item, "id", 0)))
            except Exception as exc:
                processed.append({"source": key, "status": "failed", "error": str(exc)})
                continue

            if args.bootstrap:
                max_id = max([last_id] + [int(getattr(message, "id", 0)) for message in messages])
                source_state[key] = {"last_id": max_id, "updated_at": now_iso(), "bootstrap": True}
                processed.append({"source": key, "status": "bootstrap", "seen": len(messages), "last_id": max_id})
                continue

            source_processed = 0
            max_id = last_id
            for message in messages:
                msg_id = int(getattr(message, "id", 0))
                max_id = max(max_id, msg_id)
                text = message_text(message)
                if should_ignore(text):
                    continue
                signal_path = save_signal(source, message, text)
                parsed = parse_signal(text, signal_path)
                parsed = maybe_enrich_chain(parsed)
                parsed = apply_token_aliases(parsed)
                parsed["project_registry"] = merge_signal(
                    parsed,
                    {
                        "collector": "telegram_user",
                        "source_name": source.get("name", ""),
                        "source_entity": source.get("entity", ""),
                        "telegram_message_id": msg_id,
                        "telegram_message_link": message_link(source, msg_id),
                        "source_path": str(signal_path),
                    },
                )
                if not parsed.get("symbol") and parsed["project_registry"].get("symbol"):
                    parsed["symbol"] = parsed["project_registry"]["symbol"]
                    parsed["symbols"] = [parsed["symbol"]]
                stem = signal_path.stem
                write_json(OUT_DIR / f"{stem}.json", parsed)
                (OUT_DIR / f"{stem}.md").write_text(render_markdown(parsed), encoding="utf-8")
                applied = should_auto_apply(parsed)
                if applied:
                    apply_proposals(parsed)
                target_chat = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
                token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                pushed = False
                if target_chat and token and should_push(parsed, False):
                    result = send_message(token, target_chat, analysis_message(parsed, applied))
                    pushed = bool(result.get("ok") and not result.get("disabled"))
                source_processed += 1
                processed.append(
                    {
                        "source": key,
                        "status": "signal",
                        "message_id": msg_id,
                        "priority": parsed.get("priority"),
                        "registry_status": parsed.get("project_registry", {}).get("status"),
                        "registry_added": parsed.get("project_registry", {}).get("added", []),
                        "pushed": pushed,
                    }
                )
            source_state[key] = {"last_id": max_id, "updated_at": now_iso()}
            processed.append({"source": key, "status": "processed", "seen": len(messages), "signals": source_processed, "last_id": max_id})

    write_json(STATE_PATH, {"updated_at": now_iso(), "status": "ok", "sources": source_state, "processed": processed[-200:]})
    print(STATE_PATH)
    print(json.dumps({"status": "ok", "processed": processed}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect signal-like messages from Telegram channels visible to a user session.")
    parser.add_argument("--bootstrap", action="store_true", help="Record latest message ids without processing old messages.")
    args = parser.parse_args()
    return asyncio.run(collect(args))


if __name__ == "__main__":
    raise SystemExit(main())
