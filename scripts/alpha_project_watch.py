#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import RpcDeadlineExceeded, rpc_call
from sniper_engine.telegram_send_receipt import read_telegram_send_receipt, record_telegram_send_receipt


getcontext().prec = 80

CONFIG_PATH = Path(
    os.environ.get("ALPHA_WATCHLIST_PATH", ROOT / "config" / "current_alpha_watchlist.json")
)
OUT_DIR = ROOT / "output" / "alpha_project_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
PROGRESS_PATH = OUT_DIR / "progress.json"
PENDING_PATH = OUT_DIR / "pending.json"
PENDING_REPORT_PATH = OUT_DIR / "pending.md"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x0000000000000000000000000000000000000000"
OWNER_SELECTORS = ("0x8da5cb5b", "0x893d20e8")
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
PROGRESS_SCHEMA_VERSION = 2
PROJECT_PROVIDER_ROW_LIMIT_HARD_CAP = 128
PROJECT_RUNTIME_BUDGET_SECONDS = 90
PROJECT_DEADLINE_AT: float | None = None


def project_rpc_call(
    chain: str,
    method: str,
    params: list[Any],
) -> Any:
    if PROJECT_DEADLINE_AT is None:
        return rpc_call(chain, method, params)
    return rpc_call(
        chain,
        method,
        params,
        deadline=PROJECT_DEADLINE_AT,
    )


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
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


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
    raw = project_rpc_call(
        chain,
        "eth_call",
        [{"to": contract, "data": data}, "latest"],
    )
    if (
        not isinstance(raw, str)
        or not raw.startswith("0x")
        or len(raw) <= 2
    ):
        raise RuntimeError("token uint RPC result unavailable")
    return int(raw, 16)


def decode_address_return(value: Any) -> str:
    state, address = decode_address_return_state(value)
    return address if state == "address" else ""


def decode_address_return_state(value: Any) -> tuple[str, str]:
    text = norm(str(value or ""))
    raw = text[2:] if text.startswith("0x") else text
    if len(raw) < 64:
        return "invalid", ""
    candidate = "0x" + raw[-40:]
    if not is_address(candidate):
        return "invalid", ""
    if candidate == ZERO:
        return "zero", ""
    return "address", candidate


def token_controller(chain: str, contract: str) -> dict[str, str]:
    owners: set[str] = set()
    successful_selectors = 0
    zero_selectors = 0
    failed_selectors = 0
    for selector in OWNER_SELECTORS:
        try:
            raw = project_rpc_call(
                chain,
                "eth_call",
                [{"to": contract, "data": selector}, "latest"],
            )
        except RpcDeadlineExceeded:
            raise
        except Exception:
            failed_selectors += 1
            continue
        state, owner = decode_address_return_state(raw)
        if state == "address":
            successful_selectors += 1
            owners.add(owner)
        elif state == "zero":
            successful_selectors += 1
            zero_selectors += 1
    if len(owners) > 1 or (owners and zero_selectors):
        return {
            "state": "conflicting_owner_selectors",
            "identity_status": "unattributed",
        }
    if len(owners) == 1:
        return {
            "state": "verified_token_controller",
            "address": next(iter(owners)),
            "label": "token owner() controller",
            "role": "token_controller",
            "control_scope": "token",
            "identity_status": "verified",
            "attribution": "canonical_owner_call",
            "selector_count": str(successful_selectors),
        }
    if zero_selectors and not failed_selectors:
        return {
            "state": "owner_renounced",
            "control_scope": "token",
            "identity_status": "verified_no_controller",
            "attribution": "canonical_owner_call",
            "selector_count": str(successful_selectors),
        }
    if failed_selectors:
        raise RuntimeError("token controller RPC unavailable")
    return {
        "state": "owner_unresolved",
        "identity_status": "unattributed",
    }


def token_decimals(chain: str, contract: str) -> int:
    value = call_uint(chain, contract, encode_uint_call("0x313ce567"))
    if not 0 <= value <= 36:
        raise RuntimeError("token decimals unavailable")
    return value


def token_total_supply(chain: str, contract: str, decimals: int) -> str:
    return str(
        decimal_amount(
            call_uint(chain, contract, encode_uint_call("0x18160ddd")),
            decimals,
        )
    )


def token_balance(chain: str, contract: str, address: str, decimals: int) -> Decimal:
    return decimal_amount(call_uint(chain, contract, encode_balance_of(address)), decimals)


def latest_block(chain: str) -> int:
    return int(project_rpc_call(chain, "eth_blockNumber", []), 16)


def canonical_block_hash(chain: str, block: int) -> str:
    payload = project_rpc_call(
        chain,
        "eth_getBlockByNumber",
        [hex(block), False],
    )
    block_hash = (
        normalized_hex_bytes(payload.get("hash"), 32, allow_zero=False)
        if isinstance(payload, dict)
        else ""
    )
    if not block_hash:
        raise RuntimeError("project checkpoint block hash unavailable")
    return block_hash


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


def normalized_hex_bytes(
    value: Any,
    byte_length: int,
    *,
    allow_zero: bool = True,
) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    if len(text) != 2 + (byte_length * 2) or not text.startswith("0x"):
        return ""
    if any(character not in "0123456789abcdef" for character in text[2:]):
        return ""
    if not allow_zero and int(text[2:], 16) == 0:
        return ""
    return text


