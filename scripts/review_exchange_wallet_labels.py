#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label, is_address, norm


DEFAULT_OUT_DIR = ROOT / "output" / "exchange_wallet_labels" / "review"
SUPPORTED_CHAINS = {"bsc"}
TYPE_TO_CLASS = {
    "hot_wallet": "cex_hot_wallet",
    "deposit_wallet": "cex_deposit",
    "deposit": "cex_deposit",
    "deposit_funder": "cex_deposit",
}
PROTOCOL_TYPES = {"router", "aggregator", "dex_router", "custody", "proxy"}


def read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("input must be a JSON array")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def row_type(row: dict[str, Any]) -> str:
    return str(row.get("type") or row.get("wallet_type") or "").strip().lower()


def confidence(row: dict[str, Any]) -> str:
    return str(row.get("confidence") or "").strip().lower()


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    chain = str(row.get("chain") or "").strip().lower()
    address = norm(row.get("address"))
    wallet_type = row_type(row)
    current = global_address_label(chain, address) or {}

    if chain not in SUPPORTED_CHAINS:
        return {"status": "rejected", "reason": "unsupported_chain", "current_class": current.get("class", "")}
    if not is_address(address):
        return {"status": "rejected", "reason": "invalid_address", "current_class": current.get("class", "")}
    if wallet_type in PROTOCOL_TYPES:
        return {"status": "rejected", "reason": "protocol_or_router_not_cex_wallet", "current_class": current.get("class", "")}
    if confidence(row) != "high":
        return {"status": "rejected", "reason": "confidence_not_high", "current_class": current.get("class", "")}

    label_class = TYPE_TO_CLASS.get(wallet_type)
    if not label_class:
        return {"status": "rejected", "reason": "unsupported_wallet_type", "current_class": current.get("class", "")}

    if current.get("class") == label_class:
        return {"status": "already_configured", "reason": "matching_global_label", "current_class": current.get("class", "")}
    if current.get("class") and current.get("class") != label_class:
        return {"status": "needs_manual_review", "reason": "class_conflict", "current_class": current.get("class", "")}

    return {
        "status": "accepted_candidate",
        "reason": "valid_high_confidence_cex_wallet",
        "class": label_class,
        "current_class": current.get("class", ""),
    }


def label_name(row: dict[str, Any], label_class: str) -> str:
    exchange = str(row.get("exchange") or "").strip() or "Unknown CEX"
    evidence = str(row.get("evidence") or "").strip()
    if evidence.lower().startswith("bscscan label:"):
        return evidence.split(":", 1)[1].strip()
    if label_class == "cex_deposit":
        return f"{exchange} Deposit Wallet"
    return f"{exchange} Hot Wallet"


def proposal(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("status") != "accepted_candidate":
        return None
    label_class = str(result.get("class") or "")
    return {
        "address": norm(row.get("address")),
        "label": label_name(row, label_class),
        "class": label_class,
        "exchange": str(row.get("exchange") or "").strip(),
        "evidence": (
            f"{datetime.now(timezone.utc).date()} external exchange-wallet review: "
            f"{row.get('evidence', '')}. Used as CEX destination, never as funding cluster parent."
        ),
    }


def build_review(path: Path) -> dict[str, Any]:
    rows = read_rows(path)
    reviewed = []
    proposals = []
    for index, row in enumerate(rows):
        result = classify_row(row)
        item = {
            "index": index,
            "chain": str(row.get("chain") or "").strip().lower(),
            "address": norm(row.get("address")),
            "exchange": row.get("exchange", ""),
            "type": row_type(row),
            "confidence": confidence(row),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "class": result.get("class", ""),
            "current_class": result.get("current_class", ""),
            "source_url": row.get("source_url", ""),
        }
        reviewed.append(item)
        if candidate := proposal(row, result):
            proposals.append(candidate)
    counts: dict[str, int] = {}
    for item in reviewed:
        status = str(item.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema": "exchange_wallet_label_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(path),
        "counts": counts,
        "reviewed": reviewed,
        "label_proposals": proposals,
    }


def write_review(review: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    md_path = out_dir / "latest.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(review), encoding="utf-8")
    return json_path, md_path


def markdown(review: dict[str, Any]) -> str:
    lines = [
        "# Exchange Wallet Label Review",
        "",
        f"Source: `{review['source_file']}`",
        f"Generated: `{review['generated_at']}`",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(review["counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Rows", "", "| # | Exchange | Address | Type | Confidence | Status | Reason |", "| ---: | --- | --- | --- | --- | --- | --- |"])
    for item in review["reviewed"]:
        address = str(item["address"])
        short = f"{address[:10]}...{address[-6:]}" if len(address) > 18 else address
        lines.append(
            f"| {item['index']} | {item['exchange']} | `{short}` | {item['type']} | "
            f"{item['confidence']} | {item['status']} | {item['reason']} |"
        )
    lines.extend(["", "## Label Proposals", ""])
    if not review["label_proposals"]:
        lines.append("No new high-confidence label proposals.")
    else:
        lines.append("```json")
        lines.append(json.dumps(review["label_proposals"], ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review external CEX wallet label JSON without modifying global labels.")
    parser.add_argument("--input", required=True, type=Path, help="External exchange wallet JSON array")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    args = parser.parse_args()

    review = build_review(args.input)
    json_path, md_path = write_review(review, args.out_dir)
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
