#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_pancake_v4_roundtrip_fixture import (
    ADDRESS_MSG_SENDER,
    ADDRESS_THIS,
    ARX_POOL_KEY,
    build_fixture,
)
from scripts.decode_pancake_v4_execute import decode_tx


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_roundtrip_fixture_verification"
ARX_BUY_TX = "0x046673c3b5217b271da8b2be94d892537f9b120865be9bedb49db9959bd582db"
ARX_SELL_TX = "0xdbcf8b8d95418c0d08b16fde926abaa9d2355e340e5d6d1d503a75430848e4e7"
REAL_ARX_BUY = {
    "tx_hash": ARX_BUY_TX,
    "direction": "buy",
    "pool_key": ARX_POOL_KEY,
    "zero_for_one": True,
    "amount_in": "51000000000000000000",
    "amount_out_minimum": "186106672853510527767",
    "settle_currency": ARX_POOL_KEY["currency0"],
    "settle_amount": "51000000000000000000",
    "settle_payer_is_user": True,
    "take_all_currency": ARX_POOL_KEY["currency1"],
}
REAL_ARX_SELL = {
    "tx_hash": ARX_SELL_TX,
    "direction": "sell",
    "pool_key": ARX_POOL_KEY,
    "zero_for_one": False,
    "amount_in": "102304216770951440208",
    "amount_out_minimum": "27986423584515330048",
    "settle_currency": ARX_POOL_KEY["currency1"],
    "settle_amount": "102304216770951440208",
    "settle_payer_is_user": True,
    "take_all_currency": ARX_POOL_KEY["currency0"],
}


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def canonical_pool_key(pool_key: dict[str, Any]) -> dict[str, Any]:
    return {
        "currency0": norm(pool_key.get("currency0")),
        "currency1": norm(pool_key.get("currency1")),
        "hooks": norm(pool_key.get("hooks")),
        "pool_manager": norm(pool_key.get("pool_manager")),
        "fee": int(pool_key.get("fee") or 0),
        "parameters": norm(pool_key.get("parameters")),
    }


def command_actions(command: dict[str, Any]) -> list[dict[str, Any]]:
    return list(command.get("decoded_input", {}).get("actions", []))


def extract_v4_leg(decoded: dict[str, Any], direction: str, tx_hash: str) -> dict[str, Any]:
    commands = decoded.get("input_decode", {}).get("commands", [])
    v4_commands = [command for command in commands if command.get("command") == "10"]
    if len(v4_commands) != 1:
        raise ValueError(f"{direction} tx must contain exactly one V4_SWAP command")
    actions = command_actions(v4_commands[0])
    if [action.get("name") for action in actions] != ["SWAP_EXACT_IN_SINGLE", "SETTLE", "TAKE_ALL"]:
        raise ValueError(f"{direction} tx has unexpected v4 action sequence")
    swap = actions[0]["decoded_param"]
    settle = actions[1]["decoded_param"]
    take_all = actions[2]["decoded_param"]
    return {
        "tx_hash": tx_hash,
        "direction": direction,
        "pool_key": canonical_pool_key(swap["pool_key"]),
        "zero_for_one": bool(swap["zero_for_one"]),
        "amount_in": str(swap["amount_in"]),
        "amount_out_minimum": str(swap["amount_out_minimum"]),
        "settle_currency": norm(settle["currency"]),
        "settle_amount": str(settle["amount"]),
        "settle_payer_is_user": bool(settle["payer_is_user"]),
        "take_all_currency": norm(take_all["currency"]),
        "take_all_recipient": norm(take_all["recipient"]),
    }


def offline_leg(sample: dict[str, Any]) -> dict[str, Any]:
    leg = dict(sample)
    leg["pool_key"] = canonical_pool_key(leg["pool_key"])
    leg["settle_currency"] = norm(leg["settle_currency"])
    leg["take_all_currency"] = norm(leg["take_all_currency"])
    return leg


def fixture_args() -> SimpleNamespace:
    return SimpleNamespace(
        out_dir=DEFAULT_OUT_DIR,
        deadline=0,
        buy_amount=51_000_000_000_000_000_000,
        buy_amount_out_minimum=186_106_672_853_510_527_767,
        sell_amount=186_106_672_853_510_527_767,
        sell_amount_out_minimum=0,
        pool_key=dict(ARX_POOL_KEY),
        buy_zero_for_one=True,
        sell_zero_for_one=False,
    )


