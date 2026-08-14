"""Build and atomically apply Candidate B from an immutable Candidate A."""
from __future__ import annotations

import copy
import json
import os
import secrets
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
import scripts.finalize_alpha_liquidity_recovery as candidate_a
import scripts.migrate_alpha_liquidity_seed as recovery

PLAN_SCHEMA = "alpha_liquidity_recovery_candidate_b_plan.v1"
PREPARED_SCHEMA = "alpha_liquidity_recovery_candidate_b_prepared.v1"
APPLIED_SCHEMA = "alpha_liquidity_recovery_candidate_b_applied.v1"
ARTIFACTS = {
    "before_state.json": "target_before_sha256",
    "candidate_a_state.json": "candidate_a_state_sha256",
    "candidate_b_state.json": "candidate_b_state_sha256",
    "snapshot.json": "snapshot_sha256",
}
BINDING_FIELDS = (
    "candidate_a_plan_hash", "input_hashes", "sidecar_sha256",
    "protected_manifest_sha256", "target_before_sha256",
    "candidate_a_state_sha256", "candidate_b_state_sha256", "snapshot_sha256",
    "holder_seed_sha256", "candidate_b_seed_sha256", "candidate_b_latest_block",
    "candidate_b_latest_block_hash", "target_write_status", "rollback_status",
)

def _phase_hook(_phase: str) -> None: pass


def _directory(
    paths: recovery.RecoveryPaths, candidate_a_plan_hash: str, create: bool
) -> Path:
    base = candidate_a._directory(paths, candidate_a_plan_hash, False)
    directory = base / "candidate_b"
    if directory.is_symlink():
        raise recovery.RecoveryBlocked("artifact_path_invalid")
    if not directory.exists() and create:
        directory.mkdir()
        candidate_a._sync_dir(base)
    if not directory.exists():
        return directory
    if not directory.is_dir() or directory.resolve().parent != base:
        raise recovery.RecoveryBlocked("artifact_path_invalid")
    return directory.resolve()


def _target_bytes(paths: recovery.RecoveryPaths) -> tuple[bytes, str]:
    try:
        expected = candidate_a._target_hash(paths)
        raw = paths.standalone_state.read_bytes()
    except OSError as exc:
        raise recovery.RecoveryBlocked("target_path_invalid") from exc
    if recovery.digest(raw) != expected:
        raise recovery.RecoveryBlocked("target_state_changed")
    return raw, expected


def _seed(state: dict[str, Any], code: str) -> dict[str, Any]:
    row = (state.get("tokens") or {}).get(recovery.DOS_KEY)
    raw = row.get("liquidity") if isinstance(row, dict) else None
    value = fast.validated_liquidity_seed(raw, recovery.DOS_TOKEN)
    comparable = copy.deepcopy(raw)
    reconciliation = comparable.get("reconciliation") \
        if isinstance(comparable, dict) else None
    if isinstance(reconciliation, dict) \
            and "deferred_events" not in reconciliation:
        reconciliation["deferred_events"] = []
    if not value or comparable != value:
        raise recovery.RecoveryBlocked(code)
    return value


def _project(snapshot: dict[str, Any]) -> dict[str, Any]:
    projects = [
        row for row in snapshot.get("projects", [])
        if isinstance(row, dict)
        and row.get("symbol") == "DOS"
        and row.get("chain") == "bsc"
        and holder.norm(row.get("address")) == recovery.DOS_TOKEN
    ]
    return projects[0] if len(projects) == 1 else {}


def _checkpoint(reader, block: Any, expected: Any) -> None:
    if type(block) is not int or block <= 0 \
            or not holder.valid_nonzero_hash32(expected):
        raise recovery.RecoveryBlocked("candidate_b_checkpoint_invalid")
    try:
        actual = holder.norm(reader("bsc", block))
    except Exception as exc:
        raise recovery.RecoveryBlocked("checkpoint_hash_unavailable") from exc
    if not holder.valid_nonzero_hash32(actual):
        raise recovery.RecoveryBlocked("checkpoint_hash_unavailable")
    if actual != holder.norm(expected):
        raise recovery.RecoveryBlocked("checkpoint_hash_mismatch")


