#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "output" / "aliideez_x_research"
RAW_CSV = DATA_DIR / "raw_tweets.csv"
RAW_JSON = DATA_DIR / "raw_tweets.json"
EXPANDED_CSV = DATA_DIR / "candidates" / "expanded_links.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def merge_pipe(existing: str, additions: list[str]) -> str:
    parts = [part for part in (existing or "").split("|") if part]
    for item in additions:
        if item and item not in parts:
            parts.append(item)
    return "|".join(parts)


def main() -> None:
    rows = read_csv(RAW_CSV)
    fields = list(rows[0].keys())
    expanded = read_csv(EXPANDED_CSV)
    by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for link in expanded:
        if link.get("final_url"):
            by_source[link["source_tweet_id"]].append(link)

    changed = 0
    for row in rows:
        links = by_source.get(row["id"], [])
        if not links:
            continue
        final_urls = [link["final_url"] for link in links if link.get("final_url")]
        tx_hashes: list[str] = []
        addresses: list[str] = []
        tools: list[str] = []
        for url in final_urls:
            if "bscscan.com/tx/" in url or "etherscan.io/tx/" in url or "/tx/" in url:
                tx_hashes.extend(re.findall(r"0x[a-fA-F0-9]{64}", url))
            if any(domain in url for domain in ("bscscan.com", "basescan.org", "etherscan.io", "explorer.mainnet.citrea.xyz")):
                addresses.extend(re.findall(r"0x[a-fA-F0-9]{40}", url))
            if "bscscan.com" in url:
                tools.append("BscScan")
            if "basescan.org" in url:
                tools.append("BaseScan")
            if "etherscan.io" in url:
                tools.append("Etherscan")
            if "dextools.io" in url:
                tools.append("DEXTools")

        before = json.dumps(row, ensure_ascii=False, sort_keys=True)
        row["tx_hashes"] = merge_pipe(row.get("tx_hashes", ""), tx_hashes)
        row["contract_addresses"] = merge_pipe(row.get("contract_addresses", ""), addresses)
        row["wallet_addresses"] = merge_pipe(row.get("wallet_addresses", ""), addresses)
        row["mentioned_tools"] = merge_pipe(row.get("mentioned_tools", ""), tools + ["expanded_tco"])
        if tx_hashes or addresses or tools:
            row["has_onchain_evidence"] = "yes"
        link_note = "expanded_links=" + "|".join(final_urls)
        if link_note not in row.get("raw_notes", ""):
            row["raw_notes"] = (row.get("raw_notes", "") + "; " + link_note).strip("; ")
        after = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed += 1

    write_csv(RAW_CSV, rows, fields)
    RAW_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rows_changed={changed}")


if __name__ == "__main__":
    main()
