#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "output" / "x_mcp_readiness"

X_MCP_DOC = "https://docs.x.com/tools/mcp.md"
X_DOCS_MCP_ENDPOINT = "https://docs.x.com/mcp"
X_API_MCP_ENDPOINT = "https://api.x.com/mcp"
XURL_PACKAGE = "@xdevplatform/xurl"

BEARER_ENV_NAMES = ("X_BEARER_TOKEN", "X_API_BEARER_TOKEN", "TWITTER_BEARER_TOKEN")
OAUTH_CLIENT_ID_NAMES = ("CLIENT_ID", "X_CLIENT_ID", "TWITTER_CLIENT_ID")
OAUTH_CLIENT_SECRET_NAMES = ("CLIENT_SECRET", "X_CLIENT_SECRET", "TWITTER_CLIENT_SECRET")


def bool_env(names: tuple[str, ...]) -> bool:
    return any(bool(os.environ.get(name)) for name in names)


def bundled_runtime_candidates() -> tuple[list[Path], list[Path]]:
    base = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    return (
        [
            Path.home() / ".local" / "bin" / "node",
            base / "node" / "bin" / "node",
        ],
        [
            Path.home() / ".local" / "bin" / "pnpm",
            base / "bin" / "pnpm",
        ],
    )


def resolve_executable(name: str, bundled: list[Path]) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in bundled:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run_command(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> dict[str, object]:
    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "elapsed_sec": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": None,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": "timeout",
            "elapsed_sec": round(time.time() - started, 3),
        }


def fetch_url(url: str, timeout: int) -> dict[str, object]:
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "sniper-x-mcp-readiness/1.0",
            "Accept": "text/plain, application/json, */*",
        },
    )
    started = time.time()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
            return {
                "url": url,
                "ok": True,
                "status": response.status,
                "body_excerpt": body[:2000],
                "elapsed_sec": round(time.time() - started, 3),
            }
    except HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        return {
            "url": url,
            "ok": False,
            "status": exc.code,
            "body_excerpt": body[:2000],
            "elapsed_sec": round(time.time() - started, 3),
        }
    except URLError as exc:
        return {
            "url": url,
            "ok": False,
            "status": None,
            "body_excerpt": "",
            "error": str(exc.reason),
            "elapsed_sec": round(time.time() - started, 3),
        }


def xurl_env(node_path: str | None, pnpm_path: str | None) -> dict[str, str]:
    env = os.environ.copy()
    prefixes: list[str] = []
    if node_path:
        prefixes.append(str(Path(node_path).parent))
    if pnpm_path:
        prefixes.append(str(Path(pnpm_path).parent))
    if prefixes:
        env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    return env


def collect(args: argparse.Namespace) -> dict[str, object]:
    node_candidates, pnpm_candidates = bundled_runtime_candidates()
    node_path = resolve_executable("node", node_candidates)
    pnpm_path = resolve_executable("pnpm", pnpm_candidates)

    has_bearer = bool_env(BEARER_ENV_NAMES)
    has_oauth_client_id = bool_env(OAUTH_CLIENT_ID_NAMES)
    has_oauth_client_secret = bool_env(OAUTH_CLIENT_SECRET_NAMES)
    has_oauth_pair = has_oauth_client_id and has_oauth_client_secret

    network: dict[str, object] = {"skipped": args.no_network}
    if not args.no_network:
        docs = fetch_url(X_MCP_DOC, args.timeout)
        docs_mcp = fetch_url(X_DOCS_MCP_ENDPOINT, args.timeout)
        api_mcp = fetch_url(X_API_MCP_ENDPOINT, args.timeout)
        docs_body = str(docs.get("body_excerpt", ""))
        network.update(
            {
                "x_mcp_doc": docs,
                "docs_mcp_endpoint": docs_mcp,
                "api_mcp_endpoint": api_mcp,
                "x_mcp_doc_has_expected_terms": all(
                    term in docs_body
                    for term in (
                        "https://api.x.com/mcp",
                        "https://docs.x.com/mcp",
                        "xurl",
                    )
                ),
                "docs_mcp_endpoint_reachable": docs_mcp.get("status") in (200, 405)
                or "Method not allowed" in str(docs_mcp.get("body_excerpt", "")),
                "api_mcp_endpoint_reachable": api_mcp.get("status") is not None,
            }
        )

    xurl: dict[str, object] = {
        "skipped": args.skip_xurl,
        "node_path": node_path,
        "pnpm_path": pnpm_path,
        "xurl_package": XURL_PACKAGE,
    }
    if not args.skip_xurl:
        if not node_path or not pnpm_path:
            xurl["available"] = False
            xurl["error"] = "node_or_pnpm_missing"
        else:
            env = xurl_env(node_path, pnpm_path)
            xurl_timeout = max(args.timeout, 60)
            version = run_command([pnpm_path, "dlx", XURL_PACKAGE, "version"], xurl_timeout, env=env)
            help_result = run_command([pnpm_path, "dlx", XURL_PACKAGE, "--help"], xurl_timeout, env=env)
            mcp_help = run_command([pnpm_path, "dlx", XURL_PACKAGE, "mcp", "--help"], xurl_timeout, env=env)
            help_text = f"{help_result.get('stdout', '')}\n{help_result.get('stderr', '')}"
            mcp_text = f"{mcp_help.get('stdout', '')}\n{mcp_help.get('stderr', '')}"
            xurl.update(
                {
                    "available": version.get("returncode") == 0,
                    "version": version,
                    "help_has_mcp": "mcp" in help_text.lower(),
                    "mcp_help_mentions_mcp": "mcp" in mcp_text.lower(),
                    "mcp_help": mcp_help,
                }
            )

    doc_ok = bool(network.get("x_mcp_doc_has_expected_terms")) if not args.no_network else None
    xurl_available = bool(xurl.get("available")) if not args.skip_xurl else None
    xurl_mcp_clear = bool(xurl.get("help_has_mcp") or xurl.get("mcp_help_mentions_mcp")) if not args.skip_xurl else None

    if args.no_network and args.skip_xurl:
        status = "offline_probe"
    elif doc_ok is False:
        status = "x_mcp_docs_unreachable"
    elif has_bearer:
        status = "ready_for_app_only_probe"
    elif has_oauth_pair and xurl_available:
        status = "ready_for_oauth_login"
    elif xurl_available and xurl_mcp_clear is False:
        status = "xurl_installed_mcp_ambiguous"
    else:
        status = "needs_x_credentials"

    return {
        "schema": "x_mcp_readiness.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": status,
        "official_sources": {
            "announcement": "https://x.com/xdevelopers/status/2071752389183647758",
            "x_mcp_doc": X_MCP_DOC,
            "docs_mcp_endpoint": X_DOCS_MCP_ENDPOINT,
            "api_mcp_endpoint": X_API_MCP_ENDPOINT,
        },
        "credentials": {
            "has_bearer_token": has_bearer,
            "has_oauth_client_id": has_oauth_client_id,
            "has_oauth_client_secret": has_oauth_client_secret,
            "has_oauth_pair": has_oauth_pair,
            "checked_env_names": {
                "bearer": BEARER_ENV_NAMES,
                "client_id": OAUTH_CLIENT_ID_NAMES,
                "client_secret": OAUTH_CLIENT_SECRET_NAMES,
            },
        },
        "runtime": {
            "python": sys.executable,
            "node": node_path,
            "pnpm": pnpm_path,
        },
        "network": network,
        "xurl": xurl,
    }


