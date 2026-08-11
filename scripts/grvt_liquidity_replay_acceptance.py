#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SNIPER_OFFLINE"] = "1"
os.environ["DISABLE_TELEGRAM"] = "1"

from sniper_engine.rpc import (  # noqa: E402
    DEFAULT_RPCS,
    READ_CAPABLE_PUBLIC_RPCS,
    RpcDeadlineExceeded,
    adaptive_get_logs,
    deadline_timeout,
    rpc_call_url,
    rpc_urls,
)
from scripts import alpha_holder_concentration_watch as holder  # noqa: E402
from scripts import alpha_opening_block_watch as opening  # noqa: E402


FIXTURE_PATH = (
    ROOT
    / "scripts"
    / "fixtures"
    / "grvt_v3_quote_only_removal_receipt_2026-08-07.json"
)
OUTPUT_ROOT = ROOT / "output"
Rpc = Callable[[str, str, list[Any]], Any]
PUBLIC_RPCS = tuple(
    dict.fromkeys(
        [DEFAULT_RPCS["bsc"], *READ_CAPABLE_PUBLIC_RPCS["bsc"]]
    )
)
RUNTIME_REPLAY_BUDGET_SECONDS = 210
RUNTIME_REPLAY_ATTEMPT_SECONDS = 100
RUNTIME_REPLAY_RPC_TIMEOUT_SECONDS = 8
RUNTIME_REPLAY_TRANSIENT_ISSUES = {
    "runtime_rpc_attempts_exhausted",
    "runtime_rpc_deadline_exceeded",
}


class AcceptanceFailure(RuntimeError):
    pass


class RuntimeReplayCoverageFailure(AcceptanceFailure):
    def __init__(self, issue: str, coverage: dict[str, Any]) -> None:
        super().__init__(issue)
        self.coverage = coverage


def runtime_replay_rpc_call(
    endpoint: str,
    chain: str,
    method: str,
    params: list[Any],
    *,
    timeout: int | float,
    deadline: float,
) -> Any:
    if chain != "bsc":
        raise RuntimeError("unsupported runtime replay chain")
    if method == "eth_getLogs":
        if len(params) != 1 or not isinstance(params[0], dict):
            raise RuntimeError("eth_getLogs coverage query invalid")
        return adaptive_get_logs(
            params[0],
            lambda query: rpc_call_url(
                endpoint,
                method,
                [query],
                timeout=deadline_timeout(timeout, deadline),
            ),
            max_transport_split_depth=0,
            before_attempt=lambda: deadline_timeout(timeout, deadline),
        )
    return rpc_call_url(
        endpoint,
        method,
        params,
        timeout=deadline_timeout(timeout, deadline),
    )


