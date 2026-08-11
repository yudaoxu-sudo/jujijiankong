#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROFILE = "binance_alpha_bsc.v1"
ADAPTER = "generic_alpha_watchers.v1"
BSC_USDT = "0x55d398326f99059ff775485246999027b3197955"
BSC_WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
BSC_QUOTE_TOKENS = frozenset({BSC_USDT, BSC_WBNB})
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
POOL_ID_RE = re.compile(r"^(?:|0x[0-9a-fA-F]{40}|0x[0-9a-fA-F]{64})$")
SUPPORTED_PROFILES = {PROFILE: ADAPTER}
RUNTIME_WATCHLIST_SNAPSHOT_DIR = Path("output/runtime_watchlist_cycles")
PROFILE_PRIORITY_PREFIXES = ("P0", "P1")
OPENING_REASON_CODES = frozenset(
    {
        "binance_alpha_listing_time",
        "binance_alpha_public_catalog_verified_listing",
        "listing_time",
        "币安 alpha 上线",
        "verified_prelaunch_pool",
    }
)
RESULT_KEYS = {
    "status",
    "profile",
    "adapter",
    "focused_symbol_count",
    "active_item_count",
    "holder_capacity",
    "issue_codes",
}
ISSUE_ORDER = (
    "watchlist_invalid",
    "monitoring_policy_invalid",
    "profile_unsupported",
    "adapter_unsupported",
    "focused_item_count_invalid",
    "focused_item_inactive",
    "active_scope_mismatch",
    "runtime_symbol_filter_invalid",
    "priority_invalid",
    "contract_count_invalid",
    "contract_chain_invalid",
    "contract_address_invalid",
    "contract_identity_duplicate",
    "opening_anchor_missing",
    "opening_anchor_invalid",
    "opening_anchor_ambiguous",
    "opening_anchor_conflict",
    "pool_shape_invalid",
    "pool_id_invalid",
    "pool_chain_invalid",
    "pool_quote_invalid",
    "holder_capacity_invalid",
    "holder_capacity_exceeded",
    "watchlist_unreadable",
)


def read_regular_file_once(path: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"watchlist path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(), metadata
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_materialized_watchlist(
    path: Path,
    *,
    expected_bytes: bytes,
    expected_hash: str,
) -> None:
    actual_bytes, metadata = read_regular_file_once(path)
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        raise OSError(f"materialized watchlist mode is not 0444: {path}")
    if (
        actual_bytes != expected_bytes
        or hashlib.sha256(actual_bytes).hexdigest() != expected_hash
    ):
        raise OSError(f"materialized watchlist content mismatch: {path}")


def materialize_watchlist_bytes(
    source_bytes: bytes,
    output_dir: Path = RUNTIME_WATCHLIST_SNAPSHOT_DIR,
) -> Path:
    content_hash = hashlib.sha256(source_bytes).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    directory_metadata = output_dir.lstat()
    if not stat.S_ISDIR(directory_metadata.st_mode):
        raise OSError(
            f"runtime watchlist snapshot path is not a directory: {output_dir}"
        )
    target_path = output_dir / f"{content_hash}.json"
    try:
        verify_materialized_watchlist(
            target_path,
            expected_bytes=source_bytes,
            expected_hash=content_hash,
        )
        return target_path
    except FileNotFoundError:
        pass

    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{content_hash}.",
        suffix=".tmp",
        dir=output_dir,
    )
    temporary_path = Path(temporary)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source_bytes)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target_path)
            linked = True
            fsync_directory(output_dir)
        except FileExistsError:
            pass
        verify_materialized_watchlist(
            target_path,
            expected_bytes=source_bytes,
            expected_hash=content_hash,
        )
        return target_path
    finally:
        temporary_path.unlink(missing_ok=True)
        if linked:
            fsync_directory(output_dir)


def materialize_watchlist(
    source_path: Path,
    output_dir: Path = RUNTIME_WATCHLIST_SNAPSHOT_DIR,
) -> Path:
    source_bytes, _source_metadata = read_regular_file_once(source_path)
    return materialize_watchlist_bytes(source_bytes, output_dir)


def same_path_name(left: Path, right: Path) -> bool:
    return os.path.abspath(os.fspath(left)) == os.path.abspath(os.fspath(right))


