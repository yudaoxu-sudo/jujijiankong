#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_alpha_aggregator_trace import DEFAULT_NON_ALPHA_TOKENS, extract_transfer_rows, infer_alpha_token
from sniper_engine.address_labels import global_address_label


DEFAULT_OUT_DIR = ROOT / "output" / "alpha_trace_samples" / "sample_review"


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def is_address(value: Any) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bundle_paths(bundle_dir: Path) -> list[Path]:
    paths = []
    for path in sorted(bundle_dir.glob("*.json")):
        if path.name.startswith("latest_") or path.name.endswith("_summary.json"):
            continue
        paths.append(path)
    return paths


def tx_to(payload: dict[str, Any]) -> str:
    tx = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else {}
    receipt = payload.get("receipt_summary") if isinstance(payload.get("receipt_summary"), dict) else {}
    return norm(tx.get("to") or receipt.get("to"))


def tx_hash(payload: dict[str, Any], path: Path) -> str:
    return norm(payload.get("tx_hash") or path.stem)


def trace_status(payload: dict[str, Any]) -> str:
    meta = payload.get("trace_meta") if isinstance(payload.get("trace_meta"), dict) else {}
    debug = str(meta.get("debug_traceTransaction") or "")
    trace = str(meta.get("trace_transaction") or "")
    if debug == "ok" or trace == "ok":
        return "trace_available"
    if meta:
        return "receipt_only"
    return "unknown"


def alpha_token_for_bundle(payload: dict[str, Any], excluded_tokens: set[str]) -> str:
    try:
        return infer_alpha_token(payload, excluded_tokens)
    except Exception:
        tokens = sorted({row["token"] for row in extract_transfer_rows(payload) if row["token"] not in excluded_tokens})
        return tokens[0] if tokens else ""


def target_addresses(payloads: list[dict[str, Any]], explicit: list[str], min_tokens: int, excluded_tokens: set[str]) -> list[str]:
    if explicit:
        return sorted({norm(address) for address in explicit if is_address(address)})
    by_address: dict[str, set[str]] = defaultdict(set)
    for payload in payloads:
        token = alpha_token_for_bundle(payload, excluded_tokens)
        if not token:
            continue
        to_addr = tx_to(payload)
        if is_address(to_addr):
            by_address[to_addr].add(token)
        for row in extract_transfer_rows(payload):
            for key in ("from", "to"):
                address = row[key]
                if is_address(address):
                    by_address[address].add(token)
    return sorted(address for address, tokens in by_address.items() if len(tokens) >= min_tokens)


def review_address(chain: str, address: str, payloads: list[dict[str, Any]], excluded_tokens: set[str]) -> dict[str, Any]:
    tx_to_tokens: set[str] = set()
    transfer_tokens: set[str] = set()
    transfer_hits = 0
    sample_hits = []
    for payload in payloads:
        token = alpha_token_for_bundle(payload, excluded_tokens)
        if not token:
            continue
        hit = False
        if tx_to(payload) == address:
            tx_to_tokens.add(token)
            hit = True
        per_bundle_transfer_hits = 0
        for row in extract_transfer_rows(payload):
            if row["from"] == address or row["to"] == address:
                transfer_tokens.add(token)
                transfer_hits += 1
                per_bundle_transfer_hits += 1
                hit = True
        if hit:
            sample_hits.append(
                {
                    "tx": tx_hash(payload, Path("")),
                    "alpha_token": token,
                    "tx_to": tx_to(payload) == address,
                    "transfer_hits": per_bundle_transfer_hits,
                    "trace_status": trace_status(payload),
                }
            )
    label = global_address_label(chain, address) or {}
    tx_to_count = len(tx_to_tokens)
    transfer_token_count = len(transfer_tokens)
    if tx_to_count >= 3 and transfer_token_count >= 3:
        recommendation = "exchange_aggregator_suspect_candidate"
        reason = "tx_to_and_transfer_reused_across_alpha_tokens"
    elif transfer_token_count >= 3:
        recommendation = "protocol_or_router_candidate"
        reason = "transfer_reused_across_alpha_tokens"
    else:
        recommendation = "insufficient_evidence"
        reason = "cross_token_reuse_below_threshold"
    configured_class = str(label.get("class") or "")
    needs_full_trace = (
        recommendation != "insufficient_evidence"
        and configured_class not in {"exchange_aggregator", "dex_router"}
    )
    return {
        "address": address,
        "configured_class": configured_class,
        "configured_label": label.get("label", ""),
        "recommendation": recommendation,
        "reason": reason,
        "tx_to_distinct_alpha_tokens": tx_to_count,
        "transfer_distinct_alpha_tokens": transfer_token_count,
        "transfer_hits": transfer_hits,
        "sample_hits": sample_hits,
        "needs_full_trace_before_promotion": needs_full_trace,
    }


