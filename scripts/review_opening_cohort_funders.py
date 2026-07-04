#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.entity_clustering import cluster_by_funding_source, funding_source_class, is_address, norm
from sniper_engine.rpc import get_block_by_number


DEFAULT_OUT_DIR = ROOT / "output" / "opening_cohort_funders"


def short_addr(value: str) -> str:
    return f"{value[:10]}...{value[-6:]}" if len(value) > 18 else value


def load_opening_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    extracted: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        for event in payload["events"]:
            if not isinstance(event, dict):
                continue
            for row in event.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                extracted.append(normalize_row(row, event))
                if len(extracted) >= limit:
                    return extracted
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        event = payload.get("launch_event") or payload.get("event") or {}
        for row in payload["rows"]:
            if not isinstance(row, dict):
                continue
            extracted.append(normalize_row(row, event if isinstance(event, dict) else {}))
            if len(extracted) >= limit:
                return extracted
    elif isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            extracted.append(normalize_row(row, {}))
            if len(extracted) >= limit:
                return extracted
    return extracted


def normalize_row(row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    wallet = norm(row.get("buyer") or row.get("address") or row.get("wallet"))
    return {
        "symbol": str(event.get("symbol") or row.get("symbol") or ""),
        "project": str(event.get("name") or row.get("project") or ""),
        "address": wallet if is_address(wallet) else "",
        "role": "opening_buyer",
        "buy_block": int(row.get("block") or 0),
        "tx_index": row.get("tx_index"),
        "tx": str(row.get("tx") or ""),
        "spent_quote": str(row.get("spent_quote") or row.get("spent_usdt") or row.get("estimated_spent_quote") or ""),
        "token_bought": str(row.get("token_bought") or row.get("arx_bought") or ""),
        "trace_status": str((row.get("buyer_trace") or {}).get("status") or ""),
        "funding_source": "",
        "funding_block": "",
        "funding_value_native": "",
        "funding_tx": "",
        "funding_source_class": "",
    }


def hex_int(value: str | None) -> int:
    if not value:
        return 0
    return int(value, 16)


def native_amount(value_wei: int) -> str:
    return f"{value_wei / 10**18:.8f}".rstrip("0").rstrip(".")


def scan_native_funders(
    chain: str,
    rows: list[dict[str, Any]],
    lookback_blocks: int,
    max_scan_seconds: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    targets = {row["address"] for row in rows if is_address(row.get("address")) and int(row.get("buy_block") or 0) > 0}
    if not targets or lookback_blocks <= 0:
        return {}, {"scanned_blocks": 0, "scan_limited": False, "scan_seconds": 0.0}
    before_by_target: dict[str, int] = {}
    for row in rows:
        address = row.get("address")
        block = int(row.get("buy_block") or 0)
        if address in targets and block > 0:
            before_by_target[address] = min(before_by_target.get(address, block), block)
    latest_buy_block = max(before_by_target.values())
    start = max(0, latest_buy_block - lookback_blocks)
    funders: dict[str, dict[str, Any]] = {}
    scan_started = time.monotonic()
    scanned_blocks = 0
    scan_limited = False
    for block_number in range(latest_buy_block, start - 1, -1):
        if max_scan_seconds > 0 and time.monotonic() - scan_started > max_scan_seconds:
            scan_limited = True
            break
        if len(funders) >= len(targets):
            break
        block = get_block_by_number(chain, block_number, True)
        scanned_blocks += 1
        for tx in block.get("transactions", []):
            to_addr = norm(tx.get("to"))
            if to_addr not in targets or to_addr in funders:
                continue
            if block_number > before_by_target.get(to_addr, 0):
                continue
            value = hex_int(tx.get("value"))
            if value <= 0:
                continue
            funders[to_addr] = {
                "funding_source": norm(tx.get("from")),
                "funding_block": block_number,
                "funding_value_native": native_amount(value),
                "funding_tx": str(tx.get("hash") or ""),
            }
    return funders, {
        "scanned_blocks": scanned_blocks,
        "scan_limited": scan_limited,
        "scan_seconds": round(time.monotonic() - scan_started, 3),
    }


def attach_funders(chain: str, rows: list[dict[str, Any]], funders: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        funder = funders.get(str(item.get("address") or ""))
        if funder:
            item.update(funder)
            item["funding_source_class"] = funding_source_class(chain, str(funder.get("funding_source") or "")) or "unlabeled"
        enriched.append(item)
    return enriched


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Opening Cohort Funder Review",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- chain: `{payload['chain']}`",
        f"- source_file: `{payload['source_file']}`",
        f"- lookback_blocks: `{payload['lookback_blocks']}`",
        f"- scanned_blocks: `{payload['scanned_blocks']}`",
        f"- scan_limited: `{payload['scan_limited']}`",
        f"- cohort_rows: `{len(payload['rows'])}`",
        f"- funders_found: `{payload['funders_found']}`",
        f"- cluster_count: `{payload['cluster_review']['cluster_count']}`",
        "",
        "## Cohort Rows",
        "",
        "| # | Symbol | Buyer | Funder | Funder Class | Buy Block | Funding Native |",
        "| ---: | --- | --- | --- | --- | ---: | ---: |",
    ]
    for index, row in enumerate(payload["rows"], 1):
        lines.append(
            "| {index} | {symbol} | `{buyer}` | `{funder}` | {klass} | {block} | {value} |".format(
                index=index,
                symbol=row.get("symbol") or "",
                buyer=short_addr(row.get("address") or ""),
                funder=short_addr(row.get("funding_source") or ""),
                klass=row.get("funding_source_class") or "",
                block=row.get("buy_block") or "",
                value=row.get("funding_value_native") or "",
            )
        )
    lines.extend(["", "## Funding Clusters", ""])
    clusters = payload["cluster_review"].get("clusters", [])
    if not clusters:
        lines.append("No same-funding-source cluster above threshold.")
    else:
        lines.extend(["| # | Members | Funding Sources |", "| ---: | --- | --- |"])
        for index, cluster in enumerate(clusters, 1):
            members = ", ".join(f"`{short_addr(value)}`" for value in cluster.get("members", [])[:12])
            sources = ", ".join(f"`{short_addr(value)}`" for value in cluster.get("funding_sources", [])[:6])
            lines.append(f"| {index} | {members} | {sources} |")
    skipped = payload["cluster_review"].get("skipped_parents", [])
    if skipped:
        lines.extend(["", "## Skipped Unsafe Parents", "", "| # | Parent | Class | Children |", "| ---: | --- | --- | ---: |"])
        for index, row in enumerate(skipped, 1):
            lines.append(f"| {index} | `{short_addr(row.get('address', ''))}` | {row.get('class', '')} | {row.get('child_count', 0)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract opening buyers and review recent native funding-source clusters.")
    parser.add_argument("--input", type=Path, default=ROOT / "output" / "alpha_opening_block_watch" / "latest.json")
    parser.add_argument("--chain", default="bsc")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--lookback-blocks", type=int, default=0, help="0 extracts rows only; positive values scan recent full blocks for native funding txs.")
    parser.add_argument("--max-scan-seconds", type=float, default=25.0)
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    rows = [row for row in load_opening_rows(args.input, args.limit) if is_address(row.get("address"))]
    funders, scan_meta = scan_native_funders(args.chain, rows, args.lookback_blocks, args.max_scan_seconds)
    rows = attach_funders(args.chain, rows, funders)
    cluster_review = cluster_by_funding_source(args.chain, rows, min_cluster_size=args.min_cluster_size)
    payload = {
        "schema": "opening_cohort_funder_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(args.input),
        "chain": args.chain,
        "lookback_blocks": args.lookback_blocks,
        **scan_meta,
        "funders_found": len(funders),
        "rows": rows,
        "cluster_review": cluster_review,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    latest_json = args.out_dir / "latest.json"
    latest_md = args.out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text(markdown(payload), encoding="utf-8")
    print(latest_json)
    print(latest_md)
    print(f"rows={len(rows)} funders={len(funders)} clusters={cluster_review['cluster_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
