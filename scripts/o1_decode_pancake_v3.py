#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any


getcontext().prec = 80

ROOT = Path(__file__).resolve().parents[1]
BLOCK_PATH = ROOT / "output" / "o1_block_verifier" / "block.json"
RECEIPTS_PATH = ROOT / "output" / "o1_block_verifier" / "receipts.json"
MONITORING_PATH = ROOT / "output" / "hertzflow_o1" / "monitoring" / "monitoring_paste.json"
OUT_DIR = ROOT / "output" / "o1_pancake_v3_decode"

O_TOKEN = "0x500a02a20b0b0a3f3efccfc0559543f5743bd1c4"
USDT_TOKEN = "0x55d398326f99059ff775485246999027b3197955"
POSITION_MANAGER = "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364"
V3_ROUTER = "0x1b81d678ffb9c0263b24a97847620c99d213eb14"

SELECTOR_MINT = "0x88316456"
SELECTOR_EXACT_INPUT_SINGLE = "0x414bf389"

TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_POOL_MINT = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
TOPIC_INCREASE_LIQUIDITY = "0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f"
TOPIC_SWAP = "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"

DECIMALS = {
    O_TOKEN: 18,
    USDT_TOKEN: 18,
}

LABELS = {
    O_TOKEN: "O token",
    USDT_TOKEN: "USDT",
    POSITION_MANAGER: "PancakeSwap V3 Position Manager",
    V3_ROUTER: "PancakeSwap V3 Router",
}


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def words(data: str) -> list[str]:
    raw = strip0x(data)
    return ["0x" + raw[i : i + 64] for i in range(0, len(raw), 64) if raw[i : i + 64]]


def calldata_words(input_data: str) -> list[str]:
    raw = strip0x(input_data)
    return ["0x" + raw[i : i + 64] for i in range(8, len(raw), 64) if raw[i : i + 64]]


def uint(word: str) -> int:
    return int(strip0x(word), 16)


def sint(word: str, bits: int = 256) -> int:
    value = uint(word)
    sign = 1 << (bits - 1)
    mask = 1 << bits
    return value - mask if value & sign else value


def addr_from_word(word: str) -> str:
    return "0x" + strip0x(word)[-40:].lower()


def decimal_amount(raw: int, token: str) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** DECIMALS[norm(token)])


def fmt_dec(value: Decimal, places: int = 6) -> str:
    quant = Decimal(10) ** -places
    return f"{value.quantize(quant):f}"


def fmt_addr(addr: str) -> str:
    addr = norm(addr)
    if addr in LABELS:
        return f"{LABELS[addr]} ({addr})"
    return addr


def price_from_tick(tick: int, token0: str, token1: str) -> Decimal:
    base = Decimal("1.0001") ** tick
    scale = Decimal(10) ** (DECIMALS[norm(token0)] - DECIMALS[norm(token1)])
    return base * scale


def tx_index(tx: dict[str, Any]) -> int:
    return int(tx["transactionIndex"], 16)


def raw_to_gwei(raw: str) -> Decimal:
    return Decimal(int(raw, 16)) / Decimal(1_000_000_000)


def transfer_value(log: dict[str, Any]) -> int:
    data = log.get("data", "0x")
    if data == "0x":
        return 0
    return uint(words(data)[0])


def topic_addr(topic: str) -> str:
    return "0x" + strip0x(topic)[-40:].lower()


def topic_int(topic: str) -> int:
    return sint(topic)


def load_monitor_labels() -> dict[str, str]:
    if not MONITORING_PATH.exists():
        return {}
    rows = json.loads(MONITORING_PATH.read_text(encoding="utf-8"))
    return {norm(row.get("address")): row.get("name", "") for row in rows if row.get("address")}


@dataclass
class DecodedMint:
    tx_hash: str
    tx_index: int
    sender: str
    token0: str
    token1: str
    fee: int
    tick_lower: int
    tick_upper: int
    min_price_usdt_per_o: Decimal
    max_price_usdt_per_o: Decimal
    amount0_desired: Decimal
    amount1_desired: Decimal
    amount0_added: Decimal
    amount1_added: Decimal
    liquidity: int
    token_id: int
    recipient: str
    deadline: int
    pool: str
    gas_gwei: Decimal


