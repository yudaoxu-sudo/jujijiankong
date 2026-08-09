#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "config" / "current_alpha_watchlist.json"
EVIDENCE = ROOT / "input" / "dos_prelaunch_evidence_2026-08-09.json"


def main() -> int:
    payload = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    items = payload["items"]
    active = sorted(
        str(item.get("symbol") or "").upper()
        for item in items
        if item.get("active_monitoring") is True
    )
    assert payload["monitoring_policy"] == {
        "mode": "exclusive_symbols",
        "symbols": ["DOS", "GRVT"],
    }
    assert active == ["DOS", "GRVT"]
    dos = next(item for item in items if item.get("symbol") == "DOS")
    assert dos["chain"] == "bsc"
    assert dos["contracts"] == [
        {
            "chain": "bsc",
            "address": "0xb0f09ea9ae0515c3551080d4a745c8115aa30e37",
            "confidence": "canonical_pancake_pool_key_match_official_catalog_pending",
        }
    ]
    research = dos["prelaunch_research"]
    assert research["research_status"] == "blocked"
    assert research["identity"]["verification_status"] == (
        "canonical_pool_key_match_official_contract_pending"
    )
    assert research["decision"]["action"] == "Observe"
    assert research["decision"]["automatic_trading"] is False
    assert research["pool"]["pool_id"] == (
        "0x2e9c6c234e0a93c85979ae939561543186fa6341cb52b00323eb99cfc8d98ac8"
    )
    assert research["pool"]["opening_timestamp_utc"] == "2026-08-10T09:00:00+00:00"
    assert research["pool"]["pair"] == "USDT/DOS"
    assert research["pool"]["pool_manager"] == (
        "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"
    )
    assert research["pool"]["initialization"]["receipt_status"] == "success"
    assert research["pool"]["state"]["active_liquidity"] == "0"
    assert research["pool"]["sellability"] == "blocked_no_active_liquidity"
    assert research["pool"]["segments"][0]["position_id"] == 1001030
    assert research["sniper_curve"] == []
    assert "pool.active_depth_and_sellability" in research["missing_fields"]
    assert all(
        item.get("active_monitoring") is False
        for item in items
        if item.get("symbol") not in {"DOS", "GRVT"}
    )
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["schema"] == "dos_prelaunch_evidence.v1"
    assert evidence["verdict"] == "Observe"
    assert evidence["capacity"]["status"] == "blocked_missing_actual_liquidity"
    assert evidence["capacity"]["observed_active_liquidity"] == "0"
    assert evidence["onchain"]["setter_receipt"]["status"] == "success"
    assert evidence["onchain"]["setter_receipt"]["pool_token_link_status"] == (
        "verified_by_canonical_cl_pool_key"
    )
    assert evidence["pool"]["status"] == "initialized_active_liquidity_zero"
    assert evidence["pool"]["state"]["active_liquidity"] == "0"
    print("DOS_PRELAUNCH_CONFIG PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
