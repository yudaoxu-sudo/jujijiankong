#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
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
VALID_SOURCE_AUTHORITIES = {"social_discovery", "context_only"}
PUBLIC_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
PUBLIC_TME_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def source_policy(source: dict[str, Any]) -> dict[str, Any]:
    evidence_layer = source.get("evidence_layer")
    authority = source.get("authority")
    context_only = source.get("context_only")
    if evidence_layer != "social":
        raise ValueError("Telegram user source evidence_layer must be social")
    if authority not in VALID_SOURCE_AUTHORITIES:
        raise ValueError(f"invalid Telegram user source authority: {authority!r}")
    if not isinstance(context_only, bool):
        raise ValueError("Telegram user source context_only must be boolean")
    if context_only != (authority == "context_only"):
        raise ValueError("Telegram user source authority/context_only mismatch")
    return {
        "evidence_layer": evidence_layer,
        "authority": authority,
        "context_only": context_only,
    }


def validate_source(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError("Telegram user source must be an object")
    name = source.get("name")
    entity = source.get("entity")
    state_key = source.get("state_key")
    enabled = source.get("enabled")
    limit = source.get("limit")
    bootstrap_on_first_seen = source.get("bootstrap_on_first_seen")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Telegram user source name is required")
    try:
        normalize_entity(entity)
    except ValueError as exc:
        raise ValueError(
            f"Telegram user source {name!r} entity must be a stable numeric peer id or public username"
        ) from exc
    if not isinstance(state_key, str) or not state_key.strip():
        raise ValueError(f"Telegram user source {name!r} requires a stable state_key")
    if not isinstance(enabled, bool):
        raise ValueError(f"Telegram user source {name!r} enabled must be boolean")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError(f"Telegram user source {name!r} limit must be an integer from 1 to 100")
    if not isinstance(bootstrap_on_first_seen, bool):
        raise ValueError(f"Telegram user source {name!r} bootstrap_on_first_seen must be boolean")
    source_policy(source)
    return source


def enabled_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("Telegram user source config sources must be a list")
    validated = [validate_source(source) for source in sources]
    state_keys = [source_key(source) for source in validated]
    entities = [entity_key(source.get("entity")) for source in validated]
    if len(state_keys) != len(set(state_keys)):
        raise ValueError("Telegram user source state_key values must be unique")
    if len(entities) != len(set(entities)):
        raise ValueError("Telegram user source entity values must be unique")
    return [source for source in validated if source["enabled"]]


def normalize_entity(entity: Any) -> Any:
    if isinstance(entity, bool):
        raise ValueError("invalid Telegram entity")
    if isinstance(entity, int):
        return entity
    text = str(entity or "").strip()
    if text.lstrip("-").isdigit():
        return int(text)
    public_match = PUBLIC_TME_RE.fullmatch(text)
    if public_match:
        return public_match.group(1)
    if text.startswith("@"):
        text = text[1:]
    if PUBLIC_USERNAME_RE.fullmatch(text):
        return text
    raise ValueError("invalid Telegram entity")


def entity_key(entity: Any) -> str:
    normalized = normalize_entity(entity)
    if isinstance(normalized, int):
        return f"id:{normalized}"
    return f"username:{normalized.casefold()}"


def message_text(message: Any) -> str:
    return str(getattr(message, "message", "") or "").strip()


def message_link(source: dict[str, Any], message_id: int) -> str:
    try:
        entity = normalize_entity(source.get("entity"))
    except ValueError:
        return ""
    if isinstance(entity, str):
        return f"https://t.me/{entity}/{message_id}"
    return ""


def source_key(source: dict[str, Any]) -> str:
    return str(source.get("state_key") or source.get("name") or source.get("entity") or "").strip()


def source_allows_auto_apply(source: dict[str, Any]) -> bool:
    return not source_policy(source)["context_only"]


def source_allows_secondary_push(source: dict[str, Any]) -> bool:
    return not source_policy(source)["context_only"]


def save_signal(source: dict[str, Any], message: Any, text: str, policy: dict[str, Any]) -> Path:
    target_dir = OUT_DIR / "context_raw" if policy["context_only"] else SIGNAL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    key = safe_name(source_key(source))
    message_id = int(getattr(message, "id", 0))
    path = target_dir / f"{key}_{message_id}.txt"
    header = [
        f"source_name: {source.get('name', '')}",
        f"source_entity: {source.get('entity', '')}",
        f"source_state_key: {source_key(source)}",
        f"source_evidence_layer: {policy['evidence_layer']}",
        f"source_authority: {policy['authority']}",
        f"source_context_only: {str(policy['context_only']).lower()}",
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE_PATH, {"sources": {}})
    try:
        sources = enabled_sources(config)
    except ValueError as exc:
        write_status_preserving_sources(state, "failed", str(exc))
        print(STATE_PATH)
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 1
    selected_key = getattr(args, "source_key", None)
    if selected_key:
        sources = [source for source in sources if source_key(source) == selected_key]
        if not sources:
            write_status_preserving_sources(state, "failed", f"source_key not found: {selected_key}")
            print(STATE_PATH)
            print(json.dumps({"status": "failed", "reason": f"source_key not found: {selected_key}"}, ensure_ascii=False))
            return 1
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
            policy = source_policy(source)
            entity_value = normalize_entity(source.get("entity"))
            saved_source_state = source_state.get(key, {})
            has_cursor = isinstance(saved_source_state, dict) and "last_id" in saved_source_state
            last_id = int(saved_source_state.get("last_id", 0) or 0) if has_cursor else 0
            bootstrap_source = bool(args.bootstrap or (source["bootstrap_on_first_seen"] and not has_cursor))
            limit = int(source.get("limit", 30))
            try:
                entity = await client.get_entity(entity_value)
                messages = []
                async for message in client.iter_messages(entity, limit=limit, min_id=0 if bootstrap_source else last_id):
                    messages.append(message)
                messages = sorted(messages, key=lambda item: int(getattr(item, "id", 0)))
            except Exception as exc:
                processed.append({"source": key, "status": "failed", "error": str(exc)})
                continue

            if bootstrap_source:
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
                signal_path = save_signal(source, message, text, policy)
                parsed = parse_signal(text, signal_path)
                parsed = maybe_enrich_chain(parsed)
                parsed = apply_token_aliases(parsed)
                parsed["source_policy"] = policy
                if policy["context_only"]:
                    parsed["project_registry"] = {"status": "context_only_archived", "added": []}
                else:
                    parsed["project_registry"] = merge_signal(
                        parsed,
                        {
                            "collector": "telegram_user",
                            "source_name": source.get("name", ""),
                            "source_entity": source.get("entity", ""),
                            "state_key": key,
                            **policy,
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
                applied = source_allows_auto_apply(source) and should_auto_apply(parsed)
                if applied:
                    apply_proposals(parsed)
                target_chat = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
                token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                pushed = False
                if source_allows_secondary_push(source) and target_chat and token and should_push(parsed, False):
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
    parser.add_argument("--source-key", help="Limit this run to one configured stable state_key.")
    args = parser.parse_args()
    return asyncio.run(collect(args))


if __name__ == "__main__":
    raise SystemExit(main())