def _reconciliation_rows(seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state = seed.get("reconciliation") or {}
    try:
        named = [*state.get("pending", []), *state.get("completed", [])]
        indexed = {str(row["reconcile_id"]): row for row in named}
        deferred = state.get("deferred_events", [])
        indexed.update({holder.liquidity_reconciliation_id(row): row
                        for row in deferred})
    except (AttributeError, TypeError, ValueError) as exc:
        raise recovery.RecoveryBlocked(
            "candidate_b_reconciliation_invalid") from exc
    if len(indexed) != len(named) + len(deferred):
        raise recovery.RecoveryBlocked("candidate_b_reconciliation_invalid")
    return indexed


def _policy_preserved(
    candidate_a_seed: dict[str, Any], candidate_b_seed: dict[str, Any]
) -> bool:
    before = _reconciliation_rows(candidate_a_seed)
    after = _reconciliation_rows(candidate_b_seed)
    policy = holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY

    def has_policy(value: Any) -> bool:
        return holder.recovery_replay_notification_policy(value) == policy

    for identity, row in before.items():
        source = row.get("source_event") if isinstance(row, dict) else None
        row_policy, source_policy = has_policy(row), has_policy(source)
        if not row_policy and not source_policy:
            continue
        current = after.get(identity)
        current_source = current.get("source_event") \
            if isinstance(current, dict) else None
        if not isinstance(current, dict) \
                or row_policy and not has_policy(current) \
                or source_policy and not has_policy(current_source) \
                or current.get("notify") is True \
                or current.get("alert_eligible") is True:
            return False
    return True


def _validate_new_rows(
    candidate_a_seed: dict[str, Any],
    candidate_b_seed: dict[str, Any],
    holder_latest: int,
    project: dict[str, Any],
    reader,
) -> None:
    before = set(_reconciliation_rows(candidate_a_seed))
    after = _reconciliation_rows(candidate_b_seed)
    events = ((project.get("retention_flow") or {}).get(
        "liquidity_retention"
    ) or {}).get("events")
    try:
        snapshot_events = {
            holder.liquidity_reconciliation_id(event): event for event in events
        }
    except (TypeError, ValueError) as exc:
        raise recovery.RecoveryBlocked(
            "candidate_b_snapshot_events_invalid") from exc
    if len(snapshot_events) != len(events):
        raise recovery.RecoveryBlocked("candidate_b_snapshot_events_invalid")
    latest = candidate_b_seed["latest_block"]
    for identity in set(after) - before:
        event = snapshot_events.get(identity)
        if not isinstance(event, dict):
            raise recovery.RecoveryBlocked(
                "candidate_b_live_row_not_in_snapshot")
        block = event.get("block")
        if type(block) is not int or not holder_latest < block <= latest:
            raise recovery.RecoveryBlocked(
                "candidate_b_live_row_out_of_window")
        if holder.liquidity_reconciliation_id(event) != identity:
            raise recovery.RecoveryBlocked(
                "candidate_b_live_row_not_in_snapshot")
        row = after[identity]
        source = row.get("source_event") if isinstance(row, dict) else None
        if not isinstance(source, dict):
            source = row if "block" in row else {
                "block": row.get("source_block"),
                "block_hash": row.get("source_block_hash"),
                "log_index": row.get("source_log_index"),
                "pool": row.get("source_pool"),
                "tx": row.get("source_tx"),
            }
        exact = all(source.get(field) == event.get(field) for field in (
            "block", "log_index",
        )) and all(holder.norm(source.get(field)) == holder.norm(event.get(field))
                   for field in ("block_hash", "pool", "tx"))
        source_bound = "source_event" not in row or (
            recovery.valid_pending_identity(row)
            and recovery.original_event_preserved(event, source)
        )
        if not exact or not source_bound:
            raise recovery.RecoveryBlocked("candidate_b_live_row_mismatch")
        _checkpoint(reader, block, event.get("block_hash"))


def _validate_candidate_b(
    snapshot: dict[str, Any],
    candidate_a_state: dict[str, Any],
    holder_seed: dict[str, Any],
    reader,
) -> tuple[bytes, bytes, dict[str, Any]]:
    project = _project(snapshot)
    diagnostic = project.get("runtime_diagnostic") or {}
    healthy = (
        snapshot.get("schema") == fast.SNAPSHOT_SCHEMA
        and snapshot.get("status") == "healthy"
        and snapshot.get("issue_count") == 0
        and snapshot.get("expected_count")
        == snapshot.get("processed_count") == 1
        and snapshot.get("required_count")
        == snapshot.get("complete_count") == 1
        and snapshot.get("project_count") == 1
        and snapshot.get("dropped_count") == 0
        and snapshot.get("expected_identity_hash")
        == snapshot.get("processed_identity_hash")
        and project.get("required") is True
        and project.get("operational_complete") is True
        and diagnostic.get("reason_code") == "none"
        and diagnostic.get("provider_status") == "complete"
        and diagnostic.get("coverage_status") == "complete"
        and diagnostic.get("next_state_kind") == "checkpoint"
    )
    if not healthy:
        raise recovery.RecoveryBlocked("clone_probe_incomplete")
    alerts = holder.alert_keys(snapshot)
    if alerts or snapshot.get("alert_count") != 0:
        raise recovery.RecoveryBlocked("clone_probe_alert_pending")
    next_state = snapshot.get("_next_state")
    if not isinstance(next_state, dict):
        raise recovery.RecoveryBlocked("candidate_b_state_invalid")
    candidate_a_seed = _seed(candidate_a_state, "candidate_a_state_invalid")
    candidate_b_seed = _seed(next_state, "candidate_b_state_invalid")
    if fast.liquidity_seed_state_kind(candidate_b_seed) != "checkpoint":
        raise recovery.RecoveryBlocked("candidate_b_checkpoint_invalid")
    holder_latest = holder_seed.get("latest_block")
    latest = candidate_b_seed.get("latest_block")
    if type(holder_latest) is not int or type(latest) is not int \
            or latest <= holder_latest:
        raise recovery.RecoveryBlocked("candidate_b_not_ahead")
    _checkpoint(reader, latest, candidate_b_seed.get("latest_block_hash"))
    if not fast.liquidity_reconciliation_dominates(
        candidate_b_seed, candidate_a_seed
    ) or not fast.liquidity_reconciliation_dominates(
        candidate_b_seed, holder_seed
    ):
        raise recovery.RecoveryBlocked(
            "candidate_b_reconciliation_not_dominant")
    if not _policy_preserved(candidate_a_seed, candidate_b_seed):
        raise recovery.RecoveryBlocked(
            "candidate_b_notification_policy_regressed")
    expected = copy.deepcopy(candidate_a_state)
    expected["tokens"][recovery.DOS_KEY]["liquidity"] = next_state[
        "tokens"
    ][recovery.DOS_KEY]["liquidity"]
    if next_state != expected:
        raise recovery.RecoveryBlocked("candidate_b_state_scope_changed")
    _validate_new_rows(
        candidate_a_seed, candidate_b_seed, holder_latest, project, reader
    )
    return (recovery.json_bytes(next_state, pretty=True),
            recovery.json_bytes(snapshot, pretty=True), candidate_b_seed)


def _verify_a_locked(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    sidecar_hash: str,
    plan_hash: str,
    checkpoint_hash_reader,
) -> tuple[dict[str, Any], dict[str, bytes], recovery.RecoveryBundle]:
    plan, _prepared, artifacts = candidate_a._load(paths, plan_hash)
    observed_at = holder.parse_iso(plan.get("observed_at"))
    if observed_at is None or plan.get("sidecar_sha256") != sidecar_hash:
        raise recovery.RecoveryBlocked("prepared_plan_invalid")
    bundle, sidecar_bytes, rebuilt_candidate, rebuilt_plan = \
        candidate_a._build_candidate_a_plan(
            paths, sidecar_path, sidecar_hash, observed_at,
            checkpoint_hash_reader,
        )
    if rebuilt_plan != plan \
            or bundle.archive_bytes != artifacts["source_archive.json"] \
            or sidecar_bytes != artifacts["sidecar.json"] \
            or rebuilt_candidate.state_bytes != artifacts[
                "candidate_a_state.json"
            ]:
        raise recovery.RecoveryBlocked("prepared_plan_invalid")
    return plan, artifacts, bundle


def _plan(
    a_plan: dict[str, Any],
    payloads: dict[str, bytes],
    holder_seed: dict[str, Any],
    b_seed: dict[str, Any],
) -> dict[str, Any]:
    core = {
        "schema": PLAN_SCHEMA,
        "phase": "candidate_b_prepared",
        "candidate_a_plan_hash": a_plan["plan_hash"],
        "source_plan_hash": a_plan["source_plan_hash"],
        "input_hashes": copy.deepcopy(a_plan["input_hashes"]),
        "checkpoint_checks": copy.deepcopy(a_plan["checkpoint_checks"]),
        "sidecar_sha256": a_plan["sidecar_sha256"],
        "protected_manifest": copy.deepcopy(a_plan["protected_manifest"]),
        "protected_manifest_sha256": recovery.digest(
            a_plan["protected_manifest"]),
        **{
            field: recovery.digest(payloads[name])
            for name, field in ARTIFACTS.items()
        },
        "holder_seed_sha256": recovery.digest(holder_seed),
        "holder_latest_block": holder_seed["latest_block"],
        "candidate_b_seed_sha256": recovery.digest(b_seed),
        "candidate_b_latest_block": b_seed["latest_block"],
        "candidate_b_latest_block_hash": b_seed["latest_block_hash"],
        "alert_keys": [],
        "target_write_status": "candidate_b_only",
        "candidate_b_status": "prepared",
        "rollback_status": "not_implemented",
    }
    return {**core, "plan_hash": recovery.digest(core)}


def _receipt(
    plan: dict[str, Any], applied: bool, source_bytes: bytes
) -> dict[str, Any]:
    status = "candidate_b_applied" if applied else "candidate_b_prepared"
    return {
        "schema": APPLIED_SCHEMA if applied else PREPARED_SCHEMA,
        "status": status,
        "plan_hash": plan["plan_hash"],
        ("prepared_file_sha256" if applied else "plan_file_sha256"):
            recovery.digest(source_bytes),
        **{field: copy.deepcopy(plan[field]) for field in BINDING_FIELDS},
    }


def _prepare(
    paths: recovery.RecoveryPaths,
    plan: dict[str, Any],
    payloads: dict[str, bytes],
) -> bytes:
    directory = _directory(paths, plan["candidate_a_plan_hash"], True)
    for name, field in ARTIFACTS.items():
        if recovery.digest(payloads[name]) != plan[field]:
            raise recovery.RecoveryBlocked("candidate_b_artifact_invalid")
        candidate_a._write_once(directory / name, payloads[name])
    plan_bytes = recovery.json_bytes(plan, pretty=True)
    prepared_bytes = recovery.json_bytes(
        _receipt(plan, False, plan_bytes), pretty=True
    )
    candidate_a._write_once(directory / "plan.json", plan_bytes)
    candidate_a._write_once(directory / "prepared.json", prepared_bytes)
    return prepared_bytes


def _load(
    paths: recovery.RecoveryPaths, candidate_a_plan_hash: str
) -> tuple[dict[str, Any], bytes, dict[str, bytes], bool]:
    directory = _directory(paths, candidate_a_plan_hash, False)
    plan, plan_bytes = candidate_a._read_json(directory / "plan.json")
    plan_hash = plan.get("plan_hash")
    core = {key: value for key, value in plan.items() if key != "plan_hash"}
    hashes = (
        "candidate_a_plan_hash", "sidecar_sha256", "protected_manifest_sha256",
        "target_before_sha256", "candidate_a_state_sha256",
        "candidate_b_state_sha256", "snapshot_sha256",
        "holder_seed_sha256", "candidate_b_seed_sha256",
    )
    semantics = (
        plan.get("schema") == PLAN_SCHEMA
        and plan.get("candidate_a_plan_hash") == candidate_a_plan_hash
        and plan.get("phase") == "candidate_b_prepared"
        and plan.get("candidate_b_status") == "prepared"
        and plan.get("target_write_status") == "candidate_b_only"
        and plan.get("rollback_status") == "not_implemented"
        and plan.get("alert_keys") == []
        and all(recovery.SHA256.fullmatch(plan.get(key) or "") for key in hashes)
    )
    if not semantics or plan.get("plan_hash") != plan_hash \
            or recovery.digest(core) != plan_hash \
            or plan_bytes != recovery.json_bytes(plan, pretty=True):
        raise recovery.RecoveryBlocked("candidate_b_plan_invalid")
    prepared, prepared_bytes = candidate_a._read_json(
        directory / "prepared.json"
    )
    if prepared != _receipt(plan, False, plan_bytes) \
            or prepared_bytes != recovery.json_bytes(prepared, pretty=True):
        raise recovery.RecoveryBlocked("candidate_b_prepared_invalid")
    payloads: dict[str, bytes] = {}
    for name, field in ARTIFACTS.items():
        _value, raw = candidate_a._read_json(directory / name)
        if recovery.digest(raw) != plan[field]:
            raise recovery.RecoveryBlocked("candidate_b_artifact_invalid")
        payloads[name] = raw
    applied_path = directory / "applied.json"
    if applied_path.exists():
        applied, applied_bytes = candidate_a._read_json(applied_path)
        if applied != _receipt(plan, True, prepared_bytes) \
                or applied_bytes != recovery.json_bytes(applied, pretty=True):
            raise recovery.RecoveryBlocked("applied_receipt_invalid")
    return plan, prepared_bytes, payloads, applied_path.exists()


def _assert_fresh(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    plan: dict[str, Any],
    expected_target: str,
    checkpoint_hash_reader,
) -> None:
    sources = {
        "config": paths.config,
        "holder_state": paths.holder_state,
        "opening": paths.opening,
    }
    if any(
        recovery.file_hash(path) != plan["input_hashes"].get(name)
        for name, path in sources.items()
    ):
        raise recovery.RecoveryBlocked("input_hash_changed")
    if recovery.file_hash(sidecar_path) != plan["sidecar_sha256"]:
        raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
    if recovery.protected_manifest(paths) != plan["protected_manifest"]:
        raise recovery.RecoveryBlocked("protected_state_changed")
    candidate_a._checkpoints(plan, checkpoint_hash_reader)
    _checkpoint(
        checkpoint_hash_reader,
        plan["candidate_b_latest_block"],
        plan["candidate_b_latest_block_hash"],
    )
    if _target_bytes(paths)[1] != expected_target:
        raise recovery.RecoveryBlocked("target_state_changed")


def _cas_target(
    paths: recovery.RecoveryPaths, expected_hash: str, payload: bytes
) -> None:
    if _target_bytes(paths)[1] != expected_hash:
        raise recovery.RecoveryBlocked("target_state_changed")
    _phase_hook("cas_after_validation")
    target = paths.standalone_state.absolute()
    parent_fd = -1
    temporary = f".{target.name}.candidate-b.{secrets.token_hex(8)}"
    nofollow = getattr(os, "O_NOFOLLOW", 0)

    def inode(value) -> tuple[int, int]:
        return value.st_dev, value.st_ino

    def read_target() -> bytes:
        descriptor = os.open(
            target.name, os.O_RDONLY | nofollow, dir_fd=parent_fd
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError("target is not regular")
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()

    try:
        parent_fd = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | nofollow
        )
        parent_stat = os.stat(target.parent, follow_symlinks=False)
        opened_stat = os.fstat(parent_fd)
        if inode(parent_stat) != inode(opened_stat) \
                or recovery.digest(read_target()) != expected_hash:
            raise recovery.RecoveryBlocked("target_state_changed")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o644, dir_fd=parent_fd
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if recovery.digest(read_target()) != expected_hash:
            raise recovery.RecoveryBlocked("target_state_changed")
        current_parent = os.stat(target.parent, follow_symlinks=False)
        if inode(current_parent) != inode(opened_stat):
            raise OSError("target parent changed")
        os.replace(temporary, target.name, src_dir_fd=parent_fd,
                   dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except recovery.RecoveryBlocked:
        raise
    except OSError as exc:
        raise recovery.RecoveryBlocked("target_state_cas_failed") from exc
    finally:
        if parent_fd >= 0:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)
    if _target_bytes(paths)[0] != payload:
        raise recovery.RecoveryBlocked("target_state_cas_failed")


def apply_candidate_b(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    sidecar_hash: str,
    lock_paths: candidate_a.RecoveryLockPaths,
    *,
    candidate_a_plan_hash: str,
    checkpoint_hash_reader=None,
) -> dict[str, Any]:
    reader = checkpoint_hash_reader or holder.liquidity_checkpoint_block_hash
    a_plan = candidate_a._load(paths, candidate_a_plan_hash)[0]
    if _target_bytes(paths)[1] == a_plan["target_state_sha256"]:
        candidate_a.verify_prepared_candidate_a(
            paths, sidecar_path, sidecar_hash, lock_paths,
            plan_hash=candidate_a_plan_hash,
            checkpoint_hash_reader=reader,
        )
    with candidate_a.recovery_locks(lock_paths, sidecar_path):
        directory = _directory(paths, candidate_a_plan_hash, False)
        if not (directory / "prepared.json").is_file():
            if (directory / "applied.json").exists():
                raise recovery.RecoveryBlocked("applied_receipt_invalid")
            before_bytes, before_hash = _target_bytes(paths)
            live_a_plan, a_artifacts, bundle = _verify_a_locked(
                paths, sidecar_path, sidecar_hash, candidate_a_plan_hash, reader
            )
            if before_hash != live_a_plan["target_state_sha256"]:
                raise recovery.RecoveryBlocked("target_state_neither")
            a_bytes = a_artifacts["candidate_a_state.json"]
            a_state = json.loads(a_bytes)
            with recovery.probe_paths(paths, a_state):
                snapshot = fast.build_snapshot()
            b_bytes, snapshot_bytes, b_seed = _validate_candidate_b(
                snapshot, a_state, bundle.holder_seed, reader
            )
            payloads = {
                "before_state.json": before_bytes,
                "candidate_a_state.json": a_bytes,
                "candidate_b_state.json": b_bytes,
                "snapshot.json": snapshot_bytes,
            }
            plan = _plan(live_a_plan, payloads, bundle.holder_seed, b_seed)
            _phase_hook("before_prepared_cas")
            _assert_fresh(paths, sidecar_path, plan, before_hash, reader)
            prepared_bytes = _prepare(paths, plan, payloads)
        else:
            plan, prepared_bytes, payloads, applied_exists = _load(
                paths, candidate_a_plan_hash
            )
            before_hash = plan["target_before_sha256"]
            b_bytes = payloads["candidate_b_state.json"]
            b_hash = plan["candidate_b_state_sha256"]
            current_hash = _target_bytes(paths)[1]
            if applied_exists and current_hash != b_hash:
                raise recovery.RecoveryBlocked("applied_receipt_invalid")
            if current_hash not in {before_hash, b_hash}:
                raise recovery.RecoveryBlocked("target_state_neither")
            archived_paths = replace(
                paths, standalone_state=directory / "before_state.json"
            )
            live_a_plan, a_artifacts, bundle = _verify_a_locked(
                archived_paths, sidecar_path, sidecar_hash,
                candidate_a_plan_hash, reader
            )
            snapshot = json.loads(payloads["snapshot.json"])
            a_state = json.loads(payloads["candidate_a_state.json"])
            checked_b, checked_snapshot, b_seed = _validate_candidate_b(
                snapshot, a_state, bundle.holder_seed, reader
            )
            if a_artifacts["candidate_a_state.json"] != payloads[
                "candidate_a_state.json"
            ] or checked_b != b_bytes or checked_snapshot != payloads[
                "snapshot.json"
            ]:
                raise recovery.RecoveryBlocked("candidate_b_artifact_invalid")
            rebuilt = _plan(live_a_plan, payloads, bundle.holder_seed, b_seed)
            if rebuilt != plan:
                raise recovery.RecoveryBlocked("candidate_b_plan_invalid")
        _phase_hook("after_prepared")
        b_hash = plan["candidate_b_state_sha256"]
        current_hash = _target_bytes(paths)[1]
        if current_hash == before_hash:
            _phase_hook("before_replace_cas")
            _assert_fresh(paths, sidecar_path, plan, before_hash, reader)
            _cas_target(paths, before_hash, b_bytes)
            _phase_hook("after_replace")
        elif current_hash != b_hash:
            raise recovery.RecoveryBlocked("target_state_neither")
        _assert_fresh(paths, sidecar_path, plan, b_hash, reader)
        applied = _receipt(plan, True, prepared_bytes)
        applied_bytes = recovery.json_bytes(applied, pretty=True)
        candidate_a._write_once(directory / "applied.json", applied_bytes)
        return applied
