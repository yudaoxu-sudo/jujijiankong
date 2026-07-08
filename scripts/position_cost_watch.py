#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "user_positions.json"
EXAMPLE_CONFIG = ROOT / "config" / "user_positions.example.json"
OUT_DIR = ROOT / "output" / "position_cost_watch"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dec(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def fmt(value: Any, places: str = "0.0000") -> str:
    number = dec(value)
    if number == 0:
        return "0"
    return str(number.quantize(Decimal(places)))


def short(text: str, limit: int = 140) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def by_symbol(rows: list[dict[str, Any]], key: str = "symbol") -> dict[str, dict[str, Any]]:
    out = {}
    for row in rows:
        symbol = str(row.get(key) or "").upper()
        if symbol and symbol not in out:
            out[symbol] = row
    return out


def load_context() -> dict[str, Any]:
    alpha_price = read_json(ROOT / "output" / "alpha_price_momentum_watch" / "latest.json", {"events": []})
    perp = read_json(ROOT / "output" / "perp_oi_funding_watch" / "latest.json", {"rows": []})
    surf = read_json(ROOT / "output" / "surf_aux_market_watch" / "latest.json", {"rows": []})
    intraday = read_json(ROOT / "output" / "alpha_intraday_flow_watch" / "latest.json", {"events": []})
    opening = read_json(ROOT / "output" / "alpha_opening_block_watch" / "latest.json", {"events": []})
    holder = read_json(ROOT / "output" / "alpha_holder_concentration_watch" / "latest.json", {"projects": []})
    return {
        "alpha_price": by_symbol(alpha_price.get("events", [])),
        "perp": by_symbol(perp.get("rows", [])),
        "surf": by_symbol(surf.get("rows", [])),
        "intraday": by_symbol(intraday.get("events", [])),
        "opening": by_symbol(opening.get("events", [])),
        "holder": by_symbol(holder.get("projects", [])),
    }


def price_from_context(symbol: str, instrument: str, position: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    manual = dec(position.get("current_price"))
    if manual > 0:
        return {"price": str(manual), "source": "manual_position_current_price"}
    if instrument in {"perp", "future", "swap", "contract"}:
        row = context["perp"].get(symbol, {})
        mark = dec(row.get("mark_price"))
        if mark > 0:
            return {"price": str(mark), "source": f"perp:{row.get('venue', '')}:{row.get('perp_symbol', '')}"}
    alpha = context["alpha_price"].get(symbol, {})
    alpha_price = dec((alpha.get("alpha") or {}).get("price"))
    if alpha_price > 0:
        return {"price": str(alpha_price), "source": "binance_alpha"}
    surf = context["surf"].get(symbol, {})
    summary = surf.get("summary") or {}
    for field in ("spot_last", "dex_last", "swap_last"):
        value = dec(summary.get(field))
        if value > 0:
            return {"price": str(value), "source": f"surf:{field}"}
    row = context["perp"].get(symbol, {})
    mark = dec(row.get("mark_price"))
    if mark > 0:
        return {"price": str(mark), "source": f"perp_fallback:{row.get('venue', '')}"}
    return {"price": "", "source": "missing_price"}


def risk_notes(symbol: str, context: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    intraday = context["intraday"].get(symbol, {})
    intraday_analysis = intraday.get("analysis") or {}
    for field in ("trade_signal", "spot_action", "perp_action", "reason"):
        value = intraday_analysis.get(field)
        if value:
            notes.append(f"intraday {field}: {short(value)}")
    alpha = context["alpha_price"].get(symbol, {})
    alpha_analysis = alpha.get("analysis") or {}
    for field in ("trade_signal", "spot_action", "reason"):
        value = alpha_analysis.get(field)
        if value and value != "无价格异动":
            notes.append(f"alpha_price {field}: {short(value)}")
    perp = context["perp"].get(symbol, {})
    for field in ("direction_hint", "trend_hint", "depth_state", "liquidation_state"):
        value = perp.get(field)
        if value:
            notes.append(f"perp {field}: {value}")
    holder = context["holder"].get(symbol, {})
    signal = holder.get("signal") or {}
    if signal.get("action"):
        notes.append(f"holder action: {short(signal.get('action'))}")
    return notes


def classify_position(position: dict[str, Any], current_price: Decimal, notes: list[str]) -> dict[str, str]:
    side = str(position.get("side") or "long").lower()
    stop_loss = dec(position.get("stop_loss"))
    take_profit = dec(position.get("take_profit"))
    text = "；".join(notes)
    has_sell_risk = any(term in text for term in ("卖出", "减仓", "CEX", "确认换出", "不追", "hostile", "thin_depth"))
    if current_price <= 0:
        return {"state": "needs_price", "action": "补价格源；不做仓位结论"}
    if side == "long":
        if stop_loss > 0 and current_price <= stop_loss:
            return {"state": "exit_triggered", "action": "触发止损；按计划退出或人工确认退出"}
        if has_sell_risk:
            return {"state": "reduce_watch", "action": "降低风险；等待 CEX/链上路径解除或分批减仓"}
        if take_profit > 0 and current_price >= take_profit:
            return {"state": "take_profit_zone", "action": "进入止盈区；按计划分批止盈"}
        return {"state": "hold_watch", "action": "持仓观察；按失效条件管理"}
    if side == "short":
        if stop_loss > 0 and current_price >= stop_loss:
            return {"state": "exit_triggered", "action": "触发空单止损；按计划退出或人工确认退出"}
        if take_profit > 0 and current_price <= take_profit:
            return {"state": "take_profit_zone", "action": "进入空单止盈区；按计划分批止盈"}
        return {"state": "short_watch", "action": "空单观察；只按深度、价格和流向确认加减"}
    return {"state": "unknown_side", "action": "仓位方向未知；补 side 字段"}


def position_row(position: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "").upper()
    instrument = str(position.get("instrument") or "spot").lower()
    price = price_from_context(symbol, instrument, position, context)
    current_price = dec(price.get("price"))
    quantity = dec(position.get("quantity"))
    avg_entry = dec(position.get("avg_entry"))
    cost = quantity * avg_entry
    notional = quantity * current_price
    side = str(position.get("side") or "long").lower()
    if side == "short":
        pnl = cost - notional
    else:
        pnl = notional - cost
    pnl_pct = (pnl / cost * Decimal(100)) if cost > 0 else Decimal(0)
    max_position = dec(position.get("max_position_usd"))
    notes = risk_notes(symbol, context)
    state = classify_position(position, current_price, notes)
    size_state = "ok"
    if max_position > 0 and notional > max_position:
        size_state = "over_limit"
    return {
        "symbol": symbol,
        "venue": position.get("venue", ""),
        "instrument": instrument,
        "side": side,
        "status": position.get("status", ""),
        "quantity": str(quantity),
        "avg_entry": str(avg_entry),
        "current_price": str(current_price) if current_price > 0 else "",
        "price_source": price.get("source", ""),
        "cost_usd": str(cost),
        "notional_usd": str(notional),
        "pnl_usd": str(pnl),
        "pnl_pct": str(pnl_pct),
        "stop_loss": str(position.get("stop_loss") or ""),
        "take_profit": str(position.get("take_profit") or ""),
        "size_state": size_state,
        "position_state": state["state"],
        "action": state["action"],
        "thesis": position.get("thesis", ""),
        "invalidation": position.get("invalidation", ""),
        "risk_notes": notes[:8],
    }


def paper_trade_row(plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    symbol = str(plan.get("symbol") or "").upper()
    instrument = str(plan.get("instrument") or "spot").lower()
    price = price_from_context(symbol, instrument, plan, context)
    current_price = dec(price.get("price"))
    planned_entry = dec(plan.get("planned_entry"))
    max_slippage_bps = dec(plan.get("max_slippage_bps"))
    max_buy_price = planned_entry * (Decimal(1) + max_slippage_bps / Decimal(10000)) if planned_entry > 0 else Decimal(0)
    readiness = "waiting"
    if current_price <= 0:
        readiness = "needs_price"
    elif planned_entry > 0 and current_price <= max_buy_price:
        readiness = "entry_price_available"
    return {
        "symbol": symbol,
        "instrument": instrument,
        "side": str(plan.get("side") or "long").lower(),
        "planned_entry": str(planned_entry),
        "current_price": str(current_price) if current_price > 0 else "",
        "price_source": price.get("source", ""),
        "max_slippage_bps": str(max_slippage_bps),
        "max_buy_price": str(max_buy_price) if max_buy_price > 0 else "",
        "max_loss_usd": str(plan.get("max_loss_usd") or ""),
        "target": str(plan.get("target") or ""),
        "invalidation": plan.get("invalidation", ""),
        "status": plan.get("status", ""),
        "readiness": readiness,
        "risk_notes": risk_notes(symbol, context)[:6],
    }


def build_snapshot(config: dict[str, Any], config_path: Path, use_example: bool) -> dict[str, Any]:
    context = load_context()
    positions = [position_row(row, context) for row in config.get("positions", []) if isinstance(row, dict)]
    paper_trades = [paper_trade_row(row, context) for row in config.get("paper_trades", []) if isinstance(row, dict)]
    return {
        "schema": "position_cost_watch.v1",
        "generated_at": now_iso(),
        "mode": "read_only_no_signing_no_execution",
        "config_path": str(config_path),
        "using_example_config": use_example,
        "position_count": len(positions),
        "paper_trade_count": len(paper_trades),
        "positions": positions,
        "paper_trades": paper_trades,
    }


def md_cell(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Position / Cost Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- mode: `{snapshot['mode']}`",
        f"- config_path: `{snapshot['config_path']}`",
        f"- using_example_config: `{snapshot['using_example_config']}`",
        f"- position_count: `{snapshot['position_count']}`",
        f"- paper_trade_count: `{snapshot['paper_trade_count']}`",
        "",
        "## Positions",
        "",
    ]
    if snapshot["positions"]:
        lines.extend(
            [
                "| Symbol | Side | Qty | Avg | Current | Cost | Notional | PnL | State | Action |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for row in snapshot["positions"]:
            lines.append(
                f"| `{row['symbol']}` | {row['side']} | {fmt(row['quantity'], '0.01')} | "
                f"{fmt(row['avg_entry'], '0.000001')} | {fmt(row['current_price'], '0.000001')} | "
                f"{fmt(row['cost_usd'], '0.01')} | {fmt(row['notional_usd'], '0.01')} | "
                f"{fmt(row['pnl_usd'], '0.01')} ({fmt(row['pnl_pct'], '0.01')}%) | "
                f"{row['position_state']} / {row['size_state']} | {md_cell(row['action'])} |"
            )
            if row.get("risk_notes"):
                lines.append(f"|  |  |  |  |  |  |  |  | notes | {md_cell('；'.join(row['risk_notes'][:3]))} |")
    else:
        lines.append("- No configured positions. Copy `config/user_positions.example.json` to `config/user_positions.json` and fill positions locally.")
    lines.extend(["", "## Paper Trades", ""])
    if snapshot["paper_trades"]:
        lines.extend(
            [
                "| Symbol | Side | Plan | Current | Max Buy | Readiness | Max Loss | Target | Invalidation |",
                "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |",
            ]
        )
        for row in snapshot["paper_trades"]:
            lines.append(
                f"| `{row['symbol']}` | {row['side']} | {fmt(row['planned_entry'], '0.000001')} | "
                f"{fmt(row['current_price'], '0.000001')} | {fmt(row['max_buy_price'], '0.000001')} | "
                f"{row['readiness']} | {md_cell(row['max_loss_usd'])} | {md_cell(row['target'])} | {md_cell(row['invalidation'])} |"
            )
    else:
        lines.append("- No paper trade plans configured.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only position, cost, and paper-trade risk monitor.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--use-example", action="store_true", help="Use config/user_positions.example.json for smoke tests")
    args = parser.parse_args()
    config_path = EXAMPLE_CONFIG if args.use_example else Path(args.config)
    config = read_json(config_path, {"schema": "user_positions.v1", "positions": [], "paper_trades": []})
    snapshot = build_snapshot(config, config_path, args.use_example)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "latest.json", snapshot)
    (out_dir / "latest.md").write_text(render(snapshot), encoding="utf-8")
    print(out_dir / "latest.json")
    print(out_dir / "latest.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
