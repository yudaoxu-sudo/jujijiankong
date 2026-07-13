#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label, global_address_labels
from sniper_engine.rpc import get_block_by_number, get_transaction_receipt, hex_to_int, rpc_call, rpc_call_url, rpc_urls
from scripts.build_pancake_v4_roundtrip_fixture import build_fixture


getcontext().prec = 80

CHAIN = "bsc"
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_opening_block_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
INCREASE_LIQUIDITY_TOPIC = "0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f"
DECREASE_LIQUIDITY_TOPIC = "0x26f6a048ee9138f2c0ce266f322cb99228e8d619ae2bff30c67f8dcf9d2377b4"
COLLECT_TOPIC = "0x40d0efd1a53d60ecbf40971b9daf7dc90178c3aadc7aab1765632738fa8b8f01"
BURN_TOPIC = "0xb90306ad06b2a6ff86ddc9327db583062895ef6540e62dc50add009db5b356eb"
MODIFY_LIQUIDITY_TOPIC = "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec"
QUOTE_EXACT_INPUT_SINGLE_SELECTOR = "0xc6a5026a"
LIQUIDITY_EVENT_TOPICS = {
    INCREASE_LIQUIDITY_TOPIC,
    DECREASE_LIQUIDITY_TOPIC,
    COLLECT_TOPIC,
    BURN_TOPIC,
    MODIFY_LIQUIDITY_TOPIC,
}
ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
USDT = "0x55d398326f99059ff775485246999027b3197955"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
PANCAKE_V3_QUOTER_V2 = "0xb048bbc1ee6b733fffcfb9e9cef7375518e25997"
PANCAKE_V3_ROUTER = "0x1b81d678ffb9c0263b24a97847620c99d213eb14"
PANCAKE_V3_EXACT_INPUT_SINGLE_SELECTOR = "0x04e45aaf"
PANCAKE_INFINITY_UNIVERSAL_ROUTER = "0xd9c500dff816a1da21a48a732d3498bf09dc9aeb"
PANCAKE_INFINITY_CL_QUOTER = "0xd0737c9762912dd34c3271197e362aa736df0926"
PANCAKE_INFINITY_CL_POOL_MANAGER = "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"
PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR = "0x9938b8ed"
PANCAKE_PERMIT2 = "0x31c2f6fcff4f8759b3bd5bf0e1084a055615c768"
PERMIT2_ALLOWANCE_SELECTOR = "0x927da105"
DEFAULT_QUOTE_BALANCE_SLOT = 1
DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT = 2
DEFAULT_PERMIT2_ALLOWANCE_SLOT = 1
MAX_UINT256 = 2**256 - 1
MAX_UINT160 = 2**160 - 1
MAX_UINT48 = 2**48 - 1
QUOTE_TOKENS = {USDT: "USDT", WBNB: "WBNB"}
TELEGRAM_LIMIT = 3600
CODE_CACHE: dict[tuple[str, str], bool] = {}
CONTRACT_SAFETY_CACHE: dict[tuple[str, str], dict[str, str]] = {}
BALANCE_SLOT_CACHE: dict[tuple[str, str], int | None] = {}
ALLOWANCE_SLOT_CACHE: dict[tuple[str, str, str], int | None] = {}
INFINITY_ROUNDTRIP_CACHE: dict[tuple[str, str, str, int, int], dict[str, str]] = {}
POOL_FLOW_ROLES = {"pool", "pool_manager", "v4_pool_manager", "pool_hook", "hook_operator", "market_maker", "mm", "liquidity"}
PROTOCOL_COUNTERPARTY_CLASSES = {
    "dex_router",
    "dex_quoter",
    "dex_vault",
    "exchange_aggregator",
    "exchange_aggregator_suspect",
    "exchange_rebalance",
    "lp_position_manager",
    "pool_manager",
    "permit2",
    "quote_token",
}
OWNER_SELECTORS = {
    "owner": "0x8da5cb5b",
    "getOwner": "0x893d20e8",
}
ADMIN_SELECTORS = {
    "implementation": "0x5c60da1b",
    "admin": "0xf851a440",
}
BOOL_RISK_SELECTORS = {
    "paused": "0x5c975abb",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_address(value: str | None) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def topic_addr(topic: str) -> str:
    return "0x" + strip0x(norm(topic))[-40:]


def address_topic(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


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


def parse_utc8(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc)


def decimal_amount(raw: int, decimals: int = 18) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def decimal_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def decimal_from(value: Any, default: Decimal = Decimal(0)) -> Decimal:
    if value in ("", None):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def token_call(chain: str, address: str, selector: str) -> str:
    return rpc_call(chain, "eth_call", [{"to": address, "data": selector}, "latest"]) or "0x"


def decode_abi_string(data: str) -> str:
    raw = strip0x(data or "0x")
    try:
        if len(raw) >= 128 and int(raw[:64], 16) == 32:
            size = int(raw[64:128], 16)
            return bytes.fromhex(raw[128 : 128 + size * 2]).decode("utf-8", errors="ignore").strip("\x00")
        if len(raw) == 64:
            return bytes.fromhex(raw).decode("utf-8", errors="ignore").strip("\x00")
    except Exception:
        return ""
    return ""


def token_meta(chain: str, address: str, fallback_symbol: str = "") -> dict[str, Any]:
    symbol = fallback_symbol
    name = ""
    decimals = 18
    try:
        symbol = decode_abi_string(token_call(chain, address, "0x95d89b41")) or symbol
    except Exception:
        pass
    try:
        name = decode_abi_string(token_call(chain, address, "0x06fdde03"))
    except Exception:
        pass
    try:
        raw = token_call(chain, address, "0x313ce567")
        parsed = int(raw or "0x0", 16)
        if 0 <= parsed <= 36:
            decimals = parsed
    except Exception:
        pass
    return {"address": norm(address), "symbol": symbol.upper(), "name": name, "decimals": decimals}


def latest_block_number(chain: str) -> int:
    return int(rpc_call(chain, "eth_blockNumber", []), 16)


def block_timestamp(chain: str, block_number: int) -> int:
    block = get_block_by_number(chain, block_number, full_transactions=False)
    return int(block.get("timestamp") or "0x0", 16)


def first_block_at_or_after(chain: str, target_ts: int, latest_block: int) -> int | None:
    if block_timestamp(chain, latest_block) < target_ts:
        return None
    low = 0
    high = latest_block
    while low < high:
        mid = (low + high) // 2
        if block_timestamp(chain, mid) >= target_ts:
            high = mid
        else:
            low = mid + 1
    return low


def get_logs(chain: str, query: dict[str, Any], chunk_blocks: int, max_logs: int) -> list[dict[str, Any]]:
    from_block = int(query["fromBlock"], 16)
    to_block = int(query["toBlock"], 16)
    rows: list[dict[str, Any]] = []
    start = from_block
    while start <= to_block and len(rows) < max_logs:
        end = min(to_block, start + chunk_blocks - 1)
        chunk_query = dict(query)
        chunk_query["fromBlock"] = hex(start)
        chunk_query["toBlock"] = hex(end)
        rows.extend(rpc_call(chain, "eth_getLogs", [chunk_query]) or [])
        start = end + 1
    return rows[:max_logs]


def get_logs_quick(chain: str, query: dict[str, Any], chunk_blocks: int, max_logs: int, timeout: int) -> list[dict[str, Any]]:
    from_block = int(query["fromBlock"], 16)
    to_block = int(query["toBlock"], 16)
    rows: list[dict[str, Any]] = []
    start = from_block
    while start <= to_block and len(rows) < max_logs:
        end = min(to_block, start + chunk_blocks - 1)
        chunk_query = dict(query)
        chunk_query["fromBlock"] = hex(start)
        chunk_query["toBlock"] = hex(end)
        try:
            rows.extend(quick_rpc_call(chain, "eth_getLogs", [chunk_query], timeout) or [])
        except Exception:
            break
        start = end + 1
    return rows[:max_logs]


def quick_rpc_call(chain: str, method: str, params: list[Any], timeout: int) -> Any:
    last_error: Exception | None = None
    for url in rpc_urls(chain):
        try:
            return rpc_call_url(url, method, params, timeout=timeout)
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError(f"no rpc url for {chain}")


def transfer_log(log: dict[str, Any], decimals: int) -> dict[str, Any]:
    topics = log.get("topics", [])
    return {
        "token": norm(log.get("address")),
        "block": int(log.get("blockNumber") or "0x0", 16),
        "tx": log.get("transactionHash", ""),
        "log_index": int(log.get("logIndex") or "0x0", 16),
        "from": topic_addr(topics[1]) if len(topics) > 1 else "",
        "to": topic_addr(topics[2]) if len(topics) > 2 else "",
        "amount": decimal_amount(int(log.get("data") or "0x0", 16), decimals),
    }


def liquidity_watch_addresses(event: dict[str, Any]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for address, row in global_address_labels(event["chain"]).items():
        label_class = str(row.get("class") or "").strip()
        if label_class in {"lp_position_manager", "pool_manager"}:
            rows.setdefault(
                address,
                {
                    "label": str(row.get("label") or label_class),
                    "role": label_class,
                    "watch_quote": "false",
                },
            )
    for row in event.get("watch_addresses", []):
        address = norm(row.get("address"))
        role = str(row.get("role", "")).lower()
        if is_address(address) and role in POOL_FLOW_ROLES:
            rows[address] = {
                "label": str(row.get("label") or role),
                "role": role,
                "watch_quote": "true" if row.get("watch_quote") else "false",
            }
    for key, role in (("hook", "pool_hook"), ("operator", "hook_operator")):
        address = norm(event.get(key))
        if is_address(address):
            rows.setdefault(address, {"label": key, "role": role, "watch_quote": "false"})
    return rows


def scan_key_liquidity_flows(event: dict[str, Any], latest: int) -> dict[str, Any]:
    max_age_seconds = int(os.environ.get("ALPHA_OPENING_LIQUIDITY_MAX_AGE_SECONDS", "10800"))
    if (
        os.environ.get("ALPHA_OPENING_FORCE_LIQUIDITY_FLOW", "0") != "1"
        and int(event.get("seconds_until_start") or 0) < -max_age_seconds
    ):
        return {"summary": "已超过开盘池/做市短扫窗口", "risk": "skipped_old_opening", "rows": 0}
    watch = liquidity_watch_addresses(event)
    if not watch or not event.get("opening_block"):
        return {"summary": "未配置池子/做市地址", "risk": "none", "rows": 0}
    from_block = max(
        int(event["opening_block"]),
        latest - int(os.environ.get("ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS", "5000")),
    )
    token = event["token"]
    quote = event["quote"]
    totals = {
        "token_in": Decimal(0),
        "token_out": Decimal(0),
        "quote_in": Decimal(0),
        "quote_out": Decimal(0),
        "rows": 0,
    }
    max_logs = int(os.environ.get("ALPHA_OPENING_LIQUIDITY_MAX_LOGS", "30"))
    chunk_blocks = int(os.environ.get("ALPHA_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000"))
    timeout = int(os.environ.get("ALPHA_OPENING_LIQUIDITY_RPC_TIMEOUT", "3"))
    scan_optional = os.environ.get("ALPHA_OPENING_LIQUIDITY_SCAN_OPTIONAL_DIRECTIONS", "0") == "1"
    for address, meta in watch.items():
        queries = [
            ("token_out", token["address"], int(token["decimals"]), [TRANSFER_TOPIC, address_topic(address), None]),
        ]
        if meta.get("watch_quote") == "true" or os.environ.get("ALPHA_OPENING_LIQUIDITY_SCAN_ALL_QUOTE", "0") == "1":
            queries.append(("quote_in", quote["address"], int(quote["decimals"]), [TRANSFER_TOPIC, None, address_topic(address)]))
        if scan_optional:
            queries.extend(
                [
                    ("token_in", token["address"], int(token["decimals"]), [TRANSFER_TOPIC, None, address_topic(address)]),
                    ("quote_out", quote["address"], int(quote["decimals"]), [TRANSFER_TOPIC, address_topic(address), None]),
                ]
            )
        for key, asset_address, decimals, topics in queries:
            query = {
                "address": asset_address,
                "fromBlock": hex(from_block),
                "toBlock": hex(latest),
                "topics": topics,
            }
            logs = get_logs_quick(event["chain"], query, chunk_blocks, max_logs, timeout)
            for log in logs:
                row = transfer_log(log, decimals)
                if row["from"] == row["to"]:
                    continue
                totals[key] += row["amount"]
                totals["rows"] += 1
    liquidity_events = scan_liquidity_events(event, from_block, latest, watch)
    quote_threshold = Decimal(os.environ.get("ALPHA_OPENING_LIQUIDITY_QUOTE_ALERT", "10000"))
    token_threshold = Decimal(os.environ.get("ALPHA_OPENING_LIQUIDITY_TOKEN_ALERT", "100000"))
    risk = "none"
    if liquidity_events.get("risk") in {"lp_remove", "lp_collect"}:
        risk = str(liquidity_events.get("risk"))
    elif totals["quote_in"] >= quote_threshold:
        risk = "project_quote_in"
    elif totals["token_out"] >= token_threshold:
        risk = "pool_token_out"
    elif totals["quote_out"] >= quote_threshold:
        risk = "project_quote_out"
    elif totals["token_in"] >= token_threshold:
        risk = "pool_token_in"
    return {
        "summary": liquidity_combined_text(
            liquidity_flow_text(totals, token["symbol"], quote["symbol"]),
            str(liquidity_events.get("summary") or ""),
        ),
        "risk": risk,
        "from_block": from_block,
        "to_block": latest,
        "watch_address_count": len(watch),
        "rows": int(totals["rows"]),
        "liquidity_event_rows": int(liquidity_events.get("rows") or 0),
        "token_in": decimal_str(totals["token_in"]),
        "token_out": decimal_str(totals["token_out"]),
        "quote_in": decimal_str(totals["quote_in"]),
        "quote_out": decimal_str(totals["quote_out"]),
        "liquidity_events": liquidity_events.get("events", []),
    }


def liquidity_flow_text(totals: dict[str, Decimal | int], token_symbol: str, quote_symbol: str) -> str:
    parts = []
    token_out = Decimal(str(totals.get("token_out") or "0"))
    token_in = Decimal(str(totals.get("token_in") or "0"))
    quote_in = Decimal(str(totals.get("quote_in") or "0"))
    quote_out = Decimal(str(totals.get("quote_out") or "0"))
    if token_out:
        parts.append(f"关键池/做市地址流出 {format_amount(token_out)} {token_symbol}")
    if quote_in:
        parts.append(f"收到 {format_amount(quote_in)} {quote_symbol}")
    if token_in:
        parts.append(f"流入 {format_amount(token_in)} {token_symbol}")
    if quote_out:
        parts.append(f"转出 {format_amount(quote_out)} {quote_symbol}")
    return "；".join(parts) if parts else "未发现关键池/做市地址大额进出"


def liquidity_combined_text(flow_text: str, event_text: str) -> str:
    if event_text and event_text != "未发现 LP 增减事件":
        if flow_text and flow_text != "未发现关键池/做市地址大额进出":
            return f"{flow_text}；{event_text}"
        return event_text
    return flow_text


def uint_slot(data: str, index: int) -> int:
    raw = strip0x(norm(data or "0x"))
    start = index * 64
    if len(raw) < start + 64:
        return 0
    return int(raw[start:start + 64], 16)


def int_slot(data: str, index: int) -> int:
    value = uint_slot(data, index)
    if value >= 2**255:
        value -= 2**256
    return value


def liquidity_event_row(log: dict[str, Any], meta: dict[str, str]) -> dict[str, Any]:
    topics = [norm(topic) for topic in log.get("topics", [])]
    topic0 = topics[0] if topics else ""
    data = str(log.get("data") or "0x")
    row = {
        "block": int(log.get("blockNumber") or "0x0", 16),
        "tx": log.get("transactionHash", ""),
        "address": norm(log.get("address")),
        "label": meta.get("label", ""),
        "role": meta.get("role", ""),
        "event": "unknown",
        "direction": "unknown",
        "liquidity_delta": "",
        "amount0": "",
        "amount1": "",
    }
    if topic0 == INCREASE_LIQUIDITY_TOPIC:
        row.update({"event": "IncreaseLiquidity", "direction": "add", "amount0": str(uint_slot(data, 1)), "amount1": str(uint_slot(data, 2))})
    elif topic0 == DECREASE_LIQUIDITY_TOPIC:
        row.update({"event": "DecreaseLiquidity", "direction": "remove", "amount0": str(uint_slot(data, 1)), "amount1": str(uint_slot(data, 2))})
    elif topic0 == COLLECT_TOPIC:
        row.update({"event": "Collect", "direction": "collect", "amount0": str(uint_slot(data, 1)), "amount1": str(uint_slot(data, 2))})
    elif topic0 == BURN_TOPIC:
        row.update({"event": "Burn", "direction": "remove"})
    elif topic0 == MODIFY_LIQUIDITY_TOPIC:
        delta = int_slot(data, 2)
        direction = "add" if delta > 0 else "remove" if delta < 0 else "neutral"
        row.update({"event": "ModifyLiquidity", "direction": direction, "liquidity_delta": str(delta)})
    return row


def scan_liquidity_events(event: dict[str, Any], from_block: int, latest: int, watch: dict[str, dict[str, str]]) -> dict[str, Any]:
    addresses = {
        address: meta
        for address, meta in watch.items()
        if meta.get("role") in {"lp_position_manager", "pool_manager", "pool", "v4_pool_manager"}
    }
    if not addresses:
        return {"summary": "未发现 LP 增减事件", "risk": "none", "rows": 0, "events": []}
    max_logs = int(os.environ.get("ALPHA_OPENING_LIQUIDITY_EVENT_MAX_LOGS", "20"))
    chunk_blocks = int(os.environ.get("ALPHA_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000"))
    timeout = int(os.environ.get("ALPHA_OPENING_LIQUIDITY_RPC_TIMEOUT", "3"))
    rows: list[dict[str, Any]] = []
    for address, meta in addresses.items():
        query = {
            "address": address,
            "fromBlock": hex(from_block),
            "toBlock": hex(latest),
            "topics": [sorted(LIQUIDITY_EVENT_TOPICS)],
        }
        for log in get_logs_quick(event["chain"], query, chunk_blocks, max_logs, timeout):
            rows.append(liquidity_event_row(log, meta))
            if len(rows) >= max_logs:
                break
        if len(rows) >= max_logs:
            break
    remove_count = sum(1 for row in rows if row.get("direction") == "remove")
    collect_count = sum(1 for row in rows if row.get("direction") == "collect")
    add_count = sum(1 for row in rows if row.get("direction") == "add")
    if remove_count:
        risk = "lp_remove"
    elif collect_count:
        risk = "lp_collect"
    else:
        risk = "none"
    parts = []
    if add_count:
        parts.append(f"LP加池/增流动性 {add_count} 次")
    if remove_count:
        parts.append(f"LP减池/撤流动性 {remove_count} 次")
    if collect_count:
        parts.append(f"LP收取/提取费用 {collect_count} 次")
    summary = "；".join(parts) if parts else "未发现 LP 增减事件"
    return {"summary": summary, "risk": risk, "rows": len(rows), "events": rows[-10:]}


def opening_transfer_logs(event: dict[str, Any], latest: int) -> list[dict[str, Any]]:
    scan_blocks = int(os.environ.get("ALPHA_OPENING_SCAN_BLOCKS", "240"))
    recent_blocks = int(os.environ.get("ALPHA_OPENING_RECENT_BLOCKS", "1200"))
    max_logs = int(os.environ.get("ALPHA_OPENING_MAX_LOGS", "500"))
    opening_block = int(event["opening_block"])
    ranges = [(opening_block, min(latest, opening_block + scan_blocks))]
    recent_from = max(opening_block, latest - recent_blocks)
    if recent_from > ranges[0][1]:
        ranges.append((recent_from, latest))

    rows: list[dict[str, Any]] = []
    seen = set()
    chunk_blocks = int(os.environ.get("ALPHA_OPENING_LOG_CHUNK_BLOCKS", "200"))
    for from_block, to_block in ranges:
        query = {
            "address": event["token"]["address"],
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [TRANSFER_TOPIC],
        }
        for row in get_logs(event["chain"], query, chunk_blocks, max_logs):
            key = (row.get("transactionHash"), row.get("logIndex"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= max_logs:
                return rows
    return rows


def receipt_token_transfers(chain: str, tx_hash: str, token: dict[str, Any], quote: dict[str, Any]) -> list[dict[str, Any]]:
    receipt = get_transaction_receipt(chain, tx_hash)
    return receipt_transfers_from_receipt(receipt, token, quote)


def receipt_transfers_from_receipt(receipt: dict[str, Any], token: dict[str, Any], quote: dict[str, Any]) -> list[dict[str, Any]]:
    watched = {norm(token["address"]): token, norm(quote["address"]): quote}
    rows = []
    for log in receipt.get("logs", []):
        meta = watched.get(norm(log.get("address")))
        topics = log.get("topics", [])
        if not meta or len(topics) < 3 or norm(topics[0]) != TRANSFER_TOPIC:
            continue
        rows.append(transfer_log(log, int(meta["decimals"])))
    return rows


def has_contract_code(chain: str, address: str) -> bool:
    address = norm(address)
    if not is_address(address) or address == ZERO:
        return False
    key = (chain, address)
    if key not in CODE_CACHE:
        timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
        try:
            code = quick_rpc_call(chain, "eth_getCode", [address, "latest"], timeout) or "0x"
            CODE_CACHE[key] = code not in ("0x", "0x0", "")
        except Exception:
            CODE_CACHE[key] = False
    return CODE_CACHE[key]


def contract_code(chain: str, address: str) -> str:
    address = norm(address)
    if not is_address(address) or address == ZERO:
        return "0x"
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        return quick_rpc_call(chain, "eth_getCode", [address, "latest"], timeout) or "0x"
    except Exception:
        return "0x"


def selector_present(code: str, selector: str) -> bool:
    raw = strip0x(code or "0x").lower()
    needle = strip0x(selector).lower()
    return bool(raw and needle and needle in raw)


def optional_eth_call(chain: str, address: str, selector: str) -> str:
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        return quick_rpc_call(chain, "eth_call", [{"to": address, "data": selector}, "latest"], timeout) or "0x"
    except Exception:
        return "0x"


def web3_keccak_word(chain: str, raw_hex: str) -> str:
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    return quick_rpc_call(chain, "web3_sha3", ["0x" + strip0x(raw_hex)], timeout)


def mapping_storage_key(chain: str, address: str, slot: int) -> str:
    return web3_keccak_word(chain, encode_address_word(address) + encode_uint(slot))


def nested_mapping_storage_key(chain: str, owner: str, spender: str, slot: int) -> str:
    owner_slot = mapping_storage_key(chain, owner, slot)
    return web3_keccak_word(chain, encode_address_word(spender) + strip0x(owner_slot))


def storage_at(chain: str, contract: str, key: str) -> str:
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    return quick_rpc_call(chain, "eth_getStorageAt", [contract, key, "latest"], timeout) or "0x"


def raw_balance_of(chain: str, token: dict[str, Any], holder: str) -> int:
    raw = quick_rpc_call(
        chain,
        "eth_call",
        [{"to": token["address"], "data": encode_balance_of(holder)}, "latest"],
        int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5")),
    )
    return int(raw or "0x0", 16)


def find_balance_slot(chain: str, token: dict[str, Any], holder: str) -> int | None:
    cache_key = (chain, norm(token["address"]))
    if cache_key in BALANCE_SLOT_CACHE:
        return BALANCE_SLOT_CACHE[cache_key]
    expected = raw_balance_of(chain, token, holder)
    if expected <= 0:
        BALANCE_SLOT_CACHE[cache_key] = None
        return None
    max_slots = int(os.environ.get("ALPHA_OPENING_STORAGE_SLOT_SCAN", "24"))
    for slot in range(max_slots):
        key = mapping_storage_key(chain, holder, slot)
        try:
            current = int(storage_at(chain, token["address"], key), 16)
        except Exception:
            continue
        if current == expected:
            BALANCE_SLOT_CACHE[cache_key] = slot
            return slot
    BALANCE_SLOT_CACHE[cache_key] = None
    return None


def encode_pancake_v3_exact_input_single(token_in: str, token_out: str, fee: int, recipient: str, amount_in: int) -> str:
    return (
        PANCAKE_V3_EXACT_INPUT_SINGLE_SELECTOR
        + encode_address_word(token_in)
        + encode_address_word(token_out)
        + encode_uint(fee)
        + encode_address_word(recipient)
        + encode_uint(amount_in)
        + encode_uint(0)
        + encode_uint(0)
    )


def router_sell_state_override(
    event: dict[str, Any],
    holder: str,
    amount_raw: int,
    balance_slot: int,
    allowance_slot: int,
) -> dict[str, Any]:
    token_address = norm(event["token"]["address"])
    router = norm(os.environ.get("ALPHA_OPENING_ROUTER_ADDRESS") or PANCAKE_V3_ROUTER)
    balance_key = mapping_storage_key(event["chain"], holder, balance_slot)
    allowance_key = nested_mapping_storage_key(event["chain"], holder, router, allowance_slot)
    amount_hex = "0x" + hex(amount_raw)[2:].rjust(64, "0")
    max_uint = "0x" + ("f" * 64)
    return {
        token_address: {
            "stateDiff": {
                balance_key: amount_hex,
                allowance_key: max_uint,
            }
        },
        norm(holder): {"balance": "0x3635c9adc5dea00000"},
    }


def read_uint_with_override(chain: str, to_address: str, data: str, override: dict[str, Any], timeout: int) -> int | None:
    try:
        raw = quick_rpc_call(chain, "eth_call", [{"to": to_address, "data": data}, "latest", override], timeout)
    except Exception:
        return None
    try:
        return int(raw or "0x0", 16)
    except ValueError:
        return None


def router_sell_override_readback_ok(
    event: dict[str, Any],
    holder: str,
    router: str,
    amount_raw: int,
    override: dict[str, Any],
    timeout: int,
) -> tuple[bool, str]:
    token_address = norm(event["token"]["address"])
    balance = read_uint_with_override(event["chain"], token_address, encode_balance_of(holder), override, timeout)
    if balance is None:
        return False, "balance_readback_failed"
    if balance < amount_raw:
        return False, "balance_readback_mismatch"
    allowance = read_uint_with_override(event["chain"], token_address, encode_allowance(holder, router), override, timeout)
    if allowance is None:
        return False, "allowance_readback_failed"
    if allowance < amount_raw:
        return False, "allowance_readback_mismatch"
    return True, "readback_ok"


def infinity_roundtrip_state_override(quote_address: str, holder: str, buy_amount_raw: int) -> dict[str, Any]:
    balance_key = mapping_storage_key("bsc", holder, DEFAULT_QUOTE_BALANCE_SLOT)
    owner_slot = web3_keccak_word("bsc", encode_address_word(holder) + encode_uint(DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT))
    token_allowance_key = web3_keccak_word("bsc", encode_address_word(PANCAKE_PERMIT2) + strip0x(owner_slot))
    permit2_key = permit2_storage_key(holder, quote_address, PANCAKE_INFINITY_UNIVERSAL_ROUTER, DEFAULT_PERMIT2_ALLOWANCE_SLOT)
    packed_permit2 = pack_permit2_allowance(MAX_UINT160, MAX_UINT48, 0)
    return {
        norm(quote_address): {
            "stateDiff": {
                balance_key: uint256_hex(buy_amount_raw),
                token_allowance_key: uint256_hex(MAX_UINT256),
            }
        },
        norm(PANCAKE_PERMIT2): {"stateDiff": {permit2_key: uint256_hex(packed_permit2)}},
        norm(holder): {"balance": "0x3635c9adc5dea00000"},
    }


def infinity_roundtrip_override_readback_ok(
    chain: str,
    quote_address: str,
    holder: str,
    buy_amount_raw: int,
    override: dict[str, Any],
    timeout: int,
) -> tuple[bool, str]:
    balance = read_uint_with_override(chain, quote_address, encode_balance_of(holder), override, timeout)
    if balance is None:
        return False, "quote_balance_readback_failed"
    if balance < buy_amount_raw:
        return False, "quote_balance_readback_mismatch"
    token_allowance = read_uint_with_override(chain, quote_address, encode_allowance(holder, PANCAKE_PERMIT2), override, timeout)
    if token_allowance is None:
        return False, "token_allowance_readback_failed"
    if token_allowance < buy_amount_raw:
        return False, "token_allowance_readback_mismatch"
    try:
        raw = quick_rpc_call(
            chain,
            "eth_call",
            [
                {
                    "to": PANCAKE_PERMIT2,
                    "data": permit2_allowance_call(holder, quote_address, PANCAKE_INFINITY_UNIVERSAL_ROUTER),
                },
                "latest",
                override,
            ],
            timeout,
        )
    except Exception:
        return False, "permit2_allowance_readback_failed"
    allowance = decode_permit2_allowance(raw or "0x")
    if allowance.get("amount", 0) < buy_amount_raw:
        return False, "permit2_allowance_readback_mismatch"
    return True, "readback_ok"


def quote_infinity_buy_output(event: dict[str, Any], key: dict[str, Any], buy_amount_raw: int, timeout: int) -> int:
    quote_address = norm(event["quote"]["address"])
    quote_key = dict(key)
    quote_key["zero_for_one"] = quote_address == norm(key["currency0"])
    data = encode_infinity_cl_quote_exact_input_single(quote_key, buy_amount_raw)
    result = quick_rpc_call(
        event["chain"],
        "eth_call",
        [{"to": PANCAKE_INFINITY_CL_QUOTER, "data": data}, "latest"],
        timeout,
    )
    return decode_first_uint(result or "0x")


def execute_infinity_roundtrip_call(event: dict[str, Any], holder: str, override: dict[str, Any], fixture: dict[str, Any], timeout: int) -> tuple[bool, str]:
    try:
        quick_rpc_call(
            event["chain"],
            "eth_call",
            [
                {
                    "from": holder,
                    "to": PANCAKE_INFINITY_UNIVERSAL_ROUTER,
                    "gas": hex(int(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_GAS", "20000000"))),
                    "data": fixture["calldata"],
                },
                "latest",
                override,
            ],
            timeout,
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)[:120]


def estimate_infinity_quote_recovery(
    event: dict[str, Any],
    holder: str,
    override: dict[str, Any],
    base_args: SimpleNamespace,
    buy_amount_raw: int,
    timeout: int,
) -> dict[str, str]:
    iterations = int(os.environ.get("ALPHA_OPENING_INFINITY_RECOVERY_ITERATIONS", "20"))
    high = int(os.environ.get("ALPHA_OPENING_INFINITY_RECOVERY_HIGH_RAW", "0") or "0") or buy_amount_raw
    low = 0
    last_failure = ""
    for _ in range(max(1, iterations)):
        if low >= high:
            break
        mid = (low + high + 1) // 2
        probe_args = SimpleNamespace(**vars(base_args))
        probe_args.sell_amount_out_minimum = mid
        ok, detail = execute_infinity_roundtrip_call(event, holder, override, build_fixture(probe_args), timeout)
        if ok:
            low = mid
        else:
            high = mid - 1
            last_failure = detail
    recovery_rate = Decimal(low) / Decimal(buy_amount_raw) if buy_amount_raw else Decimal(0)
    return {
        "status": "estimated",
        "quote_recovered_raw": str(low),
        "recovery_rate": str(recovery_rate),
        "calls": str(max(1, iterations)),
        "last_failure": last_failure,
    }


def simulate_infinity_router_roundtrip_safety(event: dict[str, Any], amount: Decimal) -> dict[str, str]:
    if os.environ.get("ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE", "0") != "1":
        return {"status": "unverified", "detail": "infinity_router_roundtrip_disabled"}
    key = infinity_pool_key(event)
    if key.get("status") != "ok":
        return {"status": "unverified", "detail": str(key.get("detail") or key.get("status") or "missing_pool_key")}
    token = event["token"]
    quote = event["quote"]
    quote_address = norm(quote["address"])
    token_address = norm(token["address"])
    quote_budget = Decimal(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_BUY_QUOTE", "10"))
    buy_amount_raw = raw_token_amount(quote_budget, int(quote["decimals"]))
    if buy_amount_raw <= 0:
        return {"status": "unverified", "detail": "roundtrip_buy_amount_too_small"}
    timeout = int(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_TIMEOUT", "12"))
    try:
        buy_output_raw = quote_infinity_buy_output(event, key, buy_amount_raw, timeout)
    except Exception as exc:
        return {"status": "infinity_roundtrip_quote_failed", "detail": str(exc)[:120]}
    if buy_output_raw <= 0:
        return {"status": "infinity_roundtrip_quote_failed", "detail": "zero_buy_quote"}
    share_bps = int(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_SELL_SHARE_BPS", "10000"))
    sell_amount_raw = max(1, buy_output_raw * max(1, min(10_000, share_bps)) // 10_000)
    pool_fingerprint = first_nonempty(event.get("pool_id"), key.get("parameters"), key.get("hooks"))
    cache_key = (token_address, quote_address, str(pool_fingerprint), buy_amount_raw, sell_amount_raw)
    if cache_key in INFINITY_ROUNDTRIP_CACHE:
        return dict(INFINITY_ROUNDTRIP_CACHE[cache_key])
    buy_zero_for_one = quote_address == norm(key["currency0"])
    args = SimpleNamespace(
        deadline=int(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_DEADLINE", "4102444800")),
        buy_amount=buy_amount_raw,
        buy_amount_out_minimum=0,
        sell_amount=sell_amount_raw,
        sell_amount_out_minimum=0,
        pool_key=key,
        buy_zero_for_one=buy_zero_for_one,
        sell_zero_for_one=not buy_zero_for_one,
    )
    fixture = build_fixture(args)
    holder = norm(os.environ.get("ALPHA_OPENING_INFINITY_ROUNDTRIP_FAKE_HOLDER") or "0x0000000000000000000000000000000000000abc")
    override = infinity_roundtrip_state_override(quote_address, holder, buy_amount_raw)
    readback_ok, readback_detail = infinity_roundtrip_override_readback_ok(
        event["chain"],
        quote_address,
        holder,
        buy_amount_raw,
        override,
        timeout,
    )
    if not readback_ok:
        result = {"status": "infinity_roundtrip_readback_failed", "detail": readback_detail}
        INFINITY_ROUNDTRIP_CACHE[cache_key] = result
        return dict(result)
    ok, call_detail = execute_infinity_roundtrip_call(event, holder, override, fixture, timeout)
    if not ok:
        result = {"status": "infinity_roundtrip_eth_call_failed", "detail": call_detail}
        INFINITY_ROUNDTRIP_CACHE[cache_key] = result
        return dict(result)
    buy_quote = decimal_amount(buy_amount_raw, int(quote["decimals"]))
    sell_token = decimal_amount(sell_amount_raw, int(token["decimals"]))
    if os.environ.get("ALPHA_OPENING_INFINITY_RECOVERY_ESTIMATE", "1") == "1":
        recovery = estimate_infinity_quote_recovery(event, holder, override, args, buy_amount_raw, timeout)
        recovered_quote = decimal_amount(int(recovery["quote_recovered_raw"]), int(quote["decimals"]))
        min_rate = Decimal(os.environ.get("ALPHA_OPENING_INFINITY_MIN_RECOVERY_RATE", "0.80"))
        recovery_rate = Decimal(recovery["recovery_rate"])
        status = "infinity_roundtrip_recovery_verified" if recovery_rate >= min_rate else "infinity_roundtrip_low_recovery"
        result = {
            "status": status,
            "detail": (
                f"v4往返回收率≈{decimal_str(recovery_rate * Decimal(100))}%: "
                f"buy≈{decimal_str(buy_quote)} {quote['symbol']}, "
                f"sell≈{decimal_str(sell_token)} {token['symbol']}, "
                f"recover≈{decimal_str(recovered_quote)} {quote['symbol']}"
            ),
        }
        INFINITY_ROUNDTRIP_CACHE[cache_key] = result
        return dict(result)
    result = {
        "status": "infinity_roundtrip_eth_call_success_no_recovery_rate",
        "detail": (
            f"v4往返eth_call未revert: buy≈{decimal_str(buy_quote)} {quote['symbol']}, "
            f"sell≈{decimal_str(sell_token)} {token['symbol']}, recovery_rate_unavailable"
        ),
    }
    INFINITY_ROUNDTRIP_CACHE[cache_key] = result
    return dict(result)


def simulate_router_sell_safety(event: dict[str, Any], holder: str, amount: Decimal) -> dict[str, str]:
    if os.environ.get("ALPHA_OPENING_ROUTER_SELL_PROBE", "1") != "1":
        return {"status": "unverified", "detail": "router_sell_probe_disabled"}
    if likely_infinity_event(event):
        return simulate_infinity_router_roundtrip_safety(event, amount)
    if not is_address(holder) or amount <= 0:
        return {"status": "unverified", "detail": "invalid_holder_or_amount"}
    token = event["token"]
    quote = event["quote"]
    probe_amount = min(amount, Decimal(os.environ.get("ALPHA_OPENING_ROUTER_SELL_PROBE_TOKEN", "1")))
    amount_raw = raw_token_amount(probe_amount, int(token["decimals"]))
    if amount_raw <= 0:
        return {"status": "unverified", "detail": "router_probe_amount_too_small"}
    try:
        balance_slot = find_balance_slot(event["chain"], token, holder)
    except Exception as exc:
        return {"status": "unverified", "detail": f"balance_slot_error:{str(exc)[:80]}"}
    if balance_slot is None:
        return {"status": "unverified", "detail": "balance_slot_not_found"}
    fees = []
    for item in os.environ.get("ALPHA_OPENING_QUOTER_FEES", "100,500,2500,10000").split(","):
        try:
            fees.append(int(item.strip()))
        except ValueError:
            continue
    router = norm(os.environ.get("ALPHA_OPENING_ROUTER_ADDRESS") or PANCAKE_V3_ROUTER)
    recipient = norm(event.get("sell_safety_probe_recipient") or os.environ.get("ALPHA_OPENING_TRANSFER_PROBE_TO") or DEAD)
    if not is_address(recipient):
        recipient = DEAD
    max_slots = int(os.environ.get("ALPHA_OPENING_ALLOWANCE_SLOT_SCAN", "24"))
    allowance_cache_key = (event["chain"], norm(token["address"]), router)
    slot_candidates: list[int | None] = []
    if allowance_cache_key in ALLOWANCE_SLOT_CACHE:
        slot_candidates.append(ALLOWANCE_SLOT_CACHE[allowance_cache_key])
    slot_candidates.extend(slot for slot in range(max_slots) if slot not in slot_candidates)
    errors: list[str] = []
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    for fee in fees:
        data = encode_pancake_v3_exact_input_single(token["address"], quote["address"], fee, recipient, amount_raw)
        for allowance_slot in slot_candidates:
            if allowance_slot is None:
                continue
            override = router_sell_state_override(event, holder, amount_raw, balance_slot, int(allowance_slot))
            readback_ok, readback_detail = router_sell_override_readback_ok(event, holder, router, amount_raw, override, timeout)
            if not readback_ok:
                if len(errors) < 3:
                    errors.append(f"fee={fee},allow={allowance_slot}:{readback_detail}")
                continue
            try:
                result = quick_rpc_call(
                    event["chain"],
                    "eth_call",
                    [{"from": norm(holder), "to": router, "data": data}, "latest", override],
                    timeout,
                )
            except Exception as exc:
                if len(errors) < 3:
                    errors.append(f"fee={fee},allow={allowance_slot}:{str(exc)[:70]}")
                continue
            raw_out = decode_first_uint(result or "0x")
            if raw_out > 0:
                ALLOWANCE_SLOT_CACHE[allowance_cache_key] = int(allowance_slot)
                out_amount = decimal_amount(raw_out, int(quote["decimals"]))
                return {
                    "status": "router_sell_verified",
                    "detail": (
                        f"fee={fee}, probe={decimal_str(probe_amount)}, "
                        f"out≈{decimal_str(out_amount)} {quote['symbol']}, "
                        f"balance_slot={balance_slot}, allowance_slot={allowance_slot}"
                    ),
                }
    ALLOWANCE_SLOT_CACHE[allowance_cache_key] = None
    detail = "; ".join(errors[:2]) if errors else f"balance_slot={balance_slot}, allowance_slot_not_found"
    return {"status": "router_sell_failed", "detail": detail}


def decode_address_return(data: str) -> str:
    raw = strip0x(data or "0x")
    if len(raw) < 64:
        return ""
    candidate = "0x" + raw[-40:].lower()
    return candidate if is_address(candidate) and candidate != ZERO else ""


def inspect_token_contract_safety(event: dict[str, Any]) -> dict[str, str]:
    chain = str(event.get("chain") or "")
    token_address = norm((event.get("token") or {}).get("address"))
    if not chain or not is_address(token_address):
        return {"status": "合约静态风险未验证", "gate": "static_check_unavailable", "detail": ""}
    key = (chain, token_address)
    if key in CONTRACT_SAFETY_CACHE:
        return CONTRACT_SAFETY_CACHE[key]

    code = contract_code(chain, token_address)
    if code in {"0x", "0x0", ""}:
        result = {"status": "合约代码读取失败；禁止跟随", "gate": "blocked_no_contract_code", "detail": "no_token_code"}
        CONTRACT_SAFETY_CACHE[key] = result
        return result

    risks: list[str] = []
    warnings: list[str] = []

    for name, selector in OWNER_SELECTORS.items():
        if not selector_present(code, selector):
            continue
        owner = decode_address_return(optional_eth_call(chain, token_address, selector))
        if owner and owner not in {DEAD}:
            warnings.append(f"{name}={short_addr(owner)}")

    for name, selector in ADMIN_SELECTORS.items():
        if not selector_present(code, selector):
            continue
        admin = decode_address_return(optional_eth_call(chain, token_address, selector))
        if admin and admin not in {DEAD}:
            warnings.append(f"{name}={short_addr(admin)}")

    for name, selector in BOOL_RISK_SELECTORS.items():
        if not selector_present(code, selector):
            continue
        value = parse_bool_return(optional_eth_call(chain, token_address, selector))
        if value:
            risks.append(f"{name}=true")
        else:
            warnings.append(f"{name}=false")

    if risks:
        result = {
            "status": "合约处于限制状态；禁止跟随",
            "gate": "blocked_static_contract_risk",
            "detail": "; ".join(risks[:4]),
        }
    elif warnings:
        result = {
            "status": "合约权限/暂停能力未完整验证；禁止放大仓位",
            "gate": "blocked_contract_controls_unverified",
            "detail": "; ".join(warnings[:4]),
        }
    else:
        result = {"status": "未发现常见 owner/pause 风险 selector；仍需卖出税费验证", "gate": "static_check_passed", "detail": ""}
    CONTRACT_SAFETY_CACHE[key] = result
    return result


def configured_address_class(event: dict[str, Any], address: str) -> str:
    address = norm(address)
    if not address:
        return ""
    global_label = global_address_label(event["chain"], address)
    if global_label:
        label_class = str(global_label.get("class") or "").strip()
        if label_class:
            return label_class
    for source in (event, event.get("market_context", {})):
        for row in source.get("known_contracts", []) or []:
            if isinstance(row, dict) and norm(row.get("address")) == address:
                return str(row.get("class") or row.get("destination_class") or "").strip()
        for key, class_name in (
            ("cex_deposit_addresses", "cex_deposit"),
            ("cex_addresses", "cex_deposit"),
            ("cex_hot_wallet_addresses", "cex_deposit"),
            ("exchange_addresses", "cex_deposit"),
            ("known_cex_addresses", "cex_deposit"),
            ("exchange_aggregator_addresses", "exchange_aggregator"),
            ("exchange_aggregator_suspect_addresses", "exchange_aggregator_suspect"),
            ("exchange_rebalance_addresses", "exchange_rebalance"),
            ("mm_or_project_suspect_addresses", "mm_or_project_suspect"),
            ("project_rebalance_addresses", "project_rebalance"),
            ("project_treasury_addresses", "project_treasury"),
            ("bridge_addresses", "bridge"),
            ("bridge_contracts", "bridge"),
            ("known_bridge_addresses", "bridge"),
            ("neutral_contracts", "lp_locker_or_staking"),
            ("lp_locker_addresses", "lp_locker_or_staking"),
            ("locker_addresses", "lp_locker_or_staking"),
            ("staking_addresses", "lp_locker_or_staking"),
        ):
            values = source.get(key, []) or []
            if any(norm(item.get("address") if isinstance(item, dict) else item) == address for item in values):
                return class_name
    return ""


def destination_class(event: dict[str, Any], address: str) -> str:
    address = norm(address)
    if not address:
        return "unknown"
    if address == ZERO:
        return "burn_or_zero"
    if address == norm(event["token"]["address"]):
        return "token_contract"
    if address == norm(event["quote"]["address"]):
        return "quote_token"
    configured = configured_address_class(event, address)
    if configured:
        if configured in {"lp_position_manager", "pool_manager"}:
            return "lp_locker_or_staking"
        return configured
    if address in {norm(event.get("hook")), norm(event.get("operator"))}:
        return "project_or_pool_contract"
    if has_contract_code(event["chain"], address):
        return "unknown_contract_pending_bearish"
    return "eoa_or_unlabeled"


def prefixed_next_hop_class(class_name: str) -> str:
    if class_name == "dex_sell_to_quote":
        return "next_hop_dex_sell_to_quote"
    if class_name == "cex_deposit":
        return "next_hop_cex_deposit"
    if class_name == "bridge":
        return "next_hop_bridge"
    if class_name == "dex_router":
        return "next_hop_dex_router"
    if class_name == "unknown_contract_pending_bearish":
        return "next_hop_unknown_contract_pending_bearish"
    if class_name == "lp_locker_or_staking":
        return "next_hop_lp_locker_or_staking"
    if class_name == "eoa_or_unlabeled":
        return "next_hop_eoa_or_unlabeled"
    return f"next_hop_{class_name}" if class_name else "next_hop_unknown"


def classify_recipient_next_hop_tx(event: dict[str, Any], recipient: str, tx_hash: str, outgoing_logs: list[dict[str, Any]]) -> dict[str, Any]:
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        receipt = quick_rpc_call(event["chain"], "eth_getTransactionReceipt", [tx_hash], timeout)
        transfers = receipt_transfers_from_receipt(receipt or {}, event["token"], event["quote"])
    except Exception:
        transfers = []
    quote_received = sum(
        (
            row["amount"]
            for row in transfers
            if norm(row.get("token")) == norm(event["quote"]["address"]) and norm(row.get("to")) == norm(recipient)
        ),
        Decimal(0),
    )
    classes = {prefixed_next_hop_class(destination_class(event, row.get("to", ""))) for row in outgoing_logs}
    if quote_received > 0:
        classes.add("next_hop_dex_sell_to_quote")
    return {"classes": classes, "quote_received": quote_received, "confirmed_sell_count": 1 if quote_received > 0 else 0}


def trace_next_hop_from_recipient(event: dict[str, Any], buyer: str, recipient: str, from_block: int, latest: int) -> dict[str, Any]:
    recipient = norm(recipient)
    if not is_address(recipient) or recipient == norm(buyer):
        return {"classes": set(), "quote_received": Decimal(0), "confirmed_sell_count": 0, "recipient_count": 0}
    max_span = int(os.environ.get("ALPHA_OPENING_NEXT_HOP_MAX_BLOCKS", "50000"))
    full_span = int(os.environ.get("ALPHA_OPENING_NEXT_HOP_FULL_MAX_BLOCKS", "250000"))
    trace_from = trace_start_block(from_block, latest, max_span, full_span, True)
    query = {
        "address": event["token"]["address"],
        "fromBlock": hex(trace_from),
        "toBlock": hex(latest),
        "topics": [TRANSFER_TOPIC, address_topic(recipient), None],
    }
    logs = get_logs_quick(
        event["chain"],
        query,
        int(os.environ.get("ALPHA_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000")),
        int(os.environ.get("ALPHA_OPENING_NEXT_HOP_MAX_LOGS", "80")),
        int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5")),
    )
    parsed_logs = [transfer_log(row, int(event["token"]["decimals"])) for row in logs]
    by_tx: dict[str, list[dict[str, Any]]] = {}
    for row in parsed_logs:
        by_tx.setdefault(row["tx"], []).append(row)
    classes: set[str] = set()
    quote_received = Decimal(0)
    confirmed_sell_count = 0
    max_txs = int(os.environ.get("ALPHA_OPENING_NEXT_HOP_CLASSIFY_TXS", "2"))
    ordered_txs = sorted(
        by_tx.items(),
        key=lambda item: max((row.get("block", 0), row.get("log_index", 0)) for row in item[1]),
    )
    for tx_hash, tx_logs in ordered_txs[:max_txs]:
        classified = classify_recipient_next_hop_tx(event, recipient, tx_hash, tx_logs)
        classes.update(classified["classes"])
        quote_received += classified["quote_received"]
        confirmed_sell_count += int(classified["confirmed_sell_count"])
    return {
        "classes": classes,
        "quote_received": quote_received,
        "confirmed_sell_count": confirmed_sell_count,
        "recipient_count": 1 if parsed_logs else 0,
    }


def classify_outgoing_tx(event: dict[str, Any], buyer: str, tx_hash: str, outgoing_logs: list[dict[str, Any]], latest: int) -> dict[str, Any]:
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        receipt = quick_rpc_call(event["chain"], "eth_getTransactionReceipt", [tx_hash], timeout)
        transfers = receipt_transfers_from_receipt(receipt or {}, event["token"], event["quote"])
    except Exception:
        transfers = []
    quote_received = sum(
        (
            row["amount"]
            for row in transfers
            if norm(row.get("token")) == norm(event["quote"]["address"]) and norm(row.get("to")) == norm(buyer)
        ),
        Decimal(0),
    )
    classes = set()
    eoa_recipients: list[tuple[str, int]] = []
    for row in outgoing_logs:
        to_addr = norm(row.get("to"))
        class_name = destination_class(event, to_addr)
        classes.add(class_name)
        if class_name == "eoa_or_unlabeled" and is_address(to_addr):
            eoa_recipients.append((to_addr, int(row.get("block") or 0)))
    if quote_received > 0:
        classes.add("dex_sell_to_quote")
    next_hop_quote_received = Decimal(0)
    next_hop_confirmed_sell_count = 0
    next_hop_recipient_count = 0
    seen_recipients = set()
    for recipient, block in eoa_recipients[: int(os.environ.get("ALPHA_OPENING_NEXT_HOP_RECIPIENTS", "2"))]:
        if recipient in seen_recipients:
            continue
        seen_recipients.add(recipient)
        next_hop = trace_next_hop_from_recipient(event, buyer, recipient, block, latest)
        classes.update(next_hop["classes"])
        next_hop_quote_received += next_hop["quote_received"]
        next_hop_confirmed_sell_count += int(next_hop["confirmed_sell_count"])
        next_hop_recipient_count += int(next_hop["recipient_count"])
    return {
        "classes": classes,
        "quote_received": quote_received + next_hop_quote_received,
        "direct_quote_received": quote_received,
        "next_hop_quote_received": next_hop_quote_received,
        "confirmed_sell_count": (1 if quote_received > 0 else 0) + next_hop_confirmed_sell_count,
        "next_hop_count": next_hop_recipient_count,
    }


def trace_start_block(from_block: int, latest: int, recent_span: int, full_span: int = 0, force_full: bool = False) -> int:
    from_block = max(0, int(from_block or 0))
    latest = max(0, int(latest or 0))
    recent_span = max(1, int(recent_span or 1))
    full_span = max(0, int(full_span or 0))
    if latest <= from_block:
        return from_block
    age = latest - from_block
    if age <= recent_span:
        return from_block
    if force_full and full_span and age <= full_span:
        return from_block
    return max(from_block, latest - recent_span)


def net_by_address(transfers: list[dict[str, Any]], token_addr: str, quote_addr: str) -> dict[str, dict[str, Decimal]]:
    nets: dict[str, dict[str, Decimal]] = {}
    for row in transfers:
        kind = "token" if norm(row["token"]) == norm(token_addr) else "quote"
        amount = row["amount"]
        from_addr = norm(row.get("from"))
        to_addr = norm(row.get("to"))
        nets.setdefault(from_addr, {"token": Decimal(0), "quote": Decimal(0)})[kind] -= amount
        nets.setdefault(to_addr, {"token": Decimal(0), "quote": Decimal(0)})[kind] += amount
    return nets


def excluded_addresses(event: dict[str, Any]) -> set[str]:
    out = {ZERO, norm(event["token"]["address"]), norm(event["quote"]["address"])}
    for value in (event.get("hook"), event.get("operator")):
        if is_address(value):
            out.add(norm(value))
    for address, row in global_address_labels(event["chain"]).items():
        if str(row.get("class") or "") in PROTOCOL_COUNTERPARTY_CLASSES:
            out.add(address)
    for row in event.get("known_contracts", []) or []:
        if not isinstance(row, dict):
            continue
        address = norm(row.get("address"))
        if is_address(address) and str(row.get("class") or row.get("destination_class") or "") in PROTOCOL_COUNTERPARTY_CLASSES:
            out.add(address)
    for source in (event, event.get("market_context", {})):
        for key, class_name in (
            ("exchange_aggregator_addresses", "exchange_aggregator"),
            ("exchange_aggregator_suspect_addresses", "exchange_aggregator_suspect"),
            ("exchange_rebalance_addresses", "exchange_rebalance"),
            ("dex_router_addresses", "dex_router"),
            ("dex_vault_addresses", "dex_vault"),
            ("dex_quoter_addresses", "dex_quoter"),
            ("lp_position_manager_addresses", "lp_position_manager"),
            ("pool_manager_addresses", "pool_manager"),
            ("permit2_addresses", "permit2"),
        ):
            if class_name not in PROTOCOL_COUNTERPARTY_CLASSES:
                continue
            for item in source.get(key, []) or []:
                address = norm(item.get("address") if isinstance(item, dict) else item)
                if is_address(address):
                    out.add(address)
    return out


def best_buyer(event: dict[str, Any], nets: dict[str, dict[str, Decimal]]) -> tuple[str, Decimal, Decimal]:
    candidates = []
    excluded = excluded_addresses(event)
    for address, amounts in nets.items():
        if address in excluded:
            continue
        token_net = amounts.get("token", Decimal(0))
        if token_net <= 0:
            continue
        quote_net = amounts.get("quote", Decimal(0))
        spent = abs(quote_net) if quote_net < 0 else Decimal(0)
        candidates.append((address, token_net, spent))
    if not candidates:
        return "", Decimal(0), Decimal(0)
    return max(candidates, key=lambda row: (row[2], row[1]))


def pool_side_quote_in(event: dict[str, Any], nets: dict[str, dict[str, Decimal]]) -> Decimal:
    quote_in = Decimal(0)
    for address, amounts in nets.items():
        if address in excluded_addresses(event):
            continue
        token_net = amounts.get("token", Decimal(0))
        quote_net = amounts.get("quote", Decimal(0))
        if token_net < 0 and quote_net > quote_in:
            quote_in = quote_net
    return quote_in


def internal_transfers(chain: str, tx_hash: str) -> list[dict[str, Any]]:
    if chain != "bsc" or not os.environ.get("NODEREAL_API_KEY"):
        return []
    try:
        result = rpc_call(
            chain,
            "nr_getAssetTransfers",
            [{"category": ["internal"], "transactionHash": tx_hash, "order": "asc", "maxCount": "0x64"}],
        )
    except Exception:
        return []
    return result.get("transfers", []) if isinstance(result, dict) and isinstance(result.get("transfers"), list) else []


def internal_value_to_native(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    raw = int(str(value), 16) if str(value).startswith("0x") else int(value)
    return decimal_amount(raw, 18)


def largest_internal_native(chain: str, tx_hash: str) -> dict[str, Any]:
    transfers = internal_transfers(chain, tx_hash)
    if not transfers:
        return {"amount": "0", "rows": 0}
    largest = max(transfers, key=lambda row: internal_value_to_native(row.get("value")))
    return {"amount": decimal_str(internal_value_to_native(largest.get("value"))), "rows": len(transfers)}


def encode_balance_of(address: str) -> str:
    return "0x70a08231" + norm(address)[2:].rjust(64, "0")


def encode_allowance(owner: str, spender: str) -> str:
    return "0xdd62ed3e" + norm(owner)[2:].rjust(64, "0") + norm(spender)[2:].rjust(64, "0")


def encode_transfer(to_address: str, raw_amount: int) -> str:
    return "0xa9059cbb" + norm(to_address)[2:].rjust(64, "0") + hex(raw_amount)[2:].rjust(64, "0")


def encode_uint(value: int) -> str:
    return hex(int(value))[2:].rjust(64, "0")


def encode_address_word(address: str) -> str:
    return norm(address)[2:].rjust(64, "0")


def encode_bool(value: bool) -> str:
    return encode_uint(1 if value else 0)


def encode_bytes32(value: str) -> str:
    raw = strip0x(norm(value))
    return raw.rjust(64, "0")[-64:]


def uint256_hex(value: int) -> str:
    return "0x" + int(value).to_bytes(32, "big").hex()


def permit2_allowance_call(owner: str, token: str, spender: str) -> str:
    return PERMIT2_ALLOWANCE_SELECTOR + encode_address_word(owner) + encode_address_word(token) + encode_address_word(spender)


def decode_permit2_allowance(data: str) -> dict[str, int]:
    raw = strip0x(data or "0x")
    if len(raw) < 64 * 3:
        return {"amount": 0, "expiration": 0, "nonce": 0}
    return {
        "amount": int(raw[0:64], 16),
        "expiration": int(raw[64:128], 16),
        "nonce": int(raw[128:192], 16),
    }


def pack_permit2_allowance(amount: int, expiration: int, nonce: int) -> int:
    if amount >= 2**160 or expiration >= 2**48 or nonce >= 2**48:
        raise ValueError("permit2 allowance field exceeds packed width")
    return (nonce << 208) | (expiration << 160) | amount


def permit2_storage_key(owner: str, token: str, spender: str, slot: int) -> str:
    owner_slot = web3_keccak_word("bsc", encode_address_word(owner) + encode_uint(slot))
    token_slot = web3_keccak_word("bsc", encode_address_word(token) + strip0x(owner_slot))
    return web3_keccak_word("bsc", encode_address_word(spender) + strip0x(token_slot))


def encode_quoter_v3_exact_input_single(token_in: str, token_out: str, amount_in: int, fee: int) -> str:
    return (
        QUOTE_EXACT_INPUT_SINGLE_SELECTOR
        + encode_address_word(token_in)
        + encode_address_word(token_out)
        + encode_uint(amount_in)
        + encode_uint(fee)
        + encode_uint(0)
    )


def first_nonempty(*values: Any) -> str:
    for value in values:
        if value not in ("", None):
            return str(value)
    return ""


def normalize_uint(value: Any) -> int | None:
    if value in ("", None):
        return None
    text = str(value).strip()
    try:
        return int(text, 16) if text.startswith("0x") else int(text)
    except ValueError:
        return None


def normalize_bytes32(value: Any) -> str:
    if value in ("", None):
        return ""
    text = norm(str(value))
    if text.startswith("0x") and len(strip0x(text)) <= 64:
        return "0x" + strip0x(text).rjust(64, "0")
    return ""


def likely_infinity_event(event: dict[str, Any]) -> bool:
    pool_id = str(event.get("pool_id") or "")
    if pool_id.startswith("0x") and len(strip0x(pool_id)) == 64:
        return True
    return bool(first_nonempty(event.get("fee"), event.get("parameters"), event.get("pool_manager")))


def infinity_pool_key(event: dict[str, Any]) -> dict[str, Any]:
    token_address = norm((event.get("token") or {}).get("address"))
    quote_address = norm((event.get("quote") or {}).get("address"))
    if not is_address(token_address) or not is_address(quote_address):
        return {"status": "missing_token_or_quote"}
    context = event.get("market_context") or {}
    hook = norm(first_nonempty(event.get("hook"), context.get("hook"), first_value_by_prefix(context, "pool_hook")))
    if not is_address(hook):
        hook = ZERO
    fee = normalize_uint(first_nonempty(event.get("fee"), context.get("fee"), first_value_by_prefix(context, "pool_fee")))
    parameters = normalize_bytes32(
        first_nonempty(event.get("parameters"), context.get("parameters"), first_value_by_prefix(context, "pool_parameters"))
    )
    pool_manager = norm(
        first_nonempty(
            event.get("pool_manager"),
            context.get("pool_manager"),
            first_value_by_prefix(context, "pool_manager"),
            PANCAKE_INFINITY_CL_POOL_MANAGER,
        )
    )
    if fee is None or not parameters:
        return {"status": "missing_pool_key", "detail": "fee_or_parameters_missing"}
    if not is_address(pool_manager):
        return {"status": "missing_pool_key", "detail": "pool_manager_invalid"}
    currency0, currency1 = sorted([token_address, quote_address], key=lambda item: int(strip0x(item), 16))
    return {
        "status": "ok",
        "currency0": currency0,
        "currency1": currency1,
        "hooks": hook,
        "pool_manager": pool_manager,
        "fee": fee,
        "parameters": parameters,
        "zero_for_one": token_address == currency0,
    }


def encode_infinity_cl_quote_exact_input_single(pool_key: dict[str, Any], amount_in: int, hook_data: str = "0x") -> str:
    hook_raw = strip0x(norm(hook_data))
    hook_words = ""
    if hook_raw:
        padded_len = ((len(hook_raw) + 63) // 64) * 64
        hook_words = hook_raw.ljust(padded_len, "0")
    tuple_head = (
        encode_address_word(pool_key["currency0"])
        + encode_address_word(pool_key["currency1"])
        + encode_address_word(pool_key["hooks"])
        + encode_address_word(pool_key["pool_manager"])
        + encode_uint(int(pool_key["fee"]))
        + encode_bytes32(pool_key["parameters"])
        + encode_bool(bool(pool_key["zero_for_one"]))
        + encode_uint(amount_in)
        + encode_uint(9 * 32)
    )
    dynamic_tail = encode_uint(len(hook_raw) // 2) + hook_words
    return PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR + encode_uint(32) + tuple_head + dynamic_tail


def raw_token_amount(amount: Decimal, decimals: int) -> int:
    if amount <= 0:
        return 0
    scaled = amount * (Decimal(10) ** decimals)
    return int(scaled.to_integral_value(rounding=ROUND_DOWN))


def token_balance(chain: str, token: dict[str, Any], address: str) -> Decimal:
    raw = rpc_call(chain, "eth_call", [{"to": token["address"], "data": encode_balance_of(address)}, "latest"])
    return decimal_amount(int(raw or "0x0", 16), int(token["decimals"]))


def parse_bool_return(data: str) -> bool:
    raw = strip0x(data or "0x")
    if not raw:
        return True
    try:
        return int(raw[-64:], 16) != 0
    except ValueError:
        return False


def decode_first_uint(data: str) -> int:
    raw = strip0x(data or "0x")
    if len(raw) < 64:
        return 0
    return int(raw[:64], 16)


def simulate_transfer_safety(event: dict[str, Any], holder: str, current: Decimal) -> dict[str, str]:
    if not is_address(holder):
        return {"status": "unverified", "detail": "invalid_holder"}
    if current <= 0:
        return {"status": "unverified", "detail": "no_balance_to_test"}
    token = event["token"]
    decimals = int(token["decimals"])
    probe_amount = min(current, Decimal(os.environ.get("ALPHA_OPENING_TRANSFER_PROBE_TOKEN", "1")))
    raw_amount = raw_token_amount(probe_amount, decimals)
    if raw_amount <= 0:
        return {"status": "unverified", "detail": "probe_amount_too_small"}
    recipient = norm(event.get("sell_safety_probe_recipient") or os.environ.get("ALPHA_OPENING_TRANSFER_PROBE_TO") or DEAD)
    if not is_address(recipient):
        recipient = DEAD
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        result = quick_rpc_call(
            event["chain"],
            "eth_call",
            [{"from": norm(holder), "to": token["address"], "data": encode_transfer(recipient, raw_amount)}, "latest"],
            timeout,
        )
    except Exception as exc:
        return {"status": "blocked", "detail": str(exc)[:180]}
    if parse_bool_return(result or "0x"):
        return {"status": "transfer_verified", "detail": f"probe_amount={decimal_str(probe_amount)}"}
    return {"status": "blocked", "detail": "erc20_transfer_returned_false"}


def simulate_dex_quote_safety(event: dict[str, Any], amount: Decimal) -> dict[str, str]:
    if amount <= 0:
        return {"status": "unverified", "detail": "no_amount_to_quote"}
    token = event["token"]
    quote = event["quote"]
    probe_amount = min(amount, Decimal(os.environ.get("ALPHA_OPENING_QUOTE_PROBE_TOKEN", "1")))
    raw_amount = raw_token_amount(probe_amount, int(token["decimals"]))
    if raw_amount <= 0:
        return {"status": "unverified", "detail": "quote_probe_amount_too_small"}
    fees = []
    for item in os.environ.get("ALPHA_OPENING_QUOTER_FEES", "100,500,2500,10000").split(","):
        try:
            fees.append(int(item.strip()))
        except ValueError:
            continue
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    errors = []
    for fee in fees:
        data = encode_quoter_v3_exact_input_single(token["address"], quote["address"], raw_amount, fee)
        try:
            result = quick_rpc_call(
                event["chain"],
                "eth_call",
                [{"to": PANCAKE_V3_QUOTER_V2, "data": data}, "latest"],
                timeout,
            )
        except Exception as exc:
            errors.append(f"fee={fee}:{str(exc)[:60]}")
            continue
        raw_out = decode_first_uint(result or "0x")
        if raw_out > 0:
            out_amount = decimal_amount(raw_out, int(quote["decimals"]))
            return {
                "status": "dex_quote_verified",
                "detail": f"fee={fee}, probe={decimal_str(probe_amount)}, out≈{decimal_str(out_amount)} {quote['symbol']}",
            }
    detail = "; ".join(errors[:2]) if errors else "no_fee_returned_quote"
    return {"status": "quote_failed", "detail": detail}


def simulate_infinity_cl_quote_safety(event: dict[str, Any], amount: Decimal) -> dict[str, str]:
    if os.environ.get("ALPHA_OPENING_INFINITY_QUOTE_PROBE", "1") != "1":
        return {"status": "unverified", "detail": "infinity_quote_probe_disabled"}
    if amount <= 0:
        return {"status": "unverified", "detail": "no_amount_to_quote"}
    key = infinity_pool_key(event)
    if key.get("status") != "ok":
        return {"status": "unverified", "detail": str(key.get("detail") or key.get("status") or "missing_pool_key")}
    token = event["token"]
    quote = event["quote"]
    probe_amount = min(amount, Decimal(os.environ.get("ALPHA_OPENING_QUOTE_PROBE_TOKEN", "1")))
    raw_amount = raw_token_amount(probe_amount, int(token["decimals"]))
    if raw_amount <= 0:
        return {"status": "unverified", "detail": "quote_probe_amount_too_small"}
    if raw_amount >= 2**128:
        return {"status": "unverified", "detail": "amount_exceeds_uint128"}
    timeout = int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    data = encode_infinity_cl_quote_exact_input_single(key, raw_amount)
    try:
        result = quick_rpc_call(
            event["chain"],
            "eth_call",
            [{"to": PANCAKE_INFINITY_CL_QUOTER, "data": data}, "latest"],
            timeout,
        )
    except Exception as exc:
        return {"status": "infinity_cl_quote_failed", "detail": str(exc)[:120]}
    raw_out = decode_first_uint(result or "0x")
    if raw_out <= 0:
        return {"status": "infinity_cl_quote_failed", "detail": "zero_quote"}
    out_amount = decimal_amount(raw_out, int(quote["decimals"]))
    return {
        "status": "infinity_cl_quote_verified",
        "detail": (
            f"probe={decimal_str(probe_amount)}, out≈{decimal_str(out_amount)} {quote['symbol']}, "
            "quote_only_no_tax_hooks"
        ),
    }


def trace_buyer(event: dict[str, Any], buyer: str, from_block: int, latest: int, bought: Decimal) -> dict[str, str]:
    if not buyer or bought <= 0:
        return {"status": "unknown"}
    current = token_balance(event["chain"], event["token"], buyer)
    trace_span = int(os.environ.get("ALPHA_OPENING_TRACE_MAX_BLOCKS", os.environ.get("ALPHA_OPENING_TRACE_RECENT_BLOCKS", "50000")))
    full_span = int(os.environ.get("ALPHA_OPENING_TRACE_FULL_EXITED_MAX_BLOCKS", "250000"))
    force_full = (
        os.environ.get("ALPHA_OPENING_TRACE_FULL_EXITED_BUYERS", "1") == "1"
        and current <= bought * Decimal("0.05")
    )
    trace_from = trace_start_block(from_block, latest, trace_span, full_span, force_full)
    query = {
        "address": event["token"]["address"],
        "fromBlock": hex(trace_from),
        "toBlock": hex(latest),
        "topics": [TRANSFER_TOPIC, address_topic(buyer), None],
    }
    logs = get_logs_quick(
        event["chain"],
        query,
        int(os.environ.get("ALPHA_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000")),
        int(os.environ.get("ALPHA_OPENING_TRACE_MAX_LOGS", "1200")),
        int(os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5")),
    )
    parsed_logs = [transfer_log(row, int(event["token"]["decimals"])) for row in logs]
    outgoing = sum((row["amount"] for row in parsed_logs), Decimal(0))
    by_tx: dict[str, list[dict[str, Any]]] = {}
    for row in parsed_logs:
        by_tx.setdefault(row["tx"], []).append(row)
    classes: set[str] = set()
    quote_received = Decimal(0)
    confirmed_sell_count = 0
    direct_quote_received = Decimal(0)
    next_hop_quote_received = Decimal(0)
    next_hop_count = 0
    max_classify = int(os.environ.get("ALPHA_OPENING_CLASSIFY_OUT_TXS", "3"))
    ordered_txs = sorted(
        by_tx.items(),
        key=lambda item: max((row.get("block", 0), row.get("log_index", 0)) for row in item[1]),
        reverse=True,
    )
    for tx_hash, tx_logs in ordered_txs[:max_classify]:
        classified = classify_outgoing_tx(event, buyer, tx_hash, tx_logs, latest)
        classes.update(classified["classes"])
        quote_received += classified["quote_received"]
        direct_quote_received += classified["direct_quote_received"]
        next_hop_quote_received += classified["next_hop_quote_received"]
        confirmed_sell_count += int(classified["confirmed_sell_count"])
        next_hop_count += int(classified["next_hop_count"])
    if current <= bought * Decimal("0.05"):
        status = "mostly_exited_or_transferred" if outgoing > 0 else "mostly_exited_untraced"
    elif outgoing > 0:
        status = "partially_moved"
    else:
        status = "held_or_accumulated"
    transfer_safety = simulate_transfer_safety(event, buyer, current)
    quote_probe_amount = min(current if current > 0 else bought, bought)
    dex_quote_safety = simulate_dex_quote_safety(event, quote_probe_amount)
    if likely_infinity_event(event) and dex_quote_safety.get("status") != "dex_quote_verified":
        infinity_quote = simulate_infinity_cl_quote_safety(event, quote_probe_amount)
        if infinity_quote.get("status") in {"infinity_cl_quote_verified", "infinity_cl_quote_failed"}:
            dex_quote_safety = infinity_quote
    router_sell_safety = simulate_router_sell_safety(event, buyer, quote_probe_amount)
    return {
        "status": status,
        "current_balance": decimal_str(current),
        "out_after_buy": decimal_str(outgoing),
        "out_transfer_count": str(len(logs)),
        "out_destination_classes": ",".join(sorted(classes)),
        "confirmed_sell_quote_received": decimal_str(quote_received),
        "direct_sell_quote_received": decimal_str(direct_quote_received),
        "next_hop_sell_quote_received": decimal_str(next_hop_quote_received),
        "confirmed_sell_count": str(confirmed_sell_count),
        "next_hop_count": str(next_hop_count),
        "transfer_safety_status": transfer_safety.get("status", "unverified"),
        "transfer_safety_detail": transfer_safety.get("detail", ""),
        "dex_quote_status": dex_quote_safety.get("status", "unverified"),
        "dex_quote_detail": dex_quote_safety.get("detail", ""),
        "router_sell_status": router_sell_safety.get("status", "unverified"),
        "router_sell_detail": router_sell_safety.get("detail", ""),
        "out_scan_from_block": str(trace_from),
        "as_of_block": str(latest),
        "as_of_time": now_iso(),
    }


def summarize_tx(event: dict[str, Any], tx_hash: str) -> dict[str, Any]:
    tx = rpc_call(event["chain"], "eth_getTransactionByHash", [tx_hash]) or {}
    receipt = get_transaction_receipt(event["chain"], tx_hash)
    transfers = receipt_token_transfers(event["chain"], tx_hash, event["token"], event["quote"])
    nets = net_by_address(transfers, event["token"]["address"], event["quote"]["address"])
    buyer, token_bought, spent_quote = best_buyer(event, nets)
    price_source = "transfer"
    if token_bought and not spent_quote:
        spent_quote = pool_side_quote_in(event, nets)
        price_source = "pool_quote_inferred" if spent_quote else "transfer"
    avg = spent_quote / token_bought if spent_quote and token_bought else None
    estimated_spent = Decimal(0)
    estimated_avg = None
    if token_bought and not spent_quote:
        estimated_spent = known_tx_estimated_spent_quote(event, tx_hash)
        if estimated_spent:
            price_source = "known_tx_estimate"
        if not estimated_spent:
            estimated_spent = estimate_quote_from_curve(event.get("market_context", {}), token_bought)
            price_source = "snipe_curve_estimate" if estimated_spent else "unknown"
        estimated_avg = estimated_spent / token_bought if estimated_spent else None
    bribe = largest_internal_native(event["chain"], tx_hash)
    return {
        "tx": tx_hash,
        "block": hex_to_int(receipt.get("blockNumber")),
        "tx_index": hex_to_int(receipt.get("transactionIndex")),
        "status": "success" if receipt.get("status") == "0x1" else "failed",
        "from": norm(tx.get("from")),
        "to": norm(tx.get("to")),
        "selector": (tx.get("input") or "0x")[:10],
        "buyer": buyer,
        "token_bought": decimal_str(token_bought),
        "spent_quote": decimal_str(spent_quote),
        "avg_price": decimal_str(avg),
        "estimated_spent_quote": decimal_str(estimated_spent),
        "estimated_avg_price": decimal_str(estimated_avg),
        "price_source": price_source,
        "largest_internal_native": bribe,
        "transfer_count": len(transfers),
    }


def meaningful_buy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    min_token = Decimal(os.environ.get("ALPHA_OPENING_MIN_TOKEN_BUY", "100"))
    min_spent = Decimal(os.environ.get("ALPHA_OPENING_MIN_QUOTE_SPENT", "10000"))
    min_bribe = Decimal(os.environ.get("ALPHA_OPENING_MIN_BRIBE_NATIVE", "1"))
    out = []
    for row in rows:
        try:
            token_amount = Decimal(str(row.get("token_bought", "0") or "0"))
            spent = effective_spent_quote(row)
            bribe = Decimal(str(row.get("largest_internal_native", {}).get("amount", "0") or "0"))
        except Exception:
            continue
        if token_amount >= min_token and (spent >= min_spent or bribe >= min_bribe):
            out.append(row)
    return out


def effective_spent_quote(row: dict[str, Any]) -> Decimal:
    actual = decimal_from(row.get("spent_quote"))
    return actual if actual > 0 else decimal_from(row.get("estimated_spent_quote"))


def known_tx_estimated_spent_quote(event: dict[str, Any], tx_hash: str) -> Decimal:
    tx_hash = norm(tx_hash)
    for row in event.get("known_txs", []) or []:
        if isinstance(row, dict) and norm(row.get("tx")) == tx_hash:
            value = decimal_from(row.get("estimated_spent_quote") or row.get("estimated_spent_usdt"))
            if value > 0:
                return value
    return Decimal(0)


def effective_avg_price(row: dict[str, Any]) -> Decimal:
    actual = decimal_from(row.get("avg_price"))
    return actual if actual > 0 else decimal_from(row.get("estimated_avg_price"))


def cohort_position_summary(rows: list[dict[str, Any]]) -> dict[str, Decimal | int]:
    total_token = sum((decimal_from(row.get("token_bought")) for row in rows), Decimal(0))
    total_spent = sum((effective_spent_quote(row) for row in rows), Decimal(0))
    current_token = Decimal(0)
    current_quote_est = Decimal(0)
    out_token = Decimal(0)
    confirmed_sell_quote = Decimal(0)
    traced = 0
    current_known = 0
    exited = 0
    moved = 0
    held = 0
    for row in rows:
        bought = decimal_from(row.get("token_bought"))
        if bought <= 0:
            continue
        trace = row.get("buyer_trace") or {}
        if not trace:
            continue
        traced += 1
        status = str(trace.get("status") or "")
        if status in {"mostly_exited_or_transferred", "mostly_exited_untraced"}:
            exited += 1
        elif status == "partially_moved":
            moved += 1
        elif status == "held_or_accumulated":
            held += 1
        current_raw = trace.get("current_balance")
        current_value = None
        if current_raw not in ("", None):
            current_value = max(decimal_from(current_raw), Decimal(0))
        outgoing = decimal_from(trace.get("out_after_buy"))
        if status == "mostly_exited_untraced":
            out_token += bought
        elif status == "mostly_exited_or_transferred" and current_value is not None:
            inferred_out = max(bought - current_value, Decimal(0))
            out_token += min(max(outgoing, inferred_out), bought)
        else:
            out_token += min(outgoing, bought)
        confirmed_sell_quote += decimal_from(trace.get("confirmed_sell_quote_received"))
        if current_value is not None:
            if current_value == 0 and outgoing == 0 and status == "held_or_accumulated":
                continue
            current_known += 1
            retained = min(current_value, bought)
            current_token += retained
            spent = effective_spent_quote(row)
            avg = spent / bought if spent and bought else effective_avg_price(row)
            if avg:
                current_quote_est += retained * avg
    net_out_pct = out_token / total_token * Decimal(100) if total_token else Decimal(0)
    current_pct = current_token / total_token * Decimal(100) if total_token else Decimal(0)
    return {
        "historical_token": total_token,
        "historical_spent": total_spent,
        "current_token": current_token,
        "current_quote_est": current_quote_est,
        "current_pct": current_pct,
        "out_token": out_token,
        "net_out_pct": net_out_pct,
        "confirmed_sell_quote": confirmed_sell_quote,
        "traced": traced,
        "current_known": current_known,
        "exited": exited,
        "moved": moved,
        "held": held,
    }


def cohort_position_text(summary: dict[str, Decimal | int], quote_symbol: str) -> str:
    parts = [f"首批历史开盘买入 {format_amount(summary.get('historical_spent'))} {quote_symbol}（非当前持仓）"]
    current_known = int(summary.get("current_known", 0) or 0)
    if current_known:
        parts.append(
            f"当前仍在原买入钱包约 {format_amount(summary.get('current_token'))} token"
            f"（按首批成本约 {format_amount(summary.get('current_quote_est'))} {quote_symbol}，{format_price(summary.get('current_pct'))}%）"
        )
        parts.append(f"净流出 {format_price(summary.get('net_out_pct'))}%")
    elif int(summary.get("traced", 0) or 0):
        parts.append("当前仍持仓未能确认")
    confirmed = Decimal(str(summary.get("confirmed_sell_quote") or "0"))
    if confirmed > 0:
        parts.append(f"已确认换出约 {format_amount(confirmed)} {quote_symbol}")
    return " / ".join(parts)


def sell_safety_summary(rows: list[dict[str, Any]]) -> dict[str, str]:
    statuses = []
    quote_statuses = []
    router_statuses = []
    details = []
    for row in rows:
        trace = row.get("buyer_trace") or {}
        status = str(trace.get("transfer_safety_status") or "")
        if status:
            statuses.append(status)
        quote_status = str(trace.get("dex_quote_status") or "")
        if quote_status:
            quote_statuses.append(quote_status)
        router_status = str(trace.get("router_sell_status") or "")
        if router_status:
            router_statuses.append(router_status)
        detail = str(trace.get("transfer_safety_detail") or "")
        if detail:
            details.append(detail)
        quote_detail = str(trace.get("dex_quote_detail") or "")
        if quote_detail:
            details.append(quote_detail)
        router_detail = str(trace.get("router_sell_detail") or "")
        if router_detail:
            details.append(router_detail)
    if "blocked" in statuses:
        return {
            "status": "可转出模拟失败；禁止跟随",
            "gate": "blocked_transfer_failed",
            "detail": "; ".join(details[:2]),
        }
    quote_ok_statuses = {"dex_quote_verified", "infinity_cl_quote_verified"}
    has_quote_ok = any(status in quote_ok_statuses for status in quote_statuses)
    if any(status in {"quote_failed", "infinity_cl_quote_failed"} for status in quote_statuses) and not has_quote_ok:
        return {
            "status": "DEX报价失败；禁止跟随",
            "gate": "blocked_dex_quote_failed",
            "detail": "; ".join(details[:2]),
        }
    if "router_sell_failed" in router_statuses:
        return {
            "status": "Router卖出模拟失败；禁止跟随",
            "gate": "blocked_router_sell_failed",
            "detail": "; ".join(details[:2]),
        }
    if "infinity_roundtrip_eth_call_failed" in router_statuses:
        return {
            "status": "v4执行门失败；禁止跟随",
            "gate": "blocked_infinity_roundtrip_failed",
            "detail": "; ".join(details[:2]),
        }
    if "infinity_roundtrip_readback_failed" in router_statuses:
        return {
            "status": "v4余额/授权读回失败；禁止跟随",
            "gate": "blocked_infinity_readback_failed",
            "detail": "; ".join(details[:2]),
        }
    if "infinity_roundtrip_quote_failed" in router_statuses:
        return {
            "status": "v4买入腿报价失败；禁止跟随",
            "gate": "blocked_infinity_roundtrip_quote_failed",
            "detail": "; ".join(details[:2]),
        }
    if "infinity_roundtrip_low_recovery" in router_statuses:
        return {
            "status": "v4往返回收率过低；禁止跟随",
            "gate": "blocked_infinity_low_recovery",
            "detail": "; ".join(details[:3]),
        }
    if "infinity_roundtrip_recovery_verified" in router_statuses and "transfer_verified" in statuses and has_quote_ok:
        return {
            "status": "v4可转出、报价和往返回收率已验证；仍需开盘/筹码/盘口规则确认",
            "gate": "infinity_recovery_rate_verified_tax_uncertain",
            "detail": "; ".join(details[:3]),
        }
    if (
        "infinity_roundtrip_eth_call_success_no_recovery_rate" in router_statuses
        or "infinity_roundtrip_eth_call_verified" in router_statuses
    ):
        return {
            "status": "v4往返未revert；回收率未验证，禁止跟随",
            "gate": "blocked_infinity_recovery_unverified",
            "detail": "; ".join(details[:3]),
        }
    if "transfer_verified" in statuses and has_quote_ok and "router_sell_verified" in router_statuses:
        return {
            "status": "首批钱包可转出、DEX报价和Router卖出模拟均可用；仍需多地址税费验证",
            "gate": "router_sell_verified_tax_uncertain",
            "detail": "; ".join(details[:3]),
        }
    if "transfer_verified" in statuses and "infinity_cl_quote_verified" in quote_statuses:
        return {
            "status": "首批钱包可转出且v4报价可用；Quoter不触发税费/黑名单，禁止跟随",
            "gate": "blocked_tax_unverified",
            "detail": "; ".join(details[:3]),
        }
    if "transfer_verified" in statuses and "dex_quote_verified" in quote_statuses:
        return {
            "status": "首批钱包可转出且DEX报价可用；税费/黑名单未完整验证，禁止放大仓位",
            "gate": "blocked_tax_unverified",
            "detail": "; ".join(details[:2]),
        }
    if "transfer_verified" in statuses:
        return {
            "status": "首批钱包可转出已验证；DEX卖出/税费未验证，禁止放大仓位",
            "gate": "blocked_swap_unverified",
            "detail": "; ".join(details[:2]),
        }
    return {"status": "未验证；禁止发跟随信号", "gate": "blocked_unverified", "detail": ""}


def merge_contract_safety(dynamic: dict[str, str], static: dict[str, str]) -> dict[str, str]:
    if static.get("gate") in {"blocked_static_contract_risk", "blocked_no_contract_code"}:
        return static
    if static.get("gate") == "blocked_contract_controls_unverified":
        status = dynamic.get("status") or "未验证；禁止发跟随信号"
        detail = "; ".join(part for part in [dynamic.get("detail", ""), static.get("detail", "")] if part)
        return {
            "status": f"{status}；{static['status']}",
            "gate": dynamic.get("gate") or static["gate"],
            "detail": detail,
        }
    return dynamic


def estimate_quote_from_curve(context: dict[str, Any], token_amount: Decimal) -> Decimal:
    curve = []
    for raw in context.get("snipe_curve", []) or []:
        try:
            amount_out = Decimal(str(raw.get("amount_out_token", "0")))
            pressure = Decimal(str(raw.get("buy_pressure_usdt", "0")))
        except InvalidOperation:
            continue
        if amount_out > 0 and pressure > 0:
            curve.append((amount_out, pressure))
    if not curve or token_amount <= 0:
        return Decimal(0)
    curve.sort(key=lambda row: row[0])
    if token_amount <= curve[0][0]:
        return token_amount * curve[0][1] / curve[0][0]
    for (a0, p0), (a1, p1) in zip(curve, curve[1:]):
        if token_amount <= a1:
            span = a1 - a0
            if span <= 0:
                return p1
            return p0 + (token_amount - a0) * (p1 - p0) / span
    a0, p0 = curve[-2] if len(curve) > 1 else (Decimal(0), Decimal(0))
    a1, p1 = curve[-1]
    if a1 <= a0:
        return p1
    return p1 + (token_amount - a1) * (p1 - p0) / (a1 - a0)


def first_value_by_prefix(payload: dict[str, Any], prefix: str) -> str:
    for key, value in payload.items():
        if str(key).startswith(prefix) and value not in ("", None):
            return str(value)
    return ""


def build_events() -> list[dict[str, Any]]:
    config = read_json(CONFIG_PATH, {"items": []})
    latest_cache: dict[str, int] = {}
    events = []
    for item in config.get("items", []):
        if item.get("active_monitoring") is False or item.get("opening_watch_skip_generic") or item.get("project_watch_skip_generic"):
            continue
        priority = str(item.get("priority", ""))
        if not priority.startswith(("P0", "P1", "P2")):
            continue
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        contracts = [
            row for row in item.get("contracts", [])
            if str(row.get("chain", "")).lower() == CHAIN and is_address(row.get("address")) and norm(row.get("address")) not in QUOTE_TOKENS
        ]
        if not contracts:
            continue
        token_address = norm(contracts[0]["address"])
        for pool in item.get("pool_ids", []):
            if str(pool.get("chain", CHAIN)).lower() != CHAIN:
                continue
            start = parse_utc8(pool.get("start_time_utc8", ""))
            if not start:
                continue
            latest = latest_cache.setdefault(CHAIN, latest_block_number(CHAIN))
            seconds_until = int((start - now_utc()).total_seconds())
            max_age = int(os.environ.get("ALPHA_OPENING_MAX_AGE_HOURS", "12")) * 3600
            lookahead = int(os.environ.get("ALPHA_OPENING_LOOKAHEAD_HOURS", "48")) * 3600
            if seconds_until > lookahead or seconds_until < -max_age:
                continue
            opening_block = first_block_at_or_after(CHAIN, int(start.timestamp()), latest)
            quote_address = norm(pool.get("quote_address") or USDT)
            token = token_meta(CHAIN, token_address, symbol)
            quote = token_meta(CHAIN, quote_address, QUOTE_TOKENS.get(quote_address, "QUOTE"))
            events.append(
                {
                    "symbol": symbol,
                    "name": item.get("name", ""),
                    "priority": priority,
                    "chain": CHAIN,
                    "token": token,
                    "quote": quote,
                    "pool_id": pool.get("pool_id", ""),
                    "start_time_utc8": pool.get("start_time_utc8", ""),
                    "start_time_utc": start.isoformat(),
                    "seconds_until_start": seconds_until,
                    "opening_block": opening_block,
                    "latest_block": latest,
                    "hook": pool.get("hook", ""),
                    "operator": pool.get("operator", ""),
                    "fee": pool.get("fee", ""),
                    "parameters": pool.get("parameters", ""),
                    "pool_manager": pool.get("pool_manager", ""),
                    "initial_price": first_value_by_prefix(pool, "initial_price"),
                    "market_context": item.get("market_context", {}),
                    "known_contracts": item.get("known_contracts", []),
                    "cex_deposit_addresses": item.get("cex_deposit_addresses", []),
                    "cex_addresses": item.get("cex_addresses", []),
                    "exchange_aggregator_addresses": item.get("exchange_aggregator_addresses", []),
                    "exchange_aggregator_suspect_addresses": item.get("exchange_aggregator_suspect_addresses", []),
                    "exchange_rebalance_addresses": item.get("exchange_rebalance_addresses", []),
                    "neutral_contracts": item.get("neutral_contracts", []),
                    "lp_locker_addresses": item.get("lp_locker_addresses", []),
                    "staking_addresses": item.get("staking_addresses", []),
                    "watch_addresses": item.get("watch_addresses", []),
                    "event_distributions": item.get("event_distributions", []),
                    "known_txs": item.get("known_txs", []),
                    "required_checks": item.get("required_checks", []),
                }
            )
    return events


def build_snapshot() -> dict[str, Any]:
    events = []
    for event in build_events():
        if event.get("opening_block") is None:
            event.update({"status": "waiting", "rows": [], "analysis": analyze_waiting(event)})
        else:
            event.update(build_opened_event(event))
        events.append(event)
    alerts = [key for event in events for key in event_alert_keys(event)]
    seen = set(read_json(SEEN_PATH, []))
    new_alerts = [key for key in alerts if not alert_key_seen(key, seen)]
    return {
        "generated_at": now_iso(),
        "event_count": len(events),
        "alert_count": len(alerts),
        "new_alert_count": len(new_alerts),
        "events": events,
    }


def build_opened_event(event: dict[str, Any]) -> dict[str, Any]:
    latest = int(event["latest_block"])
    logs = opening_transfer_logs(event, latest)
    event["liquidity_flow"] = scan_key_liquidity_flows(event, latest)
    max_txs = int(os.environ.get("ALPHA_OPENING_MAX_TXS", "25"))
    rows = [summarize_tx(event, tx_hash) for tx_hash in selected_tx_hashes(logs, max_txs)]
    for row in meaningful_buy_rows(rows)[: int(os.environ.get("ALPHA_OPENING_TRACE_BUYERS", "4"))]:
        try:
            row["buyer_trace"] = trace_buyer(event, row["buyer"], int(row["block"] or event["opening_block"]), latest, Decimal(row["token_bought"]))
        except Exception as exc:
            row["buyer_trace"] = {"status": "trace_failed", "error": str(exc)}
    scan_to_block = min(latest, int(event["opening_block"]) + int(os.environ.get("ALPHA_OPENING_SCAN_BLOCKS", "240")))
    return {
        "status": "opened",
        "scan_to_block": scan_to_block,
        "transfer_logs": len(logs),
        "relevant_tx_count": len(rows),
        "rows": rows,
        "analysis": analyze_opened(event, rows),
    }


def selected_tx_hashes(logs: list[dict[str, Any]], max_txs: int) -> list[str]:
    ordered: list[str] = []
    seen = set()
    sorted_logs = sorted(
        logs,
        key=lambda row: (
            int(row.get("blockNumber") or "0x0", 16),
            int(row.get("transactionIndex") or "0x0", 16),
            int(row.get("logIndex") or "0x0", 16),
        ),
    )
    for log in sorted_logs:
        tx_hash = log.get("transactionHash", "")
        if tx_hash and tx_hash not in seen:
            seen.add(tx_hash)
            ordered.append(tx_hash)
    if len(ordered) <= max_txs:
        return ordered
    head_count = min(max_txs // 2, int(os.environ.get("ALPHA_OPENING_HEAD_TXS", "12")))
    tail_count = max_txs - head_count
    selected = ordered[:head_count]
    for tx_hash in ordered[-tail_count:]:
        if tx_hash not in selected:
            selected.append(tx_hash)
    return selected[:max_txs]


def analyze_waiting(event: dict[str, Any]) -> dict[str, str]:
    seconds = int(event.get("seconds_until_start") or 0)
    context = event.get("market_context", {})
    pool_price = first_value_by_prefix(context, "pool_init_price") or event.get("initial_price", "")
    snipe_price = first_value_by_prefix(context, "snipe_400k_end_price") or first_value_by_prefix(context, "snipe_400k_reaches")
    if seconds <= 3600:
        spot = "只看首块证据；高买压或高bribe打到压力位就不追"
        perp = "先不开；冲高后等分发外流、价格破位和可交易合约深度"
        trade_signal = "等待开盘；触发条件是低bribe、低均价、首批买后持有"
    else:
        spot = "准备预案；开盘前只做合约、池子、桥和活动筹码确认"
        perp = "只设预案；等上线后交易所流入和价格结构"
        trade_signal = "未到交易窗口；只准备监控"
    attention_parts = [
        f"开盘 {event.get('start_time_utc8')} UTC+8",
        f"池子价 {pool_price}" if pool_price else "",
        f"40万买压终点 {snipe_price}" if snipe_price else "",
        "旧hook要用token反推poolId确认" if event.get("pool_id") else "",
        "看大额跨链和活动分发" if event.get("event_distributions") else "",
    ]
    attention = "；".join(part for part in attention_parts if part)
    return {
        "conclusion": f"{event['symbol']} 已进入开盘预案窗口，等待开盘块。",
        "spot_action": spot,
        "perp_action": perp,
        "attention": attention,
        "operator_behavior": "项目方已释放池子/开盘时间信号，下一步看是否补池子、改区间或大额跨链。",
        "sniper_behavior": "狙击手会围绕开盘首块竞争，重点看首批买入金额、bribe、均价和买后去向。",
        "direction": "观察；等首块交易和买后去向",
        "trade_signal": trade_signal,
        "sell_safety_status": "未验证；禁止发跟随信号",
        "can_sell_gate": "blocked_unverified",
        "buyer_trace_summary": "未开盘",
        "total_spent_quote": "",
        "weighted_avg_price": "",
        "max_bribe_native": "",
    }


SMART_MONEY_BLOCK_CLASSES = {
    "mm_or_project_suspect",
    "project_rebalance",
    "project_treasury",
    "exchange_aggregator",
    "exchange_aggregator_suspect",
    "exchange_rebalance",
}


def onchain_netflow_reliable_for_opening(event: dict[str, Any]) -> bool:
    context = event.get("market_context") or {}
    venue_class = str(
        event.get("venue_class")
        or context.get("venue_class")
        or context.get("alpha_venue_class")
        or context.get("venue")
        or ""
    ).upper()
    if venue_class == "ALPHA_DOMINANT" and os.environ.get("ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT", "0") != "1":
        return False
    return True


def trace_class_set(row: dict[str, Any]) -> set[str]:
    trace = row.get("buyer_trace") or {}
    classes = set()
    for key in ("out_destination_classes", "destination_classes"):
        raw = str(trace.get(key) or "")
        for item in raw.split(","):
            item = item.strip()
            if item:
                classes.add(item)
    return classes


def buyer_caution_reason(event: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    reasons = []
    if not onchain_netflow_reliable_for_opening(event):
        reasons.append("Alpha主导净流未认证")
    for row in rows:
        buyer = norm(row.get("buyer"))
        if buyer and destination_class(event, buyer) in SMART_MONEY_BLOCK_CLASSES:
            reasons.append("买家为项目/MM/聚合器嫌疑地址")
            break
        if trace_class_set(row) & SMART_MONEY_BLOCK_CLASSES:
            reasons.append("转出去向含项目/MM/聚合器嫌疑地址")
            break
    return "；".join(dict.fromkeys(reasons))


def analyze_opened(event: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, str]:
    buys = meaningful_buy_rows(rows)
    total_token = sum((decimal_from(row.get("token_bought")) for row in buys), Decimal(0))
    actual_spent = sum((decimal_from(row.get("spent_quote")) for row in buys), Decimal(0))
    total_spent = sum((effective_spent_quote(row) for row in buys), Decimal(0))
    weighted_avg = total_spent / total_token if total_token else Decimal(0)
    estimated_used = bool(total_spent and actual_spent < total_spent)
    bribes = [decimal_from(row.get("largest_internal_native", {}).get("amount", "0")) for row in rows]
    max_bribe = max(bribes, default=Decimal(0))
    cohort = cohort_position_summary(buys)
    cohort_status = cohort_position_text(cohort, event["quote"]["symbol"])
    safety = merge_contract_safety(sell_safety_summary(buys), inspect_token_contract_safety(event))
    trace = buyer_trace_summary(buys)
    caution_reason = buyer_caution_reason(event, buys)
    netflow_reliable = onchain_netflow_reliable_for_opening(event)
    held = [row for row in buys if row.get("buyer_trace", {}).get("status") == "held_or_accumulated"]
    moved = [row for row in buys if row.get("buyer_trace", {}).get("status") in {"partially_moved", "mostly_exited_or_transferred"}]
    confirmed_sell_min = Decimal(os.environ.get("ALPHA_OPENING_CONFIRMED_SELL_MIN_QUOTE", "10000"))
    confirmed_sell_quote = Decimal(str(cohort.get("confirmed_sell_quote") or "0"))
    high_competition = total_spent >= Decimal(os.environ.get("ALPHA_OPENING_HIGH_COMPETITION_QUOTE", "400000")) or max_bribe >= Decimal(os.environ.get("ALPHA_OPENING_HIGH_COMPETITION_BRIBE", "50"))
    context = event.get("market_context", {})
    pressure_price = decimal_from(
        first_value_by_prefix(context, "snipe_400k_end_price")
        or first_value_by_prefix(context, "snipe_400k_reaches")
        or first_value_by_prefix(context, "snipe_200k_reaches"),
        Decimal(0),
    )
    follow_avg_ceiling = decimal_from(
        first_value_by_prefix(context, "snipe_400k_avg")
        or event.get("initial_price")
        or first_value_by_prefix(context, "pool_init_price"),
        Decimal(0),
    )
    avg_above_pressure = bool(pressure_price and weighted_avg and weighted_avg >= pressure_price)
    avg_in_follow_zone = bool(
        weighted_avg
        and (
            not follow_avg_ceiling
            or weighted_avg <= follow_avg_ceiling * Decimal(os.environ.get("ALPHA_OPENING_FOLLOW_AVG_MULTIPLIER", "1.25"))
        )
    )
    low_bribe = max_bribe < Decimal(os.environ.get("ALPHA_OPENING_LOW_BRIBE_NATIVE", "1"))
    sell_zone_token = decimal_from(context.get("sell_zone_total_token"))
    sell_zone_consumed_pct = (total_token / sell_zone_token * Decimal(100)) if sell_zone_token else Decimal(0)
    sell_zone_heavy = bool(sell_zone_consumed_pct >= Decimal(os.environ.get("ALPHA_OPENING_SELL_ZONE_HEAVY_PCT", "60")))
    spent_label = format_amount(total_spent) + ("（曲线估算）" if estimated_used else "")
    liquidity_flow = event.get("liquidity_flow") or {}
    liquidity_flow_summary = str(liquidity_flow.get("summary") or "")
    liquidity_flow_risk = str(liquidity_flow.get("risk") or "none")
    liquidity_flow_active = liquidity_flow_risk not in {"none", "skipped_old_opening"}

    if not rows:
        conclusion = f"{event['symbol']} 已到开盘块，暂未发现首批 token 转账。"
        spot = "观察；等真实成交"
        perp = "不开；没有价格和抛压证据"
        direction = "观察"
        trade_signal = "不买；没有真实成交"
        operator = "项目方尚未形成可见成交路径。"
        sniper = "暂无前排买入证据。"
    elif confirmed_sell_quote >= confirmed_sell_min:
        conclusion = f"{event['symbol']} 首批买家累计确认换出 {format_amount(confirmed_sell_quote)} {event['quote']['symbol']}，按卖出信号处理。"
        spot = "减仓/卖出；空仓不接"
        perp = "偏空条件；等交易所流入、价格破位和可交易合约深度"
        direction = "偏空"
        trade_signal = "卖出/减仓；首批买家累计确认换出"
        operator = "已看到首批筹码换成报价资产，按真实派发处理。"
        sniper = "首批狙击资金已有确认卖出动作。"
    elif liquidity_flow_risk == "project_quote_in":
        conclusion = f"{event['symbol']} 池子/做市关键地址收到报价资产，项目侧资金回收风险上升。"
        spot = "不追；已有仓位先降风险，等报价资产去向确认"
        perp = "偏空条件；等交易所流入、价格走弱和可交易合约深度"
        direction = "中性偏空"
        trade_signal = "不跟；项目侧收到报价资产"
        operator = f"项目/做市相关地址出现报价资产回收：{liquidity_flow_summary}。"
        sniper = "首批买入信号降权，当前主线转为项目侧资金回收。"
    elif liquidity_flow_risk == "lp_remove":
        conclusion = f"{event['symbol']} 开盘短窗口出现减池/撤流动性事件，承接风险上升。"
        spot = "不追；已有仓位先降风险，等池子恢复和价格承接确认"
        perp = "偏空条件；等价格走弱和可交易合约深度"
        direction = "偏空"
        trade_signal = "卖出/减仓；LP 撤流动性"
        operator = f"项目/LP 相关合约出现减池动作：{liquidity_flow_summary}。"
        sniper = "首批买入信号让位于流动性风险，先看池子是否恢复。"
    elif liquidity_flow_risk == "lp_collect":
        conclusion = f"{event['symbol']} 开盘短窗口出现 LP 收取/提取事件，需要确认是否转入卖出路径。"
        spot = "不追；等费用/筹码去向确认"
        perp = "偏空观察；等交易所流入和价格走弱"
        direction = "中性偏空"
        trade_signal = "不跟；LP 收取事件待确认"
        operator = f"项目/LP 相关合约出现收取动作：{liquidity_flow_summary}。"
        sniper = "首批买入信号降权，当前看 LP 事件后续去向。"
    elif "余额接近0" in trace or "清仓转出" in trace:
        sell_note = f"且小额确认换出 {format_amount(confirmed_sell_quote)} {event['quote']['symbol']}，未达卖出阈值" if confirmed_sell_quote > 0 else "尚未确认卖到市场"
        conclusion = f"{event['symbol']} 首批买家出现清仓/余额接近0，{sell_note}。"
        spot = "不追；已有仓位先降风险"
        perp = "偏空条件；等交易所流入、价格破位和可交易合约深度"
        direction = "中性偏空"
        trade_signal = "不跟；首批清仓外转但未确认卖出"
        operator = "外转去向需要继续分类，先按筹码松动处理。"
        sniper = "首批狙击资金已经离开原买入钱包，是否卖出要看下一跳。"
    elif "已外转" in trace or moved:
        sell_note = f"且小额确认换出 {format_amount(confirmed_sell_quote)} {event['quote']['symbol']}，未达卖出阈值" if confirmed_sell_quote > 0 else "筹码稳定性不足"
        conclusion = f"{event['symbol']} 首批买家已有外转，{sell_note}。"
        spot = "不追；持仓先降风险"
        perp = "偏空条件；等外流扩大、价格转弱和可交易合约深度"
        direction = "中性偏空"
        trade_signal = "不跟；已持有先减风险"
        operator = "需要确认外转目的地是交易所、桥、新钱包还是池子。"
        sniper = "首批地址已有迁移动作，套利或撤退概率上升。"
    elif sell_zone_heavy:
        conclusion = f"{event['symbol']} 首批买走约 {format_amount(total_token)}，估算买压约 {spent_label} {event['quote']['symbol']}，约吃掉卖出区 {sell_zone_consumed_pct.quantize(Decimal('0.01'))}%；最大bribe {format_amount(max_bribe)} BNB。"
        spot = "空仓不追；已有仓位按冲高分批止盈，等回踩承接和项目侧资金去向"
        perp = "偏空预案；等交易所流入、价格走弱和可交易合约深度"
        direction = "中性偏空；项目卖出区被首批买盘大幅承接"
        trade_signal = "不追；等待回踩或资金回收证据"
        operator = "项目方预设卖出区被买盘接走，接下来重点看报价资产是否归集、跨链或进交易所。"
        sniper = f"首批狙击强度高，估算综合均价约 {format_price(weighted_avg)}；买后去向: {trace}。"
    elif high_competition:
        conclusion = f"{event['symbol']} 首批竞争强，首批历史买入规模约 {spent_label} {event['quote']['symbol']}，最大bribe {format_amount(max_bribe)} BNB。"
        spot = "空仓不追；已有仓位按冲高分批止盈，等回踩承接"
        perp = "偏空条件；等活动筹码领取、交易所流入、价格走弱和可交易合约深度"
        direction = "中性偏空；低价窗口已被首批竞争打掉"
        trade_signal = "不追；低价窗口已被抢走"
        operator = "项目方是否下场要看买入地址资金源和买后去向，先按高竞争盘处理。"
        sniper = f"狙击强度高，综合均价约 {format_price(weighted_avg)}。"
    elif avg_above_pressure:
        conclusion = f"{event['symbol']} 首批均价已接近或超过压力位，性价比不足。"
        spot = "空仓不追；等回踩或新承接"
        perp = "不开空；等活动筹码和价格结构"
        direction = "观察偏空"
        trade_signal = "不跟；首批成交价已过压力位"
        operator = "开盘价格已经被推高，后续看项目方是否继续托盘。"
        sniper = f"首批综合均价约 {format_price(weighted_avg)}，已经不在低价跟随区。"
    elif buys and held and len(held) >= max(1, len(buys) // 2) and low_bribe and avg_in_follow_zone and not caution_reason and netflow_reliable:
        conclusion = f"{event['symbol']} 首批买入 {len(buys)} 笔，当前低bribe且买后持有占优。"
        spot = "观察；DEX卖出/税费未完整验证前不发跟随试探"
        perp = "不开空；等冲高后的外流和深度"
        direction = "观察偏多"
        trade_signal = "观察；可售性未完整验证，暂不跟随"
        operator = "首批承接暂可观察，继续看补池子和关键钱包余额。"
        sniper = f"首批买后暂未跑，综合均价约 {format_price(weighted_avg)}；{safety['status']}。"
    elif buys:
        if caution_reason or not netflow_reliable:
            detail = caution_reason or "Alpha主导净流未认证"
            conclusion = f"{event['symbol']} 首批买入 {len(buys)} 笔，{detail}，不能当聪明钱承接。"
            spot = "观察；不把持有当承接，等真实净敞口和下一跳"
            perp = "不开；等交易所流入、价格结构和可交易深度"
            direction = "观察"
            trade_signal = "观察；嫌疑标签/Alpha主导净流未认证，暂不跟随"
            operator = f"当前证据被降权：{detail}。"
            sniper = f"首批买后暂未跑，但承接信号不可用；{safety['status']}。"
        else:
            conclusion = f"{event['symbol']} 首批买入 {len(buys)} 笔，当前暂未看到强外流。"
            spot = "观察；DEX卖出/税费未完整验证前不发跟随试探"
            perp = "不开空；等冲高和活动筹码"
            direction = "中性偏多"
            trade_signal = "观察；可售性未完整验证，暂不跟随"
            operator = "首批承接暂可观察，继续看补池子和关键钱包余额。"
            sniper = f"首批买后暂未跑，继续跟踪；{safety['status']}。"
    else:
        conclusion = f"{event['symbol']} 有链上动作，有效买入证据不足。"
        spot = "观察；补看路由、价格和holder变化"
        perp = "不开；证据不足"
        direction = "观察"
        trade_signal = "不买；有效买入证据不足"
        operator = "项目方实时行为仍需补证据。"
        sniper = "前排狙击强度不明。"

    return {
        "conclusion": conclusion,
        "spot_action": spot,
        "perp_action": perp,
        "attention": "重点看首批买家去向、活动分发、交易所流入、桥和池子区间是否被打穿。"
        + (f" 池/做市流向: {liquidity_flow_summary}。" if liquidity_flow_summary and liquidity_flow_active else ""),
        "operator_behavior": operator
        + (f" 池/做市流向补充: {liquidity_flow_summary}。" if liquidity_flow_summary and liquidity_flow_active and liquidity_flow_summary not in operator else ""),
        "sniper_behavior": sniper,
        "direction": direction,
        "trade_signal": trade_signal,
        "sell_safety_status": safety["status"],
        "can_sell_gate": safety["gate"],
        "sell_safety_detail": safety["detail"],
        "buyer_trace_summary": trace,
        "buyer_caution_reason": caution_reason,
        "onchain_netflow_reliable": str(netflow_reliable),
        "cohort_status_summary": cohort_status,
        "total_spent_quote": decimal_str(total_spent),
        "actual_spent_quote": decimal_str(actual_spent),
        "estimated_spent_used": "true" if estimated_used else "false",
        "weighted_avg_price": decimal_str(weighted_avg) if weighted_avg else "",
        "max_bribe_native": decimal_str(max_bribe),
        "sell_zone_consumed_pct": decimal_str(sell_zone_consumed_pct) if sell_zone_consumed_pct else "",
        "current_cohort_token": decimal_str(Decimal(str(cohort.get("current_token") or "0"))),
        "current_cohort_quote_est": decimal_str(Decimal(str(cohort.get("current_quote_est") or "0"))),
        "cohort_net_out_pct": decimal_str(Decimal(str(cohort.get("net_out_pct") or "0"))),
        "cohort_confirmed_sell_quote": decimal_str(confirmed_sell_quote),
        "liquidity_flow_summary": liquidity_flow_summary,
        "liquidity_flow_risk": liquidity_flow_risk,
        "as_of_block": trace_as_of_block(buys),
    }


def buyer_trace_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无有效首批买入"
    traced = [row for row in rows if row.get("buyer_trace")]
    if not traced:
        return "首批买家去向未追踪"
    as_of = trace_as_of_block(traced)
    suffix = f"；截至区块{as_of}" if as_of else ""
    confirmed_sell_min = Decimal(os.environ.get("ALPHA_OPENING_CONFIRMED_SELL_MIN_QUOTE", "10000"))
    cohort = cohort_position_summary(rows)
    sold_quote = Decimal(str(cohort.get("confirmed_sell_quote") or "0"))
    if sold_quote >= confirmed_sell_min:
        return f"已追踪{len(traced)}个首批买家，累计已确认DEX换出约{format_amount(sold_quote)}报价资产{suffix}"
    small_sell_text = f"；小额确认换出约{format_amount(sold_quote)}报价资产，未达卖出阈值" if sold_quote > 0 else "；未确认是否卖到市场"
    exited = [row for row in traced if row.get("buyer_trace", {}).get("status") in {"mostly_exited_or_transferred", "mostly_exited_untraced"}]
    untraced_exited = [row for row in traced if row.get("buyer_trace", {}).get("status") == "mostly_exited_untraced"]
    moved = [row for row in traced if row.get("buyer_trace", {}).get("status") == "partially_moved"]
    held = [row for row in traced if row.get("buyer_trace", {}).get("status") == "held_or_accumulated"]
    classes = trace_destination_classes(traced)
    class_text = f"，去向={classes}" if classes else ""
    if exited:
        if untraced_exited and len(untraced_exited) == len(exited):
            return f"已追踪{len(traced)}个首批买家，{len(untraced_exited)}个原买入钱包余额接近0，转出不在当前扫描窗口{small_sell_text}{suffix}"
        return f"已追踪{len(traced)}个首批买家，{len(exited)}个原买入钱包已清仓转出{class_text}{small_sell_text}{suffix}"
    if moved:
        return f"已追踪{len(traced)}个首批买家，{len(moved)}个已外转{class_text}{small_sell_text}{suffix}"
    return f"已追踪{len(traced)}个首批买家，暂未发现转出；{len(held)}个仍持有或增持{suffix}"


def trace_as_of_block(rows: list[dict[str, Any]]) -> str:
    blocks = []
    for row in rows:
        value = (row.get("buyer_trace") or {}).get("as_of_block")
        if value:
            try:
                blocks.append(int(value))
            except ValueError:
                pass
    return str(max(blocks)) if blocks else ""


def trace_destination_classes(rows: list[dict[str, Any]]) -> str:
    classes = set()
    for row in rows:
        raw = (row.get("buyer_trace") or {}).get("out_destination_classes", "")
        for item in raw.split(","):
            if item:
                classes.add(item)
    return ",".join(sorted(classes))


def event_alert_keys(event: dict[str, Any]) -> list[str]:
    keys = []
    seconds = int(event.get("seconds_until_start") or 0)
    if 0 < seconds <= int(os.environ.get("ALPHA_OPENING_PRELAUNCH_ALERT_HOURS", "36")) * 3600:
        keys.append("|".join(["prelaunch", event["symbol"], launch_stage(seconds), event.get("pool_id", ""), event.get("start_time_utc8", "")]))
    if event.get("status") == "opened":
        analysis = event.get("analysis", {})
        if analysis.get("trade_signal"):
            keys.append(
                "|".join(
                    [
                        "trade_signal",
                        event["symbol"],
                        str(event.get("opening_block", "")),
                        analysis.get("trade_signal", ""),
                        analysis.get("direction", ""),
                    ]
                )
            )
        if analysis.get("liquidity_flow_risk") and analysis.get("liquidity_flow_risk") not in {"none", "skipped_old_opening"}:
            keys.append("|".join(["liquidity_flow", event["symbol"], str(event.get("opening_block", "")), analysis.get("liquidity_flow_risk", "")]))
        for row in meaningful_buy_rows(event.get("rows", []))[:10]:
            spent = effective_spent_quote(row)
            bribe = decimal_from(row.get("largest_internal_native", {}).get("amount", "0"))
            if (
                spent >= Decimal(os.environ.get("ALPHA_OPENING_BUY_ALERT_MIN_QUOTE", "50000"))
                or bribe >= Decimal(os.environ.get("ALPHA_OPENING_BUY_ALERT_MIN_BRIBE_NATIVE", "10"))
            ):
                keys.append("|".join(["buy", event["symbol"], row.get("tx", ""), row.get("buyer", ""), alert_amount_bucket(spent, Decimal("50000"))]))
            trace = row.get("buyer_trace") or {}
            if trace:
                sell_bucket = alert_amount_bucket(
                    decimal_from(trace.get("confirmed_sell_quote_received"))
                    + decimal_from(trace.get("next_hop_sell_quote_received")),
                    Decimal(os.environ.get("ALPHA_OPENING_ALERT_QUOTE_BUCKET", "10000")),
                )
                keys.append(
                    "|".join(
                        [
                            "trace",
                            event["symbol"],
                            row.get("buyer", ""),
                            trace.get("status", ""),
                            trace.get("out_destination_classes", ""),
                            sell_bucket,
                        ]
                    )
                )
    return sorted(set(keys))


def alert_amount_bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    if step <= 0:
        step = Decimal("10000")
    bucket = (value // step) * step
    return decimal_str(bucket)


def alert_key_seen(key: str, seen: set[str]) -> bool:
    if key in seen:
        return True
    parts = key.split("|")
    if len(parts) >= 5 and parts[0] == "trade_signal":
        legacy_prefix = "|".join([parts[0], parts[1], parts[3]]) + "|"
        return any(old.startswith(legacy_prefix) for old in seen)
    if len(parts) >= 5 and parts[0] == "trace":
        legacy_key = "|".join(parts[:5])
        return any(old == legacy_key or old.startswith(legacy_key + "|") for old in seen)
    return False


def telegram_compact_amount(value: Any) -> str:
    amount = decimal_from(value)
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


def telegram_event_rank(event: dict[str, Any]) -> tuple[int, int, str]:
    analysis = event.get("analysis", {})
    signal = str(analysis.get("trade_signal") or "")
    liquidity_risk = str(analysis.get("liquidity_flow_risk") or "none")
    confirmed_sell = decimal_from(analysis.get("cohort_confirmed_sell_quote"))
    confirmed_sell_threshold = Decimal(os.environ.get("ALPHA_OPENING_CONFIRMED_SELL_MIN_QUOTE", "10000"))
    keys = event_alert_keys(event)
    if confirmed_sell >= confirmed_sell_threshold or liquidity_risk == "lp_remove" or "卖出" in signal or "减仓" in signal:
        risk_rank = 0
    elif liquidity_risk not in {"", "none", "skipped_old_opening"} or "偏空" in str(analysis.get("direction")):
        risk_rank = 1
    elif any(key.startswith("trace|") for key in keys):
        risk_rank = 2
    elif any(key.startswith("buy|") for key in keys):
        risk_rank = 3
    else:
        risk_rank = 4
    priority = str(event.get("priority", ""))
    priority_rank = int(priority[1]) if len(priority) > 1 and priority[1].isdigit() else 9
    return risk_rank, priority_rank, str(event.get("symbol", ""))


def telegram_event_evidence(event: dict[str, Any]) -> str:
    if event.get("status") != "opened":
        seconds = max(int(event.get("seconds_until_start") or 0), 0)
        return f"开盘 {event.get('start_time_utc8', '')}｜剩余{seconds // 60}m"
    analysis = event.get("analysis", {})
    quote_symbol = event.get("quote", {}).get("symbol", "")
    parts = []
    confirmed_sell = decimal_from(analysis.get("cohort_confirmed_sell_quote"))
    confirmed_sell_threshold = Decimal(os.environ.get("ALPHA_OPENING_CONFIRMED_SELL_MIN_QUOTE", "10000"))
    if confirmed_sell > 0:
        if confirmed_sell >= confirmed_sell_threshold:
            parts.append(f"确认卖出{telegram_compact_amount(confirmed_sell)} {quote_symbol}")
        else:
            parts.append(f"小额确认换出{telegram_compact_amount(confirmed_sell)} {quote_symbol}/未达阈值")
    liquidity_risk = str(analysis.get("liquidity_flow_risk") or "none")
    if liquidity_risk not in {"", "none", "skipped_old_opening"}:
        parts.append(f"流动性{liquidity_risk}")
    safety_gate = str(analysis.get("can_sell_gate") or "")
    safety_status = str(analysis.get("sell_safety_status") or "")
    if safety_gate.startswith("blocked"):
        parts.append("可售性未通过")
    elif "合约权限/暂停能力未完整验证" in safety_status:
        parts.append("可售性动态已验/合约权限未验")
    elif safety_gate == "router_sell_verified_tax_uncertain":
        parts.append("可售性路由已验证/税费待验")
    elif safety_gate == "infinity_recovery_rate_verified_tax_uncertain":
        parts.append("可售性v4回收已验证/规则待验")
    elif analysis.get("sell_safety_status"):
        parts.append("可售性待验")
    keys = event_alert_keys(event)
    if any(key.startswith("trace|") for key in keys):
        trace_summary = telegram_trace_summary(str(analysis.get("buyer_trace_summary") or ""))
        if trace_summary:
            parts.append(trace_summary)
    total_spent = decimal_from(analysis.get("total_spent_quote"))
    if total_spent > 0:
        parts.append(f"首批{telegram_compact_amount(total_spent)} {quote_symbol}")
    max_bribe = decimal_from(analysis.get("max_bribe_native"))
    if max_bribe > 0 and len(parts) < 3:
        parts.append(f"bribe {telegram_compact_amount(max_bribe)} BNB")
    return "｜".join(parts[:3]) or f"触发{len(event_alert_keys(event))}条告警"


def telegram_trace_summary(summary: str) -> str:
    if not summary:
        return ""
    if "cex_deposit" in summary or "cex_hot_wallet" in summary:
        return "买后去向CEX"
    if "余额接近0" in summary:
        return "买后去向原钱包近0/待追下一跳"
    if "已清仓转出" in summary:
        return "买后去向已清仓外转"
    if "已外转" in summary:
        return "买后去向已外转"
    if "暂未发现转出" in summary:
        return "买后去向仍持有/增持"
    return f"买后去向{summary[:24]}"


def telegram_text(snapshot: dict[str, Any]) -> str:
    new_keys = set(snapshot.get("_telegram_new_alert_keys") or [])
    events = sorted(
        (event for event in snapshot.get("events", []) if event_alert_keys(event)),
        key=lambda event: (
            0 if new_keys.intersection(event_alert_keys(event)) else 1,
            *telegram_event_rank(event),
        ),
    )
    new_count = snapshot.get("new_alert_count", snapshot.get("alert_count", 0))
    lines = [f"Alpha开盘｜新增{new_count}｜触发{len(events)}"]
    for event in events[:2]:
        analysis = event.get("analysis", {})
        rank = telegram_event_rank(event)[0]
        marker = "🔴" if rank == 0 else "🟠" if rank <= 2 else "🟡"
        lines.extend(
            [
                f"{marker} {event.get('symbol')} {event.get('priority')}｜{analysis.get('trade_signal', '观察')}",
                f"关键：{telegram_event_evidence(event)}",
                f"动作：{analysis.get('spot_action', '')}",
            ]
        )
    overflow = len(events) - 2
    if overflow > 0:
        lines.append(f"另有{overflow}项｜详情已归档")
    elif events:
        lines.append("详情已归档")
    return "\n".join(lines)


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Opening Block Watch",
        "",
        f"- generated_at: `{snapshot.get('generated_at')}`",
        f"- event_count: `{snapshot.get('event_count')}`",
        f"- alert_count: `{snapshot.get('alert_count')}`",
        f"- new_alert_count: `{snapshot.get('new_alert_count')}`",
        "",
    ]
    for event in snapshot.get("events", []):
        analysis = event.get("analysis", {})
        lines.extend(
            [
                f"## {event.get('symbol')} ({event.get('status')})",
                "",
                f"- start_time_utc8: `{event.get('start_time_utc8')}`",
                f"- opening_block: `{event.get('opening_block')}`",
                f"- latest_block: `{event.get('latest_block')}`",
                f"- scan_to_block: `{event.get('scan_to_block', '')}`",
                f"- conclusion: {analysis.get('conclusion', '')}",
                f"- direction: {analysis.get('direction', '')}",
                f"- trade_signal: {analysis.get('trade_signal', '')}",
                f"- spot_action: {analysis.get('spot_action', '')}",
                f"- perp_action: {analysis.get('perp_action', '')}",
                f"- sell_safety_status: {analysis.get('sell_safety_status', '')}",
                f"- can_sell_gate: `{analysis.get('can_sell_gate', '')}`",
                f"- cohort_status_summary: {analysis.get('cohort_status_summary', '')}",
                f"- buyer_trace_summary: {analysis.get('buyer_trace_summary', '')}",
                f"- as_of_block: `{analysis.get('as_of_block', '')}`",
                f"- total_spent_quote: `{analysis.get('total_spent_quote', '')}`",
                f"- actual_spent_quote: `{analysis.get('actual_spent_quote', '')}`",
                f"- estimated_spent_used: `{analysis.get('estimated_spent_used', '')}`",
                f"- weighted_avg_price: `{analysis.get('weighted_avg_price', '')}`",
                f"- max_bribe_native: `{analysis.get('max_bribe_native', '')}`",
                f"- sell_zone_consumed_pct: `{analysis.get('sell_zone_consumed_pct', '')}`",
                f"- current_cohort_token: `{analysis.get('current_cohort_token', '')}`",
                f"- current_cohort_quote_est: `{analysis.get('current_cohort_quote_est', '')}`",
                f"- cohort_net_out_pct: `{analysis.get('cohort_net_out_pct', '')}`",
                f"- cohort_confirmed_sell_quote: `{analysis.get('cohort_confirmed_sell_quote', '')}`",
                f"- liquidity_flow_summary: {analysis.get('liquidity_flow_summary', '')}",
                f"- liquidity_flow_risk: `{analysis.get('liquidity_flow_risk', '')}`",
                "",
            ]
        )
        rows = meaningful_buy_rows(event.get("rows", []))
        if rows:
            lines.extend(["| txIndex | buyer | token bought | quote spent | avg price | bribe | trace |", "| ---: | --- | ---: | ---: | ---: | ---: | --- |"])
            for row in rows[:20]:
                trace = row.get("buyer_trace", {})
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(row.get("tx_index", "")),
                            short_addr(row.get("buyer", "")),
                            format_amount(row.get("token_bought", "")),
                            quote_spent_display(row),
                            avg_price_display(row),
                            format_amount(row.get("largest_internal_native", {}).get("amount", "0")),
                            f"{trace.get('status', '')}/{trace.get('out_destination_classes', '')}",
                        ]
                    )
                    + " |"
                )
            lines.append("")
    return "\n".join(lines)


def quote_spent_display(row: dict[str, Any]) -> str:
    actual = decimal_from(row.get("spent_quote"))
    if actual > 0:
        return format_amount(actual)
    estimated = decimal_from(row.get("estimated_spent_quote"))
    return f"{format_amount(estimated)} est" if estimated else ""


def avg_price_display(row: dict[str, Any]) -> str:
    actual = decimal_from(row.get("avg_price"))
    if actual > 0:
        return format_price(actual)
    estimated = decimal_from(row.get("estimated_avg_price"))
    return f"{format_price(estimated)} est" if estimated else ""


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ALPHA_OPENING_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    keys = [key for event in snapshot.get("events", []) for key in event_alert_keys(event)]
    if not keys:
        return
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if not alert_key_seen(key, seen)]
    if not new_keys and os.environ.get("ALPHA_OPENING_FORCE_TELEGRAM") != "1":
        if any(key not in seen for key in keys):
            write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ALPHA_OPENING_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    push_snapshot = {**snapshot, "_telegram_new_alert_keys": new_keys}
    payload = {"chat_id": chat_id, "text": telegram_text(push_snapshot)[:TELEGRAM_LIMIT], "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20):
        pass
    write_json(SEEN_PATH, sorted(seen | set(keys)))
    record_push(snapshot)


def push_signature(snapshot: dict[str, Any]) -> str:
    parts = []
    for event in snapshot.get("events", [])[:4]:
        analysis = event.get("analysis", {})
        parts.append(
            "|".join(
                [
                    str(event.get("symbol", "")),
                    str(event.get("opening_block", "")),
                    str(analysis.get("trade_signal", "")),
                    str(analysis.get("direction", "")),
                    trace_signature_state(str(analysis.get("buyer_trace_summary", ""))),
                    alert_amount_bucket(decimal_from(analysis.get("current_cohort_quote_est")), Decimal("5000")),
                    pct_bucket(decimal_from(analysis.get("cohort_net_out_pct")), Decimal("5")),
                    alert_amount_bucket(decimal_from(analysis.get("cohort_confirmed_sell_quote")), Decimal("10000")),
                    str(analysis.get("liquidity_flow_risk", "")),
                    str(analysis.get("can_sell_gate", "")),
                ]
            )
        )
    return "\n".join(parts)


def pct_bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    if step <= 0:
        step = Decimal("5")
    bucket = (value // step) * step
    return decimal_str(bucket)


def trace_signature_state(text: str) -> str:
    markers = []
    for marker in (
        "累计已确认DEX换出",
        "清仓转出",
        "余额接近0",
        "已外转",
        "暂未发现转出",
        "去向=dex_sell_to_quote",
        "unknown_contract_pending_bearish",
        "cex_deposit",
    ):
        if marker in text:
            markers.append(marker)
    return ",".join(markers) if markers else text[:80]


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ALPHA_OPENING_REPEAT_SUPPRESS_MINUTES", "30"))
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


def record_push(snapshot: dict[str, Any]) -> None:
    write_json(LAST_PUSH_PATH, {"sent_at": now_iso(), "signature": push_signature(snapshot)})


def format_amount(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value)
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
    return format_price(amount)


def format_price(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value)
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return text
    if amount == 0:
        return "0"
    return f"{amount.quantize(Decimal('0.000001')):f}".rstrip("0").rstrip(".")


def launch_stage(seconds_until: int) -> str:
    if seconds_until <= 600:
        return "10m"
    if seconds_until <= 3600:
        return "1h"
    if seconds_until <= 6 * 3600:
        return "6h"
    return "36h"


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
    print(f"events={snapshot['event_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
