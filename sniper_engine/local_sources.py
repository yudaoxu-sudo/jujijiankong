from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE_FILES = {
    "aLiiDeez": ROOT / "output" / "aliideez_x_research" / "analysis" / "method_index.csv",
    "0xcrypto_max": ROOT / "output" / "0xcrypto_max_x_research" / "analysis" / "method_index.csv",
}

O1_THREAD_TWEET_IDS = {
    "2067399680217198964",
    "2067399682662514752",
    "2067399685204254900",
    "2067399687456661785",
    "2067399689717399958",
}

O1_MINT_DECODE = ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json"


def read_method_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source, path in SOURCE_FILES.items():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                row = dict(row)
                row["source"] = source
                apply_verified_case_evidence(row)
                rows.append(row)
    return rows


def apply_verified_case_evidence(row: dict[str, str]) -> None:
    tweet_url = row.get("tweet_url", "")
    if not any(tweet_id in tweet_url for tweet_id in O1_THREAD_TWEET_IDS):
        return
    if not O1_MINT_DECODE.exists():
        return
    try:
        mint = json.loads(O1_MINT_DECODE.read_text(encoding="utf-8"))
    except Exception:
        return
    if mint.get("position_id") != 6913002:
        return

    row["has_lp_id"] = "yes"
    flags = [item for item in row.get("evidence_flags", "").split("|") if item]
    if "lp_id" not in flags:
        flags.append("lp_id")
    row["evidence_flags"] = "|".join(flags)
