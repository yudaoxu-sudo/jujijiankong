#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "output" / "aliideez_x_research"
CANDIDATE_PATH = DATA_DIR / "candidates" / "manual_candidate_ids.csv"
RAW_CSV = DATA_DIR / "raw_tweets.csv"
RAW_JSON = DATA_DIR / "raw_tweets.json"
OEMBED_RAW = DATA_DIR / "candidates" / "oembed_raw.jsonl"
OEMBED_AUDIT = DATA_DIR / "candidates" / "oembed_audit.csv"


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fetch_oembed(tweet_id: str) -> tuple[dict[str, object] | None, str]:
    target = f"https://x.com/aLiiDeez/status/{tweet_id}"
    params = urllib.parse.urlencode({"url": target, "omit_script": "true"})
    url = f"https://publish.twitter.com/oembed?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as exc:
        return None, str(exc)


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
        if "t.co/" in decoded or "x.com/" in decoded:
            links.append(decoded)
    return paragraph, date_iso, links


def pipe_join(items: list[str]) -> str:
    seen = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return "|".join(seen)


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
        ("BSC", r"\bBSC\b|\bbsc\b|BNB Smart Chain|bscscan"),
        ("Base", r"\bBase\b|\bbase\b|basescan|Aerodrome|Aero Ignition"),
        ("Ethereum", r"\bETH\b|\beth\b|Ethereum|etherscan"),
        ("Solana", r"\bSOL\b|\bsol\b|Solana"),
        ("Arbitrum", r"\bARB\b|\barb\b|Arbitrum"),
    ):
        if re.search(pattern, text):
            chains.append(label)

    platforms = []
    for label, pattern in (
        ("PancakeSwap", r"PancakeSwap"),
        ("Aerodrome", r"Aerodrome|Aero Ignition"),
        ("BscScan", r"bscscan"),
        ("BaseScan", r"basescan"),
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
    if re.search(r"狙击|打新|开盘|抢筹|前排|snip", text, re.IGNORECASE):
        tags.append("sniping")
    if re.search(r"池子|加池|流动性|价格区间|V3|LP|PancakeSwap|Aerodrome", text, re.IGNORECASE):
        tags.append("liquidity")
    if re.search(r"贿赂|bundle|BlockRazor|txIndex|内部交易", text, re.IGNORECASE):
        tags.append("bribe_bundle")
    if re.search(r"跨链|bridge|wormhole|hyperlane", text, re.IGNORECASE):
        tags.append("bridge")
    if re.search(r"筹码|流通|锁仓|解锁|融资|FDV|TGE|tokenomics", text, re.IGNORECASE):
        tags.append("tokenomics")
    if re.search(r"地址|合约|监控|授权|大额|tx|bscscan|basescan|contract", text, re.IGNORECASE):
        tags.append("address_monitoring")
    if re.search(r"alpha|BN Alpha|Binance|OKX|coinbase|kraken|上所|上币|boost", text, re.IGNORECASE):
        tags.append("alpha")

    return {
        "topic_tags": pipe_join(tags),
        "relevance_level": "medium" if tags else "uncertain",
        "is_sniping_related": "yes" if "sniping" in tags else "no",
        "is_alpha_related": "yes" if "alpha" in tags else "no",
        "is_onchain_method": "yes" if {"liquidity", "bribe_bundle", "address_monitoring"} & set(tags) else "no",
    }


def make_row(candidate: dict[str, str], data: dict[str, object]) -> dict[str, str]:
    raw_html = str(data.get("html", ""))
    text, date_iso, links = parse_oembed_html(raw_html)
    chain = extract_chain_fields(text)
    labels = label_row(text)
    tweet_id = candidate["id"]
    has_truncation = "…" in text or "..." in text
    pic_links = [link for link in links if "t.co/" in link or "pic.twitter.com" in link]
    row = {
        "id": tweet_id,
        "tweet_url": f"https://x.com/aLiiDeez/status/{tweet_id}",
        "published_at": date_iso,
        "tweet_text": text,
        "author": str(data.get("author_name", "凌云")),
        "media_files": "",
        "media_urls": pipe_join(pic_links),
        "author_media_files": "",
        "author_media_urls": pipe_join(pic_links),
        "embedded_or_quote_media_files": "",
        "embedded_or_quote_media_urls": "",
        "ocr_text": "",
        "author_ocr_text": "",
        "embedded_or_quote_ocr_text": "",
        "topic_tags": labels["topic_tags"],
        "relevance_level": labels["relevance_level"],
        "is_sniping_related": labels["is_sniping_related"],
        "is_alpha_related": labels["is_alpha_related"],
        "is_onchain_method": labels["is_onchain_method"],
        "chain": chain["chain"],
        "project_or_token": "",
        "contract_addresses": chain["contract_addresses"],
        "tx_hashes": chain["tx_hashes"],
        "block_numbers": chain["block_numbers"],
        "wallet_addresses": chain["wallet_addresses"],
        "lp_token_id": chain["lp_token_id"],
        "dex_or_platform": chain["dex_or_platform"],
        "mentioned_tools": "oEmbed",
        "has_image": "unknown" if pic_links else "no",
        "has_video": "unknown",
        "has_onchain_evidence": "yes" if any(chain[k] for k in ("contract_addresses", "tx_hashes", "block_numbers", "lp_token_id")) else "no",
        "why_keep": "supplemental_oembed_candidate",
        "needs_manual_review": "yes",
        "raw_notes": f"source={candidate.get('source_note','')}; oembed_date_only=yes; oembed_may_truncate={'yes' if has_truncation else 'no'}",
    }
    return row


def main() -> None:
    candidates = read_csv(CANDIDATE_PATH)
    raw_rows = read_csv(RAW_CSV)
    fields = list(raw_rows[0].keys())
    existing_ids = {row["id"] for row in raw_rows}

    new_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    raw_lines = []

    for candidate in candidates:
        tweet_id = candidate["id"]
        if tweet_id in existing_ids:
            audit_rows.append({"id": tweet_id, "status": "already_present", "error": "", "added": "no"})
            continue
        data, error = fetch_oembed(tweet_id)
        if error or not data:
            audit_rows.append({"id": tweet_id, "status": "fetch_error", "error": error, "added": "no"})
            continue
        raw_lines.append(json.dumps({"id": tweet_id, "data": data}, ensure_ascii=False))
        row = make_row(candidate, data)
        if not row["tweet_text"]:
            audit_rows.append({"id": tweet_id, "status": "empty_text", "error": "", "added": "no"})
            continue
        new_rows.append(row)
        audit_rows.append({"id": tweet_id, "status": "added", "error": "", "added": "yes"})
        time.sleep(0.5)

    if new_rows:
        combined = raw_rows + [{field: row.get(field, "") for field in fields} for row in new_rows]
        combined.sort(key=lambda row: (row.get("published_at", ""), row.get("id", "")), reverse=True)
        write_csv(RAW_CSV, combined, fields)
        RAW_JSON.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    if raw_lines:
        with OEMBED_RAW.open("a", encoding="utf-8") as f:
            for line in raw_lines:
                f.write(line + "\n")

    write_csv(OEMBED_AUDIT, audit_rows, ["id", "status", "error", "added"])
    print(f"candidates={len(candidates)}")
    print(f"added={len(new_rows)}")
    print(f"already_present={sum(1 for row in audit_rows if row['status']=='already_present')}")
    print(f"errors={sum(1 for row in audit_rows if row['status']=='fetch_error')}")


if __name__ == "__main__":
    main()
