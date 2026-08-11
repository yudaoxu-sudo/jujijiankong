from __future__ import annotations

import json
import os
import urllib.request
import time
from http.client import HTTPException
from urllib.error import HTTPError
from typing import Any, Callable

from sniper_engine.env import load_local_env


load_local_env()

DEFAULT_RPCS = {
    "bsc": "https://bsc-dataseed.bnbchain.org/",
    "base": "https://mainnet.base.org",
}

LOG_CAPABLE_PUBLIC_RPCS = {
    "bsc": (
        "https://bsc.rpc.blxrbdn.com",
        "https://bsc-rpc.publicnode.com",
    ),
}
READ_CAPABLE_PUBLIC_RPCS = {
    "bsc": (
        "https://bsc-dataseed-public.bnbchain.org/",
        *LOG_CAPABLE_PUBLIC_RPCS["bsc"],
    ),
}

DISABLED_NODE_REAL = False
DISABLED_RPC_URLS: set[str] = set()
LOG_SPLIT_HTTP_STATUSES = {400, 413, 422}
READ_ONLY_RPC_METHODS = {
    "debug_traceCall",
    "eth_blockNumber",
    "eth_call",
    "eth_getBlockByNumber",
    "eth_getCode",
    "eth_getStorageAt",
    "eth_getTransactionByHash",
    "eth_getTransactionReceipt",
    "nr_getAssetTransfers",
    "web3_sha3",
}


class RpcHTTPError(RuntimeError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"rpc http {status}")


class LogCoverageError(RuntimeError):
    def __init__(self, start: int | str, end: int | str, status: int | None = None) -> None:
        self.start = start
        self.end = end
        self.status = status
        super().__init__(f"eth_getLogs coverage failed for {start}-{end}")


class RpcDeadlineExceeded(TimeoutError):
    pass


def deadline_timeout(timeout: int | float, deadline: float | None) -> float:
    if deadline is None:
        return float(timeout)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RpcDeadlineExceeded("rpc deadline exceeded")
    return max(0.1, min(float(timeout), remaining))


def rpc_url(chain: str) -> str:
    global DISABLED_NODE_REAL
    env_name = f"{chain.upper()}_RPC_URL"
    if os.environ.get(env_name):
        return os.environ[env_name]
    if chain == "bsc" and os.environ.get("NODEREAL_API_KEY") and not DISABLED_NODE_REAL:
        return f"https://bsc-mainnet.nodereal.io/v1/{os.environ['NODEREAL_API_KEY']}"
    return DEFAULT_RPCS[chain]


def rpc_urls(chain: str, method: str | None = None) -> list[str]:
    urls: list[str] = []
    env_name = f"{chain.upper()}_RPC_URL"
    if os.environ.get(env_name):
        urls.append(os.environ[env_name])
    nodereal_url = (
        f"https://bsc-mainnet.nodereal.io/v1/{os.environ['NODEREAL_API_KEY']}"
        if chain == "bsc"
        and os.environ.get("NODEREAL_API_KEY")
        and not DISABLED_NODE_REAL
        else None
    )
    fallback_env = os.environ.get(f"{chain.upper()}_RPC_FALLBACK_URLS", "")
    configured_fallbacks = [
        url.strip()
        for url in fallback_env.split(",")
        if url.strip()
    ]
    if method == "eth_getLogs" and chain in LOG_CAPABLE_PUBLIC_RPCS:
        urls.extend(configured_fallbacks)
        urls.extend(LOG_CAPABLE_PUBLIC_RPCS[chain])
        if nodereal_url:
            urls.append(nodereal_url)
    else:
        if nodereal_url:
            urls.append(nodereal_url)
        urls.extend(configured_fallbacks)
        urls.append(DEFAULT_RPCS[chain])
        urls.extend(READ_CAPABLE_PUBLIC_RPCS.get(chain, ()))
    deduped: list[str] = []
    for url in urls:
        if url not in DISABLED_RPC_URLS and url not in deduped:
            deduped.append(url)
    return deduped


