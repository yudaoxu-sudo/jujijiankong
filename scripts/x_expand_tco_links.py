#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

from x_research_common import read_csv, write_csv


def expand(url: str) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.geturl(), ""
    except Exception as exc:
        return "", str(exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    account = args.account.lstrip("@")
    rows = read_csv(data_dir / "raw_tweets.csv")
    existing_ids = {row["id"] for row in rows}
    seen_urls: set[str] = set()
    link_rows: list[dict[str, str]] = []

    for row in rows:
        haystack = "\n".join(
            [
                row.get("tweet_text", ""),
                row.get("media_urls", ""),
                row.get("author_media_urls", ""),
                row.get("raw_notes", ""),
            ]
        )
        for url in re.findall(r"https://t\.co/[A-Za-z0-9_]+", haystack):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            final_url, error = expand(url)
            link_rows.append(
                {
                    "source_tweet_id": row["id"],
                    "short_url": url,
                    "final_url": final_url,
                    "error": error,
                }
            )
            time.sleep(0.35)

    discovered_by_id: OrderedDict[str, dict[str, str]] = OrderedDict()
    for link in link_rows:
        pattern = rf"(?:x|twitter)\.com/{re.escape(account)}/status/([0-9]+)"
        for match in re.finditer(pattern, link["final_url"]):
            tweet_id = match.group(1)
            discovered_by_id.setdefault(
                tweet_id,
                {
                    "id": tweet_id,
                    "source_tweet_id": link["source_tweet_id"],
                    "short_url": link["short_url"],
                    "final_url": link["final_url"],
                    "already_present": "yes" if tweet_id in existing_ids else "no",
                },
            )

    write_csv(data_dir / "candidates" / "expanded_links.csv", link_rows, ["source_tweet_id", "short_url", "final_url", "error"])
    write_csv(
        data_dir / "candidates" / "discovered_from_links.csv",
        list(discovered_by_id.values()),
        ["id", "source_tweet_id", "short_url", "final_url", "already_present"],
    )
    print(f"short_links={len(link_rows)}")
    print(f"discovered_status_ids={len(discovered_by_id)}")
    print(f"new_status_ids={sum(1 for row in discovered_by_id.values() if row['already_present']=='no')}")


if __name__ == "__main__":
    main()
