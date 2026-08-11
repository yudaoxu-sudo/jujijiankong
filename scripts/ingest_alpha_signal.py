#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sniper_engine.token_aliases import apply_token_aliases, display_alias
from scripts.alpha_prelaunch_research import (
    build_prelaunch_research,
    forecast_context_at,
)
SIGNAL_DIR = ROOT / "input" / "signals"
OUT_DIR = ROOT / "output" / "signals"
WATCHLIST_PATH = ROOT / "config" / "current_alpha_watchlist.json"
PREDICTION_PATH = ROOT / "config" / "current_prediction_markets.json"
APPLY_LOCK_PATH = ROOT / "output" / "locks" / "alpha_signal_apply.lock"
PENDING_MONITORING_ACTIVATION = "pending_manual_onboarding"

EVM_ADDR_RE = re.compile(r"(?<![a-fA-F0-9])0x[a-fA-F0-9]{40}(?![a-fA-F0-9])")
TX_RE = re.compile(r"0x[a-fA-F0-9]{64}")
URL_RE = re.compile(r"https?://[^\s\]\)）>]+")
PANCAKE_POOL_URL_RE = re.compile(r"pancakeswap\.finance/liquidity/pool/([a-z0-9_-]+)/((?:0x)?[a-fA-F0-9]{64})", re.I)
EXPLORER_TX_URL_RE = re.compile(r"(?:bscscan\.com|basescan\.org|etherscan\.io|snowtrace\.io)/tx/(0x[a-fA-F0-9]{64})", re.I)
SYMBOL_RE = re.compile(r"\$([A-Za-z0-9]{1,16})\b")
PAREN_SYMBOL_RE = re.compile(r"[\(（]\s*([A-Z][A-Z0-9]{1,15})\s*[\)）]")
TOKEN_NAME_RE = re.compile(r"token\s*name\s*[:：]\s*([A-Za-z0-9_-]{1,32})", re.I)
SYMBOL_FIELD_RE = re.compile(r"(?:symbol|代币符号)\s*[:：]\s*([A-Za-z0-9]{1,16})", re.I)
PAIR_RE = re.compile(r"\b([A-Z0-9]{1,16})\s*/\s*(USDT|USDC|BNB|ETH)\b")
LAUNCH_SYMBOL_RE = re.compile(
    r"(?:上线|开盘|首发|(?i:listing|listed|tge))\s*"
    r"(?:代币|(?i:token|project))?\s*[:：\-]?\s*\$?([A-Z][A-Z0-9]{1,15})\b",
)
ALPHA_VENUE_RE = re.compile(
    r"(?:币安\s*Alpha|Binance\s*Alpha|BN\s*Alpha)",
    re.I,
)
LAUNCH_CONTEXT_RE = re.compile(
    r"(?:上线|开盘|首发|listing|listed|trading\s+opens?|TGE|新\s*Hook)",
    re.I,
)
BLOCK_RE = re.compile(r"(?:区块|block)\s*[:： ]\s*(\d{5,})", re.I)
POOL_ID_RE = re.compile(r"(?:PoolId|Pool ID|pool id|池子)\s*[:： ]\s*([0-9A-Za-zx_.-]{4,})", re.I)
CHINESE_DATETIME_RE = re.compile(
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})[:：](\d{2})"
)
STANDARD_DATETIME_RE = re.compile(
    r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s+(\d{1,2})[:：](\d{2})"
)
CLOCK_TIME_RE = re.compile(r"(?<!\d)((?:[01]?\d|2[0-3])[:：]\d{2})(?!\d)")
TOTAL_SUPPLY_RE = re.compile(r"(?:总量|total\s*supply)\D{0,12}([0-9]+(?:\.[0-9]+)?\s*[万亿bmMkK]?)", re.I)
INITIAL_FLOAT_RE = re.compile(r"(?:初始流通|流通量|initial\s*(?:float|circulation|circulating))\D{0,16}([0-9]+(?:\.[0-9]+)?\s*%?|[0-9]+(?:\.[0-9]+)?\s*[万亿bmMkK]?)", re.I)
FINANCING_RE = re.compile(r"(?:融资|funding|raised)\D{0,18}([0-9]+(?:\.[0-9]+)?\s*(?:万|亿|m|M|k|K|美元|usd|USDT)?)", re.I)
ALLOCATION_LINE_RE = re.compile(r"(团队|社区|生态|机构|投资者|投资|金库|流动性|空投|顾问|public|team|community|ecosystem|investor|treasury|liquidity|airdrop|advisor)[^\n]{0,40}?([0-9]+(?:\.[0-9]+)?%)", re.I)
SNIPER_AMOUNT_RE = re.compile(
    r"(?:狙击金额|snipe\s*amount|sniper\s*amount)\D{0,12}([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
BRIBE_AMOUNT_RE = re.compile(
    r"(?:贿赂金额|bribe(?:\s*amount)?)\D{0,12}([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
TOKEN_AMOUNT_RE = re.compile(
    r"(?:代币数量|token\s*(?:amount|quantity))\D{0,12}([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
HOLDING_COST_RE = re.compile(
    r"(?:持仓成本|holding\s*cost|cost\s*basis)\D{0,12}([0-9]+(?:\.[0-9]+)?)",
    re.I,
)

PRICE_PATTERNS = {
    "pool_price": re.compile(r"(?:池子价|池子价格|初始价格)\D{0,12}([0-9]+(?:\.[0-9]+)?)", re.I),
    "premarket_price": re.compile(r"(?:盘前价|盘前价格)\D{0,12}([0-9]+(?:\.[0-9]+)?)", re.I),
    "sniper_price": re.compile(r"(?:预估狙击价|预估狙击价格|狙击价格)\D{0,12}([0-9]+(?:\.[0-9]+)?)", re.I),
    "launch_fdv": re.compile(r"(?:预估开盘市值|开盘市值|FDV)\D{0,12}([0-9]+(?:\.[0-9]+)?\s*[万亿mMkKbB]?)", re.I),
}

CHAIN_HINTS = {
    "bsc": ["bsc", "bnb", "bep20", "币安链", "币安智能链"],
    "base": ["base"],
    "eth": ["eth", "ethereum", "erc20", "以太"],
}

HEADER_PREFIXES = {
    "source_chat:",
    "source_forward:",
    "source_name:",
    "source_entity:",
    "source_state_key:",
    "source_evidence_layer:",
    "source_authority:",
    "source_context_only:",
    "telegram_update_id:",
    "telegram_message_id:",
    "telegram_message_link:",
    "date_utc:",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if path.exists():
                os.fchmod(handle.fileno(), path.stat().st_mode & 0o7777)
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def source_files(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(path) for path in paths]
    if not SIGNAL_DIR.exists():
        return []
    return sorted(
        path for path in SIGNAL_DIR.glob("*")
        if path.suffix.lower() in {".txt", ".md"}
    )


def parse_signal(text: str, source_path: Path | None = None) -> dict[str, Any]:
    source_policy = source_policy_from_headers(text)
    text = strip_signal_headers(text)
    generated_at = now_iso()
    urls = unique(URL_RE.findall(text))
    pool_ids = normalize_pool_ids(POOL_ID_RE.findall(text) + extract_pool_ids_from_urls(urls))
    txs = extract_txs(text, urls, pool_ids)
    addresses = extract_addresses(text)
    symbols = extract_symbols(text)
    prices = extract_prices(text)
    facts = extract_facts(text)
    prediction_urls = [
        url for url in urls
        if "polymarket.com" in url.lower() or "predict.fun" in url.lower()
    ]
    links_by_type = classify_links(urls)
    blocks = [int(value) for value in unique(BLOCK_RE.findall(text))]
    pool_links = extract_pool_links(urls)
    primary_symbol = symbols[0] if symbols else ""
    prelaunch_research, event_schedule = build_prelaunch_research(
        text=text,
        symbol=primary_symbol,
        urls=urls,
        addresses=addresses,
        prices=prices,
        facts=facts,
        source_path=source_path,
        observed_at=generated_at,
        source_policy=source_policy,
    )
    alpha_open_times = unique(
        [
            row.get("time_utc8")
            for row in event_schedule
            if row.get("event_type") == "alpha_open"
            and row.get("time_precision") == "exact"
            and row.get("time_utc8")
        ]
    )
    has_typed_schedule = any(
        row.get("time_utc8") or row.get("time_text")
        for row in event_schedule
    )
    times = (
        alpha_open_times
        if has_typed_schedule
        else extract_times(text)
    )
    title = guess_title(text, primary_symbol)
    priority = score_priority(
        addresses,
        txs,
        pool_ids,
        prediction_urls,
        prices,
        facts=facts,
        times=times,
        links_by_type=links_by_type,
    )
    if primary_symbol and ALPHA_VENUE_RE.search(text) and LAUNCH_CONTEXT_RE.search(text):
        facts["alpha_launch_signal"] = True
        priority = promote_priority(priority, "P1_MONITOR")

    watchlist_proposal = build_watchlist_proposal(
        primary_symbol,
        title,
        addresses,
        txs,
        blocks,
        times,
        pool_ids,
        pool_links,
        links_by_type,
        priority,
    )
    watchlist_proposal.update(
        {
            "facts": facts,
            "event_schedule": event_schedule,
            "prelaunch_research": prelaunch_research,
        }
    )
    parsed = {
        "generated_at": generated_at,
        "source_path": str(source_path) if source_path else "",
        "title": title,
        "symbol": primary_symbol,
        "symbols": symbols,
        "priority": priority,
        "urls": urls,
        "links_by_type": links_by_type,
        "prediction_urls": prediction_urls,
        "pool_links": pool_links,
        "addresses": addresses,
        "txs": txs,
        "blocks": blocks,
        "pool_ids": pool_ids,
        "times": times,
        "event_schedule": event_schedule,
        "prices": prices,
        "facts": facts,
        "prelaunch_research": prelaunch_research,
        "watchlist_proposal": watchlist_proposal,
        "prediction_proposals": build_prediction_proposals(primary_symbol, title, prediction_urls),
        "next_checks": next_checks(addresses, txs, pool_ids, prediction_urls, prices),
    }
    if source_policy:
        parsed["source_policy"] = source_policy
    return apply_token_aliases(parsed)


def source_policy_from_headers(text: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    for line in lines[start : start + 16]:
        if not line.strip():
            break
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().lower()
        if normalized_key in {"source_evidence_layer", "source_authority", "source_context_only"} and normalized_key not in fields:
            fields[normalized_key] = value.strip()
    if "source_context_only" not in fields:
        return {}
    context_only = fields["source_context_only"].lower() != "false"
    return {
        "evidence_layer": "social",
        "authority": "context_only" if context_only else "social_discovery",
        "context_only": context_only,
    }


def strip_signal_headers(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    first_lines = lines[start : start + 8]
    has_header = any(line.strip().lower().startswith(tuple(HEADER_PREFIXES)) for line in first_lines)
    if not has_header:
        return text
    idx = start
    while idx < len(lines) and lines[idx].strip().lower().startswith(tuple(HEADER_PREFIXES)):
        idx += 1
    if idx < len(lines) and not lines[idx].strip():
        idx += 1
    body = "\n".join(lines[idx:]).strip()
    return body or text


def extract_symbols(text: str) -> list[str]:
    symbols = [item.upper() for item in SYMBOL_RE.findall(text)]
    for token in PAREN_SYMBOL_RE.findall(text.upper()):
        symbols.append(token.upper())
    for token in TOKEN_NAME_RE.findall(text):
        symbols.append(token.upper())
    for token in SYMBOL_FIELD_RE.findall(text):
        symbols.append(token.upper())
    for left, _ in PAIR_RE.findall(text.upper()):
        symbols.append(left.upper())
    for token in LAUNCH_SYMBOL_RE.findall(text):
        symbols.append(token.upper())
    banned = {"USDT", "USDC", "BNB", "ETH", "USD", "UTC", "LP", "POOL", "TOKEN"}
    return unique([item for item in symbols if item not in banned])


def extract_addresses(text: str) -> list[dict[str, str]]:
    rows = []
    for match in EVM_ADDR_RE.finditer(text):
        addr = match.group(0)
        if len(addr) == 66:
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end].lower()
        window = text[max(0, match.start() - 40): match.end() + 40].lower()
        rows.append(
            {
                "address": addr,
                "chain": infer_chain(line) if infer_chain(line) != "unknown" else infer_chain(window),
                "label_hint": infer_label(line) or infer_label(window),
            }
        )
    dedup: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row["address"].lower()
        if key not in dedup:
            dedup[key] = row
        elif dedup[key].get("chain") == "unknown" and row.get("chain") != "unknown":
            dedup[key] = row
    return list(dedup.values())


def infer_chain(window: str) -> str:
    for chain, hints in CHAIN_HINTS.items():
        if any(hint in window for hint in hints):
            return chain
    return "unknown"


def infer_label(window: str) -> str:
    if any(word in window for word in ["hook", "operator", "poolmanager", "pool manager"]):
        return "pool_hook_or_operator"
    if any(word in window for word in ["usdt", "usdc"]):
        return "quote_token"
    if any(word in window for word in ["tx", "交易"]):
        return "tx_related"
    if any(word in window for word in ["合约", "contract", "token"]):
        return "token_contract"
    if re.search(r"\b(?:bsc|base|eth|ethereum)\s*[:：]", window):
        return "token_contract"
    return ""


def extract_prices(text: str) -> dict[str, str]:
    prices = {}
    for key, pattern in PRICE_PATTERNS.items():
        match = pattern.search(text)
        if match and not match_is_forecast(text, match):
            prices[key] = match.group(1).strip()
    return prices


def extract_facts(text: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    match = TOTAL_SUPPLY_RE.search(text)
    if match and not match_is_forecast(text, match):
        facts["total_supply"] = match.group(1).strip()
    match = INITIAL_FLOAT_RE.search(text)
    if match and not match_is_forecast(text, match):
        facts["initial_float"] = match.group(1).strip()
    match = FINANCING_RE.search(text)
    if match and not match_is_forecast(text, match):
        facts["financing"] = match.group(1).strip()
    allocations = []
    for allocation_match in ALLOCATION_LINE_RE.finditer(text):
        if match_is_forecast(text, allocation_match):
            continue
        label, percent = allocation_match.groups()
        allocations.append(
            {"label": label.strip(), "percent": percent.strip()}
        )
    if allocations:
        facts["allocations"] = unique_dicts(allocations)
    for key, pattern in (
        ("sniper_amount_quote", SNIPER_AMOUNT_RE),
        ("bribe_amount_quote", BRIBE_AMOUNT_RE),
        ("token_amount", TOKEN_AMOUNT_RE),
        ("holding_cost", HOLDING_COST_RE),
    ):
        match = pattern.search(text)
        if match and not match_is_forecast(text, match):
            facts[key] = match.group(1).replace(",", "")
    if ALPHA_VENUE_RE.search(text):
        facts.setdefault("venues", []).append("Binance Alpha")
    for venue in ["Gate", "MEXC", "KuCoin", "HTX", "OKX", "Bitget"]:
        if venue.lower() in text.lower():
            facts.setdefault("venues", []).append(venue)
    if facts.get("venues"):
        facts["venues"] = unique(facts["venues"])
    return facts


def match_is_forecast(text: str, match: re.Match[str]) -> bool:
    return forecast_context_at(text, match.start())


def extract_times(text: str) -> list[str]:
    full: list[str] = []
    for pattern in (CHINESE_DATETIME_RE, STANDARD_DATETIME_RE):
        for match in pattern.finditer(text):
            if match_is_forecast(text, match):
                continue
            year, month, day, hour, minute = match.groups()
            full.append(
                f"{int(year):04d}-{int(month):02d}-{int(day):02d} "
                f"{int(hour):02d}:{int(minute):02d}"
            )
    if full:
        return unique(full)
    return unique(
        match.group(1).replace("：", ":")
        for match in CLOCK_TIME_RE.finditer(text)
        if not match_is_forecast(text, match)
    )


def classify_links(urls: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {
        "x": [],
        "polymarket": [],
        "predict": [],
        "binance": [],
        "explorer": [],
        "dex": [],
        "official_or_other": [],
    }
    for url in urls:
        low = url.lower()
        if "x.com" in low or "twitter.com" in low:
            out["x"].append(url)
        elif "polymarket.com" in low:
            out["polymarket"].append(url)
        elif "predict.fun" in low:
            out["predict"].append(url)
        elif "binance.com" in low:
            out["binance"].append(url)
        elif any(domain in low for domain in ["bscscan.com", "basescan.org", "etherscan.io", "snowtrace.io"]):
            out["explorer"].append(url)
        elif "pancakeswap.finance/liquidity/pool" in low:
            out["dex"].append(url)
        else:
            out["official_or_other"].append(url)
    return {key: value for key, value in out.items() if value}


def extract_pool_links(urls: list[str]) -> list[dict[str, str]]:
    rows = []
    for url in urls:
        match = PANCAKE_POOL_URL_RE.search(url)
        if not match:
            continue
        chain, pool_id = match.groups()
        rows.append({"dex": "pancakeswap", "chain": normalize_chain(chain), "pool_id": "0x" + pool_id.removeprefix("0x"), "url": url})
    return rows


def normalize_pool_ids(values: list[str]) -> list[str]:
    out = []
    for value in values:
        item = value.strip().rstrip(".,，。")
        if re.fullmatch(r"0x[a-fA-F0-9]{64}", item):
            out.append(item)
    return unique(out)


def extract_pool_ids_from_urls(urls: list[str]) -> list[str]:
    return [row["pool_id"] for row in extract_pool_links(urls)]


def extract_txs(text: str, urls: list[str], pool_ids: list[str]) -> list[str]:
    tx_from_urls = [match.group(1) for url in urls for match in [EXPLORER_TX_URL_RE.search(url)] if match]
    pool_id_set = {value.lower() for value in pool_ids}
    txs = []
    tx_url_set = {value.lower() for value in tx_from_urls}
    for match in TX_RE.finditer(text):
        tx = match.group(0)
        if tx.lower() in pool_id_set and tx.lower() not in {item.lower() for item in tx_from_urls}:
            continue
        if tx.lower() not in tx_url_set and not is_tx_context(text, match.start(), match.end()):
            continue
        txs.append(tx)
    return unique(tx_from_urls + txs)


def is_tx_context(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end].lower()
    return any(marker in line for marker in ["tx", "txn", "transaction", "交易", "hash", "哈希"])


def normalize_chain(value: str) -> str:
    value = value.lower()
    if value in {"bsc", "bnb", "binance-smart-chain"}:
        return "bsc"
    return value


def build_watchlist_proposal(
    symbol: str,
    title: str,
    addresses: list[dict[str, str]],
    txs: list[str],
    blocks: list[int],
    times: list[str],
    pool_ids: list[str],
    pool_links: list[dict[str, str]],
    links_by_type: dict[str, list[str]],
    priority: str,
) -> dict[str, Any]:
    contracts = [
        {
            "chain": row["chain"],
            "address": row["address"],
            "confidence": f"signal_ingest_{row.get('label_hint') or 'address'}",
        }
        for row in addresses
        if row.get("label_hint") == "token_contract"
    ]
    pool_candidates = build_pool_candidates(pool_ids, pool_links, times, best_chain(addresses))
    return {
        "symbol": symbol or "UNKNOWN",
        "name": title or symbol or "unknown",
        "priority": priority,
        "chain": best_chain(addresses),
        "contracts": contracts,
        "catalysts": catalyst_hints(links_by_type),
        "known_blocks": [{"chain": best_chain(addresses), "block": block, "reason": "signal_ingest"} for block in blocks],
        "known_times": [{"time": value, "reason": "signal_ingest"} for value in times],
        "known_txs": [{"chain": best_chain(addresses), "tx": tx, "reason": "signal_ingest"} for tx in txs],
        "pool_ids": pool_candidates,
        "required_checks": next_checks(addresses, txs, pool_candidates, [], {}),
    }


def build_pool_candidates(
    pool_ids: list[str],
    pool_links: list[dict[str, str]],
    times: list[str],
    fallback_chain: str,
) -> list[dict[str, str]]:
    links_by_id = {
        str(row.get("pool_id") or "").lower(): row
        for row in pool_links
        if isinstance(row, dict) and row.get("pool_id")
    }
    identifiers = list(pool_ids)
    if not identifiers and times:
        identifiers = [""] if len(times) == 1 else []
    map_times = len(times) == len(identifiers) or (
        len(times) == 1 and len(identifiers) == 1
    )
    candidates: list[dict[str, str]] = []
    for index, pool_id in enumerate(identifiers):
        link = links_by_id.get(str(pool_id).lower(), {})
        chain = str(link.get("chain") or fallback_chain or "unknown").lower()
        row = {
            "chain": chain,
            "pool_id": pool_id,
            "source": "signal_ingest",
        }
        if map_times:
            row["start_time_utc8"] = times[index]
        if chain == "bsc":
            row["quote_address"] = "0x55d398326f99059ff775485246999027b3197955"
        candidates.append(row)
    return unique_dicts(candidates)


def build_prediction_proposals(symbol: str, title: str, urls: list[str]) -> list[dict[str, Any]]:
    proposals = []
    for url in urls:
        source = "polymarket" if "polymarket.com" in url.lower() else "predict_fun"
        proposals.append(
            {
                "symbol": symbol or "UNKNOWN",
                "project": title or symbol or "unknown",
                "source": source,
                "source_type": "polymarket_event_slug" if source == "polymarket" else "manual",
                "url": url,
                "slug": slug_from_url(url) if source == "polymarket" else "",
                "total_supply": "",
                "float_supply": "",
                "targets": [],
                "notes": "generated_by_signal_ingest; fill total_supply and targets before relying on implied price",
            }
        )
    return proposals


def score_priority(
    addresses: list[dict[str, str]],
    txs: list[str],
    pool_ids: list[str],
    prediction_urls: list[str],
    prices: dict[str, str],
    *,
    facts: dict[str, Any] | None = None,
    times: list[str] | None = None,
    links_by_type: dict[str, list[str]] | None = None,
) -> str:
    score = 0
    score += 3 if addresses else 0
    score += 3 if txs else 0
    score += 3 if pool_ids else 0
    score += 2 if prediction_urls else 0
    score += 2 if prices else 0
    facts = facts or {}
    score += 3 if numeric_fact(facts.get("sniper_amount_quote")) >= 50000 else 0
    score += 3 if numeric_fact(facts.get("bribe_amount_quote")) >= 10000 else 0
    score += 1 if facts.get("token_amount") else 0
    score += 1 if facts.get("holding_cost") else 0
    score += 2 if times and "Binance Alpha" in facts.get("venues", []) else 0
    score += 1 if (links_by_type or {}).get("x") else 0
    if score >= 8:
        return "P0_DEEP_REVIEW"
    if score >= 5:
        return "P1_MONITOR"
    if score >= 2:
        return "P2_PAPER_TRADE"
    return "P3_BACKLOG"


def promote_priority(current: str, target: str) -> str:
    ranks = {
        "P0_DEEP_REVIEW": 0,
        "P1_MONITOR": 1,
        "P2_PAPER_TRADE": 2,
        "P3_BACKLOG": 3,
    }
    return current if ranks.get(current, 99) <= ranks.get(target, 99) else target


def numeric_fact(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def next_checks(
    addresses: list[dict[str, str]],
    txs: list[str],
    pool_ids: list[str] | list[Any],
    prediction_urls: list[str],
    prices: dict[str, str],
) -> list[str]:
    checks = []
    if addresses:
        checks.extend(["official_contract", "holder_distribution", "address_labeling"])
    if txs:
        checks.extend(["tx_receipt", "block_transaction_order", "internal_transactions"])
    if pool_ids or prices.get("pool_price"):
        checks.extend(["lp_position", "pool_price_range", "buy_depth_simulation"])
    if prediction_urls:
        checks.extend(["prediction_market_probability", "implied_fdv_comparison"])
    if prices:
        checks.append("price_anchor_comparison")
    if not checks:
        checks.append("source_confirmation")
    return unique(checks)


def catalyst_hints(links_by_type: dict[str, list[str]]) -> list[str]:
    hints = []
    if links_by_type.get("binance"):
        hints.append("Binance/Alpha announcement")
    if links_by_type.get("polymarket") or links_by_type.get("predict"):
        hints.append("prediction market price anchor")
    if links_by_type.get("x"):
        hints.append("X/KOL signal")
    if links_by_type.get("explorer"):
        hints.append("explorer evidence")
    if links_by_type.get("dex"):
        hints.append("DEX pool evidence")
    return hints or ["manual signal"]


def best_chain(addresses: list[dict[str, str]]) -> str:
    for row in addresses:
        if row.get("chain") != "unknown":
            return row["chain"]
    return "unknown"


def guess_title(text: str, symbol: str) -> str:
    for line in text.splitlines():
        clean = line.strip().strip("#：: ")
        if clean and len(clean) <= 80:
            return clean
    return symbol


def slug_from_url(url: str) -> str:
    parts = [part for part in re.split(r"/+", url.split("?")[0]) if part and not part.startswith("http")]
    if not parts:
        return ""
    if "event" in parts:
        idx = parts.index("event")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    if "market" in parts:
        idx = parts.index("market")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    return parts[-1]


def unique(values: list[Any]) -> list[Any]:
    seen = set()
    out = []
    for value in values:
        key = str(value).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def apply_proposals(parsed: dict[str, Any]) -> None:
    source_policy = parsed.get("source_policy", {})
    if isinstance(source_policy, dict) and source_policy.get("context_only") is True:
        return
    APPLY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APPLY_LOCK_PATH.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            watchlist = read_json(
                WATCHLIST_PATH,
                {"generated_at": now_iso(), "items": []},
            )
            prediction = read_json(
                PREDICTION_PATH,
                {"generated_at": now_iso(), "items": []},
            )

            proposal = parsed.get("watchlist_proposal", {})
            symbol = proposal.get("symbol", "UNKNOWN")
            if symbol and symbol != "UNKNOWN":
                merge_proposal = proposal
                monitoring_policy = watchlist.get("monitoring_policy")
                if (
                    isinstance(monitoring_policy, dict)
                    and monitoring_policy.get("mode") == "exclusive_symbols"
                ):
                    merge_proposal = copy.deepcopy(proposal)
                    merge_proposal["active_monitoring"] = False
                    merge_proposal["monitoring_activation"] = (
                        PENDING_MONITORING_ACTIVATION
                    )
                watchlist["items"] = merge_by_symbol(
                    watchlist.get("items", []),
                    merge_proposal,
                )
                watchlist["generated_at"] = now_iso()
                write_json(WATCHLIST_PATH, watchlist)

            prediction_items = prediction.get("items", [])
            for item in parsed.get("prediction_proposals", []):
                prediction_items = merge_prediction(prediction_items, item)
            prediction["items"] = prediction_items
            prediction["generated_at"] = now_iso()
            write_json(PREDICTION_PATH, prediction)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def evidence_rank(status: Any, authority: Any = "") -> int:
    normalized_status = str(status or "").strip().lower()
    normalized_authority = str(authority or "").strip().lower()
    if normalized_status == "verified" or normalized_authority in {
        "official",
        "onchain",
        "receipt_verified",
    }:
        return 3
    if normalized_status in {"conflicted", "stale"}:
        return 0
    return 1


def merge_event_schedule(
    existing: list[Any],
    candidate: list[Any],
) -> list[Any]:
    merged = [copy.deepcopy(row) for row in existing]
    positions: dict[tuple[str, str, str], int] = {}
    for index, row in enumerate(merged):
        if not isinstance(row, dict):
            continue
        positions[
            (
                str(row.get("event_type") or "").lower(),
                str(row.get("time_utc8") or row.get("time_text") or ""),
                str(row.get("venue") or "").lower(),
            )
        ] = index
    for row in candidate:
        if not isinstance(row, dict):
            if row not in merged:
                merged.append(copy.deepcopy(row))
            continue
        key = (
            str(row.get("event_type") or "").lower(),
            str(row.get("time_utc8") or row.get("time_text") or ""),
            str(row.get("venue") or "").lower(),
        )
        if key not in positions:
            positions[key] = len(merged)
            merged.append(copy.deepcopy(row))
            continue
        position = positions[key]
        current = merged[position]
        if not isinstance(current, dict):
            merged[position] = copy.deepcopy(row)
            continue
        current_rank = evidence_rank(
            current.get("verification_status"),
            current.get("authority"),
        )
        candidate_rank = evidence_rank(
            row.get("verification_status"),
            row.get("authority"),
        )
        if candidate_rank > current_rank:
            upgraded = {**current, **copy.deepcopy(row)}
        else:
            upgraded = copy.deepcopy(current)
            for field, value in row.items():
                if upgraded.get(field) in (None, "", [], {}):
                    upgraded[field] = copy.deepcopy(value)
        upgraded["evidence_ids"] = merge_list(
            list(current.get("evidence_ids") or []),
            list(row.get("evidence_ids") or []),
        )
        merged[position] = upgraded
    return merged


def merge_signal_facts(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    current = copy.deepcopy(existing or {})
    incoming = copy.deepcopy(candidate or {})
    current_rank = evidence_rank(current.get("verification_status"))
    incoming_rank = evidence_rank(incoming.get("verification_status"))
    if current_rank > incoming_rank:
        return current
    conflicts = list(current.get("_signal_conflicts") or [])
    for key, value in incoming.items():
        if key in {"verification_status", "_signal_conflicts"}:
            continue
        if key not in current or current.get(key) in (None, "", [], {}):
            current[key] = value
            continue
        if current[key] == value:
            continue
        if incoming_rank > current_rank:
            current[key] = value
            continue
        if isinstance(current[key], list) and isinstance(value, list):
            current[key] = merge_list(current[key], value)
            continue
        conflict = {
            "field": key,
            "existing_value": current[key],
            "candidate_value": value,
            "existing_status": (
                current.get("verification_status") or "unverified"
            ),
            "candidate_status": (
                incoming.get("verification_status") or "unverified"
            ),
        }
        if conflict not in conflicts:
            conflicts.append(conflict)
    if conflicts:
        current["_signal_conflicts"] = conflicts
    if incoming_rank > current_rank:
        current["verification_status"] = (
            incoming.get("verification_status") or "unverified"
        )
    return current


def merge_by_symbol(items: list[dict[str, Any]], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    identities = watchlist_contract_identities(proposal)
    if identities:
        matches = [
            idx
            for idx, item in enumerate(items)
            if identities & watchlist_contract_identities(item)
        ]
    else:
        symbols = watchlist_symbol_aliases(proposal)
        matches = [
            idx
            for idx, item in enumerate(items)
            if symbols & watchlist_symbol_aliases(item)
        ]
    if (
        len(matches) != 1
        or (
            not identities
            and len(watchlist_contract_identities(items[matches[0]])) > 1
        )
    ):
        items.append(proposal)
        return items

    idx = matches[0]
    item = items[idx]
    merged = dict(item)
    for key in [
        "aliases",
        "contracts",
        "catalysts",
        "known_blocks",
        "known_times",
        "known_txs",
        "pool_ids",
        "required_checks",
    ]:
        incoming = list(proposal.get(key) or [])
        if (
            key == "aliases"
            and proposal.get("symbol")
            and str(proposal.get("symbol")).upper()
            != str(item.get("symbol") or "").upper()
        ):
            incoming.append(str(proposal["symbol"]).upper())
        if key == "contracts":
            merged[key] = merge_contract_rows(
                list(merged.get(key) or []),
                incoming,
            )
        else:
            merged[key] = merge_list(merged.get(key, []), incoming)
    merged["event_schedule"] = merge_event_schedule(
        merged.get("event_schedule", []),
        proposal.get("event_schedule", []),
    )
    if proposal.get("facts"):
        merged["facts"] = merge_signal_facts(
            merged.get("facts", {}),
            proposal.get("facts", {}),
        )
    if proposal.get("prelaunch_research"):
        from scripts.binance_alpha_catalog_watch import (
            merge_prelaunch_research,
        )

        merged["prelaunch_research"] = (
            merge_prelaunch_research(
                merged.get("prelaunch_research", {}),
                proposal["prelaunch_research"],
            )
        )
    if priority_rank(str(proposal.get("priority", ""))) > priority_rank(str(merged.get("priority", ""))):
        merged["priority"] = proposal.get("priority")
    for key in ["chain", "name"]:
        if not merged.get(key) or merged.get(key) in {"unknown", "P3_BACKLOG"}:
            merged[key] = proposal.get(key, merged.get(key))
    items[idx] = merged
    return items


def watchlist_contract_identities(
    payload: dict[str, Any],
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for row in payload.get("contracts") or []:
        if not isinstance(row, dict):
            continue
        identity = watchlist_contract_identity(row)
        if identity is not None:
            identities.add(identity)
    return identities


def watchlist_contract_identity(
    row: dict[str, Any],
) -> tuple[str, str] | None:
    chain = normalize_chain(str(row.get("chain") or "").strip())
    address = str(row.get("address") or "").strip().lower()
    return (chain, address) if chain and address else None


def merge_contract_rows(
    existing: list[Any],
    incoming: list[Any],
) -> list[Any]:
    merged: list[Any] = []
    positions: dict[tuple[str, str], int] = {}
    for row in [*existing, *incoming]:
        identity = (
            watchlist_contract_identity(row)
            if isinstance(row, dict)
            else None
        )
        if identity is None:
            if not any(
                str(current).lower() == str(row).lower()
                for current in merged
            ):
                merged.append(copy.deepcopy(row))
            continue
        position = positions.get(identity)
        if position is None:
            positions[identity] = len(merged)
            merged.append(copy.deepcopy(row))
            continue
        current = merged[position]
        for field, value in row.items():
            if field in {"chain", "address"}:
                continue
            if (
                current.get(field) in (None, "", [], {})
                and value not in (None, "", [], {})
            ):
                current[field] = copy.deepcopy(value)
    return merged


def watchlist_symbol_aliases(payload: dict[str, Any]) -> set[str]:
    values = [payload.get("symbol"), *(payload.get("aliases") or [])]
    return {
        str(value).strip().upper()
        for value in values
        if str(value or "").strip()
        and str(value).strip().upper() != "UNKNOWN"
    }


def merge_prediction(items: list[dict[str, Any]], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    key = proposal.get("url", "")
    if not key:
        return items
    for item in items:
        if item.get("url") == key:
            return items
    items.append(proposal)
    return items


def priority_rank(priority: str) -> int:
    return {
        "P0_DEEP_REVIEW": 4,
        "P1_MONITOR": 3,
        "P2_PAPER_TRADE": 2,
        "P3_BACKLOG": 1,
        "P4_CONTEXT": 0,
        "": 0,
    }.get(priority, 0)


def merge_list(left: list[Any], right: list[Any]) -> list[Any]:
    return unique(left + right)


def render_markdown(parsed: dict[str, Any]) -> str:
    registry = parsed.get("project_registry") or {}
    lines = [
        "# Alpha Signal Ingest",
        "",
        f"- generated_at: `{parsed['generated_at']}`",
        f"- source_path: `{parsed.get('source_path', '')}`",
        f"- title: {parsed.get('title', '')}",
        f"- symbol: `{parsed.get('symbol') or 'UNKNOWN'}`",
        f"- display_symbol: `{display_alias(parsed) or parsed.get('symbol') or 'UNKNOWN'}`",
        f"- priority: `{parsed.get('priority')}`",
        f"- project_registry: `{registry.get('status', 'not_updated')}`",
    "",
        "## Extracted",
        "",
        f"- addresses: `{len(parsed.get('addresses', []))}`",
        f"- txs: `{len(parsed.get('txs', []))}`",
        f"- blocks: `{len(parsed.get('blocks', []))}`",
        f"- pool_ids: `{len(parsed.get('pool_ids', []))}`",
        f"- prediction_urls: `{len(parsed.get('prediction_urls', []))}`",
        f"- prices: `{json.dumps(parsed.get('prices', {}), ensure_ascii=False)}`",
        "",
        "## Next Checks",
        "",
    ]
    for check in parsed.get("next_checks", []):
        lines.append(f"- {check}")
    lines.extend(["", "## Watchlist Proposal", "", "```json", json.dumps(parsed.get("watchlist_proposal", {}), indent=2, ensure_ascii=False), "```", ""])
    lines.extend(["## Prediction Proposals", "", "```json", json.dumps(parsed.get("prediction_proposals", []), indent=2, ensure_ascii=False), "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Alpha/sniper signal fields from forwarded text files.")
    parser.add_argument("paths", nargs="*", help="Signal text/markdown files. Defaults to input/signals/*.txt|*.md")
    parser.add_argument("--apply", action="store_true", help="Merge extracted proposals into current configs.")
    parser.add_argument("--registry", action="store_true", help="Merge extracted signal fields into the project-level dedupe registry.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = source_files(args.paths)
    if not files:
        print("No signal files found.")
        return 0

    index = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        parsed = parse_signal(text, path)
        parsed.setdefault(
            "source_policy",
            {
                "evidence_layer": "manual",
                "authority": "manual_discovery",
                "context_only": False,
            },
        )
        if args.registry:
            if parsed.get("source_policy", {}).get("context_only") is True:
                parsed["project_registry"] = {"status": "context_only_archived", "added": []}
            else:
                from sniper_engine.project_registry import merge_signal
                parsed["project_registry"] = merge_signal(parsed, {"collector": "manual_ingest", "source_path": str(path)})
        stem = path.stem.replace(" ", "_")
        json_path = OUT_DIR / f"{stem}.json"
        md_path = OUT_DIR / f"{stem}.md"
        write_json(json_path, parsed)
        md_path.write_text(render_markdown(parsed), encoding="utf-8")
        if args.apply:
            apply_proposals(parsed)
        index.append({"source": str(path), "json": str(json_path), "markdown": str(md_path), "symbol": parsed.get("symbol"), "priority": parsed.get("priority")})

    write_json(OUT_DIR / "index.json", {"generated_at": now_iso(), "applied": args.apply, "registry": args.registry, "items": index})
    print(OUT_DIR / "index.json")
    for item in index:
        print(item["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
