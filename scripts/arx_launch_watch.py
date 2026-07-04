#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import rpc_call


getcontext().prec = 80

OUT_DIR = ROOT / "output" / "arx_launch_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
OPENING_PATH = ROOT / "output" / "arx_opening_block_watch" / "latest.json"
TELEGRAM_LIMIT = 3900
DEFAULT_MIN_ARX_TRANSFER = "100000"
DEFAULT_MIN_ARX_BALANCE_DELTA = "100000"
DEFAULT_MIN_USDT_BALANCE_DELTA = "100000"
DEFAULT_MIN_RECENT_TRANSFER_DISPLAY = "100000"
DEFAULT_MAX_INCREMENT_BLOCKS = "5000"
DEFAULT_MAX_TRANSFER_PAGES = "6"

ARX = "0xd5f6ef5deabe61e6d5cdb49bfb6f156f2c1ca715"
USDT = "0x55d398326f99059ff775485246999027b3197955"
POOL_MANAGER = "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

KEY_ADDRESSES = [
    {"label": "MM/接货合约", "role": "market_maker", "address": "0x238a358808379702088667322f80ac48bad5e6c4", "level": "CRITICAL", "watch_usdt": True},
    {"label": "OKX Booster分发合约3M", "role": "event_distribution", "event": "OKX Booster", "address": "0xeccbf1ac6d0407360f0992ff6ea500020d6e1702", "level": "HIGH", "watch_usdt": False},
    {"label": "Binance Alpha空投/分发8.5M", "role": "event_distribution", "event": "Binance Alpha", "address": "0x3e5e8c26cda4d0caa4bfee9cddb283b356aeea74", "level": "CRITICAL", "watch_usdt": False},
    {"label": "大持仓2.5M-A", "address": "0xf131c7335966110528bea9dbefd6c040658d6128", "level": "HIGH", "watch_usdt": False},
    {"label": "大持仓2.5M-B", "address": "0x1e2392477b413cb023cc7f46fd4a8765cd03bc4c", "level": "HIGH", "watch_usdt": False},
    {"label": "活动小额分发合约1.5M", "role": "event_distribution", "event": "Booster/airdrop", "address": "0x317cd61fa24e2e4068b4c47bd58d5fc9f4e7a12b", "level": "HIGH", "watch_usdt": False},
    {"label": "近期转出地址", "address": "0xa45c45ebe32654566c77be38a6583b8b2f1a3616", "level": "HIGH", "watch_usdt": False},
    {"label": "v4 PoolManager", "role": "pool", "address": POOL_MANAGER, "level": "CRITICAL", "watch_usdt": False},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm(value: str | None) -> str:
    return (value or "").lower()


def decimal_amount(raw: int, decimals: int = 18) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def token_balance(token: str, address: str) -> Decimal:
    data = "0x70a08231" + norm(address)[2:].rjust(64, "0")
    raw = rpc_call("bsc", "eth_call", [{"to": token, "data": data}, "latest"])
    return decimal_amount(int(raw or "0x0", 16))


def latest_block() -> int:
    return int(rpc_call("bsc", "eth_blockNumber", []), 16)


def topic_address(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


def address_from_topic(topic: str) -> str:
    return "0x" + norm(topic)[-40:]


def get_arx_transfers(from_block: int, to_block: int, watched_addresses: list[str]) -> list[dict[str, Any]]:
    if not watched_addresses:
        return []
    max_watch = int(os.environ.get("ARX_MAX_WATCH_ADDRESSES", "24"))
    topics = [topic_address(address) for address in watched_addresses[:max_watch]]
    queries = [
        [TRANSFER_TOPIC, topics, None],
        [TRANSFER_TOPIC, None, topics],
    ]
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for topic_filter in queries:
        query = {
            "address": ARX,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": topic_filter,
        }
        result = rpc_call("bsc", "eth_getLogs", [query])
        for row in result or []:
            parsed = log_to_transfer(row)
            rows[(parsed.get("hash", ""), str(parsed.get("logIndex", "")))] = parsed
    return sorted(rows.values(), key=lambda row: (transfer_block(row), int(row.get("logIndex") or 0)))


def log_to_transfer(row: dict[str, Any]) -> dict[str, Any]:
    topics = row.get("topics", [])
    return {
        "blockNum": row.get("blockNumber", "0x0"),
        "hash": row.get("transactionHash", ""),
        "logIndex": int(row.get("logIndex") or "0x0", 16),
        "from": address_from_topic(topics[1]) if len(topics) > 1 else "",
        "to": address_from_topic(topics[2]) if len(topics) > 2 else "",
        "value": row.get("data", "0x0"),
    }


def transfer_amount(row: dict[str, Any]) -> Decimal:
    return decimal_amount(int(row.get("value") or "0x0", 16))


def transfer_block(row: dict[str, Any]) -> int:
    return int(row.get("blockNum") or "0x0", 16)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def env_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default))


