#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_prelaunch_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
UTC8 = timezone(timedelta(hours=8))
TELEGRAM_LIMIT = 3200


def now_utc() -> datetime:
    override = os.environ.get("ALPHA_PRELAUNCH_NOW_UTC", "").strip()
    if override:
        return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_known_time(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("time") or value.get("startedTime") or value.get("start_time")
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("UTC+8", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC8).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def phase_for_delta(delta: timedelta) -> str:
    seconds = delta.total_seconds()
    if seconds < -1800:
        return "expired"
    if seconds <= 0:
        return "LIVE_WINDOW"
    minutes = seconds / 60
    if minutes <= 30:
        return "T_MINUS_30M"
    if minutes <= 120:
        return "T_MINUS_2H"
    if minutes <= 360:
        return "T_MINUS_6H"
    if minutes <= 1440:
        return "T_MINUS_24H"
    return "T_MINUS_48H"


def phase_action(phase: str) -> str:
    actions = {
        "T_MINUS_48H": "进入预备观察；确认官方合约、活动分发、池子参数",
        "T_MINUS_24H": "进入上线前监控；重点看是否追加池子、桥、交易所活动",
        "T_MINUS_6H": "进入冲刺观察；准备开盘块、bribe、首批买入和承接验证",
        "T_MINUS_2H": "开盘前严密盯盘；未见真实加池和首批有效买入前不追",
        "T_MINUS_30M": "进入临战窗口；只接受链上强证据，禁止凭预期追高",
        "LIVE_WINDOW": "开盘窗口；看首块顺序、有效买入、出货和承接",
    }
    return actions.get(phase, "观察")


def short_addr(value: str) -> str:
    if len(value or "") <= 14:
        return value or "-"
    return value[:8] + "..." + value[-6:]


def display_name(item: dict[str, Any]) -> str:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    project = str(facts.get("project_name") or "").strip()
    raw_symbol = str(facts.get("raw_symbol") or item.get("symbol") or "").strip()
    display = str(facts.get("display_symbol") or "").strip()
    if display and raw_symbol and display.upper() != raw_symbol.upper():
        symbol = f"{display}/{raw_symbol}"
    else:
        symbol = raw_symbol or str(item.get("symbol") or "UNKNOWN")
    return f"{symbol} · {project}" if project else symbol


def first_contract(item: dict[str, Any]) -> dict[str, str]:
    for row in item.get("contracts", []):
        if isinstance(row, dict) and row.get("address"):
            return {"chain": str(row.get("chain") or ""), "address": str(row.get("address") or "")}
    return {"chain": "", "address": ""}


def build_events(config: dict[str, Any], current: datetime) -> list[dict[str, Any]]:
    lookahead = timedelta(hours=float(os.environ.get("ALPHA_PRELAUNCH_LOOKAHEAD_HOURS", "48")))
    events: list[dict[str, Any]] = []
    for item in config.get("items", []):
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority") or "")
        if not priority.startswith(("P0", "P1")):
            continue
        known_times = item.get("known_times") or item.get("times") or []
        for known in known_times:
            start = parse_known_time(known)
            if not start:
                continue
            delta = start - current
            phase = phase_for_delta(delta)
            if phase == "expired" or delta > lookahead:
                continue
            contract = first_contract(item)
            events.append(
                {
                    "symbol": str(item.get("symbol") or "UNKNOWN"),
                    "display_name": display_name(item),
                    "priority": priority,
                    "phase": phase,
                    "action": phase_action(phase),
                    "time_utc8": start.astimezone(UTC8).strftime("%Y-%m-%d %H:%M"),
                    "minutes_to_start": int(delta.total_seconds() // 60),
                    "chain": contract.get("chain") or item.get("chain") or "",
                    "contract": contract.get("address") or "",
                    "required_checks": item.get("required_checks", [])[:6],
                    "alert_key": alert_key(item, start, phase),
                }
            )
    return sorted(events, key=lambda row: (row["minutes_to_start"], row["symbol"]))


def alert_key(item: dict[str, Any], start: datetime, phase: str) -> str:
    contract = first_contract(item).get("address") or ""
    return "|".join([str(item.get("symbol") or "UNKNOWN").upper(), contract.lower(), start.isoformat(), phase])


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Alpha Prelaunch Watch",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- events: `{len(payload.get('events', []))}`",
        "",
    ]
    if not payload.get("events"):
        lines.append("- No upcoming P0/P1 launch windows in configured lookahead.")
        return "\n".join(lines)
    lines.extend(["| Phase | Time UTC+8 | Project | Action | Contract |", "| --- | --- | --- | --- | --- |"])
    for event in payload.get("events", []):
        lines.append(
            f"| {event.get('phase')} | {event.get('time_utc8')} | {event.get('display_name')} | "
            f"{event.get('action')} | `{short_addr(event.get('contract', ''))}` |"
        )
    return "\n".join(lines)


def telegram_text(new_events: list[dict[str, Any]]) -> str:
    lines = ["Alpha 开盘时间提醒", ""]
    for event in new_events[:8]:
        lines.extend(
            [
                f"{event.get('display_name')} [{event.get('phase')}]",
                f"时间: {event.get('time_utc8')} UTC+8",
                f"动作: {event.get('action')}",
                "重点: 官方合约、加池/开盘块、首批有效买入、bribe、活动分发、承接",
                "",
            ]
        )
    return "\n".join(lines).strip()[:TELEGRAM_LIMIT]


def send_telegram(text: str) -> dict[str, Any]:
    if os.environ.get("ALPHA_PRELAUNCH_TELEGRAM", "1") == "0" or os.environ.get("DISABLE_TELEGRAM") == "1":
        return {"ok": True, "disabled": True}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "reason": "missing telegram token/chat"}
    payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    current = now_utc()
    config = read_json(CONFIG_PATH, {"items": []})
    events = build_events(config, current)
    seen = read_json(SEEN_PATH, {"keys": []})
    seen_keys = set(seen.get("keys", []))
    new_events = [event for event in events if event["alert_key"] not in seen_keys]

    push_result: dict[str, Any] = {"ok": True, "skipped": True}
    if new_events:
        push_result = send_telegram(telegram_text(new_events))
        if push_result.get("ok") and not push_result.get("disabled"):
            seen_keys.update(event["alert_key"] for event in new_events)
            write_json(SEEN_PATH, {"updated_at": now_iso(), "keys": sorted(seen_keys)[-500:]})

    payload = {
        "generated_at": now_iso(),
        "lookahead_hours": os.environ.get("ALPHA_PRELAUNCH_LOOKAHEAD_HOURS", "48"),
        "events": events,
        "new_event_count": len(new_events),
        "push_result": push_result,
    }
    write_json(LATEST_PATH, payload)
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
    print(REPORT_PATH)
    print(json.dumps({"events": len(events), "new_events": len(new_events), "push": push_result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