def decode_watchlist_bytes(payload: bytes, *, label: str) -> Any:
    try:
        return json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} Alpha watchlist is invalid JSON") from exc


def select_and_materialize_watchlist(
    *,
    runtime_path: Path,
    static_path: Path,
    max_age_seconds: int,
    configured_path: Path | None = None,
    output_dir: Path = RUNTIME_WATCHLIST_SNAPSHOT_DIR,
) -> Path:
    from scripts import binance_alpha_catalog_watch as catalog

    static_bytes, _static_metadata = read_regular_file_once(static_path)
    static_watchlist = decode_watchlist_bytes(static_bytes, label="curated")
    try:
        static_policy = catalog.normalized_monitoring_policy(static_watchlist)
    except ValueError as exc:
        raise ValueError("curated Alpha monitoring policy is invalid") from exc
    if (
        not static_policy
        or catalog.active_monitoring_symbols(static_watchlist)
        != set(static_policy["symbols"])
    ):
        raise ValueError("curated Alpha monitoring policy is invalid")

    candidate_path = configured_path if configured_path is not None else runtime_path
    if same_path_name(candidate_path, static_path):
        return materialize_watchlist_bytes(static_bytes, output_dir)

    try:
        candidate_bytes, candidate_metadata = read_regular_file_once(candidate_path)
        candidate_watchlist = decode_watchlist_bytes(
            candidate_bytes,
            label="configured" if configured_path is not None else "runtime",
        )
    except (OSError, ValueError):
        if configured_path is not None:
            raise
        return materialize_watchlist_bytes(static_bytes, output_dir)

    age_seconds = max(0, int(time.time() - candidate_metadata.st_mtime))
    candidate_valid = (
        max_age_seconds >= 1
        and age_seconds <= max_age_seconds
        and catalog.watchlist_policy_compatible(
            candidate_watchlist,
            static_watchlist,
        )
    )
    if candidate_valid:
        return materialize_watchlist_bytes(candidate_bytes, output_dir)
    if configured_path is not None:
        raise ValueError(
            "configured Alpha watchlist is stale or violates the curated policy"
        )
    return materialize_watchlist_bytes(static_bytes, output_dir)


def utc8_minute(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for shape in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, shape).replace(microsecond=0)
        except ValueError:
            continue
    return None


def configured_value(payload: dict[str, Any], item: dict[str, Any], key: str) -> str:
    aliases = (key, key.removeprefix("monitoring_"))
    for source in (item, payload):
        for alias in aliases:
            value = str(source.get(alias) or "").strip()
            if value:
                return value
    return ""


def holder_priority_prefixes() -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in os.environ.get(
            "ALPHA_HOLDER_PRIORITIES",
            "P0,P1",
        ).split(",")
        if part.strip()
    )


def opening_known_time_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = item.get("known_times", [])
    if not isinstance(raw_rows, list):
        return []
    return [
        row
        for row in raw_rows
        if isinstance(row, dict)
        and str(row.get("reason") or "").strip().lower()
        in OPENING_REASON_CODES
    ]


def opening_known_time_value(row: dict[str, Any]) -> Any:
    return row.get("time") or row.get("startedTime") or row.get("start_time") or ""


def add_opening_issues(item: dict[str, Any], issues: set[str]) -> None:
    raw_known = item.get("known_times", [])
    raw_pools = item.get("pool_ids", [])
    if not isinstance(raw_known, list) or not isinstance(raw_pools, list):
        issues.add("opening_anchor_invalid")
        if not isinstance(raw_pools, list):
            issues.add("pool_shape_invalid")
        return

    known_times: set[datetime] = set()
    pool_times: set[datetime] = set()
    invalid_anchor = False
    for row in opening_known_time_rows(item):
        parsed = utc8_minute(opening_known_time_value(row))
        if parsed is None:
            invalid_anchor = True
        else:
            known_times.add(parsed)
    for row in raw_pools:
        if not isinstance(row, dict):
            issues.add("pool_shape_invalid")
            invalid_anchor = True
            continue
        parsed = utc8_minute(row.get("start_time_utc8"))
        if parsed is None:
            invalid_anchor = True
        else:
            pool_times.add(parsed)

    if invalid_anchor:
        issues.add("opening_anchor_invalid")
    if len(known_times) > 1 or len(pool_times) > 1:
        issues.add("opening_anchor_ambiguous")
    if len(known_times) == 1 and len(pool_times) == 1 and known_times != pool_times:
        issues.add("opening_anchor_conflict")
    if not known_times and not pool_times and not invalid_anchor:
        issues.add("opening_anchor_missing")


