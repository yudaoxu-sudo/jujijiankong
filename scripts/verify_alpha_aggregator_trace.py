#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.exchange_aggregator import score_exchange_aggregator_candidate


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x0000000000000000000000000000000000000000"
DEFAULT_NON_ALPHA_TOKENS = {
    # BSC common routing / quote assets. These often appear in Alpha custody
    # swap paths and must not be inferred as the target Alpha token.
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",  # BTCB
    "0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH
}


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def is_address(value: Any) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def topic_addr(topic: Any) -> str:
    text = norm(topic)
    if not text.startswith("0x"):
        return ""
    raw = text[2:]
    if len(raw) < 40:
        return ""
    return "0x" + raw[-40:]


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def nested_address(row: dict[str, Any], *paths: str) -> str:
    for path in paths:
        cur: Any = row
        for part in path.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if is_address(cur):
            return norm(cur)
    return ""


def extract_transfer_rows(payload: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set()
    for item in walk(payload):
        token = nested_address(item, "token", "tokenAddress", "contractAddress", "rawContract.address", "address")
        from_addr = nested_address(item, "from", "fromAddress", "from.address", "src")
        to_addr = nested_address(item, "to", "toAddress", "to.address", "dst")
        topics = item.get("topics") if isinstance(item.get("topics"), list) else []
        if len(topics) >= 3 and norm(topics[0]) == TRANSFER_TOPIC:
            token = nested_address(item, "address", "contractAddress")
            from_addr = topic_addr(topics[1])
            to_addr = topic_addr(topics[2])
        if not (is_address(token) and is_address(from_addr) and is_address(to_addr)):
            continue
        amount = str(item.get("amount") or item.get("value") or item.get("rawAmount") or "")
        tx_hash = norm(item.get("hash") or item.get("transactionHash") or item.get("tx") or "")
        key = (token, from_addr, to_addr, amount, tx_hash)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"token": token, "from": from_addr, "to": to_addr, "amount": amount, "tx": tx_hash})
    return rows


def extract_call_edges(payload: Any) -> list[tuple[str, str]]:
    edges = []
    seen = set()
    for item in walk(payload):
        topics = item.get("topics") if isinstance(item.get("topics"), list) else []
        if item.get("token") or item.get("tokenAddress") or item.get("contractAddress") or (
            len(topics) >= 3 and norm(topics[0]) == TRANSFER_TOPIC
        ):
            continue
        from_addr = nested_address(item, "from", "fromAddress", "from.address")
        to_addr = nested_address(item, "to", "toAddress", "to.address")
        if not (is_address(from_addr) and is_address(to_addr)):
            continue
        key = (from_addr, to_addr)
        if key in seen:
            continue
        seen.add(key)
        edges.append(key)
    return edges


def address_token_reuse(paths: list[Path], excluded_tokens: set[str]) -> dict[str, int]:
    token_sets: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        transfers = extract_transfer_rows(payload)
        alt_tokens = {row["token"] for row in transfers if row["token"] not in excluded_tokens}
        if not alt_tokens:
            continue
        touched = set()
        for row in transfers:
            touched.add(row["from"])
            touched.add(row["to"])
        for left, right in extract_call_edges(payload):
            touched.add(left)
            touched.add(right)
        for address in touched:
            if is_address(address) and address != ZERO:
                token_sets[address].update(alt_tokens)
    return {address: len(tokens) for address, tokens in token_sets.items()}


def distinct_alt_tokens(paths: list[Path], excluded_tokens: set[str]) -> set[str]:
    tokens = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in extract_transfer_rows(payload):
            if row["token"] not in excluded_tokens:
                tokens.add(row["token"])
    return tokens


