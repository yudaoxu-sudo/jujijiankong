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
    if fast.liquidity_seed_status(raw, seed) != "valid" \
            or fast.liquidity_seed_state_kind(seed) != "checkpoint" \
            or seed != raw:
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
def merge_reconciliation(standalone: dict[str, Any], current_holder: dict[str, Any]
                         ) -> tuple[dict[str, Any], int]:
    left, right = standalone.get("reconciliation"), current_holder.get("reconciliation")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise RecoveryBlocked("reconciliation_missing")
    def merge_named(field: str) -> list[dict[str, Any]]:
        indexed = {}
        for row in [*left.get(field, []), *right.get(field, [])]:
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
        "protected_manifest_sha256": digest(protected_manifest(paths)),
    }
    plan_hash = digest(core)
    plan = {**core, "plan_hash": plan_hash}
    if any(file_hash(path) != inputs[name] for name, path in input_paths.items()):
        raise RecoveryBlocked("input_hash_changed")
    return RecoveryBundle(plan, plan_hash, candidate_state, candidate, standalone,
                          current_holder)
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
    try:
        identity = holder.liquidity_reconciliation_id(event)
    except Exception:
        return False
    return valid_completed_transition(row) \
        and str(row.get("reconcile_id") or "") == identity \
        and int(row.get("source_block") or 0) == int(event.get("block") or 0) \
        and int(row.get("source_log_index") or 0) == int(event.get("log_index") or 0) \
        and holder.norm(row.get("source_tx")) == holder.norm(event.get("tx")) \
        and holder.norm(row.get("source_pool")) == holder.norm(event.get("pool"))
def reconciliation_rows_preserved(previous: dict[str, Any],
                                  candidate: dict[str, Any]) -> bool:
    before, after = previous.get("reconciliation"), candidate.get("reconciliation")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    completed = {str(row.get("reconcile_id") or ""): row
                 for row in after.get("completed", []) if isinstance(row, dict)}
    pending = {str(row.get("reconcile_id") or ""): row
               for row in after.get("pending", []) if isinstance(row, dict)}
    for row in before.get("completed", []):
        if completed.get(str(row.get("reconcile_id") or "")) != row:
            return False
    for row in before.get("pending", []):
        key = str(row.get("reconcile_id") or "")
        if pending.get(key) == row:
            continue
        event = row.get("source_event")
        if key not in completed or not isinstance(event, dict) \
                or not completed_covers_event(completed[key], event):
            return False
    deferred = {holder.liquidity_reconciliation_id(row): row
                for row in after.get("deferred_events", [])
                if isinstance(row, dict)}
    for event in before.get("deferred_events", []):
        key = holder.liquidity_reconciliation_id(event)
        pending_event = pending.get(key, {}).get("source_event")
        if original_event_preserved(event, deferred.get(key)) \
                or original_event_preserved(event, pending_event) \
                or (key in completed and completed_covers_event(completed[key], event)):
            continue
        else:
            return False
    return True
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
    next_state = snapshot.get("_next_state") or {}
    next_row = (next_state.get("tokens") or {}).get(DOS_KEY)
    next_seed = fast.validated_liquidity_seed(
        next_row.get("liquidity") if isinstance(next_row, dict) else None, DOS_TOKEN)
    if fast.liquidity_seed_state_kind(next_seed) != "checkpoint" \
            or not fast.liquidity_reconciliation_dominates(next_seed, bundle.candidate_seed):
        raise RecoveryBlocked("clone_probe_next_state_invalid")
    if not reconciliation_rows_preserved(bundle.candidate_seed, next_seed):
        raise RecoveryBlocked("clone_probe_reconciliation_evidence_loss")
    reconciliation = next_seed.get("reconciliation") or {}
    return {"schema": PROBE_SCHEMA, "status": "pass", "plan_hash": plan_hash,
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
