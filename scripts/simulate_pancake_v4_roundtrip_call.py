#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.alpha_opening_block_watch import (
    decode_first_uint,
    encode_address_word,
    encode_allowance,
    encode_balance_of,
    encode_infinity_cl_quote_exact_input_single,
    encode_uint,
    mapping_storage_key,
    strip0x,
    web3_keccak_word,
)
from scripts.build_pancake_v4_roundtrip_fixture import ARX_POOL_KEY, UNIVERSAL_ROUTER, build_fixture
from sniper_engine.rpc import rpc_call


DEFAULT_OUT_DIR = ROOT / "output" / "pancake_v4_roundtrip_call"
BSC_USDT = ARX_POOL_KEY["currency0"].lower()
PANCAKE_PERMIT2 = "0x31c2f6fcff4f8759b3bd5bf0e1084a055615c768"
PANCAKE_CL_QUOTER = "0xd0737c9762912dd34c3271197e362aa736df0926"
DEFAULT_RICH_HOLDER = "0x8894e0a0c962cb723c1976a4421c95949be2d4e3"
DEFAULT_ALLOWANCE_OWNER = "0x9488190518d236017933b24ee0a50ddbbe0f943"
DEFAULT_FAKE_HOLDER = "0x0000000000000000000000000000000000000abc"
PERMIT2_ALLOWANCE_SELECTOR = "0x927da105"
DEFAULT_QUOTE_BALANCE_SLOT = 1
DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT = 2
DEFAULT_PERMIT2_ALLOWANCE_SLOT = 1
MAX_UINT256 = 2**256 - 1
MAX_UINT160 = 2**160 - 1
MAX_UINT48 = 2**48 - 1


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def uint256_hex(value: int) -> str:
    return "0x" + int(value).to_bytes(32, "big").hex()


def call_raw(to_address: str, data: str, block_tag: str, override: dict[str, Any] | None = None) -> str:
    params: list[Any] = [{"to": norm(to_address), "data": data}, block_tag]
    if override is not None:
        params.append(override)
    return rpc_call("bsc", "eth_call", params) or "0x"


def call_uint(to_address: str, data: str, block_tag: str, override: dict[str, Any] | None = None) -> int:
    return int(call_raw(to_address, data, block_tag, override) or "0x0", 16)


def storage_at(contract: str, key: str, block_tag: str) -> int:
    raw = rpc_call("bsc", "eth_getStorageAt", [norm(contract), key, block_tag]) or "0x0"
    return int(raw, 16)


def permit2_allowance_call(owner: str, token: str, spender: str) -> str:
    return PERMIT2_ALLOWANCE_SELECTOR + encode_address_word(owner) + encode_address_word(token) + encode_address_word(spender)


def decode_permit2_allowance(raw: str) -> dict[str, int]:
    data = strip0x(raw or "0x")
    if len(data) < 64 * 3:
        return {"amount": 0, "expiration": 0, "nonce": 0}
    return {
        "amount": int(data[0:64], 16),
        "expiration": int(data[64:128], 16),
        "nonce": int(data[128:192], 16),
    }


def pack_permit2_allowance(amount: int, expiration: int, nonce: int) -> int:
    if amount >= 2**160 or expiration >= 2**48 or nonce >= 2**48:
        raise ValueError("permit2 allowance field exceeds packed width")
    return (nonce << 208) | (expiration << 160) | amount


def permit2_storage_key(owner: str, token: str, spender: str, slot: int) -> str:
    owner_slot = web3_keccak_word("bsc", encode_address_word(owner) + encode_uint(slot))
    token_slot = web3_keccak_word("bsc", encode_address_word(token) + strip0x(owner_slot))
    return web3_keccak_word("bsc", encode_address_word(spender) + strip0x(token_slot))


def find_balance_slot(token: str, holder: str, max_slots: int, block_tag: str) -> dict[str, Any]:
    expected = call_uint(token, encode_balance_of(holder), block_tag)
    for slot in range(max_slots):
        key = mapping_storage_key("bsc", holder, slot)
        value = storage_at(token, key, block_tag)
        if expected > 0 and value == expected:
            return {"status": "found", "slot": slot, "holder_balance_raw": str(expected)}
    return {"status": "not_found", "slot": None, "holder_balance_raw": str(expected)}


