#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "surf_aux_market_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
QUOTA_STATE_PATH = OUT_DIR / "quota_state.json"
UTC8 = timezone(timedelta(hours=8))


def now_utc() -> datetime:
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


def dec(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def fmt_decimal(value: Any, places: int = 4) -> str:
    number = dec(value)
    if number == 0:
        return "0"
    quant = Decimal(10) ** -places
    return f"{number.quantize(quant):f}"


def pct(first: Decimal, last: Decimal) -> Decimal:
    if first <= 0:
        return Decimal(0)
    return (last / first - Decimal(1)) * Decimal(100)


def utc8_from_ts(value: Any) -> str:
    try:
        ts = int(value)
    except Exception:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(UTC8).strftime("%Y-%m-%d %H:%M")


def surf_bin() -> str:
    configured = os.environ.get("SURF_BIN", "").strip()
    if configured:
        return configured
    local_bin = Path.home() / ".local" / "bin" / "surf"
    if local_bin.exists():
        return str(local_bin)
    return "surf"


def today_utc() -> str:
    return now_utc().strftime("%Y-%m-%d")


def error_text(error: Any) -> str:
    if isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False)
    return str(error or "")


def is_quota_error(error: Any) -> bool:
    text = error_text(error)
    return "FREE_QUOTA_EXHAUSTED" in text or "free daily credit has been exhausted" in text


def quota_blocked() -> bool:
    state = read_json(QUOTA_STATE_PATH, {})
    return state.get("exhausted_on_utc") == today_utc()


def mark_quota_exhausted(error: Any) -> None:
    write_json(
        QUOTA_STATE_PATH,
        {
            "exhausted_on_utc": today_utc(),
            "updated_at": now_iso(),
            "error": error,
        },
    )


def run_surf(args: list[str], timeout: int) -> dict[str, Any]:
    if quota_blocked():
        return {"ok": False, "error": "surf_quota_exhausted_today", "data": []}
    command = [surf_bin(), *args, "--json", "--quiet"]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "error": "surf_cli_missing", "data": []}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "data": []}
    if result.returncode != 0:
        error = (result.stderr or result.stdout).strip()[:600]
        if is_quota_error(error):
            mark_quota_exhausted(error)
        return {"ok": False, "error": error, "data": []}
    try:
        doc = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"invalid_json: {exc}", "data": []}
    if doc.get("error"):
        if is_quota_error(doc.get("error")):
            mark_quota_exhausted(doc.get("error"))
        return {"ok": False, "error": doc.get("error"), "data": doc.get("data") or [], "meta": doc.get("meta") or {}}
    return {"ok": True, "data": doc.get("data") or [], "meta": doc.get("meta") or {}, "raw": doc}


def load_watchlist(args: argparse.Namespace) -> list[dict[str, Any]]:
    config = read_json(Path(args.config), {"items": []})
    review_symbol = (args.symbol or os.environ.get("SURF_AUX_SYMBOL", "")).strip().upper()
    rows: list[dict[str, Any]] = []
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
        contract = ""
        chain = ""
        for row in item.get("contracts", []):
            candidate_chain = str(row.get("chain") or "").lower()
            if candidate_chain in {"bsc", "base", "ethereum", "arbitrum", "polygon", "optimism", "avalanche"}:
                contract = str(row.get("address") or "").strip()
                chain = candidate_chain
                if candidate_chain == "bsc":
                    break
        rows.append(
            {
                "symbol": symbol,
                "name": item.get("name") or item.get("project") or symbol,
                "priority": priority,
                "chain": chain,
                "contract": contract,
            }
        )
    max_projects = int(os.environ.get("SURF_AUX_MAX_PROJECTS", str(args.max_projects)))
    return rows[:max_projects]


