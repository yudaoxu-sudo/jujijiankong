#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import alpha_liquidity_retention_watch as liquidity_watch
    from scripts import binance_alpha_catalog_watch as alpha_catalog
except ModuleNotFoundError:
    import alpha_liquidity_retention_watch as liquidity_watch
    import binance_alpha_catalog_watch as alpha_catalog


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "runtime_health"
HEARTBEAT_PATH = OUT_DIR / "fast_lane_last_cycle.json"
REPORT_PATH = OUT_DIR / "fast_lane_last_cycle.md"
CORE_OUTPUTS = (
    ("catalog", ROOT / "output" / "binance_alpha_catalog_watch" / "latest.json"),
    ("prelaunch", ROOT / "output" / "alpha_prelaunch_watch" / "latest.json"),
    ("prediction", ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json"),
    ("perp", ROOT / "output" / "perp_oi_funding_watch" / "latest.json"),
    ("price", ROOT / "output" / "alpha_price_momentum_watch" / "latest.json"),
    (
        "liquidity",
        ROOT / "output" / "alpha_liquidity_retention_watch" / "latest.json",
    ),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_failures(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    failures = []
    for line in path.read_text(encoding="utf-8").splitlines():
        status, seconds, command = (line.split("\t", 2) + ["", "", ""])[:3]
        failures.append(
            {
                "kind": "step_failed",
                "status": status,
                "timeout_seconds": seconds,
                "command": command,
            }
        )
    return failures


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def airdrop_identity_hash(rows: list[dict[str, Any]]) -> str:
    canonical = sorted(
        (
            str(row.get("symbol") or "").upper(),
            str(row.get("contract") or "").lower(),
            str(row.get("event_id") or ""),
        )
        for row in rows
    )
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def liquidity_output_issue(path: Path) -> str:
    payload = read_json(path)
    if payload.get("schema") != "alpha_liquidity_retention_watch.v1":
        return "liquidity output schema invalid"
    try:
        issue_count = int(payload.get("issue_count") or 0)
        required_count = int(payload.get("required_count") or 0)
        complete_count = int(payload.get("complete_count") or 0)
        expected_count = int(payload["expected_count"])
        processed_count = int(payload["processed_count"])
        dropped_count = int(payload["dropped_count"])
    except (KeyError, TypeError, ValueError):
        return "liquidity output counters invalid"
    if payload.get("status") != "healthy" or issue_count:
        return "liquidity fast scan unhealthy"
    if payload.get("delivery_status") != "complete":
        return "liquidity alert delivery incomplete"
    if min(required_count, complete_count) < 0:
        return "liquidity output counters invalid"
    if complete_count != required_count:
        return "liquidity required coverage incomplete"
    expected_hash = str(payload.get("expected_identity_hash") or "")
    processed_hash = str(payload.get("processed_identity_hash") or "")
    if (
        min(expected_count, processed_count, dropped_count) < 0
        or dropped_count
        or expected_count != processed_count
        or expected_hash != processed_hash
        or len(expected_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_hash)
    ):
        return "liquidity eligible identity coverage incomplete"
    return ""


def prelaunch_output_issue(
    path: Path,
    expected_identity_hash: str = "",
) -> str:
    payload = read_json(path)
    if payload.get("schema") != "alpha_prelaunch_watch.v2":
        return "prelaunch output schema invalid"
    launch_events = payload.get("events")
    airdrop_events = payload.get("airdrop_pressure_events")
    if not isinstance(launch_events, list) or not all(
        isinstance(event, dict) for event in launch_events
    ):
        return "prelaunch output events invalid"
    if not isinstance(airdrop_events, list) or not all(
        isinstance(event, dict) for event in airdrop_events
    ):
        return "prelaunch output airdrop events invalid"
    required_count = payload.get("airdrop_pressure_required_count")
    observed_count = payload.get("airdrop_pressure_event_count")
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in (required_count, observed_count)
    ):
        return "prelaunch airdrop counters invalid"
    if (
        any(event.get("event_kind") == "airdrop_pressure" for event in launch_events)
        or any(
            event.get("event_kind") != "airdrop_pressure"
            for event in airdrop_events
        )
        or observed_count != len(airdrop_events)
        or observed_count != required_count
    ):
        return "prelaunch airdrop coverage incomplete"
    reported_expected_hash = str(
        payload.get("airdrop_pressure_expected_identity_hash") or ""
    )
    reported_processed_hash = str(
        payload.get("airdrop_pressure_processed_identity_hash") or ""
    )
    if (
        len(reported_expected_hash) != 64
        or len(reported_processed_hash) != 64
        or reported_expected_hash != reported_processed_hash
        or reported_processed_hash != airdrop_identity_hash(airdrop_events)
        or (
            expected_identity_hash
            and reported_expected_hash != expected_identity_hash
        )
    ):
        return "prelaunch airdrop identity coverage incomplete"
    allowed_states = {
        "time_unverified",
        "not_yet",
        "in_window",
        "ended_pressure_unresolved",
        "passed",
    }
    event_ids = [str(event.get("event_id") or "").strip() for event in airdrop_events]
    if len(event_ids) != len(set(event_ids)):
        return "prelaunch airdrop event ids duplicate"
    for event in airdrop_events:
        if (
            not str(event.get("event_id") or "").strip()
            or event.get("event_id_source") != "configured"
            or event.get("reminder_state") not in allowed_states
            or event.get("automatic_trading") is not False
            or not isinstance(event.get("issue_codes"), list)
            or not all(
                isinstance(code, str) and code
                for code in event["issue_codes"]
            )
            or (
                event.get("reminder_state") == "time_unverified"
                and event.get("alert_policy") != "report_only"
            )
            or (
                event.get("alert_policy") == "notify"
                and (
                    event.get("schedule_evidence_status") != "verified"
                    or event.get("evidence_resolution_status") != "resolved"
                )
            )
            or (
                event.get("reminder_state") == "passed"
                and (
                    event.get("clearance_state") != "verified"
                    or event.get("issue_codes") != []
                )
            )
        ):
            return "prelaunch airdrop event invalid"
    return ""


def effective_watchlist_path() -> Path:
    configured = os.environ.get("ALPHA_WATCHLIST_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    generated = (
        ROOT
        / "output"
        / "binance_alpha_catalog_watch"
        / "current_watchlist.json"
    )
    if generated.exists():
        return generated
    return ROOT / "config" / "current_alpha_watchlist.json"


def airdrop_watchlist_path() -> Path:
    return ROOT / "config" / "current_alpha_watchlist.json"


def configured_airdrop_identity_hash() -> tuple[str, str]:
    payload = read_json(airdrop_watchlist_path())
    identities: list[dict[str, Any]] = []
    event_ids: list[str] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("active_monitoring") is False:
            continue
        if not str(item.get("priority") or "").startswith(("P0", "P1")):
            continue
        contract = next(
            (
                str(row.get("address") or "")
                for row in item.get("contracts", [])
                if isinstance(row, dict) and row.get("address")
            ),
            "",
        )
        for row in item.get("event_schedule", []):
            if not isinstance(row, dict) or str(
                row.get("event_type") or ""
            ).lower() not in {"airdrop_claim", "airdrop_release"}:
                continue
            event_id = str(row.get("event_id") or "").strip()
            event_ids.append(event_id)
            identities.append(
                {
                    "symbol": item.get("symbol"),
                    "contract": contract,
                    "event_id": event_id,
                }
            )
    if not event_ids or any(not value for value in event_ids):
        return "", "configured airdrop event identity missing"
    if len(event_ids) != len(set(event_ids)):
        return "", "configured airdrop event identity duplicate"
    return airdrop_identity_hash(identities), ""


def monitoring_scope_issue(liquidity_path: Path) -> str:
    watchlist_path = effective_watchlist_path()
    watchlist = read_json(watchlist_path)
    static_path = ROOT / "config" / "current_alpha_watchlist.json"
    static_watchlist = read_json(static_path)
    try:
        policy = alpha_catalog.normalized_monitoring_policy(static_watchlist)
    except ValueError:
        return "curated Alpha monitoring policy invalid"
    if not policy:
        return "curated Alpha monitoring policy missing"
    focused = set(policy["symbols"])
    if alpha_catalog.active_monitoring_symbols(static_watchlist) != focused:
        return "curated Alpha active symbols do not match the exclusive focus"
    if watchlist_path.resolve() == static_path.resolve():
        compatible = True
    else:
        compatible = alpha_catalog.watchlist_policy_compatible(
            watchlist,
            static_watchlist,
        )
        try:
            max_age_seconds = int(
                os.environ.get(
                    "BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS",
                    "21600",
                )
            )
            age_seconds = max(
                0,
                int(time.time() - watchlist_path.stat().st_mtime),
            )
        except (OSError, ValueError):
            return "runtime Alpha watchlist freshness invalid"
        if max_age_seconds < 1 or age_seconds > max_age_seconds:
            return "runtime Alpha watchlist is stale"
    if not compatible:
        return "runtime Alpha watchlist does not match the curated focus"
    if alpha_catalog.active_monitoring_symbols(watchlist) != focused:
        return "Alpha active symbols do not match the exclusive focus"
    expected_items, selection_issues = liquidity_watch.eligible_contract_items(
        watchlist
    )
    if selection_issues:
        return "Alpha focused identity selection invalid"
    expected_hash = liquidity_watch.stable_identity_hash(expected_items)
    liquidity_payload = read_json(liquidity_path)
    if liquidity_payload.get("expected_identity_hash") != expected_hash:
        return "liquidity identity set does not match the focused watchlist"
    return ""


def output_checks(max_age_seconds: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues = []
    rows = []
    current = time.time()
    for name, path in CORE_OUTPUTS:
        if not path.exists():
            issues.append(
                {
                    "kind": "missing_fast_output",
                    "name": name,
                    "detail": f"{name} output missing",
                }
            )
            rows.append({"name": name, "exists": False, "age_seconds": None})
            continue
        age = max(0, int(current - path.stat().st_mtime))
        rows.append({"name": name, "exists": True, "age_seconds": age})
        if age > max_age_seconds:
            issues.append(
                {
                    "kind": "stale_fast_output",
                    "name": name,
                    "detail": f"{name} output age {age}s exceeds {max_age_seconds}s",
                }
            )
        if name == "prelaunch":
            detail = prelaunch_output_issue(path)
            if not detail:
                expected_hash, detail = configured_airdrop_identity_hash()
                if not detail:
                    detail = prelaunch_output_issue(path, expected_hash)
            if detail:
                issues.append(
                    {
                        "kind": "invalid_fast_output",
                        "name": name,
                        "detail": detail,
                    }
                )
        if name == "liquidity":
            detail = liquidity_output_issue(path)
            if detail:
                issues.append(
                    {
                        "kind": "invalid_fast_output",
                        "name": name,
                        "detail": detail,
                    }
                )
            scope_detail = monitoring_scope_issue(path)
            if scope_detail:
                issues.append(
                    {
                        "kind": "invalid_fast_output",
                        "name": name,
                        "detail": scope_detail,
                    }
                )
    return issues, rows


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Fast Lane Health",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- started_at: `{snapshot.get('started_at', '')}`",
        f"- status: `{snapshot['status']}`",
        f"- issue_count: `{snapshot['issue_count']}`",
        "",
    ]
    for row in snapshot.get("outputs", []):
        lines.append(
            f"- {row['name']}: exists={row['exists']} age_seconds={row['age_seconds']}"
        )
    for row in snapshot.get("issues", []):
        lines.append(f"- issue `{row.get('kind')}`: {row.get('detail') or row.get('command')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure-file", default="")
    parser.add_argument("--started-at", default="")
    parser.add_argument(
        "--max-output-age-seconds",
        type=int,
        default=int(os.environ.get("FAST_LANE_MAX_OUTPUT_AGE_SECONDS", "240")),
    )
    args = parser.parse_args()

    failure_path = Path(args.failure_file) if args.failure_file else None
    failures = read_failures(failure_path)
    output_issues, outputs = output_checks(args.max_output_age_seconds)
    issues = failures + output_issues
    snapshot = {
        "schema": "sniper_fast_lane_health.v1",
        "generated_at": now_iso(),
        "started_at": args.started_at,
        "status": "healthy" if not issues else "unhealthy",
        "issue_count": len(issues),
        "issues": issues,
        "outputs": outputs,
    }
    atomic_write_json(HEARTBEAT_PATH, snapshot)
    REPORT_PATH.write_text(render(snapshot), encoding="utf-8")
    print(HEARTBEAT_PATH)
    print(f"status={snapshot['status']} issues={snapshot['issue_count']}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
