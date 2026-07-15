#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_opening_block_watch as opening
from sniper_engine.telegram_send_receipt import read_telegram_send_receipt, record_telegram_send_receipt


CHAIN = "bsc"
CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_intraday_flow_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
WITHDRAWAL_CANDIDATE_HISTORY_PATH = OUT_DIR / "withdrawal_candidate_history.json"
WITHDRAWAL_CANDIDATE_HISTORY_MAX = 200
WITHDRAWAL_TIME_RPC_TIMEOUT_SECONDS = max(
    1,
    min(int(os.environ.get("ALPHA_INTRADAY_WITHDRAWAL_TIME_RPC_TIMEOUT_SECONDS", "2")), 3),
)
WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS = max(
    0,
    min(int(os.environ.get("ALPHA_INTRADAY_WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS", "4")), 4),
)
WITHDRAWAL_TIME_RPC_ATTEMPTS_USED = 0
TELEGRAM_LIMIT = 3200
BLOCK_TX_CACHE: dict[tuple[str, int], list[dict[str, Any]]] = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def norm(value: str | None) -> str:
    return opening.norm(value)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def withdrawal_candidate_id(event: dict[str, Any], cluster: dict[str, Any]) -> str:
    transfer_anchors = sorted(
        (
            int(row.get("block") or 0),
            int(row.get("log_index") or 0),
            str(row.get("tx") or "").lower(),
        )
        for row in cluster.get("sample_transfers", []) or []
        if isinstance(row, dict)
    )
    if transfer_anchors:
        anchor: Any = transfer_anchors[0]
    else:
        first_block = cluster.get("first_block")
        anchor = (
            {"first_block": int(first_block)}
            if first_block not in (None, "")
            else str(cluster.get("window_blocks") or "")
        )
    token = event.get("token", {}) or {}
    identity = {
        "chain": str(event.get("chain") or CHAIN).lower(),
        "token_address": norm(token.get("address")),
        "source_address": norm(cluster.get("source_address")),
        "anchor": anchor,
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"cex_withdrawal_{hashlib.sha256(encoded).hexdigest()[:24]}"


def withdrawal_observation_identity(observation: dict[str, Any]) -> tuple[str, str, str]:
    event = observation.get("event", {}) or {}
    token = event.get("token", {}) or {}
    cluster = observation.get("cluster", {}) or {}
    return (
        str(event.get("chain") or CHAIN).lower(),
        norm(token.get("address")),
        norm(cluster.get("source_address")),
    )


def withdrawal_observation_sample_anchors(observation: dict[str, Any]) -> set[tuple[str, int]]:
    cluster = observation.get("cluster", {}) or {}
    anchors: set[tuple[str, int]] = set()
    for row in cluster.get("sample_transfers", []) or []:
        if not isinstance(row, dict):
            continue
        tx_hash = str(row.get("tx") or "").strip().lower()
        if not tx_hash:
            continue
        try:
            log_index = int(row.get("log_index") or 0)
        except (TypeError, ValueError):
            continue
        anchors.add((tx_hash, log_index))
    return anchors


def withdrawal_collision_candidate_id(
    provisional_id: str,
    observation: dict[str, Any],
    observed_at: str,
) -> str:
    identity = {
        "provisional_id": provisional_id,
        "observation_identity": withdrawal_observation_identity(observation),
        "sample_anchors": sorted(withdrawal_observation_sample_anchors(observation)),
        "observed_at": observed_at,
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"cex_withdrawal_{hashlib.sha256(encoded).hexdigest()[:24]}"


def record_withdrawal_candidate_history(snapshot: dict[str, Any]) -> int:
    observed_at = str(snapshot.get("generated_at") or now_iso())
    provisional_observations: dict[str, dict[str, Any]] = {}
    for event in snapshot.get("events", []) or []:
        analysis = event.get("analysis", {}) or {}
        withdrawal = analysis.get("cex_withdrawal_cluster", {}) or {}
        clusters = withdrawal.get("clusters", []) or []
        if not clusters:
            continue
        scan_coverage = {key: value for key, value in withdrawal.items() if key != "clusters"}
        scan_coverage.update(
            {
                "scan_limited": bool(analysis.get("scan_limited")),
                "sampled_receipts": int(analysis.get("sampled_receipts") or 0),
            }
        )
        token = event.get("token", {}) or {}
        quote = event.get("quote", {}) or {}
        event_context = {
            "symbol": str(event.get("symbol") or token.get("symbol") or "UNKNOWN"),
            "priority": str(event.get("priority") or ""),
            "chain": str(event.get("chain") or CHAIN),
            "token": {
                "address": norm(token.get("address")),
                "symbol": str(token.get("symbol") or event.get("symbol") or "UNKNOWN"),
                "decimals": token.get("decimals"),
            },
            "quote": {
                "address": norm(quote.get("address")),
                "symbol": str(quote.get("symbol") or ""),
                "decimals": quote.get("decimals"),
            },
        }
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            provisional_id = withdrawal_candidate_id(event, cluster)
            provisional_observations[provisional_id] = {
                "event": event_context,
                "cluster": cluster,
                "scan_coverage": scan_coverage,
            }

    if not provisional_observations and not WITHDRAWAL_CANDIDATE_HISTORY_PATH.exists():
        return 0

    history = read_json(WITHDRAWAL_CANDIDATE_HISTORY_PATH, {})
    existing_rows = history.get("candidates", []) if isinstance(history, dict) else []
    by_id = {
        str(row.get("candidate_id")): row
        for row in existing_rows
        if isinstance(row, dict) and row.get("candidate_id")
    }
    observations: dict[str, dict[str, Any]] = {}
    claimed_existing_ids: set[str] = set()
    for provisional_id, observation in sorted(provisional_observations.items()):
        identity = withdrawal_observation_identity(observation)
        anchors = withdrawal_observation_sample_anchors(observation)
        matches: list[tuple[int, str]] = []
        if anchors:
            for row in existing_rows:
                existing_id = str(row.get("candidate_id") or "") if isinstance(row, dict) else ""
                if not existing_id or existing_id in claimed_existing_ids:
                    continue
                latest_observation = row.get("latest_observation", {}) or {}
                if withdrawal_observation_identity(latest_observation) != identity:
                    continue
                overlap_count = len(anchors & withdrawal_observation_sample_anchors(latest_observation))
                if overlap_count:
                    matches.append((-overlap_count, existing_id))
        resolved_id = sorted(matches)[0][1] if matches else provisional_id
        if matches:
            claimed_existing_ids.add(resolved_id)
        elif resolved_id in by_id or resolved_id in observations:
            resolved_id = withdrawal_collision_candidate_id(provisional_id, observation, observed_at)
        observations.setdefault(resolved_id, observation)

    for candidate_id, observation in observations.items():
        previous = by_id.get(candidate_id, {})
        try:
            previous_observation_count = int(previous.get("observation_count") or 0)
        except (TypeError, ValueError):
            previous_observation_count = 0
        by_id[candidate_id] = {
            "candidate_id": candidate_id,
            "first_observed_at": str(previous.get("first_observed_at") or observed_at),
            "last_observed_at": observed_at,
            "observation_count": previous_observation_count + 1,
            "first_observation": previous.get("first_observation") or observation,
            "latest_observation": observation,
        }

    candidates = sorted(
        by_id.values(),
        key=lambda row: (str(row.get("last_observed_at") or ""), str(row.get("candidate_id") or "")),
        reverse=True,
    )[:WITHDRAWAL_CANDIDATE_HISTORY_MAX]
    retained_ids = {str(row.get("candidate_id") or "") for row in candidates}
    write_json(
        WITHDRAWAL_CANDIDATE_HISTORY_PATH,
        {
            "schema_version": 1,
            "updated_at": observed_at,
            "last_scan_at": observed_at,
            "active_candidate_ids": sorted(candidate_id for candidate_id in observations if candidate_id in retained_ids),
            "max_entries": WITHDRAWAL_CANDIDATE_HISTORY_MAX,
            "candidate_count": len(candidates),
            "candidates": candidates,
        },
    )
    return len(observations)


def decimal_from(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


def decimal_from_wei(value: Any) -> Decimal:
    if value in ("", None):
        return Decimal(0)
    try:
        raw = int(str(value), 16) if isinstance(value, str) and value.startswith("0x") else int(value)
    except Exception:
        return Decimal(0)
    return Decimal(raw) / (Decimal(10) ** 18)


def context_price_usdt(event: dict[str, Any]) -> Decimal:
    context = event.get("market_context", {}) or {}
    keys = [
        "observed_binance_alpha_price_usdt",
        "observed_price_usdt",
        "premarket_reference_price_usdt",
        "estimated_snipe_price_usdt",
        "pool_init_price_usdt_per_arx",
        "pool_init_price_usdt_per_cap",
        "pool_init_price_usdt_per_nes",
        "pool_price_usdt",
        "initial_price_usdt",
    ]
    for key in keys:
        raw = context.get(key)
        if raw in ("", None):
            continue
        text = str(raw).split("-")[-1].strip()
        price = decimal_from(text)
        if price > 0:
            return price
    for pool in context.get("pool_zones") or []:
        price = decimal_from(pool.get("price_usdt") or pool.get("initial_price_usdt"))
        if price > 0:
            return price
    return Decimal(0)


def parse_utc8(value: str) -> datetime | None:
    return opening.parse_utc8(value)


def build_events() -> list[dict[str, Any]]:
    config = read_json(CONFIG_PATH, {"items": []})
    latest_cache: dict[str, int] = {}
    review_symbol = os.environ.get("ALPHA_INTRADAY_REVIEW_SYMBOL", "").upper()
    events = []
    for item in config.get("items", []):
        symbol = str(item.get("symbol") or item.get("name") or "UNKNOWN").upper()
        if review_symbol and symbol != review_symbol:
            continue
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority", ""))
        if not priority.startswith(("P0", "P1", "P2")):
            continue
        contracts = [
            row
            for row in item.get("contracts", [])
            if str(row.get("chain", "")).lower() == CHAIN
            and opening.is_address(row.get("address"))
            and norm(row.get("address")) not in opening.QUOTE_TOKENS
        ]
        if not contracts:
            continue
        token_address = norm(contracts[0]["address"])
        for pool in item.get("pool_ids", []):
            if str(pool.get("chain", CHAIN)).lower() != CHAIN:
                continue
            start = parse_utc8(str(pool.get("start_time_utc8") or ""))
            if not start:
                continue
            seconds_since = int((now_utc() - start).total_seconds())
            if seconds_since < 0:
                continue
            max_age = int(os.environ.get("ALPHA_INTRADAY_MAX_AGE_HOURS", "72")) * 3600
            if seconds_since > max_age and not review_symbol:
                continue
            latest = latest_cache.setdefault(CHAIN, opening.latest_block_number(CHAIN))
            opening_block = opening.first_block_at_or_after(CHAIN, int(start.timestamp()), latest)
            if opening_block is None:
                continue
            quote_address = norm(pool.get("quote_address") or opening.USDT)
            events.append(
                {
                    "symbol": symbol,
                    "priority": priority,
                    "chain": CHAIN,
                    "opening_block": opening_block,
                    "latest_block": latest,
                    "start_time_utc8": pool.get("start_time_utc8", ""),
                    "token": opening.token_meta(CHAIN, token_address, symbol),
                    "quote": opening.token_meta(CHAIN, quote_address, opening.QUOTE_TOKENS.get(quote_address, "QUOTE")),
                    "market_context": item.get("market_context", {}),
                    "watch_addresses": item.get("watch_addresses", []),
                    "known_contracts": item.get("known_contracts", []),
                    "cex_deposit_addresses": item.get("cex_deposit_addresses", []),
                    "cex_addresses": item.get("cex_addresses", []),
                    "exchange_aggregator_addresses": item.get("exchange_aggregator_addresses", []),
                    "exchange_aggregator_suspect_addresses": item.get("exchange_aggregator_suspect_addresses", []),
                    "exchange_rebalance_addresses": item.get("exchange_rebalance_addresses", []),
                    "neutral_contracts": item.get("neutral_contracts", []),
                    "lp_locker_addresses": item.get("lp_locker_addresses", []),
                    "staking_addresses": item.get("staking_addresses", []),
                    "hook": pool.get("hook", ""),
                    "operator": pool.get("operator", ""),
                }
            )
            break
    return events


def aggregate_candidate_txs(event: dict[str, Any], from_block: int, to_block: int) -> tuple[list[str], int, int]:
    query = {
        "address": event["token"]["address"],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": [opening.TRANSFER_TOPIC],
    }
    logs = opening.get_logs_quick(
        event["chain"],
        query,
        int(os.environ.get("ALPHA_INTRADAY_LOG_CHUNK_BLOCKS", "1000")),
        int(os.environ.get("ALPHA_INTRADAY_MAX_LOGS", "12000")),
        int(os.environ.get("ALPHA_INTRADAY_RPC_TIMEOUT", "6")),
    )
    aggregate: dict[str, dict[str, Any]] = {}
    decimals = int(event["token"]["decimals"])
    for log in logs:
        tx_hash = str(log.get("transactionHash") or "")
        if not tx_hash:
            continue
        amount = opening.decimal_amount(int(log.get("data") or "0x0", 16), decimals)
        row = aggregate.setdefault(
            tx_hash,
            {
                "tx": tx_hash,
                "sum": Decimal(0),
                "max": Decimal(0),
                "block": int(log.get("blockNumber") or "0x0", 16),
                "idx": int(log.get("transactionIndex") or "0x0", 16),
            },
        )
        row["sum"] += amount
        row["max"] = max(row["max"], amount)
    ordered = sorted(aggregate.values(), key=lambda row: (row["block"], row["idx"]))
    max_candidates = int(os.environ.get("ALPHA_INTRADAY_MAX_RECEIPTS", "120"))
    top_max = sorted(aggregate.values(), key=lambda row: row["max"], reverse=True)[: max_candidates]
    top_sum = sorted(aggregate.values(), key=lambda row: row["sum"], reverse=True)[: max(20, max_candidates // 2)]
    tail = ordered[-max(20, max_candidates // 3) :]
    selected: list[str] = []
    seen = set()
    for row in top_max + top_sum + tail:
        tx_hash = row["tx"]
        if tx_hash not in seen:
            seen.add(tx_hash)
            selected.append(tx_hash)
        if len(selected) >= max_candidates:
            break
    return selected, len(logs), len(aggregate)


def token_transfer_logs(event: dict[str, Any], from_block: int, to_block: int) -> list[dict[str, Any]]:
    query = {
        "address": event["token"]["address"],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": [opening.TRANSFER_TOPIC],
    }
    logs = opening.get_logs_quick(
        event["chain"],
        query,
        int(os.environ.get("ALPHA_INTRADAY_LOG_CHUNK_BLOCKS", "1000")),
        int(os.environ.get("ALPHA_INTRADAY_MAX_LOGS", "12000")),
        int(os.environ.get("ALPHA_INTRADAY_RPC_TIMEOUT", "6")),
    )
    decimals = int(event["token"]["decimals"])
    return [opening.transfer_log(log, decimals) for log in logs]


def known_cex_destination_class(event: dict[str, Any], address: str) -> str:
    class_name = opening.configured_address_class(event, address)
    return class_name if class_name in {"cex_deposit", "cex_hot_wallet"} else ""


def recipient_amount_stats(amounts: list[Decimal]) -> tuple[Decimal, Decimal]:
    ordered = sorted(value for value in amounts if value > 0)
    if not ordered:
        return Decimal(0), Decimal(0)
    count = Decimal(len(ordered))
    mean = sum(ordered, Decimal(0)) / count
    variance = sum(((value - mean) ** 2 for value in ordered), Decimal(0)) / count
    cv = variance.sqrt() / mean if mean > 0 else Decimal(0)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    return median, cv


def withdrawal_block_timestamp(chain: str, block_number: int) -> int:
    global WITHDRAWAL_TIME_RPC_ATTEMPTS_USED
    last_error: Exception | None = None
    for url in opening.rpc_urls(chain)[:2]:
        if WITHDRAWAL_TIME_RPC_ATTEMPTS_USED >= WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS:
            break
        WITHDRAWAL_TIME_RPC_ATTEMPTS_USED += 1
        try:
            block = opening.rpc_call_url(
                url,
                "eth_getBlockByNumber",
                [hex(block_number), False],
                timeout=WITHDRAWAL_TIME_RPC_TIMEOUT_SECONDS,
            )
            if not block:
                raise RuntimeError(f"block not found: {chain} {block_number}")
            return int(block.get("timestamp") or "0x0", 16)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("withdrawal block-time RPC attempt budget exhausted")


def withdrawal_time_window_evidence(chain: str, first_block: int, last_block: int) -> dict[str, Any]:
    try:
        first_timestamp = withdrawal_block_timestamp(chain, first_block)
        last_timestamp = first_timestamp if last_block == first_block else withdrawal_block_timestamp(chain, last_block)
        if first_timestamp <= 0 or last_timestamp < first_timestamp:
            raise ValueError("invalid block timestamp order")
        first_utc = datetime.fromtimestamp(first_timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
        last_utc = datetime.fromtimestamp(last_timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return {
            "first_block_time_utc": None,
            "last_block_time_utc": None,
            "window_seconds": None,
            "time_window_evidence": "rpc_block_header_unavailable",
        }
    return {
        "first_block_time_utc": first_utc,
        "last_block_time_utc": last_utc,
        "window_seconds": last_timestamp - first_timestamp,
        "time_window_evidence": "rpc_block_header",
    }


def cex_withdrawal_cluster(
    event: dict[str, Any],
    transfers: list[dict[str, Any]],
    from_block: int,
    to_block: int,
) -> dict[str, Any]:
    min_recipients = 8
    max_cv = Decimal("0.20")
    max_block_span = 1200
    min_token = Decimal("100000")
    min_quote = Decimal("10000")
    token_address = norm(event["token"]["address"])
    excluded = opening.excluded_addresses(event)
    labels = opening.global_address_labels(event["chain"])
    hot_sources = {
        address: row
        for address, row in labels.items()
        if str(row.get("class") or "") == "cex_hot_wallet"
    }
    known_recipients = excluded | set(labels)
    for source in (event, event.get("market_context", {})):
        for values in source.values():
            if not isinstance(values, list):
                continue
            for item in values:
                address = norm(item.get("address") if isinstance(item, dict) else item)
                if opening.is_address(address):
                    known_recipients.add(address)
    groups: dict[str, dict[str, Any]] = {}
    for row in transfers:
        if norm(row.get("token")) != token_address:
            continue
        source_address = norm(row.get("from"))
        source = hot_sources.get(source_address)
        if not source:
            continue
        group = groups.setdefault(
            source_address,
            {"source": dict(source, address=source_address), "transfers": [], "excluded_known_infrastructure_transfer_count": 0},
        )
        recipient = norm(row.get("to"))
        amount = decimal_from(row.get("amount"))
        if not opening.is_address(recipient) or recipient in known_recipients or amount <= 0:
            group["excluded_known_infrastructure_transfer_count"] += 1
            continue
        group["transfers"].append(
            {
                "recipient": recipient,
                "amount": amount,
                "block": int(row.get("block") or 0),
                "log_index": int(row.get("log_index") or 0),
                "tx": str(row.get("tx") or ""),
            }
        )

    price = context_price_usdt(event)
    clusters: list[dict[str, Any]] = []
    for group in groups.values():
        recipient_totals: dict[str, Decimal] = {}
        for row in group["transfers"]:
            recipient_totals[row["recipient"]] = recipient_totals.get(row["recipient"], Decimal(0)) + row["amount"]
        if len(recipient_totals) < min_recipients:
            continue
        median, cv = recipient_amount_stats(list(recipient_totals.values()))
        total_token = sum(recipient_totals.values(), Decimal(0))
        total_quote = total_token * price if price > 0 else Decimal(0)
        if (price > 0 and total_quote < min_quote) or (price <= 0 and total_token < min_token):
            continue
        if cv > max_cv:
            continue
        first_block = min(row["block"] for row in group["transfers"])
        last_block = max(row["block"] for row in group["transfers"])
        if last_block - first_block > max_block_span:
            continue
        sample_transfers = sorted(
            group["transfers"],
            key=lambda row: (row["block"], row["log_index"], row["tx"], row["recipient"]),
        )[:20]
        time_window = withdrawal_time_window_evidence(event["chain"], first_block, last_block)
        unresolved_gates = [
            "recipient_freshness",
            "unknown_contract_filter",
            "log_window_completeness",
            "common_gas_source",
            "next_hop",
            "cex_redeposit",
            "dex_execution",
            "quote_recovery",
            "entity_linkage",
            "operator_conflict",
        ]
        if time_window["time_window_evidence"] != "rpc_block_header":
            unresolved_gates.insert(2, "exact_time_window")
        clusters.append(
            {
                "type": "cex_withdrawal_cluster_candidate",
                "status": "candidate",
                "direction": "unknown",
                "action": "Observe",
                "alert_policy": "report_only",
                "common_control_state": "coordination_candidate_unverified",
                "source_address": group["source"]["address"],
                "source_exchange": str(group["source"].get("exchange") or "unknown"),
                "source_class": "cex_hot_wallet",
                "exchange_label_quality": "tracked_global_label",
                "transfer_count": len(group["transfers"]),
                "recipient_count": len(recipient_totals),
                "fresh_recipient_count": None,
                "total_token": opening.decimal_str(total_token),
                "total_quote_estimate": opening.decimal_str(total_quote),
                "outflow_pct_mc": None,
                "median_recipient_token": opening.decimal_str(median),
                "equal_tranche_cv": opening.decimal_str(cv),
                "first_block": first_block,
                "last_block": last_block,
                "window_blocks": f"{first_block}->{last_block}",
                **time_window,
                "common_gas_source_ratio": None,
                "next_hop_state": "unknown",
                "cex_redeposit_state": "unknown",
                "quote_recovery_state": "unknown",
                "recipient_contract_state": "unknown_for_unlabeled_addresses",
                "excluded_known_infrastructure_transfer_count": group["excluded_known_infrastructure_transfer_count"],
                "unresolved_gates": unresolved_gates,
                "sample_transfers": [
                    {
                        "recipient": row["recipient"],
                        "amount": opening.decimal_str(row["amount"]),
                        "block": row["block"],
                        "log_index": row["log_index"],
                        "tx": row["tx"],
                    }
                    for row in sample_transfers
                ],
            }
        )
    clusters.sort(key=lambda row: (-decimal_from(row["total_quote_estimate"]), -decimal_from(row["total_token"]), row["source_address"]))
    return {
        "type": "cex_withdrawal_cluster",
        "status": "candidate" if clusters else "none",
        "direction": "unknown",
        "action": "Observe" if clusters else "",
        "alert_policy": "report_only",
        "evidence_scope": "fetched_token_transfer_logs",
        "coverage_state": "max_log_limit_reached"
        if len(transfers) >= int(os.environ.get("ALPHA_INTRADAY_MAX_LOGS", "12000"))
        else "fetched_window_unverified",
        "scan_window_blocks": f"{from_block}->{to_block}",
        "input_transfer_count": len(transfers),
        "tracked_hot_source_count": len(groups),
        "candidate_count": len(clusters),
        "rejected_known_infrastructure_transfer_count": sum(
            int(group["excluded_known_infrastructure_transfer_count"]) for group in groups.values()
        ),
        "criteria": {
            "source_class": "tracked_global_cex_hot_wallet",
            "min_recipient_count": min_recipients,
            "max_equal_tranche_cv": opening.decimal_str(max_cv),
            "max_block_span": max_block_span,
            "min_token_or_quote": {
                "token": opening.decimal_str(min_token),
                "quote": opening.decimal_str(min_quote),
            },
        },
        "clusters": clusters,
    }


def runtime_cex_deposit_candidates(
    event: dict[str, Any],
    from_block: int,
    to_block: int,
    transfers: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    if os.environ.get("ALPHA_INTRADAY_RUNTIME_CEX_DEPOSIT_CANDIDATES", "1") != "1":
        return {}
    min_out = Decimal(os.environ.get("ALPHA_INTRADAY_RUNTIME_CEX_SWEEP_MIN_TOKEN", "1000"))
    min_count = int(os.environ.get("ALPHA_INTRADAY_RUNTIME_CEX_SWEEP_MIN_COUNT", "1"))
    excluded = opening.excluded_addresses(event)
    inflow: dict[str, dict[str, Any]] = {}
    outflow: dict[str, dict[str, Any]] = {}
    for row in transfers if transfers is not None else token_transfer_logs(event, from_block, to_block):
        from_addr = norm(row.get("from"))
        to_addr = norm(row.get("to"))
        amount = row.get("amount", Decimal(0))
        order = (int(row.get("block") or 0), int(row.get("log_index") or 0))
        if to_addr and to_addr not in excluded and from_addr not in excluded:
            item = inflow.setdefault(to_addr, {"amount": Decimal(0), "count": 0, "first_order": order})
            item["amount"] += amount
            item["count"] += 1
            item["first_order"] = min(item["first_order"], order)
        if not from_addr or from_addr in excluded:
            continue
        destination_class = known_cex_destination_class(event, to_addr)
        if not destination_class:
            continue
        item = outflow.setdefault(
            from_addr,
            {
                "address": from_addr,
                "amount": Decimal(0),
                "count": 0,
                "last_order": order,
                "destination_classes": set(),
                "destinations": set(),
            },
        )
        item["amount"] += amount
        item["count"] += 1
        item["last_order"] = max(item["last_order"], order)
        item["destination_classes"].add(destination_class)
        item["destinations"].add(to_addr)
    candidates: dict[str, dict[str, Any]] = {}
    for address, out_item in outflow.items():
        in_item = inflow.get(address)
        if not in_item:
            continue
        if out_item["amount"] < min_out or out_item["count"] < min_count:
            continue
        if out_item["last_order"] < in_item["first_order"]:
            continue
        if opening.configured_address_class(event, address):
            continue
        candidates[address] = {
            "address": address,
            "class": "cex_deposit_candidate",
            "in_amount": opening.decimal_str(in_item["amount"]),
            "out_amount": opening.decimal_str(out_item["amount"]),
            "out_count": out_item["count"],
            "destination_classes": sorted(out_item["destination_classes"]),
            "destinations": sorted(out_item["destinations"])[:3],
        }
    return candidates


def summarize_flow_tx(
    event: dict[str, Any],
    tx_hash: str,
    runtime_cex_candidates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    receipt = opening.quick_rpc_call(
        event["chain"],
        "eth_getTransactionReceipt",
        [tx_hash],
        int(os.environ.get("ALPHA_INTRADAY_RPC_TIMEOUT", "6")),
    )
    if not receipt:
        return None
    transfers = opening.receipt_transfers_from_receipt(receipt, event["token"], event["quote"])
    nets = opening.net_by_address(transfers, event["token"]["address"], event["quote"]["address"])
    buyer, token_bought, spent = opening.best_buyer(event, nets)
    if token_bought and not spent:
        spent = opening.pool_side_quote_in(event, nets)
    sellers: list[tuple[str, Decimal, Decimal]] = []
    excluded = opening.excluded_addresses(event)
    for address, amounts in nets.items():
        if address in excluded:
            continue
        token_net = amounts.get("token", Decimal(0))
        quote_net = amounts.get("quote", Decimal(0))
        if token_net < 0 and quote_net > 0:
            sellers.append((address, -token_net, quote_net))
    seller, sold_token, got_quote = max(sellers, key=lambda row: row[2], default=("", Decimal(0), Decimal(0)))
    min_quote = Decimal(os.environ.get("ALPHA_INTRADAY_MIN_QUOTE", "2000"))
    cex_rows = cex_deposit_transfers(event, transfers, runtime_cex_candidates)
    cex_token = sum((row["amount"] for row in cex_rows), Decimal(0))
    price = context_price_usdt(event)
    cex_quote_est = cex_token * price if price > 0 else Decimal(0)
    min_cex_token = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_MIN_TOKEN", "100000"))
    min_cex_quote = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_MIN_QUOTE", "10000"))
    cex_significant = cex_token >= min_cex_token or (cex_quote_est and cex_quote_est >= min_cex_quote)
    gas_rows: list[dict[str, Any]] = []
    gas_bnb = Decimal(0)
    if cex_significant:
        gas_rows = cex_gas_priming_transfers(event, {row["from"] for row in cex_rows}, opening.hex_to_int(receipt.get("blockNumber")) or 0)
        gas_bnb = sum((row["amount_bnb"] for row in gas_rows), Decimal(0))
    if spent < min_quote and got_quote < min_quote and not cex_significant:
        return None
    return {
        "tx": tx_hash,
        "block": opening.hex_to_int(receipt.get("blockNumber")),
        "tx_index": opening.hex_to_int(receipt.get("transactionIndex")),
        "buyer": buyer,
        "buy_token": opening.decimal_str(token_bought),
        "spent_quote": opening.decimal_str(spent),
        "buy_avg": opening.decimal_str(spent / token_bought if spent and token_bought else None),
        "seller": seller,
        "sell_token": opening.decimal_str(sold_token),
        "got_quote": opening.decimal_str(got_quote),
        "sell_avg": opening.decimal_str(got_quote / sold_token if got_quote and sold_token else None),
        "cex_token_deposit": opening.decimal_str(cex_token),
        "cex_quote_estimate": opening.decimal_str(cex_quote_est),
        "cex_deposit_count": len(cex_rows),
        "cex_destination_classes": ",".join(sorted({row["class"] for row in cex_rows})),
        "runtime_cex_deposit_candidate_count": sum(1 for row in cex_rows if row["class"] == "cex_deposit_candidate"),
        "cex_gas_priming_count": len(gas_rows),
        "cex_gas_priming_bnb": opening.decimal_str(gas_bnb),
        "cex_gas_priming_sources": ",".join(sorted({row["source_class"] for row in gas_rows})),
    }


def cex_deposit_transfers(
    event: dict[str, Any],
    transfers: list[dict[str, Any]],
    runtime_cex_candidates: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    excluded = opening.excluded_addresses(event)
    runtime_cex_candidates = runtime_cex_candidates or {}
    rows: list[dict[str, Any]] = []
    token_address = norm(event["token"]["address"])
    for row in transfers:
        if norm(row.get("token")) != token_address:
            continue
        from_addr = norm(row.get("from"))
        to_addr = norm(row.get("to"))
        if from_addr in excluded:
            continue
        destination_class = opening.destination_class(event, to_addr)
        if destination_class not in {"cex_deposit", "cex_hot_wallet"}:
            if to_addr in runtime_cex_candidates:
                destination_class = "cex_deposit_candidate"
            else:
                continue
        if destination_class == "cex_deposit_candidate" and to_addr in excluded:
            continue
        rows.append({"from": from_addr, "to": to_addr, "amount": row["amount"], "class": destination_class})
    return rows


def cex_gas_priming_transfers(event: dict[str, Any], targets: set[str], deposit_block: int) -> list[dict[str, Any]]:
    targets = {norm(value) for value in targets if opening.is_address(value)}
    if not targets or deposit_block <= 0 or os.environ.get("ALPHA_INTRADAY_CEX_GAS_PRIMING", "1") != "1":
        return []
    lookback = int(os.environ.get("ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS", "1200"))
    if lookback <= 0:
        return []
    min_bnb = Decimal(os.environ.get("ALPHA_INTRADAY_GAS_PRIMING_MIN_BNB", "0.001"))
    max_hits = int(os.environ.get("ALPHA_INTRADAY_GAS_PRIMING_MAX_HITS", "20"))
    timeout = int(os.environ.get("ALPHA_INTRADAY_RPC_TIMEOUT", "6"))
    found_targets: set[str] = set()
    rows: list[dict[str, Any]] = []
    from_block = max(0, deposit_block - lookback)
    for block_number in range(deposit_block - 1, from_block - 1, -1):
        for tx in block_transactions(event["chain"], block_number, timeout):
            to_addr = norm(tx.get("to"))
            if to_addr not in targets or to_addr in found_targets:
                continue
            amount_bnb = decimal_from_wei(tx.get("value"))
            if amount_bnb < min_bnb:
                continue
            from_addr = norm(tx.get("from"))
            source_class = opening.destination_class(event, from_addr)
            if source_class not in {"cex_deposit", "cex_hot_wallet"}:
                continue
            rows.append(
                {
                    "from": from_addr,
                    "to": to_addr,
                    "amount_bnb": amount_bnb,
                    "block": block_number,
                    "tx": str(tx.get("hash") or ""),
                    "source_class": source_class,
                }
            )
            found_targets.add(to_addr)
            if len(rows) >= max_hits or found_targets == targets:
                return rows
    return rows


def block_transactions(chain: str, block_number: int, timeout: int) -> list[dict[str, Any]]:
    key = (chain, block_number)
    if key not in BLOCK_TX_CACHE:
        block = opening.quick_rpc_call(chain, "eth_getBlockByNumber", [hex(block_number), True], timeout) or {}
        txs = block.get("transactions") if isinstance(block, dict) else []
        BLOCK_TX_CACHE[key] = txs if isinstance(txs, list) else []
    return BLOCK_TX_CACHE[key]


def analyze_rows(event: dict[str, Any], rows: list[dict[str, Any]], from_block: int, to_block: int, logs: int, txs: int) -> dict[str, Any]:
    address_net: dict[str, Decimal] = {}
    address_buy: dict[str, Decimal] = {}
    address_sell: dict[str, Decimal] = {}
    cex_token_deposit = Decimal(0)
    cex_quote_estimate = Decimal(0)
    cex_deposit_count = 0
    cex_destination_classes: set[str] = set()
    runtime_cex_deposit_candidate_count = 0
    cex_gas_priming_bnb = Decimal(0)
    cex_gas_priming_count = 0
    for row in rows:
        buyer = norm(row.get("buyer"))
        seller = norm(row.get("seller"))
        spent = decimal_from(row.get("spent_quote"))
        got = decimal_from(row.get("got_quote"))
        if buyer and spent > 0:
            address_net[buyer] = address_net.get(buyer, Decimal(0)) + spent
            address_buy[buyer] = address_buy.get(buyer, Decimal(0)) + spent
        if seller and got > 0:
            address_net[seller] = address_net.get(seller, Decimal(0)) - got
            address_sell[seller] = address_sell.get(seller, Decimal(0)) + got
        cex_token_deposit += decimal_from(row.get("cex_token_deposit"))
        cex_quote_estimate += decimal_from(row.get("cex_quote_estimate"))
        cex_deposit_count += int(row.get("cex_deposit_count") or 0)
        runtime_cex_deposit_candidate_count += int(row.get("runtime_cex_deposit_candidate_count") or 0)
        for class_name in str(row.get("cex_destination_classes") or "").split(","):
            if class_name:
                cex_destination_classes.add(class_name)
        cex_gas_priming_bnb += decimal_from(row.get("cex_gas_priming_bnb"))
        cex_gas_priming_count += int(row.get("cex_gas_priming_count") or 0)
    net_buy = sum((value for value in address_net.values() if value > 0), Decimal(0))
    net_sell = sum((-value for value in address_net.values() if value < 0), Decimal(0))
    total_buy = sum(address_buy.values(), Decimal(0))
    total_sell = sum(address_sell.values(), Decimal(0))
    buy_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_BUY_ALERT_QUOTE", "20000"))
    sell_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_SELL_ALERT_QUOTE", "20000"))
    cex_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_ALERT_QUOTE", "10000"))
    cex_token_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_ALERT_TOKEN", "100000"))
    cex_alert = cex_deposit_count > 0 and (cex_quote_estimate >= cex_threshold or cex_token_deposit >= cex_token_threshold)
    cex_path_label = "候选CEX充值路径" if runtime_cex_deposit_candidate_count else "CEX充值/热钱包"
    if net_sell >= sell_threshold and net_sell >= net_buy * Decimal("1.2"):
        direction = "偏空"
        trade_signal = "卖出/减仓；盘中大额净卖出"
        spot_action = "持仓降风险；空仓不接反抽"
    elif cex_alert and net_buy >= buy_threshold and cex_gas_priming_count:
        direction = "冲高派发风险"
        trade_signal = f"不追；净买伴随CEX打gas和{cex_path_label}预出货"
        spot_action = "持仓冲高降风险；空仓等派发结束"
    elif cex_alert and net_buy >= buy_threshold:
        direction = "冲高派发风险"
        trade_signal = f"不追；链上净买同时出现{cex_path_label}预出货"
        spot_action = "持仓冲高降风险；空仓等派发结束"
    elif cex_alert and cex_gas_priming_count:
        direction = "偏空"
        trade_signal = f"卖出/减仓；CEX打gas后代币进入{cex_path_label}"
        spot_action = "持仓降风险；空仓不追"
    elif cex_alert:
        direction = "偏空"
        trade_signal = f"卖出/减仓；代币进入{cex_path_label}"
        spot_action = "持仓降风险；空仓不追"
    elif net_buy >= buy_threshold and net_buy >= net_sell * Decimal("1.5"):
        direction = "观察偏多"
        trade_signal = "盘中大额净买入；只等回踩确认"
        spot_action = "不追高；回踩不破再小仓试探"
    elif total_buy >= buy_threshold or total_sell >= sell_threshold:
        direction = "分歧"
        trade_signal = "盘中大额买卖对冲；观察"
        spot_action = "不追；等净方向明确"
    else:
        direction = "观察"
        trade_signal = "无新增大额方向"
        spot_action = "观察"
    top_net_buyers = sorted(((a, v) for a, v in address_net.items() if v > 0), key=lambda row: row[1], reverse=True)[:5]
    top_net_sellers = sorted(((a, -v) for a, v in address_net.items() if v < 0), key=lambda row: row[1], reverse=True)[:5]
    return {
        "direction": direction,
        "trade_signal": trade_signal,
        "spot_action": spot_action,
        "perp_action": "只在合约真实可交易且深度足够时参考；无工具时按现货减仓/不接处理",
        "window_blocks": f"{from_block}->{to_block}",
        "candidate_logs": logs,
        "candidate_txs": txs,
        "sampled_rows": len(rows),
        "total_buy_quote": opening.decimal_str(total_buy),
        "total_sell_quote": opening.decimal_str(total_sell),
        "net_buy_quote": opening.decimal_str(net_buy),
        "net_sell_quote": opening.decimal_str(net_sell),
        "cex_token_deposit": opening.decimal_str(cex_token_deposit),
        "cex_quote_estimate": opening.decimal_str(cex_quote_estimate),
        "cex_deposit_count": cex_deposit_count,
        "cex_destination_classes": ",".join(sorted(cex_destination_classes)),
        "runtime_cex_deposit_candidate_count": runtime_cex_deposit_candidate_count,
        "cex_gas_priming_bnb": opening.decimal_str(cex_gas_priming_bnb),
        "cex_gas_priming_count": cex_gas_priming_count,
        "top_net_buyers": [{"address": a, "quote": opening.decimal_str(v)} for a, v in top_net_buyers],
        "top_net_sellers": [{"address": a, "quote": opening.decimal_str(v)} for a, v in top_net_sellers],
    }


def scan_event(event: dict[str, Any]) -> dict[str, Any]:
    latest = int(event["latest_block"])
    forced_from = os.environ.get("ALPHA_INTRADAY_FROM_BLOCK")
    forced_to = os.environ.get("ALPHA_INTRADAY_TO_BLOCK")
    if forced_from and forced_to:
        from_block = int(forced_from)
        to_block = int(forced_to)
    else:
        window = int(os.environ.get("ALPHA_INTRADAY_WINDOW_BLOCKS", "1800"))
        from_block = max(int(event["opening_block"]), latest - window)
        to_block = latest
    tx_hashes, logs, txs = aggregate_candidate_txs(event, from_block, to_block)
    transfer_rows = token_transfer_logs(event, from_block, to_block)
    runtime_candidates = runtime_cex_deposit_candidates(event, from_block, to_block, transfer_rows)
    withdrawal_cluster = cex_withdrawal_cluster(event, transfer_rows, from_block, to_block)
    rows: list[dict[str, Any]] = []
    scan_limited = False
    timeout_seconds = int(os.environ.get("ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS", "20"))
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    for tx_hash in tx_hashes:
        if deadline is not None and time.monotonic() >= deadline:
            scan_limited = True
            break
        try:
            row = summarize_flow_tx(event, tx_hash, runtime_candidates)
        except Exception:
            continue
        if row:
            rows.append(row)
    analysis = analyze_rows(event, rows, from_block, to_block, logs, txs)
    analysis["cex_withdrawal_cluster"] = withdrawal_cluster
    analysis["scan_limited"] = scan_limited
    analysis["sampled_receipts"] = len(rows)
    return {
        **event,
        "status": "scanned",
        "from_block": from_block,
        "to_block": to_block,
        "runtime_cex_deposit_candidates": list(runtime_candidates.values())[:20],
        "rows": rows,
        "analysis": analysis,
    }


def build_snapshot() -> dict[str, Any]:
    events = [scan_event(event) for event in build_events()]
    keys = [key for event in events for key in event_alert_keys(event)]
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if key not in seen]
    return {
        "generated_at": now_iso(),
        "event_count": len(events),
        "alert_count": len(keys),
        "new_alert_count": len(new_keys),
        "events": events,
    }


def event_alert_keys(event: dict[str, Any]) -> list[str]:
    analysis = event.get("analysis", {})
    keys = []
    buy = decimal_from(analysis.get("net_buy_quote"))
    sell = decimal_from(analysis.get("net_sell_quote"))
    buy_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_BUY_ALERT_QUOTE", "20000"))
    sell_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_SELL_ALERT_QUOTE", "20000"))
    cex_quote = decimal_from(analysis.get("cex_quote_estimate"))
    cex_token = decimal_from(analysis.get("cex_token_deposit"))
    cex_count = int(analysis.get("cex_deposit_count") or 0)
    cex_gas_count = int(analysis.get("cex_gas_priming_count") or 0)
    cex_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_ALERT_QUOTE", "10000"))
    cex_token_threshold = Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_ALERT_TOKEN", "100000"))
    if buy >= buy_threshold or sell >= sell_threshold or (cex_count and (cex_quote >= cex_threshold or cex_token >= cex_token_threshold)):
        keys.append(
            "|".join(
                [
                    "intraday_flow",
                    event["symbol"],
                    analysis.get("direction", ""),
                    amount_bucket(buy, Decimal("10000")),
                    amount_bucket(sell, Decimal("10000")),
                    amount_bucket(cex_quote, Decimal("10000")),
                    amount_bucket(cex_token, Decimal(os.environ.get("ALPHA_INTRADAY_CEX_DEPOSIT_TOKEN_BUCKET", "100000"))),
                    str(min(cex_gas_count, 9)),
                    alert_time_bucket(),
                ]
            )
        )
    return keys


def alert_time_bucket() -> str:
    minutes = int(os.environ.get("ALPHA_INTRADAY_ALERT_BUCKET_MINUTES", "60"))
    if minutes <= 0:
        minutes = 60
    current = now_utc()
    total_minutes = current.hour * 60 + current.minute
    bucket_minutes = (total_minutes // minutes) * minutes
    bucket = current.replace(hour=bucket_minutes // 60, minute=bucket_minutes % 60, second=0)
    return bucket.strftime("%Y-%m-%dT%H:%MZ")


def amount_bucket(value: Decimal, step: Decimal) -> str:
    if value <= 0:
        return "0"
    return opening.decimal_str((value // step) * step)


def action_marker(analysis: dict[str, Any]) -> str:
    signal = str(analysis.get("trade_signal") or "")
    direction = str(analysis.get("direction") or "")
    important_terms = ("CEX预出货", "CEX打gas", "净买入", "净卖出", "卖出/减仓", "代币进入CEX", "候选充值")
    if any(term in signal for term in important_terms) or direction in {"偏空", "冲高派发风险", "观察偏多"}:
        return "❗"
    return ""


def telegram_amount(value: Any) -> str:
    amount = decimal_from(value)
    absolute = abs(amount)
    suffix = ""
    if absolute >= Decimal("1000000"):
        amount /= Decimal("1000000")
        suffix = "M"
    elif absolute >= Decimal("1000"):
        amount /= Decimal("1000")
        suffix = "K"
    text = opening.format_amount(amount)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def telegram_risk_key(event: dict[str, Any]) -> tuple[Any, ...]:
    analysis = event.get("analysis", {})
    direction_rank = {
        "冲高派发风险": 0,
        "偏空": 1,
        "分歧": 2,
        "观察偏多": 3,
    }.get(str(analysis.get("direction") or ""), 4)
    priority = str(event.get("priority") or "")
    priority_rank = 0 if priority.startswith("P0") else 1 if priority.startswith("P1") else 2
    return (
        direction_rank,
        priority_rank,
        -int(analysis.get("cex_gas_priming_count") or 0),
        -decimal_from(analysis.get("cex_quote_estimate")),
        -decimal_from(analysis.get("net_sell_quote")),
        -decimal_from(analysis.get("net_buy_quote")),
        str(event.get("symbol") or ""),
    )


def telegram_event_metrics(event: dict[str, Any]) -> str:
    analysis = event.get("analysis", {})
    quote_symbol = event["quote"]["symbol"]
    token_symbol = event["token"]["symbol"]
    metrics: list[str] = []
    net_buy = decimal_from(analysis.get("net_buy_quote"))
    net_sell = decimal_from(analysis.get("net_sell_quote"))
    if net_buy > 0:
        metrics.append(f"净买≈{telegram_amount(net_buy)} {quote_symbol}")
    if net_sell > 0:
        metrics.append(f"净卖≈{telegram_amount(net_sell)} {quote_symbol}")

    cex_quote = decimal_from(analysis.get("cex_quote_estimate"))
    cex_token = decimal_from(analysis.get("cex_token_deposit"))
    if cex_quote > 0 or cex_token > 0:
        amounts = []
        if cex_quote > 0:
            amounts.append(f"{telegram_amount(cex_quote)} {quote_symbol}")
        if cex_token > 0:
            amounts.append(f"{telegram_amount(cex_token)} {token_symbol}")
        cex_text = f"CEX预出货≈{' / '.join(amounts)}"
        cex_classes = str(analysis.get("cex_destination_classes") or "")
        if cex_classes:
            cex_text += f" [{cex_classes}]"
        metrics.append(cex_text)
    runtime_candidates = int(analysis.get("runtime_cex_deposit_candidate_count") or 0)
    if runtime_candidates:
        metrics.append(f"候选充值路径={runtime_candidates}")

    gas_bnb = decimal_from(analysis.get("cex_gas_priming_bnb"))
    gas_count = int(analysis.get("cex_gas_priming_count") or 0)
    if gas_bnb > 0 or gas_count:
        metrics.append(f"CEX打gas≈{telegram_amount(gas_bnb)} BNB / {gas_count} 次")

    withdrawal = analysis.get("cex_withdrawal_cluster") or {}
    withdrawal_count = int(withdrawal.get("candidate_count") or 0)
    if withdrawal_count:
        cluster = (withdrawal.get("clusters") or [{}])[0]
        cluster_parts = [f"提现簇候选×{withdrawal_count}"]
        recipient_count = int(cluster.get("recipient_count") or 0)
        if recipient_count:
            cluster_parts.append(f"{recipient_count}地址")
        cluster_quote = decimal_from(cluster.get("total_quote_estimate"))
        cluster_token = decimal_from(cluster.get("total_token"))
        if cluster_quote > 0:
            cluster_parts.append(f"≈{telegram_amount(cluster_quote)} {quote_symbol}")
        elif cluster_token > 0:
            cluster_parts.append(f"≈{telegram_amount(cluster_token)} {token_symbol}")
        cluster_parts.append("方向未知/仅观察")
        metrics.append(" ".join(cluster_parts))

    sampled = analysis.get("sampled_receipts", analysis.get("sampled_rows", 0))
    candidates = analysis.get("candidate_txs", 0)
    scan_state = "扫描受限" if analysis.get("scan_limited") else "扫描完成"
    metrics.append(f"{scan_state} {sampled}/{candidates}")
    return "｜".join(metrics)


def telegram_text(snapshot: dict[str, Any]) -> str:
    alert_events = [event for event in snapshot.get("events", []) if event_alert_keys(event)]
    new_keys = set(snapshot.get("_telegram_new_alert_keys") or [])
    alert_events.sort(
        key=lambda event: (
            0 if new_keys.intersection(event_alert_keys(event)) else 1,
            *telegram_risk_key(event),
        )
    )
    displayed_events = alert_events[:2]
    new_alert_count = snapshot.get("new_alert_count", snapshot.get("alert_count", len(alert_events)))
    header = f"Alpha盘中大额流｜新增告警: {new_alert_count}"
    if len(alert_events) > len(displayed_events):
        header += f"｜显示 {len(displayed_events)}/{len(alert_events)}"
    lines = [header]
    for event in displayed_events:
        analysis = event.get("analysis", {})
        marker = action_marker(analysis)
        lines.extend(
            [
                (
                    f"{marker}{event['symbol']} {event.get('priority') or '-'}｜"
                    f"{analysis.get('direction', '观察')}｜"
                    f"买卖信号: {marker}{analysis.get('trade_signal', '观察')}"
                ),
                f"现货动作: {analysis.get('spot_action', '')}",
                telegram_event_metrics(event),
            ]
        )
    if not displayed_events:
        lines.append("本轮无可推送告警")
    lines.append("合约边界：仅在真实可交易且深度足够时参考")
    return "\n".join(lines).strip()


def push_signature(snapshot: dict[str, Any]) -> str:
    parts = []
    for event in snapshot.get("events", [])[:4]:
        analysis = event.get("analysis", {})
        parts.append(
            "|".join(
                [
                    event["symbol"],
                    analysis.get("direction", ""),
                    amount_bucket(decimal_from(analysis.get("net_buy_quote")), Decimal("10000")),
                    amount_bucket(decimal_from(analysis.get("net_sell_quote")), Decimal("10000")),
                    amount_bucket(decimal_from(analysis.get("cex_quote_estimate")), Decimal("10000")),
                    str(min(int(analysis.get("cex_gas_priming_count") or 0), 9)),
                ]
            )
        )
    return "\n".join(parts)


def suppress_repeat_push(snapshot: dict[str, Any]) -> bool:
    ttl_minutes = int(os.environ.get("ALPHA_INTRADAY_REPEAT_SUPPRESS_MINUTES", "30"))
    if ttl_minutes <= 0:
        return False
    last = read_json(LAST_PUSH_PATH, {})
    if last.get("signature") != push_signature(snapshot):
        return False
    try:
        sent_at = datetime.fromisoformat(str(last.get("sent_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    return now_utc() - sent_at.astimezone(timezone.utc) < timedelta(minutes=ttl_minutes)


def maybe_send_telegram(snapshot: dict[str, Any]) -> None:
    if os.environ.get("ALPHA_INTRADAY_TELEGRAM", os.environ.get("SNIPER_MONITOR_TELEGRAM", "0")) != "1":
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    keys = [key for event in snapshot.get("events", []) for key in event_alert_keys(event)]
    if not keys:
        return
    seen = set(read_json(SEEN_PATH, []))
    new_keys = [key for key in keys if key not in seen]
    if not new_keys and os.environ.get("ALPHA_INTRADAY_FORCE_TELEGRAM") != "1":
        return
    if suppress_repeat_push(snapshot) and os.environ.get("ALPHA_INTRADAY_FORCE_TELEGRAM") != "1":
        write_json(SEEN_PATH, sorted(seen | set(keys)))
        return
    push_snapshot = {**snapshot, "_telegram_new_alert_keys": new_keys}
    text = telegram_text(push_snapshot)[:TELEGRAM_LIMIT]
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        receipt = read_telegram_send_receipt(response)
    write_json(SEEN_PATH, sorted(seen | set(keys)))
    record_telegram_send_receipt(
        LAST_PUSH_PATH,
        sent_at=now_iso(),
        signature=push_signature(snapshot),
        text=text,
        receipt=receipt,
    )


def short_addr(value: str) -> str:
    return opening.short_addr(value)


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Intraday Flow Watch",
        "",
        f"- generated_at: `{snapshot.get('generated_at')}`",
        f"- event_count: `{snapshot.get('event_count')}`",
        f"- alert_count: `{snapshot.get('alert_count')}`",
        f"- new_alert_count: `{snapshot.get('new_alert_count')}`",
        "",
    ]
    for event in snapshot.get("events", []):
        analysis = event.get("analysis", {})
        withdrawal = analysis.get("cex_withdrawal_cluster", {}) or {}
        lines.extend(
            [
                f"## {event['symbol']}",
                "",
                f"- direction: {analysis.get('direction')}",
                f"- trade_signal: {analysis.get('trade_signal')}",
                f"- spot_action: {analysis.get('spot_action')}",
                f"- window_blocks: `{analysis.get('window_blocks')}`",
                f"- candidate_logs: `{analysis.get('candidate_logs')}`",
                f"- candidate_txs: `{analysis.get('candidate_txs')}`",
                f"- scan_limited: `{analysis.get('scan_limited')}`",
                f"- sampled_receipts: `{analysis.get('sampled_receipts')}`",
                f"- sampled_rows: `{analysis.get('sampled_rows')}`",
                f"- total_buy_quote: `{analysis.get('total_buy_quote')}`",
                f"- total_sell_quote: `{analysis.get('total_sell_quote')}`",
                f"- net_buy_quote: `{analysis.get('net_buy_quote')}`",
                f"- net_sell_quote: `{analysis.get('net_sell_quote')}`",
                f"- cex_token_deposit: `{analysis.get('cex_token_deposit')}`",
                f"- cex_quote_estimate: `{analysis.get('cex_quote_estimate')}`",
                f"- cex_deposit_count: `{analysis.get('cex_deposit_count')}`",
                f"- cex_destination_classes: `{analysis.get('cex_destination_classes')}`",
                f"- runtime_cex_deposit_candidate_count: `{analysis.get('runtime_cex_deposit_candidate_count')}`",
                f"- cex_gas_priming_bnb: `{analysis.get('cex_gas_priming_bnb')}`",
                f"- cex_gas_priming_count: `{analysis.get('cex_gas_priming_count')}`",
                f"- cex_withdrawal_cluster_status: `{withdrawal.get('status')}`",
                f"- cex_withdrawal_cluster_candidates: `{withdrawal.get('candidate_count', 0)}`",
                f"- cex_withdrawal_alert_policy: `{withdrawal.get('alert_policy', 'report_only')}`",
                "",
                "### Top Net Buyers",
                "",
            ]
        )
        for row in analysis.get("top_net_buyers", []):
            lines.append(f"- {short_addr(row.get('address', ''))}: {opening.format_amount(row.get('quote'))} {event['quote']['symbol']}")
        lines.extend(["", "### Top Net Sellers", ""])
        for row in analysis.get("top_net_sellers", []):
            lines.append(f"- {short_addr(row.get('address', ''))}: {opening.format_amount(row.get('quote'))} {event['quote']['symbol']}")
        clusters = withdrawal.get("clusters", []) or []
        if clusters:
            lines.extend(["", "### CEX Withdrawal Cluster Candidates", "", "Report-only evidence. Direction stays `unknown`; action stays `Observe`.", ""])
            for cluster in clusters:
                lines.append(
                    f"- {cluster.get('source_exchange', 'unknown')} {short_addr(cluster.get('source_address', ''))}: "
                    f"recipients={cluster.get('recipient_count', 0)}, transfers={cluster.get('transfer_count', 0)}, "
                    f"token={opening.format_amount(cluster.get('total_token'))}, quote≈{opening.format_amount(cluster.get('total_quote_estimate'))}, "
                    f"CV={cluster.get('equal_tranche_cv')}, window={cluster.get('window_blocks')}; unresolved="
                    + ",".join(cluster.get("unresolved_gates", []) or [])
                )
        rows = event.get("rows", [])
        if rows:
            lines.extend(["", "| block | buy quote | sell quote | CEX token | CEX quote est | CEX class | CEX gas BNB | buyer | seller |", "| ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |"])
            for row in rows[:30]:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(row.get("block", "")),
                            opening.format_amount(row.get("spent_quote")),
                            opening.format_amount(row.get("got_quote")),
                            opening.format_amount(row.get("cex_token_deposit")),
                            opening.format_amount(row.get("cex_quote_estimate")),
                            str(row.get("cex_destination_classes") or ""),
                            opening.format_amount(row.get("cex_gas_priming_bnb")),
                            short_addr(row.get("buyer", "")),
                            short_addr(row.get("seller", "")),
                        ]
                    )
                    + " |"
                )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    write_json(LATEST_PATH, snapshot)
    record_withdrawal_candidate_history(snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    maybe_send_telegram(snapshot)
    print(LATEST_PATH)
    print(REPORT_PATH)
    print(f"events={snapshot['event_count']} alerts={snapshot['alert_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
