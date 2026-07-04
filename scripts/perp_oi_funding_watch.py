#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "perp_oi_funding_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
HISTORY_PATH = OUT_DIR / "history.jsonl"

BINANCE_FAPI = os.environ.get("PERP_WATCH_BINANCE_FAPI", "https://fapi.binance.com")
OKX_API = os.environ.get("PERP_WATCH_OKX_API", "https://www.okx.com")
BYBIT_API = os.environ.get("PERP_WATCH_BYBIT_API", "https://api.bybit.com")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def read_history() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows and LATEST_PATH.exists():
        latest = read_json(LATEST_PATH, {})
        if latest:
            rows.append(latest)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(snapshot: dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    compact_rows = []
    for row in snapshot.get("rows", []):
        compact_rows.append(
            {
                "symbol": row.get("symbol", ""),
                "perp_symbol": row.get("perp_symbol", ""),
                "venue": row.get("venue", ""),
                "listed_venues": row.get("listed_venues", []),
                "status": row.get("status", ""),
                "perp_state": row.get("perp_state", ""),
                "mark_price": row.get("mark_price", ""),
                "open_interest_usd": row.get("open_interest_usd", ""),
                "total_open_interest_usd": row.get("total_open_interest_usd", ""),
                "last_funding_rate": row.get("last_funding_rate", ""),
                "quote_volume_24h": row.get("quote_volume_24h", ""),
                "price_change_pct_24h": row.get("price_change_pct_24h", ""),
            }
        )
    entry = {
        "generated_at": snapshot.get("generated_at", ""),
        "source_status": snapshot.get("source_status", ""),
        "rows": compact_rows,
    }
    existing = []
    if HISTORY_PATH.exists():
        existing = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    existing.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    limit = int(os.environ.get("PERP_WATCH_HISTORY_LIMIT", "576"))
    HISTORY_PATH.write_text("\n".join(existing[-limit:]) + "\n", encoding="utf-8")


def decimal_from(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def http_json(path: str, params: dict[str, Any] | None = None, timeout: int = 12) -> Any:
    url = BINANCE_FAPI.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "sniper-perp-watch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_json_base(base_url: str, path: str, params: dict[str, Any] | None = None, timeout: int = 12) -> Any:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_watchlist() -> list[dict[str, Any]]:
    config = read_json(CONFIG_PATH, {"items": []})
    rows = []
    review_symbol = os.environ.get("PERP_WATCH_SYMBOL", "").strip().upper()
    for item in config.get("items", []):
        symbol = str(item.get("symbol") or item.get("name") or "").strip().upper()
        if not symbol:
            continue
        if review_symbol and symbol != review_symbol:
            continue
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority") or "")
        if not priority.startswith(("P0", "P1", "P2")):
            continue
        perp_symbol = (
            item.get("perp_symbol")
            or item.get("futures_symbol")
            or item.get("binance_perp_symbol")
            or f"{symbol}USDT"
        )
        rows.append(
            {
                "symbol": symbol,
                "project": item.get("project") or item.get("name") or symbol,
                "priority": priority,
                "perp_symbol": str(perp_symbol).strip().upper(),
            }
        )
    return rows


def exchange_symbols() -> dict[str, dict[str, Any]]:
    payload = http_json("/fapi/v1/exchangeInfo", timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")))
    symbols = {}
    for row in payload.get("symbols", []):
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols[symbol] = row
    return symbols


def okx_exchange_symbols() -> dict[str, dict[str, Any]]:
    payload = http_json_base(
        OKX_API,
        "/api/v5/public/instruments",
        {"instType": "SWAP"},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX instruments error: {payload.get('msg') or payload.get('code')}")
    symbols = {}
    for row in payload.get("data", []):
        inst_id = str(row.get("instId") or "").upper()
        if inst_id:
            symbols[inst_id] = row
    return symbols


def okx_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = http_json_base(
        OKX_API,
        path,
        params,
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX API error: {payload.get('msg') or payload.get('code')}")
    data = payload.get("data") or []
    return data[0] if data else {}


def fetch_okx_symbol(inst_id: str) -> dict[str, Any]:
    ticker = okx_json("/api/v5/market/ticker", {"instId": inst_id})
    oi = okx_json("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst_id})
    funding = okx_json("/api/v5/public/funding-rate", {"instId": inst_id})
    last = decimal_from(ticker.get("last"))
    vol_base = decimal_from(ticker.get("volCcy24h") or ticker.get("vol24h"))
    return {
        "mark_price": str(last),
        "index_price": "",
        "last_funding_rate": str(decimal_from(funding.get("fundingRate"))),
        "next_funding_time": funding.get("fundingTime", ""),
        "open_interest": str(decimal_from(oi.get("oi"))),
        "open_interest_usd": str(decimal_from(oi.get("oiUsd"))),
        "price_change_pct_24h": str(percent_change(last, decimal_from(ticker.get("open24h")))),
        "quote_volume_24h": str(vol_base * last),
        "count_24h": 0,
    }


def bybit_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = http_json_base(
        BYBIT_API,
        path,
        params,
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if int(payload.get("retCode", -1)) != 0:
        raise RuntimeError(f"Bybit API error: {payload.get('retMsg') or payload.get('retCode')}")
    data = payload.get("result", {}).get("list") or []
    return data[0] if data else {}


def fetch_bybit_symbol(symbol: str) -> dict[str, Any]:
    ticker = bybit_json("/v5/market/tickers", {"category": "linear", "symbol": symbol})
    return {
        "mark_price": str(decimal_from(ticker.get("markPrice") or ticker.get("lastPrice"))),
        "index_price": str(decimal_from(ticker.get("indexPrice"))),
        "last_funding_rate": str(decimal_from(ticker.get("fundingRate"))),
        "next_funding_time": ticker.get("nextFundingTime", ""),
        "open_interest": str(decimal_from(ticker.get("openInterest"))),
        "open_interest_usd": str(decimal_from(ticker.get("openInterestValue"))),
        "price_change_pct_24h": str(decimal_from(ticker.get("price24hPcnt")) * Decimal(100)),
        "quote_volume_24h": str(decimal_from(ticker.get("turnover24h"))),
        "count_24h": 0,
    }


def bybit_context(symbol: str) -> dict[str, Any]:
    perp_symbol = f"{symbol.upper()}USDT"
    base = {"venue": "bybit_linear", "perp_symbol": perp_symbol}
    try:
        instrument = bybit_json("/v5/market/instruments-info", {"category": "linear", "symbol": perp_symbol})
    except RuntimeError as exc:
        if "symbol invalid" in str(exc).lower():
            return dict(base, status="not_listed", error="", direction_hint="不开", action="Bybit未发现USDT永续")
        return dict(base, status="source_failed", error=str(exc), direction_hint="观察", action="Bybit合约数据源不可用")
    except Exception as exc:
        return dict(base, status="source_failed", error=str(exc), direction_hint="观察", action="Bybit合约数据源不可用")
    if not instrument or str(instrument.get("status", "")).lower() != "trading":
        return dict(base, status="not_listed", error="", direction_hint="不开", action="Bybit未发现USDT永续")
    try:
        metrics = fetch_bybit_symbol(perp_symbol)
        decision = classify_perp(metrics)
        row = dict(base, status="ok", exchange_status=instrument.get("status", ""))
        row.update(metrics)
        row["perp_state"] = decision.get("status", "")
        row["direction_hint"] = decision.get("direction_hint", "")
        row["action"] = decision.get("action", "")
        return row
    except Exception as exc:
        return dict(base, status="fetch_failed", error=str(exc), direction_hint="观察", action="Bybit合约指标拉取失败")


def okx_context(symbol: str, okx_symbols: dict[str, dict[str, Any]], source_status: str, source_error: str) -> dict[str, Any]:
    inst_id = f"{symbol.upper()}-USDT-SWAP"
    base = {"venue": "okx_swap", "perp_symbol": inst_id}
    if source_status != "ok":
        return dict(base, status="source_failed", error=source_error, direction_hint="观察", action="OKX合约数据源不可用")
    exchange_info = okx_symbols.get(inst_id)
    if not exchange_info or str(exchange_info.get("state", "")).lower() != "live":
        return dict(base, status="not_listed", error="", direction_hint="不开", action="OKX未发现USDT永续")
    try:
        metrics = fetch_okx_symbol(inst_id)
        decision = classify_perp(metrics)
        row = dict(base, status="ok", exchange_status=exchange_info.get("state", ""))
        row.update(metrics)
        row["perp_state"] = decision.get("status", "")
        row["direction_hint"] = decision.get("direction_hint", "")
        row["action"] = decision.get("action", "")
        return row
    except Exception as exc:
        return dict(base, status="fetch_failed", error=str(exc), direction_hint="观察", action="OKX合约指标拉取失败")


def venue_signal_notes(venues: list[dict[str, Any]]) -> list[str]:
    notes = []
    for venue in venues:
        if venue.get("status") != "ok":
            continue
        hint = venue.get("direction_hint", "")
        if hint not in {"拥挤", "可观察"}:
            continue
        funding_pct = decimal_from(venue.get("last_funding_rate")) * Decimal(100)
        notes.append(
            f"{venue.get('venue')} {hint} OI≈{fmt(venue.get('open_interest_usd'), '0.01')} funding {fmt(funding_pct, '0.0001')}%"
        )
    return notes


def best_ok_venue(venues: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok_venues = [venue for venue in venues if venue.get("status") == "ok"]
    if not ok_venues:
        return None
    return max(ok_venues, key=lambda venue: decimal_from(venue.get("open_interest_usd")))


def listed_venue_names(primary: dict[str, Any], extras: list[dict[str, Any]]) -> list[str]:
    names = [str(primary.get("venue") or "")]
    for venue in extras:
        if venue.get("status") == "ok":
            names.append(str(venue.get("venue") or ""))
    return [name for name in names if name]


def total_open_interest(primary: dict[str, Any], extras: list[dict[str, Any]]) -> Decimal:
    total = decimal_from(primary.get("open_interest_usd"))
    for venue in extras:
        if venue.get("status") == "ok":
            total += decimal_from(venue.get("open_interest_usd"))
    return total


def percent_change(current: Decimal, previous: Decimal) -> Decimal:
    if previous <= 0:
        return Decimal(0)
    return (current / previous - Decimal(1)) * Decimal(100)


def history_rows_for_symbol(
    history: list[dict[str, Any]],
    symbol: str,
    generated_at: datetime | None,
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    current_perp = str(current.get("perp_symbol") or "").upper()
    for snapshot in history:
        ts = parse_iso(snapshot.get("generated_at"))
        if generated_at and ts and ts >= generated_at:
            continue
        for row in snapshot.get("rows", []):
            if str(row.get("symbol", "")).upper() != symbol.upper() or row.get("status") != "ok":
                continue
            row_perp = str(row.get("perp_symbol") or "").upper()
            if current_perp and row_perp and row_perp != current_perp:
                continue
            rows.append({"generated_at": snapshot.get("generated_at", ""), **row})
    rows.sort(key=lambda row: parse_iso(row.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def trend_for_symbol(history: list[dict[str, Any]], symbol: str, current: dict[str, Any], generated_at: str) -> dict[str, Any]:
    current_time = parse_iso(generated_at)
    rows = history_rows_for_symbol(history, symbol, current_time, current)
    if not rows:
        return {"trend_status": "no_history", "trend_hint": "观察", "trend_action": "历史样本不足"}

    lookback = int(os.environ.get("PERP_WATCH_TREND_LOOKBACK_MINUTES", "60"))
    target_time = current_time.timestamp() - lookback * 60 if current_time else None
    baseline = rows[0]
    if target_time is not None:
        older = [row for row in rows if (parse_iso(row.get("generated_at")) or current_time).timestamp() <= target_time]
        if older:
            baseline = older[-1]
    previous = rows[-1]
    base_time = parse_iso(baseline.get("generated_at"))
    age_minutes = ""
    if current_time and base_time:
        age_minutes = str(max(0, int((current_time - base_time).total_seconds() // 60)))
    min_age = int(os.environ.get("PERP_WATCH_TREND_MIN_AGE_MINUTES", "10"))
    if age_minutes != "" and int(age_minutes) < min_age:
        return {
            "trend_status": "short_history",
            "baseline_generated_at": baseline.get("generated_at", ""),
            "baseline_age_minutes": age_minutes,
            "previous_generated_at": previous.get("generated_at", ""),
            "trend_hint": "观察",
            "trend_action": "历史窗口不足",
        }

    current_oi = decimal_from(current.get("open_interest_usd"))
    base_oi = decimal_from(baseline.get("open_interest_usd"))
    previous_oi = decimal_from(previous.get("open_interest_usd"))
    current_price = decimal_from(current.get("mark_price"))
    base_price = decimal_from(baseline.get("mark_price"))
    current_funding = decimal_from(current.get("last_funding_rate"))
    base_funding = decimal_from(baseline.get("last_funding_rate"))
    oi_delta = current_oi - base_oi
    oi_delta_pct = percent_change(current_oi, base_oi)
    previous_oi_delta_pct = percent_change(current_oi, previous_oi)
    price_delta_pct = percent_change(current_price, base_price)
    funding_delta = current_funding - base_funding

    oi_expand_pct = Decimal(os.environ.get("PERP_WATCH_OI_EXPANSION_PCT", "5"))
    price_move_pct = Decimal(os.environ.get("PERP_WATCH_PRICE_MOVE_PCT", "3"))
    trend_hint = "观察"
    trend_action = "OI和价格变化不足，合约层只作背景"
    if oi_delta_pct >= oi_expand_pct and price_delta_pct >= price_move_pct:
        trend_hint = "多头增量"
        trend_action = "OI扩张且价格上涨，重点等现货承接和链上净流确认"
    elif oi_delta_pct >= oi_expand_pct and price_delta_pct <= -price_move_pct:
        trend_hint = "空头增量"
        trend_action = "OI扩张且价格下跌，重点防守反弹出货和强平波动"
    elif oi_delta_pct <= -oi_expand_pct:
        trend_hint = "降杠杆"
        trend_action = "OI收缩，合约资金撤退，价格信号需要现货成交确认"
    elif abs(funding_delta) >= Decimal(os.environ.get("PERP_WATCH_FUNDING_DELTA_ALERT", "0.00025")):
        trend_hint = "费率变化"
        trend_action = "资金费率变化明显，观察是否形成拥挤方向"

    return {
        "trend_status": "ok",
        "baseline_generated_at": baseline.get("generated_at", ""),
        "baseline_age_minutes": age_minutes,
        "previous_generated_at": previous.get("generated_at", ""),
        "oi_usd_delta": str(oi_delta),
        "oi_usd_delta_pct": str(oi_delta_pct),
        "previous_oi_usd_delta_pct": str(previous_oi_delta_pct),
        "mark_price_delta_pct": str(price_delta_pct),
        "funding_rate_delta": str(funding_delta),
        "trend_hint": trend_hint,
        "trend_action": trend_action,
    }


def fetch_symbol(symbol: str) -> dict[str, Any]:
    timeout = int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30"))
    premium = http_json("/fapi/v1/premiumIndex", {"symbol": symbol}, timeout=timeout)
    oi = http_json("/fapi/v1/openInterest", {"symbol": symbol}, timeout=timeout)
    ticker = http_json("/fapi/v1/ticker/24hr", {"symbol": symbol}, timeout=timeout)
    mark = decimal_from(premium.get("markPrice"))
    open_interest = decimal_from(oi.get("openInterest"))
    return {
        "mark_price": str(mark),
        "index_price": str(decimal_from(premium.get("indexPrice"))),
        "last_funding_rate": str(decimal_from(premium.get("lastFundingRate"))),
        "next_funding_time": premium.get("nextFundingTime", ""),
        "open_interest": str(open_interest),
        "open_interest_usd": str(open_interest * mark),
        "price_change_pct_24h": str(decimal_from(ticker.get("priceChangePercent"))),
        "quote_volume_24h": str(decimal_from(ticker.get("quoteVolume"))),
        "count_24h": ticker.get("count", 0),
    }


def classify_perp(row: dict[str, Any]) -> dict[str, Any]:
    funding = decimal_from(row.get("last_funding_rate"))
    oi_usd = decimal_from(row.get("open_interest_usd"))
    volume = decimal_from(row.get("quote_volume_24h"))
    price_change = decimal_from(row.get("price_change_pct_24h"))
    oi_floor = Decimal(os.environ.get("PERP_WATCH_OI_USD_FLOOR", "500000"))
    funding_abs = Decimal(os.environ.get("PERP_WATCH_FUNDING_ABS_ALERT", "0.0005"))
    volume_floor = Decimal(os.environ.get("PERP_WATCH_VOLUME_USD_FLOOR", "1000000"))

    if oi_usd < oi_floor:
        return {
            "status": "thin_or_unusable",
            "direction_hint": "不开",
            "action": "合约深度不足，只作价格参考",
        }
    if abs(funding) >= funding_abs:
        crowded_side = "多头拥挤" if funding > 0 else "空头拥挤"
        return {
            "status": "crowded_funding",
            "direction_hint": "拥挤",
            "action": f"{crowded_side}，等价格和链上流向确认",
        }
    if volume >= volume_floor and abs(price_change) >= Decimal("10"):
        return {
            "status": "active_perp_market",
            "direction_hint": "可观察",
            "action": "合约成交活跃，可配合链上出流和价格结构判断",
        }
    return {
        "status": "listed_quiet",
        "direction_hint": "观察",
        "action": "合约已上线，暂未出现明显OI/资金费率信号",
    }


def build_snapshot() -> dict[str, Any]:
    watchlist = load_watchlist()
    rows = []
    generated_at = now_iso()
    history = read_history()
    try:
        listed = exchange_symbols()
        source_status = "ok"
        source_error = ""
    except Exception as exc:
        listed = {}
        source_status = "failed"
        source_error = str(exc)
    try:
        okx_listed = okx_exchange_symbols()
        okx_source_status = "ok"
        okx_source_error = ""
    except Exception as exc:
        okx_listed = {}
        okx_source_status = "failed"
        okx_source_error = str(exc)

    for item in watchlist:
        symbol = item["perp_symbol"]
        okx = okx_context(item["symbol"], okx_listed, okx_source_status, okx_source_error)
        bybit = bybit_context(item["symbol"])
        extra_venues = [okx, bybit]
        base = {
            "symbol": item["symbol"],
            "project": item["project"],
            "priority": item["priority"],
            "perp_symbol": symbol,
            "venue": "binance_usdm",
            "extra_venues": extra_venues,
        }
        if source_status != "ok":
            fallback = best_ok_venue(extra_venues)
            if fallback:
                decision = classify_perp(fallback)
                other_venues = [venue for venue in extra_venues if venue.get("venue") != fallback.get("venue")]
                row = dict(base, status="ok", venue=fallback.get("venue", ""), perp_symbol=fallback.get("perp_symbol", ""))
                row.update(fallback)
                trend = trend_for_symbol(history, item["symbol"], row, generated_at)
                row["perp_state"] = decision.get("status", "")
                row["direction_hint"] = decision.get("direction_hint", "")
                row["action"] = f"Binance USD-M不可用；{fallback.get('venue')} {decision.get('action', '')}"
                row["extra_venues"] = other_venues
                row["listed_venues"] = listed_venue_names(row, other_venues)
                row["total_open_interest_usd"] = str(total_open_interest(row, other_venues))
                row.update(trend)
                rows.append(row)
            else:
                rows.append(dict(base, status="source_failed", error=source_error, direction_hint="观察", action="合约数据源不可用"))
            continue
        exchange_info = listed.get(symbol)
        if not exchange_info or exchange_info.get("status") != "TRADING":
            fallback = best_ok_venue(extra_venues)
            if fallback:
                decision = classify_perp(fallback)
                other_venues = [venue for venue in extra_venues if venue.get("venue") != fallback.get("venue")]
                row = dict(base, status="ok", venue=fallback.get("venue", ""), perp_symbol=fallback.get("perp_symbol", ""))
                row.update(fallback)
                trend = trend_for_symbol(history, item["symbol"], row, generated_at)
                row["perp_state"] = decision.get("status", "")
                row["direction_hint"] = decision.get("direction_hint", "")
                row["action"] = f"Binance USD-M未上；{fallback.get('venue')} {decision.get('action', '')}"
                row["extra_venues"] = other_venues
                row["listed_venues"] = listed_venue_names(row, other_venues)
                row["total_open_interest_usd"] = str(total_open_interest(row, other_venues))
                row.update(trend)
                rows.append(row)
            else:
                rows.append(dict(base, status="not_listed", error="", direction_hint="不开", action="未发现 Binance USD-M 合约"))
            continue
        try:
            metrics = fetch_symbol(symbol)
            decision = classify_perp(metrics)
            row = dict(base, status="ok", exchange_status=exchange_info.get("status", ""))
            row.update(metrics)
            trend = trend_for_symbol(history, item["symbol"], row, generated_at)
            venue_notes = venue_signal_notes(extra_venues)
            row["perp_state"] = decision.get("status", "")
            row["direction_hint"] = decision.get("direction_hint", "")
            row["action"] = decision.get("action", "")
            if venue_notes:
                row["action"] += "；其他场地 " + "；".join(venue_notes)
            row["listed_venues"] = listed_venue_names(row, extra_venues)
            row["total_open_interest_usd"] = str(total_open_interest(row, extra_venues))
            row["cross_venue_notes"] = venue_notes
            row.update(trend)
            rows.append(row)
        except Exception as exc:
            fallback = best_ok_venue(extra_venues)
            if fallback:
                decision = classify_perp(fallback)
                other_venues = [venue for venue in extra_venues if venue.get("venue") != fallback.get("venue")]
                row = dict(base, status="ok", venue=fallback.get("venue", ""), perp_symbol=fallback.get("perp_symbol", ""))
                row.update(fallback)
                trend = trend_for_symbol(history, item["symbol"], row, generated_at)
                row["perp_state"] = decision.get("status", "")
                row["direction_hint"] = decision.get("direction_hint", "")
                row["action"] = f"Binance USD-M指标失败；{fallback.get('venue')} {decision.get('action', '')}"
                row["binance_error"] = str(exc)
                row["extra_venues"] = other_venues
                row["listed_venues"] = listed_venue_names(row, other_venues)
                row["total_open_interest_usd"] = str(total_open_interest(row, other_venues))
                row.update(trend)
                rows.append(row)
            else:
                rows.append(dict(base, status="fetch_failed", error=str(exc), direction_hint="观察", action="合约指标拉取失败"))
    alerts = [
        row
        for row in rows
        if row.get("status") == "ok"
        and (row.get("direction_hint") in {"拥挤", "可观察"} or bool(row.get("cross_venue_notes")))
    ]
    return {
        "schema": "perp_oi_funding_watch.v1",
        "generated_at": generated_at,
        "source": "multi_venue_public",
        "source_status": source_status,
        "source_error": source_error,
        "venue_source_status": {
            "binance_usdm": source_status,
            "okx_swap": okx_source_status,
            "bybit_linear": "per_symbol",
        },
        "venue_source_error": {
            "binance_usdm": source_error,
            "okx_swap": okx_source_error,
            "bybit_linear": "",
        },
        "item_count": len(watchlist),
        "alert_count": len(alerts),
        "rows": rows,
        "alerts": alerts,
    }


def fmt(value: Any, places: str = "0.0000") -> str:
    dec = decimal_from(value)
    if not dec:
        return "0"
    return str(dec.quantize(Decimal(places)))


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Perp OI/Funding Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- source_status: `{snapshot['source_status']}`",
        f"- item_count: `{snapshot['item_count']}`",
        f"- alert_count: `{snapshot['alert_count']}`",
        "",
        "| Symbol | Perp | Venues | Status | OI USD | Total OI | OI Δ | Funding | 24h Vol | 24h Chg | Trend | Action |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in snapshot["rows"]:
        funding_pct = decimal_from(row.get("last_funding_rate")) * Decimal(100)
        oi_delta_pct = decimal_from(row.get("oi_usd_delta_pct"))
        combined_action = row.get("action", "")
        if row.get("trend_action"):
            combined_action += f"; {row.get('trend_action')}"
        venues = ",".join(row.get("listed_venues") or [row.get("venue", "")])
        lines.append(
            f"| `{row.get('symbol')}` | `{row.get('perp_symbol')}` | {venues} | {row.get('status')}:{row.get('perp_state', '')} / {row.get('direction_hint', '')} | "
            f"{fmt(row.get('open_interest_usd'), '0.01')} | {fmt(row.get('total_open_interest_usd') or row.get('open_interest_usd'), '0.01')} | {fmt(oi_delta_pct, '0.01')}% | {fmt(funding_pct, '0.0001')}% | "
            f"{fmt(row.get('quote_volume_24h'), '0.01')} | {fmt(row.get('price_change_pct_24h'), '0.01')}% | "
            f"{row.get('trend_hint', '')} | {combined_action} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    snapshot = build_snapshot()
    write_json(LATEST_PATH, snapshot)
    append_history(snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    print(LATEST_PATH)
    print(REPORT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
