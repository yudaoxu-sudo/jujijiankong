#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "external_aux_sources.json"
OUT_DIR = ROOT / "output" / "external_aux_live_probe"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def secret_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def http_json(url: str, headers: dict[str, str], params: dict[str, Any] | None = None, timeout: int = 12) -> dict[str, Any]:
    target = url
    if params:
        target += "?" + urllib.parse.urlencode(params)
    safe_headers = {
        "User-Agent": "sniper-external-aux-live-probe/1.0",
        "Accept": "application/json,text/plain,*/*",
    }
    safe_headers.update(headers)
    started = time.time()
    request = Request(target, headers=safe_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(1_000_000).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw_excerpt": body[:1000]}
            return {
                "ok": 200 <= response.status < 400,
                "http_status": response.status,
                "payload": payload,
                "elapsed_sec": round(time.time() - started, 3),
            }
    except HTTPError as exc:
        body = exc.read(100_000).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "http_status": exc.code,
            "payload": safe_json_excerpt(body),
            "elapsed_sec": round(time.time() - started, 3),
        }
    except (URLError, OSError) as exc:
        return {
            "ok": False,
            "http_status": None,
            "payload": {"error": str(getattr(exc, "reason", exc))},
            "elapsed_sec": round(time.time() - started, 3),
        }


def safe_json_excerpt(body: str) -> dict[str, Any]:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_excerpt": body[:1000]}


def summarize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return {"data_type": "list", "data_count": len(data), "top_keys": sorted(payload.keys())[:12]}
        if isinstance(data, dict):
            return {"data_type": "object", "data_count": len(data), "top_keys": sorted(payload.keys())[:12]}
        return {"data_type": type(data).__name__, "data_count": 0, "top_keys": sorted(payload.keys())[:12]}
    if isinstance(payload, list):
        return {"data_type": "list", "data_count": len(payload), "top_keys": []}
    return {"data_type": type(payload).__name__, "data_count": 0, "top_keys": []}


def coinglass_probe(timeout: int) -> dict[str, Any]:
    key_name = "COINGLASS_API_KEY"
    if not secret_present(key_name):
        return missing_credentials("coinglass", [key_name])
    url = os.environ.get(
        "COINGLASS_PROBE_URL",
        "https://open-api-v4.coinglass.com/api/futures/supported-exchange-pairs",
    )
    result = http_json(url, {"CG-API-KEY": os.environ[key_name]}, timeout=timeout)
    payload = result.get("payload")
    ok = bool(result.get("ok")) and not str((payload or {}).get("code", "0")).startswith(("4", "401"))
    return probe_result("coinglass", ok, result, "Set AUX_SOURCE_VALIDATED_COINGLASS=1 only after BTC/USDT pair data is plausible.")


def coinank_probe(timeout: int) -> dict[str, Any]:
    key_name = "COINANK_API_KEY"
    if not secret_present(key_name):
        return missing_credentials("coinank", [key_name])
    url = os.environ.get("COINANK_PROBE_URL", "https://open-api.coinank.com/api/tickers/topOIByEx")
    result = http_json(url, {"apikey": os.environ[key_name]}, timeout=timeout)
    payload = result.get("payload")
    success = True
    if isinstance(payload, dict) and "success" in payload:
        success = bool(payload.get("success"))
    ok = bool(result.get("ok")) and success
    return probe_result("coinank", ok, result, "Set AUX_SOURCE_VALIDATED_COINANK=1 only after top OI rows match current market scale.")


def gmgn_probe(timeout: int) -> dict[str, Any]:
    key_name = "GMGN_API_KEY"
    if not secret_present(key_name):
        return missing_credentials("gmgn", [key_name])
    url = os.environ.get("GMGN_PROBE_URL", "").strip()
    if not url:
        return {
            "id": "gmgn",
            "status": "key_present_probe_url_needed",
            "ok": False,
            "missing_env": [],
            "summary": {
                "reason": "GMGN_API_KEY is present, but GMGN_PROBE_URL is not configured for a read-only query endpoint.",
                "expected_header": os.environ.get("GMGN_API_KEY_HEADER", "x-route-key"),
            },
            "next_step": "Provide a read-only GMGN Agent/API endpoint or set GMGN_PROBE_URL after confirming the account permissions.",
        }
    header = os.environ.get("GMGN_API_KEY_HEADER", "x-route-key")
    result = http_json(url, {header: os.environ[key_name]}, timeout=timeout)
    ok = bool(result.get("ok"))
    return probe_result("gmgn", ok, result, "Set AUX_SOURCE_VALIDATED_GMGN=1 only after wallet/token fields reconcile with local labels.")