def valid_pair(pair: Any, symbol: str) -> bool:
    parts = [part.strip().upper() for part in str(pair or "").split("/")]
    return len(parts) == 2 and set(parts) == {symbol, "USDT"}


def add_pool_issues(item: dict[str, Any], symbol: str, issues: set[str]) -> None:
    raw_pools = item.get("pool_ids", [])
    if not isinstance(raw_pools, list):
        issues.add("pool_shape_invalid")
        return
    for row in raw_pools:
        if not isinstance(row, dict):
            issues.add("pool_shape_invalid")
            continue
        if str(row.get("chain") or "").lower() != "bsc":
            issues.add("pool_chain_invalid")
        if (
            not isinstance(row.get("pool_id"), str)
            or POOL_ID_RE.fullmatch(row["pool_id"]) is None
        ):
            issues.add("pool_id_invalid")
        pair_present = bool(str(row.get("pair") or "").strip())
        quote_present = bool(str(row.get("quote_address") or "").strip())
        pair_ok = valid_pair(row.get("pair"), symbol) if pair_present else False
        quote_ok = (
            str(row.get("quote_address") or "").strip().lower() == BSC_USDT
            if quote_present
            else False
        )
        if (pair_present and not pair_ok) or (quote_present and not quote_ok):
            issues.add("pool_quote_invalid")
        elif not pair_ok and not quote_ok:
            issues.add("pool_quote_invalid")


