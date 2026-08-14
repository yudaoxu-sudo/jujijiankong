"""Prepare Candidate-A evidence; production state writes are forbidden."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
import scripts.migrate_alpha_liquidity_seed as recovery
import scripts.prepare_alpha_liquidity_recovery_enrichment as enrichment

PLAN_SCHEMA = "alpha_liquidity_recovery_candidate_a_plan.v1"
PREPARED_SCHEMA = "alpha_liquidity_recovery_candidate_a_prepared.v1"
EXPECTED_ARCHIVE_EVENT_COUNT = 499
EXPECTED_COUNTS = {"pending": 54, "completed": 6, "deferred_events": 0}
EXPECTED_TRANSITIONS = {
    "add_consumed": 390,
    "completed": 0,
    "deferred_exact": 0,
    "historical_removal_suppressed": 49,
    "legacy_unresolved_overlap": 1,
    "pending": 54,
    "zero_material_removal": 5,
}
ARTIFACTS = {
    "source_archive.json": "source_archive_sha256",
    "sidecar.json": "sidecar_sha256",
    "candidate_a_state.json": "candidate_a_state_sha256",
}


@dataclass(frozen=True)
class RecoveryLockPaths:
    main: Path
    fast: Path
    project: Path
    liquidity: Path

@dataclass(frozen=True)
class CandidateA:
    seed: dict[str, Any]
    state_bytes: bytes
    accounting: dict[str, Any]


def read_exact_sidecar(path: Path, expected_hash: str) -> tuple[dict, bytes]:
    if not recovery.SHA256.fullmatch(expected_hash or ""):
        raise recovery.RecoveryBlocked("sidecar_hash_required")
    try:
        raw = path.read_bytes()
        if recovery.digest(raw) != expected_hash:
            raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
        value = json.loads(raw)
    except recovery.RecoveryBlocked:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise recovery.RecoveryBlocked("sidecar_unavailable") from exc
    if not isinstance(value, dict):
        raise recovery.RecoveryBlocked("sidecar_unavailable")
    return value, raw


def _counts(seed: dict[str, Any]) -> dict[str, int]:
    state = seed.get("reconciliation")
    fields = ("pending", "completed", "deferred_events")
    if not isinstance(state, dict) \
            or any(not isinstance(state.get(field), list) for field in fields):
        raise recovery.RecoveryBlocked("candidate_a_reconciliation_invalid")
    return {field: len(state[field]) for field in fields}


def _clean_accounting(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("archive_event_count") == EXPECTED_ARCHIVE_EVENT_COUNT
        and value.get("transition_counts") == EXPECTED_TRANSITIONS
        and all(
            value.get(field) == 0
            for field in (
                "unaccounted_count",
                "duplicate_disposition_count",
                "invalid_transition_count",
                "prior_pending_invalid_count",
                "prior_completed_invalid_count",
            )
        )
    )


def build_candidate_a(
    bundle: recovery.RecoveryBundle,
    sidecar: dict[str, Any],
    *,
    expected_sidecar_sha256: str,
    observed_at: datetime,
) -> CandidateA:
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise recovery.RecoveryBlocked("observed_at_invalid")
    current = observed_at.astimezone(timezone.utc).replace(microsecond=0)
    events = enrichment.materialize_ready_events(
        bundle, sidecar,
        expected_sidecar_sha256=expected_sidecar_sha256,
    )
    if len(events) != EXPECTED_ARCHIVE_EVENT_COUNT:
        raise recovery.RecoveryBlocked("candidate_a_archive_count_invalid")
    events = [
        {
            **copy.deepcopy(event),
            "notification_policy": holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY,
        }
        for event in events
    ]
    output, next_reconciliation, _metadata = holder.reconcile_liquidity_events(
        events,
        copy.deepcopy(bundle.candidate_seed["reconciliation"]),
        token_decimals=18,
        observed_at=current,
        coverage_complete=True,
        evidence_by_id={},
    )
    next_reconciliation = copy.deepcopy(next_reconciliation)
    next_reconciliation["deferred_events"] = []
    seed = {
        **copy.deepcopy(bundle.candidate_seed),
        "reconciliation": next_reconciliation,
    }
    if _counts(seed) != EXPECTED_COUNTS:
        raise recovery.RecoveryBlocked("candidate_a_shape_changed")
    if fast.validated_liquidity_seed(seed, recovery.DOS_TOKEN) != seed:
        raise recovery.RecoveryBlocked("candidate_a_seed_invalid")
    accounting = recovery.typed_transition_accounting(bundle, seed)
    if not _clean_accounting(accounting):
        raise recovery.RecoveryBlocked("candidate_a_transition_invalid")
    if any(
        row.get("notify") is True
        or (
            row.get("historical_catchup") is not True
            and row.get("alert_eligible") is not False
        )
        for row in output if isinstance(row, dict)
    ):
        raise recovery.RecoveryBlocked("candidate_a_alert_pending")
    archive_ids = {
        holder.liquidity_reconciliation_id(row)
        for row in bundle.standalone_seed["reconciliation"]["deferred_events"]
    }
    for row in next_reconciliation["pending"]:
        if row.get("reconcile_id") in archive_ids and (
            row.get("notification_policy")
            != holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY
            or holder.recovery_replay_notification_policy(row.get("source_event"))
            != holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY
        ):
            raise recovery.RecoveryBlocked(
                "candidate_a_notification_policy_missing"
            )
    state = copy.deepcopy(bundle.candidate_state)
    token_state = (state.get("tokens") or {}).get(recovery.DOS_KEY)
    if not isinstance(token_state, dict):
        raise recovery.RecoveryBlocked("candidate_a_state_invalid")
    token_state["liquidity"] = seed
    return CandidateA(seed, recovery.json_bytes(state, pretty=True), accounting)


@contextmanager
def recovery_locks(
    paths: RecoveryLockPaths,
    sidecar_path: Path,
) -> Iterator[None]:
    held: list[int] = []
    ordered = (
        ("main", paths.main), ("fast", paths.fast),
        ("project", paths.project), ("liquidity", paths.liquidity),
        ("sidecar", sidecar_path.with_suffix(sidecar_path.suffix + ".lock")),
    )
    try:
        for name, path in ordered:
            descriptor = -1
            try:
                descriptor = os.open(
                    path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                )
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError("lock is not a regular file")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                if descriptor >= 0:
                    os.close(descriptor)
                raise recovery.RecoveryBlocked("recovery_lock_busy") from exc
            except OSError as exc:
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                raise recovery.RecoveryBlocked("recovery_lock_unavailable") from exc
            held.append(descriptor)
        yield
    finally:
        for descriptor in reversed(held):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _directory(paths: recovery.RecoveryPaths, plan_hash: str, create: bool) -> Path:
    if not recovery.SHA256.fullmatch(plan_hash or ""):
        raise recovery.RecoveryBlocked("candidate_a_plan_hash_invalid")
    root = paths.root.resolve()
    base = root
    for name in ("output", "alpha_liquidity_seed_recovery", "archive"):
        base = base / name
        if base.is_symlink() or (base.exists() and not base.is_dir()):
            raise recovery.RecoveryBlocked("artifact_path_invalid")
        if not base.exists():
            if not create:
                raise recovery.RecoveryBlocked("artifact_path_invalid")
            base.mkdir()
            _sync_dir(base.parent)
    directory = base / plan_hash
    if directory.is_symlink():
        raise recovery.RecoveryBlocked("artifact_path_invalid")
    if not directory.exists() and create:
        directory.mkdir()
        _sync_dir(base)
    if not directory.is_dir() or directory.resolve().parent != base.resolve() \
            or not directory.resolve().is_relative_to(root):
        raise recovery.RecoveryBlocked("artifact_path_invalid")
    return directory.resolve()


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, data: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o444,
        )
    except FileExistsError:
        if path.is_symlink() or not path.is_file() \
                or stat.S_IMODE(path.stat().st_mode) & 0o222 \
                or path.read_bytes() != data:
            raise recovery.RecoveryBlocked("immutable_artifact_conflict")
        return
    except OSError as exc:
        raise recovery.RecoveryBlocked("immutable_artifact_unavailable") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        _sync_dir(path.parent)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _target_hash(paths: recovery.RecoveryPaths) -> str:
    target = paths.standalone_state.absolute()
    if target.is_symlink() or target.parent.is_symlink() \
            or not target.is_file() \
            or not target.resolve().is_relative_to(paths.root.resolve()):
        raise recovery.RecoveryBlocked("target_path_invalid")
    return recovery.file_hash(target)


def _checkpoints(plan: dict[str, Any], reader=None) -> None:
    checks = plan.get("checkpoint_checks")
    if not isinstance(checks, list) or not checks:
        raise recovery.RecoveryBlocked("prepared_plan_invalid")
    read_hash = reader or holder.liquidity_checkpoint_block_hash
    for row in checks:
        if not isinstance(row, dict) or type(row.get("block")) is not int \
                or not holder.valid_nonzero_hash32(row.get("block_hash")):
            raise recovery.RecoveryBlocked("prepared_plan_invalid")
        try:
            actual = holder.norm(read_hash("bsc", row["block"]))
        except Exception as exc:
            raise recovery.RecoveryBlocked(
                "checkpoint_hash_unavailable"
            ) from exc
        if not holder.valid_nonzero_hash32(actual):
            raise recovery.RecoveryBlocked("checkpoint_hash_unavailable")
        if actual != holder.norm(row["block_hash"]):
            raise recovery.RecoveryBlocked("checkpoint_hash_mismatch")


def _plan(
    bundle: recovery.RecoveryBundle,
    sidecar: dict[str, Any],
    sidecar_hash: str,
    candidate: CandidateA,
    protected: dict[str, dict[str, Any]],
    observed_at: datetime,
) -> dict[str, Any]:
    core = {
        "schema": PLAN_SCHEMA,
        "phase": "candidate_a_prepared",
        "source_plan_hash": bundle.plan_hash,
        "checkpoint_checks": copy.deepcopy(bundle.safe_plan["checkpoint_checks"]),
        "input_hashes": copy.deepcopy(bundle.safe_plan["inputs"]),
        "target_state_sha256": bundle.safe_plan["inputs"]["standalone_state"],
        "candidate_a_state_sha256": recovery.digest(candidate.state_bytes),
        "source_archive_sha256": recovery.digest(bundle.archive_bytes),
        "sidecar_sha256": sidecar_hash,
        "sidecar_job_id": sidecar.get("job_id"),
        "candidate_a_seed_sha256": recovery.digest(candidate.seed),
        "candidate_a_counts": _counts(candidate.seed),
        "transition_accounting": copy.deepcopy(candidate.accounting),
        "protected_manifest": copy.deepcopy(protected),
        "observed_at": observed_at.isoformat(),
        "target_write_status": "forbidden_until_candidate_b",
        "candidate_b_status": "not_implemented",
        "rollback_status": "not_implemented",
    }
    return {**core, "plan_hash": recovery.digest(core)}


def _prepared(plan: dict[str, Any], plan_bytes: bytes) -> dict[str, Any]:
    return {
        "schema": PREPARED_SCHEMA,
        "status": "candidate_a_prepared",
        "plan_hash": plan["plan_hash"],
        "plan_file_sha256": recovery.digest(plan_bytes),
        **{key: plan[key] for key in (
            "target_state_sha256", "candidate_a_state_sha256",
            "source_archive_sha256", "sidecar_sha256",
            "target_write_status", "candidate_b_status", "rollback_status",
        )},
    }


def _prepare(
    paths: recovery.RecoveryPaths,
    bundle: recovery.RecoveryBundle,
    sidecar_bytes: bytes,
    candidate: CandidateA,
    plan: dict[str, Any],
) -> dict[str, Any]:
    directory = _directory(paths, plan["plan_hash"], True)
    payloads = {
        "source_archive.json": bundle.archive_bytes,
        "sidecar.json": sidecar_bytes,
        "candidate_a_state.json": candidate.state_bytes,
    }
    for name, field in ARTIFACTS.items():
        if recovery.digest(payloads[name]) != plan[field]:
            raise recovery.RecoveryBlocked("prepared_artifact_invalid")
        _write_once(directory / name, payloads[name])
    plan_bytes = recovery.json_bytes(plan, pretty=True)
    receipt = _prepared(plan, plan_bytes)
    _write_once(directory / "plan.json", plan_bytes)
    _write_once(
        directory / "prepared.json",
        recovery.json_bytes(receipt, pretty=True),
    )
    return receipt


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file() \
                or stat.S_IMODE(path.stat().st_mode) & 0o222:
            raise OSError("artifact path or mode invalid")
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise recovery.RecoveryBlocked("prepared_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise recovery.RecoveryBlocked("prepared_artifact_invalid")
    return value, raw


def _load(
    paths: recovery.RecoveryPaths, plan_hash: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    directory = _directory(paths, plan_hash, False)
    plan, plan_bytes = _read_json(directory / "plan.json")
    core = {key: value for key, value in plan.items() if key != "plan_hash"}
    target = plan.get("target_state_sha256")
    candidate = plan.get("candidate_a_state_sha256")
    semantics_valid = (
        plan.get("phase") == "candidate_a_prepared"
        and plan.get("target_write_status") == "forbidden_until_candidate_b"
        and plan.get("candidate_b_status") == plan.get("rollback_status")
        == "not_implemented"
        and plan.get("candidate_a_counts") == EXPECTED_COUNTS
        and _clean_accounting(plan.get("transition_accounting"))
        and recovery.SHA256.fullmatch(target or "") is not None
        and recovery.SHA256.fullmatch(candidate or "") is not None
        and target != candidate
    )
    if plan.get("schema") != PLAN_SCHEMA or plan.get("plan_hash") != plan_hash \
            or recovery.digest(core) != plan_hash \
            or plan_bytes != recovery.json_bytes(plan, pretty=True) \
            or not semantics_valid:
        raise recovery.RecoveryBlocked("prepared_plan_invalid")
    prepared, prepared_bytes = _read_json(directory / "prepared.json")
    if prepared != _prepared(plan, plan_bytes) \
            or prepared_bytes != recovery.json_bytes(prepared, pretty=True):
        raise recovery.RecoveryBlocked("prepared_receipt_invalid")
    artifacts = {}
    for name, field in ARTIFACTS.items():
        path = directory / name
        try:
            if path.is_symlink() or not path.is_file() \
                    or stat.S_IMODE(path.stat().st_mode) & 0o222:
                raise OSError("artifact path or mode invalid")
            raw = path.read_bytes()
        except OSError as exc:
            raise recovery.RecoveryBlocked("prepared_artifact_invalid") from exc
        if recovery.digest(raw) != plan[field]:
            raise recovery.RecoveryBlocked("prepared_artifact_invalid")
        artifacts[name] = raw
    return plan, prepared, artifacts


def _build_candidate_a_plan(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    sidecar_hash: str,
    observed_at: datetime,
    checkpoint_hash_reader=None,
) -> tuple[recovery.RecoveryBundle, bytes, CandidateA, dict[str, Any]]:
    target_hash = _target_hash(paths)
    bundle = recovery.build_recovery_bundle(
        paths, checkpoint_hash_reader=checkpoint_hash_reader
    )
    if bundle.safe_plan["inputs"]["standalone_state"] != target_hash:
        raise recovery.RecoveryBlocked("input_hash_changed")
    sidecar, sidecar_bytes = read_exact_sidecar(sidecar_path, sidecar_hash)
    protected = recovery.protected_manifest(paths)
    if recovery.digest(protected) \
            != bundle.safe_plan["protected_manifest_sha256"]:
        raise recovery.RecoveryBlocked("protected_state_changed")
    candidate = build_candidate_a(
        bundle, sidecar,
        expected_sidecar_sha256=sidecar_hash,
        observed_at=observed_at,
    )
    recovery.assert_inputs(paths, bundle)
    if _target_hash(paths) != target_hash:
        raise recovery.RecoveryBlocked("target_state_changed")
    if recovery.file_hash(sidecar_path) != sidecar_hash:
        raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
    if recovery.protected_manifest(paths) != protected:
        raise recovery.RecoveryBlocked("protected_state_changed")
    current = observed_at.astimezone(timezone.utc).replace(microsecond=0)
    plan = _plan(bundle, sidecar, sidecar_hash, candidate, protected, current)
    _checkpoints(plan, checkpoint_hash_reader)
    return bundle, sidecar_bytes, candidate, plan


def prepare_candidate_a(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    sidecar_hash: str,
    lock_paths: RecoveryLockPaths,
    *,
    observed_at: datetime,
    checkpoint_hash_reader=None,
) -> dict[str, Any]:
    with recovery_locks(lock_paths, sidecar_path):
        bundle, sidecar_bytes, candidate, plan = _build_candidate_a_plan(
            paths, sidecar_path, sidecar_hash, observed_at,
            checkpoint_hash_reader,
        )
        return _prepare(paths, bundle, sidecar_bytes, candidate, plan)


def verify_prepared_candidate_a(
    paths: recovery.RecoveryPaths,
    sidecar_path: Path,
    sidecar_hash: str,
    lock_paths: RecoveryLockPaths,
    *,
    plan_hash: str,
    checkpoint_hash_reader=None,
) -> dict[str, Any]:
    with recovery_locks(lock_paths, sidecar_path):
        plan, prepared, artifacts = _load(paths, plan_hash)
        observed_at = holder.parse_iso(plan.get("observed_at"))
        if observed_at is None or sidecar_hash != plan["sidecar_sha256"]:
            raise recovery.RecoveryBlocked("prepared_plan_invalid")
        if _target_hash(paths) != plan["target_state_sha256"]:
            raise recovery.RecoveryBlocked("target_state_changed")
        sources = {"config": paths.config, "holder_state": paths.holder_state,
                   "opening": paths.opening}
        if any(recovery.file_hash(path) != plan["input_hashes"].get(name)
               for name, path in sources.items()):
            raise recovery.RecoveryBlocked("input_hash_changed")
        if recovery.protected_manifest(paths) != plan["protected_manifest"]:
            raise recovery.RecoveryBlocked("protected_state_changed")
        bundle, sidecar_bytes, candidate, rebuilt = _build_candidate_a_plan(
            paths, sidecar_path, sidecar_hash, observed_at,
            checkpoint_hash_reader,
        )
        if rebuilt != plan \
                or bundle.archive_bytes != artifacts["source_archive.json"] \
                or sidecar_bytes != artifacts["sidecar.json"] \
                or candidate.state_bytes != artifacts["candidate_a_state.json"]:
            raise recovery.RecoveryBlocked("prepared_plan_invalid")
        return prepared
