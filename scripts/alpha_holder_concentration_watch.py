#!/usr/bin/env python3
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label, global_address_labels
from sniper_engine.rpc import rpc_call
from sniper_engine.telegram_send_receipt import read_telegram_send_receipt, record_telegram_send_receipt
from scripts.alpha_opening_block_watch import (
    MODIFY_LIQUIDITY_TOPIC,
    PANCAKE_INFINITY_BIN_POOL_MANAGER,
    V3_BURN_TOPIC,
    V3_COLLECT_TOPIC,
    V3_MINT_TOPIC,
    V3_SWAP_TOPIC,
    V4_SWAP_TOPIC,
    int_slot,
    strict_abi_event_word_count,
    strict_rpc_log_identity,
    strict_v3_swap_amount,
    strict_v4_swap_amount,
    uint_slot,
)


getcontext().prec = 80

CONFIG_PATH = Path(
    os.environ.get("ALPHA_WATCHLIST_PATH", ROOT / "config" / "current_alpha_watchlist.json")
)
OUT_DIR = ROOT / "output" / "alpha_holder_concentration_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
STATE_PATH = OUT_DIR / "state.json"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
DEFAULT_TELEGRAM_LOCK_PATH = (
    Path(os.environ["SNIPER_OFFLINE_TMP_ROOT"])
    / "tmp"
    / "sniper_alpha_holder_telegram.lock"
    if os.environ.get("SNIPER_OFFLINE_TMP_ROOT")
    else Path("/tmp/sniper_alpha_holder_telegram.lock")
)
TELEGRAM_LOCK_PATH = Path(
    os.environ.get(
        "ALPHA_HOLDER_TELEGRAM_LOCK_FILE",
        str(DEFAULT_TELEGRAM_LOCK_PATH),
    )
)
SURF_HOLDER_QUOTA_STATE_PATH = OUT_DIR / "surf_holder_quota_state.json"
PRICE_CONTEXT_PATH = ROOT / "output" / "alpha_price_momentum_watch" / "latest.json"
FLOW_CONTEXT_PATH = ROOT / "output" / "alpha_intraday_flow_watch" / "latest.json"
OPENING_CONTEXT_PATH = ROOT / "output" / "alpha_opening_block_watch" / "latest.json"
PROJECT_CONTEXT_PATH = ROOT / "output" / "alpha_project_watch" / "latest.json"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
BURN_ADDRESSES = {
    ZERO_ADDRESS,
    "0x000000000000000000000000000000000000dead",
    "0x0000000000000000000000000000000000000001",
}
INFRA_CLASSES = {
    "bridge",
    "cex_deposit",
    "cex_hot_wallet",
    "dex_quoter",
    "dex_router",
    "dex_vault",
    "exchange_aggregator",
    "exchange_aggregator_suspect",
    "lp_locker_or_staking",
    "lp_position_manager",
    "permit2",
    "pool",
    "pool_manager",
    "quote_token",
    "token_contract",
}
SUPPORTED_CHAINS = {"bsc", "base"}
TELEGRAM_LIMIT = 3600
FULL_HOLDER_SOURCE_ENV = "ALPHA_HOLDER_FULL_SOURCE"
RETENTION_FLOW_START_HOURS = 0
RETENTION_FLOW_DAYS = 30
RETENTION_CEX_MIN_SUPPLY_BPS = 5
BOUNDED_BOOTSTRAP_UNRELIABLE = "bounded_bootstrap_unreliable"
RETENTION_SCOPE_STATE_SCHEMA_VERSION = 1
LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION = 2
LIQUIDITY_PROVIDER_ROW_LIMIT_HARD_CAP = 128
RETENTION_PROJECT_ROLES = {
    "contract_owner",
    "deployer",
    "market_maker",
    "market_maker_wallet",
    "mm",
    "project",
    "project_operator",
    "project_treasury",
    "project_wallet",
    "token_controller",
}
CEX_ADDRESS_KEYS = (
    "cex_deposit_addresses",
    "cex_addresses",
    "cex_hot_wallet_addresses",
    "exchange_addresses",
    "known_cex_addresses",
)
CEX_ROLES = {"cex", "cex_deposit", "cex_hot_wallet", "exchange"}
HOLDER_DEADLINE_AT: float | None = None
DEFAULT_HOLDER_BUDGET_SECONDS = 210
MAX_HOLDER_BUDGET_SECONDS = 220


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def today_utc() -> str:
    return now_utc().strftime("%Y-%m-%d")


def configure_holder_deadline() -> None:
    global HOLDER_DEADLINE_AT

    try:
        configured = int(
            os.environ.get(
                "ALPHA_HOLDER_WATCHER_BUDGET_SECONDS",
                str(DEFAULT_HOLDER_BUDGET_SECONDS),
            )
        )
    except ValueError:
        configured = DEFAULT_HOLDER_BUDGET_SECONDS
    seconds = min(
        MAX_HOLDER_BUDGET_SECONDS,
        max(1, configured),
    )
    HOLDER_DEADLINE_AT = time.monotonic() + seconds


def holder_rpc_call(
    chain: str,
    method: str,
    params: list[Any],
) -> Any:
    if HOLDER_DEADLINE_AT is None:
        return rpc_call(chain, method, params)
    return rpc_call(
        chain,
        method,
        params,
        deadline=HOLDER_DEADLINE_AT,
    )


def parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def parse_utc8(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc)


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_address(value: str | None) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def decimal_from(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def decimal_amount(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def format_amount(value: Any, places: int = 4) -> str:
    amount = decimal_from(value)
    if amount == 0:
        return "0"
    if abs(amount) >= Decimal("1000000"):
        return f"{amount.quantize(Decimal('0.01')):f}"
    if abs(amount) >= Decimal("1"):
        quant = Decimal(10) ** -places
        return f"{amount.quantize(quant):f}"
    return f"{amount.normalize():f}"


def format_pct(value: Any) -> str:
    amount = decimal_from(value)
    return f"{amount.quantize(Decimal('0.0001')):f}%"


def format_signed_pct(value: Any) -> str:
    return format_point_change(value)


def format_user_pct(value: Any) -> str:
    amount = decimal_from(value)
    return f"{amount.quantize(Decimal('0.01')):f}%"


def format_point_change(value: Any) -> str:
    amount = decimal_from(value)
    shown = amount.copy_abs().quantize(Decimal("0.01"))
    if amount > 0:
        return f"较上次增加 {shown:f} 个百分点"
    if amount < 0:
        return f"较上次减少 {shown:f} 个百分点"
    return "较上次无明显变化"


def short_addr(value: str) -> str:
    text = str(value or "")
    return text if len(text) <= 14 else text[:8] + "..." + text[-6:]


def surf_cli() -> str:
    configured = os.environ.get("SURF_BIN", "").strip()
    if configured:
        return configured
    local = Path.home() / ".local" / "bin" / "surf"
    if local.exists():
        return str(local)
    return "surf"


def surf_holder_error_summary(status: str, message: str = "") -> dict[str, Any]:
    detail = message.strip().splitlines()[0][:180] if message.strip() else status
    if status == "FREE_QUOTA_EXHAUSTED":
        detail = "Surf免费额度已用完，今日不再请求"
    elif status == "UNAUTHORIZED":
        detail = "Surf未配置可用API Key"
    elif status == "PAID_BALANCE_ZERO":
        detail = "Surf付费额度为0"
    elif status == "RATE_LIMITED":
        detail = "Surf请求频率受限"
    return {
        "source": "surf",
        "status": status,
        "summary": f"Surf读取失败: {detail}；当前显示窗口重建口径",
    }


def surf_holder_quota_blocked() -> bool:
    state = read_json(SURF_HOLDER_QUOTA_STATE_PATH, {})
    return state.get("exhausted_on_utc") == today_utc()


def mark_surf_holder_quota_exhausted(message: str) -> None:
    write_json(
        SURF_HOLDER_QUOTA_STATE_PATH,
        {
            "exhausted_on_utc": today_utc(),
            "updated_at": now_iso(),
            "message": message[:300],
        },
    )


def parse_surf_error(stdout: str, stderr: str) -> tuple[str, str]:
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return "error", stderr or stdout
    error = payload.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("code") or "api_error"), str(error.get("message") or error)
    return "api_error", str(error or stderr or stdout)


def is_surf_infra_holder(row: dict[str, Any]) -> bool:
    entity_type = str(row.get("entity_type") or "").lower()
    entity_name = str(row.get("entity_name") or "").lower()
    if entity_type in {"exchange", "dex", "bridge", "protocol", "misc"}:
        return True
    return any(keyword in entity_name for keyword in ("binance", "pancake", "router", "bridge", "pool"))


def surf_full_holder_status(chain: str, token: str) -> dict[str, Any]:
    if surf_holder_quota_blocked():
        return surf_holder_error_summary("FREE_QUOTA_EXHAUSTED")
    limit = max(10, min(100, int(os.environ.get("ALPHA_HOLDER_SURF_LIMIT", "20"))))
    timeout = max(3, int(os.environ.get("ALPHA_HOLDER_SURF_TIMEOUT", "20")))
    command = [
        surf_cli(),
        "token-holders",
        "--chain",
        chain,
        "--address",
        token,
        "--limit",
        str(limit),
        "--include",
        "labels",
        "--json",
        "--quiet",
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {
            "source": "surf",
            "status": "cli_missing",
            "summary": "Surf CLI未找到；当前显示窗口重建口径",
        }
    except subprocess.TimeoutExpired:
        return {
            "source": "surf",
            "status": "timeout",
            "summary": "Surf holder读取超时；当前显示窗口重建口径",
        }
    if result.returncode != 0:
        code, message = parse_surf_error(result.stdout, result.stderr)
        if code == "FREE_QUOTA_EXHAUSTED":
            mark_surf_holder_quota_exhausted(message)
        return surf_holder_error_summary(code, message)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return surf_holder_error_summary("invalid_json", str(exc))
    if payload.get("error"):
        error = payload.get("error") or {}
        if str(error.get("code") or "") == "FREE_QUOTA_EXHAUSTED":
            mark_surf_holder_quota_exhausted(str(error.get("message") or error))
        return surf_holder_error_summary(str(error.get("code") or "api_error"), str(error.get("message") or error))
    rows = payload.get("data") or []
    if not rows:
        return {
            "source": "surf",
            "status": "empty",
            "summary": "Surf未返回holder；当前显示窗口重建口径",
        }
    top10 = rows[:10]
    top10_pct = sum((decimal_from(row.get("percentage")) for row in top10), Decimal(0))
    infra_pct = sum((decimal_from(row.get("percentage")) for row in top10 if is_surf_infra_holder(row)), Decimal(0))
    simplified_rows = [
        {
            "address": norm(row.get("address")),
            "balance": str(row.get("balance") or ""),
            "percentage": str(row.get("percentage") or "0"),
            "entity_name": str(row.get("entity_name") or ""),
            "entity_type": str(row.get("entity_type") or ""),
            "is_infra": is_surf_infra_holder(row),
        }
        for row in top10
    ]
    return {
        "source": "surf",
        "status": "ok",
        "summary": f"Surf全量Top10 {format_user_pct(top10_pct)}；其中交易所/DEX/托管约 {format_user_pct(infra_pct)}",
        "top10_pct": str(top10_pct),
        "infra_pct": str(infra_pct),
        "row_count": len(rows),
        "rows": simplified_rows,
        "meta": payload.get("meta") or {},
    }


def topic_address(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


def address_from_topic(topic: str) -> str:
    return "0x" + norm(topic)[-40:]


def latest_block(chain: str) -> int:
    return int(
        holder_rpc_call(chain, "eth_blockNumber", []),
        16,
    )


def liquidity_checkpoint_block_hash(chain: str, block: int) -> str:
    try:
        payload = holder_rpc_call(
            chain,
            "eth_getBlockByNumber",
            [hex(block), False],
        )
    except Exception:
        return ""
    block_hash = norm(
        payload.get("hash") if isinstance(payload, dict) else ""
    )
    return (
        block_hash
        if valid_hash32(block_hash)
        and int(block_hash[2:], 16) != 0
        else ""
    )


def call_uint(chain: str, contract: str, data: str) -> int:
    raw = holder_rpc_call(
        chain,
        "eth_call",
        [{"to": contract, "data": data}, "latest"],
    )
    return int(raw or "0x0", 16)


def token_decimals(chain: str, contract: str) -> int:
    try:
        value = call_uint(chain, contract, "0x313ce567")
    except Exception:
        return 18
    return value if 0 <= value <= 36 else 18


def token_total_supply_raw(chain: str, contract: str) -> int:
    try:
        return call_uint(chain, contract, "0x18160ddd")
    except Exception:
        return 0


def get_code(chain: str, address: str, cache: dict[str, str]) -> str:
    address = norm(address)
    if address not in cache:
        try:
            cache[address] = str(
                holder_rpc_call(
                    chain,
                    "eth_getCode",
                    [address, "latest"],
                )
                or "0x"
            )
        except Exception:
            cache[address] = "0x"
    return cache[address]


def block_number(row: dict[str, Any]) -> int:
    return int(row.get("blockNumber") or "0x0", 16)


def log_index(row: dict[str, Any]) -> int:
    return int(row.get("logIndex") or "0x0", 16)


def transfer_logs(chain: str, token: str, from_block: int, to_block: int) -> tuple[list[dict[str, Any]], list[str], bool]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    truncated = False
    chunk_size = max(1, int(os.environ.get("ALPHA_HOLDER_LOG_CHUNK_BLOCKS", "8000")))
    max_logs = max(1, int(os.environ.get("ALPHA_HOLDER_MAX_LOGS_PER_TOKEN", "30000")))
    for start in range(from_block, to_block + 1, chunk_size):
        end = min(to_block, start + chunk_size - 1)
        query = {
            "address": token,
            "fromBlock": hex(start),
            "toBlock": hex(end),
            "topics": [TRANSFER_TOPIC],
        }
        try:
            result = holder_rpc_call(
                chain,
                "eth_getLogs",
                [query],
            )
        except Exception:
            return [], [f"eth_getLogs coverage failed for {start}-{end}"], False
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            return [], [f"eth_getLogs coverage failed for {start}-{end}"], False
        rows.extend(result)
        if len(rows) >= max_logs:
            truncated = True
            break
    if truncated:
        return [], [], True
    rows.sort(key=lambda row: (block_number(row), log_index(row)))
    return rows, errors, truncated


def bounded_bootstrap_transfer_logs(
    chain: str,
    token: str,
    requested_from_block: int,
    to_block: int,
) -> tuple[list[dict[str, Any]], list[str], bool, int, dict[str, Any]]:
    max_window = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_BOOTSTRAP_MAX_BLOCKS", "2400")),
    )
    min_window = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_BOOTSTRAP_MIN_BLOCKS", "16")),
    )
    max_attempts = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_BOOTSTRAP_MAX_ATTEMPTS", "7")),
    )
    span = min(max_window, max(1, to_block - requested_from_block + 1))
    from_block = max(requested_from_block, to_block - span + 1)
    attempts = 0
    logs: list[dict[str, Any]] = []
    errors: list[str] = []
    truncated = True
    while attempts < max_attempts:
        attempts += 1
        logs, errors, truncated = transfer_logs(
            chain,
            token,
            from_block,
            to_block,
        )
        if errors or not truncated:
            break
        current_span = to_block - from_block + 1
        if current_span <= min_window:
            break
        next_span = max(min_window, current_span // 2)
        if next_span >= current_span:
            break
        from_block = to_block - next_span + 1
    return (
        logs,
        errors,
        truncated,
        from_block,
        {
            "active": True,
            "requested_from_block": requested_from_block,
            "selected_from_block": from_block,
            "attempt_count": attempts,
            "complete_selected_window": not errors and not truncated,
        },
    )


def bounded_incremental_transfer_logs(
    chain: str,
    token: str,
    from_block: int,
    requested_to_block: int,
) -> tuple[list[dict[str, Any]], list[str], bool, int, dict[str, Any]]:
    max_window = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_CATCHUP_MAX_BLOCKS", "8000")),
    )
    min_window = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_CATCHUP_MIN_BLOCKS", "16")),
    )
    max_attempts = max(
        1,
        int(os.environ.get("ALPHA_HOLDER_CATCHUP_MAX_ATTEMPTS", "10")),
    )
    selected_to = min(
        requested_to_block,
        from_block + max_window - 1,
    )
    attempts = 0
    logs: list[dict[str, Any]] = []
    errors: list[str] = []
    truncated = True
    while attempts < max_attempts:
        attempts += 1
        logs, errors, truncated = transfer_logs(
            chain,
            token,
            from_block,
            selected_to,
        )
        if errors or not truncated:
            break
        current_span = selected_to - from_block + 1
        if current_span <= min_window:
            break
        next_span = max(min_window, current_span // 2)
        if next_span >= current_span:
            break
        selected_to = from_block + next_span - 1
    complete_selected = not errors and not truncated
    return (
        logs,
        errors,
        truncated,
        selected_to,
        {
            "applicable": True,
            "active": selected_to < requested_to_block,
            "requested_to_block": requested_to_block,
            "selected_to_block": selected_to,
            "attempt_count": attempts,
            "complete_selected_window": complete_selected,
            "complete_requested_window": (
                complete_selected and selected_to == requested_to_block
            ),
        },
    )


def apply_transfers(balances: dict[str, int], logs: list[dict[str, Any]]) -> dict[str, int]:
    for row in logs:
        topics = row.get("topics") or []
        if len(topics) < 3:
            continue
        from_addr = address_from_topic(topics[1])
        to_addr = address_from_topic(topics[2])
        amount = int(row.get("data") or "0x0", 16)
        if from_addr != ZERO_ADDRESS:
            balances[from_addr] = balances.get(from_addr, 0) - amount
        if to_addr != ZERO_ADDRESS:
            balances[to_addr] = balances.get(to_addr, 0) + amount
    return {addr: value for addr, value in balances.items() if value != 0}


def watch_address_labels(config: dict[str, Any], symbol: str, chain: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in config.get("items", []):
        if str(item.get("symbol", "")).upper() != symbol:
            continue
        for row in item.get("watch_addresses", []):
            row_chain = str(row.get("chain", chain)).lower()
            address = norm(row.get("address"))
            if row_chain == chain and is_address(address):
                rows[address] = row
    return rows


def config_item_for_contract(
    config: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
) -> dict[str, Any]:
    token = norm(token)
    for item in config.get("items", []):
        if str(item.get("symbol") or item.get("name") or "").upper() != symbol:
            continue
        if any(
            str(row.get("chain") or "").lower() == chain
            and norm(row.get("address")) == token
            for row in item.get("contracts", [])
            if isinstance(row, dict)
        ):
            return item
    return {}


def configured_cex_addresses(item: dict[str, Any], chain: str) -> dict[str, dict[str, str]]:
    addresses: dict[str, dict[str, str]] = {}
    for key in CEX_ADDRESS_KEYS:
        for raw in item.get(key, []) or []:
            row = raw if isinstance(raw, dict) else {}
            row_chain = str(row.get("chain") or chain).lower()
            address = norm(row.get("address") if row else raw)
            if row_chain != chain or not is_address(address):
                continue
            addresses[address] = {
                "kind": "cex",
                "role": str(row.get("role") or "cex_deposit"),
                "source": f"config:{key}",
            }
    for row in item.get("watch_addresses", []) or []:
        if not isinstance(row, dict):
            continue
        row_chain = str(row.get("chain") or chain).lower()
        address = norm(row.get("address"))
        role = str(row.get("role") or "").lower()
        if row_chain != chain or not is_address(address) or role not in CEX_ROLES:
            continue
        addresses[address] = {
            "kind": "cex",
            "role": role,
            "source": "config:watch_addresses",
        }
    return addresses


def opening_time_for_item(item: dict[str, Any], chain: str) -> datetime | None:
    starts = [
        parsed
        for row in item.get("pool_ids", [])
        if isinstance(row, dict)
        and str(row.get("chain") or chain).lower() == chain
        and (parsed := parse_utc8(row.get("start_time_utc8"))) is not None
    ]
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    for key in ("opening_time_utc", "opening_time_utc8"):
        parsed = parse_iso(facts.get(key)) if key.endswith("_utc") else parse_utc8(facts.get(key))
        if parsed is not None:
            starts.append(parsed)
    if not starts:
        return None
    current = now_utc()
    past = [value for value in starts if value <= current]
    return max(past) if past else min(starts)


def retention_window(item: dict[str, Any], chain: str) -> dict[str, Any]:
    opening = opening_time_for_item(item, chain)
    if opening is None:
        return {
            "status": "not_required",
            "reason": "opening_time_unavailable",
            "opening_time_utc": "",
            "age_hours": None,
        }
    age_hours = (now_utc() - opening).total_seconds() / 3600
    if age_hours < RETENTION_FLOW_START_HOURS:
        status = "not_required"
        reason = "before_opening"
    elif age_hours > RETENTION_FLOW_DAYS * 24:
        status = "not_required"
        reason = "retention_window_expired"
    else:
        status = "active"
        reason = "opening_to_30d_retention"
    return {
        "status": status,
        "reason": reason,
        "opening_time_utc": opening.isoformat(),
        "age_hours": round(age_hours, 2),
    }


def add_retention_actor(
    actors: dict[str, dict[str, set[str]]],
    address: str,
    *,
    kind: str,
    role: str,
    source: str,
) -> None:
    address = norm(address)
    if not is_address(address):
        return
    actor = actors.setdefault(address, {"kinds": set(), "roles": set(), "sources": set()})
    actor["kinds"].add(kind)
    actor["roles"].add(role)
    actor["sources"].add(source)


def opening_retention_scope(
    payload: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
) -> tuple[
    dict[str, dict[str, set[str]]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    actors: dict[str, dict[str, set[str]]] = {}
    evidence_by_tx: dict[str, list[dict[str, Any]]] = {}
    matching_event_count = 0
    complete_event_count = 0
    for event in payload.get("events", []):
        event_token = norm((event.get("token") or {}).get("address"))
        if (
            str(event.get("symbol") or "").upper() != symbol
            or str(event.get("chain") or "").lower() != chain
            or event_token != norm(token)
        ):
            continue
        matching_event_count += 1
        if event.get("opening_buyer_scope_complete") is True:
            complete_event_count += 1
            for address in (
                event.get("opening_buyer_scope_addresses") or []
            ):
                add_retention_actor(
                    actors,
                    norm(address),
                    kind="opening_cohort_recipient",
                    role="opening_cohort_recipient",
                    source="opening_scope",
                )
        for row in event.get("rows", []):
            if not isinstance(row, dict) or decimal_from(row.get("token_bought")) <= 0:
                continue
            buyer = norm(row.get("buyer"))
            trace = row.get("buyer_trace") if isinstance(row.get("buyer_trace"), dict) else {}
            if (
                not is_address(buyer)
                or row.get("buyer_exclusion_reason")
                or trace.get("subject_exclusion_reason")
            ):
                continue
            add_retention_actor(
                actors,
                buyer,
                kind="opening_buyer",
                role="opening_buyer",
                source="opening",
            )
            for evidence in trace.get("confirmed_sell_evidence", []) or []:
                if not isinstance(evidence, dict):
                    continue
                tx_hash = norm(evidence.get("tx"))
                if (
                    len(tx_hash) != 66
                    or str(evidence.get("route") or "") != "direct"
                    or norm(evidence.get("recipient")) != buyer
                    or decimal_from(evidence.get("quote_received")) <= 0
                ):
                    continue
                evidence_by_tx.setdefault(tx_hash, []).append(
                    {
                        "tx": tx_hash,
                        "log_index": int(evidence.get("log_index") or 0),
                        "quote_received": str(evidence.get("quote_received") or "0"),
                        "route": "direct",
                        "recipient": buyer,
                    }
                )
    return (
        actors,
        evidence_by_tx,
        {
            "matching_event_count": matching_event_count,
            "complete_event_count": complete_event_count,
            "complete": bool(
                matching_event_count > 0
                and complete_event_count == matching_event_count
            ),
        },
    )


def project_retention_scope(
    payload: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
) -> dict[str, dict[str, set[str]]]:
    actors: dict[str, dict[str, set[str]]] = {}
    for project in payload.get("projects", []):
        if str(project.get("symbol") or "").upper() != symbol:
            continue
        for contract in project.get("contracts", []):
            if (
                str(contract.get("chain") or "").lower() != chain
                or norm(contract.get("address")) != norm(token)
            ):
                continue
            for row in contract.get("watch_addresses", []):
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role") or "").strip().lower()
                if (
                    str(row.get("identity_status") or "").strip().lower() != "verified"
                    or role not in RETENTION_PROJECT_ROLES
                ):
                    continue
                add_retention_actor(
                    actors,
                    norm(row.get("address")),
                    kind="verified_project",
                    role=role,
                    source="project",
                )
    return actors


def merge_retention_actors(
    *groups: dict[str, dict[str, set[str]]],
) -> dict[str, dict[str, set[str]]]:
    merged: dict[str, dict[str, set[str]]] = {}
    for group in groups:
        for address, actor in group.items():
            for kind in actor.get("kinds", set()):
                for role in actor.get("roles", set()) or {kind}:
                    for source in actor.get("sources", set()) or {"unknown"}:
                        add_retention_actor(
                            merged,
                            address,
                            kind=kind,
                            role=role,
                            source=source,
                        )
    return merged


def serialize_retention_actors(
    actors: dict[str, dict[str, set[str]]],
) -> dict[str, dict[str, list[str]]]:
    return {
        address: {
            "kinds": sorted(actor.get("kinds", set())),
            "roles": sorted(actor.get("roles", set())),
            "sources": sorted(actor.get("sources", set())),
        }
        for address, actor in sorted(actors.items())
        if is_address(address)
    }


def deserialize_retention_actors(
    payload: Any,
) -> dict[str, dict[str, set[str]]]:
    actors: dict[str, dict[str, set[str]]] = {}
    if not isinstance(payload, dict):
        return actors
    for address, actor in payload.items():
        if not is_address(address) or not isinstance(actor, dict):
            continue
        for kind in actor.get("kinds", []) or []:
            for role in actor.get("roles", []) or [kind]:
                for source in actor.get("sources", []) or ["state"]:
                    add_retention_actor(
                        actors,
                        address,
                        kind=str(kind),
                        role=str(role),
                        source=str(source),
                    )
    return actors


def opening_only_retention_actors(
    actors: dict[str, dict[str, set[str]]],
) -> dict[str, dict[str, set[str]]]:
    opening_kinds = {
        "opening_buyer",
        "opening_cohort_recipient",
    }
    filtered: dict[str, dict[str, set[str]]] = {}
    for address, actor in actors.items():
        kinds = actor.get("kinds", set()) & opening_kinds
        if not kinds:
            continue
        for kind in kinds:
            for role in actor.get("roles", set()) or {kind}:
                for source in actor.get("sources", set()) or {
                    "opening_state"
                }:
                    add_retention_actor(
                        filtered,
                        address,
                        kind=kind,
                        role=role,
                        source=source,
                    )
    return filtered


def opening_actor_scope_hash(
    actors: dict[str, dict[str, set[str]]],
) -> str:
    payload = serialize_retention_actors(
        opening_only_retention_actors(actors)
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def retention_scope_hash(
    actors: dict[str, dict[str, set[str]]],
    cex_addresses: dict[str, dict[str, str]],
) -> str:
    payload = {
        "actors": serialize_retention_actors(actors),
        "cex_addresses": sorted(
            address
            for address in cex_addresses
            if is_address(address)
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def retention_evidence_scope(
    item: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
    context: dict[str, Any],
    persisted_actors: dict[str, dict[str, set[str]]] | None = None,
    persisted_opening_scope_complete: bool = False,
) -> tuple[
    dict[str, dict[str, set[str]]],
    dict[str, dict[str, str]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    (
        opening_actors,
        evidence_by_tx,
        opening_metadata,
    ) = opening_retention_scope(
        context.get("opening") or {},
        symbol,
        chain,
        token,
    )
    project_actors = project_retention_scope(
        context.get("project") or {},
        symbol,
        chain,
        token,
    )
    persisted_opening_actors = opening_only_retention_actors(
        persisted_actors or {}
    )
    actors = merge_retention_actors(
        persisted_opening_actors,
        opening_actors,
        project_actors,
    )
    cex_addresses = configured_cex_addresses(item, chain)
    for address, label in global_address_labels(chain).items():
        role = str(label.get("class") or "").lower()
        if role in CEX_ROLES:
            cex_addresses.setdefault(
                address,
                {
                    "kind": "cex",
                    "role": role,
                    "source": "global_address_label",
                },
            )
    persisted_opening_count = sum(
        1
        for actor in persisted_opening_actors.values()
        if actor.get("kinds", set())
        & {"opening_buyer", "opening_cohort_recipient"}
    )
    opening_scope_complete = (
        bool(opening_metadata.get("complete"))
        if int(opening_metadata.get("matching_event_count") or 0)
        > 0
        else bool(persisted_opening_scope_complete)
    )
    opening_scope_actors = opening_only_retention_actors(actors)
    return (
        actors,
        cex_addresses,
        evidence_by_tx,
        {
            **opening_metadata,
            "opening_scope_complete": opening_scope_complete,
            "persisted_opening_actor_count": persisted_opening_count,
            "opening_actor_count": len(opening_scope_actors),
            "opening_actor_scope_hash": (
                opening_actor_scope_hash(opening_scope_actors)
            ),
            "scope_state_schema_version": (
                RETENTION_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": retention_scope_hash(
                actors,
                cex_addresses,
            ),
        },
    )


def valid_hash32(value: Any) -> bool:
    return re.fullmatch(r"0x[a-f0-9]{64}", norm(str(value or ""))) is not None


def valid_sha256(value: Any) -> bool:
    return re.fullmatch(r"[a-f0-9]{64}", norm(str(value or ""))) is not None


def strict_unsigned_event_word(
    data: Any,
    index: int,
    bits: int,
) -> int | None:
    if (
        bits <= 0
        or bits > 256
        or not isinstance(data, str)
        or not data.startswith("0x")
    ):
        return None
    raw = data[2:]
    start = index * 64
    if (
        index < 0
        or len(raw) < start + 64
        or re.fullmatch(r"[0-9a-fA-F]{64}", raw[start:start + 64])
        is None
    ):
        return None
    value = int(raw[start:start + 64], 16)
    return value if value < 2**bits else None


def strict_signed_event_word(
    data: Any,
    index: int,
    bits: int,
) -> int | None:
    word = strict_unsigned_event_word(data, index, 256)
    if word is None or bits <= 0 or bits > 256:
        return None
    if bits == 256:
        return word - 2**256 if word >= 2**255 else word
    mask = 2**bits - 1
    low = word & mask
    high = word >> bits
    if low >= 2 ** (bits - 1):
        if high != 2 ** (256 - bits) - 1:
            return None
        return low - 2**bits
    return low if high == 0 else None


def strict_swap_static_fields(data: Any, event_kind: str) -> bool:
    if event_kind == "v3_swap":
        return bool(
            strict_abi_event_word_count(data) == 5
            and strict_unsigned_event_word(data, 2, 160) is not None
            and strict_unsigned_event_word(data, 3, 128) is not None
            and strict_signed_event_word(data, 4, 24) is not None
        )
    if event_kind == "v4_swap":
        return bool(
            strict_abi_event_word_count(data) == 7
            and strict_unsigned_event_word(data, 2, 160) is not None
            and strict_unsigned_event_word(data, 3, 128) is not None
            and strict_signed_event_word(data, 4, 24) is not None
            and strict_unsigned_event_word(data, 5, 24) is not None
            and strict_unsigned_event_word(data, 6, 16) is not None
        )
    return False


def strict_indexed_event_word(topic: Any, bits: int) -> int | None:
    text = norm(str(topic or ""))
    if re.fullmatch(r"0x[a-f0-9]{64}", text) is None:
        return None
    value = int(text[2:], 16)
    if bits == 160:
        return value if value < 2**160 else None
    if bits <= 0 or bits > 256:
        return None
    if bits == 256:
        return value
    mask = 2**bits - 1
    low = value & mask
    high = value >> bits
    if low >= 2 ** (bits - 1):
        if high != 2 ** (256 - bits) - 1:
            return None
        return low - 2**bits
    return low if high == 0 else None


def strict_liquidity_event_fields(
    event_kind: str,
    topics: list[Any],
    data: Any,
) -> bool:
    if event_kind == "v3_swap":
        return bool(
            strict_indexed_event_word(topics[1], 160) is not None
            and strict_indexed_event_word(topics[2], 160) is not None
            and strict_swap_static_fields(data, event_kind)
        )
    if event_kind in {"v3_mint", "v3_burn", "v3_collect"}:
        indexed_valid = bool(
            strict_indexed_event_word(topics[1], 160) is not None
            and strict_indexed_event_word(topics[2], 24) is not None
            and strict_indexed_event_word(topics[3], 24) is not None
        )
        if event_kind == "v3_mint":
            return bool(
                indexed_valid
                and strict_unsigned_event_word(data, 0, 160)
                is not None
                and strict_unsigned_event_word(data, 1, 128)
                is not None
            )
        if event_kind == "v3_burn":
            return bool(
                indexed_valid
                and strict_unsigned_event_word(data, 0, 128)
                is not None
            )
        return bool(
            indexed_valid
            and strict_unsigned_event_word(data, 0, 160) is not None
            and strict_unsigned_event_word(data, 1, 128) is not None
            and strict_unsigned_event_word(data, 2, 128) is not None
        )
    if event_kind == "v4_swap":
        return bool(
            strict_indexed_event_word(topics[2], 160) is not None
            and strict_swap_static_fields(data, event_kind)
        )
    if event_kind == "v4_modify_liquidity":
        return bool(
            strict_indexed_event_word(topics[2], 160) is not None
            and strict_signed_event_word(data, 0, 24) is not None
            and strict_signed_event_word(data, 1, 24) is not None
            and strict_signed_event_word(data, 2, 256) is not None
        )
    return False


def liquidity_pool_scope_hash(pools: list[dict[str, Any]]) -> str:
    stable_rows = [
        {
            key: row.get(key)
            for key in (
                "protocol",
                "address",
                "factory",
                "pool_id",
                "v4_manager_type",
                "token0",
                "token1",
                "quote_token",
                "quote_decimals",
                "quote_symbol",
                "fee",
            )
            if key in row
        }
        for row in sorted(
            pools,
            key=lambda value: (
                str(value.get("protocol") or ""),
                str(value.get("address") or ""),
                str(value.get("pool_id") or ""),
            ),
        )
    ]
    return hashlib.sha256(
        json.dumps(
            stable_rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def normalized_verified_liquidity_pools(
    pools: Any,
    token: str,
) -> list[dict[str, Any]] | None:
    if not isinstance(pools, list):
        return None
    normalized: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in pools:
        if not isinstance(raw, dict):
            return None
        protocol = str(raw.get("protocol") or "").lower()
        address = norm(raw.get("address"))
        token0 = norm(raw.get("token0"))
        token1 = norm(raw.get("token1"))
        quote_token = norm(raw.get("quote_token"))
        try:
            quote_decimals = int(raw.get("quote_decimals"))
        except (TypeError, ValueError):
            return None
        quote_symbol = str(raw.get("quote_symbol") or "").strip().upper()
        if (
            protocol not in {"v3", "v4_cl"}
            or not is_address(address)
            or token0 == token1
            or not is_address(token0)
            or not is_address(token1)
            or norm(token) not in {token0, token1}
            or quote_token not in {token0, token1}
            or quote_token == norm(token)
            or quote_decimals < 0
            or quote_decimals > 36
            or not quote_symbol
        ):
            return None
        if protocol == "v3":
            factory = norm(raw.get("factory"))
            try:
                fee = int(raw.get("fee"))
            except (TypeError, ValueError):
                return None
            if not is_address(factory) or fee <= 0:
                return None
            row = {
                "protocol": "v3",
                "address": address,
                "factory": factory,
                "token0": token0,
                "token1": token1,
                "quote_token": quote_token,
                "quote_decimals": quote_decimals,
                "quote_symbol": quote_symbol,
                "fee": fee,
            }
            identity = ("v3", address, "")
        else:
            pool_id = norm(raw.get("pool_id"))
            manager_type = str(raw.get("v4_manager_type") or "").lower()
            pool_manager = norm(raw.get("pool_manager") or address)
            if (
                manager_type != "cl"
                or address == PANCAKE_INFINITY_BIN_POOL_MANAGER
                or pool_manager != address
                or not valid_hash32(pool_id)
            ):
                return None
            row = {
                "protocol": "v4_cl",
                "address": address,
                "pool_id": pool_id,
                "v4_manager_type": "cl",
                "token0": token0,
                "token1": token1,
                "quote_token": quote_token,
                "quote_decimals": quote_decimals,
                "quote_symbol": quote_symbol,
            }
            if str(raw.get("fee") or "").isdigit():
                row["fee"] = int(raw["fee"])
            identity = ("v4_cl", address, pool_id)
        previous = normalized.get(identity)
        if previous is not None and previous != row:
            return None
        normalized[identity] = row
    return sorted(
        normalized.values(),
        key=lambda value: (
            value["protocol"],
            value["address"],
            str(value.get("pool_id") or ""),
        ),
    )


def opening_verified_pool_scope(
    payload: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
    persisted_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_events = payload.get("events", [])
    if (
        not isinstance(raw_events, list)
        or any(not isinstance(event, dict) for event in raw_events)
    ):
        return {
            "status": "current_opening_payload_invalid",
            "complete": False,
            "source": "opening",
            "matching_event_count": 0,
            "pool_scope": [],
            "pool_count": 0,
            "v3_pool_count": 0,
            "v4_pool_count": 0,
            "scope_hash": "",
        }
    identity_candidates = [
        event
        for event in raw_events
        if str(event.get("symbol") or "").upper() == symbol
        and str(event.get("chain") or "").lower() == chain
    ]
    candidate_tokens = [
        norm(event["token"].get("address"))
        if isinstance(event.get("token"), dict)
        else ""
        for event in identity_candidates
    ]
    if identity_candidates and any(
        candidate != norm(token) for candidate in candidate_tokens
    ):
        return {
            "status": "current_opening_identity_invalid",
            "complete": False,
            "source": "opening",
            "matching_event_count": len(identity_candidates),
            "pool_scope": [],
            "pool_count": 0,
            "v3_pool_count": 0,
            "v4_pool_count": 0,
            "scope_hash": "",
        }
    matching = identity_candidates
    if not matching:
        persisted_scope = persisted_scope or {}
        persisted_pools = normalized_verified_liquidity_pools(
            persisted_scope.get("pool_scope"),
            token,
        )
        persisted_hash = str(persisted_scope.get("scope_hash") or "")
        valid_persisted = bool(
            int(
                persisted_scope.get("scope_state_schema_version")
                or 0
            )
            == LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            and persisted_pools
            and len(persisted_hash) == 64
            and all(
                character in "0123456789abcdef"
                for character in persisted_hash.lower()
            )
            and liquidity_pool_scope_hash(persisted_pools)
            == persisted_hash
        )
        if valid_persisted:
            return {
                "status": "persisted_verified_scope",
                "complete": True,
                "source": "state",
                "matching_event_count": 0,
                "pool_scope": persisted_pools,
                "pool_count": len(persisted_pools),
                "v3_pool_count": sum(
                    row["protocol"] == "v3"
                    for row in persisted_pools
                ),
                "v4_pool_count": sum(
                    row["protocol"] == "v4_cl"
                    for row in persisted_pools
                ),
                "scope_hash": persisted_hash,
            }
        return {
            "status": "opening_event_unavailable",
            "complete": False,
            "source": "none",
            "matching_event_count": 0,
            "pool_scope": [],
            "pool_count": 0,
            "v3_pool_count": 0,
            "v4_pool_count": 0,
            "scope_hash": "",
        }

    pools: list[dict[str, Any]] = []
    for event in matching:
        v3_scope = event.get("opening_v3_pool_scope")
        v4_scope = event.get("opening_v4_pool_scope")
        quote_meta = (
            event.get("quote")
            if isinstance(event.get("quote"), dict)
            else {}
        )
        quote = norm(quote_meta.get("address"))
        quote_symbol = str(quote_meta.get("symbol") or "").strip().upper()
        try:
            quote_decimals = int(quote_meta.get("decimals"))
        except (TypeError, ValueError):
            quote_decimals = -1
        if (
            event.get("status") != "opened"
            or not is_address(quote)
            or quote == norm(token)
            or not quote_symbol
            or quote_decimals < 0
            or quote_decimals > 36
            or not isinstance(v3_scope, dict)
            or v3_scope.get("schema")
            != "opening_v3_factory_matrix.v2"
            or v3_scope.get("complete") is not True
            or v3_scope.get("snapshot_coherent") is not True
            or not valid_sha256(v3_scope.get("configuration_hash"))
            or not valid_hash32(v3_scope.get("as_of_block_hash"))
            or int(v3_scope.get("as_of_block") or 0) <= 0
            or not isinstance(v3_scope.get("pools"), list)
            or any(
                not isinstance(row, dict)
                for row in v3_scope.get("pools", [])
            )
            or not isinstance(v4_scope, dict)
            or v4_scope.get("schema")
            != "opening_v4_manager_scope.v2"
            or v4_scope.get("complete") is not True
            or not isinstance(v4_scope.get("pools"), list)
            or any(
                not isinstance(row, dict)
                for row in v4_scope.get("pools", [])
            )
            or (
                v4_scope.get("applicable") is not True
                and bool(v4_scope.get("pools"))
            )
        ):
            return {
                "status": "current_opening_scope_incomplete",
                "complete": False,
                "source": "opening",
                "matching_event_count": len(matching),
                "pool_scope": [],
                "pool_count": 0,
                "v3_pool_count": 0,
                "v4_pool_count": 0,
                "scope_hash": "",
            }
        if v4_scope.get("applicable") is True and (
            v4_scope.get("snapshot_coherent") is not True
            or not valid_sha256(v4_scope.get("configuration_hash"))
            or not valid_hash32(v4_scope.get("as_of_block_hash"))
            or int(v4_scope.get("as_of_block") or 0) <= 0
        ):
            return {
                "status": "current_opening_scope_incomplete",
                "complete": False,
                "source": "opening",
                "matching_event_count": len(matching),
                "pool_scope": [],
                "pool_count": 0,
                "v3_pool_count": 0,
                "v4_pool_count": 0,
                "scope_hash": "",
            }
        v3_pools = []
        for row in v3_scope.get("pools", []):
            if not isinstance(row, dict):
                continue
            row_quote = norm(row.get("quote_token"))
            row_quote_symbol = str(
                row.get("quote_symbol") or ""
            ).strip().upper()
            try:
                row_quote_decimals = int(row.get("quote_decimals"))
            except (TypeError, ValueError):
                row_quote_decimals = -1
            if not (
                is_address(row_quote)
                and row_quote_symbol
                and 0 <= row_quote_decimals <= 36
            ):
                row_quote = quote
                row_quote_symbol = quote_symbol
                row_quote_decimals = quote_decimals
            v3_pools.append(
                {
                    **row,
                    "protocol": "v3",
                    "quote_token": row_quote,
                    "quote_decimals": row_quote_decimals,
                    "quote_symbol": row_quote_symbol,
                }
            )
        v4_pools = [
            {
                **row,
                "protocol": "v4_cl",
                "quote_token": quote,
                "quote_decimals": quote_decimals,
                "quote_symbol": quote_symbol,
            }
            for row in v4_scope.get("pools", [])
            if isinstance(row, dict)
        ]
        normalized = normalized_verified_liquidity_pools(
            v3_pools + v4_pools,
            token,
        )
        if normalized is None:
            return {
                "status": "current_opening_scope_invalid",
                "complete": False,
                "source": "opening",
                "matching_event_count": len(matching),
                "pool_scope": [],
                "pool_count": 0,
                "v3_pool_count": 0,
                "v4_pool_count": 0,
                "scope_hash": "",
            }
        if any(
            norm(token) not in {row.get("token0"), row.get("token1")}
            or row.get("quote_token")
            not in {row.get("token0"), row.get("token1")}
            or row.get("quote_token") == norm(token)
            for row in normalized
        ):
            return {
                "status": "current_opening_scope_invalid",
                "complete": False,
                "source": "opening",
                "matching_event_count": len(matching),
                "pool_scope": [],
                "pool_count": 0,
                "v3_pool_count": 0,
                "v4_pool_count": 0,
                "scope_hash": "",
            }
        pools.extend(normalized)
    normalized_pools = normalized_verified_liquidity_pools(pools, token)
    if normalized_pools is None:
        return {
            "status": "current_opening_scope_invalid",
            "complete": False,
            "source": "opening",
            "matching_event_count": len(matching),
            "pool_scope": [],
            "pool_count": 0,
            "v3_pool_count": 0,
            "v4_pool_count": 0,
            "scope_hash": "",
        }
    if not normalized_pools:
        return {
            "status": "no_verified_pool",
            "complete": True,
            "source": "opening",
            "matching_event_count": len(matching),
            "pool_scope": [],
            "pool_count": 0,
            "v3_pool_count": 0,
            "v4_pool_count": 0,
            "scope_hash": "",
        }
    scope_hash = liquidity_pool_scope_hash(normalized_pools)
    return {
        "status": "verified_pool_scope",
        "complete": True,
        "source": "opening",
        "matching_event_count": len(matching),
        "pool_scope": normalized_pools,
        "pool_count": len(normalized_pools),
        "v3_pool_count": sum(
            row["protocol"] == "v3" for row in normalized_pools
        ),
        "v4_pool_count": sum(
            row["protocol"] == "v4_cl" for row in normalized_pools
        ),
        "scope_hash": scope_hash,
    }


def targeted_retention_transfer_logs(
    chain: str,
    token: str,
    from_block: int,
    to_block: int,
    actors: dict[str, dict[str, set[str]]],
    cex_addresses: dict[str, dict[str, str]],
) -> tuple[
    list[dict[str, Any]],
    list[str],
    bool,
    dict[str, Any],
]:
    actor_addresses = sorted(
        address for address in actors if is_address(address)
    )
    cex_address_rows = sorted(
        address
        for address in cex_addresses
        if is_address(address)
    )
    topic_batch_size = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_TOPIC_BATCH_SIZE",
                "128",
            )
        ),
    )
    scopes: list[tuple[str, set[str], list[Any]]] = []
    for start in range(
        0,
        len(actor_addresses),
        topic_batch_size,
    ):
        address_batch = set(
            actor_addresses[start : start + topic_batch_size]
        )
        topics = [topic_address(address) for address in address_batch]
        scopes.append(
            (
                "tracked_actor_outgoing",
                address_batch,
                [
                    TRANSFER_TOPIC,
                    topics[0] if len(topics) == 1 else sorted(topics),
                ],
            )
        )
    for start in range(
        0,
        len(cex_address_rows),
        topic_batch_size,
    ):
        address_batch = set(
            cex_address_rows[start : start + topic_batch_size]
        )
        topics = [topic_address(address) for address in address_batch]
        scopes.append(
            (
                "cex_incoming",
                address_batch,
                [
                    TRANSFER_TOPIC,
                    None,
                    topics[0] if len(topics) == 1 else sorted(topics),
                ],
            )
        )
    metadata = {
        "coverage_mode": "targeted_indexed_topics",
        "query_scope_complete": False,
        "query_count": 0,
        "tracked_actor_count": len(actor_addresses),
        "cex_address_count": len(cex_address_rows),
        "scope_kind_count": int(bool(actor_addresses))
        + int(bool(cex_address_rows)),
        "scope_batch_count": len(scopes),
        "topic_batch_size": topic_batch_size,
    }
    if from_block > to_block:
        return [], ["retention indexed log scan window invalid"], False, metadata
    if not scopes:
        return [], ["retention indexed log scope is empty"], False, metadata

    chunk_blocks = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LOG_CHUNK_BLOCKS",
                "8000",
            )
        ),
    )
    query_chunk_count = (
        (to_block - from_block + 1 + chunk_blocks - 1)
        // chunk_blocks
    )
    metadata["query_chunk_count"] = query_chunk_count
    metadata["expected_query_count"] = (
        len(scopes) * query_chunk_count
    )
    max_logs = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_MAX_LOGS_PER_TOKEN",
                "20000",
            )
        ),
    )
    provider_row_limit = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_PROVIDER_MAX_ROWS_PER_QUERY",
                "10000",
            )
        ),
    )
    metadata["provider_row_limit"] = provider_row_limit
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    for start in range(from_block, to_block + 1, chunk_blocks):
        end = min(to_block, start + chunk_blocks - 1)
        for scope_name, address_batch, topics in scopes:
            query = {
                "address": token,
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "topics": topics,
            }
            metadata["query_count"] += 1
            try:
                result = holder_rpc_call(
                    chain,
                    "eth_getLogs",
                    [query],
                )
            except Exception:
                return (
                    [],
                    [
                        (
                            "retention indexed eth_getLogs coverage "
                            f"failed for {start}-{end}"
                        )
                    ],
                    False,
                    metadata,
                )
            if (
                not isinstance(result, list)
                or any(not isinstance(row, dict) for row in result)
            ):
                return (
                    [],
                    [
                        (
                            "retention indexed eth_getLogs response "
                            f"invalid for {start}-{end}"
                        )
                    ],
                    False,
                    metadata,
                )
            if len(result) >= provider_row_limit:
                return [], [], True, metadata
            for row in result:
                try:
                    row_address = norm(row["address"])
                    topics_row = row["topics"]
                    if (
                        row_address != norm(token)
                        or not is_address(row_address)
                        or not isinstance(topics_row, list)
                        or len(topics_row) != 3
                        or norm(topics_row[0]) != TRANSFER_TOPIC
                    ):
                        raise ValueError
                    if "removed" in row and (
                        type(row["removed"]) is not bool
                        or row["removed"] is True
                    ):
                        raise ValueError
                    for topic in topics_row[1:3]:
                        topic_text = norm(str(topic))
                        if (
                            len(topic_text) != 66
                            or not topic_text.startswith("0x")
                            or any(
                                character not in "0123456789abcdef"
                                for character in topic_text[2:]
                            )
                        ):
                            raise ValueError
                    tx_hash = norm(row["transactionHash"])
                    if (
                        len(tx_hash) != 66
                        or not tx_hash.startswith("0x")
                        or any(
                            character not in "0123456789abcdef"
                            for character in tx_hash[2:]
                        )
                    ):
                        raise ValueError
                    block_text = row.get("blockNumber")
                    log_index_text = row.get("logIndex")
                    if (
                        not isinstance(block_text, str)
                        or re.fullmatch(
                            r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)",
                            block_text,
                        )
                        is None
                        or not isinstance(log_index_text, str)
                        or re.fullmatch(
                            r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)",
                            log_index_text,
                        )
                        is None
                    ):
                        raise ValueError
                    row_block = int(block_text, 16)
                    if row_block < start or row_block > end:
                        raise ValueError
                    row_log_index = int(log_index_text, 16)
                    from_address = address_from_topic(
                        str(topics_row[1])
                    )
                    to_address = address_from_topic(
                        str(topics_row[2])
                    )
                    if (
                        scope_name == "tracked_actor_outgoing"
                        and from_address not in address_batch
                    ) or (
                        scope_name == "cex_incoming"
                        and to_address not in address_batch
                    ):
                        raise ValueError
                    data_text = norm(str(row.get("data") or ""))
                    if (
                        not data_text.startswith("0x")
                        or len(data_text) != 66
                        or any(
                            character not in "0123456789abcdef"
                            for character in data_text[2:]
                        )
                    ):
                        raise ValueError
                    int(data_text, 16)
                    identity = (
                        tx_hash,
                        row_log_index,
                    )
                except (KeyError, TypeError, ValueError):
                    return (
                        [],
                        ["retention indexed eth_getLogs row identity invalid"],
                        False,
                        metadata,
                    )
                previous = seen.get(identity)
                if previous is None:
                    seen[identity] = row
                elif previous != row:
                    return (
                        [],
                        [
                            (
                                "retention indexed eth_getLogs duplicate "
                                "identity conflict"
                            )
                        ],
                        False,
                        metadata,
                    )
                if len(seen) >= max_logs:
                    return [], [], True, metadata
    rows = sorted(
        seen.values(),
        key=lambda row: (block_number(row), log_index(row)),
    )
    metadata["query_scope_complete"] = bool(
        metadata["query_count"]
        == metadata["expected_query_count"]
    )
    return rows, [], False, metadata


