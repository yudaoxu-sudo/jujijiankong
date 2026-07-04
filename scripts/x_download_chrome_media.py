#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from x_research_common import RAW_FIELDS, json_dump_rows, pipe_join, read_csv, split_pipe, write_csv


def media_ext(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    fmt = (params.get("format") or [""])[0].lower()
    if fmt in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "jpg" if fmt == "jpeg" else fmt
    suffix = Path(parsed.path).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "jpg" if suffix == "jpeg" else suffix
    return "jpg"


def normalize_media_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if "pbs.twimg.com" not in parsed.netloc or "/media/" not in parsed.path:
        return ""
    params = urllib.parse.parse_qs(parsed.query)
    fmt = (params.get("format") or [""])[0]
    if fmt:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urllib.parse.urlencode({"format": fmt, "name": "large"}), ""))
    return url


def download(url: str, path: Path) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        path.write_bytes(data)
        return ""
    except Exception as exc:
        return str(exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    chrome_path = data_dir / "candidates" / "chrome_search_results.json"
    if not chrome_path.exists():
        print("chrome_search_results=missing")
        return

    chrome_items = json.loads(chrome_path.read_text(encoding="utf-8"))
    media_by_id: dict[str, list[str]] = {}
    for item in chrome_items:
        tweet_id = item.get("id")
        urls = []
        for src in item.get("imgSrcs") or []:
            normalized = normalize_media_url(src)
            if normalized and normalized not in urls:
                urls.append(normalized)
        if tweet_id and urls:
            media_by_id.setdefault(tweet_id, [])
            for url in urls:
                if url not in media_by_id[tweet_id]:
                    media_by_id[tweet_id].append(url)

    raw_rows = read_csv(data_dir / "raw_tweets.csv")
    manifest_rows: list[dict[str, str]] = []
    existing_manifest = read_csv(data_dir / "media_manifest.csv")
    existing_urls = {row.get("source_url", "") for row in existing_manifest}
    manifest_rows.extend(existing_manifest)

    for row in raw_rows:
        tweet_id = row["id"]
        urls = media_by_id.get(tweet_id, [])
        if not urls:
            continue
        local_files = split_pipe(row.get("media_files", ""))
        for index, url in enumerate(urls, start=1):
            ext = media_ext(url)
            filename = f"{tweet_id}_{index:02d}.{ext}"
            rel_path = f"media/{filename}"
            abs_path = media_dir / filename
            if url not in existing_urls:
                error = download(url, abs_path)
                manifest_rows.append(
                    {
                        "tweet_id": tweet_id,
                        "media_scope": "chrome_article_media_unverified",
                        "source_url": url,
                        "local_file": rel_path if not error else "",
                        "error": error,
                    }
                )
                existing_urls.add(url)
                time.sleep(0.2)
            if abs_path.exists() and rel_path not in local_files:
                local_files.append(rel_path)
        row["media_files"] = pipe_join(local_files)
        row["media_urls"] = pipe_join(split_pipe(row.get("media_urls", "")) + urls)
        if local_files:
            row["has_image"] = "yes"

    write_csv(data_dir / "raw_tweets.csv", raw_rows, RAW_FIELDS)
    json_dump_rows(data_dir / "raw_tweets.json", raw_rows)
    write_csv(data_dir / "media_manifest.csv", manifest_rows, ["tweet_id", "media_scope", "source_url", "local_file", "error"])
    print(f"tweet_ids_with_media={len(media_by_id)}")
    print(f"manifest_rows={len(manifest_rows)}")
    print(f"download_errors={sum(1 for row in manifest_rows if row.get('error'))}")


if __name__ == "__main__":
    main()
