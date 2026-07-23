#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "output" / "sniper_engine" / "verification_report.md"
PYCACHE_DIR = Path(tempfile.gettempdir()) / "sniper_pycache"


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    required_files = [
        ROOT / "sniper_engine" / "scoring.py",
        ROOT / "sniper_engine" / "local_sources.py",
        ROOT / "sniper_engine" / "rpc.py",
        ROOT / "sniper_engine" / "project_registry.py",
        ROOT / "sniper_engine" / "address_labels.py",
        ROOT / "sniper_engine" / "entity_clustering.py",
        ROOT / "sniper_engine" / "exchange_aggregator.py",
        ROOT / "sniper_engine" / "token_aliases.py",
        ROOT / "scripts" / "sniper_score_local.py",
        ROOT / "scripts" / "alpha_project_watch.py",
        ROOT / "scripts" / "alpha_holder_concentration_watch.py",
        ROOT / "scripts" / "alpha_prelaunch_watch.py",
        ROOT / "scripts" / "alpha_opening_block_watch.py",
        ROOT / "scripts" / "alpha_price_momentum_watch.py",
        ROOT / "scripts" / "alpha_intraday_flow_watch.py",
        ROOT / "scripts" / "verify_alpha_aggregator_trace.py",
        ROOT / "scripts" / "collect_alpha_trace_bundle.py",
        ROOT / "scripts" / "review_alpha_swap_samples.py",
        ROOT / "scripts" / "review_alpha_swap_txs.py",
        ROOT / "scripts" / "review_exchange_wallet_labels.py",
        ROOT / "scripts" / "review_cex_sweep_patterns.py",
        ROOT / "scripts" / "review_funding_source_clusters.py",
        ROOT / "scripts" / "review_opening_cohort_funders.py",
        ROOT / "scripts" / "review_pancake_v4_samples.py",
        ROOT / "scripts" / "x_mcp_readiness.py",
        ROOT / "scripts" / "external_aux_source_readiness.py",
        ROOT / "scripts" / "external_aux_live_probe.py",
        ROOT / "scripts" / "position_cost_watch.py",
        ROOT / "scripts" / "runtime_health_watch.py",
        ROOT / "scripts" / "project_continuity_local.py",
        ROOT / "scripts" / "project_continuity_acceptance.py",
        ROOT / "scripts" / "test_project_continuity_acceptance.py",
        ROOT / "scripts" / "server_health_watchdog.sh",
        ROOT / "scripts" / "install_server_cron.sh",
        ROOT / "scripts" / "audit_celue_integration.py",
        ROOT / "scripts" / "decode_pancake_v4_execute.py",
        ROOT / "scripts" / "build_pancake_v4_roundtrip_fixture.py",
        ROOT / "scripts" / "verify_pancake_v4_roundtrip_fixture.py",
        ROOT / "scripts" / "probe_pancake_v4_state_override.py",
        ROOT / "scripts" / "simulate_pancake_v4_roundtrip_call.py",
        ROOT / "scripts" / "alpha_opening_sprint.sh",
        ROOT / "scripts" / "arx_launch_watch.py",
        ROOT / "scripts" / "arx_opening_block_watch.py",
        ROOT / "scripts" / "arx_opening_sprint.sh",
        ROOT / "scripts" / "deploy_to_server.sh",
        ROOT / "scripts" / "build_alpha_daily_report.py",
        ROOT / "scripts" / "prediction_market_watch.py",
        ROOT / "scripts" / "perp_oi_funding_watch.py",
        ROOT / "scripts" / "surf_aux_market_watch.py",
        ROOT / "scripts" / "telegram_signal_collector.py",
        ROOT / "scripts" / "telegram_user_signal_collector.py",
        ROOT / "scripts" / "telegram_user_login.py",
        ROOT / "scripts" / "add_telegram_source.py",
        ROOT / "scripts" / "analyze_pancake_pool_tx.py",
        ROOT / "scripts" / "ingest_alpha_signal.py",
        ROOT / "scripts" / "build_monitored_wallets.py",
        ROOT / "scripts" / "o1_address_attribution.py",
        ROOT / "scripts" / "sniper_monitor.py",
        ROOT / "scripts" / "server_run_once.sh",
        ROOT / "scripts" / "o1_block_verifier.py",
        ROOT / "scripts" / "o1_decode_pancake_v3.py",
        ROOT / "scripts" / "o1_trace_front_buyers.py",
        ROOT / "scripts" / "summarize_hertzflow_skeleton.py",
        ROOT / "docs" / "alpha_swap_trace_request_prompt.md",
        ROOT / "docs" / "kol_strategy_intake_prompt.md",
        ROOT / "docs" / "pancake_v4_roundtrip_request_prompt.md",
        ROOT / "docs" / "pancake_v4_roundtrip_implementation_prompt.md",
        ROOT / "docs" / "cex_wallet_evidence_request_prompt.md",
        ROOT / "docs" / "x_mcp_setup.md",
        ROOT / "docs" / "project_continuity.md",
        ROOT / "cases" / "2026-07-08_alpha_rotated_address_review.md",
        ROOT / "config" / "watchlist.example.json",
        ROOT / "config" / "external_aux_sources.json",
        ROOT / "config" / "user_positions.example.json",
        ROOT / "config" / "token_aliases.json",
        ROOT / "config" / "current_alpha_watchlist.json",
        ROOT / "config" / "global_address_labels.json",
        ROOT / "config" / "prediction_markets.example.json",
        ROOT / "config" / "current_prediction_markets.json",
        ROOT / "config" / "telegram_user_sources.example.json",
        ROOT / "config" / "telegram_user_sources.json",
        ROOT / "config" / "monitored_wallets.json",
        ROOT / "config" / "pancake_v4_simulation_samples.json",
        ROOT / "config" / "project_continuity.json",
        ROOT / "input" / "alpha_rotated_address_review_2026-07-08.json",
        ROOT / "input" / "miles082510_wallet_cluster_review_2026-07-13.json",
        ROOT / "cases" / "2026-07-13_miles082510_wallet_cluster_review.md",
        ROOT / "input" / "elonkely_latest_100_review_2026-07-16.json",
        ROOT / "cases" / "2026-07-16_elonkely_latest_100_review.md",
        ROOT / "input" / "binance_alpha_cex_wallet_aggregation_review_2026-07-17.json",
        ROOT / "cases" / "2026-07-17_binance_alpha_cex_wallet_aggregation.md",
        ROOT / "cases" / "2026-07-15_bsc_native_history_source_review.md",
        ROOT / "input" / "signals" / "README.md",
        ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json",
        ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv",
        ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv",
        ROOT / "output" / "monitoring" / "latest_snapshot.json",
        ROOT / "output" / "monitoring" / "alerts.md",
        ROOT / "output" / "monitoring" / "telegram_payload.txt",
        ROOT / "output" / "alpha_project_watch" / "latest.json",
        ROOT / "output" / "alpha_project_watch" / "latest.md",
        ROOT / "output" / "arx_launch_watch" / "latest.json",
        ROOT / "output" / "arx_launch_watch" / "latest.md",
        ROOT / "output" / "arx_opening_block_watch" / "latest.json",
        ROOT / "output" / "arx_opening_block_watch" / "latest.md",
        ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json",
        ROOT / "output" / "prediction_markets" / "prediction_markets.md",
        ROOT / "output" / "surf_aux_market_watch" / "latest.json",
        ROOT / "output" / "surf_aux_market_watch" / "latest.md",
        ROOT / "output" / "external_aux_sources" / "latest.json",
        ROOT / "output" / "external_aux_sources" / "latest.md",
        ROOT / "output" / "o1_address_attribution" / "address_attribution.csv",
        ROOT / "output" / "o1_address_attribution" / "o1_address_attribution.md",
        ROOT / "output" / "aliideez_x_research" / "analysis" / "method_index.csv",
        ROOT / "output" / "0xcrypto_max_x_research" / "analysis" / "method_index.csv",
    ]
    for path in required_files:
        checks.append((f"file exists: {path.relative_to(ROOT)}", path.exists(), ""))

    daily_reports = sorted((ROOT / "reports").glob("*_alpha_sniper_daily.md"))
    checks.append(("daily alpha report exists", bool(daily_reports), daily_reports[-1].name if daily_reports else ""))

    config_ok = False
    config_msg = ""
    try:
        json.loads((ROOT / "config" / "watchlist.example.json").read_text(encoding="utf-8"))
        config_ok = True
    except Exception as exc:
        config_msg = str(exc)
    checks.append(("watchlist example JSON parses", config_ok, config_msg))

    cex_aggregation_review_ok = False
    cex_aggregation_review_msg = ""
    try:
        cex_review = json.loads(
            (ROOT / "input" / "binance_alpha_cex_wallet_aggregation_review_2026-07-17.json").read_text(
                encoding="utf-8"
            )
        )
        verified_rows = cex_review.get("verified_ui_records", [])
        alpha_candidate_rows = cex_review.get("matched_alpha_onchain_candidates", [])
        pending_linkage_rows = cex_review.get("pending_ui_linkage_records", [])
        runtime_integration = cex_review.get("runtime_integration", {})
        verified_by_tx = {row.get("txid"): row for row in verified_rows}
        alpha_candidate_by_tx = {row.get("txid"): row for row in alpha_candidate_rows}
        expected_gate_records = {
            "0xbd9b2b41d92c7ed59bd22afa376656aabea115755c7295f584d4130ab329ec28": {
                "from": "0xd5da17a84314194e348649c89a65143a061f7190",
                "amount": "1845034161.853208889131008",
                "time": "2026-07-14T05:11:24Z",
            },
            "0xcc96491ff1dcbf98511a5aba24955ad9629c3ff68d8325a99be7403ac72dd619": {
                "from": "0x8782163068c7cd74d2510768a61135c1e4eb07b3",
                "amount": "1914689272",
                "time": "2026-07-14T05:11:23Z",
            },
        }
        expected_alpha_records = {
            "0x288e360dc637295457af65ba3515108e4bf6342f7d2fb9efa40393540c3f8f87": {
                "record_id": "AKE-BINANCE-ALPHA-HOT-2026-07-04",
                "from": "0xb40b35fe21be75f6e5c0b7dabab1ec87d87a1395",
                "amount": "670000000",
                "raw_amount": "670000000000000000000000000",
                "time": "2026-07-04T10:58:07Z",
                "milli_time": "2026-07-04T10:58:07.650Z",
                "block": 108008641,
                "block_hex": "0x67014c1",
                "log_index": 330,
                "next_tx": "0xfa0557f8e2da6d827f73cec9557ba60f5898737efdc4165646242757059b6f36",
                "next_time": "2026-07-04T11:01:19Z",
                "next_amount": "323089",
            },
            "0x4b2d3173498afd9b056a41347276ca32fad9494eeece7e01384a755099615af8": {
                "record_id": "AKE-BINANCE-ALPHA-HOT-2026-07-05",
                "from": "0xd49ef7def42f4633cd55cb874e016a570ea99f04",
                "amount": "822989955",
                "raw_amount": "822989955000000000000000000",
                "time": "2026-07-05T10:25:35Z",
                "milli_time": "2026-07-05T10:25:35.250Z",
                "block": 108196248,
                "block_hex": "0x672f198",
                "log_index": 420,
                "next_tx": "0x68b5ee2c7d35455f0d453d0f399ee6d49abd692284e19c9b795ccd1827adce62",
                "next_time": "2026-07-05T10:30:44Z",
                "next_amount": "70322.2219445",
            },
            "0x7321a5f87f0709502c7ed8c27bcb398bef779599cee5c090190f405fae871727": {
                "record_id": "AKE-BINANCE-ALPHA-HOT-2026-07-07",
                "from": "0x6449b24d8dad7cef8ece12d7d5c8d0e0ef355a48",
                "amount": "972540250",
                "raw_amount": "972540250000000000000000000",
                "time": "2026-07-07T08:46:34Z",
                "milli_time": "2026-07-07T08:46:34.150Z",
                "block": 108566378,
                "block_hex": "0x678976a",
                "log_index": 218,
                "next_tx": "0x62b6677cc9861ece58fa7525e65197bea58fcfe91a9809bdb88b0d8b030e7843",
                "next_time": "2026-07-07T08:46:40Z",
                "next_amount": "479101.9600125",
            },
        }
        cex_aggregation_review_ok = (
            cex_review.get("schema") == "binance_alpha_cex_wallet_aggregation_review.v2"
            and cex_review.get("token", {}).get("contract")
            == "0x2c3a8ee94ddd97244a93bc48298f97d2c412f7db"
            and len(verified_rows) == 2
            and set(verified_by_tx) == set(expected_gate_records)
            and all(
                verified_by_tx[txid].get("transfer_from") == expected["from"]
                and verified_by_tx[txid].get("exact_amount_token") == expected["amount"]
                and verified_by_tx[txid].get("block_time_utc") == expected["time"]
                for txid, expected in expected_gate_records.items()
            )
            and all(
                row.get("transfer_to") == "0x0d0707963952f2fba59dd06f2b425ace40b492fe"
                for row in verified_rows
            )
            and all(row.get("receipt_status") == "success" for row in verified_rows)
            and all(row.get("token_contract_verified") is True for row in verified_rows)
            and all(row.get("path_role") == "unlabeled_to_cex_inflow_candidate" for row in verified_rows)
            and all(row.get("transfer_direction_verified") is True for row in verified_rows)
            and all(row.get("economic_external_inflow_verified") is False for row in verified_rows)
            and all(row.get("source_entity_role") == "unresolved" for row in verified_rows)
            and all(row.get("entity_linkage_verified") is False for row in verified_rows)
            and all(row.get("runtime_effect") == "cex_inflow_risk" for row in verified_rows)
            and len(alpha_candidate_rows) == 3
            and set(alpha_candidate_by_tx) == set(expected_alpha_records)
            and all(
                alpha_candidate_by_tx[txid].get("record_id") == expected["record_id"]
                and alpha_candidate_by_tx[txid].get("transfer_from") == expected["from"]
                and alpha_candidate_by_tx[txid].get("transaction_from") == expected["from"]
                and alpha_candidate_by_tx[txid].get("exact_amount_token") == expected["amount"]
                and alpha_candidate_by_tx[txid].get("exact_amount_raw") == expected["raw_amount"]
                and alpha_candidate_by_tx[txid].get("block_time_utc") == expected["time"]
                and alpha_candidate_by_tx[txid].get("block_milli_timestamp_utc")
                == expected["milli_time"]
                and alpha_candidate_by_tx[txid].get("block_milli_timestamp_source")
                == "eth_getBlockByNumber.milliTimestamp"
                and alpha_candidate_by_tx[txid].get("block_number") == expected["block"]
                and alpha_candidate_by_tx[txid].get("block_number_hex") == expected["block_hex"]
                and alpha_candidate_by_tx[txid].get("transfer_log_index") == expected["log_index"]
                and alpha_candidate_by_tx[txid].get("visible_address_level_next_hop", {}).get(
                    "txid"
                )
                == expected["next_tx"]
                and alpha_candidate_by_tx[txid].get("visible_address_level_next_hop", {}).get(
                    "block_time_utc"
                )
                == expected["next_time"]
                and alpha_candidate_by_tx[txid].get("visible_address_level_next_hop", {}).get(
                    "amount_token"
                )
                == expected["next_amount"]
                for txid, expected in expected_alpha_records.items()
            )
            and all(
                row.get("transfer_to") == "0x73d8bd54f7cf5fab43fe4ef40a62d390644946db"
                and row.get("transaction_to") == "0x73d8bd54f7cf5fab43fe4ef40a62d390644946db"
                and row.get("transaction_value_wei") == "0"
                and row.get("receipt_status") == "success"
                and row.get("receipt_log_count") == 2
                and row.get("ake_transfer_log_count") == 1
                and row.get("token_contract_verified") is True
                and row.get("token_decimals_verified") == 18
                and row.get("path_role") == "alpha_custody_movement_unresolved"
                and row.get("transfer_direction_verified") is True
                and row.get("custody_purpose_verified") is False
                and row.get("economic_external_inflow_verified") is False
                and row.get("sale_intent_verified") is False
                and row.get("ui_record_linkage_verified") is False
                and row.get("screenshot_label_exact_mapping_verified") is False
                and row.get("match_status")
                == "unique_date_amount_destination_candidate_within_bounded_search"
                and row.get("runtime_effect") == "none"
                and row.get("alert_policy") == "report_only"
                and row.get("same_tx_secondary_log", {}).get("is_ake_transfer") is False
                and row.get("same_tx_secondary_log", {}).get("dedup_effect")
                == "not_counted_as_second_transfer"
                and row.get("visible_address_level_next_hop", {}).get("to")
                == "0x6aba0315493b7e6989041c91181337b662fb1b90"
                and row.get("visible_address_level_next_hop", {}).get(
                    "same_batch_economic_linkage_verified"
                )
                is False
                for row in alpha_candidate_rows
            )
            and len(pending_linkage_rows) == 3
            and {row.get("record_id"): row.get("matched_candidate_txid") for row in pending_linkage_rows}
            == {expected["record_id"]: txid for txid, expected in expected_alpha_records.items()}
            and all(
                row.get("pending_fact") == "direct screenshot-row TXID comparison"
                for row in pending_linkage_rows
            )
            and cex_review.get("bounded_search", {}).get("address_filter", {}).get("pages_succeeded") == 73
            and cex_review.get("bounded_search", {}).get("address_filter", {}).get("missing_pages") == 0
            and cex_review.get("bounded_search", {}).get("public_rpc_verification", {}).get(
                "chain_id_verified"
            )
            == 56
            and [row.get("coverage") for row in cex_review.get("bounded_search", {}).get("date_windows", [])]
            == [
                "complete_for_union_within_address_filter",
                "complete_for_union_within_address_filter",
                "partial_after_candidate",
            ]
            and cex_review.get("semantic_conclusion", {}).get("matched_alpha_onchain_candidate_count")
            == 3
            and cex_review.get("semantic_conclusion", {}).get("verified_alpha_ui_mapping_count") == 0
            and runtime_integration.get("unlabeled_to_cex_inflow_candidate", {}).get("runtime_effect")
            == "cex_inflow_risk"
            and runtime_integration.get("cex_internal_aggregation", {}).get("alert_policy") == "report_only"
            and runtime_integration.get("alpha_custody_movement_unresolved", {}).get("direction") == "unknown"
            and runtime_integration.get("alpha_custody_movement_unresolved", {}).get("runtime_effect") == "none"
            and runtime_integration.get("alpha_custody_movement_unresolved", {}).get("alert_policy") == "report_only"
        )
        cex_aggregation_review_msg = (
            f"gate_verified={len(verified_rows)}, alpha_candidates={len(alpha_candidate_rows)}, "
            f"pending_ui_linkage={len(pending_linkage_rows)}"
        )
    except Exception as exc:
        cex_aggregation_review_msg = str(exc)
    checks.append(
        (
            "Binance Alpha CEX wallet aggregation review parses with safe path roles",
            cex_aggregation_review_ok,
            cex_aggregation_review_msg,
        )
    )

    elonkely_review_ok = False
    elonkely_review_msg = ""
    try:
        elonkely_review = json.loads(
            (ROOT / "input" / "elonkely_latest_100_review_2026-07-16.json").read_text(encoding="utf-8")
        )
        root_signals = [row.get("root_signal_id") for row in elonkely_review.get("outcome_ledger", [])]
        runtime_decisions = elonkely_review.get("runtime_decisions", {})
        time_cases = elonkely_review.get("source_time_sanity_cases", [])
        elonkely_review_ok = (
            elonkely_review.get("schema") == "kol_strategy_review.v1"
            and elonkely_review.get("source_scope", {}).get("post_count_deduped") == 100
            and elonkely_review.get("source_scope", {}).get("new_since_prior_review_count") == 17
            and len(root_signals) >= 2
            and len(root_signals) == len(set(root_signals))
            and all(row.get("evaluation_horizons") for row in elonkely_review.get("outcome_ledger", []))
            and all(row.get("outcome_status") in {"won", "lost", "mixed", "unresolved"} for row in elonkely_review.get("outcome_ledger", []))
            and any(row.get("event_time_sanity") == "mismatch" for row in time_cases)
            and runtime_decisions.get("trade_action_change") is False
            and runtime_decisions.get("telegram_alert_change") is False
        )
        elonkely_review_msg = f"roots={len(root_signals)}, time_cases={len(time_cases)}"
    except Exception as exc:
        elonkely_review_msg = str(exc)
    checks.append(("ElonKely latest-100 review parses with safe outcome ledger", elonkely_review_ok, elonkely_review_msg))

    b2_forward_ok = False
    b2_forward_msg = ""
    try:
        miles_review = json.loads(
            (ROOT / "input" / "miles082510_wallet_cluster_review_2026-07-13.json").read_text(encoding="utf-8")
        )
        b2_case = next(row for row in miles_review.get("verified_cases", []) if row.get("case_id") == "MILES-C06")
        initial = b2_case.get("onchain_partial", {})
        prior_refresh = b2_case.get("forward_refresh_2026_07_14", {})
        refresh = b2_case.get("forward_refresh_2026_07_15", {})
        social_claim = prior_refresh.get("social_claim", {})
        pre_signal = prior_refresh.get("onchain_pre_signal", {})
        forward = refresh.get("onchain_forward", {})
        market = b2_case.get("market_replay", {})
        resolved = set(refresh.get("resolved_gates", []))
        unresolved = set(refresh.get("unresolved_gates", []))
        b2_forward_ok = (
            initial.get("evidence_status") == "historical_superseded_baseline"
            and initial.get("superseded_by") == "forward_refresh_2026_07_14.onchain_pre_signal"
            and initial.get("token_total_reliable") is False
            and initial.get("token_amount_quality") == "unusable_due_to_decimal_normalization"
            and prior_refresh.get("evidence_status") == "superseded_by_forward_refresh_2026_07_15"
            and prior_refresh.get("onchain_forward", {}).get("received_usd_scope")
            == "test_plus_qualifying_large_combined"
            and social_claim.get("evidence_layer") == "social"
            and pre_signal.get("recipient_count") == 28
            and pre_signal.get("pricing_completeness") == "partial"
            and pre_signal.get("window_total_usd_known") is False
            and pre_signal.get("claimed_usd_independently_verified") is False
            and forward.get("recipient_count") == 18
            and forward.get("large_transfer_count") == 18
            and forward.get("route_test_transfer_count") == 18
            and forward.get("combined_test_and_large_transfer_count") == 36
            and abs(float(forward.get("large_received_usd_total", 0)) - 1279028.0872881992) < 0.01
            and abs(float(forward.get("route_test_received_usd_total", 0)) - 951.2565310452987) < 0.01
            and abs(float(forward.get("combined_test_and_large_received_usd_total", 0)) - 1279979.3438192448) < 0.01
            and forward.get("no_prior_b2_receipt_count") == 18
            and forward.get("cohort_role") == "post_signal_follow_up"
            and forward.get("all_qualifying_large_transfers_post_signal") is True
            and forward.get("all_route_tests_post_signal") is True
            and forward.get("route_test_window_start_utc") == "2026-07-13T15:12:08Z"
            and forward.get("route_test_window_end_utc") == "2026-07-13T18:30:35Z"
            and forward.get("recipient_freshness_scope") == "new_to_B2_within_prior_window_only"
            and forward.get("full_wallet_freshness_verified") is False
            and forward.get("shared_first_hop_source_verified") is True
            and forward.get("common_control_verified") is False
            and forward.get("entity_linkage_verified") is False
            and forward.get("operator_identity_verified") is False
            and forward.get("outbound_transfer_count") == 0
            and forward.get("next_hop_state")
            == "no_b2_outbound_observed_after_each_qualifying_receipt_in_queried_daily_warehouse"
            and forward.get("next_hop_interpretation") == "coverage_window_non_observation_only"
            and forward.get("holding_or_accumulation_inferred") is False
            and market.get("real_hourly_bars_after_post") == 24
            and market.get("first_closed_bar_utc") == "2026-07-13T10:00:00Z"
            and market.get("last_closed_bar_utc") == "2026-07-14T09:00:00Z"
            and market.get("maturity") == "closed_24h_no_price_confirmation"
            and refresh.get("direction") == "unknown"
            and refresh.get("action") == "Observe"
            and {"24h_market_replay", "same_source_test_then_large_path"} <= resolved
            and {
                "full_usd_reconstruction",
                "full_wallet_freshness",
                "common_control",
                "entity_linkage",
                "operator_identity",
                "live_next_hop",
            } <= unresolved
            and "24h_market_replay" not in unresolved
            and b2_case.get("status") == "forward_case_24h_closed_next_hop_pending"
        )
        b2_forward_msg = (
            f"pre_signal_recipients={pre_signal.get('recipient_count')} "
            f"forward_recipients={forward.get('recipient_count')} "
            f"bars={market.get('real_hourly_bars_after_post')} "
            f"action={refresh.get('action')} status={b2_case.get('status')}"
        )
    except Exception as exc:
        b2_forward_msg = str(exc)
    checks.append(("B2 forward case closes 24h without action promotion", b2_forward_ok, b2_forward_msg))

    continuity_config_ok = False
    continuity_config_msg = ""
    try:
        continuity = json.loads((ROOT / "config" / "project_continuity.json").read_text(encoding="utf-8"))
        thresholds = continuity.get("thresholds", {})
        metric_pairs = [
            (int(thresholds.get(f"{metric}_warning", 0)), int(thresholds.get(f"{metric}_rotate", 0)))
            for metric in ("log_bytes", "tokens_used", "compaction_count", "turn_count")
        ]
        context_roles = {
            str(row.get("role", ""))
            for row in continuity.get("context_files", [])
            if isinstance(row, dict)
        }
        acceptance = continuity.get("acceptance", {})
        denied_globs = {str(item) for item in acceptance.get("denied_git_globs", [])}
        denied_exceptions = {str(item) for item in acceptance.get("denied_git_exceptions", [])}
        tracked_required = {str(item) for item in acceptance.get("tracked_required_paths", [])}
        remote_health = acceptance.get("remote_health", {})
        continuity_config_ok = (
            continuity.get("schema") == "project_continuity_config.v1"
            and continuity.get("project_id") == "sniper-monitor"
            and all(warning > 0 and rotate > warning for warning, rotate in metric_pairs)
            and {
                "project_memory",
                "open_items",
                "agent_open_loops",
                "strategy_skill",
                "deployment_entrypoint",
                "server_runbook",
            }.issubset(context_roles)
            and str(continuity.get("state_db_path", "")).endswith("state_5.sqlite")
            and acceptance.get("schema") == "sniper_project_acceptance_policy.v1"
            and {
                "scripts/project_continuity_local.py",
                "scripts/project_continuity_acceptance.py",
                "scripts/test_project_continuity_acceptance.py",
                "scripts/deploy_to_server.sh",
                "docs/project_continuity.md",
                "docs/server_runbook.md",
                "config/current_alpha_watchlist.json",
            }.issubset(tracked_required)
            and {
                ".deploy/**",
                ".env",
                ".env.*",
                "**/*.session",
                "**/*.pem",
                "**/*.key",
            }.issubset(denied_globs)
            and denied_exceptions == {".env.example"}
            and str(remote_health.get("project_root", "")).startswith("/")
            and str(remote_health.get("identity_file", "")).startswith("../.deploy/")
            and str(remote_health.get("known_hosts_file", "")).startswith("../.deploy/")
            and int(remote_health.get("max_cycle_age_seconds", 0)) >= 600
        )
        continuity_config_msg = (
            f"pairs={metric_pairs}, roles={','.join(sorted(context_roles))}, "
            f"acceptance_paths={len(tracked_required)}, denied_globs={len(denied_globs)}, "
            f"denied_exceptions={','.join(sorted(denied_exceptions))}"
        )
    except Exception as exc:
        continuity_config_msg = str(exc)
    checks.append(("project continuity config parses", continuity_config_ok, continuity_config_msg))

    continuity_acceptance_test = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test_project_continuity_acceptance.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "project continuity acceptance regression tests",
            continuity_acceptance_test.returncode == 0,
            continuity_acceptance_test.stderr.strip() or continuity_acceptance_test.stdout.strip(),
        )
    )

    external_aux_config_ok = False
    external_aux_config_msg = ""
    try:
        aux_config = json.loads((ROOT / "config" / "external_aux_sources.json").read_text(encoding="utf-8"))
        source_ids = {str(row.get("id", "")) for row in aux_config.get("sources", [])}
        required_sources = {"coinglass", "coinank", "gmgn", "debot_ai", "surf"}
        rules = aux_config.get("rules", {})
        external_aux_config_ok = (
            aux_config.get("schema") == "external_aux_sources.v1"
            and required_sources.issubset(source_ids)
            and rules.get("unvalidated_source_policy") == "can_enrich_context_but_cannot_emit_buy_sell_action"
        )
        external_aux_config_msg = f"{len(source_ids)} sources, ids={','.join(sorted(source_ids))}"
    except Exception as exc:
        external_aux_config_msg = str(exc)
    checks.append(("external auxiliary source config parses", external_aux_config_ok, external_aux_config_msg))

    token_alias_config_ok = False
    token_alias_config_msg = ""
    try:
        alias_config = json.loads((ROOT / "config" / "token_aliases.json").read_text(encoding="utf-8"))
        rows = alias_config.get("tokens", [])
        by_address = {str(row.get("address", "")).lower(): row for row in rows if isinstance(row, dict)}
        wdataip = by_address.get("0xa37eded373c5cdf88644db7c6b89f222e756afb2", {})
        token_alias_config_ok = (
            alias_config.get("schema") == "token_aliases.v1"
            and wdataip.get("raw_symbol") == "WDATAIP"
            and wdataip.get("display_symbol") == "DATA"
            and wdataip.get("project_name") == "Data Network"
        )
        token_alias_config_msg = f"{len(rows)} aliases, wdataip={bool(wdataip)}"
    except Exception as exc:
        token_alias_config_msg = str(exc)
    checks.append(("token alias config parses", token_alias_config_ok, token_alias_config_msg))

    global_labels_ok = False
    global_labels_msg = ""
    try:
        labels = json.loads((ROOT / "config" / "global_address_labels.json").read_text(encoding="utf-8"))
        bsc_labels = labels.get("chains", {}).get("bsc", [])
        classes = {row.get("class") for row in bsc_labels if isinstance(row, dict)}
        global_labels_ok = bool(bsc_labels) and {"dex_router", "dex_quoter", "dex_vault", "permit2", "lp_position_manager", "pool_manager", "cex_hot_wallet", "cex_deposit"}.issubset(classes)
        global_labels_msg = f"{len(bsc_labels)} bsc labels, classes={','.join(sorted(str(item) for item in classes if item))}"
    except Exception as exc:
        global_labels_msg = str(exc)
    checks.append(("global address labels JSON parses", global_labels_ok, global_labels_msg))

    alpha_rotated_ok = False
    alpha_rotated_msg = ""
    try:
        alpha_review = json.loads((ROOT / "input" / "alpha_rotated_address_review_2026-07-08.json").read_text(encoding="utf-8"))
        labels = json.loads((ROOT / "config" / "global_address_labels.json").read_text(encoding="utf-8"))
        bsc_by_address = {str(row.get("address", "")).lower(): row for row in labels.get("chains", {}).get("bsc", []) if isinstance(row, dict)}
        expected_classes = {
            "0x6aba0315493b7e6989041c91181337b662fb1b90": "exchange_aggregator",
            "0x73d8bd54f7cf5fab43fe4ef40a62d390644946db": "exchange_aggregator",
            "0xb300000b72deaeb607a12d5f54773d1c19c7028d": "dex_router",
        }
        configured = alpha_review.get("current_configured_infrastructure", [])
        candidates = alpha_review.get("manual_review_candidates", [])
        rpc_review = alpha_review.get("rpc_review", {})
        rpc_candidates = rpc_review.get("candidate_reviews", [])
        configured_addresses = {str(row.get("address", "")).lower() for row in configured if isinstance(row, dict)}
        candidate_statuses = {str(row.get("status", "")) for row in candidates if isinstance(row, dict)}
        missing_or_wrong = [
            address
            for address, label_class in expected_classes.items()
            if bsc_by_address.get(address, {}).get("class") != label_class
        ]
        alpha_rotated_ok = (
            alpha_review.get("schema") == "alpha_rotated_address_review.v1"
            and set(expected_classes).issubset(configured_addresses)
            and not missing_or_wrong
            and len(alpha_review.get("representative_tx_hashes", [])) >= 10
            and "candidate_only_do_not_promote" in candidate_statuses
            and rpc_review.get("representative_only") is True
            and rpc_review.get("representative_tx_count") == 16
            and rpc_review.get("transaction_found_count") == 16
            and rpc_review.get("receipt_found_count") == 16
            and rpc_review.get("internal_trace_complete") is False
            and rpc_review.get("address_history_complete") is False
            and rpc_review.get("entity_ownership_verified") is False
            and sorted(row.get("indexed_receipt_occurrence_count") for row in rpc_candidates if row.get("indexed_receipt_occurrence_count") is not None) == [6, 6, 9]
            and all(row.get("decision") in {"do_not_promote", "keep_dex_vault"} for row in rpc_candidates)
            and any(row.get("proxy_type") == "eip1967" and row.get("implementation_matches_configured_infrastructure") is False for row in rpc_candidates)
        )
        alpha_rotated_msg = (
            f"configured={len(configured)}, candidates={len(candidates)}, "
            f"txs={len(alpha_review.get('representative_tx_hashes', []))}, "
            f"rpc_found={rpc_review.get('transaction_found_count')}/{rpc_review.get('representative_tx_count')}, "
            f"wrong={missing_or_wrong}"
        )
    except Exception as exc:
        alpha_rotated_msg = str(exc)
    checks.append(("alpha rotated address review parses", alpha_rotated_ok, alpha_rotated_msg))

    native_history_review = (ROOT / "cases" / "2026-07-15_bsc_native_history_source_review.md").read_text(encoding="utf-8")
    native_history_review_ok = all(
        marker in native_history_review
        for marker in (
            "blocked_paid_api_key",
            "blocked_chain_56_unsupported",
            "blocked_no_verified_official_bsc_instance",
            "common_gas_source_ratio=null",
            "direction=unknown",
            "action=Observe",
        )
    )
    checks.append(
        (
            "BSC native history review preserves unresolved common-gas boundary",
            native_history_review_ok,
            "credential-free chain-56 sources remain blocked",
        )
    )

    cex_labels_ok = False
    cex_labels_msg = ""
    try:
        bsc_by_address = {str(row.get("address", "")).lower(): row for row in bsc_labels if isinstance(row, dict)}
        high_confidence = {
            "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "cex_hot_wallet",
            "0xf977814e90da44bfa03b6295a0616a897441acec": "cex_hot_wallet",
            "0x5a52e96bacd1056251811211bc712e1b270efcb1": "cex_hot_wallet",
            "0x28c6c06298d514db089934071355e5743bf21d60": "cex_hot_wallet",
            "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "cex_hot_wallet",
            "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "cex_hot_wallet",
            "0x53f78a071d04224b8e254e243fffc6d9f2f3fa23": "cex_hot_wallet",
            "0xdd3cb5c974601bc3974d908ea4a86020f9999e0c": "cex_hot_wallet",
            "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "cex_deposit",
        }
        missing = [addr for addr, label_class in high_confidence.items() if bsc_by_address.get(addr, {}).get("class") != label_class]
        rejected_mexc_fragment = "0x56ed7392661f496d10e9119d41123fa3f58405acb59ddf8992e250696dd63f75edd0c3"
        cex_labels_ok = not missing and rejected_mexc_fragment not in bsc_by_address
        cex_labels_msg = f"imported={len(high_confidence) - len(missing)}/{len(high_confidence)}, missing={missing}, invalid_mexc_imported={rejected_mexc_fragment in bsc_by_address}"
    except Exception as exc:
        cex_labels_msg = str(exc)
    checks.append(("global CEX labels imported with invalid sample rejected", cex_labels_ok, cex_labels_msg))

    exchange_wallet_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='exchange_wallet_review_'))
