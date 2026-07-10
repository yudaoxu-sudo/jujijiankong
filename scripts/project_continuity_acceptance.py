#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "project_continuity.json"

REMOTE_PROBE = r"""
import json
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
max_age = int(sys.argv[2])

def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

health_path = root / "output" / "runtime_health" / "last_cycle.json"
health = read_json(health_path)
age = max(0, int(time.time() - health_path.stat().st_mtime)) if health_path.exists() else None
verification_path = root / "output" / "sniper_engine" / "verification_report.md"
try:
    verification_text = verification_path.read_text(encoding="utf-8", errors="replace")
except OSError:
    verification_text = ""
fail_count = sum(1 for line in verification_text.splitlines() if "| FAIL |" in line)
watchlist = read_json(root / "config" / "current_alpha_watchlist.json")
item_count = len(watchlist.get("items", [])) if isinstance(watchlist.get("items", []), list) else 0
ok = (
    health.get("schema") == "runtime_health.v1"
    and health.get("status") == "healthy"
    and age is not None
    and age <= max_age
    and verification_path.exists()
    and fail_count == 0
    and item_count > 0
)
print(json.dumps({
    "schema": "sniper_remote_health_acceptance.v1",
    "status": "pass" if ok else "fail",
    "runtime_status": health.get("status", "missing"),
    "runtime_generated_at": health.get("generated_at", ""),
    "runtime_age_seconds": age,
    "runtime_issue_count": health.get("issue_count"),
    "verification_exists": verification_path.exists(),
    "verification_fail_count": fail_count,
    "watchlist_item_count": item_count,
}, ensure_ascii=False))
""".strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run_json(command: list[str], cwd: Path, timeout: int = 30) -> tuple[dict[str, Any], str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return {}, detail[:500] or f"exit={result.returncode}"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON output: {exc}"
    if not isinstance(value, dict):
        return {}, "command returned a non-object JSON value"
    return value, ""


def git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def collect_repository(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    head = git_lines(root, "rev-parse", "HEAD")[0]
    branch = git_lines(root, "branch", "--show-current")
    status = git_lines(root, "status", "--short")
    tracked = set(git_lines(root, "ls-files"))
    required = [str(item) for item in policy.get("tracked_required_paths", [])]
    denied_globs = [str(item) for item in policy.get("denied_git_globs", [])]
    denied_exceptions = {str(item) for item in policy.get("denied_git_exceptions", [])}
    return {
        "head": head,
        "branch": branch[0] if branch else "",
        "dirty": bool(status),
        "status_lines": status,
        "missing_tracked_required": [path for path in required if path not in tracked or not (root / path).is_file()],
        "tracked_denied_paths": sorted(
            path for path in tracked if path_matches_any(path, denied_globs) and path not in denied_exceptions
        ),
        "tracked_paths": tracked,
    }


def path_matches_any(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        fnmatch.fnmatchcase(normalized, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(normalized, pattern[3:]))
        for pattern in patterns
    )


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def context_boundary_violations(
    config: dict[str, Any],
    config_path: Path,
    project_root: Path,
    tracked_paths: set[str],
    policy: dict[str, Any],
) -> list[str]:
    external_roots = [Path(str(item)).expanduser().resolve() for item in policy.get("external_context_roots", [])]
    violations: list[str] = []
    for row in config.get("context_files", []):
        if not isinstance(row, dict) or not row.get("path"):
            violations.append("invalid context_files entry")
            continue
        candidate = Path(str(row["path"])).expanduser()
        resolved = (config_path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if is_within(resolved, project_root):
            relative = resolved.relative_to(project_root).as_posix()
            if relative not in tracked_paths:
                violations.append(f"project context is not Git-tracked: {relative}")
        elif not any(is_within(resolved, root) for root in external_roots):
            violations.append(f"external context is outside approved roots: {resolved}")
    return violations


def summarize_local_runtime(root: Path) -> dict[str, Any]:
    health_path = root / "output" / "runtime_health" / "last_cycle.json"
    try:
        health = read_json(health_path)
    except (OSError, ValueError, json.JSONDecodeError):
        health = {}
    age = max(0, int(time.time() - health_path.stat().st_mtime)) if health_path.exists() else None

    verification_path = root / "output" / "sniper_engine" / "verification_report.md"
    try:
        verification_text = verification_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        verification_text = ""
    fail_count = sum(1 for line in verification_text.splitlines() if "| FAIL |" in line)

    watchlist_path = root / "config" / "current_alpha_watchlist.json"
    try:
        watchlist = read_json(watchlist_path)
    except (OSError, ValueError, json.JSONDecodeError):
        watchlist = {}
    items = watchlist.get("items", [])
    return {
        "runtime_status": health.get("status", "missing"),
        "runtime_generated_at": health.get("generated_at", ""),
        "runtime_age_seconds": age,
        "runtime_issue_count": health.get("issue_count"),
        "verification_exists": verification_path.exists(),
        "verification_fail_count": fail_count,
        "watchlist_item_count": len(items) if isinstance(items, list) else 0,
    }


def build_remote_command(config_path: Path, remote: dict[str, Any]) -> list[str]:
    host = str(remote.get("host", ""))
    remote_root = str(remote.get("project_root", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+", host) or not remote_root.startswith("/"):
        raise ValueError("remote_health requires host and absolute project_root")
    identity = (config_path.parent / str(remote.get("identity_file", ""))).resolve()
    known_hosts = (config_path.parent / str(remote.get("known_hosts_file", ""))).resolve()
    if not identity.is_file() or not known_hosts.is_file():
        raise FileNotFoundError("remote SSH identity or known-hosts file is missing")
    max_age = int(remote.get("max_cycle_age_seconds", 1200))
    remote_command = " ".join(
        [
            "python3",
            "-c",
            shlex.quote(REMOTE_PROBE),
            shlex.quote(remote_root),
            str(max_age),
        ]
    )
    return [
        "ssh",
        "-i",
        str(identity),
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=8",
        host,
        remote_command,
    ]


def issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def evaluate(snapshot: dict[str, Any], allow_dirty: bool, remote_required: bool) -> dict[str, Any]:
    issues = [issue("command_error", detail) for detail in snapshot.pop("command_errors", [])]
    advisories: list[dict[str, str]] = []
    continuity = snapshot["continuity"]
    repository = snapshot["repository"]
    local_runtime = snapshot["local_runtime"]

    severity = continuity.get("severity")
    if severity not in {"healthy", "warning"}:
        issues.append(issue("continuity_severity", f"severity={severity or 'missing'}"))
    elif severity == "warning":
        advisories.append(issue("rotation_warning", "task crossed a warning threshold; use the verified checkpoint for the next task"))
    if not continuity.get("checkpoint_id") or not continuity.get("checkpoint_hash_valid"):
        issues.append(issue("checkpoint_invalid", "latest checkpoint is missing or its hash is invalid"))
    if continuity.get("audit_status") != "pass" or int(continuity.get("audit_failed_count") or 0) != 0:
        issues.append(issue("audit_failed", f"audit_status={continuity.get('audit_status', 'missing')}"))
    if not continuity.get("checkpoint_matches_head"):
        issues.append(issue("checkpoint_stale", "latest checkpoint Git head does not match the working repository"))

    if repository.get("dirty") and not allow_dirty:
        issues.append(issue("git_dirty", "working tree has uncommitted changes"))
    for path in repository.get("missing_tracked_required", []):
        issues.append(issue("required_path_missing", path))
    for path in repository.get("tracked_denied_paths", []):
        issues.append(issue("denied_path_tracked", path))
    for detail in repository.get("context_boundary_violations", []):
        issues.append(issue("context_boundary", detail))

    if local_runtime.get("verification_fail_count", 0) > 0:
        issues.append(issue("local_verification_failed", f"FAIL rows={local_runtime['verification_fail_count']}"))
    if not local_runtime.get("verification_exists"):
        issues.append(issue("local_verification_missing", "local verification report is missing"))
    if local_runtime.get("watchlist_item_count", 0) <= 0:
        issues.append(issue("watchlist_empty", "current Alpha watchlist has no items"))
    if not remote_required and local_runtime.get("runtime_status") != "healthy":
        issues.append(issue("local_runtime_unhealthy", f"status={local_runtime.get('runtime_status', 'missing')}"))

    remote_runtime = snapshot.get("remote_runtime", {"status": "not_requested"})
    if remote_required and remote_runtime.get("status") != "pass":
        issues.append(issue("remote_runtime_failed", f"status={remote_runtime.get('status', 'missing')}"))

    snapshot["status"] = "pass" if not issues else "fail"
    snapshot["issues"] = issues
    snapshot["advisories"] = advisories
    return snapshot


def clean_markdown(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    continuity = payload["continuity"]
    repository = payload["repository"]
    local_runtime = payload["local_runtime"]
    remote_runtime = payload.get("remote_runtime", {})
    lines = [
        "# Project Continuity Acceptance",
        "",
        f"- Status: **{payload['status'].upper()}**",
        f"- Generated: `{payload['generated_at']}`",
        f"- Project: `{payload['project_id']}`",
        "",
        "## Continuity",
        "",
        "| Check | Value |",
        "| --- | --- |",
        f"| Severity | {clean_markdown(continuity.get('severity'))} |",
        f"| Conversation | {clean_markdown(continuity.get('conversation_id'))} |",
        f"| Checkpoint | {clean_markdown(continuity.get('checkpoint_id'))} |",
        f"| Checkpoint hash | {'valid' if continuity.get('checkpoint_hash_valid') else 'invalid'} |",
        f"| Checkpoint matches Git | {bool(continuity.get('checkpoint_matches_head'))} |",
        f"| Audit | {clean_markdown(continuity.get('audit_status'))} |",
        "",
        "## Repository And Runtime",
        "",
        "| Check | Value |",
        "| --- | --- |",
        f"| Git branch | {clean_markdown(repository.get('branch'))} |",
        f"| Git head | {clean_markdown(repository.get('head'))} |",
        f"| Git dirty | {bool(repository.get('dirty'))} |",
        f"| Tracked denied paths | {len(repository.get('tracked_denied_paths', []))} |",
        f"| Local runtime | {clean_markdown(local_runtime.get('runtime_status'))} |",
        f"| Local verification FAIL rows | {clean_markdown(local_runtime.get('verification_fail_count'))} |",
        f"| Watchlist items | {clean_markdown(local_runtime.get('watchlist_item_count'))} |",
        f"| Remote acceptance | {clean_markdown(remote_runtime.get('status', 'not_requested'))} |",
        "",
        "## Issues",
        "",
    ]
    if payload["issues"]:
        lines.extend(f"- `{row['code']}`: {clean_markdown(row['detail'])}" for row in payload["issues"])
    else:
        lines.append("- None")
    lines.extend(["", "## Advisories", ""])
    if payload["advisories"]:
        lines.extend(f"- `{row['code']}`: {clean_markdown(row['detail'])}" for row in payload["advisories"])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    markdown_path = output_dir / "latest.md"
    write_text_atomic(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    write_text_atomic(markdown_path, render_markdown(payload))
    return json_path, markdown_path


def write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify that the sniper project can be resumed safely in a fresh Codex task.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--remote", action="store_true", help="also verify the deployed server heartbeat and verification report")
    parser.add_argument("--allow-dirty", action="store_true", help="report, but do not fail on, an intentionally dirty worktree")
    parser.add_argument("--output-dir", help="override the configured report directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = read_json(config_path)
    policy = config.get("acceptance", {})
    if policy.get("schema") != "sniper_project_acceptance_policy.v1":
        print("missing or invalid acceptance policy", file=sys.stderr)
        return 2
    project_root = Path(str(config["project_root"])).expanduser().resolve()
    wrapper = project_root / "scripts" / "project_continuity_local.py"
    base_command = [sys.executable, str(wrapper)]
    commands = {
        "check": [*base_command, "check", "--config", str(config_path), "--no-checkpoint"],
        "resume": [*base_command, "resume", "--config", str(config_path), "--json"],
        "audit": [*base_command, "audit", "--config", str(config_path)],
    }
    results: dict[str, dict[str, Any]] = {}
    command_errors: list[str] = []
    for name, command in commands.items():
        value, error = run_json(command, project_root)
        results[name] = value
        if error:
            command_errors.append(f"{name}: {error}")

    try:
        repository = collect_repository(project_root, policy)
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        repository = {
            "head": "",
            "branch": "",
            "dirty": True,
            "status_lines": [],
            "missing_tracked_required": [],
            "tracked_denied_paths": [],
            "tracked_paths": set(),
        }
        command_errors.append(f"git: {exc}")
    repository["context_boundary_violations"] = context_boundary_violations(
        config,
        config_path,
        project_root,
        repository["tracked_paths"],
        policy,
    )
    repository.pop("tracked_paths", None)

    check = results.get("check", {})
    resume = results.get("resume", {})
    audit = results.get("audit", {})
    checkpoint_head = resume.get("checkpoint", {}).get("git", {}).get("head", "")
    snapshot: dict[str, Any] = {
        "schema": "sniper_project_continuity_acceptance.v1",
        "generated_at": now_iso(),
        "project_id": config.get("project_id", ""),
        "continuity": {
            "severity": check.get("severity", "missing"),
            "reasons": check.get("reasons", []),
            "conversation_id": check.get("metrics", {}).get("conversation_id", ""),
            "checkpoint_id": resume.get("checkpoint_id", ""),
            "checkpoint_hash_valid": bool(resume.get("checkpoint_hash_valid")),
            "checkpoint_git_head": checkpoint_head,
            "checkpoint_matches_head": bool(checkpoint_head and checkpoint_head == repository.get("head")),
            "audit_status": audit.get("status", "missing"),
            "audit_failed_count": audit.get("failed_count"),
        },
        "repository": repository,
        "local_runtime": summarize_local_runtime(project_root),
        "remote_runtime": {"status": "not_requested"},
        "command_errors": command_errors,
    }

    if args.remote:
        try:
            remote_command = build_remote_command(config_path, policy.get("remote_health", {}))
            remote_payload, remote_error = run_json(remote_command, project_root, timeout=30)
            snapshot["remote_runtime"] = remote_payload or {"status": "error"}
            if remote_error:
                snapshot["command_errors"].append(f"remote: {remote_error}")
        except (OSError, TypeError, ValueError) as exc:
            snapshot["remote_runtime"] = {"status": "error"}
            snapshot["command_errors"].append(f"remote: {exc}")

    payload = evaluate(snapshot, allow_dirty=args.allow_dirty, remote_required=args.remote)
    configured_output = Path(str(policy.get("output_dir", "../output/project_continuity_acceptance"))).expanduser()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else configured_output
    if not output_dir.is_absolute():
        output_dir = (config_path.parent / output_dir).resolve()
    json_path, markdown_path = write_outputs(output_dir, payload)
    print(json.dumps({"status": payload["status"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