def label_proposal(row: dict[str, Any]) -> dict[str, str] | None:
    if row.get("configured_class"):
        return None
    if row.get("recommendation") != "exchange_aggregator_suspect_candidate":
        return None
    return {
        "address": row["address"],
        "label": "Binance Alpha Router candidate",
        "class": "exchange_aggregator_suspect",
        "evidence": (
            "Batch Alpha swap review: tx.to and transfer participant reused across "
            f"{row['tx_to_distinct_alpha_tokens']} Alpha tokens; keep as suspect until paired custody trace confirms."
        ),
    }


def build_review(chain: str, paths: list[Path], addresses: list[str], quote: str, min_tokens: int) -> dict[str, Any]:
    payloads = [read_json(path) for path in paths]
    excluded_tokens = set(DEFAULT_NON_ALPHA_TOKENS)
    excluded_tokens.add(norm(quote))
    tokens = sorted({alpha_token_for_bundle(payload, excluded_tokens) for payload in payloads if alpha_token_for_bundle(payload, excluded_tokens)})
    trace_counts: dict[str, int] = defaultdict(int)
    for payload in payloads:
        trace_counts[trace_status(payload)] += 1
    targets = target_addresses(payloads, addresses, min_tokens, excluded_tokens)
    reviews = [review_address(chain, address, payloads, excluded_tokens) for address in targets]
    proposals = [proposal for row in reviews if (proposal := label_proposal(row))]
    return {
        "schema": "alpha_swap_sample_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain": chain,
        "sample_count": len(paths),
        "distinct_alpha_tokens": len(tokens),
        "alpha_tokens": tokens,
        "trace_status_counts": dict(sorted(trace_counts.items())),
        "addresses_reviewed": len(reviews),
        "reviews": reviews,
        "label_proposals": proposals,
        "decision_rule": (
            "exchange_aggregator_suspect_candidate/protocol_or_router_candidate can be used to exclude cohort pollution; "
            "full exchange_aggregator promotion still requires call trace or equivalent paired custody proof."
        ),
    }


def markdown(review: dict[str, Any]) -> str:
    lines = [
        "# Alpha Swap Sample Review",
        "",
        f"- Chain: `{review['chain']}`",
        f"- Samples: `{review['sample_count']}`",
        f"- Distinct Alpha tokens: `{review['distinct_alpha_tokens']}`",
        f"- Trace status: `{json.dumps(review['trace_status_counts'], ensure_ascii=False)}`",
        "",
        "## Address Decisions",
        "",
        "| Address | Current Class | Recommendation | tx.to Tokens | Transfer Tokens | Hits | Needs Full Trace |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in review["reviews"]:
        short = row["address"][:8] + "..." + row["address"][-6:]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{short}`",
                    f"`{row['configured_class'] or '-'}`",
                    f"`{row['recommendation']}`",
                    str(row["tx_to_distinct_alpha_tokens"]),
                    str(row["transfer_distinct_alpha_tokens"]),
                    str(row["transfer_hits"]),
                    "yes" if row["needs_full_trace_before_promotion"] else "no",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Config Proposals",
            "",
        ]
    )
    proposals = review.get("label_proposals") or []
    if proposals:
        lines.append("```json")
        lines.append(json.dumps(proposals, ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("- No new label proposal.")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `exchange_aggregator_suspect_candidate` and `protocol_or_router_candidate` are enough to keep exchange infrastructure out of buyer/seller cohorts.",
            "- Full `exchange_aggregator` promotion still needs call trace or equivalent proof of paired stablecoin/token custody structure.",
            "- Receipt-only evidence should not be used to claim project/MM sell pressure.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a batch of saved Binance Alpha swap bundles for infra allowlist candidates.")
    parser.add_argument("--bundle-dir", required=True, type=Path, help="Directory containing collect_alpha_trace_bundle.py JSON files")
    parser.add_argument("--chain", default="bsc", help="Chain name used for global address labels")
    parser.add_argument("--quote", default="0x55d398326f99059ff775485246999027b3197955", help="Quote token to exclude")
    parser.add_argument("--address", action="append", default=[], help="Address to review; repeatable. If omitted, review cross-token addresses.")
    parser.add_argument("--min-tokens", type=int, default=3, help="Minimum distinct Alpha tokens for auto-selected addresses")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    paths = bundle_paths(args.bundle_dir)
    if not paths:
        raise SystemExit(f"no bundle JSON files found in {args.bundle_dir}")
    review = build_review(args.chain, paths, args.address, args.quote, args.min_tokens)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "latest.json"
    md_path = args.out_dir / "latest.md"
    json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(review), encoding="utf-8")
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