source = work / 'wallets.json'
out_dir = work / 'out'
rows = [
    {
        'chain': 'bsc',
        'address': '0x1111111111111111111111111111111111111111',
        'exchange': 'TestEx',
        'type': 'hot_wallet',
        'confidence': 'high',
        'evidence': 'BscScan label: TestEx Hot Wallet',
        'source_url': 'https://example.com/1',
    },
    {
        'chain': 'bsc',
        'address': '0x2222',
        'exchange': 'BadEx',
        'type': 'hot_wallet',
        'confidence': 'high',
        'evidence': 'bad address',
    },
    {
        'chain': 'bsc',
        'address': '0x3333333333333333333333333333333333333333',
        'exchange': 'MidEx',
        'type': 'deposit_wallet',
        'confidence': 'medium',
        'evidence': 'not enough evidence',
    },
    {
        'chain': 'bsc',
        'address': '0x4444444444444444444444444444444444444444',
        'exchange': 'RouterEx',
        'type': 'router',
        'confidence': 'high',
        'evidence': 'protocol address',
    },
]
source.write_text(json.dumps(rows), encoding='utf-8')
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'review_exchange_wallet_labels.py'), '--input', str(source), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
review = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert review['counts']['accepted_candidate'] == 1, review
assert review['counts']['rejected'] == 3, review
proposal = review['label_proposals'][0]
assert proposal['class'] == 'cex_hot_wallet', proposal
assert proposal['exchange'] == 'TestEx', proposal
"""
    exchange_wallet_review_result = subprocess.run(
        [sys.executable, "-c", exchange_wallet_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange wallet label review smoke test",
            exchange_wallet_review_result.returncode == 0,
            exchange_wallet_review_result.stderr.strip(),
        )
    )

    cex_sweep_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='cex_sweep_review_'))
source = work / 'sweeps.json'
out_dir = work / 'out'
binance_hot = '0x8894e0a0c962cb723c1976a4421c95949be2d4e3'
rows = [
    {
        'chain': 'bsc',
        'address': '0x1111111111111111111111111111111111111111',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + 'a' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'b' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'c' * 64, 'to': binance_hot},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x2222222222222222222222222222222222222222',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + 'd' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'e' * 64, 'to': binance_hot},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x3333333333333333333333333333333333333333',
        'exchange': 'Unknown',
        'type': 'sweep_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + '1' * 64, 'to': '0x4444444444444444444444444444444444444444'},
            {'tx_hash': '0x' + '2' * 64, 'to': '0x4444444444444444444444444444444444444444'},
            {'tx_hash': '0x' + '3' * 64, 'to': '0x4444444444444444444444444444444444444444'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x5555555555555555555555555555555555555555',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'asset_type': 'native_bnb',
        'sweep_paths': [
            {'tx_hash': '0x' + '4' * 64, 'to': binance_hot, 'asset': 'BNB'},
            {'tx_hash': '0x' + '5' * 64, 'to': binance_hot, 'asset': 'BNB'},
            {'tx_hash': '0x' + '6' * 64, 'to': binance_hot, 'asset': 'BNB'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x6666666666666666666666666666666666666666',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + '7' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
            {'tx_hash': '0x' + '8' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
            {'tx_hash': '0x' + '9' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x7777777777777777777777777777777777777777',
        'exchange': 'Binance',
        'candidate_type': 'manual_review_only',
        'confidence': 'high',
        'asset_type': 'bep20',
        'observed_paths': [
            {'tx_hash': '0x' + '0' * 64, 'counterparty': binance_hot, 'direction': 'out_to_cex_hot_wallet', 'asset': 'USDT'},
            {'tx_hash': '0x' + 'e' * 64, 'counterparty': binance_hot, 'direction': 'out_to_cex_hot_wallet', 'asset': 'USDT'},
            {'tx_hash': '0x' + 'f' * 64, 'counterparty': binance_hot, 'direction': 'out_to_cex_hot_wallet', 'asset': 'USDT'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x8888888888888888888888888888888888888888',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + '6' * 64, 'counterparty': binance_hot},
            {'tx_hash': '0x' + '7' * 64, 'counterparty': binance_hot},
            {'tx_hash': '0x' + '8' * 64, 'counterparty': binance_hot},
        ],
    },
]
source.write_text(json.dumps(rows), encoding='utf-8')
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'review_cex_sweep_patterns.py'), '--input', str(source), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
review = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert review['counts']['accepted_candidate'] == 1, review
assert review['counts']['needs_manual_review'] == 6, review
assert any(item['reason'] == 'native_asset_only' for item in review['reviewed']), review
assert any(item['reason'] == 'missing_sweep_target' and item['address'] == '0x6666666666666666666666666666666666666666' for item in review['reviewed']), review
proposal = review['label_proposals'][0]
assert proposal['class'] == 'cex_deposit', proposal
assert proposal['exchange'] == 'Binance', proposal
assert proposal['address'] == '0x1111111111111111111111111111111111111111', proposal
manual = next(item for item in review['reviewed'] if item['address'] == '0x7777777777777777777777777777777777777777')
assert manual['status'] == 'needs_manual_review', manual
assert manual['observed_path_count'] == 3 and manual['outbound_hot_count'] == 3, manual
assert manual['promotion_eligible'] is False and manual['auto_promote_blocked'] is True, manual
assert all(item['address'] != manual['address'] for item in review['label_proposals']), review['label_proposals']
counterparty_only = next(item for item in review['reviewed'] if item['address'] == '0x8888888888888888888888888888888888888888')
assert counterparty_only['status'] == 'needs_manual_review' and counterparty_only['reason'] == 'missing_sweep_target', counterparty_only
assert all(item['address'] != counterparty_only['address'] for item in review['label_proposals']), review['label_proposals']

tracked_source = root / 'input' / 'cex_sweep_manual_review_2026-07-08.json'
tracked_out = work / 'tracked_out'
tracked_result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'review_cex_sweep_patterns.py'), '--input', str(tracked_source), '--out-dir', str(tracked_out)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert tracked_result.returncode == 0, tracked_result.stderr
tracked_review = json.loads((tracked_out / 'latest.json').read_text(encoding='utf-8'))
tracked_rows = tracked_review['reviewed']
assert tracked_review['counts'] == {'needs_manual_review': 4}, tracked_review
assert [item['observed_path_count'] for item in tracked_rows] == [4, 3, 6, 5], tracked_rows
assert sum(item['observed_path_count'] for item in tracked_rows) == 18, tracked_rows
assert tracked_review['label_proposals'] == [], tracked_review['label_proposals']
assert all(item['promotion_eligible'] is False and item['auto_promote_blocked'] is True for item in tracked_rows), tracked_rows

tracked_input = json.loads(tracked_source.read_text(encoding='utf-8'))
rpc_reviews = [item['rpc_review'] for item in tracked_input]
for key in ('listed_path_count', 'tx_found_count', 'receipt_success_count', 'direct_path_match_count'):
    assert sum(int(item.get(key) or 0) for item in rpc_reviews) == 18, (key, rpc_reviews)
assert all(
    item.get('evidence_scope') == 'listed_transactions_only'
    and item.get('address_history_complete') is False
    and item.get('entity_ownership_verified') is False
    and item.get('auto_promote_allowed') is False
    for item in rpc_reviews
), rpc_reviews
tracked_case = (root / 'cases' / '2026-07-15_cex_sweep_manual_rpc_review.md').read_text(encoding='utf-8')
assert '18/18' in tracked_case and 'auto_promote_allowed=false' in tracked_case, tracked_case
"""
    cex_sweep_review_result = subprocess.run(
        [sys.executable, "-c", cex_sweep_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "CEX sweep-pattern review smoke test",
            cex_sweep_review_result.returncode == 0,
            cex_sweep_review_result.stderr.strip(),
        )
    )

    pancake_v4_samples_ok = False
    pancake_v4_samples_msg = ""
    try:
        samples = json.loads((ROOT / "config" / "pancake_v4_simulation_samples.json").read_text(encoding="utf-8"))
        accepted = samples.get("accepted_samples", [])
        rejected = samples.get("rejected_samples", [])
        router = str(samples.get("universal_router") or "").lower()
        success_count = sum(1 for row in accepted if row.get("status") == 1)
        fail_count = sum(1 for row in accepted if row.get("status") == 0)
        selectors = {row.get("selector") for row in accepted}
        all_to_router = all(str(row.get("tx_to") or "").lower() == router for row in accepted)
        by_hash = {str(row.get("tx_hash") or "").lower(): row for row in accepted}
        rejected_hashes = {str(row.get("tx_hash") or "").lower() for row in rejected}
        arx_buy = by_hash.get("0x046673c3b5217b271da8b2be94d892537f9b120865be9bedb49db9959bd582db", {})
        arx_sell = by_hash.get("0xdbcf8b8d95418c0d08b16fde926abaa9d2355e340e5d6d1d503a75430848e4e7", {})
        docx_extra = by_hash.get("0xcc31145b750ca84cd25b4855beaecf0a8a0379c56145a7b7a695a8c29e4dbbf5", {})
        pancake_v4_samples_ok = (
            samples.get("schema") == "pancake_v4_simulation_samples.v1"
            and len(accepted) == 7
            and len(rejected) == 2
            and success_count == 5
            and fail_count == 2
            and all_to_router
            and {"0x3593564c", "0x24856bc3"}.issubset(selectors)
            and arx_buy.get("sample_type") == "successful_universal_router_buy"
            and arx_sell.get("sample_type") == "successful_universal_router_sell"
            and docx_extra.get("selector") == "0x24856bc3"
            and "0xeb126ee663d7af5c9e81a125b816e7b8ef3daf4876b764fad242663f042c13eb" in rejected_hashes
            and "0x1d33f0c687e8a362fb5c1455a534ca6a7614eb883f7869bc995153636316e73b" in rejected_hashes
            and "local sellability gate is now implemented" in str(samples.get("open_gap") or "")
            and "Route samples still do not unlock automatic follow wording" in str(samples.get("open_gap") or "")
        )
        pancake_v4_samples_msg = f"accepted={len(accepted)}, rejected={len(rejected)}, success={success_count}, fail={fail_count}, selectors={sorted(str(item) for item in selectors)}"
    except Exception as exc:
        pancake_v4_samples_msg = str(exc)
    checks.append(("pancake v4 simulation samples reviewed", pancake_v4_samples_ok, pancake_v4_samples_msg))

    pancake_v4_roundtrip_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out_dir = Path(tempfile.mkdtemp(prefix='pancake_v4_roundtrip_fixture_'))
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'build_pancake_v4_roundtrip_fixture.py'), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
fixture = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert fixture['schema'] == 'pancake_v4_roundtrip_fixture.v1', fixture
assert fixture['status'] == 'calldata_fixture_only', fixture
assert fixture['selector'] == '0x3593564c', fixture
assert fixture['commands'] == ['10', '10'], fixture
decoded_commands = fixture['decoded']['commands']
assert len(decoded_commands) == 2, decoded_commands
buy_swap = decoded_commands[0]['decoded_input']['actions'][0]['decoded_param']
sell_swap = decoded_commands[1]['decoded_input']['actions'][0]['decoded_param']
buy_settle = decoded_commands[0]['decoded_input']['actions'][1]['decoded_param']
sell_settle = decoded_commands[1]['decoded_input']['actions'][1]['decoded_param']
buy_take_all = decoded_commands[0]['decoded_input']['actions'][2]['decoded_param']
sell_take_all = decoded_commands[1]['decoded_input']['actions'][2]['decoded_param']
assert buy_swap['zero_for_one'] is True, buy_swap
assert sell_swap['zero_for_one'] is False, sell_swap
assert buy_swap['hook_data_length'] == 0, buy_swap
assert sell_swap['hook_data_length'] == 0, sell_swap
assert buy_settle['payer_is_user'] is True, buy_settle
assert sell_settle['payer_is_user'] is False, sell_settle
assert buy_take_all['recipient'] == '0x0000000000000000000000000000000000000002', buy_take_all
assert sell_take_all['recipient'] == '0x0000000000000000000000000000000000000001', sell_take_all
assert fixture['calldata'].startswith('0x3593564c'), fixture['calldata'][:20]
"""
    pancake_v4_roundtrip_result = subprocess.run(
        [sys.executable, "-c", pancake_v4_roundtrip_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip calldata fixture smoke test",
            pancake_v4_roundtrip_result.returncode == 0,
            pancake_v4_roundtrip_result.stderr.strip(),
        )
    )

    pancake_v4_roundtrip_fixture_verify = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_pancake_v4_roundtrip_fixture.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip fixture matches reviewed ARX legs",
            pancake_v4_roundtrip_fixture_verify.returncode == 0,
            pancake_v4_roundtrip_fixture_verify.stderr.strip(),
        )
    )

    pancake_v4_roundtrip_call_code = """
from scripts.simulate_pancake_v4_roundtrip_call import MAX_UINT48, MAX_UINT160, pack_permit2_allowance, sellability_gate

packed = pack_permit2_allowance(MAX_UINT160, MAX_UINT48, 0)
assert packed == (MAX_UINT48 << 160) | MAX_UINT160, hex(packed)
packed_with_nonce = pack_permit2_allowance(1, 2, 3)
assert packed_with_nonce == (3 << 208) | (2 << 160) | 1, hex(packed_with_nonce)

success_gate = sellability_gate(
    'roundtrip_eth_call_success_no_recovery_rate',
    {'status': 'success', 'return': '0x'},
    {'status': 'unavailable'},
)
assert success_gate['gate'] == 'blocked_infinity_recovery_unverified', success_gate
assert success_gate['can_follow'] is False, success_gate
assert success_gate['can_sell_proven'] is False, success_gate
assert success_gate['recovery_rate'] is None, success_gate

verified_gate = sellability_gate(
    'roundtrip_eth_call_success_with_recovery_rate',
    {'status': 'success', 'return': '0x', 'recovery_rate': '0.995', 'quote_recovered_raw': '995', 'minimum_recovery_rate': '0.80'},
    {'status': 'skipped'},
)
assert verified_gate['gate'] == 'infinity_recovery_rate_verified', verified_gate
assert verified_gate['can_follow'] is True, verified_gate
assert verified_gate['can_sell_proven'] is True, verified_gate

low_gate = sellability_gate(
    'roundtrip_eth_call_success_with_recovery_rate',
    {'status': 'success', 'return': '0x', 'recovery_rate': '0.50', 'quote_recovered_raw': '500', 'minimum_recovery_rate': '0.80'},
    {'status': 'skipped'},
)
assert low_gate['gate'] == 'blocked_infinity_low_recovery', low_gate
assert low_gate['can_follow'] is False, low_gate

revert_gate = sellability_gate(
    'roundtrip_eth_call_reverted',
    {'status': 'reverted_or_failed', 'detail': 'execution reverted'},
    {'status': 'skipped'},
)
assert revert_gate['gate'] == 'blocked_infinity_roundtrip_failed', revert_gate
assert revert_gate['can_follow'] is False, revert_gate

readback_gate = sellability_gate('state_override_blocked', {}, {'status': 'skipped'})
assert readback_gate['gate'] == 'blocked_infinity_readback_failed', readback_gate
assert readback_gate['can_follow'] is False, readback_gate
"""
    pancake_v4_roundtrip_call_result = subprocess.run(
        [sys.executable, "-c", pancake_v4_roundtrip_call_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip eth_call helper smoke test",
            pancake_v4_roundtrip_call_result.returncode == 0,
            pancake_v4_roundtrip_call_result.stderr.strip(),
        )
    )

    current_watchlist_ok = False
    current_watchlist_msg = ""
    try:
        current = json.loads((ROOT / "config" / "current_alpha_watchlist.json").read_text(encoding="utf-8"))
        items = current.get("items", [])
        o_item = next((item for item in items if item.get("symbol") == "O"), {})
        arx_item = next((item for item in items if item.get("symbol") == "ARX"), {})
        nes_item = next((item for item in items if item.get("symbol") == "NES"), {})
        current_watchlist_msg = (
            f"{len(items)} items, O active={o_item.get('active_monitoring')}, "
            f"ARX context={bool(arx_item.get('market_context'))}, NES pools={len(nes_item.get('pool_ids', []))}"
        )
        current_watchlist_ok = (
            len(items) > 0
            and o_item.get("active_monitoring") is False
            and bool(arx_item.get("market_context"))
            and bool(nes_item.get("contracts"))
            and bool(nes_item.get("pool_ids"))
        )
    except Exception as exc:
        current_watchlist_msg = str(exc)
    checks.append(("current alpha watchlist parses", current_watchlist_ok, current_watchlist_msg))

    server_run_ok = False
    server_run_msg = ""
    try:
        server_run_text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")
        opening_run = 'run_step "${ARX_OPENING_TIMEOUT_SECONDS'
        launch_run = 'run_step "${ARX_LAUNCH_TIMEOUT_SECONDS'
        arx_opening_before_launch = (
            opening_run in server_run_text
            and launch_run in server_run_text
            and server_run_text.index(opening_run) < server_run_text.index(launch_run)
        )
        arx_opening_refresh_guard = (
            "RUN_ARX_OPENING_REFRESH" in server_run_text
            and "skipped ARX opening refresh" in server_run_text
            and "arx_opening_sprint.sh" in server_run_text
        )
        arx_launch_guard = (
            "RUN_ARX_LAUNCH_WATCH" in server_run_text
            and "skipped ARX launch watch" in server_run_text
            and "arx_launch_watch.py" in server_run_text
        )
        intraday_run = "alpha_intraday_flow_watch.py"
        opening_funder_run = "review_opening_cohort_funders.py"
        perp_run = "perp_oi_funding_watch.py"
        price_run = "alpha_price_momentum_watch.py"
        holder_run = "alpha_holder_concentration_watch.py"
        external_live_probe_run = "external_aux_live_probe.py"
        position_cost_run = "position_cost_watch.py"
        verification_run = "verify_sniper_engine.py"
        runtime_health_run = "runtime_health_watch.py --mode cycle"
        holder_context_order = (
            intraday_run in server_run_text
            and perp_run in server_run_text
            and price_run in server_run_text
            and holder_run in server_run_text
            and server_run_text.index(intraday_run) < server_run_text.index(perp_run) < server_run_text.index(price_run) < server_run_text.index(holder_run)
        )
        opening_funder_order = (
            "alpha_opening_sprint.sh" in server_run_text
            and opening_funder_run in server_run_text
            and intraday_run in server_run_text
            and server_run_text.index("alpha_opening_sprint.sh") < server_run_text.index(opening_funder_run) < server_run_text.index(intraday_run)
        )
        server_run_ok = (
            "flock -n" in server_run_text
            and "timeout" in server_run_text
            and "SNIPER_MONITOR_TIMEOUT_SECONDS" in server_run_text
            and "ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS" in server_run_text
            and "ALPHA_PRELAUNCH_TIMEOUT_SECONDS" in server_run_text
            and "alpha_prelaunch_watch.py" in server_run_text
            and "ALPHA_OPENING_TIMEOUT_SECONDS" in server_run_text
            and "OPENING_COHORT_FUNDER_TIMEOUT_SECONDS" in server_run_text
            and "OPENING_COHORT_FUNDER_LOOKBACK_BLOCKS" in server_run_text
            and "OPENING_COHORT_FUNDER_MAX_SCAN_SECONDS" in server_run_text
            and opening_funder_run in server_run_text
            and "ALPHA_PRICE_MOMENTUM_TIMEOUT_SECONDS" in server_run_text
            and "alpha_price_momentum_watch.py" in server_run_text
            and "PERP_OI_FUNDING_TIMEOUT_SECONDS" in server_run_text
            and "perp_oi_funding_watch.py" in server_run_text
            and "SURF_AUX_MARKET_TIMEOUT_SECONDS" in server_run_text
            and "surf_aux_market_watch.py" in server_run_text
            and "EXTERNAL_AUX_SOURCE_TIMEOUT_SECONDS" in server_run_text
            and "external_aux_source_readiness.py" in server_run_text
            and "RUN_EXTERNAL_AUX_LIVE_PROBE" in server_run_text
            and "EXTERNAL_AUX_LIVE_PROBE_TIMEOUT_SECONDS" in server_run_text
            and external_live_probe_run in server_run_text
            and "POSITION_COST_TIMEOUT_SECONDS" in server_run_text
            and position_cost_run in server_run_text
            and "alpha_opening_sprint.sh" in server_run_text
            and "ARX_OPENING_TIMEOUT_SECONDS" in server_run_text
            and "arx_opening_sprint.sh" in server_run_text
            and "DISABLE_TELEGRAM" in server_run_text
            and "MONITOR_DISABLED_PROJECTS" in server_run_text
            and "step failed with status" in server_run_text
            and "RUNTIME_HEALTH_FAILURE_FILE" in server_run_text
            and runtime_health_run in server_run_text
            and verification_run in server_run_text
            and server_run_text.index(verification_run) < server_run_text.index(runtime_health_run)
            and "project_continuity_acceptance.py" not in server_run_text
            and "project_continuity_local.py" not in server_run_text
            and "RUN_O1_ATTRIBUTION" in server_run_text
            and arx_opening_refresh_guard
            and arx_launch_guard
            and arx_opening_before_launch
            and opening_funder_order
            and holder_context_order
        )
        server_run_msg = "lock+timeout+failure capture+health alert+O1 pause+ARX refresh/launch+opening funder+perp+surf+position guarded+order present; local continuity excluded" if server_run_ok else "missing runtime guard"
    except Exception as exc:
        server_run_msg = str(exc)
    checks.append(("server run has overlap lock and timeouts", server_run_ok, server_run_msg))

    cron_watchdog_ok = False
    cron_watchdog_msg = ""
    try:
        installer = (ROOT / "scripts" / "install_server_cron.sh").read_text(encoding="utf-8")
        watchdog = (ROOT / "scripts" / "server_health_watchdog.sh").read_text(encoding="utf-8")
        cron_watchdog_ok = (
            "server_run_once.sh" in installer
            and "server_health_watchdog.sh" in installer
            and "*/5 * * * *" in installer
            and "*/10 * * * *" in installer
            and 'mkdir -p "$project_dir/logs"' in installer
            and "runtime_health_watch.py --mode watchdog" in watchdog
            and "RUNTIME_HEALTH_WATCHDOG_TIMEOUT_SECONDS" in watchdog
        )
        cron_watchdog_msg = "main cron plus independent stale-cycle watchdog present" if cron_watchdog_ok else "missing watchdog cron guard"
    except Exception as exc:
        cron_watchdog_msg = str(exc)
    checks.append(("server cron includes independent health watchdog", cron_watchdog_ok, cron_watchdog_msg))

    perp_watch_code = """
import tempfile
from pathlib import Path
import scripts.perp_oi_funding_watch as perp_module
from scripts.perp_oi_funding_watch import aggregate_open_interest_quality, best_ok_venue, cached_funding_records, canonical_funding_records, classify_perp, depth_action_note, depth_metrics, funding_history_note, liquidation_action_note, liquidation_metrics, listed_venue_names, okx_inst_family, summarize_funding_history, total_open_interest, trend_for_symbol, venue_signal_notes

thin = classify_perp({'open_interest_usd': '1000', 'last_funding_rate': '0', 'quote_volume_24h': '0'})
assert thin['status'] == 'thin_or_unusable', thin
crowded = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0.001', 'quote_volume_24h': '10000', 'price_change_pct_24h': '1'})
assert crowded['status'] == 'crowded_funding', crowded
active = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0', 'quote_volume_24h': '2000000', 'price_change_pct_24h': '12'})
assert active['status'] == 'active_perp_market', active
quiet = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0', 'quote_volume_24h': '1000', 'price_change_pct_24h': '1'})
assert quiet['status'] == 'listed_quiet', quiet
normalized_crowded = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0.0001', 'current_funding_rate_8h': '0.0008', 'quote_volume_24h': '1000', 'price_change_pct_24h': '1'})
assert normalized_crowded['status'] == 'crowded_funding', normalized_crowded
canonical = canonical_funding_records(
    [
        {'fundingTime': '1700000000000', 'fundingRate': '0.0009', 'realizedRate': '0.0004'},
        {'fundingTime': '1700000000000', 'fundingRate': '0.0009', 'realizedRate': '0.0004'},
        {'fundingTime': 'bad', 'fundingRate': '0.1'},
    ],
    timestamp_field='fundingTime',
    rate_fields=('realizedRate', 'fundingRate'),
)
assert len(canonical) == 1 and canonical[0]['funding_rate'] == '0.0004' and canonical[0]['source_field'] == 'realizedRate', canonical
base_ts = 1700000000000
positive_history = [
    {'timestamp_ms': base_ts + index * 4 * 60 * 60 * 1000, 'funding_rate': '0.0004'}
    for index in range(7)
]
funding_summary = summarize_funding_history(positive_history, current_rate='0.0002')
assert funding_summary['funding_interval_hours'] == '4', funding_summary
assert funding_summary['current_funding_rate_8h'] == '0.0004', funding_summary
assert funding_summary['funding_24h_cumulative_rate'] == '0.0024', funding_summary
assert funding_summary['funding_history_state'] == 'sustained_long_crowding', funding_summary
assert '持续付费' in funding_history_note(funding_summary), funding_summary
flip_summary = summarize_funding_history(
    [
        {'timestamp_ms': base_ts, 'funding_rate': '-0.0002'},
        {'timestamp_ms': base_ts + 4 * 60 * 60 * 1000, 'funding_rate': '0.0002'},
    ],
    current_rate='0.0002',
)
assert flip_summary['funding_history_state'] == 'funding_flip_positive', flip_summary
fresh_cache = {'entries': {'binance_usdm:TESTUSDT': {'fetched_at': '2099-01-01T00:00:00+00:00', 'records': positive_history}}}
cached_rows, cache_source, cache_error = cached_funding_records(
    fresh_cache,
    'binance_usdm:TESTUSDT',
    lambda: (_ for _ in ()).throw(RuntimeError('fresh cache should bypass fetch')),
)
assert cached_rows == positive_history and cache_source == 'cache' and cache_error == '', (cache_source, cache_error)
stale_cache = {'entries': {'binance_usdm:TESTUSDT': {'fetched_at': '2000-01-01T00:00:00+00:00', 'records': positive_history}}}
stale_rows, stale_source, stale_error = cached_funding_records(
    stale_cache,
    'binance_usdm:TESTUSDT',
    lambda: (_ for _ in ()).throw(RuntimeError('history endpoint unavailable')),
)
assert stale_rows == positive_history and stale_source == 'stale_cache' and 'endpoint unavailable' in stale_error, (stale_source, stale_error)
history = [{
    'generated_at': '2026-06-30T00:00:00+00:00',
    'rows': [{
        'symbol': 'CAP',
        'status': 'ok',
        'mark_price': '0.02',
        'open_interest_usd': '1000000',
        'last_funding_rate': '0.0001',
    }],
}]
trend = trend_for_symbol(history, 'CAP', {'mark_price': '0.022', 'open_interest_usd': '1200000', 'last_funding_rate': '0.0002'}, '2026-06-30T01:00:00+00:00')
assert trend['trend_hint'] == '多头增量', trend
aggregate_history = [{
    'generated_at': '2026-06-30T00:00:00+00:00',
    'rows': [{
        'symbol': 'TOTAL',
        'perp_symbol': 'TOTALUSDT',
        'status': 'ok',
        'venue': 'binance_usdm',
        'mark_price': '1',
        'open_interest_usd': '1000000',
        'total_open_interest_usd': '6000000',
        'listed_venues': ['binance_usdm', 'okx_swap', 'bybit_linear'],
        'extra_venues': [
            {'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': '2000000'},
            {'venue': 'bybit_linear', 'status': 'ok', 'open_interest_usd': '3000000'},
        ],
        'last_funding_rate': '0',
    }],
}]
aggregate_trend = trend_for_symbol(
    aggregate_history,
    'TOTAL',
    {
        'perp_symbol': 'TOTALUSDT',
        'venue': 'binance_usdm',
        'mark_price': '1',
        'open_interest_usd': '1000000',
        'total_open_interest_usd': '9000000',
        'listed_venues': ['binance_usdm', 'okx_swap', 'bybit_linear'],
        'extra_venues': [
            {'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': '3000000'},
            {'venue': 'bybit_linear', 'status': 'ok', 'open_interest_usd': '5000000'},
        ],
        'last_funding_rate': '0',
    },
    '2026-06-30T01:00:00+00:00',
)
assert aggregate_trend['oi_usd_delta_pct'] == '0', aggregate_trend
assert aggregate_trend['trend_hint'] == '观察', aggregate_trend
assert aggregate_trend['total_oi_trend_status'] == 'scope_match', aggregate_trend
assert aggregate_trend['total_oi_usd_delta'] == '3000000', aggregate_trend
assert aggregate_trend['total_oi_usd_delta_pct'] == '50.0', aggregate_trend
assert aggregate_trend['total_oi_data_quality'] == 'complete', aggregate_trend
original_history_path = perp_module.HISTORY_PATH
original_latest_path = perp_module.LATEST_PATH
try:
    history_dir = Path(tempfile.mkdtemp(prefix='perp_history_roundtrip_'))
    perp_module.HISTORY_PATH = history_dir / 'history.jsonl'
    perp_module.LATEST_PATH = history_dir / 'latest.json'
    perp_module.append_history({'generated_at': '2026-06-30T00:00:00+00:00', 'source_status': 'ok', 'rows': aggregate_history[0]['rows']})
    roundtrip = perp_module.read_history()
    stored_aggregate = roundtrip[0]['rows'][0]
    assert stored_aggregate['oi_venue_components'] == {
        'binance_usdm': '1000000',
        'okx_swap': '2000000',
        'bybit_linear': '3000000',
    }, stored_aggregate
    stored_scope, stored_quality = aggregate_open_interest_quality(stored_aggregate)
    assert stored_scope == ['binance_usdm', 'bybit_linear', 'okx_swap'] and stored_quality is True, (stored_scope, stored_quality)
    roundtrip_trend = trend_for_symbol(roundtrip, 'TOTAL', {
        'perp_symbol': 'TOTALUSDT',
        'venue': 'binance_usdm',
        'mark_price': '1',
        'open_interest_usd': '1000000',
        'total_open_interest_usd': '9000000',
        'listed_venues': ['binance_usdm', 'okx_swap', 'bybit_linear'],
        'oi_venue_components': {'binance_usdm': '1000000', 'okx_swap': '3000000', 'bybit_linear': '5000000'},
        'last_funding_rate': '0',
    }, '2026-06-30T01:00:00+00:00')
    assert roundtrip_trend['total_oi_trend_status'] == 'scope_match', roundtrip_trend
    assert roundtrip_trend['total_oi_usd_delta_pct'] == '50.0', roundtrip_trend
finally:
    perp_module.HISTORY_PATH = original_history_path
    perp_module.LATEST_PATH = original_latest_path