def infer_alpha_token(payload: Any, excluded_tokens: set[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for row in extract_transfer_rows(payload):
        token = row["token"]
        if token and token not in excluded_tokens and token != ZERO:
            counts[token] += 1
    if not counts:
        raise RuntimeError("cannot infer token: no non-quote/non-routing Transfer rows found")
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def trace_roles(payload: Any, token: str, quote: str, known_router: str = "") -> dict[str, Any]:
    token = norm(token)
    quote = norm(quote)
    known_router = norm(known_router)
    transfers = extract_transfer_rows(payload)
    calls = extract_call_edges(payload)
    quote_participants = set()
    token_participants = set()
    for row in transfers:
        if row["token"] == quote:
            quote_participants.update([row["from"], row["to"]])
        if row["token"] == token:
            token_participants.update([row["from"], row["to"]])
    ignore = {ZERO, token, quote, ""}
    stable_candidates = sorted((quote_participants - token_participants) - ignore)
    alt_candidates = sorted((token_participants - quote_participants) - ignore)
    call_neighbors: dict[str, set[str]] = defaultdict(set)
    for left, right in calls:
        call_neighbors[left].add(right)
        call_neighbors[right].add(left)
    router_candidates = set()
    if known_router and any(known_router in edge for edge in calls):
        router_candidates.add(known_router)
    for address, neighbors in call_neighbors.items():
        if len(neighbors) >= 2 and address not in ignore:
            touches_stable = bool(neighbors & set(stable_candidates))
            touches_alt = bool(neighbors & set(alt_candidates))
            if touches_stable and touches_alt:
                router_candidates.add(address)
    stable_candidates = sorted(set(stable_candidates) - router_candidates)
    alt_candidate_set = set(alt_candidates) - router_candidates
    router_neighbors = set()
    for router in router_candidates:
        router_neighbors.update(call_neighbors.get(router, set()))
    pool_or_external = set()
    for row in transfers:
        if row["token"] != token:
            continue
        left = row["from"]
        right = row["to"]
        if left in alt_candidate_set and right in alt_candidate_set and left in router_neighbors:
            pool_or_external.add(left)
    alt_candidates = sorted(alt_candidate_set - pool_or_external)
    paired_pairs = []
    for stable in stable_candidates:
        for alt in alt_candidates:
            if alt in call_neighbors.get(stable, set()) or any(
                router in call_neighbors.get(stable, set()) and router in call_neighbors.get(alt, set())
                for router in router_candidates
            ):
                paired_pairs.append({"stable": stable, "alt": alt})
    return {
        "transfer_count": len(transfers),
        "call_edge_count": len(calls),
        "stable_custody_candidates": stable_candidates,
        "alt_custody_candidates": alt_candidates,
        "pool_or_external_candidates": sorted(pool_or_external),
        "router_candidates": sorted(router_candidates),
        "paired_custody_candidates": paired_pairs,
    }


def transfer_leg(row: dict[str, str], roles: dict[str, Any], token: str, quote: str) -> str:
    token = norm(token)
    quote = norm(quote)
    stable_set = set(roles.get("stable_custody_candidates") or [])
    alt_set = set(roles.get("alt_custody_candidates") or [])
    pool_set = set(roles.get("pool_or_external_candidates") or [])
    router_set = set(roles.get("router_candidates") or [])
    left = row["from"]
    right = row["to"]
    if (left in stable_set and right in alt_set) or (left in alt_set and right in stable_set):
        return "custody_internal_transfer"
    if row["token"] == quote:
        if left not in stable_set and right in stable_set:
            return "user_quote_to_stable_custody"
        if left in stable_set and right in router_set:
            return "quote_custody_to_router"
        if left in router_set or right in router_set:
            return "quote_router_or_pool_leg"
        if left in stable_set or right in stable_set:
            return "quote_custody_internal_leg"
        return "quote_transfer_other"
    if row["token"] == token:
        if left in pool_set or right in pool_set:
            return "token_router_or_pool_leg"
        if left in router_set or right in router_set:
            return "token_router_or_pool_leg"
        if left not in alt_set and right in alt_set:
            return "token_into_alt_custody"
        if left in alt_set and right not in router_set:
            return "alt_custody_token_out"
        if left in alt_set or right in alt_set:
            return "token_custody_internal_leg"
        return "token_transfer_other"
    if left in router_set or right in router_set:
        return "other_token_router_or_pool_leg"
    return "other_token_transfer"


def annotate_transfers(transfers: list[dict[str, str]], roles: dict[str, Any], token: str, quote: str) -> list[dict[str, str]]:
    return [{**row, "leg": transfer_leg(row, roles, token, quote)} for row in transfers]


def leg_summary(rows: list[dict[str, str]]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for row in rows:
        out[row["leg"]] += 1
    return dict(sorted(out.items()))


def trace_quality(
    paths: list[Path],
    excluded_tokens: set[str],
    roles: dict[str, Any],
    min_alpha_tokens: int,
) -> dict[str, Any]:
    tokens = distinct_alt_tokens(paths, excluded_tokens)
    warnings = []
    if len(tokens) < min_alpha_tokens:
        warnings.append(f"cross_token_sample_too_small:{len(tokens)}<{min_alpha_tokens}")
    if len(roles.get("stable_custody_candidates") or []) > 1:
        warnings.append("stable_custody_is_address_set")
    if not roles.get("paired_custody_candidates"):
        warnings.append("paired_custody_not_detected")
    if not roles.get("router_candidates"):
        warnings.append("router_not_detected")
    return {
        "distinct_alpha_tokens": len(tokens),
        "required_min_alpha_tokens": min_alpha_tokens,
        "history_files": max(0, len(paths) - 1),
        "warnings": warnings,
    }


def candidate_scores(roles: dict[str, Any], reuse: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    paired_addresses = {row["stable"] for row in roles["paired_custody_candidates"]} | {
        row["alt"] for row in roles["paired_custody_candidates"]
    }
    candidates = set(roles["stable_custody_candidates"]) | set(roles["alt_custody_candidates"]) | set(roles["router_candidates"])
    for address in sorted(candidates):
        features = {
            "shared_across_tokens": reuse.get(address, 0),
            "paired_custody_structure": address in paired_addresses,
            "shared_binance_wallet_router": address in set(roles["router_candidates"]),
        }
        scored = score_exchange_aggregator_candidate(features)
        out.append({"address": address, "features": features, **scored})
    return out


def build_report(
    input_path: Path,
    token: str,
    quote: str,
    router: str,
    history: list[Path],
    min_alpha_tokens: int,
    exclude_tokens: list[str],
) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    excluded_tokens = {norm(value) for value in exclude_tokens if norm(value)}
    excluded_tokens.update(DEFAULT_NON_ALPHA_TOKENS)
    excluded_tokens.add(norm(quote))
    if norm(token) in {"", "auto"}:
        token = infer_alpha_token(payload, excluded_tokens)
    roles = trace_roles(payload, token, quote, router)
    paths = [input_path, *history]
    reuse = address_token_reuse(paths, excluded_tokens)
    annotated = annotate_transfers(extract_transfer_rows(payload), roles, token, quote)
    return {
        "input": str(input_path),
        "dry_run": True,
        "config_write": False,
        "token": norm(token),
        "quote": norm(quote),
        "trace_quality": trace_quality(paths, excluded_tokens, roles, min_alpha_tokens),
        "roles": roles,
        "leg_summary": leg_summary(annotated),
        "annotated_transfers": annotated,
        "candidates": candidate_scores(roles, reuse),
        "manual_review_required": True,
        "next_step": "manually confirm candidates before adding allowlist entries",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Binance Alpha custody / aggregator evidence from saved traces.")
    parser.add_argument("--input", required=True, type=Path, help="JSON trace / receipt / transfer dump")
    parser.add_argument("--token", default="auto", help="Alpha token contract, or auto to infer from non-quote Transfer rows")
    parser.add_argument("--quote", required=True, help="Quote token contract, usually USDT")
    parser.add_argument("--exclude-token", action="append", default=[], help="Routing token to ignore during --token auto; repeatable")
    parser.add_argument("--router", default="", help="Known Binance Wallet DEX Router candidate, optional")
    parser.add_argument("--history", nargs="*", default=[], type=Path, help="Additional trace JSON files for cross-token reuse")
    parser.add_argument("--min-alpha-tokens", type=int, default=3, help="Minimum distinct Alpha tokens required before allowlist promotion")
    args = parser.parse_args()
    report = build_report(
        args.input,
        args.token,
        args.quote,
        args.router,
        args.history,
        args.min_alpha_tokens,
        args.exclude_token,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
