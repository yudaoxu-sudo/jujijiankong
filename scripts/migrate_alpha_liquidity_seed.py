#!/usr/bin/env python3
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
DOS_TOKEN = "0xb0f09ea9ae0515c3551080d4a745c8115aa30e37"
GRVT_TOKEN = "0x46f2564e0fa8248d15125e7e54173cfbdef91be7"
DOS_KEY = f"bsc:{DOS_TOKEN}"
PLAN_SCHEMA = "alpha_liquidity_seed_recovery_plan.v1"
PROBE_SCHEMA = "alpha_liquidity_seed_recovery_probe.v1"
ARCHIVE_SCHEMA = "alpha_liquidity_seed_recovery_archive.v1"
SHA256 = re.compile(r"[0-9a-f]{64}")
PROTECTED_NAMES = {
    "last_push.json", "seen_alerts.json", "seen_airdrop_alerts.json",
    "telegram_seen_alerts.json",
}
class RecoveryBlocked(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
@dataclass(frozen=True)
class RecoveryPaths:
    root: Path
    config: Path
    standalone_state: Path
    holder_state: Path
    opening: Path
    replay: Path
    @classmethod
    def for_root(cls, root: Path) -> "RecoveryPaths":
        root = Path(root).resolve()
        output = root / "output"
        return cls(
            root, root / "config/current_alpha_watchlist.json",
            output / "alpha_liquidity_retention_watch/state.json",
            output / "alpha_holder_concentration_watch/state.json",
            output / "alpha_opening_block_watch/latest.json",
            output / "grvt_liquidity_replay_acceptance/latest.json",
        )
@dataclass(frozen=True)
class RecoveryBundle:
    safe_plan: dict[str, Any]
    plan_hash: str
    candidate_state: dict[str, Any]
    candidate_seed: dict[str, Any]
    standalone_seed: dict[str, Any]
    holder_seed: dict[str, Any]
    archive_bytes: bytes
def json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return text.encode()
def digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else json_bytes(value)
    return hashlib.sha256(payload).hexdigest()
def file_hash(path: Path) -> str:
    try:
        return digest(path.read_bytes())
    except OSError as exc:
        raise RecoveryBlocked("input_file_unavailable") from exc
def read_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryBlocked("input_json_invalid") from exc
    if not isinstance(value, dict):
        raise RecoveryBlocked("input_json_invalid")
    return value, digest(raw)
def protected_manifest(paths: RecoveryPaths) -> dict[str, dict[str, Any]]:
    candidates = {paths.replay}
    output = paths.root / "output"
    if output.is_dir():
        candidates.update(path for path in output.rglob("*") if path.is_file()
                          and (path.name in PROTECTED_NAMES
                               or "telegram" in path.name.lower()))
    result = {}
    for path in sorted(candidates):
        if path.is_file():
            try:
                name = path.resolve().relative_to(paths.root).as_posix()
            except ValueError as exc:
                raise RecoveryBlocked("protected_path_invalid") from exc
            stat = path.stat()
            result[name] = {"sha256": file_hash(path), "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns}
    return result
def validate_watchlist(config: dict[str, Any]) -> None:
    items = config.get("items")
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise RecoveryBlocked("watchlist_invalid")
    if config.get("monitoring_policy") != {
            "mode": "exclusive_symbols", "symbols": ["DOS"]}:
        raise RecoveryBlocked("monitoring_policy_scope_invalid")
    if any(row.get("active_monitoring") is not False for row in items
           if str(row.get("symbol") or "").upper() != "DOS"):
        raise RecoveryBlocked("non_dos_active_scope_invalid")
    found = {}
    for symbol in ("DOS", "GRVT"):
        rows = [row for row in items if isinstance(row, dict)
                and str(row.get("symbol") or "").upper() == symbol]
        if len(rows) != 1:
            raise RecoveryBlocked("watchlist_identity_invalid")
        found[symbol] = rows[0]
    expected = {
        "DOS": (True, "P0_PRELAUNCH", DOS_TOKEN),
        "GRVT": (False, "P4_ARCHIVED_CASE", GRVT_TOKEN),
    }
    for symbol, (active, priority, token) in expected.items():
        row = found[symbol]
        contracts = row.get("contracts")
        match = isinstance(contracts, list) and len(contracts) == 1 \
            and contracts[0].get("chain") == "bsc" \
            and holder.norm(contracts[0].get("address")) == token
        if row.get("active_monitoring") is not active \
                or row.get("priority") != priority or not match:
            raise RecoveryBlocked(symbol.lower() + "_watchlist_scope_invalid")
    eligible, issues = fast.eligible_contract_items(config)
    identities = [(row.get("symbol"), row.get("chain"), row.get("address"))
                  for row in eligible]
    if issues or identities != [("DOS", "bsc", DOS_TOKEN)]:
        raise RecoveryBlocked("eligible_identity_scope_invalid")
def validated_seed(raw: Any, source: str) -> dict[str, Any]:
    seed = fast.validated_liquidity_seed(raw, DOS_TOKEN)
    expected = raw
    if source == "holder" and isinstance(raw, dict) \
            and isinstance(raw.get("reconciliation"), dict):
        reconciliation = raw["reconciliation"]
        migrated = holder.migrate_liquidity_reconciliation_state(
            reconciliation, maximum_seconds=900)
        if any(not isinstance(reconciliation.get(field, []), list)
               or migrated.get(field) != reconciliation.get(field, [])
               for field in ("pending", "completed", "deferred_events")):
            raise RecoveryBlocked("holder_seed_invalid")
        expected = copy.deepcopy(raw)
        expected["reconciliation"] = migrated
    if fast.liquidity_seed_status(raw, seed) != "valid" \
            or fast.liquidity_seed_state_kind(seed) != "checkpoint" \
            or seed != expected:
        raise RecoveryBlocked(source + "_seed_invalid")
    return seed
def identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("protocol") or ""), holder.norm(row.get("address")),
            holder.norm(row.get("pool_id")))