def run_runtime_acceptance() -> dict[str, Any]:
    overall_deadline = time.monotonic() + RUNTIME_REPLAY_BUDGET_SECONDS
    runtime_endpoints = tuple(
        dict.fromkeys(rpc_urls("bsc", "eth_getLogs"))
    )
    attempted_count = 0

    def coverage(
        terminal_reason: str,
        decision_coverage_complete: bool,
    ) -> dict[str, Any]:
        return {
            "schema": "runtime_rpc_attempt_coverage.v1",
            "eligible_count": len(runtime_endpoints),
            "attempted_count": attempted_count,
            "unattempted_count": len(runtime_endpoints) - attempted_count,
            "terminal_reason": terminal_reason,
            "decision_coverage_complete": decision_coverage_complete,
        }

    if not runtime_endpoints:
        raise RuntimeReplayCoverageFailure(
            "runtime_rpc_no_eligible_candidates",
            coverage("no_eligible_candidates", True),
        ) from None

    for endpoint in runtime_endpoints:
        attempt_started_at = time.monotonic()
        remaining = overall_deadline - attempt_started_at
        if remaining < RUNTIME_REPLAY_ATTEMPT_SECONDS:
            raise RuntimeReplayCoverageFailure(
                "runtime_rpc_attempt_coverage_incomplete",
                coverage("attempt_budget_incomplete", False),
            ) from None
        attempt_deadline = (
            attempt_started_at + RUNTIME_REPLAY_ATTEMPT_SECONDS
        )
        attempted_count += 1
        rpc_issue = ""

        def bounded_runtime_rpc(
            chain: str,
            method: str,
            params: list[Any],
        ) -> Any:
            nonlocal rpc_issue
            try:
                return runtime_replay_rpc_call(
                    endpoint,
                    chain,
                    method,
                    params,
                    timeout=RUNTIME_REPLAY_RPC_TIMEOUT_SECONDS,
                    deadline=attempt_deadline,
                )
            except RpcDeadlineExceeded:
                rpc_issue = "runtime_rpc_deadline_exceeded"
                raise AcceptanceFailure(rpc_issue) from None
            except RuntimeError:
                rpc_issue = "runtime_rpc_attempts_exhausted"
                raise AcceptanceFailure(rpc_issue) from None

        try:
            result = run_acceptance(bounded_runtime_rpc)
            if time.monotonic() > overall_deadline:
                raise RuntimeReplayCoverageFailure(
                    "runtime_rpc_deadline_exceeded",
                    coverage("overall_deadline_exceeded", True),
                ) from None
            return {
                **result,
                "runtime_rpc_coverage": coverage("pass", True),
            }
        except AcceptanceFailure as exc:
            if isinstance(exc, RuntimeReplayCoverageFailure):
                raise
            issue = rpc_issue or str(exc)
            retryable = issue in RUNTIME_REPLAY_TRANSIENT_ISSUES
            if not retryable:
                raise RuntimeReplayCoverageFailure(
                    issue,
                    coverage("semantic_failure", True),
                ) from None
    raise RuntimeReplayCoverageFailure(
        "runtime_rpc_attempts_exhausted",
        coverage("transient_attempts_exhausted", True),
    ) from None


def require(condition: bool, issue: str) -> None:
    if not condition:
        raise AcceptanceFailure(issue)


def fixed_public_rpc(chain: str, method: str, params: list[Any]) -> Any:
    if chain != "bsc":
        raise AcceptanceFailure("unsupported_chain")
    deadline = time.monotonic() + 45
    for endpoint in PUBLIC_RPCS:
        try:
            if method == "eth_getLogs":
                require(
                    len(params) == 1 and isinstance(params[0], dict),
                    "public_rpc_log_query_invalid",
                )
                return adaptive_get_logs(
                    params[0],
                    lambda query, url=endpoint: rpc_call_url(
                        url,
                        method,
                        [query],
                        timeout=max(
                            1,
                            min(15, int(deadline - time.monotonic())),
                        ),
                    ),
                    before_attempt=lambda: require(
                        time.monotonic() < deadline,
                        "public_rpc_deadline_exceeded",
                    ),
                )
            return rpc_call_url(
                endpoint,
                method,
                params,
                timeout=max(1, min(15, int(deadline - time.monotonic()))),
            )
        except AcceptanceFailure:
            raise
        except Exception:
            continue
    raise AcceptanceFailure("public_rpc_unavailable")


def fixture_payload() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    require(
        set(payload)
        == {
            "schema",
            "chain",
            "status",
            "block_number",
            "block_hash",
            "transaction_hash",
            "transaction_from",
            "transaction_nonce",
            "pool",
            "logs",
            "paired_mint",
        },
        "fixture_top_level_schema_invalid",
    )
    require(
        payload.get("schema")
        == "canonical_v3_removal_receipt_fixture.v1"
        and payload.get("chain") == "bsc"
        and payload.get("status") == 1,
        "fixture_identity_invalid",
    )
    require(
        set(payload["pool"])
        == {
            "protocol",
            "address",
            "factory",
            "token0",
            "token1",
            "fee",
            "quote_token",
            "quote_symbol",
            "quote_decimals",
        },
        "fixture_pool_schema_invalid",
    )
    require(
        set(payload["paired_mint"])
        == {
            "status",
            "block_number",
            "block_hash",
            "transaction_hash",
            "transaction_from",
            "transaction_nonce",
            "elapsed_seconds",
            "log",
        },
        "fixture_mint_schema_invalid",
    )
    return payload


