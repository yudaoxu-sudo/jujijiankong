#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.entity_clustering import cluster_by_funding_source


DEFAULT_OUT_DIR = ROOT / "output" / "funding_source_clusters"


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "wallets", "addresses", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("input must be a JSON array, a JSON object with rows/wallets/addresses/items, or a CSV file")


def read_extra_labels(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "chains" in payload:
        rows = payload.get("chains", {}).get("bsc", [])
    elif isinstance(payload, dict):
        rows = payload.get("labels") or payload.get("rows") or payload.get("items") or []
        if not rows:
            return {str(address).lower(): {"class": value} for address, value in payload.items() if str(address).startswith("0x")}
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    labels: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = str(row.get("address") or "").strip().lower()
        if len(address) != 42 or not address.startswith("0x"):
            continue
        labels[address] = row
    return labels


def short_addr(value: str) -> str:
    return f"{value[:10]}...{value[-6:]}" if len(value) > 18 else value


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Funding Source Cluster Review",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- chain: `{payload['chain']}`",
        f"- source_file: `{payload['source_file']}`",
        f"- input_rows: `{payload['input_rows']}`",
        f"- cluster_count: `{payload['cluster_count']}`",
        f"- skipped_parent_count: `{payload['skipped_parent_count']}`",
        "",
        "## Clusters",
        "",
    ]
    clusters = payload.get("clusters", [])
    if not clusters:
        lines.append("No same-funding-source clusters above threshold.")
    else:
        lines.extend(
            [
                "| # | Members | Funding Sources |",
                "| ---: | --- | --- |",
            ]
        )
        for index, cluster in enumerate(clusters, 1):
            members = ", ".join(f"`{short_addr(value)}`" for value in cluster.get("members", [])[:12])
            sources = ", ".join(f"`{short_addr(value)}`" for value in cluster.get("funding_sources", [])[:6])
            lines.append(f"| {index} | {members} | {sources} |")
    lines.extend(["", "## Skipped Parents", ""])
    skipped = payload.get("skipped_parents", [])
    if not skipped:
        lines.append("No unsafe funding parents were used.")
    else:
        lines.extend(
            [
                "| # | Parent | Class | Children |",
                "| ---: | --- | --- | ---: |",
            ]
        )
        for index, row in enumerate(skipped, 1):
            lines.append(
                f"| {index} | `{short_addr(row.get('address', ''))}` | {row.get('class', '')} | {row.get('child_count', 0)} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review wallet clusters by first funding source.")
    parser.add_argument("--input", required=True, type=Path, help="JSON/CSV rows with address/wallet and funding_source/funder/source fields.")
    parser.add_argument("--extra-labels", type=Path, help="Optional JSON labels used to reject CEX/bridge/router funding parents.")
    parser.add_argument("--chain", default="bsc")
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    rows = read_rows(args.input)
    extra_labels = read_extra_labels(args.extra_labels)
    review = cluster_by_funding_source(args.chain, rows, extra_labels=extra_labels, min_cluster_size=args.min_cluster_size)
    payload = {
        "schema": "funding_source_cluster_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(args.input),
        "extra_labels_file": str(args.extra_labels) if args.extra_labels else "",
        "extra_label_count": len(extra_labels),
        **review,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    latest_json = args.out_dir / "latest.json"
    latest_md = args.out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text(markdown(payload), encoding="utf-8")
    print(latest_json)
    print(latest_md)
    print(f"clusters={payload['cluster_count']} skipped_parents={payload['skipped_parent_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