def validate_scope(scope: dict[str, Any], standalone: dict[str, Any],
                   current_holder: dict[str, Any]) -> None:
    pools = scope.get("pool_scope")
    if scope.get("status") != "verified_pool_scope" \
            or scope.get("complete") is not True or scope.get("source") != "opening" \
            or scope.get("matching_event_count") != 1 or not isinstance(pools, list) \
            or not pools or scope.get("scope_hash") != holder.liquidity_pool_scope_hash(pools):
        raise RecoveryBlocked("opening_scope_invalid")
    holder_pools, old_pools = current_holder.get("pool_scope"), standalone.get("pool_scope")
    if pools != holder_pools or scope.get("scope_hash") != current_holder.get("scope_hash"):
        raise RecoveryBlocked("opening_holder_scope_mismatch")
    if not isinstance(old_pools, list):
        raise RecoveryBlocked("standalone_scope_invalid")
    current, old = ({identity(row): row for row in values}
                    for values in (pools, old_pools))
    if len(current) != len(pools) or len(old) != len(old_pools) \
            or len(current) <= len(old) \
            or any(current.get(key) != row for key, row in old.items()):
        raise RecoveryBlocked("scope_row_conflict")
    reason = fast.liquidity_scope_conflict_reason(scope, standalone, current_holder)
    if reason != "seed_conflict_scope_current_holder_strict_expansion":
        raise RecoveryBlocked("scope_relation_invalid")
def canonical_checks(scope: dict[str, Any], standalone: dict[str, Any],
                     current_holder: dict[str, Any],
                     reader: Callable[[str, int], str]) -> list[dict[str, Any]]:
    rows = []
    for source, seed in (("standalone", standalone), ("holder", current_holder)):
        rows.append((source, seed.get("latest_block"), seed.get("latest_block_hash")))
    refs = holder.opening_scope_snapshot_refs(scope)
    if not refs:
        raise RecoveryBlocked("opening_snapshot_refs_invalid")
    rows.extend(("opening", block, block_hash) for block, block_hash in refs)
    output = []
    for source, block, expected in rows:
        try:
            actual = holder.norm(reader("bsc", block)) if type(block) is int else ""
        except Exception as exc:
            raise RecoveryBlocked("checkpoint_hash_unavailable") from exc
        if not holder.valid_nonzero_hash32(actual):
            raise RecoveryBlocked("checkpoint_hash_unavailable")
        if actual != holder.norm(expected):
            raise RecoveryBlocked("checkpoint_hash_mismatch")
        output.append({"source": source, "block": block, "block_hash": actual})
    return output
