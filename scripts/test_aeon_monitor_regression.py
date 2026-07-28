#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AeonSignalParsingRegressionTests(unittest.TestCase):
    def test_canonical_opening_fixture_preserves_unknown_exit_boundary(self) -> None:
        fixture = json.loads(
            (
                ROOT / "input" / "aeon_opening_forensic_2026-07-27.json"
            ).read_text(encoding="utf-8")
        )
        opening = fixture["canonical_opening"]
        self.assertEqual(opening["block"], 112414374)
        self.assertEqual(opening["receipt_status"], 1)
        self.assertEqual(opening["quote_in"], "600000")
        self.assertEqual(opening["token_out"], "7177604.70848690")
        self.assertEqual(
            fixture["sniper_exit_followup"]["confirmed_sell_status"],
            "unknown_incomplete_coverage",
        )
        self.assertEqual(
            fixture["operator_attribution"]["project_or_market_maker_sell"],
            "unverified",
        )
        self.assertEqual(
            fixture["conclusions"]["token_price_drawdown"],
            "verified_by_price_backfill",
        )
        self.assertTrue(
            fixture["conclusions"]["market_wide_selloff"].startswith("unverified")
        )

    def test_chinese_opening_post_keeps_trade_anchors(self) -> None:
        from scripts.ingest_alpha_signal import parse_signal

        parsed = parse_signal(
            """
            🟢AEON $AEON 开盘狙击更新🟢
            🔵狙击金额：600,000
            🟡贿赂金额：635,591.99
            🟣代币数量：7,177,605.00
            🟠持仓成本：0.1721454427
            2026 年 07 月 27 日18:00 上线币安 Alpha 的 $AEON
            """
        )

        self.assertEqual(parsed["symbol"], "AEON")
        self.assertIn(parsed["priority"], {"P0_DEEP_REVIEW", "P1_MONITOR"})
        self.assertEqual(parsed["times"], ["2026-07-27 18:00"])
        self.assertEqual(parsed["facts"]["sniper_amount_quote"], "600000")
        self.assertEqual(parsed["facts"]["bribe_amount_quote"], "635591.99")
        self.assertEqual(parsed["facts"]["token_amount"], "7177605.00")
        self.assertEqual(parsed["facts"]["holding_cost"], "0.1721454427")
        pools = parsed["watchlist_proposal"]["pool_ids"]
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0]["start_time_utc8"], "2026-07-27 18:00")
        self.assertIn("lp_position", parsed["watchlist_proposal"]["required_checks"])

    def test_explicit_pool_candidate_keeps_pool_checks(self) -> None:
        from scripts.ingest_alpha_signal import parse_signal

        pool_id = "0x" + "a" * 64
        parsed = parse_signal(
            f"$POOL PoolId: {pool_id} 2026-07-28 09:30 上线币安 Alpha"
        )

        self.assertEqual(parsed["watchlist_proposal"]["pool_ids"][0]["pool_id"], pool_id)
        self.assertIn("buy_depth_simulation", parsed["watchlist_proposal"]["required_checks"])

    def test_pool_candidates_require_full_ids_and_unambiguous_times(self) -> None:
        from scripts.ingest_alpha_signal import build_pool_candidates, normalize_pool_ids

        first = "0x" + "a" * 64
        second = "0x" + "b" * 64
        self.assertEqual(normalize_pool_ids(["0x1234"]), [])
        candidates = build_pool_candidates(
            [first, second],
            [],
            ["2026-07-28 09:30"],
            "bsc",
        )
        self.assertEqual(len(candidates), 2)
        self.assertTrue(
            all("start_time_utc8" not in candidate for candidate in candidates)
        )