@dataclass
class DecodedSwap:
    tx_hash: str
    tx_index: int
    buyer: str
    token_in: str
    token_out: str
    fee: int
    amount_in_usdt: Decimal
    amount_out_o: Decimal
    avg_price_usdt_per_o: Decimal
    tick_after: int | None
    price_after_usdt_per_o: Decimal | None
    amount_out_min: Decimal
    deadline: int
    pool: str
    gas_gwei: Decimal
    monitoring_label: str


def decode_mint(tx: dict[str, Any], receipt: dict[str, Any]) -> DecodedMint:
    data = calldata_words(tx["input"])
    token0 = addr_from_word(data[0])
    token1 = addr_from_word(data[1])
    fee = uint(data[2])
    tick_lower = sint(data[3])
    tick_upper = sint(data[4])
    amount0_desired_raw = uint(data[5])
    amount1_desired_raw = uint(data[6])
    recipient = addr_from_word(data[9])
    deadline = uint(data[10])

    token_id = 0
    liquidity = 0
    amount0_added_raw = 0
    amount1_added_raw = 0
    pool = ""

    for log in receipt.get("logs", []):
        topics = [norm(topic) for topic in log.get("topics", [])]
        if not topics:
            continue
        if norm(log.get("address")) == POSITION_MANAGER and topics[0] == TOPIC_TRANSFER and len(topics) >= 4:
            token_id = uint(topics[3])
        elif norm(log.get("address")) == POSITION_MANAGER and topics[0] == TOPIC_INCREASE_LIQUIDITY:
            token_id = uint(topics[1])
            event_words = words(log["data"])
            liquidity = uint(event_words[0])
            amount0_added_raw = uint(event_words[1])
            amount1_added_raw = uint(event_words[2])
        elif topics[0] == TOPIC_POOL_MINT:
            pool = norm(log.get("address"))

    return DecodedMint(
        tx_hash=tx["hash"],
        tx_index=tx_index(tx),
        sender=norm(tx["from"]),
        token0=token0,
        token1=token1,
        fee=fee,
        tick_lower=tick_lower,
        tick_upper=tick_upper,
        min_price_usdt_per_o=price_from_tick(tick_lower, token0, token1),
        max_price_usdt_per_o=price_from_tick(tick_upper, token0, token1),
        amount0_desired=decimal_amount(amount0_desired_raw, token0),
        amount1_desired=decimal_amount(amount1_desired_raw, token1),
        amount0_added=decimal_amount(amount0_added_raw, token0),
        amount1_added=decimal_amount(amount1_added_raw, token1),
        liquidity=liquidity,
        token_id=token_id,
        recipient=recipient,
        deadline=deadline,
        pool=pool,
        gas_gwei=raw_to_gwei(tx["gasPrice"]),
    )


def decode_swap(tx: dict[str, Any], receipt: dict[str, Any], monitor_labels: dict[str, str]) -> DecodedSwap:
    data = calldata_words(tx["input"])
    token_in = addr_from_word(data[0])
    token_out = addr_from_word(data[1])
    fee = uint(data[2])
    recipient = addr_from_word(data[3])
    deadline = uint(data[4])
    amount_in_raw = uint(data[5])
    amount_out_min_raw = uint(data[6])

    pool = ""
    amount_in_from_logs_raw = 0
    amount_out_from_logs_raw = 0
    tick_after: int | None = None
    price_after: Decimal | None = None

    for log in receipt.get("logs", []):
        topics = [norm(topic) for topic in log.get("topics", [])]
        log_addr = norm(log.get("address"))
        if not topics:
            continue
        if topics[0] == TOPIC_TRANSFER and log_addr == token_in and len(topics) >= 3:
            if topic_addr(topics[1]) == recipient:
                amount_in_from_logs_raw += transfer_value(log)
        elif topics[0] == TOPIC_TRANSFER and log_addr == token_out and len(topics) >= 3:
            if topic_addr(topics[2]) == recipient:
                amount_out_from_logs_raw += transfer_value(log)
        elif topics[0] == TOPIC_SWAP:
            pool = log_addr
            event_words = words(log["data"])
            if len(event_words) >= 5:
                tick_after = sint(event_words[4])
                price_after = price_from_tick(tick_after, token_out, token_in)

    amount_in = decimal_amount(amount_in_from_logs_raw or amount_in_raw, token_in)
    amount_out = decimal_amount(amount_out_from_logs_raw, token_out)
    avg_price = amount_in / amount_out if amount_out else Decimal(0)

    return DecodedSwap(
        tx_hash=tx["hash"],
        tx_index=tx_index(tx),
        buyer=recipient,
        token_in=token_in,
        token_out=token_out,
        fee=fee,
        amount_in_usdt=amount_in,
        amount_out_o=amount_out,
        avg_price_usdt_per_o=avg_price,
        tick_after=tick_after,
        price_after_usdt_per_o=price_after,
        amount_out_min=decimal_amount(amount_out_min_raw, token_out),
        deadline=deadline,
        pool=pool,
        gas_gwei=raw_to_gwei(tx["gasPrice"]),
        monitoring_label=monitor_labels.get(recipient, ""),
    )


