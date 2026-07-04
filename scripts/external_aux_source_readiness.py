#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "external_aux_sources.json"
DEFAULT_OUT_DIR = ROOT / "output" / "external_aux_sources"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def docs_probe(url: str, timeout: int) -> dict[str, Any]:
    if not url:
        return {"checked": False, "ok": False, "status": None, "error": "missing_url"}
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "sniper-external-aux-source-readiness/1.0",
            "Accept": "text/html,text/plain,application/json,*/*",
        },
    )
    started = time.time()
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(4096)
            return {
                "checked": True,
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "elapsed_sec": round(time.time() - started, 3),
            }
    except HTTPError as exc:
        return {
            "checked": True,
            "ok": False,
            "status": exc.code,
            "error": "http_error",
            "elapsed_sec": round(time.time() - started, 3),
        }
    except URLError as exc:
        return {
            "checked": True,
            "ok": False,
            "status": None,
            "error": str(exc.reason),
            "elapsed_sec": round(time.time() - started, 3),
        }


def source_status(source: dict[str, Any], check_http: bool, timeout: int) -> dict[str, Any]:
    required_env = [str(item) for item in source.get("required_env", [])]
    present_env = [name for name in required_env if bool(os.environ.get(name))]
    missing_env = [name for name in required_env if name not in present_env]
    validation_env = str(source.get("validation_env", ""))
    live_probe_validated = bool_env(validation_env) if validation_env else False
    integration_mode = str(source.get("integration_mode", ""))

    if integration_mode in {"manual_or_web"}:
        status = "manual_context_only"
    elif missing_env:
        status = "needs_credentials"
    elif live_probe_validated:
        status = "validated_for_auxiliary_signals"
    else:
        status = "ready_for_live_probe"

    can_affect_trade_action = status == "validated_for_auxiliary_signals"
    docs = {"checked": False}
    if check_http:
        docs = docs_probe(str(source.get("docs_url") or source.get("official_url") or ""), timeout)

    return {
        "id": source.get("id", ""),
        "name": source.get("name", ""),
        "category": source.get("category", ""),
        "priority": source.get("priority", 99),
        "integration_mode": integration_mode,
        "status": status,
        "required_env": required_env,
        "present_env_count": len(present_env),
        "missing_env": missing_env,
        "validation_env": validation_env,
        "live_probe_validated": live_probe_validated,
        "can_affect_trade_action": can_affect_trade_action,
        "authority": "auxiliary_signal" if can_affect_trade_action else "context_only",
        "capabilities": source.get("capabilities", []),
        "target_use": source.get("target_use", []),
        "official_url": source.get("official_url", ""),
        "docs_url": source.get("docs_url", ""),
        "docs_probe": docs,
        "next_step": next_step(source, missing_env, live_probe_validated, integration_mode),
    }


def next_step(source: dict[str, Any], missing_env: list[str], live_probe_validated: bool, integration_mode: str) -> str:
    if integration_mode == "manual_or_web":
        return "use screenshots_exports_or_forwarded_alerts_as_context; keep out of direct action rules"
    if missing_env:
        return "configure " + ",".join(missing_env)
    if not live_probe_validated:
        return "run a small live probe and set validation env only after output matches local rules"
    return "eligible for auxiliary signal use; still requires local rule confirmation"


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(Path(args.config))
    rows = [
        source_status(source, args.check_http, args.timeout)
        for source in sorted(config.get("sources", []), key=lambda item: int(item.get("priority", 99)))
    ]
    return {
        "schema": "external_aux_source_readiness.v1",
        "generated_at": now_iso(),
        "config_schema": config.get("schema", ""),
        "rules": config.get("rules", {}),
        "source_count": len(rows),
        "ready_for_live_probe_count": sum(1 for row in rows if row["status"] == "ready_for_live_probe"),
        "validated_count": sum(1 for row in rows if row["live_probe_validated"]),
        "needs_credentials_count": sum(1 for row in rows if row["status"] == "needs_credentials"),
        "manual_context_count": sum(1 for row in rows if row["status"] == "manual_context_only"),
        "rows": rows,
    }


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# External Auxiliary Source Readiness",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- sources: `{snapshot['source_count']}`",
        f"- needs_credentials: `{snapshot['needs_credentials_count']}`",
        f"- ready_for_live_probe: `{snapshot['ready_for_live_probe_count']}`",
        f"- validated: `{snapshot['validated_count']}`",
        "",
        "## Rule",
        "",
        "- Third-party sources enrich context first.",
        "- A source can affect action text only after credentials, live probe validation, and local rule confirmation.",
        "- Manual or web-only sources stay as evidence notes.",
        "",
        "| Source | Category | Status | Authority | Missing env | Next step |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in snapshot["rows"]:
        missing = ",".join(row.get("missing_env") or [])
        lines.append(
            f"| {clean(row.get('name'))} | {clean(row.get('category'))} | `{clean(row.get('status'))}` | "
            f"`{clean(row.get('authority'))}` | `{clean(missing)}` | {clean(row.get('next_step'))} |"
        )
    lines.extend(["", "## Sources", ""])
    for row in snapshot["rows"]:
        lines.append(f"- {clean(row.get('name'))}: {row.get('docs_url') or row.get('official_url')}")
    lines.append("")
    return "\n".join(lines)


def clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check readiness of external auxiliary market/on-chain data sources.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--check-http", action="store_true", default=os.environ.get("AUX_SOURCE_CHECK_HTTP") == "1")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(args)
    (out_dir / "latest.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "latest.md").write_text(render_markdown(snapshot), encoding="utf-8")
    print(f"external_aux_source_readiness output={out_dir} sources={snapshot['source_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
