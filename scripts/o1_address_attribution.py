#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "o1_address_attribution"


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fmt_dec(value: Any, places: int = 4) -> str:
    try:
        quant = Decimal(10) ** -places
        return f"{Decimal(str(value or '0')).quantize(quant):f}"
    except Exception:
        return "0"


def short_addr(addr: str) -> str:
    if len(addr or "") <= 14:
        return addr or "-"
    return addr[:8] + "..." + addr[-6:]


def load_sources() -> dict[str, Any]:
    return {
        "monitored": read_json(ROOT / "config" / "monitored_wallets.json", {"wallets": []}),
        "snapshot": read_json(ROOT / "output" / "monitoring" / "latest_snapshot.json", {"wallets": []}),
        "front_trace": read_csv(ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv"),
        "block_rows": read_csv(ROOT / "output" / "o1_block_verifier" / "block_transactions.csv"),
        "mint": read_json(ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json", {}),
    }


def evidence_level(tags: set[str], role: str, role_enum: str) -> str:
    role_text = role + " " + role_enum
    if "lp_minter" in tags:
        return "PROJECT_SIDE_STRONG"
    if "opening_front_buyer" in tags and ("庄家" in role_text or "潜伏" in role_text):
        return "PROJECT_SIDE_STRONG"
    if "suspected_operator_reserve" in role_text:
        return "PROJECT_SIDE_MEDIUM"
    if "dealer_hub" in tags:
        return "PROJECT_SIDE_MEDIUM"
    if "opening_front_buyer" in tags:
        return "OPENING_BUYER_UNLABELED"
    if "failed_bribe_sender" in tags or "failed_sniper_method_sender" in tags:
        return "FAILED_SNIPER_SIDE"
    if "distribution_wallet" in tags or "anomaly_wallet" in tags:
        return "MONITOR_ONLY"
    return "CONTEXT"


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    sources = load_sources()
    by_addr: dict[str, dict[str, str]] = {}

    for wallet in sources["monitored"].get("wallets", []):
        addr = norm(wallet.get("address"))
        if not addr:
            continue
        tags = set()
        role = str(wallet.get("role", ""))
        role_enum = str(wallet.get("monitor_role_enum", ""))
        if "分发中" in role or "已分完" in role or "dumper" in role_enum:
            tags.add("distribution_wallet")
        if "异常" in role:
            tags.add("anomaly_wallet")
        if "reserve" in role_enum:
            tags.add("suspected_operator_reserve")
        if "庄家" in role:
            tags.add("dealer_hub")
        by_addr[addr] = {
            "address": addr,
            "label": str(wallet.get("label", "")),
            "role": role,
            "role_enum": role_enum,
            "monitor_level": str(wallet.get("monitor_level", "")),
            "monitor_score": str(wallet.get("monitor_score", "")),
            "tags": "|".join(sorted(tags)),
            "sources": "|".join(wallet.get("sources", [])),
        }

    for row in sources["snapshot"].get("wallets", []):
        addr = norm(row.get("address"))
        if not addr:
            continue
        item = by_addr.setdefault(addr, {"address": addr})
        item.update(
            {
                "token_balance": fmt_dec(row.get("token_balance")),
                "recent_in": fmt_dec(row.get("incoming_amount")),
                "recent_out": fmt_dec(row.get("outgoing_amount")),
                "alert_level": str(row.get("alert_level", "")),
                "last_transfer_hash": str(row.get("last_transfer_hash", "")),
            }
        )

    for row in sources["front_trace"]:
        addr = norm(row.get("buyer"))
        if not addr:
            continue
        item = by_addr.setdefault(addr, {"address": addr})
        merge_tag(item, "opening_front_buyer")
        item.update(
            {
                "buy_tx_index": row.get("buy_tx_index", ""),
                "spent_usdt": fmt_dec(row.get("spent_usdt"), 2),
                "bought_o": fmt_dec(row.get("bought_o"), 4),
                "front_status": row.get("status", ""),
            }
        )
        if not item.get("label"):
            item["label"] = row.get("monitoring_label", "")
        if not item.get("role"):
            item["role"] = row.get("monitoring_role", "")

    mint_sender = norm(sources["mint"].get("sender"))
    if mint_sender:
        item = by_addr.setdefault(mint_sender, {"address": mint_sender})
        merge_tag(item, "lp_minter")
        item["label"] = item.get("label") or "O1 LP minter"
        item["buy_tx_index"] = item.get("buy_tx_index", "15")

    failed_rows: list[dict[str, str]] = []
    for row in sources["block_rows"]:
        selector = row.get("selector")
        status = row.get("status")
        if selector != "0x72026aa8" or status != "failed":
            continue
        sender = norm(row.get("from"))
        item = by_addr.setdefault(sender, {"address": sender})
        merge_tag(item, "failed_sniper_method_sender")
        if row.get("is_failed_bribe_tx") == "yes":
            merge_tag(item, "failed_bribe_sender")
        item["failed_tx_index"] = row.get("tx_index", "")
        item["failed_gas_gwei"] = row.get("gas_price_gwei", "")
        item["failed_tx_hash"] = row.get("tx_hash", "")
        failed_rows.append(row)

    rows: list[dict[str, str]] = []
    for item in by_addr.values():
        tags = set(filter(None, item.get("tags", "").split("|")))
        level = evidence_level(tags, item.get("role", ""), item.get("role_enum", ""))
        item["attribution"] = level
        item.setdefault("token_balance", "0")
        item.setdefault("recent_in", "0")
        item.setdefault("recent_out", "0")
        rows.append(item)

    rows.sort(key=sort_key)
    return rows, failed_rows


def merge_tag(item: dict[str, str], tag: str) -> None:
    tags = set(filter(None, item.get("tags", "").split("|")))
    tags.add(tag)
    item["tags"] = "|".join(sorted(tags))


def sort_key(row: dict[str, str]) -> tuple[int, Decimal, str]:
    order = {
        "PROJECT_SIDE_STRONG": 0,
        "PROJECT_SIDE_MEDIUM": 1,
        "OPENING_BUYER_UNLABELED": 2,
        "FAILED_SNIPER_SIDE": 3,
        "MONITOR_ONLY": 4,
        "CONTEXT": 5,
    }
    try:
        balance = Decimal(row.get("token_balance") or "0")
    except Exception:
        balance = Decimal(0)
    return (order.get(row.get("attribution", ""), 9), -balance, row.get("address", ""))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "attribution",
        "address",
        "label",
        "role",
        "monitor_level",
        "monitor_score",
        "token_balance",
        "recent_in",
        "recent_out",
        "buy_tx_index",
        "spent_usdt",
        "bought_o",
        "front_status",
        "failed_tx_index",
        "failed_gas_gwei",
        "tags",
        "sources",
        "last_transfer_hash",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def render_markdown(rows: list[dict[str, str]], failed_rows: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["attribution"]] = counts.get(row["attribution"], 0) + 1

    lines = [
        "# O1 Address Attribution",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}`: `{counts[key]}`")

    lines.extend(
        [
            "",
            "## Project-Side Evidence",
            "",
            "| Attribution | Address | Label | Role | Balance | Recent out | Tags |",
            "| --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in [r for r in rows if r["attribution"].startswith("PROJECT_SIDE")][:20]:
        lines.append(
            f"| {row.get('attribution', '')} | `{row.get('address', '')}` | {clean(row.get('label', ''))} | "
            f"{clean(row.get('role', ''))} | {row.get('token_balance', '0')} | {row.get('recent_out', '0')} | "
            f"{row.get('tags', '')} |"
        )

    lines.extend(
        [
            "",
            "## Failed Sniper Side",
            "",
            "| txIndex | From | To | Gas gwei | Tx |",
            "| ---: | --- | --- | ---: | --- |",
        ]
    )
    for row in failed_rows:
        lines.append(
            f"| {row.get('tx_index', '')} | `{row.get('from', '')}` | `{row.get('to', '')}` | "
            f"{row.get('gas_price_gwei', '')} | `{row.get('tx_hash', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Top Balances",
            "",
            "| Attribution | Balance | Address | Label |",
            "| --- | ---: | --- | --- |",
        ]
    )
    top = sorted(rows, key=lambda row: Decimal(row.get("token_balance") or "0"), reverse=True)[:12]
    for row in top:
        lines.append(
            f"| {row.get('attribution', '')} | {row.get('token_balance', '0')} | "
            f"`{short_addr(row.get('address', ''))}` | {clean(row.get('label', ''))} |"
        )
    lines.append("")
    return "\n".join(lines)


def clean(value: str) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ")


def main() -> int:
    rows, failed_rows = build_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "address_attribution.csv", rows)
    (OUT_DIR / "o1_address_attribution.md").write_text(render_markdown(rows, failed_rows), encoding="utf-8")
    print(OUT_DIR / "address_attribution.csv")
    print(OUT_DIR / "o1_address_attribution.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