def bounded_targeted_retention_logs(
    chain: str,
    token: str,
    from_block: int,
    requested_to_block: int,
    actors: dict[str, dict[str, set[str]]],
    cex_addresses: dict[str, dict[str, str]],
) -> tuple[
    list[dict[str, Any]],
    list[str],
    bool,
    int,
    dict[str, Any],
]:
    max_window = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_CATCHUP_MAX_BLOCKS",
                "100000",
            )
        ),
    )
    min_window = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_CATCHUP_MIN_BLOCKS",
                "16",
            )
        ),
    )
    max_attempts = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_CATCHUP_MAX_ATTEMPTS",
                "14",
            )
        ),
    )
    selected_to = min(
        requested_to_block,
        from_block + max_window - 1,
    )
    attempts = 0
    logs: list[dict[str, Any]] = []
    errors: list[str] = []
    truncated = True
    metadata: dict[str, Any] = {}
    while attempts < max_attempts:
        attempts += 1
        logs, errors, truncated, metadata = (
            targeted_retention_transfer_logs(
                chain,
                token,
                from_block,
                selected_to,
                actors,
                cex_addresses,
            )
        )
        if errors or not truncated:
            break
        current_span = selected_to - from_block + 1
        if current_span <= min_window:
            break
        next_span = max(min_window, current_span // 2)
        if next_span >= current_span:
            break
        selected_to = from_block + next_span - 1
    complete_selected = not errors and not truncated
    metadata.update(
        {
            "applicable": True,
            "active": selected_to < requested_to_block,
            "requested_to_block": requested_to_block,
            "selected_to_block": selected_to,
            "attempt_count": attempts,
            "complete_selected_window": complete_selected,
            "complete_requested_window": bool(
                complete_selected
                and selected_to == requested_to_block
            ),
        }
    )
    return logs, errors, truncated, selected_to, metadata


def retention_liquidity_query_scopes(
    pools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    v3_pools = [
        pool for pool in pools if pool.get("protocol") == "v3"
    ]
    if v3_pools:
        addresses = sorted({pool["address"] for pool in v3_pools})
        scopes.append(
            {
                "address": addresses[0] if len(addresses) == 1 else addresses,
                "topics": [
                    sorted(
                        {
                            V3_SWAP_TOPIC,
                            V3_MINT_TOPIC,
                            V3_BURN_TOPIC,
                            V3_COLLECT_TOPIC,
                        }
                    )
                ],
                "event_specs": {
                    V3_SWAP_TOPIC: ("v3_swap", 3, 5),
                    V3_MINT_TOPIC: ("v3_mint", 4, 4),
                    V3_BURN_TOPIC: ("v3_burn", 4, 3),
                    V3_COLLECT_TOPIC: ("v3_collect", 4, 3),
                },
                "pool_by_key": {
                    pool["address"]: pool for pool in v3_pools
                },
                "protocol": "v3",
            }
        )
    v4_pools = [
        pool for pool in pools if pool.get("protocol") == "v4_cl"
    ]
    v4_by_manager: dict[str, list[dict[str, Any]]] = {}
    for pool in v4_pools:
        v4_by_manager.setdefault(pool["address"], []).append(pool)
    for manager, manager_pools in sorted(v4_by_manager.items()):
        pool_ids = sorted(
            {pool["pool_id"] for pool in manager_pools}
        )
        scopes.append(
            {
                "address": manager,
                "topics": [
                    sorted({V4_SWAP_TOPIC, MODIFY_LIQUIDITY_TOPIC}),
                    pool_ids[0] if len(pool_ids) == 1 else pool_ids,
                ],
                "event_specs": {
                    V4_SWAP_TOPIC: ("v4_swap", 3, 7),
                    MODIFY_LIQUIDITY_TOPIC: (
                        "v4_modify_liquidity",
                        3,
                        4,
                    ),
                },
                "pool_by_key": {
                    f"{pool['address']}:{pool['pool_id']}": pool
                    for pool in manager_pools
                },
                "protocol": "v4_cl",
            }
        )
    return scopes


def targeted_retention_liquidity_logs(
    chain: str,
    pools: list[dict[str, Any]],
    from_block: int,
    to_block: int,
) -> tuple[
    list[dict[str, Any]],
    list[str],
    bool,
    dict[str, Any],
]:
    scopes = retention_liquidity_query_scopes(pools)
    metadata = {
        "coverage_mode": "verified_pool_indexed_topics",
        "query_scope_complete": False,
        "query_count": 0,
        "scope_batch_count": len(scopes),
        "pool_count": len(pools),
        "v3_pool_count": sum(
            row.get("protocol") == "v3" for row in pools
        ),
        "v4_pool_count": sum(
            row.get("protocol") == "v4_cl" for row in pools
        ),
        "v4_manager_count": len(
            {
                row.get("address")
                for row in pools
                if row.get("protocol") == "v4_cl"
            }
        ),
        "event_filter_count": sum(
            4 if row.get("protocol") == "v3" else 2
            for row in pools
        ),
    }
    if from_block > to_block:
        return [], ["liquidity retention scan window invalid"], False, metadata
    if not scopes:
        return [], ["liquidity retention pool scope is empty"], False, metadata
    configured_chunk_blocks = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS",
                "8000",
            )
        ),
    )
    chunk_blocks = (
        min(configured_chunk_blocks, 2000)
        if chain == "base"
        else configured_chunk_blocks
    )
    metadata["query_chunk_blocks"] = chunk_blocks
    query_chunk_count = (
        to_block - from_block + 1 + chunk_blocks - 1
    ) // chunk_blocks
    metadata["query_chunk_count"] = query_chunk_count
    metadata["expected_query_count"] = (
        len(scopes) * query_chunk_count
    )
    max_logs = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_MAX_LOGS",
                "20000",
            )
        ),
    )
    configured_provider_row_limit = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_PROVIDER_MAX_ROWS_PER_QUERY",
                str(LIQUIDITY_PROVIDER_ROW_LIMIT_HARD_CAP),
            )
        ),
    )
    provider_row_limit = min(
        configured_provider_row_limit,
        LIQUIDITY_PROVIDER_ROW_LIMIT_HARD_CAP,
    )
    metadata["provider_row_limit"] = provider_row_limit
    seen: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
    block_hash_by_number: dict[int, str] = {}
    for start in range(from_block, to_block + 1, chunk_blocks):
        end = min(to_block, start + chunk_blocks - 1)
        for scope in scopes:
            query = {
                "address": scope["address"],
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "topics": scope["topics"],
            }
            metadata["query_count"] += 1
            try:
                result = holder_rpc_call(
                    chain,
                    "eth_getLogs",
                    [query],
                )
            except Exception:
                return (
                    [],
                    [
                        "liquidity retention indexed eth_getLogs "
                        f"coverage failed for {start}-{end}"
                    ],
                    False,
                    metadata,
                )
            if (
                not isinstance(result, list)
                or any(not isinstance(row, dict) for row in result)
            ):
                return (
                    [],
                    [
                        "liquidity retention indexed eth_getLogs "
                        f"response invalid for {start}-{end}"
                    ],
                    False,
                    metadata,
                )
            if len(result) >= provider_row_limit:
                return [], [], True, metadata
            for raw in result:
                quantity_pattern = (
                    r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)"
                )
                if (
                    not isinstance(raw.get("blockNumber"), str)
                    or re.fullmatch(
                        quantity_pattern,
                        raw["blockNumber"],
                    )
                    is None
                    or not isinstance(raw.get("logIndex"), str)
                    or re.fullmatch(
                        quantity_pattern,
                        raw["logIndex"],
                    )
                    is None
                ):
                    return (
                        [],
                        ["liquidity retention RPC quantity invalid"],
                        False,
                        metadata,
                    )
                identity = strict_rpc_log_identity(raw, query)
                topics = raw.get("topics")
                topic0 = (
                    norm(topics[0])
                    if isinstance(topics, list) and topics
                    else ""
                )
                event_spec = scope["event_specs"].get(topic0)
                if event_spec is None:
                    return (
                        [],
                        ["liquidity retention event topic invalid"],
                        False,
                        metadata,
                    )
                event_kind, topic_count, word_count = event_spec
                if (
                    identity is None
                    or not isinstance(topics, list)
                    or len(topics) != topic_count
                    or strict_abi_event_word_count(raw.get("data"))
                    != word_count
                    or not strict_liquidity_event_fields(
                        event_kind,
                        topics,
                        raw.get("data"),
                    )
                ):
                    return (
                        [],
                        ["liquidity retention log identity or ABI invalid"],
                        False,
                        metadata,
                    )
                if scope["protocol"] == "v3":
                    pool = scope["pool_by_key"].get(
                        norm(raw.get("address"))
                    )
                else:
                    pool_id = norm(topics[1]) if len(topics) > 1 else ""
                    pool = scope["pool_by_key"].get(
                        f"{norm(raw.get('address'))}:{pool_id}"
                    )
                if not isinstance(pool, dict):
                    return (
                        [],
                        ["liquidity retention pool identity invalid"],
                        False,
                        metadata,
                    )
                if event_kind == "v3_swap":
                    amount0 = strict_v3_swap_amount(raw.get("data"), 0)
                    amount1 = strict_v3_swap_amount(raw.get("data"), 1)
                    swap_valid = bool(
                        amount0 is not None
                        and amount1 is not None
                        and amount0 != 0
                        and amount1 != 0
                        and (amount0 > 0) != (amount1 > 0)
                        and strict_swap_static_fields(
                            raw.get("data"),
                            event_kind,
                        )
                    )
                elif event_kind == "v4_swap":
                    amount0 = strict_v4_swap_amount(raw.get("data"), 0)
                    amount1 = strict_v4_swap_amount(raw.get("data"), 1)
                    swap_valid = bool(
                        amount0 is not None
                        and amount1 is not None
                        and amount0 != 0
                        and amount1 != 0
                        and (amount0 > 0) != (amount1 > 0)
                        and strict_swap_static_fields(
                            raw.get("data"),
                            event_kind,
                        )
                    )
                else:
                    swap_valid = True
                if not swap_valid:
                    return (
                        [],
                        ["liquidity retention swap ABI invalid"],
                        False,
                        metadata,
                    )
                order, tx_hash, block_hash = identity
                previous_block_hash = block_hash_by_number.get(order[0])
                if (
                    previous_block_hash is not None
                    and previous_block_hash != block_hash
                ):
                    return (
                        [],
                        [
                            "liquidity retention block hash conflict "
                            f"at block {order[0]}"
                        ],
                        False,
                        metadata,
                    )
                block_hash_by_number[order[0]] = block_hash
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "address": norm(raw.get("address")),
                            "block": order[0],
                            "block_hash": norm(raw.get("blockHash")),
                            "topics": [norm(topic) for topic in topics],
                            "data": norm(raw.get("data")),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                row = {
                    **raw,
                    "_retention_pool": copy.deepcopy(pool),
                    "_retention_event_kind": event_kind,
                }
                dedupe_key = (tx_hash, order[1])
                previous = seen.get(dedupe_key)
                if previous is None:
                    seen[dedupe_key] = (fingerprint, row)
                elif previous[0] != fingerprint:
                    return (
                        [],
                        ["liquidity retention duplicate identity conflict"],
                        False,
                        metadata,
                    )
                if len(seen) >= max_logs:
                    return [], [], True, metadata
    rows = sorted(
        (row for _fingerprint, row in seen.values()),
        key=lambda row: (block_number(row), log_index(row)),
    )
    metadata["query_scope_complete"] = bool(
        metadata["query_count"] == metadata["expected_query_count"]
    )
    return rows, [], False, metadata