def find_erc20_allowance_slot(token: str, owner: str, spender: str, max_slots: int, block_tag: str) -> dict[str, Any]:
    expected = call_uint(token, encode_allowance(owner, spender), block_tag)
    for slot in range(max_slots):
        owner_slot = web3_keccak_word("bsc", encode_address_word(owner) + encode_uint(slot))
        key = web3_keccak_word("bsc", encode_address_word(spender) + strip0x(owner_slot))
        value = storage_at(token, key, block_tag)
        if expected > 0 and value == expected:
            return {"status": "found", "slot": slot, "allowance_raw": str(expected)}
    return {"status": "not_found", "slot": None, "allowance_raw": str(expected)}


def find_permit2_allowance_slot(
    permit2: str,
    owner: str,
    token: str,
    spender: str,
    max_slots: int,
    block_tag: str,
) -> dict[str, Any]:
    decoded = decode_permit2_allowance(call_raw(permit2, permit2_allowance_call(owner, token, spender), block_tag))
    expected = pack_permit2_allowance(decoded["amount"], decoded["expiration"], decoded["nonce"])
    for slot in range(max_slots):
        key = permit2_storage_key(owner, token, spender, slot)
        value = storage_at(permit2, key, block_tag)
        if expected > 0 and value == expected:
            return {"status": "found", "slot": slot, "allowance": {k: str(v) for k, v in decoded.items()}}
    return {"status": "not_found", "slot": None, "allowance": {k: str(v) for k, v in decoded.items()}}


def fallback_slot_result(result: dict[str, Any] | None, default_slot: int, detail: str = "") -> dict[str, Any]:
    if result and result.get("slot") is not None:
        return result
    status = "default_slot_used"
    if result and result.get("status") == "not_found":
        status = "not_found_default_slot_used"
    if detail:
        status = "scan_failed_default_slot_used"
    merged = dict(result or {})
    merged.update({"status": status, "slot": default_slot})
    if detail:
        merged["detail"] = detail[:180]
    return merged


def readback_override(
    token: str,
    permit2: str,
    router: str,
    fake_holder: str,
    amount: int,
    block_tag: str,
    override: dict[str, Any],
) -> dict[str, Any]:
    balance = call_uint(token, encode_balance_of(fake_holder), block_tag, override)
    token_allowance = call_uint(token, encode_allowance(fake_holder, permit2), block_tag, override)
    permit2_allowance = decode_permit2_allowance(call_raw(permit2, permit2_allowance_call(fake_holder, token, router), block_tag, override))
    ok = (
        balance >= amount
        and token_allowance == MAX_UINT256
        and permit2_allowance["amount"] == MAX_UINT160
        and permit2_allowance["expiration"] == MAX_UINT48
    )
    return {
        "status": "readback_ok" if ok else "readback_mismatch",
        "balance_raw": str(balance),
        "token_allowance_raw": str(token_allowance),
        "permit2_allowance": {key: str(value) for key, value in permit2_allowance.items()},
    }


def quote_buy_output(pool_key: dict[str, Any], buy_amount: int, block_tag: str, zero_for_one: bool) -> dict[str, Any]:
    key = dict(pool_key)
    key["zero_for_one"] = zero_for_one
    data = encode_infinity_cl_quote_exact_input_single(key, buy_amount)
    try:
        raw = call_raw(PANCAKE_CL_QUOTER, data, block_tag)
        amount = decode_first_uint(raw)
        return {"status": "quote_ok" if amount > 0 else "quote_zero", "amount_raw": str(amount)}
    except Exception as exc:
        return {"status": "quote_failed", "detail": str(exc)[:180], "amount_raw": "0"}


def build_roundtrip_calldata(
    args: argparse.Namespace,
    sell_amount: int,
    pool_key: dict[str, Any],
    buy_zero_for_one: bool,
    sell_amount_out_minimum: int | None = None,
) -> dict[str, Any]:
    fixture_args = SimpleNamespace(
        out_dir=args.out_dir,
        deadline=args.deadline,
        buy_amount=args.buy_amount,
        buy_amount_out_minimum=args.buy_amount_out_minimum,
        sell_amount=sell_amount,
        sell_amount_out_minimum=args.sell_amount_out_minimum if sell_amount_out_minimum is None else sell_amount_out_minimum,
        pool_key=pool_key,
        buy_zero_for_one=buy_zero_for_one,
        sell_zero_for_one=not buy_zero_for_one,
    )
    return build_fixture(fixture_args)


