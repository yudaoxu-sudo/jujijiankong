#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from x_research_common import RAW_FIELDS, json_dump_rows, pipe_join, read_csv, split_pipe, write_csv


def extract_fields(text: str) -> dict[str, str]:
    addresses = re.findall(r"0x[a-fA-F0-9]{40}", text)
    tx_hashes = re.findall(r"0x[a-fA-F0-9]{64}", text)
    address_set = [addr for addr in addresses if addr not in tx_hashes]
    blocks = re.findall(r"\b(?:block|区块)\s*[:#]?\s*([0-9]{7,10})\b", text, flags=re.IGNORECASE)
    lp_ids = []
    for pattern in (r"(?:Position ID|Token ID|LP #|#)\s*([0-9]{5,10})", r"\b(?:position|lp)\s*id\s*[:#]?\s*([0-9]{5,10})"):
        lp_ids.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    amounts = re.findall(r"\b\d+(?:\.\d+)?\s*(?:BNB|ETH|USDT|USDC|USD|刀|u|U)\b", text, flags=re.IGNORECASE)
    return {
        "addresses": pipe_join(address_set),
        "tx_hashes": pipe_join(tx_hashes),
        "block_numbers": pipe_join(blocks),
        "lp_token_id": pipe_join(lp_ids),
        "amounts": pipe_join(amounts[:20]),
    }


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
    ocr_path = data_dir / "ocr_results.jsonl"
    manifest = read_csv(data_dir / "media_manifest.csv")
    scope_by_file = {row["local_file"]: row.get("media_scope", "") for row in manifest if row.get("local_file")}
    tweet_by_file = {row["local_file"]: row.get("tweet_id", "") for row in manifest if row.get("local_file")}

    ocr_rows = []
    text_by_tweet: dict[str, list[str]] = defaultdict(list)
    author_text_by_tweet: dict[str, list[str]] = defaultdict(list)
    for line in ocr_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        file_path = item.get("file", "")
        rel_file = "media/" + Path(file_path).name
        text = item.get("text", "") or ""
        fields = extract_fields(text)
        tweet_id = tweet_by_file.get(rel_file, "")
        scope = scope_by_file.get(rel_file, "")
        ocr_rows.append(
            {
                "tweet_id": tweet_id,
                "tweet_url": f"https://x.com/0xcrypto_max/status/{tweet_id}" if tweet_id else "",
                "media_file": rel_file,
                "media_scope": scope,
                "addresses": fields["addresses"],
                "tx_hashes": fields["tx_hashes"],
                "block_numbers": fields["block_numbers"],
                "lp_token_id": fields["lp_token_id"],
                "amounts": fields["amounts"],
                "ocr_text": text,
                "error": item.get("error") or "",
            }
        )
        if tweet_id and text:
            text_by_tweet[tweet_id].append(text)
            if scope == "author_attached":
                author_text_by_tweet[tweet_id].append(text)

    raw_rows = read_csv(data_dir / "raw_tweets.csv")
    extracted_by_tweet: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in ocr_rows:
        tid = row["tweet_id"]
        if not tid:
            continue
        for key in ("addresses", "tx_hashes", "block_numbers", "lp_token_id"):
            for value in split_pipe(row[key]):
                extracted_by_tweet[tid][key].append(value)

    for row in raw_rows:
        tid = row["id"]
        if tid in text_by_tweet:
            row["ocr_text"] = "\n\n".join(text_by_tweet[tid])
        if tid in author_text_by_tweet:
            row["author_ocr_text"] = "\n\n".join(author_text_by_tweet[tid])
        extracted = extracted_by_tweet.get(tid, {})
        row["contract_addresses"] = merge_pipe(row.get("contract_addresses", ""), extracted.get("addresses", []))
        row["wallet_addresses"] = merge_pipe(row.get("wallet_addresses", ""), extracted.get("addresses", []))
        row["tx_hashes"] = merge_pipe(row.get("tx_hashes", ""), extracted.get("tx_hashes", []))
        row["block_numbers"] = merge_pipe(row.get("block_numbers", ""), extracted.get("block_numbers", []))
        row["lp_token_id"] = merge_pipe(row.get("lp_token_id", ""), extracted.get("lp_token_id", []))
        if any(extracted.get(key) for key in ("addresses", "tx_hashes", "block_numbers", "lp_token_id")):
            row["has_onchain_evidence"] = "yes"

    write_csv(data_dir / "ocr_extracted.csv", ocr_rows, ["tweet_id", "tweet_url", "media_file", "media_scope", "addresses", "tx_hashes", "block_numbers", "lp_token_id", "amounts", "ocr_text", "error"])
    write_csv(data_dir / "raw_tweets.csv", raw_rows, RAW_FIELDS)
    json_dump_rows(data_dir / "raw_tweets.json", raw_rows)
    print(f"ocr_rows={len(ocr_rows)}")
    print(f"nonempty_ocr={sum(1 for row in ocr_rows if row['ocr_text'])}")
    print(f"ocr_errors={sum(1 for row in ocr_rows if row['error'])}")


if __name__ == "__main__":
    main()