bad_scope, bad_quality = aggregate_open_interest_quality({
    'venue': 'binance_usdm',
    'open_interest_usd': '0',
    'total_open_interest_usd': '0',
    'listed_venues': ['binance_usdm', 'okx_swap'],
    'extra_venues': [{'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': ''}],
})
assert bad_scope == ['binance_usdm', 'okx_swap'] and bad_quality is False, (bad_scope, bad_quality)
incomplete_trend = trend_for_symbol(
    aggregate_history,
    'TOTAL',
    {
        'perp_symbol': 'TOTALUSDT',
        'venue': 'binance_usdm',
        'mark_price': '1',
        'open_interest_usd': '0',
        'total_open_interest_usd': '0',
        'listed_venues': ['binance_usdm', 'okx_swap', 'bybit_linear'],
        'extra_venues': [
            {'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': ''},
            {'venue': 'bybit_linear', 'status': 'ok', 'open_interest_usd': ''},
        ],
        'last_funding_rate': '0',
    },
    '2026-06-30T01:00:00+00:00',
)
assert incomplete_trend['total_oi_trend_status'] == 'incomplete_components', incomplete_trend
assert incomplete_trend['total_oi_usd_delta_pct'] == '', incomplete_trend
scope_mismatch = trend_for_symbol(
    aggregate_history,
    'TOTAL',
    {
        'perp_symbol': 'TOTALUSDT',
        'venue': 'binance_usdm',
        'mark_price': '1',
        'open_interest_usd': '1000000',
        'total_open_interest_usd': '7000000',
        'listed_venues': ['binance_usdm', 'okx_swap'],
        'extra_venues': [{'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': '6000000'}],
        'last_funding_rate': '0',
    },
    '2026-06-30T01:00:00+00:00',
)
assert scope_mismatch['total_oi_trend_status'] == 'scope_mismatch', scope_mismatch
assert scope_mismatch['total_oi_usd_delta_pct'] == '', scope_mismatch
history_cross_venue = [{
    'generated_at': '2026-06-30T00:00:00+00:00',
    'rows': [{
        'symbol': 'GRAM',
        'perp_symbol': 'GRAM-USDT-SWAP',
        'status': 'ok',
        'mark_price': '0.02',
        'open_interest_usd': '1000000',
        'last_funding_rate': '0.0001',
    }],
}]
cross_venue_trend = trend_for_symbol(history_cross_venue, 'GRAM', {'perp_symbol': 'GRAMUSDT', 'mark_price': '0.022', 'open_interest_usd': '5000000', 'last_funding_rate': '0.0001'}, '2026-06-30T01:00:00+00:00')
assert cross_venue_trend['trend_status'] == 'no_history', cross_venue_trend
venues = [
    {'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': '2000000', 'last_funding_rate': '0.0006', 'direction_hint': '拥挤'},
    {'venue': 'bybit_linear', 'status': 'ok', 'open_interest_usd': '3000000', 'last_funding_rate': '0.0001', 'direction_hint': '可观察'},
]
assert best_ok_venue(venues)['venue'] == 'bybit_linear', venues
primary = {'venue': 'binance_usdm', 'open_interest_usd': '1000000'}
assert listed_venue_names(primary, venues) == ['binance_usdm', 'okx_swap', 'bybit_linear']
assert str(total_open_interest(primary, venues)) == '6000000'
notes = venue_signal_notes(venues)
assert len(notes) == 2 and 'okx_swap' in notes[0] and 'bybit_linear' in notes[1], notes
depth = depth_metrics(
    '1',
    bids=[['0.999', '60000'], ['0.990', '100000']],
    asks=[['1.001', '12000'], ['1.004', '14000'], ['1.020', '100000']],
    band_bps=None,
)
assert depth['depth_status'] == 'ok', depth
assert depth['depth_state'] == 'ask_thin', depth
assert depth['bid_depth_usd'] == '59940.000', depth
assert depth['ask_depth_usd'] == '26068.000', depth
assert '上方卖盘薄' in depth_action_note(depth), depth
thin_depth = depth_metrics('1', bids=[['0.999', '10']], asks=[['1.001', '10']], band_bps=None)
assert thin_depth['depth_state'] == 'thin_depth', thin_depth
liq = liquidation_metrics(
    [
        {'bkPx': '1', 'sz': '30000', 'posSide': 'long', 'side': 'sell', 'ts': '100000'},
        {'bkPx': '1', 'sz': '2000', 'posSide': 'short', 'side': 'buy', 'ts': '100000'},
    ],
    now_ms=100000,
    lookback_minutes=60,
)
assert liq['liquidation_state'] == 'long_liquidation_pressure', liq
assert liq['long_liquidation_usd'] == '30000', liq
assert '多头强平压力' in liquidation_action_note(liq), liq
old_liq = liquidation_metrics([{'bkPx': '1', 'sz': '50000', 'posSide': 'short', 'side': 'buy', 'ts': '1'}], now_ms=100000000, lookback_minutes=1)
assert old_liq['liquidation_state'] == 'no_recent_liquidation', old_liq
assert okx_inst_family('ARX-USDT-SWAP', {}) == 'ARX-USDT'
assert okx_inst_family('ARX-USDT-SWAP', {'instFamily': 'ARX-USDT'}) == 'ARX-USDT'
"""
    perp_watch_result = subprocess.run(
        [sys.executable, "-c", perp_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("perp OI/funding classifier smoke test", perp_watch_result.returncode == 0, perp_watch_result.stderr.strip()))

    deploy_ok = False
    deploy_msg = ""
    try:
        deploy_text = (ROOT / "scripts" / "deploy_to_server.sh").read_text(encoding="utf-8")
        required_excludes = ["--exclude 'output/'", "--exclude 'reports/'", "--exclude 'logs/'", "--exclude '.env.local'", "--exclude '*.session'"]
        deploy_ok = all(item in deploy_text for item in required_excludes)
        deploy_msg = "runtime-state excludes present" if deploy_ok else "missing runtime-state exclude"
    except Exception as exc:
        deploy_msg = str(exc)
    checks.append(("deploy script preserves server runtime state", deploy_ok, deploy_msg))

    compile_cmd = [
        sys.executable,
        "-m",
        "py_compile",
        str(ROOT / "sniper_engine" / "scoring.py"),
        str(ROOT / "sniper_engine" / "local_sources.py"),
        str(ROOT / "sniper_engine" / "rpc.py"),
        str(ROOT / "sniper_engine" / "telegram_send_receipt.py"),
        str(ROOT / "sniper_engine" / "project_registry.py"),
        str(ROOT / "sniper_engine" / "address_labels.py"),
        str(ROOT / "sniper_engine" / "entity_clustering.py"),
        str(ROOT / "sniper_engine" / "exchange_aggregator.py"),
        str(ROOT / "scripts" / "sniper_score_local.py"),
        str(ROOT / "scripts" / "alpha_project_watch.py"),
        str(ROOT / "scripts" / "alpha_holder_concentration_watch.py"),
        str(ROOT / "scripts" / "alpha_prelaunch_watch.py"),
        str(ROOT / "scripts" / "alpha_opening_block_watch.py"),
        str(ROOT / "scripts" / "alpha_price_momentum_watch.py"),
        str(ROOT / "scripts" / "alpha_intraday_flow_watch.py"),
        str(ROOT / "scripts" / "verify_alpha_aggregator_trace.py"),
        str(ROOT / "scripts" / "collect_alpha_trace_bundle.py"),
        str(ROOT / "scripts" / "review_alpha_swap_samples.py"),
        str(ROOT / "scripts" / "review_alpha_swap_txs.py"),
        str(ROOT / "scripts" / "review_exchange_wallet_labels.py"),
        str(ROOT / "scripts" / "review_pancake_v4_samples.py"),
        str(ROOT / "scripts" / "x_mcp_readiness.py"),
        str(ROOT / "scripts" / "external_aux_source_readiness.py"),
        str(ROOT / "scripts" / "external_aux_live_probe.py"),
        str(ROOT / "scripts" / "position_cost_watch.py"),
        str(ROOT / "scripts" / "project_continuity_acceptance.py"),
        str(ROOT / "scripts" / "test_project_continuity_acceptance.py"),
        str(ROOT / "scripts" / "decode_pancake_v4_execute.py"),
        str(ROOT / "scripts" / "build_pancake_v4_roundtrip_fixture.py"),
        str(ROOT / "scripts" / "probe_pancake_v4_state_override.py"),
        str(ROOT / "scripts" / "simulate_pancake_v4_roundtrip_call.py"),
        str(ROOT / "scripts" / "arx_launch_watch.py"),
        str(ROOT / "scripts" / "arx_opening_block_watch.py"),
        str(ROOT / "scripts" / "build_alpha_daily_report.py"),
        str(ROOT / "scripts" / "prediction_market_watch.py"),
        str(ROOT / "scripts" / "telegram_signal_collector.py"),
        str(ROOT / "scripts" / "telegram_user_signal_collector.py"),
        str(ROOT / "scripts" / "telegram_user_login.py"),
        str(ROOT / "scripts" / "add_telegram_source.py"),
        str(ROOT / "scripts" / "analyze_pancake_pool_tx.py"),
        str(ROOT / "scripts" / "ingest_alpha_signal.py"),
        str(ROOT / "scripts" / "build_monitored_wallets.py"),
        str(ROOT / "scripts" / "o1_address_attribution.py"),
        str(ROOT / "scripts" / "sniper_monitor.py"),
        str(ROOT / "scripts" / "o1_block_verifier.py"),
        str(ROOT / "scripts" / "o1_decode_pancake_v3.py"),
        str(ROOT / "scripts" / "o1_trace_front_buyers.py"),
        str(ROOT / "scripts" / "summarize_hertzflow_skeleton.py"),
    ]
    compile_env = os.environ.copy()
    compile_env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)
    compile_result = subprocess.run(compile_cmd, cwd=ROOT, env=compile_env, capture_output=True, text=True)
    checks.append(("python files compile", compile_result.returncode == 0, compile_result.stderr.strip()))

    telegram_send_receipt_code = """
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('telegram_send_receipt', root / 'sniper_engine' / 'telegram_send_receipt.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AcceptedResponse:
    status = 200
    def read(self):
        return json.dumps({
            'ok': True,
            'result': {
                'message_id': 123,
                'date': 1783987200,
                'chat': {'id': 456, 'username': 'must_not_persist'},
                'from': {'id': 789, 'username': 'must_not_persist'},
                'text': 'server echo must not persist',
            },
        }).encode('utf-8')

receipt = module.read_telegram_send_receipt(AcceptedResponse())
assert receipt == {
    'api_ok': True,
    'http_status': 200,
    'message_id': 123,
    'message_date': 1783987200,
}, receipt
text = 'line 1\\nline 2'
out = Path(tempfile.mkdtemp(prefix='telegram_receipt_')) / 'last_push.json'
module.record_telegram_send_receipt(
    out,
    sent_at='2026-07-14T00:00:00+00:00',
    signature='fixture',
    text=text,
    receipt=receipt,
)
saved = json.loads(out.read_text(encoding='utf-8'))
assert set(saved) == {
    'sent_at', 'signature', 'text', 'text_chars', 'text_lines', 'text_sha256',
    'api_ok', 'http_status', 'message_id', 'message_date',
}, saved
assert saved['text'] == text and saved['text_chars'] == len(text) and saved['text_lines'] == 2, saved
assert saved['text_sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest(), saved
assert 'must_not_persist' not in out.read_text(encoding='utf-8'), saved

class RejectedResponse:
    status = 200
    def read(self):
        return b'{"ok": false, "description": "fixture rejection"}'

try:
    module.read_telegram_send_receipt(RejectedResponse())
except RuntimeError:
    pass
else:
    raise AssertionError('Telegram ok=false response must fail closed')

class MalformedResponse:
    status = 200
    def read(self):
        return b'not-json'

try:
    module.read_telegram_send_receipt(MalformedResponse())
except RuntimeError:
    pass
else:
    raise AssertionError('Malformed Telegram response must fail closed')

class AcceptedWithoutMessageId:
    def getcode(self):
        return 200
    def read(self):
        return b'{"ok": true, "result": {"date": 1783987201}}'

partial_receipt = module.read_telegram_send_receipt(AcceptedWithoutMessageId())
assert partial_receipt == {
    'api_ok': True,
    'http_status': 200,
    'message_id': None,
    'message_date': 1783987201,
}, partial_receipt

for relative_path in [
    'scripts/alpha_project_watch.py',
    'scripts/alpha_opening_block_watch.py',
    'scripts/alpha_holder_concentration_watch.py',
    'scripts/alpha_price_momentum_watch.py',
    'scripts/alpha_intraday_flow_watch.py',
]:
    source = (root / relative_path).read_text(encoding='utf-8')
    assert 'read_telegram_send_receipt(response)' in source, relative_path
    assert 'record_telegram_send_receipt(' in source, relative_path
    assert 'text=text' in source, relative_path
    send_block = source.split('def maybe_send_telegram', 1)[1].split('\\ndef ', 1)[0]
    receipt_index = send_block.index('receipt = read_telegram_send_receipt(response)')
    seen_index = send_block.rindex('write_json(SEEN_PATH')
    record_call = 'record_telegram_send_receipt(' if 'record_telegram_send_receipt(' in send_block else 'record_push('
    record_index = send_block.index(record_call)
    assert receipt_index < seen_index < record_index, relative_path
"""
    telegram_send_receipt_result = subprocess.run(
        [sys.executable, "-c", telegram_send_receipt_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "Telegram accepted-send receipts retain exact compact text safely",
            telegram_send_receipt_result.returncode == 0,
            telegram_send_receipt_result.stderr.strip(),
        )
    )

    holder_watch_code = """
import importlib.util
import json
import os
import tempfile
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_holder_concentration_watch', root / 'scripts' / 'alpha_holder_concentration_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SURF_HOLDER_QUOTA_STATE_PATH = Path(tempfile.mkdtemp(prefix='surf_holder_quota_')) / 'quota.json'
token = '0x' + 'a' * 40
infra = '0x' + '1' * 40
holder_a = '0x' + '2' * 40
holder_b = '0x' + '3' * 40
holder_c = '0x' + '4' * 40
module.global_address_label = lambda chain, address: {'class': 'exchange_aggregator', 'label': 'Alpha Custody'} if address == infra else None
module.get_code = lambda chain, address, cache: '0x'
balances = {infra: 400, holder_a: 300, holder_b: 200, holder_c: 100}
raw_rows = module.top_rows(balances, 'bsc', token, 1000, 0, {}, effective=False)
effective_rows = module.top_rows(balances, 'bsc', token, 1000, 0, {}, effective=True)
assert str(module.pct_sum(raw_rows)) == '100', raw_rows
assert str(module.pct_sum(effective_rows)) == '60', effective_rows
assert raw_rows[0]['class'] == 'exchange_aggregator', raw_rows
signal = module.classify_signal(
    {'effective_top10_pct': '60', 'effective_top10_delta_pct': '-2', 'raw_top10_pct': '100', 'raw_top10_delta_pct': '0', 'raw_top10_infra_pct': '40', 'raw_top10_infra_delta_pct': '0'},
    {'effective_top10_pct': '62', 'raw_top10_pct': '100', 'raw_top10_infra_pct': '40'},
)
assert signal['direction'] == 'effective_top10_down', signal
assert '持仓降风险' in signal['action'], signal
baseline = module.classify_signal({'effective_top10_pct': '60'}, None)
assert baseline['direction'] == 'baseline', baseline
class FakeSurfResult:
    returncode = 0
    stderr = ''
    stdout = json.dumps({
        'data': [
            {'address': infra, 'balance': '400', 'percentage': 40, 'entity_name': 'Binance Wallet', 'entity_type': 'misc'},
            {'address': holder_a, 'balance': '300', 'percentage': 30, 'entity_name': None, 'entity_type': None},
            {'address': holder_b, 'balance': '200', 'percentage': 20, 'entity_name': 'PancakeSwap', 'entity_type': 'dex'},
            {'address': holder_c, 'balance': '100', 'percentage': 10, 'entity_name': None, 'entity_type': None},
        ],
        'meta': {'credits_used': 0},
    })

def fake_surf_run(*args, **kwargs):
    return FakeSurfResult()

module.subprocess.run = fake_surf_run
module.surf_cli = lambda: 'surf'
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
surf_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert surf_status['status'] == 'ok', surf_status
assert 'Surf全量Top10 100.00%' in surf_status['summary'], surf_status
assert '交易所/DEX/托管约 60.00%' in surf_status['summary'], surf_status
class FakeSurfQuotaResult:
    returncode = 4
    stderr = ''
    stdout = json.dumps({'error': {'code': 'FREE_QUOTA_EXHAUSTED', 'message': 'free daily credit exhausted'}})

module.subprocess.run = lambda *args, **kwargs: FakeSurfQuotaResult()
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
quota_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert quota_status['status'] == 'FREE_QUOTA_EXHAUSTED', quota_status
assert 'Surf免费额度已用完' in quota_status['summary'], quota_status
def should_not_call_surf(*args, **kwargs):
    raise AssertionError('quota cache should block surf subprocess call')

module.subprocess.run = should_not_call_surf
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
cached_quota_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert cached_quota_status['status'] == 'FREE_QUOTA_EXHAUSTED', cached_quota_status
assert '今日不再请求' in cached_quota_status['summary'], cached_quota_status
bearish_market_context = {
    'price': {'TEST': {'stale': False, 'age_minutes': 5, 'analysis': {'direction': '放量走弱', 'trade_signal': 'Alpha 放量收跌；卖出/减仓观察'}}},
    'flow': {'TEST': {'stale': False, 'age_minutes': 5, 'analysis': {'direction': '偏空', 'trade_signal': '卖出/减仓；盘中大额净卖出'}}},
}
holder_project = {
    'symbol': 'TEST',
    'priority': 'P1_MONITOR',
    'chain': 'bsc',
    'address': token,
    'complete_holder_reconstruction': False,
    'log_count': 3,
    'metrics': {
        'effective_top10_pct': '60',
        'effective_top10_delta_pct': '-2',
        'raw_top10_pct': '100',
        'raw_top10_delta_pct': '0',
        'raw_top10_infra_pct': '40',
    },
    'full_holder_source': surf_status,
    'signal': signal,
}
holder_project['decision_context'] = module.holder_decision_context(holder_project, bearish_market_context)
assert '偏空确认' in holder_project['decision_context']['action'], holder_project
up_project = {
    **holder_project,
    'signal': {'direction': 'effective_top10_up', 'action': '吸筹观察；等价格承接和净买确认', 'reason': 'test', 'level': 'HIGH'},
    'metrics': {**holder_project['metrics'], 'effective_top10_delta_pct': '2'},
}
up_project['decision_context'] = module.holder_decision_context(up_project, {'price': {}, 'flow': {}})
assert '吸筹观察' in up_project['decision_context']['action'], up_project
text = module.telegram_text({
    'generated_at': '2026-07-03T00:00:00+00:00',
    'project_count': 1,
    'alert_count': 1,
    'projects': [holder_project],
})
assert text.startswith('Alpha 前十持仓｜触发1'), text
assert '🚨TEST P1_MONITOR｜排托管前十分散｜CRITICAL' in text, text
assert '动作：偏空确认；持仓减仓/离场，空仓不接' in text, text
assert '排托管Top10 60.00%（-2.00pp）' in text, text
assert '窗口Top10 100.00%' in text and '基础设施 40.00%' in text, text
assert 'Surf全量Top10 100.00%' in text, text
assert '有效总结' not in text and '项目总结汇总' not in text, text
assert len(text) <= 320 and len(text.splitlines()) <= 4, (len(text), text)
many_text = module.telegram_text({
    'alert_count': 3,
    'projects': [
        holder_project,
        {**up_project, 'symbol': 'UP'},
        {**up_project, 'symbol': 'THIRD'},
        {**up_project, 'symbol': 'LOW', 'signal': {'direction': 'flat', 'action': '观察', 'level': 'INFO'}},
    ],
})
assert many_text.count('动作：') == 2 and '另有1项｜详情已归档' in many_text, many_text
assert 'LOW' not in many_text, many_text
assert len(many_text) <= 650 and len(many_text.splitlines()) <= 10, (len(many_text), many_text)
third_project = {**up_project, 'symbol': 'THIRD'}
third_key = module.alert_keys({'projects': [third_project]})[0]
new_first_text = module.telegram_text({
    'alert_count': 3,
    '_telegram_new_alert_keys': [third_key],
    'projects': [holder_project, {**up_project, 'symbol': 'UP'}, third_project],
})
assert 'THIRD' in new_first_text and 'TEST' in new_first_text and 'UP ' not in new_first_text, new_first_text
same_bucket = {**holder_project, 'metrics': {**holder_project['metrics'], 'effective_top10_delta_pct': '-2.4'}}
next_bucket = {**holder_project, 'metrics': {**holder_project['metrics'], 'effective_top10_delta_pct': '-2.6'}}
assert module.alert_keys({'projects': [holder_project]}) == module.alert_keys({'projects': [same_bucket]}), (holder_project, same_bucket)
assert module.alert_keys({'projects': [holder_project]}) != module.alert_keys({'projects': [next_bucket]}), (holder_project, next_bucket)
print(f"raw={module.pct_sum(raw_rows)} effective={module.pct_sum(effective_rows)} signal={signal['direction']}")
"""
    holder_watch = subprocess.run(
        [sys.executable, "-c", holder_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    holder_watch_ok = holder_watch.returncode == 0
    holder_watch_msg = holder_watch.stdout.strip() or holder_watch.stderr.strip()
    checks.append(("holder concentration excludes infrastructure and flags downtrend", holder_watch_ok, holder_watch_msg))

    alpha_intraday_cex_code = """
import importlib.util
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_intraday_flow_watch', root / 'scripts' / 'alpha_intraday_flow_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.now_utc = lambda: datetime(2026, 7, 2, 8, 12, tzinfo=timezone.utc)
event = {
    'symbol': 'TEST',
    'chain': 'bsc',
    'token': {'address': '0x' + 'a' * 40, 'symbol': 'TEST', 'decimals': 18},
    'quote': {'address': '0x' + 'b' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {'observed_binance_alpha_price_usdt': '0.05'},
    'cex_deposit_addresses': ['0x' + 'c' * 40],
    'cex_addresses': ['0x' + 'd' * 40],
    'known_contracts': [],
}
module.opening.has_contract_code = lambda chain, address: False
hot = '0x' + '9' * 40
deposit = '0x' + '8' * 40
real_global_labels = module.opening.global_address_labels
def fake_global_labels(chain):
    rows = real_global_labels(chain)
    rows[hot] = {'address': hot, 'class': 'cex_hot_wallet', 'exchange': 'FixtureEx', 'label': 'Fixture Hot'}
    rows[deposit] = {'address': deposit, 'class': 'cex_deposit', 'exchange': 'FixtureEx', 'label': 'Fixture Deposit'}
    return rows
module.opening.global_address_labels = fake_global_labels
module.WITHDRAWAL_TIME_RPC_TIMEOUT_SECONDS = 2
module.WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS = 4
module.WITHDRAWAL_TIME_RPC_ATTEMPTS_USED = 0
module.opening.rpc_urls = lambda chain: ['fixture://primary', 'fixture://fallback', 'fixture://ignored']

def block_header_success(url, method, params, timeout):
    assert method == 'eth_getBlockByNumber' and timeout == 2, (method, timeout)
    block = int(params[0], 16)
    return {'timestamp': hex(1700000000 + block * 3)}

module.opening.rpc_call_url = block_header_success

equal_withdrawals = [
    {
        'token': event['token']['address'],
        'from': hot,
        'to': f"0x{index:040x}",
        'amount': module.Decimal(str(amount)),
        'block': 100 + index,
        'log_index': 10,
        'tx': f"0x{index:064x}",
    }
    for index, amount in enumerate([30000, 30300, 29700, 30150, 29850, 30075, 29925, 30000], 1)
]
def prior_transfer(recipient, block, log_index, marker):
    return {
        **equal_withdrawals[0],
        'from': '0x' + marker * 40,
        'to': recipient,
        'amount': module.Decimal('1'),
        'block': block,
        'log_index': log_index,
        'tx': '0x' + marker * 64,
    }

recipient_history_transfers = equal_withdrawals + [
    prior_transfer(equal_withdrawals[0]['to'], equal_withdrawals[0]['block'], 9, 'a'),
    prior_transfer(equal_withdrawals[1]['to'], equal_withdrawals[1]['block'], 11, 'b'),
]
complete_coverage = {
    'state': 'requested_window_complete',
    'requested_from_block': 100,
    'requested_to_block': 200,
    'covered_through_block': 200,
    'completed_chunk_count': 1,
    'chunk_blocks': 1000,
    'max_logs': 12000,
    'returned_log_count': len(recipient_history_transfers),
    'complete': True,
}
withdrawal = module.cex_withdrawal_cluster(event, recipient_history_transfers, 100, 200, complete_coverage)
assert withdrawal['candidate_count'] == 1, withdrawal
assert withdrawal['coverage_state'] == 'requested_window_complete', withdrawal
assert withdrawal['log_window_coverage'] == complete_coverage, withdrawal
withdrawal_row = withdrawal['clusters'][0]
assert withdrawal_row['recipient_count'] == 8 and withdrawal_row['transfer_count'] == 8, withdrawal_row
assert withdrawal_row['first_block'] == 101 and withdrawal_row['last_block'] == 108, withdrawal_row
assert withdrawal_row['first_block_time_utc'].endswith('Z') and withdrawal_row['last_block_time_utc'].endswith('Z'), withdrawal_row
assert withdrawal_row['window_seconds'] == 21, withdrawal_row
assert withdrawal_row['time_window_evidence'] == 'rpc_block_header', withdrawal_row
assert withdrawal_row['direction'] == 'unknown' and withdrawal_row['action'] == 'Observe', withdrawal_row
assert withdrawal_row['alert_policy'] == 'report_only', withdrawal_row
assert withdrawal_row['fresh_recipient_count'] is None, withdrawal_row
assert withdrawal_row['recipient_freshness_state'] == 'bounded_same_token_window', withdrawal_row
assert withdrawal_row['prior_token_inbound_recipient_count'] == 1, withdrawal_row
assert withdrawal_row['new_to_token_in_window_recipient_count'] == 7, withdrawal_row
history_by_recipient = {row['recipient']: row for row in withdrawal_row['recipient_history_sample']}
assert history_by_recipient[equal_withdrawals[0]['to']]['new_to_token_in_window'] is False, history_by_recipient
assert history_by_recipient[equal_withdrawals[1]['to']]['new_to_token_in_window'] is True, history_by_recipient
assert withdrawal_row['common_gas_source_ratio'] is None, withdrawal_row
assert 'common_gas_source' in withdrawal_row['unresolved_gates'], withdrawal_row
assert withdrawal_row['next_hop_state'] == 'unknown', withdrawal_row
assert {'entity_linkage', 'operator_conflict'} <= set(withdrawal_row['unresolved_gates']), withdrawal_row
assert 'recipient_freshness' in withdrawal_row['unresolved_gates'], withdrawal_row
assert 'log_window_completeness' not in withdrawal_row['unresolved_gates'], withdrawal_row
assert 'exact_time_window' not in withdrawal_row['unresolved_gates'], withdrawal_row
assert module.Decimal(withdrawal_row['equal_tranche_cv']) <= module.Decimal('0.20'), withdrawal_row

def raw_transfer_log(block, log_index, recipient):
    return {
        'address': event['token']['address'],
        'blockNumber': hex(block),
        'transactionHash': f"0x{block:064x}",
        'logIndex': hex(log_index),
        'topics': [
            module.opening.TRANSFER_TOPIC,
            module.opening.address_topic('0x' + '7' * 40),
            module.opening.address_topic(recipient),
        ],
        'data': hex(10**18),
    }

real_quick_rpc = module.opening.quick_rpc_call
transfer_env = {
    key: os.environ.get(key)
    for key in ('ALPHA_INTRADAY_LOG_CHUNK_BLOCKS', 'ALPHA_INTRADAY_MAX_LOGS', 'ALPHA_INTRADAY_RPC_TIMEOUT')
}
os.environ.update({'ALPHA_INTRADAY_LOG_CHUNK_BLOCKS': '1000', 'ALPHA_INTRADAY_MAX_LOGS': '12000', 'ALPHA_INTRADAY_RPC_TIMEOUT': '6'})
fetch_fixture = {'mode': 'complete', 'calls': []}
def fixture_log_fetch(chain, method, params, timeout):
    start = int(params[0]['fromBlock'], 16)
    fetch_fixture['calls'].append(start)
    if fetch_fixture['mode'] == 'partial' and start > 100:
        raise TimeoutError('fixture partial transfer-log timeout')
    if fetch_fixture['mode'] == 'cap':
        return [raw_transfer_log(101, 1, equal_withdrawals[0]['to']), raw_transfer_log(102, 2, equal_withdrawals[1]['to'])]
    return [raw_transfer_log(101, 1, equal_withdrawals[0]['to'])] if start == 100 else []

module.opening.quick_rpc_call = fixture_log_fetch
complete_rows, fetched_complete_coverage = module.token_transfer_logs_with_coverage(event, 100, 1200)
assert len(complete_rows) == 1 and fetch_fixture['calls'] == [100, 1100], fetch_fixture
assert fetched_complete_coverage['state'] == 'requested_window_complete' and fetched_complete_coverage['covered_through_block'] == 1200, fetched_complete_coverage
fetch_fixture.update(mode='partial', calls=[])
_, partial_coverage = module.token_transfer_logs_with_coverage(event, 100, 1200)
assert partial_coverage['state'] == 'partial_rpc_error' and partial_coverage['covered_through_block'] == 1099, partial_coverage
fetch_fixture.update(mode='cap', calls=[])
os.environ['ALPHA_INTRADAY_MAX_LOGS'] = '2'
_, capped_fetch_coverage = module.token_transfer_logs_with_coverage(event, 100, 200)
module.opening.quick_rpc_call = real_quick_rpc
for key, value in transfer_env.items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
assert capped_fetch_coverage['state'] == 'max_log_limit_reached' and capped_fetch_coverage['complete'] is False, capped_fetch_coverage

real_aggregate_candidate_txs = module.aggregate_candidate_txs
real_transfer_logs_with_coverage = module.token_transfer_logs_with_coverage
transfer_fetch_calls = []
module.aggregate_candidate_txs = lambda event_arg, from_arg, to_arg: ([], 0, 0)
def one_transfer_fetch(event_arg, from_arg, to_arg):
    transfer_fetch_calls.append((from_arg, to_arg))
    return [], complete_coverage
module.token_transfer_logs_with_coverage = one_transfer_fetch
scanned_once = module.scan_event({**event, 'opening_block': 100, 'latest_block': 200})
module.aggregate_candidate_txs = real_aggregate_candidate_txs
module.token_transfer_logs_with_coverage = real_transfer_logs_with_coverage
assert transfer_fetch_calls == [(100, 200)], transfer_fetch_calls
assert scanned_once['analysis']['cex_withdrawal_cluster']['coverage_state'] == 'requested_window_complete', scanned_once
real_build_events = module.build_events
real_scan_event = module.scan_event
module.build_events = lambda: [event]
module.scan_event = lambda event_arg: dict(scanned_once)
collected_forward_scans = []
collected_snapshot = module.build_snapshot(collected_forward_scans)
module.build_events = real_build_events
module.scan_event = real_scan_event
assert len(collected_forward_scans) == 1, collected_forward_scans
assert '_withdrawal_forward_scan' not in collected_snapshot['events'][0], collected_snapshot

timeout_calls = []
def fail_block_header(url, method, params, timeout):
    timeout_calls.append((url, timeout))
    raise TimeoutError('fixture RPC timeout')

module.WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS = 2
module.WITHDRAWAL_TIME_RPC_ATTEMPTS_USED = 0
module.opening.rpc_call_url = fail_block_header
unavailable_time = module.cex_withdrawal_cluster(event, equal_withdrawals, 100, 200)
assert unavailable_time['candidate_count'] == 1, unavailable_time
unavailable_row = unavailable_time['clusters'][0]
assert unavailable_row['first_block_time_utc'] is None and unavailable_row['last_block_time_utc'] is None, unavailable_row
assert unavailable_row['window_seconds'] is None, unavailable_row
assert unavailable_row['time_window_evidence'] == 'rpc_block_header_unavailable', unavailable_row
assert 'exact_time_window' in unavailable_row['unresolved_gates'], unavailable_row
assert {'recipient_freshness', 'log_window_completeness'} <= set(unavailable_row['unresolved_gates']), unavailable_row
assert unavailable_row['recipient_freshness_state'] == 'partial_log_window' and unavailable_row['new_to_token_in_window_recipient_count'] is None, unavailable_row
assert all(row['new_to_token_in_window'] is None for row in unavailable_row['recipient_history_sample']), unavailable_row
assert unavailable_row['direction'] == 'unknown' and unavailable_row['action'] == 'Observe', unavailable_row
assert timeout_calls == [('fixture://primary', 2), ('fixture://fallback', 2)], timeout_calls
budget_exhausted_time = module.cex_withdrawal_cluster(event, equal_withdrawals, 100, 200)
assert budget_exhausted_time['candidate_count'] == 1, budget_exhausted_time
assert len(timeout_calls) == 2, timeout_calls
assert 'exact_time_window' in budget_exhausted_time['clusters'][0]['unresolved_gates'], budget_exhausted_time

capped_withdrawal = module.cex_withdrawal_cluster(
    event,
    recipient_history_transfers,
    100,
    200,
    capped_fetch_coverage,
)
capped_row = capped_withdrawal['clusters'][0]
assert capped_withdrawal['coverage_state'] == 'max_log_limit_reached', capped_withdrawal
assert {'recipient_freshness', 'log_window_completeness'} <= set(capped_row['unresolved_gates']), capped_row
assert capped_row['prior_token_inbound_recipient_count'] == 1 and capped_row['new_to_token_in_window_recipient_count'] is None, capped_row
capped_history_by_recipient = {row['recipient']: row for row in capped_row['recipient_history_sample']}
assert capped_history_by_recipient[equal_withdrawals[0]['to']]['new_to_token_in_window'] is False, capped_history_by_recipient
assert capped_history_by_recipient[equal_withdrawals[1]['to']]['new_to_token_in_window'] is None, capped_history_by_recipient

def reversed_block_header(url, method, params, timeout):
    block = int(params[0], 16)
    return {'timestamp': hex(2000 - block)}

module.WITHDRAWAL_TIME_RPC_MAX_ATTEMPTS = 4
module.WITHDRAWAL_TIME_RPC_ATTEMPTS_USED = 0
module.opening.rpc_call_url = reversed_block_header
reversed_time = module.cex_withdrawal_cluster(event, equal_withdrawals, 100, 200)
reversed_row = reversed_time['clusters'][0]
assert reversed_row['first_block_time_utc'] is None and reversed_row['last_block_time_utc'] is None, reversed_row
assert reversed_row['window_seconds'] is None, reversed_row
assert reversed_row['time_window_evidence'] == 'rpc_block_header_unavailable', reversed_row
assert 'exact_time_window' in reversed_row['unresolved_gates'], reversed_row
module.WITHDRAWAL_TIME_RPC_ATTEMPTS_USED = 0
module.opening.rpc_call_url = block_header_success

wide_withdrawals = [
    {
        'token': event['token']['address'],
        'from': hot,
        'to': f"0x{index + 100:040x}",
        'amount': module.Decimal('30000'),
        'block': 100 + index,
        'log_index': 30 - index,
        'tx': f"0x{index + 100:064x}",
    }
    for index in range(1, 26)
]
wide_withdrawal = module.cex_withdrawal_cluster(event, list(reversed(wide_withdrawals)), 100, 200)
assert wide_withdrawal['candidate_count'] == 1, wide_withdrawal
wide_row = wide_withdrawal['clusters'][0]
assert wide_row['first_block'] == 101 and wide_row['last_block'] == 125, wide_row
assert len(wide_row['sample_transfers']) == 20, wide_row
wide_anchors = [(row['block'], row['log_index'], row['tx'], row['recipient']) for row in wide_row['sample_transfers']]
assert wide_anchors == sorted(wide_anchors), wide_anchors
withdrawal_analysis = module.analyze_rows(event, [], 100, 200, 8, 8)
withdrawal_analysis['cex_withdrawal_cluster'] = withdrawal
withdrawal_event = {**event, 'analysis': withdrawal_analysis}
assert withdrawal_analysis['direction'] == '观察', withdrawal_analysis
assert module.event_alert_keys(withdrawal_event) == [], withdrawal_event
assert module.action_marker(withdrawal_analysis) == '', withdrawal_analysis
withdrawal_report = module.render({'generated_at': 'fixture', 'event_count': 1, 'alert_count': 0, 'new_alert_count': 0, 'events': [withdrawal_event]})
assert 'CEX Withdrawal Cluster Candidates' in withdrawal_report and 'Report-only evidence' in withdrawal_report, withdrawal_report

history_path = Path(tempfile.mkdtemp(prefix='withdrawal_history_')) / 'withdrawal_candidate_history.json'
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = history_path
history_snapshot = {'generated_at': '2026-07-14T00:00:00+00:00', 'events': [withdrawal_event]}
alert_keys_before = module.event_alert_keys(withdrawal_event)
telegram_before = module.telegram_text({'events': [withdrawal_event], 'new_alert_count': 0})
signature_before = module.push_signature(history_snapshot)
trade_signal_before = withdrawal_event['analysis']['trade_signal']
assert module.record_withdrawal_candidate_history(history_snapshot) == 1
history = json.loads(history_path.read_text(encoding='utf-8'))
assert history['schema_version'] == 1 and history['max_entries'] == 200, history
assert history['candidate_count'] == 1 and len(history['candidates']) == 1, history
assert history['last_scan_at'] == history_snapshot['generated_at'], history
assert len(history['active_candidate_ids']) == 1, history
history_row = history['candidates'][0]
assert history['active_candidate_ids'] == [history_row['candidate_id']], history
assert history_row['observation_count'] == 1, history_row
assert history_row['first_observed_at'] == history_snapshot['generated_at'], history_row
assert history_row['last_observed_at'] == history_snapshot['generated_at'], history_row
assert history_row['first_observation'] == history_row['latest_observation'], history_row
latest_observation = history_row['latest_observation']
assert latest_observation['cluster']['direction'] == 'unknown', latest_observation
assert latest_observation['cluster']['action'] == 'Observe', latest_observation
assert latest_observation['cluster']['alert_policy'] == 'report_only', latest_observation
assert latest_observation['cluster']['unresolved_gates'] == withdrawal_row['unresolved_gates'], latest_observation
assert latest_observation['cluster']['sample_transfers'] == withdrawal_row['sample_transfers'], latest_observation
assert latest_observation['cluster']['window_seconds'] == 21, latest_observation
assert latest_observation['cluster']['time_window_evidence'] == 'rpc_block_header', latest_observation
assert latest_observation['cluster']['fresh_recipient_count'] is None and latest_observation['cluster']['recipient_freshness_state'] == 'bounded_same_token_window', latest_observation
assert latest_observation['cluster']['prior_token_inbound_recipient_count'] == 1 and latest_observation['cluster']['new_to_token_in_window_recipient_count'] == 7, latest_observation
assert latest_observation['scan_coverage']['criteria'] == withdrawal['criteria'], latest_observation
assert latest_observation['scan_coverage']['coverage_state'] == 'requested_window_complete' and latest_observation['scan_coverage']['log_window_coverage'] == complete_coverage, latest_observation
assert module.event_alert_keys(withdrawal_event) == alert_keys_before == [], withdrawal_event
assert module.telegram_text({'events': [withdrawal_event], 'new_alert_count': 0}) == telegram_before
assert module.push_signature(history_snapshot) == signature_before
assert withdrawal_event['analysis']['trade_signal'] == trade_signal_before

forward_dex = '0x' + '7' * 40
forward_plain = '0x' + '6' * 40
forward_dead = '0x000000000000000000000000000000000000dead'
forward_zero_amount = '0x' + '2' * 40
forward_tx = '0x' + 'd' * 64
def forward_transfer(recipient, destination, block, log_index, tx_hash):
    return {
        'token': event['token']['address'],
        'from': recipient,
        'to': destination,
        'amount': module.Decimal('1000'),
        'block': block,
        'log_index': log_index,
        'tx': tx_hash,
    }

forward_rows = [
    forward_transfer(equal_withdrawals[0]['to'], forward_plain, 101, 10, '0x' + '5' * 64),
    forward_transfer(equal_withdrawals[0]['to'], forward_plain, 120, 1, '0x' + '6' * 64),
    forward_transfer(equal_withdrawals[1]['to'], deposit, 121, 1, '0x' + '7' * 64),
    forward_transfer(equal_withdrawals[2]['to'], forward_dex, 122, 1, forward_tx),
    forward_transfer(equal_withdrawals[3]['to'], equal_withdrawals[3]['to'], 123, 1, '0x' + '1' * 64),
    forward_transfer(equal_withdrawals[3]['to'], module.opening.ZERO, 123, 2, '0x' + '2' * 64),
    forward_transfer(equal_withdrawals[3]['to'], forward_dead, 123, 3, '0x' + '3' * 64),
    forward_transfer(equal_withdrawals[3]['to'], 'not-an-address', 123, 4, '0x' + '4' * 64),
    {**forward_transfer(equal_withdrawals[3]['to'], forward_zero_amount, 123, 5, '0x' + '5' * 64), 'amount': module.Decimal('0')},
]
forward_scan = {
    'event': {
        **event,
        'known_contracts': [
            {'address': deposit, 'class': 'cex_deposit'},
            {'address': forward_dex, 'class': 'dex_router'},
        ],
    },
    'transfer_rows': forward_rows,
    'receipt_rows': [{'tx': forward_tx, 'seller': equal_withdrawals[2]['to'], 'got_quote': '2500'}],
    'from_block': 100,
    'to_block': 200,
    'transfer_coverage': complete_coverage,
    'scan_limited': False,
}
no_current_withdrawal = {**withdrawal, 'status': 'none', 'action': '', 'candidate_count': 0, 'clusters': []}
forward_analysis = {**withdrawal_analysis, 'cex_withdrawal_cluster': no_current_withdrawal}
forward_event = {**withdrawal_event, 'analysis': forward_analysis}
forward_snapshot = {'generated_at': '2026-07-14T00:02:00+00:00', 'events': [forward_event]}
contract_round = {'value': 1}
contract_calls = []
def fixture_contract_code(url, method, params, timeout):
    assert method == 'eth_getCode' and timeout == 1, (method, timeout)
    recipient, block = params
    expected_block = next(row['block'] for row in equal_withdrawals if row['to'] == recipient)
    assert block == hex(expected_block), (recipient, block, expected_block)
    contract_calls.append((contract_round['value'], recipient, url))
    if contract_round['value'] == 2:
        if recipient == equal_withdrawals[2]['to']:
            return '0x6000'
        if recipient == equal_withdrawals[3]['to']:
            return '0x'
    if contract_round['value'] == 3 and recipient in {
        equal_withdrawals[0]['to'], equal_withdrawals[5]['to'], equal_withdrawals[6]['to'], equal_withdrawals[7]['to'],
    }:
        return '0x'
    if contract_round['value'] == 4:
        return '0x'
    if contract_round['value'] == 6:
        return '0x'
    raise TimeoutError('fixture eth_getCode timeout')

module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
module.opening.rpc_call_url = fixture_contract_code
assert module.record_withdrawal_candidate_history(forward_snapshot, [forward_scan]) == 0
forward_history = json.loads(history_path.read_text(encoding='utf-8'))
forward_history_row = forward_history['candidates'][0]
tracking = forward_history_row['forward_tracking']
contract_review = forward_history_row['recipient_contract_review']
latest_forward = tracking['latest_scan']
assert forward_history['active_candidate_ids'] == [], forward_history
assert forward_history_row['last_observed_at'] == history_snapshot['generated_at'], forward_history_row
assert tracking['scan_count'] == 1 and latest_forward['tracked_sample_recipient_count'] == 8, tracking
assert latest_forward['next_hop_transfer_count'] == 3 and latest_forward['next_hop_recipient_count'] == 3, latest_forward
assert latest_forward['cex_redeposit_transfer_count'] == 1 and latest_forward['dex_route_transfer_count'] == 1, latest_forward
assert latest_forward['dex_execution_tx_count'] == 1 and latest_forward['quote_recovered'] == '2500', latest_forward
positive_names = {'next_hop', 'cex_redeposit', 'dex_route', 'dex_execution', 'quote_recovery'}
assert set(tracking['latest_positive_evidence']) == positive_names and 'positive_evidence' not in tracking, tracking
assert contract_review['sample_recipient_count'] == 8 and contract_review['rpc_unresolved_count'] == 8, contract_review
assert [row['attempt_count'] for row in contract_review['recipients']] == [2, 2, 0, 0, 0, 0, 0, 0], contract_review
assert len(contract_calls) == module.WITHDRAWAL_CONTRACT_RPC_MAX_ATTEMPTS == 4, contract_calls
assert not {
    equal_withdrawals[3]['to'], module.opening.ZERO, forward_dead, 'not-an-address', forward_zero_amount,
} & {row['destination'] for row in latest_forward['sample_transfers']}, latest_forward
assert forward_history_row['latest_observation'] == latest_observation, forward_history_row
assert forward_history_row['latest_observation']['cluster']['unresolved_gates'] == withdrawal_row['unresolved_gates'], forward_history_row
assert module.event_alert_keys(forward_event) == alert_keys_before == [], forward_event
assert module.telegram_text({'events': [forward_event], 'new_alert_count': 0}) == telegram_before
assert module.push_signature(forward_snapshot) == signature_before
assert forward_event['analysis']['trade_signal'] == trade_signal_before

legacy_tracking = forward_history['candidates'][0]['forward_tracking']
legacy_tracking['positive_evidence'] = legacy_tracking.pop('latest_positive_evidence')
history_path.write_text(json.dumps(forward_history), encoding='utf-8')
positive_again_scan = {
    **forward_scan,
    'transfer_rows': [forward_transfer(equal_withdrawals[3]['to'], '0x' + '4' * 40, 124, 1, '0x' + 'e' * 64)],
    'receipt_rows': [],
}
positive_again_at = '2026-07-14T00:02:30+00:00'
contract_round['value'] = 2
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
assert module.record_withdrawal_candidate_history(
    {'generated_at': positive_again_at, 'events': [forward_event]},
    [positive_again_scan],
) == 0
positive_again_history = json.loads(history_path.read_text(encoding='utf-8'))
positive_again_tracking = positive_again_history['candidates'][0]['forward_tracking']
positive_again_contract = positive_again_history['candidates'][0]['recipient_contract_review']
assert positive_again_tracking['scan_count'] == 2 and 'positive_evidence' not in positive_again_tracking, positive_again_tracking
assert set(positive_again_tracking['latest_positive_evidence']) == positive_names, positive_again_tracking
assert positive_again_tracking['latest_positive_evidence']['next_hop']['observed_at'] == positive_again_at, positive_again_tracking
assert positive_again_tracking['latest_positive_evidence']['cex_redeposit']['observed_at'] == forward_snapshot['generated_at'], positive_again_tracking
assert positive_again_contract['contract_at_anchor_block_count'] == 1, positive_again_contract
assert positive_again_contract['eoa_at_anchor_block_count'] == 1, positive_again_contract
round_two_addresses = [address for round_value, address, _url in contract_calls if round_value == 2]
assert round_two_addresses[:2] == [equal_withdrawals[2]['to'], equal_withdrawals[3]['to']], round_two_addresses
assert equal_withdrawals[0]['to'] not in round_two_addresses and equal_withdrawals[1]['to'] not in round_two_addresses, round_two_addresses

negative_scan = {**forward_scan, 'transfer_rows': forward_rows[:1], 'receipt_rows': [], 'scan_limited': True}
negative_snapshot = {'generated_at': '2026-07-14T00:03:00+00:00', 'events': [forward_event]}
contract_round['value'] = 3
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
assert module.record_withdrawal_candidate_history(negative_snapshot, [negative_scan]) == 0
negative_history = json.loads(history_path.read_text(encoding='utf-8'))
negative_tracking = negative_history['candidates'][0]['forward_tracking']
negative_contract = negative_history['candidates'][0]['recipient_contract_review']
assert negative_tracking['scan_count'] == 3, negative_tracking
assert negative_tracking['latest_scan']['next_hop_state'] == 'not_observed_in_fetched_window', negative_tracking
assert negative_tracking['latest_scan']['scan_limited'] is True, negative_tracking
assert set(negative_tracking['latest_positive_evidence']) == positive_names, negative_tracking
assert negative_contract['eoa_at_anchor_block_count'] == 5 and negative_contract['contract_at_anchor_block_count'] == 1, negative_contract
round_three_addresses = [address for round_value, address, _url in contract_calls if round_value == 3]
assert equal_withdrawals[2]['to'] not in round_three_addresses and equal_withdrawals[3]['to'] not in round_three_addresses, round_three_addresses

contract_round['value'] = 4
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
all_eoa_review = module.review_withdrawal_recipient_contracts(
    event,
    {**withdrawal_row, 'sample_transfers': withdrawal_row['sample_transfers'][:4]},
    {},
    '2026-07-14T00:04:00+00:00',
)
module.opening.rpc_call_url = block_header_success
assert all_eoa_review['review_state'] == 'all_sample_eoa_at_anchor_block' and all_eoa_review['eoa_at_anchor_block_count'] == 4, all_eoa_review
assert 'unknown_contract_filter' in withdrawal_row['unresolved_gates'], withdrawal_row

multi_candidate_reviews = []
for candidate_id, sample_rows in (
    ('candidate-a', equal_withdrawals[:2]),
    ('candidate-b', equal_withdrawals[2:4]),
):
    multi_candidate_reviews.append((
        candidate_id,
        event,
        {
            'recipients': [
                {
                    'recipient': row['to'],
                    'anchor_block': row['block'],
                    'state': 'rpc_unresolved',
                    'attempt_count': 0,
                }
                for row in sample_rows
            ],
        },
    ))
contract_round['value'] = 5
module.opening.rpc_call_url = fixture_contract_code
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
module.resolve_withdrawal_contract_reviews(multi_candidate_reviews, '2026-07-14T00:04:30+00:00')
assert [sum(row['attempt_count'] for row in review['recipients']) for _candidate, _event, review in multi_candidate_reviews] == [2, 2], multi_candidate_reviews
assert len([call for call in contract_calls if call[0] == 5]) == module.WITHDRAWAL_CONTRACT_RPC_MAX_ATTEMPTS, contract_calls
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
module.resolve_withdrawal_contract_reviews(multi_candidate_reviews, '2026-07-14T00:04:45+00:00')
assert [sorted(row['attempt_count'] for row in review['recipients']) for _candidate, _event, review in multi_candidate_reviews] == [[2, 2], [2, 2]], multi_candidate_reviews

successful_candidate_reviews = []
for candidate_id, sample_rows in (
    ('candidate-a', equal_withdrawals[:3]),
    ('candidate-b', equal_withdrawals[3:6]),
):
    successful_candidate_reviews.append((
        candidate_id,
        event,
        {
            'recipients': [
                {
                    'recipient': row['to'],
                    'anchor_block': row['block'],
                    'state': 'rpc_unresolved',
                    'attempt_count': 0,
                }
                for row in sample_rows
            ],
        },
    ))
contract_round['value'] = 6
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
module.resolve_withdrawal_contract_reviews(successful_candidate_reviews, '2026-07-14T00:04:50+00:00')
assert [review['eoa_at_anchor_block_count'] for _candidate, _event, review in successful_candidate_reviews] == [2, 2], successful_candidate_reviews
assert [review['rpc_unresolved_count'] for _candidate, _event, review in successful_candidate_reviews] == [1, 1], successful_candidate_reviews

single_unresolved_review = {
    'recipients': [{
        'recipient': equal_withdrawals[0]['to'],
        'anchor_block': equal_withdrawals[0]['block'],
        'state': 'rpc_unresolved',
        'attempt_count': 0,
    }],
}
contract_round['value'] = 7
single_call_start = len(contract_calls)
module.WITHDRAWAL_CONTRACT_RPC_ATTEMPTS_USED = 0
module.resolve_withdrawal_contract_reviews(
    [('single-candidate', event, single_unresolved_review)],
    '2026-07-14T00:04:55+00:00',
)
assert len(contract_calls) - single_call_start == 2, contract_calls[single_call_start:]
assert single_unresolved_review['recipients'][0]['attempt_count'] == 2, single_unresolved_review
module.opening.rpc_call_url = block_header_success

reordered_cluster = {**withdrawal_row, 'sample_transfers': list(reversed(withdrawal_row['sample_transfers']))}
reordered_withdrawal = {**withdrawal, 'clusters': [reordered_cluster]}
reordered_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': reordered_withdrawal}}
base_candidate_id = module.withdrawal_candidate_id(withdrawal_event, withdrawal_row)
assert base_candidate_id == module.withdrawal_candidate_id(reordered_event, reordered_cluster)
different_anchor_cluster = {
    **withdrawal_row,
    'sample_transfers': [
        {**withdrawal_row['sample_transfers'][0], 'tx': '0x' + 'e' * 64},
        *withdrawal_row['sample_transfers'][1:],
    ],
}
assert base_candidate_id != module.withdrawal_candidate_id(withdrawal_event, different_anchor_cluster)
fallback_a = {**withdrawal_row, 'sample_transfers': [], 'first_block': None, 'window_blocks': '100->200'}
fallback_b = {**fallback_a, 'window_blocks': '201->300'}
assert module.withdrawal_candidate_id(withdrawal_event, fallback_a) != module.withdrawal_candidate_id(withdrawal_event, fallback_b)
repeat_snapshot = {'generated_at': '2026-07-14T00:05:00+00:00', 'events': [withdrawal_event, reordered_event]}
assert module.record_withdrawal_candidate_history(repeat_snapshot) == 1
repeated_history = json.loads(history_path.read_text(encoding='utf-8'))
repeated_row = next(row for row in repeated_history['candidates'] if row['candidate_id'] == base_candidate_id)
assert repeated_row['observation_count'] == 2, repeated_row
assert repeated_row['first_observed_at'] == history_snapshot['generated_at'], repeated_row
assert repeated_row['last_observed_at'] == repeat_snapshot['generated_at'], repeated_row
assert repeated_row['first_observation'] == history_row['first_observation'], repeated_row
assert repeated_row['forward_tracking'] == negative_tracking, repeated_row
assert repeated_row['recipient_contract_review'] == negative_contract, repeated_row

later_cluster = {
    **withdrawal_row,
    'last_block': withdrawal_row['last_block'] + 1,
    'window_blocks': f"{withdrawal_row['first_block']}->{withdrawal_row['last_block'] + 1}",
    'sample_transfers': withdrawal_row['sample_transfers'] + [{
        **withdrawal_row['sample_transfers'][-1],
        'block': withdrawal_row['last_block'] + 1,
        'log_index': 99,
        'tx': '0x' + 'f' * 64,
    }],
}
assert base_candidate_id == module.withdrawal_candidate_id(withdrawal_event, later_cluster)

slid_cluster = {
    **withdrawal_row,
    'first_block': withdrawal_row['sample_transfers'][2]['block'],
    'sample_transfers': withdrawal_row['sample_transfers'][2:],
}
slid_id = module.withdrawal_candidate_id(withdrawal_event, slid_cluster)
assert slid_id != base_candidate_id
slid_withdrawal = {**withdrawal, 'clusters': [slid_cluster]}
slid_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': slid_withdrawal}}
slid_at = '2026-07-14T00:10:00+00:00'
assert module.record_withdrawal_candidate_history({'generated_at': slid_at, 'events': [slid_event]}) == 1
slid_history = json.loads(history_path.read_text(encoding='utf-8'))
assert slid_history['active_candidate_ids'] == [base_candidate_id], slid_history
slid_row = next(row for row in slid_history['candidates'] if row['candidate_id'] == base_candidate_id)
assert slid_row['observation_count'] == 3 and slid_row['last_observed_at'] == slid_at, slid_row

disjoint_cluster = {
    **withdrawal_row,
    'first_block': 500,
    'last_block': 507,
    'window_blocks': '500->507',
    'sample_transfers': [
        {**row, 'block': 500 + index, 'log_index': index, 'tx': f"0x{index + 900:064x}"}
        for index, row in enumerate(withdrawal_row['sample_transfers'])
    ],
}
disjoint_id = module.withdrawal_candidate_id(withdrawal_event, disjoint_cluster)
disjoint_withdrawal = {**withdrawal, 'clusters': [disjoint_cluster]}
disjoint_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': disjoint_withdrawal}}
assert module.record_withdrawal_candidate_history({'generated_at': '2026-07-14T00:15:00+00:00', 'events': [disjoint_event]}) == 1
disjoint_history = json.loads(history_path.read_text(encoding='utf-8'))
assert disjoint_history['active_candidate_ids'] == [disjoint_id], disjoint_history
assert disjoint_history['candidate_count'] == 2, disjoint_history

returned_anchor_cluster = {
    **withdrawal_row,
    'sample_transfers': [withdrawal_row['sample_transfers'][0]],
}
assert module.withdrawal_candidate_id(withdrawal_event, returned_anchor_cluster) == base_candidate_id
returned_withdrawal = {**withdrawal, 'clusters': [returned_anchor_cluster]}
returned_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': returned_withdrawal}}
assert module.record_withdrawal_candidate_history({'generated_at': '2026-07-14T00:20:00+00:00', 'events': [returned_event]}) == 1
collision_history = json.loads(history_path.read_text(encoding='utf-8'))
collision_id = collision_history['active_candidate_ids'][0]
assert collision_id != base_candidate_id, collision_history
assert module.record_withdrawal_candidate_history({'generated_at': '2026-07-14T00:25:00+00:00', 'events': [returned_event]}) == 1
collision_repeat = json.loads(history_path.read_text(encoding='utf-8'))
collision_row = next(row for row in collision_repeat['candidates'] if row['candidate_id'] == collision_id)
assert collision_repeat['active_candidate_ids'] == [collision_id], collision_repeat
assert collision_row['observation_count'] == 2, collision_row

inactive_at = '2026-07-14T00:30:00+00:00'
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = history_path
assert module.record_withdrawal_candidate_history({'generated_at': inactive_at, 'events': []}) == 0
inactive_history = json.loads(history_path.read_text(encoding='utf-8'))
assert inactive_history['last_scan_at'] == inactive_at, inactive_history
assert inactive_history['active_candidate_ids'] == [], inactive_history
assert inactive_history['candidate_count'] == 3, inactive_history

claimed_path = Path(tempfile.mkdtemp(prefix='withdrawal_history_claimed_')) / 'withdrawal_candidate_history.json'
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = claimed_path
assert module.record_withdrawal_candidate_history(history_snapshot) == 1
claim_clusters = [
    {**withdrawal_row, 'sample_transfers': [withdrawal_row['sample_transfers'][index]]}
    for index in (1, 2)
]
claim_withdrawal = {**withdrawal, 'candidate_count': 2, 'clusters': claim_clusters}
claim_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': claim_withdrawal}}
assert module.record_withdrawal_candidate_history({'generated_at': '2026-07-14T00:05:00+00:00', 'events': [claim_event]}) == 2
claimed_history = json.loads(claimed_path.read_text(encoding='utf-8'))
assert claimed_history['candidate_count'] == 2, claimed_history
assert len(claimed_history['active_candidate_ids']) == 2, claimed_history
assert len(set(claimed_history['active_candidate_ids'])) == 2, claimed_history
assert base_candidate_id in claimed_history['active_candidate_ids'], claimed_history

bounded_path = Path(tempfile.mkdtemp(prefix='withdrawal_history_bounded_')) / 'withdrawal_candidate_history.json'
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = bounded_path
module.WITHDRAWAL_CANDIDATE_HISTORY_MAX = 2
bounded_clusters = [
    {
        **withdrawal_row,
        'source_address': f"0x{index + 500:040x}",
        'first_block': withdrawal_row['first_block'] + index,
        'last_block': withdrawal_row['last_block'] + index,
    }
    for index in range(3)
]
bounded_withdrawal = {**withdrawal, 'candidate_count': 3, 'clusters': bounded_clusters}
bounded_event = {**withdrawal_event, 'analysis': {**withdrawal_analysis, 'cex_withdrawal_cluster': bounded_withdrawal}}
assert module.record_withdrawal_candidate_history({'generated_at': '2026-07-14T00:15:00+00:00', 'events': [bounded_event]}) == 3
bounded_history = json.loads(bounded_path.read_text(encoding='utf-8'))
bounded_candidate_ids = {row['candidate_id'] for row in bounded_history['candidates']}
assert bounded_history['candidate_count'] == 2 and len(bounded_history['active_candidate_ids']) == 2, bounded_history
assert set(bounded_history['active_candidate_ids']) <= bounded_candidate_ids, bounded_history
module.WITHDRAWAL_CANDIDATE_HISTORY_MAX = 200

corrupt_path = Path(tempfile.mkdtemp(prefix='withdrawal_history_corrupt_')) / 'withdrawal_candidate_history.json'
corrupt_path.write_text('{bad json', encoding='utf-8')
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = corrupt_path
assert module.record_withdrawal_candidate_history(history_snapshot) == 1
recovered_history = json.loads(corrupt_path.read_text(encoding='utf-8'))
assert recovered_history['candidate_count'] == 1, recovered_history

empty_history_path = Path(tempfile.mkdtemp(prefix='withdrawal_history_empty_')) / 'withdrawal_candidate_history.json'
module.WITHDRAWAL_CANDIDATE_HISTORY_PATH = empty_history_path
assert module.record_withdrawal_candidate_history({'generated_at': 'fixture', 'events': []}) == 0
assert not empty_history_path.exists(), empty_history_path

low_quote = module.cex_withdrawal_cluster(
    event,
    [{**row, 'amount': module.Decimal('20000')} for row in equal_withdrawals],
    100,
    200,
)
assert low_quote['candidate_count'] == 0, low_quote
long_window = module.cex_withdrawal_cluster(
    event,
    [{**row, 'block': 100 + index * 200} for index, row in enumerate(equal_withdrawals)],
    100,
    1800,
)
assert long_window['candidate_count'] == 0, long_window

retail_withdrawals = [
    {**row, 'to': f"0x{index + 20:040x}", 'amount': module.Decimal(str(amount))}
    for index, (row, amount) in enumerate(zip(equal_withdrawals, [1000, 3000, 8000, 20000, 50000, 100000, 250000, 600000]))
]
retail = module.cex_withdrawal_cluster(event, retail_withdrawals, 100, 200)
assert retail['candidate_count'] == 0, retail

infrastructure = [
    {'address': f"0x{index + 40:040x}", 'class': 'dex_router' if index % 2 else 'cex_hot_wallet'}
    for index in range(8)
]
infrastructure_event = {**event, 'known_contracts': infrastructure}
internal_transfers = [
    {**row, 'to': infrastructure[index]['address']}
    for index, row in enumerate(equal_withdrawals)
]
internal = module.cex_withdrawal_cluster(infrastructure_event, internal_transfers, 100, 200)
assert internal['candidate_count'] == 0, internal
assert internal['rejected_known_infrastructure_transfer_count'] == 8, internal

deposit_source_transfers = [{**row, 'from': deposit} for row in equal_withdrawals]
deposit_source = module.cex_withdrawal_cluster(event, deposit_source_transfers, 100, 200)
assert deposit_source['tracked_hot_source_count'] == 0 and deposit_source['candidate_count'] == 0, deposit_source

withdrawal_with_cex_pressure = module.analyze_rows(
    event,
    [{'cex_token_deposit': '300000', 'cex_quote_estimate': '15000', 'cex_deposit_count': 1}],
    100,
    200,
    8,
    8,
)
withdrawal_with_cex_pressure['cex_withdrawal_cluster'] = withdrawal
assert withdrawal_with_cex_pressure['direction'] == '偏空', withdrawal_with_cex_pressure
assert withdrawal_with_cex_pressure['cex_withdrawal_cluster']['candidate_count'] == 1, withdrawal_with_cex_pressure
transfers = [
    {'token': event['token']['address'], 'from': '0x' + '1' * 40, 'to': '0x' + 'c' * 40, 'amount': module.Decimal('300000')},
    {'token': event['token']['address'], 'from': '0x' + '2' * 40, 'to': '0x' + '3' * 40, 'amount': module.Decimal('1')},
]
cex_rows = module.cex_deposit_transfers(event, transfers)
assert len(cex_rows) == 1, cex_rows
candidate = '0x' + 'e' * 40
alpha_custody = '0x' + 'f' * 40
alpha_custody_suspect = '0x' + '5' * 40
external = '0x' + '6' * 40
project_operator = '0x' + '4' * 40
assert len({project_operator, hot, deposit, candidate, alpha_custody, alpha_custody_suspect, external}) == 7
path_event = {
    **event,
    'operator': project_operator,
    'known_contracts': [
        {'address': deposit, 'class': 'cex_deposit', 'exchange': 'FixtureEx'},
        {'address': hot, 'class': 'cex_hot_wallet', 'exchange': 'FixtureEx'},
        {'address': alpha_custody, 'class': 'exchange_aggregator', 'exchange': 'Binance'},
        {'address': alpha_custody_suspect, 'class': 'exchange_aggregator_suspect', 'exchange': 'Binance'},
    ],
}
path_rows = module.classify_cex_transfer_paths(
    path_event,
    [
        {'token': event['token']['address'], 'from': external, 'to': deposit, 'amount': module.Decimal('2000')},
        {'token': event['token']['address'], 'from': deposit, 'to': hot, 'amount': module.Decimal('2000')},
        {'token': event['token']['address'], 'from': external, 'to': candidate, 'amount': module.Decimal('3000')},
        {'token': event['token']['address'], 'from': candidate, 'to': hot, 'amount': module.Decimal('3000')},
        {'token': event['token']['address'], 'from': alpha_custody, 'to': hot, 'amount': module.Decimal('4000')},
        {'token': event['token']['address'], 'from': hot, 'to': alpha_custody, 'amount': module.Decimal('5000')},
        {'token': event['token']['address'], 'from': alpha_custody_suspect, 'to': hot, 'amount': module.Decimal('6000')},
    ],
    {candidate: {'address': candidate, 'class': 'cex_deposit_candidate'}},
)
risk_paths = [row for row in path_rows if row['runtime_effect'] == 'cex_inflow_risk']
internal_paths = [row for row in path_rows if row['runtime_effect'] == 'none']
aggregate_components = [row for row in path_rows if row['runtime_effect'] == 'aggregate_only']
assert sum((row['amount'] for row in risk_paths), module.Decimal(0)) == module.Decimal('2000'), path_rows
assert len(risk_paths) == 1 and {row['path_role'] for row in risk_paths} == {'unlabeled_to_cex_inflow_candidate'}, path_rows
assert len(aggregate_components) == 1 and aggregate_components[0]['amount'] == module.Decimal('3000'), path_rows
assert aggregate_components[0]['path_role'] == 'external_to_cex_inflow_component', path_rows
assert len(internal_paths) == 5, path_rows
assert {row['path_role'] for row in internal_paths} == {'cex_internal_aggregation', 'alpha_custody_movement_unresolved'}, path_rows
assert all(row['direction'] == 'unknown' and row['alert_policy'] == 'report_only' for row in internal_paths), path_rows
supply_risk_rows = module.classify_cex_transfer_paths(
    path_event,
    [
        {'token': event['token']['address'], 'from': module.opening.ZERO, 'to': hot, 'amount': module.Decimal('7000')},
        {'token': event['token']['address'], 'from': event['token']['address'], 'to': hot, 'amount': module.Decimal('8000')},
        {'token': event['token']['address'], 'from': project_operator, 'to': hot, 'amount': module.Decimal('9000')},
    ],
)
assert len(supply_risk_rows) == 3, supply_risk_rows
assert all(row['path_role'] == 'external_to_cex_inflow' for row in supply_risk_rows), supply_risk_rows
assert {row['source_role'] for row in supply_risk_rows} == {'mint_or_zero', 'token_contract', 'project_or_pool'}, supply_risk_rows
gate_evidence_rows = module.classify_cex_transfer_paths(
    path_event,
    [
        {
            'token': event['token']['address'],
            'from': '0xd5da17a84314194e348649c89a65143a061f7190',
            'to': hot,
            'amount': module.Decimal('1845034161.853208889131008'),
        },
        {
            'token': event['token']['address'],
            'from': '0x8782163068c7cd74d2510768a61135c1e4eb07b3',
            'to': hot,
            'amount': module.Decimal('1914689272'),
        },
    ],
)
assert len(gate_evidence_rows) == 2, gate_evidence_rows
assert all(row['path_role'] == 'unlabeled_to_cex_inflow_candidate' for row in gate_evidence_rows), gate_evidence_rows
assert all(row['runtime_effect'] == 'cex_inflow_risk' for row in gate_evidence_rows), gate_evidence_rows
assert all(row['source_role'] == 'unlabeled' for row in gate_evidence_rows), gate_evidence_rows
assert all(row['direction'] == 'bearish_risk_candidate' for row in gate_evidence_rows), gate_evidence_rows
real_internal_quick_rpc = module.opening.quick_rpc_call
real_internal_receipt_transfers = module.opening.receipt_transfers_from_receipt
real_internal_gas_priming = module.cex_gas_priming_transfers
gas_target_calls = []
module.opening.quick_rpc_call = lambda chain, method, params, timeout: {'blockNumber': '0x64', 'transactionIndex': '0x1'}
module.cex_gas_priming_transfers = lambda event, targets, block: gas_target_calls.append(set(targets)) or []
module.opening.receipt_transfers_from_receipt = lambda receipt, token, quote: [
    {'token': event['token']['address'], 'from': deposit, 'to': hot, 'amount': module.Decimal('300000')}
]
internal_receipt_row = module.summarize_flow_tx(path_event, '0x' + '4' * 64)
module.opening.receipt_transfers_from_receipt = lambda receipt, token, quote: [
    {'token': event['token']['address'], 'from': external, 'to': candidate, 'amount': module.Decimal('300000')},
    {'token': event['token']['address'], 'from': candidate, 'to': hot, 'amount': module.Decimal('300000')},
]
mixed_receipt_row = module.summarize_flow_tx(
    path_event,
    '0x' + '5' * 64,
    {candidate: {'address': candidate, 'class': 'cex_deposit_candidate'}},
)
module.opening.quick_rpc_call = real_internal_quick_rpc
module.opening.receipt_transfers_from_receipt = real_internal_receipt_transfers
module.cex_gas_priming_transfers = real_internal_gas_priming
assert internal_receipt_row is not None, internal_receipt_row
assert internal_receipt_row['cex_deposit_count'] == 0, internal_receipt_row
assert internal_receipt_row['cex_internal_aggregation_count'] == 1, internal_receipt_row
assert internal_receipt_row['cex_internal_path_roles'] == 'cex_internal_aggregation', internal_receipt_row
assert internal_receipt_row['cex_path_sample'][0]['from'] == deposit, internal_receipt_row
assert internal_receipt_row['cex_path_sample'][0]['to'] == hot, internal_receipt_row
assert internal_receipt_row['cex_path_sample'][0]['runtime_effect'] == 'none', internal_receipt_row
assert mixed_receipt_row is not None, mixed_receipt_row
assert mixed_receipt_row['cex_token_deposit'] == '0', mixed_receipt_row
assert mixed_receipt_row['cex_internal_aggregation_token'] == '300000', mixed_receipt_row
assert {row['path_role'] for row in mixed_receipt_row['cex_path_sample']} == {
    'external_to_cex_inflow_component',
    'cex_internal_aggregation',
}, mixed_receipt_row
assert gas_target_calls[0] == {deposit}, gas_target_calls
assert gas_target_calls[1] == {external, candidate}, gas_target_calls
deduped_risk_rows = module.cex_deposit_transfers(
    path_event,
    [
        {'token': event['token']['address'], 'from': external, 'to': candidate, 'amount': module.Decimal('3000')},
        {'token': event['token']['address'], 'from': candidate, 'to': hot, 'amount': module.Decimal('3000')},
    ],
    {candidate: {'address': candidate, 'class': 'cex_deposit_candidate'}},
)
assert deduped_risk_rows == [], deduped_risk_rows
complete_cex_coverage = {
    'state': 'requested_window_complete',
    'complete': True,
    'requested_from_block': 100,
    'requested_to_block': 110,
    'covered_through_block': 110,
    'returned_log_count': 2,
    'max_logs': 12000,
}
direct_small_transfers = [
    {
        'token': event['token']['address'],
        'from': '0x' + '7' * 40,
        'to': deposit,
        'amount': module.Decimal('60000'),
        'block': 101,
        'log_index': 3,
        'tx': '0x' + '1' * 64,
    },
    {
        'token': event['token']['address'],
        'from': external,
        'to': deposit,
        'amount': module.Decimal('60000'),
        'block': 104,
        'log_index': 1,
        'tx': '0x' + '2' * 64,
    },
]
direct_small_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    direct_small_transfers,
    100,
    110,
    complete_cex_coverage,
)
assert len(direct_small_rows) == 1, direct_small_rows
assert direct_small_rows[0]['observed_external_token'] == '120000', direct_small_rows
assert direct_small_rows[0]['observed_transfer_count'] == 2, direct_small_rows
assert direct_small_rows[0]['observed_tx_count'] == 2, direct_small_rows
assert direct_small_rows[0]['duplicate_log_count'] == 0, direct_small_rows
assert direct_small_rows[0]['first_block'] == 101 and direct_small_rows[0]['last_block'] == 104, direct_small_rows
assert direct_small_rows[0]['coverage_complete'] is True, direct_small_rows
assert direct_small_rows[0]['runtime_effect'] == 'cex_inflow_risk', direct_small_rows
assert direct_small_rows[0]['cex_token_deposit'] == '120000', direct_small_rows
assert direct_small_rows[0]['cex_deposit_count'] == 2, direct_small_rows
direct_small_analysis = module.analyze_rows(path_event, direct_small_rows, 100, 110, 2, 2)
assert direct_small_analysis['cex_token_deposit'] == '120000', direct_small_analysis
assert direct_small_analysis['cex_deposit_count'] == 2, direct_small_analysis
assert module.event_alert_keys({**path_event, 'analysis': direct_small_analysis}), direct_small_analysis
real_direct_aggregate_candidate_txs = module.aggregate_candidate_txs
real_direct_transfer_fetch = module.token_transfer_logs_with_coverage
module.aggregate_candidate_txs = lambda event_arg, from_arg, to_arg: ([], 2, 2)
module.token_transfer_logs_with_coverage = lambda event_arg, from_arg, to_arg: (
    direct_small_transfers,
    complete_cex_coverage,
)
scanned_direct_small = module.scan_event({**path_event, 'opening_block': 100, 'latest_block': 110})
module.aggregate_candidate_txs = real_direct_aggregate_candidate_txs
module.token_transfer_logs_with_coverage = real_direct_transfer_fetch
assert scanned_direct_small['analysis']['cex_token_deposit'] == '120000', scanned_direct_small
assert scanned_direct_small['analysis']['cex_deposit_count'] == 2, scanned_direct_small
assert len(scanned_direct_small['configured_cex_inflow_aggregate_rows']) == 1, scanned_direct_small
direct_small_text = module.telegram_text({'events': [scanned_direct_small], 'new_alert_count': 1})
assert 'CEX预出货' in direct_small_text, direct_small_text
assert direct_small_text.count('CEX预出货') == 1, direct_small_text
assert deposit not in direct_small_text, direct_small_text
assert all(value not in direct_small_text for value in ('Configured CEX', 'observed_external', 'coverage')), direct_small_text
assert len(direct_small_text) <= 320 and len(direct_small_text.splitlines()) <= 5, direct_small_text
direct_small_report = module.render({
    'generated_at': 'fixture',
    'event_count': 1,
    'alert_count': 1,
    'new_alert_count': 1,
    'events': [scanned_direct_small],
})
assert 'Configured CEX Inflow Window Aggregates' in direct_small_report, direct_small_report
assert 'observed_external=120000.0000 TEST' in direct_small_report, direct_small_report

duplicate_direct_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [direct_small_transfers[0], dict(direct_small_transfers[0]), direct_small_transfers[1]],
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 3},
)
assert duplicate_direct_rows[0]['observed_external_token'] == '120000', duplicate_direct_rows
assert duplicate_direct_rows[0]['observed_transfer_count'] == 2, duplicate_direct_rows
assert duplicate_direct_rows[0]['observed_tx_count'] == 2, duplicate_direct_rows
assert duplicate_direct_rows[0]['duplicate_log_count'] == 1, duplicate_direct_rows
assert duplicate_direct_rows[0]['cex_token_deposit'] == '120000', duplicate_direct_rows
conflicting_direct_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [direct_small_transfers[0], {**direct_small_transfers[0], 'amount': module.Decimal('70000')}],
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 2},
)
assert conflicting_direct_rows[0]['conflicting_duplicate_log_count'] == 1, conflicting_direct_rows
assert conflicting_direct_rows[0]['coverage_complete'] is False, conflicting_direct_rows
assert conflicting_direct_rows[0]['cex_token_deposit'] == '0', conflicting_direct_rows

