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

from sniper_engine.rpc import rpc_call


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_samples" / "decoded_execute"
COMMAND_NAMES = {
    "00": "V3_SWAP_EXACT_IN_OR_UNKNOWN",
    "0a": "PERMIT2_PERMIT_OR_UNKNOWN",
    "10": "V4_SWAP",
}
ACTION_NAMES = {
    "06": "SWAP_EXACT_IN_SINGLE",
    "0b": "SETTLE",
    "0e": "TAKE_ALL",
}


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def word(data: str, pos: int) -> int:
    return int(data[pos : pos + 64], 16)


def word_hex(data: str, pos: int) -> str:
    return "0x" + data[pos : pos + 64]


def address_from_word(data: str, pos: int) -> str:
    return "0x" + data[pos + 24 : pos + 64]


def read_bytes(data: str, pos: int) -> str:
    length = word(data, pos)
    return data[pos + 64 : pos + 64 + length * 2]


def decode_dynamic_bytes_array(data: str, offset_words: int) -> list[str]:
    array_start = offset_words * 2
    length = word(data, array_start)
    values: list[str] = []
    for index in range(length):
        element_offset = word(data, array_start + 64 + index * 64)
        element_pos = array_start + 64 + element_offset * 2
        values.append(read_bytes(data, element_pos))
    return values


def decode_execute_input(input_data: str) -> dict[str, Any]:
    selector = input_data[:10]
    data = input_data[10:]
    if selector not in {"0x3593564c", "0x24856bc3"}:
        return {"selector": selector, "decode_status": "unsupported_selector"}
    command_offset = word(data, 0)
    inputs_offset = word(data, 64)
    deadline = word(data, 128) if selector == "0x3593564c" else None
    commands = read_bytes(data, command_offset * 2)
    inputs = decode_dynamic_bytes_array(data, inputs_offset)
    command_bytes = [commands[i : i + 2] for i in range(0, len(commands), 2)]
    return {
        "selector": selector,
        "deadline": deadline,
        "commands": [
            {
                "index": index,
                "command": command,
                "name": COMMAND_NAMES.get(command, "UNKNOWN"),
                "input_bytes": len(inputs[index]) // 2 if index < len(inputs) else 0,
                "decoded_input": decode_command_input(command, inputs[index]) if index < len(inputs) else {},
            }
            for index, command in enumerate(command_bytes)
        ],
        "input_count": len(inputs),
    }


def decode_command_input(command: str, raw: str) -> dict[str, Any]:
    if command == "10":
        return decode_v4_swap_input(raw)
    return {"raw_head": raw[:160], "raw_bytes": len(raw) // 2}


def decode_v4_swap_input(raw: str) -> dict[str, Any]:
    actions_offset = word(raw, 0)
    params_offset = word(raw, 64)
    actions = read_bytes(raw, actions_offset * 2)
    params = decode_dynamic_bytes_array(raw, params_offset)
    action_bytes = [actions[i : i + 2] for i in range(0, len(actions), 2)]
    decoded = []
    for index, action in enumerate(action_bytes):
        param = params[index] if index < len(params) else ""
        decoded.append(
            {
                "index": index,
                "action": action,
                "name": ACTION_NAMES.get(action, "UNKNOWN"),
                "param_bytes": len(param) // 2,
                "decoded_param": decode_v4_action_param(action, param),
            }
        )
    return {"actions": decoded, "action_count": len(action_bytes), "param_count": len(params)}


def decode_v4_action_param(action: str, raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    if action == "06":
        return decode_swap_exact_in_single(raw)
    if action == "0b" and len(raw) >= 192:
        return {
            "currency": address_from_word(raw, 0),
            "amount": str(word(raw, 64)),
            "payer_is_user": bool(word(raw, 128)),
        }
    if action == "0e" and len(raw) >= 192:
        return {
            "currency": address_from_word(raw, 0),
            "recipient": address_from_word(raw, 64),
            "amount_minimum": str(word(raw, 128)),
        }
    return {"raw_head": raw[:160], "raw_bytes": len(raw) // 2}


def decode_swap_exact_in_single(raw: str) -> dict[str, Any]:
    # Pancake v4 action 0x06 in observed ARX samples:
    # (PoolKey key, bool zeroForOne, uint128 amountIn, uint128 amountOutMinimum, bytes hookData)
    # PoolKey is decoded from the inline tuple that follows the leading tuple offset.
    if len(raw) < 64 * 12:
        return {"raw_head": raw[:160], "raw_bytes": len(raw) // 2, "decode_status": "too_short"}
    hook_data_offset = word(raw, 64 * 10)
    tuple_body_start = 64
    hook_data_pos = tuple_body_start + hook_data_offset * 2
    hook_data_length = word(raw, hook_data_pos) if hook_data_pos + 64 <= len(raw) else None
    return {
        "pool_key": {
            "currency0": address_from_word(raw, 64),
            "currency1": address_from_word(raw, 128),
            "hooks": address_from_word(raw, 192),
            "pool_manager": address_from_word(raw, 256),
            "fee": word(raw, 320),
            "parameters": word_hex(raw, 384),
        },
        "zero_for_one": bool(word(raw, 448)),
        "amount_in": str(word(raw, 512)),
        "amount_out_minimum": str(word(raw, 576)),
        "hook_data_length": hook_data_length,
    }


def decode_tx(chain: str, tx_hash: str) -> dict[str, Any]:
    tx = rpc_call(chain, "eth_getTransactionByHash", [tx_hash])
    return {
        "schema": "pancake_v4_execute_decode.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain": chain,
        "tx_hash": norm(tx_hash),
        "tx_to": norm((tx or {}).get("to")),
        "from": norm((tx or {}).get("from")),
        "input_decode": decode_execute_input(str((tx or {}).get("input") or "")),
    }


def markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Pancake v4 Execute Decode", ""]
    for result in results:
        lines.append(f"## `{result['tx_hash'][:10]}...{result['tx_hash'][-6:]}`")
        lines.append("")
        lines.append(f"- to: `{result['tx_to']}`")
        decoded = result["input_decode"]
        lines.append(f"- selector: `{decoded.get('selector')}`")
        for command in decoded.get("commands", []):
            lines.append(f"- command {command['index']}: `{command['command']}` {command['name']}")
            for action in command.get("decoded_input", {}).get("actions", []):
                lines.append(f"  - action {action['index']}: `{action['action']}` {action['name']}")
                param = action.get("decoded_param", {})
                if action["name"] == "SWAP_EXACT_IN_SINGLE":
                    pool_key = param.get("pool_key", {})
                    lines.append(
                        "    - pool: "
                        f"`{pool_key.get('currency0')}` -> `{pool_key.get('currency1')}`, "
                        f"hook `{pool_key.get('hooks')}`, manager `{pool_key.get('pool_manager')}`"
                    )
                    lines.append(
                        f"    - zero_for_one={param.get('zero_for_one')} amount_in={param.get('amount_in')} "
                        f"amount_out_min={param.get('amount_out_minimum')}"
                    )
                elif param:
                    lines.append(f"    - {json.dumps(param, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode Pancake v4 Universal Router execute calldata without external ABI dependencies.")
    parser.add_argument("--chain", default="bsc", choices=["bsc"], help="EVM chain")
    parser.add_argument("--tx", action="append", required=True, help="Transaction hash; repeatable")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    args = parser.parse_args()

    results = [decode_tx(args.chain, tx_hash) for tx_hash in args.tx]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(results), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