def normalized_hex_quantity(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    if not text.startswith("0x") or not text[2:]:
        return ""
    if any(character not in "0123456789abcdef" for character in text[2:]):
        return ""
    try:
        return hex(int(text, 16))
    except ValueError:
        return ""


def normalized_transfer_log(
    row: dict[str, Any],
    token_contract: str,
) -> dict[str, Any] | None:
    transaction_hash = normalized_hex_bytes(
        row.get("transactionHash"),
        32,
        allow_zero=False,
    )
    block_hash = normalized_hex_bytes(
        row.get("blockHash"),
        32,
        allow_zero=False,
    )
    block = normalized_hex_quantity(row.get("blockNumber"))
    transaction_index = normalized_hex_quantity(row.get("transactionIndex"))
    index = normalized_hex_quantity(row.get("logIndex"))
    address = norm(str(row.get("address") or ""))
    topics = row.get("topics")
    data = normalized_hex_bytes(row.get("data"), 32)
    if (
        not transaction_hash
        or not block_hash
        or not block
        or not transaction_index
        or not index
        or address != norm(token_contract)
        or row.get("removed") is not False
        or not isinstance(topics, list)
        or len(topics) != 3
        or not data
    ):
        return None
    normalized_topics = [
        normalized_hex_bytes(topic, 32) for topic in topics
    ]
    if not all(normalized_topics) or normalized_topics[0] != TRANSFER_TOPIC:
        return None
    return {
        **row,
        "address": address,
        "blockHash": block_hash,
        "blockNumber": block,
        "data": data,
        "logIndex": index,
        "removed": False,
        "topics": normalized_topics,
        "transactionHash": transaction_hash,
        "transactionIndex": transaction_index,
    }


def transfer_log_matches_query(
    row: dict[str, Any],
    topic_filter: list[Any],
    selected_start: int,
    selected_end: int,
) -> bool:
    block = int(row["blockNumber"], 16)
    if block < selected_start or block > selected_end:
        return False
    topics = row["topics"]
    for topic_index in (1, 2):
        expected = topic_filter[topic_index]
        if expected is None:
            continue
        if not isinstance(expected, list) or topics[topic_index] not in expected:
            return False
    return True


def get_transfer_logs(
    chain: str,
    token_contract: str,
    watched_addresses: list[str],
    from_block: int,
    to_block: int,
    *,
    resume_from_block: int | None = None,
    on_chunk_complete: Any = None,
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
    configured_row_limit = max(
        1,
        int(
            os.environ.get(
                "ALPHA_PROJECT_PROVIDER_MAX_ROWS_PER_QUERY",
                str(PROJECT_PROVIDER_ROW_LIMIT_HARD_CAP),
            )
        ),
    )
    provider_row_limit = min(
        configured_row_limit,
        PROJECT_PROVIDER_ROW_LIMIT_HARD_CAP,
    )
    selected_from = max(from_block, int(resume_from_block or from_block))
    for start in range(selected_from, to_block + 1, chunk_size):
        end = min(to_block, start + chunk_size - 1)
        for topic_filter in queries:
            pending = [(start, end)]
            while pending:
                selected_start, selected_end = pending.pop(0)
                query = {
                    "address": token_contract,
                    "fromBlock": hex(selected_start),
                    "toBlock": hex(selected_end),
                    "topics": topic_filter,
                }
                try:
                    result = project_rpc_call(
                        chain,
                        "eth_getLogs",
                        [query],
                    )
                except RpcDeadlineExceeded:
                    raise
                except Exception:
                    errors.append(
                        "eth_getLogs coverage failed for "
                        f"{selected_start}-{selected_end}"
                    )
                    return [], errors
                if not isinstance(result, list) or any(
                    not isinstance(row, dict) for row in result
                ):
                    errors.append(
                        "eth_getLogs coverage failed for "
                        f"{selected_start}-{selected_end}"
                    )
                    return [], errors
                if len(result) >= provider_row_limit:
                    if selected_start >= selected_end:
                        errors.append(
                            "eth_getLogs coverage truncated for "
                            f"{selected_start}-{selected_end}"
                        )
                        return [], errors
                    midpoint = (selected_start + selected_end) // 2
                    pending[0:0] = [
                        (selected_start, midpoint),
                        (midpoint + 1, selected_end),
                    ]
                    continue
                for row in result:
                    normalized_row = normalized_transfer_log(
                        row,
                        token_contract,
                    )
                    if normalized_row is None:
                        errors.append(
                            "eth_getLogs malformed identity for "
                            f"{selected_start}-{selected_end}"
                        )
                        return [], errors
                    if not transfer_log_matches_query(
                        normalized_row,
                        topic_filter,
                        selected_start,
                        selected_end,
                    ):
                        errors.append(
                            "eth_getLogs result outside query for "
                            f"{selected_start}-{selected_end}"
                        )
                        return [], errors
                    key = (
                        normalized_row["transactionHash"],
                        normalized_row["logIndex"],
                    )
                    existing = rows.get(key)
                    if existing is not None and existing != normalized_row:
                        errors.append(
                            "eth_getLogs conflicting duplicate for "
                            f"{selected_start}-{selected_end}"
                        )
                        return [], errors
                    rows[key] = normalized_row
        if on_chunk_complete is not None:
            on_chunk_complete(
                start,
                end,
                sorted(
                    rows.values(),
                    key=lambda row: (block_number(row), log_index(row)),
                ),
            )
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


def previous_contract_hashes(
    payload: dict[str, Any],
) -> dict[tuple[str, str, str], str]:
    out: dict[tuple[str, str, str], str] = {}
    for project in payload.get("projects", []):
        symbol = str(project.get("symbol", "")).upper()
        for contract in project.get("contracts", []):
            if not complete_contract_payload(contract):
                continue
            block_hash = normalized_hex_bytes(
                contract.get("target_latest_block_hash"),
                32,
                allow_zero=False,
            )
            if not block_hash:
                continue
            key = (
                symbol,
                contract.get("chain", ""),
                norm(contract.get("address")),
            )
            out[key] = block_hash
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


def configured_control_scope(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in {"pool", "pool_manager", "v4_pool_manager", "lp_position_manager"}:
        return "pool"
    if normalized.startswith("pool_"):
        return "pool"
    if normalized in {"event_distribution", "airdrop_distribution", "distribution"}:
        return "distribution"
    if normalized == "token_controller":
        return "token"
    return "unknown"


def extract_watch_addresses(item: dict[str, Any], chain: str) -> list[dict[str, Any]]:
    rows = []
    for row in item.get("watch_addresses", []):
        row_chain = str(row.get("chain", chain)).lower()
        address = norm(row.get("address"))
        if row_chain != chain or not is_address(address):
            continue
        role = str(row.get("role", ""))
        control_scope = str(row.get("control_scope") or configured_control_scope(role))
        identity_status = str(row.get("identity_status") or "")
        if not identity_status:
            identity_status = (
                "functional_only"
                if control_scope in {"pool", "distribution"}
                else "candidate"
            )
        rows.append(
            {
                "chain": row_chain,
                "address": address,
                "label": row.get("label") or short_addr(address),
                "role": role,
                "level": row.get("level", "HIGH"),
                "watch_quote": bool(row.get("watch_quote", False)),
                "watch_quote_tokens": row.get("watch_quote_tokens", []),
                "control_scope": control_scope,
                "identity_status": identity_status,
                "attribution": row.get("attribution", "configured_watch_address"),
            }
        )
    return rows


def effective_watch_addresses(
    item: dict[str, Any],
    chain: str,
    token: str,
) -> tuple[list[dict[str, Any]], str]:
    rows = extract_watch_addresses(item, chain)
    state = "configured" if rows else "unresolved"
    if str(item.get("project_operator_probe") or "").lower() != "owner":
        return rows, state
    controller = token_controller(chain, token)
    address = norm(controller.get("address"))
    if address:
        matching = next(
            (row for row in rows if norm(row.get("address")) == address),
            None,
        )
        if matching is None:
            rows.append(
                {
                    "chain": chain,
                    "address": address,
                    "label": controller.get("label", "token controller"),
                    "role": controller.get("role", "token_controller"),
                    "level": "HIGH",
                    "watch_quote": True,
                    "watch_quote_tokens": ["USDT"],
                    "control_scope": controller.get("control_scope", "token"),
                    "identity_status": controller.get("identity_status", "verified"),
                    "attribution": controller.get("attribution", "canonical_owner_call"),
                }
            )
        else:
            matching["control_scope"] = controller.get("control_scope", "token")
            matching["identity_status"] = controller.get("identity_status", "verified")
            matching["attribution"] = controller.get("attribution", "canonical_owner_call")
        state = str(controller.get("state") or "verified_token_controller")
    else:
        state = str(controller.get("state") or "owner_unresolved")
    return rows, state


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
            receipt = project_rpc_call(
                chain,
                "eth_getTransactionReceipt",
                [tx_hash],
            )
        except RpcDeadlineExceeded:
            raise
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


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_item_scan_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Return only fields that can change project scan results."""
    watch_addresses = []
    for row in item.get("watch_addresses", []):
        if not isinstance(row, dict):
            continue
        watch_addresses.append(
            {
                key: row.get(key)
                for key in (
                    "chain",
                    "address",
                    "label",
                    "role",
                    "level",
                    "watch_quote",
                    "watch_quote_tokens",
                    "control_scope",
                    "identity_status",
                    "attribution",
                )
                if key in row
            }
        )
    known_txs = []
    for row in item.get("known_txs", []):
        if not isinstance(row, dict):
            continue
        known_txs.append(
            {
                key: row.get(key)
                for key in ("chain", "tx", "reason")
                if key in row
            }
        )
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    return {
        "symbol": str(item.get("symbol") or "").upper(),
        "name": item.get("name", ""),
        "priority": item.get("priority", ""),
        "active_monitoring": item.get("active_monitoring", True),
        "project_watch_skip_generic": bool(
            item.get("project_watch_skip_generic")
        ),
        "project_lookback_blocks": item.get("project_lookback_blocks"),
        "project_operator_probe": item.get("project_operator_probe", ""),
        "contracts": extract_contracts(item),
        "watch_addresses": watch_addresses,
        "known_txs": known_txs,
        "pool_ids": item.get("pool_ids", []),
        "alpha_id": facts.get("alpha_id"),
        "market_context": item.get("market_context", {}),
        "event_distributions": item.get("event_distributions", []),
        "required_checks": item.get("required_checks", []),
    }


def project_item_fingerprint(item: dict[str, Any]) -> str:
    return stable_hash(project_item_scan_payload(item))


def contract_checkpoint_key(contract: dict[str, Any]) -> str:
    return f"{str(contract.get('chain') or '').lower()}:{norm(contract.get('address'))}"


def project_scan_fingerprint(
    items: list[dict[str, Any]],
    previous: dict[str, Any],
    finality: int,
    lookback: int,
) -> str:
    previous_tips = [
        [symbol, chain, address, tip]
        for (symbol, chain, address), tip in sorted(
            previous_contract_tips(previous).items()
        )
    ]
    previous_balance_rows = [
        [symbol, chain, token, address, str(balance)]
        for (symbol, chain, token, address), balance in sorted(
            previous_balances(previous).items()
        )
    ]
    previous_hash_rows = [
        [symbol, chain, address, block_hash]
        for (symbol, chain, address), block_hash in sorted(
            previous_contract_hashes(previous).items()
        )
    ]
    return stable_hash(
        {
            "items": [project_item_scan_payload(item) for item in items],
            "previous_contract_tips": previous_tips,
            "previous_contract_hashes": previous_hash_rows,
            "previous_balances": previous_balance_rows,
            "finality": finality,
            "lookback": lookback,
        }
    )


def contract_scan_scope_fingerprint(
    symbol: str,
    contract: dict[str, Any],
    watch_addresses: list[dict[str, Any]],
    finality: int,
    lookback: int,
    decimals: int,
) -> str:
    return stable_hash(
        {
            "symbol": symbol,
            "contract": {
                "chain": str(contract.get("chain") or "").lower(),
                "address": norm(contract.get("address")),
            },
            "watch_addresses": sorted(
                watch_addresses,
                key=lambda row: (
                    str(row.get("chain") or ""),
                    norm(row.get("address")),
                ),
            ),
            "finality": finality,
            "lookback": lookback,
            "decimals": decimals,
            "min_transfer_alert": str(
                env_decimal(
                    "ALPHA_PROJECT_MIN_TRANSFER_ALERT",
                    "100000",
                )
            ),
        }
    )


def validated_contract_progress(
    payload: Any,
    *,
    contract_key: str,
    scope_fingerprint: str,
    previous_tip: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if (
        payload.get("contract_key") != contract_key
        or payload.get("scope_fingerprint") != scope_fingerprint
    ):
        return {}
    try:
        raw_tip = int(payload["raw_latest_block"])
        target_tip = int(payload["target_latest_block"])
        requested_from = int(payload["requested_from_block"])
        next_from = int(payload["next_from_block"])
        covered_through = int(payload["covered_through_block"])
        stored_previous = int(payload.get("previous_latest_block") or 0)
    except (KeyError, TypeError, ValueError):
        return {}
    target_hash = normalized_hex_bytes(
        payload.get("target_latest_block_hash"),
        32,
        allow_zero=False,
    )
    if (
        stored_previous != previous_tip
        or raw_tip < target_tip
        or target_tip < 0
        or not 0 <= requested_from <= target_tip + 1
        or not requested_from <= next_from <= target_tip + 1
        or covered_through != next_from - 1
        or not target_hash
    ):
        return {}
    normalized_transfer_lists: dict[str, list[dict[str, Any]]] = {}
    for field, max_rows in (
        ("recent_transfers", 40),
        ("pending_transfer_candidates", None),
    ):
        transfers = payload.get(field)
        if (
            not isinstance(transfers, list)
            or (max_rows is not None and len(transfers) > max_rows)
        ):
            return {}
        normalized_transfers: list[dict[str, Any]] = []
        for row in transfers:
            if not isinstance(row, dict):
                return {}
            try:
                block = int(row.get("block"))
                index = int(row.get("log_index"))
                Decimal(str(row.get("amount")))
            except (InvalidOperation, TypeError, ValueError):
                return {}
            if (
                block < requested_from
                or block > covered_through
                or index < 0
                or not normalized_hex_bytes(
                    row.get("tx"),
                    32,
                    allow_zero=False,
                )
                or not is_address(row.get("from"))
                or not is_address(row.get("to"))
            ):
                return {}
            normalized_transfers.append(dict(row))
        normalized_transfer_lists[field] = normalized_transfers
    return {
        **payload,
        "raw_latest_block": raw_tip,
        "target_latest_block": target_tip,
        "requested_from_block": requested_from,
        "next_from_block": next_from,
        "covered_through_block": covered_through,
        "previous_latest_block": stored_previous,
        "target_latest_block_hash": target_hash,
        **normalized_transfer_lists,
    }


def complete_contract_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("coverage_complete") is not True
        or payload.get("transfer_coverage_complete") is not True
        or payload.get("scan_status") != "complete"
        or payload.get("error")
        or int(payload.get("log_error_count") or 0) != 0
    ):
        return False
    try:
        requested = int(payload["requested_from_block"])
        target = int(payload["target_latest_block"])
        covered = int(payload["covered_through_block"])
        next_from = int(payload["next_from_block"])
        latest = int(payload["latest_block"])
        decimals = int(payload["decimals"])
        watch_address_count = int(payload["watch_address_count"])
        balance_target_count = int(payload["balance_target_count"])
        total_supply = Decimal(str(payload["total_supply"]))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False
    watch_addresses = payload.get("watch_addresses")
    balances = payload.get("balances")
    if not isinstance(balances, list):
        return False
    for balance in balances:
        if not isinstance(balance, dict) or balance.get("error"):
            return False
        try:
            current_balance = Decimal(str(balance["balance"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return False
        if current_balance < 0 or not is_address(balance.get("address")):
            return False
    expected_balance_keys = expected_balance_identities(
        str(payload.get("chain") or "").lower(),
        norm(payload.get("address")),
        watch_addresses if isinstance(watch_addresses, list) else [],
    )
    actual_balance_keys = {
        (
            norm(balance.get("address")),
            norm(balance.get("balance_token_address")),
        )
        for balance in balances
    }
    return bool(
        requested >= 0
        and requested <= target + 1
        and covered == target
        and latest == target
        and next_from == target + 1
        and 0 <= decimals <= 36
        and total_supply >= 0
        and isinstance(watch_addresses, list)
        and all(
            isinstance(row, dict) and is_address(row.get("address"))
            for row in watch_addresses
        )
        and watch_address_count == len(watch_addresses)
        and balance_target_count == len(expected_balance_keys)
        and actual_balance_keys == expected_balance_keys
        and len(actual_balance_keys) == len(balances)
        and normalized_hex_bytes(
            payload.get("target_latest_block_hash"),
            32,
            allow_zero=False,
        )
    )


def eligible_project_items(
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in config.get("items", []):
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        priority = item.get("priority", "")
        if item.get("active_monitoring") is False:
            skipped.append({"symbol": symbol, "reason": "archived_or_paused"})
            continue
        if item.get("project_watch_skip_generic"):
            skipped.append({"symbol": symbol, "reason": "specialized_watch"})
            continue
        if str(priority).startswith(("P0", "P1", "P2")):
            items.append(item)
    return items, skipped


def validated_scan_progress(
    items: list[dict[str, Any]],
    scan_fingerprint: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    bool,
]:
    progress = read_json(PROGRESS_PATH, {})
    if not isinstance(progress, dict):
        return [], [], {}, False
    if progress.get("schema_version") != PROGRESS_SCHEMA_VERSION:
        return [], [], {}, False
    if progress.get("scan_fingerprint") != scan_fingerprint:
        return [], [], {}, False
    completed_entries = progress.get("completed_projects")
    if not isinstance(completed_entries, list) or len(completed_entries) > len(items):
        return [], [], {}, False

    completed_projects: list[dict[str, Any]] = []
    for index, entry in enumerate(completed_entries):
        if not isinstance(entry, dict) or index >= len(items):
            return [], [], {}, False
        item = items[index]
        project = entry.get("project")
        if (
            entry.get("item_index") != index
            or entry.get("item_fingerprint") != project_item_fingerprint(item)
            or not isinstance(project, dict)
        ):
            return [], [], {}, False
        expected_contract_keys = [
            contract_checkpoint_key(contract) for contract in extract_contracts(item)
        ]
        project_contracts = project.get("contracts")
        if not isinstance(project_contracts, list) or any(
            not isinstance(contract, dict) for contract in project_contracts
        ):
            return [], [], {}, False
        if project.get("coverage_complete") is not True or any(
            not complete_contract_payload(contract)
            for contract in project_contracts
        ):
            return [], [], {}, False
        actual_contract_keys = [
            contract_checkpoint_key(contract) for contract in project_contracts
        ]
        if actual_contract_keys != expected_contract_keys:
            return [], [], {}, False
        completed_projects.append(project)

    active_contracts: list[dict[str, Any]] = []
    active_contract_progress: dict[str, Any] = {}
    active = progress.get("active_project")
    if active is not None:
        active_index = len(completed_projects)
        if (
            not isinstance(active, dict)
            or active_index >= len(items)
            or active.get("item_index") != active_index
            or active.get("item_fingerprint")
            != project_item_fingerprint(items[active_index])
        ):
            return [], [], {}, False
        stored_contracts = active.get("contracts")
        if not isinstance(stored_contracts, list) or any(
            not isinstance(contract, dict) for contract in stored_contracts
        ):
            return [], [], {}, False
        expected_contract_keys = [
            contract_checkpoint_key(contract)
            for contract in extract_contracts(items[active_index])
        ]
        actual_contract_keys = [
            contract_checkpoint_key(contract) for contract in stored_contracts
        ]
        if actual_contract_keys != expected_contract_keys[: len(actual_contract_keys)]:
            return [], [], {}, False
        if any(
            not complete_contract_payload(contract)
            for contract in stored_contracts
        ):
            return [], [], {}, False
        active_contracts = stored_contracts
        raw_contract_progress = active.get("contract_progress")
        if raw_contract_progress is not None:
            if not isinstance(raw_contract_progress, dict):
                return [], [], {}, False
            if len(active_contracts) >= len(expected_contract_keys):
                return [], [], {}, False
            if raw_contract_progress.get("contract_key") != expected_contract_keys[
                len(active_contracts)
            ]:
                return [], [], {}, False
            active_contract_progress = raw_contract_progress
    return completed_projects, active_contracts, active_contract_progress, bool(
        completed_projects or active_contracts or active_contract_progress
    )


def write_scan_progress(
    scan_fingerprint: str,
    items: list[dict[str, Any]],
    completed_projects: list[dict[str, Any]],
    active_contracts: list[dict[str, Any]] | None,
    active_contract_progress: dict[str, Any] | None = None,
) -> None:
    completed_entries = [
        {
            "item_index": index,
            "item_fingerprint": project_item_fingerprint(items[index]),
            "project": project,
        }
        for index, project in enumerate(completed_projects)
    ]
    active_project = None
    if active_contracts is not None and len(completed_projects) < len(items):
        active_index = len(completed_projects)
        active_project = {
            "item_index": active_index,
            "item_fingerprint": project_item_fingerprint(items[active_index]),
            "contracts": active_contracts,
            "contract_progress": active_contract_progress,
        }
    write_json(
        PROGRESS_PATH,
        {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "scan_fingerprint": scan_fingerprint,
            "completed_projects": completed_entries,
            "active_project": active_project,
        },
    )


def build_snapshot() -> dict[str, Any]:
    global PROJECT_DEADLINE_AT

    config = read_json(CONFIG_PATH, {"items": []})
    previous = load_previous()
    previous_tips = previous_contract_tips(previous)
    previous_hashes = previous_contract_hashes(previous)
    previous_balance_map = previous_balances(previous)
    finality = int(os.environ.get("ALPHA_PROJECT_FINALITY_BLOCKS", "20"))
    lookback = int(os.environ.get("ALPHA_PROJECT_LOOKBACK_BLOCKS", "50000"))
    items, skipped = eligible_project_items(config)
    scan_fingerprint = project_scan_fingerprint(
        items,
        previous,
        finality,
        lookback,
    )
    (
        projects,
        active_contracts,
        active_contract_progress,
        resumed,
    ) = validated_scan_progress(
        items,
        scan_fingerprint,
    )
    try:
        configured_budget = int(
            os.environ.get(
                "ALPHA_PROJECT_RUNTIME_BUDGET_SECONDS",
                str(PROJECT_RUNTIME_BUDGET_SECONDS),
            )
        )
    except ValueError:
        configured_budget = PROJECT_RUNTIME_BUDGET_SECONDS
    previous_deadline = PROJECT_DEADLINE_AT
    PROJECT_DEADLINE_AT = time.monotonic() + min(
        PROJECT_RUNTIME_BUDGET_SECONDS,
        max(1, configured_budget),
    )
    snapshot_projects = list(projects)
    try:
        for item_index in range(len(projects), len(items)):
            item = items[item_index]
            resumed_contracts = (
                active_contracts if item_index == len(projects) else []
            )
            resumed_progress = (
                active_contract_progress
                if item_index == len(projects)
                else {}
            )

            def checkpoint_contracts(
                contracts: list[dict[str, Any]],
            ) -> None:
                write_scan_progress(
                    scan_fingerprint,
                    items,
                    projects,
                    contracts,
                )

            def checkpoint_contract_progress(
                contracts: list[dict[str, Any]],
                contract_progress: dict[str, Any],
            ) -> None:
                write_scan_progress(
                    scan_fingerprint,
                    items,
                    projects,
                    contracts,
                    contract_progress,
                )

            project = build_project(
                item,
                previous_tips,
                previous_balance_map,
                finality,
                lookback,
                previous_hashes=previous_hashes,
                resumed_contracts=resumed_contracts,
                resumed_contract_progress=resumed_progress,
                on_contract_complete=checkpoint_contracts,
                on_contract_progress=checkpoint_contract_progress,
            )
            if project.get("coverage_complete") is not True:
                snapshot_projects = projects + [project]
                break
            projects.append(project)
            snapshot_projects = list(projects)
            active_contracts = []
            active_contract_progress = {}
            write_scan_progress(
                scan_fingerprint,
                items,
                projects,
                None,
            )
    finally:
        PROJECT_DEADLINE_AT = previous_deadline

    coverage_complete = bool(
        len(projects) == len(items)
        and all(
            project.get("coverage_complete") is True
            for project in projects
        )
    )
    alerts = [
        alert
        for project in snapshot_projects
        for alert in project.get("alerts", [])
    ]
    snapshot = {
        "generated_at": now_iso(),
        "config_path": str(CONFIG_PATH),
        "project_count": len(snapshot_projects),
        "expected_project_count": len(items),
        "alert_count": len(alerts),
        "coverage_complete": coverage_complete,
        "resumed_from_progress": resumed,
        "skipped": skipped,
        "projects": snapshot_projects,
    }
    return snapshot


def build_project(
    item: dict[str, Any],
    previous_tips: dict[tuple[str, str, str], int],
    previous_balance_map: dict[tuple[str, str, str, str], Decimal],
    finality: int,
    lookback: int,
    *,
    previous_hashes: dict[tuple[str, str, str], str] | None = None,
    resumed_contracts: list[dict[str, Any]] | None = None,
    resumed_contract_progress: dict[str, Any] | None = None,
    on_contract_complete: Any = None,
    on_contract_progress: Any = None,
) -> dict[str, Any]:
    symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
    contracts = list(resumed_contracts or [])
    alerts = []
    configured_contracts = extract_contracts(item)
    pending = False
    for contract_index, contract in enumerate(
        configured_contracts[len(contracts) :],
        start=len(contracts),
    ):
        contract_progress = (
            dict(resumed_contract_progress or {})
            if contract_index == len(contracts)
            else {}
        )

        def checkpoint_progress(progress: dict[str, Any]) -> None:
            if on_contract_progress is not None:
                on_contract_progress(contracts, progress)

        try:
            contract_payload = build_contract(
                symbol,
                contract,
                item,
                previous_tips,
                previous_balance_map,
                finality,
                lookback,
                previous_hashes=previous_hashes,
                resumed_progress=contract_progress,
                on_progress=checkpoint_progress,
            )
        except RpcDeadlineExceeded:
            raise
        except Exception as exc:
            previous_tip = previous_tips.get(
                (symbol, contract["chain"], norm(contract["address"])),
                0,
            )
            contract_payload = build_contract_error(contract, exc, previous_tip)
        contracts.append(contract_payload)
        if contract_payload.get("coverage_complete") is False:
            pending = True
            break
        if on_contract_complete is not None:
            on_contract_complete(contracts)

    for contract_payload in contracts:
        alerts.extend(contract_payload.get("alerts", []))
    launches = launch_events(item)
    receipts = [] if pending else tx_receipts(item)

    attribution_gap_states = sorted(
        {
            str(contract.get("operator_attribution_state") or "")
            for contract in contracts
        }
        & {"owner_unresolved", "conflicting_owner_selectors", "unresolved"}
    )
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    if facts.get("alpha_id") and attribution_gap_states:
        alerts.append(
            {
                "type": "ATTRIBUTION_GAP",
                "symbol": symbol,
                "level": "COVERAGE",
                "states": attribution_gap_states,
                "contracts": [
                    contract.get("address", "")
                    for contract in contracts
                    if contract.get("address")
                ],
            }
        )

    start_hours = int(os.environ.get("ALPHA_PROJECT_START_ALERT_HOURS", "36"))
    for event in [] if pending else launches:
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
        "coverage_complete": bool(
            not pending and len(contracts) == len(configured_contracts)
        ),
        "scan_status": "pending" if pending else "complete",
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
    *,
    previous_hashes: dict[tuple[str, str, str], str] | None = None,
    resumed_progress: dict[str, Any] | None = None,
    on_progress: Any = None,
) -> dict[str, Any]:
    chain = contract["chain"]
    address = norm(contract["address"])
    contract_key = contract_checkpoint_key(contract)
    checkpoint_key = (symbol, chain, address)
    previous_tip = previous_tips.get(checkpoint_key, 0)
    published_tip = previous_tip
    previous_hash = (previous_hashes or {}).get(checkpoint_key, "")
    effective_lookback = max(
        1,
        int(item.get("project_lookback_blocks") or lookback),
    )
    progress = (
        dict(resumed_progress or {})
        if (resumed_progress or {}).get("contract_key") == contract_key
        else {"contract_key": contract_key, "phase": "metadata"}
    )
    if on_progress is not None:
        on_progress(progress)

    raw_tip = int(progress.get("raw_latest_block") or 0)
    tip = int(progress.get("target_latest_block") or 0)
    from_block = int(progress.get("requested_from_block") or 0)
    decimals = 18
    total_supply = ""
    watch_addresses: list[dict[str, Any]] = []
    operator_attribution_state = "unresolved"

    def pending_payload(
        reason: str,
        log_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        next_from = int(progress.get("next_from_block") or from_block)
        covered_through = int(
            progress.get("covered_through_block")
            if progress.get("covered_through_block") is not None
            else next_from - 1
        )
        transfer_complete = bool(tip >= 0 and next_from > tip)
        balances = preserved_balance_rows(
            symbol,
            chain,
            address,
            watch_addresses,
            previous_balance_map,
        )
        errors = list(log_errors or [])
        return {
            "chain": chain,
            "address": address,
            "confidence": contract.get("confidence", ""),
            "raw_latest_block": raw_tip,
            "latest_block": previous_tip,
            "previous_latest_block": previous_tip,
            "from_block": from_block,
            "requested_from_block": from_block,
            "target_latest_block": tip,
            "target_latest_block_hash": str(
                progress.get("target_latest_block_hash") or ""
            ),
            "covered_through_block": covered_through,
            "next_from_block": next_from,
            "coverage_complete": False,
            "transfer_coverage_complete": transfer_complete,
            "scan_status": reason,
            "finality_blocks": finality,
            "lookback_blocks": effective_lookback,
            "decimals": decimals,
            "total_supply": total_supply,
            "watch_address_count": len(watch_addresses),
            "balance_target_count": len(
                expected_balance_identities(
                    chain,
                    address,
                    watch_addresses,
                )
            ),
            "operator_attribution_state": operator_attribution_state,
            "watch_addresses": watch_addresses,
            "log_error_count": len(errors),
            "log_errors": errors[:3],
            "balances": balances,
            "recent_transfers": [],
            "alerts": [],
        }

    try:
        if previous_tip:
            normalized_previous_hash = normalized_hex_bytes(
                previous_hash,
                32,
                allow_zero=False,
            )
            if not normalized_previous_hash:
                return pending_payload(
                    "previous_checkpoint_unverifiable"
                )
            if (
                canonical_block_hash(chain, previous_tip)
                != normalized_previous_hash
            ):
                return pending_payload("previous_checkpoint_reorg")
        decimals = token_decimals(chain, address)
        total_supply = token_total_supply(chain, address, decimals)
        watch_addresses, operator_attribution_state = effective_watch_addresses(
            item,
            chain,
            address,
        )
        if (
            str(item.get("project_operator_probe") or "").lower()
            == "owner"
            and not watch_addresses
            and operator_attribution_state
            in {"owner_unresolved", "conflicting_owner_selectors", "unresolved"}
        ):
            raise RuntimeError("project operator scope unresolved")
        scope_fingerprint = contract_scan_scope_fingerprint(
            symbol,
            contract,
            watch_addresses,
            finality,
            effective_lookback,
            decimals,
        )
        progress = validated_contract_progress(
            progress,
            contract_key=contract_key,
            scope_fingerprint=scope_fingerprint,
            previous_tip=previous_tip,
        )
        if progress:
            tip = int(progress["target_latest_block"])
            raw_tip = int(progress["raw_latest_block"])
            from_block = int(progress["requested_from_block"])
            if canonical_block_hash(chain, tip) != progress[
                "target_latest_block_hash"
            ]:
                progress = {}
        if not progress:
            raw_tip = latest_block(chain)
            tip = max(0, raw_tip - finality)
            if published_tip and tip < published_tip:
                from_block = published_tip + 1
                return pending_payload("target_behind_checkpoint")
            if previous_tip:
                from_block = previous_tip + 1
            else:
                from_block = max(0, tip - effective_lookback)
            from_block = min(from_block, tip + 1)
            progress = {
                "contract_key": contract_key,
                "scope_fingerprint": scope_fingerprint,
                "phase": "transfer_scan",
                "raw_latest_block": raw_tip,
                "target_latest_block": tip,
                "target_latest_block_hash": canonical_block_hash(
                    chain,
                    tip,
                ),
                "previous_latest_block": previous_tip,
                "requested_from_block": from_block,
                "next_from_block": from_block,
                "covered_through_block": from_block - 1,
                "recent_transfers": [],
                "pending_transfer_candidates": [],
            }
            if on_progress is not None:
                on_progress(progress)

        transfers = list(progress.get("recent_transfers") or [])
        transfer_candidates = list(
            progress.get("pending_transfer_candidates") or []
        )
        min_transfer = env_decimal(
            "ALPHA_PROJECT_MIN_TRANSFER_ALERT",
            "100000",
        )

        def checkpoint_chunk(
            _start: int,
            end: int,
            completed_rows: list[dict[str, Any]],
        ) -> None:
            merged: dict[tuple[str, int], dict[str, Any]] = {
                (str(row.get("tx") or "").lower(), int(row.get("log_index") or 0)): row
                for row in transfers
            }
            for raw_row in completed_rows:
                row = transfer_row(raw_row, decimals)
                key = (
                    str(row.get("tx") or "").lower(),
                    int(row.get("log_index") or 0),
                )
                previous_row = merged.get(key)
                if previous_row is not None and previous_row != row:
                    raise RuntimeError(
                        "project transfer checkpoint identity conflict"
                    )
                merged[key] = row
            candidate_merged: dict[tuple[str, int], dict[str, Any]] = {
                (
                    str(row.get("tx") or "").lower(),
                    int(row.get("log_index") or 0),
                ): row
                for row in transfer_candidates
            }
            for row in merged.values():
                if (
                    previous_tip > 0
                    and Decimal(str(row.get("amount") or "0"))
                    >= min_transfer
                ):
                    candidate_merged[
                        (
                            str(row.get("tx") or "").lower(),
                            int(row.get("log_index") or 0),
                        )
                    ] = row
            transfers[:] = sorted(
                merged.values(),
                key=lambda row: (
                    int(row.get("block") or 0),
                    int(row.get("log_index") or 0),
                ),
            )[-40:]
            transfer_candidates[:] = sorted(
                candidate_merged.values(),
                key=lambda row: (
                    int(row.get("block") or 0),
                    int(row.get("log_index") or 0),
                ),
            )
            progress.update(
                {
                    "phase": (
                        "balances" if end >= tip else "transfer_scan"
                    ),
                    "next_from_block": end + 1,
                    "covered_through_block": end,
                    "recent_transfers": list(transfers),
                    "pending_transfer_candidates": list(
                        transfer_candidates
                    ),
                }
            )
            if on_progress is not None:
                on_progress(progress)

        next_from = int(progress["next_from_block"])
        log_errors: list[str] = []
        if watch_addresses and next_from <= tip:
            _, log_errors = get_transfer_logs(
                chain,
                address,
                [row["address"] for row in watch_addresses],
                from_block,
                tip,
                resume_from_block=next_from,
                on_chunk_complete=checkpoint_chunk,
            )
        elif not watch_addresses and next_from <= tip:
            progress.update(
                {
                    "phase": "balances",
                    "next_from_block": tip + 1,
                    "covered_through_block": tip,
                }
            )
            if on_progress is not None:
                on_progress(progress)
        if log_errors:
            return pending_payload("transfer_scan_pending", log_errors)
        if int(progress["next_from_block"]) <= tip:
            return pending_payload("transfer_scan_pending")

        current_target_hash = canonical_block_hash(chain, tip)
        if current_target_hash != progress["target_latest_block_hash"]:
            progress.update(
                {
                    "phase": "target_reorg_retry",
                    "target_latest_block_hash": current_target_hash,
                    "next_from_block": from_block,
                    "covered_through_block": from_block - 1,
                    "recent_transfers": [],
                    "pending_transfer_candidates": [],
                }
            )
            transfers.clear()
            if on_progress is not None:
                on_progress(progress)
            return pending_payload("target_reorg_retry")

        balances = build_balances(
            symbol,
            chain,
            address,
            decimals,
            watch_addresses,
            previous_balance_map,
        )
        balance_errors = [
            str(row.get("error") or "balance RPC unavailable")
            for row in balances
            if row.get("error")
        ]
        expected_balance_keys = expected_balance_identities(
            chain,
            address,
            watch_addresses,
        )
        actual_balance_keys = {
            (
                norm(row.get("address")),
                norm(row.get("balance_token_address")),
            )
            for row in balances
            if isinstance(row, dict)
        }
        if (
            balance_errors
            or actual_balance_keys != expected_balance_keys
            or len(actual_balance_keys) != len(balances)
        ):
            if not balance_errors:
                balance_errors.append("balance coverage incomplete")
            return pending_payload("balance_scan_pending", balance_errors)
        alerts = build_contract_alerts(
            symbol,
            chain,
            address,
            previous_tip,
            transfer_candidates,
            balances,
            watch_addresses,
        )
        return {
            "chain": chain,
            "address": address,
            "confidence": contract.get("confidence", ""),
            "raw_latest_block": raw_tip,
            "latest_block": tip,
            "previous_latest_block": previous_tip,
            "from_block": from_block,
            "requested_from_block": from_block,
            "target_latest_block": tip,
            "target_latest_block_hash": progress[
                "target_latest_block_hash"
            ],
            "covered_through_block": tip,
            "next_from_block": tip + 1,
            "coverage_complete": True,
            "transfer_coverage_complete": True,
            "scan_status": "complete",
            "finality_blocks": finality,
            "lookback_blocks": effective_lookback,
            "decimals": decimals,
            "total_supply": total_supply,
            "watch_address_count": len(watch_addresses),
            "balance_target_count": len(expected_balance_keys),
            "operator_attribution_state": operator_attribution_state,
            "watch_addresses": watch_addresses,
            "log_error_count": 0,
            "log_errors": [],
            "balances": balances,
            "recent_transfers": transfers,
            "alerts": alerts,
        }
    except RpcDeadlineExceeded:
        return pending_payload("deadline_exceeded")


def build_contract_error(
    contract: dict[str, str],
    exc: Exception,
    previous_tip: int = 0,
) -> dict[str, Any]:
    return {
        "chain": contract.get("chain", ""),
        "address": norm(contract.get("address")),
        "confidence": contract.get("confidence", ""),
        "raw_latest_block": 0,
        "latest_block": previous_tip,
        "previous_latest_block": previous_tip,
        "from_block": previous_tip + 1 if previous_tip else 0,
        "requested_from_block": previous_tip + 1 if previous_tip else 0,
        "target_latest_block": previous_tip,
        "target_latest_block_hash": "",
        "covered_through_block": previous_tip,
        "next_from_block": previous_tip + 1,
        "coverage_complete": False,
        "transfer_coverage_complete": False,
        "scan_status": "error",
        "finality_blocks": 0,
        "lookback_blocks": 0,
        "decimals": 18,
        "total_supply": "",
        "watch_address_count": 0,
        "balance_target_count": 0,
        "operator_attribution_state": "contract_error",
        "watch_addresses": [],
        "log_error_count": 1,
        "log_errors": [str(exc)],
        "balances": [],
        "recent_transfers": [],
        "alerts": [],
        "error": str(exc),
    }


def expected_balance_identities(
    chain: str,
    token: str,
    watch_addresses: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    token = norm(token)
    for item in watch_addresses:
        address = norm(item.get("address"))
        identities.add((address, token))
        if not item.get("watch_quote"):
            continue
        requested = {
            str(row).upper()
            for row in item.get("watch_quote_tokens") or ["USDT"]
        }
        for quote_address, quote_symbol in QUOTE_TOKENS_BY_CHAIN.get(
            chain,
            {},
        ).items():
            if (
                requested
                and quote_symbol.upper() not in requested
                and quote_address.upper() not in requested
            ):
                continue
            identities.add((address, norm(quote_address)))
    return identities


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
            except RpcDeadlineExceeded:
                raise
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


def preserved_balance_rows(
    symbol: str,
    chain: str,
    token: str,
    watch_addresses: list[dict[str, Any]],
    previous_balance_map: dict[tuple[str, str, str, str], Decimal],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    token = norm(token)
    for item in watch_addresses:
        address = norm(item.get("address"))
        targets = [(token, symbol, False)]
        if item.get("watch_quote"):
            requested = {
                str(row).upper()
                for row in item.get("watch_quote_tokens") or ["USDT"]
            }
            for quote_address, quote_symbol in QUOTE_TOKENS_BY_CHAIN.get(chain, {}).items():
                if (
                    requested
                    and quote_symbol.upper() not in requested
                    and quote_address.upper() not in requested
                ):
                    continue
                targets.append((quote_address, quote_symbol, True))
        for balance_token, balance_symbol, is_quote in targets:
            previous = previous_balance_map.get(
                (symbol, chain, norm(balance_token), address)
            )
            if previous is None:
                continue
            rows.append(
                {
                    **item,
                    "balance_token": balance_symbol,
                    "balance_token_address": norm(balance_token),
                    "is_quote_balance": is_quote,
                    "balance": str(previous),
                    "previous_balance": str(previous),
                    "delta": "",
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
    watch_addresses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if previous_tip <= 0:
        return []
    alerts = []
    watch_by_address = {
        norm(row.get("address")): row
        for row in watch_addresses
        if is_address(row.get("address"))
    }
    min_transfer = env_decimal("ALPHA_PROJECT_MIN_TRANSFER_ALERT", "100000")
    min_balance_delta = env_decimal("ALPHA_PROJECT_MIN_BALANCE_DELTA_ALERT", "100000")
    min_quote_delta = env_decimal("ALPHA_PROJECT_MIN_QUOTE_BALANCE_DELTA_ALERT", "10000")
    for row in transfers:
        if previous_tip and int(row.get("block") or 0) <= previous_tip:
            continue
        amount = Decimal(str(row.get("amount", "0")))
        if amount < min_transfer:
            continue
        watched_from = watch_by_address.get(norm(row.get("from")), {})
        watched_to = watch_by_address.get(norm(row.get("to")), {})
        watched = watched_from or watched_to
        alerts.append(
            {
                "type": "TOKEN_TRANSFER",
                "symbol": symbol,
                "chain": chain,
                "token": token,
                "level": "CRITICAL" if amount >= min_transfer * Decimal(5) else "HIGH",
                "block": row.get("block"),
                "tx": row.get("tx"),
                "log_index": row.get("log_index"),
                "from": row.get("from"),
                "to": row.get("to"),
                "amount": str(amount),
                "watched_direction": "out" if watched_from else "in",
                "role": watched.get("role", ""),
                "control_scope": watched.get("control_scope", "unknown"),
                "identity_status": watched.get("identity_status", "unattributed"),
                "attribution": watched.get("attribution", ""),
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
                "control_scope": row.get("control_scope", "unknown"),
                "identity_status": row.get("identity_status", "unattributed"),
                "attribution": row.get("attribution", ""),
                "delta": str(delta),
            }
        )
    return alerts


def controller_risk_movement(row: dict[str, Any]) -> bool:
    if row.get("identity_status") != "verified" or row.get("control_scope") != "token":
        return False
    if row.get("type") == "TOKEN_TRANSFER":
        return row.get("watched_direction") == "out"
    if row.get("type") != "BALANCE_CHANGE":
        return False
    try:
        delta = Decimal(str(row.get("delta") or "0"))
    except InvalidOperation:
        return False
    return (bool(row.get("is_quote_balance")) and delta > 0) or (
        not row.get("is_quote_balance") and delta < 0
    )


def controller_inbound_movement(row: dict[str, Any]) -> bool:
    if row.get("identity_status") != "verified" or row.get("control_scope") != "token":
        return False
    if row.get("type") == "TOKEN_TRANSFER":
        return row.get("watched_direction") == "in"
    if row.get("type") != "BALANCE_CHANGE" or row.get("is_quote_balance"):
        return False
    try:
        return Decimal(str(row.get("delta") or "0")) > 0
    except InvalidOperation:
        return False


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
    controller_alerts = [row for row in movement_alerts if controller_risk_movement(row)]
    controller_inbound_alerts = [
        row for row in movement_alerts if controller_inbound_movement(row)
    ]
    candidate_alerts = [
        row
        for row in movement_alerts
        if row.get("identity_status") in {"candidate", "functional_only", "unattributed", ""}
        and row.get("control_scope") not in {"pool", "distribution"}
    ]
    attribution_states = {
        str(contract.get("operator_attribution_state") or "")
        for contract in contracts
    }
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

    if controller_alerts:
        conclusion = f"{symbol} 合约控制地址出现新资金动作，卖出状态需要同一成功收据中的 token 流出与报价资产流入共同确认。"
        spot_action = "持仓降低风险；空仓等待卖出收据或后续承接"
        perp_action = "记录偏空条件；等待真实可交易深度与价格走弱"
        attention = "核对控制地址动作的成功收据、对手方与报价资产净流"
        operator = "已确认链上 token controller 身份；当前动作仍按资金移动记录。"
        sniper = "首批狙击去向继续由 opening cohort 独立追踪。"
    elif candidate_alerts:
        conclusion = f"{symbol} 关键地址或功能地址出现新动作，来源归属仍待验证。"
        spot_action = "持仓降低风险；空仓等待身份与成交收据补齐"
        perp_action = "仅记录风险条件；不把候选身份当项目方事实"
        attention = "补齐 control_scope、identity_status 与同收据成交证据"
        operator = "当前只确认地址动作；项目方或做市身份尚未成立。"
        sniper = "狙击地址与项目控制地址保持独立归因。"
    elif pool_token_out:
        conclusion = f"{symbol} 池子卖出区正在被买盘吃掉，PoolManager {symbol} 减少约 {format_amount(pool_token_out)}。"
        spot_action = "空仓不追；持仓按冲高降风险，等回踩承接和项目侧资金去向"
        perp_action = "偏空预案；等交易所流入、价格转弱和可交易合约深度"
        attention = "卖出区消耗后继续看报价资产是否离开池子路径、是否跨链或进交易所"
        operator = "已确认池侧 token 流出；操作者身份仍需单独归因。"
        sniper = "狙击买盘和跟风买盘正在承接卖出区，若买盘衰竭容易出现冲高回落。"
    elif quote_in:
        conclusion = f"{symbol} 关键地址收到报价资产约 {format_amount(quote_in)}，需要确认来源是否来自池子卖出区或做市回收。"
        spot_action = "空仓不追；已有仓位降低风险，等报价资产来源确认"
        perp_action = "偏空条件；若同步出现价格走弱和交易所流入，再执行"
        attention = "打开最新 tx，看对手方是池子、聚合器、CEX 还是内部钱包"
        operator = "关键地址正在接收报价资产；是否属于项目或做市回收仍需身份与收据证据。"
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
        operator = "已确认池侧流动性变化，操作者身份待归因。"
        sniper = "狙击判断要等新区间和真实买入出现。"
    elif quote_out:
        conclusion = f"{symbol} 关键地址转出报价资产约 {format_amount(quote_out)}，需要追踪下一跳。"
        spot_action = "观察偏谨慎；持仓先降风险"
        perp_action = "偏空条件；等去向进交易所或价格走弱"
        attention = "确认报价资产是做市调仓、跨链、归集，还是进入交易所"
        operator = "关键地址出现报价资产转移，身份与资金路径需要继续追。"
        sniper = "狙击手行为不是当前主信号，优先看项目侧资金路径。"
    elif controller_inbound_alerts:
        conclusion = f"{symbol} 合约控制地址收到 token，本轮只记录入账。"
        spot_action = "观察；等待后续成功收据和资金去向"
        perp_action = "不开仓；单纯入账不构成偏空证据"
        attention = "继续看该地址是否转出 token、收到报价资产或进入交易所路径"
        operator = "已确认 token controller 入账，尚未出现卖出或出金组合证据。"
        sniper = "首批狙击去向继续由 opening cohort 独立追踪。"
    elif critical or transfer_alerts or balance_alerts:
        conclusion = f"{symbol} 关键地址出现新动作，进入深度验证。"
        spot_action = "观察；先打开最新 tx，确认流向交易所、池子、桥或新中转钱包"
        perp_action = "合约未确认；只记录偏空条件，等交易所充值、大户外流或首波冲高回落证据"
        attention = "重点看 txIndex、counterparty、bribe、池子深度和后续余额变化"
        operator = "关键地址正在移动筹码，归属与控制关系需要继续验证。"
        sniper = "狙击判断点在开盘块前后买入排序、gas/bribe 和买入后是否快速转出。"
    elif launch_alerts:
        conclusion = f"{symbol} 已进入上线窗口，开始开盘块预案。"
        spot_action = launch_spot_plan(item)
        perp_action = launch_perp_plan(item)
        attention = launch_attention(item)
        operator = "官方上线时间已进入监控窗口，下一步看池侧流动性与控制地址动作。"
        sniper = "狙击手通常会在池子可交易后的首块竞争，重点看同块排序和贿赂。"
    elif contracts and watched == 0:
        conclusion = f"{symbol} 已有合约线索，缺少关键地址监控。"
        spot_action = "观察；先补官方合约、池子、分发、做市和空投地址"
        perp_action = "不开仓；缺少筹码流向和价格结构"
        attention = "把团队、部署、加池、分发、桥和 CEX 充值地址补进 watch_addresses"
        operator = "当前只能确认合约线索，项目方实时行为证据不足。"
        sniper = "当前无法判断外部狙击和项目方自买，需要开盘块与关键地址。"
    elif contracts and attribution_states <= {
        "verified_token_controller",
        "configured",
    }:
        conclusion = f"{symbol} 控制/候选地址处于监控中，本轮无新增资金动作。"
        spot_action = "观察；等待成功收据与报价资产净流"
        perp_action = "不开仓；当前没有新增出货证据"
        attention = "持续区分 token controller、池侧功能地址与未归属卖家"
        operator = "控制关系按现有链上或配置证据记录，本轮没有确认卖出。"
        sniper = "首批狙击 cohort 仍按独立链路追踪。"
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
                        str(alert.get("log_index", "")),
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
        elif kind == "ATTRIBUTION_GAP":
            keys.append(
                "|".join(
                    [
                        "attribution_gap",
                        str(alert.get("symbol", "")),
                        ",".join(sorted(str(value) for value in alert.get("states", []))),
                        ",".join(sorted(norm(value) for value in alert.get("contracts", []))),
                    ]
                )
            )
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


def maybe_send_telegram(snapshot: dict[str, Any]) -> bool:
    if os.environ.get("ALPHA_PROJECT_WATCH_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return True
    keys = alert_keys([alert for project in snapshot.get("projects", []) for alert in project.get("alerts", [])])
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if key not in seen]
    force = os.environ.get("ALPHA_PROJECT_WATCH_FORCE_TELEGRAM") == "1"
    if not new_keys and not force:
        return True
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    text = telegram_text(
        {**snapshot, "new_alert_count": len(new_keys), "_telegram_new_alert_keys": new_keys}
    )[:TELEGRAM_LIMIT]
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        receipt = read_telegram_send_receipt(response)
    write_json(SEEN_PATH, sorted(seen | set(keys)))
    record_push(snapshot, text, receipt)
    return True


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


def record_push(snapshot: dict[str, Any], text: str, receipt: dict[str, Any]) -> None:
    record_telegram_send_receipt(
        LAST_PUSH_PATH,
        sent_at=now_iso(),
        signature=project_push_signature(snapshot),
        text=text,
        receipt=receipt,
    )


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
    if kind == "ATTRIBUTION_GAP":
        return f"{level} 项目/做市身份覆盖待补"
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
        f"- expected_project_count: `{snapshot.get('expected_project_count', snapshot.get('project_count'))}`",
        f"- coverage_complete: `{snapshot.get('coverage_complete')}`",
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
                f"- scan_status: `{project.get('scan_status', '')}`",
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
    if kind == "ATTRIBUTION_GAP":
        return (
            f"{alert.get('level')} {alert.get('symbol')} operator attribution "
            f"{','.join(alert.get('states', []))}"
        )
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


def publish_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("coverage_complete") is not True:
        write_text(PENDING_REPORT_PATH, render(snapshot))
        write_json(PENDING_PATH, snapshot)
        return
    if not maybe_send_telegram(snapshot):
        raise RuntimeError("alpha project Telegram delivery unavailable")
    write_text(REPORT_PATH, render(snapshot))
    write_json(LATEST_PATH, snapshot)
    PROGRESS_PATH.unlink(missing_ok=True)
    PENDING_PATH.unlink(missing_ok=True)
    PENDING_REPORT_PATH.unlink(missing_ok=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    publish_snapshot(snapshot)
    if snapshot.get("coverage_complete") is True:
        print(LATEST_PATH)
        print(REPORT_PATH)
    else:
        print(PENDING_PATH)
        print(PENDING_REPORT_PATH)
    print(f"projects={snapshot['project_count']} alerts={snapshot['alert_count']}")
    return 0 if snapshot.get("coverage_complete") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
