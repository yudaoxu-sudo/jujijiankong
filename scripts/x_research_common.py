from __future__ import annotations

import csv
import html
import json
import re
from collections import OrderedDict
from pathlib import Path


RAW_FIELDS = [
    "id",
    "tweet_url",
    "published_at",
    "tweet_text",
    "author",
    "media_files",
    "media_urls",
    "author_media_files",
    "author_media_urls",
    "embedded_or_quote_media_files",
    "embedded_or_quote_media_urls",
    "ocr_text",
    "author_ocr_text",
    "embedded_or_quote_ocr_text",
    "topic_tags",
    "relevance_level",
    "is_sniping_related",
    "is_alpha_related",
    "is_onchain_method",
    "chain",
    "project_or_token",
    "contract_addresses",
    "tx_hashes",
    "block_numbers",
    "wallet_addresses",
    "lp_token_id",
    "dex_or_platform",
    "mentioned_tools",
    "has_image",
    "has_video",
    "has_onchain_evidence",
    "why_keep",
    "needs_manual_review",
    "raw_notes",
]


MONTHS = {
    "January": "01",
    "February": "02",
    "March": "03",
    "April": "04",
    "May": "05",
    "June": "06",
    "July": "07",
    "August": "08",
    "September": "09",
    "October": "10",
    "November": "11",
    "December": "12",
}