same_tx = '0x' + '8' * 64
same_tx_distinct_logs = [
    {**direct_small_transfers[0], 'tx': same_tx, 'amount': module.Decimal('60000'), 'log_index': 7},
    {**direct_small_transfers[1], 'tx': same_tx, 'amount': module.Decimal('20000'), 'log_index': 8},
]
same_tx_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [same_tx_distinct_logs[0], dict(same_tx_distinct_logs[0]), same_tx_distinct_logs[1]],
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 3},
)
assert same_tx_rows[0]['observed_external_token'] == '80000', same_tx_rows
assert same_tx_rows[0]['observed_transfer_count'] == 2, same_tx_rows
assert same_tx_rows[0]['observed_tx_count'] == 1, same_tx_rows
assert same_tx_rows[0]['duplicate_log_count'] == 1, same_tx_rows
same_tx_analysis = module.analyze_rows(path_event, same_tx_rows, 100, 110, 3, 1)
assert module.event_alert_keys({**path_event, 'analysis': same_tx_analysis}) == [], same_tx_analysis

incomplete_direct_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    direct_small_transfers,
    100,
    110,
    {
        'state': 'partial_rpc_error',
        'complete': False,
        'requested_from_block': 100,
        'requested_to_block': 110,
        'covered_through_block': 105,
        'returned_log_count': 2,
        'max_logs': 12000,
    },
)
assert incomplete_direct_rows[0]['observed_external_token'] == '120000', incomplete_direct_rows
assert incomplete_direct_rows[0]['cex_token_deposit'] == '0', incomplete_direct_rows
assert incomplete_direct_rows[0]['cex_deposit_count'] == 0, incomplete_direct_rows
assert incomplete_direct_rows[0]['runtime_effect'] == 'none_incomplete_coverage', incomplete_direct_rows
incomplete_direct_analysis = module.analyze_rows(path_event, incomplete_direct_rows, 100, 110, 2, 2)
assert module.event_alert_keys({**path_event, 'analysis': incomplete_direct_analysis}) == [], incomplete_direct_analysis
missing_coverage_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    direct_small_transfers,
    100,
    110,
)
assert missing_coverage_rows[0]['coverage_state'] == 'missing_transfer_coverage', missing_coverage_rows
assert missing_coverage_rows[0]['cex_token_deposit'] == '0', missing_coverage_rows
wrong_window_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    direct_small_transfers,
    100,
    110,
    {**complete_cex_coverage, 'requested_from_block': 99},
)
assert wrong_window_rows[0]['coverage_complete'] is False, wrong_window_rows
assert wrong_window_rows[0]['cex_token_deposit'] == '0', wrong_window_rows
real_incomplete_aggregate_candidate_txs = module.aggregate_candidate_txs
real_incomplete_transfer_fetch = module.token_transfer_logs_with_coverage
module.aggregate_candidate_txs = lambda event_arg, from_arg, to_arg: ([], 2, 2)
module.token_transfer_logs_with_coverage = lambda event_arg, from_arg, to_arg: (
    direct_small_transfers,
    {
        'state': 'partial_rpc_error',
        'complete': False,
        'requested_from_block': 100,
        'requested_to_block': 110,
        'covered_through_block': 105,
        'returned_log_count': 2,
        'max_logs': 12000,
    },
)
scanned_incomplete_direct = module.scan_event({**path_event, 'opening_block': 100, 'latest_block': 110})
module.aggregate_candidate_txs = real_incomplete_aggregate_candidate_txs
module.token_transfer_logs_with_coverage = real_incomplete_transfer_fetch
assert scanned_incomplete_direct['configured_cex_inflow_aggregate_rows'][0]['observed_external_token'] == '120000', scanned_incomplete_direct
assert scanned_incomplete_direct['analysis']['cex_token_deposit'] == '0', scanned_incomplete_direct
assert scanned_incomplete_direct['analysis']['cex_deposit_count'] == 0, scanned_incomplete_direct
assert module.event_alert_keys(scanned_incomplete_direct) == [], scanned_incomplete_direct

