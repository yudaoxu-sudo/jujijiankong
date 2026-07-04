#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.env import load_local_env


def main() -> int:
    load_local_env()
    key = os.environ.get("NODEREAL_API_KEY")
    if not key:
        print("NODEREAL_API_KEY missing. Run: bash scripts/setup_local_env.sh")
        return 1

    url = f"https://bsc-mainnet.nodereal.io/v1/{key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_blockNumber",
        "params": [],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"NodeReal HTTP {exc.code}. Key loaded, but endpoint rejected it.")
        if body:
            print(f"Response: {body}")
        print("Likely fix: finish NodeReal Get Involved / enable MegaNode BNB Smart Chain endpoint in the dashboard.")
        return 2
    except URLError as exc:
        print(f"Network error: {exc}")
        return 3

    if data.get("result"):
        print("NodeReal key works for BSC RPC.")
        print(f"Latest block hex: {data['result']}")
        return 0

    print(f"Unexpected response: {json.dumps(data, ensure_ascii=False)[:300]}")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())