def previous_balances(payload: dict[str, Any]) -> dict[str, Decimal]:
    rows = payload.get("balances", [])
    out: dict[str, Decimal] = {}
    for row in rows:
        key = f"{norm(row.get('token'))}:{norm(row.get('address'))}"
        out[key] = Decimal(str(row.get("balance", "0")))
    return out


def build_snapshot() -> dict[str, Any]:
    finality = int(os.environ.get("ARX_FINALITY_BLOCKS", "20"))
    lookback = int(os.environ.get("ARX_LOOKBACK_BLOCKS", "50000"))
    tip = max(0, latest_block() - finality)
    previous_payload = read_json(LATEST_PATH, {})
    previous_tip = int(previous_payload.get("latest_block") or 0)
    max_increment = int(os.environ.get("ARX_MAX_INCREMENT_BLOCKS", DEFAULT_MAX_INCREMENT_BLOCKS))
    if previous_tip and previous_tip < tip:
        from_block = max(previous_tip + 1, tip - max_increment)
    else:
        from_block = max(0, tip - min(lookback, max_increment))
    prev = previous_balances(previous_payload)
    watched = {norm(row["address"]): row for row in KEY_ADDRESSES}
    transfers = get_arx_transfers(from_block, tip, list(watched))
    relevant = [
        row for row in transfers
        if norm(row.get("from")) in watched or norm(row.get("to")) in watched
    ]

    balances = []
    for item in KEY_ADDRESSES:
        address = item["address"]
        arx_balance = token_balance(ARX, address)
        balances.append(balance_row("ARX", ARX, item, arx_balance, prev))
        if item.get("watch_usdt"):
            usdt_balance = token_balance(USDT, address)
            balances.append(balance_row("USDT", USDT, item, usdt_balance, prev))

    alerts = build_alerts(relevant, balances, previous_tip)
    recent_rows, suppressed_small_event_transfers = display_transfers(relevant, watched)
    analysis = analyze_snapshot(alerts, balances)
    return {
        "generated_at": now_iso(),
        "latest_block": tip,
        "previous_latest_block": previous_tip,
        "from_block": from_block,
        "lookback_blocks": lookback,
        "transfer_rows": len(transfers),
        "relevant_transfer_rows": len(relevant),
        "suppressed_small_event_transfers": suppressed_small_event_transfers,
        "balances": balances,
        "recent_transfers": recent_rows[-20:],
        "alerts": alerts,
        "analysis": analysis,
        "conclusion": analysis["conclusion"],
    }


def balance_row(token_symbol: str, token: str, item: dict[str, Any], balance: Decimal, prev: dict[str, Decimal]) -> dict[str, Any]:
    key = f"{norm(token)}:{norm(item['address'])}"
    previous = prev.get(key)
    delta = "" if previous is None else str(balance - previous)
    return {
        "token": token,
        "symbol": token_symbol,
        "address": item["address"],
        "label": item["label"],
        "role": item.get("role", ""),
        "event": item.get("event", ""),
        "level": item["level"],
        "balance": str(balance),
        "previous_balance": "" if previous is None else str(previous),
        "delta": delta,
    }


