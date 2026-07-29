#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_opening_block_watch as opening


TransferRpc = Callable[[str, dict[str, Any]], Any]
ReceiptRpc = Callable[[str, str], Any]


class IncompleteAcquisitionError(RuntimeError):
    pass


class SnapshotChangedError(RuntimeError):
    pass


class RuntimeBusyError(RuntimeError):
    pass


def deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def remaining_timeout(deadline: float | None, maximum: int) -> int:
    if deadline is None:
        return max(1, maximum)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise opening.RpcDeadlineExceeded("rebuild deadline exceeded")
    return max(1, min(maximum, int(remaining) or 1))


def collect(
    event: dict[str, Any],
    buyer: str,
    max_pages: int,
    max_transactions: int,
    deadline: float | None,
    rpc: TransferRpc,
) -> tuple[list[str], set[str], int]:
    start = int(event.get("_buy_block") or 0)
    end = int(event.get("latest_block") or 0)
    reasons: set[str] = set()
    transactions: list[str] = []
    seen: set[str] = set()
    seen_page_keys: set[str] = set()
    page_key = ""
    pages = 0
    if start <= 0 or end < start:
        return transactions, {"invalid_block_range"}, pages

    for page in range(max(1, max_pages)):
        if deadline_expired(deadline):
            reasons.add("deadline_exceeded")
            break
        query = {
            "category": ["20"],
            "fromBlock": hex(start),
            "toBlock": hex(end),
            "contractAddresses": [
                opening.norm(event["token"]["address"])
            ],
            "fromAddress": opening.norm(buyer),
            "order": "asc",
            "maxCount": "0x3e8",
        }
        if page_key:
            query["pageKey"] = page_key
        try:
            result = rpc(event["chain"], query)
        except opening.RpcDeadlineExceeded:
            reasons.add("deadline_exceeded")
            break
        except Exception:
            result = None
        pages += 1
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("transfers"), list)
        ):
            reasons.add("asset_transfer_response_invalid")
            break

        transfers = result["transfers"]
        for row in transfers:
            if not isinstance(row, dict):
                reasons.add("asset_transfer_row_invalid")
                continue
            if (
                opening.norm(row.get("from")) != opening.norm(buyer)
                or opening.norm(row.get("contractAddress"))
                != opening.norm(event["token"]["address"])
            ):
                reasons.add("asset_transfer_row_scope_mismatch")
                continue
            tx_hash = opening.norm(
                row.get("hash") or row.get("transactionHash")
            )
            if (
                len(tx_hash) != 66
                or not tx_hash.startswith("0x")
            ):
                reasons.add("asset_transfer_row_invalid")
                continue
            if tx_hash not in seen:
                if len(transactions) >= max_transactions:
                    reasons.add("asset_transfer_transaction_limit")
                    break
                seen.add(tx_hash)
                transactions.append(tx_hash)
        if "asset_transfer_transaction_limit" in reasons:
            break

        raw_page_key = result.get("pageKey") or result.get("PageKey") or ""
        if raw_page_key and not isinstance(raw_page_key, str):
            reasons.add("asset_transfer_page_key_invalid")
            break
        next_page_key = str(raw_page_key)
        if not next_page_key:
            if len(transfers) >= 1000:
                reasons.add("asset_transfer_full_page_without_cursor")
            break
        if next_page_key in seen_page_keys:
            reasons.add("asset_transfer_page_key_repeated")
            break
        seen_page_keys.add(next_page_key)
        page_key = next_page_key
        if page + 1 == max(1, max_pages):
            reasons.add("asset_transfer_page_limit")

    return transactions, reasons, pages


def receipt_identity_issue(
    receipt: dict[str, Any],
    tx_hash: str,
    from_block: int,
    to_block: int,
) -> str:
    if opening.norm(receipt.get("transactionHash")) != tx_hash:
        return "receipt_transaction_mismatch"
    try:
        receipt_block = opening.hex_to_int(receipt.get("blockNumber"))
    except (TypeError, ValueError):
        return "receipt_block_invalid"
    if not isinstance(receipt_block, int):
        return "receipt_block_invalid"
    if receipt_block < from_block or receipt_block > to_block:
        return "receipt_block_out_of_range"
    logs = receipt.get("logs")
    if not isinstance(logs, list):
        return "receipt_incomplete"
    for log in logs:
        if not isinstance(log, dict):
            return "receipt_log_invalid"
        if opening.norm(log.get("transactionHash")) != tx_hash:
            return "receipt_log_transaction_mismatch"
        try:
            log_block = opening.hex_to_int(log.get("blockNumber"))
        except (TypeError, ValueError):
            return "receipt_log_block_invalid"
        if not isinstance(log_block, int):
            return "receipt_log_block_invalid"
        if log_block != receipt_block:
            return "receipt_log_block_mismatch"
    return ""


