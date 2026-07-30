#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.alpha_prelaunch_research import (
    normalize_prelaunch_research as validate_prelaunch_research,
)


CONFIG_PATH = Path(
    os.environ.get("ALPHA_WATCHLIST_PATH", ROOT / "config" / "current_alpha_watchlist.json")
)
OUT_DIR = ROOT / "output" / "alpha_prelaunch_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
UTC8 = timezone(timedelta(hours=8))
TELEGRAM_LIMIT = 4000
RESEARCH_SCHEMA_VERSION = "alpha_prelaunch_research.v1"
FINGERPRINT_IGNORED_KEYS = {
    "as_of",
    "fetched_at",
    "generated_at",
    "last_checked_at",
    "observed_at",
    "research_fingerprint",
    "updated_at",
}
REQUIRED_RESEARCH_SECTIONS = (
    ("evidence",),
    ("timeline",),
    ("pool", "segments"),
    ("supply", "allocations"),
    ("supply", "cross_chain"),
    ("venues", "cex"),
    ("actors", "market_makers"),
    ("sniper_curve",),
    ("valuation", "anchors"),
    ("sell_pressure_scenarios",),
)
STATUS_BADGES = {
    "verified": "[V]",
    "unverified": "[U]",
    "conflicted": "[C]",
    "stale": "[S]",
}


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