STOP_TICKERS = {
    "USD",
    "USDT",
    "USDC",
    "BUSD",
    "BNB",
    "ETH",
    "BTC",
    "FDV",
    "TVL",
    "ATH",
    "ROI",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pipe_join(items: list[str]) -> str:
    seen: list[str] = []
    for item in items:
        item = (item or "").strip()
        if item and item not in seen:
            seen.append(item)
    return "|".join(seen)


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</p>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_oembed_html(raw_html: str) -> tuple[str, str, list[str]]:
    paragraph = ""
    match = re.search(r"<p[^>]*>(.*?)</p>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        paragraph = strip_tags(match.group(1))

    date_iso = ""
    date_match = re.search(r">([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})</a>", raw_html)
    if date_match:
        month_name, day, year = date_match.groups()
        month = MONTHS.get(month_name)
        if month:
            date_iso = f"{year}-{month}-{int(day):02d}T00:00:00.000Z"

    links = []
    for href in re.findall(r'href="([^"]+)"', raw_html):
        decoded = html.unescape(href)
        if "t.co/" in decoded or "x.com/" in decoded or "twitter.com/" in decoded:
            links.append(decoded)
    return paragraph, date_iso, links


def extract_chain_fields(text: str) -> dict[str, str]:
    addresses = re.findall(r"0x[a-fA-F0-9]{40}", text)
    tx_hashes = re.findall(r"0x[a-fA-F0-9]{64}", text)
    address_set = [addr for addr in addresses if addr not in tx_hashes]
    lp_ids = []
    for pattern in (
        r"(?:Position ID|Token ID|LP #|#)\s*([0-9]{5,10})",
        r"\b(?:position|lp)\s*id\s*[:#]?\s*([0-9]{5,10})",
    ):
        lp_ids.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    blocks = re.findall(r"\b(?:block|区块)\s*[:#]?\s*([0-9]{7,10})\b", text, flags=re.IGNORECASE)

    chains = []
    for label, pattern in (
        ("BSC", r"\bBSC\b|\bbsc\b|BNB Smart Chain|bscscan|four\.meme"),
        ("Base", r"\bBase\b|\bbase\b|basescan|Aerodrome|Aero Ignition"),
        ("Ethereum", r"\bETH\b|\beth\b|Ethereum|etherscan"),
        ("Solana", r"\bSOL\b|\bsol\b|Solana"),
        ("Arbitrum", r"\bARB\b|\barb\b|Arbitrum"),
        ("Hyperliquid", r"Hyperliquid|\bHL\b"),
    ):
        if re.search(pattern, text):
            chains.append(label)

    platforms = []
    for label, pattern in (
        ("PancakeSwap", r"PancakeSwap"),
        ("Aerodrome", r"Aerodrome|Aero Ignition"),
        ("BscScan", r"bscscan"),
        ("BaseScan", r"basescan"),
        ("GMGN", r"\bgmgn\b|GMGN"),
        ("DEXTools", r"dextools"),
        ("DEXScreener", r"dexscreener"),
        ("Four.Meme", r"four\.meme|Four\.Meme|四妹"),
        ("OKX", r"\bokx\b|OKX"),
        ("Binance", r"Binance|BN|bn alpha|币安"),
        ("Coinbase", r"Coinbase|coinbase"),
        ("Kraken", r"Kraken|kraken"),
    ):
        if re.search(pattern, text):
            platforms.append(label)

    return {
        "chain": pipe_join(chains),
        "contract_addresses": pipe_join(address_set),
        "tx_hashes": pipe_join(tx_hashes),
        "block_numbers": pipe_join(blocks),
        "wallet_addresses": pipe_join(address_set),
        "lp_token_id": pipe_join(lp_ids),
        "dex_or_platform": pipe_join(platforms),
    }


def label_row(text: str) -> dict[str, str]:
    tags = []
    if re.search(r"狙击|打新|开盘|抢筹|前排|冲新币|战壕|snip|trenches", text, re.IGNORECASE):
        tags.append("sniping")
    if re.search(r"池子|加池|流动性|价格区间|V3|LP|PancakeSwap|Aerodrome|四妹|four\\.meme", text, re.IGNORECASE):
        tags.append("liquidity")
    if re.search(r"贿赂|bundle|BlockRazor|txIndex|内部交易|MEV", text, re.IGNORECASE):
        tags.append("bribe_bundle")
    if re.search(r"跨链|bridge|wormhole|hyperlane", text, re.IGNORECASE):
        tags.append("bridge")
    if re.search(r"筹码|流通|锁仓|解锁|融资|FDV|TGE|tokenomics|分配|VC|机构|空投", text, re.IGNORECASE):
        tags.append("tokenomics")
    if re.search(r"地址|合约|监控|授权|大额|tx|bscscan|basescan|contract|聪明钱|链上", text, re.IGNORECASE):
        tags.append("address_monitoring")
    if re.search(r"alpha|BN Alpha|Binance|OKX|coinbase|kraken|上所|上币|boost|list", text, re.IGNORECASE):
        tags.append("alpha")
    if re.search(r"庄|抓庄|控盘|成本|拉盘|砸盘|老鼠仓|聪明钱", text, re.IGNORECASE):
        tags.append("market_maker")

    return {
        "topic_tags": pipe_join(tags),
        "relevance_level": "medium" if tags else "uncertain",
        "is_sniping_related": "yes" if "sniping" in tags else "no",
        "is_alpha_related": "yes" if "alpha" in tags else "no",
        "is_onchain_method": "yes" if {"liquidity", "bribe_bundle", "address_monitoring", "market_maker"} & set(tags) else "no",
    }


def extract_symbols(text: str, project_or_token: str = "") -> str:
    candidates: OrderedDict[str, None] = OrderedDict()
    source = "\n".join([text or "", project_or_token or ""])
    for match in re.finditer(r"\$([A-Za-z][A-Za-z0-9_]{0,15})\b", source):
        symbol = match.group(1).upper()
        if symbol not in STOP_TICKERS:
            candidates[f"${symbol}"] = None
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_. -]{1,40})\(([A-Z0-9]{1,10})\)", source):
        name = norm_space(match.group(1))
        ticker = match.group(2).upper()
        if ticker in STOP_TICKERS or ticker.isdigit():
            continue
        if len(name) > 2:
            candidates[f"{name}({ticker})"] = None
    project_or_token = norm_space(project_or_token)
    if project_or_token and not re.fullmatch(r"\$?\d+(?:\.\d+)?[KMB]?", project_or_token, re.IGNORECASE):
        candidates[project_or_token] = None
    return "|".join(candidates.keys())


def ensure_raw_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "candidates").mkdir(parents=True, exist_ok=True)
    if not (data_dir / "raw_tweets.csv").exists():
        write_csv(data_dir / "raw_tweets.csv", [], RAW_FIELDS)
        (data_dir / "raw_tweets.json").write_text("[]\n", encoding="utf-8")


def json_dump_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