def bounded_retention_liquidity_logs(
    chain: str,
    pools: list[dict[str, Any]],
    from_block: int,
    requested_to_block: int,
    *,
    token: str = "",
    decimals: int = 18,
    supply_raw: int = 0,
) -> tuple[
    list[dict[str, Any]],
    list[str],
    bool,
    int,
    dict[str, Any],
]:
    max_window = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS",
                "50000",
            )
        ),
    )
    min_window = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS",
                "16",
            )
        ),
    )
    max_attempts = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_ATTEMPTS",
                "12",
            )
        ),
    )
    selected_to = min(
        requested_to_block,
        from_block + max_window - 1,
    )
    attempts = 0
    logs: list[dict[str, Any]] = []
    errors: list[str] = []
    truncated = True
    metadata: dict[str, Any] = {}
    derived_event_shrink_count = 0
    while attempts < max_attempts:
        attempts += 1
        logs, errors, raw_truncated, metadata = (
            targeted_retention_liquidity_logs(
                chain,
                pools,
                from_block,
                selected_to,
            )
        )
        derived_events_truncated = False
        if not errors and not raw_truncated and token:
            _, _, derived_events_truncated = retention_liquidity_events(
                logs,
                token,
                decimals,
                supply_raw,
            )
        truncated = raw_truncated or derived_events_truncated
        if derived_events_truncated:
            derived_event_shrink_count += 1
        if errors or not truncated:
            break
        current_span = selected_to - from_block + 1
        if current_span <= min_window or attempts >= max_attempts:
            break
        next_span = max(min_window, current_span // 2)
        if next_span >= current_span:
            break
        selected_to = from_block + next_span - 1
    complete_selected = not errors and not truncated
    metadata.update(
        {
            "applicable": True,
            "active": selected_to < requested_to_block,
            "requested_to_block": requested_to_block,
            "selected_to_block": selected_to,
            "attempt_count": attempts,
            "derived_event_shrink_count": derived_event_shrink_count,
            "complete_selected_window": complete_selected,
            "complete_requested_window": bool(
                complete_selected
                and selected_to == requested_to_block
            ),
        }
    )
    return logs, errors, truncated, selected_to, metadata


def retention_transfer_events(
    logs: list[dict[str, Any]],
    decimals: int,
    supply_raw: int,
    actors: dict[str, dict[str, set[str]]],
    cex_addresses: dict[str, dict[str, str]],
    evidence_by_tx: dict[str, list[dict[str, Any]]],
    alert_from_block: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[str, bool], dict[str, Any]] = {}
    matched_transfer_count = 0
    for row in logs:
        topics = row.get("topics") or []
        if len(topics) < 3:
            continue
        from_addr = address_from_topic(topics[1])
        to_addr = address_from_topic(topics[2])
        from_actor = actors.get(from_addr)
        to_actor = actors.get(to_addr)
        to_cex = cex_addresses.get(to_addr)
        if from_actor is None and to_cex is None:
            continue
        amount_raw = int(row.get("data") or "0x0", 16)
        tx_hash = norm(row.get("transactionHash"))
        receipt_evidence = [
            evidence
            for evidence in evidence_by_tx.get(tx_hash, [])
            if norm(evidence.get("recipient")) == from_addr
        ]
        realized = bool(receipt_evidence)
        source_kinds = sorted(from_actor.get("kinds", set())) if from_actor else ["unknown_holder"]
        source_roles = sorted(from_actor.get("roles", set())) if from_actor else ["unknown_holder"]
        destination_class = (
            "cex_deposit"
            if to_cex
            else "tracked_actor"
            if to_addr in actors
            else "unknown_next_hop"
        )
        if realized:
            risk_type = "realized_sell"
            evidence_level = "receipt_quote_recovery"
            direction = "realized_sell"
            level = "CRITICAL"
        elif (
            from_actor
            and to_actor
            and "verified_project" in from_actor.get("kinds", set())
            and "verified_project" in to_actor.get("kinds", set())
        ):
            risk_type = "project_internal_rebalance"
            evidence_level = "transfer_only"
            direction = "internal_rebalance"
            level = "INFO"
        elif to_cex:
            risk_type = "cex_inflow_transfer_risk"
            evidence_level = "transfer_only"
            direction = "sell_pressure_candidate"
            level = "HIGH"
        elif "opening_buyer" in source_kinds:
            risk_type = "opening_buyer_outflow_transfer_risk"
            evidence_level = "transfer_only"
            direction = "destination_unresolved"
            level = "HIGH"
        elif "opening_cohort_recipient" in source_kinds:
            risk_type = (
                "opening_cohort_recipient_outflow_transfer_risk"
            )
            evidence_level = "opening_recipient_transfer_only"
            direction = "destination_unresolved"
            level = "HIGH"
        else:
            risk_type = "project_or_mm_outflow_transfer_risk"
            evidence_level = "transfer_only"
            direction = "destination_unresolved"
            level = "HIGH"
        event_block = block_number(row)
        historical_catchup = bool(
            alert_from_block is not None
            and event_block < alert_from_block
        )
        matched_transfer_count += 1
        event = {
            "type": risk_type,
            "level": level,
            "evidence_level": evidence_level,
            "direction": direction,
            "block": event_block,
            "tx": tx_hash,
            "log_index": log_index(row),
            "from": from_addr,
            "to": to_addr,
            "amount": str(decimal_amount(amount_raw, decimals)),
            "amount_supply_bps": (
                str(Decimal(amount_raw) * Decimal(10_000) / Decimal(supply_raw))
                if supply_raw > 0
                else ""
            ),
            "source_kinds": source_kinds,
            "source_roles": source_roles,
            "destination_class": destination_class,
            "destination_source": str((to_cex or {}).get("source") or ""),
            "receipt_evidence": receipt_evidence,
            "historical_catchup": historical_catchup,
            "alert_eligible": not historical_catchup,
        }
        group = grouped.setdefault(
            (risk_type, historical_catchup),
            {
                **event,
                "transfer_count": 0,
                "_amount_total": Decimal(0),
                "_amount_raw_total": 0,
                "_tracked_source_count": 0,
                "samples": [],
            },
        )
        group.update(
            {
                key: value
                for key, value in event.items()
                if key not in {"amount", "receipt_evidence"}
            }
        )
        group["transfer_count"] += 1
        group["_amount_total"] += decimal_from(event["amount"])
        group["_amount_raw_total"] += amount_raw
        group["_tracked_source_count"] += int(from_actor is not None)
        group["samples"].append(event)
        group["samples"] = group["samples"][-5:]
        if receipt_evidence:
            group["receipt_evidence"] = receipt_evidence
    events = []
    for group in grouped.values():
        amount_total = group.pop("_amount_total")
        amount_raw_total = int(group.pop("_amount_raw_total"))
        tracked_source_count = int(group.pop("_tracked_source_count"))
        if (
            group.get("type") == "cex_inflow_transfer_risk"
            and tracked_source_count == 0
            and (
                supply_raw <= 0
                or amount_raw_total * 10_000
                < supply_raw * RETENTION_CEX_MIN_SUPPLY_BPS
            )
        ):
            matched_transfer_count -= int(group.get("transfer_count") or 0)
            continue
        group["amount"] = str(amount_total)
        group["amount_supply_bps"] = (
            str(
                Decimal(amount_raw_total)
                * Decimal(10_000)
                / Decimal(supply_raw)
            )
            if supply_raw > 0
            else ""
        )
        group["tracked_source_count"] = tracked_source_count
        group["summary_scope"] = "risk_type_scan_window"
        group["samples_truncated"] = (
            int(group.get("transfer_count") or 0)
            > len(group.get("samples") or [])
        )
        group["sample_from"] = group.pop("from", "")
        group["sample_to"] = group.pop("to", "")
        group["sample_tx"] = group.pop("tx", "")
        group["sample_log_index"] = group.pop("log_index", 0)
        events.append(group)
    events.sort(
        key=lambda event: (
            int(event.get("block") or 0),
            int(event.get("log_index") or 0),
            str(event.get("type") or ""),
        )
    )
    return events, matched_transfer_count


def retention_liquidity_events(
    logs: list[dict[str, Any]],
    token: str,
    decimals: int,
    supply_raw: int,
    alert_from_block: int | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    try:
        min_supply_bps = max(
            1,
            int(
                os.environ.get(
                    "ALPHA_RETENTION_LIQUIDITY_MIN_SUPPLY_BPS",
                    "5",
                )
            ),
        )
    except ValueError:
        min_supply_bps = 5
    configured_quote_min = os.environ.get(
        "ALPHA_RETENTION_LIQUIDITY_QUOTE_MIN_AMOUNT"
    )

    def quote_min_amount(pool: dict[str, Any]) -> Decimal:
        if configured_quote_min is not None:
            parsed = decimal_from(configured_quote_min, "-1")
            if parsed >= 0:
                return parsed
        return (
            Decimal("10")
            if str(pool.get("quote_symbol") or "").upper()
            in {"WBNB", "WETH"}
            else Decimal("10000")
        )

    swaps: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    v3_lp: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    v4_liquidity: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in logs:
        pool = row.get("_retention_pool")
        event_kind = str(row.get("_retention_event_kind") or "")
        if not isinstance(pool, dict):
            continue
        protocol = str(pool.get("protocol") or "")
        address = norm(pool.get("address"))
        pool_id = norm(pool.get("pool_id"))
        tx_hash = norm(row.get("transactionHash"))
        token0 = norm(pool.get("token0"))
        token1 = norm(pool.get("token1"))
        if norm(token) not in {token0, token1}:
            continue
        target_slot = 0 if norm(token) == token0 else 1
        key = (protocol, address, pool_id, tx_hash)
        order = (block_number(row), log_index(row))
        if event_kind in {"v3_swap", "v4_swap"}:
            if event_kind == "v3_swap":
                target_raw = strict_v3_swap_amount(
                    row.get("data"),
                    target_slot,
                )
                quote_raw = strict_v3_swap_amount(
                    row.get("data"),
                    1 - target_slot,
                )
                normalized_target = target_raw
                normalized_quote = (
                    -quote_raw if quote_raw is not None else None
                )
            else:
                target_raw = strict_v4_swap_amount(
                    row.get("data"),
                    target_slot,
                )
                quote_raw = strict_v4_swap_amount(
                    row.get("data"),
                    1 - target_slot,
                )
                normalized_target = (
                    -target_raw if target_raw is not None else None
                )
                normalized_quote = quote_raw
            if (
                target_raw is None
                or quote_raw is None
                or target_raw == 0
                or quote_raw == 0
                or (target_raw > 0) == (quote_raw > 0)
                or normalized_target is None
                or normalized_quote is None
            ):
                continue
            group = swaps.setdefault(
                key,
                {
                    "target_net_raw": 0,
                    "quote_net_raw": 0,
                    "latest_order": order,
                    "latest_row": row,
                    "pool": pool,
                },
            )
            group["target_net_raw"] += normalized_target
            group["quote_net_raw"] += normalized_quote
            if order >= group["latest_order"]:
                group["latest_order"] = order
                group["latest_row"] = row
        elif event_kind in {"v3_mint", "v3_burn", "v3_collect"}:
            first_amount_slot = 2 if event_kind == "v3_mint" else 1
            amounts_raw = [
                uint_slot(
                    str(row.get("data") or "0x"),
                    first_amount_slot + slot,
                )
                for slot in (0, 1)
            ]
            group = v3_lp.setdefault(
                key,
                {
                    "mint_raw": [0, 0],
                    "burn_raw": [0, 0],
                    "collect_raw": [0, 0],
                    "latest_burn_order": (-1, -1),
                    "latest_burn_row": None,
                    "latest_collect_order": (-1, -1),
                    "latest_collect_row": None,
                    "pool": pool,
                },
            )
            if event_kind == "v3_mint":
                group["mint_raw"] = [
                    int(group["mint_raw"][slot]) + amounts_raw[slot]
                    for slot in (0, 1)
                ]
            elif event_kind == "v3_burn":
                group["burn_raw"] = [
                    int(group["burn_raw"][slot]) + amounts_raw[slot]
                    for slot in (0, 1)
                ]
                if order >= group["latest_burn_order"]:
                    group["latest_burn_order"] = order
                    group["latest_burn_row"] = row
            else:
                group["collect_raw"] = [
                    int(group["collect_raw"][slot]) + amounts_raw[slot]
                    for slot in (0, 1)
                ]
                if order >= group["latest_collect_order"]:
                    group["latest_collect_order"] = order
                    group["latest_collect_row"] = row
        elif event_kind == "v4_modify_liquidity":
            delta = int_slot(str(row.get("data") or "0x"), 2)
            if delta:
                group = v4_liquidity.setdefault(
                    key,
                    {
                        "liquidity_delta": 0,
                        "liquidity_added": 0,
                        "liquidity_removed": 0,
                        "saw_add": False,
                        "saw_remove": False,
                        "latest_order": order,
                        "latest_row": row,
                        "pool": pool,
                    },
                )
                group["liquidity_delta"] += delta
                if delta > 0:
                    group["liquidity_added"] += delta
                else:
                    group["liquidity_removed"] += -delta
                group["saw_add"] = bool(group["saw_add"] or delta > 0)
                group["saw_remove"] = bool(
                    group["saw_remove"] or delta < 0
                )
                if order >= group["latest_order"]:
                    group["latest_order"] = order
                    group["latest_row"] = row

    def supply_bps(amount_raw: int) -> Decimal:
        if supply_raw <= 0:
            return Decimal(0)
        return (
            Decimal(amount_raw)
            * Decimal(10_000)
            / Decimal(supply_raw)
        )

    def base_event(
        key: tuple[str, str, str, str],
        row: dict[str, Any],
        pool: dict[str, Any],
    ) -> dict[str, Any]:
        block = block_number(row)
        historical = bool(
            alert_from_block is not None
            and block < alert_from_block
        )
        return {
            "protocol": key[0],
            "pool": key[1],
            "pool_id": key[2],
            "block": block,
            "tx": key[3],
            "log_index": log_index(row),
            "token0": pool.get("token0"),
            "token1": pool.get("token1"),
            "historical_catchup": historical,
            "alert_eligible": not historical,
        }

    events: list[dict[str, Any]] = []
    handled_swap_keys: set[tuple[str, str, str, str]] = set()
    for key, lp in v3_lp.items():
        pool = lp["pool"]
        target_slot = (
            0 if norm(token) == norm(pool.get("token0")) else 1
        )
        quote_slot = 1 - target_slot
        net_remove_by_slot = [
            max(
                0,
                int(lp["burn_raw"][slot])
                - int(lp["mint_raw"][slot]),
            )
            for slot in (0, 1)
        ]
        net_add_by_slot = [
            max(
                0,
                int(lp["mint_raw"][slot])
                - int(lp["burn_raw"][slot]),
            )
            for slot in (0, 1)
        ]
        net_remove_raw = net_remove_by_slot[target_slot]
        quote_remove_raw = net_remove_by_slot[quote_slot]
        net_add_raw = net_add_by_slot[target_slot]
        quote_add_raw = net_add_by_slot[quote_slot]
        try:
            quote_decimals = int(pool.get("quote_decimals"))
        except (TypeError, ValueError):
            quote_decimals = -1
        quote_removed_amount = (
            decimal_amount(quote_remove_raw, quote_decimals)
            if quote_remove_raw > 0 and quote_decimals >= 0
            else Decimal(0)
        )
        quote_added_amount = (
            decimal_amount(quote_add_raw, quote_decimals)
            if quote_add_raw > 0 and quote_decimals >= 0
            else Decimal(0)
        )
        lp_bps = supply_bps(net_remove_raw)
        lp_added_bps = supply_bps(net_add_raw)
        quote_remove_material = bool(
            quote_remove_raw > 0
            and quote_decimals >= 0
            and quote_removed_amount >= quote_min_amount(pool)
        )
        material_net_add = bool(
            lp_added_bps >= Decimal(min_supply_bps)
            or (
                quote_add_raw > 0
                and quote_decimals >= 0
                and quote_added_amount >= quote_min_amount(pool)
            )
        )
        saw_mint_burn = bool(
            any(int(value) > 0 for value in lp["mint_raw"])
            and any(int(value) > 0 for value in lp["burn_raw"])
        )
        mixed_mode = (
            "rebalance"
            if saw_mint_burn and material_net_add
            else "partial_remove"
            if saw_mint_burn
            else "remove"
        )
        collect_target_raw = int(lp["collect_raw"][target_slot])
        collect_quote_raw = int(lp["collect_raw"][quote_slot])
        collect_target_bps = supply_bps(collect_target_raw)
        quote_collected_amount = (
            decimal_amount(collect_quote_raw, quote_decimals)
            if collect_quote_raw > 0 and quote_decimals >= 0
            else Decimal(0)
        )
        collect_fields = {
            "collected_amount": (
                str(decimal_amount(collect_target_raw, decimals))
                if collect_target_raw > 0
                else ""
            ),
            "collected_supply_bps": (
                str(collect_target_bps)
                if collect_target_raw > 0
                else ""
            ),
            "quote_collected_amount": (
                str(quote_collected_amount)
                if collect_quote_raw > 0 and quote_decimals >= 0
                else ""
            ),
            "quote_collected_token": pool.get("quote_token"),
            "quote_collected_symbol": pool.get("quote_symbol"),
        }
        burn_row = lp.get("latest_burn_row")
        swap = swaps.get(key)
        removal_event_emitted = False
        if (
            (net_remove_raw > 0 or quote_remove_raw > 0)
            and isinstance(burn_row, dict)
        ):
            if swap and int(swap["target_net_raw"]) > 0:
                sell_raw = int(swap["target_net_raw"])
                sell_bps = supply_bps(sell_raw)
                event = {
                    **base_event(
                        key,
                        swap["latest_row"],
                        lp["pool"],
                    ),
                    "type": (
                        "liquidity_rebalance_with_sell"
                        if mixed_mode == "rebalance"
                        else "liquidity_partial_remove_with_sell"
                        if mixed_mode == "partial_remove"
                        else "liquidity_exit_with_sell"
                    ),
                    "level": (
                        "HIGH"
                        if (
                            sell_bps >= Decimal(min_supply_bps)
                            if mixed_mode == "rebalance"
                            else (
                                max(lp_bps, sell_bps)
                                >= Decimal(min_supply_bps)
                                or quote_remove_material
                            )
                        )
                        else "INFO"
                    ),
                    "direction": (
                        "liquidity_rebalance_and_sell"
                        if mixed_mode == "rebalance"
                        else "liquidity_partial_remove_and_sell"
                        if mixed_mode == "partial_remove"
                        else "liquidity_exit_and_sell"
                    ),
                    "evidence_level": (
                        "verified_pool_swap_and_v3_mint_burn_rebalance_same_tx"
                        if mixed_mode == "rebalance"
                        else "verified_pool_swap_and_v3_mint_burn_partial_remove_same_tx"
                        if mixed_mode == "partial_remove"
                        else "verified_pool_swap_and_v3_burn_same_tx"
                    ),
                    "amount": str(decimal_amount(sell_raw, decimals)),
                    "amount_supply_bps": str(sell_bps),
                    "lp_removed_amount": (
                        str(decimal_amount(net_remove_raw, decimals))
                        if net_remove_raw > 0
                        else ""
                    ),
                    "lp_removed_supply_bps": (
                        str(lp_bps) if net_remove_raw > 0 else ""
                    ),
                    "lp_added_amount": (
                        str(decimal_amount(net_add_raw, decimals))
                        if net_add_raw > 0
                        else ""
                    ),
                    "lp_added_supply_bps": (
                        str(lp_added_bps) if net_add_raw > 0 else ""
                    ),
                    "quote_removed_amount": (
                        str(quote_removed_amount)
                        if quote_remove_raw > 0 and quote_decimals >= 0
                        else ""
                    ),
                    "quote_removed_token": pool.get("quote_token"),
                    "quote_removed_symbol": pool.get("quote_symbol"),
                    "quote_added_amount": (
                        str(quote_added_amount)
                        if quote_add_raw > 0 and quote_decimals >= 0
                        else ""
                    ),
                    "quote_added_token": pool.get("quote_token"),
                    "quote_added_symbol": pool.get("quote_symbol"),
                    **collect_fields,
                    "quote_amount_raw": str(
                        max(0, int(swap["quote_net_raw"]))
                    ),
                }
                events.append(event)
                handled_swap_keys.add(key)
                removal_event_emitted = True
            elif (
                lp_bps >= Decimal(min_supply_bps)
                or quote_remove_material
            ):
                events.append(
                    {
                        **base_event(key, burn_row, pool),
                        "type": (
                            "lp_rebalance_observation"
                            if mixed_mode == "rebalance"
                            else "lp_partial_remove_observation"
                            if mixed_mode == "partial_remove"
                            else "lp_remove_observation"
                        ),
                        "level": (
                            "INFO"
                            if mixed_mode == "rebalance"
                            else "HIGH"
                        ),
                        "direction": (
                            "liquidity_rebalance"
                            if mixed_mode == "rebalance"
                            else "liquidity_partial_remove"
                            if mixed_mode == "partial_remove"
                            else "liquidity_remove"
                        ),
                        "evidence_level": (
                            "v3_mint_burn_rebalance_same_pool_tx"
                            if mixed_mode == "rebalance"
                            else "v3_mint_burn_partial_remove_same_pool_tx"
                            if mixed_mode == "partial_remove"
                            else "v3_burn_same_pool_tx"
                        ),
                        "amount": (
                            str(decimal_amount(net_remove_raw, decimals))
                            if net_remove_raw > 0
                            else ""
                        ),
                        "amount_supply_bps": (
                            str(lp_bps) if net_remove_raw > 0 else ""
                        ),
                        "quote_removed_amount": (
                            str(quote_removed_amount)
                            if quote_remove_raw > 0
                            and quote_decimals >= 0
                            else ""
                        ),
                        "quote_removed_token": pool.get("quote_token"),
                        "quote_removed_symbol": pool.get("quote_symbol"),
                        "lp_added_amount": (
                            str(decimal_amount(net_add_raw, decimals))
                            if net_add_raw > 0
                            else ""
                        ),
                        "lp_added_supply_bps": (
                            str(lp_added_bps)
                            if net_add_raw > 0
                            else ""
                        ),
                        "quote_added_amount": (
                            str(quote_added_amount)
                            if quote_add_raw > 0
                            and quote_decimals >= 0
                            else ""
                        ),
                        "quote_added_token": pool.get("quote_token"),
                        "quote_added_symbol": pool.get("quote_symbol"),
                        **collect_fields,
                    }
                )
                removal_event_emitted = True
        if removal_event_emitted:
            continue
        collect_material = bool(
            collect_target_bps >= Decimal(min_supply_bps)
            or (
                collect_quote_raw > 0
                and quote_decimals >= 0
                and quote_collected_amount >= quote_min_amount(pool)
            )
        )
        collect_row = lp.get("latest_collect_row")
        if not (
            collect_material
            and isinstance(collect_row, dict)
        ):
            continue
        events.append(
            {
                **base_event(key, collect_row, pool),
                "type": (
                    "lp_rebalance_collect_observation"
                    if saw_mint_burn
                    else "lp_collect_observation"
                ),
                "level": "INFO",
                    "direction": (
                        "liquidity_rebalance_collect"
                        if saw_mint_burn
                    else "collect_only"
                ),
                    "evidence_level": (
                        "v3_mint_burn_collect_same_pool_tx"
                        if saw_mint_burn
                    else "v3_collect_only"
                ),
                "amount": collect_fields["collected_amount"],
                "amount_supply_bps": collect_fields[
                    "collected_supply_bps"
                ],
                **collect_fields,
            }
        )
    for key, liquidity in v4_liquidity.items():
        if liquidity.get("saw_remove") is not True:
            continue
        swap = swaps.get(key)
        row = liquidity["latest_row"]
        mixed_mode = (
            "partial_remove"
            if (
                liquidity.get("saw_add") is True
                and int(liquidity.get("liquidity_delta") or 0) < 0
            )
            else "rebalance"
            if liquidity.get("saw_add") is True
            else "remove"
        )
        if swap and int(swap["target_net_raw"]) > 0:
            sell_raw = int(swap["target_net_raw"])
            sell_bps = supply_bps(sell_raw)
            events.append(
                {
                    **base_event(key, swap["latest_row"], liquidity["pool"]),
                    "type": (
                        "liquidity_rebalance_with_sell"
                        if mixed_mode == "rebalance"
                        else "liquidity_partial_remove_with_sell"
                        if mixed_mode == "partial_remove"
                        else "liquidity_exit_with_sell"
                    ),
                    "level": (
                        "HIGH"
                        if sell_bps >= Decimal(min_supply_bps)
                        else "INFO"
                    ),
                    "direction": (
                        "liquidity_rebalance_and_sell"
                        if mixed_mode == "rebalance"
                        else "liquidity_partial_remove_and_sell"
                        if mixed_mode == "partial_remove"
                        else "liquidity_exit_and_sell"
                    ),
                    "evidence_level": (
                        "verified_pool_swap_and_mixed_liquidity_delta_same_tx"
                        if mixed_mode == "rebalance"
                        else "verified_pool_swap_and_net_negative_mixed_liquidity_delta_same_tx"
                        if mixed_mode == "partial_remove"
                        else "verified_pool_swap_and_liquidity_delta_same_tx"
                    ),
                    "amount": str(decimal_amount(sell_raw, decimals)),
                    "amount_supply_bps": str(sell_bps),
                    "liquidity_delta": str(liquidity["liquidity_delta"]),
                    "liquidity_added": str(liquidity["liquidity_added"]),
                    "liquidity_removed": str(
                        liquidity["liquidity_removed"]
                    ),
                    "quote_amount_raw": str(
                        max(0, int(swap["quote_net_raw"]))
                    ),
                }
            )
            handled_swap_keys.add(key)
        else:
            events.append(
                {
                    **base_event(key, row, liquidity["pool"]),
                    "type": (
                        "lp_rebalance_observation"
                        if mixed_mode == "rebalance"
                        else "lp_partial_remove_observation"
                        if mixed_mode == "partial_remove"
                        else "lp_remove_observation"
                    ),
                    "level": "INFO",
                    "direction": (
                        "liquidity_rebalance_unattributed"
                        if mixed_mode == "rebalance"
                        else "liquidity_partial_remove_unattributed"
                        if mixed_mode == "partial_remove"
                        else "liquidity_remove_unattributed"
                    ),
                    "evidence_level": (
                        "mixed_liquidity_delta_only"
                        if mixed_mode == "rebalance"
                        else "net_negative_mixed_liquidity_delta_only"
                        if mixed_mode == "partial_remove"
                        else "liquidity_delta_only"
                    ),
                    "amount": "",
                    "amount_supply_bps": "",
                    "liquidity_delta": str(liquidity["liquidity_delta"]),
                    "liquidity_added": str(liquidity["liquidity_added"]),
                    "liquidity_removed": str(
                        liquidity["liquidity_removed"]
                    ),
                }
            )
    for key, swap in swaps.items():
        sell_raw = int(swap["target_net_raw"])
        sell_bps = supply_bps(sell_raw)
        if (
            key in handled_swap_keys
            or sell_raw <= 0
            or sell_bps < Decimal(min_supply_bps)
        ):
            continue
        events.append(
            {
                **base_event(key, swap["latest_row"], swap["pool"]),
                "type": "verified_pool_sell_pressure",
                "level": "HIGH",
                "direction": "verified_pool_sell",
                "evidence_level": "verified_pool_swap",
                "amount": str(decimal_amount(sell_raw, decimals)),
                "amount_supply_bps": str(sell_bps),
                "quote_amount_raw": str(
                    max(0, int(swap["quote_net_raw"]))
                ),
            }
        )
    events.sort(
        key=lambda event: (
            int(event.get("block") or 0),
            int(event.get("log_index") or 0),
            str(event.get("type") or ""),
        )
    )
    max_events = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_MAX_EVENTS",
                "500",
            )
        ),
    )
    events_truncated = len(events) > max_events
    return events[-max_events:], len(events), events_truncated