def canonical_transaction(
    rpc: Rpc,
    *,
    tx_hash: str,
    block_number: int,
    block_hash: str,
    sender: str,
    nonce: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        receipt = rpc("bsc", "eth_getTransactionReceipt", [tx_hash])
        transaction = rpc("bsc", "eth_getTransactionByHash", [tx_hash])
        block = rpc(
            "bsc", "eth_getBlockByNumber", [hex(block_number), False]
        )
    except AcceptanceFailure:
        raise
    except Exception as exc:
        raise AcceptanceFailure("canonical_transaction_rpc_failed") from exc
    require(
        isinstance(receipt, dict)
        and isinstance(transaction, dict)
        and isinstance(block, dict),
        "canonical_transaction_shape_invalid",
    )
    require(
        holder.norm(receipt.get("transactionHash")) == holder.norm(tx_hash)
        and int(receipt.get("status") or "0x0", 16) == 1
        and int(receipt.get("blockNumber") or "0x0", 16) == block_number
        and holder.norm(receipt.get("blockHash"))
        == holder.norm(block_hash),
        "canonical_receipt_identity_mismatch",
    )
    require(
        holder.norm(transaction.get("hash")) == holder.norm(tx_hash)
        and holder.norm(transaction.get("from")) == holder.norm(sender)
        and int(transaction.get("nonce") or "0x0", 16) == nonce
        and int(transaction.get("blockNumber") or "0x0", 16)
        == block_number
        and holder.norm(transaction.get("blockHash"))
        == holder.norm(block_hash),
        "canonical_sender_or_nonce_mismatch",
    )
    require(
        int(block.get("number") or "0x0", 16) == block_number
        and holder.norm(block.get("hash")) == holder.norm(block_hash)
        and int(block.get("timestamp") or "0x0", 16) > 0,
        "canonical_block_identity_mismatch",
    )
    return receipt, block


def log_projection(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": holder.norm(raw.get("address")),
        "blockNumber": str(raw.get("blockNumber") or "").lower(),
        "blockHash": holder.norm(raw.get("blockHash")),
        "logIndex": str(raw.get("logIndex") or "").lower(),
        "transactionHash": holder.norm(raw.get("transactionHash")),
        "topics": [holder.norm(value) for value in raw.get("topics") or []],
        "data": holder.norm(raw.get("data")),
        "removed": raw.get("removed", False),
    }


def strict_fixture_logs(
    receipt: dict[str, Any], expected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    expected_indexes = {
        int(row["logIndex"], 16): row for row in expected
    }
    live = {
        holder.log_index(row): row
        for row in receipt.get("logs") or []
        if holder.log_index(row) in expected_indexes
    }
    require(
        set(live) == set(expected_indexes),
        "fixture_log_indexes_missing",
    )
    for index, expected_row in expected_indexes.items():
        require(
            log_projection(live[index]) == log_projection(expected_row),
            "fixture_log_payload_mismatch",
        )
    return [copy.deepcopy(live[index]) for index in sorted(live)]


def rpc_address(rpc: Rpc, to: str, selector: str, block: int) -> str:
    state, address = opening.strict_abi_address_return(
        rpc(
            "bsc",
            "eth_call",
            [{"to": to, "data": selector}, hex(block)],
        )
    )
    require(state == "address", "pool_address_call_invalid")
    return holder.norm(address)


def rpc_uint(
    rpc: Rpc, to: str, selector: str, block: int, bits: int
) -> int:
    value = opening.strict_abi_uint_return(
        rpc(
            "bsc",
            "eth_call",
            [{"to": to, "data": selector}, hex(block)],
        ),
        bits,
    )
    require(value is not None, "pool_uint_call_invalid")
    return int(value)


def verify_pool_identity(rpc: Rpc, pool: dict[str, Any], block: int) -> None:
    code = rpc("bsc", "eth_getCode", [pool["address"], hex(block)])
    require(opening.has_runtime_bytecode(code), "pool_runtime_code_invalid")
    require(
        rpc_address(rpc, pool["address"], "0x0dfe1681", block)
        == holder.norm(pool["token0"])
        and rpc_address(rpc, pool["address"], "0xd21220a7", block)
        == holder.norm(pool["token1"])
        and rpc_address(rpc, pool["address"], "0xc45a0155", block)
        == holder.norm(pool["factory"])
        and rpc_uint(rpc, pool["address"], "0xddca3f43", block, 24)
        == int(pool["fee"]),
        "pool_identity_mismatch",
    )
    get_pool_call = (
        opening.V3_GET_POOL_SELECTOR
        + opening.encode_address_word(pool["token0"])
        + opening.encode_address_word(pool["token1"])
        + opening.encode_uint(int(pool["fee"]))
    )
    require(
        rpc_address(rpc, pool["factory"], get_pool_call, block)
        == holder.norm(pool["address"]),
        "factory_pool_identity_mismatch",
    )
    require(
        rpc_uint(rpc, pool["quote_token"], "0x313ce567", block, 8)
        == int(pool["quote_decimals"]),
        "quote_decimals_mismatch",
    )


def event_logs(rows: list[dict[str, Any]], pool: dict[str, Any]) -> list[dict[str, Any]]:
    kind_by_topic = {
        holder.V3_BURN_TOPIC: "v3_burn",
        holder.V3_COLLECT_TOPIC: "v3_collect",
        holder.V3_MINT_TOPIC: "v3_mint",
    }
    output = []
    for raw in rows:
        topic = holder.norm((raw.get("topics") or [""])[0])
        require(topic in kind_by_topic, "fixture_event_topic_invalid")
        row = copy.deepcopy(raw)
        row["_retention_pool"] = copy.deepcopy(pool)
        row["_retention_event_kind"] = kind_by_topic[topic]
        output.append(row)
    return output


def coverage_project(
    pool: dict[str, Any],
    logs: list[dict[str, Any]],
    verdict: dict[str, Any],
    removal_block: int,
    mint_block: int,
    mint_hash: str,
) -> dict[str, Any]:
    scope_hash = holder.liquidity_pool_scope_hash([pool])
    coverage = {
        "query_scope_complete": True,
        "query_count": 1,
        "scope_batch_count": 1,
        "query_chunk_count": 1,
        "query_chunk_blocks": mint_block - removal_block + 1,
        "expected_query_count": 1,
        "v4_manager_count": 0,
        "event_filter_count": 4,
        "applicable": True,
        "active": False,
        "requested_to_block": mint_block,
        "selected_to_block": mint_block,
        "attempt_count": 1,
        "initial_window_blocks": mint_block - removal_block + 1,
        "successful_window_blocks": mint_block - removal_block + 1,
        "next_window_blocks": 0,
        "retry_window_blocks": 0,
        "deadline_exceeded": False,
        "raw_truncation_shrink_count": 0,
        "rpc_error_shrink_count": 0,
        "derived_event_shrink_count": 0,
        "historical_event_truncation_count": 0,
        "complete_selected_window": True,
        "complete_requested_window": True,
        "quote_boundary_complete": True,
        "quote_boundary_query_count": 4,
        "quote_boundary_cache_hit_count": 0,
        "quote_boundary_candidate_count": 1,
        "quote_boundary_error_count": 0,
        "quote_boundary_issue_codes": [],
    }
    with mock.patch.object(
        holder, "retention_window", return_value={"status": "active"}
    ):
        flow = holder.build_liquidity_retention(
            item={"chain": "bsc"},
            token=pool["token0"],
            pools=[pool],
            scope_hash=scope_hash,
            previous_scope_hash=scope_hash,
            scope_rebaseline=False,
            previous_catchup_active=False,
            scope_coverage_from_block=removal_block,
            logs=logs,
            errors=[],
            truncated=False,
            decimals=18,
            supply_raw=10**27,
            scan_from_block=removal_block,
            scan_to_block=mint_block,
            target_scan_to_block=mint_block,
            previous_latest_block=removal_block - 1,
            coverage_metadata=coverage,
            alert_from_block=removal_block,
        )
    flow.update(
        {
            "events": [copy.deepcopy(verdict)],
            "event_count": 1,
            "alert_event_count": 1,
            "observed_latest_block": mint_block,
            "confirmation_blocks": 0,
            "latest_block_hash": mint_hash,
        }
    )
    return {
        "symbol": "GRVT",
        "priority": "P0_DEEP_REVIEW",
        "chain": "bsc",
        "address": pool["token0"],
        "retention_flow": {"liquidity_retention": flow},
    }


class FakeTelegramResponse:
    status = 200

    def __enter__(self) -> "FakeTelegramResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "result": {"message_id": 1, "date": 1},
            }
        ).encode("utf-8")


