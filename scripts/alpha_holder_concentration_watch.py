#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label, global_address_labels
from sniper_engine.rpc import rpc_call
from sniper_engine.telegram_send_receipt import read_telegram_send_receipt, record_telegram_send_receipt


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


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def today_utc() -> str:
    return now_utc().strftime("%Y-%m-%d")


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
    return int(rpc_call(chain, "eth_blockNumber", []), 16)


def call_uint(chain: str, contract: str, data: str) -> int:
    raw = rpc_call(chain, "eth_call", [{"to": contract, "data": data}, "latest"])
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
            cache[address] = str(rpc_call(chain, "eth_getCode", [address, "latest"]) or "0x")
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
            result = rpc_call(chain, "eth_getLogs", [query])
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
                "16",
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
                result = rpc_call(chain, "eth_getLogs", [query])
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
    return payload


def build_snapshot() -> dict[str, Any]:
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


def retention_alert_events(project: dict[str, Any]) -> list[dict[str, Any]]:
    if not retention_alert_coverage_complete(project):
        return []
    retention = project["retention_flow"]
    return [
        event
        for event in retention.get("events", []) or []
        if isinstance(event, dict)
        and event.get("historical_catchup") is not True
        and event.get("alert_eligible") is not False
        and str(event.get("level") or "").upper() in {"HIGH", "CRITICAL"}
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
    return "|".join(
        [
            str(project.get("chain") or ""),
            str(project.get("address") or ""),
            str(event.get("sample_tx") or event.get("tx") or ""),
            str(
                event.get("sample_log_index")
                or event.get("log_index")
                or 0
            ),
            str(event.get("type") or ""),
        ]
    )


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
) -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        receipt = read_telegram_send_receipt(response)
    seen.update(batch_keys)
    write_json(SEEN_PATH, sorted(seen))
    record_telegram_send_receipt(
        LAST_PUSH_PATH,
        sent_at=now_iso(),
        signature="\n".join(sorted(batch_keys)),
        text=text,
        receipt=receipt,
    )


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
                    f"｜合计 {format_amount(event.get('amount'))} 枚"
                    f"｜{event.get('evidence_level')}"
                ),
                (
                    f"样本 {short_addr(str(event.get('sample_from') or event.get('from') or ''))} → "
                    f"{short_addr(str(event.get('sample_to') or event.get('to') or ''))}｜"
                    f"tx {short_addr(str(event.get('sample_tx') or event.get('tx') or ''))}"
                ),
            ]
        )
    return "\n".join(lines)[:TELEGRAM_LIMIT]


def holder_only_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        **project,
        "retention_flow": {
            "status": "not_required",
            "events": [],
        },
    }


def maybe_send_telegram(snapshot: dict[str, Any]) -> bool:
    if os.environ.get("ALPHA_HOLDER_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return True
    keys = alert_keys(snapshot)
    seen = set(read_json(SEEN_PATH, []))
    force = os.environ.get("ALPHA_HOLDER_FORCE_TELEGRAM") == "1"
    pending = set(keys if force else (key for key in keys if key not in seen))
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
        batch_keys = [
            retention_event_key(project, event)
            for event in events
        ]
        send_telegram_batch(
            retention_telegram_text(project, events),
            batch_keys,
            token=token,
            chat_id=chat_id,
            seen=seen,
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
        )

    if force and not keys:
        send_telegram_batch(
            telegram_text({**snapshot, "projects": []}),
            [],
            token=token,
            chat_id=chat_id,
            seen=seen,
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
            }
            lines.extend(
                [
                    (
                        f"{marker}{project.get('symbol')} {project.get('priority')}"
                        f"｜30天流向｜{effective_level}"
                    ),
                    (
                        f"信号：{event_labels.get(str(event.get('type') or ''), str(event.get('type') or '转移风险'))}"
                        f"｜{int(event.get('transfer_count') or 1)}笔合计 "
                        f"{format_amount(event.get('amount'))} 枚"
                        f"｜证据 {event.get('evidence_level')}"
                    ),
                    (
                        f"样本路径：{short_addr(str(event.get('sample_from') or event.get('from') or ''))}"
                        f" → {short_addr(str(event.get('sample_to') or event.get('to') or ''))}"
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
                    "### 72小时后增量流向",
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
