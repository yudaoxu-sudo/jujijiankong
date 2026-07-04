#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_OUT = ROOT / "config" / "monitored_wallets.json"
HERTZFLOW_O1 = ROOT / "output" / "hertzflow_o1" / "monitoring" / "monitoring_wallets_full.json"
O1_FRONT_BUYERS = ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv"
O1_CONTRACT = "0x500a02a20b0b0a3f3efccfc0559543f5743bd1c4"


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_hertzflow_o1() -> list[dict[str, Any]]:
    if not HERTZFLOW_O1.exists():
        return []
    payload = json.loads(HERTZFLOW_O1.read_text(encoding="utf-8"))
    wallets = []
    for row in payload.get("addresses", []):
        addr = norm(row.get("address"))
        if not addr:
            continue
        wallets.append(
            {
                "project": "O1",
                "symbol": payload.get("source_symbol", row.get("source_sym", "O")),
                "chain": row.get("chain", "bsc"),
                "token_contract": norm(payload.get("source_contract") or row.get("source_contract") or O1_CONTRACT),
                "address": addr,
                "label": row.get("label", ""),
                "role": row.get("role", ""),
                "monitor_level": row.get("monitor_level", ""),
                "monitor_score": row.get("monitor_score", 0),
                "monitor_role_enum": row.get("monitor_role_enum", ""),
                "monitor_reason": row.get("monitor_reason", ""),
                "trigger_summary": row.get("trigger_summary", ""),
                "sources": ["hertzflow_o1"],
                "watch_rules": infer_watch_rules(row),
            }
        )
    return wallets


def load_front_buyers() -> list[dict[str, Any]]:
    if not O1_FRONT_BUYERS.exists():
        return []
    rows: list[dict[str, Any]] = []
    with O1_FRONT_BUYERS.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            addr = norm(row.get("buyer"))
            if not addr:
                continue
            rows.append(
                {
                    "project": "O1",
                    "symbol": "O",
                    "chain": "bsc",
                    "token_contract": O1_CONTRACT,
                    "address": addr,
                    "label": row.get("monitoring_label", "") or f"O-front-buyer-{addr[2:7]}",
                    "role": row.get("monitoring_role", "") or "opening front buyer",
                    "monitor_level": row.get("monitoring_level", "") or "HIGH",
                    "monitor_score": 8,
                    "monitor_role_enum": "opening_front_buyer",
                    "monitor_reason": "开盘前排买入地址；监控是否转出、砸池子、转入交易所。",
                    "trigger_summary": "O 余额减少、转入池子、转入交易所或拆分到下游地址时触发复盘。",
                    "sources": ["o1_front_buyers_trace"],
                    "watch_rules": ["token_balance_drop", "token_out_transfer", "transfer_to_pool_or_cex"],
                }
            )
    return rows


def infer_watch_rules(row: dict[str, Any]) -> list[str]:
    role_enum = str(row.get("monitor_role_enum", ""))
    text = " ".join(
        str(row.get(key, ""))
        for key in ("role", "monitor_reason", "trigger_summary", "label")
    )
    rules = ["token_balance_change", "token_out_transfer"]
    if "reserve" in role_enum or "隐藏庄家弹药" in text:
        rules.extend(["reserve_split", "transfer_to_pool_or_cex"])
    if "dumper" in role_enum or "分发" in text or "已分" in text:
        rules.extend(["continued_distribution", "transfer_to_pool_or_cex"])
    if "异常" in text:
        rules.append("recent_anomaly_followup")
    return sorted(set(rules))


def merge_wallets(wallet_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for group in wallet_groups:
        for wallet in group:
            key = (wallet["chain"], wallet["token_contract"], wallet["address"])
            if key not in merged:
                merged[key] = wallet
                continue
            existing = merged[key]
            for source in wallet.get("sources", []):
                if source not in existing["sources"]:
                    existing["sources"].append(source)
            for rule in wallet.get("watch_rules", []):
                if rule not in existing["watch_rules"]:
                    existing["watch_rules"].append(rule)
            if not existing.get("label") and wallet.get("label"):
                existing["label"] = wallet["label"]
            if not existing.get("role") and wallet.get("role"):
                existing["role"] = wallet["role"]
            existing["monitor_score"] = max(int(existing.get("monitor_score") or 0), int(wallet.get("monitor_score") or 0))
            if severity_rank(wallet.get("monitor_level", "")) > severity_rank(existing.get("monitor_level", "")):
                existing["monitor_level"] = wallet.get("monitor_level", "")
    return sorted(merged.values(), key=lambda item: (-severity_rank(item.get("monitor_level", "")), -int(item.get("monitor_score") or 0), item["address"]))


def severity_rank(level: str) -> int:
    return {"CRITICAL": 3, "HIGH": 2, "NORMAL": 1}.get((level or "").upper(), 0)


def render_markdown(payload: dict[str, Any]) -> str:
    wallets = payload["wallets"]
    lines = [
        "# Monitored Wallets",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- wallet_count: `{len(wallets)}`",
        "",
        "| Level | Score | Symbol | Address | Label | Role | Sources |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in wallets:
        lines.append(
            f"| {row.get('monitor_level', '')} | {row.get('monitor_score', '')} | {row.get('symbol', '')} | "
            f"`{row.get('address', '')}` | {clean(row.get('label', ''))} | {clean(row.get('role', ''))} | "
            f"{','.join(row.get('sources', []))} |"
        )
    lines.append("")
    return "\n".join(lines)


def clean(value: str) -> str:
    return (value or "").replace("|", "/").replace("\n", " ")


def main() -> int:
    wallets = merge_wallets([load_hertzflow_o1(), load_front_buyers()])
    payload = {
        "generated_at": now_iso(),
        "schema_version": "monitored_wallets.v1",
        "wallets": wallets,
    }
    CONFIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "output" / "monitored_wallets.md").write_text(render_markdown(payload), encoding="utf-8")
    print(CONFIG_OUT)
    print(ROOT / "output" / "monitored_wallets.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