def fingerprint_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: fingerprint_payload(item)
            for key, item in sorted(value.items())
            if key not in FINGERPRINT_IGNORED_KEYS
        }
    if isinstance(value, list):
        normalized = [fingerprint_payload(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def research_fingerprint(research: dict[str, Any]) -> str:
    payload = json.dumps(
        fingerprint_payload(research),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def has_conflicted_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        if str(value.get("verification_status") or "").lower() == "conflicted":
            return True
        return any(has_conflicted_evidence(item) for item in value.values())
    if isinstance(value, list):
        return any(has_conflicted_evidence(item) for item in value)
    return False


def prepare_prelaunch_research(item: dict[str, Any]) -> dict[str, Any]:
    supplied = item.get("prelaunch_research")
    has_supplied_research = isinstance(supplied, dict) and bool(supplied)
    research = copy.deepcopy(supplied) if has_supplied_research else {}
    if not has_supplied_research:
        research.update(
            {
                "schema_version": RESEARCH_SCHEMA_VERSION,
                "evidence": [],
                "conflicts": [],
            }
        )

    market_context = item.get("market_context")
    if isinstance(market_context, dict) and market_context:
        research.setdefault("market_context", copy.deepcopy(market_context))
    event_distributions = item.get("event_distributions")
    if isinstance(event_distributions, list) and event_distributions:
        research.setdefault(
            "event_distributions",
            copy.deepcopy(event_distributions),
        )
    if has_supplied_research:
        research = validate_prelaunch_research(research)

    missing = {
        str(value)
        for value in research.get("missing_fields", [])
        if str(value).strip()
    }
    if not has_supplied_research:
        missing.add("prelaunch_research")
    for path in REQUIRED_RESEARCH_SECTIONS:
        value = nested_value(research, path)
        if value in (None, "", [], {}):
            missing.add(".".join(path))

    conflicts = research.get("conflicts")
    blocked = bool(conflicts) or has_conflicted_evidence(research)
    supplied_status = str(research.get("research_status") or "").lower()
    if blocked or supplied_status in {"blocked", "conflicted"}:
        status = "blocked"
    elif missing or supplied_status == "partial":
        status = "partial"
    else:
        status = "ready"
    research["research_status"] = status
    research["missing_fields"] = sorted(missing)
    research["research_fingerprint"] = research_fingerprint(research)
    return research


def build_events(config: dict[str, Any], current: datetime) -> list[dict[str, Any]]:
    lookahead = timedelta(hours=float(os.environ.get("ALPHA_PRELAUNCH_LOOKAHEAD_HOURS", "48")))
    events: list[dict[str, Any]] = []
    for item in config.get("items", []):
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority") or "")
        if not priority.startswith(("P0", "P1")):
            continue
        research = prepare_prelaunch_research(item)
        fingerprint = str(research.get("research_fingerprint") or "")
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
                    "research_status": research.get(
                        "research_status",
                        "partial",
                    ),
                    "research_fingerprint": fingerprint,
                    "prelaunch_research": copy.deepcopy(research),
                    "alert_key": alert_key(
                        item,
                        start,
                        phase,
                        fingerprint,
                    ),
                }
            )
    return sorted(events, key=lambda row: (row["minutes_to_start"], row["symbol"]))


def alert_key(
    item: dict[str, Any],
    start: datetime,
    phase: str,
    fingerprint: str = "",
) -> str:
    contract = first_contract(item).get("address") or ""
    return "|".join(
        [
            str(item.get("symbol") or "UNKNOWN").upper(),
            contract.lower(),
            start.isoformat(),
            phase,
            fingerprint,
        ]
    )


def verification_badge(row: Any) -> str:
    status = (
        str(row.get("verification_status") or "unverified").lower()
        if isinstance(row, dict)
        else "unverified"
    )
    return STATUS_BADGES.get(status, "[U]")


def text_value(value: Any, fallback: str = "-") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def research_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def preview_rows(
    rows: list[dict[str, Any]],
    formatter: Any,
    *,
    limit: int | None = 2,
) -> str:
    if not rows:
        return "待补"
    selected = rows if limit is None else rows[:limit]
    rendered = [formatter(row) for row in selected]
    if limit is not None and len(rows) > limit:
        rendered.append(f"+{len(rows) - limit}")
    return "；".join(rendered)


def timeline_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("timeline"))

    def render(row: dict[str, Any]) -> str:
        event = text_value(
            row.get("event") or row.get("label") or row.get("kind")
        )
        event_time = text_value(row.get("time_utc8"), "")
        if not event_time and row.get("time_utc"):
            try:
                event_time = (
                    datetime.fromisoformat(
                        str(row["time_utc"]).replace("Z", "+00:00")
                    )
                    .astimezone(UTC8)
                    .strftime("%Y-%m-%d %H:%M UTC+8")
                )
            except ValueError:
                event_time = text_value(row.get("time_utc"))
        event_time = event_time or text_value(row.get("time"))
        anchor_status = text_value(
            row.get("runtime_anchor_status"),
            "",
        )
        anchor_suffix = f" {anchor_status}" if anchor_status else ""
        return (
            f"{event}@{event_time} {verification_badge(row)}"
            f"{anchor_suffix}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def pool_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    pool = research.get("pool")
    pool = pool if isinstance(pool, dict) else {}
    context = research.get("market_context")
    context = context if isinstance(context, dict) else {}
    segments = research_rows(pool.get("segments"))
    if not segments:
        segments = research_rows(context.get("pool_zones"))
    details: list[str] = []
    pair = pool.get("pair")
    price = pool.get("initial_price_usdt")
    if pair or price:
        details.append(
            f"{text_value(pair)} 初价{text_value(price)} "
            f"{verification_badge(pool)}"
        )

    def render(row: dict[str, Any]) -> str:
        kind = text_value(
            row.get("kind")
            or row.get("label")
            or row.get("position_id")
        )
        low = row.get("min_price_usdt")
        high = row.get("max_price_usdt")
        if low is not None or high is not None:
            price_range = f"{text_value(low)}-{text_value(high)}"
        else:
            price_range = text_value(
                row.get("price_usdt") or row.get("price")
            )
        amount = row.get("token_amount")
        suffix = f" token={amount}" if amount not in (None, "") else ""
        return (
            f"{kind} {price_range}{suffix} "
            f"{verification_badge(row)}"
        )

    if segments:
        details.append(
            preview_rows(
                segments,
                render,
                limit=2 if compact else None,
            )
        )
    return "；".join(details) if details else "待补"


def supply_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    supply = research.get("supply")
    supply = supply if isinstance(supply, dict) else {}
    allocations = research_rows(supply.get("allocations"))
    if not allocations:
        allocations = research_rows(research.get("event_distributions"))
    cross_chain = research_rows(supply.get("cross_chain"))

    def render_allocation(row: dict[str, Any]) -> str:
        role = text_value(
            row.get("role")
            or row.get("name")
            or row.get("label")
        )
        share = text_value(
            row.get("percent")
            or row.get("share_of_total")
            or row.get("token_amount")
        )
        return f"{role} {share} {verification_badge(row)}"

    def render_cross_chain(row: dict[str, Any]) -> str:
        chain = text_value(row.get("chain"))
        inventory = text_value(
            row.get("inventory")
            or row.get("inventory_amount")
            or (
                f"{row.get('inventory_percent')}%"
                if row.get("inventory_percent") not in (None, "")
                else ""
            )
            or row.get("token_amount")
        )
        bridge = text_value(
            row.get("bridge_state") or row.get("state")
        )
        return (
            f"{chain} 库存{inventory}/桥{bridge} "
            f"{verification_badge(row)}"
        )

    return (
        "分发 "
        + preview_rows(
            allocations,
            render_allocation,
            limit=2 if compact else None,
        )
        + "；跨链 "
        + preview_rows(
            cross_chain,
            render_cross_chain,
            limit=2 if compact else None,
        )
    )


def venue_actor_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    venues = research.get("venues")
    venues = venues if isinstance(venues, dict) else {}
    actors = research.get("actors")
    actors = actors if isinstance(actors, dict) else {}
    cex_rows = research_rows(venues.get("cex"))
    mm_rows = research_rows(actors.get("market_makers"))

    def render_cex(row: dict[str, Any]) -> str:
        venue = text_value(row.get("venue"))
        market = text_value(row.get("market"))
        deposit = text_value(
            row.get("deposit_state") or row.get("state")
        )
        return (
            f"{venue}/{market} 充值{deposit} "
            f"{verification_badge(row)}"
        )

    def render_mm(row: dict[str, Any]) -> str:
        identity = short_addr(
            text_value(row.get("address") or row.get("name"))
        )
        role = text_value(row.get("role"))
        return f"{identity} {role} {verification_badge(row)}"

    return (
        "CEX "
        + preview_rows(
            cex_rows,
            render_cex,
            limit=2 if compact else None,
        )
        + "；MM "
        + preview_rows(
            mm_rows,
            render_mm,
            limit=2 if compact else None,
        )
    )


def sniper_curve_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("sniper_curve"))
    if not rows:
        context = research.get("market_context")
        context = context if isinstance(context, dict) else {}
        rows = research_rows(context.get("sniper_curve"))

    def render(row: dict[str, Any]) -> str:
        pressure = text_value(
            row.get("buy_pressure_usdt") or row.get("snipe_amount_usdt")
        )
        average = text_value(
            row.get("avg_price_usdt") or row.get("average_price_usdt")
        )
        end = text_value(
            row.get("end_price_usdt") or row.get("price_usdt")
        )
        tokens = text_value(
            row.get("token_out") or row.get("token_amount")
        )
        return (
            f"{pressure}U→均{average}/末{end}/得{tokens} "
            f"{verification_badge(row)}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def opening_forecast_text(research: dict[str, Any]) -> str:
    forecast = research.get("opening_forecast")
    if not isinstance(forecast, dict) or not forecast:
        return "待补"
    parts = []
    for label, key, suffix in (
        ("买压", "buy_quote_usdt", "U"),
        ("bribe", "bribe_quote_usdt", "U"),
        ("预计均价", "predicted_fill_avg_usdt", "U"),
    ):
        value = forecast.get(key)
        if value not in (None, ""):
            parts.append(f"{label}{value}{suffix}")
    return (
        " / ".join(parts) + f" {verification_badge(forecast)}"
        if parts
        else "待补"
    )


def opening_actual_text(research: dict[str, Any]) -> str:
    actual = research.get("opening_actual")
    if not isinstance(actual, dict) or not actual:
        return "待开盘回执核验"
    parts = []
    for label, key, suffix in (
        ("实际买入", "buy_quote_usdt", "U"),
        ("实际bribe", "bribe_quote_usdt", "U"),
        ("实际均价", "weighted_avg_price_usdt", "U"),
        ("已确认卖出", "confirmed_sell_quote_usdt", "U"),
    ):
        value = actual.get(key)
        if value not in (None, ""):
            parts.append(f"{label}{value}{suffix}")
    return (
        " / ".join(parts) + f" {verification_badge(actual)}"
        if parts
        else "待开盘回执核验"
    )


def valuation_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    valuation = research.get("valuation")
    valuation = valuation if isinstance(valuation, dict) else {}
    anchors = research_rows(valuation.get("anchors"))
    predictions = research_rows(valuation.get("prediction_markets"))

    def render_anchor(row: dict[str, Any]) -> str:
        kind = text_value(row.get("kind") or row.get("source"))
        price = row.get("price_usdt")
        fdv = row.get("fdv_usd")
        price_or_fdv = row.get("price_or_fdv")
        values = []
        if price not in (None, ""):
            values.append(f"价{text_value(price)}")
        if fdv not in (None, ""):
            values.append(f"FDV{text_value(fdv)}")
        if not values and price_or_fdv not in (None, ""):
            values.append(text_value(price_or_fdv))
        return (
            f"{kind} {'/'.join(values) if values else '-'} "
            f"{verification_badge(row)}"
        )

    def render_prediction(row: dict[str, Any]) -> str:
        source = text_value(row.get("source"))
        target = text_value(row.get("target_fdv_usd"))
        probability = text_value(row.get("probability"))
        return (
            f"{source} FDV>{target}@{probability} "
            f"{verification_badge(row)}"
        )

    rendered = []
    if anchors:
        rendered.append(
            preview_rows(
                anchors,
                render_anchor,
                limit=2 if compact else None,
            )
        )
    if predictions:
        rendered.append(
            preview_rows(
                predictions,
                render_prediction,
                limit=2 if compact else None,
            )
        )
    if rendered:
        return "；".join(rendered)

    context = research.get("market_context")
    context = context if isinstance(context, dict) else {}
    legacy_parts = [
        f"{key}={context[key]}"
        for key in (
            "premarket_reference_price_usdt",
            "public_sale_price_usdt",
            "implied_fdv_usd",
        )
        if context.get(key) not in (None, "")
    ]
    return (
        "；".join(legacy_parts) + (" [U]" if legacy_parts else "")
        if legacy_parts
        else "待补"
    )


def sell_pressure_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("sell_pressure_scenarios"))

    def render(row: dict[str, Any]) -> str:
        scenario = text_value(row.get("scenario") or row.get("name"))
        effect = text_value(
            row.get("expected_effect") or row.get("summary")
        )
        action = text_value(row.get("action"))
        return (
            f"{scenario}: {effect} / {action} "
            f"{verification_badge(row)}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def evidence_text(research: dict[str, Any]) -> str:
    counts = {key: 0 for key in STATUS_BADGES}
    evidence = research_rows(research.get("evidence"))
    for row in evidence:
        status = str(
            row.get("verification_status") or "unverified"
        ).lower()
        counts[status if status in counts else "unverified"] += 1
    claim_conflicts = len(research.get("conflicts") or [])
    if has_conflicted_evidence(research):
        claim_conflicts = max(1, claim_conflicts)
    return (
        f"V{counts['verified']}/U{counts['unverified']}/"
        f"C{counts['conflicted']}/S{counts['stale']}/"
        f"ClaimConflict{claim_conflicts}"
    )


def markdown_value(value: Any, fallback: str = "-") -> str:
    return text_value(value, fallback).replace("\r", " ").replace("\n", " ")


def evidence_detail_lines(research: dict[str, Any]) -> list[str]:
    evidence = research_rows(research.get("evidence"))
    lines = ["### Evidence / Sources", ""]
    if not evidence:
        lines.append("- evidence: 待补")
        return lines
    for row in evidence:
        evidence_id = markdown_value(row.get("evidence_id"))
        kind = markdown_value(
            row.get("evidence_kind") or row.get("kind")
        )
        source_ref = markdown_value(
            row.get("source_ref")
            or row.get("source")
            or row.get("publisher")
        )
        source_url = markdown_value(
            row.get("url")
            or row.get("source_url")
            or row.get("link")
            or (
                row.get("source_ref")
                if str(row.get("source_ref") or "").startswith(
                    ("http://", "https://")
                )
                else ""
            ),
            "",
        )
        lines.extend(
            [
                (
                    f"- evidence_id: `{evidence_id}` · "
                    f"kind: {kind} · {verification_badge(row)}"
                ),
                f"  - source: {source_ref}",
                (
                    f"  - URL: <{source_url}>"
                    if source_url
                    else "  - URL: -"
                ),
            ]
        )
    return lines


def research_section_lines(
    event: dict[str, Any],
    *,
    compact: bool = True,
) -> list[str]:
    research = event.get("prelaunch_research")
    research = research if isinstance(research, dict) else {}
    missing = research.get("missing_fields")
    missing = missing if isinstance(missing, list) else []
    conflicts = research_rows(research.get("conflicts"))
    shown_conflicts = conflicts[:2] if compact else conflicts
    conflict_text = "；".join(
        (
            text_value(row.get("path"))
            + ": "
            + text_value(row.get("detail"))
        )
        for row in shown_conflicts
    )
    return [
        f"时间轴: {timeline_text(research, compact=compact)}",
        f"池子: {pool_text(research, compact=compact)}",
        f"筹码/跨链: {supply_text(research, compact=compact)}",
        f"CEX/MM: {venue_actor_text(research, compact=compact)}",
        f"狙击预测: {opening_forecast_text(research)}",
        f"开盘实绩: {opening_actual_text(research)}",
        f"狙击曲线: {sniper_curve_text(research, compact=compact)}",
        f"估值: {valuation_text(research, compact=compact)}",
        f"卖压情景: {sell_pressure_text(research, compact=compact)}",
        f"证据: {evidence_text(research)}",
        "缺口: " + ("、".join(str(value) for value in missing) if missing else "无"),
        "冲突: " + (conflict_text or "无"),
    ]


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
    for event in payload.get("events", []):
        research = event.get("prelaunch_research")
        research = research if isinstance(research, dict) else {}
        decision = research.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        lines.extend(
            [
                "",
                f"## {event.get('display_name')} · {event.get('phase')}",
                "",
                f"- research_status: `{event.get('research_status')}`",
                f"- research_fingerprint: `{event.get('research_fingerprint')}`",
                *[
                    f"- {line}"
                    for line in research_section_lines(
                        event,
                        compact=False,
                    )
                ],
                "",
                *evidence_detail_lines(research),
                (
                    "- 决策: "
                    + text_value(
                        decision.get("action") or event.get("action")
                    )
                    + "｜"
                    + text_value(
                        decision.get("summary") or event.get("action")
                    )
                ),
            ]
        )
    return "\n".join(lines)


def telegram_event_text(event: dict[str, Any]) -> str:
    lines = ["Alpha 盘前投研", ""]
    research = event.get("prelaunch_research")
    research = research if isinstance(research, dict) else {}
    decision = research.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    lines.extend(
        [
            (
                f"{event.get('display_name')} [{event.get('phase')}]"
                f"｜{event.get('research_status')}"
            ),
            f"时间: {event.get('time_utc8')} UTC+8",
            *research_section_lines(event),
            (
                "动作: "
                + text_value(
                    decision.get("action") or event.get("action")
                )
                + "｜"
                + text_value(
                    decision.get("summary") or event.get("action")
                )
            ),
        ]
    )
    return "\n".join(lines).strip()


def split_telegram_text(
    text: str,
    limit: int = TELEGRAM_LIMIT,
) -> list[str]:
    if limit <= 0:
        raise ValueError("Telegram message limit must be positive")
    remaining = text
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary <= 0:
            boundary = limit
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
        if remaining.startswith("\n"):
            remaining = remaining[1:]
    return chunks


def telegram_messages(new_events: list[dict[str, Any]]) -> list[str]:
    return [
        chunk
        for event in new_events
        for chunk in split_telegram_text(telegram_event_text(event))
    ]


def telegram_text(new_events: list[dict[str, Any]]) -> str:
    messages = telegram_messages(new_events)
    return messages[0] if messages else "Alpha 盘前投研"


def send_telegram(text: str) -> dict[str, Any]:
    if len(text) > TELEGRAM_LIMIT:
        return {
            "ok": False,
            "reason": "telegram_message_exceeds_limit",
        }
    if os.environ.get("ALPHA_PRELAUNCH_TELEGRAM", "1") == "0" or os.environ.get("DISABLE_TELEGRAM") == "1":
        return {"ok": True, "disabled": True}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "reason": "missing telegram token/chat"}
    payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"telegram_request_failed:{type(exc).__name__}",
        }