def adaptive_get_logs(
    query: dict[str, Any],
    fetch: Callable[[dict[str, Any]], Any],
    max_attempts: int = 256,
    max_split_depth: int = 4,
    max_transport_split_depth: int = 3,
    before_attempt: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    from_value = query.get("fromBlock")
    to_value = query.get("toBlock")
    symbolic_latest = from_value == to_value == "latest"
    if symbolic_latest:
        from_block: int | str = "latest"
        to_block: int | str = "latest"
    else:
        try:
            from_block = int(from_value, 16)
            to_block = int(to_value, 16)
        except (TypeError, ValueError):
            raise RuntimeError("eth_getLogs coverage query invalid") from None
        if from_block > to_block:
            return []

    pending = [(from_block, to_block, 0, 0)]
    rows: list[dict[str, Any]] = []
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    attempts = 0
    while pending:
        if before_attempt is not None:
            before_attempt()
        start, end, split_depth, transport_split_depth = pending.pop()
        if attempts >= max_attempts:
            raise LogCoverageError(start, end) from None
        attempts += 1
        chunk_query = dict(query)
        chunk_query["fromBlock"] = hex(start) if isinstance(start, int) else start
        chunk_query["toBlock"] = hex(end) if isinstance(end, int) else end
        try:
            result = fetch(chunk_query)
            if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                raise RuntimeError("invalid log response")
        except RpcDeadlineExceeded:
            raise
        except Exception as exc:
            status = (
                exc.code
                if isinstance(exc, HTTPError)
                else exc.status if isinstance(exc, RpcHTTPError) else None
            )
            transport_error = isinstance(exc, RuntimeError) and str(exc) == "rpc transport error"
            splittable = (
                status in LOG_SPLIT_HTTP_STATUSES
                if status is not None
                else isinstance(exc, RuntimeError)
                and str(exc) not in {
                    "rpc response shape error",
                    "rpc null result",
                }
            )
            if transport_error:
                splittable = transport_split_depth < max_transport_split_depth
            if start == end or split_depth >= max_split_depth or not splittable:
                raise LogCoverageError(start, end, status) from None
            if not isinstance(start, int) or not isinstance(end, int):
                raise LogCoverageError(start, end, status) from None
            midpoint = (start + end) // 2
            next_split_depth = split_depth + 1
            next_transport_depth = transport_split_depth + 1 if transport_error else transport_split_depth
            pending.append((midpoint + 1, end, next_split_depth, next_transport_depth))
            pending.append((start, midpoint, next_split_depth, next_transport_depth))
            continue
        for row in result:
            tx_hash = row.get("transactionHash")
            log_index = row.get("logIndex")
            try:
                identity = (
                    (str(tx_hash).lower(), int(str(log_index), 16))
                    if tx_hash not in (None, "") and log_index not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                identity = None
            if identity is None:
                rows.append(row)
                continue
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = row
                rows.append(row)
            elif previous != row:
                raise LogCoverageError(start, end) from None
    return rows


def rpc_call(
    chain: str,
    method: str,
    params: list[Any],
    timeout: int = 30,
    deadline: float | None = None,
) -> Any:
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
    urls = rpc_urls(chain, method)
    if method == "eth_getLogs":
        if len(params) != 1 or not isinstance(params[0], dict):
            raise RuntimeError("eth_getLogs coverage query invalid")
        last_coverage_error: LogCoverageError | None = None
        for index, url in enumerate(urls):
            deadline_timeout(timeout, deadline)
            try:
                return adaptive_get_logs(
                    params[0],
                    lambda query, endpoint=url: rpc_call_url(
                        endpoint,
                        method,
                        [query],
                        timeout=deadline_timeout(timeout, deadline),
                    ),
                    before_attempt=lambda: deadline_timeout(timeout, deadline),
                )
            except RpcDeadlineExceeded:
                raise
            except LogCoverageError as exc:
                last_coverage_error = exc
                errors.append(f"{chain} rpc[{index + 1}] log_coverage_error")
                if url == nodereal_url and exc.status in {401, 403}:
                    DISABLED_NODE_REAL = True
                if exc.status == 429:
                    DISABLED_RPC_URLS.add(url)
                    if index + 1 < len(urls):
                        backoff = float(
                            os.environ.get("RPC_429_BACKOFF_SECONDS", "0.25")
                        )
                        time.sleep(
                            min(
                                backoff,
                                deadline_timeout(backoff, deadline),
                            )
                        )
                continue
        if last_coverage_error is not None:
            raise LogCoverageError(
                last_coverage_error.start,
                last_coverage_error.end,
                last_coverage_error.status,
            ) from None
        raise RuntimeError("; ".join(errors) or f"no rpc url for {chain}") from None

    for index, url in enumerate(urls):
        request_timeout = deadline_timeout(timeout, deadline)
        try:
            return rpc_call_url(
                url,
                method,
                params,
                timeout=request_timeout,
            )
        except (HTTPError, RpcHTTPError) as exc:
            status = exc.code if isinstance(exc, HTTPError) else exc.status
            errors.append(f"{chain} rpc[{index + 1}] http {status}")
            if url == nodereal_url and status in {401, 403}:
                DISABLED_NODE_REAL = True
            if status == 429:
                DISABLED_RPC_URLS.add(url)
            if (
                status in {401, 403, 429, 500, 502, 503, 504}
                or method in READ_ONLY_RPC_METHODS
            ) and index + 1 < len(urls):
                if status == 429:
                    backoff = float(
                        os.environ.get("RPC_429_BACKOFF_SECONDS", "0.25")
                    )
                    time.sleep(
                        min(
                            backoff,
                            deadline_timeout(backoff, deadline),
                        )
                    )
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
