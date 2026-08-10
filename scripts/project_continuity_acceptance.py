#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "project_continuity.json"
DEPLOY_PARITY_PATHS = (
    "config/current_alpha_watchlist.json",
    "input/dos_airdrop_pressure_evidence_2026-08-10.json",
    "input/dos_alpha_200_sell_receipt_2026-08-10.json",
    "scripts/alpha_holder_concentration_watch.py",
    "scripts/alpha_liquidity_retention_watch.py",
    "scripts/alpha_prelaunch_watch.py",
    "scripts/fast_lane_health.py",
    "scripts/runtime_health_watch.py",
    "scripts/build_alpha_daily_report.py",
    "scripts/test_aeon_monitor_regression.py",
    "scripts/test_dos_prelaunch_config.py",
    "scripts/grvt_liquidity_replay_acceptance.py",
    "scripts/fixtures/grvt_v3_quote_only_removal_receipt_2026-08-07.json",
    "scripts/server_run_once.sh",
    "scripts/deploy_to_server.sh",
    "scripts/project_continuity_acceptance.py",
    "scripts/test_project_continuity_acceptance.py",
    "scripts/verify_sniper_engine.py",
)
REMOTE_RUNTIME_ISSUE_CODES = frozenset(
    {
        "alpha_catalog_budget_exceeded",
        "alpha_catalog_failed",
        "alpha_catalog_focus_missing",
        "alpha_coverage_gap",
        "alpha_launch_candidate_gap",
        "alpha_monitoring_focus_missing",
        "alpha_monitoring_policy_mismatch",
        "alpha_project_scan_pending",
        "alpha_static_time_conflict",
        "alpha_static_time_conflict_summary_invalid",
        "alpha_unsupported_chain",
        "fast_lane_unhealthy",
        "missing_fast_lane_heartbeat",
        "missing_heartbeat",
        "missing_output",
        "stale_fast_lane_heartbeat",
        "stale_heartbeat",
        "stale_output",
        "step_failed",
        "verification_failed",
    }
)
REMOTE_RUNTIME_ISSUE_SCOPES = frozenset(
    {
        "",
        "holder",
        "intraday",
        "liquidity_retention",
        "opening",
        "prelaunch",
        "price",
        "project",
        "retention_flow",
        "runtime_watchlist",
    }
)
REMOTE_RUNTIME_ISSUE_REASONS = frozenset(
    {
        "",
        "contract_mismatch",
        "opening_buyer_scope",
        "opening_buyer_scope_incomplete",
        "opening_buyer_trace_failed",
        "opening_cohort_incomplete",
        "opening_deadline",
        "opening_identity_conflict",
        "opening_liquidity_incomplete",
        "opening_scan_errors",
        "opening_status_invalid",
        "other",
    }
)
REMOTE_OPENING_ERROR_CODES = frozenset(
    {"", "opening_cohort_coverage_incomplete", "opening_scope_error"}
)
REMOTE_VALIDATION_ERROR_CODES = frozenset(
    {
        "holder_summary_invalid",
        "liquidity_numeric_invalid",
        "liquidity_summary_invalid",
        "max_age_invalid",
        "natural_history_invalid",
        "natural_required_values_invalid",
        "nested_shape_invalid",
        "replay_summary_invalid",
        "replay_boolean_values_invalid",
        "replay_required_values_invalid",
        "runtime_issue_codes_invalid",
        "runtime_issue_summaries_shape_invalid",
        "runtime_issue_summary_row_shape_invalid",
        "runtime_issue_summary_value_invalid",
        "runtime_required_values_invalid",
        "top_shape_invalid",
        "holder_required_values_invalid",
        "liquidity_required_values_invalid",
        "verification_summary_invalid",
        "verdict_contract_activation_invalid",
        "verdict_contract_counts_invalid",
        "verdict_contract_required_values_invalid",
        "verdict_contract_version_invalid",
    }
)

