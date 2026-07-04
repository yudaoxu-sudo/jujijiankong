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


OUT_DIR = ROOT / "output" / "alpha_trace_samples"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def is_tx_hash(value: str) -> bool:
    text = norm(value)
    return len(text) == 66 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def tx_hashes_from_text(text: str) -> list[str]:
    return [norm(match.group(0)) for match in TX_HASH_RE.finditer(text or "")]


def topic_addr(topic: Any) -> str:
    text = norm(topic)
    raw = strip0x(text)
    if len(raw) < 40:
        return ""
    return "0x" + raw[-40:]


def uint_hex(value: Any) -> int:
    text = str(value or "0x0")
    return int(text, 16)


def compact_tx(tx: dict[str, Any] | None) -> dict[str, Any]:
    if not tx:
        return {}
    keys = ["hash", "blockNumber", "transactionIndex", "from", "to", "value", "gas", "gasPrice", "input"]
    return {key: tx.get(key) for key in keys if key in tx}


def compact_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_number": hex_to_int(receipt.get("blockNumber")),
        "tx_index": hex_to_int(receipt.get("transactionIndex")),
        "status": hex_to_int(receipt.get("status")),
        "from": receipt.get("from"),
        "to": receipt.get("to"),
        "gas_used": hex_to_int(receipt.get("gasUsed")),
        "effective_gas_price": hex_to_int(receipt.get("effectiveGasPrice")),
        "log_count": len(receipt.get("logs", [])),
    }


def parse_transfer_logs(receipt: dict[str, Any], tx_hash: str) -> list[dict[str, str]]:
    rows = []
    for log in receipt.get("logs", []):
        topics = log.get("topics") or []
        if len(topics) < 3 or norm(topics[0]) != TRANSFER_TOPIC:
            continue
        rows.append(
            {
                "token": norm(log.get("address")),
                "from": topic_addr(topics[1]),
                "to": topic_addr(topics[2]),
                "amount": str(uint_hex(log.get("data"))),
                "rawAmount": str(uint_hex(log.get("data"))),
                "tx": norm(tx_hash),
                "logIndex": str(hex_to_int(log.get("logIndex"))),
                "source": "receipt_log",
            }
        )
    return rows


def call_edges_from_call_tracer(trace: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        from_addr = norm(node.get("from"))
        to_addr = norm(node.get("to"))
        if from_addr.startswith("0x") and to_addr.startswith("0x") and len(from_addr) == 42 and len(to_addr) == 42:
            key = (from_addr, to_addr)
            if key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "from": from_addr,
                        "to": to_addr,
                        "type": str(node.get("type") or "CALL"),
                        "value": str(node.get("value") or "0x0"),
                        "source": "debug_callTracer",
                    }
                )
        for child in node.get("calls") or []:
            visit(child)

    visit(trace)
    return rows


def call_edges_from_trace_transaction(trace_rows: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set()
    if not isinstance(trace_rows, list):
        return rows
    for row in trace_rows:
        action = row.get("action") if isinstance(row, dict) else {}
        if not isinstance(action, dict):
            continue
        from_addr = norm(action.get("from"))
        to_addr = norm(action.get("to"))
        if from_addr.startswith("0x") and to_addr.startswith("0x") and len(from_addr) == 42 and len(to_addr) == 42:
            key = (from_addr, to_addr)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "from": from_addr,
                    "to": to_addr,
                    "type": str(action.get("callType") or row.get("type") or "call"),
                    "value": str(action.get("value") or "0x0"),
                    "source": "trace_transaction",
                }
            )
    return rows


def try_rpc(chain: str, method: str, params: list[Any]) -> tuple[str, Any]:
    try:
        return "ok", rpc_call(chain, method, params)
    except Exception as exc:
        return "error", str(exc)