def rebuild_trace(
    event: dict[str, Any],
    row: dict[str, Any],
    max_pages: int,
    max_transactions: int,
    deadline: float | None,
    transfer_rpc: TransferRpc,
    receipt_rpc: ReceiptRpc,
) -> dict[str, Any]:
    previous = copy.deepcopy(row.get("buyer_trace") or {})
    scoped_event = dict(
        event,
        _buy_block=int(row.get("block") or 0),
    )
    transactions, acquisition_reasons, pages = collect(
        scoped_event,
        row["buyer"],
        max_pages,
        max_transactions,
        deadline,
        transfer_rpc,
    )
    evidence: list[dict[str, Any]] = []
    excluded_transactions = 0
    unresolved_outbound_transactions = 0
    for tx_hash in transactions:
        if deadline_expired(deadline):
            acquisition_reasons.add("deadline_exceeded")
            break
        try:
            receipt = receipt_rpc(event["chain"], tx_hash)
            if not isinstance(receipt, dict):
                raise ValueError("receipt is not an object")
            identity_issue = receipt_identity_issue(
                receipt,
                tx_hash,
                int(row.get("block") or 0),
                int(event.get("latest_block") or 0),
            )
            if identity_issue:
                acquisition_reasons.add(identity_issue)
                continue
            complete, status = opening.receipt_execution_status(receipt)
            if not complete:
                raise ValueError("receipt execution status incomplete")
            if status != 1:
                acquisition_reasons.add("receipt_execution_failed")
                continue
            transfers = opening.receipt_transfers_from_receipt(
                receipt,
                event["token"],
                event["quote"],
            )
        except opening.RpcDeadlineExceeded:
            acquisition_reasons.add("deadline_exceeded")
            break
        except Exception:
            acquisition_reasons.add("receipt_incomplete")
            continue
        exclusion_reason = opening.receipt_confirmed_sell_exclusion_reason(
            transfers,
            event,
            row["buyer"],
            receipt.get("from", ""),
        )
        if exclusion_reason == "receipt_direction_missing_token_out":
            acquisition_reasons.add(exclusion_reason)
            continue
        if exclusion_reason:
            excluded_transactions += 1
            continue
        transaction_evidence = opening.receipt_confirmed_sell_evidence(
            transfers,
            event,
            row["buyer"],
            tx_hash,
            "direct",
            receipt.get("from", ""),
        )
        if transaction_evidence:
            evidence.extend(transaction_evidence)
        else:
            unresolved_outbound_transactions += 1

    fresh_summary = opening.confirmed_sell_evidence_summary(evidence)
    refreshed = copy.deepcopy(previous)
    refreshed.update(
        {
            "coverage_complete": not acquisition_reasons,
            "confirmed_sell_evidence": evidence,
            "confirmed_sell_quote_received": opening.decimal_str(
                fresh_summary["quote_received"]
            ),
            "direct_sell_quote_received": opening.decimal_str(
                fresh_summary["direct_quote_received"]
            ),
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": str(
                fresh_summary["confirmed_sell_count"]
            ),
        }
    )
    result = opening.trace_sell_lower_bound(previous, refreshed)
    overall_reasons = set(acquisition_reasons)
    if previous.get("coverage_complete") is not True:
        overall_reasons.add("prior_trace_incomplete")
    legacy_values = (
        opening.decimal_from(
            result.get("legacy_confirmed_sell_quote_received")
        ),
        opening.decimal_from(
            result.get("legacy_direct_sell_quote_received")
        ),
        opening.decimal_from(
            result.get("legacy_next_hop_sell_quote_received")
        ),
        opening.Decimal(
            opening.int_from(result.get("legacy_confirmed_sell_count"))
        ),
    )
    if any(value > 0 for value in legacy_values):
        overall_reasons.add("legacy_lower_bound_unverified")
    if previous.get("next_hop_watch_recipients"):
        overall_reasons.add("next_hop_not_refreshed")
    if unresolved_outbound_transactions:
        overall_reasons.add("next_hop_not_refreshed")
    if result.get("coverage_complete") is not True:
        overall_reasons.add("merged_trace_incomplete")

    acquisition_complete = not acquisition_reasons
    coverage_complete = (
        acquisition_complete
        and result.get("coverage_complete") is True
        and not overall_reasons
    )
    total = opening.decimal_from(
        result.get("confirmed_sell_quote_received")
    )
    result.update(
        {
            "coverage_complete": coverage_complete,
            "coverage_status": (
                "complete" if coverage_complete else "partial"
            ),
            "confirmed_sell_status": (
                "confirmed"
                if coverage_complete and total > 0
                else "confirmed_partial_coverage"
                if total > 0
                else "not_observed"
                if coverage_complete
                else "unknown_incomplete_coverage"
            ),
            "direct_sell_rebuild": {
                "status": (
                    "complete" if coverage_complete else "partial"
                ),
                "overall_trace_status": (
                    "complete" if coverage_complete else "partial"
                ),
                "coverage_complete": coverage_complete,
                "incomplete_reasons": sorted(overall_reasons),
                "acquisition_status": (
                    "complete" if acquisition_complete else "partial"
                ),
                "direct_acquisition_status": (
                    "complete" if acquisition_complete else "partial"
                ),
                "acquisition_complete": acquisition_complete,
                "acquisition_incomplete_reasons": sorted(
                    acquisition_reasons
                ),
                "page_count": pages,
                "transaction_count": len(transactions),
                "excluded_transaction_count": excluded_transactions,
                "unresolved_outbound_transaction_count": (
                    unresolved_outbound_transactions
                ),
                "canonical_evidence_count": len(evidence),
                "merged_canonical_evidence_count": len(
                    result.get("confirmed_sell_evidence") or []
                ),
                "as_of_block": str(event.get("latest_block") or ""),
            },
        }
    )
    if coverage_complete:
        result["status"] = str(
            result.get("position_status")
            or previous.get("position_status")
            or previous.get("status")
            or "held_or_accumulated"
        )
    else:
        result["status"] = (
            "confirmed_sell_partial_coverage"
            if total > 0
            else "unknown_incomplete_coverage"
        )
    return result


