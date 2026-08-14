#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder
import scripts.migrate_alpha_liquidity_seed as recovery

SCHEMA = "alpha_liquidity_recovery_enrichment.v1"
ARCHIVE_SCHEMA = "alpha_liquidity_recovery_source_archive.v1"
MAX_STEP_EVENTS = 32
MAX_STEP_SECONDS = 20.0
HEX_DATA = re.compile(r"0x[0-9a-f]*")
OPERATOR_FIELDS = ("liquidity_operator", "liquidity_operator_basis",
                   "liquidity_operator_confidence", "liquidity_operator_class")
CANDIDATE_TYPES = holder.LIQUIDITY_RECONCILIATION_REMOVAL_TYPES \
    | holder.LIQUIDITY_RECONCILIATION_SELL_TYPES | {"lp_add_observation"}

def _archive(bundle: recovery.RecoveryBundle) -> dict[str, Any]:
    try:
        raw = json.loads(bundle.archive_bytes)
    except (TypeError, json.JSONDecodeError) as exc:
        raise recovery.RecoveryBlocked("recovery_archive_invalid") from exc
    events = bundle.standalone_seed["reconciliation"]["deferred_events"]
    if not isinstance(raw, dict) \
            or raw.get("schema") != recovery.ARCHIVE_SCHEMA \
            or raw.get("standalone_seed") != bundle.standalone_seed \
            or raw.get("original_events") != events \
            or raw.get("original_event_sha256") != [recovery.digest(row) for row in events]:
        raise recovery.RecoveryBlocked("recovery_archive_invalid")
    return raw

def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    fields = ("protocol", "type", "pool", "tx", "block", "block_hash",
              "log_index", "lp_owner", "tick_lower", "tick_upper")
    return {key: event.get(key) for key in fields}

def _manifest(bundle: recovery.RecoveryBundle) -> list[dict[str, str]]:
    events = _archive(bundle)["original_events"]
    rows = [{"reconcile_id": holder.liquidity_reconciliation_id(event),
             "event_sha256": recovery.digest(event),
             "event_core_sha256": recovery.digest(_event_core(event))}
            for event in events]
    if len(rows) != len({row["reconcile_id"] for row in rows}):
        raise recovery.RecoveryBlocked("archive_event_manifest_invalid")
    return rows

def stable_archive_projection(bundle: recovery.RecoveryBundle) -> dict[str, Any]:
    """Project the migrator archive onto fields that holder drift cannot change."""
    archive = _archive(bundle)
    return {"schema": ARCHIVE_SCHEMA, "chain": "bsc", "token": recovery.DOS_TOKEN,
        "standalone_state_sha256": bundle.safe_plan["inputs"]["standalone_state"],
        "standalone_seed": archive["standalone_seed"],
        "event_manifest": _manifest(bundle)}

def _source(bundle: recovery.RecoveryBundle) -> dict[str, Any]:
    projection = stable_archive_projection(bundle)
    manifest = projection["event_manifest"]
    seed = bundle.standalone_seed
    return {"chain": "bsc", "token": recovery.DOS_TOKEN,
        "archive_sha256": recovery.digest(projection),
        "standalone_state_sha256": projection["standalone_state_sha256"],
        "standalone_seed_sha256": recovery.digest(seed),
        "scope_hash": seed["scope_hash"], "checkpoint_block": seed["latest_block"],
        "checkpoint_block_hash": holder.norm(seed["latest_block_hash"]),
        "event_count": len(manifest), "event_manifest_sha256": recovery.digest(manifest)}

def initialize_sidecar(bundle: recovery.RecoveryBundle) -> dict[str, Any]:
    source = _source(bundle)
    manifest = _manifest(bundle)
    return {"schema": SCHEMA, "job_id": recovery.digest(source), "source": source,
        "cursor": {"next_index": 0,
            "next_reconcile_id": manifest[0]["reconcile_id"] if manifest else "",
            "pass": 0},
        "entries": [{**row, "attempt_count": 0, "last_error_code": ""}
                    for row in manifest],
        "rpc_cache": {"blocks": {}, "transactions": {}, "codes": {}},
        "updated_at": ""}