def normal_replay_dedup(snapshot: dict[str, Any]) -> dict[str, Any]:
    keys = holder.alert_keys(snapshot)
    require(len(keys) == 1, "final_alert_key_cardinality_mismatch")
    with tempfile.TemporaryDirectory(prefix="grvt-replay-") as temporary:
        root = Path(temporary)
        seen_path = root / "seen.json"
        last_push_path = root / "last_push.json"
        lock_path = root / "telegram.lock"
        calls = 0

        def fake_urlopen(*_args: object, **_kwargs: object) -> FakeTelegramResponse:
            nonlocal calls
            calls += 1
            return FakeTelegramResponse()

        with (
            mock.patch.dict(
                os.environ,
                {
                    "DISABLE_TELEGRAM": "0",
                    "ALPHA_HOLDER_TELEGRAM": "1",
                    "ALPHA_HOLDER_FORCE_TELEGRAM": "0",
                    "TELEGRAM_BOT_TOKEN": "fixture",
                    "TELEGRAM_CHAT_ID": "fixture",
                },
            ),
            mock.patch.object(
                holder.urllib.request,
                "urlopen",
                side_effect=fake_urlopen,
            ),
        ):
            first_ok = holder.maybe_send_telegram(
                snapshot,
                seen_path=seen_path,
                last_push_path=last_push_path,
                lock_path=lock_path,
            )
            first_calls = calls
            second_ok = holder.maybe_send_telegram(
                snapshot,
                seen_path=seen_path,
                last_push_path=last_push_path,
                lock_path=lock_path,
            )
        seen = holder.read_json(seen_path, [])
        receipt = holder.read_json(last_push_path, {})
        require(first_ok and second_ok, "telegram_test_sink_failed")
        require(first_calls == 1 and calls == 1, "normal_replay_dedup_failed")
        require(seen == keys, "telegram_seen_ledger_mismatch")
        require(
            receipt.get("api_ok") is True
            and receipt.get("signature") == keys[0],
            "telegram_receipt_ledger_mismatch",
        )
        return {
            "first_send_count": first_calls,
            "replay_duplicate_send_count": calls - first_calls,
            "message": str(receipt.get("text") or ""),
        }