def collect_debug_calls(chain: str, tx_hash: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    calls: list[dict[str, str]] = []
    debug_status, debug_result = try_rpc(chain, "debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    meta: dict[str, Any] = {"debug_traceTransaction": debug_status}
    if debug_status == "ok":
        calls.extend(call_edges_from_call_tracer(debug_result))
        meta["debug_call_count"] = len(calls)
    else:
        meta["debug_error"] = str(debug_result)

    trace_status, trace_result = try_rpc(chain, "trace_transaction", [tx_hash])
    meta["trace_transaction"] = trace_status
    if trace_status == "ok":
        trace_calls = call_edges_from_trace_transaction(trace_result)
        seen = {(row["from"], row["to"], row.get("source")) for row in calls}
        for row in trace_calls:
            key = (row["from"], row["to"], row.get("source"))
            if key not in seen:
                calls.append(row)
                seen.add(key)
        meta["trace_call_count"] = len(trace_calls)
    else:
        meta["trace_error"] = str(trace_result)
    return calls, meta


def build_bundle(chain: str, tx_hash: str, tx: dict[str, Any] | None, receipt: dict[str, Any], include_debug: bool) -> dict[str, Any]:
    calls: list[dict[str, str]] = []
    trace_meta: dict[str, Any] = {"debug_requested": include_debug}
    if include_debug:
        calls, trace_meta = collect_debug_calls(chain, tx_hash)
        trace_meta["debug_requested"] = True
    return {
        "schema": "alpha_trace_bundle.v1",
        "chain": chain,
        "tx_hash": norm(tx_hash),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transaction": compact_tx(tx),
        "receipt_summary": compact_receipt(receipt),
        "transfers": parse_transfer_logs(receipt, tx_hash),
        "calls": calls,
        "trace_meta": trace_meta,
        "verifier_hint": "Pass this file to scripts/verify_alpha_aggregator_trace.py as --input or --history.",
    }


def tx_hashes_from_args(values: list[str], file_path: Path | None) -> list[str]:
    out = []
    for value in values:
        clean = norm(value)
        if not clean:
            continue
        extracted = tx_hashes_from_text(clean)
        if extracted:
            out.extend(extracted)
            continue
        out.append(clean)
    if file_path:
        out.extend(tx_hashes_from_text(file_path.read_text(encoding="utf-8")))
    deduped = []
    for tx_hash in out:
        if not is_tx_hash(tx_hash):
            raise SystemExit(f"invalid tx hash: {tx_hash}")
        if tx_hash not in deduped:
            deduped.append(tx_hash)
    return deduped


def write_bundle(out_dir: Path, bundle: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    block = bundle.get("receipt_summary", {}).get("block_number") or "unknown"
    tx_index = bundle.get("receipt_summary", {}).get("tx_index")
    tx_hash = str(bundle.get("tx_hash", "tx"))
    suffix = tx_hash[:10]
    name = f"{bundle['chain']}_{block}_{tx_index}_{suffix}.json"
    path = out_dir / name
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a read-only Alpha swap trace bundle for aggregator verification.")
    parser.add_argument("--chain", default="bsc", choices=["bsc", "base"], help="EVM chain")
    parser.add_argument("--tx", action="append", default=[], help="Transaction hash; repeatable")
    parser.add_argument("--tx-file", type=Path, help="File containing one tx hash per line")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="Output directory")
    parser.add_argument("--no-debug", action="store_true", help="Only collect tx receipt and Transfer logs")
    args = parser.parse_args()

    tx_hashes = tx_hashes_from_args(args.tx, args.tx_file)
    if not tx_hashes:
        raise SystemExit("provide at least one --tx or --tx-file")

    written = []
    for tx_hash in tx_hashes:
        tx = rpc_call(args.chain, "eth_getTransactionByHash", [tx_hash])
        receipt = get_transaction_receipt(args.chain, tx_hash)
        bundle = build_bundle(args.chain, tx_hash, tx, receipt, include_debug=not args.no_debug)
        path = write_bundle(args.out_dir, bundle)
        written.append(str(path))
        print(path)
    summary = {
        "written": written,
        "count": len(written),
        "next_step": "Run verify_alpha_aggregator_trace.py with one file as --input and 2+ other token files as --history.",
    }
    (args.out_dir / "latest_collection_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