def valid_event_identity(event: Any) -> bool:
    try:
        pool = event.get("pool")
        return isinstance(event, dict) and type(event.get("block")) is int \
            and event["block"] >= 0 and type(event.get("log_index")) is int \
            and event["log_index"] >= 0 and holder.valid_nonzero_hash32(event.get("tx")) \
            and holder.valid_nonzero_hash32(event.get("block_hash")) \
            and isinstance(pool, str) and pool == holder.norm(pool) \
            and holder.is_address(pool) \
            and holder.valid_sha256(holder.liquidity_reconciliation_id(event))
    except Exception:
        return False
def valid_pending_identity(row: Any) -> bool:
    event = row.get("source_event") if isinstance(row, dict) else None
    return valid_event_identity(event) \
        and str(row.get("reconcile_id") or "") == holder.liquidity_reconciliation_id(event) \
        and all(type(row.get(left)) is int and row[left] == event[right]
                for left, right in (("source_block", "block"), ("source_log_index", "log_index"))) \
        and row.get("source_pool") == event["pool"] \
        and holder.valid_nonzero_hash32(row.get("source_block_hash")) \
        and holder.norm(row["source_block_hash"]) == holder.norm(event["block_hash"]) \
        and ("source_tx" not in row or holder.valid_nonzero_hash32(row.get("source_tx"))
             and holder.norm(row["source_tx"]) == holder.norm(event["tx"]))
def merge_reconciliation(standalone: dict[str, Any], current_holder: dict[str, Any]
                         ) -> tuple[dict[str, Any], int]:
    left, right = standalone.get("reconciliation"), current_holder.get("reconciliation")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise RecoveryBlocked("reconciliation_missing")
    allowed_pools = {holder.norm(row.get("address"))
                     for row in current_holder.get("pool_scope", [])}
    def merge_named(field: str) -> list[dict[str, Any]]:
        indexed = {}
        for row in [*left.get(field, []), *right.get(field, [])]:
            if field == "pending" and not valid_pending_identity(row):
                raise RecoveryBlocked("reconciliation_identity_invalid")
            if field == "pending" \
                    and holder.norm(row["source_event"]["pool"]) not in allowed_pools:
                raise RecoveryBlocked("reconciliation_scope_invalid")
            key = str(row.get("reconcile_id") or "")
            if not holder.valid_sha256(key):
                raise RecoveryBlocked("reconciliation_identity_invalid")
            if key in indexed and indexed[key] != row:
                raise RecoveryBlocked("reconciliation_row_conflict")
            indexed[key] = copy.deepcopy(row)
        time_field = "completed_at" if field == "completed" else "first_seen_at"
        return sorted(indexed.values(), key=lambda row: (
            str(row.get(time_field) or ""), str(row.get("reconcile_id") or "")))
    pending, completed = merge_named("pending"), merge_named("completed")
    pending_ids = {row["reconcile_id"] for row in pending}
    completed_ids = {row["reconcile_id"] for row in completed}
    if pending_ids & completed_ids:
        raise RecoveryBlocked("reconciliation_lifecycle_conflict")
    deferred = {}
    for row in [*left.get("deferred_events", []), *right.get("deferred_events", [])]:
        if not valid_event_identity(row):
            raise RecoveryBlocked("reconciliation_identity_invalid")
        if holder.norm(row["pool"]) not in allowed_pools:
            raise RecoveryBlocked("reconciliation_scope_invalid")
        try:
            key = holder.liquidity_reconciliation_id(row)
        except Exception as exc:
            raise RecoveryBlocked("reconciliation_identity_invalid") from exc
        if key in deferred and deferred[key] != row:
            raise RecoveryBlocked("reconciliation_row_conflict")
        deferred[key] = copy.deepcopy(row)
    events = sorted(deferred.values(), key=lambda row: (
        int(row.get("block") or 0), int(row.get("log_index") or 0),
        str(row.get("type") or ""), holder.norm(row.get("pool"))))
    if any(len(values) > 500 for values in (pending, completed, events)):
        raise RecoveryBlocked("reconciliation_limit_exceeded")
    result = {"schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
              "pending": pending, "completed": completed, "deferred_events": events}
    updated = max(str(left.get("updated_at") or ""), str(right.get("updated_at") or ""))
    if updated:
        result["updated_at"] = updated
    return result, len(set(deferred) & (pending_ids | completed_ids))