def fixture_legs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fixture = build_fixture(fixture_args())
    commands = fixture["decoded"]["commands"]
    if len(commands) != 2:
        raise ValueError("roundtrip fixture must contain two V4_SWAP commands")
    legs: list[dict[str, Any]] = []
    for index, direction in enumerate(["buy", "sell"]):
        actions = command_actions(commands[index])
        if [action.get("name") for action in actions] != ["SWAP_EXACT_IN_SINGLE", "SETTLE", "TAKE_ALL"]:
            raise ValueError(f"fixture {direction} leg has unexpected v4 action sequence")
        swap = actions[0]["decoded_param"]
        settle = actions[1]["decoded_param"]
        take_all = actions[2]["decoded_param"]
        legs.append(
            {
                "direction": direction,
                "pool_key": canonical_pool_key(swap["pool_key"]),
                "zero_for_one": bool(swap["zero_for_one"]),
                "amount_in": str(swap["amount_in"]),
                "amount_out_minimum": str(swap["amount_out_minimum"]),
                "settle_currency": norm(settle["currency"]),
                "settle_amount": str(settle["amount"]),
                "settle_payer_is_user": bool(settle["payer_is_user"]),
                "take_all_currency": norm(take_all["currency"]),
                "take_all_recipient": norm(take_all["recipient"]),
            }
        )
    return fixture, legs[0], legs[1]


def check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def build_report(use_rpc: bool) -> dict[str, Any]:
    if use_rpc:
        buy_real = extract_v4_leg(decode_tx("bsc", ARX_BUY_TX), "buy", ARX_BUY_TX)
        sell_real = extract_v4_leg(decode_tx("bsc", ARX_SELL_TX), "sell", ARX_SELL_TX)
        evidence_mode = "rpc"
    else:
        buy_real = offline_leg(REAL_ARX_BUY)
        sell_real = offline_leg(REAL_ARX_SELL)
        evidence_mode = "offline_reviewed_arx_pair"

    fixture, buy_fixture, sell_fixture = fixture_legs()
    checks = [
        check("fixture status stays calldata-only", fixture["status"] == "calldata_fixture_only", fixture["status"]),
        check("fixture commands are two v4 swaps", fixture["commands"] == ["10", "10"], str(fixture["commands"])),
        check("buy pool key matches reviewed ARX buy", buy_fixture["pool_key"] == buy_real["pool_key"]),
        check("sell pool key matches reviewed ARX sell", sell_fixture["pool_key"] == sell_real["pool_key"]),
        check("buy direction matches real buy", buy_fixture["zero_for_one"] == buy_real["zero_for_one"]),
        check("sell direction matches real sell", sell_fixture["zero_for_one"] == sell_real["zero_for_one"]),
        check("buy quote input matches real ARX buy", buy_fixture["amount_in"] == buy_real["amount_in"]),
        check("buy min output matches real ARX buy", buy_fixture["amount_out_minimum"] == buy_real["amount_out_minimum"]),
        check("buy settle payer matches real user-funded buy", buy_fixture["settle_payer_is_user"] is True),
        check("sell settle uses router-held token", sell_fixture["settle_payer_is_user"] is False),
        check("buy take_all keeps bought token inside router", buy_fixture["take_all_recipient"] == norm(ADDRESS_THIS)),
        check("sell take_all returns quote to msg.sender", sell_fixture["take_all_recipient"] == norm(ADDRESS_MSG_SENDER)),
        check("fixture does not claim recovery rate", "sellability" not in fixture),
    ]
    ok = all(item["ok"] for item in checks)
    return {
        "schema": "pancake_v4_roundtrip_fixture_verification.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ok else "fail",
        "evidence_mode": evidence_mode,
        "source_samples": {
            "buy_tx": ARX_BUY_TX,
            "sell_tx": ARX_SELL_TX,
        },
        "scope": [
            "This verifies local calldata shape against reviewed ARX buy/sell legs.",
            "It does not prove UniversalRouter eth_call execution, final quote recovery, sell tax, blacklist behavior, or honeypot safety.",
            "Any v4 follow signal remains blocked until recovery-rate parsing is proven.",
        ],
        "checks": checks,
        "reviewed_real_legs": {
            "buy": buy_real,
            "sell": sell_real,
        },
        "fixture_legs": {
            "buy": buy_fixture,
            "sell": sell_fixture,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Pancake v4 Roundtrip Fixture Verification",
        "",
        f"- status: `{report['status']}`",
        f"- evidence_mode: `{report['evidence_mode']}`",
        f"- buy sample: `{report['source_samples']['buy_tx']}`",
        f"- sell sample: `{report['source_samples']['sell_tx']}`",
        "",
        "## Scope",
        "",
    ]
    lines.extend(f"- {item}" for item in report["scope"])
    lines.extend(["", "## Checks", ""])
    for item in report["checks"]:
        mark = "PASS" if item["ok"] else "FAIL"
        suffix = f" - {item['detail']}" if item.get("detail") else ""
        lines.append(f"- {mark}: {item['name']}{suffix}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Pancake v4 roundtrip fixture shape against reviewed ARX buy/sell legs.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--rpc", action="store_true", help="Decode the ARX buy/sell txs from live BSC RPC before checking.")
    args = parser.parse_args()

    report = build_report(args.rpc)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
