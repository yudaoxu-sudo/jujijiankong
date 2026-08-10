#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRELAUNCH_LOOKAHEAD_HOURS = 48
DEFAULT_INTRADAY_CORE_HOURS = 72
LIQUIDITY_RETENTION_STATE_SCHEMA_VERSION = 2
# Historical prelaunch receipt enforcement first became a runtime-health
# invariant in commit 4bf8d53. Projects both discovered and opened before this
# boundary cannot acquire a persisted delivery receipt retroactively.
PRELAUNCH_RECEIPT_POLICY_VERSION = "prelaunch_receipt_v1"
PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT = datetime(
    2026,
    7,
    30,
    7,
    36,
    39,
    tzinfo=timezone.utc,
)
LEGACY_PRELAUNCH_DELIVERY_UNVERIFIED_IDENTITIES = {
    (
        "bsc",
        "0x277add739c6e0477616948357af9e79fe1ec9b80",
        "2026-07-27T10:00:00+00:00",
    ),
}

CRITICAL_OUTPUTS = (
    ("binance_alpha_catalog", "output/binance_alpha_catalog_watch/latest.json"),
    ("wallet_monitor", "output/monitoring/latest_snapshot.json"),
    ("alpha_project", "output/alpha_project_watch/latest.json"),
    ("alpha_prelaunch", "output/alpha_prelaunch_watch/latest.json"),
    ("alpha_opening", "output/alpha_opening_block_watch/latest.json"),
    ("opening_funders", "output/opening_cohort_funders/latest.json"),
    ("alpha_intraday", "output/alpha_intraday_flow_watch/latest.json"),
    ("perp_oi_funding", "output/perp_oi_funding_watch/latest.json"),
    ("alpha_price", "output/alpha_price_momentum_watch/latest.json"),
    ("alpha_holders", "output/alpha_holder_concentration_watch/latest.json"),
    (
        "alpha_liquidity",
        "output/alpha_liquidity_retention_watch/latest.json",
    ),
    ("surf_aux", "output/surf_aux_market_watch/latest.json"),
    ("telegram_bot", "output/telegram_signals/state.json"),
    ("telegram_user", "output/telegram_user_signals/state.json"),
    ("prediction_markets", "output/prediction_markets/latest_prediction_markets.json"),
    ("external_aux", "output/external_aux_sources/latest.json"),
    ("position_cost", "output/position_cost_watch/latest.json"),
    ("verification", "output/sniper_engine/verification_report.md"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_local_env(root: Path) -> None:
    path = root / ".env.local"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_failure_file(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw_line.split("\t", 2)
        if len(parts) != 3:
            continue
        status_text, timeout_text, command = parts
        try:
            status = int(status_text)
        except ValueError:
            status = -1
        rows.append(
            {
                "exit_status": status,
                "timeout_seconds": int(timeout_text) if timeout_text.isdigit() else 0,
                "timed_out": status == 124,
                "command": command[:500],
            }
        )
    return rows


def failed_step_detail(row: dict[str, Any]) -> str:
    command = str(row.get("command") or "")
    timeout_seconds = int(row.get("timeout_seconds") or 0)
    if row.get("timed_out"):
        return f"步骤超时 {timeout_seconds}s · {command}"
    timeout_limit = f" · 超时上限 {timeout_seconds}s" if timeout_seconds else ""
    return f"步骤失败 exit={row.get('exit_status')}{timeout_limit} · {command}"


def issue(kind: str, name: str, detail: str, fingerprint: str | None = None) -> dict[str, str]:
    return {
        "kind": kind,
        "name": name,
        "detail": detail,
        "fingerprint": fingerprint or f"{kind}:{name}",
    }


def latest_daily_report(root: Path) -> Path | None:
    reports = sorted((root / "reports").glob("*_alpha_sniper_daily.md"))
    return reports[-1] if reports else None


def output_freshness_timestamp(name: str, path: Path) -> float:
    if name != "alpha_opening":
        return path.stat().st_mtime
    snapshot = read_json(path, {})
    rebuild = snapshot.get("direct_sell_evidence_rebuild") or {}
    if rebuild.get("applied") is not True:
        return path.stat().st_mtime
    source_time = parse_time(rebuild.get("source_generated_at"))
    return source_time.timestamp() if source_time is not None else 0.0


def output_freshness(root: Path, max_age_seconds: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    current = time.time()
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    targets: list[tuple[str, Path | None]] = [(name, root / rel) for name, rel in CRITICAL_OUTPUTS]
    targets.append(("daily_report", latest_daily_report(root)))
    for name, path in targets:
        if name == "telegram_bot" and os.environ.get("DISABLE_TELEGRAM", "0") == "1":
            rows.append(
                {
                    "name": name,
                    "path": str(path or ""),
                    "exists": bool(path and path.exists()),
                    "age_seconds": None,
                    "required": False,
                    "reason": "DISABLE_TELEGRAM=1",
                }
            )
            continue
        if path is None or not path.exists():
            rows.append({"name": name, "path": str(path or ""), "exists": False, "age_seconds": None, "required": True})
            issues.append(issue("missing_output", name, f"missing critical output: {name}"))
            continue
        age_seconds = max(
            0,
            int(current - output_freshness_timestamp(name, path)),
        )
        rows.append({"name": name, "path": str(path), "exists": True, "age_seconds": age_seconds, "required": True})
        if age_seconds > max_age_seconds:
            issues.append(
                issue(
                    "stale_output",
                    name,
                    f"{name} is {age_seconds}s old; limit is {max_age_seconds}s",
                )
            )
    return rows, issues


def verification_issues(root: Path) -> list[dict[str, str]]:
    path = root / "output" / "sniper_engine" / "verification_report.md"
    if not path.exists():
        return []
    fail_rows = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if "| FAIL |" in line]
    if not fail_rows:
        return []
    return [
        issue(
            "verification_failed",
            "verification_report",
            f"verification report contains {len(fail_rows)} FAIL row(s)",
            f"verification_failed:{len(fail_rows)}",
        )
    ]


def snapshot_rows(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, {})
    rows = payload.get("projects")
    if not isinstance(rows, list):
        rows = payload.get("events")
    if not isinstance(rows, list):
        rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def snapshot_symbols(path: Path) -> set[str]:
    return {
        str(row.get("symbol") or "").upper()
        for row in snapshot_rows(path)
        if row.get("symbol")
    }


def snapshot_symbol_rows(path: Path, symbol: str) -> list[dict[str, Any]]:
    return [
        row
        for row in snapshot_rows(path)
        if str(row.get("symbol") or "").upper() == symbol.upper()
    ]


def row_contract_identities(
    row: dict[str, Any],
    output_name: str,
) -> set[tuple[str, str]]:
    if output_name == "project":
        return {
            (
                str(contract.get("chain") or row.get("chain") or "").lower(),
                str(contract.get("address")).lower(),
            )
            for contract in row.get("contracts") or []
            if isinstance(contract, dict) and contract.get("address")
        }
    if output_name in {"opening", "intraday"}:
        address = str((row.get("token") or {}).get("address") or "").lower()
        chain = str(row.get("chain") or "bsc").lower()
        return {(chain, address)} if address else set()
    if output_name in {"prelaunch", "price"}:
        address = str(row.get("contract") or "").lower()
        chain = str(row.get("chain") or "bsc").lower()
        return {(chain, address)} if address else set()
    if output_name == "catalog":
        address = str(row.get("contract") or "").lower()
        chain = str(row.get("chain") or "bsc").lower()
        return {(chain, address)} if address else set()
    if output_name in {"holder", "liquidity"}:
        address = str(row.get("address") or "").lower()
        chain = str(row.get("chain") or "").lower()
        return {(chain, address)} if address else set()
    return set()


def row_contract_addresses(row: dict[str, Any], output_name: str) -> set[str]:
    return {
        address
        for _, address in row_contract_identities(row, output_name)
        if address
    }


def output_row_coverage_issue(
    output_name: str,
    row: dict[str, Any],
    target_contract: str = "",
) -> str:
    if row.get("error"):
        return f"{output_name} scan has errors"
    if output_name == "prelaunch" and row.get("event_kind") != "launch_window":
        return "prelaunch event kind invalid"
    if output_name == "project":
        if row.get("coverage_complete") is not True:
            return "project coverage incomplete"
        raw_contracts = row.get("contracts")
        if not isinstance(raw_contracts, list) or any(
            not isinstance(item, dict) for item in raw_contracts
        ):
            return "project contract coverage metadata invalid"
        contracts = list(raw_contracts)
        if target_contract:
            contracts = [
                item
                for item in contracts
                if str(item.get("address") or "").lower() == target_contract.lower()
            ]
        if not contracts:
            return "project contract missing"
        if any(item.get("coverage_complete") is not True for item in contracts):
            return "project contract coverage incomplete"
        if any(
            item.get("error") or int(item.get("log_error_count") or 0)
            for item in contracts
        ):
            return "project contract scan has errors"
        for item in contracts:
            try:
                requested = int(item["requested_from_block"])
                target = int(item["target_latest_block"])
                covered = int(item["covered_through_block"])
                next_from = int(item["next_from_block"])
                latest = int(item["latest_block"])
                decimals = int(item["decimals"])
                watch_address_count = int(item["watch_address_count"])
                balance_target_count = int(item["balance_target_count"])
                total_supply = Decimal(str(item["total_supply"]))
            except (InvalidOperation, KeyError, TypeError, ValueError):
                return "project contract coverage metadata invalid"
            target_hash = str(
                item.get("target_latest_block_hash") or ""
            ).lower()
            balances = item.get("balances")
            watch_addresses = item.get("watch_addresses")
            if (
                requested < 0
                or requested > target + 1
                or covered != target
                or latest != target
                or next_from != target + 1
                or item.get("transfer_coverage_complete") is not True
                or item.get("scan_status") != "complete"
                or not 0 <= decimals <= 36
                or total_supply < 0
                or not isinstance(watch_addresses, list)
                or any(
                    not isinstance(watch, dict)
                    or not str(watch.get("address") or "")
                    for watch in watch_addresses
                )
                or watch_address_count != len(watch_addresses)
                or not isinstance(balances, list)
                or any(
                    not isinstance(balance, dict) or balance.get("error")
                    for balance in balances
                )
                or len(target_hash) != 66
                or not target_hash.startswith("0x")
                or any(
                    char not in "0123456789abcdef"
                    for char in target_hash[2:]
                )
                or int(target_hash, 16) == 0
            ):
                return "project contract coverage metadata invalid"
            actual_balance_keys = {
                (
                    str(balance.get("address") or "").lower(),
                    str(
                        balance.get("balance_token_address") or ""
                    ).lower(),
                )
                for balance in balances
            }
            primary_balance_keys = {
                (
                    str(watch.get("address") or "").lower(),
                    str(item.get("address") or "").lower(),
                )
                for watch in watch_addresses
            }
            if (
                balance_target_count != len(balances)
                or len(actual_balance_keys) != len(balances)
                or not primary_balance_keys.issubset(actual_balance_keys)
            ):
                return "project contract coverage metadata invalid"
            for balance in balances:
                try:
                    current_balance = Decimal(str(balance["balance"]))
                except (InvalidOperation, KeyError, TypeError, ValueError):
                    return "project contract coverage metadata invalid"
                if current_balance < 0:
                    return "project contract coverage metadata invalid"
        states = {
            str(item.get("operator_attribution_state") or "")
            for item in contracts
        }
        if "contract_error" in states:
            return "project operator attribution contract error"
    elif output_name == "opening":
        if row.get("status") == "opened":
            if row.get("opening_cohort_coverage_complete") is not True:
                return "opening cohort transfer coverage incomplete"
            if row.get("opening_buyer_scope_complete") is not True:
                return "opening buyer address scope incomplete"
            if row.get("opening_liquidity_coverage_complete") is not True:
                return "opening liquidity flow coverage incomplete"
            if (
                row.get("cache_identity_status")
                == "metadata_conflict_unresolved"
            ):
                return (
                    "opening stable identity metadata conflict="
                    + str(
                        row.get("cache_identity_conflict")
                        or "unknown"
                    )
                )
            if row.get("refresh_status") == "partial_opening_deadline":
                return "opening evidence deadline exceeded before a usable snapshot"
            traces = [
                item.get("buyer_trace") or {}
                for item in row.get("rows", [])
                if isinstance(item, dict)
            ]
            if any(trace.get("status") == "trace_failed" for trace in traces):
                return "opening buyer trace failed"
        elif row.get("status") not in {"waiting", "opened"}:
            return f"opening status={row.get('status', 'missing')}"
    elif output_name == "intraday":
        if row.get("status") != "scanned":
            return f"intraday status={row.get('status', 'missing')}"
        coverage = row.get("transfer_coverage") or {}
        if coverage.get("state") != "requested_window_complete" or coverage.get("complete") is not True:
            return f"intraday transfer coverage={coverage.get('state', 'missing')}"
        analysis = row.get("analysis") or {}
        if analysis.get("scan_limited"):
            return "intraday receipt coverage limited"
    elif output_name == "price":
        analysis = row.get("analysis") or {}
        if analysis.get("direction") == "数据缺口":
            return "price layer data gap"
    elif output_name == "holder":
        if int(row.get("log_error_count") or 0) or row.get("truncated"):
            return "holder scan incomplete"
        catchup = row.get("incremental_catchup")
        if not isinstance(catchup, dict):
            return "holder incremental catch-up metadata missing"
        if catchup.get("applicable") is False:
            try:
                target_latest = int(row.get("target_latest_block") or 0)
                scan_to = int(row.get("scan_to_block") or 0)
            except (TypeError, ValueError):
                return "holder incremental catch-up metadata invalid"
            if target_latest > scan_to and (
                row.get("holder_baseline_status")
                != "bounded_bootstrap_unreliable"
                or row.get("holder_scan_status")
                != "skipped_unreliable_baseline"
                or catchup.get("reason")
                != "holder_baseline_unavailable_retention_only"
            ):
                return "holder incremental catch-up metadata invalid"
        elif catchup.get("applicable") is not True:
            return "holder incremental catch-up metadata invalid"
        elif (
            not isinstance(catchup.get("active"), bool)
            or not isinstance(
                catchup.get("complete_selected_window"),
                bool,
            )
            or not isinstance(
                catchup.get("complete_requested_window"),
                bool,
            )
        ):
            return "holder incremental catch-up metadata invalid"
        else:
            try:
                requested_to = int(catchup["requested_to_block"])
                selected_to = int(catchup["selected_to_block"])
                target_latest = int(row["target_latest_block"])
                scan_to = int(row["scan_to_block"])
            except (KeyError, TypeError, ValueError):
                return "holder incremental catch-up metadata invalid"
            if (
                min(requested_to, selected_to, target_latest, scan_to)
                < 0
                or requested_to != target_latest
                or selected_to != scan_to
                or catchup.get("active")
                is not (selected_to < requested_to)
                or catchup.get("complete_requested_window")
                is not (
                    catchup.get("complete_selected_window") is True
                    and selected_to == requested_to
                )
            ):
                return "holder incremental catch-up metadata invalid"
        if catchup.get("applicable") is True and (
            catchup.get("complete_selected_window") is not True
        ):
            return "holder incremental catch-up selected window incomplete"
        if catchup.get("applicable") is True and (
            catchup.get("active") is True
        ):
            if catchup.get("complete_requested_window") is True:
                return "holder incremental catch-up metadata invalid"
            return "holder incremental catch-up pending"
        if catchup.get("applicable") is True and (
            catchup.get("complete_requested_window") is not True
        ):
            return "holder incremental catch-up metadata invalid"
        if (
            row.get("holder_baseline_status")
            == "bounded_bootstrap_unreliable"
            and (
                row.get("complete_holder_reconstruction") is True
                or any(
                    key in (row.get("metrics") or {})
                    for key in (
                        "raw_top10_delta_pct",
                        "effective_top10_delta_pct",
                        "raw_top10_infra_delta_pct",
                    )
                )
                or str(
                    (row.get("signal") or {}).get("level") or ""
                ).upper()
                in {"HIGH", "CRITICAL"}
            )
        ):
            return "holder emitted directional risk from an unreliable baseline"
    return ""


def project_scan_progress_issues(root: Path) -> list[dict[str, str]]:
    path = root / "output" / "alpha_project_watch" / "progress.json"
    if not path.exists():
        return []
    progress = read_json(path, None)
    if not isinstance(progress, dict) or progress.get("schema_version") != 2:
        detail = "project scan progress invalid"
    else:
        active = progress.get("active_project")
        completed = progress.get("completed_projects")
        if active is None:
            detail = (
                "project publish pending"
                if isinstance(completed, list)
                else "project scan progress invalid"
            )
        elif not isinstance(active, dict):
            detail = "project scan progress invalid"
        else:
            contract_progress = active.get("contract_progress")
            if not isinstance(contract_progress, dict):
                detail = "project scan pending"
            else:
                try:
                    previous_tip = int(
                        contract_progress["previous_latest_block"]
                    )
                    requested = int(
                        contract_progress["requested_from_block"]
                    )
                    target = int(
                        contract_progress["target_latest_block"]
                    )
                    covered = int(
                        contract_progress["covered_through_block"]
                    )
                    next_from = int(contract_progress["next_from_block"])
                except (KeyError, TypeError, ValueError):
                    detail = "project scan pending"
                else:
                    target_hash = str(
                        contract_progress.get("target_latest_block_hash")
                        or ""
                    ).lower()
                    if (
                        previous_tip < 0
                        or requested < 0
                        or requested > target + 1
                        or covered != next_from - 1
                        or not requested <= next_from <= target + 1
                        or len(target_hash) != 66
                        or not target_hash.startswith("0x")
                        or any(
                            char not in "0123456789abcdef"
                            for char in target_hash[2:]
                        )
                        or int(target_hash, 16) == 0
                    ):
                        detail = "project scan progress invalid"
                    else:
                        phase = (
                            "bootstrap" if previous_tip == 0 else "catchup"
                        )
                        detail = (
                            f"project {phase} pending; "
                            f"covered={covered} target={target}"
                        )
    return [
        issue(
            "alpha_project_scan_pending",
            "alpha_project",
            detail,
            "alpha_project_scan_pending",
        )
    ]


def output_row_coverage_warning(
    output_name: str,
    row: dict[str, Any],
    target_contract: str = "",
) -> str:
    if output_name == "intraday" and row.get("status") == "scanned":
        analysis = row.get("analysis") or {}
        warnings: list[str] = []
        if analysis.get("scan_limited"):
            warnings.append(
                "intraday receipt scan limited; complete transfer evidence only"
            )
        if analysis.get("cex_gas_priming_scan_limited"):
            warnings.append(
                "intraday CEX gas-priming scan time-limited; transfer risk retained"
            )
        if analysis.get("optional_market_scan_limited"):
            warnings.append(
                "intraday required known paths complete; remaining market receipts sampled"
            )
        return "; ".join(warnings)
    if output_name == "opening" and row.get("status") == "opened":
        warnings: list[str] = []
        if row.get("opening_recent_tail_coverage_complete") is False:
            warnings.append(
                "opening cohort complete; recent transfer tail uses a bounded window"
            )
        if (
            row.get("opening_log_required_windows_complete") is True
            and row.get("opening_log_contiguous_coverage_complete") is False
        ):
            warnings.append(
                "opening watcher covers the cohort and recent tail; middle history belongs to intraday/holder stages"
            )
        if row.get("opening_receipt_classification_complete") is False:
            warnings.append(
                "opening receipt attribution sampled; complete transfer-recipient scope remains required intraday"
            )
        traces = [
            item.get("buyer_trace") or {}
            for item in row.get("rows", [])
            if isinstance(item, dict)
        ]
        partial_statuses = {
            "unknown_incomplete_coverage",
            "confirmed_sell_partial_coverage",
        }
        if any(
            trace.get("coverage_complete") is False
            or trace.get("coverage_status") == "partial"
            or trace.get("status") in partial_statuses
            for trace in traces
        ):
            warnings.append("opening buyer trace coverage incomplete")
        if row.get("refresh_status") == "partial_trace_deadline":
            warnings.append("opening buyer trace deadline reached")
        return "; ".join(warnings)
    if (
        output_name == "holder"
        and row.get("holder_baseline_status")
        == "bounded_bootstrap_unreliable"
    ):
        return (
            "holder concentration baseline unavailable after bounded "
            "bootstrap; indexed retention flow remains active"
        )
    if output_name != "project":
        return ""
    contracts = [item for item in row.get("contracts", []) if isinstance(item, dict)]
    if target_contract:
        contracts = [
            item
            for item in contracts
            if str(item.get("address") or "").lower() == target_contract.lower()
        ]
    states = {
        str(item.get("operator_attribution_state") or "")
        for item in contracts
    }
    unresolved = states & {
        "owner_unresolved",
        "conflicting_owner_selectors",
        "unresolved",
    }
    if unresolved:
        return "project operator attribution warning=" + ",".join(sorted(unresolved))
    return ""


def matching_rows_coverage_issue(
    output_name: str,
    rows: list[dict[str, Any]],
    target_contract: str = "",
) -> str:
    for row in rows:
        detail = output_row_coverage_issue(
            output_name,
            row,
            target_contract=target_contract,
        )
        if detail:
            return detail
    return ""


def matching_opening_nonhistorical_coverage_issue(
    rows: list[dict[str, Any]],
) -> str:
    adjusted_rows = []
    for row in rows:
        adjusted = dict(row)
        if adjusted.get("status") == "opened":
            adjusted["opening_liquidity_coverage_complete"] = True
        adjusted_rows.append(adjusted)
    return matching_rows_coverage_issue("opening", adjusted_rows)


def matching_rows_coverage_warning(
    output_name: str,
    rows: list[dict[str, Any]],
    target_contract: str = "",
) -> str:
    for row in rows:
        detail = output_row_coverage_warning(
            output_name,
            row,
            target_contract=target_contract,
        )
        if detail:
            return detail
    return ""


def opening_buyer_addresses_for_identity(
    path: Path,
    identity: tuple[str, str],
) -> set[str]:
    buyers: set[str] = set()
    for event in snapshot_rows(path):
        if identity not in row_contract_identities(event, "opening"):
            continue
        for address in event.get("opening_buyer_scope_addresses", []) or []:
            address = str(address or "").lower()
            if address:
                buyers.add(address)
        for row in event.get("rows", []):
            if not isinstance(row, dict):
                continue
            try:
                token_bought = float(row.get("token_bought") or 0)
            except (TypeError, ValueError):
                token_bought = 0
            trace = (
                row.get("buyer_trace")
                if isinstance(row.get("buyer_trace"), dict)
                else {}
            )
            buyer = str(row.get("buyer") or "").lower()
            if (
                token_bought > 0
                and buyer
                and not row.get("buyer_exclusion_reason")
                and not trace.get("subject_exclusion_reason")
            ):
                buyers.add(buyer)
    return buyers


def intraday_opening_buyer_scope_issue(
    opening_path: Path,
    identity: tuple[str, str],
    intraday_rows: list[dict[str, Any]],
) -> str:
    expected = opening_buyer_addresses_for_identity(
        opening_path,
        identity,
    )
    observed = {
        str(address or "").lower()
        for row in intraday_rows
        for address in (row.get("opening_buyer_addresses") or [])
        if address
    }
    missing = expected - observed
    return (
        f"intraday opening-buyer scope missing {len(missing)} address(es)"
        if missing
        else ""
    )


def retention_flow_required(
    listing: datetime | None,
    current: datetime,
) -> bool:
    return bool(
        listing is not None
        and listing <= current <= listing + timedelta(days=30)
    )


def valid_hex_value(value: Any, digits: int, prefix: str = "") -> bool:
    text = str(value or "").lower()
    return bool(
        len(text) == len(prefix) + digits
        and text.startswith(prefix)
        and all(
            character in "0123456789abcdef"
            for character in text[len(prefix):]
        )
    )


def opening_has_verified_liquidity_pool_scope(
    opening_path: Path,
    identity: tuple[str, str],
) -> bool:
    chain, token = identity
    matching = [
        event
        for event in snapshot_rows(opening_path)
        if event.get("status") == "opened"
        and identity in row_contract_identities(event, "opening")
    ]
    symbols = {
        str(event.get("symbol") or "").strip().upper()
        for event in matching
    }
    if (
        not valid_hex_value(token, 40, "0x")
        or not matching
        or len(symbols) != 1
        or not next(iter(symbols))
    ):
        return False
    try:
        from scripts import alpha_holder_concentration_watch as holder_watch
    except ModuleNotFoundError:
        import alpha_holder_concentration_watch as holder_watch
    scope = holder_watch.opening_verified_pool_scope(
        {"events": matching},
        next(iter(symbols)),
        chain,
        token,
    )
    return bool(
        scope.get("complete") is True
        and type(scope.get("matching_event_count")) is int
        and scope.get("matching_event_count") == len(matching)
        and type(scope.get("pool_count")) is int
        and scope.get("pool_count") > 0
    )


def opening_liquidity_gap_is_historical_only(
    opening_path: Path,
    identity: tuple[str, str],
    detail: str,
) -> bool:
    return bool(
        detail == "opening liquidity flow coverage incomplete"
        and opening_has_verified_liquidity_pool_scope(
            opening_path,
            identity,
        )
    )


def retention_flow_coverage_issue(row: dict[str, Any]) -> str:
    flow = (
        row.get("retention_flow")
        if isinstance(row.get("retention_flow"), dict)
        else {}
    )
    if flow.get("status") != "active":
        return f"retention flow status={flow.get('status', 'missing')}"
    coverage_mode = str(flow.get("coverage_mode") or "")
    if coverage_mode not in {
        "full_transfer_stream",
        "targeted_indexed_topics",
    }:
        return "retention flow coverage mode invalid"
    if (
        row.get("holder_baseline_status")
        == "bounded_bootstrap_unreliable"
        and coverage_mode != "targeted_indexed_topics"
    ):
        return (
            "retention flow must use indexed topics when holder "
            "baseline is unavailable"
        )
    if flow.get("complete") is not True:
        return "retention flow coverage incomplete"
    if int(flow.get("log_error_count") or 0):
        return "retention flow log scan has errors"
    if flow.get("truncated") or flow.get("events_truncated"):
        return "retention flow output truncated"
    if coverage_mode == "targeted_indexed_topics":
        if flow.get("query_scope_complete") is not True:
            return "retention flow indexed query scope incomplete"
        if flow.get("opening_scope_complete") is not True:
            return "retention flow opening actor scope incomplete"
        scope_hash = str(flow.get("scope_hash") or "")
        if (
            len(scope_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in scope_hash.lower()
            )
        ):
            return "retention flow scope hash invalid"
        try:
            scope_count = int(flow.get("scope_kind_count") or 0)
            scope_batch_count = int(
                flow.get("scope_batch_count") or 0
            )
            query_count = int(flow.get("query_count") or 0)
            query_chunk_count = int(
                flow.get("query_chunk_count") or 0
            )
            expected_query_count = int(
                flow.get("expected_query_count") or 0
            )
            actor_count = int(flow.get("opening_buyer_count") or 0)
            actor_count += int(
                flow.get("opening_cohort_recipient_count") or 0
            )
            actor_count += int(
                flow.get("verified_project_address_count") or 0
            )
            cex_count = int(flow.get("cex_address_count") or 0)
            opening_actor_count = int(
                flow.get("opening_actor_count") or 0
            )
            scope_state_schema_version = int(
                flow.get("scope_state_schema_version") or 0
            )
        except (TypeError, ValueError):
            return "retention flow indexed query metadata invalid"
        if scope_count <= 0 or actor_count + cex_count <= 0:
            return "retention flow indexed query scope empty"
        if (
            scope_batch_count <= 0
            or query_chunk_count <= 0
            or expected_query_count
            != scope_batch_count * query_chunk_count
            or query_count != expected_query_count
        ):
            return "retention flow indexed query count invalid"
        opening_scope_hash = str(
            flow.get("opening_actor_scope_hash") or ""
        )
        if (
            scope_state_schema_version != 1
            or opening_actor_count < 0
            or len(opening_scope_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in opening_scope_hash.lower()
            )
        ):
            return "retention flow opening scope state invalid"
        catchup = flow.get("incremental_catchup")
        if not isinstance(catchup, dict):
            return "retention flow catch-up metadata missing"
        try:
            requested_to = int(catchup["requested_to_block"])
            selected_to = int(catchup["selected_to_block"])
            target_latest = int(flow["target_latest_block"])
            scan_to = int(flow["scan_to_block"])
        except (KeyError, TypeError, ValueError):
            return "retention flow catch-up metadata invalid"
        if (
            catchup.get("applicable") is not True
            or not isinstance(catchup.get("active"), bool)
            or flow.get("selected_window_complete") is not True
            or catchup.get("complete_selected_window") is not True
            or catchup.get("complete_requested_window") is not True
            or catchup.get("active") is not False
            or requested_to != target_latest
            or selected_to != scan_to
            or selected_to != requested_to
        ):
            return "retention flow catch-up metadata invalid"
        previous_scope_hash = str(
            flow.get("previous_scope_hash") or ""
        )
        if flow.get("scope_rebaseline") is True:
            if previous_scope_hash == scope_hash:
                return "retention flow scope rebaseline metadata invalid"
        elif previous_scope_hash != scope_hash:
            return "retention flow scope continuity hash mismatch"
    if (
        flow.get("continuous") is not True
        and flow.get("late_discovery_bootstrap") is not True
        and flow.get("scope_rebaseline") is not True
    ):
        return "retention flow block checkpoint gap"
    try:
        scan_from = int(flow.get("scan_from_block") or 0)
        scan_to = int(flow.get("scan_to_block") or 0)
        previous = int(flow.get("previous_latest_block") or 0)
        latest = int(flow.get("latest_block") or 0)
        scope_coverage_from = int(
            flow.get("scope_coverage_from_block") or 0
        )
    except (TypeError, ValueError):
        return "retention flow block metadata invalid"
    if scan_from > scan_to:
        return "retention flow scan window invalid"
    if (
        flow.get("scope_rebaseline") is True
        and scan_from != scope_coverage_from
    ):
        return "retention flow scope rebaseline start invalid"
    if (
        previous > 0
        and flow.get("scope_rebaseline") is not True
        and scan_from != previous + 1
    ):
        return "retention flow scan does not continue previous checkpoint"
    if latest != scan_to:
        return "retention flow checkpoint did not reach scan tip"
    return ""


def standalone_liquidity_snapshot_issue(path: Path) -> str:
    payload = read_json(path, {})
    if payload.get("schema") != "alpha_liquidity_retention_watch.v1":
        return "standalone liquidity output schema invalid"
    if payload.get("status") != "healthy":
        return "standalone liquidity scan unhealthy"
    if payload.get("delivery_status") != "complete":
        return "standalone liquidity alert delivery incomplete"
    try:
        issue_count = int(payload.get("issue_count") or 0)
        required_count = int(payload.get("required_count") or 0)
        complete_count = int(payload.get("complete_count") or 0)
        expected_count = int(payload["expected_count"])
        processed_count = int(payload["processed_count"])
        dropped_count = int(payload["dropped_count"])
    except (KeyError, TypeError, ValueError):
        return "standalone liquidity counters invalid"
    if (
        issue_count
        or min(required_count, complete_count) < 0
        or required_count != complete_count
    ):
        return "standalone liquidity required coverage incomplete"
    expected_hash = str(payload.get("expected_identity_hash") or "")
    processed_hash = str(payload.get("processed_identity_hash") or "")
    if (
        min(expected_count, processed_count, dropped_count) < 0
        or dropped_count
        or expected_count != processed_count
        or expected_hash != processed_hash
        or not valid_hex_value(expected_hash, 64)
    ):
        return "standalone liquidity eligible identity coverage incomplete"
    return ""


def liquidity_retention_required(
    opening_path: Path,
    identity: tuple[str, str],
    listing: datetime | None,
    current: datetime,
) -> bool:
    return bool(
        opening_has_verified_liquidity_pool_scope(opening_path, identity)
        and not (
            listing is not None
            and current > listing + timedelta(days=30)
        )
    )


def liquidity_retention_coverage_issue(row: dict[str, Any]) -> str:
    retention = (
        row.get("retention_flow")
        if isinstance(row.get("retention_flow"), dict)
        else {}
    )
    flow = (
        retention.get("liquidity_retention")
        if isinstance(retention.get("liquidity_retention"), dict)
        else {}
    )
    if flow.get("status") != "active":
        return (
            "liquidity retention status="
            f"{flow.get('status', 'missing')}"
        )
    if flow.get("coverage_mode") != "verified_pool_indexed_topics":
        return "liquidity retention coverage mode invalid"
    if flow.get("scope_complete") is not True:
        return "liquidity retention verified pool scope incomplete"
    if flow.get("complete") is not True:
        return "liquidity retention coverage incomplete"
    if flow.get("selected_window_complete") is not True:
        return "liquidity retention selected window incomplete"
    if flow.get("query_scope_complete") is not True:
        return "liquidity retention indexed query scope incomplete"
    if flow.get("truncated") or flow.get("events_truncated"):
        return "liquidity retention output truncated"
    try:
        log_error_count = int(flow.get("log_error_count") or 0)
        decode_error_count = int(flow.get("decode_error_count") or 0)
        pool_count = int(flow.get("pool_count") or 0)
        v3_pool_count = int(flow.get("v3_pool_count") or 0)
        v4_pool_count = int(flow.get("v4_pool_count") or 0)
        v4_manager_count = int(flow.get("v4_manager_count") or 0)
        event_filter_count = int(
            flow.get("event_filter_count") or 0
        )
        scope_state_schema_version = int(
            flow.get("scope_state_schema_version") or 0
        )
        scope_batch_count = int(flow.get("scope_batch_count") or 0)
        query_count = int(flow.get("query_count") or 0)
        query_chunk_count = int(flow.get("query_chunk_count") or 0)
        expected_query_count = int(
            flow.get("expected_query_count") or 0
        )
    except (TypeError, ValueError):
        return "liquidity retention indexed query metadata invalid"
    if log_error_count or decode_error_count:
        return "liquidity retention log scan has errors"
    if (
        scope_state_schema_version
        != LIQUIDITY_RETENTION_STATE_SCHEMA_VERSION
        or pool_count <= 0
        or min(v3_pool_count, v4_pool_count) < 0
        or v3_pool_count + v4_pool_count != pool_count
        or v4_manager_count < int(v4_pool_count > 0)
        or v4_manager_count > v4_pool_count
        or event_filter_count
        != v3_pool_count * 4 + v4_pool_count * 2
    ):
        return "liquidity retention verified pool scope invalid"
    if (
        scope_batch_count <= 0
        or scope_batch_count
        != int(v3_pool_count > 0) + v4_manager_count
        or query_chunk_count <= 0
        or expected_query_count
        != scope_batch_count * query_chunk_count
        or query_count != expected_query_count
    ):
        return "liquidity retention indexed query count invalid"

    scope_hash = str(flow.get("scope_hash") or "")
    previous_scope_hash = str(flow.get("previous_scope_hash") or "")
    latest_block_hash = str(flow.get("latest_block_hash") or "")
    if (
        not valid_hex_value(latest_block_hash, 64, "0x")
        or int(latest_block_hash[2:], 16) == 0
    ):
        return "liquidity retention checkpoint hash invalid"
    scope_rebaseline = flow.get("scope_rebaseline") is True
    if not valid_hex_value(scope_hash, 64):
        return "liquidity retention scope hash invalid"
    if scope_rebaseline:
        if previous_scope_hash == scope_hash:
            return "liquidity retention scope rebaseline metadata invalid"
    elif previous_scope_hash != scope_hash:
        return "liquidity retention scope continuity hash mismatch"

    catchup = flow.get("incremental_catchup")
    if not isinstance(catchup, dict):
        return "liquidity retention catch-up metadata missing"
    try:
        requested_to = int(catchup["requested_to_block"])
        selected_to = int(catchup["selected_to_block"])
        scan_from = int(flow["scan_from_block"])
        scan_to = int(flow["scan_to_block"])
        target_latest = int(flow["target_latest_block"])
        previous_latest = int(flow.get("previous_latest_block") or 0)
        latest = int(flow["latest_block"])
        scope_coverage_from = int(
            flow.get("scope_coverage_from_block") or 0
        )
        observed_latest = int(flow.get("observed_latest_block") or 0)
        confirmation_blocks = int(flow.get("confirmation_blocks") or 0)
    except (KeyError, TypeError, ValueError):
        return "liquidity retention block metadata invalid"
    if min(
        requested_to,
        selected_to,
        scan_from,
        scan_to,
        target_latest,
        previous_latest,
        latest,
        scope_coverage_from,
        observed_latest,
        confirmation_blocks,
    ) < 0:
        return "liquidity retention block metadata invalid"
    if target_latest != max(0, observed_latest - confirmation_blocks):
        return "liquidity retention confirmation boundary invalid"
    if (
        catchup.get("applicable") is not True
        or not isinstance(catchup.get("active"), bool)
        or catchup.get("active") is not False
        or catchup.get("complete_selected_window") is not True
        or catchup.get("complete_requested_window") is not True
        or requested_to != target_latest
        or selected_to != scan_to
        or selected_to != requested_to
    ):
        return "liquidity retention catch-up metadata invalid"
    if scan_from > scan_to or latest != scan_to:
        return "liquidity retention scan window invalid"
    if scope_rebaseline:
        if scan_from != scope_coverage_from:
            return "liquidity retention scope rebaseline start invalid"
    elif (
        flow.get("continuous") is not True
        or scan_from != previous_latest + 1
    ):
        return "liquidity retention scan does not continue previous checkpoint"
    return ""


def liquidity_retention_coverage_warning(row: dict[str, Any]) -> str:
    retention = (
        row.get("retention_flow")
        if isinstance(row.get("retention_flow"), dict)
        else {}
    )
    flow = (
        retention.get("liquidity_retention")
        if isinstance(retention.get("liquidity_retention"), dict)
        else {}
    )
    if flow.get("status") == "active" and flow.get("scope_rebaseline"):
        return (
            "liquidity retention verified pool scope was baselined from "
            "its declared coverage block; earlier pool history remains "
            "outside verified monitoring"
        )
    if (
        flow.get("status") == "active"
        and flow.get("checkpoint_reorg_recovery") is True
    ):
        return (
            "liquidity retention checkpoint hash changed; the configured "
            "overlap was rescanned from the canonical chain"
        )
    return ""


def retention_flow_coverage_warning(row: dict[str, Any]) -> str:
    flow = (
        row.get("retention_flow")
        if isinstance(row.get("retention_flow"), dict)
        else {}
    )
    if (
        flow.get("status") == "active"
        and flow.get("scope_rebaseline")
    ):
        return (
            "retention indexed scope was baselined from its declared "
            "coverage block; earlier scope history remains outside "
            "verified monitoring"
        )
    if (
        flow.get("status") == "active"
        and flow.get("late_discovery_bootstrap")
    ):
        return (
            "retention flow begins at late-discovery first observation; "
            "earlier history was outside monitored scope"
        )
    return ""


def runtime_watchlist_contracts(path: Path) -> set[tuple[str, str]]:
    payload = read_json(path, {})
    rows: set[tuple[str, str]] = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("active_monitoring") is False:
            continue
        for contract in item.get("contracts", []):
            if not isinstance(contract, dict):
                continue
            chain = str(contract.get("chain") or item.get("chain") or "").lower()
            address = str(contract.get("address") or "").lower()
            if chain and address:
                rows.add((chain, address))
    return rows


def runtime_watchlist_targets(
    path: Path,
    *,
    fallback_path: Path | None = None,
) -> list[dict[str, Any]]:
    payload = read_json(path, {})
    targets: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("active_monitoring") is False:
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
        for contract in item.get("contracts", []):
            if not isinstance(contract, dict):
                continue
            chain = str(
                contract.get("chain") or item.get("chain") or ""
            ).lower()
            address = str(contract.get("address") or "").lower()
            if not symbol or not chain or not address:
                continue
            targets.append(
                {
                    "symbol": symbol,
                    "chain": chain,
                    "contract": address,
                    "listing_time_utc": str(
                        facts.get("listing_time_utc") or ""
                    ),
                    "monitoring_anchor_time_utc": str(
                        facts.get("monitoring_anchor_time_utc") or ""
                    ),
                    "lifecycle_first_seen_at": str(
                        facts.get("lifecycle_first_seen_at") or ""
                    ),
                    "active_monitoring": True,
                }
            )
    if fallback_path is not None and fallback_path != path:
        fallback_by_identity = {
            (row["chain"], row["contract"]): row
            for row in runtime_watchlist_targets(fallback_path)
        }
        for target in targets:
            fallback = fallback_by_identity.get(
                (target["chain"], target["contract"]),
                {},
            )
            for key in (
                "listing_time_utc",
                "monitoring_anchor_time_utc",
                "lifecycle_first_seen_at",
            ):
                if not target.get(key):
                    target[key] = fallback.get(key, "")
    return targets


def catalog_pending_runtime_identities(path: Path) -> set[tuple[str, str]]:
    payload = read_json(path, {})
    identities: set[tuple[str, str]] = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("active_monitoring") is not True:
            continue
        facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
        if parse_time(facts.get("monitoring_anchor_time_utc")) is None:
            continue
        research = (
            item.get("prelaunch_research")
            if isinstance(item.get("prelaunch_research"), dict)
            else {}
        )
        identity = (
            research.get("identity")
            if isinstance(research.get("identity"), dict)
            else {}
        )
        pool = (
            research.get("pool")
            if isinstance(research.get("pool"), dict)
            else {}
        )
        pool_key = (
            pool.get("pool_key")
            if isinstance(pool.get("pool_key"), dict)
            else {}
        )
        decision = (
            research.get("decision")
            if isinstance(research.get("decision"), dict)
            else {}
        )
        identity_chain = str(identity.get("chain") or "").lower()
        identity_contract = str(identity.get("contract") or "").lower()
        pool_tokens = {
            str(pool_key.get("token0") or "").lower(),
            str(pool_key.get("token1") or "").lower(),
        }
        pool_id = str(pool.get("pool_id") or "").lower()
        if (
            research.get("schema_version") != "alpha_prelaunch_research.v1"
            or research.get("research_status") != "blocked"
            or identity.get("verification_status")
            != "canonical_pool_key_match_official_contract_pending"
            or decision.get("action") != "Observe"
            or decision.get("automatic_trading") is not False
            or len(pool_id) != 66
            or not pool_id.startswith("0x")
            or identity_contract not in pool_tokens
        ):
            continue
        for contract in item.get("contracts", []):
            if not isinstance(contract, dict):
                continue
            chain = str(
                contract.get("chain") or item.get("chain") or ""
            ).lower()
            address = str(contract.get("address") or "").lower()
            if (
                chain == identity_chain
                and address == identity_contract
                and contract.get("confidence")
                == "canonical_pancake_pool_key_match_official_catalog_pending"
            ):
                identities.add((chain, address))
    return identities


def effective_runtime_watchlist_path(root: Path) -> Path:
    configured = os.environ.get("ALPHA_WATCHLIST_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    generated = (
        root
        / "output"
        / "binance_alpha_catalog_watch"
        / "current_watchlist.json"
    )
    if generated.exists():
        return generated
    return root / "config" / "current_alpha_watchlist.json"


def monitoring_focus_scope(
    root: Path,
    runtime_path: Path,
) -> tuple[set[str] | None, str]:
    static_path = root / "config" / "current_alpha_watchlist.json"
    if not static_path.exists():
        return set(), "curated Alpha monitoring policy is missing"
    static_watchlist = read_json(static_path, {})
    policy = static_watchlist.get("monitoring_policy")
    if (
        not isinstance(policy, dict)
        or policy.get("mode") != "exclusive_symbols"
        or not isinstance(policy.get("symbols"), list)
    ):
        return set(), "curated Alpha monitoring policy invalid"
    focused = {
        str(symbol or "").strip().upper()
        for symbol in policy["symbols"]
        if str(symbol or "").strip()
    }
    if not focused:
        return set(), "curated Alpha monitoring focus is empty"

    def active_symbols(payload: dict[str, Any]) -> set[str]:
        return {
            str(item.get("symbol") or "").strip().upper()
            for item in payload.get("items", [])
            if isinstance(item, dict)
            and item.get("active_monitoring") is not False
            and str(item.get("symbol") or "").strip()
        }

    if active_symbols(static_watchlist) != focused:
        return focused, "curated Alpha active symbols differ from monitoring focus"
    runtime_watchlist = read_json(runtime_path, {})
    if runtime_path.resolve() == static_path.resolve():
        return focused, ""
    try:
        max_age_seconds = int(
            os.environ.get(
                "BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS",
                "21600",
            )
        )
        age_seconds = max(
            0,
            int(time.time() - runtime_path.stat().st_mtime),
        )
    except (OSError, ValueError):
        return focused, "runtime Alpha watchlist freshness invalid"
    if max_age_seconds < 1 or age_seconds > max_age_seconds:
        return focused, "runtime Alpha watchlist is stale"
    canonical_policy = {
        "mode": "exclusive_symbols",
        "symbols": sorted(focused),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            canonical_policy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        runtime_watchlist.get("monitoring_policy") != canonical_policy
        or runtime_watchlist.get("monitoring_policy_fingerprint")
        != fingerprint
        or active_symbols(runtime_watchlist) != focused
    ):
        return focused, "runtime Alpha watchlist monitoring policy mismatch"
    return focused, ""


def prelaunch_delivery_issue(
    root: Path,
    matching_rows: list[dict[str, Any]],
) -> str:
    delivery_rows = [
        row
        for row in matching_rows
        if row.get("event_kind") != "airdrop_pressure"
        and row.get("alert_policy", "notify") == "notify"
    ]
    if not delivery_rows:
        return ""
    alert_keys = {
        str(row.get("alert_key") or "")
        for row in delivery_rows
        if str(row.get("alert_key") or "")
    }
    if not alert_keys:
        return "prelaunch event has no delivery identity"
    seen = read_json(
        root / "output" / "alpha_prelaunch_watch" / "seen_alerts.json",
        {},
    )
    seen_keys = {
        str(value or "")
        for value in (seen.get("keys") or [])
    }
    if alert_keys <= seen_keys:
        return ""
    return "prelaunch Telegram delivery receipt missing"


def alpha_required_outputs(
    chain: str,
    listing: datetime | None,
    current: datetime,
) -> list[str]:
    required = ["project", "holder"]
    if chain != "bsc":
        required.append("price")
        return required
    required.append("opening")
    if listing is None:
        required.extend(["intraday", "price"])
        return required
    if listing > current:
        lookahead = timedelta(
            hours=float(
                os.environ.get(
                    "ALPHA_PRELAUNCH_LOOKAHEAD_HOURS",
                    str(DEFAULT_PRELAUNCH_LOOKAHEAD_HOURS),
                )
            )
        )
        if listing - current <= lookahead:
            required.append("prelaunch")
        return required
    required.append("price")
    intraday_core = timedelta(
        hours=float(
            os.environ.get(
                "ALPHA_INTRADAY_CORE_HOURS",
                str(DEFAULT_INTRADAY_CORE_HOURS),
            )
        )
    )
    if current - listing <= intraday_core:
        required.append("intraday")
    return required


def historical_prelaunch_delivery_issue(
    root: Path,
    row: dict[str, Any],
    current: datetime,
) -> str:
    listing = parse_time(
        row.get("listing_time_utc")
        or row.get("monitoring_anchor_time_utc")
    )
    if listing is None or current < listing:
        return ""
    first_seen = parse_time(row.get("lifecycle_first_seen_at"))
    if first_seen is None:
        return "prelaunch lifecycle first-seen timestamp missing"
    live_window = timedelta(minutes=30)
    if first_seen > listing + live_window:
        return ""
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    contract = str(row.get("contract") or "").lower()
    listing_key = listing.replace(second=0, microsecond=0).isoformat()
    key_prefix = f"{symbol}|{contract}|{listing_key}|"
    cycle_sla = timedelta(
        minutes=max(
            0,
            float(
                os.environ.get(
                    "ALPHA_PRELAUNCH_DELIVERY_SLA_MINUTES",
                    "10",
                )
            )
        ),
    )
    allowed_phases = ("T_MINUS_",)
    if first_seen >= listing:
        allowed_phases = ("LIVE_WINDOW",)
    elif first_seen > listing - cycle_sla:
        allowed_phases = ("T_MINUS_", "LIVE_WINDOW")
    seen = read_json(
        root / "output" / "alpha_prelaunch_watch" / "seen_alerts.json",
        {},
    )
    if any(
        any(
            str(value or "").startswith(key_prefix + phase)
            for phase in allowed_phases
        )
        for value in (seen.get("keys") or [])
    ):
        return ""
    return "historical prelaunch Telegram delivery receipt missing"


def legacy_prelaunch_delivery_warning(
    row: dict[str, Any],
    delivery_detail: str,
) -> str:
    if delivery_detail != "historical prelaunch Telegram delivery receipt missing":
        return ""
    listing = parse_time(row.get("listing_time_utc"))
    first_seen = parse_time(row.get("lifecycle_first_seen_at"))
    if listing is None or first_seen is None:
        return ""
    if (
        listing >= PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT
        or first_seen >= PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT
    ):
        return ""
    listing_key = listing.isoformat()
    identities = {
        (chain, contract, listing_key)
        for chain, contract in row_contract_identities(row, "catalog")
    }
    if not (
        identities
        & LEGACY_PRELAUNCH_DELIVERY_UNVERIFIED_IDENTITIES
    ):
        return ""
    return (
        "historical prelaunch delivery_unverified under legacy migration; "
        f"policy={PRELAUNCH_RECEIPT_POLICY_VERSION}; "
        f"first_seen={first_seen.isoformat()}; "
        f"listing={listing.isoformat()}; "
        f"enforced_at={PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT.isoformat()}; "
        "missing persisted receipt is not evidence of delivery"
    )


def alpha_coverage_evaluation(
    root: Path,
    *,
    current: datetime | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    attempt = read_json(
        root / "output" / "binance_alpha_catalog_watch" / "status.json",
        {},
    )
    if attempt and attempt.get("status") != "pass":
        return (
            [
                issue(
                    "alpha_catalog_failed",
                    "binance_alpha_catalog",
                    f"official Alpha catalog status={attempt.get('status', 'missing')}: "
                    f"{str(attempt.get('reason') or '')[:240]}",
                )
            ],
            [],
        )
    catalog = read_json(
        root / "output" / "binance_alpha_catalog_watch" / "latest.json",
        {},
    )
    if not catalog:
        return [], []
    if catalog.get("status") != "pass":
        return (
            [
                issue(
                    "alpha_catalog_failed",
                    "binance_alpha_catalog",
                    f"official Alpha catalog status={catalog.get('status', 'missing')}",
                )
            ],
            [],
        )
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    current = (
        current or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)
    runtime_watchlist_path = effective_runtime_watchlist_path(root)
    focus_symbols, focus_detail = monitoring_focus_scope(
        root,
        runtime_watchlist_path,
    )
    if focus_detail:
        issues.append(
            issue(
                "alpha_monitoring_policy_mismatch",
                "binance_alpha_catalog",
                focus_detail,
                f"alpha_monitoring_policy_mismatch:{focus_detail}",
            )
        )

    def in_monitoring_focus(row: dict[str, Any]) -> bool:
        if focus_symbols is None:
            return row.get("active_monitoring") is not False
        return str(row.get("symbol") or "").strip().upper() in focus_symbols

    static_time_conflicts = [
        row
        for row in catalog.get("static_time_conflicts", [])
        if isinstance(row, dict)
    ]
    static_time_conflict_count = int(
        catalog.get("static_time_conflict_count") or 0
    )
    if static_time_conflict_count != len(static_time_conflicts):
        issues.append(
            issue(
                "alpha_static_time_conflict_summary_invalid",
                "binance_alpha_catalog",
                (
                    "static launch conflict count does not match detail rows: "
                    f"count={static_time_conflict_count}, "
                    f"rows={len(static_time_conflicts)}"
                ),
                (
                    "alpha_static_time_conflict_summary_invalid:"
                    f"{static_time_conflict_count}:"
                    f"{len(static_time_conflicts)}"
                ),
            )
        )
    for row in static_time_conflicts:
        if not in_monitoring_focus(row):
            continue
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        static_times = ",".join(
            str(value)
            for value in row.get("static_opening_times_utc8", [])
        )
        official_time = str(row.get("official_listing_time_utc8") or "")
        issues.append(
            issue(
                "alpha_static_time_conflict",
                symbol,
                (
                    f"{symbol} static launch anchor {static_times or 'unknown'} "
                    f"conflicts with official Alpha listing "
                    f"{official_time or 'unknown'}"
                ),
                (
                    f"alpha_static_time_conflict:{symbol}:"
                    f"{static_times}:{official_time}"
                ),
            )
        )
    dropped_count = int(catalog.get("dropped_count") or 0)
    if dropped_count:
        dropped_rows = [
            row
            for row in catalog.get("dropped", [])
            if isinstance(row, dict) and in_monitoring_focus(row)
        ]
        if focus_symbols is not None and not dropped_rows:
            dropped_count = 0
    if dropped_count:
        dropped_symbols = ",".join(
            str(row.get("symbol") or "")
            for row in dropped_rows[:8]
        )
        suffix = f": {dropped_symbols}" if dropped_symbols else ""
        dropped_identities = "\n".join(
            sorted(
                f"{str(row.get('chain') or '').lower()}:{str(row.get('contract') or '').lower()}"
                for row in dropped_rows
            )
        )
        dropped_signature = hashlib.sha256(
            dropped_identities.encode("utf-8")
        ).hexdigest()[:16]
        issues.append(
            issue(
                "alpha_catalog_budget_exceeded",
                "binance_alpha_catalog",
                f"{dropped_count} eligible Alpha catalog item(s) exceeded the runtime budget{suffix}",
                f"alpha_catalog_budget_exceeded:{dropped_count}:{dropped_signature}",
            )
        )
    unsupported_count = int(catalog.get("unsupported_count") or 0)
    if unsupported_count:
        unsupported_rows = [
            row
            for row in catalog.get("unsupported", [])
            if isinstance(row, dict) and in_monitoring_focus(row)
        ]
        if focus_symbols is not None:
            unsupported_count = len(unsupported_rows)
    if unsupported_count:
        labels = ",".join(
            f"{row.get('symbol')}@{row.get('chain')}"
            for row in unsupported_rows[:8]
        )
        issues.append(
            issue(
                "alpha_unsupported_chain",
                "binance_alpha_catalog",
                f"{unsupported_count} recent Alpha item(s) need an unsupported-chain monitor: {labels}",
                f"alpha_unsupported_chain:{unsupported_count}:{labels}",
            )
        )
    static_watchlist_path = root / "config" / "current_alpha_watchlist.json"
    catalog_pending_identities = catalog_pending_runtime_identities(
        static_watchlist_path
    )
    active_pending_by_symbol: dict[str, set[tuple[str, str]]] = {}
    for target in runtime_watchlist_targets(static_watchlist_path):
        identity = (target["chain"], target["contract"])
        anchor = parse_time(target.get("monitoring_anchor_time_utc"))
        if (
            identity in catalog_pending_identities
            and anchor is not None
            and current < anchor
        ):
            active_pending_by_symbol.setdefault(
                str(target.get("symbol") or "").upper(),
                set(),
            ).add(identity)
    pending_registry = [
        row
        for row in catalog.get("registry_pending", [])
        if isinstance(row, dict) and in_monitoring_focus(row)
    ]
    for row in pending_registry:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        reasons = ",".join(str(value) for value in row.get("reasons", []))
        project_key = str(row.get("project_key") or symbol)
        pending_identities = active_pending_by_symbol.get(symbol, set())
        row_identity = (
            str(row.get("chain") or "").lower(),
            str(row.get("contract") or "").lower(),
        )
        is_pending = (
            row_identity in pending_identities
            if all(row_identity)
            else len(pending_identities) == 1
        )
        target = warnings if is_pending else issues
        kind = (
            "alpha_launch_candidate_pending"
            if is_pending
            else "alpha_launch_candidate_gap"
        )
        target.append(
            issue(
                kind,
                symbol,
                (
                    f"{symbol} official catalog contract remains pending; "
                    "canonical prelaunch monitoring stays Observe"
                    if is_pending
                    else (
                        f"{symbol} launch candidate is not monitor-ready: "
                        f"{reasons or 'unknown gap'}"
                    )
                ),
                f"{kind}:{project_key}:{reasons}",
            )
        )
    catalog_selected = [
        row
        for row in (
            list(catalog.get("selected", []))
            + list(catalog.get("registry_selected", []))
        )
        if isinstance(row, dict)
        and row.get("symbol")
        and in_monitoring_focus(row)
        and row.get("active_monitoring") is not False
    ]
    runtime_targets = [
        row
        for row in runtime_watchlist_targets(
            runtime_watchlist_path,
            fallback_path=static_watchlist_path,
        )
        if in_monitoring_focus(row)
    ]
    selected_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for row in runtime_targets:
        identity = (
            str(row.get("chain") or "").lower(),
            str(row.get("contract") or "").lower(),
        )
        if identity[0] and identity[1]:
            selected_by_identity[identity] = dict(row)
    catalog_identities: set[tuple[str, str]] = set()
    for row in catalog_selected:
        identity = (
            str(row.get("chain") or "").lower(),
            str(row.get("contract") or "").lower(),
        )
        if not identity[0] or not identity[1]:
            continue
        catalog_identities.add(identity)
        merged = selected_by_identity.get(identity, {})
        selected_by_identity[identity] = {
            **merged,
            **{
                key: value
                for key, value in row.items()
                if value not in (None, "")
            },
        }
    for row in runtime_targets:
        identity = (
            str(row.get("chain") or "").lower(),
            str(row.get("contract") or "").lower(),
        )
        if identity not in catalog_identities:
            symbol = str(row.get("symbol") or "UNKNOWN").upper()
            monitoring_anchor = parse_time(
                row.get("monitoring_anchor_time_utc")
            )
            is_pending = (
                identity in catalog_pending_identities
                and monitoring_anchor is not None
                and current < monitoring_anchor
            )
            target = warnings if is_pending else issues
            kind = (
                "alpha_catalog_focus_pending"
                if is_pending
                else "alpha_catalog_focus_missing"
            )
            target.append(
                issue(
                    kind,
                    symbol,
                    (
                        f"{symbol} canonical pool identity is active while "
                        "the official catalog contract remains pending"
                        if is_pending
                        else (
                            f"{symbol} is active in the runtime focus but "
                            "absent from the current catalog summary"
                        )
                    ),
                    f"{kind}:{identity[0]}:{identity[1]}",
                )
            )
    selected = list(selected_by_identity.values())
    if not selected:
        if focus_symbols:
            issues.append(
                issue(
                    "alpha_monitoring_focus_missing",
                    "binance_alpha_catalog",
                    "exclusive Alpha monitoring focus has no active contract identity",
                    "alpha_monitoring_focus_missing",
                )
            )
        return issues, warnings
    runtime_contracts = runtime_watchlist_contracts(runtime_watchlist_path)
    output_paths = {
        "project": root / "output" / "alpha_project_watch" / "latest.json",
        "prelaunch": root / "output" / "alpha_prelaunch_watch" / "latest.json",
        "opening": root / "output" / "alpha_opening_block_watch" / "latest.json",
        "intraday": root / "output" / "alpha_intraday_flow_watch" / "latest.json",
        "intraday_required": root / "output" / "alpha_intraday_flow_watch" / "required_only_latest.json",
        "price": root / "output" / "alpha_price_momentum_watch" / "latest.json",
        "holder": root / "output" / "alpha_holder_concentration_watch" / "latest.json",
        "liquidity": root
        / "output"
        / "alpha_liquidity_retention_watch"
        / "latest.json",
    }
    for row in selected:
        symbol = str(row.get("symbol") or "").upper()
        chain = str(row.get("chain") or "").lower()
        contract = str(row.get("contract") or "").lower()
        identity = (chain, contract)
        identity_label = f"{chain}:{contract}"
        if identity not in runtime_contracts:
            issues.append(
                issue(
                    "alpha_coverage_gap",
                    symbol,
                    f"{symbol} is an active Alpha lifecycle target but missing from the runtime watchlist",
                    f"alpha_coverage_gap:{identity_label}:runtime_watchlist",
                )
            )
            continue
        listing = parse_time(
            row.get("listing_time_utc")
            or row.get("monitoring_anchor_time_utc")
        )
        required_outputs = alpha_required_outputs(
            chain,
            listing,
            current,
        )
        for output_name in required_outputs:
            candidates = snapshot_rows(output_paths[output_name])
            matching = [
                candidate
                for candidate in candidates
                if identity in row_contract_identities(candidate, output_name)
            ]
            if output_name == "intraday":
                required_path = output_paths["intraday_required"]
                main_path = output_paths["intraday"]
                required_is_current = (
                    required_path.exists()
                    and (
                        not main_path.exists()
                        or required_path.stat().st_mtime
                        >= main_path.stat().st_mtime
                    )
                )
                if required_is_current:
                    required_matching = [
                        candidate
                        for candidate in snapshot_rows(required_path)
                        if identity
                        in row_contract_identities(candidate, "intraday")
                    ]
                    matching = required_matching
            if not matching:
                issues.append(
                    issue(
                        "alpha_coverage_gap",
                        symbol,
                        f"{symbol} {output_name} output does not match official contract",
                        f"alpha_coverage_gap:{identity_label}:{output_name}:contract_mismatch",
                    )
                )
                continue
            detail = matching_rows_coverage_issue(
                output_name,
                matching,
                target_contract=contract,
            )
            if (
                output_name == "opening"
                and opening_liquidity_gap_is_historical_only(
                    output_paths["opening"],
                    identity,
                    detail,
                )
            ):
                warnings.append(
                    issue(
                        "alpha_coverage_warning",
                        symbol,
                        (
                            f"{symbol} opening: historical liquidity flow "
                            "coverage incomplete; verified pool scope retained"
                        ),
                        (
                            f"alpha_coverage_warning:{identity_label}:opening:"
                            "historical_liquidity_flow_incomplete"
                        ),
                    )
                )
                detail = matching_opening_nonhistorical_coverage_issue(
                    matching
                )
            if detail:
                issues.append(
                    issue(
                        "alpha_coverage_gap",
                        symbol,
                        f"{symbol} {output_name}: {detail}",
                        f"alpha_coverage_gap:{identity_label}:{output_name}:{detail}",
                    )
                )
                continue
            if output_name == "intraday":
                scope_detail = intraday_opening_buyer_scope_issue(
                    output_paths["opening"],
                    identity,
                    matching,
                )
                if scope_detail:
                    issues.append(
                        issue(
                            "alpha_coverage_gap",
                            symbol,
                            f"{symbol} {scope_detail}",
                            (
                                f"alpha_coverage_gap:{identity_label}:intraday:"
                                "opening_buyer_scope"
                            ),
                        )
                    )
                    continue
            warning_detail = matching_rows_coverage_warning(
                output_name,
                matching,
                target_contract=contract,
            )
            if warning_detail:
                warnings.append(
                    issue(
                        "alpha_coverage_warning",
                        symbol,
                        f"{symbol} {output_name}: {warning_detail}",
                        f"alpha_coverage_warning:{identity_label}:{output_name}:{warning_detail}",
                    )
                )
            if output_name == "holder":
                retention_details = (
                    [
                        detail
                        for detail in (
                            retention_flow_coverage_issue(candidate)
                            for candidate in matching
                        )
                        if detail
                    ]
                    if retention_flow_required(listing, current)
                    else []
                )
                if retention_details:
                    detail = retention_details[0]
                    issues.append(
                        issue(
                            "alpha_coverage_gap",
                            symbol,
                            f"{symbol} retention_flow: {detail}",
                            f"alpha_coverage_gap:{identity_label}:retention_flow:{detail}",
                        )
                    )
                elif retention_flow_required(listing, current):
                    retention_warnings = [
                        detail
                        for detail in (
                            retention_flow_coverage_warning(candidate)
                            for candidate in matching
                        )
                        if detail
                    ]
                    if retention_warnings:
                        detail = retention_warnings[0]
                        warnings.append(
                            issue(
                                "alpha_coverage_warning",
                                symbol,
                                f"{symbol} retention_flow: {detail}",
                                f"alpha_coverage_warning:{identity_label}:retention_flow:{detail}",
                            )
                        )
                if liquidity_retention_required(
                    output_paths["opening"],
                    identity,
                    listing,
                    current,
                ):
                    standalone_detail = standalone_liquidity_snapshot_issue(
                        output_paths["liquidity"]
                    )
                    liquidity_matching = [
                        candidate
                        for candidate in snapshot_rows(
                            output_paths["liquidity"]
                        )
                        if identity
                        in row_contract_identities(candidate, "liquidity")
                    ]
                    if standalone_detail:
                        liquidity_details = [standalone_detail]
                    elif not liquidity_matching:
                        liquidity_details = [
                            "standalone liquidity output does not match "
                            "official contract"
                        ]
                    else:
                        liquidity_details = [
                            detail
                            for detail in (
                                liquidity_retention_coverage_issue(candidate)
                                for candidate in liquidity_matching
                            )
                            if detail
                        ]
                    if liquidity_details:
                        detail = liquidity_details[0]
                        issues.append(
                            issue(
                                "alpha_coverage_gap",
                                symbol,
                                (
                                    f"{symbol} liquidity_retention: "
                                    f"{detail}"
                                ),
                                (
                                    f"alpha_coverage_gap:{identity_label}:"
                                    f"liquidity_retention:{detail}"
                                ),
                            )
                        )
                    else:
                        liquidity_warnings = [
                            detail
                            for detail in (
                                liquidity_retention_coverage_warning(
                                    candidate
                                )
                                for candidate in liquidity_matching
                            )
                            if detail
                        ]
                        if liquidity_warnings:
                            detail = liquidity_warnings[0]
                            warnings.append(
                                issue(
                                    "alpha_coverage_warning",
                                    symbol,
                                    (
                                        f"{symbol} liquidity_retention: "
                                        f"{detail}"
                                    ),
                                    (
                                        "alpha_coverage_warning:"
                                        f"{identity_label}:"
                                        "liquidity_retention:"
                                        f"{detail}"
                                    ),
                                )
                            )
            if output_name == "prelaunch":
                delivery_detail = prelaunch_delivery_issue(root, matching)
                if delivery_detail:
                    issues.append(
                        issue(
                            "alpha_coverage_gap",
                            symbol,
                            f"{symbol} prelaunch: {delivery_detail}",
                            f"alpha_coverage_gap:{identity_label}:prelaunch:delivery_receipt",
                        )
                    )
        historical_delivery_detail = historical_prelaunch_delivery_issue(
            root,
            row,
            current,
        )
        if historical_delivery_detail:
            legacy_warning = legacy_prelaunch_delivery_warning(
                row,
                historical_delivery_detail,
            )
            if legacy_warning:
                warnings.append(
                    issue(
                        "alpha_coverage_warning",
                        symbol,
                        f"{symbol} prelaunch: {legacy_warning}",
                        (
                            f"alpha_coverage_warning:{identity_label}:prelaunch:"
                            f"legacy_delivery_unverified:{PRELAUNCH_RECEIPT_POLICY_VERSION}"
                        ),
                    )
                )
            else:
                issues.append(
                    issue(
                        "alpha_coverage_gap",
                        symbol,
                        f"{symbol} prelaunch: {historical_delivery_detail}",
                        f"alpha_coverage_gap:{identity_label}:prelaunch:historical_delivery_receipt",
                    )
                )
    return issues, warnings


def alpha_coverage_issues(
    root: Path,
    *,
    current: datetime | None = None,
) -> list[dict[str, str]]:
    issues, _ = alpha_coverage_evaluation(root, current=current)
    return issues


def alpha_coverage_warnings(
    root: Path,
    *,
    current: datetime | None = None,
) -> list[dict[str, str]]:
    _, warnings = alpha_coverage_evaluation(root, current=current)
    return warnings


def signature_for(issues: list[dict[str, str]]) -> str:
    if not issues:
        return "healthy"
    stable = "\n".join(sorted(row.get("fingerprint", "") for row in issues))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def fast_lane_heartbeat_issues(
    out_dir: Path,
    max_age_seconds: int,
) -> tuple[list[dict[str, str]], dict[str, Any], int | None]:
    path = out_dir / "fast_lane_last_cycle.json"
    snapshot = read_json(path, {})
    if not path.exists() or not snapshot:
        return (
            [
                issue(
                    "missing_fast_lane_heartbeat",
                    "fast_lane",
                    "no completed fast-lane heartbeat exists",
                )
            ],
            {},
            None,
        )
    age_seconds = max(0, int(time.time() - path.stat().st_mtime))
    if age_seconds > max_age_seconds:
        return (
            [
                issue(
                    "stale_fast_lane_heartbeat",
                    "fast_lane",
                    (
                        f"last fast lane is {age_seconds}s old; "
                        f"limit is {max_age_seconds}s"
                    ),
                )
            ],
            snapshot,
            age_seconds,
        )
    rows = []
    if snapshot.get("status") != "healthy":
        for row in snapshot.get("issues", []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("command") or "fast_lane")
            detail = str(row.get("detail") or row.get("command") or "fast lane failed")
            rows.append(
                issue(
                    "fast_lane_unhealthy",
                    name,
                    detail,
                    f"fast_lane_unhealthy:{row.get('kind')}:{name}",
                )
            )
    return rows, snapshot, age_seconds


def build_cycle_snapshot(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    failed_steps = parse_failure_file(Path(args.failure_file) if args.failure_file else None)
    issues = [
        issue(
            "step_failed",
            row["command"],
            failed_step_detail(row),
            f"step_failed:{row['exit_status']}:{row['command']}",
        )
        for row in failed_steps
    ]
    freshness, freshness_issues = output_freshness(root, args.max_output_age_seconds)
    issues.extend(freshness_issues)
    fast_lane: dict[str, Any] = {}
    fast_lane_age_seconds: int | None = None
    if (root / "scripts" / "server_fast_lane.sh").exists():
        fast_lane_issues, fast_lane, fast_lane_age_seconds = (
            fast_lane_heartbeat_issues(
                root / "output" / "runtime_health",
                args.max_fast_lane_age_seconds,
            )
        )
        issues.extend(fast_lane_issues)
    issues.extend(verification_issues(root))
    issues.extend(project_scan_progress_issues(root))
    coverage_issues, warnings = alpha_coverage_evaluation(root)
    issues.extend(coverage_issues)
    return {
        "schema": "runtime_health.v1",
        "generated_at": now_iso(),
        "mode": "cycle",
        "cycle_started_at": args.started_at or "",
        "status": "healthy" if not issues else "unhealthy",
        "signature": signature_for(issues),
        "issue_count": len(issues),
        "issues": issues,
        "warning_count": len(warnings),
        "warnings": warnings,
        "failed_steps": failed_steps,
        "freshness": freshness,
        "fast_lane_generated_at": fast_lane.get("generated_at", ""),
        "fast_lane_age_seconds": fast_lane_age_seconds,
    }


def build_watchdog_snapshot(args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    last_cycle_path = out_dir / "last_cycle.json"
    last_cycle = read_json(last_cycle_path, {})
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    age_seconds: int | None = None
    if not last_cycle_path.exists() or not last_cycle:
        issues.append(issue("missing_heartbeat", "last_cycle", "no completed runtime cycle heartbeat exists"))
    else:
        age_seconds = max(0, int(time.time() - last_cycle_path.stat().st_mtime))
        if age_seconds > args.max_cycle_age_seconds:
            issues.append(
                issue(
                    "stale_heartbeat",
                    "last_cycle",
                    f"last completed cycle is {age_seconds}s old; limit is {args.max_cycle_age_seconds}s",
                )
            )
        elif last_cycle.get("status") == "unhealthy":
            issues.extend(last_cycle.get("issues", []))
        warnings.extend(last_cycle.get("warnings", []))
    fast_lane: dict[str, Any] = {}
    fast_lane_age_seconds: int | None = None
    if (Path(args.root).resolve() / "scripts" / "server_fast_lane.sh").exists():
        fast_lane_issues, fast_lane, fast_lane_age_seconds = (
            fast_lane_heartbeat_issues(
                out_dir,
                args.max_fast_lane_age_seconds,
            )
        )
        issues.extend(fast_lane_issues)
    return {
        "schema": "runtime_health.v1",
        "generated_at": now_iso(),
        "mode": "watchdog",
        "status": "healthy" if not issues else "unhealthy",
        "signature": signature_for(issues),
        "issue_count": len(issues),
        "issues": issues,
        "warning_count": len(warnings),
        "warnings": warnings,
        "last_cycle_generated_at": last_cycle.get("generated_at", ""),
        "last_cycle_age_seconds": age_seconds,
        "fast_lane_generated_at": fast_lane.get("generated_at", ""),
        "fast_lane_age_seconds": fast_lane_age_seconds,
    }


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def telegram_enabled(args: argparse.Namespace) -> bool:
    return (
        not args.no_telegram
        and os.environ.get("DISABLE_TELEGRAM", "0") != "1"
        and os.environ.get("RUNTIME_HEALTH_TELEGRAM", "1") == "1"
    )


def send_telegram(text: str, timeout: int) -> dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        return {"status": "skipped", "reason": "missing Telegram bot token or chat id"}
    payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return {"status": "sent", "message_id": (body.get("result") or {}).get("message_id")}
    except Exception as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}


def alert_text(snapshot: dict[str, Any]) -> str:
    lines = [
        "狙击系统健康告警",
        f"时间: {snapshot['generated_at']}",
        f"来源: {snapshot['mode']}",
        f"问题数: {snapshot['issue_count']}",
    ]
    for row in snapshot.get("issues", [])[:8]:
        lines.append(f"- {row.get('detail', '')[:260]}")
    if snapshot.get("issue_count", 0) > 8:
        lines.append(f"- 其余 {snapshot['issue_count'] - 8} 项见服务器 output/runtime_health/latest.json")
    lines.append("系统保持只读并会继续重试；本消息仅在故障、故障变化或持续提醒窗口触发。")
    return "\n".join(lines)


def recovery_text(snapshot: dict[str, Any]) -> str:
    warnings = snapshot.get("warnings") or []
    if warnings:
        lines = [
            "狙击系统阻断性故障已解除",
            f"时间: {snapshot['generated_at']}",
            f"仍有 {len(warnings)} 项非阻断覆盖告警；相关结论保持仅报告。",
        ]
        for row in warnings[:3]:
            lines.append(f"- {row.get('detail', '')[:260]}")
        return "\n".join(lines)
    return "\n".join(
        [
            "狙击系统已恢复",
            f"时间: {snapshot['generated_at']}",
            "最近一轮无失败，核心产物和自检报告均恢复正常。",
        ]
    )


def clear_active_incident(state: dict[str, Any]) -> None:
    for key in ("active_incident_signature", "incident_alert_attempted_at", "incident_alert_sent_at"):
        state.pop(key, None)


def apply_notification(snapshot: dict[str, Any], out_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    state_path = out_dir / "state.json"
    state = read_json(state_path, {})
    previous_status = state.get("last_status", "unknown")
    previous_signature = state.get("last_signature", "")

    notification: dict[str, Any] = {"status": "not_needed"}
    if snapshot["status"] == "unhealthy":
        if (
            previous_status == "unhealthy"
            and previous_signature == snapshot["signature"]
            and not state.get("active_incident_signature")
        ):
            state["active_incident_signature"] = snapshot["signature"]
            legacy_alert_at = state.get("last_alert_sent_at") or state.get("last_alert_attempted_at")
            if legacy_alert_at:
                state["incident_alert_attempted_at"] = legacy_alert_at
                if state.get("last_alert_sent_at"):
                    state["incident_alert_sent_at"] = state["last_alert_sent_at"]
        new_incident = (
            previous_status != "unhealthy"
            or previous_signature != snapshot["signature"]
            or state.get("active_incident_signature") != snapshot["signature"]
        )
        if new_incident:
            clear_active_incident(state)
            state["active_incident_signature"] = snapshot["signature"]
        previous_alert_at = parse_time(state.get("incident_alert_attempted_at"))
        repeat_due = previous_alert_at is None or (
            datetime.now(timezone.utc) - previous_alert_at
        ).total_seconds() >= args.repeat_minutes * 60
        should_send = new_incident or repeat_due
        if should_send:
            if telegram_enabled(args):
                state["last_alert_attempted_at"] = snapshot["generated_at"]
                state["incident_alert_attempted_at"] = snapshot["generated_at"]
                notification = send_telegram(alert_text(snapshot), args.telegram_timeout)
            else:
                notification = {"status": "disabled"}
            if notification.get("status") == "sent":
                state["last_alert_sent_at"] = snapshot["generated_at"]
                state["incident_alert_sent_at"] = snapshot["generated_at"]
        else:
            notification = {"status": "suppressed", "reason": "same issue signature inside repeat window"}
    elif state.get("active_incident_signature"):
        if not state.get("incident_alert_attempted_at"):
            clear_active_incident(state)
        elif os.environ.get("RUNTIME_HEALTH_SEND_RECOVERY", "1") != "1":
            clear_active_incident(state)
        elif telegram_enabled(args):
            state["last_recovery_attempted_at"] = snapshot["generated_at"]
            notification = send_telegram(recovery_text(snapshot), args.telegram_timeout)
            if notification.get("status") == "sent":
                state["last_recovery_sent_at"] = snapshot["generated_at"]
                clear_active_incident(state)
        else:
            notification = {"status": "disabled"}

    state.update(
        {
            "schema": "runtime_health_state.v1",
            "updated_at": snapshot["generated_at"],
            "last_status": snapshot["status"],
            "last_signature": snapshot["signature"],
            "last_notification": notification,
        }
    )
    write_json(state_path, state)
    return notification


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Runtime Health",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- mode: `{snapshot['mode']}`",
        f"- status: `{snapshot['status']}`",
        f"- issue_count: `{snapshot['issue_count']}`",
        f"- warning_count: `{snapshot.get('warning_count', 0)}`",
        f"- notification: `{(snapshot.get('notification') or {}).get('status', '')}`",
        "",
    ]
    if snapshot.get("issues"):
        lines.extend(["## Issues", ""])
        for row in snapshot["issues"]:
            lines.append(f"- `{row.get('kind')}` {row.get('detail')}")
    else:
        lines.append("- No runtime health issue detected.")
    if snapshot.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for row in snapshot["warnings"]:
            lines.append(f"- `{row.get('kind')}` {row.get('detail')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--root", default=str(ROOT))
    pre_args, _ = pre_parser.parse_known_args()
    load_local_env(Path(pre_args.root).resolve())

    parser = argparse.ArgumentParser(description="Detect sniper runtime failures and send deduplicated failure-only alerts.")
    parser.add_argument("--mode", choices=("cycle", "watchdog"), default="cycle")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--failure-file", default="")
    parser.add_argument("--started-at", default="")
    parser.add_argument("--max-output-age-seconds", type=int, default=int(os.environ.get("RUNTIME_HEALTH_MAX_OUTPUT_AGE_SECONDS", "1800")))
    parser.add_argument("--max-cycle-age-seconds", type=int, default=int(os.environ.get("RUNTIME_HEALTH_MAX_CYCLE_AGE_SECONDS", "1200")))
    parser.add_argument("--max-fast-lane-age-seconds", type=int, default=int(os.environ.get("RUNTIME_HEALTH_MAX_FAST_LANE_AGE_SECONDS", "240")))
    parser.add_argument("--repeat-minutes", type=int, default=int(os.environ.get("RUNTIME_HEALTH_REPEAT_MINUTES", "360")))
    parser.add_argument("--telegram-timeout", type=int, default=15)
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else root / "output" / "runtime_health"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / ".lock").open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        snapshot = build_cycle_snapshot(args, root) if args.mode == "cycle" else build_watchdog_snapshot(args, out_dir)
        snapshot["notification"] = apply_notification(snapshot, out_dir, args)
        write_json(out_dir / "latest.json", snapshot)
        (out_dir / "latest.md").write_text(render(snapshot), encoding="utf-8")
        if args.mode == "cycle":
            write_json(out_dir / "last_cycle.json", snapshot)
        else:
            write_json(out_dir / "latest_watchdog.json", snapshot)
    print(out_dir / "latest.json")
    print(f"status={snapshot['status']} issues={snapshot['issue_count']} notification={snapshot['notification'].get('status')}")
    return 1 if args.strict and snapshot["status"] != "healthy" else 0


if __name__ == "__main__":
    raise SystemExit(main())