def build_recovery_bundle(paths: RecoveryPaths, *, checkpoint_hash_reader=None
                          ) -> RecoveryBundle:
    config, config_hash = read_json(paths.config)
    state, state_hash = read_json(paths.standalone_state)
    holder_state, holder_hash = read_json(paths.holder_state)
    opening, opening_hash = read_json(paths.opening)
    validate_watchlist(config)
    if state.get("schema") != fast.STATE_SCHEMA or not isinstance(state.get("tokens"), dict):
        raise RecoveryBlocked("standalone_state_invalid")
    row = state["tokens"].get(DOS_KEY)
    holder_row = (holder_state.get("tokens") or {}).get(DOS_KEY)
    if not isinstance(row, dict) or not isinstance(holder_row, dict):
        raise RecoveryBlocked("dos_state_missing")
    standalone = validated_seed(row.get("liquidity"), "standalone")
    retention = holder_row.get("retention_flow")
    current_holder = validated_seed(
        retention.get("liquidity") if isinstance(retention, dict) else None, "holder")
    if current_holder["latest_block"] <= standalone["latest_block"]:
        raise RecoveryBlocked("holder_checkpoint_not_ahead")
    scope = holder.opening_verified_pool_scope(
        opening, "DOS", "bsc", DOS_TOKEN, persisted_scope={})
    validate_scope(scope, standalone, current_holder)
    checks = canonical_checks(scope, standalone, current_holder,
                              checkpoint_hash_reader or holder.liquidity_checkpoint_block_hash)
    reconciliation, overlap = merge_reconciliation(standalone, current_holder)
    candidate = {**copy.deepcopy(current_holder), "reconciliation": reconciliation}
    if fast.validated_liquidity_seed(candidate, DOS_TOKEN) != candidate \
            or not fast.liquidity_reconciliation_dominates(candidate, standalone) \
            or not fast.liquidity_reconciliation_dominates(candidate, current_holder):
        raise RecoveryBlocked("candidate_seed_invalid")
    selection = fast.select_liquidity_seed(candidate, current_holder)
    if selection.get("conflict") is not False or selection.get("source") != "standalone" \
            or selection.get("seed") != candidate:
        raise RecoveryBlocked("candidate_selection_invalid")
    candidate_state = copy.deepcopy(state)
    candidate_state["tokens"][DOS_KEY] = {**row, "liquidity": candidate}
    input_paths = {"config": paths.config, "standalone_state": paths.standalone_state,
                   "holder_state": paths.holder_state, "opening": paths.opening}
    inputs = dict(zip(input_paths, (
        config_hash, state_hash, holder_hash, opening_hash)))
    original_events = standalone["reconciliation"]["deferred_events"]
    archive_bytes = json_bytes({
        "schema": ARCHIVE_SCHEMA,
        "input_hashes": inputs,
        "standalone_seed": standalone,
        "holder_seed": current_holder,
        "original_events": original_events,
        "original_event_sha256": [digest(event) for event in original_events],
    })
    core = {
        "schema": PLAN_SCHEMA, "mode": "dry_run",
        "status": "probe_required",
        "target": {"symbol": "DOS", "chain": "bsc", "token": DOS_TOKEN},
        "grvt_archived": True, "scope_relation":
            "seed_conflict_scope_current_holder_strict_expansion",
        "inputs": inputs, "checkpoint_checks": checks,
        "standalone": {"seed_sha256": digest(standalone),
                       "scope_hash": standalone["scope_hash"],
                       "pool_count": standalone["pool_count"],
                       "latest_block": standalone["latest_block"],
                       "coverage_from_block": standalone["scope_coverage_from_block"]},
        "holder": {"seed_sha256": digest(current_holder),
                   "scope_hash": current_holder["scope_hash"],
                   "pool_count": current_holder["pool_count"],
                   "latest_block": current_holder["latest_block"],
                   "coverage_from_block": current_holder["scope_coverage_from_block"]},
        "candidate_seed_sha256": digest(candidate),
        "candidate_state_sha256": digest(json_bytes(candidate_state, pretty=True)),
        "candidate_pending_count": len(reconciliation["pending"]),
        "candidate_completed_count": len(reconciliation["completed"]),
        "candidate_deferred_count": len(reconciliation["deferred_events"]),
        "ambiguous_overlap_count": overlap,
        "archive_sha256": digest(archive_bytes),
        "archive_event_count": len(original_events),
        "protected_manifest_sha256": digest(protected_manifest(paths)),
    }
    plan_hash = digest(core)
    plan = {**core, "plan_hash": plan_hash}
    if any(file_hash(path) != inputs[name] for name, path in input_paths.items()):
        raise RecoveryBlocked("input_hash_changed")
    return RecoveryBundle(plan, plan_hash, candidate_state, candidate, standalone,
                          current_holder, archive_bytes)
