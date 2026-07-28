#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

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
        age_seconds = max(0, int(current - path.stat().st_mtime))
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
    if output_name == "holder":
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
    if output_name == "project":
        contracts = [item for item in row.get("contracts", []) if isinstance(item, dict)]
        if target_contract:
            contracts = [
                item
                for item in contracts
                if str(item.get("address") or "").lower() == target_contract.lower()
            ]
        if not contracts:
            return "project contract missing"
        if any(
            item.get("error") or int(item.get("log_error_count") or 0)
            for item in contracts
        ):
            return "project contract scan has errors"
        states = {
            str(item.get("operator_attribution_state") or "")
            for item in contracts
        }
        if "contract_error" in states:
            return "project operator attribution contract error"
        unresolved = states & {
            "owner_unresolved",
            "conflicting_owner_selectors",
            "unresolved",
        }
        if unresolved:
            return "project operator attribution unresolved=" + ",".join(
                sorted(unresolved)
            )
    elif output_name == "opening":
        if row.get("status") == "opened":
            traces = [
                item.get("buyer_trace") or {}
                for item in row.get("rows", [])
                if isinstance(item, dict)
            ]
            if any(trace.get("status") == "trace_failed" for trace in traces):
                return "opening buyer trace failed"
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
                return "opening buyer trace coverage incomplete"
        elif row.get("status") not in {"waiting", "opened"}:
            return f"opening status={row.get('status', 'missing')}"
    elif output_name == "intraday":
        if row.get("status") != "scanned":
            return f"intraday status={row.get('status', 'missing')}"
        analysis = row.get("analysis") or {}
        if analysis.get("scan_limited"):
            return "intraday receipt scan limited"
        coverage = row.get("transfer_coverage") or {}
        if coverage.get("state") != "requested_window_complete" or coverage.get("complete") is not True:
            return f"intraday transfer coverage={coverage.get('state', 'missing')}"
    elif output_name == "price":
        analysis = row.get("analysis") or {}
        if analysis.get("direction") == "数据缺口":
            return "price layer data gap"
    elif output_name == "holder":
        if int(row.get("log_error_count") or 0) or row.get("truncated"):
            return "holder scan incomplete"
    return ""


def output_row_coverage_warning(
    output_name: str,
    row: dict[str, Any],
    target_contract: str = "",
) -> str:
    if output_name == "opening" and row.get("status") == "opened":
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
            return "opening buyer trace coverage incomplete"
        return ""
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
    return generated


def alpha_coverage_evaluation(
    root: Path,
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
    dropped_count = int(catalog.get("dropped_count") or 0)
    if dropped_count:
        dropped_rows = [
            row for row in catalog.get("dropped", []) if isinstance(row, dict)
        ]
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
    selected = [
        row
        for row in catalog.get("selected", [])
        if isinstance(row, dict) and row.get("symbol")
    ]
    if not selected:
        return issues, warnings
    runtime_contracts = runtime_watchlist_contracts(
        effective_runtime_watchlist_path(root)
    )
    current = parse_time(catalog.get("generated_at")) or datetime.now(timezone.utc)
    output_paths = {
        "project": root / "output" / "alpha_project_watch" / "latest.json",
        "prelaunch": root / "output" / "alpha_prelaunch_watch" / "latest.json",
        "opening": root / "output" / "alpha_opening_block_watch" / "latest.json",
        "intraday": root / "output" / "alpha_intraday_flow_watch" / "latest.json",
        "price": root / "output" / "alpha_price_momentum_watch" / "latest.json",
        "holder": root / "output" / "alpha_holder_concentration_watch" / "latest.json",
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
                    f"{symbol} is in the official recent Alpha catalog but missing from the runtime watchlist",
                    f"alpha_coverage_gap:{identity_label}:runtime_watchlist",
                )
            )
            continue
        required_outputs = ["project", "price", "holder"]
        listing = parse_time(row.get("listing_time_utc"))
        if chain == "bsc":
            required_outputs.append("opening")
            if listing is not None and listing > current:
                required_outputs.append("prelaunch")
            else:
                required_outputs.append("intraday")
        for output_name in required_outputs:
            candidates = snapshot_rows(output_paths[output_name])
            matching = [
                candidate
                for candidate in candidates
                if identity in row_contract_identities(candidate, output_name)
            ]
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
            detail = output_row_coverage_issue(
                output_name,
                matching[0],
                target_contract=contract,
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
            warning_detail = output_row_coverage_warning(
                output_name,
                matching[0],
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
    return issues, warnings


def alpha_coverage_issues(root: Path) -> list[dict[str, str]]:
    issues, _ = alpha_coverage_evaluation(root)
    return issues


def alpha_coverage_warnings(root: Path) -> list[dict[str, str]]:
    _, warnings = alpha_coverage_evaluation(root)
    return warnings


def signature_for(issues: list[dict[str, str]]) -> str:
    if not issues:
        return "healthy"
    stable = "\n".join(sorted(row.get("fingerprint", "") for row in issues))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


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
    issues.extend(verification_issues(root))
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
