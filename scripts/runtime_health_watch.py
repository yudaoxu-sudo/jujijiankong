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
                "command": command[:500],
            }
        )
    return rows


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
            f"exit={row['exit_status']} timeout={row['timeout_seconds']}s command={row['command']}",
            f"step_failed:{row['exit_status']}:{row['command']}",
        )
        for row in failed_steps
    ]
    freshness, freshness_issues = output_freshness(root, args.max_output_age_seconds)
    issues.extend(freshness_issues)
    issues.extend(verification_issues(root))
    return {
        "schema": "runtime_health.v1",
        "generated_at": now_iso(),
        "mode": "cycle",
        "cycle_started_at": args.started_at or "",
        "status": "healthy" if not issues else "unhealthy",
        "signature": signature_for(issues),
        "issue_count": len(issues),
        "issues": issues,
        "failed_steps": failed_steps,
        "freshness": freshness,
    }


def build_watchdog_snapshot(args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    last_cycle_path = out_dir / "last_cycle.json"
    last_cycle = read_json(last_cycle_path, {})
    issues: list[dict[str, str]] = []
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
    return {
        "schema": "runtime_health.v1",
        "generated_at": now_iso(),
        "mode": "watchdog",
        "status": "healthy" if not issues else "unhealthy",
        "signature": signature_for(issues),
        "issue_count": len(issues),
        "issues": issues,
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


def apply_notification(snapshot: dict[str, Any], out_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    state_path = out_dir / "state.json"
    state = read_json(state_path, {})
    previous_status = state.get("last_status", "unknown")
    previous_signature = state.get("last_signature", "")
    previous_alert_at = parse_time(state.get("last_alert_sent_at"))
    repeat_due = previous_alert_at is None or (
        datetime.now(timezone.utc) - previous_alert_at
    ).total_seconds() >= args.repeat_minutes * 60

    notification: dict[str, Any] = {"status": "not_needed"}
    if snapshot["status"] == "unhealthy":
        should_send = previous_status != "unhealthy" or previous_signature != snapshot["signature"] or repeat_due
        if should_send:
            notification = send_telegram(alert_text(snapshot), args.telegram_timeout) if telegram_enabled(args) else {"status": "disabled"}
            if notification.get("status") == "sent":
                state["last_alert_sent_at"] = snapshot["generated_at"]
        else:
            notification = {"status": "suppressed", "reason": "same issue signature inside repeat window"}
    elif previous_status == "unhealthy" and state.get("last_alert_sent_at") and os.environ.get("RUNTIME_HEALTH_SEND_RECOVERY", "1") == "1":
        notification = send_telegram(recovery_text(snapshot), args.telegram_timeout) if telegram_enabled(args) else {"status": "disabled"}
        if notification.get("status") == "sent":
            state["last_recovery_sent_at"] = snapshot["generated_at"]

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
        f"- notification: `{(snapshot.get('notification') or {}).get('status', '')}`",
        "",
    ]
    if snapshot.get("issues"):
        lines.extend(["## Issues", ""])
        for row in snapshot["issues"]:
            lines.append(f"- `{row.get('kind')}` {row.get('detail')}")
    else:
        lines.append("- No runtime health issue detected.")
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