FINAL_CLASSIFICATIONS = {
    "removed_plus_sold", "range_repositioned", "re_added", "migrated",
    "net_removed",
}
def original_event_preserved(original: dict[str, Any], candidate: Any) -> bool:
    return isinstance(candidate, dict) and all(
        key in candidate and candidate[key] == value
        for key, value in original.items()
    )
def valid_completed_transition(row: dict[str, Any]) -> bool:
    classification = str(row.get("classification") or "")
    if classification == "unresolved_coverage":
        return bool(
            row.get("notify") is False
            and row.get("verdict_coverage_contract_version")
            == holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            and row.get("source_receipt_canonical") is not True
            and row.get("verdict_coverage_complete") is not True
            and row.get("evidence_level") in (None, "", "coverage_incomplete")
            and str(row.get("coverage_issue_code") or "")
            and isinstance(row.get("evidence_coverage_issues"), list)
            and row["evidence_coverage_issues"]
        )
    if classification not in FINAL_CLASSIFICATIONS \
            or row.get("verdict_coverage_complete") is not True:
        return False
    evidence = copy.deepcopy(row)
    evidence["coverage_complete"] = row.get("enrichment_coverage_complete")
    evidence["coverage_issues"] = row.get("evidence_coverage_issues")
    return holder.liquidity_verdict_evidence_finalizable(evidence)
def completed_covers_event(row: dict[str, Any], event: dict[str, Any]) -> bool:
    if not valid_event_identity(event):
        return False
    identity = holder.liquidity_reconciliation_id(event)
    return valid_completed_transition(row) \
        and str(row.get("reconcile_id") or "") == identity \
        and all(type(row.get(left)) is int and type(event.get(right)) is int
                and row[left] == event[right] for left, right in (("source_block", "block"), ("source_log_index", "log_index"))) \
        and holder.norm(row.get("source_tx")) == holder.norm(event.get("tx")) \
        and holder.norm(row.get("source_pool")) == holder.norm(event.get("pool"))
def legacy_unresolved_covers_event(row: dict[str, Any], event: dict[str, Any]) -> bool:
    if str(row.get("classification") or "") != "unresolved_coverage" \
            or not valid_completed_transition(row) \
            or not valid_event_identity(event):
        return False
    try:
        key = holder.liquidity_reconciliation_id(event)
        if str(row.get("reconcile_id") or "") != key \
                or "source_block" not in row or "source_tx" not in row \
                or type(row["source_block"]) is not int \
                or row["source_block"] != event["block"] \
                or holder.norm(row["source_tx"]) != holder.norm(event.get("tx")):
            return False
        if "source_log_index" in row \
                and (type(row["source_log_index"]) is not int
                     or row["source_log_index"] != event["log_index"]):
            return False
    except (TypeError, ValueError):
        return False
    if "source_pool" in row and holder.norm(row["source_pool"]) != holder.norm(event.get("pool")):
        return False
    if "source_block_hash" in row and holder.norm(
            row["source_block_hash"]) != holder.norm(event.get("block_hash")):
        return False
    return "source_event" not in row or original_event_preserved(event, row.get("source_event"))
