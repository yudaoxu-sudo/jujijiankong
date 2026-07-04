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

from scripts.decode_pancake_v4_execute import decode_execute_input


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_roundtrip_fixture"
SELECTOR_EXECUTE_WITH_DEADLINE = "0x3593564c"
COMMAND_V4_SWAP = "10"
ACTION_SWAP_EXACT_IN_SINGLE = "06"
ACTION_SETTLE = "0b"
ACTION_TAKE_ALL = "0e"

UNIVERSAL_ROUTER = "0xd9c500dff816a1da21a48a732d3498bf09dc9aeb"
ADDRESS_MSG_SENDER = "0x0000000000000000000000000000000000000001"
ADDRESS_THIS = "0x0000000000000000000000000000000000000002"

ARX_POOL_KEY = {
    "currency0": "0x55d398326f99059ff775485246999027b3197955",
    "currency1": "0xd5f6ef5deabe61e6d5cdb49bfb6f156f2c1ca715",
    "hooks": "0xb0bb171d333569cfd28a37f5c5dddaaa90ad46af",
    "pool_manager": "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b",
    "fee": 67,
    "parameters": "0x0000000000000000000000000000000000000000000000000000000000020045",
}


def strip0x(value: str) -> str:
    return str(value).lower().removeprefix("0x")


def pad32(hex_data: str) -> str:
    if len(hex_data) % 64 == 0:
        return hex_data
    return hex_data + "0" * (64 - len(hex_data) % 64)


def encode_uint(value: int) -> str:
    if value < 0:
        raise ValueError("uint cannot be negative")
    return f"{value:064x}"


def encode_bool(value: bool) -> str:
    return encode_uint(1 if value else 0)


def encode_address_word(address: str) -> str:
    raw = strip0x(address)
    if len(raw) != 40:
        raise ValueError(f"bad address: {address}")
    return "0" * 24 + raw


def encode_bytes32(value: str) -> str:
    raw = strip0x(value)
    if len(raw) != 64:
        raise ValueError(f"bad bytes32: {value}")
    return raw


