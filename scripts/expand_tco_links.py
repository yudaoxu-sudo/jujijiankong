#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "output" / "aliideez_x_research"
RAW_CSV = DATA_DIR / "raw_tweets.csv"
EXPANDED_CSV = DATA_DIR / "candidates" / "expanded_links.csv"
DISCOVERED_CSV = DATA_DIR / "candidates" / "discovered_from_links.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


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
    rows = read_csv(RAW_CSV)
    seen_urls: set[str] = set()
    link_rows: list[dict[str, str]] = []
    existing_ids = {row["id"] for row in rows}

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

    discovered: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for link in link_rows:
        for match in re.finditer(r"(?:x|twitter)\.com/aLiiDeez/status/([0-9]+)", link["final_url"]):
            tweet_id = match.group(1)
            if tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)
            discovered.append(
                {
                    "id": tweet_id,
                    "source_tweet_id": link["source_tweet_id"],
                    "short_url": link["short_url"],
                    "final_url": link["final_url"],
                    "already_present": "yes" if tweet_id in existing_ids else "no",
                }
            )

    write_csv(EXPANDED_CSV, link_rows, ["source_tweet_id", "short_url", "final_url", "error"])
    write_csv(DISCOVERED_CSV, discovered, ["id", "source_tweet_id", "short_url", "final_url", "already_present"])
    print(f"short_links={len(link_rows)}")
    print(f"discovered_status_ids={len(discovered)}")
    print(f"new_status_ids={sum(1 for row in discovered if row['already_present']=='no')}")


if __name__ == "__main__":
    main()