def _block_key(event: dict[str, Any]) -> str:
    return f"bsc|{event['block']}|{holder.norm(event['block_hash'])}"

def _tx_key(event: dict[str, Any]) -> str:
    return f"bsc|{holder.norm(event['tx'])}|{holder.norm(event['block_hash'])}"

def _code_key(address: str, event: dict[str, Any]) -> str:
    return (
        f"bsc|{holder.norm(address)}|{event['block']}|"
        f"{holder.norm(event['block_hash'])}"
    )

def _production_operator_skip(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "")
    return str(event.get("protocol") or "") != "v3" \
        or event_type not in CANDIDATE_TYPES \
        or (
            event.get("historical_catchup") is True
            and event_type != "lp_add_observation"
        )

def _record(kind: str, core: dict[str, Any]) -> dict[str, Any]:
    return {**core, "receipt_sha256": recovery.digest({"kind": kind, "value": core})}

def _valid_block(event: dict[str, Any], row: Any) -> bool:
    core = {
        "number": event["block"], "hash": holder.norm(event["block_hash"]),
        "timestamp": row.get("timestamp") if isinstance(row, dict) else None}
    return isinstance(row, dict) and row == _record("block", core) \
        and type(row["timestamp"]) is int and row["timestamp"] > 0

def _valid_transaction(event: dict[str, Any], row: Any) -> bool:
    core = {"hash": holder.norm(event["tx"]),
            "from": row.get("from") if isinstance(row, dict) else None,
            "block": event["block"],
            "block_hash": holder.norm(event["block_hash"])}
    return isinstance(row, dict) and holder.is_address(row.get("from")) \
        and row == _record("transaction", core)

def _valid_code(address: str, event: dict[str, Any], row: Any) -> bool:
    core = {"chain": "bsc", "address": holder.norm(address),
            "block": event["block"],
            "block_hash": holder.norm(event["block_hash"]),
            "code": row.get("code") if isinstance(row, dict) else None}
    return isinstance(row, dict) and isinstance(row.get("code"), str) \
        and HEX_DATA.fullmatch(row["code"]) is not None \
        and row == _record("code", core)

def _raw_evidence_state(event: dict[str, Any], cache: dict[str, Any]) -> str:
    block = cache["blocks"].get(_block_key(event))
    if block is None:
        return "partial"
    if not _valid_block(event, block):
        return "invalid"
    if _production_operator_skip(event):
        return "ready"
    if str(event.get("protocol") or "") != "v3" \
            or str(event.get("type") or "") not in CANDIDATE_TYPES:
        return "invalid"
    owner = holder.norm(event.get("lp_owner"))
    owner_code = cache["codes"].get(_code_key(owner, event)) \
        if holder.is_address(owner) else None
    if holder.is_address(owner) and owner_code is None:
        return "partial"
    if owner_code is not None and not _valid_code(owner, event, owner_code):
        return "invalid"
    transaction = cache["transactions"].get(_tx_key(event))
    if transaction is None:
        return "partial"
    if not _valid_transaction(event, transaction):
        return "invalid"
    sender_code = cache["codes"].get(_code_key(transaction["from"], event))
    if sender_code is None:
        return "partial"
    return "ready" if _valid_code(
        transaction["from"], event, sender_code) else "invalid"

def entry_raw_ready(entry: Any, event: dict[str, Any], cache: dict[str, Any]) -> bool:
    return isinstance(entry, dict) and _raw_evidence_state(event, cache) == "ready"