def write_seen_keys(seen_order: list[str]) -> None:
    write_json(
        SEEN_PATH,
        {
            "updated_at": now_iso(),
            "keys": seen_order[-500:],
        },
    )


def push_new_events(
    new_events: list[dict[str, Any]],
    seen_order: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "skipped": not new_events,
        "event_count": len(new_events),
        "delivered_event_count": 0,
        "message_count": 0,
        "batches": [],
    }
    seen_keys = set(seen_order)
    for event in new_events:
        alert_key = str(event.get("alert_key") or "")
        messages = split_telegram_text(telegram_event_text(event))
        event_delivered = True
        event_batches = []
        for index, message in enumerate(messages, start=1):
            batch_result = send_telegram(message)
            result["message_count"] += 1
            event_batches.append(
                {
                    "index": index,
                    "message_count": len(messages),
                    "ok": bool(batch_result.get("ok")),
                    "disabled": bool(batch_result.get("disabled")),
                    "reason": batch_result.get("reason", ""),
                }
            )
            if (
                not batch_result.get("ok")
                or batch_result.get("disabled")
            ):
                event_delivered = False
                result["ok"] = bool(batch_result.get("ok"))
                result["reason"] = batch_result.get("reason", "")
                if batch_result.get("disabled"):
                    result["disabled"] = True
                break
        result["batches"].append(
            {
                "alert_key": alert_key,
                "delivered": event_delivered,
                "messages": event_batches,
            }
        )
        if not event_delivered:
            break
        if alert_key and alert_key not in seen_keys:
            seen_keys.add(alert_key)
            seen_order.append(alert_key)
            write_seen_keys(seen_order)
        result["delivered_event_count"] += 1
    return result


def main() -> int:
    current = now_utc()
    config = read_json(CONFIG_PATH, {"items": []})
    events = build_events(config, current)
    seen = read_json(SEEN_PATH, {"keys": []})
    seen_order = list(
        dict.fromkeys(
            str(key)
            for key in seen.get("keys", [])
            if str(key)
        )
    )
    seen_keys = set(seen_order)
    new_events = [event for event in events if event["alert_key"] not in seen_keys]

    push_result = push_new_events(new_events, seen_order)

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
    return 0 if push_result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
