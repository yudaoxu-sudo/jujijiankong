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

from scripts.alpha_opening_block_watch import encode_balance_of, mapping_storage_key
from sniper_engine.rpc import rpc_call


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_state_override_probe"
BSC_USDT = "0x55d398326f99059ff775485246999027b3197955"
DEFAULT_RICH_HOLDER = "0x8894e0a0c962cb723c1976a4421c95949be2d4e3"
DEFAULT_FAKE_HOLDER = "0x0000000000000000000000000000000000000abc"


def storage_at_block(token: str, key: str, block_tag: str) -> str:
    return rpc_call("bsc", "eth_getStorageAt", [token, key, block_tag]) or "0x0"


def find_balance_slot(token: str, holder: str, max_slots: int, block_tag: str) -> dict[str, Any]:
    expected = int(rpc_call("bsc", "eth_call", [{"to": token, "data": encode_balance_of(holder)}, block_tag]) or "0x0", 16)
    checked: list[dict[str, Any]] = []
    for slot in range(max_slots):
        key = mapping_storage_key("bsc", holder, slot)
        value = int(storage_at_block(token, key, block_tag), 16)
        row = {"slot": slot, "match": value == expected}
        checked.append(row)
        if value == expected and expected > 0:
            return {"status": "found", "slot": slot, "holder_balance_raw": str(expected), "checked": checked}
    return {"status": "not_found", "slot": None, "holder_balance_raw": str(expected), "checked": checked}


def readback_state_override(token: str, fake_holder: str, balance_slot: int, amount: int, block_tag: str) -> dict[str, Any]:
    key = mapping_storage_key("bsc", fake_holder, balance_slot)
    override = {
        token: {
            "stateDiff": {
                key: "0x" + hex(amount)[2:].rjust(64, "0"),
            }
        }
    }
    try:
        raw = rpc_call("bsc", "eth_call", [{"to": token, "data": encode_balance_of(fake_holder)}, block_tag, override]) or "0x0"
    except Exception as exc:
        return {"status": "state_override_failed", "detail": str(exc)[:180]}
    value = int(raw, 16)
    return {"status": "readback_ok" if value == amount else "readback_mismatch", "expected_raw": str(amount), "actual_raw": str(value)}


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Pancake v4 State Override Probe",
        "",
        f"- status: `{result['status']}`",
        f"- block: `{result['block_number']}`",
        f"- token: `{result['token']}`",
        f"- rich_holder: `{result['rich_holder']}`",
        f"- balance_slot_status: `{result['balance_slot']['status']}`",
        f"- balance_slot: `{result['balance_slot'].get('slot')}`",
        f"- readback_status: `{result['readback'].get('status')}`",
        "",
        "## Scope",
        "",
        "- This probe only verifies RPC stateOverride readback for ERC-20 balance storage.",
        "- It does not execute Pancake v4 Universal Router or prove sellability.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe BSC stateOverride prerequisites for Pancake v4 roundtrip simulation.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--token", default=BSC_USDT)
    parser.add_argument("--rich-holder", default=DEFAULT_RICH_HOLDER)
    parser.add_argument("--fake-holder", default=DEFAULT_FAKE_HOLDER)
    parser.add_argument("--max-slots", type=int, default=12)
    parser.add_argument("--confirmations", type=int, default=5)
    parser.add_argument("--amount", type=int, default=1_234_567_890_123_456_789)
    args = parser.parse_args()

    latest = int(rpc_call("bsc", "eth_blockNumber", []), 16)
    block_number = max(0, latest - max(0, args.confirmations))
    block_tag = hex(block_number)
    slot_result = find_balance_slot(args.token.lower(), args.rich_holder.lower(), args.max_slots, block_tag)
    if slot_result.get("slot") is None:
        readback = {"status": "skipped_no_balance_slot"}
        status = "blocked"
    else:
        readback = readback_state_override(args.token.lower(), args.fake_holder.lower(), int(slot_result["slot"]), args.amount, block_tag)
        status = "ok" if readback.get("status") == "readback_ok" else "blocked"
    result = {
        "schema": "pancake_v4_state_override_probe.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "chain": "bsc",
        "block_tag": block_tag,
        "block_number": block_number,
        "token": args.token.lower(),
        "rich_holder": args.rich_holder.lower(),
        "fake_holder": args.fake_holder.lower(),
        "balance_slot": slot_result,
        "readback": readback,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(result), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
