#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label
from sniper_engine.rpc import rpc_call
from sniper_engine.telegram_send_receipt import read_telegram_send_receipt, record_telegram_send_receipt


getcontext().prec = 80

CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_holder_concentration_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
STATE_PATH = OUT_DIR / "state.json"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
SURF_HOLDER_QUOTA_STATE_PATH = OUT_DIR / "surf_holder_quota_state.json"
PRICE_CONTEXT_PATH = ROOT / "output" / "alpha_price_momentum_watch" / "latest.json"
FLOW_CONTEXT_PATH = ROOT / "output" / "alpha_intraday_flow_watch" / "latest.json"

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
            result = rpc_call(chain, "eth_getLogs", [query]) or []
        except Exception as exc:
            errors.append(str(exc))
            continue
        rows.extend(result)
        if len(rows) >= max_logs:
            rows = rows[:max_logs]
            truncated = True
            break
    rows.sort(key=lambda row: (block_number(row), log_index(row)))
    return rows, errors, truncated


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
    max_projects = int(os.environ.get("ALPHA_HOLDER_MAX_PROJECTS", "8"))
    rows: list[dict[str, str]] = []
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
                rows.append({"symbol": symbol, "name": str(item.get("name") or ""), "priority": priority, "chain": chain, "address": address})
                break
        if len(rows) >= max_projects:
            break
    return rows


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


def build_token_snapshot(item: dict[str, str], config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    symbol = item["symbol"]
    chain = item["chain"]
    token = norm(item["address"])
    key = f"{chain}:{token}"
    finality = int(os.environ.get("ALPHA_HOLDER_FINALITY_BLOCKS", "20"))
    lookback = int(os.environ.get("ALPHA_HOLDER_LOOKBACK_BLOCKS", "50000"))
    raw_tip = latest_block(chain)
    tip = max(0, raw_tip - finality)
    token_state = state.setdefault("tokens", {}).setdefault(key, {})
    previous_metrics = token_state.get("last_metrics")
    previous_tip = int(token_state.get("latest_block") or 0)
    if previous_tip and previous_tip < tip:
        from_block = previous_tip + 1
        balances = {addr: int(value) for addr, value in token_state.get("balances_raw", {}).items()}
        basis_from_block = int(token_state.get("basis_from_block") or max(0, tip - lookback))
    else:
        from_block = max(0, tip - lookback)
        balances = {}
        basis_from_block = from_block
    logs, errors, truncated = transfer_logs(chain, token, from_block, tip)
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
    metrics: dict[str, Any] = {
        "raw_top10_pct": str(raw_pct),
        "effective_top10_pct": str(effective_pct),
        "raw_top10_infra_pct": str(infra_pct),
    }
    if previous_metrics:
        metrics.update(
            {
                "raw_top10_delta_pct": str(raw_pct - decimal_from(previous_metrics.get("raw_top10_pct"))),
                "effective_top10_delta_pct": str(effective_pct - decimal_from(previous_metrics.get("effective_top10_pct"))),
                "raw_top10_infra_delta_pct": str(infra_pct - decimal_from(previous_metrics.get("raw_top10_infra_pct"))),
            }
        )
    signal = classify_signal(metrics, previous_metrics)
    negative_count = sum(1 for value in balances.values() if value < 0)
    positive_count = sum(1 for value in balances.values() if value > 0)
    complete = basis_from_block == 0 and not truncated and not errors and negative_count == 0
    payload = {
        **item,
        "raw_latest_block": raw_tip,
        "latest_block": tip,
        "previous_latest_block": previous_tip,
        "basis_from_block": basis_from_block,
        "scan_from_block": from_block,
        "scan_to_block": tip,
        "log_count": len(logs),
        "log_error_count": len(errors),
        "log_errors": errors[:3],
        "truncated": truncated,
        "complete_holder_reconstruction": complete,
        "coverage_note": "complete_from_genesis" if complete else "window_or_incremental_reconstruction",
        "decimals": decimals,
        "total_supply_raw": str(supply_raw),
        "total_supply": str(decimal_amount(supply_raw, decimals)) if supply_raw else "0",
        "supply_source": supply_source,
        "positive_holder_count": positive_count,
        "negative_balance_count": negative_count,
        "metrics": metrics,
        "signal": signal,
        "top10_raw": raw_rows,
        "top10_effective": effective_rows,
        "full_holder_source": full_holder_source_status(chain, token),
    }
    token_state.update(
        {
            "symbol": symbol,
            "chain": chain,
            "address": token,
            "decimals": decimals,
            "basis_from_block": basis_from_block,
            "latest_block": tip,
            "last_metrics": metrics,
            "balances_raw": {addr: str(value) for addr, value in balances.items() if value != 0},
        }
    )
    return payload


def build_snapshot() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, {"items": []})
    state = read_json(STATE_PATH, {"tokens": {}})
    market_context = latest_market_context()
    projects = []
    for item in contract_items(config):
        try:
            project = build_token_snapshot(item, config, state)
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
        "alert_count": sum(1 for item in projects if item.get("signal", {}).get("level") in {"HIGH", "CRITICAL"}),
        "projects": projects,
    }
    write_json(STATE_PATH, state)
    return snapshot


