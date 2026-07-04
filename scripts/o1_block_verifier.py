#!/usr/bin/env python3
from __future__ import annotations

import csv
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import get_block_by_number, get_transaction_receipt, hex_to_int, rpc_call


CHAIN = "bsc"
BLOCK_NUMBER = 104769548
FAILED_BRIBE_TX = "0x19fabd65d1106ae7816e119342058404732098fbaab7fdf2d938ed2b9bf1bcc3"
OUT_DIR = ROOT / "output" / "o1_block_verifier"
FOCUS_TX_INDEXES = set(
    list(range(10, 26))
    + [37]
)

SELECTOR_LABELS = {
    "0x095ea7b3": "approve",
    "0x414bf389": "exactInputSingle",
    "0x04e45aaf": "exactInputSingle",
    "0x5023b4df": "mint/addLiquidity",
    "0x88316456": "mint",
    "0x72026aa8": "unknown_failed_sniper_method",
    "0x38ed1739": "swapExactTokensForTokens",
    "0x7ff36ab5": "swapExactETHForTokens",
    "0x18cbafe5": "swapExactTokensForETH",
}


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    block = get_block_by_number(CHAIN, BLOCK_NUMBER, full_transactions=True)
    txs = block.get("transactions", [])
    receipts = []
    rows = []

    for idx, tx in enumerate(txs):
        if not args.full and idx not in FOCUS_TX_INDEXES:
            continue
        tx_hash = tx["hash"]
        receipt = get_transaction_receipt(CHAIN, tx_hash)
        receipts.append(receipt)
        selector = (tx.get("input") or "0x")[:10]
        status = receipt.get("status")
        row = {
            "tx_index": str(idx),
            "tx_hash": tx_hash,
            "status": status_label(status),
            "from": tx.get("from", ""),
            "to": tx.get("to") or "",
            "value_bnb": wei_hex_to_bnb(tx.get("value")),
            "gas": str(hex_to_int(tx.get("gas")) or ""),
            "gas_price_gwei": wei_hex_to_gwei(tx.get("gasPrice")),
            "selector": selector,
            "selector_label": SELECTOR_LABELS.get(selector, ""),
            "is_failed_bribe_tx": "yes" if tx_hash.lower() == FAILED_BRIBE_TX.lower() else "no",
            "logs_count": str(len(receipt.get("logs", []))),
        }
        rows.append(row)

    internal_result = fetch_internal_tx(FAILED_BRIBE_TX)

    write_json(OUT_DIR / "block.json", block)
    write_json(OUT_DIR / "receipts.json", receipts)
    write_json(OUT_DIR / "failed_bribe_internal.json", internal_result)
    write_csv(OUT_DIR / "block_transactions.csv", rows)
    (OUT_DIR / "o1_block_report.md").write_text(
        render_report(block, rows, internal_result, full=args.full),
        encoding="utf-8",
    )
    print(OUT_DIR / "o1_block_report.md")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify O1 opening block ordering.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Fetch receipts for every transaction in the block. Default only fetches known O1-relevant tx indexes.",
    )
    return parser.parse_args()


def fetch_internal_tx(tx_hash: str) -> dict[str, Any]:
    nodereal_error = ""
    if os.environ.get("NODEREAL_API_KEY"):
        try:
            result = rpc_call(
                CHAIN,
                "nr_getAssetTransfers",
                [
                    {
                        "category": ["internal"],
                        "transactionHash": tx_hash,
                        "order": "asc",
                        "maxCount": "0x64",
                    }
                ],
            )
            return {
                "status": "ok",
                "source": "NodeReal nr_getAssetTransfers",
                "message": "Fetched internal transfers from NodeReal enhanced API.",
                "tx_hash": tx_hash,
                "result": result,
            }
        except Exception as exc:
            nodereal_error = str(exc)

    api_key = os.environ.get("BSCSCAN_API_KEY") or os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        return {
            "status": "missing_api_key",
            "source": "Etherscan V2 txlistinternal",
            "message": nodereal_error
            or "Set BSCSCAN_API_KEY or ETHERSCAN_API_KEY with BSC/Etherscan V2 chain coverage to fetch internal transactions.",
            "tx_hash": tx_hash,
        }

    params = urllib.parse.urlencode(
        {
            "chainid": "56",
            "module": "account",
            "action": "txlistinternal",
            "txhash": tx_hash,
            "apikey": api_key,
        }
    )
    url = f"https://api.etherscan.io/v2/api?{params}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except Exception as exc:
        return {
            "status": "request_failed",
            "source": "Etherscan V2 txlistinternal",
            "message": str(exc),
            "tx_hash": tx_hash,
        }


