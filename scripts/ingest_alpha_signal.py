#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sniper_engine.token_aliases import apply_token_aliases, display_alias
SIGNAL_DIR = ROOT / "input" / "signals"
OUT_DIR = ROOT / "output" / "signals"
WATCHLIST_PATH = ROOT / "config" / "current_alpha_watchlist.json"
PREDICTION_PATH = ROOT / "config" / "current_prediction_markets.json"

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
BLOCK_RE = re.compile(r"(?:区块|block)\s*[:： ]\s*(\d{5,})", re.I)
POOL_ID_RE = re.compile(r"(?:PoolId|Pool ID|pool id|池子)\s*[:： ]\s*([0-9A-Za-zx_.-]{4,})", re.I)
TIME_RE = re.compile(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}\s+\d{1,2}[:：]\d{2}|(?<!\d)(?:[01]?\d|2[0-3])[:：]\d{2}(?!\d))")
TOTAL_SUPPLY_RE = re.compile(r"(?:总量|total\s*supply)\D{0,12}([0-9]+(?:\.[0-9]+)?\s*[万亿bmMkK]?)", re.I)
INITIAL_FLOAT_RE = re.compile(r"(?:初始流通|流通量|initial\s*(?:float|circulation|circulating))\D{0,16}([0-9]+(?:\.[0-9]+)?\s*%?|[0-9]+(?:\.[0-9]+)?\s*[万亿bmMkK]?)", re.I)
FINANCING_RE = re.compile(r"(?:融资|funding|raised)\D{0,18}([0-9]+(?:\.[0-9]+)?\s*(?:万|亿|m|M|k|K|美元|usd|USDT)?)", re.I)
ALLOCATION_LINE_RE = re.compile(r"(团队|社区|生态|机构|投资者|投资|金库|流动性|空投|顾问|public|team|community|ecosystem|investor|treasury|liquidity|airdrop|advisor)[^\n]{0,40}?([0-9]+(?:\.[0-9]+)?%)", re.I)

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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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
    text = strip_signal_headers(text)
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
    times = unique(TIME_RE.findall(text))
    primary_symbol = symbols[0] if symbols else ""
    title = guess_title(text, primary_symbol)
    priority = score_priority(addresses, txs, pool_ids, prediction_urls, prices)

    parsed = {
        "generated_at": now_iso(),
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
        "prices": prices,
        "facts": facts,
        "watchlist_proposal": build_watchlist_proposal(primary_symbol, title, addresses, txs, blocks, times, links_by_type, priority),
        "prediction_proposals": build_prediction_proposals(primary_symbol, title, prediction_urls),
        "next_checks": next_checks(addresses, txs, pool_ids, prediction_urls, prices),
    }
    return apply_token_aliases(parsed)


def strip_signal_headers(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    first_lines = lines[:8]
    has_header = any(line.strip().lower().startswith(tuple(HEADER_PREFIXES)) for line in first_lines)
    if not has_header:
        return text
    idx = 0
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
        if match:
            prices[key] = match.group(1).strip()
    return prices


def extract_facts(text: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    match = TOTAL_SUPPLY_RE.search(text)
    if match:
        facts["total_supply"] = match.group(1).strip()
    match = INITIAL_FLOAT_RE.search(text)
    if match:
        facts["initial_float"] = match.group(1).strip()
    match = FINANCING_RE.search(text)
    if match:
        facts["financing"] = match.group(1).strip()
    allocations = []
    for label, percent in ALLOCATION_LINE_RE.findall(text):
        allocations.append({"label": label.strip(), "percent": percent.strip()})
    if allocations:
        facts["allocations"] = unique_dicts(allocations)
    if "币安Alpha" in text or "Binance Alpha" in text or "binance alpha" in text.lower():
        facts.setdefault("venues", []).append("Binance Alpha")
    for venue in ["Gate", "MEXC", "KuCoin", "HTX", "OKX", "Bitget"]:
        if venue.lower() in text.lower():
            facts.setdefault("venues", []).append(venue)
    if facts.get("venues"):
        facts["venues"] = unique(facts["venues"])
    return facts


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
        "required_checks": next_checks(addresses, txs, [], [], {}),
    }


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
) -> str:
    score = 0
    score += 3 if addresses else 0
    score += 3 if txs else 0
    score += 3 if pool_ids else 0
    score += 2 if prediction_urls else 0
    score += 2 if prices else 0
    if score >= 8:
        return "P0_DEEP_REVIEW"
    if score >= 5:
        return "P1_MONITOR"
    if score >= 2:
        return "P2_PAPER_TRADE"
    return "P3_BACKLOG"


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
    watchlist = read_json(WATCHLIST_PATH, {"generated_at": now_iso(), "items": []})
    prediction = read_json(PREDICTION_PATH, {"generated_at": now_iso(), "items": []})

    proposal = parsed.get("watchlist_proposal", {})
    symbol = proposal.get("symbol", "UNKNOWN")
    if symbol and symbol != "UNKNOWN":
        watchlist["items"] = merge_by_symbol(watchlist.get("items", []), proposal)
        watchlist["generated_at"] = now_iso()
        write_json(WATCHLIST_PATH, watchlist)

    prediction_items = prediction.get("items", [])
    for item in parsed.get("prediction_proposals", []):
        prediction_items = merge_prediction(prediction_items, item)
    prediction["items"] = prediction_items
    prediction["generated_at"] = now_iso()
    write_json(PREDICTION_PATH, prediction)


def merge_by_symbol(items: list[dict[str, Any]], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = proposal.get("symbol", "").upper()
    for idx, item in enumerate(items):
        if str(item.get("symbol", "")).upper() == symbol:
            merged = dict(item)
            for key in ["aliases", "contracts", "catalysts", "known_blocks", "known_times", "known_txs", "required_checks"]:
                merged[key] = merge_list(merged.get(key, []), proposal.get(key, []))
            if proposal.get("facts"):
                merged["facts"] = {**merged.get("facts", {}), **proposal.get("facts", {})}
            if priority_rank(str(proposal.get("priority", ""))) > priority_rank(str(merged.get("priority", ""))):
                merged["priority"] = proposal.get("priority")
            for key in ["chain", "name"]:
                if not merged.get(key) or merged.get(key) in {"unknown", "P3_BACKLOG"}:
                    merged[key] = proposal.get(key, merged.get(key))
            items[idx] = merged
            return items
    items.append(proposal)
    return items


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
        if args.registry:
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