def build_liquidity_retention(
    *,
    item: dict[str, Any],
    token: str,
    pools: list[dict[str, Any]],
    scope_hash: str,
    previous_scope_hash: str,
    scope_rebaseline: bool,
    previous_catchup_active: bool,
    scope_coverage_from_block: int,
    logs: list[dict[str, Any]],
    errors: list[str],
    truncated: bool,
    decimals: int,
    supply_raw: int,
    scan_from_block: int,
    scan_to_block: int,
    target_scan_to_block: int,
    previous_latest_block: int,
    coverage_metadata: dict[str, Any],
    alert_from_block: int,
) -> dict[str, Any]:
    window = retention_window(item, str(item.get("chain") or ""))
    events, event_count, events_truncated = retention_liquidity_events(
        logs,
        token,
        decimals,
        supply_raw,
        alert_from_block,
    )
    continuous = bool(
        previous_latest_block > 0
        and scan_from_block == previous_latest_block + 1
    )
    continuity_ready = continuous or scope_rebaseline
    try:
        query_count = int(coverage_metadata.get("query_count") or 0)
        scope_batch_count = int(
            coverage_metadata.get("scope_batch_count") or 0
        )
        query_chunk_count = int(
            coverage_metadata.get("query_chunk_count") or 0
        )
        expected_query_count = int(
            coverage_metadata.get("expected_query_count") or 0
        )
    except (TypeError, ValueError):
        query_count = 0
        scope_batch_count = 0
        query_chunk_count = 0
        expected_query_count = 0
    query_scope_complete = bool(
        coverage_metadata.get("query_scope_complete") is True
        and scope_batch_count > 0
        and query_chunk_count > 0
        and expected_query_count
        == scope_batch_count * query_chunk_count
        and query_count == expected_query_count
    )
    scan_complete = bool(
        window.get("status") == "active"
        and pools
        and len(scope_hash) == 64
        and not errors
        and not truncated
        and not events_truncated
        and scan_from_block <= scan_to_block
        and continuity_ready
        and query_scope_complete
    )
    latest = scan_to_block if scan_complete else previous_latest_block
    complete = bool(
        scan_complete and latest == target_scan_to_block
    )
    return {
        **window,
        "status": "active",
        "coverage_mode": "verified_pool_indexed_topics",
        "complete": complete,
        "selected_window_complete": scan_complete,
        "scope_complete": True,
        "scope_hash": scope_hash,
        "previous_scope_hash": previous_scope_hash,
        "scope_rebaseline": scope_rebaseline,
        "scope_state_schema_version": (
            LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
        ),
        "scope_coverage_from_block": scope_coverage_from_block,
        "pool_count": len(pools),
        "v3_pool_count": sum(
            row.get("protocol") == "v3" for row in pools
        ),
        "v4_pool_count": sum(
            row.get("protocol") == "v4_cl" for row in pools
        ),
        "v4_manager_count": int(
            coverage_metadata.get("v4_manager_count") or 0
        ),
        "event_filter_count": int(
            coverage_metadata.get("event_filter_count") or 0
        ),
        "scan_from_block": scan_from_block,
        "scan_to_block": scan_to_block,
        "target_latest_block": target_scan_to_block,
        "previous_latest_block": previous_latest_block,
        "latest_block": latest,
        "continuous": continuous,
        "previous_catchup_active": previous_catchup_active,
        "query_scope_complete": query_scope_complete,
        "query_count": query_count,
        "scope_batch_count": scope_batch_count,
        "query_chunk_count": query_chunk_count,
        "query_chunk_blocks": int(
            coverage_metadata.get("query_chunk_blocks") or 0
        ),
        "expected_query_count": expected_query_count,
        "log_count": len(logs),
        "log_error_count": len(errors),
        "log_errors": errors[:3],
        "truncated": truncated,
        "events_truncated": events_truncated,
        "incremental_catchup": {
            key: coverage_metadata.get(key)
            for key in (
                "applicable",
                "active",
                "requested_to_block",
                "selected_to_block",
                "attempt_count",
                "complete_selected_window",
                "complete_requested_window",
            )
            if key in coverage_metadata
        },
        "alert_from_block": alert_from_block,
        "event_count": event_count,
        "events": events,
    }