def run_acceptance(rpc: Rpc) -> dict[str, Any]:
    fixture = fixture_payload()
    pool = fixture["pool"]
    mint = fixture["paired_mint"]
    removal_receipt, removal_block = canonical_transaction(
        rpc,
        tx_hash=fixture["transaction_hash"],
        block_number=int(fixture["block_number"]),
        block_hash=fixture["block_hash"],
        sender=fixture["transaction_from"],
        nonce=int(fixture["transaction_nonce"]),
    )
    mint_receipt, mint_block = canonical_transaction(
        rpc,
        tx_hash=mint["transaction_hash"],
        block_number=int(mint["block_number"]),
        block_hash=mint["block_hash"],
        sender=mint["transaction_from"],
        nonce=int(mint["transaction_nonce"]),
    )
    removal_rows = strict_fixture_logs(removal_receipt, fixture["logs"])
    mint_rows = strict_fixture_logs(mint_receipt, [mint["log"]])
    started = datetime.fromtimestamp(
        int(removal_block["timestamp"], 16), timezone.utc
    ).replace(microsecond=0)
    paired_at = datetime.fromtimestamp(
        int(mint_block["timestamp"], 16), timezone.utc
    ).replace(microsecond=0)
    elapsed = int((paired_at - started).total_seconds())
    require(
        elapsed == int(mint["elapsed_seconds"]) and 0 < elapsed <= 900,
        "fixture_elapsed_window_mismatch",
    )
    verify_pool_identity(rpc, pool, int(fixture["block_number"]))
    removal_logs = event_logs(removal_rows, pool)
    mint_logs = event_logs(mint_rows, pool)
    with mock.patch.object(holder, "holder_rpc_call", side_effect=rpc):
        removal_logs, boundary_errors, boundary_metadata = (
            holder.attach_v3_quote_balance_boundaries(
                "bsc", removal_logs
            )
        )
        require(not boundary_errors, "quote_boundary_coverage_failed")
        require(
            boundary_metadata.get("quote_boundary_complete") is True,
            "quote_boundary_incomplete",
        )
        removal_events, _, _ = holder.retention_liquidity_events(
            removal_logs,
            pool["token0"],
            18,
            10**27,
            alert_from_block=int(fixture["block_number"]),
        )
        mint_events, _, _ = holder.retention_liquidity_events(
            mint_logs,
            pool["token0"],
            18,
            10**27,
            alert_from_block=int(fixture["block_number"]),
        )
        require(
            len(removal_events) == 1
            and removal_events[0].get("quote_removed_relative_material")
            is True
            and holder.decimal_from(
                removal_events[0].get("quote_removed_pool_bps")
            )
            >= holder.liquidity_quote_relative_min_bps(),
            "relative_materiality_not_proven",
        )
        removal_events, removal_errors = (
            holder.annotate_liquidity_event_operators(
                "bsc", removal_events
            )
        )
        mint_events, mint_errors = holder.annotate_liquidity_event_operators(
            "bsc", mint_events
        )
        removal_events, removal_time_errors = (
            holder.attach_canonical_liquidity_timestamps(
                "bsc", removal_events
            )
        )
        mint_events, mint_time_errors = (
            holder.attach_canonical_liquidity_timestamps(
                "bsc", mint_events
            )
        )
        require(
            not any(
                (
                    removal_errors,
                    mint_errors,
                    removal_time_errors,
                    mint_time_errors,
                )
            ),
            "operator_or_timestamp_attribution_incomplete",
        )
        require(
            holder.norm(removal_events[0].get("liquidity_operator"))
            == holder.norm(fixture["transaction_from"])
            and removal_events[0].get("liquidity_operator_basis")
            == "transaction_sender_eoa",
            "eip7702_operator_attribution_mismatch",
        )
        raw_events, state, _ = holder.reconcile_liquidity_events(
            removal_events,
            {},
            token_decimals=18,
            observed_at=started,
            evidence_by_id={},
        )
        require(
            len(state.get("pending") or []) == 1
            and raw_events[0].get("alert_eligible") is False,
            "raw_removal_was_not_suppressed",
        )
        _, state, _ = holder.reconcile_liquidity_events(
            mint_events,
            state,
            token_decimals=18,
            observed_at=paired_at,
            evidence_by_id={},
        )
        require(
            len(state.get("pending") or []) == 1,
            "paired_pending_state_missing",
        )
        reconcile_id = state["pending"][0]["reconcile_id"]
        confirmed_tip = int(rpc("bsc", "eth_blockNumber", []), 16) - 2
        evidence = holder.collect_liquidity_verdict_evidence(
            "bsc",
            pool["token0"],
            18,
            [pool],
            state["pending"][0],
            confirmed_tip,
        )
        require(
            evidence.get("coverage_complete") is True,
            "verdict_evidence_coverage_incomplete",
        )
        final_events, final_state, metadata = (
            holder.reconcile_liquidity_events(
                [],
                state,
                token_decimals=18,
                observed_at=started.replace(microsecond=0)
                + timedelta(seconds=900),
                evidence_by_id={reconcile_id: evidence},
            )
        )
    verdicts = [
        event
        for event in final_events
        if event.get("type") == "liquidity_reconciliation"
    ]
    require(len(verdicts) == 1, "final_verdict_cardinality_mismatch")
    verdict = verdicts[0]
    require(
        verdict.get("classification") == "range_repositioned"
        and verdict.get("range_changed") is True
        and holder.norm(verdict.get("source_pool"))
        == holder.norm(verdict.get("destination_pool"))
        and verdict.get("source_ranges") != verdict.get("destination_ranges")
        and verdict.get("paired_chain_elapsed_seconds") == elapsed
        and metadata.get("pending_count") == 0
        and not final_state.get("pending"),
        "range_reposition_verdict_mismatch",
    )
    with mock.patch.object(holder, "holder_rpc_call", side_effect=rpc):
        replay_events, replay_state, _ = holder.reconcile_liquidity_events(
            removal_events,
            final_state,
            token_decimals=18,
            observed_at=started + timedelta(seconds=901),
            evidence_by_id={reconcile_id: evidence},
        )
    require(
        not any(
            event.get("reconciliation_final") is True
            for event in replay_events
        )
        and not replay_state.get("pending"),
        "final_verdict_replayed",
    )
    project = coverage_project(
        pool,
        [*removal_logs, *mint_logs],
        verdict,
        int(fixture["block_number"]),
        int(mint["block_number"]),
        mint["block_hash"],
    )
    snapshot = {"projects": [project]}
    require(
        holder.liquidity_selected_window_alert_coverage_complete(project)
        is True
        and len(holder.retention_alert_events(project)) == 1,
        "final_coverage_contract_invalid",
    )
    sink = normal_replay_dedup(snapshot)
    message = sink.pop("message")
    require(
        all(
            marker in message
            for marker in (
                "撤池后原池改区间",
                "原区间 ",
                "新区间 ",
                "池流动性 ",
                "recipient next-hop",
                "价格 5m",
            )
        )
        and "撤池后迁移新池" not in message,
        "telegram_range_message_incomplete",
    )
    return {
        "schema": "grvt_liquidity_replay_acceptance.v1",
        "status": "pass",
        "issues": [],
        "receipt_count": 2,
        "elapsed_seconds": elapsed,
        "classification": verdict["classification"],
        "range_changed": True,
        "source_pool_equals_destination_pool": True,
        "operator_basis": verdict["liquidity_operator_basis"],
        "quote_boundary_complete": True,
        "relative_materiality_proven": True,
        "raw_removal_alert_eligible": False,
        "pending_count": 0,
        "normal_replay_dedup_pass": True,
        "code_hashes": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "scripts/alpha_holder_concentration_watch.py",
                "scripts/grvt_liquidity_replay_acceptance.py",
                "scripts/fixtures/grvt_v3_quote_only_removal_receipt_2026-08-07.json",
            )
        },
        **sink,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rpc-mode",
        choices=("public", "runtime"),
        default="public",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = (
            run_acceptance(fixed_public_rpc)
            if args.rpc_mode == "public"
            else run_runtime_acceptance()
        )
    except RuntimeReplayCoverageFailure as exc:
        result = {
            "schema": "grvt_liquidity_replay_acceptance.v1",
            "status": "blocked",
            "issues": [str(exc)],
            "runtime_rpc_coverage": exc.coverage,
        }
        exit_code = 2
    except AcceptanceFailure as exc:
        result = {
            "schema": "grvt_liquidity_replay_acceptance.v1",
            "status": "blocked",
            "issues": [str(exc)],
        }
        exit_code = 2
    except Exception:
        result = {
            "schema": "grvt_liquidity_replay_acceptance.v1",
            "status": "blocked",
            "issues": ["unexpected_runtime_error"],
        }
        exit_code = 2
    else:
        exit_code = 0
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    if args.output is not None:
        output_path = args.output
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path = output_path.resolve()
        try:
            output_path.relative_to(OUTPUT_ROOT.resolve())
        except ValueError:
            result = {
                "schema": "grvt_liquidity_replay_acceptance.v1",
                "status": "blocked",
                "issues": ["output_path_outside_project_output"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            exit_code = 2
        else:
            holder.atomic_write_json(output_path, result)
    print(json.dumps(result, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
