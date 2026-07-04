from __future__ import annotations

import json
import os
import urllib.request
import time
from urllib.error import HTTPError, URLError
from typing import Any

from sniper_engine.env import load_local_env


load_local_env()

DEFAULT_RPCS = {
    "bsc": "https://bsc-dataseed.binance.org/",
    "base": "https://mainnet.base.org",
}

DISABLED_NODE_REAL = False


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
    for index, url in enumerate(rpc_urls(chain)):
        try:
            return rpc_call_url(url, method, params)
        except HTTPError as exc:
            errors.append(f"{exc.code} {url}")
            if chain == "bsc" and os.environ.get("NODEREAL_API_KEY") and exc.code in {401, 403}:
                DISABLED_NODE_REAL = True
            if exc.code in {401, 403, 429, 500, 502, 503, 504} and index + 1 < len(rpc_urls(chain)):
                if exc.code == 429:
                    time.sleep(float(os.environ.get("RPC_429_BACKOFF_SECONDS", "0.25")))
                continue
            raise
        except RuntimeError as exc:
            errors.append(str(exc))
            if index + 1 < len(rpc_urls(chain)):
                continue
            raise RuntimeError("; ".join(errors)) from exc
    raise RuntimeError("; ".join(errors) or f"no rpc url for {chain}")


def rpc_call_url(url: str, method: str, params: list[Any], timeout: int = 30) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "sniper-monitor/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
    except HTTPError:
        raise
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")


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
