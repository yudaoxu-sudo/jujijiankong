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

from scripts.collect_alpha_trace_bundle import build_bundle, tx_hashes_from_args, write_bundle
from scripts.review_alpha_swap_samples import build_review, markdown
from sniper_engine.rpc import get_transaction_receipt, rpc_call


DEFAULT_OUT_ROOT = ROOT / "output" / "alpha_trace_samples" / "tx_review"


def slug_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_bundles(chain: str, tx_hashes: list[str], out_dir: Path, include_debug: bool) -> list[Path]:
    written = []
    for tx_hash in tx_hashes:
        tx = rpc_call(chain, "eth_getTransactionByHash", [tx_hash])
        receipt = get_transaction_receipt(chain, tx_hash)
        bundle = build_bundle(chain, tx_hash, tx, receipt, include_debug=include_debug)
        written.append(write_bundle(out_dir, bundle))
    summary = {
        "schema": "alpha_tx_review_collection.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain": chain,
        "count": len(written),
        "written": [str(path) for path in written],
    }
    (out_dir / "latest_collection_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return written


def write_review(review: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "latest.json"
    md_path = out_dir / "latest.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(review), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and review Binance Alpha swap tx hashes in one read-only command.")
    parser.add_argument("--chain", default="bsc", choices=["bsc", "base"], help="EVM chain")
    parser.add_argument("--tx", action="append", default=[], help="Transaction hash; repeatable")
    parser.add_argument("--tx-file", type=Path, help="File containing one tx hash per line")
    parser.add_argument("--address", action="append", default=[], help="Address to review; repeatable. If omitted, review cross-token addresses.")
    parser.add_argument("--quote", default="0x55d398326f99059ff775485246999027b3197955", help="Quote token to exclude")
    parser.add_argument("--min-tokens", type=int, default=3, help="Minimum distinct Alpha tokens for auto-selected addresses")
    parser.add_argument("--out-dir", type=Path, help="Output directory. Defaults to a UTC timestamped folder.")
    parser.add_argument("--no-debug", action="store_true", help="Only collect tx receipt and Transfer logs")
    args = parser.parse_args()

    tx_hashes = tx_hashes_from_args(args.tx, args.tx_file)
    if not tx_hashes:
        raise SystemExit("provide at least one --tx or --tx-file")
    out_dir = args.out_dir or (DEFAULT_OUT_ROOT / slug_now())
    bundle_dir = out_dir / "bundles"
    review_dir = out_dir / "review"
    bundle_paths = collect_bundles(args.chain, tx_hashes, bundle_dir, include_debug=not args.no_debug)
    review = build_review(args.chain, bundle_paths, args.address, args.quote, args.min_tokens)
    json_path, md_path = write_review(review, review_dir)
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
