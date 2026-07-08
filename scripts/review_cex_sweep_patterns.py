#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.address_labels import global_address_label, is_address, norm


DEFAULT_OUT_DIR = ROOT / "output" / "exchange_wallet_labels" / "sweep_review"
SUPPORTED_CHAINS = {"bsc"}
MIN_SWEEP_TXS = 3
NATIVE_ASSET_VALUES = {"native", "native_bnb", "bnb"}
OUTBOUND_SWEEP_DIRECTIONS = {"out_to_cex_hot_wallet", "sweep_to_hot_wallet", "outbound_sweep"}


def read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("input must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def row_type(row: dict[str, Any]) -> str:
    return str(row.get("type") or row.get("wallet_type") or row.get("candidate_type") or "").strip().lower()


def confidence(row: dict[str, Any]) -> str:
    return str(row.get("confidence") or "").strip().lower()


def sweep_paths(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("sweep_paths") or row.get("sweep_txs") or row.get("paths") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def outbound_sweep_path(path: dict[str, Any]) -> bool:
    direction = str(path.get("direction") or "").strip().lower()
    return not direction or direction in OUTBOUND_SWEEP_DIRECTIONS


def normalized_asset_type(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_").lstrip("$")


def row_asset_type(row: dict[str, Any]) -> str:
    for key in ("asset_type", "token_type", "asset_class"):
        value = normalized_asset_type(row.get(key))
        if value:
            return value
    return ""


def path_asset_type(path: dict[str, Any]) -> str:
    for key in ("asset_type", "token_type", "asset", "symbol", "token_symbol", "currency"):
        value = normalized_asset_type(path.get(key))
        if value:
            return value
    return ""


def native_asset_only(row: dict[str, Any], paths: list[dict[str, Any]]) -> bool:
    row_asset = row_asset_type(row)
    if row_asset in NATIVE_ASSET_VALUES:
        return True
    path_assets = [path_asset_type(path) for path in paths]
    path_assets = [asset for asset in path_assets if asset]
    return bool(path_assets) and all(asset in NATIVE_ASSET_VALUES for asset in path_assets)


def target_address(path: dict[str, Any]) -> str:
    for key in ("hot_wallet", "sweep_to", "to", "target", "final_to"):
        value = norm(path.get(key))
        if is_address(value):
            return value
    return ""


def path_tx_hash(path: dict[str, Any]) -> str:
    text = str(path.get("tx_hash") or path.get("tx") or "").strip().lower()
    if len(text) == 66 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:]):
        return text
    return ""


def target_exchange(chain: str, address: str) -> str:
    row = global_address_label(chain, address) or {}
    return str(row.get("exchange") or "").strip()


def target_class(chain: str, address: str) -> str:
    row = global_address_label(chain, address) or {}
    return str(row.get("class") or "").strip()


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    chain = str(row.get("chain") or "").strip().lower()
    address = norm(row.get("address"))
    wallet_type = row_type(row)
    current = global_address_label(chain, address) or {}

    if chain not in SUPPORTED_CHAINS:
        return {"status": "rejected", "reason": "unsupported_chain", "current_class": current.get("class", "")}
    if not is_address(address):
        return {"status": "rejected", "reason": "invalid_address", "current_class": current.get("class", "")}
    if current.get("class"):
        return {"status": "already_configured", "reason": "address_already_labeled", "current_class": current.get("class", "")}
    if wallet_type not in {"deposit", "deposit_wallet", "deposit_funder", "sweep_wallet"}:
        return {"status": "rejected", "reason": "unsupported_wallet_type", "current_class": current.get("class", "")}
    if confidence(row) not in {"high", "medium"}:
        return {"status": "rejected", "reason": "confidence_too_low", "current_class": current.get("class", "")}

    raw_paths = sweep_paths(row)
    if native_asset_only(row, raw_paths):
        return {"status": "needs_manual_review", "reason": "native_asset_only", "current_class": ""}

    paths = [path for path in raw_paths if outbound_sweep_path(path)]
    targets = [target_address(path) for path in paths]
    targets = [target for target in targets if target]
    tx_hashes = {path_tx_hash(path) for path in paths if path_tx_hash(path)}
    counts = Counter(targets)
    if not counts:
        return {"status": "needs_manual_review", "reason": "missing_sweep_target", "current_class": ""}

    best_target, best_count = counts.most_common(1)[0]
    best_class = target_class(chain, best_target)
    best_exchange = target_exchange(chain, best_target)
    source_exchange = str(row.get("exchange") or "").strip()
    same_exchange = not source_exchange or not best_exchange or source_exchange.lower() == best_exchange.lower()
    if best_class != "cex_hot_wallet":
        return {
            "status": "needs_manual_review",
            "reason": "target_not_known_cex_hot_wallet",
            "current_class": "",
            "sweep_target": best_target,
            "sweep_target_class": best_class,
            "sweep_tx_count": best_count,
        }
    if best_count < MIN_SWEEP_TXS or len(tx_hashes) < MIN_SWEEP_TXS:
        return {
            "status": "needs_manual_review",
            "reason": "insufficient_distinct_sweep_txs",
            "current_class": "",
            "sweep_target": best_target,
            "sweep_target_class": best_class,
            "sweep_tx_count": best_count,
            "distinct_tx_count": len(tx_hashes),
        }
    if not same_exchange:
        return {
            "status": "needs_manual_review",
            "reason": "exchange_mismatch_with_hot_wallet",
            "current_class": "",
            "sweep_target": best_target,
            "sweep_target_class": best_class,
            "sweep_target_exchange": best_exchange,
            "sweep_tx_count": best_count,
        }

    return {
        "status": "accepted_candidate",
        "reason": "sweeps_to_known_cex_hot_wallet",
        "class": "cex_deposit",
        "current_class": "",
        "sweep_target": best_target,
        "sweep_target_class": best_class,
        "sweep_target_exchange": best_exchange,
        "sweep_tx_count": best_count,
        "distinct_tx_count": len(tx_hashes),
    }


def proposal(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("status") != "accepted_candidate":
        return None
    exchange = str(row.get("exchange") or result.get("sweep_target_exchange") or "Unknown CEX").strip()
    return {
        "address": norm(row.get("address")),
        "label": f"{exchange} Deposit/Sweep Wallet",
        "class": "cex_deposit",
        "exchange": exchange,
        "evidence": (
            f"{datetime.now(timezone.utc).date()} sweep-pattern review: "
            f"{result.get('sweep_tx_count')} distinct paths to known CEX hot wallet "
            f"{result.get('sweep_target')}. Treat as pending sell / MM inventory, not confirmed DEX sell."
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
            "asset_type": row_asset_type(row),
            "confidence": confidence(row),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "class": result.get("class", ""),
            "current_class": result.get("current_class", ""),
            "sweep_target": result.get("sweep_target", ""),
            "sweep_target_class": result.get("sweep_target_class", ""),
            "sweep_tx_count": result.get("sweep_tx_count", 0),
            "distinct_tx_count": result.get("distinct_tx_count", 0),
        }
        reviewed.append(item)
        if candidate := proposal(row, result):
            proposals.append(candidate)
    counts: dict[str, int] = {}
    for item in reviewed:
        status = str(item.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema": "cex_sweep_pattern_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(path),
        "min_sweep_txs": MIN_SWEEP_TXS,
        "counts": counts,
        "reviewed": reviewed,
        "label_proposals": proposals,
    }


def markdown(review: dict[str, Any]) -> str:
    lines = [
        "# CEX Sweep Pattern Review",
        "",
        f"Source: `{review['source_file']}`",
        f"Generated: `{review['generated_at']}`",
        f"Minimum distinct sweep txs: `{review['min_sweep_txs']}`",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(review["counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| # | Exchange | Address | Type | Status | Reason | Target | Sweep txs |",
            "| ---: | --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for item in review["reviewed"]:
        address = str(item["address"])
        target = str(item.get("sweep_target") or "")
        short = f"{address[:10]}...{address[-6:]}" if len(address) > 18 else address
        target_short = f"{target[:10]}...{target[-6:]}" if len(target) > 18 else target
        lines.append(
            f"| {item['index']} | {item['exchange']} | `{short}` | {item['type']} | "
            f"{item['status']} | {item['reason']} | `{target_short}` | {item['sweep_tx_count']} |"
        )
    lines.extend(["", "## Label Proposals", ""])
    if not review["label_proposals"]:
        lines.append("No sweep-derived label proposals.")
    else:
        lines.append("```json")
        lines.append(json.dumps(review["label_proposals"], ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_review(review: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    md_path = out_dir / "latest.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(review), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Review CEX deposit/sweep evidence without modifying global labels.")
    parser.add_argument("--input", required=True, type=Path, help="JSON array of CEX sweep-pattern evidence")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    review = build_review(args.input)
    json_path, md_path = write_review(review, args.out_dir)
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
