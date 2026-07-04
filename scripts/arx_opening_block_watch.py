#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label
from sniper_engine.rpc import get_block_by_number, get_transaction_receipt, hex_to_int, rpc_call, rpc_call_url, rpc_urls


getcontext().prec = 80

OUT_DIR = ROOT / "output" / "arx_opening_block_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
WATCHLIST_PATH = ROOT / "config" / "current_alpha_watchlist.json"

CHAIN = "bsc"
ARX = "0xd5f6ef5deabe61e6d5cdb49bfb6f156f2c1ca715"
USDT = "0x55d398326f99059ff775485246999027b3197955"
POOL_MANAGER = "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"
HOOK_OR_MANAGER = "0xb0bb171d333569cfd28a37f5c5dddaaa90ad46af"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
EXCLUDED_BUYERS = {
    ZERO,
    ARX,
    USDT,
    POOL_MANAGER,
    HOOK_OR_MANAGER,
}
TELEGRAM_LIMIT = 3900
DEFAULT_MIN_MEANINGFUL_ARX_BUY = "100"
DEFAULT_MIN_MEANINGFUL_USDT_SPENT = "10000"
DEFAULT_MIN_MEANINGFUL_BRIBE_BNB = "1"
DEFAULT_PRELAUNCH_SPRINT_WINDOW_SECONDS = "600"
PRICE_ANCHORS = {
    "pool_init_price": "0.13000013",
    "coinlist_public_sale_price": "0.20",
    "premarket_reference_price": "0.30",
    "snipe_200k_reaches": "0.20",
    "snipe_400k_reaches": "0.30",
}
CODE_CACHE: dict[str, bool] = {}
ARX_ITEM_CACHE: dict[str, Any] | None = None


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
    return "0x" + strip0x(topic)[-40:].lower()


