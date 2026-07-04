#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from x_research_common import read_csv, write_csv


KEYWORDS = [
    "alpha",
    "Alpha",
    "链上",
    "打新",
    "狙击",
    "开盘",
    "地址",
    "监控",
    "抓庄",
    "庄",
    "钱包",
    "聪明钱",
    "老鼠仓",
    "meme",
    "Meme",
    "memerush",
    "fourmeme",
    "four.meme",
    "GMGN",
    "项目方",
    "机构",
    "VC",
    "筹码",
    "流动性",
    "土狗",
    "冲狗",
    "合约",
    "TGE",
    "FDV",
    "上币",
    "上所",
    "Binance",
    "OKX",
    "BN",
]


LOW_VALUE_PATTERNS = [
    r"^mark\s*$",
    r"^转发微博\s*$",
]


def score_text(text: str) -> int:
    return sum(1 for keyword in KEYWORDS if keyword in text)


def low_value(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text or "").strip()
    return any(re.search(pattern, stripped, flags=re.IGNORECASE) for pattern in LOW_VALUE_PATTERNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    account = args.account.lstrip("@")
    raw_path = data_dir / "candidates" / "chrome_search_results.json"
    all_results = json.loads(raw_path.read_text(encoding="utf-8"))
    existing_raw = {row["id"] for row in read_csv(data_dir / "raw_tweets.csv")}
    existing_candidates = read_csv(data_dir / "candidates" / "manual_candidate_ids.csv")
    candidate_ids = {row["id"] for row in existing_candidates}

    kept = []
    rejected = []
    additions = []
    for item in all_results:
        text = item.get("text", "")
        score = score_text(text)
        row = {
            "id": item.get("id", ""),
            "tweet_url": f"https://x.com/{account}/status/{item.get('id','')}",
            "query": item.get("query", ""),
            "score": str(score),
            "already_raw": "yes" if item.get("id") in existing_raw else "no",
            "already_candidate": "yes" if item.get("id") in candidate_ids else "no",
            "text_preview": re.sub(r"\s+", " ", text).strip()[:280],
            "image_count": str(len(item.get("imgSrcs") or [])),
        }
        if score > 0 and not low_value(text):
            kept.append(row)
            if row["already_candidate"] == "no":
                additions.append(
                    {
                        "id": item.get("id", ""),
                        "source_note": f"chrome_search:{row['query']}; score={score}",
                    }
                )
                candidate_ids.add(item.get("id", ""))
        else:
            rejected.append(row)

    write_csv(
        data_dir / "candidates" / "chrome_candidates_filtered.csv",
        kept,
        ["id", "tweet_url", "query", "score", "already_raw", "already_candidate", "text_preview", "image_count"],
    )
    write_csv(
        data_dir / "candidates" / "chrome_candidates_rejected.csv",
        rejected,
        ["id", "tweet_url", "query", "score", "already_raw", "already_candidate", "text_preview", "image_count"],
    )
    merged_candidates = existing_candidates + additions
    write_csv(data_dir / "candidates" / "manual_candidate_ids.csv", merged_candidates, ["id", "source_note"])
    print(f"chrome_results={len(all_results)}")
    print(f"kept={len(kept)}")
    print(f"rejected={len(rejected)}")
    print(f"new_candidate_ids={len(additions)}")


if __name__ == "__main__":
    main()