class BinanceAlphaCatalogRegressionTests(unittest.TestCase):
    def test_aeon_enters_runtime_watchlist_from_official_catalog(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_1053",
                    "symbol": "AEON",
                    "name": "AEON",
                    "chainId": "56",
                    "chainName": "BSC",
                    "contractAddress": "0x277add739c6e0477616948357af9e79fe1ec9b80",
                    "decimals": 8,
                    "listingTime": 1785146400000,
                    "cexOffDisplay": False,
                    "bnExclusiveState": False,
                }
            ],
        }
        current = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)

        payload, selected = catalog.build_runtime_watchlist(
            {"generated_at": "2026-07-01T05:59:01+00:00", "items": []},
            response,
            current=current,
            lookback_hours=72,
            lookahead_hours=48,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(payload["catalog_eligible_count"], 1)
        self.assertEqual(payload["catalog_dropped_count"], 0)
        self.assertEqual([item["symbol"] for item in payload["items"]], ["AEON"])
        item = payload["items"][0]
        self.assertEqual(item["priority"], "P1_MONITOR")
        self.assertEqual(item["chain"], "bsc")
        self.assertEqual(
            item["contracts"][0]["address"],
            "0x277add739c6e0477616948357af9e79fe1ec9b80",
        )
        self.assertEqual(item["pool_ids"][0]["start_time_utc8"], "2026-07-27 18:00")
        self.assertEqual(
            item["pool_ids"][0]["opening_anchor_status"],
            "catalog_listing_candidate",
        )
        self.assertGreaterEqual(item["opening_max_age_hours"], 72)
        self.assertEqual(item["opening_max_logs"], 5000)
        self.assertEqual(item["opening_trace_buyers"], 8)
        self.assertEqual(item["opening_max_txs"], 24)
        self.assertGreaterEqual(item["opening_liquidity_max_age_seconds"], 72 * 3600)
        self.assertEqual(item["opening_classify_out_txs"], 8)
        self.assertEqual(item["opening_next_hop_recipients"], 8)
        self.assertEqual(item["opening_next_hop_classify_txs"], 6)
        self.assertEqual(item["project_operator_probe"], "owner")
        self.assertEqual(item["project_lookback_blocks"], 250000)
        self.assertEqual(item["facts"]["alpha_id"], "ALPHA_1053")
        self.assertEqual(
            item["facts"]["opening_anchor_status"],
            "catalog_listing_candidate",
        )

    def test_catalog_rejects_invalid_and_hidden_rows(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        current = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
        invalid = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_1",
                    "symbol": "HIDDEN",
                    "chainId": "56",
                    "contractAddress": "0x" + "1" * 40,
                    "listingTime": 1785146400000,
                    "cexOffDisplay": True,
                },
                {
                    "alphaId": "ALPHA_2",
                    "symbol": "BAD",
                    "chainId": "56",
                    "contractAddress": "not-an-address",
                    "listingTime": 1785146400000,
                },
            ],
        }

        payload, selected = catalog.build_runtime_watchlist(
            {"items": []},
            invalid,
            current=current,
            lookback_hours=72,
            lookahead_hours=48,
        )

        self.assertEqual(selected, [])
        self.assertEqual(payload["items"], [])

    def test_catalog_rejects_empty_or_invalid_static_inputs(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        with self.assertRaisesRegex(ValueError, "empty"):
            catalog.valid_catalog_response({
                "code": "000000",
                "success": True,
                "data": [],
            })
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "watchlist.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                catalog.read_static_watchlist(path)
        with self.assertRaisesRegex(ValueError, "items array"):
            catalog.validate_static_watchlist({})

    def test_same_ticker_without_identity_is_not_merged(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_1053",
                    "symbol": "AEON",
                    "name": "AEON",
                    "chainId": "56",
                    "contractAddress": "0x277add739c6e0477616948357af9e79fe1ec9b80",
                    "listingTime": 1785146400000,
                    "cexOffDisplay": False,
                }
            ],
        }
        payload, selected = catalog.build_runtime_watchlist(
            {
                "items": [
                    {
                        "symbol": "AEON",
                        "chain": "bsc",
                        "contracts": [],
                        "known_times": [
                            {"time": "2026-01-01 00:00", "reason": "unrelated_event"}
                        ],
                    }
                ]
            },
            response,
            current=datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc),
            lookback_hours=72,
            lookahead_hours=48,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["contracts"], [])
        self.assertEqual(
            payload["items"][1]["contracts"][0]["address"],
            "0x277add739c6e0477616948357af9e79fe1ec9b80",
        )

    def test_catalog_limits_to_supported_chain_and_budget(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_BASE",
                    "symbol": "BASEONLY",
                    "chainId": "8453",
                    "contractAddress": "0x" + "1" * 40,
                    "listingTime": 1785146400000,
                },
                {
                    "alphaId": "ALPHA_OLD",
                    "symbol": "OLDER",
                    "chainId": "56",
                    "contractAddress": "0x" + "2" * 40,
                    "listingTime": 1785142800000,
                },
                {
                    "alphaId": "ALPHA_NEW",
                    "symbol": "NEWER",
                    "chainId": "56",
                    "contractAddress": "0x" + "3" * 40,
                    "listingTime": 1785146400000,
                },
            ],
        }
        payload, selected = catalog.build_runtime_watchlist(
            {"items": []},
            response,
            current=datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc),
            lookback_hours=72,
            lookahead_hours=48,
            max_selected=1,
        )

        self.assertEqual([item["symbol"] for item in selected], ["NEWER"])
        self.assertEqual([item["symbol"] for item in payload["items"]], ["NEWER"])
        self.assertEqual(payload["catalog_eligible_count"], 2)
        self.assertEqual(payload["catalog_dropped_count"], 1)

    def test_catalog_merge_deduplicates_contract_identity(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        address = "0x" + "1" * 40

        merged = catalog.merge_item(
            {
                "symbol": "AEON",
                "contracts": [
                    {
                        "chain": "bsc",
                        "address": address,
                        "confidence": "curated",
                    }
                ],
            },
            {
                "symbol": "AEON",
                "contracts": [
                    {
                        "chain": "BSC",
                        "address": address.upper().replace("0X", "0x"),
                        "confidence": "catalog",
                    }
                ],
            },
        )

        self.assertEqual(len(merged["contracts"]), 1)
        self.assertEqual(merged["contracts"][0]["confidence"], "curated")
        self.assertEqual(catalog.DEFAULT_MAX_SELECTED, 8)

    def test_catalog_retains_a_previous_cohort_for_thirty_days(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        current = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
        retained_address = "0x" + "1" * 40
        previous = {
            "items": [
                {
                    "symbol": "RETAINED",
                    "chain": "bsc",
                    "active_monitoring": True,
                    "contracts": [{"chain": "bsc", "address": retained_address}],
                    "facts": {
                        "alpha_id": "ALPHA_RETAINED",
                        "listing_time_utc": "2026-07-18T01:00:00+00:00",
                    },
                }
            ]
        }
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_TOO_OLD",
                    "symbol": "TOOOLD",
                    "chainId": "56",
                    "contractAddress": "0x" + "2" * 40,
                    "listingTime": 1782522000000,
                }
            ],
        }

        payload, selected = catalog.build_runtime_watchlist(
            {"items": []},
            response,
            current=current,
            lookback_hours=72,
            lookahead_hours=48,
            previous_runtime_watchlist=previous,
            retention_days=30,
        )

        self.assertEqual([item["symbol"] for item in selected], ["RETAINED"])
        self.assertEqual(payload["catalog_retained_selected_count"], 1)
        self.assertEqual(payload["catalog_dropped_count"], 0)
        self.assertGreaterEqual(
            selected[0]["opening_max_age_hours"],
            30 * 24,
        )

    def test_catalog_schema_continuity_fails_closed_on_abrupt_drop(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        rows = [
            {
                "alphaId": "ALPHA_1",
                "symbol": "AEON",
                "chainId": "56",
                "contractAddress": "0x" + "1" * 40,
                "listingTime": 1785146400000,
            }
        ]

        with self.assertRaisesRegex(ValueError, "dropped abruptly"):
            catalog.validate_schema_continuity(
                rows,
                {"supported_schema_count": 10},
                0.5,
            )

    def test_catalog_contract_migration_promotes_the_new_official_contract(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        old_address = "0x" + "1" * 40
        new_address = "0x" + "2" * 40

        merged = catalog.merge_item(
            {
                "symbol": "AEON",
                "contracts": [{"chain": "bsc", "address": old_address}],
                "facts": {
                    "alpha_id": "ALPHA_1",
                    "listing_time_utc": "2026-01-01T00:00:00+00:00",
                },
            },
            {
                "symbol": "AEON",
                "contracts": [{"chain": "bsc", "address": new_address}],
                "facts": {
                    "alpha_id": "ALPHA_1",
                    "listing_time_utc": "2026-07-28T00:00:00+00:00",
                },
            },
        )

        self.assertEqual(merged["contracts"][0]["address"], new_address)
        self.assertEqual(merged["contracts"][1]["address"], old_address)
        self.assertEqual(
            merged["facts"]["listing_time_utc"],
            "2026-07-28T00:00:00+00:00",
        )


class RuntimeIntegrationRegressionTests(unittest.TestCase):
    def test_generic_runtime_context_uses_aeon_watch_outputs(self) -> None:
        from scripts.telegram_signal_collector import runtime_context_from_snapshots

        context = runtime_context_from_snapshots(
            "AEON",
            {
                "opening": {
                    "generated_at": "2026-07-28T01:00:00+00:00",
                    "events": [
                        {
                            "symbol": "AEON",
                            "analysis": {
                                "conclusion": "首批买家已确认",
                                "spot_action": "等待承接",
                                "perp_action": "偏空观察",
                                "attention": "追踪分仓",
                                "operator_behavior": "池子报价资产外流",
                                "sniper_behavior": "首批地址已有确认卖出",
                            },
                        }
                    ],
                },
                "price": {
                    "generated_at": "2026-07-28T01:01:00+00:00",
                    "events": [
                        {
                            "symbol": "AEON",
                            "analysis": {
                                "direction": "冲高回落",
                                "spot_action": "降低风险",
                                "perp_action": "等待深度",
                            },
                        }
                    ],
                },
                "project": {
                    "generated_at": "2026-07-28T02:00:00+00:00",
                    "projects": [
                        {
                            "symbol": "OTHER",
                            "analysis": {"conclusion": "unrelated"},
                        }
                    ],
                },
            },
        )

        self.assertEqual(context["conclusion"], "首批买家已确认")
        self.assertEqual(context["spot_action"], "降低风险")
        self.assertEqual(context["sniper_behavior"], "首批地址已有确认卖出")
        self.assertEqual(context["generated_at"], "2026-07-28T01:01:00+00:00")

    def test_runtime_context_does_not_cross_same_ticker_contracts(self) -> None:
        from scripts.telegram_signal_collector import runtime_context_from_snapshots

        target = "0x" + "2" * 40
        context = runtime_context_from_snapshots(
            "AEON",
            {
                "project": {
                    "generated_at": "2026-07-28T01:00:00+00:00",
                    "projects": [
                        {
                            "symbol": "AEON",
                            "contracts": [{"address": "0x" + "1" * 40}],
                            "analysis": {"conclusion": "wrong contract"},
                        },
                        {
                            "symbol": "AEON",
                            "contracts": [{"address": target}],
                            "analysis": {"conclusion": "target contract"},
                        },
                    ],
                }
            },
            {target},
        )

        self.assertEqual(context["conclusion"], "target contract")

    def test_server_cycle_discovers_before_downstream(self) -> None:
        text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")

        catalog_index = text.index("binance_alpha_catalog_watch.py")
        collector_index = text.index("telegram_signal_collector.py")
        user_collector_index = text.index("telegram_user_signal_collector.py")
        project_index = text.index("alpha_project_watch.py")
        opening_index = text.index("alpha_opening_sprint.sh")
        self.assertLess(collector_index, catalog_index)
        self.assertLess(user_collector_index, catalog_index)
        self.assertLess(catalog_index, project_index)
        self.assertLess(project_index, opening_index)
        self.assertIn("ALPHA_WATCHLIST_PATH", text)
        self.assertIn("SIGNAL_RUNTIME_CONTEXT=0", text)
        self.assertIn("BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS", text)
        self.assertIn('[[ -z "${ALPHA_WATCHLIST_PATH:-}" ]]', text)

    def test_server_cycle_preserves_external_disable_telegram(self) -> None:
        text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")

        capture = 'REQUESTED_DISABLE_TELEGRAM="${DISABLE_TELEGRAM:-0}"'
        source = ". ./.env.local"
        restore = 'export DISABLE_TELEGRAM=1'
        guard = 'if [[ "${DISABLE_TELEGRAM:-0}" == "1" ]]; then'
        self.assertLess(text.index(capture), text.index(source))
        self.assertLess(text.index(source), text.index(restore))
        self.assertLess(text.index(restore), text.index(guard))

    def test_server_cycle_intraday_budget_covers_dynamic_watchlist(self) -> None:
        text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")

        self.assertIn(
            'run_step "${ALPHA_INTRADAY_TIMEOUT_SECONDS:-480}" '
            "python3 scripts/alpha_intraday_flow_watch.py",
            text,
        )

    def test_server_cycle_runs_fast_signals_before_opening_trace(self) -> None:
        text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")

        intraday_index = text.index("alpha_intraday_flow_watch.py")
        price_index = text.index("alpha_price_momentum_watch.py")
        flush_index = text.index("telegram_signal_collector.py --flush-pending")
        opening_index = text.index("alpha_opening_sprint.sh")
        self.assertLess(intraday_index, opening_index)
        self.assertLess(price_index, opening_index)
        self.assertLess(flush_index, opening_index)

    def test_intraday_defaults_keep_the_fast_window_coverage_budget(self) -> None:
        text = (ROOT / "scripts" / "alpha_intraday_flow_watch.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('ALPHA_INTRADAY_WINDOW_BLOCKS", "360"', text)
        self.assertIn('ALPHA_INTRADAY_MAX_RECEIPTS", "300"', text)
        self.assertIn('ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS", "90"', text)

    def test_pre_watch_signal_reply_omits_stale_runtime_context(self) -> None:
        import scripts.telegram_signal_collector as collector

        with mock.patch.dict(os.environ, {"SIGNAL_RUNTIME_CONTEXT": "0"}):
            self.assertEqual(
                collector.project_runtime_context({"symbol": "AEON"}),
                {},
            )

    def test_opening_times_do_not_cross_assign_multiple_pools(self) -> None:
        from scripts.alpha_opening_block_watch import opening_pool_rows

        ambiguous = opening_pool_rows({
            "pool_ids": [
                {"chain": "bsc", "pool_id": "pool-a"},
                {"chain": "bsc", "pool_id": "pool-b"},
            ],
            "known_times": [
                {"time": "2026-07-28 09:00", "reason": "listing_time"},
                {"time": "2026-07-29 09:00", "reason": "token_unlock"},
            ],
        })
        self.assertEqual(ambiguous, [])

        unique = opening_pool_rows({
            "pool_ids": [{"chain": "bsc", "pool_id": "pool-a"}],
            "known_times": [
                {"time": "2026-07-28 09:00", "reason": "listing_time"},
                {"time": "2026-07-29 09:00", "reason": "token_unlock"},
            ],
        })
        self.assertEqual(unique[0]["start_time_utc8"], "2026-07-28 09:00")

    def test_watchers_accept_runtime_watchlist_path(self) -> None:
        module_names = [
            "scripts.alpha_project_watch",
            "scripts.alpha_prelaunch_watch",
            "scripts.alpha_opening_block_watch",
            "scripts.alpha_intraday_flow_watch",
            "scripts.alpha_price_momentum_watch",
            "scripts.alpha_holder_concentration_watch",
            "scripts.perp_oi_funding_watch",
            "scripts.surf_aux_market_watch",
        ]
        old_value = os.environ.get("ALPHA_WATCHLIST_PATH")
        try:
            os.environ["ALPHA_WATCHLIST_PATH"] = "/tmp/aeon-runtime-watchlist.json"
            for module_name in module_names:
                module = importlib.import_module(module_name)
                module = importlib.reload(module)
                self.assertEqual(
                    module.CONFIG_PATH,
                    Path("/tmp/aeon-runtime-watchlist.json"),
                    module_name,
                )
        finally:
            if old_value is None:
                os.environ.pop("ALPHA_WATCHLIST_PATH", None)
            else:
                os.environ["ALPHA_WATCHLIST_PATH"] = old_value

    def test_health_reads_the_effective_runtime_watchlist(self) -> None:
        from scripts.runtime_health_watch import effective_runtime_watchlist_path

        root = Path("/tmp/sniper-root")
        with mock.patch.dict(
            os.environ,
            {"ALPHA_WATCHLIST_PATH": "config/custom-alpha.json"},
        ):
            self.assertEqual(
                effective_runtime_watchlist_path(root),
                root / "config" / "custom-alpha.json",
            )

    def test_health_fails_when_recent_official_token_has_no_runtime_coverage(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog_path = root / "output" / "binance_alpha_catalog_watch" / "latest.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [
                            {
                                "symbol": "AEON",
                                "chain": "bsc",
                                "contract": "0x277add739c6e0477616948357af9e79fe1ec9b80",
                                "listing_time_utc": "2026-07-27T10:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            runtime_path = (
                root
                / "output"
                / "binance_alpha_catalog_watch"
                / "current_watchlist.json"
            )
            runtime_path.write_text(json.dumps({"items": []}), encoding="utf-8")

            issues = alpha_coverage_issues(root)

        self.assertTrue(issues)
        self.assertTrue(
            any(row["kind"] == "alpha_coverage_gap" and row["name"] == "AEON" for row in issues)
        )

    def test_health_reports_catalog_items_dropped_by_budget(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "output" / "binance_alpha_catalog_watch" / "latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "dropped_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            issues = alpha_coverage_issues(root)

        self.assertEqual(issues[0]["kind"], "alpha_catalog_budget_exceeded")

    def test_health_warns_on_partial_opening_buyer_trace_coverage(self) -> None:
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
        )

        for status in (
            "unknown_incomplete_coverage",
            "confirmed_sell_partial_coverage",
        ):
            with self.subTest(status=status):
                row = {
                    "status": "opened",
                    "rows": [
                        {
                            "buyer_trace": {
                                "status": status,
                                "coverage_complete": False,
                                "coverage_status": "partial",
                            }
                        }
                    ],
                }
                self.assertEqual(output_row_coverage_issue("opening", row), "")
                self.assertEqual(
                    output_row_coverage_warning("opening", row),
                    "opening buyer trace coverage incomplete",
                )

    def test_health_warns_on_unresolved_project_operator_attribution(self) -> None:
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
        )

        row = {
            "contracts": [
                {
                    "address": "0x" + "1" * 40,
                    "operator_attribution_state": "conflicting_owner_selectors",
                }
            ]
        }

        self.assertEqual(
            output_row_coverage_issue(
                "project",
                row,
                target_contract="0x" + "1" * 40,
            ),
            "",
        )
        self.assertEqual(
            output_row_coverage_warning(
                "project",
                row,
                target_contract="0x" + "1" * 40,
            ),
            "project operator attribution warning=conflicting_owner_selectors",
        )

    def test_shared_pool_manager_event_requires_matching_pool_id(self) -> None:
        from scripts.alpha_opening_block_watch import liquidity_event_matches

        target_pool = "0x" + "a" * 64
        other_pool = "0x" + "b" * 64
        event = {"pool_id": target_pool}
        meta = {"role": "pool_manager"}

        self.assertFalse(
            liquidity_event_matches(
                event,
                {"topics": ["0xevent", other_pool]},
                meta,
            )
        )
        self.assertTrue(
            liquidity_event_matches(
                event,
                {"topics": ["0xevent", target_pool]},
                meta,
            )
        )

    def test_liquidity_event_display_limit_does_not_truncate_coverage(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        target_pool = "0x" + "a" * 64
        first = "0x" + "1" * 40
        second = "0x" + "2" * 40
        calls: list[tuple[str, int]] = []

        def fetch(chain, query, chunk_blocks, max_logs, timeout):
            calls.append((query["address"], max_logs))
            direction_topic = (
                opening.INCREASE_LIQUIDITY_TOPIC
                if query["address"] == first
                else opening.DECREASE_LIQUIDITY_TOPIC
            )
            return [
                {
                    "address": query["address"],
                    "blockNumber": "0x64",
                    "transactionHash": "0x" + query["address"][2:].rjust(64, "0"),
                    "topics": [direction_topic, target_pool],
                    "data": "0x" + "0" * 192,
                }
            ]

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_LIQUIDITY_EVENT_MAX_LOGS": "1",
                    "ALPHA_OPENING_LIQUIDITY_EVENT_QUERY_MAX_LOGS": "5000",
                },
            ),
            mock.patch.object(opening, "get_logs_quick", side_effect=fetch),
        ):
            result = opening.scan_liquidity_events(
                {"chain": "bsc", "pool_id": target_pool},
                100,
                200,
                {
                    first: {"role": "pool_manager", "label": "first"},
                    second: {"role": "pool_manager", "label": "second"},
                },
            )

        self.assertEqual(calls, [(first, 5000), (second, 5000)])
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["risk"], "lp_remove")
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["label"], "second")

    def test_opening_owner_probe_rejects_owner_zero_conflict(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        owner = "0x" + "1" * 40
        encoded_owner = "0x" + owner[2:].rjust(64, "0")
        zero = "0x" + "0" * 64
        with mock.patch.object(
            opening,
            "optional_eth_call",
            side_effect=[encoded_owner, zero],
        ):
            controller = opening.token_controller("bsc", "0x" + "2" * 40)

        self.assertEqual(controller["state"], "conflicting_owner_selectors")
        self.assertNotIn("address", controller)

    def test_opening_trace_marks_bounded_history_unknown(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "AEON",
                "decimals": 8,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_TRACE_MAX_BLOCKS": "10",
                    "ALPHA_OPENING_TRACE_FULL_EXITED_MAX_BLOCKS": "100",
                },
            ),
            mock.patch.object(opening, "token_balance", return_value=opening.Decimal(0)),
            mock.patch.object(opening, "get_logs_quick", return_value=[]),
            mock.patch.object(
                opening,
                "simulate_transfer_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
            mock.patch.object(
                opening,
                "simulate_dex_quote_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
            mock.patch.object(
                opening,
                "simulate_router_sell_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
        ):
            trace = opening.trace_buyer(
                event,
                "0x" + "3" * 40,
                100,
                1000,
                opening.Decimal("7177604"),
            )

        self.assertEqual(opening.trace_start_block(100, 1000, 10, 100, True), 900)
        self.assertFalse(trace["coverage_complete"])
        self.assertEqual(trace["status"], "unknown_incomplete_coverage")
        self.assertEqual(trace["confirmed_sell_status"], "unknown_incomplete_coverage")

        self.assertFalse(
            opening.liquidity_event_matches(
                {"lp_position_ids": [7]},
                {"topics": ["0xevent", "0xnot-hex"]},
                {"role": "lp_position_manager"},
            )
        )

    def test_opening_quote_includes_infrastructure_counterparty(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        payer = "0x" + "3" * 40
        relay = "0x" + "4" * 40
        pool = "0x" + "5" * 40
        receiver = "0x" + "6" * 40
        event = {
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": quote},
            "known_contracts": [{"address": pool, "class": "pool_manager"}],
        }
        transfers = [
            {
                "token": quote,
                "from": payer,
                "to": relay,
                "amount": opening.Decimal("600000"),
            },
            {
                "token": quote,
                "from": relay,
                "to": pool,
                "amount": opening.Decimal("600000"),
            },
            {
                "token": token,
                "from": pool,
                "to": receiver,
                "amount": opening.Decimal("7177604.70848690"),
            },
        ]

        nets = opening.net_by_address(transfers, token, quote)
        buyer, token_bought, spent_quote = opening.best_buyer(event, nets)

        self.assertEqual(buyer, receiver)
        self.assertEqual(token_bought, opening.Decimal("7177604.70848690"))
        self.assertEqual(spent_quote, opening.Decimal(0))
        self.assertEqual(
            opening.pool_side_quote_in(event, nets),
            opening.Decimal("600000"),
        )

    def test_opening_trace_keeps_a_coverage_safe_log_floor(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "AEON",
                "decimals": 8,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_TRACE_MAX_LOGS": "80",
                    "ALPHA_OPENING_INFINITY_QUOTE_PROBE": "0",
                },
            ),
            mock.patch.object(opening, "token_balance", return_value=opening.Decimal("1")),
            mock.patch.object(opening, "get_logs_quick", return_value=[]) as get_logs,
            mock.patch.object(
                opening,
                "simulate_transfer_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
            mock.patch.object(
                opening,
                "simulate_dex_quote_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
            mock.patch.object(
                opening,
                "simulate_router_sell_safety",
                return_value={"status": "unverified", "detail": ""},
            ),
        ):
            opening.trace_buyer(
                event,
                "0x" + "3" * 40,
                100,
                200,
                opening.Decimal("1"),
            )

        self.assertEqual(get_logs.call_args.args[3], 1200)

    def test_next_hop_log_limit_becomes_partial_coverage(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "AEON",
                "decimals": 8,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_NEXT_HOP_MAX_LOGS": "80"},
            ),
            mock.patch.object(
                opening,
                "get_logs_quick",
                side_effect=RuntimeError("coverage truncated"),
            ) as get_logs,
        ):
            result = opening.trace_next_hop_from_recipient(
                event,
                "0x" + "3" * 40,
                "0x" + "4" * 40,
                100,
                200,
            )

        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["confirmed_sell_count"], 0)
        self.assertEqual(get_logs.call_args.args[3], 1200)

    def test_next_hop_classification_caps_are_partial_coverage(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "AEON",
                "decimals": 8,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        raw_logs = [
            {"transactionHash": "0x" + f"{index:064x}"}
            for index in range(3)
        ]

        def parse_log(row, decimals):
            return {
                "tx": row["transactionHash"],
                "block": 100,
                "log_index": 0,
                "to": "0x" + "5" * 40,
                "amount": opening.Decimal("1"),
            }

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_NEXT_HOP_CLASSIFY_TXS": "2"},
            ),
            mock.patch.object(opening, "get_logs_quick", return_value=raw_logs),
            mock.patch.object(opening, "transfer_log", side_effect=parse_log),
            mock.patch.object(
                opening,
                "classify_recipient_next_hop_tx",
                return_value={
                    "classes": set(),
                    "quote_received": opening.Decimal(0),
                    "confirmed_sell_count": 0,
                },
            ) as classify_tx,
        ):
            tx_limited = opening.trace_next_hop_from_recipient(
                event,
                "0x" + "3" * 40,
                "0x" + "4" * 40,
                100,
                200,
            )

        self.assertFalse(tx_limited["coverage_complete"])
        self.assertEqual(classify_tx.call_count, 2)

        recipients = ["0x" + f"{index + 6:040x}" for index in range(3)]
        outgoing_logs = [
            {
                "to": recipient,
                "block": 100 + index,
            }
            for index, recipient in enumerate(recipients)
        ]
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_NEXT_HOP_RECIPIENTS": "2"},
            ),
            mock.patch.object(
                opening,
                "quick_rpc_call",
                return_value={"status": "0x1", "logs": []},
            ),
            mock.patch.object(
                opening,
                "destination_class",
                return_value="eoa_or_unlabeled",
            ),
            mock.patch.object(
                opening,
                "trace_next_hop_from_recipient",
                return_value={
                    "classes": set(),
                    "quote_received": opening.Decimal(0),
                    "confirmed_sell_count": 0,
                    "recipient_count": 0,
                    "coverage_complete": True,
                },
            ) as trace_recipient,
        ):
            recipient_limited = opening.classify_outgoing_tx(
                event,
                "0x" + "3" * 40,
                "0x" + "9" * 64,
                outgoing_logs,
                200,
            )

        self.assertFalse(recipient_limited["next_hop_coverage_complete"])
        self.assertEqual(trace_recipient.call_count, 2)

    def test_opening_selection_keeps_large_middle_transfer(self) -> None:
        from scripts.alpha_opening_block_watch import (
            capped_event_int_setting,
            selected_tx_hashes,
        )

        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_OPENING_MAX_TXS": "8",
                "ALPHA_OPENING_TRACE_BUYERS": "4",
            },
        ):
            self.assertEqual(
                capped_event_int_setting(
                    {"opening_max_txs": 24},
                    "opening_max_txs",
                    "ALPHA_OPENING_MAX_TXS",
                    25,
                ),
                8,
            )
            self.assertEqual(
                capped_event_int_setting(
                    {"opening_trace_buyers": 8},
                    "opening_trace_buyers",
                    "ALPHA_OPENING_TRACE_BUYERS",
                    4,
                ),
                4,
            )

        logs = []
        for index in range(30):
            amount = 10_000_000 if index == 15 else index + 1
            logs.append(
                {
                    "blockNumber": "0x1",
                    "transactionIndex": hex(index),
                    "logIndex": "0x0",
                    "transactionHash": "0x" + f"{index:064x}",
                    "data": hex(amount),
                }
            )
        selected = selected_tx_hashes(logs, 8)
        self.assertIn("0x" + f"{15:064x}", selected)
        self.assertEqual(len(selected), 8)

    def test_opening_log_coverage_fails_closed(self) -> None:
        import scripts.alpha_opening_block_watch as opening
        from sniper_engine import rpc

        query = {
            "fromBlock": "0x1",
            "toBlock": "0x4",
            "topics": [opening.TRANSFER_TOPIC],
        }
        def fail_after_first_chunk(url, method, params, timeout):
            start = int(params[0]["fromBlock"], 16)
            if start <= 2:
                return []
            raise RuntimeError("private-provider-secret")

        with (
            mock.patch.object(rpc, "rpc_urls", return_value=["fixture://only"]),
            mock.patch.object(rpc, "rpc_call_url", side_effect=fail_after_first_chunk),
        ):
            with self.assertRaisesRegex(RuntimeError, "coverage failed"):
                opening.get_logs_quick("bsc", query, 2, 10, 1)

        capped_query = {
            "fromBlock": "0x1",
            "toBlock": "0x1",
            "topics": [opening.TRANSFER_TOPIC],
        }
        with mock.patch.object(
            opening,
            "rpc_call",
            return_value=[{"logIndex": hex(index)} for index in range(3)],
        ):
            with self.assertRaisesRegex(RuntimeError, "coverage truncated"):
                opening.get_logs("bsc", capped_query, 1, 2)

    def test_opening_transfer_ranges_cover_overlapping_recent_tail(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        calls: list[tuple[int, int, int]] = []

        def fetch(chain, query, chunk_blocks, max_logs):
            calls.append(
                (
                    int(query["fromBlock"], 16),
                    int(query["toBlock"], 16),
                    max_logs,
                )
            )
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "token": {"address": "0x" + "1" * 40},
            "opening_max_logs": 5000,
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_SCAN_BLOCKS": "240",
                    "ALPHA_OPENING_RECENT_BLOCKS": "1200",
                    "ALPHA_OPENING_MAX_LOGS": "1000",
                },
            ),
            mock.patch.object(opening, "get_logs", side_effect=fetch),
        ):
            rows = opening.opening_transfer_logs(event, 1000)

        self.assertEqual(rows, [])
        self.assertEqual(calls, [(100, 1000, 1000)])

    def test_opening_transfer_budget_cannot_hide_a_second_range(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        calls: list[tuple[int, int, int]] = []

        def fetch(chain, query, chunk_blocks, max_logs):
            start = int(query["fromBlock"], 16)
            end = int(query["toBlock"], 16)
            calls.append((start, end, max_logs))
            return [
                {
                    "transactionHash": "0x" + f"{index:064x}",
                    "logIndex": hex(index),
                }
                for index in range(3)
            ]

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "token": {"address": "0x" + "1" * 40},
            "opening_max_logs": 3,
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_SCAN_BLOCKS": "10",
                    "ALPHA_OPENING_RECENT_BLOCKS": "20",
                    "ALPHA_OPENING_MAX_LOGS": "3",
                },
            ),
            mock.patch.object(opening, "get_logs", side_effect=fetch),
        ):
            with self.assertRaisesRegex(RuntimeError, "coverage truncated"):
                opening.opening_transfer_logs(event, 200)

        self.assertEqual(calls, [(100, 110, 3)])

    def test_opening_log_coverage_adaptively_splits_failed_ranges(self) -> None:
        import scripts.alpha_opening_block_watch as opening
        from sniper_engine import rpc

        calls = []

        def fetch(url, method, params, timeout):
            start = int(params[0]["fromBlock"], 16)
            end = int(params[0]["toBlock"], 16)
            calls.append((start, end))
            if start != end:
                raise RuntimeError("rpc response error")
            return [{"blockNumber": hex(start)}]

        query = {
            "fromBlock": hex(100),
            "toBlock": hex(103),
            "topics": [opening.TRANSFER_TOPIC],
        }
        with (
            mock.patch.object(rpc, "rpc_urls", return_value=["fixture://only"]),
            mock.patch.object(rpc, "rpc_call_url", side_effect=fetch),
        ):
            rows = opening.get_logs_quick("bsc", query, 4, 10, 1)
        self.assertEqual([int(row["blockNumber"], 16) for row in rows], [100, 101, 102, 103])
        self.assertEqual(len(calls), 7)

    def test_intraday_log_coverage_adaptively_splits_failed_ranges(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday
        from sniper_engine import rpc

        token = "0x" + "a" * 40
        recipient = "0x" + "b" * 40

        def fetch(url, method, params, timeout):
            start = int(params[0]["fromBlock"], 16)
            end = int(params[0]["toBlock"], 16)
            if start != end:
                raise RuntimeError("rpc response error")
            return [{
                "address": token,
                "blockNumber": hex(start),
                "blockHash": f"0x{start:064x}",
                "transactionHash": f"0x{start:064x}",
                "transactionIndex": "0x0",
                "logIndex": "0x0",
                "topics": [
                    intraday.opening.TRANSFER_TOPIC,
                    intraday.opening.address_topic("0x" + "c" * 40),
                    intraday.opening.address_topic(recipient),
                ],
                "data": "0x1",
            }]

        event = {
            "chain": "bsc",
            "token": {"address": token, "decimals": 18},
        }
        env = {
            "ALPHA_INTRADAY_LOG_CHUNK_BLOCKS": "4",
            "ALPHA_INTRADAY_MAX_LOGS": "10",
            "ALPHA_INTRADAY_RPC_TIMEOUT": "1",
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(rpc, "rpc_urls", return_value=["fixture://only"]),
            mock.patch.object(rpc, "rpc_call_url", side_effect=fetch),
        ):
            rows, coverage = intraday.token_transfer_logs_with_coverage(event, 100, 103)
        self.assertEqual([row["block"] for row in rows], [100, 101, 102, 103])
        self.assertEqual(coverage["state"], "requested_window_complete")
        self.assertTrue(coverage["complete"])

    def test_next_hop_selection_keeps_largest_middle_transfer(self) -> None:
        from scripts.alpha_opening_block_watch import select_transfer_tx_items

        by_tx = {
            f"tx-{index}": [
                {
                    "block": index,
                    "log_index": 0,
                    "amount": "1000000" if index == 5 else "1",
                }
            ]
            for index in range(10)
        }
        selected = select_transfer_tx_items(by_tx, 6)
        self.assertIn("tx-5", {tx_hash for tx_hash, _rows in selected})

    def test_buyer_trace_selection_keeps_large_middle_sniper(self) -> None:
        from scripts.alpha_opening_block_watch import selected_buyer_trace_rows

        rows = [
            {
                "tx": f"tx-{index}",
                "token_bought": "1000000" if index == 8 else "1000",
                "spent_quote": "600000" if index == 8 else "10000",
                "largest_internal_native": {"amount": "0"},
            }
            for index in range(12)
        ]

        selected = selected_buyer_trace_rows(rows, 8)

        selected_txs = {row["tx"] for row in selected}
        self.assertIn("tx-0", selected_txs)
        self.assertIn("tx-8", selected_txs)
        self.assertEqual(len(selected), 8)

    def test_owner_probe_promotes_only_a_consistent_controller(self) -> None:
        import scripts.alpha_project_watch as project

        owner = "0x" + "1" * 40
        encoded_owner = "0x" + owner[2:].rjust(64, "0")
        with mock.patch.object(project, "rpc_call", return_value=encoded_owner):
            result = project.token_controller("bsc", "0x" + "2" * 40)
        self.assertEqual(result["state"], "verified_token_controller")
        self.assertEqual(result["address"], owner)
        self.assertEqual(result["identity_status"], "verified")

        values = iter(
            [
                "0x" + ("0x" + "3" * 40)[2:].rjust(64, "0"),
                "0x" + ("0x" + "4" * 40)[2:].rjust(64, "0"),
            ]
        )
        with mock.patch.object(project, "rpc_call", side_effect=lambda *args: next(values)):
            conflict = project.token_controller("bsc", "0x" + "2" * 40)
        self.assertEqual(conflict["state"], "conflicting_owner_selectors")
        self.assertNotIn("address", conflict)

    def test_owner_probe_distinguishes_renounced_and_conflicting_zero(self) -> None:
        import scripts.alpha_project_watch as project

        zero = "0x" + "0" * 64
        owner = "0x" + "1" * 40
        encoded_owner = "0x" + owner[2:].rjust(64, "0")
        with mock.patch.object(project, "rpc_call", side_effect=[zero, encoded_owner]):
            conflict = project.token_controller("bsc", "0x" + "2" * 40)
        self.assertEqual(conflict["state"], "conflicting_owner_selectors")

        with mock.patch.object(project, "rpc_call", return_value=zero):
            renounced = project.token_controller("bsc", "0x" + "2" * 40)
        self.assertEqual(renounced["state"], "owner_renounced")
        self.assertEqual(renounced["identity_status"], "verified_no_controller")

    def test_owner_probe_conflict_is_not_hidden_by_configured_addresses(self) -> None:
        import scripts.alpha_project_watch as project

        configured = "0x" + "5" * 40
        item = {
            "project_operator_probe": "owner",
            "watch_addresses": [
                {
                    "chain": "bsc",
                    "address": configured,
                    "role": "candidate",
                }
            ],
        }
        with mock.patch.object(
            project,
            "token_controller",
            return_value={
                "state": "conflicting_owner_selectors",
                "identity_status": "unattributed",
            },
        ):
            rows, state = project.effective_watch_addresses(
                item,
                "bsc",
                "0x" + "2" * 40,
            )

        self.assertEqual([row["address"] for row in rows], [configured])
        self.assertEqual(state, "conflicting_owner_selectors")

    def test_owner_probe_verifies_a_matching_configured_address(self) -> None:
        import scripts.alpha_project_watch as project

        owner = "0x" + "1" * 40
        item = {
            "project_operator_probe": "owner",
            "watch_addresses": [
                {
                    "chain": "bsc",
                    "address": owner,
                    "role": "candidate",
                    "identity_status": "candidate",
                }
            ],
        }
        with mock.patch.object(
            project,
            "token_controller",
            return_value={
                "state": "verified_token_controller",
                "address": owner,
                "control_scope": "token",
                "identity_status": "verified",
                "attribution": "canonical_owner_call",
            },
        ):
            rows, state = project.effective_watch_addresses(
                item,
                "bsc",
                "0x" + "2" * 40,
            )

        self.assertEqual(state, "verified_token_controller")
        self.assertEqual(rows[0]["identity_status"], "verified")
        self.assertEqual(rows[0]["control_scope"], "token")

    def test_configured_function_addresses_keep_their_scope(self) -> None:
        import scripts.alpha_project_watch as project

        rows = project.extract_watch_addresses(
            {
                "watch_addresses": [
                    {
                        "chain": "bsc",
                        "address": "0x" + "1" * 40,
                        "role": "pool_manager",
                    },
                    {
                        "chain": "bsc",
                        "address": "0x" + "2" * 40,
                        "role": "event_distribution",
                    },
                ]
            },
            "bsc",
        )

        self.assertEqual(rows[0]["control_scope"], "pool")
        self.assertEqual(rows[1]["control_scope"], "distribution")
        self.assertTrue(all(row["identity_status"] == "functional_only" for row in rows))

    def test_controller_inbound_is_neutral_and_outbound_is_risk(self) -> None:
        import scripts.alpha_project_watch as project

        base = {
            "type": "TOKEN_TRANSFER",
            "identity_status": "verified",
            "control_scope": "token",
            "level": "HIGH",
        }
        contracts = [
            {
                "watch_address_count": 1,
                "operator_attribution_state": "verified_token_controller",
            }
        ]
        inbound = project.analyze_project(
            {"symbol": "AEON"},
            contracts,
            [],
            [],
            [{**base, "watched_direction": "in"}],
        )
        outbound = project.analyze_project(
            {"symbol": "AEON"},
            contracts,
            [],
            [],
            [{**base, "watched_direction": "out"}],
        )

        self.assertIn("收到 token", inbound["conclusion"])
        self.assertNotIn("降低风险", inbound["spot_action"])
        self.assertIn("降低风险", outbound["spot_action"])

    def test_project_first_scan_establishes_a_baseline_without_history_alerts(self) -> None:
        import scripts.alpha_project_watch as project

        alerts = project.build_contract_alerts(
            "AEON",
            "bsc",
            "0x" + "1" * 40,
            0,
            [
                {
                    "block": 100,
                    "tx": "0x" + "2" * 64,
                    "from": "0x" + "3" * 40,
                    "to": "0x" + "4" * 40,
                    "amount": "600000",
                }
            ],
            [
                {
                    "address": "0x" + "3" * 40,
                    "delta": "-600000",
                    "balance_token": "AEON",
                }
            ],
            [],
        )

        self.assertEqual(alerts, [])

    def test_project_log_gap_keeps_previous_checkpoint_and_balances(self) -> None:
        from decimal import Decimal

        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        calls: list[tuple[int, int]] = []

        def fetch(chain, method, params):
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            bounds = (
                int(query["fromBlock"], 16),
                int(query["toBlock"], 16),
            )
            calls.append(bounds)
            if bounds == (103, 104):
                raise RuntimeError("private-provider-secret")
            return [
                {
                    "blockNumber": hex(bounds[0]),
                    "transactionHash": "0x" + "3" * 64,
                    "logIndex": "0x0",
                }
            ]

        item = {
            "watch_addresses": [
                {
                    "chain": "bsc",
                    "address": watched,
                    "role": "token_controller",
                }
            ]
        }
        previous_balances = {
            ("AEON", "bsc", token, watched): Decimal("7"),
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_PROJECT_LOG_CHUNK_BLOCKS": "2"},
            ),
            mock.patch.object(project, "latest_block", return_value=104),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(project, "rpc_call", side_effect=fetch),
            mock.patch.object(
                project,
                "build_balances",
                side_effect=AssertionError("current balances must not be queried"),
            ),
        ):
            result = project.build_contract(
                "AEON",
                {"chain": "bsc", "address": token, "confidence": "high"},
                item,
                {("AEON", "bsc", token): 100},
                previous_balances,
                finality=0,
                lookback=10,
            )

        self.assertEqual(calls, [(101, 102), (101, 102), (103, 104)])
        self.assertEqual(result["raw_latest_block"], 104)
        self.assertEqual(result["latest_block"], 100)
        self.assertEqual(result["previous_latest_block"], 100)
        self.assertEqual(result["balances"][0]["balance"], "7")
        self.assertEqual(result["balances"][0]["delta"], "")
        self.assertEqual(result["recent_transfers"], [])
        self.assertEqual(result["alerts"], [])
        self.assertEqual(result["log_error_count"], 1)
        self.assertNotIn(
            "private-provider-secret",
            " ".join(result["log_errors"]),
        )

    def test_project_attribution_gap_has_a_stable_alert_key(self) -> None:
        import scripts.alpha_project_watch as project

        keys = project.alert_keys(
            [
                {
                    "type": "ATTRIBUTION_GAP",
                    "symbol": "AEON",
                    "states": ["owner_unresolved"],
                    "contracts": ["0x" + "1" * 40],
                }
            ]
        )

        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].startswith("attribution_gap|AEON|owner_unresolved|"))

    def test_market_sell_stays_unattributed_without_identity_evidence(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        event = {
            "quote": {"symbol": "USDT"},
        }
        rows = [
            {
                "seller": "0x" + "5" * 40,
                "got_quote": "600000",
                "seller_control_scope": "unknown",
                "seller_identity_status": "unattributed",
            }
        ]
        analysis = intraday.analyze_rows(event, rows, 1, 2, 1, 1)
        self.assertEqual(analysis["unattributed_sell_quote"], "600000")
        self.assertEqual(analysis["verified_controller_sell_quote"], "0")
        self.assertIn("来源待归属", analysis["operator_behavior"])

    def test_failed_receipt_cannot_become_a_sell(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        event = {"chain": "bsc"}
        with mock.patch.object(
            intraday.opening,
            "quick_rpc_call",
            return_value={"status": "0x0", "logs": []},
        ):
            self.assertIsNone(intraday.summarize_flow_tx(event, "0x" + "6" * 64, {}))

    def test_health_rejects_limited_intraday_coverage(self) -> None:
        from scripts.runtime_health_watch import output_row_coverage_issue

        detail = output_row_coverage_issue(
            "intraday",
            {
                "status": "scanned",
                "analysis": {"scan_limited": True},
                "transfer_coverage": {
                    "state": "partial_rpc_error",
                    "complete": False,
                },
            },
        )
        self.assertEqual(detail, "intraday transfer coverage=partial_rpc_error")

    def test_limited_intraday_receipts_are_report_only(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
        )

        row = {
            "status": "scanned",
            "analysis": {
                "scan_limited": True,
                "net_buy_quote": "50000",
            },
            "transfer_coverage": {
                "state": "requested_window_complete",
                "complete": True,
            },
        }
        self.assertEqual(intraday.event_alert_keys({"symbol": "AEON", **row}), [])
        self.assertEqual(output_row_coverage_issue("intraday", row), "")
        self.assertEqual(
            output_row_coverage_warning("intraday", row),
            "intraday receipt scan limited; complete transfer evidence only",
        )
        self.assertEqual(
            intraday.event_alert_keys(
                {
                    "symbol": "AEON",
                    "analysis": {
                        "scan_limited": False,
                        "net_buy_quote": "50000",
                    },
                    "transfer_coverage": {
                        "state": "partial_rpc_error",
                        "complete": False,
                    },
                }
            ),
            [],
        )

    def test_intraday_receipt_coverage_guard_detects_caps_and_missing_receipts(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        event = {
            "symbol": "AEON",
            "chain": "bsc",
            "token": {"address": "0x" + "1" * 40, "decimals": 8},
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "latest_block": 200,
            "opening_block": 100,
        }
        strong_analysis = {
            "direction": "偏空",
            "trade_signal": "fixture signal",
            "spot_action": "fixture action",
            "perp_action": "fixture action",
            "net_buy_quote": "0",
            "net_sell_quote": "50000",
            "cex_quote_estimate": "0",
            "cex_token_deposit": "0",
            "cex_deposit_count": 0,
            "cex_gas_priming_count": 0,
        }
        quiet_analysis = {
            **strong_analysis,
            "direction": "观察",
            "trade_signal": "fixture quiet",
            "spot_action": "观察",
            "perp_action": "观察",
            "net_sell_quote": "0",
        }
        analyses = iter(
            [
                dict(strong_analysis),
                dict(strong_analysis),
                quiet_analysis,
            ]
        )
        tx_hash = "0x" + "3" * 64
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS": "0"},
            ),
            mock.patch.object(
                intraday,
                "aggregate_candidate_txs",
                side_effect=[
                    ([tx_hash], 2, 2),
                    ([tx_hash], 1, 1),
                    ([tx_hash], 1, 1),
                ],
            ),
            mock.patch.object(
                intraday,
                "token_transfer_logs_with_coverage",
                return_value=(
                    [],
                    {
                        "state": "requested_window_complete",
                        "complete": True,
                    },
                ),
            ),
            mock.patch.object(
                intraday,
                "deduplicate_transfer_logs",
                return_value=(
                    [],
                    {
                        "duplicate_log_count": 0,
                        "conflicting_duplicate_log_count": 0,
                        "missing_log_identity_count": 0,
                    },
                ),
            ),
            mock.patch.object(intraday, "runtime_cex_deposit_candidates", return_value={}),
            mock.patch.object(
                intraday,
                "collect_report_only_cex_micro_gas_samples",
                return_value={},
            ),
            mock.patch.object(intraday, "cex_withdrawal_cluster", return_value={}),
            mock.patch.object(
                intraday,
                "runtime_cex_candidate_aggregate_rows",
                return_value=[],
            ),
            mock.patch.object(
                intraday,
                "configured_cex_inflow_aggregate_rows",
                return_value=[],
            ),
            mock.patch.object(
                intraday.opening,
                "quick_rpc_call",
                side_effect=[
                    {"status": "0x1", "logs": []},
                    None,
                    {"status": "0x0", "logs": []},
                ],
            ),
            mock.patch.object(intraday, "summarize_flow_tx", return_value={}),
            mock.patch.object(
                intraday,
                "analyze_rows",
                side_effect=lambda *args: next(analyses),
            ),
        ):
            capped = intraday.scan_event(event)
            missing = intraday.scan_event(event)
            failed_transaction = intraday.scan_event(event)

        self.assertTrue(capped["analysis"]["scan_limited"])
        self.assertEqual(capped["analysis"]["selected_receipts"], 1)
        self.assertEqual(capped["analysis"]["sampled_receipts"], 1)
        self.assertEqual(capped["analysis"]["receipt_errors"], 0)
        self.assertEqual(
            capped["analysis"]["receipt_coverage"]["reasons"],
            ["candidate_selection_limit"],
        )
        self.assertEqual(intraday.event_alert_keys(capped), [])
        self.assertTrue(missing["analysis"]["scan_limited"])
        self.assertEqual(missing["analysis"]["sampled_receipts"], 0)
        self.assertEqual(missing["analysis"]["receipt_errors"], 1)
        self.assertEqual(
            missing["analysis"]["receipt_coverage"]["reasons"],
            ["receipt_error"],
        )
        self.assertEqual(intraday.event_alert_keys(missing), [])
        self.assertFalse(failed_transaction["analysis"]["scan_limited"])
        self.assertEqual(failed_transaction["analysis"]["sampled_receipts"], 1)
        self.assertEqual(failed_transaction["analysis"]["receipt_errors"], 0)
        self.assertTrue(
            failed_transaction["analysis"]["receipt_coverage"]["complete"]
        )
        self.assertEqual(intraday.event_alert_keys(failed_transaction), [])

    def test_limited_receipts_keep_complete_cex_transfer_evidence(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        source = "0x" + "3" * 40
        deposit = "0x" + "4" * 40
        tx_hash = "0x" + "5" * 64
        transfer_rows = [
            {
                "token": token,
                "from": source,
                "to": deposit,
                "amount": intraday.Decimal("120000"),
                "block": 150,
                "log_index": 0,
                "tx": tx_hash,
            }
        ]
        transfer_coverage = {
            "state": "requested_window_complete",
            "complete": True,
            "requested_from_block": 100,
            "requested_to_block": 200,
            "covered_through_block": 200,
            "max_logs": 100,
            "returned_log_count": 1,
            "conflicting_duplicate_log_count": 0,
            "missing_log_identity_count": 0,
        }
        receipt_row = {
            "tx": tx_hash,
            "cex_token_deposit": "120000",
            "cex_deposit_count": 1,
        }
        event = {
            "symbol": "AEON",
            "chain": "bsc",
            "token": {"address": token, "decimals": 8, "symbol": "AEON"},
            "quote": {"address": quote, "decimals": 18, "symbol": "USDT"},
            "market_context": {"observed_price_usdt": "1"},
            "cex_deposit_addresses": [deposit],
            "latest_block": 200,
            "opening_block": 100,
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS": "0"},
            ),
            mock.patch.object(
                intraday,
                "aggregate_candidate_txs",
                return_value=([tx_hash], 1, 2),
            ),
            mock.patch.object(
                intraday,
                "token_transfer_logs_with_coverage",
                return_value=(transfer_rows, transfer_coverage),
            ),
            mock.patch.object(intraday, "runtime_cex_deposit_candidates", return_value={}),
            mock.patch.object(
                intraday,
                "collect_report_only_cex_micro_gas_samples",
                return_value={},
            ),
            mock.patch.object(intraday, "cex_withdrawal_cluster", return_value={}),
            mock.patch.object(
                intraday,
                "runtime_cex_candidate_aggregate_rows",
                return_value=[],
            ),
            mock.patch.object(
                intraday.opening,
                "quick_rpc_call",
                return_value={"status": "0x1", "logs": []},
            ),
            mock.patch.object(
                intraday,
                "summarize_flow_tx",
                return_value=receipt_row,
            ),
        ):
            result = intraday.scan_event(event)

        self.assertTrue(result["analysis"]["scan_limited"])
        self.assertEqual(
            result["analysis"]["alert_policy"],
            "complete_transfer_evidence_only",
        )
        self.assertEqual(
            result["configured_cex_inflow_aggregate_rows"][0][
                "cex_token_deposit"
            ],
            "120000",
        )
        self.assertEqual(result["analysis"]["cex_token_deposit"], "120000")
        self.assertTrue(intraday.event_alert_keys(result))

    def test_runtime_recovery_text_preserves_warning_scope(self) -> None:
        from scripts.runtime_health_watch import recovery_text

        text = recovery_text(
            {
                "generated_at": "2026-07-28T00:00:00+00:00",
                "warnings": [{"detail": "receipt coverage remains report only"}],
            }
        )
        self.assertIn("阻断性故障已解除", text)
        self.assertIn("仍有 1 项非阻断覆盖告警", text)
        self.assertIn("receipt coverage remains report only", text)
        self.assertNotIn("均恢复正常", text)

    def test_price_kline_backfill_paginates_past_one_thousand_minutes(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        calls: list[dict[str, object]] = []

        def fake_http_json(
            _url: str,
            params: dict[str, object],
            timeout: int,
        ) -> dict[str, object]:
            self.assertGreater(timeout, 0)
            calls.append(dict(params))
            page_limit = int(params["limit"])
            end_minute = (
                int(params["endTime"]) // 60000
                if "endTime" in params
                else 2499
            )
            start_minute = max(0, end_minute - page_limit + 1)
            rows = [
                [
                    str(minute * 60000),
                    "1",
                    "1",
                    "1",
                    "1",
                    "0",
                    str((minute + 1) * 60000 - 1),
                    "1",
                    "1",
                ]
                for minute in range(start_minute, end_minute + 1)
            ]
            return {"data": rows}

        with mock.patch.object(price, "http_json", side_effect=fake_http_json):
            rows = price.fetch_klines("ALPHA_1053USDT", "1m", 2500)

        self.assertEqual(len(rows), 2500)
        self.assertEqual(int(rows[0][0]), 0)
        self.assertEqual(int(rows[-1][0]), 2499 * 60000)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("endTime", calls[0])
        self.assertEqual(calls[1]["endTime"], 1500 * 60000 - 1)
        self.assertEqual(calls[2]["endTime"], 500 * 60000 - 1)
        source = (ROOT / "scripts" / "alpha_price_momentum_watch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('ALPHA_PRICE_KLINE_LIMIT", "3000"', source)

    def test_low_volume_peak_drawdown_still_alerts(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        event = {
            "symbol": "AEON",
            "analysis": {
                "direction": "高位大幅回撤",
                "window_15m": {
                    "high_pct": "1",
                    "low_pct": "-1",
                    "close_pct": "0",
                    "quote_volume": "1000",
                    "to_utc8": "2026-07-28 01:00",
                },
                "window_backfill": {
                    "high": "0.172",
                    "close": "0.089",
                    "peak_drawdown_pct": "48.25",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }
        keys = [key for key, _legacy in price.event_alert_key_pairs(event)]
        self.assertTrue(any(key.startswith("alpha_peak_drawdown|AEON|") for key in keys))

    def test_peak_drawdown_alerts_are_scoped_to_a_day(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        def event_at(value: str) -> dict[str, object]:
            return {
                "symbol": "AEON",
                "analysis": {
                    "window_15m": {
                        "high_pct": "1",
                        "low_pct": "-1",
                        "close_pct": "0",
                        "quote_volume": "1000",
                        "to_utc8": value,
                    },
                    "window_backfill": {
                        "high": "0.172",
                        "close": "0.089",
                        "peak_drawdown_pct": "48.25",
                        "to_utc8": value,
                    },
                },
            }

        first = price.event_alert_keys(event_at("2026-07-28 01:00"))[0]
        second = price.event_alert_keys(event_at("2026-07-29 01:00"))[0]
        self.assertNotEqual(first, second)

    def test_peak_drawdown_telegram_shows_risk_evidence(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        event = {
            "symbol": "AEON",
            "priority": "P1_MONITOR",
            "analysis": {
                "direction": "高位大幅回撤",
                "spot_action": "持仓降低风险",
                "venue": {"venue_class": "ALPHA_DOMINANT"},
                "window_15m": {
                    "high_pct": "1",
                    "low_pct": "-1",
                    "close_pct": "0",
                    "quote_volume": "1000",
                    "to_utc8": "2026-07-28 01:00",
                },
                "window_backfill": {
                    "high": "0.21",
                    "close": "0.09",
                    "peak_drawdown_pct": "57.14",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }

        text = price.telegram_text(
            {
                "events": [event],
                "alert_count": 1,
                "new_alert_count": 1,
                "_telegram_new_alert_keys": price.event_alert_keys(event),
            }
        )

        self.assertIn("🚨AEON", text)
        self.assertIn("峰值回撤", text)
        self.assertIn("57.14%", text)

    def test_price_push_signature_includes_alert_after_fourth_event(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        quiet = [
            {
                "symbol": f"QUIET{index}",
                "analysis": {
                    "window_15m": {},
                    "window_backfill": {},
                },
            }
            for index in range(4)
        ]
        aeon = {
            "symbol": "AEON",
            "analysis": {
                "window_15m": {
                    "to_utc8": "2026-07-28 01:00",
                    "quote_volume": "1000",
                },
                "window_backfill": {
                    "high": "0.21",
                    "close": "0.09",
                    "peak_drawdown_pct": "57.14",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }

        self.assertIn("AEON", price.push_signature({"events": quiet + [aeon]}))

    def test_holder_budget_prioritizes_recent_catalog_items(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        def item(symbol: str, digit: str, *, alpha_id: str = "") -> dict[str, object]:
            payload: dict[str, object] = {
                "symbol": symbol,
                "priority": "P1_MONITOR",
                "contracts": [
                    {
                        "chain": "bsc",
                        "address": "0x" + digit * 40,
                    }
                ],
            }
            if alpha_id:
                payload["facts"] = {"alpha_id": alpha_id}
            return payload

        config = {
            "items": [
                item("STATIC1", "1"),
                item("STATIC2", "2"),
                item("RECENT1", "3", alpha_id="ALPHA_1"),
                item("RECENT2", "4", alpha_id="ALPHA_2"),
            ]
        }
        with mock.patch.dict(os.environ, {"ALPHA_HOLDER_MAX_PROJECTS": "2"}):
            rows = holder.contract_items(config)
        self.assertEqual([row["symbol"] for row in rows], ["RECENT1", "RECENT2"])

    def test_holder_log_gap_keeps_previous_state_checkpoint(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "3" * 40
        account = "0x" + "4" * 40
        key = f"bsc:{token}"
        state = {
            "tokens": {
                key: {
                    "symbol": "AEON",
                    "chain": "bsc",
                    "address": token,
                    "decimals": 18,
                    "basis_from_block": 1,
                    "latest_block": 100,
                    "last_metrics": {
                        "raw_top10_pct": "10",
                        "effective_top10_pct": "9",
                        "raw_top10_infra_pct": "1",
                    },
                    "balances_raw": {account: "100"},
                }
            }
        }
        before = json.loads(json.dumps(state))
        calls: list[tuple[int, int]] = []

        def fetch(chain, method, params):
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            bounds = (
                int(query["fromBlock"], 16),
                int(query["toBlock"], 16),
            )
            calls.append(bounds)
            if bounds == (103, 104):
                raise RuntimeError("private-provider-secret")
            return [{"blockNumber": hex(bounds[0]), "logIndex": "0x0"}]

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_FINALITY_BLOCKS": "0",
                    "ALPHA_HOLDER_LOG_CHUNK_BLOCKS": "2",
                    "ALPHA_HOLDER_MAX_LOGS_PER_TOKEN": "100",
                },
            ),
            mock.patch.object(holder, "latest_block", return_value=104),
            mock.patch.object(holder, "rpc_call", side_effect=fetch),
            mock.patch.object(holder, "token_total_supply_raw", return_value=1000),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={"source": "none", "status": "not_configured"},
            ),
        ):
            result = holder.build_token_snapshot(
                {
                    "symbol": "AEON",
                    "name": "AEON",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )

        self.assertEqual(calls, [(101, 102), (103, 104)])
        self.assertEqual(state, before)
        self.assertEqual(result["raw_latest_block"], 104)
        self.assertEqual(result["latest_block"], 100)
        self.assertEqual(result["previous_latest_block"], 100)
        self.assertEqual(result["log_count"], 0)
        self.assertEqual(result["metrics"], before["tokens"][key]["last_metrics"])
        self.assertEqual(result["coverage_note"], "log_coverage_failed")
        self.assertEqual(result["signal"]["level"], "ERROR")
        self.assertNotIn(
            "private-provider-secret",
            " ".join(result["log_errors"]),
        )

    def test_holder_log_truncation_keeps_previous_state_checkpoint(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "5" * 40
        key = f"bsc:{token}"
        state = {
            "tokens": {
                key: {
                    "symbol": "AEON",
                    "chain": "bsc",
                    "address": token,
                    "decimals": 18,
                    "basis_from_block": 1,
                    "latest_block": 100,
                    "last_metrics": {"raw_top10_pct": "8"},
                    "balances_raw": {},
                }
            }
        }
        before = json.loads(json.dumps(state))
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_FINALITY_BLOCKS": "0",
                    "ALPHA_HOLDER_LOG_CHUNK_BLOCKS": "2",
                    "ALPHA_HOLDER_MAX_LOGS_PER_TOKEN": "1",
                },
            ),
            mock.patch.object(holder, "latest_block", return_value=104),
            mock.patch.object(
                holder,
                "rpc_call",
                return_value=[{"blockNumber": "0x65", "logIndex": "0x0"}],
            ),
            mock.patch.object(holder, "token_total_supply_raw", return_value=1000),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={"source": "none", "status": "not_configured"},
            ),
        ):
            result = holder.build_token_snapshot(
                {
                    "symbol": "AEON",
                    "name": "AEON",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )

        self.assertEqual(state, before)
        self.assertEqual(result["latest_block"], 100)
        self.assertEqual(result["log_count"], 0)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["coverage_note"], "log_coverage_truncated")
        self.assertEqual(result["metrics"], before["tokens"][key]["last_metrics"])

    def test_health_matches_the_target_project_contract_only(self) -> None:
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
            row_contract_addresses,
        )

        target = "0x" + "2" * 40
        row = {
            "contracts": [
                {
                    "address": "0x" + "1" * 40,
                    "log_error_count": 1,
                    "operator_attribution_state": "contract_error",
                },
                {
                    "address": target,
                    "log_error_count": 0,
                    "operator_attribution_state": "owner_renounced",
                },
            ]
        }
        self.assertIn(target, row_contract_addresses(row, "project"))
        self.assertEqual(
            output_row_coverage_issue("project", row, target_contract=target),
            "",
        )
        unresolved = {
            "contracts": [
                {
                    "address": target,
                    "operator_attribution_state": "owner_unresolved",
                }
            ]
        }
        self.assertEqual(
            output_row_coverage_issue(
                "project",
                unresolved,
                target_contract=target,
            ),
            "",
        )
        self.assertIn(
            "owner_unresolved",
            output_row_coverage_warning(
                "project",
                unresolved,
                target_contract=target,
            ),
        )

    def test_future_catalog_item_requires_prelaunch_contract_coverage(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        contract = "0x" + "2" * 40
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def write(relative: str, payload: dict[str, object]) -> None:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")

            write(
                "output/binance_alpha_catalog_watch/latest.json",
                {
                    "status": "pass",
                    "selected": [
                        {
                            "symbol": "AEON",
                            "chain": "bsc",
                            "contract": contract,
                            "listing_time_utc": "2099-07-28T10:00:00+00:00",
                        }
                    ],
                },
            )
            write(
                "output/binance_alpha_catalog_watch/current_watchlist.json",
                {
                    "items": [
                        {
                            "symbol": "LEGACYAEON",
                            "contracts": [{"chain": "bsc", "address": contract}],
                        }
                    ]
                },
            )
            write(
                "output/alpha_project_watch/latest.json",
                {
                    "projects": [
                        {
                            "symbol": "LEGACYAEON",
                            "contracts": [
                                {
                                    "chain": "bsc",
                                    "address": contract,
                                    "log_error_count": 0,
                                    "operator_attribution_state": "owner_renounced",
                                }
                            ],
                        }
                    ]
                },
            )
            write(
                "output/alpha_opening_block_watch/latest.json",
                {
                    "events": [
                        {
                            "symbol": "LEGACYAEON",
                            "chain": "bsc",
                            "token": {"address": contract},
                            "status": "waiting",
                        }
                    ]
                },
            )
            write(
                "output/alpha_price_momentum_watch/latest.json",
                {
                    "events": [
                        {
                            "symbol": "LEGACYAEON",
                            "chain": "bsc",
                            "contract": contract,
                            "analysis": {"direction": "观察"},
                        }
                    ]
                },
            )
            write(
                "output/alpha_holder_concentration_watch/latest.json",
                {
                    "projects": [
                        {
                            "symbol": "LEGACYAEON",
                            "chain": "bsc",
                            "address": contract,
                            "log_error_count": 0,
                            "truncated": False,
                        }
                    ]
                },
            )
            write("output/alpha_prelaunch_watch/latest.json", {"events": []})

            issues = alpha_coverage_issues(root)

        self.assertTrue(issues)
        self.assertTrue(
            all("prelaunch" in row["detail"] for row in issues),
            issues,
        )


if __name__ == "__main__":
    unittest.main()