def execute_roundtrip_call(
    args: argparse.Namespace,
    sell_amount: int,
    pool_key: dict[str, Any],
    buy_zero_for_one: bool,
    fake_holder: str,
    router: str,
    block_tag: str,
    override: dict[str, Any],
    sell_amount_out_minimum: int,
) -> dict[str, Any]:
    fixture = build_roundtrip_calldata(args, sell_amount, pool_key, buy_zero_for_one, sell_amount_out_minimum)
    tx = {
        "from": fake_holder,
        "to": router,
        "gas": "0x1312d00",
        "data": fixture["calldata"],
    }
    try:
        result = rpc_call("bsc", "eth_call", [tx, block_tag, override]) or "0x"
        return {
            "status": "success",
            "return": result,
            "calldata": fixture["calldata"],
            "sell_amount_out_minimum_raw": str(sell_amount_out_minimum),
            "fixture": {
                "calldata_selector": "0x3593564c",
                "commands": ["10", "10"],
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "detail": str(exc)[:240],
            "sell_amount_out_minimum_raw": str(sell_amount_out_minimum),
        }


def estimate_quote_recovery(
    args: argparse.Namespace,
    sell_amount: int,
    pool_key: dict[str, Any],
    buy_zero_for_one: bool,
    fake_holder: str,
    router: str,
    block_tag: str,
    override: dict[str, Any],
) -> dict[str, Any]:
    high = int(args.recovery_high_raw or args.buy_amount)
    if high <= 0:
        return {"status": "skipped", "detail": "bad_recovery_high", "calls": 0}
    low = 0
    calls = 0
    last_failure = ""
    for _ in range(max(1, int(args.recovery_iterations))):
        if low >= high:
            break
        mid = (low + high + 1) // 2
        probe = execute_roundtrip_call(args, sell_amount, pool_key, buy_zero_for_one, fake_holder, router, block_tag, override, mid)
        calls += 1
        if probe["status"] == "success":
            low = mid
        else:
            high = mid - 1
            last_failure = probe.get("detail", "")
    recovery_rate = Decimal(low) / Decimal(args.buy_amount) if args.buy_amount else Decimal(0)
    return {
        "status": "estimated",
        "quote_recovered_raw": str(low),
        "recovery_rate": str(recovery_rate),
        "calls": calls,
        "last_failure": last_failure,
        "search_high_raw": str(int(args.recovery_high_raw or args.buy_amount)),
    }


def pool_key_from_args(args: argparse.Namespace) -> dict[str, Any]:
    pool_key = dict(ARX_POOL_KEY)
    for attr in ["currency0", "currency1", "hooks", "pool_manager", "parameters"]:
        value = getattr(args, attr, None)
        if value:
            pool_key[attr] = norm(value)
    if args.fee is not None:
        pool_key["fee"] = int(args.fee)
    return pool_key


def build_state_override(
    token: str,
    permit2: str,
    router: str,
    fake_holder: str,
    balance_slot: int,
    token_allowance_slot: int,
    permit2_allowance_slot: int,
    buy_amount: int,
) -> dict[str, Any]:
    balance_key = mapping_storage_key("bsc", fake_holder, balance_slot)
    owner_slot = web3_keccak_word("bsc", encode_address_word(fake_holder) + encode_uint(token_allowance_slot))
    token_allowance_key = web3_keccak_word("bsc", encode_address_word(permit2) + strip0x(owner_slot))
    packed_permit2 = pack_permit2_allowance(MAX_UINT160, MAX_UINT48, 0)
    permit2_key = permit2_storage_key(fake_holder, token, router, permit2_allowance_slot)
    return {
        token: {
            "stateDiff": {
                balance_key: uint256_hex(buy_amount),
                token_allowance_key: uint256_hex(MAX_UINT256),
            }
        },
        permit2: {
            "stateDiff": {
                permit2_key: uint256_hex(packed_permit2),
            }
        },
        fake_holder: {"balance": "0x3635c9adc5dea00000"},
    }


def trace_call_probe(from_address: str, to_address: str, calldata: str, block_tag: str, override: dict[str, Any]) -> dict[str, Any]:
    tx = {"from": from_address, "to": to_address, "gas": "0x1312d00", "data": calldata}
    try:
        rpc_call("bsc", "debug_traceCall", [tx, block_tag, {"tracer": "callTracer"}, override])
    except Exception as exc:
        return {"status": "unavailable", "detail": str(exc)[:180]}
    return {"status": "available"}


def sellability_gate(status: str, eth_call: dict[str, Any], debug_trace: dict[str, Any]) -> dict[str, Any]:
    if status == "roundtrip_eth_call_success_with_recovery_rate":
        recovery_rate = Decimal(str(eth_call.get("recovery_rate") or "0"))
        minimum_recovery_rate = Decimal(str(eth_call.get("minimum_recovery_rate") or "0.80"))
        passed = recovery_rate >= minimum_recovery_rate
        return {
            "status": "recovery_rate_verified" if passed else "blocked_low_recovery",
            "gate": "infinity_recovery_rate_verified" if passed else "blocked_infinity_low_recovery",
            "can_follow": passed,
            "can_sell_proven": passed,
            "quote_recovered_raw": eth_call.get("quote_recovered_raw"),
            "recovery_rate": str(recovery_rate),
            "minimum_recovery_rate": str(minimum_recovery_rate),
            "reason": (
                "Universal Router buy->sell eth_call succeeded and quote recovery was estimated through "
                "TAKE_ALL amountMinimum binary search."
            ),
        }
    if status == "roundtrip_eth_call_success_no_recovery_rate":
        trace_status = str(debug_trace.get("status") or "skipped")
        return {
            "status": "unknown_recovery_unverified",
            "gate": "blocked_infinity_recovery_unverified",
            "can_follow": False,
            "can_sell_proven": False,
            "recovery_rate": None,
            "reason": (
                "Universal Router buy->sell eth_call did not revert, but the RPC did not expose final "
                f"quote-token recovery. debug_traceCall={trace_status}."
            ),
        }
    if status == "roundtrip_eth_call_reverted":
        return {
            "status": "blocked_execution_reverted",
            "gate": "blocked_infinity_roundtrip_failed",
            "can_follow": False,
            "can_sell_proven": False,
            "recovery_rate": None,
            "reason": str(eth_call.get("detail") or "Universal Router roundtrip eth_call reverted")[:240],
        }
    if status == "state_override_blocked":
        return {
            "status": "unknown_state_override_failed",
            "gate": "blocked_infinity_readback_failed",
            "can_follow": False,
            "can_sell_proven": False,
            "recovery_rate": None,
            "reason": "stateOverride balance/allowance readback did not pass",
        }
    return {
        "status": "unknown",
        "gate": "blocked_unverified",
        "can_follow": False,
        "can_sell_proven": False,
        "recovery_rate": None,
        "reason": f"probe status={status}",
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Pancake v4 Roundtrip eth_call Probe",
        "",
        f"- status: `{result['status']}`",
        f"- block: `{result['block_number']}`",
        f"- router: `{result['router']}`",
        f"- token: `{result['token']}`",
        f"- quote: `{result['quote']}`",
        f"- buy_amount_raw: `{result['roundtrip']['buy_amount_raw']}`",
        f"- sell_amount_raw: `{result['roundtrip']['sell_amount_raw']}`",
        f"- readback: `{result.get('readback', {}).get('status')}`",
        f"- eth_call: `{result.get('eth_call', {}).get('status')}`",
        f"- debug_traceCall: `{result.get('debug_trace_call', {}).get('status')}`",
        f"- sellability_gate: `{result.get('sellability', {}).get('gate')}`",
        f"- can_follow: `{result.get('sellability', {}).get('can_follow')}`",
        f"- quote_recovered_raw: `{result.get('sellability', {}).get('quote_recovered_raw')}`",
        f"- recovery_rate: `{result.get('sellability', {}).get('recovery_rate')}`",
        "",
        "## Scope",
        "",
    ]
    lines.extend(f"- {item}" for item in result["scope"])
    if result.get("slot_detection"):
        lines.extend(["", "## Slot Detection", ""])
        for key, value in result["slot_detection"].items():
            lines.append(f"- {key}: `{value.get('status')}` slot=`{value.get('slot')}`")
    if result.get("eth_call", {}).get("detail"):
        lines.extend(["", "## eth_call Detail", "", f"- {result['eth_call']['detail']}"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Pancake v4 Universal Router roundtrip eth_call probe.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--token", default=ARX_POOL_KEY["currency1"])
    parser.add_argument("--quote", default=BSC_USDT)
    parser.add_argument("--currency0")
    parser.add_argument("--currency1")
    parser.add_argument("--hooks")
    parser.add_argument("--pool-manager")
    parser.add_argument("--fee", type=int)
    parser.add_argument("--parameters")
    parser.add_argument("--router", default=UNIVERSAL_ROUTER)
    parser.add_argument("--permit2", default=PANCAKE_PERMIT2)
    parser.add_argument("--rich-holder", default=DEFAULT_RICH_HOLDER)
    parser.add_argument("--allowance-owner", default=DEFAULT_ALLOWANCE_OWNER)
    parser.add_argument("--fake-holder", default=DEFAULT_FAKE_HOLDER)
    parser.add_argument("--buy-amount", type=int, default=10_000_000_000_000_000_000)
    parser.add_argument("--buy-amount-out-minimum", type=int, default=0)
    parser.add_argument("--sell-amount", type=int, default=1_000_000_000_000_000_000)
    parser.add_argument("--sell-amount-out-minimum", type=int, default=0)
    parser.add_argument("--sell-quote-share-bps", type=int, default=0)
    parser.add_argument("--skip-recovery-estimate", action="store_true")
    parser.add_argument("--recovery-iterations", type=int, default=48)
    parser.add_argument("--recovery-high-raw", type=int, default=0)
    parser.add_argument("--min-recovery-rate", default="0.80")
    parser.add_argument("--deadline", type=int, default=4_102_444_800)
    parser.add_argument("--confirmations", type=int, default=5)
    parser.add_argument("--pin-block", action="store_true")
    parser.add_argument("--scan-slots", action="store_true")
    parser.add_argument("--max-slots", type=int, default=16)
    parser.add_argument("--probe-debug-trace", action="store_true")
    args = parser.parse_args()

    latest = int(rpc_call("bsc", "eth_blockNumber", []), 16)
    block_number = max(0, latest - max(0, args.confirmations))
    block_tag = hex(block_number) if args.pin_block else "latest"
    quote = norm(args.quote)
    token = norm(args.token)
    router = norm(args.router)
    permit2 = norm(args.permit2)
    fake_holder = norm(args.fake_holder)
    pool_key = pool_key_from_args(args)
    buy_zero_for_one = quote == norm(pool_key["currency0"])

    status = "blocked"
    eth_call = {"status": "skipped"}
    debug_trace = {"status": "skipped"}
    fixture_summary = {}
    quote_probe = quote_buy_output(pool_key, args.buy_amount, block_tag, buy_zero_for_one)
    sell_amount = args.sell_amount
    if args.sell_quote_share_bps > 0 and int(quote_probe.get("amount_raw") or "0") > 0:
        sell_amount = max(1, int(quote_probe["amount_raw"]) * args.sell_quote_share_bps // 10_000)

    scope = [
        "This probe executes synthetic Universal Router buy->sell calldata through eth_call with stateOverride readbacks.",
        "It estimates quote recovery by binary-searching the sell leg TAKE_ALL amountMinimum through repeated eth_call probes.",
        "The default sell leg is a configured token amount, so it is not proof of full-output sellability unless sized by a verified quote.",
        "eth_call success with recovery_rate proves this synthetic route recovered at least the reported quote amount at the pinned block.",
        "Trading signals still need local launch rules before follow wording; this script only closes the v4 sellability measurement gap.",
    ]

    try:
        if args.scan_slots:
            try:
                balance_slot = find_balance_slot(quote, norm(args.rich_holder), args.max_slots, block_tag)
                balance_slot = fallback_slot_result(balance_slot, DEFAULT_QUOTE_BALANCE_SLOT)
            except Exception as exc:
                balance_slot = fallback_slot_result(None, DEFAULT_QUOTE_BALANCE_SLOT, str(exc))
            try:
                token_allowance_slot = find_erc20_allowance_slot(quote, norm(args.allowance_owner), permit2, args.max_slots, block_tag)
                token_allowance_slot = fallback_slot_result(token_allowance_slot, DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT)
            except Exception as exc:
                token_allowance_slot = fallback_slot_result(None, DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT, str(exc))
            try:
                permit2_allowance_slot = find_permit2_allowance_slot(
                    permit2,
                    norm(args.allowance_owner),
                    quote,
                    router,
                    args.max_slots,
                    block_tag,
                )
                permit2_allowance_slot = fallback_slot_result(permit2_allowance_slot, DEFAULT_PERMIT2_ALLOWANCE_SLOT)
            except Exception as exc:
                permit2_allowance_slot = fallback_slot_result(None, DEFAULT_PERMIT2_ALLOWANCE_SLOT, str(exc))
        else:
            balance_slot = {"status": "configured_default_slot", "slot": DEFAULT_QUOTE_BALANCE_SLOT}
            token_allowance_slot = {"status": "configured_default_slot", "slot": DEFAULT_QUOTE_TOKEN_ALLOWANCE_SLOT}
            permit2_allowance_slot = {"status": "configured_default_slot", "slot": DEFAULT_PERMIT2_ALLOWANCE_SLOT}
        slot_detection = {
            "quote_balance": balance_slot,
            "quote_token_allowance_to_permit2": token_allowance_slot,
            "permit2_allowance_to_router": permit2_allowance_slot,
        }
        if any(item.get("slot") is None for item in slot_detection.values()):
            readback = {"status": "skipped_slot_not_found"}
            status = "state_override_blocked"
        else:
            override = build_state_override(
                quote,
                permit2,
                router,
                fake_holder,
                int(balance_slot["slot"]),
                int(token_allowance_slot["slot"]),
                int(permit2_allowance_slot["slot"]),
                args.buy_amount,
            )
            readback = readback_override(quote, permit2, router, fake_holder, args.buy_amount, block_tag, override)
            if readback["status"] != "readback_ok":
                status = "state_override_blocked"
            else:
                base_call = execute_roundtrip_call(
                    args,
                    sell_amount,
                    pool_key,
                    buy_zero_for_one,
                    fake_holder,
                    router,
                    block_tag,
                    override,
                    args.sell_amount_out_minimum,
                )
                if base_call["status"] == "success":
                    eth_call = {"status": "success", "return": base_call.get("return", "0x")}
                    status = "roundtrip_eth_call_success_no_recovery_rate"
                    if not args.skip_recovery_estimate:
                        recovery = estimate_quote_recovery(
                            args,
                            sell_amount,
                            pool_key,
                            buy_zero_for_one,
                            fake_holder,
                            router,
                            block_tag,
                            override,
                        )
                        eth_call["recovery_estimate"] = recovery
                        if recovery.get("status") == "estimated":
                            eth_call["quote_recovered_raw"] = recovery.get("quote_recovered_raw")
                            eth_call["recovery_rate"] = recovery.get("recovery_rate")
                            eth_call["minimum_recovery_rate"] = args.min_recovery_rate
                            status = "roundtrip_eth_call_success_with_recovery_rate"
                    if args.probe_debug_trace:
                        debug_trace = trace_call_probe(fake_holder, router, str(base_call.get("calldata") or "0x"), block_tag, override)
                    fixture_summary = base_call.get("fixture", {})
                else:
                    eth_call = {"status": "reverted_or_failed", "detail": base_call.get("detail", "")}
                    status = "roundtrip_eth_call_reverted"
                    fixture_summary = {}
    except Exception as exc:
        slot_detection = {}
        readback = {"status": "not_run"}
        fixture_summary = {}
        status = "probe_failed"
        eth_call = {"status": "probe_failed", "detail": str(exc)[:240]}

    result = {
        "schema": "pancake_v4_roundtrip_call_probe.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "chain": "bsc",
        "block_tag": block_tag,
        "block_number": block_number,
        "router": router,
        "permit2": permit2,
        "token": token,
        "quote": quote,
        "fake_holder": fake_holder,
        "roundtrip": {
            "buy_amount_raw": str(args.buy_amount),
            "sell_amount_raw": str(sell_amount),
            "sell_amount_source": "quote_share" if args.sell_quote_share_bps > 0 else "explicit",
            "sell_quote_share_bps": args.sell_quote_share_bps,
            "deadline": args.deadline,
            "buy_zero_for_one": buy_zero_for_one,
            "sell_zero_for_one": not buy_zero_for_one,
        },
        "pool_key": pool_key,
        "quote_probe": quote_probe,
        "slot_detection": slot_detection,
        "readback": readback,
        "eth_call": eth_call,
        "debug_trace_call": debug_trace,
        "sellability": sellability_gate(status, eth_call, debug_trace),
        "fixture": fixture_summary,
        "scope": scope,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(result), encoding="utf-8")
    print(json_path)
    print(md_path)
    print(status)
    return 0 if status in {"roundtrip_eth_call_success_no_recovery_rate", "roundtrip_eth_call_success_with_recovery_rate"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