def validate_sidecar(
    bundle: recovery.RecoveryBundle, sidecar: Any, *, require_raw_ready: bool = False
) -> dict[str, int]:
    manifest = _manifest(bundle)
    if (
        not isinstance(sidecar, dict)
        or sidecar.get("schema") != SCHEMA
        or sidecar.get("source") != _source(bundle)
        or sidecar.get("job_id") != recovery.digest(sidecar.get("source"))
        or not isinstance(sidecar.get("entries"), list)
        or len(sidecar["entries"]) != len(manifest)
        or not isinstance(sidecar.get("rpc_cache"), dict)
        or set(sidecar["rpc_cache"]) != {"blocks", "transactions", "codes"}
        or any(not isinstance(value, dict) for value in sidecar["rpc_cache"].values())
    ):
        raise recovery.RecoveryBlocked("sidecar_source_mismatch")
    cursor = sidecar.get("cursor")
    if not isinstance(cursor, dict) or type(cursor.get("next_index")) is not int \
            or not 0 <= cursor["next_index"] < max(1, len(manifest)) \
            or type(cursor.get("pass")) is not int or cursor["pass"] < 0 \
            or cursor.get("next_reconcile_id") != manifest[
                cursor["next_index"]]["reconcile_id"]:
        raise recovery.RecoveryBlocked("sidecar_cursor_invalid")
    raw_ready = 0
    events = _archive(bundle)["original_events"]
    for expected, event, entry in zip(manifest, events, sidecar["entries"]):
        if (
            not isinstance(entry, dict)
            or set(entry) != set(expected) | {"attempt_count", "last_error_code"}
            or any(entry.get(key) != value for key, value in expected.items())
            or type(entry.get("attempt_count")) is not int
            or entry["attempt_count"] < 0
            or not isinstance(entry.get("last_error_code"), str)
        ):
            raise recovery.RecoveryBlocked("sidecar_event_manifest_invalid")
        evidence_state = _raw_evidence_state(event, sidecar["rpc_cache"])
        if evidence_state == "invalid":
            raise recovery.RecoveryBlocked("sidecar_cache_invalid")
        raw_ready += int(evidence_state == "ready")
    if require_raw_ready and raw_ready != len(events):
        raise recovery.RecoveryBlocked("sidecar_incomplete")
    return {"raw_ready_count": raw_ready, "event_count": len(events)}