def build_alerts(transfers: list[dict[str, Any]], balances: list[dict[str, Any]], previous_tip: int) -> list[dict[str, Any]]:
    alerts = []
    min_arx_transfer = env_decimal("ARX_MIN_TRANSFER_ALERT", DEFAULT_MIN_ARX_TRANSFER)
    min_arx_delta = env_decimal("ARX_MIN_BALANCE_DELTA_ALERT", DEFAULT_MIN_ARX_BALANCE_DELTA)
    min_usdt_delta = env_decimal("ARX_MIN_USDT_DELTA_ALERT", DEFAULT_MIN_USDT_BALANCE_DELTA)
    for row in transfers:
        block = transfer_block(row)
        if previous_tip and block <= previous_tip:
            continue
        amount = transfer_amount(row)
        if amount < min_arx_transfer:
            continue
        alerts.append(
            {
                "type": "ARX_TRANSFER",
                "block": block,
                "hash": row.get("hash", ""),
                "from": norm(row.get("from")),
                "to": norm(row.get("to")),
                "amount": str(amount),
                "level": "CRITICAL" if amount >= Decimal("1000000") else "HIGH",
                "classification": "large_transfer",
            }
        )
    for row in balances:
        delta_raw = row.get("delta")
        if delta_raw in ("", None):
            continue
        delta = Decimal(str(delta_raw))
        threshold = min_usdt_delta if row.get("symbol") == "USDT" else min_arx_delta
        if abs(delta) >= threshold:
            alerts.append(
                {
                    "type": "BALANCE_CHANGE",
                    "token": row.get("symbol"),
                    "address": row.get("address"),
                    "label": row.get("label"),
                    "role": row.get("role", ""),
                    "event": row.get("event", ""),
                    "delta": str(delta),
                    "level": "CRITICAL" if abs(delta) >= threshold * Decimal(5) else "HIGH",
                    "classification": "event_distribution" if row.get("role") == "event_distribution" and delta < 0 else "balance_change",
                }
            )
    return alerts