REMOTE_PROBE = r"""
import json
import hashlib
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

root = Path(sys.argv[1])
max_age = int(sys.argv[2])
expected_hashes = json.loads(sys.argv[3])
enriched_deploy_boundary = "2026-08-06T15:33:40+00:00"
verdict_coverage_contract_version = "liquidity_verdict_coverage.v2"
verdict_coverage_activated_at_utc = "2026-08-09T12:41:07+00:00"
recipient_next_hop_scope_issue = "recipient_next_hop_scope_exceeded"
historical_scope_reconcile_ids = {
    "2889857dc0b23b492d8949eae9e59049f937783af86ea6ae40822d5744bc2a8f",
    "b58cec136e8bdfc76e7739f9c5789bd4f60abafcbf5589a2cd6a671e37b5758e",
    "21e9f32ff27150b7d5241e90279327e37a37fd79b8e1f493deb45d94142b5b32",
}
liquidity_final_classifications = {
    "net_removed",
    "range_repositioned",
    "re_added",
    "migrated",
    "removed_plus_sold",
}
safe_output_codes = liquidity_final_classifications | {
    "active",
    "alpha_catalog_budget_exceeded",
    "alpha_catalog_failed",
    "alpha_catalog_focus_missing",
    "alpha_coverage_gap",
    "alpha_launch_candidate_gap",
    "alpha_monitoring_focus_missing",
    "alpha_monitoring_policy_mismatch",
    "alpha_project_scan_pending",
    "alpha_static_time_conflict",
    "alpha_static_time_conflict_summary_invalid",
    "alpha_unsupported_chain",
    "canonical_block",
    "contract_mismatch",
    "deadline_exceeded",
    "error",
    "eth_getlogs_coverage_failed",
    "execution_failed",
    "fail",
    "fast_lane_unhealthy",
    "healthy",
    "holder_scan_failed",
    "holder_transfer_coverage_failed",
    "invalid_runtime_metadata",
    "liquidity_evidence_cycle_limit",
    "liquidity_flow_coverage_incomplete",
    "liquidity_materiality_unverified",
    "liquidity_operator_basis_unreliable",
    "liquidity_operator_unavailable",
    "liquidity_pairing_ambiguous",
    "liquidity_reconciliation_incomplete",
    "missing",
    "missing_fast_lane_heartbeat",
    "missing_heartbeat",
    "missing_output",
    "out_of_range",
    "pass",
    "pool_liquidity_boundary_unavailable",
    "pool_token_orientation_invalid",
    "prelaunch",
    "price",
    "project",
    "provider_error",
    "recipient_next_hop_coverage_incomplete",
    "recipient_next_hop_identity_invalid",
    "recipient_next_hop_receipt_invalid",
    "recipient_next_hop_scope_exceeded",
    "recipient_scope_exceeded",
    "retention_flow",
    "runtime_dependency_failed",
    "runtime_io_failed",
    "runtime_watchlist",
    "source_block_not_canonical",
    "source_chain_timestamp_unavailable",
    "source_pool_scope_unavailable",
    "source_price_unavailable",
    "source_receipt_not_canonical",
    "stale_fast_lane_heartbeat",
    "stale_heartbeat",
    "stale_output",
    "step_failed",
    "timeout",
    "timestamp_target_unavailable",
    "timestamp_window_unavailable",
    "unexpected_runtime_error",
    "unknown",
    "unknown_issue",
    "unhealthy",
    "unresolved_coverage",
    "v3_price_unavailable",
    "v3_state_unavailable",
    "verification_failed",
    "holder",
    "intraday",
    "liquidity_retention",
    "opening",
    "opening_buyer_scope",
    "opening_buyer_scope_incomplete",
    "opening_buyer_trace_failed",
    "opening_cohort_incomplete",
    "opening_cohort_coverage_incomplete",
    "opening_deadline",
    "opening_identity_conflict",
    "opening_liquidity_incomplete",
    "opening_scan_errors",
    "opening_scope_error",
    "opening_status_invalid",
}

def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def read_list(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []

def parse_iso_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None

def valid_iso(value):
    return parse_iso_utc(value) is not None

verdict_coverage_activated_at = parse_iso_utc(
    verdict_coverage_activated_at_utc
)

def safe_timestamp(value):
    rendered = str(value or "")
    return rendered if valid_iso(rendered) else ""

def candidate_history(path, *, schema=None, schema_version=None):
    exists = path.exists()
    if not exists:
        return {"exists": False, "valid": True, "candidate_count": 0, "updated_at": ""}
    payload = read_json(path)
    candidates = payload.get("candidates")
    try:
        declared_count = int(payload.get("candidate_count"))
    except (TypeError, ValueError):
        declared_count = -1
    valid = (
        isinstance(candidates, list)
        and all(isinstance(row, dict) for row in candidates)
        and declared_count == len(candidates)
        and (schema is None or payload.get("schema") == schema)
        and (schema_version is None or payload.get("schema_version") == schema_version)
    )
    return {
        "exists": True,
        "valid": valid,
        "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
        "updated_at": safe_timestamp(
            payload.get("updated_at") or payload.get("last_scan_at")
        ),
    }

def evidence_coverage_issues(row):
    values = (
        row.get("evidence_coverage_issues")
        if isinstance(row.get("evidence_coverage_issues"), list)
        else []
    )
    return [
        safe_code(value, "unknown_issue")
        for value in values[:8]
        if isinstance(value, str)
    ]

def valid_reconcile_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

def safe_code(value, default="unknown"):
    rendered = str(value or "")
    return rendered if rendered in safe_output_codes else default

def safe_int(value, default=None):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return default

def safe_bool(value):
    return value if type(value) is bool else None

def safe_contract_version(value):
    rendered = str(value or "")
    if not rendered or rendered == verdict_coverage_contract_version:
        return rendered
    return "unsupported"

def v2_core_evidence(row):
    if (
        row.get("verdict_coverage_contract_version")
        != verdict_coverage_contract_version
        or row.get("source_receipt_canonical") is not True
        or not valid_iso(row.get("source_event_utc"))
        or row.get("active_range_vs_spot") not in {"active", "out_of_range"}
        or type(row.get("spot_tick")) is not int
    ):
        return None
    try:
        before_raw = row.get("pool_liquidity_before")
        after_raw = row.get("pool_liquidity_after")
        five_raw = row.get("price_reaction_5m_pct")
        fifteen_raw = row.get("price_reaction_15m_pct")
        if (
            not isinstance(before_raw, str)
            or re.fullmatch(r"[0-9]+", before_raw) is None
            or not isinstance(after_raw, str)
            or re.fullmatch(r"[0-9]+", after_raw) is None
            or not isinstance(five_raw, str)
            or not isinstance(fifteen_raw, str)
        ):
            return None
        before = int(before_raw)
        after = int(after_raw)
        five = Decimal(five_raw)
        fifteen = Decimal(fifteen_raw)
        next_hop = row.get("recipient_next_hop")
        integer_fields = (
            "recipient_count",
            "canonical_transaction_count",
            "observed_transaction_count_lower_bound",
            "scope_limit",
        )
        if not isinstance(next_hop, dict) or any(
            type(next_hop.get(field)) is not int for field in integer_fields
        ):
            return None
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not (
        before >= 0
        and after >= 0
        and five.is_finite()
        and fifteen.is_finite()
        and next_hop.get("attribution_complete") is False
        and next_hop.get("existence_complete") is True
        and 0 <= next_hop["recipient_count"] <= 8
        and next_hop["canonical_transaction_count"] >= 0
        and next_hop["observed_transaction_count_lower_bound"] >= 0
        and next_hop["scope_limit"] == 16
    ):
        return None
    return next_hop

def valid_v2_lifecycle(row):
    completed_at = parse_iso_utc(row.get("completed_at"))
    first_seen_at = parse_iso_utc(row.get("first_seen_at"))
    source_event_at = parse_iso_utc(row.get("source_event_utc"))
    return bool(
        completed_at is not None
        and completed_at >= verdict_coverage_activated_at
        and first_seen_at is not None
        and source_event_at is not None
        and first_seen_at <= completed_at
        and source_event_at <= completed_at
        and type(row.get("source_block")) is int
        and row.get("source_block") > 0
        and type(row.get("reconciliation_window_seconds")) is int
        and row.get("reconciliation_window_seconds") == 900
        and type(row.get("observation_age_seconds")) is int
        and row.get("observation_age_seconds") >= 0
        and type(row.get("chain_age_seconds")) is int
        and row.get("chain_age_seconds") >= 900
    )

def valid_v2_full_final(row, alert_sent_count):
    next_hop = v2_core_evidence(row)
    if (
        next_hop is None
        or not valid_v2_lifecycle(row)
        or not valid_reconcile_id(row.get("reconcile_id"))
        or str(row.get("classification") or "")
        not in liquidity_final_classifications
        or row.get("verdict_coverage_complete") is not True
        or row.get("enrichment_coverage_complete") is not True
        or row.get("evidence_coverage_issues") != []
        or row.get("evidence_level") != "receipt_canonical_bounded_15m"
        or next_hop.get("coverage_complete") is not True
        or next_hop.get("enumeration_complete") is not True
        or next_hop["canonical_transaction_count"]
        != next_hop["observed_transaction_count_lower_bound"]
        or alert_sent_count != 1
    ):
        return False
    if next_hop.get("status") == "no_outbound_observed":
        return next_hop["canonical_transaction_count"] == 0
    return bool(
        next_hop.get("status") == "outbound_observed"
        and 1 <= next_hop["recipient_count"] <= 8
        and 1 <= next_hop["canonical_transaction_count"] <= 16
    )

def valid_v2_scope_final(row, alert_sent_count):
    next_hop = v2_core_evidence(row)
    return bool(
        next_hop is not None
        and valid_v2_lifecycle(row)
        and valid_reconcile_id(row.get("reconcile_id"))
        and str(row.get("classification") or "")
        in liquidity_final_classifications
        and row.get("verdict_coverage_complete") is True
        and row.get("enrichment_coverage_complete") is False
        and row.get("evidence_coverage_issues")
        == [recipient_next_hop_scope_issue]
        and row.get("evidence_level")
        == "core_receipt_canonical_next_hop_observed_partial"
        and next_hop.get("status") == "high_activity_unattributed"
        and next_hop.get("coverage_complete") is False
        and next_hop.get("attribution_complete") is False
        and next_hop.get("existence_complete") is True
        and next_hop.get("enumeration_complete") is False
        and type(next_hop.get("recipient_count")) is int
        and 1 <= next_hop.get("recipient_count") <= 8
        and type(next_hop.get("canonical_transaction_count")) is int
        and next_hop.get("canonical_transaction_count") == 16
        and type(next_hop.get("observed_transaction_count_lower_bound")) is int
        and next_hop.get("observed_transaction_count_lower_bound") == 17
        and type(next_hop.get("scope_limit")) is int
        and next_hop.get("scope_limit") == 16
        and alert_sent_count == 1
    )

health_path = root / "output" / "runtime_health" / "last_cycle.json"
health = read_json(health_path)
age = max(0, int(time.time() - health_path.stat().st_mtime)) if health_path.exists() else None
verification_path = root / "output" / "sniper_engine" / "verification_report.md"
try:
    verification_text = verification_path.read_text(encoding="utf-8", errors="replace")
except OSError:
    verification_text = ""
verification_fail_rows = [
    line for line in verification_text.splitlines() if "| FAIL |" in line
]
fail_count = len(verification_fail_rows)
verification_fail_check_hashes = sorted(
    hashlib.sha256(
        line.split("|")[1].strip().encode("utf-8")
    ).hexdigest()[:16]
    for line in verification_fail_rows
    if len(line.split("|")) >= 4
)
grvt_replay_path = root / "output" / "grvt_liquidity_replay_acceptance" / "latest.json"
grvt_replay = read_json(grvt_replay_path)
grvt_replay_age = max(0, int(time.time() - grvt_replay_path.stat().st_mtime)) if grvt_replay_path.exists() else None
grvt_replay_hashes = grvt_replay.get("code_hashes") if isinstance(grvt_replay.get("code_hashes"), dict) else {}
grvt_replay_hash_parity = all(
    grvt_replay_hashes.get(relative_path) == expected_hashes.get(relative_path)
    for relative_path in (
        "scripts/alpha_holder_concentration_watch.py",
        "scripts/grvt_liquidity_replay_acceptance.py",
        "scripts/fixtures/grvt_v3_quote_only_removal_receipt_2026-08-07.json",
    )
)
grvt_replay_contract = (
    grvt_replay.get("schema") == "grvt_liquidity_replay_acceptance.v1"
    and grvt_replay.get("status") == "pass"
    and grvt_replay.get("issues") == []
    and isinstance(grvt_replay.get("generated_at"), str)
    and bool(grvt_replay.get("generated_at"))
    and grvt_replay_age is not None
    and int(grvt_replay.get("receipt_count") or 0) == 2
    and int(grvt_replay.get("elapsed_seconds") or 0) == 80
    and grvt_replay.get("classification") == "range_repositioned"
    and grvt_replay.get("range_changed") is True
    and grvt_replay.get("source_pool_equals_destination_pool") is True
    and grvt_replay.get("operator_basis") == "transaction_sender_eoa"
    and grvt_replay.get("quote_boundary_complete") is True
    and grvt_replay.get("relative_materiality_proven") is True
    and grvt_replay.get("raw_removal_alert_eligible") is False
    and int(grvt_replay.get("pending_count") or 0) == 0
    and grvt_replay.get("normal_replay_dedup_pass") is True
    and int(grvt_replay.get("first_send_count") or 0) == 1
    and int(
        grvt_replay.get("replay_duplicate_send_count")
        if grvt_replay.get("replay_duplicate_send_count") is not None
        else -1
    ) == 0
    and grvt_replay_hash_parity
)
watchlist = read_json(root / "config" / "current_alpha_watchlist.json")
item_count = len(watchlist.get("items", [])) if isinstance(watchlist.get("items", []), list) else 0
grvt_scope_keys = set()
for watch_item in watchlist.get("items", []):
    if (
        not isinstance(watch_item, dict)
        or str(watch_item.get("symbol") or "").upper() != "GRVT"
    ):
        continue
    for contract in watch_item.get("contracts") or []:
        if not isinstance(contract, dict):
            continue
        contract_chain = str(contract.get("chain") or "").lower()
        contract_address = str(contract.get("address") or "").lower()
        if (
            re.fullmatch(r"[a-z0-9_-]{1,32}", contract_chain)
            and re.fullmatch(r"0x[0-9a-f]{40}", contract_address)
        ):
            grvt_scope_keys.add((contract_chain, contract_address))
parity_matches = 0
for relative_path, expected_hash in expected_hashes.items():
    try:
        actual_hash = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
    except OSError:
        actual_hash = ""
    parity_matches += actual_hash == expected_hash
liquidity = read_json(root / "output" / "alpha_liquidity_retention_watch" / "latest.json")
grvt_projects = [
    row for row in liquidity.get("projects", [])
    if isinstance(row, dict) and str(row.get("symbol") or "").upper() == "GRVT"
]
grvt_flow = {}
if len(grvt_projects) == 1:
    retention = grvt_projects[0].get("retention_flow") or {}
    grvt_flow = retention.get("liquidity_retention") or {}
liquidity_state = read_json(root / "output" / "alpha_liquidity_retention_watch" / "state.json")
holder_snapshot = read_json(root / "output" / "alpha_holder_concentration_watch" / "latest.json")
grvt_holder_rows = [
    row for row in holder_snapshot.get("projects", [])
    if isinstance(row, dict) and str(row.get("symbol") or "").upper() == "GRVT"
]
grvt_holder = grvt_holder_rows[0] if len(grvt_holder_rows) == 1 else {}
reconciliations = []
reconciliation_scopes = []
reconciliation_shape_invalid_count = 0
token_states = liquidity_state.get("tokens")
if not isinstance(token_states, dict):
    reconciliation_shape_invalid_count += 1
    token_states = {}
for token_key, token_state in token_states.items():
    if not isinstance(token_state, dict):
        reconciliation_shape_invalid_count += 1
        continue
    liquidity_payload = token_state.get("liquidity")
    if liquidity_payload is None:
        continue
    if not isinstance(liquidity_payload, dict):
        reconciliation_shape_invalid_count += 1
        continue
    reconciliation = liquidity_payload.get("reconciliation")
    if reconciliation is None:
        continue
    pending_rows = (
        reconciliation.get("pending")
        if isinstance(reconciliation, dict)
        else None
    )
    completed_state_rows = (
        reconciliation.get("completed")
        if isinstance(reconciliation, dict)
        else None
    )
    if (
        not isinstance(reconciliation, dict)
        or not isinstance(pending_rows, list)
        or not isinstance(completed_state_rows, list)
        or any(not isinstance(row, dict) for row in pending_rows)
        or any(not isinstance(row, dict) for row in completed_state_rows)
    ):
        reconciliation_shape_invalid_count += 1
        continue
    reconciliations.append(reconciliation)
    chain, _, token = str(token_key).partition(":")
    reconciliation_scopes.append((chain, token, reconciliation))
pending_count = sum(len(row.get("pending") or []) for row in reconciliations)
completed_rows = [item for row in reconciliations for item in (row.get("completed") or []) if isinstance(item, dict)]
completed_classes = {}
for row in completed_rows:
    classification = safe_code(row.get("classification"))
    completed_classes[classification] = completed_classes.get(classification, 0) + 1
completed_times = sorted(
    str(row.get("completed_at") or "")
    for row in completed_rows
    if str(row.get("completed_at") or "")
)
seen_alerts = set(read_list(root / "output" / "alpha_holder_concentration_watch" / "seen_alerts.json"))
last_push = read_json(root / "output" / "alpha_liquidity_retention_watch" / "last_push.json")
last_push_keys = set(str(last_push.get("signature") or "").splitlines())
intraday = read_json(root / "output" / "alpha_intraday_flow_watch" / "latest.json")
micro_gas_history = candidate_history(
    root / "output" / "alpha_intraday_flow_watch" / "cex_micro_gas_candidate_history.json",
    schema="cex_micro_gas_candidate_history.v1",
)
withdrawal_history = candidate_history(
    root / "output" / "alpha_intraday_flow_watch" / "withdrawal_candidate_history.json",
    schema_version=1,
)
grvt_reconciliation_events = []
historical_unversioned_scope_count = 0
v2_scope_pending_count = 0
v2_scope_unresolved_count = 0
v2_scope_legal_final_count = 0
v2_full_final_count = 0
v2_invalid_or_unsent_final_count = 0
v2_invalid_pending_count = 0
missing_contract_version_count = 0
unsupported_contract_version_count = 0
historical_scope_id_occurrences = {}
for _chain, _token, reconciliation in reconciliation_scopes:
    for collection_name in ("pending", "completed"):
        for row in reconciliation.get(collection_name) or []:
            if not isinstance(row, dict):
                continue
            reconcile_id = str(row.get("reconcile_id") or "")
            if reconcile_id in historical_scope_reconcile_ids:
                historical_scope_id_occurrences[reconcile_id] = (
                    historical_scope_id_occurrences.get(reconcile_id, 0) + 1
                )
for chain, token, reconciliation in reconciliation_scopes:
    for row in reconciliation.get("pending") or []:
        if not isinstance(row, dict):
            continue
        issues = evidence_coverage_issues(row)
        scope_issue_present = recipient_next_hop_scope_issue in (
            row.get("evidence_coverage_issues")
            if isinstance(row.get("evidence_coverage_issues"), list)
            else []
        )
        contract_version = str(
            row.get("verdict_coverage_contract_version") or ""
        )
        raw_issues = row.get("evidence_coverage_issues")
        if contract_version == verdict_coverage_contract_version:
            if (
                not valid_reconcile_id(row.get("reconcile_id"))
                or not valid_iso(row.get("first_seen_at"))
                or raw_issues not in (None, [])
            ):
                v2_invalid_pending_count += 1
                if scope_issue_present:
                    v2_scope_pending_count += 1
        elif contract_version:
            unsupported_contract_version_count += 1
        else:
            missing_contract_version_count += 1
        first_seen = str(row.get("first_seen_at") or "")
        if first_seen < enriched_deploy_boundary:
            continue
        reconcile_id = str(row.get("reconcile_id") or "")
        reconcile_id_prefix = (
            reconcile_id[:12] if valid_reconcile_id(reconcile_id) else "invalid"
        )
        key = "|".join((chain, token, "liquidity_reconciliation", reconcile_id))
        grvt_reconciliation_events.append({
            "reconcile_id_prefix": reconcile_id_prefix,
            "status": "pending",
            "source_event_utc": safe_timestamp(row.get("source_event_utc")),
            "source_block": safe_int(row.get("source_block")),
            "classification": "",
            "verdict_coverage_contract_version": safe_contract_version(contract_version),
            "evidence_coverage_issues": issues,
            "pending_at": safe_timestamp(first_seen),
            "final_at": "",
            "window_seconds": None,
            "alert_key": "liquidity_reconciliation/" + reconcile_id_prefix,
            "alert_sent_count": int(key in seen_alerts),
            "last_push_receipt_match": key in last_push_keys,
            "raw_removal_alert_eligible": False,
            "enrichment_coverage_complete": False,
            "enriched_fields_present": {
                "active_range_vs_spot": False,
                "pool_liquidity_boundary": False,
                "recipient_next_hop": False,
                "price_reaction_5m": False,
                "price_reaction_15m": False,
            },
        })
    for row in reconciliation.get("completed") or []:
        if not isinstance(row, dict):
            continue
        reconcile_id = str(row.get("reconcile_id") or "")
        reconcile_id_prefix = (
            reconcile_id[:12] if valid_reconcile_id(reconcile_id) else "invalid"
        )
        key = "|".join((chain, token, "liquidity_reconciliation", reconcile_id))
        issues = evidence_coverage_issues(row)
        scope_issue_present = recipient_next_hop_scope_issue in (
            row.get("evidence_coverage_issues")
            if isinstance(row.get("evidence_coverage_issues"), list)
            else []
        )
        contract_version = str(
            row.get("verdict_coverage_contract_version") or ""
        )
        alert_sent_count = int(key in seen_alerts)
        completed_at = str(row.get("completed_at") or "")
        completed_at_utc = parse_iso_utc(completed_at)
        if contract_version == verdict_coverage_contract_version:
            classification = str(row.get("classification") or "")
            if classification == "unresolved_coverage":
                v2_scope_unresolved_count += 1
            elif valid_v2_full_final(row, alert_sent_count):
                v2_full_final_count += 1
            elif valid_v2_scope_final(row, alert_sent_count):
                v2_scope_legal_final_count += 1
            else:
                v2_invalid_or_unsent_final_count += 1
        elif contract_version:
            unsupported_contract_version_count += 1
        elif (
            completed_at_utc is None
            or completed_at_utc >= verdict_coverage_activated_at
        ):
            missing_contract_version_count += 1
        elif scope_issue_present:
            if (
                str(row.get("classification") or "")
                == "unresolved_coverage"
                and row.get("evidence_coverage_issues")
                == [recipient_next_hop_scope_issue]
                and valid_reconcile_id(row.get("reconcile_id"))
                and str(row.get("reconcile_id"))
                in historical_scope_reconcile_ids
                and historical_scope_id_occurrences.get(
                    str(row.get("reconcile_id")), 0
                ) == 1
                and (str(chain).lower(), str(token).lower())
                in grvt_scope_keys
            ):
                historical_unversioned_scope_count += 1
            else:
                missing_contract_version_count += 1
        if completed_at < enriched_deploy_boundary:
            continue
        grvt_reconciliation_events.append({
            "reconcile_id_prefix": reconcile_id_prefix,
            "status": "final",
            "source_event_utc": safe_timestamp(row.get("source_event_utc")),
            "source_block": safe_int(row.get("source_block")),
            "classification": safe_code(row.get("classification")),
            "verdict_coverage_contract_version": safe_contract_version(contract_version),
            "pending_at": safe_timestamp(row.get("first_seen_at")),
            "final_at": safe_timestamp(completed_at),
            "expires_at": safe_timestamp(row.get("expires_at")),
            "window_seconds": safe_int(row.get("reconciliation_window_seconds")),
            "observation_age_seconds": safe_int(row.get("observation_age_seconds")),
            "chain_age_seconds": safe_int(row.get("chain_age_seconds")),
            "source_chain_timestamp_basis": safe_code(row.get("source_chain_timestamp_basis"), ""),
            "coverage_issue_code": safe_code(row.get("coverage_issue_code"), ""),
            "evidence_coverage_issues": issues,
            "alert_key": "liquidity_reconciliation/" + reconcile_id_prefix,
            "alert_sent_count": alert_sent_count,
            "last_push_receipt_match": key in last_push_keys,
            "raw_removal_alert_eligible": safe_bool(row.get("raw_removal_alert_eligible")),
            "enrichment_coverage_complete": row.get("enrichment_coverage_complete") is True,
            "enriched_fields_present": {
                "active_range_vs_spot": row.get("active_range_vs_spot") is not None,
                "pool_liquidity_boundary": row.get("pool_liquidity_before") is not None and row.get("pool_liquidity_after") is not None,
                "recipient_next_hop": isinstance(row.get("recipient_next_hop"), dict),
                "price_reaction_5m": row.get("price_reaction_5m_pct") is not None,
                "price_reaction_15m": row.get("price_reaction_15m_pct") is not None,
            },
        })
grvt_reconciliation_events.sort(key=lambda row: (str(row.get("final_at") or row.get("pending_at") or ""), str(row.get("reconcile_id_prefix") or "")))
v2_scope_contract_pass = (
    v2_scope_pending_count == 0
    and v2_scope_unresolved_count == 0
    and v2_invalid_or_unsent_final_count == 0
    and v2_invalid_pending_count == 0
    and missing_contract_version_count == 0
    and unsupported_contract_version_count == 0
    and reconciliation_shape_invalid_count == 0
)
runtime_issue_codes = sorted({
    safe_code(row.get("kind") or row.get("code"))
    for row in (health.get("issues") or [])
    if isinstance(row, dict)
})
def runtime_issue_scope(row):
    if safe_code(row.get("kind") or row.get("code")) != "alpha_coverage_gap":
        return ""
    parts = str(row.get("fingerprint") or "").split(":")
    return safe_code(parts[3], "") if len(parts) > 3 else ""

def runtime_issue_reason(row):
    if runtime_issue_scope(row) != "opening":
        return ""
    parts = str(row.get("fingerprint") or "").split(":")
    detail = ":".join(parts[4:]) if len(parts) > 4 else ""
    exact = {
        "contract_mismatch": "contract_mismatch",
        "opening cohort transfer coverage incomplete": "opening_cohort_incomplete",
        "opening buyer address scope incomplete": "opening_buyer_scope_incomplete",
        "opening liquidity flow coverage incomplete": "opening_liquidity_incomplete",
        "opening scan has errors": "opening_scan_errors",
        "opening evidence deadline exceeded before a usable snapshot": "opening_deadline",
        "opening buyer trace failed": "opening_buyer_trace_failed",
        "opening_buyer_scope": "opening_buyer_scope",
    }
    if detail in exact:
        return exact[detail]
    if detail.startswith("opening stable identity metadata conflict="):
        return "opening_identity_conflict"
    if detail.startswith("opening status="):
        return "opening_status_invalid"
    return "other"

opening_snapshot = read_json(
    root / "output" / "alpha_opening_block_watch" / "latest.json"
)
opening_rows = opening_snapshot.get("events")
if not isinstance(opening_rows, list):
    opening_rows = opening_snapshot.get("projects")
if not isinstance(opening_rows, list):
    opening_rows = opening_snapshot.get("rows")
if not isinstance(opening_rows, list):
    opening_rows = []

def runtime_issue_error_code(row):
    if runtime_issue_scope(row) != "opening":
        return ""
    symbol = str(row.get("name") or "").upper()
    parts = str(row.get("fingerprint") or "").split(":")
    contract = parts[2].lower() if len(parts) > 2 else ""
    for event in opening_rows:
        token = event.get("token") if isinstance(event, dict) else {}
        event_contract = (
            str(token.get("address") or "").lower()
            if isinstance(token, dict)
            else ""
        )
        if (
            isinstance(event, dict)
            and (
                str(event.get("symbol") or "").upper() == symbol
                or (contract and event_contract == contract)
            )
        ):
            code = safe_code(event.get("error"), "")
            if code:
                return code
    return ""

def runtime_issue_contract_hash(row):
    parts = str(row.get("fingerprint") or "").split(":")
    contract = parts[2].lower() if len(parts) > 2 else ""
    return hashlib.sha256(contract.encode("utf-8")).hexdigest()[:16]

runtime_issue_summaries = [
    {
        "kind": safe_code(row.get("kind") or row.get("code")),
        "name_hash": hashlib.sha256(
            str(row.get("name") or "").encode("utf-8")
        ).hexdigest()[:16],
        "fingerprint_hash": hashlib.sha256(
            str(row.get("fingerprint") or "").encode("utf-8")
        ).hexdigest()[:16],
        "scope": runtime_issue_scope(row),
        "reason": runtime_issue_reason(row),
        "error_code": runtime_issue_error_code(row),
        "contract_hash": runtime_issue_contract_hash(row),
    }
    for row in (health.get("issues") or [])
    if isinstance(row, dict)
][:20]
ok = (
    health.get("schema") == "runtime_health.v1"
    and health.get("status") == "healthy"
    and int(health.get("issue_count") or 0) == 0
    and health.get("issues") == []
    and age is not None
    and age <= max_age
    and verification_path.exists()
    and fail_count == 0
    and item_count > 0
    and parity_matches == len(expected_hashes)
    and grvt_replay_contract
    and liquidity.get("status") == "healthy"
    and int(liquidity.get("issue_count") or 0) == 0
    and int(liquidity.get("complete_count") or 0) == 1
    and int(liquidity.get("alert_ready_count") or 0) == 1
    and grvt_flow.get("continuous") is True
    and int(grvt_flow.get("latest_block") or 0) > 0
    and int(grvt_flow.get("latest_block") or 0)
    == int(grvt_flow.get("target_latest_block") or 0)
    and v2_scope_contract_pass
    and micro_gas_history["valid"]
    and withdrawal_history["valid"]
)
print(json.dumps({
    "schema": "sniper_remote_health_acceptance.v1",
    "status": "pass" if ok else "fail",
    "runtime_status": safe_code(health.get("status"), "missing"),
    "runtime_generated_at": safe_timestamp(health.get("generated_at")),
    "runtime_age_seconds": age,
    "runtime_issue_count": safe_int(health.get("issue_count")),
    "runtime_issue_codes": runtime_issue_codes,
    "runtime_issue_summaries": runtime_issue_summaries,
    "verification_exists": verification_path.exists(),
    "verification_fail_count": fail_count,
    "verification_fail_check_hashes": verification_fail_check_hashes,
    "watchlist_item_count": item_count,
    "deployed_hash_parity_count": parity_matches,
    "deployed_hash_expected_count": len(expected_hashes),
    "grvt_replay_acceptance": {
        "status": safe_code(grvt_replay.get("status"), "missing"),
        "issues": [
            safe_code(value)
            for value in (
                grvt_replay.get("issues")
                if isinstance(grvt_replay.get("issues"), list)
                else []
            )[:8]
        ],
        "generated_at": safe_timestamp(grvt_replay.get("generated_at")),
        "age_seconds": grvt_replay_age,
        "contract_pass": grvt_replay_contract,
        "classification": safe_code(grvt_replay.get("classification")),
        "range_changed": safe_bool(grvt_replay.get("range_changed")),
        "source_pool_equals_destination_pool": safe_bool(grvt_replay.get("source_pool_equals_destination_pool")),
        "quote_boundary_complete": safe_bool(grvt_replay.get("quote_boundary_complete")),
        "relative_materiality_proven": safe_bool(grvt_replay.get("relative_materiality_proven")),
        "normal_replay_dedup_pass": safe_bool(grvt_replay.get("normal_replay_dedup_pass")),
        "replay_duplicate_send_count": safe_int(grvt_replay.get("replay_duplicate_send_count")),
        "code_hash_parity": grvt_replay_hash_parity,
    },
    "grvt_liquidity": {
        "status": safe_code(liquidity.get("status"), "missing"),
        "issue_count": safe_int(liquidity.get("issue_count")),
        "alert_ready_count": safe_int(liquidity.get("alert_ready_count")),
        "alert_count": safe_int(liquidity.get("alert_count")),
        "complete_count": safe_int(liquidity.get("complete_count")),
        "cursor": safe_int(grvt_flow.get("latest_block")),
        "confirmed_tip": safe_int(grvt_flow.get("target_latest_block")),
        "continuous": safe_bool(grvt_flow.get("continuous")),
        "pool_count": safe_int(grvt_flow.get("pool_count")),
        "pending_count": pending_count,
        "completed_count": len(completed_rows),
        "completed_classes": completed_classes,
        "first_completed_at": safe_timestamp(completed_times[0]) if completed_times else "",
        "last_completed_at": safe_timestamp(completed_times[-1]) if completed_times else "",
        "enriched_deploy_boundary_utc": enriched_deploy_boundary,
        "reconciliation_events_since_enriched_deploy": grvt_reconciliation_events,
        "reconciliation_event_count_since_enriched_deploy": len(grvt_reconciliation_events),
        "verdict_coverage_contract": {
            "version": verdict_coverage_contract_version,
            "activated_at_utc": verdict_coverage_activated_at_utc,
            "historical_unversioned_scope_count": historical_unversioned_scope_count,
            "v2_scope_pending_count": v2_scope_pending_count,
            "v2_scope_unresolved_count": v2_scope_unresolved_count,
            "v2_scope_legal_final_count": v2_scope_legal_final_count,
            "v2_full_final_count": v2_full_final_count,
            "v2_invalid_or_unsent_final_count": v2_invalid_or_unsent_final_count,
            "v2_invalid_pending_count": v2_invalid_pending_count,
            "missing_contract_version_count": missing_contract_version_count,
            "unsupported_contract_version_count": unsupported_contract_version_count,
            "reconciliation_shape_invalid_count": reconciliation_shape_invalid_count,
            "pass": v2_scope_contract_pass,
        },
        "telegram_seen_ledger_count": len(seen_alerts),
        "telegram_last_push_sent_at": safe_timestamp(last_push.get("sent_at")),
    },
    "grvt_holder": {
        "project_count": len(holder_snapshot.get("projects") or []),
        "scan_from_block": safe_int(grvt_holder.get("scan_from_block")),
        "scan_to_block": safe_int(grvt_holder.get("scan_to_block")),
        "previous_latest_block": safe_int(grvt_holder.get("previous_latest_block")),
        "latest_block": safe_int(grvt_holder.get("latest_block")),
        "target_latest_block": safe_int(grvt_holder.get("target_latest_block")),
        "log_error_count": safe_int(grvt_holder.get("log_error_count")),
        "error_code": next(
            (
                code
                for marker, code in (
                    ("eth_getLogs coverage failed", "eth_getlogs_coverage_failed"),
                    ("holder transfer coverage", "holder_transfer_coverage_failed"),
                    ("holder scan", "holder_scan_failed"),
                    ("deadline", "deadline_exceeded"),
                    ("timed out", "timeout"),
                    ("provider", "provider_error"),
                )
                if marker.lower() in str(grvt_holder.get("error") or "").lower()
            ),
            "other",
        ),
    },
    "natural_evidence_watch": {
        "intraday_generated_at": safe_timestamp(intraday.get("generated_at")),
        "intraday_event_count": safe_int(intraday.get("event_count"), 0),
        "intraday_alert_count": safe_int(intraday.get("alert_count"), 0),
        "cex_micro_gas_candidate_history": micro_gas_history,
        "cex_withdrawal_candidate_history": withdrawal_history,
    },
}, ensure_ascii=False))
""".strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run_json(command: list[str], cwd: Path, timeout: int = 30) -> tuple[dict[str, Any], str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {}, "timeout"
    except OSError:
        return {}, "execution_failed"
    if result.returncode != 0:
        return {}, f"exit_nonzero_{result.returncode}"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}, "invalid_json"
    if not isinstance(value, dict):
        return {}, "non_object_json"
    return value, ""


