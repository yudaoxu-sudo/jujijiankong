#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import alpha_prelaunch_watch as prelaunch
from runtime_health_watch import historical_prelaunch_delivery_issue
from verify_sniper_engine import validate_dos_candidate_sell_receipt


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "config" / "current_alpha_watchlist.json"
EVIDENCE = ROOT / "input" / "dos_prelaunch_evidence_2026-08-09.json"
AIRDROP_EVIDENCE = (
    ROOT / "input" / "dos_airdrop_pressure_evidence_2026-08-10.json"
)
SELL_RECEIPT = ROOT / "input" / "dos_alpha_200_sell_receipt_2026-08-10.json"


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
        "symbols": ["DOS"],
    }
    assert active == ["DOS"]
    grvt = next(item for item in items if item.get("symbol") == "GRVT")
    assert grvt["active_monitoring"] is False
    assert grvt["priority"] == "P4_ARCHIVED_CASE"
    assert grvt["monitoring_paused_at"] == "2026-08-14T05:12:20+00:00"
    assert grvt["archive_reason"] == (
        "User confirmed full GRVT exit and disabled active monitoring and "
        "notifications on 2026-08-14. Keep historical evidence and replay "
        "fixtures only."
    )
    dos = next(item for item in items if item.get("symbol") == "DOS")
    assert dos["chain"] == "bsc"
    assert dos["facts"]["monitoring_anchor_time_utc"] == (
        "2026-08-10T09:00:00+00:00"
    )
    assert dos["facts"]["lifecycle_first_seen_at"] == (
        "2026-08-09T16:20:58+00:00"
    )
    assert dos["facts"]["lifecycle_first_seen_basis"] == (
        "first_tracked_monitor_commit"
    )
    assert dos["facts"]["lifecycle_first_seen_ref"] == (
        "git:d6d05b4c60201ffb62c2aee8a6f9a847b832c93f"
    )
    with tempfile.TemporaryDirectory() as temporary:
        assert historical_prelaunch_delivery_issue(
            Path(temporary),
            {
                "symbol": dos["symbol"],
                "contract": dos["contracts"][0]["address"],
                **dos["facts"],
            },
            datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        ) == "historical prelaunch Telegram delivery receipt missing"
    assert "listing_time_utc" not in dos["facts"]
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
    schedules = {
        row["event_id"]: row
        for row in dos["event_schedule"]
        if row.get("event_id")
    }
    assert schedules["dos-binance-alpha-points-claim"]["claim_start_utc"] == (
        "2026-08-10T09:00:00+00:00"
    )
    assert schedules["dos-binance-alpha-points-claim"][
        "distribution_identity_status"
    ] == "explorer_labeled_venue_proxy_candidate_claim_distributor_unverified"
    assert schedules["dos-dappos-phase1-claim"]["claim_start_utc"] == (
        "2026-08-10T10:00:00+00:00"
    )
    assert schedules["dos-dappos-phase1-claim"]["claim_end_utc"] == ""
    assert schedules["dos-binance-alpha-points-claim"][
        "venue_sell_evidence"
    ]["status"] == "receipt_confirmed"
    assert schedules["dos-binance-alpha-points-claim"][
        "airdrop_attribution"
    ]["status"] == "unverified"
    assert research["supply"]["total_supply"] == "1000000000"
    allocations = {
        row["bucket_id"]: row
        for row in research["supply"]["allocations"]
    }
    assert allocations["airdrop_total"]["percent_of_total"] == "6"
    assert allocations["airdrop_tge_initial"]["token_amount"] == "30000000"
    assert allocations["airdrop_future_monthly_total"]["token_amount"] == (
        "30000000"
    )
    bitget = next(
        row
        for row in research["venues"]["cex"]
        if row.get("venue") == "Bitget"
    )
    assert bitget["trading_state"] == (
        "official_schedule_elapsed_live_state_unverified"
    )
    assert "pool.active_depth_and_sellability" in research["missing_fields"]
    assert all(
        item.get("active_monitoring") is False
        for item in items
        if item.get("symbol") != "DOS"
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
    airdrop = json.loads(AIRDROP_EVIDENCE.read_text(encoding="utf-8"))
    assert airdrop["schema"] == "dos_airdrop_pressure_evidence.v1"
    assert airdrop["verdict"] == "Observe"
    assert airdrop["automatic_trading"] is False
    assert [row["state"] for row in airdrop["calendar"]] == [
        "claim_open_end_unknown",
        "claim_open_end_unknown",
    ]
    assert airdrop["binance_claim_rules"]["reward_dos_per_user"] == "200"
    assert airdrop["onchain"]["confirmed_candidate_asset_sell"]["status"] == (
        "receipt_verified_offline_fixture"
    )
    assert airdrop["onchain"]["exact_200_dos_route_cluster"][
        "coverage_status"
    ] == "bounded_sample_lower_bound"
    assert airdrop["pressure_state"] == {
        "calendar_state": "claim_open_end_unknown",
        "venue_sell_state": "candidate_asset_receipt_confirmed",
        "airdrop_attribution_state": "unverified",
        "derived_state": "candidate_asset_sell_receipt_origin_unverified",
        "reminder_state": "in_window",
        "clearance_status": "blocked",
    }
    pressure_events = prelaunch.build_airdrop_pressure_events(
        payload,
        datetime(2026, 8, 10, 10, 11, tzinfo=timezone.utc),
    )
    dos_events = {
        row["event_id"]: row
        for row in pressure_events
        if row["symbol"] == "DOS"
    }
    alpha = dos_events["dos-binance-alpha-points-claim"]
    assert alpha["calendar_state"] == "claim_open_end_unknown"
    assert alpha["venue_sell_state"] == "candidate_asset_receipt_confirmed"
    assert alpha["airdrop_attribution_state"] == "unverified"
    assert alpha["pressure_state"] == (
        "candidate_asset_sell_receipt_origin_unverified"
    )
    assert alpha["alert_policy"] == "notify"
    assert "airdrop_sell_attribution_unverified" in alpha["issue_codes"]
    assert "airdrop_asset_identity_unverified" in alpha["issue_codes"]
    community = dos_events["dos-dappos-phase1-claim"]
    assert community["calendar_state"] == "claim_open_end_unknown"
    assert community["venue_sell_state"] == "unknown"
    assert community["airdrop_attribution_state"] == "unverified"
    assert "airdrop_distribution_identity_missing" in community["issue_codes"]
    receipt = json.loads(SELL_RECEIPT.read_text(encoding="utf-8"))
    evidence_rows = {
        row["evidence_id"]: row
        for row in research["evidence"]
        if row.get("evidence_id")
    }
    validate_dos_candidate_sell_receipt(
        receipt,
        schedule=schedules["dos-binance-alpha-points-claim"],
        evidence=evidence_rows["dos-onchain-alpha-200-sell"],
    )

    def assert_receipt_rejected(
        candidate: dict,
        *,
        schedule: dict = schedules["dos-binance-alpha-points-claim"],
        evidence_row: dict = evidence_rows["dos-onchain-alpha-200-sell"],
    ) -> None:
        try:
            validate_dos_candidate_sell_receipt(
                candidate,
                schedule=schedule,
                evidence=evidence_row,
            )
        except AssertionError:
            return
        raise AssertionError("tampered DOS sell receipt was accepted")

    for field in ("transaction_hash", "block_hash"):
        tampered = json.loads(json.dumps(receipt))
        tampered[field] = "0x" + "0" * 64
        assert_receipt_rejected(tampered)
    tampered = json.loads(json.dumps(receipt))
    tampered["token_context"]["candidate_dos"]["address"] = "0x" + "0" * 40
    assert_receipt_rejected(tampered)
    tampered = json.loads(json.dumps(receipt))
    tampered["canonical_transfers"][0]["value_raw"] = "201000000000000000000"
    assert_receipt_rejected(tampered)
    tampered = json.loads(json.dumps(receipt))
    tampered["canonical_transfers"][2]["from"] = "0x" + "0" * 40
    assert_receipt_rejected(tampered)
    tampered = json.loads(json.dumps(receipt))
    tampered["canonical_transfer_count"] = 5
    assert_receipt_rejected(tampered)
    bad_schedule = json.loads(
        json.dumps(schedules["dos-binance-alpha-points-claim"])
    )
    bad_schedule["venue_sell_evidence"]["quote_out_usdt"] = "51"
    assert_receipt_rejected(receipt, schedule=bad_schedule)
    bad_evidence = json.loads(
        json.dumps(evidence_rows["dos-onchain-alpha-200-sell"])
    )
    bad_evidence["transaction_ref"] = "bsc:0x" + "0" * 64
    assert_receipt_rejected(receipt, evidence_row=bad_evidence)
    print("DOS_PRELAUNCH_CONFIG PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