def address_topic(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


def decimal_amount(raw: int, decimals: int = 18) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def decimal_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


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


def arx_launch_event() -> dict[str, Any]:
    payload = read_json(WATCHLIST_PATH, {"items": []})
    for item in payload.get("items", []):
        if str(item.get("symbol", "")).upper() != "ARX":
            continue
        events = []
        for pool in item.get("pool_ids", []):
            start = parse_utc8(pool.get("start_time_utc8", ""))
            if start:
                events.append((start, pool))
        if not events:
            break
        start, pool = sorted(events, key=lambda row: row[0])[0]
        return {
            "start_time_utc": start.isoformat(),
            "start_time_utc8": pool.get("start_time_utc8", ""),
            "pool_id": pool.get("pool_id", ""),
            "initial_price_usdt_per_arx": pool.get("initial_price_usdt_per_arx", ""),
        }
    return {
        "start_time_utc": "2026-06-22T10:00:00+00:00",
        "start_time_utc8": "2026-06-22 18:00:00",
        "pool_id": "",
        "initial_price_usdt_per_arx": "0.13000013",
    }


def arx_watchlist_item() -> dict[str, Any]:
    global ARX_ITEM_CACHE
    if ARX_ITEM_CACHE is not None:
        return ARX_ITEM_CACHE
    payload = read_json(WATCHLIST_PATH, {"items": []})
    for item in payload.get("items", []):
        if str(item.get("symbol", "")).upper() == "ARX":
            ARX_ITEM_CACHE = item
            return item
    ARX_ITEM_CACHE = {}
    return {}


def latest_block_number() -> int:
    return int(rpc_call(CHAIN, "eth_blockNumber", []), 16)


def block_timestamp(block_number: int) -> int:
    block = get_block_by_number(CHAIN, block_number, full_transactions=False)
    return int(block.get("timestamp") or "0x0", 16)


def find_first_block_at_or_after(target_ts: int, latest_block: int) -> int | None:
    previous = read_json(LATEST_PATH, {})
    cached = previous.get("opening_block")
    if isinstance(cached, int) and cached > 0:
        return cached
    latest_ts = block_timestamp(latest_block)
    if latest_ts < target_ts:
        return None
    low = 0
    high = latest_block
    while low < high:
        mid = (low + high) // 2
        if block_timestamp(mid) >= target_ts:
            high = mid
        else:
            low = mid + 1
    return low


def get_transfer_logs(token: str, from_block: int, to_block: int, max_logs: int) -> list[dict[str, Any]]:
    return get_transfer_logs_by_topics(token, from_block, to_block, [TRANSFER_TOPIC], max_logs)


def get_transfer_logs_by_topics(
    token: str,
    from_block: int,
    to_block: int,
    topics: list[Any],
    max_logs: int,
    chunk_blocks: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    chunk = chunk_blocks or int(os.environ.get("ARX_OPENING_LOG_CHUNK_BLOCKS", "40"))
    start = from_block
    while start <= to_block and len(rows) < max_logs:
        end = min(to_block, start + chunk - 1)
        query = {
            "address": token,
            "fromBlock": hex(start),
            "toBlock": hex(end),
            "topics": topics,
        }
        result = rpc_call(CHAIN, "eth_getLogs", [query]) or []
        rows.extend(result)
        start = end + 1
    return rows[:max_logs]


def get_transfer_logs_by_topics_quick(
    token: str,
    from_block: int,
    to_block: int,
    topics: list[Any],
    max_logs: int,
    chunk_blocks: int,
    timeout: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = from_block
    while start <= to_block and len(rows) < max_logs:
        end = min(to_block, start + chunk_blocks - 1)
        query = {
            "address": token,
            "fromBlock": hex(start),
            "toBlock": hex(end),
            "topics": topics,
        }
        try:
            rows.extend(quick_rpc_call("eth_getLogs", [query], timeout) or [])
        except Exception:
            break
        start = end + 1
    return rows[:max_logs]


def quick_rpc_call(method: str, params: list[Any], timeout: int) -> Any:
    last_error: Exception | None = None
    for url in rpc_urls(CHAIN):
        try:
            return rpc_call_url(url, method, params, timeout=timeout)
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError(f"no rpc url for {CHAIN}")


def transfer_amount(log: dict[str, Any], decimals: int = 18) -> Decimal:
    return decimal_amount(int(log.get("data") or "0x0", 16), decimals)


def transfer_log(log: dict[str, Any], decimals: int = 18) -> dict[str, Any]:
    topics = log.get("topics", [])
    return {
        "token": norm(log.get("address")),
        "block": int(log.get("blockNumber") or "0x0", 16),
        "tx": log.get("transactionHash", ""),
        "log_index": int(log.get("logIndex") or "0x0", 16),
        "from": topic_addr(topics[1]) if len(topics) > 1 else "",
        "to": topic_addr(topics[2]) if len(topics) > 2 else "",
        "amount": transfer_amount(log, decimals),
    }


def encode_balance_of(address: str) -> str:
    return "0x70a08231" + norm(address)[2:].rjust(64, "0")


def encode_transfer(to_address: str, raw_amount: int) -> str:
    return "0xa9059cbb" + norm(to_address)[2:].rjust(64, "0") + hex(raw_amount)[2:].rjust(64, "0")


def raw_token_amount(amount: Decimal, decimals: int = 18) -> int:
    if amount <= 0:
        return 0
    scaled = amount * (Decimal(10) ** decimals)
    return int(scaled.to_integral_value(rounding=ROUND_DOWN))


def arx_balance(address: str) -> Decimal:
    raw = rpc_call(CHAIN, "eth_call", [{"to": ARX, "data": encode_balance_of(address)}, "latest"])
    return decimal_amount(int(raw or "0x0", 16), 18)


def parse_bool_return(data: str) -> bool:
    raw = strip0x(data or "0x")
    if not raw:
        return True
    try:
        return int(raw[-64:], 16) != 0
    except ValueError:
        return False


def simulate_transfer_safety(holder: str, current: Decimal) -> dict[str, str]:
    if not is_address(holder):
        return {"status": "unverified", "detail": "invalid_holder"}
    if current <= 0:
        return {"status": "unverified", "detail": "no_balance_to_test"}
    probe_amount = min(current, Decimal(os.environ.get("ARX_OPENING_TRANSFER_PROBE_ARX", "1")))
    raw_amount = raw_token_amount(probe_amount)
    if raw_amount <= 0:
        return {"status": "unverified", "detail": "probe_amount_too_small"}
    recipient = norm(os.environ.get("ARX_OPENING_TRANSFER_PROBE_TO") or DEAD)
    if not is_address(recipient):
        recipient = DEAD
    timeout = int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        result = quick_rpc_call(
            "eth_call",
            [{"from": norm(holder), "to": ARX, "data": encode_transfer(recipient, raw_amount)}, "latest"],
            timeout,
        )
    except Exception as exc:
        return {"status": "blocked", "detail": str(exc)[:180]}
    if parse_bool_return(result or "0x"):
        return {"status": "transfer_verified", "detail": f"probe_amount={decimal_str(probe_amount)}"}
    return {"status": "blocked", "detail": "erc20_transfer_returned_false"}


def internal_transfers(tx_hash: str) -> list[dict[str, Any]]:
    if not os.environ.get("NODEREAL_API_KEY"):
        return []
    try:
        result = rpc_call(
            CHAIN,
            "nr_getAssetTransfers",
            [
                {
                    "category": ["internal"],
                    "transactionHash": tx_hash,
                    "order": "asc",
                    "maxCount": "0x64",
                }
            ],
        )
    except Exception:
        return []
    if isinstance(result, dict) and isinstance(result.get("transfers"), list):
        return result["transfers"]
    return []


def internal_value_to_bnb(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    if isinstance(value, int):
        raw = value
    else:
        text = str(value)
        raw = int(text, 16) if text.startswith("0x") else int(text)
    return decimal_amount(raw, 18)


def largest_internal_bnb(tx_hash: str) -> dict[str, Any]:
    transfers = internal_transfers(tx_hash)
    if not transfers:
        return {"amount_bnb": "0", "to": "", "rows": 0}
    largest = max(transfers, key=lambda row: internal_value_to_bnb(row.get("value")))
    return {
        "amount_bnb": decimal_str(internal_value_to_bnb(largest.get("value"))),
        "to": norm(largest.get("to")),
        "rows": len(transfers),
    }


def receipt_token_transfers(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for log in receipt.get("logs", []):
        if norm(log.get("address")) not in {ARX, USDT}:
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or norm(topics[0]) != TRANSFER_TOPIC:
            continue
        decimals = 18
        rows.append(transfer_log(log, decimals))
    return rows


def has_contract_code(address: str) -> bool:
    address = norm(address)
    if not is_address(address) or address == ZERO:
        return False
    if address not in CODE_CACHE:
        timeout = int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
        try:
            code = quick_rpc_call("eth_getCode", [address, "latest"], timeout) or "0x"
            CODE_CACHE[address] = code not in ("0x", "0x0", "")
        except Exception:
            CODE_CACHE[address] = False
    return CODE_CACHE[address]


def configured_address_class(address: str) -> str:
    address = norm(address)
    if not address:
        return ""
    global_label = global_address_label(CHAIN, address)
    if global_label:
        label_class = str(global_label.get("class") or "").strip()
        if label_class:
            return label_class
    item = arx_watchlist_item()
    for source in (item, item.get("market_context", {})):
        for row in source.get("known_contracts", []) or []:
            if isinstance(row, dict) and norm(row.get("address")) == address:
                return str(row.get("class") or row.get("destination_class") or "").strip()
        for key, class_name in (
            ("cex_deposit_addresses", "cex_deposit"),
            ("cex_addresses", "cex_deposit"),
            ("neutral_contracts", "lp_locker_or_staking"),
            ("lp_locker_addresses", "lp_locker_or_staking"),
            ("staking_addresses", "lp_locker_or_staking"),
        ):
            values = source.get(key, []) or []
            if any(norm(row.get("address") if isinstance(row, dict) else row) == address for row in values):
                return class_name
    return ""


def destination_class(address: str) -> str:
    address = norm(address)
    if not address:
        return "unknown"
    if address == ZERO:
        return "burn_or_zero"
    if address == ARX:
        return "token_contract"
    if address == USDT:
        return "quote_token"
    configured = configured_address_class(address)
    if configured:
        if configured in {"lp_position_manager", "pool_manager"}:
            return "lp_locker_or_staking"
        return configured
    if address in {POOL_MANAGER, HOOK_OR_MANAGER}:
        return "project_or_pool_contract"
    if has_contract_code(address):
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


def classify_recipient_next_hop_tx(recipient: str, tx_hash: str, outgoing_logs: list[dict[str, Any]]) -> dict[str, Any]:
    timeout = int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        receipt = quick_rpc_call("eth_getTransactionReceipt", [tx_hash], timeout)
        transfers = receipt_token_transfers(receipt or {})
    except Exception:
        transfers = []
    usdt_received = sum(
        (
            row["amount"]
            for row in transfers
            if norm(row.get("token")) == USDT and norm(row.get("to")) == norm(recipient)
        ),
        Decimal(0),
    )
    classes = {prefixed_next_hop_class(destination_class(row.get("to", ""))) for row in outgoing_logs}
    if usdt_received > 0:
        classes.add("next_hop_dex_sell_to_quote")
    return {"classes": classes, "usdt_received": usdt_received, "confirmed_sell_count": 1 if usdt_received > 0 else 0}


def trace_next_hop_from_recipient(buyer: str, recipient: str, from_block: int, latest_block: int) -> dict[str, Any]:
    recipient = norm(recipient)
    if not is_address(recipient) or recipient == norm(buyer):
        return {"classes": set(), "usdt_received": Decimal(0), "confirmed_sell_count": 0, "recipient_count": 0}
    max_span = int(os.environ.get("ARX_OPENING_NEXT_HOP_MAX_BLOCKS", "50000"))
    trace_from = max(from_block, latest_block - max_span)
    logs = get_transfer_logs_by_topics_quick(
        ARX,
        trace_from,
        latest_block,
        [TRANSFER_TOPIC, address_topic(recipient), None],
        max_logs=int(os.environ.get("ARX_OPENING_NEXT_HOP_MAX_LOGS", "80")),
        chunk_blocks=int(os.environ.get("ARX_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000")),
        timeout=int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5")),
    )
    parsed_logs = [transfer_log(row) for row in logs]
    by_tx: dict[str, list[dict[str, Any]]] = {}
    for row in parsed_logs:
        by_tx.setdefault(row["tx"], []).append(row)
    classes: set[str] = set()
    usdt_received = Decimal(0)
    confirmed_sell_count = 0
    ordered_txs = sorted(
        by_tx.items(),
        key=lambda item: max((row.get("block", 0), row.get("log_index", 0)) for row in item[1]),
    )
    for tx_hash, tx_logs in ordered_txs[: int(os.environ.get("ARX_OPENING_NEXT_HOP_CLASSIFY_TXS", "2"))]:
        classified = classify_recipient_next_hop_tx(recipient, tx_hash, tx_logs)
        classes.update(classified["classes"])
        usdt_received += classified["usdt_received"]
        confirmed_sell_count += int(classified["confirmed_sell_count"])
    return {
        "classes": classes,
        "usdt_received": usdt_received,
        "confirmed_sell_count": confirmed_sell_count,
        "recipient_count": 1 if parsed_logs else 0,
    }


def classify_outgoing_tx(buyer: str, tx_hash: str, outgoing_logs: list[dict[str, Any]], latest_block: int) -> dict[str, Any]:
    timeout = int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5"))
    try:
        receipt = quick_rpc_call("eth_getTransactionReceipt", [tx_hash], timeout)
        transfers = receipt_token_transfers(receipt or {})
    except Exception:
        transfers = []
    usdt_received = sum(
        (
            row["amount"]
            for row in transfers
            if norm(row.get("token")) == USDT and norm(row.get("to")) == norm(buyer)
        ),
        Decimal(0),
    )
    classes = set()
    eoa_recipients: list[tuple[str, int]] = []
    for row in outgoing_logs:
        to_addr = norm(row.get("to"))
        class_name = destination_class(to_addr)
        classes.add(class_name)
        if class_name == "eoa_or_unlabeled" and is_address(to_addr):
            eoa_recipients.append((to_addr, int(row.get("block") or 0)))
    if usdt_received > 0:
        classes.add("dex_sell_to_quote")
    next_hop_usdt_received = Decimal(0)
    next_hop_confirmed_sell_count = 0
    next_hop_count = 0
    seen_recipients = set()
    for recipient, block in eoa_recipients[: int(os.environ.get("ARX_OPENING_NEXT_HOP_RECIPIENTS", "2"))]:
        if recipient in seen_recipients:
            continue
        seen_recipients.add(recipient)
        next_hop = trace_next_hop_from_recipient(buyer, recipient, block, latest_block)
        classes.update(next_hop["classes"])
        next_hop_usdt_received += next_hop["usdt_received"]
        next_hop_confirmed_sell_count += int(next_hop["confirmed_sell_count"])
        next_hop_count += int(next_hop["recipient_count"])
    return {
        "classes": classes,
        "usdt_received": usdt_received + next_hop_usdt_received,
        "direct_usdt_received": usdt_received,
        "next_hop_usdt_received": next_hop_usdt_received,
        "confirmed_sell_count": (1 if usdt_received > 0 else 0) + next_hop_confirmed_sell_count,
        "next_hop_count": next_hop_count,
    }


def net_by_address(transfers: list[dict[str, Any]]) -> dict[str, dict[str, Decimal]]:
    nets: dict[str, dict[str, Decimal]] = {}
    for row in transfers:
        token = "arx" if norm(row.get("token")) == ARX else "usdt"
        amount = row["amount"]
        from_addr = norm(row.get("from"))
        to_addr = norm(row.get("to"))
        nets.setdefault(from_addr, {"arx": Decimal(0), "usdt": Decimal(0)})[token] -= amount
        nets.setdefault(to_addr, {"arx": Decimal(0), "usdt": Decimal(0)})[token] += amount
    return nets


def best_buyer(nets: dict[str, dict[str, Decimal]]) -> tuple[str, Decimal, Decimal]:
    candidates = []
    for address, amounts in nets.items():
        if address in EXCLUDED_BUYERS:
            continue
        arx_net = amounts.get("arx", Decimal(0))
        if arx_net <= 0:
            continue
        usdt_net = amounts.get("usdt", Decimal(0))
        candidates.append((address, arx_net, usdt_net))
    if not candidates:
        return "", Decimal(0), Decimal(0)
    return max(candidates, key=lambda row: row[1])


def trace_outgoing(address: str, from_block: int, latest_block: int, bought: Decimal) -> dict[str, str]:
    if not address or bought <= 0:
        return {"current_balance": "", "out_after_buy": "", "retention_pct": "", "status": "unknown"}
    current = arx_balance(address)
    trace_recent = int(os.environ.get("ARX_OPENING_TRACE_RECENT_BLOCKS", "5000"))
    trace_from = max(from_block, latest_block - trace_recent)
    logs = get_transfer_logs_by_topics_quick(
        ARX,
        trace_from,
        latest_block,
        [TRANSFER_TOPIC, address_topic(address), None],
        max_logs=int(os.environ.get("ARX_OPENING_TRACE_MAX_LOGS", "1200")),
        chunk_blocks=int(os.environ.get("ARX_OPENING_TRACE_LOG_CHUNK_BLOCKS", "5000")),
        timeout=int(os.environ.get("ARX_OPENING_CLASSIFY_RPC_TIMEOUT", "5")),
    )
    parsed_logs = [transfer_log(row) for row in logs]
    outgoing = sum((row["amount"] for row in parsed_logs), Decimal(0))
    by_tx: dict[str, list[dict[str, Any]]] = {}
    for row in parsed_logs:
        by_tx.setdefault(row["tx"], []).append(row)
    classes: set[str] = set()
    usdt_received = Decimal(0)
    confirmed_sell_count = 0
    direct_usdt_received = Decimal(0)
    next_hop_usdt_received = Decimal(0)
    next_hop_count = 0
    max_classify = int(os.environ.get("ARX_OPENING_CLASSIFY_OUT_TXS", "3"))
    ordered_txs = sorted(
        by_tx.items(),
        key=lambda item: max((row.get("block", 0), row.get("log_index", 0)) for row in item[1]),
        reverse=True,
    )
    for tx_hash, tx_logs in ordered_txs[:max_classify]:
        classified = classify_outgoing_tx(address, tx_hash, tx_logs, latest_block)
        classes.update(classified["classes"])
        usdt_received += classified["usdt_received"]
        direct_usdt_received += classified["direct_usdt_received"]
        next_hop_usdt_received += classified["next_hop_usdt_received"]
        confirmed_sell_count += int(classified["confirmed_sell_count"])
        next_hop_count += int(classified["next_hop_count"])
    retention = current / bought * Decimal(100) if bought else Decimal(0)
    if current <= bought * Decimal("0.05"):
        status = "mostly_exited_or_transferred" if outgoing > 0 else "mostly_exited_untraced"
    elif outgoing > 0:
        status = "partially_moved"
    else:
        status = "held_or_accumulated"
    transfer_safety = simulate_transfer_safety(address, current)
    return {
        "current_balance": decimal_str(current),
        "out_after_buy": decimal_str(outgoing),
        "retention_pct": decimal_str(retention),
        "status": status,
        "out_transfer_count": str(len(parsed_logs)),
        "last_out_to": norm(parsed_logs[-1].get("to")) if parsed_logs else "",
        "last_out_block": str(parsed_logs[-1].get("block")) if parsed_logs else "",
        "out_destination_classes": ",".join(sorted(classes)),
        "confirmed_sell_usdt_received": decimal_str(usdt_received),
        "direct_sell_usdt_received": decimal_str(direct_usdt_received),
        "next_hop_sell_usdt_received": decimal_str(next_hop_usdt_received),
        "confirmed_sell_count": str(confirmed_sell_count),
        "next_hop_count": str(next_hop_count),
        "transfer_safety_status": transfer_safety.get("status", "unverified"),
        "transfer_safety_detail": transfer_safety.get("detail", ""),
        "out_scan_from_block": str(trace_from),
        "as_of_block": str(latest_block),
        "as_of_time": now_iso(),
    }


def build_snapshot() -> dict[str, Any]:
    event = arx_launch_event()
    start_dt = datetime.fromisoformat(event["start_time_utc"])
    current = now_utc()
    seconds_until = int((start_dt - current).total_seconds())
    latest = latest_block_number()
    start_ts = int(start_dt.timestamp())
    opening_block = find_first_block_at_or_after(start_ts, latest)
    if opening_block is None:
        snapshot = {
            "generated_at": now_iso(),
            "status": "waiting",
            "launch_event": event,
            "seconds_until_start": seconds_until,
            "latest_block": latest,
            "opening_block": None,
            "scan_to_block": None,
            "rows": [],
            "analysis": analyze_waiting(seconds_until),
        }
        return snapshot

    scan_blocks = int(os.environ.get("ARX_OPENING_SCAN_BLOCKS", "240"))
    max_logs = int(os.environ.get("ARX_OPENING_MAX_LOGS", "300"))
    to_block = min(latest, opening_block + scan_blocks)
    logs = get_transfer_logs(ARX, opening_block, to_block, max_logs=max_logs)
    tx_hashes = []
    seen = set()
    for log in logs:
        tx_hash = log.get("transactionHash", "")
        if tx_hash and tx_hash not in seen:
            tx_hashes.append(tx_hash)
            seen.add(tx_hash)
    max_txs = int(os.environ.get("ARX_OPENING_MAX_TXS", "25"))
    rows = [summarize_tx(tx_hash) for tx_hash in tx_hashes[:max_txs]]
    top_rows = meaningful_buy_rows(rows)
    for row in top_rows[: int(os.environ.get("ARX_OPENING_TRACE_BUYERS", "4"))]:
        try:
            row["buyer_trace"] = trace_outgoing(row["buyer"], int(row["block"] or opening_block), latest, Decimal(row["arx_bought"]))
        except Exception as exc:
            row["buyer_trace"] = {"status": "trace_failed", "error": str(exc)}
    analysis = analyze_opening(seconds_until, opening_block, to_block, rows)
    return {
        "generated_at": now_iso(),
        "status": "opened",
        "launch_event": event,
        "seconds_until_start": seconds_until,
        "latest_block": latest,
        "opening_block": opening_block,
        "scan_to_block": to_block,
        "arx_transfer_logs": len(logs),
        "relevant_tx_count": len(rows),
        "rows": rows,
        "analysis": analysis,
    }


def summarize_tx(tx_hash: str) -> dict[str, Any]:
    tx = rpc_call(CHAIN, "eth_getTransactionByHash", [tx_hash])
    receipt = get_transaction_receipt(CHAIN, tx_hash)
    transfers = receipt_token_transfers(receipt)
    nets = net_by_address(transfers)
    buyer, arx_bought, usdt_net = best_buyer(nets)
    spent_usdt = abs(usdt_net) if usdt_net < 0 else Decimal(0)
    if spent_usdt == 0:
        spent_usdt = max((abs(row.get("usdt", Decimal(0))) for row in nets.values() if row.get("usdt", Decimal(0)) < 0), default=Decimal(0))
    avg_price = spent_usdt / arx_bought if spent_usdt and arx_bought else None
    bribe = largest_internal_bnb(tx_hash)
    return {
        "tx": tx_hash,
        "block": hex_to_int(receipt.get("blockNumber")),
        "tx_index": hex_to_int(receipt.get("transactionIndex")),
        "status": "success" if receipt.get("status") == "0x1" else "failed",
        "from": norm(tx.get("from")) if tx else "",
        "to": norm(tx.get("to")) if tx else "",
        "selector": (tx.get("input") or "0x")[:10] if tx else "",
        "gas_price_gwei": wei_to_gwei(tx.get("gasPrice") if tx else None),
        "buyer": buyer,
        "arx_bought": decimal_str(arx_bought),
        "spent_usdt": decimal_str(spent_usdt),
        "avg_price_usdt_per_arx": decimal_str(avg_price),
        "largest_internal_bnb": bribe,
        "transfer_count": len(transfers),
    }


def cohort_position_summary(rows: list[dict[str, Any]]) -> dict[str, Decimal | int]:
    total_arx = sum((decimal_value(row.get("arx_bought")) for row in rows), Decimal(0))
    total_spent = sum((decimal_value(row.get("spent_usdt")) for row in rows), Decimal(0))
    current_arx = Decimal(0)
    current_usdt_est = Decimal(0)
    out_arx = Decimal(0)
    confirmed_sell_usdt = Decimal(0)
    traced = 0
    current_known = 0
    exited = 0
    moved = 0
    held = 0
    for row in rows:
        bought = decimal_value(row.get("arx_bought"))
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
        if status == "mostly_exited_untraced":
            out_arx += bought
        else:
            out_arx += min(decimal_value(trace.get("out_after_buy")), bought)
        confirmed_sell_usdt += decimal_value(trace.get("confirmed_sell_usdt_received"))
        current_raw = trace.get("current_balance")
        if current_raw not in ("", None):
            current_value = max(decimal_value(current_raw), Decimal(0))
            outgoing = decimal_value(trace.get("out_after_buy"))
            if current_value == 0 and outgoing == 0 and status == "held_or_accumulated":
                continue
            current_known += 1
            retained = min(current_value, bought)
            current_arx += retained
            spent = decimal_value(row.get("spent_usdt"))
            avg = spent / bought if spent and bought else decimal_value(row.get("avg_price_usdt_per_arx"))
            if avg:
                current_usdt_est += retained * avg
    net_out_pct = out_arx / total_arx * Decimal(100) if total_arx else Decimal(0)
    current_pct = current_arx / total_arx * Decimal(100) if total_arx else Decimal(0)
    return {
        "historical_arx": total_arx,
        "historical_spent": total_spent,
        "current_arx": current_arx,
        "current_usdt_est": current_usdt_est,
        "current_pct": current_pct,
        "out_arx": out_arx,
        "net_out_pct": net_out_pct,
        "confirmed_sell_usdt": confirmed_sell_usdt,
        "traced": traced,
        "current_known": current_known,
        "exited": exited,
        "moved": moved,
        "held": held,
    }


def cohort_position_text(summary: dict[str, Decimal | int]) -> str:
    parts = [f"首批历史开盘买入 {format_amount(summary.get('historical_spent'))} USDT（非当前持仓）"]
    current_known = int(summary.get("current_known", 0) or 0)
    if current_known:
        parts.append(
            f"当前仍在原买入钱包约 {format_amount(summary.get('current_arx'))} ARX"
            f"（约 {format_amount(summary.get('current_usdt_est'))} USDT，{format_price(summary.get('current_pct'))}%）"
        )
        parts.append(f"净流出 {format_price(summary.get('net_out_pct'))}%")
    elif int(summary.get("traced", 0) or 0):
        parts.append("当前仍持仓未能确认")
    confirmed = Decimal(str(summary.get("confirmed_sell_usdt") or "0"))
    if confirmed > 0:
        parts.append(f"已确认换出约 {format_amount(confirmed)} USDT")
    return " / ".join(parts)


def sell_safety_summary(rows: list[dict[str, Any]]) -> dict[str, str]:
    statuses = []
    details = []
    for row in rows:
        trace = row.get("buyer_trace") or {}
        status = str(trace.get("transfer_safety_status") or "")
        if status:
            statuses.append(status)
        detail = str(trace.get("transfer_safety_detail") or "")
        if detail:
            details.append(detail)
    if "blocked" in statuses:
        return {
            "status": "可转出模拟失败；禁止跟随",
            "gate": "blocked_transfer_failed",
            "detail": "; ".join(details[:2]),
        }
    if "transfer_verified" in statuses:
        return {
            "status": "首批钱包可转出已验证；DEX卖出/税费未验证，禁止放大仓位",
            "gate": "blocked_swap_unverified",
            "detail": "; ".join(details[:2]),
        }
    return {"status": "未验证；禁止发跟随信号", "gate": "blocked_unverified", "detail": ""}


def analyze_waiting(seconds_until: int) -> dict[str, str]:
    hours = Decimal(seconds_until) / Decimal(3600)
    if seconds_until > 3600:
        conclusion = f"ARX 开盘预案已形成，距离 18:00 UTC+8 约 {hours.quantize(Decimal('0.01'))} 小时。"
        spot_action = "只做预案；低价买入条件必须等首块证据确认"
        perp_action = "不开仓；只记录偏空条件，等冲高、活动筹码外流和合约深度"
        direction = "观察"
        trade_signal = "等待开盘；只准备监控"
        attention = "价格锚点: 池子0.13、公募0.20、盘前0.30；首块买入>=20万U或bribe>=50BNB时放弃追价"
    elif seconds_until > 0:
        conclusion = "ARX 已进入开盘前 1 小时，按高竞争开盘处理。"
        spot_action = "只看首块执行；低bribe且买后持有才允许小仓试探"
        perp_action = "不开仓；开盘后若高价冲出且筹码进交易所，再等可交易合约和深度"
        direction = "观察；等首块证据"
        trade_signal = "等待开盘；低bribe且买后持有才允许观察试探"
        attention = "v4预加池不能同块绑定加池和买入，项目方若买也要竞争bribe；重点看首块买入金额、bribe和买后去向"
    else:
        conclusion = "ARX 已到开盘时间，等待链上首批 ARX 转账。"
        spot_action = "观察；不追没有成交证据的空窗口"
        perp_action = "不开仓；缺少成交和抛压路径"
        direction = "观察"
        trade_signal = "不买；等待真实成交"
        attention = "如果 10-30 分钟仍无首批转账，优先检查池子实际开放状态"
    return {
        "conclusion": conclusion,
        "spot_action": spot_action,
        "perp_action": perp_action,
        "direction": direction,
        "trade_signal": trade_signal,
        "attention": attention,
        "operator_behavior": "项目方已提前布好v4池子，实时判断点在首批成交和关键地址余额变化。",
        "sniper_behavior": "外部狙击证据等待开盘块确认；预案按20万U/40万U压力阈值和bribe阈值执行。",
        "sell_safety_status": "未验证；禁止发跟随信号",
        "can_sell_gate": "blocked_unverified",
        "total_spent_usdt": "",
        "weighted_avg_price": "",
        "max_bribe_bnb": "",
    }


def analyze_opening(seconds_until: int, opening_block: int, to_block: int, rows: list[dict[str, Any]]) -> dict[str, str]:
    buy_rows = meaningful_buy_rows(rows)
    bribes = [Decimal(str(row.get("largest_internal_bnb", {}).get("amount_bnb", "0") or "0")) for row in rows]
    max_bribe = max(bribes, default=Decimal(0))
    held = [row for row in buy_rows if row.get("buyer_trace", {}).get("status") == "held_or_accumulated"]
    moved = [row for row in buy_rows if row.get("buyer_trace", {}).get("status") in {"partially_moved", "mostly_exited_or_transferred", "mostly_exited_untraced"}]
    confirmed_sell_min = Decimal(os.environ.get("ARX_OPENING_CONFIRMED_SELL_MIN_USDT", "10000"))
    cohort = cohort_position_summary(buy_rows)
    cohort_status = cohort_position_text(cohort)
    safety = sell_safety_summary(buy_rows)
    confirmed_sell_usdt = Decimal(str(cohort.get("confirmed_sell_usdt") or "0"))
    total_arx = sum((Decimal(row["arx_bought"]) for row in buy_rows), Decimal(0))
    total_spent = sum((Decimal(row["spent_usdt"]) for row in buy_rows), Decimal(0))
    weighted_avg = total_spent / total_arx if total_arx else Decimal(0)
    first_big = next((row for row in buy_rows if Decimal(row["spent_usdt"]) >= Decimal("200000")), None)
    high_competition = total_spent >= Decimal("400000") or max_bribe >= Decimal("50")
    trace_summary = buyer_trace_summary(buy_rows)

    if not rows:
        conclusion = f"ARX 已定位开盘块 `{opening_block}`，扫描到 `{to_block}` 尚无 ARX Transfer。"
        spot_action = "观察；等真实成交"
        perp_action = "不开仓；没有价格和抛压证据"
        direction = "观察"
        trade_signal = "不买；没有真实成交"
        attention = "检查池子是否延迟开放、是否换池子、是否只在其他链成交"
        operator = "项目方尚未形成可见成交路径。"
        sniper = "没有前排买入证据。"
    elif confirmed_sell_usdt >= confirmed_sell_min:
        conclusion = f"ARX 首批买家累计确认换出约 `{format_amount(confirmed_sell_usdt)}` USDT，按卖出信号处理。"
        spot_action = "减仓/卖出；空仓不接"
        perp_action = "偏空条件；等交易所流入、价格破位和可交易合约深度"
        direction = "偏空"
        trade_signal = "卖出/减仓；首批买家累计确认换出"
        attention = "首批历史买入只代表开盘竞争，当前方向看首批去向和活动分发"
        operator = "已看到首批筹码换成 USDT，按真实派发处理。"
        sniper = "首批狙击资金已有确认卖出动作。"
    elif buy_rows and moved:
        sell_note = f"且小额确认换出约 `{format_amount(confirmed_sell_usdt)}` USDT，未达卖出阈值" if confirmed_sell_usdt > 0 else "尚未确认卖到市场"
        conclusion = f"ARX 首批买入 `{len(buy_rows)}` 笔，其中 `{len(moved)}` 笔买后转出或余额接近0，{sell_note}。"
        spot_action = "不追；已有仓位先降风险"
        perp_action = "只做观察；若价格冲高且外流扩大，再等可交易合约和深度"
        direction = "中性偏空"
        trade_signal = "不跟；首批买家已外转或余额接近0"
        attention = "重点看转出目的地是否交易所、桥、池子或新钱包"
        operator = "筹码稳定性不足，当前按外流风险处理。"
        sniper = "前排地址有迁移动作，外部狙击或套利概率上升；是否真实卖出要看下一跳。"
    elif first_big and high_competition:
        conclusion = (
            f"ARX 首块出现大额狙击：首笔约 `{format_amount(first_big.get('spent_usdt'))}` USDT，"
            f"均价 `{format_amount(first_big.get('avg_price_usdt_per_arx'))}`，最大 bribe `{format_amount(max_bribe)}` BNB。"
        )
        spot_action = "空仓不追；已有仓位按冲高分批止盈，等活动分发和回踩承接"
        perp_action = "偏空条件；等分发筹码进交易所、价格跌破承接位、合约深度够再执行"
        direction = "中性偏空；低价窗口已被首块竞争打掉"
        trade_signal = "不追；低价窗口已被抢走"
        attention = "低价窗口已被首块竞争打掉，后续重点看前排地址是否继续外流和活动分发领取"
        operator = "v4 预加池场景下项目方无法同块绑定加池和买入，项目方若参与也要和外部狙击竞争 bribe。"
        sniper = f"外部狙击强度高，首批历史买入合计约 `{format_amount(total_spent)}` USDT，综合均价约 `{format_amount(weighted_avg)}`。"
    elif buy_rows and len(held) >= max(1, len(buy_rows) // 2) and max_bribe < Decimal("1"):
        conclusion = f"ARX 首批买入 `{len(buy_rows)}` 笔，合计约 `{format_amount(total_arx)}` ARX，买后持有占优，bribe 低。"
        spot_action = "观察；DEX卖出/税费未完整验证前不发跟随试探"
        perp_action = "不开空；等冲高后再看外流和合约深度"
        direction = "观察偏多"
        trade_signal = "观察；可售性未完整验证，暂不跟随"
        attention = f"继续看首批地址是否转交易所、是否补池子、MM USDT 是否减少；{safety['status']}"
        operator = "首批成交后没有明显外流，项目方或强关联买入概率上升。"
        sniper = "外部高贿赂竞争暂不明显，前排买入更像低 bribe 顺序成交；只观察，不发跟随。"
    elif max_bribe >= Decimal("1"):
        conclusion = f"ARX 首批交易出现较大内部 BNB 转账，最大约 `{format_amount(max_bribe)}` BNB。"
        spot_action = "不追；先确认 bribe 交易是否成功和买入后去向"
        perp_action = "不开仓；等价格结构确认"
        direction = "观察偏空"
        trade_signal = "不追；先确认bribe交易和买后去向"
        attention = "高 bribe 代表竞争强，注意首块成交价可能偏离池子价"
        operator = "项目方行为需要结合买入地址资金源判断。"
        sniper = "外部狙击竞争证据增强。"
    else:
        conclusion = f"ARX 已有首批相关交易 `{len(rows)}` 笔，买入证据不足。"
        spot_action = "观察；补看价格、路由和 holder 变化"
        perp_action = "不开仓；证据不够"
        direction = "观察"
        trade_signal = "不买；有效买入证据不足"
        attention = "需要继续解码 calldata 和池子真实价格"
        operator = "项目方是否下场仍未定性。"
        sniper = "当前只能确认有链上动作，前排狙击强度不明。"

    return {
        "conclusion": conclusion,
        "spot_action": spot_action,
        "perp_action": perp_action,
        "direction": direction,
        "trade_signal": trade_signal,
        "attention": attention,
        "operator_behavior": operator,
        "sniper_behavior": sniper,
        "sell_safety_status": safety["status"],
        "can_sell_gate": safety["gate"],
        "sell_safety_detail": safety["detail"],
        "total_spent_usdt": decimal_str(total_spent),
        "weighted_avg_price": decimal_str(weighted_avg) if weighted_avg else "",
        "max_bribe_bnb": decimal_str(max_bribe),
        "buyer_trace_summary": trace_summary,
        "cohort_status_summary": cohort_status,
        "current_cohort_arx": decimal_str(Decimal(str(cohort.get("current_arx") or "0"))),
        "current_cohort_usdt_est": decimal_str(Decimal(str(cohort.get("current_usdt_est") or "0"))),
        "cohort_net_out_pct": decimal_str(Decimal(str(cohort.get("net_out_pct") or "0"))),
        "cohort_confirmed_sell_usdt": decimal_str(confirmed_sell_usdt),
        "as_of_block": trace_as_of_block(buy_rows),
    }


def buyer_trace_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无有效首批买入"
    traced = [row for row in rows if row.get("buyer_trace")]
    if not traced:
        return "首批买家去向未追踪，下一轮补"
    as_of = trace_as_of_block(traced)
    suffix = f"；截至区块{as_of}" if as_of else ""
    confirmed_sell_min = Decimal(os.environ.get("ARX_OPENING_CONFIRMED_SELL_MIN_USDT", "10000"))
    cohort = cohort_position_summary(rows)
    sold_usdt = Decimal(str(cohort.get("confirmed_sell_usdt") or "0"))
    if sold_usdt >= confirmed_sell_min:
        return f"已追踪{len(traced)}个首批买家，累计已确认DEX换出约{format_amount(sold_usdt)} USDT{suffix}"
    small_sell_text = f"；小额确认换出约{format_amount(sold_usdt)} USDT，未达卖出阈值" if sold_usdt > 0 else "；未确认是否卖到市场"
    moved = [row for row in traced if row.get("buyer_trace", {}).get("status") in {"partially_moved", "mostly_exited_or_transferred", "mostly_exited_untraced"}]
    exited = [row for row in traced if row.get("buyer_trace", {}).get("status") in {"mostly_exited_or_transferred", "mostly_exited_untraced"}]
    untraced_exited = [row for row in traced if row.get("buyer_trace", {}).get("status") == "mostly_exited_untraced"]
    held = [row for row in traced if row.get("buyer_trace", {}).get("status") == "held_or_accumulated"]
    failed = [row for row in traced if row.get("buyer_trace", {}).get("status") == "trace_failed"]
    classes = trace_destination_classes(traced)
    class_text = f"，去向={classes}" if classes else ""
    if exited:
        if untraced_exited and len(untraced_exited) == len(exited):
            return f"已追踪{len(traced)}个首批买家，{len(untraced_exited)}个原买入钱包余额接近0，转出不在当前扫描窗口{small_sell_text}{suffix}"
        return f"已追踪{len(traced)}个首批买家，{len(exited)}个原买入钱包已清仓转出{class_text}{small_sell_text}{suffix}"
    if moved:
        return f"已追踪{len(traced)}个首批买家，{len(moved)}个已外转{class_text}{small_sell_text}{suffix}"
    if failed and len(failed) == len(traced):
        return f"首批买家追踪失败{len(failed)}个，下一轮重试"
    return f"已追踪{len(traced)}个首批买家，暂未发现转出；{len(held)}个仍持有或增持{suffix}"


def decimal_value(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


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


def render(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    lines = [
        "# ARX Opening Block Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- status: `{snapshot['status']}`",
        f"- start_time_utc8: `{snapshot['launch_event'].get('start_time_utc8')}`",
        f"- seconds_until_start: `{snapshot.get('seconds_until_start')}`",
        f"- opening_block: `{snapshot.get('opening_block')}`",
        f"- latest_block: `{snapshot.get('latest_block')}`",
        f"- scan_to_block: `{snapshot.get('scan_to_block')}`",
        f"- relevant_tx_count: `{snapshot.get('relevant_tx_count', 0)}`",
        "",
        "## Action",
        "",
        f"- conclusion: {analysis['conclusion']}",
        f"- direction: {analysis.get('direction', '')}",
        f"- trade_signal: {analysis.get('trade_signal', '')}",
        f"- spot_action: {analysis['spot_action']}",
        f"- perp_action: {analysis['perp_action']}",
        f"- attention: {analysis['attention']}",
        f"- operator_behavior: {analysis['operator_behavior']}",
        f"- sniper_behavior: {analysis['sniper_behavior']}",
        f"- sell_safety_status: {analysis.get('sell_safety_status', '')}",
        f"- can_sell_gate: `{analysis.get('can_sell_gate', '')}`",
        f"- cohort_status_summary: {analysis.get('cohort_status_summary', '')}",
        f"- buyer_trace_summary: {analysis.get('buyer_trace_summary', '')}",
        f"- as_of_block: `{analysis.get('as_of_block', '')}`",
        f"- total_spent_usdt: `{analysis.get('total_spent_usdt', '')}`",
        f"- weighted_avg_price: `{analysis.get('weighted_avg_price', '')}`",
        f"- max_bribe_bnb: `{analysis.get('max_bribe_bnb', '')}`",
        f"- current_cohort_arx: `{analysis.get('current_cohort_arx', '')}`",
        f"- current_cohort_usdt_est: `{analysis.get('current_cohort_usdt_est', '')}`",
        f"- cohort_net_out_pct: `{analysis.get('cohort_net_out_pct', '')}`",
        f"- cohort_confirmed_sell_usdt: `{analysis.get('cohort_confirmed_sell_usdt', '')}`",
        "",
        "## Price Anchors",
        "",
        f"- pool_init_price: `{PRICE_ANCHORS['pool_init_price']}` USDT/ARX",
        f"- CoinList public sale: `{PRICE_ANCHORS['coinlist_public_sale_price']}` USDT/ARX",
        f"- premarket reference: `{PRICE_ANCHORS['premarket_reference_price']}` USDT/ARX",
        f"- 200k snipe stress: `{PRICE_ANCHORS['snipe_200k_reaches']}` USDT/ARX",
        f"- 400k snipe stress: `{PRICE_ANCHORS['snipe_400k_reaches']}` USDT/ARX",
        "",
    ]
    rows = meaningful_buy_rows(snapshot.get("rows", []))
    if rows:
        lines.extend(
            [
                "## First ARX Transactions",
                "",
                "| block | txIndex | status | buyer | ARX bought | USDT spent | avg price | bribe BNB | trace | tx |",
                "| ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for row in rows[:25]:
            trace = row.get("buyer_trace", {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("block", "")),
                        str(row.get("tx_index", "")),
                        str(row.get("status", "")),
                        short_addr(row.get("buyer", "")),
                        format_amount(row.get("arx_bought", "")),
                        format_amount(row.get("spent_usdt", "")),
                        format_amount(row.get("avg_price_usdt_per_arx", "")),
                        format_amount(row.get("largest_internal_bnb", {}).get("amount_bnb", "0")),
                        f"{trace.get('status', '')}/{trace.get('out_destination_classes', '')}",
                        short_addr(row.get("tx", "")),
                    ]
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def alert_keys(snapshot: dict[str, Any]) -> list[str]:
    keys = []
    seconds_until = int(snapshot.get("seconds_until_start") or 0)
    if 0 < seconds_until <= 6 * 3600:
        keys.append("|".join(["prelaunch", "ARX", launch_stage(seconds_until), snapshot["launch_event"].get("start_time_utc8", "")]))
    if snapshot.get("status") == "opened":
        analysis = snapshot.get("analysis", {})
        if analysis.get("trade_signal"):
            keys.append("|".join(["trade_signal", "ARX", str(snapshot.get("opening_block", "")), analysis.get("trade_signal", ""), analysis.get("direction", "")]))
        for row in snapshot.get("rows", [])[:10]:
            if Decimal(str(row.get("arx_bought", "0") or "0")) >= min_meaningful_arx_buy():
                keys.append("|".join(["buy", row.get("tx", ""), row.get("buyer", ""), row.get("arx_bought", "")]))
        trace_keys = buyer_trace_alert_keys(meaningful_buy_rows(snapshot.get("rows", []))[:5])
        keys.extend(trace_keys)
        if not snapshot.get("rows") and seconds_until < -1800:
            keys.append("no-arx-transfer-after-open|" + str(snapshot.get("opening_block")))
    return sorted(set(keys))


def buyer_trace_alert_keys(rows: list[dict[str, Any]]) -> list[str]:
    keys = []
    for row in rows:
        trace = row.get("buyer_trace") or {}
        if not trace:
            continue
        status = str(trace.get("status") or "unknown")
        classes = trace.get("out_destination_classes", "")
        sell_bucket = alert_amount_bucket(
            decimal_value(trace.get("confirmed_sell_usdt_received")) + decimal_value(trace.get("next_hop_sell_usdt_received")),
            Decimal(os.environ.get("ARX_OPENING_ALERT_USDT_BUCKET", "10000")),
        )
        keys.append("|".join(["buyer_trace", row.get("buyer", ""), status, classes, sell_bucket]))
    return keys


def alert_amount_bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    if step <= 0:
        step = Decimal("10000")
    return decimal_str((value // step) * step)


def alert_key_seen(key: str, seen: set[str]) -> bool:
    if key in seen:
        return True
    parts = key.split("|")
    if len(parts) >= 3 and parts[0] == "buyer_trace":
        stable_key = "|".join(parts[:4]) if len(parts) >= 4 else "|".join(parts[:3])
        return any(old == stable_key or old.startswith(stable_key + "|") for old in seen)
    return False


def telegram_text(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    lines = [
        "ARX 开盘块监控",
        f"有效总结: {opening_effective_summary(snapshot)}",
        f"方向判断: {analysis.get('direction') or opening_direction(snapshot)}",
        f"动作信号: {analysis.get('trade_signal', '')}",
        f"结论: {analysis['conclusion']}",
        f"现货动作: {analysis['spot_action']}",
        f"合约动作: {analysis['perp_action']}",
        f"可售性: {analysis.get('sell_safety_status', '')}",
        f"注意: {analysis['attention']}",
        f"庄家行为: {analysis['operator_behavior']}",
        f"狙击手行为: {analysis['sniper_behavior']}",
        f"仓位口径: {analysis.get('cohort_status_summary', '')}",
        f"买后去向: {analysis.get('buyer_trace_summary', '')}",
    ]
    if snapshot.get("status") == "opened":
        lines.append(
            f"首批历史买入: 截至区块{analysis.get('as_of_block', snapshot.get('latest_block', ''))}，{format_amount(analysis.get('total_spent_usdt'))} USDT，均价 {format_price(analysis.get('weighted_avg_price'))}，最大bribe {format_amount(analysis.get('max_bribe_bnb'))} BNB"
        )
    rows = meaningful_buy_rows(snapshot.get("rows", []))
    if rows:
        first = rows[0]
        lines.append("")
        lines.append(
            "核心证据: "
            f"首笔约{format_amount(first.get('spent_usdt'))} USDT，"
            f"均价{format_price(first.get('avg_price_usdt_per_arx'))}，"
            f"bribe {format_amount(first.get('largest_internal_bnb', {}).get('amount_bnb', '0'))} BNB；"
            f"有意义买入{len(rows)}笔"
        )
        lines.append("细节: 地址、tx、区块已归档，需要时再查")
    return "\n".join(lines)


def opening_effective_summary(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    signal = analysis.get("trade_signal") or analysis["spot_action"]
    if snapshot.get("status") != "opened":
        return f"{signal}；{analysis['spot_action']}；{analysis['perp_action']}"
    trace = analysis.get("buyer_trace_summary", "")
    spent = format_amount(analysis.get("total_spent_usdt"))
    bribe = format_amount(analysis.get("max_bribe_bnb"))
    return f"{signal}；{analysis['spot_action']}；{analysis.get('cohort_status_summary', '')}；最大bribe {bribe} BNB；{trace}"


def opening_direction(snapshot: dict[str, Any]) -> str:
    analysis = snapshot["analysis"]
    if analysis.get("direction"):
        return analysis["direction"]
    trace = analysis.get("buyer_trace_summary", "")
    if "清仓转出" in trace or "已外转" in trace:
        return "偏空；现货不追，合约只等交易所流入/价格破位/深度足够再执行"
    if "暂未发现转出" in trace:
        return "中性偏多；首批暂未跑，继续看承接和分发筹码"
    if snapshot.get("status") == "opened" and Decimal(str(analysis.get("max_bribe_bnb") or "0")) >= Decimal("50"):
        return "中性偏空；开盘竞争强，低价窗口已消失"
    return "观察；等待首批买家去向和活动筹码路径"


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ARX_OPENING_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    keys = alert_keys(snapshot)
    if not keys:
        return
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if not alert_key_seen(key, seen)]
    if not new_keys and os.environ.get("ARX_OPENING_FORCE_TELEGRAM") != "1":
        if any(key not in seen for key in keys):
            write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ARX_OPENING_FORCE_TELEGRAM") != "1":
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
    record_push(snapshot)


def push_signature(snapshot: dict[str, Any]) -> str:
    analysis = snapshot.get("analysis", {})
    return "|".join(
        [
            str(snapshot.get("opening_block", "")),
            str(analysis.get("trade_signal", "")),
            str(analysis.get("direction", "")),
            str(analysis.get("buyer_trace_summary", "")),
            str(analysis.get("cohort_status_summary", "")),
            str(analysis.get("can_sell_gate", "")),
        ]
    )


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ARX_OPENING_REPEAT_SUPPRESS_MINUTES", "30"))
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


def wei_to_gwei(value: str | None) -> str:
    raw = hex_to_int(value)
    if raw is None:
        return ""
    return format((Decimal(raw) / Decimal(10**9)).normalize(), "f")


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
    return "6h"


def min_meaningful_arx_buy() -> Decimal:
    return Decimal(os.environ.get("ARX_OPENING_MIN_MEANINGFUL_ARX_BUY", DEFAULT_MIN_MEANINGFUL_ARX_BUY))


def min_meaningful_usdt_spent() -> Decimal:
    return Decimal(os.environ.get("ARX_OPENING_MIN_MEANINGFUL_USDT_SPENT", DEFAULT_MIN_MEANINGFUL_USDT_SPENT))


def min_meaningful_bribe_bnb() -> Decimal:
    return Decimal(os.environ.get("ARX_OPENING_MIN_MEANINGFUL_BRIBE_BNB", DEFAULT_MIN_MEANINGFUL_BRIBE_BNB))


def meaningful_buy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    arx_threshold = min_meaningful_arx_buy()
    spent_threshold = min_meaningful_usdt_spent()
    bribe_threshold = min_meaningful_bribe_bnb()
    out = []
    for row in rows:
        try:
            amount = Decimal(str(row.get("arx_bought", "0") or "0"))
            spent = Decimal(str(row.get("spent_usdt", "0") or "0"))
            bribe = Decimal(str(row.get("largest_internal_bnb", {}).get("amount_bnb", "0") or "0"))
        except Exception:
            continue
        if amount >= arx_threshold and (spent >= spent_threshold or bribe >= bribe_threshold):
            out.append(row)
    return out


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
    print(snapshot["analysis"]["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
