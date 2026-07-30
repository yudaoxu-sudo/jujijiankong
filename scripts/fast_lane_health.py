#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
