#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any


getcontext().prec = 80

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import get_transaction_receipt, hex_to_int, rpc_call


OUT_DIR = ROOT / "output" / "pancake_pool_tx"
QUOTE_SYMBOLS = {"USDT", "USDC", "BUSD", "FDUSD"}
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def norm(value: str | None) -> str:
    return (value or "").lower()


def words(data: str) -> list[str]:
    raw = strip0x(data or "0x")
    return ["0x" + raw[i : i + 64] for i in range(0, len(raw), 64) if raw[i : i + 64]]


def uint(word: str) -> int:
    return int(strip0x(word), 16)


def sint(word: str, bits: int = 256) -> int:
    value = uint(word)
    sign = 1 << (bits - 1)
    mask = 1 << bits
    return value - mask if value & sign else value


def topic_addr(topic: str) -> str:
    return "0x" + strip0x(topic)[-40:].lower()


def decode_abi_string(data: str) -> str:
    if not data or data == "0x":
        return ""
    raw = strip0x(data)
    try:
        if len(raw) >= 128 and int(raw[:64], 16) == 32:
            size = int(raw[64:128], 16)
            payload = raw[128 : 128 + size * 2]
            return bytes.fromhex(payload).decode("utf-8", errors="ignore").strip("\x00")
        if len(raw) == 64:
            return bytes.fromhex(raw).decode("utf-8", errors="ignore").strip("\x00")
    except Exception:
        return ""
    return ""


def erc20_call(chain: str, address: str, selector: str) -> str:
    return rpc_call(chain, "eth_call", [{"to": address, "data": selector}, "latest"]) or "0x"


def token_meta(chain: str, address: str) -> dict[str, Any]:
    symbol = ""
    name = ""
    decimals = None
    try:
        symbol = decode_abi_string(erc20_call(chain, address, "0x95d89b41"))
    except Exception:
        pass
    try:
        name = decode_abi_string(erc20_call(chain, address, "0x06fdde03"))
    except Exception:
        pass
    try:
        raw_decimals = erc20_call(chain, address, "0x313ce567")
        decimals = int(raw_decimals, 16)
    except Exception:
        pass
    return {"address": address, "symbol": symbol, "name": name, "decimals": decimals}


