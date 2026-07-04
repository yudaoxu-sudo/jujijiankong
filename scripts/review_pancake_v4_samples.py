#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import get_transaction_receipt, hex_to_int, rpc_call


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_samples" / "external_review"
DEFAULT_ROUTER = "0xd9c500dff816a1da21a48a732d3498bf09dc9aeb"
TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def tx_hashes_from_text(text: str) -> list[str]:
    return [norm(match.group(0)) for match in TX_HASH_RE.finditer(text or "")]


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("input JSON must be an array")
    return [row for row in payload if isinstance(row, dict)]


def row_tx_hash(row: dict[str, Any]) -> str:
    return norm(row.get("tx_hash") or row.get("hash") or row.get("tx"))


def status_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = norm(value)
    if text in {"success", "succeeded", "1", "true"}:
        return 1
    if text in {"failed", "fail", "0", "false"}:
        return 0
    return None


def transfer_tokens(receipt: dict[str, Any]) -> list[str]:
    return sorted({norm(log.get("address")) for log in receipt.get("logs", []) if log.get("address")})


def review_row(chain: str, row: dict[str, Any], router: str) -> dict[str, Any]:
    tx_hash = row_tx_hash(row)
    if not tx_hash:
        return {"tx_hash": "", "status": "rejected", "reason": "missing_tx_hash", "source": row}
    tx = rpc_call(chain, "eth_getTransactionByHash", [tx_hash])
    receipt = get_transaction_receipt(chain, tx_hash)
    chain_to = norm((tx or {}).get("to"))
    chain_selector = str((tx or {}).get("input") or "")[:10]
    chain_status = hex_to_int(receipt.get("status"))
    claimed_selector = norm(row.get("selector"))
    claimed_status = status_int(row.get("status"))
    claimed_block = int(row["block"]) if str(row.get("block") or "").isdigit() else None
    block_number = hex_to_int((tx or {}).get("blockNumber"))
    problems = []
    if chain_to != router:
        problems.append("tx_to_not_universal_router")
    if claimed_selector and claimed_selector != chain_selector:
        problems.append("selector_mismatch")
    if claimed_status is not None and claimed_status != chain_status:
        problems.append("status_mismatch")
    if claimed_block is not None and claimed_block != block_number:
        problems.append("block_mismatch")

    reviewed = {
        "tx_hash": tx_hash,
        "claimed_symbol": row.get("symbol", ""),
        "claimed_side": row.get("side", ""),
        "claimed_status": row.get("status", ""),
        "block_number": block_number,
        "transaction_index": hex_to_int((tx or {}).get("transactionIndex")),
        "tx_to": chain_to,
        "selector": chain_selector,
        "status_int": chain_status,
        "is_universal_router": chain_to == router,
        "log_count": len(receipt.get("logs", [])),
        "transfer_tokens": transfer_tokens(receipt),
        "problems": problems,
    }
    reviewed["status"] = "accepted" if not problems else "rejected"
    reviewed["reason"] = "rpc_matches_claims" if not problems else ",".join(problems)
    return reviewed


def build_review(chain: str, input_path: Path, extra_text_path: Path | None, router: str) -> dict[str, Any]:
    rows = load_rows(input_path)
    known = {row_tx_hash(row) for row in rows}
    if extra_text_path:
        for tx_hash in tx_hashes_from_text(extra_text_path.read_text(encoding="utf-8", errors="ignore")):
            if tx_hash not in known:
                rows.append({"tx_hash": tx_hash, "source": "extra_text"})
                known.add(tx_hash)
    reviewed = [review_row(chain, row, router) for row in rows]
    counts: dict[str, int] = {}
    for row in reviewed:
        status = str(row.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema": "pancake_v4_external_sample_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain": chain,
        "universal_router": router,
        "input_file": str(input_path),
        "extra_text_file": str(extra_text_path or ""),
        "counts": counts,
        "reviewed": reviewed,
    }


def markdown(review: dict[str, Any]) -> str:
    lines = [
        "# Pancake v4 External Sample Review",
        "",
        f"Input: `{review['input_file']}`",
        f"Generated: `{review['generated_at']}`",
        f"Universal Router: `{review['universal_router']}`",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(review["counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Rows", "", "| Tx | Claimed | Chain Status | Router | Selector | Verdict | Reason |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in review["reviewed"]:
        tx = str(row.get("tx_hash") or "")
        short = f"{tx[:10]}...{tx[-6:]}" if len(tx) > 18 else tx
        claimed = f"{row.get('claimed_symbol', '')} {row.get('claimed_side', '')} {row.get('claimed_status', '')}".strip()
        router = "yes" if row.get("is_universal_router") else "no"
        lines.append(
            f"| `{short}` | {claimed} | {row.get('status_int')} | {router} | `{row.get('selector', '')}` | "
            f"{row.get('status')} | {row.get('reason')} |"
        )
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
    parser = argparse.ArgumentParser(description="Review external Pancake v4 / Infinity sample JSON against RPC truth.")
    parser.add_argument("--chain", default="bsc", choices=["bsc"], help="EVM chain")
    parser.add_argument("--input", required=True, type=Path, help="External JSON array")
    parser.add_argument("--extra-text", type=Path, help="Optional text file containing more tx hashes")
    parser.add_argument("--router", default=DEFAULT_ROUTER, help="Expected Universal Router address")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    args = parser.parse_args()
    review = build_review(args.chain, args.input, args.extra_text, norm(args.router))
    json_path, md_path = write_review(review, args.out_dir)
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
