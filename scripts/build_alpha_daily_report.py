#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
TZ_CN = timezone(timedelta(hours=8))
CELUE_STRATEGY_FIELDS = [
    (
        "source_layers",
        "official / onchain / market / social / inference",
        "每条交易判断先分离来源类型，再写动作。",
    ),
    (
        "path_stage",
        "alpha_intraday_flow_watch CEX fields, opening buyer trace, wallet monitor",
        "标记 source -> CEX cold/hot/deposit -> intermediate wallet -> perp venue treasury/sell venue -> quote recovery。",
    ),
    (
        "cex_wallet_aggregation",
        "Binance Alpha due-diligence UI plus alpha_intraday_flow_watch receipt paths",
        "官方 +归集 只作发现；TXID/receipt 核验后区分供给风险候选、CEX 内部归集和 Alpha 托管相关未决路径，内部路径仅报告。",
    ),
    (
        "cluster_evidence",
        "funding_source_clusters, intraday runtime CEX candidates, gas priming",
        "记录钱包数量、共同来源、共同时间窗、共同充值端口、共同 gas 来源。",
    ),
    (
        "deposit_status",
        "exchange announcements, listing calendar, watchlist required_checks",
        "记录 closed、open、reopened、chain-supported、chain-migrated、unknown。",
    ),
    (
        "derivatives_ratio",
        "perp_oi_funding_watch plus MC/FDV from market_context or external validated sources",
        "跟踪 OI/MC、OI/FDV、24h volume/MC 和 funding 方向。",
    ),
    (
        "event_window",
        "prelaunch, listing, delisting, unlock, deposit reopen, sector rotation",
        "附上精确事件窗口和下一次检查时间。",
    ),
    (
        "index_or_deposit_policy_event",
        "exchange announcements, Binance index basket changes, deposit closure/reopen",
        "记录充值端口、指数篮子、场所支持变化，并作为市场结构事件处理。",
    ),
    (
        "operator_supply",
        "holder concentration, tokenomics, CEX/pool/custody labels",
        "拆分 operator、CEX/pool/custody、verified retail、unknown supply。",
    ),
    (
        "catalyst_source",
        "official links, founder/exchange posts, KOL/social, media, community",
        "社交输入进入 discovery 层；动作依赖本地证据确认。",
    ),
    (
        "meme_stage",
        "first-seen time, market cap, liquidity, holder quality, price multiple",
        "标记 pre-viral、first trigger、post-5x、post-10x、exhausted、unknown。",
    ),
    (
        "tokenomics_catalyst",
        "tokenomics section, announcements, on-chain execution",
        "区分 burn、buyback、buyback-to-liquidity、fee donation、foundation、airdrop、initial float、utility change。",
    ),
    (
        "supply_lifecycle",
        "official tokenomics plus on-chain supply and first-receiver paths",
        "区分 mint、reissue、retirement、compensation、snapshot、migration，并核对相对流通量、锁定和 CEX/LP 去向。",
    ),
    (
        "identity_label_quality",
        "global address labels, external label review, custody/MM/foundation checks",
        "标记 verified official、exchange/custody、market maker、inferred whale、KOL、unknown。",
    ),
    (
        "venue_rotation",
        "price momentum venue class, CEX listings, Surf context-only market rows",
        "跟踪 Binance Alpha、Binance spot/perps、Binance Wallet、Coinbase、Korea CEX、SOL/Pump、Base、ASTER、unknown。",
    ),
    (
        "outcome_ledger",
        "deduped KOL root signal plus fixed-horizon local replay",
        "同一原始信号的引用更新只计一次；记录 24h/72h/7d、MFE、MAE、期末收益、失效和 unresolved。",
    ),
    (
        "regime_expectancy",
        "current liquidity, MC/FDV, aggregate OI, venue policy, capital breadth",
        "按当前市场重算目标、分段止盈和 time stop；历史倍数只作背景。",
    ),
    (
        "source_time_sanity",
        "source published time, claimed event time, quote context",
        "时间或引用上下文冲突时保持待证，不升级事实层。",
    ),
    (
        "flow_recycling_candidate",
        "gross buy/sell, net-to-gross, round-trip addresses, quote recovery",
        "只作 report-only 候选；本地验证前不改变告警或动作。",
    ),
]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fmt_dec(value: Any, places: int = 4) -> str:
    try:
        quant = Decimal(10) ** -places
        return f"{Decimal(str(value)).quantize(quant):f}"
    except Exception:
        return "-"


