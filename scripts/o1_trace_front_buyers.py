#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from decimal import Decimal, getcontext
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import rpc_call


getcontext().prec = 80

O_TOKEN = "0x500a02a20b0b0a3f3efccfc0559543f5743bd1c4"
POOL = "0x1a9b68ca1dcacb106c4b853e2d9c915f0cfe2e56"
OPENING_BLOCK = 104769548
MAX_TRANSFER_BLOCK_SPAN = 100_000
SWAPS_CSV = ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv"
MONITORING_FULL = ROOT / "output" / "hertzflow_o1" / "monitoring" / "monitoring_wallets_full.json"
OUT_DIR = ROOT / "output" / "o1_front_buyers_trace"


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def decimal_amount(raw: int, decimals: int = 18) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def fmt_dec(value: Decimal, places: int = 6) -> str:
    quant = Decimal(10) ** -places
    return f"{value.quantize(quant):f}"


def load_swaps() -> list[dict[str, str]]:
    with SWAPS_CSV.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_monitor_labels() -> dict[str, dict[str, str]]:
    if not MONITORING_FULL.exists():
        return {}
    payload = json.loads(MONITORING_FULL.read_text(encoding="utf-8"))
    labels: dict[str, dict[str, str]] = {}
    for row in payload.get("addresses", []):
        labels[norm(row.get("address"))] = {
            "label": row.get("label", ""),
            "role": row.get("role", ""),
            "level": row.get("monitor_level", ""),
        }
    return labels


def encode_balance_of(addr: str) -> str:
    return "0x70a08231" + "0" * 24 + norm(addr)[2:]


def current_balance(addr: str) -> Decimal:
    result = rpc_call("bsc", "eth_call", [{"to": O_TOKEN, "data": encode_balance_of(addr)}, "latest"])
    return decimal_amount(int(result, 16))


def latest_block() -> int:
    return int(rpc_call("bsc", "eth_blockNumber", []), 16)


def get_outgoing_o(addr: str) -> list[dict[str, Any]]:
    transfers: list[dict[str, Any]] = []
    chain_tip = latest_block()
    start = OPENING_BLOCK
    while start <= chain_tip:
        end = min(start + MAX_TRANSFER_BLOCK_SPAN, chain_tip)
        page_key = ""
        while True:
            query: dict[str, Any] = {
                "category": ["20"],
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "contractAddresses": [O_TOKEN],
                "fromAddress": addr,
                "order": "asc",
                "maxCount": "0x3e8",
            }
            if page_key:
                query["pageKey"] = page_key
            result = rpc_call("bsc", "nr_getAssetTransfers", [query])
            if isinstance(result, dict):
                transfers.extend(result.get("transfers", []))
                page_key = result.get("pageKey") or result.get("PageKey") or ""
            else:
                page_key = ""
            if not page_key:
                break
        start = end + 1
    return [row for row in transfers if norm(row.get("from")) == norm(addr) and norm(row.get("contractAddress")) == O_TOKEN]


def transfer_amount(row: dict[str, Any]) -> Decimal:
    value = row.get("value") or "0x0"
    return decimal_amount(int(value, 16))


def summarize_row(swap: dict[str, str], labels: dict[str, dict[str, str]]) -> dict[str, str]:
    buyer = norm(swap["buyer"])
    bought_o = Decimal(swap["o_out"])
    spent_usdt = Decimal(swap["usdt_in"])
    avg_price = Decimal(swap["avg_price_usdt_per_o"])
    label = labels.get(buyer, {})

    balance = current_balance(buyer)
    outgoing = get_outgoing_o(buyer)
    total_out = sum((transfer_amount(row) for row in outgoing), Decimal(0))
    out_pct = (total_out / bought_o * Decimal(100)) if bought_o else Decimal(0)

    first = outgoing[0] if outgoing else {}
    first_to = norm(first.get("to"))
    first_to_label = "pool" if first_to == POOL else ""
    if first_to == buyer:
        first_to_label = "self"

    status = "held_or_accumulated"
    if total_out > 0 and balance <= bought_o * Decimal("0.05"):
        status = "mostly_exited_or_transferred"
    elif total_out > 0:
        status = "partially_moved"

    return {
        "buyer": buyer,
        "monitoring_label": label.get("label", swap.get("monitoring_label", "")),
        "monitoring_role": label.get("role", ""),
        "monitoring_level": label.get("level", ""),
        "buy_tx_index": swap["tx_index"],
        "spent_usdt": str(spent_usdt),
        "bought_o": str(bought_o),
        "avg_price_usdt_per_o": str(avg_price),
        "current_o_balance": str(balance),
        "outgoing_o_after_open": str(total_out),
        "out_pct_of_bought": str(out_pct),
        "outgoing_transfer_count": str(len(outgoing)),
        "first_out_block": first.get("blockNum", ""),
        "first_out_to": first_to,
        "first_out_to_label": first_to_label,
        "first_out_hash": first.get("hash", ""),
        "status": status,
    }


def build_report(rows: list[dict[str, str]]) -> str:
    lines = [
        "# O1 Front Buyer Trace",
        "",
        "## Summary",
        "",
    ]
    exited = [row for row in rows if row["status"] == "mostly_exited_or_transferred"]
    moved = [row for row in rows if row["status"] == "partially_moved"]
    held = [row for row in rows if row["status"] == "held_or_accumulated"]
    lines.append(f"- buyers traced: `{len(rows)}`")
    lines.append(f"- mostly exited or transferred: `{len(exited)}`")
    lines.append(f"- partially moved: `{len(moved)}`")
    lines.append(f"- held or accumulated: `{len(held)}`")
    lines.append("")
    lines.append("## Buyers")
    lines.append("")
    lines.append("| buyer | label | bought O | current O | outgoing O | out % | transfers | status | first out |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for row in rows:
        first_out = row["first_out_hash"]
        if first_out:
            first_out = f"`{first_out}` -> `{row['first_out_to']}` {row['first_out_to_label']}"
        lines.append(
            f"| `{row['buyer']}` | {row['monitoring_label']} | "
            f"{fmt_dec(Decimal(row['bought_o']), 6)} | {fmt_dec(Decimal(row['current_o_balance']), 6)} | "
            f"{fmt_dec(Decimal(row['outgoing_o_after_open']), 6)} | {fmt_dec(Decimal(row['out_pct_of_bought']), 2)}% | "
            f"{row['outgoing_transfer_count']} | `{row['status']}` | {first_out} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    swaps = load_swaps()
    labels = load_monitor_labels()
    rows = [summarize_row(swap, labels) for swap in swaps]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "front_buyers_trace.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (OUT_DIR / "front_buyers_trace.md").write_text(build_report(rows), encoding="utf-8")
    print(OUT_DIR / "front_buyers_trace.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
