#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import alpha_holder_concentration_watch as holder
from scripts import alpha_liquidity_retention_watch as retention
from scripts import alpha_onboarding_preflight as preflight
from scripts import alpha_opening_block_watch as opening


WATCHLIST = ROOT / "config" / "current_alpha_watchlist.json"
KII_CONTRACT = "0xeec6574eabba52bac3f0277f2cd5ac7e67197886"
KII_POOL_ID = (
    "0xf43fdb854021ddeb41e06ac1d6e5df475197038ba5d3cba147f469a56870cd1b"
)
KII_HOOK = "0xb0bb171d333569cfd28a37f5c5dddaaa90ad46af"
PANCAKE_INFINITY_CL_MANAGER = "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"


def main() -> int:
    payload = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    items = payload["items"]
    assert payload["monitoring_policy"] == {
        "mode": "exclusive_symbols",
        "symbols": ["DOS", "KII"],
    }
    assert sorted(
        str(item.get("symbol") or "").upper()
        for item in items
        if item.get("active_monitoring") is True
    ) == ["DOS", "KII"]

    grvt = next(item for item in items if item.get("symbol") == "GRVT")
    assert grvt["priority"] == "P4_ARCHIVED_CASE"
    assert grvt["active_monitoring"] is False

    kii = next(item for item in items if item.get("symbol") == "KII")
    assert kii["priority"] == "P0_PRELAUNCH"
    assert kii["active_monitoring"] is True
    assert kii["chain"] == "bsc"
    assert kii["facts"]["lifecycle_first_seen_at"] == (
        "2026-08-14T08:10:32+00:00"
    )
    assert kii["facts"]["lifecycle_first_seen_basis"] == (
        "local_curated_monitoring_activation"
    )
    assert kii["contracts"] == [
        {
            "chain": "bsc",
            "address": KII_CONTRACT,
            "confidence": "official_hyperlane_registry_and_canonical_pool_key_verified",
            "evidence_ids": [
                "kii-official-bridge-docs",
                "kii-hyperlane-route-registry",
                "kii-onchain-pool-key-latest",
            ],
        }
    ]
    assert kii["known_times"] == [
        {
            "time": "2026-08-14 21:00",
            "reason": "verified_prelaunch_pool",
            "evidence_ids": [
                "kii-kucoin-listing",
                "kii-kraken-listing",
                "kii-mexc-listing",
                "kii-onchain-pool-start",
            ],
        }
    ]
    pool = kii["pool_ids"][0]
    assert pool["pool_id"] == KII_POOL_ID
    assert pool["start_time_utc8"] == "2026-08-14 21:00:00"
    assert pool["pair"] == "USDT/KII"
    assert pool["hook"] == KII_HOOK
    assert pool["pool_manager"] == PANCAKE_INFINITY_CL_MANAGER
    assert pool["verification_status"] == (
        "verified_canonical_pool_key_latest_eth_call_start_time_composite"
    )

    research = kii["prelaunch_research"]
    assert research["research_status"] == "blocked"
    assert research["decision"]["action"] == "Observe"
    assert research["decision"]["automatic_trading"] is False
    assert research["identity"]["contract"] == KII_CONTRACT
    assert research["identity"]["contract_role"] == "evm_hyp_synthetic"
    assert research["identity"]["official_catalog_status"] == (
        "pending_no_match_as_of_observation"
    )

    evidence = {
        row["evidence_id"]: row for row in research["evidence"]
    }
    assert evidence["kii-binance-wallet-official"]["verification_status"] == (
        "verified_launch_day_and_points_claim_after_trading_open"
    )
    assert evidence["kii-binance-public-catalog-sample"]["matched_rows"] == 0
    assert evidence["kii-binance-public-catalog-sample"]["row_count"] == 661
    assert evidence["kii-detailed-social-research"]["verification_status"] == (
        "discovery_only_unverified_claims"
    )
    assert evidence["kii-onchain-pool-key-latest"]["verification_status"] == (
        "verified_canonical_pool_key_latest_eth_call"
    )

    supply = research["supply"]
    assert supply["max_supply"] == "1800000000"
    assert supply["official_initial_circulating_supply"] == "324000000"
    assert supply["official_initial_circulating_percent"] == "18"
    assert supply["component_sum_token_amount"] == "314190000"
    assert supply["component_sum_percent"] == "17.455"
    assert supply["headline_component_gap_token_amount"] == "9810000"
    assert supply["headline_component_gap_percent"] == "0.545"
    assert supply["reconciliation_status"] == "blocked_unattributed_gap"
    assert [
        row["percent_of_total"] for row in supply["tge_components"]
    ] == ["2.1", "0.275", "5", "10.08"]

    cross_chain = research["cross_chain"]
    assert cross_chain["transport"] == "hyperlane_warp_route"
    assert cross_chain["canonical_chain"] == "kiichain"
    assert cross_chain["canonical_standard"] == "EvmHypNative"
    assert cross_chain["bsc_standard"] == "EvmHypSynthetic"
    assert cross_chain["bsc_contract"] == KII_CONTRACT
    assert set(cross_chain["connected_chains"]) == {
        "kiichain",
        "bsc",
        "polygon",
        "base",
        "ethereum",
        "mantle",
    }

    candidates = research["unverified_candidates"]
    assert candidates == {
        "binance_alpha_allocation_percent": "1",
        "okx_allocation_percent": "0.3",
        "bybit_deposit_identity": "unknown",
        "market_maker_addresses": [],
    }

    result = preflight.validate_watchlist(
        payload,
        profile="binance_alpha_bsc.v1",
        holder_capacity=8,
    )
    assert result["status"] == "pass", result
    assert result["focused_symbol_count"] == 2
    assert result["active_item_count"] == 2

    opening_rows = opening.opening_pool_rows(kii)
    assert len(opening_rows) == 1
    assert opening_rows[0]["pool_id"] == KII_POOL_ID

    holder_rows = holder.contract_items(payload)
    retention_rows, retention_issues = retention.eligible_contract_items(payload)
    assert retention_issues == []
    assert KII_CONTRACT in {row["address"] for row in holder_rows}
    assert KII_CONTRACT in {row["address"] for row in retention_rows}

    print("KII_PRELAUNCH_CONFIG PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