def display_transfers(transfers: list[dict[str, Any]], watched: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    min_display = env_decimal("ARX_MIN_RECENT_TRANSFER_DISPLAY", DEFAULT_MIN_RECENT_TRANSFER_DISPLAY)
    rows = []
    suppressed = 0
    for row in transfers:
        amount = transfer_amount(row)
        from_item = watched.get(norm(row.get("from")), {})
        to_item = watched.get(norm(row.get("to")), {})
        if amount < min_display:
            suppressed += 1
            continue
        rows.append(format_transfer(row, watched))
    return rows, suppressed


def format_transfer(row: dict[str, Any], watched: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from_addr = norm(row.get("from"))
    to_addr = norm(row.get("to"))
    return {
        "block": transfer_block(row),
        "hash": row.get("hash", ""),
        "from": from_addr,
        "from_label": watched.get(from_addr, {}).get("label", ""),
        "to": to_addr,
        "to_label": watched.get(to_addr, {}).get("label", ""),
        "amount": str(transfer_amount(row)),
    }


def analyze_snapshot(alerts: list[dict[str, Any]], balances: list[dict[str, Any]]) -> dict[str, str]:
    opening = read_json(OPENING_PATH, {})
    opening_analysis = opening.get("analysis", {}) if isinstance(opening, dict) else {}
    opened = opening.get("status") == "opened" if isinstance(opening, dict) else False
    buyer_trace = public_trace_text(opening_analysis.get("buyer_trace_summary", ""))
    opening_spent_text = format_amount(opening_analysis.get("total_spent_usdt", ""))
    opening_bribe_text = format_amount(opening_analysis.get("max_bribe_bnb", ""))
    first_batch_text = first_batch_status_text(opening_analysis)
    pool_balance = next((Decimal(row["balance"]) for row in balances if norm(row["address"]) == norm(POOL_MANAGER) and row["symbol"] == "ARX"), Decimal(0))
    mm_arx = next((Decimal(row["balance"]) for row in balances if row.get("role") == "market_maker" and row["symbol"] == "ARX"), Decimal(0))
    mm_usdt = next((Decimal(row["balance"]) for row in balances if row.get("role") == "market_maker" and row["symbol"] == "USDT"), Decimal(0))
    transfer_alerts = [row for row in alerts if row.get("type") == "ARX_TRANSFER"]
    balance_alerts = [row for row in alerts if row.get("type") == "BALANCE_CHANGE"]
    event_out = [row for row in balance_alerts if row.get("classification") == "event_distribution"]

    if event_out:
        total_event_out = sum((abs(Decimal(str(row.get("delta", "0")))) for row in event_out), Decimal(0))
        conclusion = f"ARX 活动分发合约累计释放约 {format_amount(total_event_out)} ARX，属于后续抛压线索。"
        spot_action = "空仓观察；涨幅已大，等分发外流结束或回踩承接"
        perp_action = "合约未确认；只记录偏空条件，看到分发筹码进交易所且价格走弱再执行"
        attention = "区分 OKX/Binance/Booster 活动分发和大户主动卖出，重点看领取后是否进交易所"
    elif transfer_alerts or balance_alerts:
        mm_arx_delta = sum(
            (Decimal(str(row.get("delta", "0"))) for row in balance_alerts if row.get("role") == "market_maker" and row.get("token") == "ARX"),
            Decimal(0),
        )
        mm_usdt_delta = sum(
            (Decimal(str(row.get("delta", "0"))) for row in balance_alerts if row.get("role") == "market_maker" and row.get("token") == "USDT"),
            Decimal(0),
        )
        if mm_arx_delta < 0:
            conclusion = f"ARX 出现 MM/接货合约 ARX 外流约 {format_amount(abs(mm_arx_delta))}，需要立刻追踪去向。"
            spot_action = "空仓不追；已有仓位继续降低风险，等外流目的地确认"
            perp_action = "偏空条件升一级；有可交易合约和深度，且后续进交易所并价格走弱再执行"
            attention = "先判断这笔是换钱包、做市调仓、进池子还是进交易所；不要把活动分发和主动卖出混在一起"
        elif mm_usdt_delta < 0:
            conclusion = f"ARX 出现 MM/接货合约 USDT 减少约 {format_amount(abs(mm_usdt_delta))}，可能是承接/调仓动作。"
            spot_action = "观察；不因单笔余额变化追涨"
            perp_action = "不开空；先看是否同步买入或转入做市路径"
            attention = "继续看 MM 的 ARX 是否增加、价格是否获得承接"
        else:
            conclusion = f"ARX 关键地址出现 {len(transfer_alerts) + len(balance_alerts)} 条新告警。"
            spot_action = "观察；先确认流向，再决定是否试探"
            perp_action = "合约未确认；只记录交易所流入、价格走弱和活动分发扩大条件"
            attention = "重点看交易所、桥、池子、新钱包和后续余额变化"
    elif pool_balance > 0:
        conclusion = "ARX 已有 token 进入 v4 PoolManager，进入开盘块跟踪。"
        spot_action = "小仓试探预案；先看第一块买入和池子深度"
        perp_action = "不开空；等第一波冲高和筹码外流证据"
        attention = "注意首批 txIndex、bribe、买入地址是否项目方关联"
    elif opened:
        conclusion = f"ARX 已开盘，本窗口没有新的关键分发或大户外流；{first_batch_text}。"
        spot_action = "空仓不追；已有仓位按冲高分批止盈，等活动分发和回踩承接"
        perp_action = "合约未确认；等分发筹码进交易所、价格跌破承接位、合约深度够再执行"
        attention = "继续盯 Binance Alpha、OKX Booster、Bybit 等活动筹码是否领取后进交易所"
    else:
        conclusion = "ARX 池子参数已准备，当前没有新的关键告警。"
        spot_action = "观察；不追，等开盘块"
        perp_action = "不开空；缺少砸盘路径证据"
        attention = "注意 2026-06-22 18:00 UTC+8 的首块买入、池子深度和 bribe"

    if event_out:
        operator = "活动分发地址正在释放筹码，当前主线是活动领取后的二级卖压。"
    elif opened and not alerts:
        operator = "开盘后项目相关关键钱包本窗口暂无新增大额迁移，主线转为观察活动分发后的承接。"
    elif opened and alerts:
        operator = "开盘后关键钱包已有新动作，当前主线是追踪外流目的地和承接强弱。"
    elif mm_arx >= Decimal("3000000") and mm_usdt >= Decimal("10000000"):
        operator = "MM/接货合约同时持有大额 ARX 和 USDT，偏做市准备和承接准备。"
    elif alerts:
        operator = "项目相关筹码有新动作，需要按 tx 去向重新定性。"
    else:
        operator = "项目方维持池子启动准备，关键筹码暂无新增大额迁移。"

    if opened:
        if "清仓转出" in buyer_trace or "已外转" in buyer_trace:
            sniper = f"首批历史买入约 {opening_spent_text} USDT，当前去向显示首批钱包已撤离或迁移；按撤退信号处理。"
        else:
            sniper = f"首批历史买入约 {opening_spent_text} USDT，最大 bribe 约 {opening_bribe_text} BNB；当前去向: {buyer_trace or '未确认'}。"
    elif pool_balance > 0:
        sniper = "开盘后开始看前排买入、gas、bribe 和是否快速转出。"
    else:
        sniper = "当前还没有明确前排狙击手买入证据，真正判断点在开盘块。"

    return {
        "conclusion": conclusion,
        "spot_action": spot_action,
        "perp_action": perp_action,
        "attention": attention,
        "operator_behavior": operator,
        "sniper_behavior": sniper,
        "first_batch_status": first_batch_text,
    }


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# ARX Launch Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- blocks: `{snapshot['from_block']} -> {snapshot['latest_block']}`",
        f"- previous_latest_block: `{snapshot['previous_latest_block']}`",
        f"- transfer_rows: `{snapshot['transfer_rows']}`",
        f"- relevant_transfer_rows: `{snapshot['relevant_transfer_rows']}`",
        f"- suppressed_small_event_transfers: `{snapshot.get('suppressed_small_event_transfers', 0)}`",
        f"- alert_count: `{len(snapshot.get('alerts', []))}`",
        f"- conclusion: {snapshot['conclusion']}",
        f"- spot_action: {snapshot['analysis']['spot_action']}",
        f"- perp_action: {snapshot['analysis']['perp_action']}",
        "",
        "## Key Balances",
        "",
        "| Label | Token | Balance | Delta |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in snapshot.get("balances", []):
        lines.append(f"| {row['label']} | {row['symbol']} | {row['balance']} | {row['delta']} |")
    lines.extend(["", "## Recent Relevant ARX Transfers", ""])
    if not snapshot.get("recent_transfers"):
        lines.append("- none")
    for row in snapshot.get("recent_transfers", []):
        lines.append(f"- block `{row['block']}` `{row['amount']}` ARX: {row['from_label'] or row['from']} -> {row['to_label'] or row['to']} `{row['hash']}`")
    return "\n".join(lines) + "\n"


def alert_keys(alerts: list[dict[str, Any]]) -> list[str]:
    keys = []
    for alert in alerts:
        if alert.get("type") == "ARX_TRANSFER":
            keys.append(f"transfer|{alert.get('hash')}|{alert.get('from')}|{alert.get('to')}|{alert.get('amount')}")
        else:
            delta = Decimal(str(alert.get("delta", "0")))
            direction = "in" if delta > 0 else "out"
            rounded = abs(delta).quantize(Decimal("1"))
            keys.append(f"balance|{alert.get('token')}|{norm(alert.get('address'))}|{direction}|{rounded}")
    return sorted(set(keys))


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ARX_LAUNCH_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    seen = set(read_json(SEEN_PATH, []))
    keys = alert_keys(snapshot.get("alerts", []))
    new_keys = [key for key in keys if key not in seen]
    if not new_keys:
        return
    text = telegram_text(snapshot)
    payload = {"chat_id": chat_id, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20):
        pass
    write_json(SEEN_PATH, sorted(seen | set(keys)))


def telegram_text(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    lines = [
        "ARX 开盘监控",
        f"有效总结: {launch_effective_summary(snapshot)}",
        f"方向判断: {launch_direction(snapshot)}",
        f"结论: {snapshot['conclusion']}",
        f"现货动作: {analysis['spot_action']}",
        f"合约动作: {analysis['perp_action']}",
        f"注意: {analysis['attention']}",
        f"庄家行为: {analysis['operator_behavior']}",
        f"狙击手行为: {analysis['sniper_behavior']}",
        f"新增告警: {len(snapshot.get('alerts', []))}",
    ]
    if snapshot.get("alerts"):
        lines.append("")
        lines.append("新增证据:")
        for alert in snapshot["alerts"][:8]:
            if alert.get("type") == "ARX_TRANSFER":
                lines.append(f"- {format_amount(alert['amount'])} ARX {display_party(alert.get('from'))} -> {display_party(alert.get('to'))}")
            else:
                extra = f" ({alert.get('event')})" if alert.get("event") else ""
                lines.append(f"- {alert.get('label')}{extra} {alert.get('token')} 余额变动 {signed_amount(alert.get('delta'))}")
    if snapshot.get("suppressed_small_event_transfers"):
        lines.append("")
        lines.append(f"已折叠小额活动分发: {snapshot.get('suppressed_small_event_transfers')} 笔")
    elif snapshot.get("recent_transfers"):
        lines.append("")
        lines.append("最近相关转账已归档，本轮没有新增告警:")
        for row in snapshot["recent_transfers"][-5:]:
            lines.append(f"- {format_amount(row['amount'])} ARX {row['from_label'] or short_addr(row['from'])} -> {row['to_label'] or short_addr(row['to'])}")
    return "\n".join(lines)


def launch_effective_summary(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    alerts = snapshot.get("alerts", [])
    opening = read_json(OPENING_PATH, {})
    opening_analysis = opening.get("analysis", {}) if isinstance(opening, dict) else {}
    first_batch = analysis.get("first_batch_status", "")
    buyer_trace = public_trace_text(opening_analysis.get("buyer_trace_summary", ""))
    if alerts:
        return f"{analysis['spot_action']}；新增{len(alerts)}条关键动作；{first_batch or buyer_trace or analysis['attention']}"
    if first_batch:
        return f"{analysis['spot_action']}；本轮无新增关键外流；{first_batch}"
    if buyer_trace:
        return f"{analysis['spot_action']}；本轮无新增关键外流；{buyer_trace}"
    return f"{analysis['spot_action']}；本轮无新增关键外流；继续等活动筹码流向"


def first_batch_status_text(opening_analysis: dict[str, Any]) -> str:
    raw_spent = opening_analysis.get("total_spent_usdt", "")
    raw_bribe = opening_analysis.get("max_bribe_bnb", "")
    spent = format_amount(raw_spent) if raw_spent not in ("", None) else ""
    bribe = format_amount(raw_bribe) if raw_bribe not in ("", None) else ""
    cohort = opening_analysis.get("cohort_status_summary", "")
    buyer_trace = public_trace_text(opening_analysis.get("buyer_trace_summary", ""))
    if not spent and not cohort:
        return "首批买入规模未确认"
    base = cohort or f"首批历史买入规模约 {spent} USDT"
    if bribe:
        base = f"{base}，最大 bribe 约 {bribe} BNB"
    if buyer_trace:
        return f"{base}；当前去向: {buyer_trace}"
    return f"{base}；当前去向未确认"


def launch_direction(snapshot: dict[str, Any]) -> str:
    alerts = snapshot.get("alerts", [])
    opening = read_json(OPENING_PATH, {})
    opening_analysis = opening.get("analysis", {}) if isinstance(opening, dict) else {}
    buyer_trace = opening_analysis.get("buyer_trace_summary", "")
    mm_out = any(
        alert.get("type") == "ARX_TRANSFER"
        and norm(alert.get("from")) == norm(KEY_ADDRESSES[0]["address"])
        for alert in alerts
    )
    event_out = any(alert.get("classification") == "event_distribution" for alert in alerts)
    if "清仓转出" in buyer_trace and (mm_out or event_out):
        return "偏空；首批原买入钱包已离场且关键筹码有外流"
    if "清仓转出" in buyer_trace:
        return "偏空；首批原买入钱包已离场，等待确认是否进交易所"
    if mm_out or event_out:
        return "偏空观察；关键筹码外流，等目的地和价格确认"
    return "中性偏空；开盘竞争强，缺少追多条件"


def public_trace_text(text: str) -> str:
    return re.sub(r"；截至区块\d+", "；截至最新扫描", text or "")


def display_party(address: str | None) -> str:
    text = norm(address)
    if text == "0x0000000000000000000000000000000000000000":
        return "铸造/分发源"
    for item in KEY_ADDRESSES:
        if norm(item.get("address")) == text:
            return str(item.get("label"))
    return "未标记钱包"


def signed_amount(value: Any) -> str:
    amount = Decimal(str(value or "0"))
    sign = "+" if amount > 0 else ""
    return sign + format_amount(amount)


def format_amount(value: Any) -> str:
    amount = Decimal(str(value or "0"))
    if abs(amount) >= Decimal("1000000"):
        return f"{amount.quantize(Decimal('0.01')):f}"
    if abs(amount) >= Decimal("1"):
        return f"{amount.quantize(Decimal('0.0001')):f}"
    return f"{amount.quantize(Decimal('0.000001')):f}".rstrip("0").rstrip(".")


def short_addr(value: str) -> str:
    text = str(value or "")
    if len(text) <= 14:
        return text
    return text[:8] + "..." + text[-6:]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    write_json(LATEST_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    maybe_send_telegram(snapshot)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(snapshot["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