def alert_keys(snapshot: dict[str, Any]) -> list[str]:
    keys = []
    for project in snapshot.get("projects", []):
        signal = project.get("signal", {})
        if signal.get("level") not in {"HIGH", "CRITICAL"}:
            continue
        metrics = project.get("metrics", {})
        bucket = decimal_from(metrics.get("effective_top10_delta_pct")) // Decimal("0.5")
        keys.append("|".join([project.get("symbol", ""), project.get("chain", ""), project.get("address", ""), signal.get("direction", ""), str(bucket)]))
    return sorted(set(keys))


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ALPHA_HOLDER_REPEAT_SUPPRESS_MINUTES", "30"))
    if ttl_minutes <= 0:
        return False
    signature = "\n".join(alert_keys(snapshot))
    last = read_json(LAST_PUSH_PATH, {})
    if last.get("signature") != signature:
        return False
    try:
        sent_at = datetime.fromisoformat(str(last.get("sent_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    return now_utc() - sent_at.astimezone(timezone.utc) < timedelta(minutes=ttl_minutes)


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ALPHA_HOLDER_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    keys = alert_keys(snapshot)
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if key not in seen]
    if not new_keys and os.environ.get("ALPHA_HOLDER_FORCE_TELEGRAM") != "1":
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ALPHA_HOLDER_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
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
    record_telegram_send_receipt(
        LAST_PUSH_PATH,
        sent_at=now_iso(),
        signature="\n".join(keys),
        text=text,
        receipt=receipt,
    )


def telegram_text(snapshot: dict[str, Any]) -> str:
    new_keys = set(snapshot.get("_telegram_new_alert_keys") or [])
    active = sorted(
        (
            item
            for item in snapshot.get("projects", [])
            if item.get("signal", {}).get("level") in {"HIGH", "CRITICAL"}
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
        marker = "🚨" if effective_level == "CRITICAL" else "❗"
        coverage = "全量" if project.get("complete_holder_reconstruction") else "窗口/增量"
        if index:
            lines.append("")
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
    delta = abs(decimal_from(project.get("metrics", {}).get("effective_top10_delta_pct")))
    return (
        -level_rank.get(str(signal.get("level")), 0),
        -level_rank.get(str(decision.get("level")), 0),
        -delta,
        str(project.get("symbol") or ""),
    )


def holder_effective_level(project: dict[str, Any]) -> str:
    ranks = {"INFO": 0, "HIGH": 1, "CRITICAL": 2}
    signal_level = str(project.get("signal", {}).get("level") or "INFO")
    decision_level = str(project_decision_context(project).get("level") or "INFO")
    return max((signal_level, decision_level), key=lambda level: ranks.get(level, 0))


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
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    write_json(LATEST_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    maybe_send_telegram(snapshot)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(f"holder_projects={snapshot['project_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