def build_token_liquidity_retention(
    *,
    item: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
    tip: int,
    decimals: int,
    supply_raw: int,
    opening_payload: dict[str, Any],
    liquidity_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    window = retention_window(item, chain)
    if window.get("status") != "active":
        return {
            **window,
            "coverage_mode": "verified_pool_indexed_topics",
            "scope_complete": True,
            "pool_count": 0,
            "events": [],
        }, None
    scope = opening_verified_pool_scope(
        opening_payload,
        symbol,
        chain,
        token,
        persisted_scope=liquidity_state,
    )
    pools = scope.get("pool_scope") or []
    if scope.get("complete") is not True or not pools:
        return {
            **window,
            "status": (
                "not_applicable"
                if scope.get("complete") is True
                else "coverage_gap"
            ),
            "reason": str(scope.get("status") or "pool_scope_unavailable"),
            "coverage_mode": "verified_pool_indexed_topics",
            "scope_complete": scope.get("complete") is True,
            "scope_hash": str(scope.get("scope_hash") or ""),
            "pool_count": int(scope.get("pool_count") or 0),
            "v3_pool_count": int(scope.get("v3_pool_count") or 0),
            "v4_pool_count": int(scope.get("v4_pool_count") or 0),
            "complete": scope.get("complete") is True,
            "selected_window_complete": False,
            "log_error_count": int(scope.get("complete") is not True),
            "truncated": False,
            "events_truncated": False,
            "events": [],
        }, None
    previous_latest = int(liquidity_state.get("latest_block") or 0)
    previous_scope_hash = str(liquidity_state.get("scope_hash") or "")
    current_scope_hash = str(scope.get("scope_hash") or "")
    previous_catchup_active = (
        liquidity_state.get("catchup_active") is True
    )
    try:
        state_schema_version = int(
            liquidity_state.get("scope_state_schema_version") or 0
        )
    except (TypeError, ValueError):
        state_schema_version = 0
    scope_rebaseline = bool(
        previous_latest <= 0
        or state_schema_version
        != LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
        or not previous_scope_hash
        or previous_scope_hash != current_scope_hash
    )
    bootstrap_blocks = max(
        1,
        int(
            os.environ.get(
                "ALPHA_RETENTION_LIQUIDITY_BOOTSTRAP_BLOCKS",
                "2400",
            )
        ),
    )
    scope_coverage_from = int(
        liquidity_state.get("scope_coverage_from_block") or 0
    )
    try:
        confirmation_blocks = max(
            0,
            int(
                os.environ.get(
                    "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS",
                    "2",
                )
            ),
        )
    except ValueError:
        confirmation_blocks = 2
    confirmed_tip = max(0, tip - confirmation_blocks)
    checkpoint_reorg_recovery = False
    checkpoint_refresh = False
    effective_previous_latest = previous_latest
    verified_previous_hash = ""
    if scope_rebaseline:
        scan_from = max(0, confirmed_tip - bootstrap_blocks + 1)
        scope_coverage_from = scan_from
    else:
        previous_block_hash = str(
            liquidity_state.get("latest_block_hash") or ""
        ).lower()
        canonical_previous_hash = liquidity_checkpoint_block_hash(
            chain,
            previous_latest,
        )
        if (
            not valid_hash32(previous_block_hash)
            or int(previous_block_hash[2:], 16) == 0
            or not canonical_previous_hash
        ):
            return {
                **window,
                "status": "coverage_gap",
                "reason": "liquidity_checkpoint_hash_unavailable",
                "coverage_mode": "verified_pool_indexed_topics",
                "scope_complete": True,
                "scope_hash": current_scope_hash,
                "pool_count": len(pools),
                "complete": False,
                "selected_window_complete": False,
                "log_error_count": 1,
                "truncated": False,
                "events_truncated": False,
                "events": [],
            }, None
        if canonical_previous_hash != previous_block_hash:
            checkpoint_reorg_recovery = True
            try:
                reorg_rescan_blocks = max(
                    1,
                    int(
                        os.environ.get(
                            "ALPHA_RETENTION_LIQUIDITY_REORG_RESCAN_BLOCKS",
                            "2400",
                        )
                    ),
                )
            except ValueError:
                reorg_rescan_blocks = 2400
            scan_from = max(
                scope_coverage_from,
                previous_latest - reorg_rescan_blocks + 1,
            )
            effective_previous_latest = max(0, scan_from - 1)
        elif previous_latest >= confirmed_tip:
            if previous_latest > confirmed_tip:
                return {
                    **window,
                    "status": "coverage_gap",
                    "reason": "liquidity_confirmed_tip_behind_checkpoint",
                    "coverage_mode": "verified_pool_indexed_topics",
                    "scope_complete": True,
                    "scope_hash": current_scope_hash,
                    "pool_count": len(pools),
                    "complete": False,
                    "selected_window_complete": False,
                    "log_error_count": 1,
                    "truncated": False,
                    "events_truncated": False,
                    "events": [],
                }, None
            checkpoint_refresh = True
            verified_previous_hash = canonical_previous_hash
            scan_from = previous_latest
            effective_previous_latest = max(0, previous_latest - 1)
        else:
            verified_previous_hash = canonical_previous_hash
            scan_from = previous_latest + 1
    confirmed_tip_hash_before = liquidity_checkpoint_block_hash(
        chain,
        confirmed_tip,
    )
    if not confirmed_tip_hash_before:
        return {
            **window,
            "status": "coverage_gap",
            "reason": "liquidity_confirmed_tip_hash_unavailable",
            "coverage_mode": "verified_pool_indexed_topics",
            "scope_complete": True,
            "scope_hash": current_scope_hash,
            "pool_count": len(pools),
            "complete": False,
            "selected_window_complete": False,
            "log_error_count": 1,
            "truncated": False,
            "events_truncated": False,
            "events": [],
        }, None
    (
        logs,
        errors,
        truncated,
        scan_to,
        coverage_metadata,
    ) = bounded_retention_liquidity_logs(
        chain,
        pools,
        scan_from,
        confirmed_tip,
        token=token,
        decimals=decimals,
        supply_raw=supply_raw,
    )
    checkpoint_hash = ""
    if not errors and not truncated:
        checkpoint_hash = liquidity_checkpoint_block_hash(chain, scan_to)
        if not checkpoint_hash:
            errors = [*errors, "liquidity checkpoint hash unavailable"]
        elif any(
            block_number(row) == scan_to
            and norm(row.get("blockHash")) != checkpoint_hash
            for row in logs
        ):
            errors = [*errors, "liquidity checkpoint block hash mismatch"]
        elif (
            verified_previous_hash
            and liquidity_checkpoint_block_hash(chain, previous_latest)
            != verified_previous_hash
        ):
            errors = [
                *errors,
                "liquidity previous checkpoint changed during scan",
            ]
        elif (
            (
                checkpoint_hash
                if scan_to == confirmed_tip
                else liquidity_checkpoint_block_hash(chain, confirmed_tip)
            )
            != confirmed_tip_hash_before
        ):
            errors = [
                *errors,
                "liquidity confirmed tip changed during scan",
            ]
    alert_from = (
        confirmed_tip + 1
        if (
            scope_rebaseline
            or previous_catchup_active
            or coverage_metadata.get("active") is True
        )
        else scan_from
    )
    flow = build_liquidity_retention(
        item={**item, "chain": chain},
        token=token,
        pools=pools,
        scope_hash=current_scope_hash,
        previous_scope_hash=(
            ""
            if scope_rebaseline
            and previous_scope_hash == current_scope_hash
            else previous_scope_hash
        ),
        scope_rebaseline=scope_rebaseline,
        previous_catchup_active=previous_catchup_active,
        scope_coverage_from_block=scope_coverage_from,
        logs=logs,
        errors=errors,
        truncated=truncated,
        decimals=decimals,
        supply_raw=supply_raw,
        scan_from_block=scan_from,
        scan_to_block=scan_to,
        target_scan_to_block=confirmed_tip,
        previous_latest_block=effective_previous_latest,
        coverage_metadata=coverage_metadata,
        alert_from_block=alert_from,
    )
    flow.update(
        {
            "observed_latest_block": tip,
            "confirmation_blocks": confirmation_blocks,
            "latest_block_hash": (
                checkpoint_hash
                if flow.get("selected_window_complete") is True
                else str(liquidity_state.get("latest_block_hash") or "")
            ),
            "checkpoint_reorg_recovery": checkpoint_reorg_recovery,
            "checkpoint_refresh": checkpoint_refresh,
            "replaced_checkpoint_block": (
                previous_latest if checkpoint_reorg_recovery else 0
            ),
        }
    )
    next_state = None
    if flow.get("selected_window_complete") is True:
        next_state = {
            "scope_state_schema_version": (
                LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": current_scope_hash,
            "pool_scope": copy.deepcopy(pools),
            "pool_count": len(pools),
            "scope_coverage_from_block": scope_coverage_from,
            "latest_block": int(flow.get("latest_block") or scan_to),
            "latest_block_hash": checkpoint_hash,
            "catchup_active": (
                (flow.get("incremental_catchup") or {}).get("active")
                is True
            ),
        }
    return flow, next_state


def build_retention_flow(
    *,
    item: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
    logs: list[dict[str, Any]],
    errors: list[str],
    truncated: bool,
    decimals: int,
    supply_raw: int,
    scan_from_block: int,
    scan_to_block: int,
    previous_latest_block: int,
    holder_previous_latest_block: int,
    context: dict[str, Any],
    coverage_mode: str = "full_transfer_stream",
    coverage_metadata: dict[str, Any] | None = None,
    alert_from_block: int | None = None,
    scope_actors: dict[str, dict[str, set[str]]] | None = None,
    scope_cex_addresses: dict[str, dict[str, str]] | None = None,
    scope_evidence_by_tx: dict[
        str,
        list[dict[str, Any]],
    ] | None = None,
    scope_metadata: dict[str, Any] | None = None,
    scope_rebaseline: bool = False,
    previous_scope_hash: str = "",
    scope_coverage_from_block: int = 0,
    target_scan_to_block: int | None = None,
) -> dict[str, Any]:
    window = retention_window(item, chain)
    if (
        scope_actors is None
        or scope_cex_addresses is None
        or scope_evidence_by_tx is None
        or scope_metadata is None
    ):
        (
            actors,
            cex_addresses,
            evidence_by_tx,
            resolved_scope_metadata,
        ) = retention_evidence_scope(
            item,
            symbol,
            chain,
            token,
            context,
        )
    else:
        actors = scope_actors
        cex_addresses = scope_cex_addresses
        evidence_by_tx = scope_evidence_by_tx
        resolved_scope_metadata = scope_metadata
    events, event_count = retention_transfer_events(
        logs,
        decimals,
        supply_raw,
        actors,
        cex_addresses,
        evidence_by_tx,
        alert_from_block=alert_from_block,
    )
    coverage_metadata = coverage_metadata or {}
    bounded_bootstrap = previous_latest_block <= 0
    active = window["status"] == "active"
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    first_seen = parse_iso(facts.get("lifecycle_first_seen_at"))
    opening_time = parse_iso(window.get("opening_time_utc"))
    late_discovery_bootstrap = bool(
        active
        and bounded_bootstrap
        and holder_previous_latest_block <= 0
        and first_seen is not None
        and opening_time is not None
        and first_seen
        >= opening_time + timedelta(hours=RETENTION_FLOW_START_HOURS)
    )
    continuous = (
        not bounded_bootstrap
        and scan_from_block == previous_latest_block + 1
    )
    continuity_ready = (
        continuous
        or (bounded_bootstrap and not active)
        or late_discovery_bootstrap
        or scope_rebaseline
    )
    targeted_query_scope_complete = True
    if coverage_mode == "targeted_indexed_topics":
        try:
            query_count = int(
                coverage_metadata.get("query_count") or 0
            )
            scope_batch_count = int(
                coverage_metadata.get("scope_batch_count") or 0
            )
            query_chunk_count = int(
                coverage_metadata.get("query_chunk_count") or 0
            )
            expected_query_count = int(
                coverage_metadata.get("expected_query_count")
                or 0
            )
        except (TypeError, ValueError):
            targeted_query_scope_complete = False
        else:
            targeted_query_scope_complete = bool(
                coverage_metadata.get("query_scope_complete") is True
                and scope_batch_count > 0
                and query_chunk_count > 0
                and expected_query_count
                == scope_batch_count * query_chunk_count
                and query_count == expected_query_count
                and len(actors) + len(cex_addresses) > 0
            )
    scan_complete = (
        not errors
        and not truncated
        and scan_from_block <= scan_to_block
        and continuity_ready
        and targeted_query_scope_complete
        and (
            not active
            or coverage_mode != "targeted_indexed_topics"
            or resolved_scope_metadata.get(
                "opening_scope_complete"
            )
            is True
        )
    )
    latest = scan_to_block if scan_complete else previous_latest_block
    target_scan_to = (
        int(target_scan_to_block)
        if target_scan_to_block is not None
        else scan_to_block
    )
    complete = (
        scan_complete and latest == target_scan_to
        if active
        else True
    )
    return {
        **window,
        "complete": complete,
        "selected_window_complete": scan_complete,
        "scan_from_block": scan_from_block,
        "scan_to_block": scan_to_block,
        "target_latest_block": target_scan_to,
        "previous_latest_block": previous_latest_block,
        "holder_previous_latest_block": holder_previous_latest_block,
        "latest_block": latest,
        "log_error_count": len(errors),
        "truncated": truncated,
        "coverage_mode": coverage_mode,
        "query_scope_complete": (
            coverage_metadata.get("query_scope_complete")
            if coverage_mode == "targeted_indexed_topics"
            else True
        ),
        "query_count": int(
            coverage_metadata.get("query_count") or 0
        ),
        "scope_kind_count": int(
            coverage_metadata.get("scope_kind_count") or 0
        ),
        "scope_batch_count": int(
            coverage_metadata.get("scope_batch_count") or 0
        ),
        "query_chunk_count": int(
            coverage_metadata.get("query_chunk_count") or 0
        ),
        "expected_query_count": int(
            coverage_metadata.get("expected_query_count") or 0
        ),
        "incremental_catchup": {
            key: coverage_metadata.get(key)
            for key in (
                "applicable",
                "active",
                "requested_to_block",
                "selected_to_block",
                "attempt_count",
                "complete_selected_window",
                "complete_requested_window",
            )
            if key in coverage_metadata
        },
        "alert_from_block": (
            int(alert_from_block)
            if alert_from_block is not None
            else scan_from_block
        ),
        "continuous": continuous,
        "bounded_bootstrap": bounded_bootstrap,
        "late_discovery_bootstrap": late_discovery_bootstrap,
        "coverage_scope": (
            "scope_rebaseline"
            if scope_rebaseline
            else "first_success_bounded_baseline"
            if late_discovery_bootstrap
            else "continuous_checkpoint"
            if continuous
            else "pre_retention_baseline"
            if bounded_bootstrap and not active
            else "historical_backfill_required"
        ),
        "opening_buyer_count": sum(
            1 for actor in actors.values() if "opening_buyer" in actor.get("kinds", set())
        ),
        "opening_cohort_recipient_count": sum(
            1
            for actor in actors.values()
            if "opening_cohort_recipient"
            in actor.get("kinds", set())
        ),
        "verified_project_address_count": sum(
            1 for actor in actors.values() if "verified_project" in actor.get("kinds", set())
        ),
        "cex_address_count": len(cex_addresses),
        "opening_scope_complete": bool(
            resolved_scope_metadata.get("opening_scope_complete")
        ),
        "opening_actor_count": int(
            resolved_scope_metadata.get("opening_actor_count") or 0
        ),
        "opening_actor_scope_hash": str(
            resolved_scope_metadata.get(
                "opening_actor_scope_hash"
            )
            or ""
        ),
        "scope_state_schema_version": int(
            resolved_scope_metadata.get(
                "scope_state_schema_version"
            )
            or 0
        ),
        "scope_hash": str(
            resolved_scope_metadata.get("scope_hash") or ""
        ),
        "previous_scope_hash": previous_scope_hash,
        "scope_rebaseline": scope_rebaseline,
        "scope_coverage_from_block": int(
            scope_coverage_from_block
            or scan_from_block
        ),
        "event_count": event_count,
        "event_group_count": len(events),
        "events_truncated": False,
        "events": events,
    }


def classify_holder(
    chain: str,
    holder: str,
    token: str,
    watch_labels: dict[str, dict[str, Any]],
    code_cache: dict[str, str],
) -> dict[str, str]:
    holder = norm(holder)
    if holder in BURN_ADDRESSES:
        return {"class": "burn_or_zero", "label": "burn/zero"}
    if holder == norm(token):
        return {"class": "token_contract", "label": "token contract"}
    global_label = global_address_label(chain, holder)
    if global_label:
        return {"class": str(global_label.get("class") or "labeled"), "label": str(global_label.get("label") or "")}
    watch_label = watch_labels.get(holder)
    if watch_label:
        role = str(watch_label.get("role") or "watch_address")
        label = str(watch_label.get("label") or role)
        return {"class": role, "label": label}
    if os.environ.get("ALPHA_HOLDER_CLASSIFY_CONTRACTS", "0") == "1" and get_code(chain, holder, code_cache) not in ("", "0x", "0X"):
        return {"class": "unknown_contract", "label": "unknown contract"}
    return {"class": "unknown_address", "label": "unlabeled"}


def eligible_for_effective(row: dict[str, Any]) -> bool:
    return row.get("class") not in INFRA_CLASSES and row.get("class") != "burn_or_zero"


def holder_row(
    chain: str,
    token: str,
    holder: str,
    balance_raw: int,
    supply_raw: int,
    decimals: int,
    watch_labels: dict[str, dict[str, Any]],
    code_cache: dict[str, str],
) -> dict[str, Any]:
    label = classify_holder(chain, holder, token, watch_labels, code_cache)
    pct = Decimal(0) if supply_raw <= 0 else Decimal(balance_raw) * Decimal(100) / Decimal(supply_raw)
    return {
        "address": holder,
        "balance_raw": str(balance_raw),
        "balance": str(decimal_amount(balance_raw, decimals)),
        "pct": str(pct),
        "class": label["class"],
        "label": label["label"],
    }


def top_rows(
    balances: dict[str, int],
    chain: str,
    token: str,
    supply_raw: int,
    decimals: int,
    watch_labels: dict[str, dict[str, Any]],
    effective: bool,
) -> list[dict[str, Any]]:
    code_cache: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for holder, balance_raw in sorted(balances.items(), key=lambda item: item[1], reverse=True):
        if balance_raw <= 0:
            continue
        row = holder_row(chain, token, holder, balance_raw, supply_raw, decimals, watch_labels, code_cache)
        if row["class"] == "burn_or_zero":
            continue
        if effective and not eligible_for_effective(row):
            continue
        rows.append(row)
        if len(rows) >= 10:
            break
    return rows


def pct_sum(rows: list[dict[str, Any]]) -> Decimal:
    return sum((decimal_from(row.get("pct")) for row in rows), Decimal(0))


def raw_top10_infra_pct(rows: list[dict[str, Any]]) -> Decimal:
    return sum((decimal_from(row.get("pct")) for row in rows if row.get("class") in INFRA_CLASSES), Decimal(0))


def classify_signal(metrics: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "direction": "baseline",
            "action": "建基线；下一轮开始判断筹码变化",
            "reason": "首次快照没有可比基准",
            "level": "INFO",
        }
    effective_delta = decimal_from(metrics.get("effective_top10_delta_pct"))
    raw_delta = decimal_from(metrics.get("raw_top10_delta_pct"))
    infra_delta = decimal_from(metrics.get("raw_top10_infra_delta_pct"))
    down_threshold = decimal_from(os.environ.get("ALPHA_HOLDER_EFFECTIVE_TOP10_DOWN_ALERT_PP", "1"))
    up_threshold = decimal_from(os.environ.get("ALPHA_HOLDER_EFFECTIVE_TOP10_UP_ALERT_PP", "1"))
    infra_threshold = decimal_from(os.environ.get("ALPHA_HOLDER_INFRA_TOP10_ALERT_PP", "1"))
    if effective_delta <= -down_threshold:
        return {
            "direction": "effective_top10_down",
            "action": "持仓降风险；空仓等流向确认",
            "reason": "排除托管后的前十占比下降，优先查 CEX 预出货、DEX 换出和多钱包拆分",
            "level": "CRITICAL" if effective_delta <= down_threshold * Decimal("-3") else "HIGH",
        }
    if effective_delta >= up_threshold:
        return {
            "direction": "effective_top10_up",
            "action": "吸筹观察；等价格承接和净买确认",
            "reason": "排除托管后的前十占比上升，已剔除已知托管、LP、桥地址影响",
            "level": "HIGH",
        }
    if raw_delta >= infra_threshold and infra_delta >= infra_threshold:
        return {
            "direction": "infra_top10_up",
            "action": "基础设施归集；观察",
            "reason": "窗口重建前十上升主要来自基础设施地址，可能是 Alpha 托管、CEX 或池子归集",
            "level": "INFO",
        }
    return {
        "direction": "flat",
        "action": "观察；筹码集中度未给出新方向",
        "reason": "前十占比变化未超过阈值",
        "level": "INFO",
    }


def build_symbol_context(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path, {"events": []})
    generated = parse_iso(payload.get("generated_at"))
    age_minutes = None
    stale = True
    if generated:
        age_minutes = max(0, int((now_utc() - generated).total_seconds() // 60))
        stale = age_minutes > int(os.environ.get("ALPHA_HOLDER_CONTEXT_MAX_AGE_MINUTES", "45"))
    rows: dict[str, dict[str, Any]] = {}
    for event in payload.get("events", []):
        symbol = str(event.get("symbol") or "").upper()
        if not symbol:
            continue
        rows[symbol] = {
            "analysis": event.get("analysis", {}),
            "age_minutes": age_minutes,
            "stale": stale,
            "generated_at": payload.get("generated_at"),
        }
    return rows


def latest_market_context() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "price": build_symbol_context(PRICE_CONTEXT_PATH),
        "flow": build_symbol_context(FLOW_CONTEXT_PATH),
    }


def context_is_bearish(ctx: dict[str, Any], *, source: str) -> bool:
    if not ctx or ctx.get("stale"):
        return False
    analysis = ctx.get("analysis", {})
    direction = str(analysis.get("direction") or "")
    signal = str(analysis.get("trade_signal") or "")
    if source == "flow":
        return direction in {"偏空", "冲高派发风险"} or "卖出/减仓" in signal or "CEX预出货" in signal
    return direction in {"放量走弱", "放量下插", "冲高回落"} or "卖出/减仓" in signal or "不抄底" in signal


def context_is_bullish(ctx: dict[str, Any], *, source: str) -> bool:
    if not ctx or ctx.get("stale"):
        return False
    analysis = ctx.get("analysis", {})
    direction = str(analysis.get("direction") or "")
    signal = str(analysis.get("trade_signal") or "")
    if source == "flow":
        return direction == "观察偏多" or "净买入" in signal
    return direction == "观察偏多" and "放量" in signal


def short_context(ctx: dict[str, Any], *, source: str) -> str:
    label = "价格" if source == "price" else "链上流"
    if not ctx:
        return f"{label}缺失"
    age = ctx.get("age_minutes")
    if ctx.get("stale"):
        return f"{label}过期{age}分钟" if age is not None else f"{label}过期"
    analysis = ctx.get("analysis", {})
    return f"{label}{analysis.get('direction', '观察')}：{analysis.get('trade_signal', '观察')}"


def holder_decision_context(project: dict[str, Any], market_context: dict[str, dict[str, dict[str, Any]]] | None = None) -> dict[str, str]:
    context = market_context or {}
    symbol = str(project.get("symbol") or "").upper()
    price_ctx = context.get("price", {}).get(symbol, {})
    flow_ctx = context.get("flow", {}).get(symbol, {})
    holder_direction = str(project.get("signal", {}).get("direction") or "")
    price_bearish = context_is_bearish(price_ctx, source="price")
    flow_bearish = context_is_bearish(flow_ctx, source="flow")
    price_bullish = context_is_bullish(price_ctx, source="price")
    flow_bullish = context_is_bullish(flow_ctx, source="flow")
    bearish = price_bearish or flow_bearish
    bullish = price_bullish or flow_bullish
    evidence = "；".join([short_context(price_ctx, source="price"), short_context(flow_ctx, source="flow")])
    if holder_direction == "effective_top10_down":
        if bearish:
            return {
                "action": "偏空确认；持仓减仓/离场，空仓不接",
                "reason": f"前十分散同时出现价格走弱或链上卖出证据；{evidence}",
                "level": "CRITICAL",
            }
        return {
            "action": "持仓降风险；等 CEX/DEX/价格确认",
            "reason": f"前十分散已经出现，暂缺同向确认；{evidence}",
            "level": "HIGH",
        }
    if holder_direction == "effective_top10_up":
        if bearish:
            return {
                "action": "分歧；不追，先排除派发和诱多",
                "reason": f"前十集中上升但价格或链上流向偏空；{evidence}",
                "level": "HIGH",
            }
        if price_bullish and flow_bullish:
            return {
                "action": "吸筹有承接；只等回踩小仓试探",
                "reason": f"前十集中上升，价格和链上净买同向；{evidence}",
                "level": "HIGH",
            }
        if bullish:
            return {
                "action": "吸筹待确认；不追高",
                "reason": f"前十集中上升，只有一层市场证据同向；{evidence}",
                "level": "INFO",
            }
        return {
            "action": "吸筹观察；等价格承接和净买确认",
            "reason": f"前十集中上升，暂缺市场确认；{evidence}",
            "level": "INFO",
        }
    if holder_direction == "infra_top10_up":
        return {
            "action": "基础设施归集；不当成庄家吸筹",
            "reason": f"上升主要来自托管/CEX/池子类地址；{evidence}",
            "level": "INFO",
        }
    if bearish:
        return {
            "action": "holder无方向；按价格/链上偏空处理",
            "reason": f"前十未给出方向，但市场证据偏空；{evidence}",
            "level": "HIGH",
        }
    if bullish:
        return {
            "action": "holder无方向；价格/链上偏多，等承接",
            "reason": f"前十未给出方向，市场证据偏多；{evidence}",
            "level": "INFO",
        }
    return {
        "action": "观察；holder只作辅助",
        "reason": f"前十、价格和链上流向都没有形成同向结论；{evidence}",
        "level": "INFO",
    }


def contract_items(config: dict[str, Any]) -> list[dict[str, str]]:
    priorities = tuple(part.strip() for part in os.environ.get("ALPHA_HOLDER_PRIORITIES", "P0,P1").split(",") if part.strip())
    max_projects = max(1, int(os.environ.get("ALPHA_HOLDER_MAX_PROJECTS", "8")))
    catalog_rows: list[dict[str, str]] = []
    configured_rows: list[dict[str, str]] = []
    for item in config.get("items", []):
        if item.get("active_monitoring") is False:
            continue
        if item.get("project_watch_skip_generic") and os.environ.get("ALPHA_HOLDER_INCLUDE_SPECIALIZED") != "1":
            continue
        priority = str(item.get("priority", ""))
        if priorities and not priority.startswith(priorities):
            continue
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        for contract in item.get("contracts", []):
            chain = str(contract.get("chain", "")).lower()
            address = norm(contract.get("address"))
            if chain in SUPPORTED_CHAINS and is_address(address):
                row = {
                    "symbol": symbol,
                    "name": str(item.get("name") or ""),
                    "priority": priority,
                    "chain": chain,
                    "address": address,
                }
                facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
                target = catalog_rows if facts.get("alpha_id") else configured_rows
                target.append(row)
                break
    return (catalog_rows + configured_rows)[:max_projects]


def full_holder_source_status(chain: str, token: str) -> dict[str, Any]:
    source = os.environ.get(FULL_HOLDER_SOURCE_ENV, "none").strip().lower()
    if source in {"", "none", "off", "disabled"}:
        return {
            "source": "none",
            "status": "not_configured",
            "summary": "未接入；当前显示窗口重建口径",
        }
    if source == "bscscan":
        api_key = os.environ.get("BSCSCAN_API_KEY") or os.environ.get("BSC_SCAN_API_KEY")
        if not api_key:
            return {
                "source": "bscscan",
                "status": "missing_credentials",
                "summary": "BscScan 未配置密钥；当前显示窗口重建口径",
            }
    elif source == "gmgn":
        if not os.environ.get("GMGN_API_KEY"):
            return {
                "source": "gmgn",
                "status": "missing_credentials",
                "summary": "GMGN 未配置密钥；当前显示窗口重建口径",
            }
    elif source == "surf":
        return surf_full_holder_status(chain, token)
    else:
        return {
            "source": source,
            "status": "unsupported",
            "summary": f"{source} 暂未支持；当前显示窗口重建口径",
        }
    return {
        "source": source,
        "status": "configured_unimplemented",
        "summary": f"{source} 已配置，读取器待接入；当前显示窗口重建口径",
    }


def merge_retention_events(
    *groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in (
        event
        for group in groups
        for event in group
        if isinstance(event, dict)
    ):
        identity = (
            str(event.get("sample_tx") or event.get("tx") or ""),
            str(
                event.get("sample_log_index")
                or event.get("log_index")
                or 0
            ),
            str(event.get("type") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(copy.deepcopy(event))
    return merged


def build_token_snapshot(
    item: dict[str, str],
    config: dict[str, Any],
    state: dict[str, Any],
    retention_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = item["symbol"]
    chain = item["chain"]
    token = norm(item["address"])
    key = f"{chain}:{token}"
    finality = int(os.environ.get("ALPHA_HOLDER_FINALITY_BLOCKS", "20"))
    lookback = int(os.environ.get("ALPHA_HOLDER_LOOKBACK_BLOCKS", "50000"))
    raw_tip = latest_block(chain)
    tip = max(0, raw_tip - finality)
    tokens_state = state.get("tokens")
    if not isinstance(tokens_state, dict):
        tokens_state = {}
    token_state = tokens_state.get(key, {})
    previous_metrics = token_state.get("last_metrics")
    previous_tip = int(token_state.get("latest_block") or 0)
    holder_baseline_status = str(token_state.get("holder_baseline_status") or "")
    retention_state = (
        token_state.get("retention_flow")
        if isinstance(token_state.get("retention_flow"), dict)
        else {}
    )
    retention_previous_tip = int(retention_state.get("latest_block") or 0)
    retention_was_catching_up = (
        retention_state.get("catchup_active") is True
    )
    liquidity_state = (
        retention_state.get("liquidity")
        if isinstance(retention_state.get("liquidity"), dict)
        else {}
    )
    holder_scan_skipped = (
        holder_baseline_status == BOUNDED_BOOTSTRAP_UNRELIABLE
    )
    if holder_scan_skipped:
        from_block = previous_tip + 1 if previous_tip < tip else previous_tip
        balances = {
            addr: int(value)
            for addr, value in token_state.get(
                "balances_raw",
                {},
            ).items()
        }
        basis_from_block = int(
            token_state.get("basis_from_block")
            or max(0, previous_tip - lookback)
        )
        logs: list[dict[str, Any]] = []
        errors: list[str] = []
        truncated = False
        scan_tip = previous_tip
        incremental_catchup = {
            "applicable": False,
            "active": False,
            "reason": "holder_baseline_unavailable_retention_only",
            "requested_to_block": tip,
            "selected_to_block": previous_tip,
            "attempt_count": 0,
            "complete_selected_window": True,
            "complete_requested_window": False,
        }
    elif previous_tip and previous_tip < tip:
        from_block = previous_tip + 1
        balances = {addr: int(value) for addr, value in token_state.get("balances_raw", {}).items()}
        basis_from_block = int(token_state.get("basis_from_block") or max(0, tip - lookback))
        (
            logs,
            errors,
            truncated,
            scan_tip,
            incremental_catchup,
        ) = bounded_incremental_transfer_logs(
            chain,
            token,
            from_block,
            tip,
        )
    else:
        from_block = max(0, tip - lookback)
        balances = {}
        basis_from_block = from_block
        logs, errors, truncated = transfer_logs(
            chain,
            token,
            from_block,
            tip,
        )
        scan_tip = tip
        incremental_catchup = {
            "applicable": False,
            "active": False,
            "requested_to_block": tip,
            "selected_to_block": tip,
            "attempt_count": 1,
            "complete_selected_window": not errors and not truncated,
            "complete_requested_window": not errors and not truncated,
        }
    bootstrap = {
        "active": False,
        "requested_from_block": from_block,
        "selected_from_block": from_block,
        "attempt_count": 0,
        "complete_selected_window": not errors and not truncated,
    }
    if previous_tip <= 0 and truncated:
        requested_from_block = from_block
        (
            logs,
            errors,
            truncated,
            from_block,
            bootstrap,
        ) = bounded_bootstrap_transfer_logs(
            chain,
            token,
            requested_from_block,
            tip,
        )
        basis_from_block = from_block
        scan_tip = tip
    coverage_failed = bool(errors or truncated)
    if (
        holder_baseline_status == BOUNDED_BOOTSTRAP_UNRELIABLE
        or (bootstrap["active"] and not coverage_failed)
    ):
        holder_baseline_status = BOUNDED_BOOTSTRAP_UNRELIABLE
    comparison_metrics = (
        None
        if holder_baseline_status == BOUNDED_BOOTSTRAP_UNRELIABLE
        else previous_metrics
    )
    if not coverage_failed:
        balances = apply_transfers(balances, logs)
    decimals = int(token_state.get("decimals") or token_decimals(chain, token))
    supply_raw = token_total_supply_raw(chain, token)
    supply_source = "totalSupply"
    if supply_raw <= 0:
        supply_raw = sum(value for value in balances.values() if value > 0)
        supply_source = "observed_positive_balances"
    watch_labels = watch_address_labels(config, symbol, chain)
    raw_rows = top_rows(balances, chain, token, supply_raw, decimals, watch_labels, effective=False)
    effective_rows = top_rows(balances, chain, token, supply_raw, decimals, watch_labels, effective=True)
    raw_pct = pct_sum(raw_rows)
    effective_pct = pct_sum(effective_rows)
    infra_pct = raw_top10_infra_pct(raw_rows)
    if coverage_failed:
        metrics = dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
        failure_reason = (
            errors[0]
            if errors
            else f"eth_getLogs coverage truncated at {int(os.environ.get('ALPHA_HOLDER_MAX_LOGS_PER_TOKEN', '30000'))} rows"
        )
        signal = {
            "level": "ERROR",
            "action": "holder扫描失败",
            "reason": failure_reason,
        }
    else:
        metrics = {
            "raw_top10_pct": str(raw_pct),
            "effective_top10_pct": str(effective_pct),
            "raw_top10_infra_pct": str(infra_pct),
        }
        if comparison_metrics:
            metrics.update(
                {
                    "raw_top10_delta_pct": str(raw_pct - decimal_from(comparison_metrics.get("raw_top10_pct"))),
                    "effective_top10_delta_pct": str(effective_pct - decimal_from(comparison_metrics.get("effective_top10_pct"))),
                    "raw_top10_infra_delta_pct": str(infra_pct - decimal_from(comparison_metrics.get("raw_top10_infra_pct"))),
                }
            )
        if holder_baseline_status == BOUNDED_BOOTSTRAP_UNRELIABLE:
            signal = {
                "direction": "baseline_unavailable",
                "action": "holder基线不可用；仅保留链上流向监控",
                "reason": "首次请求窗口超出日志上限，当前有界窗口及后续增量不用于筹码集中度比较",
                "level": "INFO",
            }
        else:
            signal = classify_signal(metrics, comparison_metrics)
    config_item = config_item_for_contract(config, symbol, chain, token)
    resolved_retention_context = retention_context or {
        "opening": read_json(
            OPENING_CONTEXT_PATH,
            {"events": []},
        ),
        "project": read_json(
            PROJECT_CONTEXT_PATH,
            {"projects": []},
        ),
    }
    retention_logs = logs
    retention_errors = errors
    retention_truncated = truncated
    retention_scan_from = from_block
    retention_scan_to = scan_tip
    retention_target_scan_to = scan_tip
    retention_coverage_mode = "full_transfer_stream"
    retention_coverage_metadata: dict[str, Any] = {}
    retention_alert_from_block: int | None = None
    persisted_retention_actors = deserialize_retention_actors(
        retention_state.get("actor_scope")
    )
    persisted_opening_actors = opening_only_retention_actors(
        persisted_retention_actors
    )
    persisted_opening_scope_complete = bool(
        retention_state.get("opening_scope_complete") is True
        and int(
            retention_state.get("scope_state_schema_version")
            or 0
        )
        == RETENTION_SCOPE_STATE_SCHEMA_VERSION
        and int(retention_state.get("opening_actor_count") or 0)
        == len(persisted_opening_actors)
        and str(
            retention_state.get("opening_actor_scope_hash")
            or ""
        )
        == opening_actor_scope_hash(persisted_opening_actors)
    )
    (
        retention_actors,
        retention_cex_addresses,
        retention_evidence_by_tx,
        retention_scope_metadata,
    ) = retention_evidence_scope(
        config_item,
        symbol,
        chain,
        token,
        resolved_retention_context,
        persisted_actors=persisted_retention_actors,
        persisted_opening_scope_complete=(
            persisted_opening_scope_complete
        ),
    )
    previous_retention_scope_hash = str(
        retention_state.get("scope_hash") or ""
    )
    current_retention_scope_hash = str(
        retention_scope_metadata.get("scope_hash") or ""
    )
    retention_scope_rebaseline = False
    retention_scope_coverage_from = int(
        retention_state.get("scope_coverage_from_block") or 0
    )
    if (
        holder_scan_skipped
        and retention_window(config_item, chain).get("status")
        == "active"
    ):
        retention_bootstrap_blocks = max(
            1,
            int(
                os.environ.get(
                    "ALPHA_RETENTION_BOOTSTRAP_BLOCKS",
                    "2400",
                )
            ),
        )
        retention_live_tail_blocks = max(
            1,
            int(
                os.environ.get(
                    "ALPHA_RETENTION_LIVE_TAIL_BLOCKS",
                    "1200",
                )
            ),
        )
        retention_scan_from = (
            retention_previous_tip + 1
            if retention_previous_tip > 0
            else max(0, tip - retention_bootstrap_blocks + 1)
        )
        retention_scope_rebaseline = bool(
            retention_previous_tip <= 0
            or not previous_retention_scope_hash
            or previous_retention_scope_hash
            != current_retention_scope_hash
        )
        if retention_scope_rebaseline:
            retention_scope_coverage_from = (
                retention_scope_coverage_from
                or max(
                    0,
                    tip - retention_bootstrap_blocks + 1,
                )
            )
            retention_scan_from = retention_scope_coverage_from
        elif retention_scope_coverage_from <= 0:
            retention_scope_coverage_from = retention_scan_from
        retention_scan_to = tip
        retention_target_scan_to = tip
        if (
            retention_scope_metadata.get(
                "opening_scope_complete"
            )
            is not True
        ):
            retention_logs = []
            retention_errors = [
                "retention opening actor scope incomplete"
            ]
            retention_truncated = False
            retention_coverage_metadata = {
                "coverage_mode": "targeted_indexed_topics",
                "query_scope_complete": False,
                "query_count": 0,
                "tracked_actor_count": len(retention_actors),
                "cex_address_count": len(
                    retention_cex_addresses
                ),
                "scope_kind_count": 0,
                "scope_batch_count": 0,
                "applicable": True,
                "active": False,
                "requested_to_block": tip,
                "selected_to_block": tip,
                "attempt_count": 0,
                "complete_selected_window": False,
                "complete_requested_window": False,
            }
        else:
            (
                retention_logs,
                retention_errors,
                retention_truncated,
                retention_scan_to,
                retention_coverage_metadata,
            ) = bounded_targeted_retention_logs(
                chain,
                token,
                retention_scan_from,
                tip,
                retention_actors,
                retention_cex_addresses,
            )
        retention_coverage_mode = "targeted_indexed_topics"
        retention_alert_from_block = (
            tip + 1
            if (
                retention_scope_rebaseline
                or retention_was_catching_up
                or retention_coverage_metadata.get("active")
                is True
            )
            else max(
                retention_scan_from,
                tip - retention_live_tail_blocks + 1,
            )
        )
    retention_flow = build_retention_flow(
        item=config_item,
        symbol=symbol,
        chain=chain,
        token=token,
        logs=retention_logs,
        errors=retention_errors,
        truncated=retention_truncated,
        decimals=decimals,
        supply_raw=supply_raw,
        scan_from_block=retention_scan_from,
        scan_to_block=retention_scan_to,
        previous_latest_block=retention_previous_tip,
        holder_previous_latest_block=previous_tip,
        context=resolved_retention_context,
        coverage_mode=retention_coverage_mode,
        coverage_metadata=retention_coverage_metadata,
        alert_from_block=retention_alert_from_block,
        scope_actors=retention_actors,
        scope_cex_addresses=retention_cex_addresses,
        scope_evidence_by_tx=retention_evidence_by_tx,
        scope_metadata=retention_scope_metadata,
        scope_rebaseline=retention_scope_rebaseline,
        previous_scope_hash=previous_retention_scope_hash,
        scope_coverage_from_block=retention_scope_coverage_from,
        target_scan_to_block=retention_target_scan_to,
    )
    retention_flow["previous_catchup_active"] = (
        retention_was_catching_up
    )
    (
        liquidity_retention,
        next_liquidity_state,
    ) = build_token_liquidity_retention(
        item=config_item,
        symbol=symbol,
        chain=chain,
        token=token,
        tip=raw_tip,
        decimals=decimals,
        supply_raw=supply_raw,
        opening_payload=resolved_retention_context.get("opening") or {},
        liquidity_state=liquidity_state,
    )
    retention_flow["liquidity_retention"] = liquidity_retention
    catchup_pending = bool(
        not coverage_failed
        and
        incremental_catchup.get("applicable") is True
        and incremental_catchup.get("complete_requested_window") is not True
    )
    previous_pending_retention = [
        event
        for event in retention_state.get("pending_alert_events", [])
        if isinstance(event, dict)
    ]
    current_retention_events = [
        event
        for event in retention_flow.get("events", [])
        if isinstance(event, dict)
    ]
    pending_retention_events: list[dict[str, Any]] = []
    if catchup_pending:
        pending_retention_events = merge_retention_events(
            previous_pending_retention,
            [
                event
                for event in current_retention_events
                if str(event.get("level") or "").upper()
                in {"HIGH", "CRITICAL"}
            ],
        )
    else:
        historical_catchup_events = [
            {
                **event,
                "historical_catchup": True,
                "alert_eligible": False,
            }
            for event in previous_pending_retention
        ]
        retention_flow["events"] = merge_retention_events(
            historical_catchup_events,
            current_retention_events,
        )
    retention_flow["pending_alert_event_count"] = len(
        pending_retention_events
    )
    previous_historical_retention = [
        event
        for event in retention_state.get("historical_events", [])
        if isinstance(event, dict)
    ]
    current_historical_retention = [
        event
        for event in retention_flow.get("events", [])
        if isinstance(event, dict)
        and (
            event.get("historical_catchup") is True
            or event.get("alert_eligible") is False
        )
    ]
    historical_retention_events = merge_retention_events(
        previous_historical_retention,
        current_historical_retention,
    )[-100:]
    retention_flow["events"] = merge_retention_events(
        historical_retention_events,
        [
            event
            for event in retention_flow.get("events", [])
            if isinstance(event, dict)
            and event.get("historical_catchup") is not True
            and event.get("alert_eligible") is not False
        ],
    )
    if catchup_pending:
        signal = {
            "direction": "catchup_pending",
            "action": "holder增量积压追赶中；暂不发方向信号",
            "reason": (
                f"已完整处理至区块 {scan_tip}，"
                f"目标区块 {tip}；追平后统一比较筹码变化"
            ),
            "level": "INFO",
        }
    holder_checkpoint_can_advance = not coverage_failed
    retention_checkpoint_can_advance = (
        retention_flow.get("selected_window_complete") is True
    )
    liquidity_checkpoint_can_advance = next_liquidity_state is not None
    current_opening_scope_complete = bool(
        int(
            retention_scope_metadata.get(
                "matching_event_count"
            )
            or 0
        )
        > 0
        and retention_scope_metadata.get(
            "opening_scope_complete"
        )
        is True
    )
    scope_state_can_advance = current_opening_scope_complete
    scope_state_valid_for_write = bool(
        scope_state_can_advance
        or (
            int(
                retention_scope_metadata.get(
                    "matching_event_count"
                )
                or 0
            )
            == 0
            and persisted_opening_scope_complete
        )
    )
    checkpoint_tip = (
        scan_tip
        if holder_checkpoint_can_advance
        else previous_tip
    )
    negative_count = sum(1 for value in balances.values() if value < 0)
    positive_count = sum(1 for value in balances.values() if value > 0)
    complete = (
        not coverage_failed
        and basis_from_block == 0
        and negative_count == 0
    )
    coverage_note = (
        "holder_baseline_unavailable_retention_only"
        if holder_scan_skipped
        else "log_coverage_failed"
        if errors
        else "log_coverage_truncated"
        if truncated
        else "bounded_bootstrap_window_after_truncation"
        if bootstrap["active"]
        else "incremental_catchup_pending"
        if incremental_catchup["active"]
        else "complete_from_genesis"
        if complete
        else "window_or_incremental_reconstruction"
    )
    payload = {
        **item,
        "raw_latest_block": raw_tip,
        "latest_block": checkpoint_tip,
        "previous_latest_block": previous_tip,
        "basis_from_block": basis_from_block,
        "scan_from_block": from_block,
        "scan_to_block": scan_tip,
        "target_latest_block": tip,
        "log_count": len(logs),
        "log_error_count": len(errors),
        "log_errors": errors[:3],
        "truncated": truncated,
        "bounded_bootstrap": bootstrap,
        "incremental_catchup": incremental_catchup,
        "holder_scan_status": (
            "skipped_unreliable_baseline"
            if holder_scan_skipped
            else "scanned"
        ),
        "holder_baseline_status": holder_baseline_status,
        "complete_holder_reconstruction": complete,
        "coverage_note": coverage_note,
        "decimals": decimals,
        "total_supply_raw": str(supply_raw),
        "total_supply": str(decimal_amount(supply_raw, decimals)) if supply_raw else "0",
        "supply_source": supply_source,
        "positive_holder_count": positive_count,
        "negative_balance_count": negative_count,
        "metrics": metrics,
        "signal": signal,
        "retention_flow": retention_flow,
        "top10_raw": raw_rows,
        "top10_effective": effective_rows,
        "full_holder_source": full_holder_source_status(chain, token),
    }
    token_state_next = (
        state.setdefault("tokens", {}).setdefault(key, {})
        if (
            holder_checkpoint_can_advance
            or retention_checkpoint_can_advance
            or scope_state_can_advance
            or liquidity_checkpoint_can_advance
        )
        else token_state
    )
    if holder_checkpoint_can_advance:
        token_state_next.update(
            {
                "symbol": symbol,
                "chain": chain,
                "address": token,
                "decimals": decimals,
                "basis_from_block": basis_from_block,
                "latest_block": checkpoint_tip,
                "last_metrics": (
                    {}
                    if holder_baseline_status
                    == BOUNDED_BOOTSTRAP_UNRELIABLE
                    else token_state.get("last_metrics", {})
                    if catchup_pending
                    else metrics
                ),
                "balances_raw": {addr: str(value) for addr, value in balances.items() if value != 0},
                "holder_baseline_status": holder_baseline_status,
            }
        )
    if retention_checkpoint_can_advance:
        token_state_next.update(
            {
                "symbol": symbol,
                "chain": chain,
                "address": token,
            }
        )
        next_retention_state = dict(
            token_state_next.get("retention_flow")
            if isinstance(
                token_state_next.get("retention_flow"),
                dict,
            )
            else {}
        )
        next_retention_state.update(
            {
                "latest_block": int(
                    retention_flow.get("latest_block")
                    or retention_scan_to
                ),
                "pending_alert_events": pending_retention_events,
                "historical_events": historical_retention_events,
                "scope_coverage_from_block": int(
                    retention_flow.get(
                        "scope_coverage_from_block"
                    )
                    or retention_scan_from
                ),
                "catchup_active": (
                    (
                        retention_flow.get(
                            "incremental_catchup"
                        )
                        or {}
                    ).get("active")
                    is True
                ),
            }
        )
        if scope_state_valid_for_write:
            next_retention_state["scope_hash"] = (
                current_retention_scope_hash
            )
        token_state_next["retention_flow"] = next_retention_state
    if scope_state_valid_for_write:
        next_retention_state = dict(
            token_state_next.get("retention_flow")
            if isinstance(
                token_state_next.get("retention_flow"),
                dict,
            )
            else {}
        )
        opening_scope_actors = opening_only_retention_actors(
            retention_actors
        )
        next_retention_state.update(
            {
                "actor_scope": serialize_retention_actors(
                    opening_scope_actors
                ),
                "opening_scope_complete": True,
                "opening_actor_count": len(
                    opening_scope_actors
                ),
                "opening_actor_scope_hash": (
                    opening_actor_scope_hash(
                        opening_scope_actors
                    )
                ),
                "scope_state_schema_version": (
                    RETENTION_SCOPE_STATE_SCHEMA_VERSION
                ),
            }
        )
        token_state_next["retention_flow"] = next_retention_state
    if next_liquidity_state is not None:
        next_retention_state = dict(
            token_state_next.get("retention_flow")
            if isinstance(
                token_state_next.get("retention_flow"),
                dict,
            )
            else {}
        )
        next_retention_state["liquidity"] = next_liquidity_state
        token_state_next["retention_flow"] = next_retention_state
    return payload


def build_snapshot_within_deadline() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, {"items": []})
    state = read_json(STATE_PATH, {"tokens": {}})
    market_context = latest_market_context()
    retention_context = {
        "opening": read_json(OPENING_CONTEXT_PATH, {"events": []}),
        "project": read_json(PROJECT_CONTEXT_PATH, {"projects": []}),
    }
    projects = []
    for item in contract_items(config):
        try:
            project = build_token_snapshot(item, config, state, retention_context)
            project["decision_context"] = holder_decision_context(project, market_context)
            projects.append(project)
        except Exception as exc:
            project = {**item, "error": str(exc), "metrics": {}, "signal": {"level": "ERROR", "action": "holder扫描失败", "reason": str(exc)}}
            project["decision_context"] = holder_decision_context(project, market_context)
            projects.append(project)
    snapshot = {
        "generated_at": now_iso(),
        "config_path": str(CONFIG_PATH),
        "project_count": len(projects),
        "alert_count": sum(
            1
            for item in projects
            if holder_signal_key(item)
        )
        + sum(
            len(retention_alert_events(item))
            for item in projects
        ),
        "projects": projects,
        "_next_state": state,
    }
    return snapshot


def build_snapshot() -> dict[str, Any]:
    global HOLDER_DEADLINE_AT

    previous_deadline = HOLDER_DEADLINE_AT
    configure_holder_deadline()
    try:
        return build_snapshot_within_deadline()
    finally:
        HOLDER_DEADLINE_AT = previous_deadline


def holder_alert_coverage_complete(project: dict[str, Any]) -> bool:
    if int(project.get("log_error_count") or 0) or project.get("truncated"):
        return False
    catchup = project.get("incremental_catchup")
    if not isinstance(catchup, dict):
        return False
    if catchup.get("applicable") is False:
        return True
    return bool(
        catchup.get("applicable") is True
        and catchup.get("active") is False
        and catchup.get("complete_selected_window") is True
        and catchup.get("complete_requested_window") is True
    )


def retention_alert_coverage_complete(
    project: dict[str, Any],
) -> bool:
    retention = (
        project.get("retention_flow")
        if isinstance(project.get("retention_flow"), dict)
        else {}
    )
    base_complete = bool(
        retention.get("status") == "active"
        and retention.get("complete") is True
        and not int(retention.get("log_error_count") or 0)
        and not retention.get("truncated")
        and not retention.get("events_truncated")
    )
    if not base_complete:
        return False
    if retention.get("coverage_mode") != "targeted_indexed_topics":
        if (
            project.get("holder_baseline_status")
            == BOUNDED_BOOTSTRAP_UNRELIABLE
        ):
            return False
        return holder_alert_coverage_complete(project)
    scope_hash = str(retention.get("scope_hash") or "")
    previous_scope_hash = str(
        retention.get("previous_scope_hash") or ""
    )
    catchup = (
        retention.get("incremental_catchup")
        if isinstance(
            retention.get("incremental_catchup"),
            dict,
        )
        else {}
    )
    try:
        query_count = int(retention.get("query_count") or 0)
        scope_batch_count = int(
            retention.get("scope_batch_count") or 0
        )
        scope_kind_count = int(
            retention.get("scope_kind_count") or 0
        )
        query_chunk_count = int(
            retention.get("query_chunk_count") or 0
        )
        expected_query_count = int(
            retention.get("expected_query_count") or 0
        )
        actor_count = int(
            retention.get("opening_buyer_count") or 0
        )
        actor_count += int(
            retention.get("opening_cohort_recipient_count")
            or 0
        )
        actor_count += int(
            retention.get("verified_project_address_count")
            or 0
        )
        cex_count = int(
            retention.get("cex_address_count") or 0
        )
        opening_actor_count = int(
            retention.get("opening_actor_count") or 0
        )
        scan_from = int(retention.get("scan_from_block") or 0)
        scan_to = int(retention.get("scan_to_block") or 0)
        previous_latest = int(
            retention.get("previous_latest_block") or 0
        )
        latest = int(retention.get("latest_block") or 0)
        target_latest = int(
            retention.get("target_latest_block") or 0
        )
        requested_to = int(catchup["requested_to_block"])
        selected_to = int(catchup["selected_to_block"])
    except (TypeError, ValueError):
        return False
    except KeyError:
        return False
    opening_scope_hash = str(
        retention.get("opening_actor_scope_hash") or ""
    )
    return bool(
        retention.get("opening_scope_complete") is True
        and retention.get("selected_window_complete") is True
        and len(scope_hash) == 64
        and all(
            character in "0123456789abcdef"
            for character in scope_hash.lower()
        )
        and previous_scope_hash == scope_hash
        and retention.get("scope_rebaseline") is not True
        and retention.get("previous_catchup_active") is not True
        and retention.get("query_scope_complete") is True
        and retention.get("continuous") is True
        and query_chunk_count > 0
        and scope_kind_count > 0
        and actor_count + cex_count > 0
        and scope_batch_count > 0
        and expected_query_count
        == scope_batch_count * query_chunk_count
        and query_count == expected_query_count
        and retention.get("scope_state_schema_version")
        == RETENTION_SCOPE_STATE_SCHEMA_VERSION
        and opening_actor_count >= 0
        and len(opening_scope_hash) == 64
        and all(
            character in "0123456789abcdef"
            for character in opening_scope_hash.lower()
        )
        and catchup.get("applicable") is True
        and catchup.get("active") is False
        and catchup.get("complete_selected_window") is True
        and catchup.get("complete_requested_window") is True
        and requested_to == target_latest
        and selected_to == scan_to == requested_to
        and scan_from == previous_latest + 1
        and scan_from <= scan_to
        and latest == scan_to == target_latest
    )


def liquidity_retention_alert_coverage_complete(
    project: dict[str, Any],
) -> bool:
    retention = (
        project.get("retention_flow")
        if isinstance(project.get("retention_flow"), dict)
        else {}
    )
    liquidity = (
        retention.get("liquidity_retention")
        if isinstance(
            retention.get("liquidity_retention"),
            dict,
        )
        else {}
    )
    catchup = (
        liquidity.get("incremental_catchup")
        if isinstance(liquidity.get("incremental_catchup"), dict)
        else {}
    )
    try:
        pool_count = int(liquidity.get("pool_count") or 0)
        v3_count = int(liquidity.get("v3_pool_count") or 0)
        v4_count = int(liquidity.get("v4_pool_count") or 0)
        v4_manager_count = int(
            liquidity.get("v4_manager_count") or 0
        )
        event_filter_count = int(
            liquidity.get("event_filter_count") or 0
        )
        query_count = int(liquidity.get("query_count") or 0)
        scope_batch_count = int(
            liquidity.get("scope_batch_count") or 0
        )
        query_chunk_count = int(
            liquidity.get("query_chunk_count") or 0
        )
        expected_query_count = int(
            liquidity.get("expected_query_count") or 0
        )
        scan_from = int(liquidity.get("scan_from_block") or 0)
        scan_to = int(liquidity.get("scan_to_block") or 0)
        previous_latest = int(
            liquidity.get("previous_latest_block") or 0
        )
        latest = int(liquidity.get("latest_block") or 0)
        target_latest = int(
            liquidity.get("target_latest_block") or 0
        )
        observed_latest = int(
            liquidity.get("observed_latest_block") or 0
        )
        confirmation_blocks = int(
            liquidity.get("confirmation_blocks") or 0
        )
        requested_to = int(catchup["requested_to_block"])
        selected_to = int(catchup["selected_to_block"])
    except (KeyError, TypeError, ValueError):
        return False
    scope_hash = str(liquidity.get("scope_hash") or "")
    previous_scope_hash = str(
        liquidity.get("previous_scope_hash") or ""
    )
    latest_block_hash = str(
        liquidity.get("latest_block_hash") or ""
    ).lower()
    return bool(
        liquidity.get("status") == "active"
        and liquidity.get("coverage_mode")
        == "verified_pool_indexed_topics"
        and liquidity.get("complete") is True
        and liquidity.get("selected_window_complete") is True
        and liquidity.get("scope_complete") is True
        and not int(liquidity.get("log_error_count") or 0)
        and liquidity.get("truncated") is not True
        and liquidity.get("events_truncated") is not True
        and liquidity.get("query_scope_complete") is True
        and liquidity.get("scope_rebaseline") is not True
        and liquidity.get("previous_catchup_active") is not True
        and liquidity.get("continuous") is True
        and liquidity.get("scope_state_schema_version")
        == LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
        and len(scope_hash) == 64
        and all(
            character in "0123456789abcdef"
            for character in scope_hash.lower()
        )
        and previous_scope_hash == scope_hash
        and valid_hash32(latest_block_hash)
        and int(latest_block_hash[2:], 16) != 0
        and confirmation_blocks >= 0
        and target_latest
        == max(0, observed_latest - confirmation_blocks)
        and pool_count > 0
        and pool_count == v3_count + v4_count
        and scope_batch_count
        == int(v3_count > 0) + v4_manager_count
        and v4_manager_count
        >= int(v4_count > 0)
        and v4_manager_count <= v4_count
        and event_filter_count == v3_count * 4 + v4_count * 2
        and query_chunk_count > 0
        and expected_query_count
        == scope_batch_count * query_chunk_count
        and query_count == expected_query_count
        and catchup.get("applicable") is True
        and catchup.get("active") is False
        and catchup.get("complete_selected_window") is True
        and catchup.get("complete_requested_window") is True
        and requested_to == selected_to == scan_to == target_latest
        and scan_from == previous_latest + 1
        and scan_from <= scan_to
        and latest == scan_to
    )


def retention_alert_events(project: dict[str, Any]) -> list[dict[str, Any]]:
    retention = (
        project.get("retention_flow")
        if isinstance(project.get("retention_flow"), dict)
        else {}
    )
    events: list[dict[str, Any]] = []
    if retention_alert_coverage_complete(project):
        events.extend(retention.get("events", []) or [])
    if liquidity_retention_alert_coverage_complete(project):
        liquidity = retention.get("liquidity_retention") or {}
        events.extend(liquidity.get("events", []) or [])
    return [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("historical_catchup") is not True
        and event.get("alert_eligible") is not False
        and str(event.get("level") or "").upper()
        in {"HIGH", "CRITICAL"}
    ]


def holder_signal_key(project: dict[str, Any]) -> str:
    if not holder_alert_coverage_complete(project):
        return ""
    if project.get("holder_baseline_status") == BOUNDED_BOOTSTRAP_UNRELIABLE:
        return ""
    signal = project.get("signal", {})
    if signal.get("level") not in {"HIGH", "CRITICAL"}:
        return ""
    metrics = project.get("metrics", {})
    bucket = (
        decimal_from(metrics.get("effective_top10_delta_pct"))
        // Decimal("0.5")
    )
    return "|".join(
        [
            str(project.get("symbol") or ""),
            str(project.get("chain") or ""),
            str(project.get("address") or ""),
            str(signal.get("direction") or ""),
            str(bucket),
        ]
    )


def retention_event_key(
    project: dict[str, Any],
    event: dict[str, Any],
) -> str:
    parts = [
        str(project.get("chain") or ""),
        str(project.get("address") or ""),
    ]
    if event.get("pool"):
        parts.append(str(event.get("pool") or ""))
    parts.extend(
        [
            str(event.get("sample_tx") or event.get("tx") or ""),
            str(
                event.get("sample_log_index")
                or event.get("log_index")
                or 0
            ),
            str(event.get("type") or ""),
        ]
    )
    return "|".join(parts)


def alert_keys(snapshot: dict[str, Any]) -> list[str]:
    keys = []
    for project in snapshot.get("projects", []):
        signal_key = holder_signal_key(project)
        if signal_key:
            keys.append(signal_key)
        for event in retention_alert_events(project):
            keys.append(retention_event_key(project, event))
    return sorted(set(keys))


def send_telegram_batch(
    text: str,
    batch_keys: list[str],
    *,
    token: str,
    chat_id: str,
    seen: set[str],
    seen_path: Path | None = None,
    last_push_path: Path | None = None,
) -> None:
    resolved_seen_path = seen_path or SEEN_PATH
    resolved_last_push_path = last_push_path or LAST_PUSH_PATH
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        receipt = read_telegram_send_receipt(response)
    seen.update(batch_keys)
    atomic_write_json(resolved_seen_path, sorted(seen))
    record_telegram_send_receipt(
        resolved_last_push_path,
        sent_at=now_iso(),
        signature="\n".join(sorted(batch_keys)),
        text=text,
        receipt=receipt,
    )


def retention_event_amount_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    if str(event.get("amount") or ""):
        parts.append(f"合计 {format_amount(event.get('amount'))} 枚")
    if str(event.get("lp_added_amount") or ""):
        parts.append(
            "代币侧再投入 "
            f"{format_amount(event.get('lp_added_amount'))} 枚"
        )
    if str(event.get("collected_amount") or ""):
        parts.append(
            "代币侧提取 "
            f"{format_amount(event.get('collected_amount'))} 枚"
        )
    quote_symbol = str(
        event.get("quote_removed_symbol")
        or event.get("quote_added_symbol")
        or event.get("quote_collected_symbol")
        or "报价资产"
    )
    if str(event.get("quote_removed_amount") or ""):
        parts.append(
            "报价侧撤出 "
            f"{format_amount(event.get('quote_removed_amount'))} "
            f"{quote_symbol}"
        )
    if str(event.get("quote_added_amount") or ""):
        parts.append(
            "报价侧再投入 "
            f"{format_amount(event.get('quote_added_amount'))} "
            f"{quote_symbol}"
        )
    if str(event.get("quote_collected_amount") or ""):
        parts.append(
            "报价侧提取 "
            f"{format_amount(event.get('quote_collected_amount'))} "
            f"{quote_symbol}"
        )
    return "；".join(parts) if parts else "金额未归因"


def retention_telegram_text(
    project: dict[str, Any],
    events: list[dict[str, Any]],
) -> str:
    event_labels = {
        "realized_sell": "收据确认卖出",
        "cex_inflow_transfer_risk": "CEX 入金风险",
        "opening_buyer_outflow_transfer_risk": "首批狙击地址转出",
        "opening_cohort_recipient_outflow_transfer_risk": (
            "开盘接收地址转出"
        ),
        "project_or_mm_outflow_transfer_risk": "项目/做市地址外流",
        "verified_pool_sell_pressure": "已验证池大额卖压",
        "lp_remove_observation": "LP 撤出观察",
        "lp_partial_remove_observation": "LP 部分撤出观察",
        "lp_collect_observation": "LP 提取观察",
        "lp_rebalance_collect_observation": "LP 调仓提取观察",
        "lp_rebalance_observation": "LP 调仓观察",
        "liquidity_exit_with_sell": "撤池并卖出复合风险",
        "liquidity_partial_remove_with_sell": "部分撤池并卖出复合风险",
        "liquidity_rebalance_with_sell": "调池并卖出复合风险",
    }
    lines = [
        (
            f"Alpha 30天流向｜{project.get('symbol')} "
            f"{project.get('priority')}｜新增{len(events)}类"
        )
    ]
    for event in events:
        marker = "🚨" if event.get("level") == "CRITICAL" else "❗"
        lines.extend(
            [
                (
                    f"{marker}{event_labels.get(str(event.get('type') or ''), str(event.get('type') or '转移风险'))}"
                    f"｜{int(event.get('transfer_count') or 1)}笔"
                    f"｜{retention_event_amount_text(event)}"
                    f"｜{event.get('evidence_level')}"
                ),
                (
                    f"样本 {short_addr(str(event.get('pool') or event.get('sample_from') or event.get('from') or ''))} → "
                    f"{short_addr(str(event.get('sample_to') or event.get('to') or project.get('address') or ''))}｜"
                    f"tx {short_addr(str(event.get('sample_tx') or event.get('tx') or ''))}"
                ),
            ]
        )
    return "\n".join(lines)


def retention_telegram_batches(
    project: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    batches: list[tuple[str, list[dict[str, Any]]]] = []
    current: list[dict[str, Any]] = []
    for event in events:
        candidate = [*current, event]
        if (
            current
            and len(retention_telegram_text(project, candidate))
            > TELEGRAM_LIMIT
        ):
            batches.append(
                (
                    retention_telegram_text(project, current)[
                        :TELEGRAM_LIMIT
                    ],
                    current,
                )
            )
            current = [event]
        else:
            current = candidate
    if current:
        batches.append(
            (
                retention_telegram_text(project, current)[
                    :TELEGRAM_LIMIT
                ],
                current,
            )
        )
    return batches


def holder_only_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        **project,
        "retention_flow": {
            "status": "not_required",
            "events": [],
        },
    }


@contextmanager
def telegram_delivery_lock(
    lock_path: Path | None = None,
) -> Any:
    resolved_path = lock_path or TELEGRAM_LOCK_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with resolved_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def maybe_send_telegram(
    snapshot: dict[str, Any],
    *,
    seen_path: Path | None = None,
    last_push_path: Path | None = None,
    lock_path: Path | None = None,
) -> bool:
    if os.environ.get("DISABLE_TELEGRAM", "0") == "1":
        return True
    if os.environ.get("ALPHA_HOLDER_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return True
    resolved_seen_path = seen_path or SEEN_PATH
    resolved_last_push_path = last_push_path or LAST_PUSH_PATH
    with telegram_delivery_lock(lock_path):
        keys = alert_keys(snapshot)
        seen = set(read_json(resolved_seen_path, []))
        force = os.environ.get("ALPHA_HOLDER_FORCE_TELEGRAM") == "1"
        pending = set(
            keys if force else (key for key in keys if key not in seen)
        )
        if not pending and not force:
            return True
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return False

        for project in snapshot.get("projects", []):
            events = [
                event
                for event in retention_alert_events(project)
                if retention_event_key(project, event) in pending
            ]
            if not events:
                continue
            for text, batch_events in retention_telegram_batches(
                project,
                events,
            ):
                batch_keys = [
                    retention_event_key(project, event)
                    for event in batch_events
                ]
                send_telegram_batch(
                    text,
                    batch_keys,
                    token=token,
                    chat_id=chat_id,
                    seen=seen,
                    seen_path=resolved_seen_path,
                    last_push_path=resolved_last_push_path,
                )

        holder_projects = [
            holder_only_project(project)
            for project in snapshot.get("projects", [])
            if holder_signal_key(project) in pending
        ]
        for start in range(0, len(holder_projects), 2):
            batch = holder_projects[start : start + 2]
            batch_keys = [
                holder_signal_key(project)
                for project in batch
                if holder_signal_key(project)
            ]
            text = telegram_text(
                {
                    **snapshot,
                    "alert_count": len(batch),
                    "new_alert_count": len(batch_keys),
                    "_telegram_new_alert_keys": batch_keys,
                    "projects": batch,
                }
            )[:TELEGRAM_LIMIT]
            send_telegram_batch(
                text,
                batch_keys,
                token=token,
                chat_id=chat_id,
                seen=seen,
                seen_path=resolved_seen_path,
                last_push_path=resolved_last_push_path,
            )

        if force and not keys:
            send_telegram_batch(
                telegram_text({**snapshot, "projects": []}),
                [],
                token=token,
                chat_id=chat_id,
                seen=seen,
                seen_path=resolved_seen_path,
                last_push_path=resolved_last_push_path,
            )
        if pending - seen:
            return False
        return True


def telegram_text(snapshot: dict[str, Any]) -> str:
    new_keys = set(snapshot.get("_telegram_new_alert_keys") or [])
    active = sorted(
        (
            item
            for item in snapshot.get("projects", [])
            if item.get("signal", {}).get("level") in {"HIGH", "CRITICAL"}
            or retention_alert_events(item)
        ),
        key=lambda project: (
            0 if new_keys.intersection(alert_keys({"projects": [project]})) else 1,
            *holder_telegram_risk_key(project),
        ),
    )
    shown_projects = active[:2]
    trigger_count = int(snapshot.get("alert_count", len(active)) or 0)
    header = f"Alpha 前十持仓｜触发{trigger_count}"
    if "new_alert_count" in snapshot:
        header += f"｜新增{int(snapshot.get('new_alert_count') or 0)}"
    lines = [header]
    if not shown_projects:
        lines.append("无触发项目")
        return "\n".join(lines)
    for index, project in enumerate(shown_projects):
        signal = project.get("signal", {})
        metrics = project.get("metrics", {})
        decision = project_decision_context(project)
        effective_level = holder_effective_level(project)
        retention_events = retention_alert_events(project)
        marker = "🚨" if effective_level == "CRITICAL" else "❗"
        coverage = "全量" if project.get("complete_holder_reconstruction") else "窗口/增量"
        if index:
            lines.append("")
        if retention_events:
            event = retention_events[-1]
            event_labels = {
                "realized_sell": "收据确认卖出",
                "cex_inflow_transfer_risk": "CEX 入金风险",
                "opening_buyer_outflow_transfer_risk": "首批狙击地址转出",
                "opening_cohort_recipient_outflow_transfer_risk": (
                    "开盘接收地址转出"
                ),
                "project_or_mm_outflow_transfer_risk": "项目/做市地址外流",
                "verified_pool_sell_pressure": "已验证池大额卖压",
                "lp_remove_observation": "LP 撤出观察",
                "lp_partial_remove_observation": "LP 部分撤出观察",
                "lp_collect_observation": "LP 提取观察",
                "lp_rebalance_collect_observation": "LP 调仓提取观察",
                "lp_rebalance_observation": "LP 调仓观察",
                "liquidity_exit_with_sell": "撤池并卖出复合风险",
                "liquidity_partial_remove_with_sell": "部分撤池并卖出复合风险",
                "liquidity_rebalance_with_sell": "调池并卖出复合风险",
            }
            lines.extend(
                [
                    (
                        f"{marker}{project.get('symbol')} {project.get('priority')}"
                        f"｜30天流向｜{effective_level}"
                    ),
                    (
                        f"信号：{event_labels.get(str(event.get('type') or ''), str(event.get('type') or '转移风险'))}"
                        f"｜{int(event.get('transfer_count') or 1)}笔｜"
                        f"{retention_event_amount_text(event)}"
                        f"｜证据 {event.get('evidence_level')}"
                    ),
                    (
                        f"样本路径：{short_addr(str(event.get('pool') or event.get('sample_from') or event.get('from') or ''))}"
                        f" → {short_addr(str(event.get('sample_to') or event.get('to') or project.get('address') or ''))}"
                        f"｜tx {short_addr(str(event.get('sample_tx') or event.get('tx') or ''))}"
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    f"{marker}{project.get('symbol')} {project.get('priority')}｜{holder_direction_label(signal.get('direction'))}｜{effective_level}",
                    f"动作：{decision.get('action') or signal.get('action') or '观察'}",
                    (
                        f"排托管Top10 {format_user_pct(metrics.get('effective_top10_pct'))}"
                        f"（{compact_point_delta(metrics.get('effective_top10_delta_pct'))}）｜"
                        f"窗口Top10 {format_user_pct(metrics.get('raw_top10_pct'))}｜"
                        f"基础设施 {format_user_pct(metrics.get('raw_top10_infra_pct'))}｜{coverage}｜"
                        f"外部 {holder_external_summary(project)}"
                    ),
                ]
            )
    remaining = len(active) - len(shown_projects)
    if remaining > 0:
        lines.extend(["", f"另有{remaining}项｜详情已归档"])
    return "\n".join(lines).strip()


def holder_telegram_risk_key(project: dict[str, Any]) -> tuple[int, int, Decimal, str]:
    level_rank = {"CRITICAL": 2, "HIGH": 1}
    signal = project.get("signal", {})
    decision = project_decision_context(project)
    retention_rank = max(
        (
            level_rank.get(str(event.get("level") or "").upper(), 0)
            for event in retention_alert_events(project)
        ),
        default=0,
    )
    delta = abs(decimal_from(project.get("metrics", {}).get("effective_top10_delta_pct")))
    return (
        -max(level_rank.get(str(signal.get("level")), 0), retention_rank),
        -level_rank.get(str(decision.get("level")), 0),
        -delta,
        str(project.get("symbol") or ""),
    )


def holder_effective_level(project: dict[str, Any]) -> str:
    ranks = {"INFO": 0, "HIGH": 1, "CRITICAL": 2}
    signal_level = str(project.get("signal", {}).get("level") or "INFO")
    decision_level = str(project_decision_context(project).get("level") or "INFO")
    retention_levels = [
        str(event.get("level") or "INFO").upper()
        for event in retention_alert_events(project)
    ]
    return max(
        (signal_level, decision_level, *retention_levels),
        key=lambda level: ranks.get(level, 0),
    )


def holder_direction_label(value: Any) -> str:
    return {
        "effective_top10_down": "排托管前十分散",
        "effective_top10_up": "排托管前十集中",
        "infra_top10_up": "基础设施归集",
        "flat": "持仓平稳",
        "baseline": "基线",
    }.get(str(value or ""), str(value or "未知"))


def compact_point_delta(value: Any) -> str:
    amount = decimal_from(value).quantize(Decimal("0.01"))
    prefix = "+" if amount > 0 else ""
    return f"{prefix}{amount:f}pp"


def holder_external_summary(project: dict[str, Any]) -> str:
    summary = str(project.get("full_holder_source", {}).get("summary") or "")
    if summary.startswith("Surf全量Top10"):
        return summary.split("；", 1)[0]
    if "Surf免费额度已用完" in summary:
        return "Surf额度用完"
    if not summary or "未接入" in summary:
        return "未接入"
    return summary[:28]


def project_decision_context(project: dict[str, Any]) -> dict[str, str]:
    decision = project.get("decision_context")
    if isinstance(decision, dict) and decision.get("action"):
        return decision
    return holder_decision_context(project, {})


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Holder Concentration Watch",
        "",
        f"- generated_at: `{snapshot.get('generated_at')}`",
        f"- project_count: `{snapshot.get('project_count')}`",
        f"- alert_count: `{snapshot.get('alert_count')}`",
        "",
        "| Symbol | Chain | Contract | 排除托管后前十 | 窗口重建前十 | 交易所/托管/池子 | 外部全量Top10 | 动作 | 数据覆盖 | Logs |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for project in snapshot.get("projects", []):
        metrics = project.get("metrics", {})
        signal = project.get("signal", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{project.get('symbol', '')}`",
                    project.get("chain", ""),
                    f"`{short_addr(project.get('address', ''))}`",
                    f"{format_user_pct(metrics.get('effective_top10_pct'))}；{format_point_change(metrics.get('effective_top10_delta_pct'))}",
                    f"{format_user_pct(metrics.get('raw_top10_pct'))}；{format_point_change(metrics.get('raw_top10_delta_pct'))}",
                    format_user_pct(metrics.get("raw_top10_infra_pct")),
                    project.get("full_holder_source", {}).get("summary", ""),
                    f"{signal.get('action', '')}；{project_decision_context(project).get('action', '')}",
                    project.get("coverage_note", ""),
                    str(project.get("log_count", "")),
                ]
            )
            + " |"
        )
    for project in snapshot.get("projects", []):
        lines.extend(["", f"## {project.get('symbol')} 排除托管后的前十地址", ""])
        for row in project.get("top10_effective", [])[:10]:
            lines.append(f"- `{short_addr(row.get('address', ''))}` {format_user_pct(row.get('pct'))} {row.get('class')} {row.get('label')}")
        retention = project.get("retention_flow") or {}
        if retention.get("status") == "active":
            lines.extend(
                [
                    "",
                    "### 开盘至30天增量流向",
                    "",
                    (
                        f"- coverage: complete={retention.get('complete')} "
                        f"blocks={retention.get('scan_from_block')}..{retention.get('scan_to_block')}"
                    ),
                ]
            )
            for event in retention.get("events", [])[-10:]:
                lines.append(
                    (
                        f"- `{event.get('type')}` "
                        f"{int(event.get('transfer_count') or 1)}笔合计 "
                        f"{format_amount(event.get('amount'))}；样本 "
                        f"`{short_addr(str(event.get('sample_tx') or event.get('tx') or ''))}` "
                        f"{short_addr(str(event.get('sample_from') or event.get('from') or ''))} → "
                        f"{short_addr(str(event.get('sample_to') or event.get('to') or ''))} "
                        f"evidence={event.get('evidence_level')}"
                    )
                )
            liquidity = retention.get("liquidity_retention") or {}
            if liquidity:
                lines.extend(
                    [
                        "",
                        "### 已验证池连续流动性",
                        "",
                        (
                            f"- status={liquidity.get('status')} "
                            f"complete={liquidity.get('complete')} "
                            f"pools={liquidity.get('pool_count')} "
                            f"blocks={liquidity.get('scan_from_block')}..{liquidity.get('scan_to_block')}"
                        ),
                    ]
                )
                for event in liquidity.get("events", [])[-10:]:
                    amount = retention_event_amount_text(event)
                    lines.append(
                        (
                            f"- `{event.get('type')}` {amount}；pool "
                            f"`{short_addr(str(event.get('pool') or ''))}`；tx "
                            f"`{short_addr(str(event.get('tx') or ''))}` "
                            f"evidence={event.get('evidence_level')}"
                        )
                    )
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    next_state = snapshot.pop("_next_state", {"tokens": {}})
    atomic_write_json(LATEST_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    if not maybe_send_telegram(snapshot):
        print("holder Telegram delivery unavailable; checkpoint retained", file=sys.stderr)
        return 1
    atomic_write_json(STATE_PATH, next_state)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(f"holder_projects={snapshot['project_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