def fmt_pct(value: Any, places: int = 4) -> str:
    try:
        quant = Decimal(10) ** -places
        return f"{(Decimal(str(value)) * Decimal(100)).quantize(quant):f}%"
    except Exception:
        return "-"


def fmt_signed_pct(value: Any, places: int = 2) -> str:
    try:
        quant = Decimal(10) ** -places
        number = Decimal(str(value)).quantize(quant)
        sign = "+" if number > 0 else ""
        return f"{sign}{number:f}%"
    except Exception:
        return "-"


def fmt_holder_pct(value: Any) -> str:
    try:
        return f"{Decimal(str(value)).quantize(Decimal('0.01')):f}%"
    except Exception:
        return "-"


def fmt_holder_change(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except Exception:
        return "变化未知"
    shown = number.copy_abs().quantize(Decimal("0.01"))
    if number > 0:
        return f"增加 {shown:f} 个百分点"
    if number < 0:
        return f"减少 {shown:f} 个百分点"
    return "无明显变化"


def md_cell(value: Any) -> str:
    text = str(value or "-").replace("\n", " ")
    return text.replace("|", "/")


def short_addr(addr: str) -> str:
    if len(addr or "") <= 14:
        return addr or "-"
    return addr[:8] + "..." + addr[-6:]


def contract_summary(item: dict[str, Any]) -> str:
    contracts = item.get("contracts", [])
    if not contracts:
        return "待确认"
    parts = []
    for contract in contracts[:3]:
        parts.append(f"{contract.get('chain', '-')}: `{short_addr(contract.get('address', ''))}`")
    if len(contracts) > 3:
        parts.append(f"+{len(contracts) - 3}")
    return ", ".join(parts)


def first_required_check(item: dict[str, Any]) -> str:
    checks = item.get("required_checks", [])
    return checks[0] if checks else "-"


def known_time_summary(item: dict[str, Any]) -> str:
    times = item.get("known_times", [])
    if not times:
        return "-"
    out = []
    for row in times[:2]:
        if isinstance(row, dict):
            out.append(str(row.get("time") or ""))
        else:
            out.append(str(row))
    return ", ".join(item for item in out if item) or "-"


def verification_status() -> str:
    report = ROOT / "output" / "sniper_engine" / "verification_report.md"
    if not report.exists():
        return "missing"
    text = report.read_text(encoding="utf-8")
    return "PASS" if "| FAIL |" not in text else "FAIL"


def celue_strategy_checklist() -> list[str]:
    lines = [
        "",
        "## Celue 策略校验清单",
        "",
        "| 字段 | 本地来源 | 使用要求 |",
        "| --- | --- | --- |",
    ]
    for field, source, required_use in CELUE_STRATEGY_FIELDS:
        lines.append(f"| `{field}` | {source} | {required_use} |")
    lines.extend(
        [
            "",
            "- 动作标签固定使用：Avoid、Observe、Reduce、Small test、Follow only after confirmation。",
            "- 每条实盘判断都要写止损规则、失效证据、退出触发器和下一次检查时间。",
        ]
    )
    return lines


def build_report() -> str:
    today = datetime.now(TZ_CN).date().isoformat()
    watchlist = read_json(ROOT / "config" / "current_alpha_watchlist.json", {"items": []})
    active_items = [item for item in watchlist.get("items", []) if item.get("active_monitoring") is not False]
    archived_items = [item for item in watchlist.get("items", []) if item.get("active_monitoring") is False]
    mint = read_json(ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json", {})
    swaps = read_csv(ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv")
    front_trace = read_csv(ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv")
    attribution = read_csv(ROOT / "output" / "o1_address_attribution" / "address_attribution.csv")
    monitor = read_json(ROOT / "output" / "monitoring" / "latest_snapshot.json", {"wallets": [], "alerts": [], "groups": []})
    prediction = read_json(ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json", {"rows": []})
    alpha_price = read_json(ROOT / "output" / "alpha_price_momentum_watch" / "latest.json", {"events": []})
    intraday_flow = read_json(ROOT / "output" / "alpha_intraday_flow_watch" / "latest.json", {"events": []})
    holder_concentration = read_json(ROOT / "output" / "alpha_holder_concentration_watch" / "latest.json", {"projects": []})
    perp_watch = read_json(ROOT / "output" / "perp_oi_funding_watch" / "latest.json", {"rows": []})
    surf_aux = read_json(ROOT / "output" / "surf_aux_market_watch" / "latest.json", {"rows": []})
    external_aux = read_json(ROOT / "output" / "external_aux_sources" / "latest.json", {"rows": []})
    external_aux_probe = read_json(ROOT / "output" / "external_aux_live_probe" / "latest.json", {"rows": []})
    position_cost = read_json(ROOT / "output" / "position_cost_watch" / "latest.json", {"positions": [], "paper_trades": []})
    prelaunch = read_json(ROOT / "output" / "alpha_prelaunch_watch" / "latest.json", {"events": []})
    arx_launch = read_json(ROOT / "output" / "arx_launch_watch" / "latest.json", {"analysis": {}})
    arx_opening = read_json(ROOT / "output" / "arx_opening_block_watch" / "latest.json", {"analysis": {}})

    total_usdt = sum(Decimal(row.get("usdt_in") or "0") for row in swaps)
    total_o = sum(Decimal(row.get("o_out") or "0") for row in swaps)
    avg_price = total_usdt / total_o if total_o else Decimal(0)
    held_front = [row for row in front_trace if row.get("status") == "held_or_accumulated"]
    attribution_counts: dict[str, int] = {}
    for row in attribution:
        attribution_counts[row.get("attribution", "")] = attribution_counts.get(row.get("attribution", ""), 0) + 1
    top_balances = sorted(
        monitor.get("wallets", []),
        key=lambda row: Decimal(str(row.get("token_balance") or "0")),
        reverse=True,
    )[:8]

    lines = [
        "# Alpha Sniper Daily Report",
        "",
        f"- date_cn: `{today}`",
        f"- watchlist_generated_at: `{watchlist.get('generated_at', '-')}`",
        f"- verification: `{verification_status()}`",
        f"- monitored_wallets: `{len(monitor.get('wallets', []))}`",
        f"- monitor_alerts: `{len(monitor.get('alerts', []))}`",
        "",
        "## Priority Queue",
        "",
        "| Priority | Symbol | Name | Time | Chain | Contracts | First check |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in active_items:
        lines.append(
            f"| {item.get('priority', '-')} | `{item.get('symbol', '-')}` | {item.get('name', '-')} | {known_time_summary(item)} | "
            f"{item.get('chain', '-')} | {contract_summary(item)} | {first_required_check(item)} |"
        )

    if archived_items:
        lines.extend(["", "## Archived Cases", ""])
        for item in archived_items:
            lines.append(f"- `{item.get('symbol', '-')}`: {item.get('archive_reason', '')}")

    lines.extend(["", "## Prelaunch Schedule", ""])
    prelaunch_events = prelaunch.get("events", [])
    if prelaunch_events:
        lines.extend(["| Phase | Time UTC+8 | Project | Action |", "| --- | --- | --- | --- |"])
        for event in prelaunch_events[:12]:
            lines.append(
                f"| {event.get('phase', '')} | {event.get('time_utc8', '')} | "
                f"{event.get('display_name', event.get('symbol', ''))} | {event.get('action', '')} |"
            )
    else:
        lines.append("- No upcoming P0/P1 launch windows in prelaunch watch output.")

    lines.extend(
        [
            "",
            "## O1 Case State (Historical)",
            "",
            f"- LP position ID: `{mint.get('position_id', '-')}`",
            f"- pool: `{mint.get('pool', '-')}`",
            f"- price range: `{fmt_dec(mint.get('min_price_usdt_per_o'), 6)} -> {fmt_dec(mint.get('max_price_usdt_per_o'), 6)}` USDT/O",
            f"- opening swaps: `{len(swaps)}`",
            f"- opening buy total: `{fmt_dec(total_usdt, 2)}` USDT for `{fmt_dec(total_o, 2)}` O",
            f"- opening weighted avg: `{fmt_dec(avg_price, 6)}` USDT/O",
            f"- front buyers held_or_accumulated: `{len(held_front)}/{len(front_trace)}`",
            f"- attribution strong project-side: `{attribution_counts.get('PROJECT_SIDE_STRONG', 0)}`",
            f"- attribution medium project-side: `{attribution_counts.get('PROJECT_SIDE_MEDIUM', 0)}`",
            f"- failed sniper side addresses: `{attribution_counts.get('FAILED_SNIPER_SIDE', 0)}`",
            "",
            "## Active Wallet Monitor",
            "",
        ]
    )
    for group in monitor.get("groups", []):
        lines.append(
            f"- `{group.get('chain')}` `{short_addr(group.get('token_contract', ''))}` "
            f"blocks `{group.get('from_block')}` -> `{group.get('latest_block')}`: "
            f"`{group.get('relevant_rows')}/{group.get('transfer_rows')}` relevant transfers"
        )
    if monitor.get("alerts"):
        lines.append(f"- alert count: `{len(monitor.get('alerts', []))}`")
    else:
        lines.append("- alert count: `0`")

    lines.extend(
        [
            "",
            "## ARX Runtime Judgment",
            "",
            f"- opening_conclusion: {arx_opening.get('analysis', {}).get('conclusion', '-')}",
            f"- opening_spot_action: {arx_opening.get('analysis', {}).get('spot_action', '-')}",
            f"- opening_perp_action: {arx_opening.get('analysis', {}).get('perp_action', '-')}",
            f"- launch_conclusion: {arx_launch.get('analysis', {}).get('conclusion', '-')}",
            f"- launch_spot_action: {arx_launch.get('analysis', {}).get('spot_action', '-')}",
            f"- launch_perp_action: {arx_launch.get('analysis', {}).get('perp_action', '-')}",
        ]
    )

    lines.extend(["", "## Top Watched Balances", "", "| Balance | Address | Label | Level |", "| ---: | --- | --- | --- |"])
    for row in top_balances:
        lines.append(
            f"| {fmt_dec(row.get('token_balance'), 2)} | `{short_addr(row.get('address', ''))}` | "
            f"{row.get('label', '')} | {row.get('monitor_level', '')} |"
        )

    lines.extend(["", "## Prediction Markets", ""])
    prediction_rows = prediction.get("rows", [])
    if prediction_rows:
        lines.extend(["| Status | Symbol | Source | Target | Probability | Target FDV | Implied Price |", "| --- | --- | --- | --- | ---: | ---: | ---: |"])
        for row in prediction_rows[:12]:
            lines.append(
                f"| {row.get('status', '')} | `{row.get('symbol', '')}` | {row.get('source', '')} | "
                f"{row.get('target_label') or row.get('outcome', '')} | {row.get('probability', '')} | "
                f"{row.get('target_fdv_usd', '')} | {row.get('implied_token_price', '')} |"
            )
    else:
        lines.append("- No prediction markets configured.")

    lines.extend(["", "## Perp / OI / Funding", ""])
    perp_rows = perp_watch.get("rows", [])
    if perp_rows:
        lines.extend(["| Symbol | Perp | Venues | State | Main OI | Total OI | OI Δ | Price Δ | Funding 8h | Funding 24h | 24h Vol | 24h Chg | Trend | Action |", "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |"])
        for row in perp_rows[:12]:
            state = row.get("perp_state") or row.get("status", "")
            hint = row.get("direction_hint", "")
            action = row.get("action", "")
            if row.get("trend_action"):
                action += f"; {row.get('trend_action')}"
            venues = ",".join(row.get("listed_venues") or [row.get("venue", "")])
            funding_rate = row.get("current_funding_rate_8h")
            if funding_rate in ("", None):
                funding_rate = row.get("last_funding_rate")
            funding_24h = (
                f"{row.get('funding_history_state', '')} / avg8h {fmt_pct(row.get('funding_24h_avg_8h_rate'), 4)} / "
                f"cum {fmt_pct(row.get('funding_24h_cumulative_rate'), 4)}"
                if row.get("funding_history_status") in {"ok", "short_history"}
                else row.get("funding_history_status", "")
            )
            lines.append(
                f"| `{row.get('symbol', '')}` | `{row.get('perp_symbol', '')}` | {venues} | {state} / {hint} | "
                f"{fmt_dec(row.get('open_interest_usd'), 2)} | {fmt_dec(row.get('total_open_interest_usd') or row.get('open_interest_usd'), 2)} | "
                f"{fmt_signed_pct(row.get('oi_usd_delta_pct'), 2)} | "
                f"{fmt_signed_pct(row.get('mark_price_delta_pct'), 2)} | {fmt_pct(funding_rate, 4)} | {funding_24h} | "
                f"{fmt_dec(row.get('quote_volume_24h'), 2)} | {fmt_dec(row.get('price_change_pct_24h'), 2)}% | "
                f"{row.get('trend_hint', '')} | {action} |"
            )
    else:
        lines.append("- No perp/OI snapshot available.")

    lines.extend(["", "## Alpha Price Momentum", ""])
    price_events = alpha_price.get("events", [])
    if price_events:
        def price_sort_key(event: dict[str, Any]) -> tuple[int, str]:
            signal = event.get("analysis", {}).get("trade_signal", "")
            return (0 if signal and signal != "无价格异动" else 1, str(event.get("symbol", "")))

        lines.extend(["| Symbol | Signal | Spot action | 15m high/low/close | 15m quote | Venue | Book | Reason |", "| --- | --- | --- | ---: | ---: | --- | --- | --- |"])
        for event in sorted(price_events, key=price_sort_key)[:12]:
            analysis = event.get("analysis", {})
            window = analysis.get("window_15m", {})
            depth = analysis.get("depth", {})
            venue = analysis.get("venue", {})
            move = "/".join(
                [
                    fmt_signed_pct(window.get("high_pct"), 2),
                    fmt_signed_pct(window.get("low_pct"), 2),
                    fmt_signed_pct(window.get("close_pct"), 2),
                ]
            )
            lines.append(
                f"| `{event.get('symbol', '')}` | {md_cell(analysis.get('trade_signal', ''))} | "
                f"{md_cell(analysis.get('spot_action', ''))} | {move} | {fmt_dec(window.get('quote_volume'), 2)} | "
                f"{venue.get('venue_class', '-')} / {venue.get('coverage', '-')} | "
                f"{depth.get('orderbook_status', '-')} | {md_cell(analysis.get('reason', ''))} |"
            )
        lines.append("")
        lines.append("- Alpha 价格层只给动作提醒和注意力排序，跟随口径仍需要链上成交、首批去向、活动分发和可售性共同确认。")
    else:
        lines.append("- No Alpha price momentum snapshot available.")

    lines.extend(["", "## CEX Wallet Flow", ""])
    cex_flow_events = []
    for event in intraday_flow.get("events", []):
        analysis = event.get("analysis", {}) or {}
        withdrawal = analysis.get("cex_withdrawal_cluster", {}) or {}
        if (
            int(analysis.get("cex_deposit_count") or 0)
            or int(analysis.get("cex_internal_aggregation_count") or 0)
            or int(withdrawal.get("candidate_count") or 0)
        ):
            cex_flow_events.append(event)
    if cex_flow_events:
        lines.extend(
            [
                "| Symbol | Direction | External CEX inflow | Internal gross turnover | Internal role | Withdrawal candidates |",
                "| --- | --- | ---: | ---: | --- | ---: |",
            ]
        )
        for event in cex_flow_events[:12]:
            analysis = event.get("analysis", {}) or {}
            withdrawal = analysis.get("cex_withdrawal_cluster", {}) or {}
            lines.append(
                f"| `{event.get('symbol', '')}` | {analysis.get('direction', '')} | "
                f"{fmt_dec(analysis.get('cex_quote_estimate'), 2)} | "
                f"{fmt_dec(analysis.get('cex_internal_aggregation_quote_estimate'), 2)} | "
                f"{analysis.get('cex_internal_path_roles') or '-'} | {int(withdrawal.get('candidate_count') or 0)} |"
            )
    else:
        lines.append("- No verified CEX inflow, internal aggregation, or withdrawal-cluster observation in the latest intraday snapshot.")
    lines.append("- `+归集` 先核验 receipt 与 CEX 目标；未标记来源进入供给风险候选，CEX/Alpha 内部路径保持 report-only，来源实体和出售意图继续 unresolved。")
    lines.append("- Internal gross turnover 是内部路径 Transfer 毛额；同一批代币经过多跳时可能重复出现，不作为净经济流。")

    lines.extend(["", "## Holder Concentration", ""])
    holder_projects = holder_concentration.get("projects", [])
    if holder_projects:
        lines.extend(["| Symbol | Action | 联动判断 | 排除托管后前十 | 窗口重建前十 | 交易所/托管/池子 | 外部全量Top10 | Coverage |", "| --- | --- | --- | ---: | ---: | ---: | --- | --- |"])
        for project in holder_projects[:12]:
            metrics = project.get("metrics", {})
            signal = project.get("signal", {})
            full_holder = project.get("full_holder_source", {})
            decision = project.get("decision_context", {})
            lines.append(
                f"| `{project.get('symbol', '')}` | {md_cell(signal.get('action', ''))} | "
                f"{md_cell(decision.get('action', ''))} | "
                f"{fmt_holder_pct(metrics.get('effective_top10_pct'))}；{fmt_holder_change(metrics.get('effective_top10_delta_pct'))} | "
                f"{fmt_holder_pct(metrics.get('raw_top10_pct'))}；{fmt_holder_change(metrics.get('raw_top10_delta_pct'))} | "
                f"{fmt_holder_pct(metrics.get('raw_top10_infra_pct'))} | {md_cell(full_holder.get('summary', '未接入；当前显示窗口重建口径'))} | {project.get('coverage_note', '')} |"
            )
        lines.append("")
        lines.append("- Holder 层用于判断筹码集中/分散；联动判断会结合价格动量和盘中链上大额流。排除托管后前十已剔除 CEX、Alpha 托管、LP、桥和 Pancake 基础设施。外部全量Top10字段会标明是否已接入 App 式全量 holder 源。")
    else:
        lines.append("- No holder concentration snapshot available.")

    lines.extend(["", "## Surf Auxiliary Market", ""])
    surf_rows = surf_aux.get("rows", [])
    if surf_rows:
        lines.extend(["| Symbol | Venues | Spot last | DEX last | Basis | Spot 4h high | DEX 24h high | Listings | Authority |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
        for row in surf_rows[:12]:
            summary = row.get("summary", {})
            markets = row.get("markets", {})
            spot_klines = row.get("spot_5m_4h", {})
            dex = row.get("dex_24h", {})
            venues = ",".join(markets.get("spot_venues") or [])
            if markets.get("swap_venues"):
                venues += (" / perp:" + ",".join(markets.get("swap_venues") or []))
            lines.append(
                f"| `{row.get('symbol', '')}` | {venues or '-'} | {fmt_dec(summary.get('spot_last'), 6)} | "
                f"{fmt_dec(summary.get('dex_last'), 6)} | {fmt_dec(summary.get('spot_vs_dex_basis_pct'), 2)}% | "
                f"{fmt_dec(spot_klines.get('high'), 6) if spot_klines.get('ok') else '-'} | "
                f"{fmt_dec(dex.get('high'), 6) if dex.get('ok') else '-'} | "
                f"{len(row.get('listing_events', {}).get('rows', []))} | `context_only` |"
            )
        lines.append("")
        lines.append("- Surf 只用于外部市场背景，不能单独触发买卖动作。")
    else:
        lines.append("- No Surf auxiliary market snapshot available.")

    lines.extend(["", "## External Auxiliary Sources", ""])
    external_rows = external_aux.get("rows", [])
    if external_rows:
        lines.extend(["| Source | Category | Status | Authority | Next step |", "| --- | --- | --- | --- | --- |"])
        for row in external_rows[:12]:
            lines.append(
                f"| {row.get('name', '')} | {row.get('category', '')} | `{row.get('status', '')}` | "
                f"`{row.get('authority', '')}` | {row.get('next_step', '')} |"
            )
    else:
        lines.append("- No external auxiliary source snapshot available.")

    probe_rows = external_aux_probe.get("rows", [])
    if probe_rows:
        lines.extend(["", "### External Aux Live Probe", "", "| Source | Status | HTTP | Validation | Next step |", "| --- | --- | ---: | --- | --- |"])
        for row in probe_rows[:12]:
            lines.append(
                f"| {row.get('name') or row.get('id', '')} | `{row.get('status', '')}` | {row.get('http_status', '')} | "
                f"`{row.get('validation_env', '')}` | {md_cell(row.get('next_step', ''))} |"
            )
    else:
        lines.append("")
        lines.append("- External aux live probe has not run in this cycle.")

    lines.extend(["", "## Position / Cost Watch", ""])
    position_rows = position_cost.get("positions", [])
    paper_rows = position_cost.get("paper_trades", [])
    if position_rows:
        lines.extend(["| Symbol | Side | Cost | Notional | PnL | State | Action |", "| --- | --- | ---: | ---: | ---: | --- | --- |"])
        for row in position_rows[:12]:
            lines.append(
                f"| `{row.get('symbol', '')}` | {row.get('side', '')} | {fmt_dec(row.get('cost_usd'), 2)} | "
                f"{fmt_dec(row.get('notional_usd'), 2)} | {fmt_dec(row.get('pnl_usd'), 2)} / {fmt_dec(row.get('pnl_pct'), 2)}% | "
                f"{row.get('position_state', '')} / {row.get('size_state', '')} | {md_cell(row.get('action', ''))} |"
            )
    else:
        lines.append("- No configured real positions. `config/user_positions.json` is git-ignored; fill it locally when needed.")
    if paper_rows:
        lines.extend(["", "| Paper | Side | Plan | Current | Readiness | Invalidation |", "| --- | --- | ---: | ---: | --- | --- |"])
        for row in paper_rows[:12]:
            lines.append(
                f"| `{row.get('symbol', '')}` | {row.get('side', '')} | {fmt_dec(row.get('planned_entry'), 6)} | "
                f"{fmt_dec(row.get('current_price'), 6)} | {row.get('readiness', '')} | {md_cell(row.get('invalidation', ''))} |"
            )
    else:
        lines.append("- No paper trade plans configured.")

    lines.extend(celue_strategy_checklist())

    lines.extend(
        [
            "",
            "## Action Queue",
            "",
            "1. ARX: 以开盘块、首批买入、bribe、活动分发和交易所流向作为主线。",
            "2. O1: 已暂停主动钱包监控，只保留历史复盘样本。",
            "3. RE: 做 Alpha 到 CEX 承接复盘，重点看 Prime Sale、充值地址、现货/永续价差。",
            "4. VELVET/ESPORTS: 先看交易赛带来的真实成交质量和活动钱包。",
            "5. NIGHT/GRAM: 作为 OKX Boost/衍生品结构样本，等链上合约确认后上调。",
            "6. External sources: Coinglass/CoinAnk/GMGN 先跑 readiness 和 live probe，再允许进入动作文案。",
            "",
            "## Sources",
            "",
            "- Binance New Cryptocurrency Listing: https://www.binance.com/en/support/announcement/list/48",
            "- OKX New listings: https://www.okx.com/help/section/announcements-new-listings",
            "- OKX NIGHT Boost: https://www.okx.com/en-us/learn/trade-dex-night-boost",
            "- Local verification: `output/sniper_engine/verification_report.md`",
            "- Local monitor: `output/monitoring/alerts.md`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ_CN).date().isoformat()
    path = REPORTS_DIR / f"{today}_alpha_sniper_daily.md"
    path.write_text(build_report(), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