def validate_watchlist(
    payload: Any,
    *,
    profile: str = PROFILE,
    holder_capacity: int = 8,
) -> dict[str, Any]:
    issues: set[str] = set()
    focused: list[str] = []
    active_rows: list[dict[str, Any]] = []

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        issues.add("watchlist_invalid")
        items: list[Any] = []
    else:
        items = payload["items"]
        if any(not isinstance(row, dict) for row in items):
            issues.add("watchlist_invalid")

    policy = payload.get("monitoring_policy") if isinstance(payload, dict) else None
    if not isinstance(policy, dict) or policy.get("mode") != "exclusive_symbols":
        issues.add("monitoring_policy_invalid")
    else:
        raw_symbols = policy.get("symbols")
        if not isinstance(raw_symbols, list):
            issues.add("monitoring_policy_invalid")
        else:
            normalized = [
                value.upper()
                for value in raw_symbols
                if isinstance(value, str)
                and value
                and value == value.strip()
            ]
            if (
                len(normalized) != len(raw_symbols)
                or any(not value for value in normalized)
                or len(set(normalized)) != len(normalized)
            ):
                issues.add("monitoring_policy_invalid")
            else:
                focused = normalized
            if not normalized:
                issues.add("monitoring_policy_invalid")

    if SUPPORTED_PROFILES.get(profile) != ADAPTER:
        issues.add("profile_unsupported")
    payload_profile = (
        configured_value(payload, {}, "monitoring_profile")
        if isinstance(payload, dict)
        else ""
    )
    payload_adapter = (
        configured_value(payload, {}, "monitoring_adapter")
        if isinstance(payload, dict)
        else ""
    )
    if payload_profile and payload_profile != PROFILE:
        issues.add("profile_unsupported")
    if payload_adapter and payload_adapter != ADAPTER:
        issues.add("adapter_unsupported")

    valid_items = [row for row in items if isinstance(row, dict)]
    active_rows = [row for row in valid_items if row.get("active_monitoring") is not False]
    active_symbols = [str(row.get("symbol") or "").upper() for row in active_rows]
    if len(active_rows) != len(focused) or set(active_symbols) != set(focused):
        issues.add("active_scope_mismatch")
    focused_active_symbols = set(focused).intersection(active_symbols)
    for variable in (
        "ALPHA_INTRADAY_REVIEW_SYMBOL",
        "ALPHA_PRICE_REVIEW_SYMBOL",
    ):
        review_symbol = os.environ.get(variable, "").upper()
        if review_symbol and review_symbol not in focused_active_symbols:
            issues.add("runtime_symbol_filter_invalid")

    identities: set[str] = set()
    holder_priorities = holder_priority_prefixes()
    for symbol in focused:
        symbol_rows = [
            row
            for row in valid_items
            if str(row.get("symbol") or "").upper() == symbol
        ]
        matching = [
            row
            for row in symbol_rows
            if row.get("active_monitoring") is not False
        ]
        if (
            len(symbol_rows) == 1
            and symbol_rows[0].get("active_monitoring") is not True
        ):
            issues.add("focused_item_inactive")
        if len(matching) != 1:
            issues.add("focused_item_count_invalid")
            continue
        item = matching[0]
        if item.get("active_monitoring") is not True:
            issues.add("focused_item_inactive")

        item_profile = configured_value({}, item, "monitoring_profile")
        item_adapter = configured_value({}, item, "monitoring_adapter")
        if item_profile and item_profile != PROFILE:
            issues.add("profile_unsupported")
        if item_adapter and item_adapter != ADAPTER:
            issues.add("adapter_unsupported")
        if any(
            field in item and item[field] is not False
            for field in (
                "project_watch_skip_generic",
                "opening_watch_skip_generic",
            )
        ):
            issues.add("adapter_unsupported")

        priority = str(item.get("priority") or "")
        if (
            not priority.startswith(PROFILE_PRIORITY_PREFIXES)
            or (
                holder_priorities
                and not priority.startswith(holder_priorities)
            )
        ):
            issues.add("priority_invalid")

        contracts = item.get("contracts")
        if (
            not isinstance(contracts, list)
            or len(contracts) != 1
            or not isinstance(contracts[0], dict)
        ):
            issues.add("contract_count_invalid")
        else:
            contract = contracts[0]
            chain = str(contract.get("chain") or "").lower()
            address = str(contract.get("address") or "").strip().lower()
            raw_item_chain = item.get("chain") if "chain" in item else "bsc"
            item_chain = (
                raw_item_chain.lower()
                if isinstance(raw_item_chain, str)
                else ""
            )
            if chain != "bsc" or item_chain != "bsc":
                issues.add("contract_chain_invalid")
            if (
                ADDRESS_RE.fullmatch(address) is None
                or address in BSC_QUOTE_TOKENS
            ):
                issues.add("contract_address_invalid")
            if chain == "bsc" and ADDRESS_RE.fullmatch(address) is not None:
                identity = f"{chain}:{address}"
                if identity in identities:
                    issues.add("contract_identity_duplicate")
                identities.add(identity)

        add_opening_issues(item, issues)
        add_pool_issues(item, symbol, issues)

    if (
        not isinstance(holder_capacity, int)
        or isinstance(holder_capacity, bool)
        or holder_capacity < 1
    ):
        issues.add("holder_capacity_invalid")
        safe_capacity = 0
    else:
        safe_capacity = holder_capacity
        if len(active_rows) > holder_capacity:
            issues.add("holder_capacity_exceeded")

    ordered_issues = [code for code in ISSUE_ORDER if code in issues]
    return {
        "status": "blocked" if ordered_issues else "pass",
        "profile": PROFILE,
        "adapter": ADAPTER,
        "focused_symbol_count": len(focused),
        "active_item_count": len(active_rows),
        "holder_capacity": safe_capacity,
        "issue_codes": ordered_issues,
    }


def parse_capacity(raw: Any) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generic Alpha onboarding readiness")
    parser.add_argument("--watchlist", required=True, type=Path)
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--holder-capacity")
    args = parser.parse_args()

    capacity = parse_capacity(
        args.holder_capacity
        if args.holder_capacity is not None
        else os.environ.get("ALPHA_HOLDER_MAX_PROJECTS", "8")
    )
    try:
        payload = json.loads(args.watchlist.read_text(encoding="utf-8"))
        result = validate_watchlist(
            payload,
            profile=str(args.profile),
            holder_capacity=capacity,
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        result = {
            "status": "blocked",
            "profile": PROFILE,
            "adapter": ADAPTER,
            "focused_symbol_count": 0,
            "active_item_count": 0,
            "holder_capacity": max(0, capacity),
            "issue_codes": ["watchlist_unreadable"],
        }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "pass" else 78


if __name__ == "__main__":
    raise SystemExit(main())
