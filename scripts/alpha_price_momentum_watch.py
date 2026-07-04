#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_price_momentum_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
ONCHAIN_FLOW_PATH = ROOT / "output" / "alpha_intraday_flow_watch" / "latest.json"
PERP_WATCH_PATH = ROOT / "output" / "perp_oi_funding_watch" / "latest.json"

TOKEN_LIST_URL = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
TRADE_BASE = "https://www.binance.com/bapi/defi/v1/public/alpha-trade"
TELEGRAM_LIMIT = 3200
UTC8 = timezone(timedelta(hours=8))


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def decimal_from(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


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


def http_json(url: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    full_url = url
    if params:
        full_url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_alpha_tokens() -> dict[str, dict[str, Any]]:
    data = http_json(TOKEN_LIST_URL, timeout=int(os.environ.get("ALPHA_PRICE_HTTP_TIMEOUT", "20")))
    rows = data.get("data") or []
    by_contract: dict[str, dict[str, Any]] = {}
    for row in rows:
        contract = norm(row.get("contractAddress"))
        if contract:
            by_contract[contract] = row
    return by_contract


def watchlist_events(token_by_contract: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    config = read_json(CONFIG_PATH, {"items": []})
    review_symbol = os.environ.get("ALPHA_PRICE_REVIEW_SYMBOL", "").upper()
    events: list[dict[str, Any]] = []
    for item in config.get("items", []):
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        if review_symbol and symbol != review_symbol:
            continue
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority", ""))
        if not priority.startswith(("P0", "P1", "P2")):
            continue
        contract = ""
        for row in item.get("contracts", []):
            if str(row.get("chain", "")).lower() == "bsc":
                contract = norm(row.get("address"))
                break
        if not contract:
            continue
        alpha = token_by_contract.get(contract)
        if not alpha or not alpha.get("alphaId"):
            continue
        events.append(
            {
                "symbol": symbol,
                "priority": priority,
                "contract": contract,
                "alpha_symbol": f"{alpha['alphaId']}USDT",
                "alpha": alpha,
            }
        )
    return events


def fetch_klines(alpha_symbol: str, interval: str, limit: int) -> list[list[Any]]:
    data = http_json(
        f"{TRADE_BASE}/klines",
        {"symbol": alpha_symbol, "interval": interval, "limit": limit},
        timeout=int(os.environ.get("ALPHA_PRICE_HTTP_TIMEOUT", "20")),
    )
    return data.get("data") or []


def fetch_ticker(alpha_symbol: str) -> dict[str, Any]:
    data = http_json(
        f"{TRADE_BASE}/ticker",
        {"symbol": alpha_symbol},
        timeout=int(os.environ.get("ALPHA_PRICE_HTTP_TIMEOUT", "20")),
    )
    return data.get("data") or {}


def fetch_depth(alpha_symbol: str) -> dict[str, Any]:
    try:
        data = http_json(
            f"{TRADE_BASE}/fullDepth",
            {"symbol": alpha_symbol, "limit": int(os.environ.get("ALPHA_PRICE_DEPTH_LIMIT", "1000"))},
            timeout=int(os.environ.get("ALPHA_PRICE_HTTP_TIMEOUT", "20")),
        )
        return data.get("data") or {}
    except Exception as exc:
        return {"error": str(exc)}


def ms_to_utc8(ms: Any) -> str:
    try:
        value = int(ms)
    except Exception:
        return ""
    return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(UTC8).strftime("%Y-%m-%d %H:%M")


def window_stats(rows: list[list[Any]], minutes: int) -> dict[str, Any]:
    if not rows:
        return {}
    selected = rows[-minutes:] if len(rows) >= minutes else rows
    open_price = decimal_from(selected[0][1])
    close_price = decimal_from(selected[-1][4])
    high_price = max(decimal_from(row[2]) for row in selected)
    low_price = min(decimal_from(row[3]) for row in selected)
    quote = sum((decimal_from(row[7]) for row in selected), Decimal(0))
    trades = sum((int(row[8]) for row in selected if str(row[8]).isdigit()), 0)
    high_pct = Decimal(0)
    low_pct = Decimal(0)
    close_pct = Decimal(0)
    retrace_pct = Decimal(0)
    if open_price > 0:
        high_pct = (high_price / open_price - Decimal(1)) * Decimal(100)
        low_pct = (low_price / open_price - Decimal(1)) * Decimal(100)
        close_pct = (close_price / open_price - Decimal(1)) * Decimal(100)
    if high_price > open_price:
        retrace_pct = max(Decimal(0), (high_price - close_price) / (high_price - open_price) * Decimal(100))
    return {
        "from_utc8": ms_to_utc8(selected[0][0]),
        "to_utc8": ms_to_utc8(selected[-1][0]),
        "open": str(open_price),
        "high": str(high_price),
        "low": str(low_price),
        "close": str(close_price),
        "high_pct": str(high_pct),
        "low_pct": str(low_pct),
        "close_pct": str(close_pct),
        "retrace_pct": str(retrace_pct),
        "quote_volume": str(quote),
        "trades": trades,
    }


def depth_stats(depth: dict[str, Any], last_price: Decimal) -> dict[str, Any]:
    if last_price <= 0 or depth.get("error"):
        return {"error": depth.get("error", "depth_unavailable")}
    bids = sorted(
        [(decimal_from(price), decimal_from(qty)) for price, qty in depth.get("bids", [])],
        key=lambda level: level[0],
        reverse=True,
    )
    asks = sorted([(decimal_from(price), decimal_from(qty)) for price, qty in depth.get("asks", [])], key=lambda level: level[0])
    result: dict[str, Any] = {"bids": len(bids), "asks": len(asks)}
    for pct in (Decimal("0.01"), Decimal("0.03"), Decimal("0.05"), Decimal("0.10")):
        ask_value = sum((price * qty for price, qty in asks if price <= last_price * (Decimal(1) + pct)), Decimal(0))
        bid_value = sum((price * qty for price, qty in bids if price >= last_price * (Decimal(1) - pct)), Decimal(0))
        key = str(int(pct * 100))
        result[f"ask_{key}pct_usdt"] = str(ask_value)
        result[f"bid_{key}pct_usdt"] = str(bid_value)
    if bids and asks:
        result["best_bid"] = str(bids[0][0])
        result["best_ask"] = str(asks[0][0])
        if asks[0][0] <= bids[0][0]:
            result["orderbook_status"] = "crossed_or_stale"
            result["spread_pct"] = ""
            result["microstructure_notes"] = ["盘口交叉或快照异常，盘口结构不下方向"]
            return result
        result["orderbook_status"] = "normal"
        result["spread_pct"] = str((asks[0][0] / bids[0][0] - Decimal(1)) * Decimal(100))
    top_n = int(os.environ.get("ALPHA_PRICE_DEPTH_TOP_N", "20"))
    top_bids = bids[:top_n]
    top_asks = asks[:top_n]
    top_bid_value = sum((price * qty for price, qty in top_bids), Decimal(0))
    top_ask_value = sum((price * qty for price, qty in top_asks), Decimal(0))
    result["top_depth_n"] = top_n
    result["top_bid_value_usdt"] = str(top_bid_value)
    result["top_ask_value_usdt"] = str(top_ask_value)
    if top_ask_value > 0:
        result["top_bid_ask_value_ratio"] = str(top_bid_value / top_ask_value)
    def top_concentration(levels: list[tuple[Decimal, Decimal]], total: Decimal) -> str:
        if not levels or total <= 0:
            return ""
        return str(max((price * qty for price, qty in levels), default=Decimal(0)) / total * Decimal(100))

    def repeated_qty(levels: list[tuple[Decimal, Decimal]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for _, qty in levels:
            if qty <= 0:
                continue
            key = format(qty.normalize(), "f")
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return {"qty": "", "count": 0}
        qty, count = max(counts.items(), key=lambda item: item[1])
        return {"qty": qty, "count": count}

    result["top_bid_concentration_pct"] = top_concentration(top_bids, top_bid_value)
    result["top_ask_concentration_pct"] = top_concentration(top_asks, top_ask_value)
    result["repeated_bid_qty"] = repeated_qty(top_bids)
    result["repeated_ask_qty"] = repeated_qty(top_asks)

    notes: list[str] = []
    repeated_ask_count = int(result["repeated_ask_qty"].get("count") or 0)
    repeated_bid_count = int(result["repeated_bid_qty"].get("count") or 0)
    bid_ask_ratio = decimal_from(result.get("top_bid_ask_value_ratio"))
    bid_concentration = decimal_from(result.get("top_bid_concentration_pct"))
    ask_concentration = decimal_from(result.get("top_ask_concentration_pct"))
    spread_pct = decimal_from(result.get("spread_pct"))
    if repeated_ask_count >= int(os.environ.get("ALPHA_PRICE_MECHANICAL_QTY_COUNT", "5")):
        notes.append(f"卖盘重复数量梯队({result['repeated_ask_qty'].get('qty')} x{repeated_ask_count})")
    if repeated_bid_count >= int(os.environ.get("ALPHA_PRICE_MECHANICAL_QTY_COUNT", "5")):
        notes.append(f"买盘重复数量梯队({result['repeated_bid_qty'].get('qty')} x{repeated_bid_count})")
    if bid_ask_ratio >= Decimal(os.environ.get("ALPHA_PRICE_VISIBLE_BID_ASK_SKEW", "10")):
        notes.append("可见买盘远厚于卖盘，只能说明显示盘口失衡")
    if bid_concentration >= Decimal(os.environ.get("ALPHA_PRICE_TOP_LEVEL_CONCENTRATION_PCT", "50")):
        notes.append("买盘集中在少数档位，承接质量需看成交")
    if ask_concentration >= Decimal(os.environ.get("ALPHA_PRICE_TOP_LEVEL_CONCENTRATION_PCT", "50")):
        notes.append("卖盘集中在少数档位，卖压判断需看撤挂和成交")
    if spread_pct >= Decimal(os.environ.get("ALPHA_PRICE_WIDE_SPREAD_PCT", "1")):
        notes.append(f"价差偏宽({spread_pct:.2f}%)")
    result["microstructure_notes"] = notes
    return result


def depth_amounts_reliable(depth: dict[str, Any]) -> bool:
    return depth.get("orderbook_status") != "crossed_or_stale"


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def latest_onchain_flow(symbol: str) -> dict[str, Any]:
    snapshot = read_json(ONCHAIN_FLOW_PATH, {})
    generated_at = parse_iso(str(snapshot.get("generated_at") or ""))
    max_age = timedelta(minutes=int(os.environ.get("ALPHA_PRICE_ONCHAIN_FLOW_MAX_AGE_MINUTES", "20")))
    stale = True
    if generated_at:
        stale = now_utc() - generated_at.astimezone(timezone.utc) > max_age
    for event in snapshot.get("events", []):
        if str(event.get("symbol", "")).upper() != symbol.upper():
            continue
        analysis = event.get("analysis", {})
        total_buy = decimal_from(analysis.get("total_buy_quote"))
        total_sell = decimal_from(analysis.get("total_sell_quote"))
        return {
            "status": "stale" if stale else "ok",
            "generated_at": snapshot.get("generated_at", ""),
            "window_blocks": analysis.get("window_blocks", ""),
            "onchain_gross_quote": str(total_buy + total_sell),
            "net_buy_quote": analysis.get("net_buy_quote", "0"),
            "net_sell_quote": analysis.get("net_sell_quote", "0"),
            "trade_signal": analysis.get("trade_signal", ""),
        }
    return {"status": "missing", "onchain_gross_quote": "0"}


def latest_perp_context(symbol: str) -> dict[str, Any]:
    snapshot = read_json(PERP_WATCH_PATH, {})
    generated_at = parse_iso(str(snapshot.get("generated_at") or ""))
    max_age = timedelta(minutes=int(os.environ.get("ALPHA_PRICE_PERP_MAX_AGE_MINUTES", "90")))
    stale = True
    if generated_at:
        stale = now_utc() - generated_at.astimezone(timezone.utc) > max_age
    for row in snapshot.get("rows", []):
        if str(row.get("symbol", "")).upper() != symbol.upper():
            continue
        return {
            "snapshot_status": "stale" if stale else "ok",
            "generated_at": snapshot.get("generated_at", ""),
            "venue": row.get("venue", ""),
            "perp_symbol": row.get("perp_symbol", ""),
            "status": row.get("status", ""),
            "perp_state": row.get("perp_state", ""),
            "direction_hint": row.get("direction_hint", ""),
            "action": row.get("action", ""),
            "open_interest_usd": row.get("open_interest_usd", ""),
            "total_open_interest_usd": row.get("total_open_interest_usd", ""),
            "listed_venues": row.get("listed_venues", []),
            "last_funding_rate": row.get("last_funding_rate", ""),
            "quote_volume_24h": row.get("quote_volume_24h", ""),
            "price_change_pct_24h": row.get("price_change_pct_24h", ""),
            "oi_usd_delta_pct": row.get("oi_usd_delta_pct", ""),
            "previous_oi_usd_delta_pct": row.get("previous_oi_usd_delta_pct", ""),
            "mark_price_delta_pct": row.get("mark_price_delta_pct", ""),
            "funding_rate_delta": row.get("funding_rate_delta", ""),
            "trend_status": row.get("trend_status", ""),
            "trend_hint": row.get("trend_hint", ""),
            "trend_action": row.get("trend_action", ""),
            "baseline_age_minutes": row.get("baseline_age_minutes", ""),
            "error": row.get("error", ""),
        }
    return {"snapshot_status": "missing", "status": "missing", "action": "合约/OI快照缺失"}


def venue_classification(alpha_quote: Decimal, onchain_flow: dict[str, Any]) -> dict[str, Any]:
    floor = Decimal(os.environ.get("ALPHA_VENUE_VOL_FLOOR", "50000"))
    onchain_gross = decimal_from(onchain_flow.get("onchain_gross_quote"))
    alpha_netflow_reliable = os.environ.get("ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT", "0") == "1"
    if alpha_quote < floor:
        return {
            "venue_class": "INSUFFICIENT_DATA",
            "coverage": "NO_DIRECTION",
            "onchain_netflow_reliable": False,
            "alpha_quote_volume": str(alpha_quote),
            "onchain_gross_quote": str(onchain_gross),
            "alpha_onchain_ratio": "",
            "note": "Alpha成交额不足，不产出方向",
        }
    if onchain_flow.get("status") != "ok":
        return {
            "venue_class": "UNKNOWN",
            "coverage": "PRICE_ONLY",
            "onchain_netflow_reliable": False,
            "alpha_quote_volume": str(alpha_quote),
            "onchain_gross_quote": str(onchain_gross),
            "alpha_onchain_ratio": "",
            "note": "链上盘中流缺失或过期，价格层只能作注意力提醒",
        }
    ratio = alpha_quote / max(onchain_gross, Decimal(1))
    if ratio >= Decimal(os.environ.get("ALPHA_DOMINANT_RATIO", "10")):
        venue_class = "ALPHA_DOMINANT"
        coverage = "ONCHAIN_PARTIAL_NEGATIVE_ONLY" if alpha_netflow_reliable else "ONCHAIN_NETFLOW_UNRELIABLE"
        note = "Alpha成交主导；链上确认卖出仍算偏空" if alpha_netflow_reliable else "Alpha成交主导；链上净流层暂不产出方向"
    elif ratio >= Decimal(os.environ.get("ALPHA_MIXED_RATIO", "3")):
        venue_class = "MIXED"
        coverage = "ONCHAIN_PARTIAL"
        note = "Alpha和链上混合驱动；链上信号需降权"
    else:
        venue_class = "ONCHAIN_NATIVE"
        coverage = "ONCHAIN_FULLER"
        note = "链上成交覆盖度较高"
    return {
        "venue_class": venue_class,
        "coverage": coverage,
        "onchain_netflow_reliable": False if venue_class == "ALPHA_DOMINANT" and not alpha_netflow_reliable else venue_class != "UNKNOWN",
        "alpha_quote_volume": str(alpha_quote),
        "onchain_gross_quote": str(onchain_gross),
        "alpha_onchain_ratio": str(ratio),
        "note": note,
    }


def perp_action_summary(perp: dict[str, Any]) -> str:
    status = perp.get("snapshot_status")
    if status == "missing":
        return "合约/OI快照缺失"
    if status == "stale":
        return "合约快照过期，只作背景"
    if perp.get("status") != "ok":
        return perp.get("action") or "合约层不可用"

    trend = perp.get("trend_hint")
    if trend == "多头增量":
        return "偏多观察；持仓看承接，空仓等回踩和现货净买确认"
    if trend == "空头增量":
        return "偏空防守；持仓减风险，空仓等反抽弱化"
    if trend == "降杠杆":
        return "降杠杆；不把价格波动单独当入场依据"

    perp_state = perp.get("perp_state")
    funding = decimal_from(perp.get("last_funding_rate"))
    if perp_state == "crowded_funding":
        if funding > 0:
            return "多头拥挤；持仓防回撤，空仓不追高"
        return "空头拥挤；等现货止跌和回补确认"
    if perp.get("direction_hint") == "可观察":
        return "可观察；只和价格、链上流向同向时使用"
    return perp.get("action") or "合约层只作背景"


def analyze_event(event: dict[str, Any]) -> dict[str, Any]:
    rows_1m = fetch_klines(event["alpha_symbol"], "1m", int(os.environ.get("ALPHA_PRICE_KLINE_LIMIT", "180")))
    ticker = fetch_ticker(event["alpha_symbol"])
    last_price = decimal_from(ticker.get("lastPrice") or event["alpha"].get("price"))
    depth = depth_stats(fetch_depth(event["alpha_symbol"]), last_price)
    w15 = window_stats(rows_1m, 15)
    w60 = window_stats(rows_1m, 60)
    onchain_flow = latest_onchain_flow(event["symbol"])
    venue = venue_classification(decimal_from(w60.get("quote_volume")), onchain_flow)
    perp_context = latest_perp_context(event["symbol"])

    spike_threshold = Decimal(os.environ.get("ALPHA_PRICE_15M_SPIKE_PCT", "15"))
    close_threshold = Decimal(os.environ.get("ALPHA_PRICE_15M_CLOSE_PCT", "8"))
    drop_threshold = Decimal(os.environ.get("ALPHA_PRICE_15M_DROP_PCT", "8"))
    drawdown_threshold = Decimal(os.environ.get("ALPHA_PRICE_15M_DRAWDOWN_PCT", "15"))
    volume_threshold = Decimal(os.environ.get("ALPHA_PRICE_QUOTE_ALERT", "200000"))
    shallow_threshold = Decimal(os.environ.get("ALPHA_PRICE_SHALLOW_ASK_USDT", "50000"))

    high_pct = decimal_from(w15.get("high_pct"))
    low_pct = decimal_from(w15.get("low_pct"))
    close_pct = decimal_from(w15.get("close_pct"))
    quote = decimal_from(w15.get("quote_volume"))
    retrace = decimal_from(w15.get("retrace_pct"))
    ask_5 = decimal_from(depth.get("ask_5pct_usdt"))

    direction = "观察"
    trade_signal = "无价格异动"
    spot_action = "观察"
    reason = "未触发价格/成交额阈值"
    alpha_dominant = venue.get("venue_class") == "ALPHA_DOMINANT"
    if quote >= volume_threshold and close_pct <= -drop_threshold:
        direction = "放量走弱"
        trade_signal = "Alpha 放量收跌；卖出/减仓观察"
        spot_action = "持仓减风险；空仓不接，等止跌承接"
        reason = f"15m close {fmt(close_pct)}%，低点 {fmt(low_pct)}%，成交额≈{fmt(quote)} USDT"
    elif quote >= volume_threshold and low_pct <= -drawdown_threshold:
        direction = "放量下插"
        trade_signal = "Alpha 放量下插；不抄底"
        spot_action = "持仓看反抽减风险；空仓等收回关键位"
        reason = f"15m low {fmt(low_pct)}%，收盘 {fmt(close_pct)}%，成交额≈{fmt(quote)} USDT"
    elif quote >= volume_threshold and high_pct >= spike_threshold:
        if alpha_dominant:
            direction = "Alpha主导/观察"
            trade_signal = "Alpha 价格放量异动；不追"
            spot_action = "有仓看回吐减仓；空仓等真实净敞口"
        elif retrace >= Decimal("55"):
            direction = "冲高回落"
            trade_signal = "Alpha 价格急拉后回吐；不追"
            spot_action = "有仓按强弱减仓；空仓不追尖刺"
        else:
            direction = "观察偏多"
            trade_signal = "Alpha 价格放量上冲；等链上净买或回踩承接"
            spot_action = "不追高；只看回踩承接"
        reason = f"15m high +{fmt(high_pct)}%，收盘 {fmt(close_pct)}%，成交额≈{fmt(quote)} USDT"
    elif quote >= volume_threshold and close_pct >= close_threshold:
        if alpha_dominant:
            direction = "Alpha主导/观察"
            trade_signal = "Alpha 收盘价放量走强；只作注意力提醒"
            spot_action = "不追；等回踩和链上负面证据排除"
        else:
            direction = "观察偏多"
            trade_signal = "Alpha 收盘价放量走强；等待链上确认"
            spot_action = "小仓只等回踩，不追市价"
        reason = f"15m close +{fmt(close_pct)}%，成交额≈{fmt(quote)} USDT"
    if depth_amounts_reliable(depth) and ask_5 and ask_5 < shallow_threshold:
        reason += f"；当前 +5% 卖盘约 {fmt(ask_5)} USDT，盘口偏薄"
    micro_notes = depth.get("microstructure_notes") or []
    if micro_notes:
        reason += "；盘口结构: " + "，".join(micro_notes[:3])
    if venue.get("venue_class") == "ALPHA_DOMINANT":
        reason += f"；Alpha/链上成交比≈{fmt(venue.get('alpha_onchain_ratio'))}，链上覆盖不完整"
    if perp_context.get("snapshot_status") == "ok" and perp_context.get("direction_hint") in {"拥挤", "可观察"}:
        reason += f"；合约层{perp_context.get('direction_hint')}，{perp_context.get('action')}"

    return {
        "source": "binance_alpha_public_api",
        "alpha_symbol": event["alpha_symbol"],
        "last_price": str(last_price),
        "ticker": ticker,
        "window_15m": w15,
        "window_60m": w60,
        "depth": depth,
        "onchain_flow": onchain_flow,
        "perp_context": perp_context,
        "venue": venue,
        "direction": direction,
        "trade_signal": trade_signal,
        "spot_action": spot_action,
        "perp_action": perp_action_summary(perp_context),
        "reason": reason,
    }


def scan() -> dict[str, Any]:
    token_by_contract = load_alpha_tokens()
    events = []
    for event in watchlist_events(token_by_contract):
        try:
            analysis = analyze_event(event)
        except Exception as exc:
            analysis = {
                "source": "binance_alpha_public_api",
                "direction": "数据缺口",
                "trade_signal": "Alpha 价格层读取失败",
                "spot_action": "只看链上监控，不用价格层下判断",
                "perp_action": "不开",
                "reason": str(exc),
            }
        events.append({**event, "analysis": analysis})
    key_pairs = [pair for event in events for pair in event_alert_key_pairs(event)]
    keys = [key for key, _ in key_pairs]
    seen = set(read_json(SEEN_PATH, []))
    new_keys = unseen_alert_keys(key_pairs, seen)
    return {
        "generated_at": now_iso(),
        "event_count": len(events),
        "alert_count": len(keys),
        "new_alert_count": len(new_keys),
        "events": events,
    }


def event_alert_keys(event: dict[str, Any]) -> list[str]:
    return [key for key, _ in event_alert_key_pairs(event)]


def event_alert_key_pairs(event: dict[str, Any]) -> list[tuple[str, list[str]]]:
    analysis = event.get("analysis", {})
    w15 = analysis.get("window_15m", {})
    high_pct = decimal_from(w15.get("high_pct"))
    low_pct = decimal_from(w15.get("low_pct"))
    close_pct = decimal_from(w15.get("close_pct"))
    quote = decimal_from(w15.get("quote_volume"))
    time_bucket = alert_time_bucket(
        str(w15.get("to_utc8") or ""),
        int(os.environ.get("ALPHA_PRICE_ALERT_TIME_BUCKET_MINUTES", "60")),
    )
    pairs: list[tuple[str, list[str]]] = []
    if quote < Decimal(os.environ.get("ALPHA_PRICE_QUOTE_ALERT", "200000")):
        price_alert = False
    else:
        price_alert = (
            high_pct >= Decimal(os.environ.get("ALPHA_PRICE_15M_SPIKE_PCT", "15"))
            or close_pct >= Decimal(os.environ.get("ALPHA_PRICE_15M_CLOSE_PCT", "8"))
            or close_pct <= -Decimal(os.environ.get("ALPHA_PRICE_15M_DROP_PCT", "8"))
            or low_pct <= -Decimal(os.environ.get("ALPHA_PRICE_15M_DRAWDOWN_PCT", "15"))
        )
    if price_alert:
        base_parts = [
            "alpha_price",
            event["symbol"],
            analysis.get("direction", ""),
            bucket(high_pct, Decimal("5")),
            bucket(abs(low_pct), Decimal("5")),
            bucket(close_pct, Decimal("5")),
            bucket(quote, Decimal("100000")),
        ]
        pairs.append(
            (
                "|".join(base_parts + [time_bucket]),
                ["|".join(base_parts + [str(w15.get("from_utc8", "")), str(w15.get("to_utc8", ""))])],
            )
        )

    perp = analysis.get("perp_context", {})
    if (
        perp.get("snapshot_status") == "ok"
        and perp.get("status") == "ok"
        and perp.get("trend_status") == "ok"
        and perp.get("trend_hint") in {"多头增量", "空头增量", "降杠杆"}
    ):
        base_parts = [
            "perp_trend",
            event["symbol"],
            str(perp.get("trend_hint", "")),
            bucket(decimal_from(perp.get("oi_usd_delta_pct")), Decimal("5")),
            bucket(decimal_from(perp.get("mark_price_delta_pct")), Decimal("5")),
            bucket(decimal_from(perp.get("total_open_interest_usd") or perp.get("open_interest_usd")), Decimal("1000000")),
        ]
        pairs.append(
            (
                "|".join(base_parts),
                ["|".join(base_parts + [str(perp.get("baseline_age_minutes", ""))])],
            )
        )
    return pairs


def unseen_alert_keys(key_pairs: list[tuple[str, list[str]]], seen: set[str]) -> list[str]:
    return [key for key, legacy_keys in key_pairs if key not in seen and not any(legacy in seen for legacy in legacy_keys)]


def bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    return str((value // step) * step)


def alert_time_bucket(value: str, minutes: int) -> str:
    if minutes <= 0:
        return "all"
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC8)
    except Exception:
        return "unknown"
    day_minute = dt.hour * 60 + dt.minute
    floored = (day_minute // minutes) * minutes
    bucket_dt = dt.replace(hour=floored // 60, minute=floored % 60)
    return bucket_dt.strftime("%Y-%m-%d %H:%M")


def fmt(value: Any, places: int = 2) -> str:
    number = decimal_from(value)
    if number == number.to_integral():
        return f"{number:,.0f}"
    return f"{number:,.{places}f}"


def perp_summary(perp: dict[str, Any]) -> str:
    status = perp.get("snapshot_status")
    if status == "missing":
        return "合约/OI快照缺失"
    if status == "stale":
        return f"{perp.get('perp_symbol', '-')}: 快照过期；{perp.get('action', '')}"
    if perp.get("status") != "ok":
        return f"{perp.get('perp_symbol', '-')}: {perp.get('status', '')}；{perp.get('action', '')}"
    funding_pct = decimal_from(perp.get("last_funding_rate")) * Decimal(100)
    oi_delta_pct = decimal_from(perp.get("oi_usd_delta_pct"))
    price_delta_pct = decimal_from(perp.get("mark_price_delta_pct"))
    venues = ",".join(perp.get("listed_venues") or [perp.get("venue", "")])
    total_oi = perp.get("total_open_interest_usd") or perp.get("open_interest_usd")
    trend_tail = ""
    if perp.get("trend_status") == "ok" and perp.get("trend_action"):
        trend_tail = f"；{perp.get('baseline_age_minutes') or '?'}m OI {fmt(oi_delta_pct)}%，价格 {fmt(price_delta_pct)}%；{perp.get('trend_hint', '')}: {perp.get('trend_action')}"
    return (
        f"{perp.get('perp_symbol', '-')}: {perp.get('perp_state', '')}/{perp.get('direction_hint', '')}；"
        f"场地 {venues or '-'}；主OI≈{fmt(perp.get('open_interest_usd'))} USDT；总OI≈{fmt(total_oi)} USDT；资金费率 {fmt(funding_pct, 4)}%；"
        f"24h量≈{fmt(perp.get('quote_volume_24h'))}；{perp.get('action', '')}{trend_tail}"
    )


def event_effective_summary(event: dict[str, Any]) -> str:
    a = event.get("analysis", {})
    perp = a.get("perp_context", {})
    symbol = event.get("symbol", "-")
    if (
        a.get("trade_signal") == "无价格异动"
        and perp.get("snapshot_status", "ok") == "ok"
        and perp.get("trend_hint") in {"多头增量", "空头增量", "降杠杆"}
    ):
        return f"{symbol}: 合约{perp.get('trend_hint')}；{a.get('perp_action', '')}"
    reason = a.get("reason") or ""
    if reason:
        return f"{symbol}: {a.get('trade_signal', '观察')}；{reason}"
    return f"{symbol}: {a.get('trade_signal', '观察')}"


def effective_summary(events: list[dict[str, Any]]) -> str:
    if not events:
        return "没有 Alpha 价格扫描项目"
    return f"扫描 {min(len(events), 4)} 个项目；所有项目总结在文末"


def project_summary_lines(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return []
    lines = ["项目总结汇总:"]
    for event in events:
        a = event.get("analysis", {})
        symbol = str(event.get("symbol", "-"))
        summary = event_effective_summary(event)
        prefix = f"{symbol}: "
        if summary.startswith(prefix):
            summary = summary[len(prefix) :]
        lines.extend(
            [
                f"- {symbol}: {summary}",
                f"  方向: {a.get('direction')}；信号: {a.get('trade_signal')}；现货: {a.get('spot_action')}；合约: {a.get('perp_action')}",
            ]
        )
    return lines


def depth_line(depth: dict[str, Any]) -> str:
    if not depth_amounts_reliable(depth):
        return "盘口: 交叉/过期快照，深度金额不采用"
    return f"盘口: +5%卖盘≈{fmt(depth.get('ask_5pct_usdt'))} USDT；-5%买盘≈{fmt(depth.get('bid_5pct_usdt'))} USDT"


def telegram_text(snapshot: dict[str, Any]) -> str:
    events = snapshot.get("events", [])[:4]
    lines = [
        "Alpha 价格动量监控",
        f"新增告警: {snapshot.get('new_alert_count', 0)}",
        f"有效总结: {effective_summary(events)}",
        "",
    ]
    for event in events:
        a = event.get("analysis", {})
        w15 = a.get("window_15m", {})
        depth = a.get("depth", {})
        venue = a.get("venue", {})
        perp = a.get("perp_context", {})
        lines.extend(
            [
                f"{event['symbol']} | {event.get('priority')}",
                f"成交场地: {venue.get('venue_class', 'UNKNOWN')}；覆盖: {venue.get('coverage', '')}",
                f"15m: 开 {w15.get('open')} 高 {w15.get('high')} 低 {w15.get('low')} 收 {w15.get('close')}；成交≈{fmt(w15.get('quote_volume'))} USDT",
                depth_line(depth),
                f"盘口结构: {'；'.join(depth.get('microstructure_notes') or ['无明显重复梯队'])}",
                f"合约层: {perp_summary(perp)}",
                "说明: Alpha主导时，链上缺失类证据不得用于偏多；链上确认卖出仍算偏空证据",
                "",
            ]
        )
    lines.extend(project_summary_lines(events))
    return "\n".join(lines).strip()


def push_signature(snapshot: dict[str, Any]) -> str:
    keys = [key for event in snapshot.get("events", [])[:4] for key in event_alert_keys(event)]
    return "\n".join(sorted(keys))


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ALPHA_PRICE_REPEAT_SUPPRESS_MINUTES", "30"))
    if ttl_minutes <= 0:
        return False
    last = read_json(LAST_PUSH_PATH, {})
    if last.get("signature") != push_signature(snapshot):
        return False
    try:
        sent_at = datetime.fromisoformat(str(last.get("sent_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    return now_utc() - sent_at.astimezone(timezone.utc) < timedelta(minutes=ttl_minutes)


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ALPHA_PRICE_MOMENTUM_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    key_pairs = [pair for event in snapshot.get("events", []) for pair in event_alert_key_pairs(event)]
    keys = [key for key, _ in key_pairs]
    if not keys:
        return
    seen = set(read_json(SEEN_PATH, []))
    new_keys = unseen_alert_keys(key_pairs, seen)
    if not new_keys and os.environ.get("ALPHA_PRICE_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ALPHA_PRICE_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    payload = {"chat_id": chat_id, "text": telegram_text(snapshot)[:TELEGRAM_LIMIT], "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20):
        pass
    write_json(SEEN_PATH, sorted(seen | set(keys)))
    write_json(LAST_PUSH_PATH, {"sent_at": now_iso(), "signature": push_signature(snapshot)})


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Price Momentum Watch",
        "",
        f"- generated_at: `{snapshot.get('generated_at')}`",
        f"- event_count: `{snapshot.get('event_count')}`",
        f"- alert_count: `{snapshot.get('alert_count')}`",
        f"- new_alert_count: `{snapshot.get('new_alert_count')}`",
        "",
    ]
    for event in snapshot.get("events", []):
        a = event.get("analysis", {})
        depth = a.get("depth", {})
        venue = a.get("venue", {})
        onchain = a.get("onchain_flow", {})
        perp = a.get("perp_context", {})
        for window_name in ("window_15m", "window_60m"):
            window = a.get(window_name, {})
            lines.extend(
                [
                    f"## {event['symbol']} {window_name}",
                    "",
                    f"- alpha_symbol: `{a.get('alpha_symbol')}`",
                    f"- direction: {a.get('direction')}",
                    f"- trade_signal: {a.get('trade_signal')}",
                    f"- spot_action: {a.get('spot_action')}",
                    f"- perp_action: {a.get('perp_action')}",
                    f"- reason: {a.get('reason')}",
                    f"- venue_class: `{venue.get('venue_class')}`",
                    f"- coverage: `{venue.get('coverage')}`",
                    f"- alpha_onchain_ratio: `{venue.get('alpha_onchain_ratio')}`",
                    f"- onchain_gross_quote: `{onchain.get('onchain_gross_quote')}`",
                    f"- onchain_flow_status: `{onchain.get('status')}`",
                    f"- from_utc8: `{window.get('from_utc8')}`",
                    f"- to_utc8: `{window.get('to_utc8')}`",
                    f"- open/high/low/close: `{window.get('open')}` / `{window.get('high')}` / `{window.get('low')}` / `{window.get('close')}`",
                    f"- high_pct: `{window.get('high_pct')}`",
                    f"- low_pct: `{window.get('low_pct')}`",
                    f"- close_pct: `{window.get('close_pct')}`",
                    f"- retrace_pct: `{window.get('retrace_pct')}`",
                    f"- quote_volume: `{window.get('quote_volume')}`",
                    f"- trades: `{window.get('trades')}`",
                    f"- perp_summary: {perp_summary(perp)}",
                    "",
                ]
            )
        lines.extend(
            [
                "### Depth",
                "",
                f"- last_price: `{a.get('last_price')}`",
                f"- ask_1pct_usdt: `{depth.get('ask_1pct_usdt')}`",
                f"- ask_3pct_usdt: `{depth.get('ask_3pct_usdt')}`",
                f"- ask_5pct_usdt: `{depth.get('ask_5pct_usdt')}`",
                f"- bid_5pct_usdt: `{depth.get('bid_5pct_usdt')}`",
                f"- top_bid_value_usdt: `{depth.get('top_bid_value_usdt')}`",
                f"- top_ask_value_usdt: `{depth.get('top_ask_value_usdt')}`",
                f"- top_bid_ask_value_ratio: `{depth.get('top_bid_ask_value_ratio')}`",
                f"- top_bid_concentration_pct: `{depth.get('top_bid_concentration_pct')}`",
                f"- top_ask_concentration_pct: `{depth.get('top_ask_concentration_pct')}`",
                f"- repeated_bid_qty: `{depth.get('repeated_bid_qty')}`",
                f"- repeated_ask_qty: `{depth.get('repeated_ask_qty')}`",
                f"- microstructure_notes: `{depth.get('microstructure_notes')}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = scan()
    write_json(LATEST_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    maybe_send_telegram(snapshot)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(f"events={snapshot['event_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