def pending_transition_valid(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if not valid_pending_identity(before) or not valid_pending_identity(after):
        return False
    mutable = {
        "last_updated_at", "added_target_raw", "added_quote_raw",
        "paired_chain_elapsed_seconds", "destination_pools", "add_transactions",
        "destination_ranges", "pairing_ambiguous", "range_changed",
        "evidence_coverage_issues", "verdict_coverage_contract_version",
    }
    if any(key not in after for key in before) \
            or any(after[key] != value for key, value in before.items()
                   if key not in mutable) \
            or after.get("forced_classification") != before.get(
                "forced_classification"):
        return False
    contract = after.get("verdict_coverage_contract_version")
    if ("verdict_coverage_contract_version" in before
            and contract != before["verdict_coverage_contract_version"]) \
            or ("verdict_coverage_contract_version" not in before
                and contract not in (None, holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION)):
        return False
    before_updated = holder.parse_iso(before.get("last_updated_at"))
    after_updated = holder.parse_iso(after.get("last_updated_at"))
    if before_updated is None or after_updated is None \
            or after_updated < before_updated:
        return False
    try:
        if any(int(after.get(field) or 0) < int(before.get(field) or 0) for field in (
                "added_target_raw", "added_quote_raw", "paired_chain_elapsed_seconds")):
            return False
    except (TypeError, ValueError):
        return False
    for field in ("destination_pools", "add_transactions", "destination_ranges"):
        old, new = before.get(field) or [], after.get(field)
        if not isinstance(old, list) or not isinstance(new, list) \
                or len({digest(value) for value in new}) != len(new) \
                or any(value not in new for value in old):
            return False
    for field in ("pairing_ambiguous", "range_changed"):
        if field in after and not isinstance(after[field], bool) \
                or before.get(field) is True and after.get(field) is not True:
            return False
    issues = after.get("evidence_coverage_issues")
    if issues is not None and (not isinstance(issues, list) or len(issues) > 8):
        return False
    return True
TRANSITION_KINDS = ("deferred_exact", "pending", "completed",
                    "legacy_unresolved_overlap", "add_consumed",
                    "historical_removal_suppressed", "zero_material_removal")
def typed_transition_accounting(bundle: RecoveryBundle, next_seed: dict[str, Any]) -> dict[str, Any]:
    try:
        archive = json.loads(bundle.archive_bytes)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RecoveryBlocked("recovery_archive_invalid") from exc
    if not isinstance(archive, dict):
        raise RecoveryBlocked("recovery_archive_invalid")
    events = archive.get("original_events")
    expected_events = bundle.standalone_seed["reconciliation"]["deferred_events"]
    if digest(bundle.archive_bytes) != bundle.safe_plan.get("archive_sha256") \
            or archive.get("schema") != ARCHIVE_SCHEMA \
            or archive.get("input_hashes") != bundle.safe_plan.get("inputs") \
            or archive.get("standalone_seed") != bundle.standalone_seed \
            or archive.get("holder_seed") != bundle.holder_seed \
            or not isinstance(events, list) or events != expected_events \
            or archive.get("original_event_sha256") != [digest(row) for row in events]:
        raise RecoveryBlocked("recovery_archive_invalid")
    before = bundle.candidate_seed.get("reconciliation") or {}
    after = next_seed.get("reconciliation") or {}
    allowed_pools = {holder.norm(row.get("address"))
                     for row in bundle.candidate_seed.get("pool_scope", [])}
    before_pending = {str(row.get("reconcile_id") or ""): row
                      for row in before.get("pending", [])}
    before_completed = {str(row.get("reconcile_id") or ""): row
                        for row in before.get("completed", [])}
    result = {
        "archive_event_count": len(events),
        "transition_counts": dict.fromkeys(TRANSITION_KINDS, 0),
        "unaccounted_count": 0, "duplicate_disposition_count": 0,
        "invalid_transition_count": 0, "prior_pending_invalid_count": 0,
        "prior_completed_invalid_count": 0,
    }
    if not isinstance(after, dict):
        result["invalid_transition_count"] = 1
        return result
    invalid_rows = 0
    def indexed(field: str) -> dict[str, list[dict[str, Any]]]:
        nonlocal invalid_rows
        output: dict[str, list[dict[str, Any]]] = {}
        rows = after.get(field)
        if not isinstance(rows, list):
            invalid_rows += 1
            return output
        for row in rows:
            try:
                key = (holder.liquidity_reconciliation_id(row)
                       if field == "deferred_events"
                       else str(row.get("reconcile_id") or ""))
            except Exception:
                key = ""
            pool = holder.norm(row.get("pool")) if isinstance(row, dict) \
                and field == "deferred_events" else holder.norm(
                    (row.get("source_event") or {}).get("pool")) \
                if isinstance(row, dict) and field == "pending" else ""
            if not isinstance(row, dict) or not holder.valid_sha256(key) \
                    or field == "pending" and not valid_pending_identity(row) \
                    or field in ("deferred_events", "pending") \
                    and pool not in allowed_pools:
                invalid_rows += 1
                continue
            output.setdefault(key, []).append(row)
        return output
    deferred, pending, completed = (indexed(field) for field in (
        "deferred_events", "pending", "completed"))
    result["invalid_transition_count"] += invalid_rows
    duplicate_ids = {key for key in set(deferred) | set(pending) | set(completed)
                     if len(deferred.get(key, [])) + len(pending.get(key, []))
                     + len(completed.get(key, [])) > 1}
    result["duplicate_disposition_count"] = len(duplicate_ids)
    event_ids = []
    for event in events:
        try:
            key = holder.liquidity_reconciliation_id(event)
        except Exception:
            result["unaccounted_count"] += 1
            continue
        event_ids.append(key)
        rows = [*deferred.get(key, []), *pending.get(key, []), *completed.get(key, [])]
        matches = []
        matches.extend("deferred_exact" for row in deferred.get(key, []) if row == event)
        matches.extend("pending" for row in pending.get(key, [])
                       if original_event_preserved(event, row.get("source_event")))
        for row in completed.get(key, []):
            if before_completed.get(key) == row \
                    and legacy_unresolved_covers_event(row, event):
                matches.append("legacy_unresolved_overlap")
            elif str(row.get("classification") or "") != "unresolved_coverage" \
                    and completed_covers_event(row, event):
                matches.append("completed")
        event_type = str(event.get("type") or "")
        zero_or_historical = event.get("historical_catchup") is True
        try:
            zero_or_historical = zero_or_historical or (
                int(event.get("lp_removed_amount_raw") or 0) <= 0
                and int(event.get("quote_removed_amount_raw") or 0) <= 0)
        except (TypeError, ValueError):
            pass
        if event_type == "lp_add_observation" or zero_or_historical:
            matches = [kind for kind in matches if kind == "deferred_exact"]
        if len(rows) == 1 and len(matches) == 1:
            result["transition_counts"][matches[0]] += 1
            continue
        if rows:
            if key not in duplicate_ids:
                result["unaccounted_count"] += 1
            continue
        if event_type == "lp_add_observation":
            kind = "add_consumed"
        elif event_type in holder.LIQUIDITY_RECONCILIATION_REMOVAL_TYPES \
                and event.get("historical_catchup") is True:
            kind = "historical_removal_suppressed"
        else:
            try:
                zero = int(event.get("lp_removed_amount_raw") or 0) <= 0 \
                    and int(event.get("quote_removed_amount_raw") or 0) <= 0
            except (TypeError, ValueError):
                zero = False
            kind = "zero_material_removal" if event_type in \
                holder.LIQUIDITY_RECONCILIATION_REMOVAL_TYPES and zero else ""
        if kind:
            result["transition_counts"][kind] += 1
        else:
            result["unaccounted_count"] += 1
    for key, row in before_pending.items():
        destinations = [*pending.get(key, []), *completed.get(key, [])]
        event = row.get("source_event")
        valid = len(destinations) == 1 and (
            (key in pending and pending_transition_valid(row, destinations[0]))
            or (isinstance(event, dict) and key in completed and (
                completed_covers_event(destinations[0], event)
                or legacy_unresolved_covers_event(destinations[0], event))))
        result["prior_pending_invalid_count"] += int(not valid)
    for key, row in before_completed.items():
        result["prior_completed_invalid_count"] += int(completed.get(key) != [row])
    allowed = set(event_ids) | set(before_pending) | set(before_completed)
    result["duplicate_disposition_count"] += len(event_ids) - len(set(event_ids))
    result["invalid_transition_count"] += sum(
        len(rows) for index in (deferred, pending, completed)
        for key, rows in index.items() if key not in allowed)
    return result
@contextmanager
def probe_paths(paths: RecoveryPaths, candidate: dict[str, Any]) -> Iterator[None]:
    saved = (fast.CONFIG_PATH, fast.STATE_PATH, holder.STATE_PATH,
             holder.OPENING_CONTEXT_PATH, holder.read_json)
    def read(path: Path, default: Any) -> Any:
        return copy.deepcopy(candidate) if Path(path).resolve() == paths.standalone_state \
            else saved[4](path, default)
    fast.CONFIG_PATH, fast.STATE_PATH = paths.config, paths.standalone_state
    holder.STATE_PATH, holder.OPENING_CONTEXT_PATH = paths.holder_state, paths.opening
    holder.read_json = read
    try:
        yield
    finally:
        (fast.CONFIG_PATH, fast.STATE_PATH, holder.STATE_PATH,
         holder.OPENING_CONTEXT_PATH, holder.read_json) = saved
def assert_inputs(paths: RecoveryPaths, bundle: RecoveryBundle) -> None:
    current = {name: file_hash(path) for name, path in {
        "config": paths.config, "standalone_state": paths.standalone_state,
        "holder_state": paths.holder_state, "opening": paths.opening}.items()}
    if current != bundle.safe_plan["inputs"]:
        raise RecoveryBlocked("input_hash_changed")
def probe_recovery(paths: RecoveryPaths, plan_hash: str, *, checkpoint_hash_reader=None
                   ) -> dict[str, Any]:
    if not SHA256.fullmatch(plan_hash or ""):
        raise RecoveryBlocked("plan_hash_required")
    bundle = build_recovery_bundle(paths, checkpoint_hash_reader=checkpoint_hash_reader)
    if bundle.plan_hash != plan_hash:
        raise RecoveryBlocked("plan_hash_mismatch")
    assert_inputs(paths, bundle)
    protected = protected_manifest(paths)
    if digest(protected) != bundle.safe_plan["protected_manifest_sha256"]:
        raise RecoveryBlocked("protected_state_changed")
    with probe_paths(paths, bundle.candidate_state):
        snapshot = fast.build_snapshot()
    assert_inputs(paths, bundle)
    if protected_manifest(paths) != protected:
        raise RecoveryBlocked("protected_state_changed")
    projects = [row for row in snapshot.get("projects", []) if isinstance(row, dict)
                and row.get("symbol") == "DOS" and row.get("chain") == "bsc"
                and holder.norm(row.get("address")) == DOS_TOKEN]
    project = projects[0] if len(projects) == 1 else {}
    diagnostic = project.get("runtime_diagnostic") or {}
    healthy = snapshot.get("schema") == fast.SNAPSHOT_SCHEMA \
        and snapshot.get("status") == "healthy" and snapshot.get("issue_count") == 0 \
        and snapshot.get("expected_count") == snapshot.get("processed_count") == 1 \
        and snapshot.get("required_count") == snapshot.get("complete_count") == 1 \
        and project.get("operational_complete") is True \
        and diagnostic.get("reason_code") == "none" \
        and diagnostic.get("provider_status") == "complete" \
        and diagnostic.get("coverage_status") == "complete" \
        and diagnostic.get("next_state_kind") == "checkpoint"
    if not healthy:
        raise RecoveryBlocked("clone_probe_incomplete")
    if holder.alert_keys(snapshot):
        raise RecoveryBlocked("clone_probe_alert_pending")
    next_state = snapshot.get("_next_state") or {}
    next_row = (next_state.get("tokens") or {}).get(DOS_KEY)
    next_seed = fast.validated_liquidity_seed(
        next_row.get("liquidity") if isinstance(next_row, dict) else None, DOS_TOKEN)
    if fast.liquidity_seed_state_kind(next_seed) != "checkpoint":
        raise RecoveryBlocked("clone_probe_next_state_invalid")
    accounting = typed_transition_accounting(bundle, next_seed)
    accounted = sum(accounting["transition_counts"].values())
    if accounted != accounting["archive_event_count"] or any(
            accounting[field] for field in (
                "unaccounted_count", "duplicate_disposition_count",
                "invalid_transition_count", "prior_pending_invalid_count",
                "prior_completed_invalid_count")):
        raise RecoveryBlocked("clone_probe_transition_invalid")
    reconciliation = next_seed.get("reconciliation") or {}
    return {"schema": PROBE_SCHEMA, "status": "pass", "plan_hash": plan_hash,
            "archive_sha256": bundle.safe_plan["archive_sha256"],
            **accounting,
            "next_seed_sha256": digest(next_seed),
            "next_latest_block": next_seed.get("latest_block"),
            "next_pending_count": len(reconciliation.get("pending") or []),
            "next_completed_count": len(reconciliation.get("completed") or []),
            "next_deferred_count": len(reconciliation.get("deferred_events") or []),
            "candidate_reconciliation_sha256": digest(
                bundle.candidate_seed["reconciliation"]),
            "next_reconciliation_sha256": digest(reconciliation),
            "protected_manifest_sha256": digest(protected)}
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="plan",
                        choices=("plan", "probe"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-hash", default="")
    args = parser.parse_args(argv)
    paths = RecoveryPaths.for_root(args.root)
    try:
        if args.dry_run and args.action != "plan":
            raise RecoveryBlocked("dry_run_action_invalid")
        if args.action == "plan":
            result = build_recovery_bundle(paths).safe_plan
        else:
            result = probe_recovery(paths, args.plan_hash)
    except RecoveryBlocked as exc:
        result = {"schema": PLAN_SCHEMA, "status": "blocked", "error_code": exc.code}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
