#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import rpc_call


getcontext().prec = 80

CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_project_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
QUOTE_TOKENS = {
    "0x55d398326f99059ff775485246999027b3197955": "USDT",
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": "WBNB",
    "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
}
QUOTE_TOKENS_BY_CHAIN = {
    "bsc": QUOTE_TOKENS,
}
SUPPORTED_CHAINS = {"bsc", "base"}
TELEGRAM_LIMIT = 3900


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_address(value: str | None) -> bool:
    text = norm(value)
    if len(text) != 42 or not text.startswith("0x"):
        return False
    return all(ch in "0123456789abcdef" for ch in text[2:])


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


def decimal_amount(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def env_decimal(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.environ.get(name, default))
    except InvalidOperation:
        return Decimal(default)


def encode_uint_call(selector: str) -> str:
    return selector


def encode_balance_of(address: str) -> str:
    return "0x70a08231" + norm(address)[2:].rjust(64, "0")


def call_uint(chain: str, contract: str, data: str) -> int:
    raw = rpc_call(chain, "eth_call", [{"to": contract, "data": data}, "latest"])
    return int(raw or "0x0", 16)


def token_decimals(chain: str, contract: str) -> int:
    try:
        value = call_uint(chain, contract, encode_uint_call("0x313ce567"))
    except Exception:
        return 18
    return value if 0 <= value <= 36 else 18


def token_total_supply(chain: str, contract: str, decimals: int) -> str:
    try:
        return str(decimal_amount(call_uint(chain, contract, encode_uint_call("0x18160ddd")), decimals))
    except Exception:
        return ""


def token_balance(chain: str, contract: str, address: str, decimals: int) -> Decimal:
    return decimal_amount(call_uint(chain, contract, encode_balance_of(address)), decimals)


def latest_block(chain: str) -> int:
    return int(rpc_call(chain, "eth_blockNumber", []), 16)


def topic_address(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


def address_from_topic(topic: str) -> str:
    return "0x" + norm(topic)[-40:]


def log_value(row: dict[str, Any], decimals: int) -> Decimal:
    return decimal_amount(int(row.get("data") or "0x0", 16), decimals)


def block_number(row: dict[str, Any]) -> int:
    return int(row.get("blockNumber") or "0x0", 16)


def log_index(row: dict[str, Any]) -> int:
    return int(row.get("logIndex") or "0x0", 16)


def get_transfer_logs(
    chain: str,
    token_contract: str,
    watched_addresses: list[str],
    from_block: int,
    to_block: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not watched_addresses:
        return [], []
    topics = [topic_address(address) for address in watched_addresses[: int(os.environ.get("ALPHA_PROJECT_MAX_WATCH_ADDRESSES", "24"))]]
    queries = [
        [TRANSFER_TOPIC, topics, None],
        [TRANSFER_TOPIC, None, topics],
    ]
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []
    chunk_size = max(1, int(os.environ.get("ALPHA_PROJECT_LOG_CHUNK_BLOCKS", "10000")))
    for start in range(from_block, to_block + 1, chunk_size):
        end = min(to_block, start + chunk_size - 1)
        for topic_filter in queries:
            query = {
                "address": token_contract,
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "topics": topic_filter,
            }
            try:
                result = rpc_call(chain, "eth_getLogs", [query])
            except Exception as exc:
                errors.append(str(exc))
                continue
            for row in result or []:
                key = (row.get("transactionHash", ""), row.get("logIndex", ""))
                rows[key] = row
    ordered = sorted(rows.values(), key=lambda row: (block_number(row), log_index(row)))
    return ordered, errors


def transfer_row(row: dict[str, Any], decimals: int) -> dict[str, Any]:
    topics = row.get("topics", [])
    from_addr = address_from_topic(topics[1]) if len(topics) > 1 else ""
    to_addr = address_from_topic(topics[2]) if len(topics) > 2 else ""
    return {
        "block": block_number(row),
        "tx": row.get("transactionHash", ""),
        "log_index": log_index(row),
        "from": from_addr,
        "to": to_addr,
        "amount": str(log_value(row, decimals)),
    }


def load_previous() -> dict[str, Any]:
    return read_json(LATEST_PATH, {"projects": []})


def previous_contract_tips(payload: dict[str, Any]) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    for project in payload.get("projects", []):
        symbol = str(project.get("symbol", "")).upper()
        for contract in project.get("contracts", []):
            key = (symbol, contract.get("chain", ""), norm(contract.get("address")))
            out[key] = int(contract.get("latest_block") or 0)
    return out


def previous_balances(payload: dict[str, Any]) -> dict[tuple[str, str, str, str], Decimal]:
    out: dict[tuple[str, str, str, str], Decimal] = {}
    for project in payload.get("projects", []):
        symbol = str(project.get("symbol", "")).upper()
        for contract in project.get("contracts", []):
            chain = contract.get("chain", "")
            for row in contract.get("balances", []):
                token = norm(row.get("balance_token_address") or row.get("token_address") or contract.get("address"))
                key = (symbol, chain, token, norm(row.get("address")))
                try:
                    out[key] = Decimal(str(row.get("balance", "0")))
                except InvalidOperation:
                    continue
    return out


def extract_contracts(item: dict[str, Any]) -> list[dict[str, str]]:
    contracts = []
    for row in item.get("contracts", []):
        chain = str(row.get("chain", "")).lower()
        address = norm(row.get("address"))
        if chain not in SUPPORTED_CHAINS or not is_address(address):
            continue
        if address in QUOTE_TOKENS:
            continue
        contracts.append({"chain": chain, "address": address, "confidence": row.get("confidence", "")})
    return contracts


def extract_watch_addresses(item: dict[str, Any], chain: str) -> list[dict[str, Any]]:
    rows = []
    for row in item.get("watch_addresses", []):
        row_chain = str(row.get("chain", chain)).lower()
        address = norm(row.get("address"))
        if row_chain != chain or not is_address(address):
            continue
        rows.append(
            {
                "chain": row_chain,
                "address": address,
                "label": row.get("label") or short_addr(address),
                "role": row.get("role", ""),
                "level": row.get("level", "HIGH"),
                "watch_quote": bool(row.get("watch_quote", False)),
                "watch_quote_tokens": row.get("watch_quote_tokens", []),
            }
        )
    return rows


def parse_utc8(value: str) -> datetime | None:
    if not value:
        return None
    try:
        naive = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if naive.tzinfo is None:
        return naive.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    return naive.astimezone(timezone.utc)


def launch_events(item: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for pool in item.get("pool_ids", []):
        start = parse_utc8(pool.get("start_time_utc8", ""))
        if not start:
            continue
        hours = (start - now_utc()).total_seconds() / 3600
        events.append(
            {
                "chain": pool.get("chain", ""),
                "pool_id": pool.get("pool_id", ""),
                "start_time_utc": start.isoformat(),
                "start_time_utc8": pool.get("start_time_utc8", ""),
                "hours_until_start": round(hours, 2),
                "initial_price": first_value_by_prefix(pool, "initial_price"),
            }
        )
    return events


def first_value_by_prefix(payload: dict[str, Any], prefix: str) -> str:
    for key, value in payload.items():
        if str(key).startswith(prefix) and value not in ("", None):
            return str(value)
    return ""


def tx_receipts(item: dict[str, Any]) -> list[dict[str, Any]]:
    max_txs = int(os.environ.get("ALPHA_PROJECT_MAX_KNOWN_TXS", "4"))
    rows = []
    for tx in item.get("known_txs", [])[:max_txs]:
        chain = str(tx.get("chain", "")).lower()
        tx_hash = tx.get("tx", "")
        if chain not in SUPPORTED_CHAINS or not tx_hash:
            continue
        try:
            receipt = rpc_call(chain, "eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:
            rows.append({"chain": chain, "tx": tx_hash, "reason": tx.get("reason", ""), "error": str(exc)})
            continue
        if not receipt:
            rows.append({"chain": chain, "tx": tx_hash, "reason": tx.get("reason", ""), "status": "missing"})
            continue
        rows.append(
            {
                "chain": chain,
                "tx": tx_hash,
                "reason": tx.get("reason", ""),
                "status": "success" if receipt.get("status") == "0x1" else "failed",
                "block": int(receipt.get("blockNumber") or "0x0", 16),
                "tx_index": int(receipt.get("transactionIndex") or "0x0", 16),
            }
        )
    return rows


def build_snapshot() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, {"items": []})
    previous = load_previous()
    previous_tips = previous_contract_tips(previous)
    previous_balance_map = previous_balances(previous)
    finality = int(os.environ.get("ALPHA_PROJECT_FINALITY_BLOCKS", "20"))
    lookback = int(os.environ.get("ALPHA_PROJECT_LOOKBACK_BLOCKS", "50000"))
    projects = []
    skipped = []

    for item in config.get("items", []):
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        priority = item.get("priority", "")
        if item.get("active_monitoring") is False:
            skipped.append({"symbol": symbol, "reason": "archived_or_paused"})
            continue
        if item.get("project_watch_skip_generic"):
            skipped.append({"symbol": symbol, "reason": "specialized_watch"})
            continue
        if not str(priority).startswith(("P0", "P1", "P2")):
            continue
        projects.append(build_project(item, previous_tips, previous_balance_map, finality, lookback))

    alerts = [alert for project in projects for alert in project.get("alerts", [])]
    snapshot = {
        "generated_at": now_iso(),
        "config_path": str(CONFIG_PATH),
        "project_count": len(projects),
        "alert_count": len(alerts),
        "skipped": skipped,
        "projects": projects,
    }
    return snapshot


def build_project(
    item: dict[str, Any],
    previous_tips: dict[tuple[str, str, str], int],
    previous_balance_map: dict[tuple[str, str, str, str], Decimal],
    finality: int,
    lookback: int,
) -> dict[str, Any]:
    symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
    contracts = []
    alerts = []
    launches = launch_events(item)
    receipts = tx_receipts(item)
    for contract in extract_contracts(item):
        try:
            contract_payload = build_contract(symbol, contract, item, previous_tips, previous_balance_map, finality, lookback)
        except Exception as exc:
            contract_payload = build_contract_error(contract, exc)
        contracts.append(contract_payload)
        alerts.extend(contract_payload.get("alerts", []))

    start_hours = int(os.environ.get("ALPHA_PROJECT_START_ALERT_HOURS", "36"))
    for event in launches:
        hours = float(event.get("hours_until_start", 9999))
        if -1 <= hours <= start_hours and str(item.get("priority", "")).startswith(("P0", "P1")):
            alerts.append(
                {
                    "type": "LAUNCH_WINDOW",
                    "symbol": symbol,
                    "level": "HIGH" if hours > 1 else "CRITICAL",
                    "stage": launch_stage(hours),
                    "pool_id": event.get("pool_id", ""),
                    "start_time_utc8": event.get("start_time_utc8", ""),
                    "hours_until_start": hours,
                }
            )

    analysis = analyze_project(item, contracts, launches, receipts, alerts)
    return {
        "symbol": symbol,
        "name": item.get("name", ""),
        "priority": item.get("priority", ""),
        "contracts": contracts,
        "launch_events": launches,
        "tx_receipts": receipts,
        "alerts": alerts,
        "analysis": analysis,
        "required_checks": item.get("required_checks", []),
    }


def build_contract(
    symbol: str,
    contract: dict[str, str],
    item: dict[str, Any],
    previous_tips: dict[tuple[str, str, str], int],
    previous_balance_map: dict[tuple[str, str, str, str], Decimal],
    finality: int,
    lookback: int,
) -> dict[str, Any]:
    chain = contract["chain"]
    address = norm(contract["address"])
    raw_tip = latest_block(chain)
    tip = max(0, raw_tip - finality)
    from_block = max(0, tip - lookback)
    previous_tip = previous_tips.get((symbol, chain, address), 0)
    decimals = token_decimals(chain, address)
    total_supply = token_total_supply(chain, address, decimals)
    watch_addresses = extract_watch_addresses(item, chain)
    watch_addr_values = [row["address"] for row in watch_addresses]
    logs, log_errors = get_transfer_logs(chain, address, watch_addr_values, from_block, tip)
    transfers = [transfer_row(row, decimals) for row in logs[-40:]]
    balances = build_balances(symbol, chain, address, decimals, watch_addresses, previous_balance_map)
    alerts = build_contract_alerts(symbol, chain, address, previous_tip, transfers, balances)
    return {
        "chain": chain,
        "address": address,
        "confidence": contract.get("confidence", ""),
        "raw_latest_block": raw_tip,
        "latest_block": tip,
        "previous_latest_block": previous_tip,
        "from_block": from_block,
        "finality_blocks": finality,
        "lookback_blocks": lookback,
        "decimals": decimals,
        "total_supply": total_supply,
        "watch_address_count": len(watch_addresses),
        "log_error_count": len(log_errors),
        "log_errors": log_errors[:3],
        "balances": balances,
        "recent_transfers": transfers,
        "alerts": alerts,
    }


def build_contract_error(contract: dict[str, str], exc: Exception) -> dict[str, Any]:
    return {
        "chain": contract.get("chain", ""),
        "address": norm(contract.get("address")),
        "confidence": contract.get("confidence", ""),
        "raw_latest_block": 0,
        "latest_block": 0,
        "previous_latest_block": 0,
        "from_block": 0,
        "finality_blocks": 0,
        "lookback_blocks": 0,
        "decimals": 18,
        "total_supply": "",
        "watch_address_count": 0,
        "log_error_count": 1,
        "log_errors": [str(exc)],
        "balances": [],
        "recent_transfers": [],
        "alerts": [],
        "error": str(exc),
    }


def build_balances(
    symbol: str,
    chain: str,
    token: str,
    decimals: int,
    watch_addresses: list[dict[str, Any]],
    previous_balance_map: dict[tuple[str, str, str, str], Decimal],
) -> list[dict[str, Any]]:
    rows = []
    for item in watch_addresses:
        address = norm(item.get("address"))
        balance_targets = [(norm(token), symbol, decimals, False)]
        if item.get("watch_quote"):
            balance_targets.extend(quote_balance_targets(chain, item))
        for balance_token, balance_symbol, balance_decimals, is_quote in balance_targets:
            try:
                balance = token_balance(chain, balance_token, address, balance_decimals)
            except Exception as exc:
                rows.append(
                    {
                        **item,
                        "balance_token": balance_symbol,
                        "balance_token_address": balance_token,
                        "is_quote_balance": is_quote,
                        "balance": "",
                        "previous_balance": "",
                        "delta": "",
                        "error": str(exc),
                    }
                )
                continue
            key = (symbol, chain, balance_token, address)
            previous = previous_balance_map.get(key)
            delta = "" if previous is None else str(balance - previous)
            rows.append(
                {
                    **item,
                    "balance_token": balance_symbol,
                    "balance_token_address": balance_token,
                    "is_quote_balance": is_quote,
                    "balance": str(balance),
                    "previous_balance": "" if previous is None else str(previous),
                    "delta": delta,
                }
            )
    return rows


def quote_balance_targets(chain: str, watch_item: dict[str, Any]) -> list[tuple[str, str, int, bool]]:
    tokens = QUOTE_TOKENS_BY_CHAIN.get(chain, {})
    requested = [str(row).upper() for row in watch_item.get("watch_quote_tokens") or ["USDT"]]
    rows = []
    for address, symbol in tokens.items():
        if requested and symbol.upper() not in requested and address.upper() not in requested:
            continue
        rows.append((address, symbol, token_decimals(chain, address), True))
    return rows


def build_contract_alerts(
    symbol: str,
    chain: str,
    token: str,
    previous_tip: int,
    transfers: list[dict[str, Any]],
    balances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts = []
    min_transfer = env_decimal("ALPHA_PROJECT_MIN_TRANSFER_ALERT", "100000")
    min_balance_delta = env_decimal("ALPHA_PROJECT_MIN_BALANCE_DELTA_ALERT", "100000")
    min_quote_delta = env_decimal("ALPHA_PROJECT_MIN_QUOTE_BALANCE_DELTA_ALERT", "10000")
    for row in transfers:
        if previous_tip and int(row.get("block") or 0) <= previous_tip:
            continue
        amount = Decimal(str(row.get("amount", "0")))
        if amount < min_transfer:
            continue
        alerts.append(
            {
                "type": "TOKEN_TRANSFER",
                "symbol": symbol,
                "chain": chain,
                "token": token,
                "level": "CRITICAL" if amount >= min_transfer * Decimal(5) else "HIGH",
                "block": row.get("block"),
                "tx": row.get("tx"),
                "from": row.get("from"),
                "to": row.get("to"),
                "amount": str(amount),
            }
        )
    for row in balances:
        delta_raw = row.get("delta")
        if delta_raw in ("", None):
            continue
        delta = Decimal(str(delta_raw))
        balance_token = row.get("balance_token") or symbol
        balance_token_address = norm(row.get("balance_token_address") or token)
        threshold = min_quote_delta if row.get("is_quote_balance") else min_balance_delta
        if abs(delta) < threshold:
            continue
        alerts.append(
            {
                "type": "BALANCE_CHANGE",
                "symbol": symbol,
                "chain": chain,
                "token": balance_token,
                "token_address": balance_token_address,
                "is_quote_balance": bool(row.get("is_quote_balance")),
                "level": "CRITICAL" if abs(delta) >= threshold * Decimal(5) else "HIGH",
                "address": row.get("address"),
                "label": row.get("label", ""),
                "role": row.get("role", ""),
                "delta": str(delta),
            }
        )
    return alerts


def analyze_project(
    item: dict[str, Any],
    contracts: list[dict[str, Any]],
    launches: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> dict[str, str]:
    symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
    movement_alerts = [row for row in alerts if row.get("type") in {"TOKEN_TRANSFER", "BALANCE_CHANGE"}]
    critical = [row for row in movement_alerts if row.get("level") == "CRITICAL"]
    transfer_alerts = [row for row in alerts if row.get("type") == "TOKEN_TRANSFER"]
    balance_alerts = [row for row in alerts if row.get("type") == "BALANCE_CHANGE"]
    launch_alerts = [row for row in alerts if row.get("type") == "LAUNCH_WINDOW"]
    watched = sum(int(contract.get("watch_address_count") or 0) for contract in contracts)
    pool_token_out = sum_balance_delta(
        balance_alerts,
        token=symbol,
        roles={"pool", "pool_manager", "v4_pool_manager"},
        sign="out",
    )
    pool_token_in = sum_balance_delta(
        balance_alerts,
        token=symbol,
        roles={"pool", "pool_manager", "v4_pool_manager"},
        sign="in",
    )
    activity_out = sum_balance_delta(balance_alerts, token=symbol, roles={"event_distribution"}, sign="out")
    quote_in = sum_balance_delta(balance_alerts, quote=True, sign="in")
    quote_out = sum_balance_delta(balance_alerts, quote=True, sign="out")
    pool_structure = pool_structure_summary(item)

    if pool_token_out:
        conclusion = f"{symbol} 池子卖出区正在被买盘吃掉，PoolManager {symbol} 减少约 {format_amount(pool_token_out)}。"
        spot_action = "空仓不追；持仓按冲高降风险，等回踩承接和项目侧资金去向"
        perp_action = "偏空预案；等交易所流入、价格转弱和可交易合约深度"
        attention = "卖出区消耗后继续看项目/做市地址是否回收 USDT、是否跨链或进交易所"
        operator = "项目方预设卖出区被买盘接走，下一步确认报价资产是否离开池子路径。"
        sniper = "狙击买盘和跟风买盘正在承接卖出区，若买盘衰竭容易出现冲高回落。"
    elif quote_in:
        conclusion = f"{symbol} 关键地址收到报价资产约 {format_amount(quote_in)}，需要确认来源是否来自池子卖出区或做市回收。"
        spot_action = "空仓不追；已有仓位降低风险，等报价资产来源确认"
        perp_action = "偏空条件；若同步出现价格走弱和交易所流入，再执行"
        attention = "打开最新 tx，看对手方是池子、聚合器、CEX 还是内部钱包"
        operator = "项目/做市相关地址正在接收报价资产，可能是回收流动性或卖出区收益归集。"
        sniper = "狙击手信号降权，当前主线切到项目侧资金回收。"
    elif activity_out:
        conclusion = f"{symbol} 活动分发地址释放约 {format_amount(activity_out)} {symbol}，属于后续抛压线索。"
        spot_action = "空仓观察；已持仓按冲高分批降风险"
        perp_action = "偏空预案；等活动筹码进交易所、价格走弱和合约深度"
        attention = "区分 Alpha/Booster/交易所活动分发和主动大户卖出，重点看领取后去向"
        operator = "活动筹码正在释放，主线是分发后的二级卖压。"
        sniper = "首批买家信号需要结合活动分发节奏，单独看首批买入容易误判。"
    elif pool_token_in:
        conclusion = f"{symbol} PoolManager {symbol} 增加约 {format_amount(pool_token_in)}，可能是补池子或区间调整。"
        spot_action = "观察；先看新增区间价格和深度"
        perp_action = "不开仓；补池子方向确认后再判断"
        attention = "确认是加池、改区间、迁移池子还是普通转入"
        operator = "项目方可能在调整流动性结构，先还原价格区间。"
        sniper = "狙击判断要等新区间和真实买入出现。"
    elif quote_out:
        conclusion = f"{symbol} 关键地址转出报价资产约 {format_amount(quote_out)}，需要追踪下一跳。"
        spot_action = "观察偏谨慎；持仓先降风险"
        perp_action = "偏空条件；等去向进交易所或价格走弱"
        attention = "确认报价资产是做市调仓、跨链、归集，还是进入交易所"
        operator = "项目/做市地址出现报价资产转移，资金路径需要继续追。"
        sniper = "狙击手行为不是当前主信号，优先看项目侧资金路径。"
    elif critical or transfer_alerts or balance_alerts:
        conclusion = f"{symbol} 关键地址出现新动作，进入深度验证。"
        spot_action = "观察；先打开最新 tx，确认流向交易所、池子、桥或新中转钱包"
        perp_action = "合约未确认；只记录偏空条件，等交易所充值、大户外流或首波冲高回落证据"
        attention = "重点看 txIndex、counterparty、bribe、池子深度和后续余额变化"
        operator = "项目相关筹码或关键地址正在移动，当前优先判断筹码管理节奏。"
        sniper = "狙击判断点在开盘块前后买入排序、gas/bribe 和买入后是否快速转出。"
    elif launch_alerts:
        conclusion = f"{symbol} 已进入上线窗口，开始开盘块预案。"
        spot_action = launch_spot_plan(item)
        perp_action = launch_perp_plan(item)
        attention = launch_attention(item)
        operator = "项目方已释放上线或池子信号，下一步看是否补池子和控筹。"
        sniper = "狙击手通常会在池子可交易后的首块竞争，重点看同块排序和贿赂。"
    elif contracts and watched == 0:
        conclusion = f"{symbol} 已有合约线索，缺少关键地址监控。"
        spot_action = "观察；先补官方合约、池子、分发、做市和空投地址"
        perp_action = "不开仓；缺少筹码流向和价格结构"
        attention = "把团队、部署、加池、分发、桥和 CEX 充值地址补进 watch_addresses"
        operator = "当前只能确认合约线索，项目方实时行为证据不足。"
        sniper = "当前无法判断外部狙击和项目方自买，需要开盘块与关键地址。"
    elif contracts:
        conclusion = f"{symbol} 暂无新增关键告警。"
        spot_action = "观察；等待池子、上线时间或关键地址变化"
        perp_action = "不开仓；等更强催化和链上证据"
        attention = "保留监控，新增池子或分发地址后会升级"
        operator = "项目方暂无可确认的新链上动作。"
        sniper = "暂无前排买入或狙击竞争证据。"
    else:
        conclusion = f"{symbol} 缺少可监控合约。"
        spot_action = "先补合约；暂不下单"
        perp_action = "不开仓；无链上锚点"
        attention = "从官方公告、BscScan、Basescan、Alpha 池子推送补齐合约"
        operator = "没有合约锚点，项目方行为无法落到链上验证。"
        sniper = "没有合约和池子，无法判断狙击窗口。"

    if receipts:
        tx_summary = "; ".join(f"{short_tx(row.get('tx',''))}:{row.get('status','')}" for row in receipts[:3])
        attention = f"{attention}; known_tx {tx_summary}"
    if pool_structure and "池子结构" not in attention:
        attention = f"{attention}; {pool_structure}"

    return {
        "conclusion": conclusion,
        "spot_action": spot_action,
        "perp_action": perp_action,
        "attention": attention,
        "operator_behavior": operator,
        "sniper_behavior": sniper,
    }


def sum_balance_delta(
    alerts: list[dict[str, Any]],
    *,
    token: str | None = None,
    roles: set[str] | None = None,
    quote: bool | None = None,
    sign: str | None = None,
) -> Decimal:
    total = Decimal(0)
    for row in alerts:
        if row.get("type") != "BALANCE_CHANGE":
            continue
        if token and str(row.get("token", "")).upper() != token.upper():
            continue
        if quote is not None and bool(row.get("is_quote_balance")) != quote:
            continue
        if roles and str(row.get("role", "")) not in roles:
            continue
        delta = Decimal(str(row.get("delta", "0")))
        if sign == "out" and delta >= 0:
            continue
        if sign == "in" and delta <= 0:
            continue
        total += abs(delta)
    return total


def pool_structure_summary(item: dict[str, Any]) -> str:
    context = item.get("market_context", {})
    zones = context.get("pool_zones") or []
    if not zones:
        return ""
    buy_support = sum_decimal(row.get("quote_amount") for row in zones if row.get("type") == "buy_support")
    sell_zone = sum_decimal(row.get("token_amount") for row in zones if row.get("type") == "sell_zone")
    overrange = context.get("overrange_buy_pressure_quote") or ""
    parts = []
    if buy_support:
        parts.append(f"买入支撑约 {format_amount(buy_support)} USDT")
    if sell_zone:
        parts.append(f"卖出区约 {format_amount(sell_zone)} {item.get('symbol', '').upper()}")
    if overrange:
        parts.append(f"{format_amount(overrange)} USDT 买压可能出区间")
    return "池子结构: " + "，".join(parts) if parts else ""


def sum_decimal(values: Any) -> Decimal:
    total = Decimal(0)
    for value in values:
        try:
            total += Decimal(str(value or "0"))
        except InvalidOperation:
            continue
    return total


def alert_keys(alerts: list[dict[str, Any]]) -> list[str]:
    keys = []
    for alert in alerts:
        kind = alert.get("type", "")
        if kind == "TOKEN_TRANSFER":
            keys.append(
                "|".join(
                    [
                        "transfer",
                        alert.get("symbol", ""),
                        alert.get("chain", ""),
                        norm(alert.get("token")),
                        alert.get("tx", ""),
                        str(alert.get("amount", "")),
                    ]
                )
            )
        elif kind == "BALANCE_CHANGE":
            delta = Decimal(str(alert.get("delta", "0")))
            direction = "in" if delta > 0 else "out"
            keys.append(
                "|".join(
                    [
                        "balance",
                        alert.get("symbol", ""),
                        alert.get("chain", ""),
                        norm(alert.get("token")),
                        norm(alert.get("address")),
                        str(alert.get("role", "")),
                        direction,
                        alert_amount_bucket(abs(delta), balance_alert_bucket(alert)),
                    ]
                )
            )
        elif kind == "LAUNCH_WINDOW":
            keys.append("|".join(["launch", alert.get("symbol", ""), alert.get("stage", ""), alert.get("pool_id", ""), alert.get("start_time_utc8", "")]))
    return sorted(set(keys))


def balance_alert_bucket(alert: dict[str, Any]) -> Decimal:
    if alert.get("is_quote_balance"):
        return env_decimal("ALPHA_PROJECT_QUOTE_ALERT_BUCKET", "50000")
    role = str(alert.get("role", ""))
    if role == "event_distribution":
        return env_decimal("ALPHA_PROJECT_DISTRIBUTION_ALERT_BUCKET", "500000")
    return env_decimal("ALPHA_PROJECT_TOKEN_ALERT_BUCKET", "250000")


def alert_amount_bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    if step <= 0:
        step = Decimal("1")
    return format((value // step) * step, "f")


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ALPHA_PROJECT_WATCH_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    keys = alert_keys([alert for project in snapshot.get("projects", []) for alert in project.get("alerts", [])])
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if key not in seen]
    if not new_keys and os.environ.get("ALPHA_PROJECT_WATCH_FORCE_TELEGRAM") != "1":
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ALPHA_PROJECT_WATCH_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    text = telegram_text(
        {**snapshot, "new_alert_count": len(new_keys), "_telegram_new_alert_keys": new_keys}
    )
    payload = {"chat_id": chat_id, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20):
        pass
    write_json(SEEN_PATH, sorted(seen | set(keys)))
    record_push(snapshot)


def project_push_signature(snapshot: dict[str, Any]) -> str:
    parts = []
    for project in snapshot.get("projects", [])[:5]:
        analysis = project.get("analysis", {})
        alert_parts = []
        for alert in project.get("alerts", [])[:8]:
            if alert.get("type") == "BALANCE_CHANGE":
                delta = abs(Decimal(str(alert.get("delta", "0"))))
                direction = "in" if Decimal(str(alert.get("delta", "0"))) > 0 else "out"
                alert_parts.append(
                    "|".join(
                        [
                            "balance",
                            str(alert.get("token", "")),
                            str(alert.get("role", "")),
                            direction,
                            alert_amount_bucket(delta, balance_alert_bucket(alert)),
                        ]
                    )
                )
            elif alert.get("type") == "LAUNCH_WINDOW":
                alert_parts.append("|".join(["launch", str(alert.get("stage", "")), str(alert.get("start_time_utc8", ""))]))
            else:
                alert_parts.append(str(alert.get("type", "")))
        parts.append(
            "|".join(
                [
                    str(project.get("symbol", "")),
                    str(analysis.get("spot_action", "")),
                    str(analysis.get("perp_action", "")),
                    ",".join(sorted(alert_parts)),
                ]
            )
        )
    return "\n".join(parts)


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ALPHA_PROJECT_REPEAT_SUPPRESS_MINUTES", "30"))
    if ttl_minutes <= 0:
        return False
    last = read_json(LAST_PUSH_PATH, {})
    if last.get("signature") != project_push_signature(snapshot):
        return False
    try:
        sent_at = datetime.fromisoformat(str(last.get("sent_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    return now_utc() - sent_at.astimezone(timezone.utc) < timedelta(minutes=ttl_minutes)


def record_push(snapshot: dict[str, Any]) -> None:
    write_json(LAST_PUSH_PATH, {"sent_at": now_iso(), "signature": project_push_signature(snapshot)})


def telegram_compact_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value or 0))
    except InvalidOperation:
        return str(value or "0")
    if amount == 0:
        return "0"
    absolute = abs(amount)
    if absolute >= Decimal("1000000"):
        scaled, suffix = amount / Decimal("1000000"), "M"
    elif absolute >= Decimal("1000"):
        scaled, suffix = amount / Decimal("1000"), "K"
    else:
        scaled, suffix = amount, ""
    if abs(scaled) < Decimal("1"):
        places = Decimal("0.0001")
    elif abs(scaled) < Decimal("100"):
        places = Decimal("0.1")
    else:
        places = Decimal("1")
    text = f"{scaled.quantize(places):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + suffix


def telegram_alert_rank(project: dict[str, Any]) -> tuple[int, int, str]:
    levels = {str(alert.get("level", "")).upper() for alert in project.get("alerts", [])}
    level_rank = 0 if "CRITICAL" in levels else 1 if "HIGH" in levels else 2
    priority = str(project.get("priority", ""))
    priority_rank = int(priority[1]) if len(priority) > 1 and priority[1].isdigit() else 9
    return level_rank, priority_rank, str(project.get("symbol", ""))


def telegram_alert_summary(alert: dict[str, Any]) -> str:
    kind = alert.get("type")
    level = str(alert.get("level") or "ALERT").upper()
    if kind == "TOKEN_TRANSFER":
        return f"{level} {alert.get('symbol', '')}转移{telegram_compact_amount(alert.get('amount'))}"
    if kind == "BALANCE_CHANGE":
        try:
            delta = Decimal(str(alert.get("delta") or 0))
        except InvalidOperation:
            delta = Decimal(0)
        direction = "流入" if delta > 0 else "流出"
        token = alert.get("token") or alert.get("symbol", "")
        return f"{level} {token}{direction}{telegram_compact_amount(abs(delta))}"
    if kind == "LAUNCH_WINDOW":
        return f"{level} {alert.get('stage', '')}上线窗口"
    return level


def telegram_text(snapshot: dict[str, Any]) -> str:
    new_keys = set(snapshot.get("_telegram_new_alert_keys") or [])
    projects = sorted(
        (project for project in snapshot.get("projects", []) if project.get("alerts")),
        key=lambda project: (
            0 if new_keys.intersection(alert_keys(project.get("alerts", []))) else 1,
            *telegram_alert_rank(project),
        ),
    )
    new_count = snapshot.get("new_alert_count", snapshot.get("alert_count", 0))
    lines = [f"Alpha项目｜新增{new_count}｜触发{len(projects)}"]
    for project in projects[:2]:
        analysis = project.get("analysis", {})
        alerts = sorted(
            project.get("alerts", []),
            key=lambda row: (
                0 if new_keys.intersection(alert_keys([row])) else 1,
                0 if str(row.get("level") or "").upper() == "CRITICAL" else 1,
            ),
        )
        project_levels = {str(row.get("level") or "").upper() for row in alerts}
        marker = "🔴" if "CRITICAL" in project_levels else "🟠"
        evidence = telegram_alert_summary(alerts[0])
        if len(alerts) > 1:
            evidence += f"｜另{len(alerts) - 1}条"
        lines.extend(
            [
                f"{marker} {project.get('symbol')} {project.get('priority')}｜{evidence}",
                f"判断：{analysis.get('conclusion', '')}",
                f"动作：{analysis.get('spot_action', '')}",
            ]
        )
    overflow = len(projects) - 2
    if overflow > 0:
        lines.append(f"另有{overflow}项｜详情已归档")
    elif projects:
        lines.append("详情已归档")
    return "\n".join(lines)
def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Project Watch",
        "",
        f"- generated_at: `{snapshot.get('generated_at')}`",
        f"- project_count: `{snapshot.get('project_count')}`",
        f"- alert_count: `{snapshot.get('alert_count')}`",
        f"- skipped: `{len(snapshot.get('skipped', []))}`",
        "",
    ]
    for project in snapshot.get("projects", []):
        analysis = project.get("analysis", {})
        lines.extend(
            [
                f"## {project.get('symbol')} ({project.get('priority')})",
                "",
                f"- conclusion: {analysis.get('conclusion', '')}",
                f"- spot_action: {analysis.get('spot_action', '')}",
                f"- perp_action: {analysis.get('perp_action', '')}",
                f"- attention: {analysis.get('attention', '')}",
                f"- alerts: `{len(project.get('alerts', []))}`",
                "",
                "| Chain | Contract | Block Range | Watch Addresses | Supply |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for contract in project.get("contracts", []):
            lines.append(
                "| "
                + " | ".join(
                    [
                        contract.get("chain", ""),
                        short_addr(contract.get("address", "")),
                        f"{contract.get('from_block')} -> {contract.get('latest_block')}",
                        str(contract.get("watch_address_count", 0)),
                        format_amount(contract.get("total_supply", "")),
                    ]
                )
                + " |"
            )
        if project.get("launch_events"):
            lines.extend(["", "Launch events:"])
            for event in project.get("launch_events", []):
                lines.append(
                    f"- `{event.get('start_time_utc8')}` UTC+8 pool `{short_tx(event.get('pool_id',''))}` hours `{event.get('hours_until_start')}` price `{event.get('initial_price')}`"
                )
        if project.get("alerts"):
            lines.extend(["", "Alerts:"])
            for alert in project.get("alerts", []):
                lines.append(f"- {format_alert(alert)}")
        lines.append("")
    return "\n".join(lines)


def format_alert(alert: dict[str, Any]) -> str:
    kind = alert.get("type")
    if kind == "TOKEN_TRANSFER":
        return f"{alert.get('level')} {alert.get('symbol')} {format_amount(alert.get('amount'))} {short_addr(alert.get('from',''))}->{short_addr(alert.get('to',''))} tx {short_tx(alert.get('tx',''))}"
    if kind == "BALANCE_CHANGE":
        return f"{alert.get('level')} {alert.get('symbol')} {alert.get('label') or short_addr(alert.get('address',''))} {alert.get('token', '')} delta {format_amount(alert.get('delta'))}"
    if kind == "LAUNCH_WINDOW":
        return f"{alert.get('level')} {alert.get('symbol')} launch {alert.get('start_time_utc8')} UTC+8, {alert.get('stage')} stage"
    return json.dumps(alert, ensure_ascii=False)


def launch_stage(hours_until_start: float) -> str:
    hours = Decimal(str(hours_until_start))
    if hours <= 0:
        return "open"
    if hours <= Decimal("0.17"):
        return "10m"
    if hours <= 1:
        return "1h"
    if hours <= 6:
        return "6h"
    return "36h"


def launch_spot_plan(item: dict[str, Any]) -> str:
    context = item.get("market_context", {})
    snipe_pressure = (
        context.get("snipe_200k_reaches_usdt")
        or context.get("snipe_400k_reaches_usdt")
        or context.get("snipe_400k_end_price_usdt")
    )
    if snipe_pressure:
        return "只看首块执行；若大额买入或高bribe把价格打到压力位，空仓不追；只有低bribe、低滑点、买后持有才考虑小仓"
    return "准备小仓试探条件；只在首块低bribe、低滑点、买后持有时执行"


def launch_perp_plan(item: dict[str, Any]) -> str:
    if item.get("event_distributions"):
        return "不开仓；活动筹码领取后若流向交易所且价格走弱，再等可交易合约和深度"
    return "不开空；等待现货拉升、筹码外流和可交易合约深度"


def launch_attention(item: dict[str, Any]) -> str:
    context = item.get("market_context", {})
    parts = ["提前打开官方合约、池子、holder、开盘块和前排tx"]
    anchors = []
    pool_price = first_value_by_prefix(context, "pool_init_price")
    if pool_price:
        anchors.append(f"池子{pool_price}")
    public_sale = first_value_by_prefix(context, "coinlist_public_sale_price") or first_value_by_prefix(context, "public_sale_price")
    if public_sale:
        anchors.append(f"公募{public_sale}")
    premarket = first_value_by_prefix(context, "premarket_reference_price")
    if premarket:
        anchors.append(f"盘前{premarket}")
    snipe_price = first_value_by_prefix(context, "snipe_400k_end_price") or first_value_by_prefix(context, "snipe_400k_reaches")
    if snipe_price:
        anchors.append(f"40万买压终点{ snipe_price }")
    if anchors:
        parts.append("价格锚点: " + "、".join(anchors))
    structure = pool_structure_summary(item)
    if structure:
        parts.append(structure)
    if context.get("pool_range_note") and not structure:
        parts.append("池子结构: " + str(context["pool_range_note"]))
    if context.get("quality_note"):
        parts.append("质量备注: " + str(context["quality_note"]))
    if item.get("event_distributions"):
        names = "、".join(str(row.get("name", "")) for row in item.get("event_distributions", [])[:3] if row.get("name"))
        parts.append(f"活动分发: {names}，后续看领取后是否进交易所")
    return "；".join(parts)


def format_amount(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return text
    if amount == 0:
        return "0"
    if abs(amount) >= Decimal("1000000"):
        return f"{amount.quantize(Decimal('0.01')):f}"
    if abs(amount) >= Decimal("1"):
        return f"{amount.quantize(Decimal('0.0001')):f}"
    return f"{amount.normalize():f}"


def short_addr(value: str) -> str:
    text = str(value or "")
    if len(text) <= 14:
        return text
    return text[:8] + "..." + text[-6:]


def short_tx(value: str) -> str:
    return short_addr(value)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    write_json(LATEST_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    maybe_send_telegram(snapshot)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(f"projects={snapshot['project_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