def surf_probe(timeout: int) -> dict[str, Any]:
    return {
        "id": "surf",
        "status": "handled_by_surf_aux_market_watch",
        "ok": True,
        "missing_env": [],
        "summary": {"reason": "Surf validation is covered by scripts/surf_aux_market_watch.py and quota_state handling."},
        "next_step": "Use SURF_AUX_MAX_PROJECTS=1 python3 scripts/surf_aux_market_watch.py for a paid/credit-aware live check.",
    }


def missing_credentials(source_id: str, names: list[str]) -> dict[str, Any]:
    return {
        "id": source_id,
        "status": "needs_credentials",
        "ok": False,
        "missing_env": names,
        "summary": {},
        "next_step": "Configure " + ",".join(names) + " in server .env.local, then rerun this probe.",
    }


def probe_result(source_id: str, ok: bool, result: dict[str, Any], next_step: str) -> dict[str, Any]:
    payload = result.get("payload")
    return {
        "id": source_id,
        "status": "probe_ok" if ok else "probe_failed",
        "ok": ok,
        "missing_env": [],
        "http_status": result.get("http_status"),
        "elapsed_sec": result.get("elapsed_sec"),
        "summary": summarize_payload(payload),
        "error": error_summary(payload) if not ok else "",
        "next_step": next_step if ok else "Check key, plan permission, IP whitelist, endpoint path, and rate limits before enabling validation env.",
    }


def error_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("msg", "message", "error", "retMsg", "raw_excerpt"):
            if payload.get(key):
                return str(payload.get(key))[:240]
    return str(payload)[:240]


PROBERS = {
    "coinglass": coinglass_probe,
    "coinank": coinank_probe,
    "gmgn": gmgn_probe,
    "surf": surf_probe,
}


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(Path(args.config), {"sources": []})
    wanted = {item.strip() for item in args.source.split(",") if item.strip()} if args.source else set(PROBERS)
    rows = []
    for source in config.get("sources", []):
        source_id = str(source.get("id") or "")
        if source_id not in wanted or source_id not in PROBERS:
            continue
        row = PROBERS[source_id](args.timeout)
        row["name"] = source.get("name", source_id)
        row["category"] = source.get("category", "")
        row["validation_env"] = source.get("validation_env", "")
        row["authority_after_validation"] = "auxiliary_signal"
        rows.append(row)
    return {
        "schema": "external_aux_live_probe.v1",
        "generated_at": now_iso(),
        "mode": "read_only_no_trade_execution",
        "source_count": len(rows),
        "ok_count": sum(1 for row in rows if row.get("ok")),
        "rows": rows,
    }


def md_cell(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# External Auxiliary Live Probe",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- mode: `{snapshot['mode']}`",
        f"- source_count: `{snapshot['source_count']}`",
        f"- ok_count: `{snapshot['ok_count']}`",
        "",
        "| Source | Status | HTTP | Summary | Validation env | Next step |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for row in snapshot["rows"]:
        summary = row.get("summary") or {}
        summary_text = ", ".join(f"{key}={value}" for key, value in summary.items()) or row.get("error", "")
        lines.append(
            f"| {md_cell(row.get('name') or row.get('id'))} | `{row.get('status')}` | "
            f"{row.get('http_status', '')} | {md_cell(summary_text)} | `{row.get('validation_env', '')}` | {md_cell(row.get('next_step'))} |"
        )
    lines.extend(
        [
            "",
            "- Passing this probe does not create buy/sell authority by itself. The source still needs local rule confirmation.",
            "- Do not paste API keys into chat or commit them to git.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run small read-only live probes for external auxiliary sources.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--source", default="", help="Comma-separated source ids: coinglass,coinank,gmgn,surf")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    snapshot = build_snapshot(args)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "latest.json", snapshot)
    (out_dir / "latest.md").write_text(render(snapshot), encoding="utf-8")
    print(out_dir / "latest.json")
    print(out_dir / "latest.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
