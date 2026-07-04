#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from x_research_common import (
    RAW_FIELDS,
    ensure_raw_files,
    extract_chain_fields,
    json_dump_rows,
    label_row,
    parse_oembed_html,
    pipe_join,
    read_csv,
    write_csv,
)


def fetch_oembed(account: str, tweet_id: str) -> tuple[dict[str, object] | None, str]:
    target = f"https://x.com/{account}/status/{tweet_id}"
    params = urllib.parse.urlencode({"url": target, "omit_script": "true"})
    url = f"https://publish.twitter.com/oembed?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as exc:
        return None, str(exc)


def make_row(account: str, candidate: dict[str, str], data: dict[str, object]) -> dict[str, str]:
    raw_html = str(data.get("html", ""))
    text, date_iso, links = parse_oembed_html(raw_html)
    chain = extract_chain_fields(text)
    labels = label_row(text)
    tweet_id = candidate["id"]
    has_truncation = "…" in text or "..." in text
    pic_links = [link for link in links if "t.co/" in link or "pic.twitter.com" in link]
    return {
        "id": tweet_id,
        "tweet_url": f"https://x.com/{account}/status/{tweet_id}",
        "published_at": date_iso,
        "tweet_text": text,
        "author": str(data.get("author_name", account)),
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    account = args.account.lstrip("@")
    ensure_raw_files(data_dir)

    candidate_path = data_dir / "candidates" / "manual_candidate_ids.csv"
    raw_csv = data_dir / "raw_tweets.csv"
    raw_json = data_dir / "raw_tweets.json"
    oembed_raw = data_dir / "candidates" / "oembed_raw.jsonl"
    oembed_audit = data_dir / "candidates" / "oembed_audit.csv"

    candidates = read_csv(candidate_path)
    raw_rows = read_csv(raw_csv)
    existing_ids = {row["id"] for row in raw_rows}
    new_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    raw_lines: list[str] = []

    seen_candidate_ids: set[str] = set()
    for candidate in candidates:
        tweet_id = candidate["id"]
        if tweet_id in seen_candidate_ids:
            audit_rows.append({"id": tweet_id, "status": "duplicate_candidate", "error": "", "added": "no"})
            continue
        seen_candidate_ids.add(tweet_id)
        if tweet_id in existing_ids:
            audit_rows.append({"id": tweet_id, "status": "already_present", "error": "", "added": "no"})
            continue
        data, error = fetch_oembed(account, tweet_id)
        if error or not data:
            audit_rows.append({"id": tweet_id, "status": "fetch_error", "error": error, "added": "no"})
            continue
        raw_lines.append(json.dumps({"id": tweet_id, "data": data}, ensure_ascii=False))
        row = make_row(account, candidate, data)
        if not row["tweet_text"]:
            audit_rows.append({"id": tweet_id, "status": "empty_text", "error": "", "added": "no"})
            continue
        new_rows.append(row)
        existing_ids.add(tweet_id)
        audit_rows.append({"id": tweet_id, "status": "added", "error": "", "added": "yes"})
        time.sleep(0.5)

    if new_rows:
        combined = raw_rows + [{field: row.get(field, "") for field in RAW_FIELDS} for row in new_rows]
        combined.sort(key=lambda row: (row.get("published_at", ""), row.get("id", "")), reverse=True)
        write_csv(raw_csv, combined, RAW_FIELDS)
        json_dump_rows(raw_json, combined)

    if raw_lines:
        with oembed_raw.open("a", encoding="utf-8") as f:
            for line in raw_lines:
                f.write(line + "\n")

    write_csv(oembed_audit, audit_rows, ["id", "status", "error", "added"])
    print(f"candidates={len(candidates)}")
    print(f"added={len(new_rows)}")
    print(f"already_present={sum(1 for row in audit_rows if row['status']=='already_present')}")
    print(f"errors={sum(1 for row in audit_rows if row['status']=='fetch_error')}")


if __name__ == "__main__":
    main()