def find_pool_initialize_log(receipt: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        data_words = words(log.get("data", "0x"))
        if len(topics) >= 4 and len(data_words) >= 5:
            if len(strip0x(topics[1])) == 64 and topics[2].lower().startswith("0x000000000000000000000000"):
                candidates.append(log)
    if not candidates:
        raise RuntimeError("No Pancake pool initialize-like log found")
    return candidates[0]


def price_from_sqrt_x96(sqrt_price_x96: int, decimals0: int, decimals1: int) -> Decimal:
    raw_price = (Decimal(sqrt_price_x96) / (Decimal(2) ** 96)) ** 2
    return raw_price * (Decimal(10) ** (decimals0 - decimals1))


def analyze_tx(chain: str, tx_hash: str) -> dict[str, Any]:
    tx = rpc_call(chain, "eth_getTransactionByHash", [tx_hash])
    if not tx:
        raise RuntimeError(f"transaction not found: {tx_hash}")
    receipt = get_transaction_receipt(chain, tx_hash)
    init_log = find_pool_initialize_log(receipt)
    topics = init_log["topics"]
    data_words = words(init_log["data"])

    token0 = topic_addr(topics[2])
    token1 = topic_addr(topics[3])
    meta0 = token_meta(chain, token0)
    meta1 = token_meta(chain, token1)
    decimals0 = meta0.get("decimals")
    decimals1 = meta1.get("decimals")
    sqrt_price_x96 = uint(data_words[3])
    tick = sint(data_words[4])

    price_1_per_0 = None
    price_0_per_1 = None
    quote_summary = None
    if isinstance(decimals0, int) and isinstance(decimals1, int) and sqrt_price_x96:
        price_1_per_0 = price_from_sqrt_x96(sqrt_price_x96, decimals0, decimals1)
        price_0_per_1 = Decimal(1) / price_1_per_0 if price_1_per_0 else None
        quote_summary = build_quote_summary(meta0, meta1, price_1_per_0, price_0_per_1)

    token_transfers = token_transfer_summary(receipt, meta0, meta1)

    return {
        "chain": chain,
        "tx_hash": tx_hash,
        "block": hex_to_int(receipt.get("blockNumber")),
        "tx_index": hex_to_int(receipt.get("transactionIndex")),
        "status": hex_to_int(receipt.get("status")),
        "from": tx.get("from"),
        "to": tx.get("to"),
        "pool_id": topics[1],
        "event_contract": init_log.get("address"),
        "token0": meta0,
        "token1": meta1,
        "raw_fields": {
            "hook": topic_addr(data_words[0]),
            "fee": uint(data_words[1]),
            "parameters": data_words[2],
            "hook_or_manager": topic_addr(data_words[0]),
            "fee_or_param0": uint(data_words[1]),
            "param1": uint(data_words[2]),
            "sqrt_price_x96": sqrt_price_x96,
            "tick": tick,
        },
        "price": {
            "token1_per_token0": decimal_to_str(price_1_per_0),
            "token0_per_token1": decimal_to_str(price_0_per_1),
            "summary": quote_summary,
            "method": "sqrtPriceX96 adjusted by token decimals",
        },
        "token_transfers": token_transfers,
    }


def build_quote_summary(
    token0: dict[str, Any],
    token1: dict[str, Any],
    price_1_per_0: Decimal | None,
    price_0_per_1: Decimal | None,
) -> str:
    symbol0 = str(token0.get("symbol") or "token0").upper()
    symbol1 = str(token1.get("symbol") or "token1").upper()
    if symbol1 in QUOTE_SYMBOLS and price_1_per_0 is not None and price_0_per_1 is not None:
        return f"1 {symbol0} ≈ {compact_decimal(price_1_per_0)} {symbol1}; 1 {symbol1} ≈ {compact_decimal(price_0_per_1)} {symbol0}"
    if symbol0 in QUOTE_SYMBOLS and price_0_per_1 is not None and price_1_per_0 is not None:
        return f"1 {symbol1} ≈ {compact_decimal(price_0_per_1)} {symbol0}; 1 {symbol0} ≈ {compact_decimal(price_1_per_0)} {symbol1}"
    return f"1 {symbol0} ≈ {compact_decimal(price_1_per_0)} {symbol1}" if price_1_per_0 is not None else ""


def token_transfer_summary(receipt: dict[str, Any], token0: dict[str, Any], token1: dict[str, Any]) -> dict[str, Any]:
    rows = []
    watched = {
        norm(token0.get("address")): token0,
        norm(token1.get("address")): token1,
    }
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if len(topics) < 3 or norm(topics[0]) != TRANSFER_TOPIC:
            continue
        token = watched.get(norm(log.get("address")))
        if not token:
            continue
        decimals = token.get("decimals")
        raw_value = uint(log.get("data", "0x0"))
        amount = None
        if isinstance(decimals, int):
            amount = Decimal(raw_value) / (Decimal(10) ** decimals)
        rows.append(
            {
                "token": token.get("symbol") or token.get("address"),
                "token_address": token.get("address"),
                "from": topic_addr(topics[1]),
                "to": topic_addr(topics[2]),
                "amount": decimal_to_str(amount) if amount is not None else str(raw_value),
            }
        )
    return {
        "count": len(rows),
        "rows": rows,
        "interpretation": "this tx moved pair tokens" if rows else "no token0/token1 Transfer logs in this tx",
    }


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def compact_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value == value.to_integral():
        return format(value.quantize(Decimal(1)), "f")
    if value >= Decimal("1"):
        return format(value.quantize(Decimal("0.000001")).normalize(), "f")
    return format(value.quantize(Decimal("0.000000000001")).normalize(), "f")


def render_markdown(row: dict[str, Any]) -> str:
    token0 = row["token0"]
    token1 = row["token1"]
    lines = [
        "# Pancake Pool Tx Analysis",
        "",
        f"- chain: `{row['chain']}`",
        f"- tx: `{row['tx_hash']}`",
        f"- block: `{row['block']}`",
        f"- tx_index: `{row['tx_index']}`",
        f"- status: `{row['status']}`",
        f"- pool_id: `{row['pool_id']}`",
        "",
        "## Tokens",
        "",
        f"- token0: `{token0.get('symbol')}` `{token0.get('address')}` decimals `{token0.get('decimals')}`",
        f"- token1: `{token1.get('symbol')}` `{token1.get('address')}` decimals `{token1.get('decimals')}`",
        "",
        "## Initial Price",
        "",
        f"- {row['price'].get('summary') or 'unknown'}",
        f"- method: {row['price'].get('method')}",
        "",
        "## Token Transfers In Tx",
        "",
        f"- count: `{row.get('token_transfers', {}).get('count', 0)}`",
        f"- interpretation: {row.get('token_transfers', {}).get('interpretation', '')}",
        "",
        "## Raw Fields",
        "",
        "```json",
        json.dumps(row["raw_fields"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a PancakeSwap pool initialize tx from receipt logs.")
    parser.add_argument("tx_hash")
    parser.add_argument("--chain", default="bsc")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    row = analyze_tx(args.chain, args.tx_hash)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.tx_hash[:10]
    json_path = args.out_dir / f"{stem}.json"
    md_path = args.out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(row), encoding="utf-8")
    print(json_path)
    print(md_path)
    print(row["price"].get("summary") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
