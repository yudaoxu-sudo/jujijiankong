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
FUNDING_HISTORY_CACHE_PATH = OUT_DIR / "funding_history_cache.json"

BINANCE_FAPI = os.environ.get("PERP_WATCH_BINANCE_FAPI", "https://fapi.binance.com")
OKX_API = os.environ.get("PERP_WATCH_OKX_API", "https://www.okx.com")
BYBIT_API = os.environ.get("PERP_WATCH_BYBIT_API", "https://api.bybit.com")
DEPTH_BAND_BPS = Decimal(os.environ.get("PERP_WATCH_DEPTH_BAND_BPS", "50"))


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
                "current_funding_rate_8h": row.get("current_funding_rate_8h", ""),
                "funding_24h_avg_8h_rate": row.get("funding_24h_avg_8h_rate", ""),
                "funding_24h_cumulative_rate": row.get("funding_24h_cumulative_rate", ""),
                "funding_history_state": row.get("funding_history_state", ""),
                "quote_volume_24h": row.get("quote_volume_24h", ""),
                "price_change_pct_24h": row.get("price_change_pct_24h", ""),
                "depth_state": row.get("depth_state", ""),
                "bid_depth_usd": row.get("bid_depth_usd", ""),
                "ask_depth_usd": row.get("ask_depth_usd", ""),
                "liquidation_state": row.get("liquidation_state", ""),
                "long_liquidation_usd": row.get("long_liquidation_usd", ""),
                "short_liquidation_usd": row.get("short_liquidation_usd", ""),
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


