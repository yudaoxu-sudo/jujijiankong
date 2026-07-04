#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from x_research_common import RAW_FIELDS, json_dump_rows, read_csv, split_pipe, write_csv


def merge_pipe(existing: str, additions: list[str]) -> str:
    parts = split_pipe(existing)
    for item in additions:
        if item and item not in parts:
            parts.append(item)
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    rows = read_csv(data_dir / "raw_tweets.csv")
    expanded = read_csv(data_dir / "candidates" / "expanded_links.csv")
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
            if "/tx/" in url:
                tx_hashes.extend(re.findall(r"0x[a-fA-F0-9]{64}", url))
            if any(domain in url for domain in ("bscscan.com", "basescan.org", "etherscan.io", "arbiscan.io", "solscan.io", "hypurrscan.io")):
                addresses.extend(re.findall(r"0x[a-fA-F0-9]{40}", url))
            for name, domain in (
                ("BscScan", "bscscan.com"),
                ("BaseScan", "basescan.org"),
                ("Etherscan", "etherscan.io"),
                ("Arbiscan", "arbiscan.io"),
                ("Solscan", "solscan.io"),
                ("Hypurrscan", "hypurrscan.io"),
                ("DEXTools", "dextools.io"),
                ("DEXScreener", "dexscreener.com"),
            ):
                if domain in url:
                    tools.append(name)

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

    write_csv(data_dir / "raw_tweets.csv", rows, RAW_FIELDS)
    json_dump_rows(data_dir / "raw_tweets.json", rows)
    print(f"rows_changed={changed}")


if __name__ == "__main__":
    main()