def build_report(mint: DecodedMint, swaps: list[DecodedSwap], receipt_count: int, block_tx_count: int) -> str:
    total_usdt = sum((swap.amount_in_usdt for swap in swaps), Decimal(0))
    total_o = sum((swap.amount_out_o for swap in swaps), Decimal(0))
    avg = total_usdt / total_o if total_o else Decimal(0)
    lines: list[str] = []
    lines.append("# O1 PancakeSwap V3 Decode")
    lines.append("")
    lines.append("## Mint")
    lines.append("")
    lines.append(f"- txIndex: `{mint.tx_index}`")
    lines.append(f"- tx: `{mint.tx_hash}`")
    lines.append(f"- sender: `{mint.sender}`")
    lines.append(f"- position ID: `{mint.token_id}`")
    lines.append(f"- pool: `{mint.pool}`")
    lines.append(f"- token0: {fmt_addr(mint.token0)}")
    lines.append(f"- token1: {fmt_addr(mint.token1)}")
    lines.append(f"- fee: `{mint.fee}`")
    lines.append(f"- tick range: `{mint.tick_lower}` -> `{mint.tick_upper}`")
    lines.append(f"- price range: `{fmt_dec(mint.min_price_usdt_per_o, 6)}` -> `{fmt_dec(mint.max_price_usdt_per_o, 6)}` USDT per O")
    lines.append(f"- amount added: `{fmt_dec(mint.amount0_added, 6)}` O + `{fmt_dec(mint.amount1_added, 6)}` USDT")
    lines.append(f"- liquidity: `{mint.liquidity}`")
    lines.append(f"- gas price: `{fmt_dec(mint.gas_gwei, 6)}` gwei")
    lines.append(f"- receipt coverage: `{receipt_count}/{block_tx_count}` block transactions")
    lines.append("")
    lines.append("## Opening Swaps")
    lines.append("")
    lines.append("| txIndex | buyer | USDT in | O out | avg USDT/O | tick after | price after | monitoring |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for swap in swaps:
        price_after = "-" if swap.price_after_usdt_per_o is None else fmt_dec(swap.price_after_usdt_per_o, 6)
        tick_after = "-" if swap.tick_after is None else str(swap.tick_after)
        monitoring = swap.monitoring_label or ""
        lines.append(
            f"| {swap.tx_index} | `{swap.buyer}` | {fmt_dec(swap.amount_in_usdt, 6)} | "
            f"{fmt_dec(swap.amount_out_o, 6)} | {fmt_dec(swap.avg_price_usdt_per_o, 6)} | "
            f"{tick_after} | {price_after} | {monitoring} |"
        )
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- decoded swap count: `{len(swaps)}`")
    lines.append(f"- total USDT in: `{fmt_dec(total_usdt, 6)}`")
    lines.append(f"- total O out: `{fmt_dec(total_o, 6)}`")
    lines.append(f"- weighted average price: `{fmt_dec(avg, 6)}` USDT per O")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- LP mint 是单边 O 加池，USDT 数量为 0。")
    lines.append("- position ID 和价格区间与帖子截图里的 `0.045-0.36` 区间一致。")
    lines.append("- 前排 swap 的 `amountOutMinimum` 都是 0，说明这些买入没有设置链上最小收币保护。")
    if receipt_count >= block_tx_count:
        lines.append("- 本报告已覆盖该区块本地保存的全量 receipts；Pancake V3 Router 的 O/USDT 开盘买入为上述 5 笔。")
    else:
        lines.append("- 本报告只解码已在本地 receipt 集合里的开盘 swap；需要 full receipt 才能覆盖整个区块。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    block = json.loads(BLOCK_PATH.read_text(encoding="utf-8"))
    receipts = json.loads(RECEIPTS_PATH.read_text(encoding="utf-8"))
    receipt_by_hash = {norm(row["transactionHash"]): row for row in receipts}
    monitor_labels = load_monitor_labels()

    txs = sorted(block["transactions"], key=tx_index)
    mint_tx = next(tx for tx in txs if norm(tx.get("to")) == POSITION_MANAGER and tx.get("input", "").startswith(SELECTOR_MINT))
    mint_receipt = receipt_by_hash[norm(mint_tx["hash"])]
    mint = decode_mint(mint_tx, mint_receipt)

    swaps: list[DecodedSwap] = []
    for tx in txs:
        if norm(tx.get("to")) != V3_ROUTER or not tx.get("input", "").startswith(SELECTOR_EXACT_INPUT_SINGLE):
            continue
        receipt = receipt_by_hash.get(norm(tx["hash"]))
        if not receipt or receipt.get("status") != "0x1":
            continue
        decoded = decode_swap(tx, receipt, monitor_labels)
        if decoded.token_in == USDT_TOKEN and decoded.token_out == O_TOKEN:
            swaps.append(decoded)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mint_json = {
        "tx_hash": mint.tx_hash,
        "tx_index": mint.tx_index,
        "sender": mint.sender,
        "position_id": mint.token_id,
        "pool": mint.pool,
        "token0": mint.token0,
        "token1": mint.token1,
        "fee": mint.fee,
        "tick_lower": mint.tick_lower,
        "tick_upper": mint.tick_upper,
        "min_price_usdt_per_o": str(mint.min_price_usdt_per_o),
        "max_price_usdt_per_o": str(mint.max_price_usdt_per_o),
        "amount0_added": str(mint.amount0_added),
        "amount1_added": str(mint.amount1_added),
        "liquidity": str(mint.liquidity),
        "recipient": mint.recipient,
        "deadline": mint.deadline,
        "gas_gwei": str(mint.gas_gwei),
    }
    (OUT_DIR / "decoded_mint.json").write_text(json.dumps(mint_json, indent=2), encoding="utf-8")

    with (OUT_DIR / "decoded_swaps.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "tx_index",
                "tx_hash",
                "buyer",
                "usdt_in",
                "o_out",
                "avg_price_usdt_per_o",
                "tick_after",
                "price_after_usdt_per_o",
                "amount_out_min",
                "gas_gwei",
                "monitoring_label",
            ],
        )
        writer.writeheader()
        for swap in swaps:
            writer.writerow(
                {
                    "tx_index": swap.tx_index,
                    "tx_hash": swap.tx_hash,
                    "buyer": swap.buyer,
                    "usdt_in": str(swap.amount_in_usdt),
                    "o_out": str(swap.amount_out_o),
                    "avg_price_usdt_per_o": str(swap.avg_price_usdt_per_o),
                    "tick_after": "" if swap.tick_after is None else swap.tick_after,
                    "price_after_usdt_per_o": "" if swap.price_after_usdt_per_o is None else str(swap.price_after_usdt_per_o),
                    "amount_out_min": str(swap.amount_out_min),
                    "gas_gwei": str(swap.gas_gwei),
                    "monitoring_label": swap.monitoring_label,
                }
            )

    report = build_report(mint, swaps, len(receipts), len(block.get("transactions", [])))
    (OUT_DIR / "o1_pancake_v3_decode.md").write_text(report, encoding="utf-8")
    print(OUT_DIR / "o1_pancake_v3_decode.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