def git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def collect_repository(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    head = git_lines(root, "rev-parse", "HEAD")[0]
    branch = git_lines(root, "branch", "--show-current")
    status = git_lines(root, "status", "--short")
    tracked = set(git_lines(root, "ls-files"))
    required = [str(item) for item in policy.get("tracked_required_paths", [])]
    denied_globs = [str(item) for item in policy.get("denied_git_globs", [])]
    denied_exceptions = {str(item) for item in policy.get("denied_git_exceptions", [])}
    return {
        "head": head,
        "branch": branch[0] if branch else "",
        "dirty": bool(status),
        "status_lines": status,
        "missing_tracked_required": [path for path in required if path not in tracked or not (root / path).is_file()],
        "tracked_denied_paths": sorted(
            path for path in tracked if path_matches_any(path, denied_globs) and path not in denied_exceptions
        ),
        "tracked_paths": tracked,
    }


def path_matches_any(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        fnmatch.fnmatchcase(normalized, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(normalized, pattern[3:]))
        for pattern in patterns
    )


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def context_boundary_violations(
    config: dict[str, Any],
    config_path: Path,
    project_root: Path,
    tracked_paths: set[str],
    policy: dict[str, Any],
) -> list[str]:
    external_roots = [Path(str(item)).expanduser().resolve() for item in policy.get("external_context_roots", [])]
    violations: list[str] = []
    for row in config.get("context_files", []):
        if not isinstance(row, dict) or not row.get("path"):
            violations.append("invalid context_files entry")
            continue
        candidate = Path(str(row["path"])).expanduser()
        resolved = (config_path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if is_within(resolved, project_root):
            relative = resolved.relative_to(project_root).as_posix()
            if relative not in tracked_paths:
                violations.append(f"project context is not Git-tracked: {relative}")
        elif not any(is_within(resolved, root) for root in external_roots):
            violations.append(f"external context is outside approved roots: {resolved}")
    return violations


def summarize_local_runtime(root: Path) -> dict[str, Any]:
    health_path = root / "output" / "runtime_health" / "last_cycle.json"
    try:
        health = read_json(health_path)
    except (OSError, ValueError, json.JSONDecodeError):
        health = {}
    age = max(0, int(time.time() - health_path.stat().st_mtime)) if health_path.exists() else None

    verification_path = root / "output" / "sniper_engine" / "verification_report.md"
    try:
        verification_text = verification_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        verification_text = ""
    fail_count = sum(1 for line in verification_text.splitlines() if "| FAIL |" in line)

    watchlist_path = root / "config" / "current_alpha_watchlist.json"
    try:
        watchlist = read_json(watchlist_path)
    except (OSError, ValueError, json.JSONDecodeError):
        watchlist = {}
    items = watchlist.get("items", [])
    return {
        "runtime_status": health.get("status", "missing"),
        "runtime_generated_at": health.get("generated_at", ""),
        "runtime_age_seconds": age,
        "runtime_issue_count": health.get("issue_count"),
        "verification_exists": verification_path.exists(),
        "verification_fail_count": fail_count,
        "watchlist_item_count": len(items) if isinstance(items, list) else 0,
    }


def build_remote_command(config_path: Path, remote: dict[str, Any]) -> list[str]:
    host = str(remote.get("host", ""))
    remote_root = str(remote.get("project_root", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+", host) or not remote_root.startswith("/"):
        raise ValueError("remote_health requires host and absolute project_root")
    identity = (config_path.parent / str(remote.get("identity_file", ""))).resolve()
    known_hosts = (config_path.parent / str(remote.get("known_hosts_file", ""))).resolve()
    if not identity.is_file() or not known_hosts.is_file():
        raise FileNotFoundError("remote SSH identity or known-hosts file is missing")
    max_age = int(remote.get("max_cycle_age_seconds", 1200))
    expected_hashes = {
        relative_path: hashlib.sha256(
            (ROOT / relative_path).read_bytes()
        ).hexdigest()
        for relative_path in DEPLOY_PARITY_PATHS
    }
    remote_command = " ".join(
        [
            "python3",
            "-c",
            shlex.quote(REMOTE_PROBE),
            shlex.quote(remote_root),
            str(max_age),
            shlex.quote(json.dumps(expected_hashes, sort_keys=True)),
        ]
    )
    return [
        "ssh",
        "-i",
        str(identity),
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=8",
        host,
        remote_command,
    ]


def issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def safe_command_error(value: Any) -> str:
    rendered = str(value or "")
    if re.fullmatch(
        r"(?:check|resume|audit|git|remote): [a-z0-9_]+",
        rendered,
    ):
        return rendered
    return "operation_failed"


def strict_remote_int(value: Any, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    return value if type(value) is int and value >= 0 else None


def strict_remote_bool(value: Any, *, optional: bool = False) -> bool | None:
    if value is None and optional:
        return None
    return value if type(value) is bool else None


def strict_remote_code(
    value: Any,
    allowed: set[str],
) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in allowed else None


def strict_remote_timestamp(
    value: Any,
    *,
    optional: bool = False,
) -> str | None:
    if value == "" and optional:
        return ""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def sanitize_remote_runtime(
    value: Any,
    *,
    max_age_seconds: int = 1200,
) -> tuple[dict[str, Any], bool]:
    def validation_error(code: str) -> tuple[dict[str, Any], bool]:
        return (
            {
                "schema": "sniper_remote_health_acceptance.v1",
                "status": "error",
                "validation_error_code": code,
            },
            False,
        )

    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        return validation_error("max_age_invalid")
    if isinstance(value, dict) and set(value) == {"status"}:
        status = value.get("status")
        if status in {"not_requested", "fail", "error"}:
            return {"status": status}, True
    if (
        isinstance(value, dict)
        and set(value) == {"schema", "status", "validation_error_code"}
        and value.get("schema") == "sniper_remote_health_acceptance.v1"
        and value.get("status") == "error"
        and value.get("validation_error_code")
        in REMOTE_VALIDATION_ERROR_CODES
    ):
        return dict(value), True
    top_keys = {
        "schema",
        "status",
        "runtime_status",
        "runtime_generated_at",
        "runtime_age_seconds",
        "runtime_issue_count",
        "runtime_issue_codes",
        "runtime_issue_summaries",
        "verification_exists",
        "verification_fail_count",
        "verification_fail_check_hashes",
        "watchlist_item_count",
        "deployed_hash_parity_count",
        "deployed_hash_expected_count",
        "grvt_replay_acceptance",
        "grvt_liquidity",
        "grvt_holder",
        "natural_evidence_watch",
    }
    replay_keys = {
        "status",
        "issues",
        "age_seconds",
        "generated_at",
        "classification",
        "code_hash_parity",
        "contract_pass",
        "normal_replay_dedup_pass",
        "replay_duplicate_send_count",
        "quote_boundary_complete",
        "range_changed",
        "relative_materiality_proven",
        "source_pool_equals_destination_pool",
    }
    liquidity_keys = {
        "status",
        "issue_count",
        "alert_ready_count",
        "alert_count",
        "complete_count",
        "cursor",
        "confirmed_tip",
        "continuous",
        "pool_count",
        "pending_count",
        "completed_count",
        "completed_classes",
        "first_completed_at",
        "last_completed_at",
        "enriched_deploy_boundary_utc",
        "reconciliation_events_since_enriched_deploy",
        "reconciliation_event_count_since_enriched_deploy",
        "telegram_seen_ledger_count",
        "telegram_last_push_sent_at",
        "verdict_coverage_contract",
    }
    contract_keys = {
        "version",
        "activated_at_utc",
        "historical_unversioned_scope_count",
        "v2_scope_pending_count",
        "v2_scope_unresolved_count",
        "v2_scope_legal_final_count",
        "v2_full_final_count",
        "v2_invalid_or_unsent_final_count",
        "v2_invalid_pending_count",
        "missing_contract_version_count",
        "unsupported_contract_version_count",
        "reconciliation_shape_invalid_count",
        "pass",
    }
    holder_keys = {
        "project_count",
        "latest_block",
        "previous_latest_block",
        "scan_from_block",
        "scan_to_block",
        "target_latest_block",
        "log_error_count",
        "error_code",
    }
    natural_keys = {
        "intraday_generated_at",
        "intraday_event_count",
        "intraday_alert_count",
        "cex_micro_gas_candidate_history",
        "cex_withdrawal_candidate_history",
    }
    history_keys = {"exists", "valid", "candidate_count", "updated_at"}
    if not isinstance(value, dict) or set(value) != top_keys:
        return validation_error("top_shape_invalid")
    replay = value.get("grvt_replay_acceptance")
    liquidity = value.get("grvt_liquidity")
    holder = value.get("grvt_holder")
    natural = value.get("natural_evidence_watch")
    contract = (
        liquidity.get("verdict_coverage_contract")
        if isinstance(liquidity, dict)
        else None
    )
    histories = []
    if isinstance(natural, dict):
        histories = [
            natural.get("cex_micro_gas_candidate_history"),
            natural.get("cex_withdrawal_candidate_history"),
        ]
    if (
        value.get("schema") != "sniper_remote_health_acceptance.v1"
        or value.get("status") not in {"pass", "fail"}
        or not isinstance(replay, dict)
        or set(replay) != replay_keys
        or not isinstance(liquidity, dict)
        or set(liquidity) != liquidity_keys
        or not isinstance(contract, dict)
        or set(contract) != contract_keys
        or not isinstance(holder, dict)
        or set(holder) != holder_keys
        or not isinstance(natural, dict)
        or set(natural) != natural_keys
        or len(histories) != 2
        or any(not isinstance(row, dict) or set(row) != history_keys for row in histories)
    ):
        return validation_error("nested_shape_invalid")

    runtime_status = strict_remote_code(
        value.get("runtime_status"),
        {"healthy", "unhealthy", "missing", "error"},
    )
    runtime_generated_at = strict_remote_timestamp(
        value.get("runtime_generated_at"), optional=True
    )
    runtime_age = strict_remote_int(
        value.get("runtime_age_seconds"), optional=True
    )
    runtime_issue_count = strict_remote_int(
        value.get("runtime_issue_count"), optional=True
    )
    raw_runtime_issue_codes = value.get("runtime_issue_codes")
    if (
        not isinstance(raw_runtime_issue_codes, list)
        or len(raw_runtime_issue_codes) > 20
        or any(not isinstance(item, str) for item in raw_runtime_issue_codes)
    ):
        return validation_error("runtime_issue_codes_invalid")
    runtime_issue_codes = sorted(
        {
            item
            if item in REMOTE_RUNTIME_ISSUE_CODES
            else "issue_present"
            for item in raw_runtime_issue_codes
        }
    )
    issue_summaries = value.get("runtime_issue_summaries")
    if not isinstance(issue_summaries, list) or len(issue_summaries) > 20:
        return validation_error("runtime_issue_summaries_shape_invalid")
    safe_issue_summaries = []
    for row in issue_summaries:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "kind",
                "name_hash",
                "fingerprint_hash",
                "scope",
                "reason",
                "error_code",
                "contract_hash",
            }
        ):
            return validation_error("runtime_issue_summary_row_shape_invalid")
        if (
            not isinstance(row.get("kind"), str)
            or not isinstance(row.get("name_hash"), str)
            or re.fullmatch(r"[0-9a-f]{16}", row["name_hash"]) is None
            or not isinstance(row.get("fingerprint_hash"), str)
            or re.fullmatch(r"[0-9a-f]{16}", row["fingerprint_hash"])
            is None
            or row.get("scope") not in REMOTE_RUNTIME_ISSUE_SCOPES
            or row.get("reason") not in REMOTE_RUNTIME_ISSUE_REASONS
            or row.get("error_code") not in REMOTE_OPENING_ERROR_CODES
            or not isinstance(row.get("contract_hash"), str)
            or re.fullmatch(r"[0-9a-f]{16}", row["contract_hash"]) is None
        ):
            return validation_error("runtime_issue_summary_value_invalid")
        kind = row["kind"]
        safe_issue_summaries.append(
            {
                "kind": (
                    kind
                    if kind in REMOTE_RUNTIME_ISSUE_CODES
                    else "issue_present"
                ),
                "name_hash": row["name_hash"],
                "fingerprint_hash": row["fingerprint_hash"],
                "scope": row["scope"],
                "reason": row["reason"],
                "error_code": row["error_code"],
                "contract_hash": row["contract_hash"],
            }
        )
    verification_exists = strict_remote_bool(value.get("verification_exists"))
    verification_fail_count = strict_remote_int(
        value.get("verification_fail_count")
    )
    verification_fail_check_hashes = value.get(
        "verification_fail_check_hashes"
    )
    if (
        not isinstance(verification_fail_check_hashes, list)
        or len(verification_fail_check_hashes) > 20
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"[0-9a-f]{16}", item) is None
            for item in verification_fail_check_hashes
        )
        or len(verification_fail_check_hashes) != verification_fail_count
    ):
        return validation_error("verification_summary_invalid")
    watchlist_item_count = strict_remote_int(value.get("watchlist_item_count"))
    parity_count = strict_remote_int(value.get("deployed_hash_parity_count"))
    parity_expected = strict_remote_int(value.get("deployed_hash_expected_count"))

    replay_status = strict_remote_code(
        replay.get("status"),
        {"pass", "fail", "missing", "error"},
    )
    raw_replay_issues = replay.get("issues")
    if (
        not isinstance(raw_replay_issues, list)
        or len(raw_replay_issues) > 20
        or any(not isinstance(item, str) for item in raw_replay_issues)
    ):
        return validation_error("replay_summary_invalid")
    replay_issues = [] if not raw_replay_issues else ["issue_present"]
    replay_age = strict_remote_int(replay.get("age_seconds"), optional=True)
    replay_generated_at = strict_remote_timestamp(
        replay.get("generated_at"), optional=True
    )
    replay_classification = strict_remote_code(
        replay.get("classification"),
        {
            "range_repositioned",
            "net_removed",
            "re_added",
            "migrated",
            "removed_plus_sold",
            "missing",
            "unknown",
        },
    )
    replay_duplicate_count = strict_remote_int(
        replay.get("replay_duplicate_send_count"), optional=True
    )
    replay_bools = {
        key: strict_remote_bool(replay.get(key), optional=True)
        for key in (
            "code_hash_parity",
            "contract_pass",
            "normal_replay_dedup_pass",
            "quote_boundary_complete",
            "range_changed",
            "relative_materiality_proven",
            "source_pool_equals_destination_pool",
        )
    }

    liquidity_status = strict_remote_code(
        liquidity.get("status"),
        {"healthy", "unhealthy", "missing", "error"},
    )
    liquidity_int_keys = (
        "issue_count",
        "alert_ready_count",
        "alert_count",
        "complete_count",
        "cursor",
        "confirmed_tip",
        "pool_count",
        "pending_count",
        "completed_count",
        "reconciliation_event_count_since_enriched_deploy",
        "telegram_seen_ledger_count",
    )
    liquidity_ints = {
        key: strict_remote_int(liquidity.get(key), optional=True)
        for key in liquidity_int_keys
    }
    if any(
        liquidity.get(key) is not None and liquidity_ints[key] is None
        for key in liquidity_int_keys
    ):
        return validation_error("liquidity_numeric_invalid")
    liquidity_timestamps = {
        key: strict_remote_timestamp(
            liquidity.get(key),
            optional=key != "enriched_deploy_boundary_utc",
        )
        for key in (
            "first_completed_at",
            "last_completed_at",
            "enriched_deploy_boundary_utc",
            "telegram_last_push_sent_at",
        )
    }
    completed_classes = liquidity.get("completed_classes")
    reconciliation_events = liquidity.get(
        "reconciliation_events_since_enriched_deploy"
    )
    if (
        any(item is None for item in liquidity_timestamps.values())
        or liquidity_timestamps["enriched_deploy_boundary_utc"]
        != "2026-08-06T15:33:40+00:00"
        or not isinstance(completed_classes, dict)
        or any(
            key not in {
                "net_removed",
                "range_repositioned",
                "re_added",
                "migrated",
                "removed_plus_sold",
                "unresolved_coverage",
                "unknown",
            }
            or strict_remote_int(count) is None
            for key, count in completed_classes.items()
        )
        or not isinstance(reconciliation_events, list)
        or any(not isinstance(row, dict) for row in reconciliation_events)
        or liquidity_ints[
            "reconciliation_event_count_since_enriched_deploy"
        ] != len(reconciliation_events)
    ):
        return validation_error("liquidity_summary_invalid")
    continuous = strict_remote_bool(liquidity.get("continuous"), optional=True)

    contract_counts = {
        key: strict_remote_int(contract.get(key))
        for key in contract_keys
        if key not in {"version", "activated_at_utc", "pass"}
    }
    contract_pass_flag = strict_remote_bool(contract.get("pass"))
    contract_activated_at = strict_remote_timestamp(
        contract.get("activated_at_utc")
    )

    holder_ints = {
        key: strict_remote_int(holder.get(key), optional=True)
        for key in holder_keys
        if key != "error_code"
    }
    if any(
        holder.get(key) is not None and holder_ints[key] is None
        for key in holder_ints
    ):
        return validation_error("holder_summary_invalid")
    holder_error_code = strict_remote_code(
        holder.get("error_code"),
        {
            "eth_getlogs_coverage_failed",
            "holder_transfer_coverage_failed",
            "holder_scan_failed",
            "deadline_exceeded",
            "timeout",
            "provider_error",
            "other",
        },
    )

    intraday_generated_at = strict_remote_timestamp(
        natural.get("intraday_generated_at"), optional=True
    )
    intraday_event_count = strict_remote_int(
        natural.get("intraday_event_count"), optional=True
    )
    intraday_alert_count = strict_remote_int(
        natural.get("intraday_alert_count"), optional=True
    )
    safe_histories = []
    for row in histories:
        exists = strict_remote_bool(row.get("exists"))
        valid = strict_remote_bool(row.get("valid"))
        candidate_count = strict_remote_int(row.get("candidate_count"))
        updated_at = strict_remote_timestamp(
            row.get("updated_at"), optional=True
        )
        if None in (exists, valid, candidate_count, updated_at):
            return validation_error("natural_history_invalid")
        safe_histories.append(
            {
                "exists": exists,
                "valid": valid,
                "candidate_count": candidate_count,
                "updated_at": updated_at,
            }
        )

    required_groups = (
        (
            "runtime_required_values_invalid",
            (
                runtime_status,
                runtime_generated_at,
                runtime_age,
                runtime_issue_count,
                runtime_issue_codes,
                verification_exists,
                verification_fail_count,
                watchlist_item_count,
                parity_count,
                parity_expected,
            ),
        ),
        (
            "replay_required_values_invalid",
            (
                replay_status,
                replay_issues,
                replay_age,
                replay_generated_at,
                replay_classification,
                replay_duplicate_count,
            ),
        ),
        (
            "liquidity_required_values_invalid",
            (liquidity_status,),
        ),
        (
            "verdict_contract_required_values_invalid",
            (contract_pass_flag, contract_activated_at),
        ),
        ("holder_required_values_invalid", (holder_error_code,)),
        (
            "natural_required_values_invalid",
            (
                intraday_generated_at,
                intraday_event_count,
                intraday_alert_count,
            ),
        ),
    )
    for error_code, values in required_groups:
        if any(item is None for item in values):
            return validation_error(error_code)
    if any(item is None for item in replay_bools.values()):
        return validation_error("replay_boolean_values_invalid")
    if any(item is None for item in contract_counts.values()):
        return validation_error("verdict_contract_counts_invalid")
    if contract.get("version") != "liquidity_verdict_coverage.v2":
        return validation_error("verdict_contract_version_invalid")
    if contract_activated_at != "2026-08-09T12:41:07+00:00":
        return validation_error("verdict_contract_activation_invalid")

    contract_recomputed = (
        contract_counts["historical_unversioned_scope_count"] <= 3
        and contract_counts["v2_scope_pending_count"] == 0
        and contract_counts["v2_scope_unresolved_count"] == 0
        and contract_counts["v2_invalid_or_unsent_final_count"] == 0
        and contract_counts["v2_invalid_pending_count"] == 0
        and contract_counts["missing_contract_version_count"] == 0
        and contract_counts["unsupported_contract_version_count"] == 0
        and contract_counts["reconciliation_shape_invalid_count"] == 0
    )
    replay_recomputed = (
        replay_status == "pass"
        and replay_issues == []
        and replay_classification == "range_repositioned"
        and replay_bools["code_hash_parity"] is True
        and replay_bools["contract_pass"] is True
        and replay_bools["normal_replay_dedup_pass"] is True
        and replay_duplicate_count == 0
        and replay_bools["quote_boundary_complete"] is True
        and replay_bools["range_changed"] is True
        and replay_bools["relative_materiality_proven"] is True
        and replay_bools["source_pool_equals_destination_pool"] is True
    )
    remote_recomputed = (
        runtime_status == "healthy"
        and runtime_age <= max_age_seconds
        and runtime_issue_count == 0
        and runtime_issue_codes == []
        and safe_issue_summaries == []
        and verification_exists is True
        and verification_fail_count == 0
        and verification_fail_check_hashes == []
        and watchlist_item_count > 0
        and parity_expected == len(DEPLOY_PARITY_PATHS)
        and parity_count == parity_expected
        and replay_recomputed
        and liquidity_status == "healthy"
        and liquidity_ints["issue_count"] == 0
        and liquidity_ints["complete_count"] == 1
        and liquidity_ints["alert_ready_count"] == 1
        and continuous is True
        and type(liquidity_ints["cursor"]) is int
        and type(liquidity_ints["confirmed_tip"]) is int
        and liquidity_ints["cursor"] > 0
        and liquidity_ints["cursor"] == liquidity_ints["confirmed_tip"]
        and contract_pass_flag is True
        and contract_recomputed
        and all(row["valid"] is True for row in safe_histories)
    )
    safe_contract = {
        "version": "liquidity_verdict_coverage.v2",
        "activated_at_utc": contract_activated_at,
        **contract_counts,
        "pass": contract_pass_flag,
    }
    safe_value = {
        "schema": "sniper_remote_health_acceptance.v1",
        "status": (
            "pass"
            if value.get("status") == "pass" and remote_recomputed
            else "fail"
        ),
        "runtime_status": runtime_status,
        "runtime_generated_at": runtime_generated_at,
        "runtime_age_seconds": runtime_age,
        "runtime_issue_count": runtime_issue_count,
        "runtime_issue_codes": runtime_issue_codes,
        "runtime_issue_summaries": safe_issue_summaries,
        "verification_exists": verification_exists,
        "verification_fail_count": verification_fail_count,
        "verification_fail_check_hashes": verification_fail_check_hashes,
        "watchlist_item_count": watchlist_item_count,
        "deployed_hash_parity_count": parity_count,
        "deployed_hash_expected_count": parity_expected,
        "grvt_replay_acceptance": {
            "status": replay_status,
            "issues": replay_issues,
            "age_seconds": replay_age,
            "generated_at": replay_generated_at,
            "classification": replay_classification,
            **replay_bools,
            "replay_duplicate_send_count": replay_duplicate_count,
        },
        "grvt_liquidity": {
            "status": liquidity_status,
            **liquidity_ints,
            "continuous": continuous,
            "completed_classes": dict(completed_classes),
            "first_completed_at": liquidity_timestamps[
                "first_completed_at"
            ],
            "last_completed_at": liquidity_timestamps[
                "last_completed_at"
            ],
            "enriched_deploy_boundary_utc": liquidity_timestamps[
                "enriched_deploy_boundary_utc"
            ],
            "reconciliation_events_since_enriched_deploy": [],
            "reconciliation_event_count_since_enriched_deploy": 0,
            "telegram_last_push_sent_at": liquidity_timestamps[
                "telegram_last_push_sent_at"
            ],
            "verdict_coverage_contract": safe_contract,
        },
        "grvt_holder": {
            **holder_ints,
            "error_code": holder_error_code,
        },
        "natural_evidence_watch": {
            "intraday_generated_at": intraday_generated_at,
            "intraday_event_count": intraday_event_count,
            "intraday_alert_count": intraday_alert_count,
            "cex_micro_gas_candidate_history": safe_histories[0],
            "cex_withdrawal_candidate_history": safe_histories[1],
        },
    }
    return safe_value, True


def evaluate(
    snapshot: dict[str, Any],
    allow_dirty: bool,
    remote_required: bool,
    remote_max_age_seconds: int = 1200,
) -> dict[str, Any]:
    issues = [
        issue("command_error", safe_command_error(detail))
        for detail in snapshot.pop("command_errors", [])
    ]
    advisories: list[dict[str, str]] = []
    continuity = snapshot["continuity"]
    repository = snapshot["repository"]
    local_runtime = snapshot["local_runtime"]

    severity = continuity.get("severity")
    if severity not in {"healthy", "warning"}:
        issues.append(issue("continuity_severity", f"severity={severity or 'missing'}"))
    elif severity == "warning":
        advisories.append(issue("rotation_warning", "task crossed a warning threshold; use the verified checkpoint for the next task"))
    if not continuity.get("checkpoint_id") or not continuity.get("checkpoint_hash_valid"):
        issues.append(issue("checkpoint_invalid", "latest checkpoint is missing or its hash is invalid"))
    if continuity.get("audit_status") != "pass" or int(continuity.get("audit_failed_count") or 0) != 0:
        issues.append(issue("audit_failed", f"audit_status={continuity.get('audit_status', 'missing')}"))
    if not continuity.get("checkpoint_matches_head"):
        issues.append(issue("checkpoint_stale", "latest checkpoint Git head does not match the working repository"))

    if repository.get("dirty") and not allow_dirty:
        issues.append(issue("git_dirty", "working tree has uncommitted changes"))
    for path in repository.get("missing_tracked_required", []):
        issues.append(issue("required_path_missing", path))
    for path in repository.get("tracked_denied_paths", []):
        issues.append(issue("denied_path_tracked", path))
    for detail in repository.get("context_boundary_violations", []):
        issues.append(issue("context_boundary", detail))

    if local_runtime.get("verification_fail_count", 0) > 0:
        issues.append(issue("local_verification_failed", f"FAIL rows={local_runtime['verification_fail_count']}"))
    if not local_runtime.get("verification_exists"):
        issues.append(issue("local_verification_missing", "local verification report is missing"))
    if local_runtime.get("watchlist_item_count", 0) <= 0:
        issues.append(issue("watchlist_empty", "current Alpha watchlist has no items"))
    if not remote_required and local_runtime.get("runtime_status") != "healthy":
        issues.append(issue("local_runtime_unhealthy", f"status={local_runtime.get('runtime_status', 'missing')}"))

    remote_runtime, remote_payload_valid = sanitize_remote_runtime(
        snapshot.get("remote_runtime", {"status": "not_requested"}),
        max_age_seconds=remote_max_age_seconds,
    )
    snapshot["remote_runtime"] = remote_runtime
    if remote_required and (
        not remote_payload_valid or remote_runtime.get("status") != "pass"
    ):
        issues.append(issue("remote_runtime_failed", f"status={remote_runtime.get('status', 'missing')}"))

    snapshot["status"] = "pass" if not issues else "fail"
    snapshot["issues"] = issues
    snapshot["advisories"] = advisories
    return snapshot


def clean_markdown(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    continuity = payload["continuity"]
    repository = payload["repository"]
    local_runtime = payload["local_runtime"]
    remote_runtime = payload.get("remote_runtime", {})
    lines = [
        "# Project Continuity Acceptance",
        "",
        f"- Status: **{payload['status'].upper()}**",
        f"- Generated: `{payload['generated_at']}`",
        f"- Project: `{payload['project_id']}`",
        "",
        "## Continuity",
        "",
        "| Check | Value |",
        "| --- | --- |",
        f"| Severity | {clean_markdown(continuity.get('severity'))} |",
        f"| Conversation | {clean_markdown(continuity.get('conversation_id'))} |",
        f"| Checkpoint | {clean_markdown(continuity.get('checkpoint_id'))} |",
        f"| Checkpoint hash | {'valid' if continuity.get('checkpoint_hash_valid') else 'invalid'} |",
        f"| Checkpoint matches Git | {bool(continuity.get('checkpoint_matches_head'))} |",
        f"| Audit | {clean_markdown(continuity.get('audit_status'))} |",
        "",
        "## Repository And Runtime",
        "",
        "| Check | Value |",
        "| --- | --- |",
        f"| Git branch | {clean_markdown(repository.get('branch'))} |",
        f"| Git head | {clean_markdown(repository.get('head'))} |",
        f"| Git dirty | {bool(repository.get('dirty'))} |",
        f"| Tracked denied paths | {len(repository.get('tracked_denied_paths', []))} |",
        f"| Local runtime | {clean_markdown(local_runtime.get('runtime_status'))} |",
        f"| Local verification FAIL rows | {clean_markdown(local_runtime.get('verification_fail_count'))} |",
        f"| Watchlist items | {clean_markdown(local_runtime.get('watchlist_item_count'))} |",
        f"| Remote acceptance | {clean_markdown(remote_runtime.get('status', 'not_requested'))} |",
        "",
        "## Issues",
        "",
    ]
    if payload["issues"]:
        lines.extend(f"- `{row['code']}`: {clean_markdown(row['detail'])}" for row in payload["issues"])
    else:
        lines.append("- None")
    lines.extend(["", "## Advisories", ""])
    if payload["advisories"]:
        lines.extend(f"- `{row['code']}`: {clean_markdown(row['detail'])}" for row in payload["advisories"])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    markdown_path = output_dir / "latest.md"
    write_text_atomic(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    write_text_atomic(markdown_path, render_markdown(payload))
    return json_path, markdown_path


def write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify that the sniper project can be resumed safely in a fresh Codex task.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--remote", action="store_true", help="also verify the deployed server heartbeat and verification report")
    parser.add_argument("--allow-dirty", action="store_true", help="report, but do not fail on, an intentionally dirty worktree")
    parser.add_argument("--output-dir", help="override the configured report directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = read_json(config_path)
    policy = config.get("acceptance", {})
    if policy.get("schema") != "sniper_project_acceptance_policy.v1":
        print("missing or invalid acceptance policy", file=sys.stderr)
        return 2
    project_root = Path(str(config["project_root"])).expanduser().resolve()
    wrapper = project_root / "scripts" / "project_continuity_local.py"
    base_command = [sys.executable, str(wrapper)]
    commands = {
        "check": [*base_command, "check", "--config", str(config_path), "--no-checkpoint"],
        "resume": [*base_command, "resume", "--config", str(config_path), "--json"],
        "audit": [*base_command, "audit", "--config", str(config_path)],
    }
    results: dict[str, dict[str, Any]] = {}
    command_errors: list[str] = []
    for name, command in commands.items():
        value, error = run_json(command, project_root)
        results[name] = value
        if error:
            command_errors.append(f"{name}: {error}")

    try:
        repository = collect_repository(project_root, policy)
    except (OSError, subprocess.CalledProcessError, IndexError):
        repository = {
            "head": "",
            "branch": "",
            "dirty": True,
            "status_lines": [],
            "missing_tracked_required": [],
            "tracked_denied_paths": [],
            "tracked_paths": set(),
        }
        command_errors.append("git: collection_failed")
    repository["context_boundary_violations"] = context_boundary_violations(
        config,
        config_path,
        project_root,
        repository["tracked_paths"],
        policy,
    )
    repository.pop("tracked_paths", None)

    check = results.get("check", {})
    resume = results.get("resume", {})
    audit = results.get("audit", {})
    checkpoint_head = resume.get("checkpoint", {}).get("git", {}).get("head", "")
    snapshot: dict[str, Any] = {
        "schema": "sniper_project_continuity_acceptance.v1",
        "generated_at": now_iso(),
        "project_id": config.get("project_id", ""),
        "continuity": {
            "severity": check.get("severity", "missing"),
            "reasons": check.get("reasons", []),
            "conversation_id": check.get("metrics", {}).get("conversation_id", ""),
            "checkpoint_id": resume.get("checkpoint_id", ""),
            "checkpoint_hash_valid": bool(resume.get("checkpoint_hash_valid")),
            "checkpoint_git_head": checkpoint_head,
            "checkpoint_matches_head": bool(checkpoint_head and checkpoint_head == repository.get("head")),
            "audit_status": audit.get("status", "missing"),
            "audit_failed_count": audit.get("failed_count"),
        },
        "repository": repository,
        "local_runtime": summarize_local_runtime(project_root),
        "remote_runtime": {"status": "not_requested"},
        "command_errors": command_errors,
    }

    if args.remote:
        try:
            remote_command = build_remote_command(config_path, policy.get("remote_health", {}))
            remote_payload, remote_error = run_json(remote_command, project_root, timeout=30)
            snapshot["remote_runtime"] = remote_payload or {"status": "error"}
            if remote_error:
                snapshot["command_errors"].append(f"remote: {remote_error}")
        except (OSError, TypeError, ValueError):
            snapshot["remote_runtime"] = {"status": "error"}
            snapshot["command_errors"].append("remote: setup_failed")

    remote_policy = policy.get("remote_health", {})
    try:
        remote_max_age_seconds = int(
            remote_policy.get("max_cycle_age_seconds", 1200)
        )
    except (AttributeError, TypeError, ValueError):
        remote_max_age_seconds = 0
    payload = evaluate(
        snapshot,
        allow_dirty=args.allow_dirty,
        remote_required=args.remote,
        remote_max_age_seconds=remote_max_age_seconds,
    )
    configured_output = Path(str(policy.get("output_dir", "../output/project_continuity_acceptance"))).expanduser()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else configured_output
    if not output_dir.is_absolute():
        output_dir = (config_path.parent / output_dir).resolve()
    json_path, markdown_path = write_outputs(output_dir, payload)
    print(json.dumps({"status": payload["status"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