def deadline_partial_trace(
    event: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    trace = copy.deepcopy(row.get("buyer_trace") or {})
    total = opening.decimal_from(
        trace.get("confirmed_sell_quote_received")
    )
    trace.update(
        {
            "coverage_complete": False,
            "coverage_status": "partial",
            "status": (
                "confirmed_sell_partial_coverage"
                if total > 0
                else "unknown_incomplete_coverage"
            ),
            "direct_sell_rebuild": {
                "status": "partial",
                "overall_trace_status": "partial",
                "coverage_complete": False,
                "incomplete_reasons": ["deadline_exceeded"],
                "acquisition_status": "partial",
                "direct_acquisition_status": "partial",
                "acquisition_complete": False,
                "acquisition_incomplete_reasons": [
                    "deadline_exceeded"
                ],
                "page_count": 0,
                "transaction_count": 0,
                "excluded_transaction_count": 0,
                "unresolved_outbound_transaction_count": 0,
                "canonical_evidence_count": 0,
                "merged_canonical_evidence_count": len(
                    trace.get("confirmed_sell_evidence") or []
                ),
                "as_of_block": str(event.get("latest_block") or ""),
            },
        }
    )
    return trace


def rebuild_snapshot(
    snapshot: dict[str, Any],
    symbol: str,
    token: str,
    opening_block: int,
    max_buyers: int,
    max_pages: int,
    max_transactions: int,
    deadline: float | None,
    transfer_rpc: TransferRpc,
    receipt_rpc: ReceiptRpc,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested_symbol = str(symbol).strip().upper()
    requested_token = opening.norm(token)
    updated = copy.deepcopy(snapshot)
    matching_events = [
        event
        for event in updated.get("events", [])
        if isinstance(event, dict)
        and event.get("status") == "opened"
        and str(event.get("symbol") or "").upper() == requested_symbol
        and opening.norm(
            (event.get("token") or {}).get("address")
        )
        == requested_token
        and int(event.get("opening_block") or 0) == opening_block
    ]
    summary: dict[str, Any] = {
        "status": (
            "target_not_found"
            if not matching_events
            else "target_ambiguous"
        ),
        "acquisition_status": "not_started",
        "applied": False,
        "symbol": requested_symbol,
        "token": requested_token,
        "opening_block": opening_block,
        "matching_event_count": len(matching_events),
        "target_row_count": 0,
        "rebuilt_row_count": 0,
        "invalid_buyer_row_count": 0,
        "canonical_evidence_count": 0,
        "incomplete_reasons": [],
        "source_generated_at": str(
            snapshot.get("generated_at") or ""
        ),
        "rebuilt_at": opening.now_iso(),
    }
    updated["direct_sell_evidence_rebuild"] = summary
    if len(matching_events) != 1:
        return updated, summary

    event = matching_events[0]
    buys = opening.meaningful_buy_rows(event.get("rows", []))
    summary["target_row_count"] = len(buys)
    statuses: list[str] = []
    acquisition_statuses: list[str] = []
    if len(buys) > max_buyers:
        statuses.append("partial")
        acquisition_statuses.append("partial")
        summary["incomplete_reasons"].append("buyer_limit")

    for row in buys[:max_buyers]:
        if not opening.is_address(row.get("buyer")):
            statuses.append("partial")
            acquisition_statuses.append("partial")
            summary["invalid_buyer_row_count"] += 1
            summary["incomplete_reasons"].append("buyer_invalid")
            continue
        if deadline_expired(deadline):
            row["buyer_trace"] = deadline_partial_trace(event, row)
        else:
            row["buyer_trace"] = rebuild_trace(
                event,
                row,
                max_pages,
                max_transactions,
                deadline,
                transfer_rpc,
                receipt_rpc,
            )
        audit = row["buyer_trace"]["direct_sell_rebuild"]
        statuses.append(audit["status"])
        acquisition_statuses.append(audit["acquisition_status"])
        summary["canonical_evidence_count"] += int(
            audit["canonical_evidence_count"]
        )
        summary["incomplete_reasons"].extend(
            audit["acquisition_incomplete_reasons"]
        )
        summary["rebuilt_row_count"] += 1

    event["analysis"] = opening.analyze_opened(
        event,
        event.get("rows", []),
        allow_rpc=False,
    )
    if not buys:
        summary["status"] = "no_matching_rows"
        summary["acquisition_status"] = "no_matching_rows"
    else:
        summary["status"] = (
            "partial" if "partial" in statuses else "complete"
        )
        summary["acquisition_status"] = (
            "partial"
            if "partial" in acquisition_statuses
            else "complete"
        )
    summary["incomplete_reasons"] = sorted(
        set(summary["incomplete_reasons"])
    )
    alerts = [
        key
        for current_event in updated.get("events", [])
        if isinstance(current_event, dict)
        for key in opening.event_alert_keys(current_event)
    ]
    seen = set(opening.read_json(opening.SEEN_PATH, []))
    updated["event_count"] = len(updated.get("events", []))
    updated["alert_count"] = len(alerts)
    updated["new_alert_count"] = sum(
        1 for key in alerts if not opening.alert_key_seen(key, seen)
    )
    updated["direct_sell_evidence_rebuild"] = copy.deepcopy(summary)
    return updated, summary


def stage(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return name


def replace_pair(files: list[tuple[Path, str]]) -> None:
    originals = [
        (path, path.read_text(encoding="utf-8") if path.exists() else None)
        for path, _ in files
    ]
    staged = [(path, stage(path, text)) for path, text in files]
    replaced: list[Path] = []
    try:
        for path, temporary in staged:
            os.replace(temporary, path)
            replaced.append(path)
        for directory in {path.parent for path, _ in files}:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:
        for path, old_text in originals:
            if path not in replaced:
                continue
            if old_text is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(stage(path, old_text), path)
        raise
    finally:
        for _, temporary in staged:
            if os.path.exists(temporary):
                os.unlink(temporary)


def file_state(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, ""
    return True, hashlib.sha256(path.read_bytes()).hexdigest()


def apply_prepared_rebuild(
    json_path: Path,
    markdown_path: Path,
    json_state: tuple[bool, str],
    markdown_state: tuple[bool, str],
    updated: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    if summary["acquisition_status"] != "complete":
        raise IncompleteAcquisitionError(
            str(summary["acquisition_status"])
        )
    if (
        file_state(json_path) != json_state
        or file_state(markdown_path) != markdown_state
    ):
        raise SnapshotChangedError("opening snapshot changed")
    summary["applied"] = True
    updated["direct_sell_evidence_rebuild"] = copy.deepcopy(summary)
    replace_pair(
        [
            (markdown_path, opening.render(updated)),
            (
                json_path,
                json.dumps(
                    updated,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            ),
        ]
    )


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            raise RuntimeBusyError(str(path)) from exc
        yield


def execute(args: argparse.Namespace) -> dict[str, Any]:
    timeout = int(
        os.environ.get("ALPHA_OPENING_CLASSIFY_RPC_TIMEOUT", "5")
    )
    deadline = time.monotonic() + args.max_seconds
    markdown_path = args.input.with_suffix(".md")
    transfer_rpc = lambda chain, query: opening.rpc_call(
        chain,
        "nr_getAssetTransfers",
        [query],
        timeout=remaining_timeout(deadline, timeout),
        deadline=deadline,
    )
    receipt_rpc = lambda chain, tx_hash: opening.rpc_call(
        chain,
        "eth_getTransactionReceipt",
        [tx_hash],
        timeout=remaining_timeout(deadline, timeout),
        deadline=deadline,
    )
    output_lock = args.input.parent / ".lock"
    if not args.apply:
        with exclusive_lock(output_lock):
            source = args.input.read_text(encoding="utf-8")
        _, summary = rebuild_snapshot(
            json.loads(source),
            args.symbol,
            args.token,
            args.opening_block,
            args.max_buyers,
            args.max_pages,
            args.max_transactions,
            deadline,
            transfer_rpc,
            receipt_rpc,
        )
        return summary

    server_lock = Path(
        os.environ.get(
            "SNIPER_RUN_LOCK_FILE",
            "/tmp/sniper_server_run_once.lock",
        )
    )
    with exclusive_lock(server_lock):
        with exclusive_lock(output_lock):
            json_state = file_state(args.input)
            markdown_state = file_state(markdown_path)
            source = args.input.read_text(encoding="utf-8")
    updated, summary = rebuild_snapshot(
        json.loads(source),
        args.symbol,
        args.token,
        args.opening_block,
        args.max_buyers,
        args.max_pages,
        args.max_transactions,
        deadline,
        transfer_rpc,
        receipt_rpc,
    )
    with exclusive_lock(server_lock):
        with exclusive_lock(output_lock):
            apply_prepared_rebuild(
                args.input,
                markdown_path,
                json_state,
                markdown_state,
                updated,
                summary,
            )
    return summary


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=opening.LATEST_PATH,
    )
    parser.add_argument(
        "--symbol",
        required=True,
    )
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--opening-block",
        type=positive_int,
        required=True,
    )
    parser.add_argument("--max-buyers", type=positive_int, default=20)
    parser.add_argument("--max-pages", type=positive_int, default=100)
    parser.add_argument(
        "--max-transactions",
        type=positive_int,
        default=1000,
    )
    parser.add_argument("--max-seconds", type=positive_int, default=180)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.symbol.strip():
        parser.error("symbol must be non-empty")
    if not opening.is_address(args.token):
        parser.error("token must be an EVM address")
    if (
        args.max_buyers > 100
        or args.max_pages > 1000
        or args.max_transactions > 10000
        or args.max_seconds > 1800
    ):
        parser.error("limit exceeds safety maximum")
    try:
        result = execute(args)
    except RuntimeBusyError:
        print(json.dumps({"status": "lock_busy"}), file=sys.stderr)
        return 75
    except SnapshotChangedError:
        print(json.dumps({"status": "source_changed"}), file=sys.stderr)
        return 3
    except IncompleteAcquisitionError:
        print(
            json.dumps({"status": "incomplete_acquisition"}),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