def canonical_funding_records(
    rows: list[dict[str, Any]],
    *,
    timestamp_field: str,
    rate_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    by_timestamp: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            timestamp_ms = int(row.get(timestamp_field) or 0)
        except (TypeError, ValueError):
            continue
        rate_value: Any = None
        source_field = ""
        for field in rate_fields:
            if row.get(field) not in ("", None):
                rate_value = row.get(field)
                source_field = field
                break
        if timestamp_ms <= 0 or rate_value in ("", None):
            continue
        try:
            Decimal(str(rate_value))
        except Exception:
            continue
        by_timestamp[timestamp_ms] = {
            "timestamp_ms": timestamp_ms,
            "funding_rate": str(rate_value),
            "source_field": source_field,
        }
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def funding_history_limit() -> int:
    return max(2, min(200, int(os.environ.get("PERP_WATCH_FUNDING_HISTORY_LIMIT", "30"))))


def fetch_binance_funding_history(symbol: str) -> list[dict[str, Any]]:
    payload = http_json(
        "/fapi/v1/fundingRate",
        {"symbol": symbol, "limit": funding_history_limit()},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if not isinstance(payload, list):
        raise RuntimeError("Binance funding history returned a non-list payload")
    return canonical_funding_records(payload, timestamp_field="fundingTime", rate_fields=("fundingRate",))


def fetch_okx_funding_history(inst_id: str) -> list[dict[str, Any]]:
    payload = http_json_base(
        OKX_API,
        "/api/v5/public/funding-rate-history",
        {"instId": inst_id, "limit": funding_history_limit()},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX funding history error: {payload.get('msg') or payload.get('code')}")
    return canonical_funding_records(
        payload.get("data") or [],
        timestamp_field="fundingTime",
        rate_fields=("realizedRate", "fundingRate"),
    )


def fetch_bybit_funding_history(symbol: str) -> list[dict[str, Any]]:
    payload = http_json_base(
        BYBIT_API,
        "/v5/market/funding/history",
        {"category": "linear", "symbol": symbol, "limit": funding_history_limit()},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if int(payload.get("retCode", -1)) != 0:
        raise RuntimeError(f"Bybit funding history error: {payload.get('retMsg') or payload.get('retCode')}")
    return canonical_funding_records(
        payload.get("result", {}).get("list") or [],
        timestamp_field="fundingRateTimestamp",
        rate_fields=("fundingRate",),
    )


def inferred_funding_interval_hours(records: list[dict[str, Any]], fallback: Any = "8") -> Decimal:
    timestamps = sorted({int(row.get("timestamp_ms") or 0) for row in records if int(row.get("timestamp_ms") or 0) > 0})
    gaps = []
    for previous, current in zip(timestamps, timestamps[1:]):
        gap = Decimal(current - previous) / Decimal(3_600_000)
        if Decimal("0.5") <= gap <= Decimal(24):
            gaps.append(gap)
    if gaps:
        gaps.sort()
        middle = len(gaps) // 2
        return gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / Decimal(2)
    fallback_value = decimal_from(fallback)
    return fallback_value if fallback_value > 0 else Decimal(8)


def funding_history_state(
    latest_8h: Decimal,
    previous_8h: Decimal,
    average_8h: Decimal,
    positive_ratio: Decimal,
    negative_ratio: Decimal,
    point_count: int,
) -> str:
    crowding = Decimal(os.environ.get("PERP_WATCH_FUNDING_HISTORY_CROWDING_8H", "0.0005"))
    flip = Decimal(os.environ.get("PERP_WATCH_FUNDING_HISTORY_FLIP_8H", "0.0001"))
    sustained_ratio = Decimal(os.environ.get("PERP_WATCH_FUNDING_HISTORY_SUSTAINED_RATIO", "0.75"))
    if point_count >= 3 and average_8h >= crowding and positive_ratio >= sustained_ratio:
        return "sustained_long_crowding"
    if point_count >= 3 and average_8h <= -crowding and negative_ratio >= sustained_ratio:
        return "sustained_short_crowding"
    if previous_8h <= -flip and latest_8h >= flip:
        return "funding_flip_positive"
    if previous_8h >= flip and latest_8h <= -flip:
        return "funding_flip_negative"
    if latest_8h >= crowding:
        return "recent_long_crowding"
    if latest_8h <= -crowding:
        return "recent_short_crowding"
    if point_count >= 3 and positive_ratio >= Decimal("0.25") and negative_ratio >= Decimal("0.25"):
        return "mixed_funding"
    return "neutral_funding"


def summarize_funding_history(
    records: list[dict[str, Any]],
    *,
    current_rate: Any = "",
    fallback_interval_hours: Any = "8",
) -> dict[str, Any]:
    canonical = canonical_funding_records(records, timestamp_field="timestamp_ms", rate_fields=("funding_rate",))
    if not canonical:
        return {
            "funding_history_status": "no_history",
            "funding_history_state": "unknown_funding_history",
            "funding_history_points": 0,
        }
    interval = inferred_funding_interval_hours(canonical, fallback_interval_hours)
    latest_timestamp = int(canonical[-1]["timestamp_ms"])
    recent = [row for row in canonical if int(row["timestamp_ms"]) > latest_timestamp - 24 * 60 * 60 * 1000]
    recent_rates = [decimal_from(row.get("funding_rate")) for row in recent]
    normalized = [rate * Decimal(8) / interval for rate in recent_rates]
    latest_8h = normalized[-1]
    previous_8h = normalized[-2] if len(normalized) >= 2 else Decimal(0)
    average_8h = sum(normalized, Decimal(0)) / Decimal(len(normalized))
    cumulative = sum(recent_rates, Decimal(0))
    positive_ratio = Decimal(sum(1 for rate in recent_rates if rate > 0)) / Decimal(len(recent_rates))
    negative_ratio = Decimal(sum(1 for rate in recent_rates if rate < 0)) / Decimal(len(recent_rates))
    current_raw = decimal_from(current_rate)
    current_8h = current_raw * Decimal(8) / interval
    state = funding_history_state(
        latest_8h,
        previous_8h,
        average_8h,
        positive_ratio,
        negative_ratio,
        len(recent_rates),
    )
    return {
        "funding_history_status": "ok" if len(canonical) >= 2 else "short_history",
        "funding_history_state": state,
        "funding_history_points": len(canonical),
        "funding_24h_points": len(recent_rates),
        "funding_interval_hours": str(interval),
        "current_funding_rate_8h": str(current_8h),
        "settled_funding_rate_8h": str(latest_8h),
        "previous_settled_funding_rate_8h": str(previous_8h),
        "funding_24h_avg_8h_rate": str(average_8h),
        "funding_24h_cumulative_rate": str(cumulative),
        "funding_24h_positive_ratio": str(positive_ratio),
        "funding_24h_negative_ratio": str(negative_ratio),
        "funding_history_latest_timestamp": latest_timestamp,
    }


def cached_funding_records(
    cache: dict[str, Any],
    key: str,
    fetcher: Any,
) -> tuple[list[dict[str, Any]], str, str]:
    entries = cache.setdefault("entries", {})
    entry = entries.get(key) if isinstance(entries.get(key), dict) else {}
    cached_rows = entry.get("records") if isinstance(entry.get("records"), list) else []
    fetched_at = parse_iso(entry.get("fetched_at"))
    ttl_seconds = int(os.environ.get("PERP_WATCH_FUNDING_HISTORY_TTL_SECONDS", "1800"))
    age_seconds = (datetime.now(timezone.utc) - fetched_at).total_seconds() if fetched_at else None
    if cached_rows and age_seconds is not None and age_seconds <= ttl_seconds:
        return cached_rows, "cache", ""
    try:
        records = fetcher()
        if not records:
            raise RuntimeError("empty funding history")
        entries[key] = {"fetched_at": now_iso(), "records": records}
        return records, "live", ""
    except Exception as exc:
        if cached_rows:
            return cached_rows, "stale_cache", str(exc)[:180]
        raise


def funding_history_note(row: dict[str, Any]) -> str:
    state = str(row.get("funding_history_state") or "")
    mapping = {
        "sustained_long_crowding": "24h多头持续付费，防回撤",
        "sustained_short_crowding": "24h空头持续付费，防逼空",
        "funding_flip_positive": "结算费率由负翻正，观察多头是否开始拥挤",
        "funding_flip_negative": "结算费率由正翻负，观察空头是否开始拥挤",
        "recent_long_crowding": "最新结算多头拥挤",
        "recent_short_crowding": "最新结算空头拥挤",
        "mixed_funding": "24h费率方向反复，合约方向降权",
    }
    return mapping.get(state, "")


def attach_funding_history(
    row: dict[str, Any],
    cache: dict[str, Any],
    cache_key: str,
    fetcher: Any,
    *,
    fallback_interval_hours: Any = "8",
) -> dict[str, Any]:
    try:
        records, source, error = cached_funding_records(cache, cache_key, fetcher)
        row.update(
            summarize_funding_history(
                records,
                current_rate=row.get("last_funding_rate"),
                fallback_interval_hours=fallback_interval_hours,
            )
        )
        row["funding_history_source"] = source
        if error:
            row["funding_history_error"] = error
    except Exception as exc:
        row["funding_history_status"] = "failed"
        row["funding_history_state"] = "unknown_funding_history"
        row["funding_history_error"] = str(exc)[:180]
    note = funding_history_note(row)
    if note:
        row["funding_history_note"] = note
    return row


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
    funding_time = decimal_from(funding.get("fundingTime"))
    next_funding_time = decimal_from(funding.get("nextFundingTime"))
    interval_hint = (next_funding_time - funding_time) / Decimal(3_600_000) if next_funding_time > funding_time else Decimal(0)
    return {
        "mark_price": str(last),
        "index_price": "",
        "last_funding_rate": str(decimal_from(funding.get("fundingRate"))),
        "next_funding_time": funding.get("fundingTime", ""),
        "funding_interval_hint_hours": str(interval_hint) if interval_hint > 0 else "",
        "open_interest": str(decimal_from(oi.get("oi"))),
        "open_interest_usd": str(decimal_from(oi.get("oiUsd"))),
        "price_change_pct_24h": str(percent_change(last, decimal_from(ticker.get("open24h")))),
        "quote_volume_24h": str(vol_base * last),
        "count_24h": 0,
    }


def depth_metrics(
    mark_price: Any,
    bids: list[list[Any]],
    asks: list[list[Any]],
    band_bps: Decimal | None = None,
    size_multiplier: Decimal | None = None,
) -> dict[str, Any]:
    band = band_bps if band_bps is not None else DEPTH_BAND_BPS
    multiplier = size_multiplier if size_multiplier is not None else Decimal(1)
    mark = decimal_from(mark_price)
    if mark <= 0:
        return {"depth_status": "unavailable", "depth_state": "unknown_depth", "depth_error": "missing_mark_price"}
    bid_floor = mark * (Decimal(1) - band / Decimal(10000))
    ask_ceiling = mark * (Decimal(1) + band / Decimal(10000))

    def notional(rows: list[list[Any]], *, side: str, limit: Decimal) -> Decimal:
        total = Decimal(0)
        for row in rows:
            if len(row) < 2:
                continue
            price = decimal_from(row[0])
            size = decimal_from(row[1])
            if price <= 0 or size <= 0:
                continue
            if side == "bid" and price < limit:
                continue
            if side == "ask" and price > limit:
                continue
            total += price * size * multiplier
        return total

    best_bid = decimal_from(bids[0][0]) if bids and bids[0] else Decimal(0)
    best_ask = decimal_from(asks[0][0]) if asks and asks[0] else Decimal(0)
    bid_depth = notional(bids, side="bid", limit=bid_floor)
    ask_depth = notional(asks, side="ask", limit=ask_ceiling)
    total_depth = bid_depth + ask_depth
    spread_bps = Decimal(0)
    if best_bid > 0 and best_ask > 0:
        spread_bps = (best_ask - best_bid) / ((best_ask + best_bid) / Decimal(2)) * Decimal(10000)
    imbalance = Decimal(0)
    if total_depth > 0:
        imbalance = (bid_depth - ask_depth) / total_depth

    floor = Decimal(os.environ.get("PERP_WATCH_DEPTH_USD_FLOOR", "20000"))
    imbalance_alert = Decimal(os.environ.get("PERP_WATCH_DEPTH_IMBALANCE_ALERT", "0.35"))
    spread_alert = Decimal(os.environ.get("PERP_WATCH_SPREAD_BPS_ALERT", "30"))
    depth_state = "balanced_depth"
    if bid_depth < floor or ask_depth < floor:
        depth_state = "thin_depth"
    elif spread_bps >= spread_alert:
        depth_state = "wide_spread"
    elif imbalance >= imbalance_alert:
        depth_state = "ask_thin"
    elif imbalance <= -imbalance_alert:
        depth_state = "bid_thin"

    return {
        "depth_status": "ok",
        "depth_band_bps": str(band),
        "best_bid": str(best_bid),
        "best_ask": str(best_ask),
        "spread_bps": str(spread_bps),
        "bid_depth_usd": str(bid_depth),
        "ask_depth_usd": str(ask_depth),
        "depth_imbalance": str(imbalance),
        "depth_state": depth_state,
    }


def depth_action_note(row: dict[str, Any]) -> str:
    state = str(row.get("depth_state") or "")
    if row.get("depth_status") != "ok" or not state:
        return ""
    bid = fmt(row.get("bid_depth_usd"), "0.01")
    ask = fmt(row.get("ask_depth_usd"), "0.01")
    spread = fmt(row.get("spread_bps"), "0.01")
    band = row.get("depth_band_bps") or str(DEPTH_BAND_BPS)
    prefix = f"盘口±{band}bps bid≈{bid} ask≈{ask} spread≈{spread}bps"
    if state == "thin_depth":
        return prefix + "，合约盘口薄"
    if state == "wide_spread":
        return prefix + "，点差偏宽"
    if state == "ask_thin":
        return prefix + "，上方卖盘薄"
    if state == "bid_thin":
        return prefix + "，下方买盘薄"
    return prefix + "，盘口厚度可用"


def liquidation_metrics(
    details: list[dict[str, Any]],
    size_multiplier: Decimal | None = None,
    now_ms: int | None = None,
    lookback_minutes: int | None = None,
) -> dict[str, Any]:
    multiplier = size_multiplier if size_multiplier is not None else Decimal(1)
    current_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    window_minutes = lookback_minutes if lookback_minutes is not None else int(os.environ.get("PERP_WATCH_LIQUIDATION_LOOKBACK_MINUTES", "60"))
    since_ms = current_ms - window_minutes * 60 * 1000
    long_liq = Decimal(0)
    short_liq = Decimal(0)
    long_count = 0
    short_count = 0
    latest_ms = 0
    for row in details:
        ts = int(row.get("ts") or row.get("time") or 0)
        if ts and ts < since_ms:
            continue
        price = decimal_from(row.get("bkPx"))
        size = decimal_from(row.get("sz"))
        if price <= 0 or size <= 0:
            continue
        latest_ms = max(latest_ms, ts)
        notional = price * size * multiplier
        pos_side = str(row.get("posSide") or "").lower()
        side = str(row.get("side") or "").lower()
        if pos_side == "long" or side == "sell":
            long_liq += notional
            long_count += 1
        elif pos_side == "short" or side == "buy":
            short_liq += notional
            short_count += 1
    total = long_liq + short_liq
    threshold = Decimal(os.environ.get("PERP_WATCH_LIQUIDATION_USD_ALERT", "20000"))
    state = "no_recent_liquidation"
    if total > 0 and total < threshold:
        state = "light_liquidation"
    elif long_liq >= threshold and long_liq >= short_liq * Decimal(2):
        state = "long_liquidation_pressure"
    elif short_liq >= threshold and short_liq >= long_liq * Decimal(2):
        state = "short_liquidation_pressure"
    elif total >= threshold:
        state = "two_sided_liquidation"
    return {
        "liquidation_status": "ok",
        "liquidation_venue": "okx_swap",
        "liquidation_lookback_minutes": str(window_minutes),
        "long_liquidation_usd": str(long_liq),
        "short_liquidation_usd": str(short_liq),
        "total_liquidation_usd": str(total),
        "long_liquidation_count": long_count,
        "short_liquidation_count": short_count,
        "latest_liquidation_ts": str(latest_ms) if latest_ms else "",
        "liquidation_state": state,
    }


def liquidation_action_note(row: dict[str, Any]) -> str:
    state = str(row.get("liquidation_state") or "")
    if row.get("liquidation_status") != "ok" or state in {"", "no_recent_liquidation"}:
        return ""
    lookback = row.get("liquidation_lookback_minutes") or os.environ.get("PERP_WATCH_LIQUIDATION_LOOKBACK_MINUTES", "60")
    long_liq = fmt(row.get("long_liquidation_usd"), "0.01")
    short_liq = fmt(row.get("short_liquidation_usd"), "0.01")
    prefix = f"OKX近{lookback}分钟强平 long≈{long_liq} short≈{short_liq}"
    if state == "long_liquidation_pressure":
        return prefix + "，多头强平压力"
    if state == "short_liquidation_pressure":
        return prefix + "，空头强平压力"
    if state == "two_sided_liquidation":
        return prefix + "，双向强平波动"
    return prefix + "，轻量强平"


def binance_depth_context(symbol: str, mark_price: Any) -> dict[str, Any]:
    limit = int(os.environ.get("PERP_WATCH_DEPTH_LIMIT", "50"))
    payload = http_json("/fapi/v1/depth", {"symbol": symbol, "limit": limit}, timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")))
    return depth_metrics(mark_price, payload.get("bids") or [], payload.get("asks") or [])


def okx_depth_context(inst_id: str, mark_price: Any, exchange_info: dict[str, Any]) -> dict[str, Any]:
    limit = int(os.environ.get("PERP_WATCH_DEPTH_LIMIT", "50"))
    payload = http_json_base(
        OKX_API,
        "/api/v5/market/books",
        {"instId": inst_id, "sz": limit},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX depth error: {payload.get('msg') or payload.get('code')}")
    data = payload.get("data") or []
    book = data[0] if data else {}
    multiplier = decimal_from(exchange_info.get("ctVal") or "1")
    if multiplier <= 0:
        multiplier = Decimal(1)
    return depth_metrics(mark_price, book.get("bids") or [], book.get("asks") or [], size_multiplier=multiplier)


def okx_inst_family(inst_id: str, exchange_info: dict[str, Any]) -> str:
    family = str(exchange_info.get("instFamily") or "").upper()
    if family:
        return family
    if inst_id.endswith("-SWAP"):
        return inst_id[:-5]
    parts = inst_id.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else inst_id


def okx_liquidation_context(inst_id: str, exchange_info: dict[str, Any]) -> dict[str, Any]:
    payload = http_json_base(
        OKX_API,
        "/api/v5/public/liquidation-orders",
        {
            "instType": "SWAP",
            "mgnMode": os.environ.get("PERP_WATCH_OKX_LIQUIDATION_MGN_MODE", "cross"),
            "instFamily": okx_inst_family(inst_id, exchange_info),
            "state": "filled",
            "limit": int(os.environ.get("PERP_WATCH_LIQUIDATION_LIMIT", "100")),
        },
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX liquidation error: {payload.get('msg') or payload.get('code')}")
    details: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        for detail in item.get("details") or []:
            if isinstance(detail, dict):
                details.append(detail)
    multiplier = decimal_from(exchange_info.get("ctVal") or "1")
    if multiplier <= 0:
        multiplier = Decimal(1)
    return liquidation_metrics(details, size_multiplier=multiplier)


def bybit_orderbook(symbol: str, limit: int) -> dict[str, Any]:
    payload = http_json_base(
        BYBIT_API,
        "/v5/market/orderbook",
        {"category": "linear", "symbol": symbol, "limit": limit},
        timeout=int(os.environ.get("PERP_WATCH_HTTP_TIMEOUT", "30")),
    )
    if int(payload.get("retCode", -1)) != 0:
        raise RuntimeError(f"Bybit orderbook error: {payload.get('retMsg') or payload.get('retCode')}")
    return payload.get("result", {})


def bybit_depth_context(symbol: str, mark_price: Any) -> dict[str, Any]:
    limit = int(os.environ.get("PERP_WATCH_DEPTH_LIMIT", "50"))
    book = bybit_orderbook(symbol, limit)
    return depth_metrics(mark_price, book.get("b") or [], book.get("a") or [])


def attach_depth(row: dict[str, Any], fetcher: Any, *args: Any) -> dict[str, Any]:
    try:
        row.update(fetcher(*args))
    except Exception as exc:
        row["depth_status"] = "failed"
        row["depth_state"] = "unknown_depth"
        row["depth_error"] = str(exc)[:180]
    note = depth_action_note(row)
    if note:
        row["depth_note"] = note
    return row


def attach_liquidations(row: dict[str, Any], fetcher: Any, *args: Any) -> dict[str, Any]:
    try:
        row.update(fetcher(*args))
    except Exception as exc:
        row["liquidation_status"] = "failed"
        row["liquidation_state"] = "unknown_liquidation"
        row["liquidation_error"] = str(exc)[:180]
    note = liquidation_action_note(row)
    if note:
        row["liquidation_note"] = note
    return row


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


def bybit_context(symbol: str, funding_cache: dict[str, Any]) -> dict[str, Any]:
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
        row = dict(base, status="ok", exchange_status=instrument.get("status", ""))
        row.update(metrics)
        interval_minutes = decimal_from(instrument.get("fundingInterval"))
        interval_hint = interval_minutes / Decimal(60) if interval_minutes > 0 else Decimal(8)
        attach_funding_history(
            row,
            funding_cache,
            f"bybit_linear:{perp_symbol}",
            lambda: fetch_bybit_funding_history(perp_symbol),
            fallback_interval_hours=interval_hint,
        )
        decision = classify_perp(row)
        attach_depth(row, bybit_depth_context, perp_symbol, row.get("mark_price"))
        row["perp_state"] = decision.get("status", "")
        row["direction_hint"] = decision.get("direction_hint", "")
        row["action"] = decision.get("action", "")
        if row.get("depth_note"):
            row["action"] += "；" + row["depth_note"]
        if row.get("funding_history_note"):
            row["action"] += "；" + row["funding_history_note"]
        return row
    except Exception as exc:
        return dict(base, status="fetch_failed", error=str(exc), direction_hint="观察", action="Bybit合约指标拉取失败")


def okx_context(
    symbol: str,
    okx_symbols: dict[str, dict[str, Any]],
    source_status: str,
    source_error: str,
    funding_cache: dict[str, Any],
) -> dict[str, Any]:
    inst_id = f"{symbol.upper()}-USDT-SWAP"
    base = {"venue": "okx_swap", "perp_symbol": inst_id}
    if source_status != "ok":
        return dict(base, status="source_failed", error=source_error, direction_hint="观察", action="OKX合约数据源不可用")
    exchange_info = okx_symbols.get(inst_id)
    if not exchange_info or str(exchange_info.get("state", "")).lower() != "live":
        return dict(base, status="not_listed", error="", direction_hint="不开", action="OKX未发现USDT永续")
    try:
        metrics = fetch_okx_symbol(inst_id)
        row = dict(base, status="ok", exchange_status=exchange_info.get("state", ""))
        row.update(metrics)
        attach_funding_history(
            row,
            funding_cache,
            f"okx_swap:{inst_id}",
            lambda: fetch_okx_funding_history(inst_id),
            fallback_interval_hours=row.get("funding_interval_hint_hours") or "8",
        )
        decision = classify_perp(row)
        attach_depth(row, okx_depth_context, inst_id, row.get("mark_price"), exchange_info)
        attach_liquidations(row, okx_liquidation_context, inst_id, exchange_info)
        row["perp_state"] = decision.get("status", "")
        row["direction_hint"] = decision.get("direction_hint", "")
        row["action"] = decision.get("action", "")
        if row.get("depth_note"):
            row["action"] += "；" + row["depth_note"]
        if row.get("liquidation_note"):
            row["action"] += "；" + row["liquidation_note"]
        if row.get("funding_history_note"):
            row["action"] += "；" + row["funding_history_note"]
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
        funding_rate = venue.get("current_funding_rate_8h")
        if funding_rate in ("", None):
            funding_rate = venue.get("last_funding_rate")
        funding_pct = decimal_from(funding_rate) * Decimal(100)
        notes.append(
            f"{venue.get('venue')} {hint} OI≈{fmt(venue.get('open_interest_usd'), '0.01')} funding8h {fmt(funding_pct, '0.0001')}%"
        )
        if venue.get("liquidation_note"):
            notes.append(f"{venue.get('venue')} {venue.get('liquidation_note')}")
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
    current_funding = decimal_from(current.get("current_funding_rate_8h") or current.get("last_funding_rate"))
    base_funding = decimal_from(baseline.get("current_funding_rate_8h") or baseline.get("last_funding_rate"))
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
    funding = decimal_from(row.get("current_funding_rate_8h") or row.get("last_funding_rate"))
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
    funding_cache = read_json(FUNDING_HISTORY_CACHE_PATH, {"schema": "perp_funding_history_cache.v1", "entries": {}})
    if not isinstance(funding_cache, dict):
        funding_cache = {"schema": "perp_funding_history_cache.v1", "entries": {}}
    funding_cache.setdefault("schema", "perp_funding_history_cache.v1")
    funding_cache.setdefault("entries", {})
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
        okx = okx_context(item["symbol"], okx_listed, okx_source_status, okx_source_error, funding_cache)
        bybit = bybit_context(item["symbol"], funding_cache)
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
                if row.get("funding_history_note"):
                    row["action"] += "；" + row["funding_history_note"]
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
                if row.get("funding_history_note"):
                    row["action"] += "；" + row["funding_history_note"]
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
            row = dict(base, status="ok", exchange_status=exchange_info.get("status", ""))
            row.update(metrics)
            attach_funding_history(
                row,
                funding_cache,
                f"binance_usdm:{symbol}",
                lambda: fetch_binance_funding_history(symbol),
            )
            decision = classify_perp(row)
            attach_depth(row, binance_depth_context, symbol, row.get("mark_price"))
            trend = trend_for_symbol(history, item["symbol"], row, generated_at)
            venue_notes = venue_signal_notes(extra_venues)
            row["perp_state"] = decision.get("status", "")
            row["direction_hint"] = decision.get("direction_hint", "")
            row["action"] = decision.get("action", "")
            if row.get("depth_note"):
                row["action"] += "；" + row["depth_note"]
            if row.get("funding_history_note"):
                row["action"] += "；" + row["funding_history_note"]
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
                if row.get("funding_history_note"):
                    row["action"] += "；" + row["funding_history_note"]
                row["binance_error"] = str(exc)
                row["extra_venues"] = other_venues
                row["listed_venues"] = listed_venue_names(row, other_venues)
                row["total_open_interest_usd"] = str(total_open_interest(row, other_venues))
                row.update(trend)
                rows.append(row)
            else:
                rows.append(dict(base, status="fetch_failed", error=str(exc), direction_hint="观察", action="合约指标拉取失败"))
    alert_liquidation_states = {"long_liquidation_pressure", "short_liquidation_pressure", "two_sided_liquidation"}
    alert_funding_history_states = {
        "sustained_long_crowding",
        "sustained_short_crowding",
        "funding_flip_positive",
        "funding_flip_negative",
        "recent_long_crowding",
        "recent_short_crowding",
    }
    alerts = [
        row
        for row in rows
        if row.get("status") == "ok"
        and (
            row.get("direction_hint") in {"拥挤", "可观察"}
            or bool(row.get("cross_venue_notes"))
            or row.get("depth_state") in {"thin_depth", "wide_spread", "ask_thin", "bid_thin"}
            or row.get("liquidation_state") in alert_liquidation_states
            or row.get("funding_history_state") in alert_funding_history_states
        )
    ]
    funding_cache["updated_at"] = generated_at
    write_json(FUNDING_HISTORY_CACHE_PATH, funding_cache)
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
        "| Symbol | Perp | Venues | Status | OI USD | Total OI | OI Δ | Funding 8h | Funding 24h | 24h Vol | 24h Chg | Depth | Liq | Trend | Action |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in snapshot["rows"]:
        funding_rate = row.get("current_funding_rate_8h")
        if funding_rate in ("", None):
            funding_rate = row.get("last_funding_rate")
        funding_pct = decimal_from(funding_rate) * Decimal(100)
        funding_24h = (
            f"{row.get('funding_history_state', '')} avg8h={fmt(decimal_from(row.get('funding_24h_avg_8h_rate')) * Decimal(100), '0.0001')}% "
            f"cum={fmt(decimal_from(row.get('funding_24h_cumulative_rate')) * Decimal(100), '0.0001')}%"
            if row.get("funding_history_status") in {"ok", "short_history"}
            else row.get("funding_history_status", "")
        )
        oi_delta_pct = decimal_from(row.get("oi_usd_delta_pct"))
        combined_action = row.get("action", "")
        if row.get("trend_action"):
            combined_action += f"; {row.get('trend_action')}"
        venues = ",".join(row.get("listed_venues") or [row.get("venue", "")])
        depth = ""
        if row.get("depth_status") == "ok":
            depth = (
                f"{row.get('depth_state')} bid={fmt(row.get('bid_depth_usd'), '0.01')} "
                f"ask={fmt(row.get('ask_depth_usd'), '0.01')} spread={fmt(row.get('spread_bps'), '0.01')}bps"
            )
        liquidation = ""
        if row.get("liquidation_status") == "ok":
            liquidation = (
                f"{row.get('liquidation_state')} long={fmt(row.get('long_liquidation_usd'), '0.01')} "
                f"short={fmt(row.get('short_liquidation_usd'), '0.01')}"
            )
        lines.append(
            f"| `{row.get('symbol')}` | `{row.get('perp_symbol')}` | {venues} | {row.get('status')}:{row.get('perp_state', '')} / {row.get('direction_hint', '')} | "
            f"{fmt(row.get('open_interest_usd'), '0.01')} | {fmt(row.get('total_open_interest_usd') or row.get('open_interest_usd'), '0.01')} | {fmt(oi_delta_pct, '0.01')}% | {fmt(funding_pct, '0.0001')}% | {funding_24h} | "
            f"{fmt(row.get('quote_volume_24h'), '0.01')} | {fmt(row.get('price_change_pct_24h'), '0.01')}% | "
            f"{depth} | {liquidation} | {row.get('trend_hint', '')} | {combined_action} |"
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
