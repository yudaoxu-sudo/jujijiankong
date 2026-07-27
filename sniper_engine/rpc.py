from __future__ import annotations

import json
import os
import urllib.request
import time
from http.client import HTTPException
from urllib.error import HTTPError
from typing import Any

from sniper_engine.env import load_local_env


load_local_env()

DEFAULT_RPCS = {
    "bsc": "https://bsc-dataseed.binance.org/",
    "base": "https://mainnet.base.org",
}

DISABLED_NODE_REAL = False


class RpcHTTPError(RuntimeError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"rpc http {status}")


def rpc_url(chain: str) -> str:
    global DISABLED_NODE_REAL
    env_name = f"{chain.upper()}_RPC_URL"
    if os.environ.get(env_name):
        return os.environ[env_name]
    if chain == "bsc" and os.environ.get("NODEREAL_API_KEY") and not DISABLED_NODE_REAL:
        return f"https://bsc-mainnet.nodereal.io/v1/{os.environ['NODEREAL_API_KEY']}"
    return DEFAULT_RPCS[chain]


def rpc_urls(chain: str) -> list[str]:
    urls: list[str] = []
    env_name = f"{chain.upper()}_RPC_URL"
    if os.environ.get(env_name):
        urls.append(os.environ[env_name])
    if chain == "bsc" and os.environ.get("NODEREAL_API_KEY") and not DISABLED_NODE_REAL:
        urls.append(f"https://bsc-mainnet.nodereal.io/v1/{os.environ['NODEREAL_API_KEY']}")
    fallback_env = os.environ.get(f"{chain.upper()}_RPC_FALLBACK_URLS", "")
    urls.extend(url.strip() for url in fallback_env.split(",") if url.strip())
    urls.append(DEFAULT_RPCS[chain])
    deduped: list[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def rpc_call(chain: str, method: str, params: list[Any]) -> Any:
    global DISABLED_NODE_REAL
    errors: list[str] = []
    nodereal_key = os.environ.get("NODEREAL_API_KEY")
    nodereal_url = (
        f"https://bsc-mainnet.nodereal.io/v1/{nodereal_key}"
        if chain == "bsc" and nodereal_key and not DISABLED_NODE_REAL
        else None
    )
    # Snapshot the URL list once: disabling NodeReal mid-call shrinks rpc_urls()
    # and would otherwise cut the failover walk short of the remaining URLs.
    urls = rpc_urls(chain)
    for index, url in enumerate(urls):
        try:
            return rpc_call_url(url, method, params)
        except (HTTPError, RpcHTTPError) as exc:
            status = exc.code if isinstance(exc, HTTPError) else exc.status
            errors.append(f"{chain} rpc[{index + 1}] http {status}")
            if url == nodereal_url and status in {401, 403}:
                DISABLED_NODE_REAL = True
            if status in {401, 403, 429, 500, 502, 503, 504} and index + 1 < len(urls):
                if status == 429:
                    time.sleep(float(os.environ.get("RPC_429_BACKOFF_SECONDS", "0.25")))
                continue
            raise RuntimeError("; ".join(errors)) from None
        except RuntimeError:
            errors.append(f"{chain} rpc[{index + 1}] runtime_error")
            if index + 1 < len(urls):
                continue
            raise RuntimeError("; ".join(errors)) from None
    raise RuntimeError("; ".join(errors) or f"no rpc url for {chain}")


def rpc_call_url(url: str, method: str, params: list[Any], timeout: int = 30) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "sniper-monitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
        response = None
    except HTTPError as exc:
        raise RpcHTTPError(exc.code) from None
    # OSError covers URLError plus raw socket timeouts/resets surfaced while the
    # body is read; HTTPException covers truncated/invalid HTTP framing;
    # ValueError covers non-JSON 200 bodies and malformed URLs, whose native
    # messages would echo the endpoint. All become one sanitized, retryable error.
    except (OSError, HTTPException, ValueError):
        raise RuntimeError("rpc transport error") from None
    if not isinstance(data, dict):
        raise RuntimeError("rpc response shape error")
    if "error" in data and data["error"] is not None:
        # Provider error bodies are untrusted and may echo endpoint credentials.
        # Drop the parsed response before raising so the exception does not
        # retain the provider-supplied error body.
        data = {}
        raise RuntimeError("rpc response error")
    if "result" not in data or data["result"] is None:
        # A null/missing result is incomplete coverage for every RPC method used
        # by this project. Treat it as retryable so the next configured endpoint
        # gets a chance instead of letting callers mistake absence for evidence.
        raise RuntimeError("rpc null result")
    return data["result"]


def get_block_by_number(chain: str, block_number: int, full_transactions: bool = True) -> dict[str, Any]:
    result = rpc_call(chain, "eth_getBlockByNumber", [hex(block_number), full_transactions])
    if not result:
        raise RuntimeError(f"block not found: {chain} {block_number}")
    return result


def get_transaction_receipt(chain: str, tx_hash: str) -> dict[str, Any]:
    result = rpc_call(chain, "eth_getTransactionReceipt", [tx_hash])
    if not result:
        raise RuntimeError(f"receipt not found: {chain} {tx_hash}")
    return result


def hex_to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value, 16)