large_tx = '0x' + '3' * 64
large_transfer = {
    'token': event['token']['address'],
    'from': external,
    'to': deposit,
    'amount': module.Decimal('150000'),
    'block': 105,
    'log_index': 2,
    'tx': large_tx,
}
large_receipt_row = {
    'tx': large_tx,
    'cex_token_deposit': '150000',
    'cex_quote_estimate': '7500',
    'cex_deposit_count': 1,
    'cex_destination_classes': 'cex_deposit',
}
large_aggregate_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [large_transfer],
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 1},
    [large_receipt_row],
)
assert large_aggregate_rows == [], large_aggregate_rows
large_analysis = module.analyze_rows(path_event, [large_receipt_row] + large_aggregate_rows, 100, 110, 1, 1)
assert large_analysis['cex_token_deposit'] == '150000', large_analysis
assert large_analysis['cex_deposit_count'] == 1, large_analysis
large_with_residual_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [large_transfer] + direct_small_transfers,
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 3},
    [large_receipt_row],
)
assert large_with_residual_rows[0]['cex_token_deposit'] == '120000', large_with_residual_rows
large_with_residual_analysis = module.analyze_rows(
    path_event,
    [large_receipt_row] + large_with_residual_rows,
    100,
    110,
    3,
    3,
)
assert large_with_residual_analysis['cex_token_deposit'] == '270000', large_with_residual_analysis
assert large_with_residual_analysis['cex_deposit_count'] == 3, large_with_residual_analysis

internal_window_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    [
        {
            'token': event['token']['address'],
            'from': hot,
            'to': deposit,
            'amount': module.Decimal('60000'),
            'block': 106,
            'log_index': 0,
            'tx': '0x' + '4' * 64,
        },
        {
            'token': event['token']['address'],
            'from': deposit,
            'to': hot,
            'amount': module.Decimal('60000'),
            'block': 109,
            'log_index': 0,
            'tx': '0x' + '9' * 64,
        },
    ],
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': 2},
)
assert internal_window_rows == [], internal_window_rows
internal_window_analysis = module.analyze_rows(path_event, internal_window_rows, 100, 110, 2, 2)
assert module.event_alert_keys({**path_event, 'analysis': internal_window_analysis}) == [], internal_window_analysis
runtime_rows = module.cex_deposit_transfers(
    event,
    [{'token': event['token']['address'], 'from': '0x' + '6' * 40, 'to': candidate, 'amount': module.Decimal('150000')}],
    {candidate: {'address': candidate, 'class': 'cex_deposit_candidate'}},
)
assert runtime_rows == [], runtime_rows
small_inflows = [
    {
        'token': event['token']['address'],
        'from': f"0x{100 + index:040x}",
        'to': candidate,
        'amount': module.Decimal('50000'),
        'block': 100 + index,
        'log_index': 0,
    }
    for index in range(20)
]
small_inflows.append(
    {
        'token': event['token']['address'],
        'from': candidate,
        'to': hot,
        'amount': module.Decimal('1000000'),
        'block': 130,
        'log_index': 0,
    }
)
small_candidates = module.runtime_cex_deposit_candidates(path_event, 100, 130, small_inflows)
assert small_candidates[candidate]['attributed_external_inflow_amount'] == '1000000', small_candidates
assert small_candidates[candidate]['attributed_external_inbound_count'] == 20, small_candidates
assert small_candidates[candidate]['attribution_method'] == 'observed_window_fifo_in_before_cex_out', small_candidates
small_aggregate_rows = module.runtime_cex_candidate_aggregate_rows(path_event, small_candidates)
assert len(small_aggregate_rows) == 1, small_aggregate_rows
assert small_aggregate_rows[0]['cex_token_deposit'] == '1000000', small_aggregate_rows
assert small_aggregate_rows[0]['path_role'] == 'external_to_cex_inflow', small_aggregate_rows
assert small_aggregate_rows[0]['source_roles'] == 'unlabeled', small_aggregate_rows
assert small_aggregate_rows[0]['attributed_external_inbound_count'] == 20, small_aggregate_rows
assert small_aggregate_rows[0]['coverage_complete'] is True, small_aggregate_rows
small_analysis = module.analyze_rows(path_event, small_aggregate_rows, 100, 130, 21, 21)
assert small_analysis['cex_token_deposit'] == '1000000', small_analysis
assert small_analysis['cex_deposit_count'] == 1, small_analysis
assert module.event_alert_keys({**path_event, 'analysis': small_analysis}), small_analysis
combined_direct_transfers = direct_small_transfers + [
    {
        'token': event['token']['address'],
        'from': external,
        'to': candidate,
        'amount': module.Decimal('80000'),
        'block': 107,
        'log_index': 0,
        'tx': '0x' + '5' * 64,
    },
    {
        'token': event['token']['address'],
        'from': candidate,
        'to': hot,
        'amount': module.Decimal('80000'),
        'block': 108,
        'log_index': 0,
        'tx': '0x' + '6' * 64,
    },
    {
        'token': event['token']['address'],
        'from': hot,
        'to': deposit,
        'amount': module.Decimal('40000'),
        'block': 109,
        'log_index': 0,
        'tx': '0x' + '7' * 64,
    },
]
combined_candidates = module.runtime_cex_deposit_candidates(path_event, 100, 110, combined_direct_transfers)
combined_runtime_rows = module.runtime_cex_candidate_aggregate_rows(
    path_event,
    combined_candidates,
    {**complete_cex_coverage, 'returned_log_count': len(combined_direct_transfers)},
)
combined_direct_rows = module.configured_cex_inflow_aggregate_rows(
    path_event,
    combined_direct_transfers,
    100,
    110,
    {**complete_cex_coverage, 'returned_log_count': len(combined_direct_transfers)},
    [],
    combined_candidates,
)
assert combined_runtime_rows[0]['cex_token_deposit'] == '80000', combined_runtime_rows
assert combined_direct_rows[0]['cex_token_deposit'] == '120000', combined_direct_rows
combined_analysis = module.analyze_rows(
    path_event,
    combined_runtime_rows + combined_direct_rows,
    100,
    110,
    len(combined_direct_transfers),
    len(combined_direct_transfers),
)
assert combined_analysis['cex_token_deposit'] == '200000', combined_analysis
assert combined_analysis['cex_deposit_count'] == 3, combined_analysis
assert combined_analysis['runtime_cex_deposit_candidate_count'] == 1, combined_analysis
duplicate_combined_transfers = combined_direct_transfers + [
    dict(combined_direct_transfers[2]),
    dict(combined_direct_transfers[3]),
]
deduped_combined_transfers, combined_deduplication = module.deduplicate_transfer_logs(duplicate_combined_transfers)
assert len(deduped_combined_transfers) == len(combined_direct_transfers), deduped_combined_transfers
assert combined_deduplication['duplicate_log_count'] == 2, combined_deduplication
assert combined_deduplication['conflicting_duplicate_log_count'] == 0, combined_deduplication
deduped_combined_candidates = module.runtime_cex_deposit_candidates(
    path_event,
    100,
    110,
    deduped_combined_transfers,
)
assert deduped_combined_candidates[candidate]['attributed_external_inflow_amount'] == '80000', deduped_combined_candidates
real_duplicate_aggregate_candidate_txs = module.aggregate_candidate_txs
real_duplicate_transfer_fetch = module.token_transfer_logs_with_coverage
module.aggregate_candidate_txs = lambda event_arg, from_arg, to_arg: ([], len(duplicate_combined_transfers), len(combined_direct_transfers))
module.token_transfer_logs_with_coverage = lambda event_arg, from_arg, to_arg: (
    duplicate_combined_transfers,
    {**complete_cex_coverage, 'returned_log_count': len(duplicate_combined_transfers)},
)
scanned_duplicate_combined = module.scan_event({**path_event, 'opening_block': 100, 'latest_block': 110})
module.aggregate_candidate_txs = real_duplicate_aggregate_candidate_txs
module.token_transfer_logs_with_coverage = real_duplicate_transfer_fetch
assert scanned_duplicate_combined['analysis']['cex_token_deposit'] == '200000', scanned_duplicate_combined
assert scanned_duplicate_combined['analysis']['cex_deposit_count'] == 3, scanned_duplicate_combined
assert scanned_duplicate_combined['analysis']['runtime_cex_deposit_candidate_count'] == 1, scanned_duplicate_combined
duplicate_coverage = scanned_duplicate_combined['_withdrawal_forward_scan']['transfer_coverage']
assert duplicate_coverage['duplicate_log_count'] == 2, duplicate_coverage
assert duplicate_coverage['unique_log_count'] == len(combined_direct_transfers), duplicate_coverage
missing_log_index_transfers = direct_small_transfers + [{
    **direct_small_transfers[0],
    'tx': '0x' + 'a' * 64,
    'log_index': None,
}]
real_missing_identity_aggregate_candidate_txs = module.aggregate_candidate_txs
real_missing_identity_transfer_fetch = module.token_transfer_logs_with_coverage
module.aggregate_candidate_txs = lambda event_arg, from_arg, to_arg: ([], len(missing_log_index_transfers), len(missing_log_index_transfers))
module.token_transfer_logs_with_coverage = lambda event_arg, from_arg, to_arg: (
    missing_log_index_transfers,
    {**complete_cex_coverage, 'returned_log_count': len(missing_log_index_transfers)},
)
scanned_missing_log_index = module.scan_event({**path_event, 'opening_block': 100, 'latest_block': 110})
module.aggregate_candidate_txs = real_missing_identity_aggregate_candidate_txs
module.token_transfer_logs_with_coverage = real_missing_identity_transfer_fetch
missing_identity_coverage = scanned_missing_log_index['_withdrawal_forward_scan']['transfer_coverage']
assert missing_identity_coverage['state'] == 'invalid_transfer_log_identity', missing_identity_coverage
assert missing_identity_coverage['complete'] is False, missing_identity_coverage
assert missing_identity_coverage['missing_log_identity_count'] == 1, missing_identity_coverage
assert scanned_missing_log_index['analysis']['cex_token_deposit'] == '0', scanned_missing_log_index
assert scanned_missing_log_index['analysis']['cex_deposit_count'] == 0, scanned_missing_log_index
assert module.event_alert_keys(scanned_missing_log_index) == [], scanned_missing_log_index
incomplete_aggregate_rows = module.runtime_cex_candidate_aggregate_rows(
    path_event,
    small_candidates,
    {'state': 'partial_rpc_error', 'complete': False},
)
assert incomplete_aggregate_rows[0]['attributed_external_token'] == '1000000', incomplete_aggregate_rows
assert incomplete_aggregate_rows[0]['cex_token_deposit'] == '0', incomplete_aggregate_rows
assert incomplete_aggregate_rows[0]['runtime_effect'] == 'none_incomplete_coverage', incomplete_aggregate_rows
incomplete_analysis = module.analyze_rows(path_event, incomplete_aggregate_rows, 100, 130, 20, 20)
assert incomplete_analysis['cex_deposit_count'] == 0, incomplete_analysis
assert module.event_alert_keys({**path_event, 'analysis': incomplete_analysis}) == [], incomplete_analysis
late_inflow_rows = [
    {'token': event['token']['address'], 'from': external, 'to': candidate, 'amount': module.Decimal('100000'), 'block': 1, 'log_index': 0},
    {'token': event['token']['address'], 'from': candidate, 'to': hot, 'amount': module.Decimal('1000000'), 'block': 2, 'log_index': 0},
    {'token': event['token']['address'], 'from': '0x' + '7' * 40, 'to': candidate, 'amount': module.Decimal('900000'), 'block': 3, 'log_index': 0},
]
late_candidates = module.runtime_cex_deposit_candidates(path_event, 1, 3, late_inflow_rows)
assert late_candidates[candidate]['external_in_amount'] == '1000000', late_candidates
assert late_candidates[candidate]['attributed_external_inflow_amount'] == '100000', late_candidates
mixed_origin_rows = [
    {'token': event['token']['address'], 'from': hot, 'to': candidate, 'amount': module.Decimal('400000'), 'block': 1, 'log_index': 0},
    {'token': event['token']['address'], 'from': external, 'to': candidate, 'amount': module.Decimal('600000'), 'block': 2, 'log_index': 0},
    {'token': event['token']['address'], 'from': candidate, 'to': hot, 'amount': module.Decimal('500000'), 'block': 3, 'log_index': 0},
]
mixed_origin_candidates = module.runtime_cex_deposit_candidates(path_event, 1, 3, mixed_origin_rows)
assert mixed_origin_candidates[candidate]['external_in_amount'] == '600000', mixed_origin_candidates
assert mixed_origin_candidates[candidate]['attributed_external_inflow_amount'] == '100000', mixed_origin_candidates
runtime_analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '150000', 'cex_quote_estimate': '7500', 'cex_deposit_count': 1, 'runtime_cex_deposit_candidate_count': 1, 'cex_destination_classes': 'cex_deposit_candidate'}],
    100,
    200,
    2,
    2,
)
assert runtime_analysis['runtime_cex_deposit_candidate_count'] == 1, runtime_analysis
assert runtime_analysis['cex_destination_classes'] == 'cex_deposit_candidate', runtime_analysis
assert '候选CEX充值路径' in runtime_analysis['trade_signal'], runtime_analysis
internal_analysis = module.analyze_rows(
    path_event,
    [{
        'cex_token_deposit': '0',
        'cex_quote_estimate': '0',
        'cex_deposit_count': 0,
        'cex_internal_aggregation_token': '300000',
        'cex_internal_aggregation_quote_estimate': '15000',
        'cex_internal_aggregation_count': 2,
        'cex_internal_path_roles': 'alpha_custody_movement_unresolved,cex_internal_aggregation',
    }],
    100,
    200,
    2,
    2,
)
assert internal_analysis['direction'] == '观察', internal_analysis
assert internal_analysis['cex_internal_aggregation_count'] == 2, internal_analysis
assert internal_analysis['cex_internal_aggregation_quote_estimate'] == '15000', internal_analysis
assert internal_analysis['cex_internal_aggregation_measure'] == 'gross_transfer_turnover_may_repeat_economic_tokens', internal_analysis
assert module.event_alert_keys({**path_event, 'analysis': internal_analysis}) == [], internal_analysis
def fake_get_logs(chain, query, chunk_blocks, max_logs, timeout):
    user = '0x' + '7' * 40
    hot = '0x' + 'd' * 40
    amount = hex(200000 * 10**18)
    return [
        {
            'address': event['token']['address'],
            'topics': [module.opening.TRANSFER_TOPIC, module.opening.address_topic(user), module.opening.address_topic(candidate)],
            'data': amount,
            'blockNumber': hex(101),
            'transactionIndex': '0x1',
            'logIndex': '0x1',
            'transactionHash': '0x' + 'a' * 64,
        },
        {
            'address': event['token']['address'],
            'topics': [module.opening.TRANSFER_TOPIC, module.opening.address_topic(candidate), module.opening.address_topic(hot)],
            'data': amount,
            'blockNumber': hex(102),
            'transactionIndex': '0x1',
            'logIndex': '0x2',
            'transactionHash': '0x' + 'b' * 64,
        },
    ]
real_runtime_log_rpc = module.opening.quick_rpc_call
module.opening.quick_rpc_call = lambda chain, method, params, timeout: fake_get_logs(
    chain,
    params[0],
    0,
    0,
    timeout,
)
runtime_candidates = module.runtime_cex_deposit_candidates(event, 100, 200)
module.opening.quick_rpc_call = real_runtime_log_rpc
assert candidate in runtime_candidates, runtime_candidates
assert runtime_candidates[candidate]['destination_classes'] == ['cex_deposit'], runtime_candidates
analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '300000', 'cex_quote_estimate': '15000', 'cex_deposit_count': 1}],
    100,
    200,
    2,
    2,
)
assert analysis['direction'] == '偏空', analysis
assert '代币进入CEX' in analysis['trade_signal'], analysis
assert analysis['spot_action'] == '持仓降风险；空仓不追', analysis
assert analysis['cex_quote_estimate'] == '15000', analysis
event_a = {**event, 'from_block': 100, 'to_block': 200, 'analysis': analysis}
event_b = {**event, 'from_block': 120, 'to_block': 220, 'analysis': analysis}
assert module.event_alert_keys(event_a) == module.event_alert_keys(event_b), (module.event_alert_keys(event_a), module.event_alert_keys(event_b))
text = module.telegram_text({'events': [event_a], 'new_alert_count': 1})
assert 'CEX预出货' in text and '持仓降风险' in text and '❗TEST' in text and '买卖信号: ❗' in text, text
assert '有效总结' not in text and len(text) <= 320 and len(text.splitlines()) <= 5, (len(text), text)
many_text = module.telegram_text({
    'events': [event_a, {**event_a, 'symbol': 'SECOND'}, {**event_a, 'symbol': 'THIRD'}],
    'new_alert_count': 3,
})
assert many_text.count('现货动作:') == 2 and '显示 2/3' in many_text and 'THIRD' not in many_text, many_text
assert len(many_text) <= 650 and len(many_text.splitlines()) <= 8, (len(many_text), many_text)
third_event = {**event_a, 'symbol': 'THIRD'}
new_first_text = module.telegram_text({
    'events': [event_a, {**event_a, 'symbol': 'SECOND'}, third_event],
    'new_alert_count': 1,
    '_telegram_new_alert_keys': module.event_alert_keys(third_event),
})
assert 'THIRD' in new_first_text and new_first_text.count('现货动作:') == 2, new_first_text
quiet_analysis = {
    'direction': '观察',
    'trade_signal': '无盘中大额流',
    'spot_action': '观察',
    'net_buy_quote': '0',
    'net_sell_quote': '0',
    'cex_quote_estimate': '0',
    'cex_token_deposit': '0',
    'cex_deposit_count': 0,
    'cex_gas_priming_count': 0,
}
quiet_event = {**event, 'symbol': 'QUIET', 'analysis': quiet_analysis}
mixed_text = module.telegram_text({'events': [event_a, quiet_event], 'new_alert_count': 1})
assert 'QUIET' not in mixed_text and module.event_alert_keys(quiet_event) == [], mixed_text
at_buy = {**quiet_event, 'analysis': {**quiet_analysis, 'net_buy_quote': '20000'}}
below_buy = {**quiet_event, 'analysis': {**quiet_analysis, 'net_buy_quote': '19999'}}
at_cex = {**quiet_event, 'analysis': {**quiet_analysis, 'cex_quote_estimate': '10000', 'cex_deposit_count': 1}}
below_cex = {**quiet_event, 'analysis': {**quiet_analysis, 'cex_quote_estimate': '9999', 'cex_deposit_count': 1}}
assert module.event_alert_keys(at_buy) and not module.event_alert_keys(below_buy), (at_buy, below_buy)
assert module.event_alert_keys(at_cex) and not module.event_alert_keys(below_cex), (at_cex, below_cex)
buy_analysis = module.analyze_rows(
    event,
    [{'buyer': '0x' + '4' * 40, 'spent_quote': '25000', 'cex_token_deposit': '0', 'cex_quote_estimate': '0', 'cex_deposit_count': 0}],
    100,
    200,
    1,
    1,
)
buy_text = module.telegram_text({'events': [{**event, 'analysis': buy_analysis}], 'new_alert_count': 1})
assert buy_analysis['direction'] == '观察偏多', buy_analysis
assert '❗TEST' in buy_text and '买卖信号: ❗盘中大额净买入' in buy_text, buy_text
withdrawal_analysis = {
    **buy_analysis,
    'cex_withdrawal_cluster': {
        'candidate_count': 1,
        'clusters': [{'recipient_count': 9, 'total_quote_estimate': '12000', 'total_token': '240000'}],
    },
}
withdrawal_text = module.telegram_text({'events': [{**event, 'analysis': withdrawal_analysis}], 'new_alert_count': 1})
assert '提现簇候选×1 9地址 ≈12K USDT 方向未知/仅观察' in withdrawal_text, withdrawal_text
candidate_only = {**quiet_event, 'analysis': {**quiet_analysis, 'cex_withdrawal_cluster': withdrawal_analysis['cex_withdrawal_cluster']}}
assert module.event_alert_keys(candidate_only) == [], module.event_alert_keys(candidate_only)
module.BLOCK_TX_CACHE.clear()
real_quick_rpc = module.opening.quick_rpc_call
def fake_quick_rpc(chain, method, params, timeout):
    if method == 'eth_getBlockByNumber':
        return {
            'transactions': [
                {'from': '0x' + 'd' * 40, 'to': '0x' + '1' * 40, 'value': hex(2 * 10**15), 'hash': '0x' + '9' * 64},
                {'from': '0x' + '5' * 40, 'to': '0x' + '1' * 40, 'value': hex(5 * 10**15), 'hash': '0x' + '8' * 64},
            ]
        }
    return real_quick_rpc(chain, method, params, timeout)
module.opening.quick_rpc_call = fake_quick_rpc
gas_rows = module.cex_gas_priming_transfers(event, {'0x' + '1' * 40}, 150)
module.opening.quick_rpc_call = real_quick_rpc
assert len(gas_rows) == 1 and gas_rows[0]['amount_bnb'] == module.Decimal('0.002'), gas_rows
gas_analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '300000', 'cex_quote_estimate': '15000', 'cex_deposit_count': 1, 'cex_gas_priming_count': 1, 'cex_gas_priming_bnb': '0.002'}],
    100,
    200,
    2,
    2,
)
gas_text = module.telegram_text({'events': [{**event, 'analysis': gas_analysis}], 'new_alert_count': 1})
assert 'CEX打gas后代币进入CEX充值/热钱包' in gas_analysis['trade_signal'], gas_analysis
assert 'CEX打gas≈0.002 BNB / 1 次' in gas_text and '买卖信号: ❗' in gas_text, gas_text

micro_recipient = '0x' + '7' * 40
micro_gas_tx = '0x' + '6' * 64
micro_after_tx = '0x' + '4' * 64
micro_token_tx = '0x' + '5' * 64
micro_transfer = {
    'token': event['token']['address'],
    'from': micro_recipient,
    'to': hot,
    'amount_raw': str(123456 * 10**18),
    'decimals': 18,
    'amount': module.Decimal('123456'),
    'block': 150,
    'log_index': 7,
    'tx': micro_token_tx,
}
micro_path = module.classify_cex_transfer_paths(path_event, [micro_transfer])[0]
assert micro_path['tx'] == micro_token_tx and micro_path['log_index'] == 7, micro_path
assert micro_path['token_contract'] == event['token']['address'], micro_path
assert micro_path['token_decimals'] == 18, micro_path

real_block_transactions = module.block_transactions
real_block_timestamp_utc = module.block_timestamp_utc
real_global_address_label = module.opening.global_address_label
real_micro_quick_rpc = module.opening.quick_rpc_call
old_gas_lookback = os.environ.get('ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS')
os.environ['ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS'] = '2'
module.block_transactions = lambda chain, block, timeout: (
    [{
        'from': hot,
        'to': micro_recipient,
        'value': hex(3_000_000_000_000),
        'hash': micro_gas_tx,
        'transactionIndex': '0x3',
    }]
    if block == 149
    else [{
        'from': hot,
        'to': micro_recipient,
        'value': hex(2_000_000_000_000),
        'hash': micro_after_tx,
        'transactionIndex': '0x5',
    }]
    if block == 150
    else []
)
module.block_timestamp_utc = lambda chain, block, timeout: (
    '2026-07-23T00:00:03Z' if block == 150 else '2026-07-23T00:00:00Z'
)
module.opening.global_address_label = lambda chain, address: (
    {
        'address': hot,
        'class': 'cex_hot_wallet',
        'exchange': 'FixtureEx',
        'label': 'Fixture Hot',
        'evidence': 'fixture exact-address label',
    }
    if address == hot
    else None
)
module.opening.quick_rpc_call = lambda chain, method, params, timeout: (
    {
        'transactionHash': micro_gas_tx,
        'blockNumber': hex(149),
        'transactionIndex': '0x3',
        'status': '0x1',
        'from': hot,
        'to': micro_recipient,
    }
    if method == 'eth_getTransactionReceipt' and params == [micro_gas_tx]
    else {
        'transactionHash': micro_token_tx,
        'blockNumber': hex(150),
        'transactionIndex': '0x4',
        'status': '0x1',
        'logs': [{
            'address': event['token']['address'],
            'blockNumber': hex(150),
            'transactionHash': micro_token_tx,
            'logIndex': hex(7),
            'topics': [
                module.opening.TRANSFER_TOPIC,
                '0x' + '0' * 24 + micro_recipient[2:],
                '0x' + '0' * 24 + hot[2:],
            ],
            'data': hex(123456 * 10**18),
        }],
    }
    if method == 'eth_getTransactionReceipt' and params == [micro_token_tx]
    else real_micro_quick_rpc(chain, method, params, timeout)
)
expired_rows, expired_coverage = module.native_micro_gas_rows(
    path_event,
    micro_recipient,
    150,
    4,
    module.time.monotonic() - 1,
)
assert expired_rows == [], expired_rows
assert expired_coverage['state'] == 'partial_time_budget', expired_coverage
assert expired_coverage['completed_block_count'] == 0, expired_coverage
micro_coverage = {
    'state': 'requested_window_complete',
    'complete': True,
    'requested_from_block': 100,
    'requested_to_block': 200,
    'covered_through_block': 200,
    'returned_log_count': 1,
    'max_logs': 12000,
}
micro_bundle = module.collect_report_only_cex_micro_gas_samples(
    path_event,
    [micro_transfer],
    micro_coverage,
    {},
)
partial_bundle = module.collect_report_only_cex_micro_gas_samples(
    path_event,
    [micro_transfer],
    {**micro_coverage, 'state': 'partial_rpc_error', 'complete': False},
    {},
)
module.block_transactions = real_block_transactions
module.block_timestamp_utc = real_block_timestamp_utc
module.opening.global_address_label = real_global_address_label
module.opening.quick_rpc_call = real_micro_quick_rpc
if old_gas_lookback is None:
    os.environ.pop('ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS', None)
else:
    os.environ['ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS'] = old_gas_lookback

assert micro_bundle['candidate_count'] == 1, micro_bundle
assert micro_bundle['window_reviews'][0]['native_scan_coverage']['state'] == 'requested_window_complete', micro_bundle
assert micro_bundle['window_reviews'][0]['native_scan_coverage']['after_or_equal_transaction_count'] == 1, micro_bundle
micro_candidate = micro_bundle['candidates'][0]
assert micro_candidate['status'] == 'blocked', micro_candidate
assert micro_candidate['alert_policy'] == 'report_only' and micro_candidate['runtime_effect'] == 'none', micro_candidate
assert micro_candidate['action_guard'] == 'no_runtime_action_mutation', micro_candidate
assert micro_candidate['native_gas']['tx'] == micro_gas_tx, micro_candidate
assert micro_candidate['native_gas']['receipt_status'] == 1, micro_candidate
assert micro_candidate['native_gas']['value_wei'] == '3000000000000', micro_candidate
assert micro_candidate['native_gas']['value_native'] == '0.000003', micro_candidate
assert micro_candidate['native_gas']['source_label']['label'] == 'Fixture Hot', micro_candidate
assert micro_candidate['token_ingress']['tx'] == micro_token_tx, micro_candidate
assert micro_candidate['token_ingress']['log_index'] == 7, micro_candidate
assert micro_candidate['token_ingress']['decimals'] == 18, micro_candidate
assert micro_candidate['token_ingress']['amount_raw'] == str(123456 * 10**18), micro_candidate
assert micro_candidate['token_ingress']['amount_normalized'] == '123456', micro_candidate
assert micro_candidate['token_ingress']['destination_label']['exchange'] == 'FixtureEx', micro_candidate
assert micro_candidate['pairing']['gas_before_token_seconds'] == 3, micro_candidate
assert micro_candidate['pairing']['recipient_match'] is True, micro_candidate
assert micro_candidate['pairing']['exchange_entity_match'] is True, micro_candidate
assert micro_candidate['independence']['exchange_entity'] == 'FixtureEx', micro_candidate
assert micro_candidate['pairing']['unique_pairing'] is True, micro_candidate
assert micro_candidate['pairing']['ambiguity_reasons'] == ['same_block_after_or_equal_native_transfer_observed'], micro_candidate
assert micro_candidate['coverage']['coverage_complete'] is True, micro_candidate
assert micro_candidate['independence']['independence_eligible'] is False, micro_candidate
assert 'unique_gas_to_token_pairing' not in micro_candidate['unresolved_fields'], micro_candidate
assert 'independent_positive_root_review' in micro_candidate['unresolved_fields'], micro_candidate
partial_candidate = partial_bundle['candidates'][0]
assert partial_candidate['status'] == 'blocked' and partial_candidate['pairing']['unique_pairing'] is False, partial_candidate
assert 'token_transfer_window_coverage_incomplete' in partial_candidate['pairing']['ambiguity_reasons'], partial_candidate
assert 'unique_gas_to_token_pairing' in partial_candidate['unresolved_fields'], partial_candidate
micro_event = {
    **quiet_event,
    'report_only_cex_micro_gas_samples': micro_bundle,
}
assert module.event_alert_keys(micro_event) == []
assert module.telegram_text({'events': [micro_event], 'new_alert_count': 0}) == module.telegram_text({
    'events': [quiet_event],
    'new_alert_count': 0,
})