def filter_symbol_markets(symbol: str, markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in markets:
        base = str(row.get("base") or "").upper()
        pair = str(row.get("pair") or "").upper()
        if base == symbol or pair.startswith(f"{symbol}/"):
            output.append(row)
    return output


def exchange_markets(symbol: str, timeout: int) -> dict[str, Any]:
    doc = run_surf(["exchange-markets", "--search", symbol, "--quote", "USDT", "--limit", "100"], timeout)
    rows = filter_symbol_markets(symbol, doc.get("data") or []) if doc.get("ok") else []
    spot = [row for row in rows if str(row.get("type") or "").lower() == "spot" and row.get("active") is not False]
    swap = [row for row in rows if str(row.get("type") or "").lower() in {"swap", "perpetual", "perp"} and row.get("active") is not False]
    return {
        "ok": bool(doc.get("ok")),
        "error": doc.get("error", ""),
        "spot_markets": spot,
        "swap_markets": swap,
        "spot_venues": sorted({str(row.get("exchange") or "") for row in spot if row.get("exchange")}),
        "swap_venues": sorted({str(row.get("exchange") or "") for row in swap if row.get("exchange")}),
        "credits_used": (doc.get("meta") or {}).get("credits_used", 0),
    }


def prices_for_markets(markets: list[dict[str, Any]], market_type: str, limit: int, timeout: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for market in markets:
        exchange = str(market.get("exchange") or "")
        pair = str(market.get("pair") or "")
        if not exchange or not pair:
            continue
        key = (exchange, pair)
        if key in seen:
            continue
        seen.add(key)
        doc = run_surf(
            ["exchange-price", "--exchange", exchange, "--pair", pair, "--type", market_type],
            timeout,
        )
        if doc.get("ok") and doc.get("data"):
            row = dict(doc["data"][0])
            row["credits_used"] = (doc.get("meta") or {}).get("credits_used", 0)
            rows.append(row)
        else:
            rows.append({"exchange": exchange, "pair": pair, "type": market_type, "error": doc.get("error", "no_data")})
        if len(rows) >= limit:
            break
    return rows


def klines_for_market(markets: list[dict[str, Any]], market_type: str, timeout: int) -> dict[str, Any]:
    if not markets:
        return {"ok": False, "error": "no_market"}
    errors = []
    for market in markets[:5]:
        exchange = str(market.get("exchange") or "")
        pair = str(market.get("pair") or "")
        if not exchange or not pair:
            errors.append("bad_market")
            continue
        doc = run_surf(
            ["exchange-klines", "--exchange", exchange, "--pair", pair, "--type", market_type, "--interval", "5m", "--limit", "48"],
            timeout,
        )
        if not doc.get("ok") or not doc.get("data"):
            errors.append(f"{exchange}:{doc.get('error', 'no_data')}")
            continue
        payload = doc["data"][0]
        candles = payload.get("candles") or []
        if not candles:
            errors.append(f"{exchange}:empty_candles")
            continue
        ordered = sorted(candles, key=lambda row: int(row.get("timestamp") or 0))
        first = dec(ordered[0].get("open"))
        last = dec(ordered[-1].get("close"))
        high = max(dec(row.get("high")) for row in ordered)
        low = min(dec(row.get("low")) for row in ordered)
        volume_base = sum(dec(row.get("volume")) for row in ordered)
        return {
            "ok": True,
            "exchange": exchange,
            "pair": pair,
            "type": market_type,
            "from_utc8": utc8_from_ts(ordered[0].get("timestamp")),
            "to_utc8": utc8_from_ts(ordered[-1].get("timestamp")),
            "open": str(first),
            "high": str(high),
            "low": str(low),
            "close": str(last),
            "change_pct": str(pct(first, last)),
            "high_from_open_pct": str(pct(first, high)),
            "volume_base": str(volume_base),
            "credits_used": (doc.get("meta") or {}).get("credits_used", 0),
        }
    return {"ok": False, "error": "; ".join(errors[:3]) or "no_supported_market"}


def dex_candles(chain: str, contract: str, timeout: int) -> dict[str, Any]:
    if not chain or not contract:
        return {"ok": False, "error": "missing_contract"}
    doc = run_surf(
        ["dex-token-price", "--chain", chain, "--address", contract, "--interval", "15m", "--time-range", "24h"],
        timeout,
    )
    if not doc.get("ok") or not doc.get("data"):
        return {"ok": False, "chain": chain, "contract": contract, "error": doc.get("error", "no_data")}
    rows = sorted(doc["data"], key=lambda row: int(row.get("timestamp") or 0))
    first = dec(rows[0].get("open"))
    last = dec(rows[-1].get("close"))
    high = max(dec(row.get("high")) for row in rows)
    low = min(dec(row.get("low")) for row in rows)
    volume = sum(dec(row.get("volume_usd")) for row in rows)
    return {
        "ok": True,
        "chain": chain,
        "contract": contract,
        "from_utc8": utc8_from_ts(rows[0].get("timestamp")),
        "to_utc8": utc8_from_ts(rows[-1].get("timestamp")),
        "open": str(first),
        "high": str(high),
        "low": str(low),
        "close": str(last),
        "change_pct": str(pct(first, last)),
        "high_from_open_pct": str(pct(first, high)),
        "volume_usd": str(volume),
        "credits_used": (doc.get("meta") or {}).get("credits_used", 0),
    }


def listing_events(symbol: str, timeout: int) -> dict[str, Any]:
    from_day = (now_utc() - timedelta(days=int(os.environ.get("SURF_AUX_LISTING_LOOKBACK_DAYS", "14")))).date().isoformat()
    doc = run_surf(["listing", "--symbol", symbol, "--from", from_day, "--limit", "20"], timeout)
    rows = doc.get("data") or []
    return {
        "ok": bool(doc.get("ok")),
        "error": doc.get("error", ""),
        "rows": rows,
        "credits_used": (doc.get("meta") or {}).get("credits_used", 0),
    }


def summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    spot_prices = [item for item in row.get("spot_prices", []) if not item.get("error")]
    swap_prices = [item for item in row.get("swap_prices", []) if not item.get("error")]
    dex = row.get("dex_24h", {})
    spot_last = dec(spot_prices[0].get("last")) if spot_prices else Decimal(0)
    dex_last = dec(dex.get("close")) if dex.get("ok") else Decimal(0)
    venue_hint = "无CEX市场"
    if spot_prices and swap_prices:
        venue_hint = "现货与合约均有覆盖"
    elif spot_prices:
        venue_hint = "已有现货覆盖"
    elif swap_prices:
        venue_hint = "仅见合约覆盖"
    if dex.get("ok") and spot_last > 0 and dex_last > 0:
        basis = (spot_last / dex_last - Decimal(1)) * Decimal(100)
    else:
        basis = Decimal(0)
    return {
        "venue_hint": venue_hint,
        "spot_last": str(spot_last),
        "dex_last": str(dex_last),
        "spot_vs_dex_basis_pct": str(basis),
        "context_action": "context_only; do not emit buy_sell_action from Surf alone",
    }


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    timeout = int(os.environ.get("SURF_AUX_TIMEOUT_SECONDS", str(args.timeout)))
    rows = []
    credits = 0
    for item in load_watchlist(args):
        markets = exchange_markets(item["symbol"], timeout)
        credits += int(markets.get("credits_used") or 0)
        spot_limit = int(os.environ.get("SURF_AUX_SPOT_PRICE_LIMIT", "3"))
        swap_limit = int(os.environ.get("SURF_AUX_SWAP_PRICE_LIMIT", "2"))
        spot_prices = prices_for_markets(markets["spot_markets"], "spot", spot_limit, timeout)
        swap_prices = prices_for_markets(markets["swap_markets"], "swap", swap_limit, timeout)
        listing = listing_events(item["symbol"], timeout)
        dex = dex_candles(item["chain"], item["contract"], timeout)
        spot_klines = klines_for_market(markets["spot_markets"], "spot", timeout)
        for price in spot_prices + swap_prices:
            credits += int(price.get("credits_used") or 0)
        credits += int(listing.get("credits_used") or 0)
        credits += int(dex.get("credits_used") or 0)
        credits += int(spot_klines.get("credits_used") or 0)
        row = {
            **item,
            "markets": markets,
            "spot_prices": spot_prices,
            "swap_prices": swap_prices,
            "spot_5m_4h": spot_klines,
            "dex_24h": dex,
            "listing_events": listing,
        }
        row["summary"] = summarize_row(row)
        rows.append(row)
    return {
        "schema": "surf_aux_market_watch.v1",
        "generated_at": now_iso(),
        "source": "surf",
        "authority": "auxiliary_context_only",
        "policy": "Surf enriches external market context; it cannot emit direct buy/sell actions until local rules promote a specific field.",
        "row_count": len(rows),
        "credits_used_observed": credits,
        "rows": rows,
    }


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Surf Auxiliary Market Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- authority: `{snapshot['authority']}`",
        f"- credits_used_observed: `{snapshot.get('credits_used_observed', 0)}`",
        "",
        "## Rule",
        "",
        "- Surf only enriches external market context in this layer.",
        "- Do not turn Surf-only movement into buy/sell advice without local chain/Alpha rule confirmation.",
        "",
        "| Symbol | Priority | Venues | Spot last | DEX last | Basis | Spot 4h high | DEX 24h high | Listing events | Context |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in snapshot.get("rows", []):
        summary = row.get("summary", {})
        spot_klines = row.get("spot_5m_4h", {})
        dex = row.get("dex_24h", {})
        venues = ",".join(row.get("markets", {}).get("spot_venues", [])[:5])
        if row.get("markets", {}).get("swap_venues"):
            venues += (" / perp:" + ",".join(row["markets"]["swap_venues"][:3]))
        lines.append(
            f"| `{row.get('symbol', '')}` | {row.get('priority', '')} | {venues or '-'} | "
            f"{fmt_decimal(summary.get('spot_last'), 6)} | {fmt_decimal(summary.get('dex_last'), 6)} | "
            f"{fmt_decimal(summary.get('spot_vs_dex_basis_pct'), 2)}% | "
            f"{fmt_decimal(spot_klines.get('high'), 6) if spot_klines.get('ok') else '-'} | "
            f"{fmt_decimal(dex.get('high'), 6) if dex.get('ok') else '-'} | "
            f"{len(row.get('listing_events', {}).get('rows', []))} | {summary.get('venue_hint', '')} |"
        )
    lines.extend(["", "## Notes", ""])
    had_errors = False
    for row in snapshot.get("rows", []):
        errors = []
        for key in ("spot_5m_4h", "dex_24h"):
            if row.get(key, {}).get("error"):
                errors.append(f"{key}:{row[key]['error']}")
        if row.get("markets", {}).get("error"):
            errors.append(f"markets:{row['markets']['error']}")
        if errors:
            had_errors = True
            lines.append(f"- `{row.get('symbol')}`: " + "; ".join(str(item) for item in errors))
    if not had_errors:
        lines.append("- No notable fetch errors.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Surf auxiliary market snapshot for Alpha watchlist projects.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--symbol", default="")
    parser.add_argument("--max-projects", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    snapshot = build_snapshot(args)
    write_json(out_dir / "latest.json", snapshot)
    (out_dir / "latest.md").write_text(render(snapshot), encoding="utf-8")
    print(f"surf_aux_market_watch output={out_dir} rows={snapshot['row_count']} credits={snapshot.get('credits_used_observed', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