def render_report(
    block: dict[str, Any],
    rows: list[dict[str, str]],
    internal_result: dict[str, Any],
    full: bool,
) -> str:
    failed_row = next((row for row in rows if row["is_failed_bribe_tx"] == "yes"), None)
    interesting = [
        row
        for row in rows
        if row["is_failed_bribe_tx"] == "yes"
        or row["status"] == "failed"
        or row["selector_label"]
        or 10 <= int(row["tx_index"]) <= 25
    ]

    lines = [
        "# O1 Block Verifier",
        "",
        f"- chain: `{CHAIN}`",
        f"- block: `{BLOCK_NUMBER}`",
        f"- block tx count: `{len(block.get('transactions', []))}`",
        f"- fetched receipt count: `{len(rows)}`",
        f"- block hash: `{block.get('hash')}`",
        f"- receipt mode: `{'full' if full else 'focus'}`",
        f"- failed bribe tx: `{FAILED_BRIBE_TX}`",
        "",
        "## Key Result",
        "",
    ]
    if failed_row:
        lines.extend(
            [
                f"- failed bribe tx index: `{failed_row['tx_index']}`",
                f"- failed bribe tx status: `{failed_row['status']}`",
                f"- failed bribe method selector: `{failed_row['selector']}`",
                f"- failed bribe from: `{failed_row['from']}`",
                f"- failed bribe to: `{failed_row['to']}`",
            ]
        )
    else:
        lines.append("- failed bribe tx not found in this block")

    transfers = internal_transfers(internal_result)
    largest_bnb_transfer = largest_internal_bnb_transfer(transfers)
    if largest_bnb_transfer:
        lines.extend(
            [
                f"- largest internal BNB transfer: `{internal_value_to_bnb(largest_bnb_transfer.get('value'))} BNB`",
                f"- largest internal transfer to: `{largest_bnb_transfer.get('to')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Internal Transaction Status",
            "",
            f"- status: `{internal_result.get('status')}`",
            f"- source: `{internal_result.get('source')}`",
            f"- message: `{internal_result.get('message')}`",
        ]
    )
    lines.append(f"- internal rows: `{len(transfers)}`")

    if transfers:
        lines.extend(
            [
                "",
                "## Internal Transfers",
                "",
                "| category | asset | from | to | value BNB | receiptStatus |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for transfer in transfers[:20]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(transfer.get("category", "")),
                        str(transfer.get("asset", "")),
                        short_addr(str(transfer.get("from", ""))),
                        short_addr(str(transfer.get("to", ""))),
                        internal_value_to_bnb(transfer.get("value")),
                        str(transfer.get("receiptsStatus", "")),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Interesting Block Rows",
            "",
            "| txIndex | status | selector | label | tx | from | to | value BNB | gasPrice gwei |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in interesting[:80]:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["tx_index"],
                    row["status"],
                    row["selector"],
                    row["selector_label"],
                    short_hash(row["tx_hash"]),
                    short_addr(row["from"]),
                    short_addr(row["to"]),
                    row["value_bnb"],
                    row["gas_price_gwei"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- CSV: `{(OUT_DIR / 'block_transactions.csv')}`",
            f"- block JSON: `{(OUT_DIR / 'block.json')}`",
            f"- receipts JSON: `{(OUT_DIR / 'receipts.json')}`",
            f"- internal JSON: `{(OUT_DIR / 'failed_bribe_internal.json')}`",
            "",
            "## Next Checks",
            "",
            "- Map PancakeSwap router/position manager addresses to labels.",
            "- Decode mint/swap calldata to recover token pair, amount, and LP position.",
            "- Join this block view with token holder changes after the block.",
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def status_label(status_hex: str | None) -> str:
    if status_hex == "0x1":
        return "success"
    if status_hex == "0x0":
        return "failed"
    return status_hex or ""


def wei_hex_to_bnb(value: str | None) -> str:
    amount = hex_to_int(value) or 0
    if amount == 0:
        return "0"
    return f"{amount / 10**18:.12f}".rstrip("0").rstrip(".")


def wei_hex_to_gwei(value: str | None) -> str:
    amount = hex_to_int(value)
    if amount is None:
        return ""
    return f"{amount / 10**9:.6f}".rstrip("0").rstrip(".")


def internal_transfers(internal_result: dict[str, Any]) -> list[dict[str, Any]]:
    result = internal_result.get("result")
    if isinstance(result, dict) and isinstance(result.get("transfers"), list):
        return result["transfers"]
    if isinstance(result, list):
        return result
    return []


def largest_internal_bnb_transfer(transfers: list[dict[str, Any]]) -> dict[str, Any] | None:
    bnb_transfers = [
        transfer
        for transfer in transfers
        if str(transfer.get("asset", "")).upper() in {"BNB", ""}
    ]
    if not bnb_transfers:
        return None
    return max(bnb_transfers, key=lambda transfer: internal_value_to_wei(transfer.get("value")))


def internal_value_to_bnb(value: Any) -> str:
    amount = internal_value_to_wei(value)
    if amount == 0:
        return "0"
    return f"{amount / 10**18:.12f}".rstrip("0").rstrip(".")


def internal_value_to_wei(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, int):
        return value
    text = str(value)
    if text.startswith("0x"):
        return int(text, 16)
    return int(text)


def short_hash(value: str) -> str:
    if len(value) <= 18:
        return value
    return f"{value[:10]}...{value[-6:]}"


def short_addr(value: str) -> str:
    if not value:
        return ""
    return f"{value[:8]}...{value[-6:]}"


if __name__ == "__main__":
    raise SystemExit(main())