def atomic_cas_write(path: Path, payload: Any, expected_hash: str | None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    actual = recovery.file_hash(path) if path.is_file() else None
    if actual != expected_hash:
        raise recovery.RecoveryBlocked("sidecar_cas_changed")
    data = recovery.json_bytes(payload, pretty=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return recovery.digest(data)

@contextmanager
def _sidecar_lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

@contextmanager
def _patched_holder_rpc(adapter: Callable) -> Iterator[None]:
    previous = holder.holder_rpc_call
    holder.holder_rpc_call = adapter
    try:
        yield
    finally:
        holder.holder_rpc_call = previous

@contextmanager
def _patched_holder_labels(labels: dict[str, Any]) -> Iterator[None]:
    previous = holder.global_address_labels
    holder.global_address_labels = lambda _chain: labels
    try:
        yield
    finally:
        holder.global_address_labels = previous

class _EventRpc:
    def __init__(self, event: dict[str, Any], cache: dict[str, Any], live: Callable,
                 deadline: float, monotonic: Callable[[], float]) -> None:
        self.event, self.cache, self.live = event, cache, live
        self.deadline, self.monotonic = deadline, monotonic
        self.error_code = ""

    def _call(self, chain: str, method: str, params: list[Any]) -> Any:
        if self.monotonic() >= self.deadline:
            self.error_code = "deadline_exceeded"
            raise TimeoutError("deadline")
        try:
            return self.live(chain, method, params)
        except Exception:
            self.error_code = "rpc_unavailable"
            raise

    def __call__(self, chain: str, method: str, params: list[Any]) -> Any:
        event = self.event
        if chain != "bsc":
            raise ValueError("chain")
        if method == "eth_getBlockByNumber":
            key = _block_key(event)
            row = self.cache["blocks"].get(key)
            if row is None:
                raw = self._call(chain, method, params)
                try:
                    candidate = _record("block", {
                        "number": int(str(raw["number"]), 16),
                        "hash": holder.norm(raw["hash"]),
                        "timestamp": int(str(raw["timestamp"]), 16)})
                except (KeyError, TypeError, ValueError):
                    candidate = {}
                if not _valid_block(event, candidate):
                    self.error_code = "event_block_not_canonical"
                    raise ValueError("block")
                self.cache["blocks"][key] = row = candidate
            if int(str(params[0]), 16) != event["block"] or not _valid_block(event, row):
                self.error_code = "event_block_not_canonical"
                raise ValueError("block")
            return {"number": hex(row["number"]), "hash": row["hash"],
                    "timestamp": hex(row["timestamp"])}
        if method == "eth_getTransactionByHash":
            key = _tx_key(event)
            row = self.cache["transactions"].get(key)
            if row is None:
                raw = self._call(chain, method, params)
                try:
                    candidate = _record("transaction", {
                        "hash": holder.norm(raw["hash"]),
                        "from": holder.norm(raw["from"]),
                        "block": int(str(raw["blockNumber"]), 16),
                        "block_hash": holder.norm(raw["blockHash"])})
                except (KeyError, TypeError, ValueError):
                    candidate = {}
                if not _valid_transaction(event, candidate):
                    self.error_code = "transaction_not_canonical"
                    raise ValueError("transaction")
                self.cache["transactions"][key] = row = candidate
            if holder.norm(params[0]) != holder.norm(event["tx"]) \
                    or not _valid_transaction(event, row):
                self.error_code = "transaction_not_canonical"
                raise ValueError("transaction")
            return {"hash": row["hash"], "from": row["from"],
                    "blockNumber": hex(row["block"]), "blockHash": row["block_hash"]}
        if method == "eth_getCode":
            address = holder.norm(params[0])
            key = _code_key(address, event)
            row = self.cache["codes"].get(key)
            if row is None:
                code = holder.norm(self._call(chain, method, params))
                candidate = _record("code", {
                    "chain": chain, "address": address, "block": event["block"],
                    "block_hash": holder.norm(event["block_hash"]), "code": code})
                if not _valid_code(address, event, candidate):
                    self.error_code = "code_response_invalid"
                    raise ValueError("code")
                self.cache["codes"][key] = row = candidate
            if int(str(params[1]), 16) != event["block"] \
                    or not _valid_code(address, event, row):
                self.error_code = "code_response_invalid"
                raise ValueError("code")
            return row["code"]
        raise ValueError("rpc_method")

def _prepare_entry(event: dict[str, Any], entry: dict[str, Any], cache: dict[str, Any],
                   rpc_call: Callable, deadline: float,
                   monotonic: Callable[[], float]) -> None:
    adapter = _EventRpc(event, cache, rpc_call, deadline, monotonic)
    try:
        adapter("bsc", "eth_getBlockByNumber", [hex(event["block"]), False])
        if not _production_operator_skip(event):
            if str(event.get("protocol") or "") != "v3" \
                    or str(event.get("type") or "") not in CANDIDATE_TYPES:
                raise ValueError("unsupported event")
            owner = holder.norm(event.get("lp_owner"))
            if holder.is_address(owner):
                adapter("bsc", "eth_getCode", [owner, hex(event["block"])])
            transaction = adapter(
                "bsc", "eth_getTransactionByHash", [holder.norm(event["tx"])])
            adapter("bsc", "eth_getCode", [transaction["from"], hex(event["block"])])
    except Exception:
        pass
    entry["attempt_count"] += 1
    entry["last_error_code"] = "" if entry_raw_ready(entry, event, cache) else (
        adapter.error_code or "raw_evidence_incomplete")

def run_step(paths: recovery.RecoveryPaths, sidecar_path: Path, job_id: str = "", *,
             expected_sidecar_sha256: str = "",
             limit: int = MAX_STEP_EVENTS, budget_seconds: float = MAX_STEP_SECONDS,
             rpc_call: Callable = holder.holder_rpc_call,
             checkpoint_hash_reader=None, monotonic: Callable[[], float] = time.monotonic
             ) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= MAX_STEP_EVENTS:
        raise recovery.RecoveryBlocked("sidecar_step_limit_invalid")
    if not 0 < float(budget_seconds) <= MAX_STEP_SECONDS:
        raise recovery.RecoveryBlocked("sidecar_step_budget_invalid")
    with _sidecar_lock(sidecar_path):
        bundle = recovery.build_recovery_bundle(
            paths, checkpoint_hash_reader=checkpoint_hash_reader)
        if sidecar_path.is_file():
            if not recovery.SHA256.fullmatch(expected_sidecar_sha256 or ""):
                raise recovery.RecoveryBlocked("sidecar_hash_required")
            raw_sidecar = sidecar_path.read_bytes()
            expected_hash = recovery.digest(raw_sidecar)
            if expected_hash != expected_sidecar_sha256:
                raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
            sidecar = json.loads(raw_sidecar)
        else:
            if expected_sidecar_sha256:
                raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
            expected_hash = None
            sidecar = initialize_sidecar(bundle)
        if job_id and sidecar.get("job_id") != job_id:
            raise recovery.RecoveryBlocked("sidecar_job_mismatch")
        validate_sidecar(bundle, sidecar)
        protected = recovery.protected_manifest(paths)
        events = _archive(bundle)["original_events"]
        cursor, attempted, scanned = sidecar["cursor"], 0, 0
        deadline = monotonic() + float(budget_seconds)
        previous_deadline = holder.HOLDER_DEADLINE_AT
        holder.HOLDER_DEADLINE_AT = min(previous_deadline, deadline) \
            if previous_deadline is not None else deadline
        try:
            while attempted < limit and scanned < len(events) \
                    and monotonic() < deadline:
                index = cursor["next_index"]
                entry = sidecar["entries"][index]
                if not entry_raw_ready(entry, events[index], sidecar["rpc_cache"]):
                    _prepare_entry(events[index], entry, sidecar["rpc_cache"],
                                   rpc_call, deadline, monotonic)
                    attempted += 1
                index += 1
                if index == len(events):
                    index = 0
                    cursor["pass"] += 1
                cursor["next_index"] = index
                cursor["next_reconcile_id"] = sidecar["entries"][index]["reconcile_id"]
                scanned += 1
        finally:
            holder.HOLDER_DEADLINE_AT = previous_deadline
        sidecar["updated_at"] = holder.now_iso()
        summary = validate_sidecar(bundle, sidecar)
        recovery.assert_inputs(paths, bundle)
        if recovery.protected_manifest(paths) != protected:
            raise recovery.RecoveryBlocked("protected_state_changed")
        sidecar_sha = atomic_cas_write(sidecar_path, sidecar, expected_hash)
        return {"schema": SCHEMA, "status": "raw_evidence_ready"
                if summary["raw_ready_count"] == summary["event_count"] else "partial",
                "job_id": sidecar["job_id"],
                **summary, "attempted_count": attempted,
                "deadline_reached": monotonic() >= deadline,
                "sidecar_sha256": sidecar_sha}

class _GroupCacheRpc:
    def __init__(self, events: list[dict[str, Any]], cache: dict[str, Any]) -> None:
        self.events, self.cache = events, cache
        self.by_tx = {holder.norm(event["tx"]): event for event in events}

    def __call__(self, chain: str, method: str, params: list[Any]) -> Any:
        if chain != "bsc":
            raise ValueError("chain")
        event = self.events[0]
        if method == "eth_getBlockByNumber":
            row = self.cache["blocks"].get(_block_key(event))
            if int(str(params[0]), 16) != event["block"] or not _valid_block(event, row):
                raise ValueError("block")
            return {"number": hex(row["number"]), "hash": row["hash"],
                    "timestamp": hex(row["timestamp"])}
        if method == "eth_getTransactionByHash":
            requested = holder.norm(params[0])
            source = self.by_tx.get(requested)
            row = self.cache["transactions"].get(_tx_key(source)) if source else None
            if source is None or not _valid_transaction(source, row):
                raise ValueError("transaction")
            return {"hash": row["hash"], "from": row["from"],
                    "blockNumber": hex(row["block"]), "blockHash": row["block_hash"]}
        if method == "eth_getCode":
            address = holder.norm(params[0])
            row = self.cache["codes"].get(_code_key(address, event))
            if int(str(params[1]), 16) != event["block"] \
                    or not _valid_code(address, event, row):
                raise ValueError("code")
            return row["code"]
        raise ValueError("rpc method")

def materialize_ready_events(
    bundle: recovery.RecoveryBundle,
    sidecar: dict[str, Any],
    *,
    expected_sidecar_sha256: str,
) -> list[dict[str, Any]]:
    actual_sidecar_sha256 = recovery.digest(recovery.json_bytes(sidecar, pretty=True))
    if not recovery.SHA256.fullmatch(expected_sidecar_sha256 or "") \
            or actual_sidecar_sha256 != expected_sidecar_sha256:
        raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
    validate_sidecar(bundle, sidecar, require_raw_ready=True)
    originals = _archive(bundle)["original_events"]
    output: list[dict[str, Any] | None] = [None] * len(originals)
    groups: dict[tuple[int, str], list[int]] = {}
    for index, event in enumerate(originals):
        groups.setdefault((event["block"], holder.norm(event["block_hash"])), []).append(index)
    labels = holder.global_address_labels("bsc")
    with _patched_holder_labels(labels):
        for indices in groups.values():
            events = [originals[index] for index in indices]
            with _patched_holder_rpc(_GroupCacheRpc(events, sidecar["rpc_cache"])):
                enriched, timestamp_errors = holder.attach_canonical_liquidity_timestamps(
                    "bsc", events)
                enriched, operator_errors = holder.annotate_liquidity_event_operators(
                    "bsc", enriched)
            if timestamp_errors or operator_errors:
                raise recovery.RecoveryBlocked("sidecar_materialize_incomplete")
            for index, event in zip(indices, enriched):
                if not _production_operator_skip(event) and (
                        not holder.is_address(event.get("liquidity_operator"))
                        or event.get("liquidity_operator_basis")
                        not in holder.LIQUIDITY_RELIABLE_OPERATOR_BASES):
                    raise recovery.RecoveryBlocked("sidecar_materialize_incomplete")
                output[index] = event
    if any(event is None for event in output):
        raise recovery.RecoveryBlocked("sidecar_materialize_incomplete")
    return [copy.deepcopy(event) for event in output if event is not None]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("step", "status"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--expected-sidecar-sha256", default="")
    parser.add_argument("--limit", type=int, default=MAX_STEP_EVENTS)
    parser.add_argument("--budget-seconds", type=float, default=MAX_STEP_SECONDS)
    args = parser.parse_args(argv)
    path = args.sidecar or args.root / "output/alpha_liquidity_recovery_enrichment/sidecar.json"
    try:
        if args.action == "step":
            result = run_step(recovery.RecoveryPaths.for_root(args.root), path,
                              args.job_id,
                              expected_sidecar_sha256=args.expected_sidecar_sha256,
                              limit=args.limit,
                              budget_seconds=args.budget_seconds)
        else:
            bundle = recovery.build_recovery_bundle(recovery.RecoveryPaths.for_root(args.root))
            raw_sidecar = path.read_bytes()
            if not recovery.SHA256.fullmatch(args.expected_sidecar_sha256 or ""):
                raise recovery.RecoveryBlocked("sidecar_hash_required")
            if recovery.digest(raw_sidecar) != args.expected_sidecar_sha256:
                raise recovery.RecoveryBlocked("sidecar_hash_mismatch")
            sidecar = json.loads(raw_sidecar)
            summary = validate_sidecar(bundle, sidecar)
            result = {"schema": SCHEMA, "status": "raw_evidence_ready"
                      if summary["raw_ready_count"] == summary["event_count"]
                      else "partial",
                      "job_id": sidecar["job_id"], **summary}
    except (OSError, json.JSONDecodeError, recovery.RecoveryBlocked) as exc:
        code = exc.code if isinstance(exc, recovery.RecoveryBlocked) else "sidecar_unavailable"
        print(json.dumps({"schema": SCHEMA, "status": "blocked", "error_code": code},
                         sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