def render_markdown(payload: dict[str, object]) -> str:
    credentials = payload["credentials"]
    runtime = payload["runtime"]
    xurl = payload["xurl"]
    network = payload["network"]
    lines = [
        "# X MCP Readiness",
        "",
        f"- Status: `{payload['status']}`",
        f"- Generated: `{payload['generated_at']}`",
        f"- Official X MCP doc: {payload['official_sources']['x_mcp_doc']}",
        f"- X API MCP endpoint: {payload['official_sources']['api_mcp_endpoint']}",
        f"- Docs MCP endpoint: {payload['official_sources']['docs_mcp_endpoint']}",
        "",
        "## Credentials",
        "",
        f"- Bearer token present: `{credentials['has_bearer_token']}`",
        f"- OAuth client id present: `{credentials['has_oauth_client_id']}`",
        f"- OAuth client secret present: `{credentials['has_oauth_client_secret']}`",
        f"- OAuth pair present: `{credentials['has_oauth_pair']}`",
        "",
        "## Runtime",
        "",
        f"- Python: `{runtime['python']}`",
        f"- Node: `{runtime['node']}`",
        f"- pnpm: `{runtime['pnpm']}`",
        f"- xurl available: `{xurl.get('available')}`",
        f"- xurl help mentions mcp: `{xurl.get('help_has_mcp')}`",
        f"- xurl mcp help mentions mcp: `{xurl.get('mcp_help_mentions_mcp')}`",
        "",
        "## Network",
        "",
        f"- Network skipped: `{network.get('skipped')}`",
        f"- X MCP doc has expected terms: `{network.get('x_mcp_doc_has_expected_terms')}`",
        f"- Docs MCP endpoint reachable: `{network.get('docs_mcp_endpoint_reachable')}`",
        f"- X API MCP endpoint reachable: `{network.get('api_mcp_endpoint_reachable')}`",
        "",
        "## Operator Action",
        "",
        "- If status is `needs_x_credentials`, create an X Developer app and provide env vars on the server, not in chat.",
        "- For read-only app-only mode, use one bearer env var: `X_BEARER_TOKEN`, `X_API_BEARER_TOKEN`, or `TWITTER_BEARER_TOKEN`.",
        "- For OAuth bridge mode, set `CLIENT_ID` and `CLIENT_SECRET`; the default callback URL in X docs is `http://localhost:8080/callback`.",
        "- Re-run this probe after credentials are installed.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local readiness for official X MCP integration.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for latest.json and latest.md")
    parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    parser.add_argument("--no-network", action="store_true", help="Skip network checks")
    parser.add_argument("--skip-xurl", action="store_true", help="Skip xurl runtime checks")
    parser.add_argument("--print-json", action="store_true", help="Print JSON payload to stdout")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = collect(args)
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "latest.md").write_text(render_markdown(payload), encoding="utf-8")
    if args.print_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"x_mcp_readiness status={payload['status']} output={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