micro_history_path = Path(tempfile.mkdtemp(prefix='cex_micro_gas_history_')) / 'cex_micro_gas_candidate_history.json'
module.CEX_MICRO_GAS_CANDIDATE_HISTORY_PATH = micro_history_path
micro_snapshot = {
    'generated_at': '2026-07-23T00:00:03+00:00',
    'events': [{
        **event,
        'report_only_cex_micro_gas_samples': micro_bundle,
    }],
}
assert module.record_cex_micro_gas_candidate_history(micro_snapshot) == 1
assert module.record_cex_micro_gas_candidate_history(micro_snapshot) == 1
micro_history = json.loads(micro_history_path.read_text(encoding='utf-8'))
assert micro_history['schema'] == 'cex_micro_gas_candidate_history.v1', micro_history
assert micro_history['max_candidates'] == module.CEX_MICRO_GAS_CANDIDATE_HISTORY_MAX, micro_history
assert len(micro_history['candidates']) == 1, micro_history
assert micro_history['candidates'][0]['observation_count'] == 2, micro_history
assert module.record_cex_micro_gas_candidate_history({
    'generated_at': '2026-07-23T00:05:03+00:00',
    'events': [],
}) == 0
assert len(json.loads(micro_history_path.read_text(encoding='utf-8'))['candidates']) == 1
"""
    alpha_intraday_cex_result = subprocess.run(
        [sys.executable, "-c", alpha_intraday_cex_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha intraday CEX flow and withdrawal cluster safeguards",
            alpha_intraday_cex_result.returncode == 0,
            alpha_intraday_cex_result.stderr.strip(),
        )
    )

    x_mcp_readiness_code = """
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='x_mcp_readiness_'))
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'x_mcp_readiness.py'),
        '--out-dir',
        str(out),
        '--no-network',
        '--skip-xurl',
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'x_mcp_readiness.v1', payload
assert payload['status'] == 'offline_probe', payload
assert payload['network']['skipped'] is True, payload
assert payload['xurl']['skipped'] is True, payload
assert (out / 'latest.md').exists(), out
spec = importlib.util.spec_from_file_location('x_mcp_readiness', root / 'scripts' / 'x_mcp_readiness.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def raise_reset(*args, **kwargs):
    raise ConnectionResetError('reset by peer')
module.urlopen = raise_reset
fetch = module.fetch_url('https://example.com', 1)
assert fetch['ok'] is False and fetch['status'] is None and 'reset by peer' in fetch['error'], fetch
"""
    x_mcp_readiness_result = subprocess.run(
        [sys.executable, "-c", x_mcp_readiness_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("x mcp readiness offline smoke test", x_mcp_readiness_result.returncode == 0, x_mcp_readiness_result.stderr.strip()))

    external_aux_readiness_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='external_aux_sources_'))
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'external_aux_source_readiness.py'),
        '--out-dir',
        str(out),
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'external_aux_source_readiness.v1', payload
assert payload['source_count'] >= 4, payload
ids = {row['id'] for row in payload['rows']}
assert {'coinglass', 'coinank', 'gmgn', 'debot_ai'}.issubset(ids), payload
assert all(row['authority'] == 'context_only' for row in payload['rows'] if not row['live_probe_validated']), payload
assert (out / 'latest.md').exists(), out
"""
    external_aux_readiness_result = subprocess.run(
        [sys.executable, "-c", external_aux_readiness_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "external auxiliary source readiness smoke test",
            external_aux_readiness_result.returncode == 0,
            external_aux_readiness_result.stderr.strip(),
        )
    )

    external_aux_live_probe_code = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='external_aux_live_probe_'))
env = os.environ.copy()
for key in ['COINGLASS_API_KEY', 'COINANK_API_KEY', 'GMGN_API_KEY']:
    env.pop(key, None)
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'external_aux_live_probe.py'),
        '--out-dir',
        str(out),
        '--source',
        'coinglass,coinank,gmgn,surf',
    ],
    cwd=root,
    env=env,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'external_aux_live_probe.v1', payload
rows = {row['id']: row for row in payload['rows']}
assert rows['coinglass']['status'] == 'needs_credentials', rows
assert rows['coinank']['status'] == 'needs_credentials', rows
assert rows['gmgn']['status'] == 'needs_credentials', rows
assert rows['surf']['ok'] is True, rows
assert (out / 'latest.md').exists(), out
"""
    external_aux_live_probe_result = subprocess.run(
        [sys.executable, "-c", external_aux_live_probe_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "external auxiliary live probe smoke test",
            external_aux_live_probe_result.returncode == 0,
            external_aux_live_probe_result.stderr.strip(),
        )
    )

    position_cost_watch_code = """
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import scripts.position_cost_watch as module

as_of = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)
active = module.position_time_fields(
    {'opened_at': '2026-07-08T08:00:00+08:00', 'time_stop_days': '30'},
    as_of,
)
assert active['holding_days'] == 6 and active['time_stop_state'] == 'active', active
same_instant = module.position_time_fields(
    {'opened_at': '2026-07-08T00:00:00Z', 'time_stop_days': '30'},
    as_of,
)
assert same_instant['holding_days'] == active['holding_days'], (same_instant, active)
assert same_instant['time_stop_state'] == active['time_stop_state'], (same_instant, active)
before_due = module.position_time_fields(
    {'opened_at': '2026-06-14T00:00:01+00:00', 'time_stop_days': '30'},
    as_of,
)
assert before_due['holding_days'] == 29 and before_due['time_stop_state'] == 'active', before_due
due = module.position_time_fields(
    {'opened_at': '2026-06-14T00:00:00+00:00', 'time_stop_days': '30'},
    as_of,
)
assert due['holding_days'] == 30 and due['time_stop_state'] == 'due', due
empty_context = {key: {} for key in ('alpha_price', 'perp', 'surf', 'intraday', 'opening', 'holder')}
due_position = module.position_row(
    {
        'symbol': 'TEST',
        'side': 'long',
        'quantity': '1',
        'avg_entry': '1',
        'current_price': '1',
        'opened_at': '2026-06-14T00:00:00Z',
        'time_stop_days': '30',
    },
    empty_context,
    as_of,
)
assert due_position['time_stop_state'] == 'due', due_position
assert due_position['position_state'] == 'hold_watch', due_position
assert due_position['action'] == '持仓观察；按失效条件管理', due_position
assert module.position_time_fields({'opened_at': '2026-07-08T00:00:00Z'}, as_of)['time_stop_state'] == 'not_configured'
assert module.position_time_fields({'time_stop_days': '30'}, as_of)['time_stop_state'] == 'missing_opened_at'
assert module.position_time_fields({'opened_at': 'invalid', 'time_stop_days': '30'}, as_of)['time_stop_state'] == 'invalid_opened_at'
assert module.position_time_fields({'opened_at': '2026-07-08T00:00:00', 'time_stop_days': '30'}, as_of)['time_stop_state'] == 'invalid_opened_at'
assert module.position_time_fields({'opened_at': '2026-07-15T00:00:00Z', 'time_stop_days': '30'}, as_of)['time_stop_state'] == 'future_opened_at'
for invalid_limit in ('0', 0, '-1', 'NaN', 'Infinity', 'invalid'):
    invalid = module.position_time_fields(
        {'opened_at': '2026-07-08T00:00:00Z', 'time_stop_days': invalid_limit},
        as_of,
    )
    assert invalid['time_stop_state'] == 'invalid_time_stop_days', invalid

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='position_cost_watch_'))
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'position_cost_watch.py'),
        '--out-dir',
        str(out),
        '--use-example',
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'position_cost_watch.v1', payload
assert payload['mode'] == 'read_only_no_signing_no_execution', payload
assert payload['position_count'] == 1 and payload['paper_trade_count'] == 1, payload
assert payload['positions'][0]['symbol'] == 'ARX', payload
assert {'opened_at', 'holding_days', 'time_stop_days', 'time_stop_state'} <= set(payload['positions'][0]), payload
assert 'Held / Time stop' in (out / 'latest.md').read_text(encoding='utf-8')
assert (out / 'latest.md').exists(), out
"""
    position_cost_watch_result = subprocess.run(
        [sys.executable, "-c", position_cost_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "position cost watch smoke test",
            position_cost_watch_result.returncode == 0,
            position_cost_watch_result.stderr.strip(),
        )
    )

    runtime_health_watch_code = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import scripts.runtime_health_watch as health
from scripts.runtime_health_watch import CRITICAL_OUTPUTS, apply_notification, write_json

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='runtime_health_watch_'))
fake_root = work / 'root'
out = work / 'out'
for _, relative in CRITICAL_OUTPUTS:
    path = fake_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('# verification has no failures\\n' if path.suffix == '.md' else '{}\\n', encoding='utf-8')
daily = fake_root / 'reports' / '2026-07-10_alpha_sniper_daily.md'
daily.parent.mkdir(parents=True, exist_ok=True)
daily.write_text('# Daily report\\n', encoding='utf-8')
failure_file = out / 'failures.tsv'
out.mkdir(parents=True, exist_ok=True)
failure_file.write_text('', encoding='utf-8')
base_cmd = [
    sys.executable,
    str(root / 'scripts' / 'runtime_health_watch.py'),
    '--root',
    str(fake_root),
    '--out-dir',
    str(out),
    '--max-output-age-seconds',
    '999999999',
    '--max-cycle-age-seconds',
    '999999999',
    '--no-telegram',
]
healthy = subprocess.run(base_cmd + ['--mode', 'cycle', '--failure-file', str(failure_file)], cwd=root, capture_output=True, text=True)
assert healthy.returncode == 0, healthy.stderr or healthy.stdout
payload = json.loads((out / 'last_cycle.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'runtime_health.v1', payload
assert payload['status'] == 'healthy' and payload['issue_count'] == 0, payload

failure_file.write_text('124\\t30\\tpython3 scripts/example_timeout.py\\n', encoding='utf-8')
failed = subprocess.run(base_cmd + ['--mode', 'cycle', '--failure-file', str(failure_file)], cwd=root, capture_output=True, text=True)
assert failed.returncode == 0, failed.stderr or failed.stdout
payload = json.loads((out / 'last_cycle.json').read_text(encoding='utf-8'))
assert payload['status'] == 'unhealthy', payload
assert payload['failed_steps'][0]['exit_status'] == 124, payload
assert payload['failed_steps'][0]['timed_out'] is True, payload
assert payload['issues'][0]['detail'] == '步骤超时 30s · python3 scripts/example_timeout.py', payload
assert any(row['kind'] == 'step_failed' for row in payload['issues']), payload

failure_file.write_text('1\\t30\\tpython3 scripts/example_failure.py\\n', encoding='utf-8')
failed = subprocess.run(base_cmd + ['--mode', 'cycle', '--failure-file', str(failure_file)], cwd=root, capture_output=True, text=True)
assert failed.returncode == 0, failed.stderr or failed.stdout
payload = json.loads((out / 'last_cycle.json').read_text(encoding='utf-8'))
assert payload['failed_steps'][0]['timed_out'] is False, payload
assert payload['issues'][0]['detail'] == '步骤失败 exit=1 · 超时上限 30s · python3 scripts/example_failure.py', payload

watchdog = subprocess.run(base_cmd + ['--mode', 'watchdog'], cwd=root, capture_output=True, text=True)
assert watchdog.returncode == 0, watchdog.stderr or watchdog.stdout
payload = json.loads((out / 'latest_watchdog.json').read_text(encoding='utf-8'))
assert payload['status'] == 'unhealthy', payload
assert any(row['kind'] == 'step_failed' for row in payload['issues']), payload
assert (out / 'latest.md').exists(), out

write_json(
    out / 'state.json',
    {
        'last_status': 'unhealthy',
        'last_signature': payload['signature'],
        'last_alert_sent_at': payload['generated_at'],
    },
)
suppressed = apply_notification(
    payload,
    out,
    SimpleNamespace(repeat_minutes=360, no_telegram=True, telegram_timeout=1),
)
assert suppressed['status'] == 'suppressed', suppressed

last_cycle = out / 'last_cycle.json'
os.utime(last_cycle, (1, 1))
stale = subprocess.run(base_cmd + ['--mode', 'watchdog', '--max-cycle-age-seconds', '1'], cwd=root, capture_output=True, text=True)
assert stale.returncode == 0, stale.stderr or stale.stdout
payload = json.loads((out / 'latest_watchdog.json').read_text(encoding='utf-8'))
assert any(row['kind'] == 'stale_heartbeat' for row in payload['issues']), payload

recovery_snapshot = {
    'status': 'healthy',
    'signature': 'healthy',
    'generated_at': '2026-07-14T02:00:00+00:00',
}
incident_snapshot = {
    'status': 'unhealthy',
    'signature': 'collector-timeout',
    'generated_at': '2026-07-14T01:30:00+00:00',
    'issue_count': 1,
    'mode': 'cycle',
    'issues': [{'detail': '步骤失败 exit=1 · 超时上限 90s · python3 scripts/telegram_signal_collector.py'}],
}
write_json(
    out / 'state.json',
    {
        'last_status': 'healthy',
        'last_signature': 'healthy',
        'last_alert_sent_at': '2026-07-13T01:00:00+00:00',
    },
)
os.environ['DISABLE_TELEGRAM'] = '0'
os.environ['RUNTIME_HEALTH_TELEGRAM'] = '1'
health.send_telegram = lambda text, timeout: {'status': 'failed', 'reason': 'fixture'}
recovery_args = SimpleNamespace(repeat_minutes=360, no_telegram=False, telegram_timeout=1)
failed_alert = health.apply_notification(incident_snapshot, out, recovery_args)
assert failed_alert['status'] == 'failed', failed_alert
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert state['last_status'] == 'unhealthy', state
assert state['incident_alert_attempted_at'] == incident_snapshot['generated_at'], state
assert state['last_alert_sent_at'] == '2026-07-13T01:00:00+00:00', state
health.send_telegram = lambda text, timeout: {'status': 'failed', 'reason': 'fixture recovery'}
failed_recovery = health.apply_notification(recovery_snapshot, out, recovery_args)
assert failed_recovery['status'] == 'failed', failed_recovery
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert state['last_status'] == 'healthy' and state['active_incident_signature'] == incident_snapshot['signature'], state
assert state['incident_alert_attempted_at'] == incident_snapshot['generated_at'], state
health.send_telegram = lambda text, timeout: {'status': 'sent', 'message_id': 1}
retry_recovery_snapshot = {**recovery_snapshot, 'generated_at': '2026-07-14T02:05:00+00:00'}
sent_recovery = health.apply_notification(retry_recovery_snapshot, out, recovery_args)
assert sent_recovery['status'] == 'sent', sent_recovery
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert 'incident_alert_attempted_at' not in state, state
assert 'active_incident_signature' not in state, state
assert state['last_recovery_attempted_at'] == retry_recovery_snapshot['generated_at'], state
assert state['last_recovery_sent_at'] == retry_recovery_snapshot['generated_at'], state

write_json(
    out / 'state.json',
    {
        'last_status': 'unhealthy',
        'last_signature': 'collector-timeout',
        'last_alert_sent_at': '2026-07-13T01:00:00+00:00',
    },
)
disabled_args = SimpleNamespace(repeat_minutes=360, no_telegram=True, telegram_timeout=1)
no_ghost_recovery = health.apply_notification(recovery_snapshot, out, disabled_args)
assert no_ghost_recovery['status'] == 'not_needed', no_ghost_recovery

write_json(
    out / 'state.json',
    {
        'last_status': 'healthy',
        'last_signature': 'healthy',
        'last_alert_sent_at': '2026-07-13T01:00:00+00:00',
    },
)
disabled_alert = health.apply_notification(incident_snapshot, out, disabled_args)
assert disabled_alert['status'] == 'disabled', disabled_alert
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert state['active_incident_signature'] == incident_snapshot['signature'], state
assert 'incident_alert_attempted_at' not in state, state
health.send_telegram = lambda text, timeout: {'status': 'sent', 'message_id': 2}
enabled_alert = health.apply_notification(incident_snapshot, out, recovery_args)
assert enabled_alert['status'] == 'sent', enabled_alert
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert state['incident_alert_sent_at'] == incident_snapshot['generated_at'], state
disabled_recovery = health.apply_notification(recovery_snapshot, out, disabled_args)
assert disabled_recovery['status'] == 'disabled', disabled_recovery
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert state['active_incident_signature'] == incident_snapshot['signature'], state
sent_after_disabled = health.apply_notification(retry_recovery_snapshot, out, recovery_args)
assert sent_after_disabled['status'] == 'sent', sent_after_disabled
state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
assert 'active_incident_signature' not in state, state
"""
    runtime_health_watch_result = subprocess.run(
        [sys.executable, "-c", runtime_health_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "runtime health failure and watchdog smoke test",
            runtime_health_watch_result.returncode == 0,
            runtime_health_watch_result.stderr.strip(),
        )
    )

    cron_installer_code = """
import os
import subprocess
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='cron_installer_'))
bin_dir = work / 'bin'
bin_dir.mkdir()
store = work / 'crontab.txt'
store.write_text('17 3 * * * /usr/local/bin/unrelated-job\\n', encoding='utf-8')
fake = bin_dir / 'crontab'
fake.write_text(
    '#!/usr/bin/env bash\\n'
    'set -euo pipefail\\n'
    'store="${FAKE_CRONTAB_STORE:?}"\\n'
    'if [[ "${1:-}" == "-l" ]]; then cat "$store"; exit 0; fi\\n'
    'cp "$1" "$store"\\n',
    encoding='utf-8',
)
fake.chmod(0o755)
env = os.environ.copy()
env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
env['FAKE_CRONTAB_STORE'] = str(store)
project_dir = work / 'project'
env['SNIPER_PROJECT_DIR'] = str(project_dir)
cmd = ['bash', str(root / 'scripts' / 'install_server_cron.sh')]
for _ in range(2):
    result = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
text = store.read_text(encoding='utf-8')
assert text.count(str(project_dir / 'scripts' / 'server_run_once.sh')) == 1, text
assert text.count(str(project_dir / 'scripts' / 'server_health_watchdog.sh')) == 1, text
assert '/usr/local/bin/unrelated-job' in text, text
assert (project_dir / 'logs').is_dir(), project_dir
"""
    cron_installer_result = subprocess.run(
        [sys.executable, "-c", cron_installer_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "server cron installer is idempotent and preserves unrelated jobs",
            cron_installer_result.returncode == 0,
            cron_installer_result.stderr.strip(),
        )
    )

    celue_audit_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='celue_audit_'))
source_skill = Path('/Users/xuyufan/Documents/蒸馏技能/celue')
installed_skill = Path('/Users/xuyufan/.codex/skills/celue')
cmd = [
    sys.executable,
    str(root / 'scripts' / 'audit_celue_integration.py'),
    '--out-dir',
    str(out),
]
if not (source_skill.exists() and installed_skill.exists()):
    cmd.append('--project-only')
result = subprocess.run(
    cmd,
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr or result.stdout
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'celue_integration_audit.v1', payload
assert payload['failed_count'] == 0, payload
assert payload['check_count'] >= 10, payload
assert (out / 'latest.md').exists(), out
"""
    celue_audit_result = subprocess.run(
        [sys.executable, "-c", celue_audit_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "celue integration audit smoke test",
            celue_audit_result.returncode == 0,
            celue_audit_result.stderr.strip() or celue_audit_result.stdout.strip(),
        )
    )

    registry_env = os.environ.copy()
    registry_env["PROJECT_REGISTRY_PATH"] = str(Path(tempfile.gettempdir()) / "sniper_project_registry_test.json")
    registry_env["PROJECT_REGISTRY_SUMMARY_PATH"] = str(Path(tempfile.gettempdir()) / "sniper_project_registry_test.md")
    registry_test_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal
from sniper_engine.project_registry import merge_signal, read_json, REGISTRY_PATH, SUMMARY_PATH

for path in [REGISTRY_PATH, SUMMARY_PATH]:
    path.unlink(missing_ok=True)

text1 = '$BTC 即将上线\\n区块: 123456\\nBSC 合约: 0x1111111111111111111111111111111111111111'
text2 = '$BTC 总量 1B\\n团队 10%\\n流动性 6%'
first = merge_signal(parse_signal(text1, Path('/tmp/btc1.txt')), {'collector': 'verify', 'source': 'one'})
second = merge_signal(parse_signal(text2, Path('/tmp/btc2.txt')), {'collector': 'verify', 'source': 'two'})
third = merge_signal(parse_signal(text2, Path('/tmp/btc2.txt')), {'collector': 'verify', 'source': 'two'})
cap_text = '''LP / USDT
CAP 合约: 0x99991c6aabba5a096f24f250b73580f5179b9999
hook: 0xb0baa371b899950b4ef6a27c21baf5ef7c434d0f
PoolId: 0x3bca91b9b847cff6f4b666fa1d966981678975e13fd69d647bd11bed99f5fa14'''
cap_bad = parse_signal(cap_text, Path('/tmp/cap_pool_bad.txt'))
cap_bad['symbol'] = 'LP'
cap_first = merge_signal(cap_bad, {'collector': 'verify', 'source': 'cap_bad'})
cap_good = parse_signal(cap_text, Path('/tmp/cap_pool_good.txt'))
cap_good['symbol'] = 'CAP'
cap_second = merge_signal(cap_good, {'collector': 'verify', 'source': 'cap_good'})
registry = read_json(REGISTRY_PATH, {})
projects = registry.get('projects', [])
assert first['status'] == 'new_project', first
assert second['status'] == 'updated_project', second
assert third['status'] == 'duplicate_signal', third
assert cap_first['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap_first
assert cap_second['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap_second
assert len(projects) == 2, projects
btc = next(project for project in projects if project['symbol'] == 'BTC')
cap = next(project for project in projects if project['symbol'] == 'CAP')
assert btc['facts']['total_supply'] == '1B', btc['facts']
assert cap['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap
assert cap['symbol'] == 'CAP', cap
assert any(row.get('address', '').lower() == '0x99991c6aabba5a096f24f250b73580f5179b9999' for row in cap.get('contracts', [])), cap
"""
    registry_result = subprocess.run(
        [sys.executable, "-c", registry_test_code],
        cwd=ROOT,
        env=registry_env,
        capture_output=True,
        text=True,
    )
    checks.append(("project registry dedup smoke test", registry_result.returncode == 0, registry_result.stderr.strip()))

    parser_test_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal

text = '''18点空投 (ARX）
分数要求：225分 先到先得 每人172个代币
代币合约：0xd5f6ef5dEabE61E6d5CDB49BFB6f156F2c1cA715
Alpha空投占代币总量的0.85%'''
parsed = parse_signal(text, Path('/tmp/arx_airdrop.txt'))
assert parsed['symbol'] == 'ARX', parsed
assert parsed['addresses'][0]['label_hint'] == 'token_contract', parsed['addresses']
"""
    parser_result = subprocess.run(
        [sys.executable, "-c", parser_test_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal parser handles parenthesized ARX", parser_result.returncode == 0, parser_result.stderr.strip()))

    clustering_guard_code = """
from sniper_engine.entity_clustering import can_use_as_funding_cluster_parent, cluster_by_funding_source

extra = {
    '0x' + '1' * 40: {'class': 'cex_hot_wallet'},
    '0x' + '2' * 40: {'class': 'cex_deposit'},
    '0x' + '3' * 40: {'class': 'bridge'},
    '0x' + '4' * 40: {'class': 'unknown_contract_pending_bearish'},
    '0x' + '5' * 40: {'class': 'eoa'},
}
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '1' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '2' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '3' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '4' * 40, extra)
assert can_use_as_funding_cluster_parent('bsc', '0x' + '5' * 40, extra)
assert can_use_as_funding_cluster_parent('bsc', '0x' + '6' * 40, extra)
rows = [
    {'address': '0x' + 'a' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'b' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'c' * 40, 'funding_source': '0x' + '1' * 40},
    {'address': '0x' + 'd' * 40, 'funding_source': '0x' + '1' * 40},
]
review = cluster_by_funding_source('bsc', rows, extra)
assert review['cluster_count'] == 1, review
assert review['clusters'][0]['member_count'] == 2, review
assert review['skipped_parent_count'] == 1, review
assert review['skipped_parents'][0]['class'] == 'cex_hot_wallet', review
"""
    clustering_guard_result = subprocess.run(
        [sys.executable, "-c", clustering_guard_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("funding-source clustering guard", clustering_guard_result.returncode == 0, clustering_guard_result.stderr.strip()))

    funding_cluster_review_code = """
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='funding_cluster_review_'))
source = work / 'clusters.csv'
labels = work / 'labels.json'
out_dir = work / 'out'
rows = [
    {'address': '0x' + 'a' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'b' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'c' * 40, 'funding_source': '0x' + '1' * 40},
    {'address': '0x' + 'd' * 40, 'funding_source': '0x' + '1' * 40},
]
with source.open('w', encoding='utf-8', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['address', 'funding_source'])
    writer.writeheader()
    writer.writerows(rows)