def encode_bytes(raw_hex: str) -> str:
    raw = strip0x(raw_hex)
    if len(raw) % 2:
        raise ValueError("bytes hex must have even length")
    return encode_uint(len(raw) // 2) + pad32(raw)


def encode_bytes_array(values: list[str]) -> str:
    heads: list[str] = []
    tails: list[str] = []
    offset = 32 * len(values)
    for value in values:
        encoded = encode_bytes(value)
        heads.append(encode_uint(offset))
        tails.append(encoded)
        offset += len(encoded) // 2
    return encode_uint(len(values)) + "".join(heads) + "".join(tails)


def encode_v4_swap_input(actions: str, params: list[str]) -> str:
    actions_encoded = encode_bytes(actions)
    params_encoded = encode_bytes_array(params)
    actions_offset = 64
    params_offset = actions_offset + len(actions_encoded) // 2
    return encode_uint(actions_offset) + encode_uint(params_offset) + actions_encoded + params_encoded


def encode_execute_with_deadline(commands: str, inputs: list[str], deadline: int) -> str:
    commands_encoded = encode_bytes(commands)
    inputs_encoded = encode_bytes_array(inputs)
    commands_offset = 96
    inputs_offset = commands_offset + len(commands_encoded) // 2
    data = encode_uint(commands_offset) + encode_uint(inputs_offset) + encode_uint(deadline)
    data += commands_encoded + inputs_encoded
    return SELECTOR_EXECUTE_WITH_DEADLINE + data


def encode_swap_exact_in_single(
    pool_key: dict[str, Any],
    *,
    zero_for_one: bool,
    amount_in: int,
    amount_out_minimum: int,
    hook_data: str = "",
) -> str:
    hook_encoded = encode_bytes(hook_data)
    tuple_body = (
        encode_address_word(pool_key["currency0"])
        + encode_address_word(pool_key["currency1"])
        + encode_address_word(pool_key["hooks"])
        + encode_address_word(pool_key["pool_manager"])
        + encode_uint(int(pool_key["fee"]))
        + encode_bytes32(pool_key["parameters"])
        + encode_bool(zero_for_one)
        + encode_uint(amount_in)
        + encode_uint(amount_out_minimum)
        + encode_uint(32 * 10)
        + hook_encoded
    )
    return encode_uint(32) + tuple_body


def encode_settle(currency: str, amount: int, payer_is_user: bool) -> str:
    return encode_address_word(currency) + encode_uint(amount) + encode_bool(payer_is_user)


def encode_take_all(currency: str, recipient: str, amount_minimum: int) -> str:
    return encode_address_word(currency) + encode_address_word(recipient) + encode_uint(amount_minimum)


def build_fixture(args: argparse.Namespace) -> dict[str, Any]:
    pool_key = dict(getattr(args, "pool_key", None) or ARX_POOL_KEY)
    buy_zero_for_one = bool(getattr(args, "buy_zero_for_one", True))
    sell_zero_for_one = bool(getattr(args, "sell_zero_for_one", not buy_zero_for_one))
    buy_input_currency = pool_key["currency0"] if buy_zero_for_one else pool_key["currency1"]
    buy_output_currency = pool_key["currency1"] if buy_zero_for_one else pool_key["currency0"]
    sell_input_currency = pool_key["currency0"] if sell_zero_for_one else pool_key["currency1"]
    sell_output_currency = pool_key["currency1"] if sell_zero_for_one else pool_key["currency0"]
    buy_actions = ACTION_SWAP_EXACT_IN_SINGLE + ACTION_SETTLE + ACTION_TAKE_ALL
    buy_params = [
        encode_swap_exact_in_single(
            pool_key,
            zero_for_one=buy_zero_for_one,
            amount_in=args.buy_amount,
            amount_out_minimum=args.buy_amount_out_minimum,
        ),
        encode_settle(buy_input_currency, args.buy_amount, True),
        encode_take_all(buy_output_currency, ADDRESS_THIS, 0),
    ]
    sell_actions = ACTION_SWAP_EXACT_IN_SINGLE + ACTION_SETTLE + ACTION_TAKE_ALL
    sell_params = [
        encode_swap_exact_in_single(
            pool_key,
            zero_for_one=sell_zero_for_one,
            amount_in=args.sell_amount,
            amount_out_minimum=args.sell_amount_out_minimum,
        ),
        encode_settle(sell_input_currency, args.sell_amount, False),
        encode_take_all(sell_output_currency, ADDRESS_MSG_SENDER, 0),
    ]
    buy_input = encode_v4_swap_input(buy_actions, buy_params)
    sell_input = encode_v4_swap_input(sell_actions, sell_params)
    calldata = encode_execute_with_deadline(COMMAND_V4_SWAP + COMMAND_V4_SWAP, [buy_input, sell_input], args.deadline)
    decoded = decode_execute_input(calldata)
    return {
        "schema": "pancake_v4_roundtrip_fixture.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "calldata_fixture_only",
        "chain": "bsc",
        "router": UNIVERSAL_ROUTER,
        "selector": SELECTOR_EXECUTE_WITH_DEADLINE,
        "commands": [COMMAND_V4_SWAP, COMMAND_V4_SWAP],
        "assumptions": [
            "This fixture only proves local calldata encoding and decoder agreement.",
            "It does not prove eth_call execution, recovery rate, Permit2 override, or sellability.",
            "ADDRESS_THIS and MSG_SENDER use Universal Router sentinel address conventions for synthetic same-call routing.",
            "Reviewed real ARX buy/sell samples are separate single-leg transactions with user recipients.",
        ],
        "pool_key": pool_key,
        "roundtrip": {
            "buy_quote_amount_in": str(args.buy_amount),
            "buy_token_amount_minimum": str(args.buy_amount_out_minimum),
            "sell_token_amount_in": str(args.sell_amount),
            "sell_quote_amount_minimum": str(args.sell_amount_out_minimum),
            "buy_take_all_recipient": ADDRESS_THIS,
            "sell_take_all_recipient": ADDRESS_MSG_SENDER,
            "sell_settle_payer_is_user": False,
            "buy_zero_for_one": buy_zero_for_one,
            "sell_zero_for_one": sell_zero_for_one,
        },
        "calldata": calldata,
        "decoded": decoded,
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Pancake v4 Roundtrip Calldata Fixture",
        "",
        f"- status: `{result['status']}`",
        f"- router: `{result['router']}`",
        f"- selector: `{result['selector']}`",
        f"- commands: `{''.join(result['commands'])}`",
        "",
        "## Scope",
        "",
    ]
    lines.extend(f"- {item}" for item in result["assumptions"])
    lines.extend(["", "## Roundtrip", ""])
    for key, value in result["roundtrip"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Decoded Commands", ""])
    for command in result["decoded"].get("commands", []):
        lines.append(f"- command {command['index']}: `{command['command']}` {command['name']}")
        for action in command.get("decoded_input", {}).get("actions", []):
            param = action.get("decoded_param", {})
            lines.append(f"  - action {action['index']}: `{action['action']}` {action['name']}")
            if action["name"] == "SWAP_EXACT_IN_SINGLE":
                pool = param.get("pool_key", {})
                lines.append(
                    f"    - zero_for_one={param.get('zero_for_one')} amount_in={param.get('amount_in')} "
                    f"amount_out_min={param.get('amount_out_minimum')}"
                )
                lines.append(f"    - pool: `{pool.get('currency0')}` -> `{pool.get('currency1')}`")
            elif param:
                lines.append(f"    - {json.dumps(param, ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local Pancake v4 Universal Router buy->sell calldata fixture.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--deadline", type=int, default=0)
    parser.add_argument("--buy-amount", type=int, default=51_000_000_000_000_000_000)
    parser.add_argument("--buy-amount-out-minimum", type=int, default=186_106_672_853_510_527_767)
    parser.add_argument("--sell-amount", type=int, default=186_106_672_853_510_527_767)
    parser.add_argument("--sell-amount-out-minimum", type=int, default=0)
    args = parser.parse_args()

    result = build_fixture(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(result), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