labels.write_text(json.dumps({'0x' + '1' * 40: 'cex_hot_wallet'}), encoding='utf-8')
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'review_funding_source_clusters.py'),
        '--input',
        str(source),
        '--extra-labels',
        str(labels),
        '--out-dir',
        str(out_dir),
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert payload['cluster_count'] == 1, payload
assert payload['skipped_parent_count'] == 1, payload
assert payload['skipped_parents'][0]['class'] == 'cex_hot_wallet', payload
assert (out_dir / 'latest.md').exists(), out_dir
"""
    funding_cluster_review_result = subprocess.run(
        [sys.executable, "-c", funding_cluster_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("funding-source cluster review smoke test", funding_cluster_review_result.returncode == 0, funding_cluster_review_result.stderr.strip()))

    opening_funder_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='opening_funder_review_'))
source = work / 'opening.json'
out_dir = work / 'out'
source.write_text(json.dumps({
    'events': [
        {
            'symbol': 'TEST',
            'name': 'Test Token',
            'rows': [
                {'buyer': '0x' + 'a' * 40, 'block': 123, 'tx': '0x' + '1' * 64, 'spent_quote': '100'},
                {'buyer': '0x' + 'b' * 40, 'block': 124, 'tx': '0x' + '2' * 64, 'spent_quote': '200'},
            ],
        }
    ]
}), encoding='utf-8')
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'review_opening_cohort_funders.py'),
        '--input',
        str(source),
        '--out-dir',
        str(out_dir),
        '--lookback-blocks',
        '0',
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert payload['funders_found'] == 0, payload
assert len(payload['rows']) == 2, payload
assert payload['rows'][0]['symbol'] == 'TEST', payload
assert (out_dir / 'latest.md').exists(), out_dir
"""
    opening_funder_review_result = subprocess.run(
        [sys.executable, "-c", opening_funder_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("opening cohort funder review smoke test", opening_funder_review_result.returncode == 0, opening_funder_review_result.stderr.strip()))

    alpha_venue_code = """
from decimal import Decimal
import os
from scripts.alpha_price_momentum_watch import venue_classification

cap = venue_classification(Decimal('869294.19'), {'status': 'ok', 'onchain_gross_quote': '37699.91'})
assert cap['venue_class'] == 'ALPHA_DOMINANT', cap
assert cap['coverage'] == 'ONCHAIN_NETFLOW_UNRELIABLE', cap
assert cap['onchain_netflow_reliable'] is False, cap
os.environ['ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT'] = '1'
cap_reliable = venue_classification(Decimal('869294.19'), {'status': 'ok', 'onchain_gross_quote': '37699.91'})
assert cap_reliable['coverage'] == 'ONCHAIN_PARTIAL_NEGATIVE_ONLY', cap_reliable
assert cap_reliable['onchain_netflow_reliable'] is True, cap_reliable
os.environ.pop('ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT', None)
mixed = venue_classification(Decimal('300000'), {'status': 'ok', 'onchain_gross_quote': '100000'})
assert mixed['venue_class'] == 'MIXED', mixed
native = venue_classification(Decimal('100000'), {'status': 'ok', 'onchain_gross_quote': '70000'})
assert native['venue_class'] == 'ONCHAIN_NATIVE', native
missing = venue_classification(Decimal('100000'), {'status': 'missing', 'onchain_gross_quote': '0'})
assert missing['venue_class'] == 'UNKNOWN', missing
"""
    alpha_venue_result = subprocess.run(
        [sys.executable, "-c", alpha_venue_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("alpha venue classification guard", alpha_venue_result.returncode == 0, alpha_venue_result.stderr.strip()))

    exchange_aggregator_exclusion_code = """
from scripts.alpha_opening_block_watch import excluded_addresses

event = {
    'chain': 'bsc',
    'token': {'address': '0x' + 'a' * 40},
    'quote': {'address': '0x' + 'b' * 40},
    'hook': '',
    'operator': '',
    'known_contracts': [],
    'exchange_aggregator_addresses': ['0x' + '1' * 40],
    'exchange_aggregator_suspect_addresses': [{'address': '0x' + '2' * 40}],
    'market_context': {
        'exchange_rebalance_addresses': ['0x' + '3' * 40],
        'pool_manager_addresses': ['0x' + '4' * 40],
    },
}
excluded = excluded_addresses(event)
assert '0x' + '1' * 40 in excluded, excluded
assert '0x' + '2' * 40 in excluded, excluded
assert '0x' + '3' * 40 in excluded, excluded
assert '0x' + '4' * 40 in excluded, excluded
"""
    exchange_aggregator_exclusion_result = subprocess.run(
        [sys.executable, "-c", exchange_aggregator_exclusion_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange aggregator cohort exclusion guard",
            exchange_aggregator_exclusion_result.returncode == 0,
            exchange_aggregator_exclusion_result.stderr.strip(),
        )
    )

    exchange_aggregator_classifier_code = """
from sniper_engine.exchange_aggregator import classify_market_flow_effect, score_exchange_aggregator_candidate

infra = score_exchange_aggregator_candidate({
    'shared_across_tokens': 8,
    'paired_custody_structure': True,
})
assert infra['classification'] == 'exchange_aggregator_suspect', infra
assert infra['has_mechanism_fingerprint'] is True, infra
assert infra['exclude_from_cohort'] is True, infra
assert infra['action'] == 'manual_confirm_then_allowlist', infra

allowlist_empty_structural = score_exchange_aggregator_candidate({
    'shared_across_tokens': 12,
    'paired_custody_structure': True,
    'shared_binance_wallet_router': True,
})
assert allowlist_empty_structural['classification'] == 'exchange_aggregator_suspect', allowlist_empty_structural
assert allowlist_empty_structural['signals'] == ['cross_token_reuse', 'paired_custody_structure', 'shared_binance_wallet_router'], allowlist_empty_structural

mm_like = score_exchange_aggregator_candidate({
    'bidirectional_high_frequency_net_flat': True,
    'contract_direct_pool_non_terminal': True,
})
assert mm_like['classification'] == 'mm_or_project_suspect', mm_like
assert mm_like['has_mechanism_fingerprint'] is False, mm_like
assert mm_like['exclude_from_cohort'] is False, mm_like

weak = score_exchange_aggregator_candidate({'shared_across_tokens': 2})
assert weak['classification'] == 'unknown', weak

sell = classify_market_flow_effect('exchange_aggregator', confirmed_dex_sell=True)
assert sell['market_effect'] == 'bearish_confirmed_dex_sell', sell
assert sell['action'] == 'keep_bearish_signal', sell

rebalance = classify_market_flow_effect('exchange_aggregator')
assert rebalance['market_effect'] == 'exchange_rebalance_reference', rebalance
assert rebalance['cohort_effect'] == 'exclude_from_cohort', rebalance

project = classify_market_flow_effect('mm_or_project_suspect')
assert project['market_effect'] == 'transfer_only_neutral_watch', project
assert project['action'] == 'trace_next_hop_before_sell_claim', project
"""
    exchange_aggregator_classifier_result = subprocess.run(
        [sys.executable, "-c", exchange_aggregator_classifier_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange aggregator mechanism classifier guard",
            exchange_aggregator_classifier_result.returncode == 0,
            exchange_aggregator_classifier_result.stderr.strip(),
        )
    )

    alpha_aggregator_trace_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
token = '0x' + 'a' * 40
quote = '0x' + 'b' * 40
router = '0x' + 'c' * 40
stable = '0x' + '1' * 40
alt = '0x' + '2' * 40
user = '0x' + '3' * 40
pool = '0x' + '4' * 40
usdc = '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d'

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    main = {
        'transfers': [
            {'token': quote, 'from': user, 'to': stable, 'amount': '100'},
            {'token': quote, 'from': stable, 'to': router, 'amount': '100'},
            {'token': usdc, 'from': user, 'to': stable, 'amount': '50'},
            {'token': usdc, 'from': stable, 'to': router, 'amount': '50'},
            {'token': usdc, 'from': router, 'to': pool, 'amount': '50'},
            {'token': token, 'from': pool, 'to': alt, 'amount': '1000'},
            {'token': token, 'from': alt, 'to': user, 'amount': '1000'},
        ],
        'calls': [
            {'from': stable, 'to': router},
            {'from': alt, 'to': router},
            {'from': router, 'to': pool},
        ],
    }
    main_path = tmp_path / 'trace_main.json'
    main_path.write_text(json.dumps(main), encoding='utf-8')
    history_paths = []
    for idx in range(6):
        hist_token = '0x' + format(idx + 10, '040x')
        hist = {
            'transfers': [
                {'token': hist_token, 'from': pool, 'to': alt, 'amount': '1'},
                {'token': hist_token, 'from': alt, 'to': user, 'amount': '1'},
            ],
            'calls': [{'from': alt, 'to': router}],
        }
        path = tmp_path / f'history_{idx}.json'
        path.write_text(json.dumps(hist), encoding='utf-8')
        history_paths.append(path)
    cmd = [
        sys.executable,
        str(root / 'scripts' / 'verify_alpha_aggregator_trace.py'),
        '--input',
        str(main_path),
        '--token',
        'auto',
        '--quote',
        quote,
        '--router',
        router,
        '--history',
        *[str(path) for path in history_paths],
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['dry_run'] is True and report['config_write'] is False, report
    assert report['manual_review_required'] is True, report
    assert report['token'] == token, report
    assert report['quote'] == quote, report
    assert report['trace_quality']['distinct_alpha_tokens'] >= 3, report['trace_quality']
    assert report['trace_quality']['warnings'] == [], report['trace_quality']
    assert report['leg_summary']['user_quote_to_stable_custody'] == 1, report['leg_summary']
    assert report['leg_summary']['quote_custody_to_router'] == 1, report['leg_summary']
    assert report['leg_summary']['token_router_or_pool_leg'] == 1, report['leg_summary']
    assert report['leg_summary']['alt_custody_token_out'] == 1, report['leg_summary']
    assert pool in report['roles']['pool_or_external_candidates'], report['roles']
    assert pool not in report['roles']['alt_custody_candidates'], report['roles']
    candidates = {row['address']: row for row in report['candidates']}
    assert router in candidates, candidates
    assert candidates[router]['classification'] == 'exchange_aggregator_suspect', candidates[router]
    assert candidates[alt]['classification'] == 'exchange_aggregator_suspect', candidates[alt]
    assert candidates[alt]['shared_across_tokens'] >= 5, candidates[alt]
"""
    alpha_aggregator_trace_result = subprocess.run(
        [sys.executable, "-c", alpha_aggregator_trace_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha aggregator trace dry-run verifier",
            alpha_aggregator_trace_result.returncode == 0,
            alpha_aggregator_trace_result.stderr.strip() or alpha_aggregator_trace_result.stdout.strip(),
        )
    )

    trace_bundle_collector_code = """
from scripts.collect_alpha_trace_bundle import (
    build_bundle,
    call_edges_from_call_tracer,
    call_edges_from_trace_transaction,
    parse_transfer_logs,
)

tx_hash = '0x' + 'a' * 64
token = '0x' + '1' * 40
sender = '0x' + '2' * 40
recipient = '0x' + '3' * 40
router = '0x' + '4' * 40
pool = '0x' + '5' * 40

def topic(address):
    return '0x' + ('0' * 24) + address[2:]

receipt = {
    'blockNumber': '0x7b',
    'transactionIndex': '0x5',
    'status': '0x1',
    'from': sender,
    'to': router,
    'gasUsed': '0x5208',
    'effectiveGasPrice': '0x3b9aca00',
    'logs': [
        {
            'address': token,
            'topics': [
                '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
                topic(sender),
                topic(recipient),
            ],
            'data': '0x' + hex(1000)[2:].rjust(64, '0'),
            'logIndex': '0x0',
        }
    ],
}
tx = {'hash': tx_hash, 'blockNumber': '0x7b', 'transactionIndex': '0x5', 'from': sender, 'to': router, 'value': '0x0', 'input': '0x1234'}
transfers = parse_transfer_logs(receipt, tx_hash)
assert len(transfers) == 1, transfers
assert transfers[0]['token'] == token and transfers[0]['from'] == sender and transfers[0]['to'] == recipient, transfers
assert transfers[0]['amount'] == '1000', transfers

trace = {'from': sender, 'to': router, 'type': 'CALL', 'calls': [{'from': router, 'to': pool, 'type': 'CALL'}]}
call_edges = call_edges_from_call_tracer(trace)
assert len(call_edges) == 2 and call_edges[0]['source'] == 'debug_callTracer', call_edges
parity_edges = call_edges_from_trace_transaction([{'type': 'call', 'action': {'from': router, 'to': pool, 'callType': 'call', 'value': '0x0'}}])
assert len(parity_edges) == 1 and parity_edges[0]['source'] == 'trace_transaction', parity_edges

bundle = build_bundle('bsc', tx_hash, tx, receipt, include_debug=False)
assert bundle['schema'] == 'alpha_trace_bundle.v1', bundle
assert bundle['receipt_summary']['block_number'] == 123, bundle
assert bundle['receipt_summary']['tx_index'] == 5, bundle
assert bundle['transfers'][0]['amount'] == '1000', bundle
assert bundle['calls'] == [], bundle
assert bundle['trace_meta']['debug_requested'] is False, bundle
"""
    trace_bundle_collector_result = subprocess.run(
        [sys.executable, "-c", trace_bundle_collector_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha trace bundle collector guard",
            trace_bundle_collector_result.returncode == 0,
            trace_bundle_collector_result.stderr.strip() or trace_bundle_collector_result.stdout.strip(),
        )
    )

    alpha_swap_sample_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
quote = '0x55d398326f99059ff775485246999027b3197955'
proxy = '0x73d8bd54f7cf5fab43fe4ef40a62d390644946db'
router = '0x6aba0315493b7e6989041c91181337b662fb1b90'
dex_router = '0xb300000b72deaeb607a12d5f54773d1c19c7028d'
user = '0x' + '1' * 40
pool = '0x' + '2' * 40

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    bundle_dir = tmp_path / 'bundles'
    out_dir = tmp_path / 'review'
    bundle_dir.mkdir()
    for idx in range(3):
        token = '0x' + format(idx + 100, '040x')
        payload = {
            'schema': 'alpha_trace_bundle.v1',
            'chain': 'bsc',
            'tx_hash': '0x' + format(idx + 1, '064x'),
            'transaction': {'from': user, 'to': router},
            'receipt_summary': {'from': user, 'to': router, 'status': 1, 'block_number': 100 + idx, 'tx_index': idx},
            'trace_meta': {'debug_traceTransaction': 'error', 'trace_transaction': 'error'},
            'transfers': [
                {'token': token, 'from': proxy, 'to': router, 'amount': '1000'},
                {'token': token, 'from': router, 'to': dex_router, 'amount': '1000'},
                {'token': token, 'from': dex_router, 'to': pool, 'amount': '1000'},
                {'token': quote, 'from': pool, 'to': dex_router, 'amount': '500'},
                {'token': quote, 'from': dex_router, 'to': router, 'amount': '500'},
            ],
        }
        (bundle_dir / f'bundle_{idx}.json').write_text(json.dumps(payload), encoding='utf-8')
    cmd = [
        sys.executable,
        str(root / 'scripts' / 'review_alpha_swap_samples.py'),
        '--bundle-dir',
        str(bundle_dir),
        '--out-dir',
        str(out_dir),
        '--address',
        proxy,
        '--address',
        router,
        '--address',
        dex_router,
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
    assert report['sample_count'] == 3, report
    assert report['distinct_alpha_tokens'] == 3, report
    rows = {row['address']: row for row in report['reviews']}
    assert rows[router]['recommendation'] == 'exchange_aggregator_suspect_candidate', rows[router]
    assert rows[router]['tx_to_distinct_alpha_tokens'] == 3, rows[router]
    assert rows[router]['configured_class'] in {'exchange_aggregator', 'exchange_aggregator_suspect'}, rows[router]
    if rows[router]['configured_class'] == 'exchange_aggregator':
        assert rows[router]['needs_full_trace_before_promotion'] is False, rows[router]
    else:
        assert rows[router]['needs_full_trace_before_promotion'] is True, rows[router]
    assert rows[proxy]['transfer_distinct_alpha_tokens'] == 3, rows[proxy]
    assert rows[dex_router]['configured_class'] == 'dex_router', rows[dex_router]
    assert rows[dex_router]['needs_full_trace_before_promotion'] is False, rows[dex_router]
    assert report['label_proposals'] == [], report['label_proposals']
    assert (out_dir / 'latest.md').exists(), result.stdout

    unknown_router = '0x' + '9' * 40
    proposed = {
        'address': unknown_router,
        'configured_class': '',
        'recommendation': 'exchange_aggregator_suspect_candidate',
        'tx_to_distinct_alpha_tokens': 3,
    }
    from scripts.review_alpha_swap_samples import label_proposal
    proposal = label_proposal(proposed)
    assert proposal['address'] == unknown_router, proposal
    assert proposal['class'] == 'exchange_aggregator_suspect', proposal
"""
    alpha_swap_sample_review_result = subprocess.run(
        [sys.executable, "-c", alpha_swap_sample_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha swap sample batch reviewer",
            alpha_swap_sample_review_result.returncode == 0,
            alpha_swap_sample_review_result.stderr.strip() or alpha_swap_sample_review_result.stdout.strip(),
        )
    )

    alpha_swap_tx_review_code = """
import json
import tempfile
from pathlib import Path

from scripts import review_alpha_swap_txs as module
from scripts.collect_alpha_trace_bundle import tx_hashes_from_args

quote = '0x55d398326f99059ff775485246999027b3197955'
proxy = '0x73d8bd54f7cf5fab43fe4ef40a62d390644946db'
router = '0x6aba0315493b7e6989041c91181337b662fb1b90'
dex_router = '0xb300000b72deaeb607a12d5f54773d1c19c7028d'
pool = '0x' + '2' * 40
user = '0x' + '3' * 40

def topic(address):
    return '0x' + ('0' * 24) + address[2:]

def slot(value):
    return hex(int(value))[2:].rjust(64, '0')

def transfer_log(token, from_addr, to_addr, amount, index):
    return {
        'address': token,
        'topics': [
            '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
            topic(from_addr),
            topic(to_addr),
        ],
        'data': '0x' + slot(amount),
        'logIndex': hex(index),
    }

tx_hashes = ['0x' + format(i + 1, '064x') for i in range(3)]

def fake_rpc_call(chain, method, params):
    tx_hash = params[0]
    idx = tx_hashes.index(tx_hash)
    return {
        'hash': tx_hash,
        'blockNumber': hex(200 + idx),
        'transactionIndex': hex(idx),
        'from': user,
        'to': router,
        'value': '0x0',
        'gas': '0x5208',
        'gasPrice': '0x1',
        'input': '0x',
    }

def fake_receipt(chain, tx_hash):
    idx = tx_hashes.index(tx_hash)
    token = '0x' + format(idx + 500, '040x')
    return {
        'blockNumber': hex(200 + idx),
        'transactionIndex': hex(idx),
        'status': '0x1',
        'from': user,
        'to': router,
        'gasUsed': '0x5208',
        'effectiveGasPrice': '0x1',
        'logs': [
            transfer_log(token, proxy, router, 1000, 0),
            transfer_log(token, router, dex_router, 1000, 1),
            transfer_log(token, dex_router, pool, 1000, 2),
            transfer_log(quote, pool, dex_router, 500, 3),
            transfer_log(quote, dex_router, router, 500, 4),
        ],
    }

module.rpc_call = fake_rpc_call
module.get_transaction_receipt = fake_receipt
with tempfile.TemporaryDirectory() as tmp:
    out_dir = Path(tmp) / 'tx_review'
    tx_file = Path(tmp) / 'external_agent_report.md'
    tx_file.write_text(
        '| token | tx |\\n'
        f'| A | https://bscscan.com/tx/{tx_hashes[0]} |\\n'
        f'| B | `{tx_hashes[1]}` |\\n'
        f'| C | {tx_hashes[1]} duplicate |\\n',
        encoding='utf-8',
    )
    assert tx_hashes_from_args([], tx_file) == tx_hashes[:2]
    written = module.collect_bundles('bsc', tx_hashes, out_dir / 'bundles', include_debug=False)
    review = module.build_review('bsc', written, [proxy, router, dex_router], quote, 3)
    json_path, md_path = module.write_review(review, out_dir / 'review')
    assert json_path.exists() and md_path.exists(), (json_path, md_path)
    assert review['sample_count'] == 3, review
    assert review['distinct_alpha_tokens'] == 3, review
    rows = {row['address']: row for row in review['reviews']}
    assert rows[router]['recommendation'] == 'exchange_aggregator_suspect_candidate', rows[router]
    assert rows[dex_router]['configured_class'] == 'dex_router', rows[dex_router]
    assert rows[dex_router]['needs_full_trace_before_promotion'] is False, rows[dex_router]
"""
    alpha_swap_tx_review_result = subprocess.run(
        [sys.executable, "-c", alpha_swap_tx_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha swap tx collect-and-review wrapper",
            alpha_swap_tx_review_result.returncode == 0,
            alpha_swap_tx_review_result.stderr.strip() or alpha_swap_tx_review_result.stdout.strip(),
        )
    )

    telegram_collector_retry_code = """
import json
import os
import urllib.error
import scripts.telegram_signal_collector as module

assert (
    module.GET_UPDATES_ATTEMPTS * module.GET_UPDATES_TIMEOUT_SECONDS
    + module.GET_UPDATES_MAX_RETRY_DELAY_SECONDS
) < 90
server_run_source = open('scripts/server_run_once.sh', encoding='utf-8').read()
assert 'TELEGRAM_COLLECTOR_TIMEOUT_SECONDS:-90' in server_run_source, server_run_source

calls = []
sleeps = []
def flaky_get_updates(token, method, payload=None, timeout_seconds=20):
    calls.append((method, payload, timeout_seconds))
    if len(calls) == 1:
        raise TimeoutError('fixture read timeout')
    return {'ok': True, 'result': [{'update_id': 7}]}
module.telegram_api = flaky_get_updates
module.time.sleep = sleeps.append
updates = module.get_updates('fixture-token', 42)
assert updates == [{'update_id': 7}], updates
assert len(calls) == 2 and all(row[0] == 'getUpdates' for row in calls), calls
assert all(row[1]['offset'] == 42 and row[2] == module.GET_UPDATES_TIMEOUT_SECONDS for row in calls), calls
assert sleeps == [1], sleeps

calls = []
def persistent_timeout(*args, **kwargs):
    calls.append(1)
    raise TimeoutError('fixture persistent timeout')
module.telegram_api = persistent_timeout
try:
    module.get_updates('fixture-token', 42)
except TimeoutError:
    pass
else:
    raise AssertionError('persistent getUpdates timeout must surface')
assert len(calls) == module.GET_UPDATES_ATTEMPTS, calls

http_503 = urllib.error.HTTPError('https://example.invalid', 503, 'fixture', {}, None)
http_401 = urllib.error.HTTPError('https://example.invalid', 401, 'fixture', {}, None)
assert module.get_updates_exception_retry_delay(http_503) == 1
assert module.get_updates_exception_retry_delay(http_401) is None
assert module.get_updates_response_retry_delay({'error_code': 429, 'parameters': {'retry_after': 5}}) == 5
assert module.get_updates_response_retry_delay({'error_code': 429, 'parameters': {'retry_after': 6}}) is None
assert module.get_updates_response_retry_delay({'error_code': 429, 'parameters': 'invalid'}) == 1
assert module.get_updates_response_retry_delay({'error_code': 409}) is None
assert module.get_updates_exception_retry_delay(json.JSONDecodeError('fixture', '', 0)) == 1

calls = []
def transient_http(*args, **kwargs):
    calls.append(1)
    if len(calls) == 1:
        raise urllib.error.HTTPError('https://example.invalid', 503, 'fixture', {}, None)
    return {'ok': True, 'result': []}
module.telegram_api = transient_http
assert module.get_updates('fixture-token', 42) == []
assert len(calls) == 2, calls

calls = []
def api_conflict(*args, **kwargs):
    calls.append(1)
    return {'ok': False, 'error_code': 409, 'description': 'fixture conflict'}
module.telegram_api = api_conflict
try:
    module.get_updates('fixture-token', 42)
except RuntimeError:
    pass
else:
    raise AssertionError('API 409 must fail without retry')
assert len(calls) == 1, calls

send_calls = []
def failed_send(*args, **kwargs):
    send_calls.append(1)
    raise TimeoutError('fixture send timeout')
module.telegram_api = failed_send
os.environ['DISABLE_TELEGRAM'] = '0'
try:
    module.send_message('fixture-token', 'fixture-chat', 'fixture')
except TimeoutError:
    pass
else:
    raise AssertionError('sendMessage timeout must surface without retry')
assert len(send_calls) == 1, send_calls
"""
    telegram_collector_retry_result = subprocess.run(
        [sys.executable, "-c", telegram_collector_retry_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "Telegram Bot getUpdates bounded retry keeps sendMessage single-shot",
            telegram_collector_retry_result.returncode == 0,
            telegram_collector_retry_result.stderr.strip(),
        )
    )

    symbol_refine_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal
from scripts.telegram_signal_collector import refine_symbol_from_chain

text = '''🟩 [BN Alpha] v4 新池子 Initialize
LP / USDT
PoolId: 0x3bca91b9b847cff6f4b666fa1d966981678975e13fd69d647bd11bed99f5fa14
tx: 0xd7c6c7b89917f39eb46f55b8f06b0f5ae892c546d3f2b0dbe116abfd0476ee18'''
parsed = parse_signal(text, Path('/tmp/cap_pool.txt'))
assert parsed['symbol'] in {'', 'UNKNOWN'}, parsed
parsed['chain_enrichment'] = [{
    'status': 'ok',
    'token0': {'symbol': 'USDT'},
    'token1': {'symbol': 'CAP'},
}]
refine_symbol_from_chain(parsed)
assert parsed['symbol'] == 'CAP', parsed
assert parsed['watchlist_proposal']['symbol'] == 'CAP', parsed['watchlist_proposal']
"""
    symbol_refine_result = subprocess.run(
        [sys.executable, "-c", symbol_refine_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal parser prefers chain token symbol over LP", symbol_refine_result.returncode == 0, symbol_refine_result.stderr.strip()))

    signal_message_code = """
from scripts.telegram_signal_collector import analysis_message

parsed = {
    'symbol': 'ARX',
    'priority': 'P0_DEEP_REVIEW',
    'title': 'BN Alpha new pool',
    'addresses': [{'address': '0x' + '1' * 40}],
    'txs': ['0x' + '2' * 64],
    'blocks': [123456],
    'pool_ids': ['0x' + '3' * 64],
    'prediction_urls': [],
    'prices': {'pool_price': '0.13'},
    'next_checks': ['official_contract', 'block_transaction_order', 'internal_transactions'],
    'project_registry': {'status': 'updated_project', 'added': ['交易']},
    'chain_enrichment': [
        {
            'status': 'ok',
            'block': 123456,
            'tx_index': 39,
            'token0': {'symbol': 'USDT'},
            'token1': {'symbol': 'ARX'},
            'price_summary': '1 ARX ≈ 0.13 USDT',
            'token_transfers': {'interpretation': '已归档'},
        }
    ],
}
text = analysis_message(parsed, False)
for forbidden in ['0x', 'txIndex', 'block 123456', 'tx_receipt', 'block_transaction_order', 'internal_transactions']:
    assert forbidden not in text, text
assert '有效总结:' in text and '细节已归档' in text and '看开盘块交易顺序' in text and '看贿赂和内部转账' in text, text
print(len(text))
"""
    signal_message_result = subprocess.run(
        [sys.executable, "-c", signal_message_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal analysis message hides machine ids", signal_message_result.returncode == 0, signal_message_result.stdout.strip() or signal_message_result.stderr.strip()))

    score_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sniper_score_local.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("local scoring script runs", score_result.returncode == 0, score_result.stderr.strip()))

    monitored_ok = False
    monitored_msg = ""
    try:
        monitored = json.loads((ROOT / "config" / "monitored_wallets.json").read_text(encoding="utf-8"))
        wallets = monitored.get("wallets", [])
        quote_tokens = {
            "0x55d398326f99059ff775485246999027b3197955": "USDT",
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": "WBNB",
            "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
        }
        quote_hits = [
            quote_tokens.get(str(row.get("token_contract", "")).lower(), "")
            for row in wallets
            if str(row.get("token_contract", "")).lower() in quote_tokens
        ]
        front_traced = [
            row for row in wallets
            if "o1_front_buyers_trace" in row.get("sources", [])
        ]
        monitored_ok = len(wallets) >= 32 and len(front_traced) >= 5 and not quote_hits
        monitored_msg = f"{len(wallets)} wallets, {len(front_traced)} front-trace linked, quote token hits={quote_hits}"
    except Exception as exc:
        monitored_msg = str(exc)
    checks.append(("monitored wallet config parses", monitored_ok, monitored_msg))

    snapshot_ok = False
    snapshot_msg = ""
    try:
        snapshot = json.loads((ROOT / "output" / "monitoring" / "latest_snapshot.json").read_text(encoding="utf-8"))
        disabled = set(snapshot.get("disabled_projects", []))
        if "O1" in disabled:
            snapshot_ok = "groups" in snapshot and "alerts" in snapshot and len(snapshot.get("wallets", [])) == 0
        else:
            snapshot_ok = len(snapshot.get("wallets", [])) >= 32 and "groups" in snapshot and "alerts" in snapshot
        snapshot_msg = f"{len(snapshot.get('wallets', []))} wallets, {len(snapshot.get('alerts', []))} alerts, disabled={sorted(disabled)}"
    except Exception as exc:
        snapshot_msg = str(exc)
    checks.append(("latest monitor snapshot parses", snapshot_ok, snapshot_msg))

    project_watch_ok = False
    project_watch_msg = ""
    try:
        project_watch = json.loads((ROOT / "output" / "alpha_project_watch" / "latest.json").read_text(encoding="utf-8"))
        projects = project_watch.get("projects", [])
        skipped = project_watch.get("skipped", [])
        project_watch_ok = (
            len(projects) >= 2
            and "alert_count" in project_watch
            and any(row.get("symbol") == "ARX" and row.get("reason") == "specialized_watch" for row in skipped)
            and all("spot_action" in row.get("analysis", {}) for row in projects)
            and all("perp_action" in row.get("analysis", {}) for row in projects)
        )
        project_watch_msg = f"{len(projects)} projects, alerts={project_watch.get('alert_count')}, skipped={skipped}"
    except Exception as exc:
        project_watch_msg = str(exc)
    checks.append(("alpha project watch parses", project_watch_ok, project_watch_msg))

    alpha_project_dedupe_ok = False
    alpha_project_dedupe_msg = ""
    alpha_project_dedupe_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_project_watch', root / 'scripts' / 'alpha_project_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base_alert = {
    'type': 'BALANCE_CHANGE',
    'symbol': 'CAP',
    'chain': 'bsc',
    'token': 'CAP',
    'token_address': '0x' + '1' * 40,
    'address': '0x' + '2' * 40,
    'role': 'event_distribution',
    'is_quote_balance': False,
    'level': 'HIGH',
}
small_a = dict(base_alert, delta='155738.9162')
small_b = dict(base_alert, delta='142284.6864')
large = dict(base_alert, delta='650000')
assert module.alert_keys([small_a]) == module.alert_keys([small_b]), (module.alert_keys([small_a]), module.alert_keys([small_b]))
assert module.alert_keys([small_a]) != module.alert_keys([large]), (module.alert_keys([small_a]), module.alert_keys([large]))
snapshot_a = {'projects': [{'symbol': 'CAP', 'analysis': {'spot_action': '观察', 'perp_action': '不开仓'}, 'alerts': [small_a]}]}
snapshot_b = {'projects': [{'symbol': 'CAP', 'analysis': {'spot_action': '观察', 'perp_action': '不开仓'}, 'alerts': [small_b]}]}
assert module.project_push_signature(snapshot_a) == module.project_push_signature(snapshot_b), (module.project_push_signature(snapshot_a), module.project_push_signature(snapshot_b))
compact_projects = [
    {'symbol': 'QUIET', 'priority': 'P0', 'analysis': {'conclusion': '安静', 'spot_action': '观察'}, 'alerts': []},
    {'symbol': 'LOWER', 'priority': 'P2', 'analysis': {'conclusion': '次要', 'spot_action': '观察'}, 'alerts': [{**small_a, 'symbol': 'LOWER', 'token': 'LOWER'}]},
    {'symbol': 'RISK', 'priority': 'P0', 'analysis': {'conclusion': '风险结论', 'spot_action': '减仓'}, 'alerts': [{**large, 'symbol': 'RISK', 'token': 'RISK', 'level': 'CRITICAL'}]},
    {'symbol': 'WATCH', 'priority': 'P1', 'analysis': {'conclusion': '观察结论', 'spot_action': '等待'}, 'alerts': [{**small_a, 'symbol': 'WATCH', 'token': 'WATCH'}]},
]
compact_text = module.telegram_text({'alert_count': 3, 'new_alert_count': 1, 'projects': compact_projects})
assert compact_text.startswith('Alpha项目｜新增1｜触发3'), compact_text
assert 'RISK P0' in compact_text and 'WATCH P1' in compact_text, compact_text
assert 'CRITICAL RISK流入650K' in compact_text, compact_text
assert 'QUIET' not in compact_text and 'LOWER P2' not in compact_text, compact_text
assert compact_text.count('动作：') == 2 and '另有1项｜详情已归档' in compact_text, compact_text
assert '有效总结' not in compact_text and '0x' not in compact_text, compact_text
assert len(compact_text) <= 600 and len(compact_text.splitlines()) <= 8, (len(compact_text), compact_text)
lower_key = module.alert_keys(compact_projects[1]['alerts'])[0]
new_first_text = module.telegram_text({
    'alert_count': 3,
    'new_alert_count': 1,
    '_telegram_new_alert_keys': [lower_key],
    'projects': compact_projects,
})
assert 'LOWER P2' in new_first_text and 'RISK P0' in new_first_text and 'WATCH P1' not in new_first_text, new_first_text
old_critical = {**large, 'symbol': 'MIX', 'token': 'OLD', 'level': 'CRITICAL'}
new_high = {**small_a, 'symbol': 'MIX', 'token': 'NEW', 'level': 'HIGH'}
mixed_project = {
    'symbol': 'MIX',
    'priority': 'P0',
    'analysis': {'conclusion': '混合告警', 'spot_action': '核查新增证据'},
    'alerts': [old_critical, new_high],
}
new_evidence_text = module.telegram_text({
    'alert_count': 2,
    'new_alert_count': 1,
    '_telegram_new_alert_keys': module.alert_keys([new_high]),
    'projects': [mixed_project],
})
assert '🔴 MIX P0｜HIGH NEW流入156K｜另1条' in new_evidence_text, new_evidence_text
assert module.telegram_compact_amount('0.002') == '0.002', module.telegram_compact_amount('0.002')
print(module.alert_keys([small_a])[0])
"""
    alpha_project_dedupe = subprocess.run(
        [sys.executable, "-c", alpha_project_dedupe_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_project_dedupe_ok = alpha_project_dedupe.returncode == 0
    alpha_project_dedupe_msg = alpha_project_dedupe.stdout.strip() or alpha_project_dedupe.stderr.strip()
    checks.append(("alpha project watch alert dedupe buckets", alpha_project_dedupe_ok, alpha_project_dedupe_msg))

    alpha_opening_ok = False
    alpha_opening_msg = ""
    try:
        alpha_opening = json.loads((ROOT / "output" / "alpha_opening_block_watch" / "latest.json").read_text(encoding="utf-8"))
        events = alpha_opening.get("events", [])
        opened_events = [event for event in events if event.get("status") == "opened"]
        alpha_opening_ok = bool(
            "event_count" in alpha_opening
            and all("spot_action" in event.get("analysis", {}) for event in events)
            and all("perp_action" in event.get("analysis", {}) for event in events)
            and all("direction" in event.get("analysis", {}) for event in events)
            and all("trade_signal" in event.get("analysis", {}) for event in events)
            and all("cohort_status_summary" in event.get("analysis", {}) for event in opened_events)
        )
        alpha_opening_msg = f"events={len(events)}, opened={len(opened_events)}, alerts={alpha_opening.get('alert_count')}"
    except Exception as exc:
        alpha_opening_msg = str(exc)
    checks.append(("generic alpha opening watch parses", alpha_opening_ok, alpha_opening_msg))

    alpha_opening_telegram_ok = False
    alpha_opening_telegram_msg = ""
    alpha_opening_telegram_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_opening_block_watch', root / 'scripts' / 'alpha_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'alpha_opening_block_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'opening_block', 'scan_to_block']:
    assert forbidden not in text, text
assert text.startswith('Alpha开盘｜新增'), text
assert module.telegram_compact_amount('0.002') == '0.002', module.telegram_compact_amount('0.002')
assert '有效总结:' not in text and '合约动作:' not in text and '仓位口径:' not in text, text
active = [event for event in snapshot.get('events', []) if module.event_alert_keys(event)]
assert text.count('动作：') == min(2, len(active)), text
if active:
    assert '详情已归档' in text, text
else:
    assert '触发0' in text, text
assert len(text) <= 700 and len(text.splitlines()) <= 8, (len(text), text)
print(len(text))
"""
    alpha_opening_telegram = subprocess.run(
        [sys.executable, "-c", alpha_opening_telegram_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_opening_telegram_ok = alpha_opening_telegram.returncode == 0
    alpha_opening_telegram_msg = alpha_opening_telegram.stdout.strip() or alpha_opening_telegram.stderr.strip()
    checks.append(("generic alpha opening Telegram output is concise", alpha_opening_telegram_ok, alpha_opening_telegram_msg))

    alpha_opening_trade_rules_ok = False
    alpha_opening_trade_rules_msg = ""
    alpha_opening_trade_rules_code = """
import importlib.util
import os
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_opening_block_watch', root / 'scripts' / 'alpha_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
event = {
    'symbol': 'TEST',
    'quote': {'symbol': 'USDT'},
    'market_context': {
        'snipe_400k_avg_usdt': '0.15',
        'snipe_400k_end_price_usdt': '0.22',
    },
    'initial_price': '0.11',
}
base = {
    'token_bought': '100000',
    'spent_quote': '12000',
    'largest_internal_native': {'amount': '0'},
}
follow = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'held_or_accumulated'})])
project_quote_in = module.analyze_opened(
    {**event, 'liquidity_flow': {'risk': 'project_quote_in', 'summary': '收到 12000 USDT'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
lp_remove = module.analyze_opened(
    {**event, 'liquidity_flow': {'risk': 'lp_remove', 'summary': 'LP减池/撤流动性 1 次'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
transfer_unknown = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'mostly_exited_or_transferred'})])
cex_transfer = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'out_destination_classes': 'cex_deposit', 'confirmed_sell_quote_received': '0'})])
sell_confirmed = module.analyze_opened(event, [
    dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'confirmed_sell_quote_received': '6000', 'current_balance': '0', 'out_after_buy': '100000'}),
    dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'confirmed_sell_quote_received': '6000', 'current_balance': '0', 'out_after_buy': '100000'}),
])
untraced_exit = module.analyze_opened(event, [
    dict(base, buyer_trace={'status': 'mostly_exited_untraced', 'current_balance': '0', 'out_after_buy': '0'}),
])
hot = module.analyze_opened(event, [dict(base, token_bought='1000000', spent_quote='400000', largest_internal_native={'amount': '65'}, buyer_trace={'status': 'held_or_accumulated'})])
old_static_safety = module.inspect_token_contract_safety
module.inspect_token_contract_safety = lambda event: {'status': 'static-ok', 'gate': 'static_check_passed', 'detail': ''}
suspect_buyer_event = {
    **event,
    'chain': 'bsc',
    'token': {'address': '0x' + 'd' * 40, 'decimals': 18},
    'quote': {'address': '0x' + 'e' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {
        **event['market_context'],
        'mm_or_project_suspect_addresses': ['0x' + '8' * 40],
    },
}
suspect_hold = module.analyze_opened(
    suspect_buyer_event,
    [dict(base, buyer='0x' + '8' * 40, buyer_trace={'status': 'held_or_accumulated'})],
)
alpha_dominant_hold = module.analyze_opened(
    {**event, 'market_context': {**event['market_context'], 'venue_class': 'ALPHA_DOMINANT'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
module.inspect_token_contract_safety = old_static_safety
assert '可售性未完整验证' in follow['trade_signal'], follow
assert '不跟' in project_quote_in['trade_signal'], project_quote_in
assert project_quote_in['liquidity_flow_risk'] == 'project_quote_in', project_quote_in
assert '卖出/减仓' in lp_remove['trade_signal'], lp_remove
assert lp_remove['liquidity_flow_risk'] == 'lp_remove', lp_remove
assert '不跟' in transfer_unknown['trade_signal'], transfer_unknown
assert '不跟' in cex_transfer['trade_signal'], cex_transfer
assert 'cex_deposit' in cex_transfer['buyer_trace_summary'], cex_transfer
assert cex_transfer['cohort_confirmed_sell_quote'] == '0', cex_transfer
assert '卖出/减仓' in sell_confirmed['trade_signal'], sell_confirmed
assert '不跟' in untraced_exit['trade_signal'], untraced_exit
assert '余额接近0' in untraced_exit['buyer_trace_summary'], untraced_exit
assert untraced_exit['cohort_net_out_pct'] == '100', untraced_exit
assert '不追' in hot['trade_signal'], hot
assert '偏多' not in suspect_hold['direction'], suspect_hold
assert '聪明钱承接' in suspect_hold['conclusion'], suspect_hold
assert suspect_hold['buyer_caution_reason'] == '买家为项目/MM/聚合器嫌疑地址', suspect_hold
assert '偏多' not in alpha_dominant_hold['direction'], alpha_dominant_hold
assert alpha_dominant_hold['onchain_netflow_reliable'] == 'False', alpha_dominant_hold
assert 'Alpha主导净流未认证' in alpha_dominant_hold['buyer_caution_reason'], alpha_dominant_hold
assert sell_confirmed['cohort_confirmed_sell_quote'] == '12000', sell_confirmed
assert sell_confirmed['total_spent_quote'] == '24000', sell_confirmed
assert sell_confirmed['current_cohort_quote_est'] == '0', sell_confirmed
assert sell_confirmed['cohort_net_out_pct'] == '100', sell_confirmed
assert '首批历史开盘买入 24000.0000 USDT（非当前持仓）' in sell_confirmed['cohort_status_summary'], sell_confirmed
assert '按首批成本约 0 USDT' in sell_confirmed['cohort_status_summary'], sell_confirmed
assert '当前仍在原买入钱包' in sell_confirmed['cohort_status_summary'], sell_confirmed
opened_event = {
    **event,
    'status': 'opened',
    'opening_block': 123,
    'analysis': {**hot, 'buyer_trace_summary': '已追踪2个首批买家；截至区块999'},
    'rows': [dict(base, tx='0xabc', buyer='0x' + '1' * 40, buyer_trace={'status': 'held_or_accumulated', 'out_after_buy': '0'})],
}
keys = module.event_alert_keys(opened_event)
assert not any('截至区块' in key for key in keys), keys
trade_key = next(key for key in keys if key.startswith('trade_signal|TEST|'))
legacy_seen = {'trade_signal|TEST|' + hot['trade_signal'] + '|已追踪2个首批买家；截至区块998'}
assert module.alert_key_seen(trade_key, legacy_seen), trade_key
classified_event = {
    'symbol': 'TEST',
    'chain': 'bsc',
    'token': {'address': '0x' + 'd' * 40, 'decimals': 18},
    'quote': {'address': '0x' + 'e' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {
        'cex_deposit_addresses': ['0x' + 'c' * 40],
        'cex_hot_wallet_addresses': ['0x' + '4' * 40],
        'exchange_rebalance_addresses': ['0x' + '7' * 40],
        'mm_or_project_suspect_addresses': ['0x' + '8' * 40],
        'bridge_addresses': ['0x' + '2' * 40],
        'neutral_contracts': [{'address': '0x' + 'f' * 40}],
        'locker_addresses': [{'address': '0x' + '3' * 40}],
    },
}
assert module.destination_class(classified_event, '0x' + 'c' * 40) == 'cex_deposit'
assert module.destination_class(classified_event, '0x' + '4' * 40) == 'cex_deposit'
assert module.destination_class(classified_event, '0x' + '7' * 40) == 'exchange_rebalance'
assert module.destination_class(classified_event, '0x' + '8' * 40) == 'mm_or_project_suspect'
assert module.destination_class(classified_event, '0x' + '2' * 40) == 'bridge'
assert module.destination_class(classified_event, '0x' + '3' * 40) == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x' + 'f' * 40) == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x46a15b0b27311cedf172ab29e4f4766fbe7f4364') == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x1b81d678ffb9c0263b24a97847620c99d213eb14') == 'dex_router'
assert '0x238a358808379702088667322f80ac48bad5e6c4' in module.excluded_addresses(classified_event)
known_est_event = {**classified_event, 'known_txs': [{'tx': '0x' + 'a' * 64, 'estimated_spent_quote': '400200'}]}
assert module.known_tx_estimated_spent_quote(known_est_event, '0x' + 'a' * 64) == module.Decimal('400200')
known_est_analysis = module.analyze_opened(
    event,
    [dict(base, spent_quote='0', estimated_spent_quote='400200', buyer_trace={'status': 'held_or_accumulated'})],
)
assert known_est_analysis['total_spent_quote'] == '400200', known_est_analysis
old_has_contract_code = module.has_contract_code
module.has_contract_code = lambda chain, address: address == '0x' + '5' * 40
assert module.destination_class(classified_event, '0x' + '5' * 40) == 'unknown_contract_pending_bearish'
module.has_contract_code = old_has_contract_code
assert module.trace_start_block(100, 105, 50, 0, False) == 100
assert module.trace_start_block(100, 1000, 50, 0, False) == 950
assert module.trace_start_block(100, 1000, 50, 1200, True) == 100
assert module.trace_start_block(100, 2000, 50, 1200, True) == 1950
module.CONTRACT_SAFETY_CACHE.clear()
module.contract_code = lambda chain, address: '0x' + module.OWNER_SELECTORS['owner'][2:] + module.BOOL_RISK_SELECTORS['paused'][2:]

def fake_static_call(chain, address, selector):
    if selector == module.OWNER_SELECTORS['owner']:
        return '0x' + ('0' * 24) + ('1' * 40)
    if selector == module.BOOL_RISK_SELECTORS['paused']:
        return '0x' + '0' * 64
    return '0x'

module.optional_eth_call = fake_static_call
contract_warning = module.inspect_token_contract_safety(classified_event)
assert contract_warning['gate'] == 'blocked_contract_controls_unverified', contract_warning

def fake_paused_call(chain, address, selector):
    if selector == module.BOOL_RISK_SELECTORS['paused']:
        return '0x' + '0' * 63 + '1'
    return '0x'

module.CONTRACT_SAFETY_CACHE.clear()
module.optional_eth_call = fake_paused_call
contract_blocked = module.inspect_token_contract_safety(classified_event)
assert contract_blocked['gate'] == 'blocked_static_contract_risk', contract_blocked
assert module.alert_amount_bucket(module.Decimal('19999.99'), module.Decimal('10000')) == '10000'
new_trace_key = 'trace|TEST|0x' + ('1' * 40) + '|partially_moved|eoa_or_unlabeled|10000'
old_trace_key = 'trace|TEST|0x' + ('1' * 40) + '|partially_moved|eoa_or_unlabeled|0'
assert module.alert_key_seen(new_trace_key, {old_trace_key}), new_trace_key

def slot(value):
    return hex(int(value) % (2 ** 256))[2:].rjust(64, '0')

lp_log = {
    'address': '0x46a15b0b27311cedf172ab29e4f4766fbe7f4364',
    'topics': [module.DECREASE_LIQUIDITY_TOPIC, '0x' + '0' * 63 + '1'],
    'data': '0x' + slot(100) + slot(200) + slot(300),
    'transactionHash': '0xlp',
    'blockNumber': '0x1',
    'logIndex': '0x0',
}
lp_row = module.liquidity_event_row(lp_log, {'label': 'position manager', 'role': 'lp_position_manager'})
assert lp_row['event'] == 'DecreaseLiquidity' and lp_row['direction'] == 'remove', lp_row

buyer = '0x' + 'a' * 40
recipient = '0x' + 'b' * 40
router = '0x' + '9' * 40

def make_log(address, from_addr, to_addr, amount, tx='0xnext', block=12, idx=1):
    return {
        'address': address,
        'topics': [module.TRANSFER_TOPIC, module.address_topic(from_addr), module.address_topic(to_addr)],
        'data': hex(int(module.Decimal(str(amount)) * (module.Decimal(10) ** 18))),
        'transactionHash': tx,
        'blockNumber': hex(block),
        'logIndex': hex(idx),
    }

module.has_contract_code = lambda chain, address: False
module.get_logs_quick = lambda *args, **kwargs: [make_log(classified_event['token']['address'], recipient, router, '1000')]

def fake_quick_rpc_call(chain, method, params, timeout):
    tx_hash = params[0]
    if tx_hash == '0xnext':
        return {'logs': [make_log(classified_event['quote']['address'], router, recipient, '500', tx='0xnext', block=12, idx=2)]}
    return {'logs': []}

module.quick_rpc_call = fake_quick_rpc_call
classified = module.classify_outgoing_tx(
    classified_event,
    buyer,
    '0xorig',
    [{'to': recipient, 'block': 11, 'tx': '0xorig', 'log_index': 1, 'amount': module.Decimal('1000')}],
    20,
)
assert classified['quote_received'] == module.Decimal('500'), classified
assert 'next_hop_dex_sell_to_quote' in classified['classes'], classified
def fake_transfer_ok(chain, method, params, timeout):
    return '0x' + '0' * 63 + '1'

module.quick_rpc_call = fake_transfer_ok
safe = module.simulate_transfer_safety(classified_event, buyer, module.Decimal('10'))
assert safe['status'] == 'transfer_verified', safe
quote_payload = module.encode_quoter_v3_exact_input_single(classified_event['token']['address'], classified_event['quote']['address'], 10 ** 18, 100)
assert quote_payload.startswith(module.QUOTE_EXACT_INPUT_SINGLE_SELECTOR), quote_payload

def fake_transfer_blocked(chain, method, params, timeout):
    raise RuntimeError('execution reverted')

module.quick_rpc_call = fake_transfer_blocked
blocked = module.simulate_transfer_safety(classified_event, buyer, module.Decimal('10'))
assert blocked['status'] == 'blocked', blocked

def fake_quote_ok(chain, method, params, timeout):
    return '0x' + hex(123 * 10 ** 18)[2:].rjust(64, '0') + '0' * 64 * 3

module.quick_rpc_call = fake_quote_ok
quote_ok = module.simulate_dex_quote_safety(classified_event, module.Decimal('10'))
assert quote_ok['status'] == 'dex_quote_verified', quote_ok
combined_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'transfer_safety_detail': 'probe_amount=1', 'dex_quote_status': 'dex_quote_verified', 'dex_quote_detail': 'fee=100'}}
])
assert combined_safety['gate'] == 'blocked_tax_unverified', combined_safety
infinity_event = {
    **classified_event,
    'pool_id': '0x' + '2' * 64,
    'hook': module.ZERO,
    'fee': '100',
    'parameters': '0x' + '0' * 64,
}
pool_key = module.infinity_pool_key(infinity_event)
assert pool_key['status'] == 'ok' and pool_key['zero_for_one'] is True, pool_key
infinity_payload = module.encode_infinity_cl_quote_exact_input_single(pool_key, 10 ** 18)
assert infinity_payload.startswith(module.PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR), infinity_payload
assert len(infinity_payload) == 2 + 8 + 64 * 11, len(infinity_payload)
old_infinity_router_probe = os.environ.pop('ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE', None)
try:
    infinity_router_skip = module.simulate_router_sell_safety(infinity_event, buyer, module.Decimal('10'))
    assert infinity_router_skip['status'] == 'unverified' and 'infinity_router' in infinity_router_skip['detail'], infinity_router_skip
finally:
    if old_infinity_router_probe is not None:
        os.environ['ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE'] = old_infinity_router_probe

def fake_infinity_quote(chain, method, params, timeout):
    assert params[0]['to'] == module.PANCAKE_INFINITY_CL_QUOTER, params
    assert params[0]['data'].startswith(module.PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR), params
    return '0x' + hex(321 * 10 ** 18)[2:].rjust(64, '0') + hex(999)[2:].rjust(64, '0')

module.quick_rpc_call = fake_infinity_quote
infinity_quote_ok = module.simulate_infinity_cl_quote_safety(infinity_event, module.Decimal('10'))
assert infinity_quote_ok['status'] == 'infinity_cl_quote_verified', infinity_quote_ok
combined_infinity_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'dex_quote_status': 'infinity_cl_quote_verified', 'dex_quote_detail': infinity_quote_ok['detail']}}
])
assert combined_infinity_safety['gate'] == 'blocked_tax_unverified', combined_infinity_safety
assert 'Quoter不触发税费' in combined_infinity_safety['status'], combined_infinity_safety
combined_infinity_roundtrip_safety = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_eth_call_success_no_recovery_rate',
            'router_sell_detail': 'v4往返eth_call未revert: recovery_rate_unavailable',
        }
    }
])
assert combined_infinity_roundtrip_safety['gate'] == 'blocked_infinity_recovery_unverified', combined_infinity_roundtrip_safety
assert '回收率未验证' in combined_infinity_roundtrip_safety['status'], combined_infinity_roundtrip_safety
assert '执行门通过' not in combined_infinity_roundtrip_safety['status'], combined_infinity_roundtrip_safety
combined_infinity_low_recovery = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_low_recovery',
            'router_sell_detail': 'v4往返回收率≈50%',
        }
    }
])
assert combined_infinity_low_recovery['gate'] == 'blocked_infinity_low_recovery', combined_infinity_low_recovery
combined_infinity_recovery_verified = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_recovery_verified',
            'router_sell_detail': 'v4往返回收率≈99%',
        }
    }
])
assert combined_infinity_recovery_verified['gate'] == 'infinity_recovery_rate_verified_tax_uncertain', combined_infinity_recovery_verified
legacy_infinity_roundtrip_safety = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_eth_call_verified',
            'router_sell_detail': 'legacy status',
        }
    }
])
assert legacy_infinity_roundtrip_safety['gate'] == 'blocked_infinity_recovery_unverified', legacy_infinity_roundtrip_safety

def fake_quote_fail(chain, method, params, timeout):
    raise RuntimeError('execution reverted')

module.quick_rpc_call = fake_quote_fail
quote_failed = module.simulate_dex_quote_safety(classified_event, module.Decimal('10'))
assert quote_failed['status'] == 'quote_failed', quote_failed

module.BALANCE_SLOT_CACHE.clear()
module.ALLOWANCE_SLOT_CACHE.clear()
module.web3_keccak_word = lambda chain, raw_hex: '0x' + (raw_hex[-64:] if len(raw_hex) >= 64 else raw_hex.rjust(64, '0'))
module.raw_balance_of = lambda chain, token, holder: 10 ** 18
balance_key = module.mapping_storage_key(classified_event['chain'], buyer, 3)
module.storage_at = lambda chain, contract, key: hex(10 ** 18) if key == balance_key else '0x0'

def fake_router_sell(chain, method, params, timeout):
    if method == 'eth_call' and len(params) == 3 and params[0].get('to') == classified_event['token']['address']:
        data = params[0].get('data', '')
        if data.startswith('0x70a08231'):
            return '0x' + hex(10 ** 18)[2:].rjust(64, '0')
        if data.startswith('0xdd62ed3e'):
            return '0x' + ('f' * 64)
    if method == 'eth_call' and len(params) == 3 and params[0].get('to') == module.PANCAKE_V3_ROUTER:
        override = params[2]
        state_diff = override[classified_event['token']['address']]['stateDiff']
        assert state_diff, override
        return '0x' + hex(456 * 10 ** 18)[2:].rjust(64, '0')
    return '0x'

module.quick_rpc_call = fake_router_sell
router_ok = module.simulate_router_sell_safety(classified_event, buyer, module.Decimal('10'))
assert router_ok['status'] == 'router_sell_verified', router_ok
combined_router_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'dex_quote_status': 'dex_quote_verified', 'router_sell_status': 'router_sell_verified', 'router_sell_detail': 'router ok'}}
])
assert combined_router_safety['gate'] == 'router_sell_verified_tax_uncertain', combined_router_safety
assert '可售性' in module.telegram_text({'events': [{'symbol': 'TEST', 'priority': 'P0', 'status': 'opened', 'analysis': follow}]}), follow
small_sell_analysis = {
    **follow,
    'direction': '观察',
    'trade_signal': '观察',
    'cohort_confirmed_sell_quote': '1',
}
small_sell_event = {**event, 'symbol': 'SMALL', 'priority': 'P2', 'status': 'opened', 'analysis': small_sell_analysis}
assert module.telegram_event_rank(small_sell_event)[0] != 0, module.telegram_event_rank(small_sell_event)
assert '小额确认换出1 USDT/未达阈值' in module.telegram_text({'events': [small_sell_event]}), small_sell_event
static_limited = {
    **follow,
    'can_sell_gate': 'router_sell_verified_tax_uncertain',
    'sell_safety_status': '首批钱包可转出、DEX报价和Router卖出模拟均可用；合约权限/暂停能力未完整验证；禁止放大仓位',
}
static_text = module.telegram_text({'events': [{**event, 'symbol': 'STATIC', 'priority': 'P1', 'status': 'opened', 'analysis': static_limited}]})
assert '可售性动态已验/合约权限未验' in static_text, static_text
blocked_static = {
    **static_limited,
    'can_sell_gate': 'blocked_router_sell_failed',
    'sell_safety_status': 'Router卖出模拟失败；禁止跟随；合约权限/暂停能力未完整验证；禁止放大仓位',
}
blocked_static_text = module.telegram_text({'events': [{**event, 'symbol': 'BLOCKED', 'priority': 'P0', 'status': 'opened', 'analysis': blocked_static}]})
assert '可售性未通过' in blocked_static_text and '动态已验' not in blocked_static_text, blocked_static_text
combined_safety_event = {
    **event,
    'symbol': 'COMBINED',
    'priority': 'P0',
    'status': 'opened',
    'analysis': {
        **static_limited,
        'cohort_confirmed_sell_quote': '12000',
        'liquidity_flow_risk': 'lp_remove',
        'buyer_trace_summary': '已清仓转出，去向=cex_deposit',
    },
    'rows': [dict(base, buyer='0x' + '5' * 40, buyer_trace={'status': 'mostly_exited_or_transferred', 'out_destination_classes': 'cex_deposit'})],
}
combined_safety_text = module.telegram_text({'events': [combined_safety_event]})
assert '确认卖出12K USDT' in combined_safety_text and '流动性lp_remove' in combined_safety_text, combined_safety_text
assert '可售性动态已验/合约权限未验' in combined_safety_text, combined_safety_text
trace_event = {
    **event,
    'symbol': 'TRACE',
    'priority': 'P1',
    'status': 'opened',
    'analysis': cex_transfer,
    'rows': [dict(base, buyer='0x' + '6' * 40, buyer_trace={'status': 'mostly_exited_or_transferred', 'out_destination_classes': 'cex_deposit', 'confirmed_sell_quote_received': '0'})],
}
trace_text = module.telegram_text({'events': [trace_event]})
assert '买后去向CEX' in trace_text, trace_text
sell_event = {**event, 'symbol': 'SELL', 'priority': 'P0', 'status': 'opened', 'analysis': sell_confirmed}
lp_event = {**event, 'symbol': 'LP', 'priority': 'P0', 'status': 'opened', 'analysis': lp_remove}
follow_event = {**event, 'symbol': 'FOLLOW', 'priority': 'P2', 'status': 'opened', 'analysis': follow}
quiet_event = {**event, 'symbol': 'QUIET', 'priority': 'P0', 'status': 'opened', 'analysis': {'spot_action': '观察'}}
risk_text = module.telegram_text({'events': [sell_event, lp_event]})
assert '确认卖出12K USDT' in risk_text and '流动性lp_remove' in risk_text, risk_text
new_first_text = module.telegram_text({
    'events': [sell_event, lp_event, follow_event, quiet_event],
    'new_alert_count': 1,
    '_telegram_new_alert_keys': module.event_alert_keys(follow_event),
})
assert 'FOLLOW P2' in new_first_text and 'QUIET' not in new_first_text, new_first_text
assert new_first_text.count('动作：') == 2 and '另有1项｜详情已归档' in new_first_text, new_first_text
assert len(new_first_text) <= 700 and len(new_first_text.splitlines()) <= 8, (len(new_first_text), new_first_text)
print(follow['trade_signal'] + ' / ' + transfer_unknown['trade_signal'] + ' / ' + sell_confirmed['trade_signal'] + ' / ' + hot['trade_signal'])
"""
    alpha_opening_trade_rules = subprocess.run(
        [sys.executable, "-c", alpha_opening_trade_rules_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_opening_trade_rules_ok = alpha_opening_trade_rules.returncode == 0
    alpha_opening_trade_rules_msg = alpha_opening_trade_rules.stdout.strip() or alpha_opening_trade_rules.stderr.strip()
    checks.append(("generic alpha opening trade rules", alpha_opening_trade_rules_ok, alpha_opening_trade_rules_msg))

    arx_ok = False
    arx_msg = ""
    try:
        arx = json.loads((ROOT / "output" / "arx_launch_watch" / "latest.json").read_text(encoding="utf-8"))
        analysis = arx.get("analysis", {})
        arx_ok = bool(
            arx.get("latest_block")
            and "spot_action" in analysis
            and "perp_action" in analysis
            and "attention" in analysis
            and "suppressed_small_event_transfers" in arx
        )
        arx_msg = f"alerts={len(arx.get('alerts', []))}, suppressed={arx.get('suppressed_small_event_transfers')}, spot={analysis.get('spot_action', '')}"
    except Exception as exc:
        arx_msg = str(exc)
    checks.append(("ARX launch watch action fields present", arx_ok, arx_msg))

    arx_opening_ok = False
    arx_opening_msg = ""
    try:
        arx_opening = json.loads((ROOT / "output" / "arx_opening_block_watch" / "latest.json").read_text(encoding="utf-8"))
        analysis = arx_opening.get("analysis", {})
        arx_opening_ok = bool(
            arx_opening.get("generated_at")
            and "spot_action" in analysis
            and "perp_action" in analysis
            and "operator_behavior" in analysis
            and "total_spent_usdt" in analysis
            and "direction" in analysis
            and "trade_signal" in analysis
            and "buyer_trace_summary" in analysis
            and "cohort_status_summary" in analysis
            and "current_cohort_arx" in analysis
            and "cohort_net_out_pct" in analysis
            and "cohort_confirmed_sell_usdt" in analysis
            and arx_opening.get("status") in {"waiting", "opened"}
        )
        arx_opening_msg = f"status={arx_opening.get('status')}, opening_block={arx_opening.get('opening_block')}, spent={analysis.get('total_spent_usdt')}, txs={arx_opening.get('relevant_tx_count', 0)}, trace={analysis.get('buyer_trace_summary')}"
    except Exception as exc:
        arx_opening_msg = str(exc)
    checks.append(("ARX opening block watch parses", arx_opening_ok, arx_opening_msg))

    arx_telegram_ok = False
    arx_telegram_msg = ""
    telegram_preview_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('arx_opening_block_watch', root / 'scripts' / 'arx_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'arx_opening_block_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'opening_block', 'scan_to_block', 'buyer ']:
    assert forbidden not in text, text
assert len(text) <= 1500, len(text)
assert '有效总结:' in text and '动作信号:' in text and '仓位口径:' in text and '买后去向:' in text and '现货动作:' in text and '合约动作:' in text and '细节: 地址、tx、区块已归档' in text, text
old_key = 'buyer_trace|0xabc|mostly_exited_untraced|100|0|eoa_or_unlabeled|1'
new_key = 'buyer_trace|0xabc|mostly_exited_untraced|100|0|eoa_or_unlabeled|2'
assert module.alert_key_seen(new_key, {old_key}), new_key
assert any(key.startswith('trade_signal|ARX|') for key in module.alert_keys(snapshot)), module.alert_keys(snapshot)
print(len(text))
"""
    telegram_preview = subprocess.run(
        [sys.executable, "-c", telegram_preview_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    arx_telegram_ok = telegram_preview.returncode == 0
    arx_telegram_msg = telegram_preview.stdout.strip() or telegram_preview.stderr.strip()
    checks.append(("ARX Telegram output is concise", arx_telegram_ok, arx_telegram_msg))

    arx_launch_telegram_ok = False
    arx_launch_telegram_msg = ""
    arx_launch_telegram_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('arx_launch_watch', root / 'scripts' / 'arx_launch_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'arx_launch_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'tx:', 'block', '区块', '重点余额']:
    assert forbidden not in text, text
assert len(text) <= 1800, len(text)
assert '有效总结:' in text and '现货动作:' in text and '合约动作:' in text and '新增告警:' in text, text
assert '首批狙击强度已确认' not in text, text
assert ('首批历史' in text or '当前去向' in text), text
print(len(text))
"""
    arx_launch_telegram = subprocess.run(
        [sys.executable, "-c", arx_launch_telegram_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    arx_launch_telegram_ok = arx_launch_telegram.returncode == 0
    arx_launch_telegram_msg = arx_launch_telegram.stdout.strip() or arx_launch_telegram.stderr.strip()
    checks.append(("ARX launch Telegram output is concise", arx_launch_telegram_ok, arx_launch_telegram_msg))

    prediction_ok = False
    prediction_msg = ""
    try:
        prediction = json.loads((ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json").read_text(encoding="utf-8"))
        prediction_ok = "rows" in prediction and "item_count" in prediction
        prediction_msg = f"{prediction.get('item_count', 0)} items, {len(prediction.get('rows', []))} rows"
    except Exception as exc:
        prediction_msg = str(exc)
    checks.append(("prediction market snapshot parses", prediction_ok, prediction_msg))

    perp_snapshot_ok = False
    perp_snapshot_msg = ""
    try:
        perp_snapshot = json.loads((ROOT / "output" / "perp_oi_funding_watch" / "latest.json").read_text(encoding="utf-8"))
        rows = perp_snapshot.get("rows", [])
        perp_snapshot_ok = "rows" in perp_snapshot and "alert_count" in perp_snapshot and isinstance(rows, list)
        perp_snapshot_msg = f"{perp_snapshot.get('item_count', 0)} items, {len(rows)} rows, alerts={perp_snapshot.get('alert_count', 0)}"
    except Exception as exc:
        perp_snapshot_msg = str(exc)
    checks.append(("perp OI/funding snapshot parses", perp_snapshot_ok, perp_snapshot_msg))

    surf_aux_snapshot_ok = False
    surf_aux_snapshot_msg = ""
    try:
        surf_aux_snapshot = json.loads((ROOT / "output" / "surf_aux_market_watch" / "latest.json").read_text(encoding="utf-8"))
        rows = surf_aux_snapshot.get("rows", [])
        surf_aux_snapshot_ok = (
            surf_aux_snapshot.get("schema") == "surf_aux_market_watch.v1"
            and surf_aux_snapshot.get("authority") == "auxiliary_context_only"
            and isinstance(rows, list)
            and all("summary" in row for row in rows)
        )
        surf_aux_snapshot_msg = f"{surf_aux_snapshot.get('row_count', 0)} rows, credits={surf_aux_snapshot.get('credits_used_observed', 0)}"
    except Exception as exc:
        surf_aux_snapshot_msg = str(exc)
    checks.append(("Surf auxiliary market snapshot parses", surf_aux_snapshot_ok, surf_aux_snapshot_msg))

    external_aux_snapshot_ok = False
    external_aux_snapshot_msg = ""
    try:
        external_aux_snapshot = json.loads((ROOT / "output" / "external_aux_sources" / "latest.json").read_text(encoding="utf-8"))
        rows = external_aux_snapshot.get("rows", [])
        external_aux_snapshot_ok = (
            external_aux_snapshot.get("schema") == "external_aux_source_readiness.v1"
            and isinstance(rows, list)
            and all("status" in row and "authority" in row for row in rows)
        )
        external_aux_snapshot_msg = (
            f"{external_aux_snapshot.get('source_count', 0)} sources, "
            f"needs_credentials={external_aux_snapshot.get('needs_credentials_count', 0)}, "
            f"validated={external_aux_snapshot.get('validated_count', 0)}"
        )
    except Exception as exc:
        external_aux_snapshot_msg = str(exc)
    checks.append(("external auxiliary source snapshot parses", external_aux_snapshot_ok, external_aux_snapshot_msg))

    alpha_price_perp_text_ok = False
    alpha_price_perp_text_msg = ""
    alpha_price_perp_text_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_price_momentum_watch', root / 'scripts' / 'alpha_price_momentum_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
perp_context = {
    'snapshot_status': 'ok',
    'status': 'ok',
    'perp_symbol': 'CAPUSDT',
    'perp_state': 'active_perp_market',
    'direction_hint': '可观察',
    'open_interest_usd': '3370000',
    'last_funding_rate': '0.0001',
    'quote_volume_24h': '75300000',
    'oi_usd_delta_pct': '12',
    'mark_price_delta_pct': '6',
    'trend_status': 'ok',
    'trend_hint': '多头增量',
    'trend_action': 'OI扩张且价格上涨，重点等现货承接和链上净流确认',
    'baseline_age_minutes': '60',
    'action': '合约成交活跃，可配合链上出流和价格结构判断',
}
snapshot = {
    'events': [{
        'symbol': 'CAP',
        'priority': 'P1',
        'analysis': {
            'direction': '观察偏多',
            'trade_signal': 'Alpha 收盘价放量走强；等待链上确认',
            'spot_action': '小仓只等回踩，不追市价',
            'perp_action': module.perp_action_summary(perp_context),
            'window_15m': {'open': '0.01', 'high': '0.04', 'low': '0.009', 'close': '0.03', 'high_pct': '18', 'low_pct': '-10', 'close_pct': '9', 'quote_volume': '300000'},
            'depth': {'ask_5pct_usdt': '120000', 'bid_5pct_usdt': '90000'},
            'venue': {'venue_class': 'ALPHA_DOMINANT', 'coverage': 'ONCHAIN_NETFLOW_UNRELIABLE'},
            'perp_context': perp_context,
        },
    }]
}
text = module.telegram_text(snapshot)
assert text.startswith('Alpha 价格动量｜新增'), text
assert '15m 高+18%/低-10%/收+9%｜量300K USDT' in text, text
assert 'OI 多头增量 +12%｜价格+6%｜总OI 3.4M USDT' in text, text
assert '动作：现货 小仓只等回踩，不追市价｜合约 OI扩张且价格上涨' in text, text
assert '有效总结' not in text and '项目总结汇总' not in text and '合约层:' not in text, text
assert len(text) <= 520 and len(text.splitlines()) <= 4, (len(text), text)
quiet_price_event = {
    'symbol': 'CAP',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'perp_action': module.perp_action_summary(perp_context),
        'window_15m': {'high_pct': '1', 'close_pct': '1', 'quote_volume': '1000'},
        'perp_context': perp_context,
    },
}
quiet_keys = module.event_alert_keys(quiet_price_event)
assert quiet_keys and quiet_keys[0].startswith('perp_trend|CAP|多头增量'), quiet_keys
perp_only_text = module.telegram_text({'events': [quiet_price_event], 'new_alert_count': 1})
assert '动作：OI扩张且价格上涨，重点等现货承接和链上净流确认' in perp_only_text, perp_only_text
quiet_price_event_later = {
    'symbol': 'CAP',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'perp_action': module.perp_action_summary({**perp_context, 'baseline_age_minutes': '65'}),
        'window_15m': {'high_pct': '1', 'close_pct': '1', 'quote_volume': '1000'},
        'perp_context': {**perp_context, 'baseline_age_minutes': '65'},
    },
}
assert module.event_alert_keys(quiet_price_event_later) == quiet_keys, (module.event_alert_keys(quiet_price_event_later), quiet_keys)
down_price_event = {
    'symbol': 'LAB',
    'analysis': {
        'direction': '放量走弱',
        'trade_signal': 'Alpha 放量收跌；卖出/减仓观察',
        'window_15m': {'high_pct': '1', 'low_pct': '-18', 'close_pct': '-9', 'quote_volume': '300000', 'from_utc8': '2026-07-02 15:31', 'to_utc8': '2026-07-02 15:45'},
        'perp_context': {},
    },
}
down_keys = module.event_alert_keys(down_price_event)
assert down_keys and down_keys[0].startswith('alpha_price|LAB|放量走弱'), down_keys
legacy_down_key = 'alpha_price|LAB|放量走弱|0|15|0|300000|2026-07-02 15:31|2026-07-02 15:45'
assert module.unseen_alert_keys(module.event_alert_key_pairs(down_price_event), {legacy_down_key}) == [], module.event_alert_key_pairs(down_price_event)
down_price_event_later = {
    'symbol': 'LAB',
    'analysis': {
        'direction': '放量走弱',
        'trade_signal': 'Alpha 放量收跌；卖出/减仓观察',
        'window_15m': {'high_pct': '1', 'low_pct': '-18', 'close_pct': '-9', 'quote_volume': '300000', 'from_utc8': '2026-07-02 15:36', 'to_utc8': '2026-07-02 15:50'},
        'perp_context': {},
    },
}
assert module.event_alert_keys(down_price_event_later) == down_keys, (module.event_alert_keys(down_price_event_later), down_keys)
assert '2026-07-02 15:45' not in down_keys[0], down_keys
new_perp_event = {**quiet_price_event, 'symbol': 'NEW'}
silent_event = {
    'symbol': 'SILENT',
    'priority': 'P0',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'spot_action': '观察',
        'window_15m': {'high_pct': '1', 'low_pct': '-1', 'close_pct': '0', 'quote_volume': '1000'},
        'perp_context': {},
    },
}
new_first_text = module.telegram_text({
    'events': [snapshot['events'][0], down_price_event, new_perp_event, silent_event],
    'new_alert_count': 1,
    '_telegram_new_alert_keys': module.event_alert_keys(new_perp_event),
})
assert 'NEW' in new_first_text and 'SILENT' not in new_first_text, new_first_text
assert new_first_text.count('动作：') == 2 and '另有1项｜详情已归档' in new_first_text, new_first_text
assert len(new_first_text) <= 700 and len(new_first_text.splitlines()) <= 10, (len(new_first_text), new_first_text)
crossed = module.depth_stats({'bids': [['1.2', '10']], 'asks': [['1.0', '10']]}, module.Decimal('1.1'))
assert crossed.get('orderbook_status') == 'crossed_or_stale', crossed
assert '盘口结构不下方向' in ''.join(crossed.get('microstructure_notes') or []), crossed
assert module.depth_amounts_reliable(crossed) is False, crossed
crossed_text = module.telegram_text({'events': [{
    'symbol': 'CROSS',
    'priority': 'P0',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'spot_action': '观察',
        'perp_action': '不开仓',
        'window_15m': {'open': '1', 'high': '1', 'low': '1', 'close': '1', 'high_pct': '20', 'low_pct': '0', 'close_pct': '10', 'quote_volume': '300000'},
        'depth': crossed,
        'venue': {},
        'perp_context': {},
        'reason': '盘口结构: 盘口交叉或快照异常，盘口结构不下方向',
    },
}]})
assert '深度金额不采用' in crossed_text and '+5%卖盘≈' not in crossed_text, crossed_text
normal_depth = module.depth_stats({'bids': [['0.9', '10']], 'asks': [['1.0', '10']]}, module.Decimal('0.95'))
assert module.depth_amounts_reliable(normal_depth) is True, normal_depth
noted_depth = {
    'orderbook_status': 'normal',
    'ask_5pct_usdt': '10000',
    'bid_5pct_usdt': '9000',
    'microstructure_notes': ['价差偏宽(1.20%)'],
}
noted_text = module.telegram_text({'events': [{
    'symbol': 'NOTE',
    'priority': 'P1',
    'analysis': {
        'direction': '放量走弱',
        'trade_signal': 'Alpha 放量收跌；卖出/减仓观察',
        'spot_action': '减仓',
        'window_15m': {'high_pct': '1', 'low_pct': '-18', 'close_pct': '-9', 'quote_volume': '300000'},
        'depth': noted_depth,
        'venue': {},
        'perp_context': {},
    },
}]})
assert '盘口提示:价差偏宽(1.20%)' in noted_text, noted_text
print(len(text))
"""
    alpha_price_perp_text = subprocess.run(
        [sys.executable, "-c", alpha_price_perp_text_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_price_perp_text_ok = alpha_price_perp_text.returncode == 0
    alpha_price_perp_text_msg = alpha_price_perp_text.stdout.strip() or alpha_price_perp_text.stderr.strip()
    checks.append(("alpha price Telegram includes perp layer", alpha_price_perp_text_ok, alpha_price_perp_text_msg))

    prelaunch_watch_code = """
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_prelaunch_watch', root / 'scripts' / 'alpha_prelaunch_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = {
    'items': [
        {
            'symbol': 'WDATAIP',
            'priority': 'P0_DEEP_REVIEW',
            'chain': 'bsc',
            'contracts': [{'chain': 'bsc', 'address': '0xa37eded373c5cdf88644db7c6b89f222e756afb2'}],
            'known_times': [{'time': '2026-07-02 16:00'}],
            'facts': {'display_symbol': 'DATA', 'raw_symbol': 'WDATAIP', 'project_name': 'Data Network'},
            'required_checks': ['official_contract', 'holder_distribution'],
        }
    ]
}
events = module.build_events(config, datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc))
assert len(events) == 1, events
assert events[0]['phase'] == 'T_MINUS_24H', events
assert events[0]['display_name'] == 'DATA/WDATAIP · Data Network', events
assert '未见真实加池' in module.phase_action('T_MINUS_2H')
print(events[0]['display_name'])
"""
    prelaunch_watch = subprocess.run(
        [sys.executable, "-c", prelaunch_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    prelaunch_watch_ok = prelaunch_watch.returncode == 0
    prelaunch_watch_msg = prelaunch_watch.stdout.strip() or prelaunch_watch.stderr.strip()
    checks.append(("alpha prelaunch watch identifies upcoming launch window", prelaunch_watch_ok, prelaunch_watch_msg))

    daily_perp_section_ok = False
    daily_perp_section_msg = ""
    daily_perp_section_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('build_alpha_daily_report', root / 'scripts' / 'build_alpha_daily_report.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
text = module.build_report()
assert '## Perp / OI / Funding' in text, text
assert '## Alpha Price Momentum' in text, text
assert '## CEX Wallet Flow' in text, text
assert '## Holder Concentration' in text, text
assert '## Surf Auxiliary Market' in text, text
assert '## External Auxiliary Sources' in text, text
assert '## Position / Cost Watch' in text, text
assert '## Prelaunch Schedule' in text, text
assert '15m high/low/close' in text and 'Book' in text and 'Alpha 价格层' in text, text
assert '+归集' in text and 'report-only' in text, text
assert '排除托管后前十' in text or 'No holder concentration snapshot available.' in text, text
assert '外部全量Top10' in text or 'No holder concentration snapshot available.' in text, text
assert '联动判断' in text or 'No holder concentration snapshot available.' in text, text
assert 'Action Queue' in text, text
print(len(text))
"""
    daily_perp_section = subprocess.run(
        [sys.executable, "-c", daily_perp_section_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    daily_perp_section_ok = daily_perp_section.returncode == 0
    daily_perp_section_msg = daily_perp_section.stdout.strip() or daily_perp_section.stderr.strip()
    checks.append(("daily report includes market and holder auxiliary sections", daily_perp_section_ok, daily_perp_section_msg))

    csv_path = ROOT / "output" / "sniper_engine" / "signal_scores.csv"
    rows: list[dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    checks.append(("score CSV has rows", len(rows) > 0, f"{len(rows)} rows"))

    lane_counts: dict[str, int] = {}
    for row in rows:
        lane_counts[row.get("lane", "")] = lane_counts.get(row.get("lane", ""), 0) + 1
    checks.append(("P0 queue present", lane_counts.get("P0_DEEP_REVIEW", 0) > 0, str(lane_counts)))

    o1_rows = [row for row in rows if "2067399680217198964" in row.get("tweet_url", "")]
    o1_ok = bool(o1_rows and o1_rows[0].get("lane") == "P0_DEEP_REVIEW")
    o1_msg = ""
    if o1_rows:
        o1_msg = f"score={o1_rows[0].get('score')} lane={o1_rows[0].get('lane')}"
    checks.append(("O1 bribe/bundle sample ranks P0", o1_ok, o1_msg))

    mint_ok = False
    mint_msg = ""
    try:
        mint = json.loads((ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json").read_text(encoding="utf-8"))
        mint_ok = mint.get("position_id") == 6913002 and mint.get("tick_lower") == -30991 and mint.get("tick_upper") == -10219
        mint_msg = f"position_id={mint.get('position_id')} ticks={mint.get('tick_lower')}..{mint.get('tick_upper')}"
    except Exception as exc:
        mint_msg = str(exc)
    checks.append(("O1 Pancake V3 mint decoded", mint_ok, mint_msg))

    swap_ok = False
    swap_msg = ""
    try:
        with (ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv").open("r", encoding="utf-8", newline="") as f:
            swap_rows = list(csv.DictReader(f))
        total_usdt = sum(float(row.get("usdt_in") or 0) for row in swap_rows)
        swap_ok = len(swap_rows) == 5 and 1_003_000 <= total_usdt <= 1_004_000
        swap_msg = f"{len(swap_rows)} swaps total_usdt={total_usdt:.2f}"
    except Exception as exc:
        swap_msg = str(exc)
    checks.append(("O1 opening swaps decoded", swap_ok, swap_msg))

    front_trace_ok = False
    front_trace_msg = ""
    try:
        with (ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv").open("r", encoding="utf-8", newline="") as f:
            trace_rows = list(csv.DictReader(f))
        held_rows = [row for row in trace_rows if row.get("status") == "held_or_accumulated"]
        front_trace_ok = len(trace_rows) == 5 and len(held_rows) == 5
        front_trace_msg = f"{len(held_rows)}/{len(trace_rows)} held_or_accumulated"
    except Exception as exc:
        front_trace_msg = str(exc)
    checks.append(("O1 front buyers traced", front_trace_ok, front_trace_msg))

    report = render_report(checks, lane_counts, o1_rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(REPORT)

    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print("failed checks:")
        for name in failed:
            print(f"- {name}")
        return 1
    return 0


def render_report(
    checks: list[tuple[str, bool, str]],
    lane_counts: dict[str, int],
    o1_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# Sniper Engine Verification Report",
        "",
        "Generated by `scripts/verify_sniper_engine.py`.",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        lines.append(f"| {name} | {status} | {clean(detail)} |")

    lines.extend(["", "## Lane Counts", ""])
    for lane, count in sorted(lane_counts.items()):
        lines.append(f"- `{lane}`: {count}")

    lines.extend(["", "## O1 Sample", ""])
    if o1_rows:
        row = o1_rows[0]
        lines.extend(
            [
                f"- score: `{row.get('score')}`",
                f"- lane: `{row.get('lane')}`",
                f"- evidence: `{row.get('evidence_flags')}`",
                f"- gaps: `{row.get('gaps')}`",
                f"- next checks: `{row.get('next_checks')}`",
            ]
        )
    else:
        lines.append("- missing")

    lines.append("")
    return "\n".join(lines)


def clean(value: str) -> str:
    return (value or "").replace("\n", " ").replace("|", "/")


if __name__ == "__main__":
    raise SystemExit(main())
