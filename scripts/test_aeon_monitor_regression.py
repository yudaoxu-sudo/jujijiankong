#!/usr/bin/env python3
from __future__ import annotations

import importlib
import copy
import json
import os
import subprocess
import time
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def complete_project_contract(
    address: str,
    *,
    operator_state: str = "owner_renounced",
    latest_block: int = 100,
) -> dict[str, object]:
    return {
        "chain": "bsc",
        "address": address,
        "latest_block": latest_block,
        "requested_from_block": 1,
        "target_latest_block": latest_block,
        "target_latest_block_hash": "0x" + "a" * 64,
        "covered_through_block": latest_block,
        "next_from_block": latest_block + 1,
        "coverage_complete": True,
        "transfer_coverage_complete": True,
        "scan_status": "complete",
        "decimals": 18,
        "total_supply": "1000",
        "watch_address_count": 0,
        "balance_target_count": 0,
        "watch_addresses": [],
        "operator_attribution_state": operator_state,
        "log_error_count": 0,
        "balances": [],
    }


class AeonSignalParsingRegressionTests(unittest.TestCase):
    def test_opening_sprint_inner_timeout_is_bounded_and_remapped(self) -> None:
        if os.environ.get("SNIPER_OFFLINE") == "1":
            source = (ROOT / "scripts" / "alpha_opening_sprint.sh").read_text(encoding="utf-8")
            lines = source.splitlines()
            start = lines.index("run_once() {") + 1
            end = next(
                index
                for index in range(start, len(lines))
                if lines[index] == "}"
            )
            body = [
                line.strip()
                for line in lines[start:end]
                if line.strip() and not line.lstrip().startswith("#")
            ]
            budget_if = body.index(
                "if (( trace_budget > remaining - post_seconds )); then"
            )
            self.assertEqual(
                body[budget_if : budget_if + 3],
                [
                    "if (( trace_budget > remaining - post_seconds )); then",
                    "trace_budget=$((remaining - post_seconds))",
                    "fi",
                ],
            )
            hard_timeout = body.index(
                "hard_timeout=$((trace_budget + post_seconds))",
                budget_if + 3,
            )
            timeout_if = body.index(
                'if timeout "${hard_timeout}s" "${command[@]}"; then',
                hard_timeout + 1,
            )
            self.assertEqual(
                body[timeout_if : timeout_if + 5],
                [
                    'if timeout "${hard_timeout}s" "${command[@]}"; then',
                    "return 0",
                    "else",
                    "status=$?",
                    "fi",
                ],
            )
            status_if = body.index(
                "if (( status == 124 )); then",
                timeout_if + 5,
            )
            self.assertEqual(
                body[status_if : status_if + 4],
                [
                    "if (( status == 124 )); then",
                    'echo "opening sprint inner hard timeout after ${hard_timeout}s" >&2',
                    "return 75",
                    "fi",
                ],
            )
            self.assertEqual(body[status_if + 4], 'return "$status"')
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            timeout_stub = bin_dir / "timeout"
            timeout_stub.write_text("#!/bin/sh\nexit 124\n", encoding="utf-8")
            timeout_stub.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                    "SNIPER_PROJECT_DIR": str(root),
                    "ALPHA_OPENING_SPRINT_TOTAL_SECONDS": "60",
                    "ALPHA_OPENING_SPRINT_TRACE_DEADLINE_SECONDS": "1",
                    "ALPHA_OPENING_SPRINT_POST_SECONDS": "1",
                }
            )

            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "alpha_opening_sprint.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

        self.assertEqual(result.returncode, 75)
        self.assertIn("inner hard timeout after 2s", result.stderr)

    def test_trace_deadline_is_not_downgraded_by_optional_rpc_helpers(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        address = "0x" + "1" * 40
        opening.CODE_CACHE.pop(("bsc", address), None)
        deadline = opening.OpeningTraceDeadlineExceeded("deadline")
        callbacks = [
            lambda: opening.token_meta("bsc", address, "AEON"),
            lambda: opening.has_contract_code("bsc", address),
            lambda: opening.contract_code("bsc", address),
            lambda: opening.optional_eth_call("bsc", address, "0x12345678"),
            lambda: opening.read_uint_with_override(
                "bsc",
                address,
                "0x12345678",
                {},
                5,
            ),
            lambda: opening.execute_infinity_roundtrip_call(
                {"chain": "bsc"},
                address,
                {},
                {"calldata": "0x"},
                5,
            ),
        ]

        with mock.patch.object(
            opening,
            "quick_rpc_call",
            side_effect=deadline,
        ):
            for callback in callbacks:
                with self.subTest(callback=callback):
                    with self.assertRaises(
                        opening.OpeningTraceDeadlineExceeded
                    ):
                        callback()

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

    def test_spaced_alpha_launch_announcement_is_monitor_priority(self) -> None:
        from scripts.ingest_alpha_signal import parse_signal

        parsed = parse_signal(
            "binancezh: 币安 Alpha 将在 7 月 30 日成为首个上线 Grvt（GRVT）的平台！"
        )
        compact = parse_signal("币安 Alpha 今日上线GVRT")
        prose = parse_signal("Binance Alpha listing change from July 20 to July 30")

        self.assertEqual(parsed["symbol"], "GRVT")
        self.assertEqual(parsed["priority"], "P1_MONITOR")
        self.assertEqual(parsed["facts"]["venues"], ["Binance Alpha"])
        self.assertTrue(parsed["facts"]["alpha_launch_signal"])
        self.assertEqual(compact["symbol"], "GVRT")
        self.assertEqual(compact["priority"], "P1_MONITOR")
        self.assertEqual(prose["symbol"], "")

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


    def test_prelaunch_signal_uses_typed_alpha_time_and_forecast_schema(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest
        import scripts.alpha_prelaunch_watch as prelaunch

        token = "0x" + "1" * 40
        text = f"""
$GRVT 币安 Alpha 2026年07月30日20:00上线
Booster 20:10
空投领取 21:00
OKX Bybit Coinbase 多CEX交易所 22:00
BSC: {token}
总量: 1B
初始流通: 11.43%
池子价 0.30 → 0.15
预计狙击金额: 300K
预计 bribe amount: 200K
预计均价: 0.46
https://x.com/example/status/1
"""

        parsed = ingest.parse_signal(text)
        research = parsed["prelaunch_research"]
        schedule = parsed["event_schedule"]

        self.assertEqual(parsed["times"], ["2026-07-30 20:00"])
        self.assertEqual(
            [
                row["event_type"]
                for row in schedule
                if row.get("time_utc8")
            ],
            [
                "alpha_open",
                "booster",
                "airdrop_claim",
                "cex_trade",
            ],
        )
        self.assertEqual(
            research["opening_forecast"]["buy_quote_usdt"],
            "300000",
        )
        self.assertEqual(
            research["opening_forecast"]["bribe_quote_usdt"],
            "200000",
        )
        self.assertEqual(
            research["opening_forecast"]["predicted_fill_avg_usdt"],
            "0.46",
        )
        self.assertNotIn("sniper_amount_quote", parsed["facts"])
        self.assertNotIn("bribe_amount_quote", parsed["facts"])
        self.assertEqual(
            research["pool"]["price_revisions"][0][
                "current_price_usdt"
            ],
            "0.15",
        )
        self.assertIn(
            "价0.3",
            prelaunch.valuation_text(research),
        )

    def test_prelaunch_provenance_keeps_sources_and_claim_scopes(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest

        parsed = ingest.parse_signal(
            """
source_evidence_layer: social
source_authority: context_only
source_context_only: true

$SCOPE 币安 Alpha 2026-08-01 20:00 上线
团队: 20%
池子价: 0.30
https://x.com/example/status/1
https://example.org/official
"""
        )
        research = parsed["prelaunch_research"]
        evidence = research["evidence"]
        source_refs = {
            row["source_ref"]
            for row in evidence
            if row.get("evidence_role") == "source_reference"
        }
        claim_scopes = {
            row.get("claim_scope")
            for row in evidence
            if row.get("evidence_role") == "claim_source"
        }

        self.assertEqual(
            source_refs,
            {
                "https://x.com/example/status/1",
                "https://example.org/official",
            },
        )
        self.assertEqual(
            claim_scopes,
            {
                "identity",
                "timeline",
                "pool",
                "supply",
                "venues",
                "opening_forecast",
                "valuation",
            },
        )
        self.assertTrue(
            all(row.get("context_only") is True for row in evidence)
        )
        allocation = research["supply"]["allocations"][0]
        self.assertTrue(allocation["bucket_id"])
        self.assertEqual(
            allocation["aggregation_policy"],
            "standalone",
        )
        timeline = research["timeline"][0]
        self.assertEqual(timeline["time_utc8"], "2026-08-01 20:00")
        self.assertEqual(
            timeline["time_utc"],
            "2026-08-01T12:00:00+00:00",
        )

    def test_prelaunch_normalizer_blocks_invalid_provenance(self) -> None:
        import scripts.alpha_prelaunch_research as research

        normalized = research.normalize_prelaunch_research(
            {
                "schema_version": "wrong",
                "research_status": "ready",
                "evidence": [
                    {
                        "evidence_id": "bad id",
                        "source_ref": "inline_signal:fixture",
                    }
                ],
                "identity": {
                    "verification_status": "verified",
                    "evidence_ids": ["missing"],
                },
                "missing_fields": [],
                "conflicts": [],
            }
        )

        self.assertEqual(normalized["research_status"], "blocked")
        paths = {row["path"] for row in normalized["conflicts"]}
        self.assertIn("schema_version", paths)
        self.assertIn("evidence[0].evidence_id", paths)
        self.assertIn("identity.evidence_ids", paths)

        precision = research.normalize_prelaunch_research(
            {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "ready",
                "evidence": [
                    {
                        "evidence_id": "precision-source",
                        "source_ref": "inline_signal:precision",
                    }
                ],
                "timeline": [
                    {
                        "event": "alpha_open",
                        "time_utc8": "2026-08-01 20:00",
                        "time_precision": "minute",
                        "verification_status": "unverified",
                        "evidence_ids": ["precision-source"],
                    }
                ],
                "missing_fields": [],
                "conflicts": [],
            }
        )
        self.assertEqual(precision["research_status"], "blocked")
        self.assertTrue(
            any(
                row["path"] == "timeline[0].time_precision"
                for row in precision["conflicts"]
            )
        )

    def test_estimated_prelaunch_values_do_not_become_facts_or_known_time(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest

        parsed = ingest.parse_signal(
            """
$TEST 币安 Alpha 预计 2026-08-01 20:00 上线
预计总量: 2B
预计初始流通: 20%
预计融资: 10M
预计团队: 20%
预计池子价: 0.30
"""
        )

        self.assertTrue(parsed["event_schedule"])
        self.assertEqual(
            parsed["event_schedule"][0]["time_precision"],
            "estimated",
        )
        self.assertEqual(parsed["times"], [])
        self.assertEqual(
            parsed["watchlist_proposal"]["known_times"],
            [],
        )
        self.assertNotIn("total_supply", parsed["facts"])
        self.assertNotIn("initial_float", parsed["facts"])
        self.assertNotIn("financing", parsed["facts"])
        self.assertNotIn("allocations", parsed["facts"])
        self.assertNotIn("pool_price", parsed["prices"])
        self.assertNotIn(
            "initial_price_usdt",
            parsed["prelaunch_research"]["pool"],
        )

    def test_forecast_vocabulary_and_pool_predictions_stay_non_actual(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest

        for term in (
            "预测",
            "forecast",
            "forecasted",
            "forecasting",
            "predict",
            "predicted",
            "predicting",
            "prediction",
            "projected",
            "projecting",
            "projection",
            "estimating",
        ):
            with self.subTest(term=term):
                parsed = ingest.parse_signal(
                    f"""
$TEST 币安 Alpha {term} 2026-08-01 20:00 上线
{term} 总量: 2B
{term} 池子价 0.30 -> 0.15
{term} 池子区间 0.10-0.20 100K USDT
"""
                )
                research = parsed["prelaunch_research"]
                self.assertEqual(parsed["times"], [])
                self.assertEqual(
                    parsed["watchlist_proposal"]["known_times"],
                    [],
                )
                self.assertNotIn("total_supply", parsed["facts"])
                self.assertNotIn(
                    "initial_price_usdt",
                    research["pool"],
                )
                self.assertEqual(research["pool"]["segments"], [])
                self.assertEqual(
                    research["opening_forecast"][
                        "predicted_pool_price_usdt"
                    ],
                    "0.15",
                )
                self.assertTrue(
                    research["opening_forecast"][
                        "predicted_pool_segments"
                    ]
                )
        multi_line = ingest.parse_signal(
            """
$TEST 币安 Alpha 预测如下：
2026-08-01 20:00 上线
池子价 0.30 -> 0.15
池子区间 0.10-0.20 100K USDT
"""
        )
        multi_research = multi_line["prelaunch_research"]
        self.assertEqual(multi_line["times"], [])
        self.assertEqual(
            multi_line["watchlist_proposal"]["known_times"],
            [],
        )
        self.assertNotIn(
            "initial_price_usdt",
            multi_research["pool"],
        )
        self.assertEqual(multi_research["pool"]["segments"], [])
        self.assertEqual(
            multi_research["opening_forecast"][
                "predicted_pool_price_usdt"
            ],
            "0.15",
        )
        self.assertTrue(
            multi_research["opening_forecast"][
                "predicted_pool_segments"
            ]
        )
        spaced_forecast = ingest.parse_signal(
            """
$TEST 币安 Alpha 预测如下：

2026-08-01 20:00 上线

池子价 0.30 -> 0.15

池子区间 0.10-0.20 100K USDT

实际如下：
池子价 0.40 -> 0.20
"""
        )
        spaced_research = spaced_forecast["prelaunch_research"]
        self.assertEqual(spaced_forecast["times"], [])
        self.assertEqual(
            spaced_research["opening_forecast"][
                "predicted_pool_price_usdt"
            ],
            "0.15",
        )
        self.assertEqual(
            spaced_research["pool"]["initial_price_usdt"],
            "0.2",
        )
        self.assertEqual(
            spaced_research["pool"]["segments"],
            [],
        )

    def test_clock_only_schedule_uses_nearest_preceding_date(self) -> None:
        import scripts.ingest_alpha_signal as ingest

        parsed = ingest.parse_signal(
            """
$TEST 币安 Alpha 2026-08-01 20:00 上线
Booster 20:10
2026-08-02 21:00 空投领取
同日 22:00 多CEX交易所
"""
        )
        schedule = parsed["event_schedule"]
        by_event = {
            row["event_type"]: row["time_utc8"]
            for row in schedule
            if row.get("time_utc8")
        }

        self.assertEqual(by_event["alpha_open"], "2026-08-01 20:00")
        self.assertEqual(by_event["booster"], "2026-08-01 20:10")
        self.assertEqual(by_event["airdrop_claim"], "2026-08-02 21:00")
        self.assertEqual(by_event["cex_trade"], "2026-08-02 22:00")

    def test_social_facts_cannot_overwrite_verified_existing_facts(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest

        items = [
            {
                "symbol": "SAFE",
                "facts": {
                    "total_supply": "1000000000",
                    "verification_status": "verified",
                },
            }
        ]
        proposal = {
            "symbol": "SAFE",
            "facts": {
                "total_supply": "2000000000",
                "verification_status": "unverified",
            },
        }

        merged = ingest.merge_by_symbol(items, proposal)[0]

        self.assertEqual(
            merged["facts"]["total_supply"],
            "1000000000",
        )
        self.assertEqual(
            merged["facts"]["verification_status"],
            "verified",
        )


class BinanceAlphaCatalogRegressionTests(unittest.TestCase):
    def test_exclusive_focus_keeps_only_grvt_active_after_catalog_retention(
        self,
    ) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        current = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
        grvt_address = "0x" + "1" * 40
        aeon_address = "0x" + "2" * 40
        static = {
            "monitoring_policy": {
                "mode": "exclusive_symbols",
                "symbols": ["GRVT"],
            },
            "items": [
                {
                    "symbol": "GRVT",
                    "priority": "P0_DEEP_REVIEW",
                    "active_monitoring": True,
                    "contracts": [
                        {"chain": "bsc", "address": grvt_address}
                    ],
                },
                {
                    "symbol": "AEON",
                    "priority": "P1_MONITOR",
                    "active_monitoring": False,
                    "contracts": [
                        {"chain": "bsc", "address": aeon_address}
                    ],
                },
            ],
        }
        previous = {
            "items": [
                {
                    "symbol": "AEON",
                    "active_monitoring": True,
                    "contracts": [
                        {"chain": "bsc", "address": aeon_address}
                    ],
                    "facts": {
                        "alpha_id": "ALPHA_AEON",
                        "listing_time_utc": "2026-07-28T01:00:00+00:00",
                    },
                }
            ]
        }
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_OLD",
                    "symbol": "OLD",
                    "chainId": "56",
                    "contractAddress": "0x" + "3" * 40,
                    "listingTime": 1,
                }
            ],
        }

        payload, selected = catalog.build_runtime_watchlist(
            static,
            response,
            current=current,
            lookback_hours=168,
            lookahead_hours=48,
            previous_runtime_watchlist=previous,
            retention_days=30,
        )
        active = [
            item["symbol"]
            for item in payload["items"]
            if item.get("active_monitoring") is not False
        ]
        summary = catalog.public_summary(
            current=current,
            token_count=0,
            selected=selected,
            runtime_watchlist=payload,
            lookback_hours=168,
            lookahead_hours=48,
            max_selected=64,
        )

        self.assertEqual(active, ["GRVT"])
        self.assertEqual(payload["active_monitoring_symbols"], ["GRVT"])
        self.assertFalse(summary["selected"][0]["active_monitoring"])
        self.assertTrue(catalog.watchlist_policy_compatible(payload, static))
        tampered = copy.deepcopy(payload)
        next(
            item for item in tampered["items"] if item["symbol"] == "AEON"
        )["active_monitoring"] = True
        self.assertFalse(catalog.watchlist_policy_compatible(tampered, static))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            static_path = root / "static.json"
            runtime_path = root / "runtime.json"
            static_path.write_text(json.dumps(static), encoding="utf-8")
            runtime_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                catalog.watchlist_policy_status(runtime_path, static_path),
                "runtime_valid",
            )
            self.assertEqual(
                catalog.watchlist_policy_status(static_path, static_path),
                "runtime_valid",
            )
            os.utime(runtime_path, (1, 1))
            self.assertEqual(
                catalog.watchlist_policy_status(
                    runtime_path,
                    static_path,
                    1,
                ),
                "runtime_stale",
            )
            runtime_path.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertEqual(
                catalog.watchlist_policy_status(runtime_path, static_path),
                "runtime_invalid",
            )

    def test_verified_pool_replaces_same_window_catalog_placeholder(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        placeholder = {
            "chain": "bsc",
            "pool_id": "",
            "start_time_utc8": "2026-07-30 20:00",
            "source": "binance_alpha_public_catalog",
        }
        verified = {
            "chain": "bsc",
            "pool_id": "0x" + "1" * 64,
            "start_time_utc8": "2026-07-30 20:00",
            "source": "telegram_signal_receipt_verified",
        }

        merged = catalog.merge_pool_rows([placeholder], [verified])
        times = catalog.merge_known_time_rows(
            [{"time": "2026-07-30 20:00", "reason": "catalog"}],
            [{"time": "2026-07-30 20:00", "reason": "verified_pool"}],
        )

        self.assertEqual(merged, [verified])
        self.assertEqual(
            times,
            [{"time": "2026-07-30 20:00", "reason": "verified_pool"}],
        )

    def test_signal_candidate_loader_excludes_context_only_artifacts(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        parsed = {
            "generated_at": "2026-07-30T01:00:00+00:00",
            "symbol": "SAFE",
            "title": "BN Alpha pool opening time",
            "priority": "P0_DEEP_REVIEW",
            "times": ["2026-07-30 20:00"],
            "txs": ["0x" + "1" * 64],
            "pool_ids": ["0x" + "2" * 64],
            "watchlist_proposal": {
                "contracts": [{"chain": "bsc", "address": "0x" + "3" * 40}]
            },
            "chain_enrichment": [{"status": "ok"}],
            "source_policy": {
                "authority": "social_discovery",
                "context_only": False,
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "safe.json").write_text(
                json.dumps(parsed),
                encoding="utf-8",
            )
            private = json.loads(json.dumps(parsed))
            private["source_policy"] = {
                "authority": "context_only",
                "context_only": True,
            }
            (root / "private.json").write_text(
                json.dumps(private),
                encoding="utf-8",
            )
            for name, policy in (
                ("missing.json", {"authority": "social_discovery"}),
                (
                    "string_false.json",
                    {
                        "authority": "social_discovery",
                        "context_only": "false",
                    },
                ),
                (
                    "authority_conflict.json",
                    {
                        "authority": "context_only",
                        "context_only": False,
                    },
                ),
            ):
                malformed = json.loads(json.dumps(parsed))
                malformed["source_policy"] = policy
                (root / name).write_text(
                    json.dumps(malformed),
                    encoding="utf-8",
                )

            projects = catalog.load_signal_candidate_projects(root)

        self.assertEqual(len(projects), 1)
        self.assertEqual(
            projects[0]["_candidate_provenance"],
            "single_signal_artifact",
        )
        self.assertEqual(projects[0]["symbol"], "SAFE")

    def test_signal_candidate_preserves_prelaunch_research_fields(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        parsed = {
            "generated_at": "2026-07-30T01:00:00+00:00",
            "symbol": "RESEARCH",
            "title": "Binance Alpha RESEARCH opening",
            "priority": "P0_DEEP_REVIEW",
            "times": ["2026-07-30 20:00"],
            "txs": ["0x" + "1" * 64],
            "pool_ids": ["0x" + "2" * 64],
            "watchlist_proposal": {
                "contracts": [
                    {
                        "chain": "bsc",
                        "address": "0x" + "3" * 40,
                    }
                ]
            },
            "chain_enrichment": [{"status": "ok"}],
            "source_policy": {
                "authority": "social_discovery",
                "context_only": False,
            },
            "prelaunch_research": {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "partial",
                "evidence": [
                    {
                        "evidence_id": "social-1",
                        "evidence_kind": "social",
                        "verification_status": "unverified",
                    }
                ],
                "missing_fields": ["pool.segments"],
            },
            "market_context": {"premarket_reference_price_usdt": "0.20"},
            "event_distributions": [
                {"name": "Binance Alpha", "share_of_total": "1%"}
            ],
        }

        project = catalog.signal_candidate_project(
            parsed,
            artifact_name="research.json",
            updated_at="2026-07-30T01:00:00+00:00",
        )

        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual(
            project["prelaunch_research"]["schema_version"],
            "alpha_prelaunch_research.v1",
        )
        self.assertEqual(
            project["market_context"]["premarket_reference_price_usdt"],
            "0.20",
        )
        self.assertEqual(
            project["event_distributions"][0]["name"],
            "Binance Alpha",
        )

    def test_conflicting_signal_opening_times_fail_closed(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        contract = "0x" + "1" * 40
        quote = "0x55d398326f99059ff775485246999027b3197955"
        tx_hash = "0x" + "2" * 64
        pool_id = "0x" + "3" * 64
        base = {
            "_candidate_provenance": "single_signal_artifact",
            "project_key": "signal_artifact:first",
            "symbol": "TIME",
            "titles": ["BN Alpha pool opening time"],
            "updated_at": "2026-07-30T01:00:00+00:00",
            "last_priority": "P0_DEEP_REVIEW",
            "contracts": [{"chain": "bsc", "address": contract}],
            "addresses": [],
            "txs": [tx_hash],
            "times": ["2026-07-30 20:00"],
            "pool_ids": [pool_id],
            "facts": {},
            "sources": [{"authority": "social_discovery", "context_only": False}],
            "chain_enrichment": [
                {
                    "status": "ok",
                    "chain": "bsc",
                    "tx_hash": tx_hash,
                    "pool_id": pool_id,
                    "token0": {"address": contract, "symbol": "TIME"},
                    "token1": {"address": quote, "symbol": "USDT"},
                    "raw_fields": {},
                }
            ],
        }
        conflicting = json.loads(json.dumps(base))
        conflicting["project_key"] = "signal_artifact:second"
        conflicting["updated_at"] = "2026-07-30T02:00:00+00:00"
        conflicting["times"] = ["2026-07-30 21:00"]

        ready, pending = catalog.verified_registry_candidates(
            {"projects": [base, conflicting]},
            current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
            retention_days=30,
        )

        self.assertEqual(ready, [])
        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["reasons"],
            ["conflicting_single_signal_opening_times"],
        )
        self.assertEqual(
            pending[0]["conflicting_opening_times_utc"],
            [
                "2026-07-30T12:00:00+00:00",
                "2026-07-30T13:00:00+00:00",
            ],
        )

    def test_official_and_signal_opening_time_conflict_fails_closed(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        contract = "0x" + "1" * 40
        signal = {
            "symbol": "CLASH",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": contract}],
            "known_times": [
                {"time": "2026-07-30 21:00", "reason": "verified_prelaunch_pool"}
            ],
            "facts": {
                "source": "telegram_signal_receipt_verified",
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }
        official_time = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_CLASH",
                    "symbol": "CLASH",
                    "name": "Clash",
                    "chainId": "56",
                    "contractAddress": contract,
                    "listingTime": int(official_time.timestamp() * 1000),
                }
            ],
        }
        with mock.patch.object(
            catalog,
            "verified_registry_candidates",
            return_value=([signal], []),
        ):
            payload, selected = catalog.build_runtime_watchlist(
                {"items": []},
                response,
                current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
                lookback_hours=72,
                lookahead_hours=48,
            )

        self.assertEqual(len(selected), 1)
        self.assertEqual(payload["registry_selected_count"], 0)
        self.assertEqual(payload["registry_pending_count"], 1)
        self.assertEqual(
            payload["registry_pending"][0]["reasons"],
            ["official_signal_opening_time_conflict"],
        )
        self.assertEqual(
            payload["items"][0]["known_times"],
            [{"time": "2026-07-30 20:00", "reason": "binance_alpha_listing_time"}],
        )

    def test_receipt_verified_registry_candidate_enters_runtime_watchlist(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        contract = "0x46f2564e0fa8248d15125e7e54173cfbdef91be7"
        quote = "0x55d398326f99059ff775485246999027b3197955"
        tx_hash = "0x" + "1" * 64
        pool_id = "0x" + "2" * 64
        registry = {
            "projects": [
                {
                    "_candidate_provenance": "single_signal_artifact",
                    "project_key": f"contract:{contract}",
                    "symbol": "GRVT",
                    "titles": ["[BN Alpha 新Hook] 设置池子开盘时间"],
                    "updated_at": "2026-07-29T15:15:02+00:00",
                    "last_priority": "P0_DEEP_REVIEW",
                    "contracts": [
                        {"chain": "bsc", "address": contract}
                    ],
                    "addresses": [
                        {
                            "chain": "bsc",
                            "address": "0x" + "3" * 40,
                            "label_hint": "pool_hook_or_operator",
                        }
                    ],
                    "txs": [tx_hash],
                    "times": ["2026-07-30 20:00"],
                    "pool_ids": [pool_id],
                    "facts": {"venues": ["Binance Alpha"]},
                    "prelaunch_research": {
                        "schema_version": "alpha_prelaunch_research.v1",
                        "research_status": "partial",
                        "evidence": [
                            {
                                "evidence_id": "social-1",
                                "evidence_kind": "social",
                                "verification_status": "unverified",
                            }
                        ],
                        "timeline": [
                            {
                                "event": "listing",
                                "time_utc": "2026-07-30T12:00:00+00:00",
                                "verification_status": "unverified",
                                "evidence_ids": ["social-1"],
                            }
                        ],
                        "missing_fields": ["pool.segments"],
                    },
                    "market_context": {
                        "premarket_reference_price_usdt": "0.20"
                    },
                    "event_distributions": [
                        {
                            "name": "Binance Alpha",
                            "share_of_total": "1%",
                        }
                    ],
                    "sources": [
                        {
                            "authority": "social_discovery",
                            "context_only": False,
                        }
                    ],
                    "chain_enrichment": [
                        {
                            "status": "ok",
                            "chain": "bsc",
                            "tx_hash": tx_hash,
                            "block": 112774138,
                            "pool_id": pool_id,
                            "token0": {
                                "address": contract,
                                "symbol": "GRVT",
                            },
                            "token1": {
                                "address": quote,
                                "symbol": "USDT",
                            },
                            "raw_fields": {"hook": "0x" + "3" * 40},
                        }
                    ],
                }
            ]
        }
        second = json.loads(json.dumps(registry["projects"][0]))
        second["project_key"] = "signal_artifact:second"
        second_tx = "0x" + "5" * 64
        second_pool = "0x" + "6" * 64
        second["txs"] = [second_tx]
        second["pool_ids"] = [second_pool]
        second["chain_enrichment"][0]["tx_hash"] = second_tx
        second["chain_enrichment"][0]["pool_id"] = second_pool
        registry["projects"].append(second)
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_OLD",
                    "symbol": "OLD",
                    "chainId": "56",
                    "contractAddress": "0x" + "4" * 40,
                    "listingTime": 1700000000000,
                }
            ],
        }

        payload, selected = catalog.build_runtime_watchlist(
            {"items": []},
            response,
            current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
            lookback_hours=72,
            lookahead_hours=48,
            project_registry=registry,
        )

        self.assertEqual(selected, [])
        self.assertEqual(payload["registry_selected_count"], 1)
        self.assertEqual(payload["registry_pending_count"], 0)
        item = payload["items"][0]
        self.assertEqual(item["symbol"], "GRVT")
        self.assertEqual(item["contracts"][0]["address"], contract)
        self.assertEqual(
            {row["pool_id"] for row in item["pool_ids"]},
            {pool_id, second_pool},
        )
        self.assertEqual(item["pool_ids"][0]["start_time_utc8"], "2026-07-30 20:00")
        self.assertEqual(
            item["facts"]["opening_anchor_status"],
            "verified_prelaunch_pool",
        )
        self.assertEqual(
            item["facts"]["lifecycle_first_seen_at"],
            "2026-07-29T15:15:02+00:00",
        )
        self.assertEqual(
            item["prelaunch_research"]["schema_version"],
            "alpha_prelaunch_research.v1",
        )
        self.assertEqual(
            item["market_context"]["premarket_reference_price_usdt"],
            "0.20",
        )
        self.assertEqual(
            item["event_distributions"][0]["share_of_total"],
            "1%",
        )
        self.assertEqual(item["opening_max_logs"], 30000)
        self.assertEqual(item["project_lookback_blocks"], 50000)

    def test_lower_grade_research_conflict_keeps_verified_value_and_blocks(
        self,
    ) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        existing = {
            "symbol": "SAFE",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "1" * 40}
            ],
            "prelaunch_research": {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "ready",
                "pool": {
                    "verification_status": "verified",
                    "initial_price_usdt": "0.10",
                    "evidence_ids": ["onchain-1"],
                },
                "missing_fields": [],
                "conflicts": [],
            },
            "market_context": {
                "premarket_reference_price_usdt": "0.20"
            },
            "event_distributions": [
                {"name": "Alpha", "share_of_total": "1%"}
            ],
        }
        candidate = {
            "symbol": "SAFE",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "1" * 40}
            ],
            "prelaunch_research": {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "partial",
                "pool": {
                    "verification_status": "unverified",
                    "initial_price_usdt": "0.30",
                    "evidence_ids": ["social-1"],
                },
                "missing_fields": ["supply.allocations"],
                "conflicts": [],
            },
            "market_context": {"bridge_open_reported": True},
            "event_distributions": [
                {"name": "Booster", "share_of_total": "0.2%"}
            ],
        }

        merged = catalog.merge_item(existing, candidate)
        research = merged["prelaunch_research"]

        self.assertEqual(research["pool"]["initial_price_usdt"], "0.10")
        self.assertEqual(
            research["pool"]["verification_status"],
            "conflicted",
        )
        self.assertEqual(research["research_status"], "blocked")
        self.assertTrue(
            any(
                row.get("path") == "pool.initial_price_usdt"
                for row in research["conflicts"]
            )
        )
        self.assertEqual(
            merged["market_context"]["premarket_reference_price_usdt"],
            "0.20",
        )
        self.assertTrue(merged["market_context"]["bridge_open_reported"])
        self.assertEqual(
            {row["name"] for row in merged["event_distributions"]},
            {"Alpha", "Booster"},
        )

    def test_research_merge_keeps_same_chain_venues_distinct(self) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        research = {
            "schema_version": "alpha_prelaunch_research.v1",
            "research_status": "partial",
            "supply": {
                "cross_chain": [
                    {
                        "chain": "eth",
                        "venue": "OKX",
                        "inventory_percent": "0.8",
                    },
                    {
                        "chain": "eth",
                        "venue": "Bybit",
                        "inventory_percent": "0.25",
                    },
                ]
            },
            "missing_fields": ["cross_chain.receipts"],
            "conflicts": [],
        }

        merged = catalog.merge_prelaunch_research(
            research,
            research,
        )
        rows = merged["supply"]["cross_chain"]

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["venue"] for row in rows},
            {"OKX", "Bybit"},
        )

    def test_research_status_never_ready_with_missing_or_conflicts(
        self,
    ) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        ready = {
            "schema_version": "alpha_prelaunch_research.v1",
            "research_status": "ready",
            "evidence": [
                {
                    "evidence_id": "fixture-ready",
                    "source_ref": "inline_signal:ready",
                }
            ],
            "missing_fields": [],
            "conflicts": [],
        }
        partial = {
            "schema_version": "alpha_prelaunch_research.v1",
            "research_status": "partial",
            "evidence": [
                {
                    "evidence_id": "fixture-ready",
                    "source_ref": "inline_signal:ready",
                }
            ],
            "missing_fields": ["pool.position_ids"],
            "conflicts": [],
        }
        conflicted = {
            "schema_version": "alpha_prelaunch_research.v1",
            "research_status": "partial",
            "evidence": [
                {
                    "evidence_id": "fixture-conflict",
                    "source_ref": "inline_signal:conflict",
                }
            ],
            "missing_fields": [],
            "conflicts": [
                {
                    "path": "supply.total_supply",
                    "detail": "conflict",
                }
            ],
        }

        merged = catalog.merge_prelaunch_research(ready, partial)
        self.assertEqual(merged["research_status"], "partial")
        self.assertTrue(merged["missing_fields"])
        normalized = catalog.merge_prelaunch_research({}, conflicted)
        self.assertEqual(normalized["research_status"], "blocked")

    def test_catalog_consumer_blocks_invalid_nested_provenance(self) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        normalized = catalog.merge_prelaunch_research(
            {},
            {
                "schema_version": "wrong",
                "research_status": "ready",
                "evidence": [
                    {
                        "evidence_id": "fixture-source",
                        "source_ref": "",
                    }
                ],
                "pool": {
                    "verification_status": "conflicted",
                    "evidence_ids": ["missing"],
                },
                "timeline": 1,
                "sniper_curve": 2,
                "valuation": 3,
                "missing_fields": [],
                "conflicts": [],
            },
        )

        self.assertEqual(normalized["research_status"], "blocked")
        paths = {row["path"] for row in normalized["conflicts"]}
        self.assertIn("schema_version", paths)
        self.assertIn("evidence[0].source_ref", paths)
        self.assertIn("pool", paths)
        self.assertIn("pool.evidence_ids", paths)
        self.assertIn("timeline", paths)
        self.assertIn("sniper_curve", paths)
        self.assertIn("valuation", paths)

        empty_shell = {
            "schema_version": "alpha_prelaunch_research.v1",
            "research_status": "ready",
            "evidence": [
                {
                    "evidence_id": "shell-source",
                    "source_ref": "inline_signal:shell",
                }
            ],
            "timeline": [{}],
            "pool": {"segments": [{}]},
            "supply": {
                "allocations": [{}],
                "cross_chain": [{}],
            },
            "venues": {"cex": [{}]},
            "actors": {"market_makers": [{}]},
            "sniper_curve": [{}],
            "valuation": {"anchors": [{}]},
            "sell_pressure_scenarios": [{}],
            "missing_fields": [],
            "conflicts": [],
        }
        shell_catalog = catalog.merge_prelaunch_research(
            {},
            empty_shell,
        )
        self.assertEqual(
            shell_catalog["research_status"],
            "blocked",
        )
        import scripts.alpha_prelaunch_watch as prelaunch

        shell_watch = prelaunch.prepare_prelaunch_research(
            {"prelaunch_research": empty_shell}
        )
        self.assertEqual(
            shell_watch["research_status"],
            "blocked",
        )
        shell_paths = {
            row["path"]
            for row in shell_watch["conflicts"]
        }
        for required_path in (
            "timeline[0]",
            "pool.segments[0]",
            "supply.allocations[0]",
            "supply.cross_chain[0]",
            "venues.cex[0]",
            "actors.market_makers[0]",
            "sniper_curve[0]",
            "valuation.anchors[0]",
            "sell_pressure_scenarios[0]",
        ):
            self.assertIn(required_path, shell_paths)

    def test_static_launch_time_conflict_keeps_only_official_anchor(
        self,
    ) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        contract = "0x" + "4" * 40
        static = {
            "items": [
                {
                    "symbol": "GRVT",
                    "name": "GRVT",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "contracts": [
                        {"chain": "bsc", "address": contract}
                    ],
                    "known_times": [
                        {
                            "time": "2026-07-30 20:00",
                            "reason": "typed_alpha_open_social_candidate",
                        }
                    ],
                    "event_schedule": [
                        {
                            "event_type": "alpha_open",
                            "time_utc8": "2026-07-30 20:00",
                        },
                        {
                            "event_type": "booster",
                            "time_utc8": "2026-07-30 20:10",
                        },
                    ],
                    "pool_ids": [
                        {
                            "chain": "bsc",
                            "pool_id": "",
                            "start_time_utc8": "2026-07-30 20:00",
                        },
                        {
                            "chain": "bsc",
                            "pool_id": "0x" + "a" * 64,
                            "start_time_utc8": "2026-07-30 18:00",
                            "source": "receipt_verified",
                        }
                    ],
                    "facts": {
                        "listing_time_utc": "2026-07-30T12:00:00+00:00",
                        "listing_time_utc8": "2026-07-30 20:00",
                    },
                    "prelaunch_research": {
                        "schema_version": "alpha_prelaunch_research.v1",
                        "research_status": "ready",
                        "evidence": [
                            {
                                "evidence_id": "social-launch",
                                "source_ref": "https://x.com/example/status/1",
                            }
                        ],
                        "timeline": [
                            {
                                "event": "alpha_open",
                                "time_utc8": "2026-07-30 20:00",
                                "verification_status": "unverified",
                                "evidence_ids": ["social-launch"],
                            }
                        ],
                        "missing_fields": [],
                        "conflicts": [],
                    },
                }
            ]
        }
        official = datetime(
            2026,
            7,
            30,
            13,
            0,
            tzinfo=timezone.utc,
        )
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_GRVT",
                    "symbol": "GRVT",
                    "name": "GRVT",
                    "chainId": "56",
                    "contractAddress": contract,
                    "listingTime": int(official.timestamp() * 1000),
                }
            ],
        }

        payload, _ = catalog.build_runtime_watchlist(
            static,
            response,
            current=datetime(
                2026,
                7,
                30,
                4,
                0,
                tzinfo=timezone.utc,
            ),
            lookback_hours=168,
            lookahead_hours=48,
        )

        item = payload["items"][0]
        self.assertEqual(payload["static_time_conflict_count"], 1)
        self.assertEqual(
            [
                row["time"]
                for row in item["known_times"]
                if isinstance(row, dict)
            ],
            ["2026-07-30 21:00"],
        )
        self.assertEqual(
            [
                row["time_utc8"]
                for row in item["event_schedule"]
                if row.get("event_type") == "alpha_open"
            ],
            [],
        )
        self.assertEqual(
            {
                (
                    row.get("pool_id"),
                    row.get("start_time_utc8"),
                )
                for row in item["pool_ids"]
            },
            {
                ("0x" + "a" * 64, "2026-07-30 18:00"),
                ("", "2026-07-30 21:00"),
            },
        )
        self.assertEqual(
            item["facts"]["listing_time_utc8"],
            "2026-07-30 21:00",
        )
        self.assertEqual(
            item["prelaunch_research"]["research_status"],
            "blocked",
        )
        self.assertEqual(
            item["prelaunch_research"]["timeline"][0][
                "runtime_anchor_status"
            ],
            "superseded_by_official_catalog",
        )

    def test_fact_only_static_time_conflict_and_minute_precision(
        self,
    ) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        contract = "0x" + "6" * 40
        existing = {
            "symbol": "CLOCK",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": contract}],
            "facts": {
                "listing_time_utc": "2026-07-30T12:00:00+00:00",
                "listing_time_utc8": "2026-07-30 20:00",
            },
        }
        candidate = {
            "symbol": "CLOCK",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": contract}],
            "known_times": [
                {
                    "time": "2026-07-30 21:00",
                    "reason": "binance_alpha_listing_time",
                }
            ],
            "facts": {
                "source": "binance_alpha_public_catalog",
                "listing_time_utc": "2026-07-30T13:00:30+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }

        sanitized, conflict = (
            catalog.sanitize_static_launch_time_conflict(
                existing,
                candidate,
            )
        )
        self.assertIsNotNone(conflict)
        merged = catalog.merge_item(sanitized, candidate)
        self.assertEqual(
            merged["facts"]["listing_time_utc8"],
            "2026-07-30 21:00",
        )
        same_minute = {
            **existing,
            "facts": {
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }
        _, false_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                same_minute,
                candidate,
            )
        )
        self.assertIsNone(false_conflict)

        utc8_wrong = {
            **existing,
            "facts": {
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 20:00",
            },
        }
        sanitized_wrong, utc8_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                utc8_wrong,
                candidate,
            )
        )
        self.assertIsNotNone(utc8_conflict)
        merged_wrong = catalog.merge_item(
            sanitized_wrong,
            candidate,
        )
        self.assertEqual(
            merged_wrong["facts"]["listing_time_utc8"],
            "2026-07-30 21:00",
        )

        invalid_utc = {
            **existing,
            "facts": {
                "listing_time_utc": "invalid",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }
        sanitized_invalid, invalid_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                invalid_utc,
                candidate,
            )
        )
        self.assertIsNotNone(invalid_conflict)
        merged_invalid = catalog.merge_item(
            sanitized_invalid,
            candidate,
        )
        self.assertEqual(
            merged_invalid["facts"]["listing_time_utc"],
            "2026-07-30T13:00:30+00:00",
        )
        self.assertIsNotNone(catalog.item_listing_time(merged_invalid))

        event_inconsistent = {
            "symbol": "CLOCK",
            "event_schedule": [
                {
                    "event_type": "alpha_open",
                    "venue": "Binance Alpha",
                    "time_utc": "2026-07-30T13:00:00+00:00",
                    "time_utc8": "2026-07-30 20:00",
                    "time_precision": "exact",
                }
            ],
        }
        sanitized_event, event_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                event_inconsistent,
                candidate,
            )
        )
        self.assertIsNotNone(event_conflict)
        self.assertEqual(sanitized_event["event_schedule"], [])

        text_inconsistent = {
            "symbol": "CLOCK",
            "event_schedule": [
                {
                    "event_type": "alpha_open",
                    "venue": "Binance Alpha",
                    "time_utc": "2026-07-30T13:00:00+00:00",
                    "time_utc8": "2026-07-30 21:00",
                    "time_text": "20:00",
                    "time_precision": "exact",
                }
            ],
        }
        sanitized_text, text_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                text_inconsistent,
                candidate,
            )
        )
        self.assertIsNotNone(text_conflict)
        self.assertEqual(sanitized_text["event_schedule"], [])

        invalid_precision = {
            "symbol": "CLOCK",
            "event_schedule": [
                {
                    "event_type": "alpha_open",
                    "venue": "Binance Alpha",
                    "time_utc": "2026-07-30T13:00:00+00:00",
                    "time_utc8": "2026-07-30 21:00",
                    "time_text": "21:00",
                    "time_precision": "minute",
                }
            ],
        }
        sanitized_precision, precision_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                invalid_precision,
                candidate,
            )
        )
        self.assertIsNotNone(precision_conflict)
        self.assertEqual(
            sanitized_precision["event_schedule"],
            [],
        )

        research_only = {
            "symbol": "CLOCK",
            "prelaunch_research": {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "ready",
                "evidence": [
                    {
                        "evidence_id": "research-clock",
                        "source_ref": "https://x.com/example/status/clock",
                    }
                ],
                "timeline": [
                    {
                        "event": "alpha_open",
                        "venue": "Binance Alpha",
                        "time_utc8": "2026-07-30 20:00",
                        "time_precision": "exact",
                        "verification_status": "unverified",
                        "evidence_ids": ["research-clock"],
                    }
                ],
                "missing_fields": [],
                "conflicts": [],
            },
        }
        sanitized_research, research_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                research_only,
                candidate,
            )
        )
        self.assertIsNotNone(research_conflict)
        self.assertEqual(
            sanitized_research["prelaunch_research"][
                "research_status"
            ],
            "blocked",
        )
        self.assertEqual(
            sanitized_research["prelaunch_research"]["timeline"][0][
                "runtime_anchor_status"
            ],
            "superseded_by_official_catalog",
        )

        invalid_known = {
            "symbol": "CLOCK",
            "known_times": [
                {
                    "time": "invalid",
                    "reason": "binance_alpha_listing_time",
                }
            ],
        }
        sanitized_known, known_conflict = (
            catalog.sanitize_static_launch_time_conflict(
                invalid_known,
                candidate,
            )
        )
        self.assertIsNotNone(known_conflict)
        self.assertEqual(sanitized_known["known_times"], [])

    def test_non_alpha_cex_listing_is_not_an_alpha_time_conflict(
        self,
    ) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        existing = {
            "symbol": "VENUE",
            "known_times": [
                {
                    "time": "2026-07-30 22:00",
                    "reason": "coinbase_listing",
                }
            ],
            "event_schedule": [
                {
                    "event_type": "listing",
                    "venue": "Coinbase",
                    "time_utc8": "2026-07-30 22:00",
                }
            ],
        }
        candidate = {
            "symbol": "VENUE",
            "facts": {
                "source": "binance_alpha_public_catalog",
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }

        sanitized, conflict = (
            catalog.sanitize_static_launch_time_conflict(
                existing,
                candidate,
            )
        )

        self.assertIsNone(conflict)
        self.assertEqual(sanitized, existing)

        self.assertEqual(
            catalog.parse_iso_time(
                "2026-07-30T13:00:00"
            ).isoformat(),
            "2026-07-30T13:00:00+00:00",
        )

    def test_chinese_alpha_listing_is_canonicalized(self) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        existing = {
            "symbol": "CNALPHA",
            "known_times": [
                {
                    "time": "2026-07-30 20:00",
                    "reason": "币安 Alpha 上线",
                }
            ],
            "event_schedule": [
                {
                    "event_type": "listing",
                    "venue": "币安 Alpha",
                    "time_utc8": "2026-07-30 20:00",
                    "time_precision": "exact",
                }
            ],
        }
        candidate = {
            "symbol": "CNALPHA",
            "facts": {
                "source": "binance_alpha_public_catalog",
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }

        sanitized, conflict = (
            catalog.sanitize_static_launch_time_conflict(
                existing,
                candidate,
            )
        )

        self.assertIsNotNone(conflict)
        self.assertEqual(sanitized["known_times"], [])
        self.assertEqual(sanitized["event_schedule"], [])

    def test_signal_ingest_time_is_superseded_by_official_catalog(
        self,
    ) -> None:
        import scripts.ingest_alpha_signal as ingest

        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        contract = "0x" + "7" * 40
        parsed = ingest.parse_signal(
            f"""
$LIVE 币安 Alpha 2026-07-30 20:00 上线
BSC: {contract}
"""
        )
        existing = parsed["watchlist_proposal"]
        self.assertEqual(
            existing["known_times"][0]["reason"],
            "signal_ingest",
        )
        candidate = {
            "symbol": "LIVE",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": contract}],
            "known_times": [
                {
                    "time": "2026-07-30 21:00",
                    "reason": "binance_alpha_listing_time",
                }
            ],
            "facts": {
                "source": "binance_alpha_public_catalog",
                "listing_time_utc": "2026-07-30T13:00:00+00:00",
                "listing_time_utc8": "2026-07-30 21:00",
            },
        }

        sanitized, conflict = (
            catalog.sanitize_static_launch_time_conflict(
                existing,
                candidate,
            )
        )
        self.assertIsNotNone(conflict)
        merged = catalog.merge_item(sanitized, candidate)
        self.assertEqual(
            [row["time"] for row in merged["known_times"]],
            ["2026-07-30 21:00"],
        )
        self.assertFalse(
            any(
                row.get("event_type") == "alpha_open"
                and row.get("time_utc8") == "2026-07-30 20:00"
                for row in merged.get("event_schedule", [])
            )
        )

    def test_unverified_or_context_only_registry_candidate_stays_pending(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        base = {
            "project_key": "symbol:WAIT",
            "symbol": "WAIT",
            "titles": ["Binance Alpha will list WAIT"],
            "updated_at": "2026-07-30T01:00:00+00:00",
            "last_priority": "P1_MONITOR",
            "contracts": [],
            "txs": [],
            "times": [],
            "pool_ids": [],
            "facts": {"venues": ["Binance Alpha"]},
            "chain_enrichment": [],
            "sources": [{"authority": "social_discovery", "context_only": False}],
        }
        context_only = {
            **base,
            "project_key": "symbol:PRIVATE",
            "symbol": "PRIVATE",
            "sources": [
                {"authority": "social_discovery", "context_only": False},
                {"authority": "context_only", "context_only": True},
            ],
        }

        ready, pending = catalog.verified_registry_candidates(
            {"projects": [base, context_only]},
            current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
            retention_days=30,
        )

        self.assertEqual(ready, [])
        by_symbol = {row["symbol"]: row["reasons"] for row in pending}
        self.assertIn("unproven_time_pool_binding", by_symbol["WAIT"])
        self.assertIn("missing_receipt_verified_alpha_pool", by_symbol["WAIT"])
        self.assertIn("missing_exact_opening_time", by_symbol["WAIT"])
        self.assertNotIn("PRIVATE", by_symbol)

    def test_aggregated_registry_evidence_cannot_claim_time_pool_binding(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        contract = "0x" + "1" * 40
        quote = "0x55d398326f99059ff775485246999027b3197955"
        tx_hash = "0x" + "2" * 64
        pool_id = "0x" + "3" * 64
        project = {
            "project_key": f"contract:{contract}",
            "symbol": "BIND",
            "titles": ["BN Alpha pool opening time"],
            "updated_at": "2026-07-30T01:00:00+00:00",
            "last_priority": "P0_DEEP_REVIEW",
            "contracts": [{"chain": "bsc", "address": contract}],
            "addresses": [],
            "txs": [tx_hash],
            "times": ["2026-07-30 20:00"],
            "pool_ids": [pool_id],
            "facts": {"venues": ["Binance Alpha"]},
            "sources": [{"authority": "social_discovery", "context_only": False}],
            "chain_enrichment": [
                {
                    "status": "ok",
                    "chain": "bsc",
                    "tx_hash": tx_hash,
                    "pool_id": pool_id,
                    "token0": {"address": contract, "symbol": "BIND"},
                    "token1": {"address": quote, "symbol": "USDT"},
                    "raw_fields": {},
                }
            ],
        }

        ready, pending = catalog.verified_registry_candidates(
            {"projects": [project]},
            current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
            retention_days=30,
        )

        self.assertEqual(ready, [])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["reasons"], ["unproven_time_pool_binding"])

    def test_static_identity_does_not_hide_verified_lifecycle_target(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        contract = "0x" + "1" * 40
        candidate = {
            "symbol": "COVER",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": contract}],
            "facts": {
                "listing_time_utc": "2026-07-30T12:00:00+00:00",
                "listing_time_utc8": "2026-07-30 20:00",
            },
        }
        response = {
            "code": "000000",
            "success": True,
            "data": [
                {
                    "alphaId": "ALPHA_OLD",
                    "symbol": "OLD",
                    "chainId": "56",
                    "contractAddress": "0x" + "4" * 40,
                    "listingTime": 1700000000000,
                }
            ],
        }
        with mock.patch.object(
            catalog,
            "verified_registry_candidates",
            return_value=([candidate], []),
        ):
            payload, _ = catalog.build_runtime_watchlist(
                {"items": [candidate]},
                response,
                current=datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
                lookback_hours=72,
                lookahead_hours=48,
            )

        self.assertEqual(payload["registry_selected_count"], 1)
        self.assertEqual(payload["registry_selected"][0]["symbol"], "COVER")

    def test_verified_signal_target_survives_bounded_artifact_window(self) -> None:
        catalog = importlib.import_module("scripts.binance_alpha_catalog_watch")
        candidate = {
            "symbol": "KEEP",
            "chain": "bsc",
            "contracts": [{"chain": "bsc", "address": "0x" + "1" * 40}],
            "facts": {
                "source": "telegram_signal_receipt_verified",
                "listing_time_utc": "2026-07-30T12:00:00+00:00",
            },
        }

        retained = catalog.retained_signal_candidates(
            {"items": [candidate]},
            current=datetime(2026, 7, 31, 4, 0, tzinfo=timezone.utc),
            retention_days=30,
        )
        expired = catalog.retained_signal_candidates(
            {"items": [candidate]},
            current=datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc),
            retention_days=30,
        )

        self.assertEqual(len(retained), 1)
        self.assertEqual(
            retained[0]["facts"]["signal_candidate_cohort_source"],
            "retained_previous_runtime",
        )
        self.assertEqual(retained[0]["project_lookback_blocks"], 50000)
        self.assertEqual(retained[0]["intraday_max_age_hours"], 72)
        self.assertEqual(expired, [])

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
        self.assertEqual(item["intraday_max_age_hours"], 72)
        self.assertEqual(
            item["facts"]["lifecycle_first_seen_at"],
            current.isoformat(),
        )
        self.assertGreaterEqual(item["opening_max_age_hours"], 72)
        self.assertEqual(item["opening_max_logs"], 30000)
        self.assertEqual(item["opening_trace_buyers"], 8)
        self.assertEqual(item["opening_max_txs"], 24)
        self.assertGreaterEqual(
            item["opening_liquidity_max_age_seconds"],
            72 * 3600,
        )
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

    def test_catalog_merge_preserves_earliest_lifecycle_first_seen(self) -> None:
        catalog = importlib.import_module(
            "scripts.binance_alpha_catalog_watch"
        )
        contract = "0x" + "1" * 40
        existing = {
            "symbol": "KEEP",
            "contracts": [{"chain": "bsc", "address": contract}],
            "facts": {
                "lifecycle_first_seen_at": "2026-07-29T01:00:00+00:00"
            },
        }
        candidate = {
            "symbol": "KEEP",
            "contracts": [{"chain": "bsc", "address": contract}],
            "facts": {
                "lifecycle_first_seen_at": "2026-07-30T01:00:00+00:00"
            },
        }

        merged = catalog.merge_item(existing, candidate)

        self.assertEqual(
            merged["facts"]["lifecycle_first_seen_at"],
            "2026-07-29T01:00:00+00:00",
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
        self.assertEqual(payload["catalog_unsupported_count"], 1)
        self.assertEqual(payload["catalog_unsupported"][0]["symbol"], "BASEONLY")

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
        self.assertEqual(catalog.DEFAULT_MAX_SELECTED, 64)

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
    @staticmethod
    def write_focus_config(
        root: Path,
        symbol: str,
        *,
        contract: str = "",
        listing_time_utc: str = "",
    ) -> tuple[dict[str, object], dict[str, object]]:
        policy: dict[str, object] = {
            "mode": "exclusive_symbols",
            "symbols": [symbol],
        }
        item: dict[str, object] = {
            "symbol": symbol,
            "priority": "P0_DEEP_REVIEW",
            "active_monitoring": True,
            "contracts": (
                [{"chain": "bsc", "address": contract}]
                if contract
                else []
            ),
        }
        if listing_time_utc:
            item["facts"] = {"listing_time_utc": listing_time_utc}
        payload = {"monitoring_policy": policy, "items": [item]}
        path = root / "config" / "current_alpha_watchlist.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return policy, item

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
        fast = (ROOT / "scripts" / "server_fast_lane.sh").read_text(
            encoding="utf-8"
        )
        heavy = (ROOT / "scripts" / "server_run_once.sh").read_text(
            encoding="utf-8"
        )

        catalog_index = fast.index("binance_alpha_catalog_watch.py")
        collector_index = fast.index("telegram_signal_collector.py")
        user_collector_index = fast.index(
            "telegram_user_signal_collector.py"
        )
        project_index = heavy.index("alpha_project_watch.py")
        opening_index = heavy.index("alpha_opening_sprint.sh")
        self.assertLess(collector_index, catalog_index)
        self.assertLess(user_collector_index, catalog_index)
        self.assertLess(project_index, opening_index)
        self.assertIn("ALPHA_WATCHLIST_PATH", fast)
        self.assertIn("ALPHA_WATCHLIST_PATH", heavy)
        self.assertIn("SIGNAL_RUNTIME_CONTEXT=0", fast)
        self.assertIn("BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS", fast)
        self.assertIn("BINANCE_ALPHA_CATALOG_STALE_TTL_SECONDS", heavy)
        self.assertIn("watchlist_policy_status", fast)
        self.assertIn("watchlist_policy_status", heavy)
        self.assertIn("runtime_policy_status", fast)
        self.assertIn("runtime_policy_status", heavy)
        self.assertIn("configured_policy_status", fast)
        self.assertIn("configured_policy_status", heavy)
        self.assertLess(
            fast.index("configured_policy_status"),
            fast.index("alpha_prelaunch_watch.py"),
        )
        self.assertLess(
            heavy.index("configured_policy_status"),
            heavy.index("alpha_project_watch.py"),
        )
        self.assertIn('[[ -z "${ALPHA_WATCHLIST_PATH:-}" ]]', fast)
        self.assertIn('[[ -z "${ALPHA_WATCHLIST_PATH:-}" ]]', heavy)
        self.assertIn(
            "flock is required for overlap protection",
            fast,
        )
        self.assertNotIn("continuing without overlap lock", fast)
        self.assertIn("collector_pid=$!", fast)
        self.assertIn("user_collector_pid=$!", fast)
        self.assertIn("prediction_pid=$!", fast)
        self.assertIn("prelaunch_pid=$!", fast)
        self.assertIn("perp_pid=$!", fast)
        self.assertLess(
            fast.index('wait "$perp_pid"'),
            fast.index("alpha_price_momentum_watch.py"),
        )

    def test_fast_lane_health_returns_nonzero_when_unhealthy(self) -> None:
        import scripts.fast_lane_health as health

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "health.md"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["fast_lane_health.py"],
                ),
                mock.patch.object(
                    health,
                    "read_failures",
                    return_value=[
                        {
                            "kind": "step_failed",
                            "command": "collector",
                        }
                    ],
                ),
                mock.patch.object(
                    health,
                    "output_checks",
                    return_value=([], []),
                ),
                mock.patch.object(health, "REPORT_PATH", report_path),
                mock.patch.object(health, "atomic_write_json"),
            ):
                status = health.main()

        self.assertEqual(status, 1)

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
        import scripts.alpha_intraday_flow_watch as intraday

        text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")

        self.assertIn(
            'run_step "${ALPHA_INTRADAY_TIMEOUT_SECONDS:-480}" '
            "python3 scripts/alpha_intraday_flow_watch.py",
            text,
        )
        self.assertLess(
            intraday.DEFAULT_WATCHER_BUDGET_SECONDS,
            480,
        )

    def test_server_cycle_runs_fast_signals_before_opening_trace(self) -> None:
        fast = (ROOT / "scripts" / "server_fast_lane.sh").read_text(
            encoding="utf-8"
        )
        heavy = (ROOT / "scripts" / "server_run_once.sh").read_text(
            encoding="utf-8"
        )

        intraday_index = heavy.index("alpha_intraday_flow_watch.py")
        price_index = fast.index("alpha_price_momentum_watch.py")
        flush_index = fast.index(
            "telegram_signal_collector.py --flush-pending"
        )
        opening_index = heavy.index("alpha_opening_sprint.sh")
        self.assertLess(intraday_index, opening_index)
        self.assertLess(price_index, flush_index)
        self.assertNotIn("alpha_price_momentum_watch.py", heavy)
        post_opening_refresh = heavy.index(
            "ALPHA_INTRADAY_REQUIRED_ONLY=1"
        )
        self.assertGreater(post_opening_refresh, opening_index)
        self.assertIn(
            "ALPHA_INTRADAY_POST_OPENING_TIMEOUT_SECONDS",
            heavy,
        )
        self.assertIn(
            "ALPHA_INTRADAY_POST_OPENING_TIMEOUT_SECONDS:-360",
            heavy,
        )
        self.assertIn(
            "ALPHA_INTRADAY_POST_OPENING_WATCHER_BUDGET_SECONDS:-330",
            heavy,
        )

    def test_opening_telegram_keeps_pool_identity_in_archived_detail(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        text = opening.telegram_text(
            {
                "new_alert_count": 1,
                "events": [
                    {
                        "symbol": "TEST",
                        "priority": "P1_MONITOR",
                        "status": "opened",
                        "opening_block": 123,
                        "pool_id": "0x" + "a" * 40,
                        "analysis": {
                            "trade_signal": "观察",
                            "direction": "neutral",
                            "spot_action": "等待真实成交",
                        },
                    }
                ],
            }
        )

        self.assertNotIn("0x", text)
        self.assertIn("详情已归档", text)

    def test_opening_collects_transfer_scope_before_liquidity_deadline(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "symbol": "TEST",
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 200,
            "seconds_until_start": -1,
            "token": {"address": "0x" + "1" * 40},
        }

        def transfer_scope(
            current: dict[str, object],
            _latest: int,
        ) -> list[dict[str, object]]:
            current.update(
                {
                    "opening_cohort_coverage_complete": True,
                    "opening_recent_tail_coverage_complete": True,
                    "opening_log_required_windows_complete": True,
                    "opening_log_covered_to_block": 200,
                }
            )
            return []

        with (
            mock.patch.object(
                opening,
                "opening_transfer_logs",
                side_effect=transfer_scope,
            ),
            mock.patch.object(
                opening,
                "opening_buyer_scope_from_transfer_logs",
                return_value=(
                    [],
                    {
                        "opening_buyer_scope_complete": True,
                        "opening_buyer_scope_addresses": [],
                        "opening_buyer_scope_address_count": 0,
                        "opening_cohort_unique_tx_count": 0,
                    },
                ),
            ),
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                side_effect=opening.OpeningTraceDeadlineExceeded(),
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={
                    "trade_signal": "观察",
                    "spot_action": "等待",
                    "direction": "neutral",
                },
            ),
        ):
            result = opening.build_opened_event(event)

        self.assertTrue(event["opening_cohort_coverage_complete"])
        self.assertTrue(event["opening_buyer_scope_complete"])
        self.assertFalse(event["opening_liquidity_coverage_complete"])
        self.assertEqual(
            event["opening_liquidity_coverage_status"],
            "deadline_exceeded",
        )
        self.assertEqual(
            event["liquidity_flow"]["coverage_status"],
            "deadline_exceeded",
        )
        self.assertEqual(result["refresh_status"], "partial_opening_coverage")

    def test_old_opening_without_watch_scope_stays_unverified(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "symbol": "TEST",
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 10000,
            "seconds_until_start": -20000,
            "token": {"address": "0x" + "1" * 40},
            "opening_cohort_coverage_complete": True,
            "opening_recent_tail_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_buyer_scope_complete": True,
            "opening_buyer_scope_addresses": [],
            "opening_buyer_scope_address_count": 0,
            "opening_cohort_unique_tx_count": 0,
            "opening_liquidity_coverage_complete": True,
            "opening_liquidity_coverage_status": (
                "complete_recent_window"
            ),
            "opening_liquidity_watch_scope_hash": "a" * 64,
        }
        prepared = {
            "rows": [],
            "selected_hashes": [],
            "transfer_logs": 0,
            "relevant_tx_count": 0,
        }
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                opening,
                "liquidity_watch_addresses",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={
                    "trade_signal": "观察",
                    "spot_action": "等待",
                    "direction": "neutral",
                },
            ),
        ):
            result = opening.build_opened_event(
                event,
                prepared_scope=prepared,
            )

        self.assertFalse(event["opening_liquidity_coverage_complete"])
        self.assertEqual(
            event["opening_liquidity_coverage_status"],
            "empty_watch_scope_unverified",
        )
        self.assertEqual(
            event["liquidity_flow"]["coverage_status"],
            "empty_watch_scope_unverified",
        )
        self.assertEqual(result["refresh_status"], "partial_opening_coverage")

    def test_old_opening_skip_can_carry_verified_liquidity(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        watch = {
            "0x" + "3" * 40: {
                "role": "pool",
                "watch_quote": "false",
                "source": "event_config",
                "v3_validation_status": "factory_matrix_verified",
            }
        }
        event = {
            "chain": "bsc",
            "seconds_until_start": -20000,
            "opening_block": 100,
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "opening_liquidity_coverage_complete": True,
            "opening_liquidity_coverage_status": (
                "complete_recent_window"
            ),
        }
        event["opening_liquidity_watch_scope_hash"] = (
            opening.liquidity_watch_scope_hash(watch, event)
        )
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                opening,
                "liquidity_watch_addresses",
                return_value=watch,
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "",
                    "required_as_of_block": 0,
                    "pools": [
                        {
                            "address": "0x" + "3" * 40,
                            "token0": "0x" + "1" * 40,
                            "token1": "0x" + "2" * 40,
                        }
                    ],
                },
            ),
        ):
            result = opening.scan_key_liquidity_flows(
                event,
                10000,
            )

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(
            result["coverage_status"],
            "carried_verified_old_opening",
        )
        self.assertEqual(
            result["watch_scope_hash"],
            opening.liquidity_watch_scope_hash(watch, event),
        )

    def test_legacy_liquidity_boolean_without_status_is_backfilled(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        queries: list[dict[str, object]] = []

        def fetch(
            _chain: str,
            query: dict[str, object],
            _chunk_blocks: int,
            _max_logs: int,
            _timeout: int,
        ) -> list[dict[str, object]]:
            queries.append(query)
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -20000,
            "opening_liquidity_coverage_complete": True,
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
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
                    "ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS": "5000",
                },
                clear=True,
            ),
            mock.patch.object(
                opening,
                "liquidity_watch_addresses",
                return_value={
                    "0x" + "3" * 40: {
                        "role": "pool",
                        "watch_quote": "false",
                        "source": "event_config",
                        "v3_validation_status": (
                            "factory_matrix_verified"
                        ),
                    }
                },
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "",
                    "pools": [
                        {
                            "address": "0x" + "3" * 40,
                            "token0": "0x" + "1" * 40,
                            "token1": "0x" + "2" * 40,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "get_logs_quick",
                side_effect=fetch,
            ),
            mock.patch.object(
                opening,
                "scan_liquidity_events",
                return_value={
                    "summary": "未发现 LP 增减事件",
                    "risk": "none",
                    "rows": 0,
                    "events": [],
                },
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 10000)

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(
            result["coverage_status"],
            "complete_historical_opening_window",
        )
        self.assertEqual(queries[0]["fromBlock"], hex(100))
        self.assertEqual(queries[0]["toBlock"], hex(5099))
        self.assertEqual(
            result["watch_scope_hash"],
            opening.liquidity_watch_scope_hash(
                {
                    "0x" + "3" * 40: {
                        "role": "pool",
                        "watch_quote": "false",
                        "source": "event_config",
                        "v3_validation_status": (
                            "factory_matrix_verified"
                        ),
                    }
                },
                event,
            ),
        )

    def test_verified_liquidity_refresh_uses_exact_block_window(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        watch = {
            "0x" + "3" * 40: {
                "role": "pool",
                "watch_quote": "false",
                "source": "event_config",
                "v3_validation_status": "factory_matrix_verified",
            }
        }
        queries: list[dict[str, object]] = []

        def fetch(
            _chain: str,
            query: dict[str, object],
            _chunk_blocks: int,
            _max_logs: int,
            _timeout: int,
        ) -> list[dict[str, object]]:
            queries.append(query)
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "opening_liquidity_coverage_complete": True,
            "opening_liquidity_coverage_status": (
                "complete_recent_window"
            ),
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        event["opening_liquidity_watch_scope_hash"] = (
            opening.liquidity_watch_scope_hash(watch, event)
        )
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS": "5000",
                },
                clear=True,
            ),
            mock.patch.object(
                opening,
                "liquidity_watch_addresses",
                return_value=watch,
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "",
                    "pools": [
                        {
                            "address": "0x" + "3" * 40,
                            "token0": "0x" + "1" * 40,
                            "token1": "0x" + "2" * 40,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "get_logs_quick",
                side_effect=fetch,
            ),
            mock.patch.object(
                opening,
                "scan_liquidity_events",
                return_value={
                    "summary": "未发现 LP 增减事件",
                    "risk": "none",
                    "rows": 0,
                    "events": [],
                },
            ),
        ):
            result = opening.scan_key_liquidity_flows(
                event,
                10000,
            )

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(
            result["coverage_status"],
            "complete_recent_window",
        )
        self.assertEqual(queries[0]["fromBlock"], hex(5001))
        self.assertEqual(queries[0]["toBlock"], hex(10000))

    def test_opening_liquidity_truncation_keeps_stable_status(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "symbol": "TEST",
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 200,
            "token": {"address": "0x" + "1" * 40},
            "opening_cohort_coverage_complete": True,
            "opening_recent_tail_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_buyer_scope_complete": True,
            "opening_buyer_scope_addresses": [],
            "opening_buyer_scope_address_count": 0,
            "opening_cohort_unique_tx_count": 0,
        }
        prepared = {
            "rows": [],
            "selected_hashes": [],
            "transfer_logs": 0,
            "relevant_tx_count": 0,
        }
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                side_effect=opening.OpeningLogCoverageTruncated(),
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={
                    "trade_signal": "观察",
                    "spot_action": "等待",
                    "direction": "neutral",
                },
            ),
        ):
            result = opening.build_opened_event(
                event,
                prepared_scope=prepared,
            )

        self.assertFalse(event["opening_liquidity_coverage_complete"])
        self.assertEqual(
            event["opening_liquidity_coverage_status"],
            "log_coverage_truncated",
        )
        self.assertEqual(
            event["liquidity_flow"]["coverage_status"],
            "log_coverage_truncated",
        )
        self.assertEqual(result["refresh_status"], "partial_opening_coverage")

    def test_opening_liquidity_scan_precedes_receipt_deep_trace(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        calls: list[str] = []
        event = {
            "symbol": "TEST",
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 200,
            "token": {"address": "0x" + "1" * 40},
            "opening_cohort_coverage_complete": True,
            "opening_recent_tail_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_buyer_scope_complete": True,
            "opening_buyer_scope_addresses": [],
            "opening_buyer_scope_address_count": 0,
            "opening_cohort_unique_tx_count": 1,
        }
        prepared = {
            "rows": [],
            "selected_hashes": ["0x" + "2" * 64],
            "transfer_logs": 1,
            "relevant_tx_count": 0,
        }

        def scan(
            _event: dict[str, object],
            _latest: int,
        ) -> dict[str, object]:
            calls.append("liquidity")
            return {
                "risk": "none",
                "rows": 0,
                "coverage_complete": True,
                "coverage_status": "complete_historical_opening_window",
            }

        def summarize(
            _event: dict[str, object],
            tx_hash: str,
        ) -> dict[str, object]:
            calls.append("receipt")
            return {
                "tx": tx_hash,
                "buyer": "",
                "token_bought": "0",
            }

        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                side_effect=scan,
            ),
            mock.patch.object(
                opening,
                "summarize_tx",
                side_effect=summarize,
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={
                    "trade_signal": "观察",
                    "spot_action": "等待",
                    "direction": "neutral",
                },
            ),
        ):
            opening.build_opened_event(
                event,
                prepared_scope=prepared,
            )

        self.assertEqual(calls[:2], ["liquidity", "receipt"])

    def test_opening_build_budget_reallocates_unused_time(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        initial_deadline = opening.TRACE_DEADLINE_AT
        self.addCleanup(
            setattr,
            opening,
            "TRACE_DEADLINE_AT",
            initial_deadline,
        )
        events = [
            {
                "symbol": symbol,
                "chain": "bsc",
                "token": {"address": "0x" + digit * 40},
                "quote": {"address": "0x" + "9" * 40},
                "opening_block": 100 + index,
                "start_time_utc": f"2026-07-30T0{index}:00:00+00:00",
                "pool_id": f"pool-{index}",
            }
            for index, (symbol, digit) in enumerate(
                (("FIRST", "1"), ("SECOND", "2")),
                start=1,
            )
        ]
        observed_deadlines: list[float | None] = []
        clock = {"now": 0.0}

        def configure() -> None:
            opening.TRACE_DEADLINE_AT = 100.0

        def build_event(
            _event: dict[str, object],
            _previous: dict[str, object] | None,
            _prepared_scope: dict[str, object],
        ) -> dict[str, object]:
            observed_deadlines.append(opening.TRACE_DEADLINE_AT)
            if len(observed_deadlines) == 1:
                clock["now"] = 25.0
            return {
                "status": "opened",
                "rows": [],
                "analysis": {},
            }

        with (
            mock.patch.object(
                opening,
                "read_json",
                side_effect=lambda _path, default: default,
            ),
            mock.patch.object(
                opening,
                "configure_trace_deadline",
                side_effect=configure,
            ),
            mock.patch.object(
                opening.time,
                "monotonic",
                side_effect=lambda: clock["now"],
            ),
            mock.patch.object(
                opening,
                "build_events",
                return_value=events,
            ),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                side_effect=build_event,
            ),
            mock.patch.object(
                opening,
                "event_alert_keys",
                return_value=[],
            ),
        ):
            snapshot = opening.build_snapshot()

        self.assertEqual(snapshot["event_count"], 2)
        self.assertTrue(
            all(
                "_opening_snapshot_log_cache" not in event
                for event in snapshot["events"]
            )
        )
        self.assertEqual(observed_deadlines, [50.0, 100.0])
        self.assertEqual(opening.TRACE_DEADLINE_AT, 100.0)
        self.assertEqual(
            [
                event["opening_build_budget_seconds"]
                for event in snapshot["events"]
            ],
            [50.0, 75.0],
        )

    def test_opening_receipt_deadline_keeps_prefetched_transfer_scope(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "symbol": "TEST",
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 200,
            "token": {"address": "0x" + "1" * 40},
            "opening_cohort_coverage_complete": True,
            "opening_recent_tail_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_buyer_scope_complete": True,
            "opening_buyer_scope_addresses": [],
            "opening_buyer_scope_address_count": 0,
            "opening_cohort_unique_tx_count": 1,
        }
        prepared = {
            "rows": [],
            "selected_hashes": ["0x" + "2" * 64],
            "transfer_logs": 1,
            "relevant_tx_count": 0,
        }
        with (
            mock.patch.object(
                opening,
                "summarize_tx",
                side_effect=opening.OpeningTraceDeadlineExceeded(),
            ),
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "risk": "none",
                    "rows": 0,
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={
                    "trade_signal": "观察",
                    "spot_action": "等待",
                    "direction": "neutral",
                },
            ),
        ):
            result = opening.build_opened_event(
                event,
                prepared_scope=prepared,
            )

        self.assertTrue(event["opening_cohort_coverage_complete"])
        self.assertTrue(event["opening_buyer_scope_complete"])
        self.assertFalse(event["opening_receipt_classification_complete"])
        self.assertEqual(event["opening_receipt_selected_tx_count"], 0)
        self.assertEqual(result["refresh_status"], "partial_trace_deadline")
        self.assertEqual(result["last_full_trace_success_at"], "")

    def test_opening_prefetches_all_transfer_scopes_before_deep_build(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        def event(symbol: str, digit: str) -> dict[str, object]:
            return {
                "symbol": symbol,
                "chain": "bsc",
                "opening_block": 100,
                "latest_block": 200,
                "token": {"address": "0x" + digit * 40},
                "quote": {"address": "0x" + "f" * 40},
                "pool_id": "0x" + digit * 64,
            }

        calls: list[str] = []

        def prepare(
            current: dict[str, object],
            _previous: dict[str, object] | None,
        ) -> dict[str, object]:
            calls.append(f"prepare:{current['symbol']}")
            return {
                "rows": [],
                "selected_hashes": [],
                "transfer_logs": 0,
                "relevant_tx_count": 0,
            }

        def build(
            current: dict[str, object],
            _previous: dict[str, object] | None,
            _prepared: dict[str, object],
        ) -> dict[str, object]:
            calls.append(f"build:{current['symbol']}")
            return {
                "status": "opened",
                "rows": [],
                "analysis": {},
            }

        current_events = [event("ONE", "1"), event("TWO", "2")]
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_TRACE_DEADLINE_SECONDS": "100"},
            ),
            mock.patch.object(opening, "TRACE_DEADLINE_AT", None),
            mock.patch.object(
                opening,
                "read_json",
                side_effect=lambda path, default: (
                    {"events": []}
                    if path == opening.LATEST_PATH
                    else default
                ),
            ),
            mock.patch.object(
                opening,
                "build_events",
                return_value=current_events,
            ),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                side_effect=prepare,
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                side_effect=build,
            ),
        ):
            opening.build_snapshot()

        self.assertEqual(
            calls,
            [
                "prepare:ONE",
                "prepare:TWO",
                "build:ONE",
                "build:TWO",
            ],
        )
        budgets = [
            row["opening_scope_budget_seconds"]
            for row in current_events
        ]
        self.assertEqual(budgets[0], budgets[1])
        self.assertGreater(budgets[0], 0)
        self.assertLess(budgets[0], 50)

    def test_intraday_defaults_keep_the_fast_window_coverage_budget(self) -> None:
        text = (ROOT / "scripts" / "alpha_intraday_flow_watch.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('ALPHA_INTRADAY_WINDOW_BLOCKS", "360"', text)
        self.assertIn('ALPHA_INTRADAY_MAX_RECEIPTS", "300"', text)
        self.assertIn('ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS", "120"', text)
        self.assertIn("ALPHA_INTRADAY_WATCHER_BUDGET_SECONDS", text)
        self.assertNotIn(
            'or item.get("opening_max_age_hours")',
            text,
        )

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

    def test_opening_forecast_and_receipt_actual_stay_separate(
        self,
    ) -> None:
        from decimal import Decimal
        from scripts.alpha_opening_block_watch import (
            opening_forecast_comparison,
        )

        comparison = opening_forecast_comparison(
            {
                "opening_forecast": {
                    "buy_quote_usdt": "300000",
                    "bribe_quote_usdt": "200000",
                    "predicted_fill_avg_usdt": "0.46",
                }
            },
            actual_spent=Decimal("280000"),
            weighted_avg=Decimal("0.44"),
            max_bribe_native=Decimal("12"),
            estimated_spent_used=False,
        )

        self.assertEqual(
            comparison["forecast_buy_quote_usdt"],
            "300000",
        )
        self.assertEqual(
            comparison["actual_buy_quote_usdt"],
            "280000",
        )
        self.assertEqual(
            comparison["bribe_comparison_status"],
            "different_units_not_compared",
        )
        self.assertEqual(
            comparison["verification_status"],
            "receipt_actual",
        )

    def test_prelaunch_research_renders_all_required_sections(self) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        item = {
            "symbol": "RICH",
            "name": "Rich Research",
            "priority": "P0_DEEP_REVIEW",
            "chain": "bsc",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "1" * 40}
            ],
            "known_times": [{"time": "2026-07-30 20:00"}],
            "required_checks": ["opening_block"],
            "prelaunch_research": {
                "schema_version": "alpha_prelaunch_research.v1",
                "research_status": "ready",
                "evidence": [
                    {
                        "evidence_id": "official-1",
                        "evidence_kind": "official",
                        "source_ref": "https://example.com/official",
                        "verification_status": "verified",
                    },
                    {
                        "evidence_id": "social-1",
                        "evidence_kind": "social",
                        "source_ref": "https://x.com/example/status/1",
                        "verification_status": "unverified",
                    },
                ],
                "timeline": [
                    {
                        "event": "listing",
                        "time_utc": "2026-07-30T12:00:00+00:00",
                        "verification_status": "verified",
                        "evidence_ids": ["official-1"],
                    },
                    {
                        "event": "bridge_open",
                        "time_utc": "2026-07-30T10:00:00+00:00",
                        "verification_status": "unverified",
                        "evidence_ids": ["social-1"],
                    },
                    {
                        "event": "airdrop_claim",
                        "time_utc": "2026-07-30T13:00:00+00:00",
                        "verification_status": "unverified",
                        "evidence_ids": ["social-1"],
                    },
                ],
                "pool": {
                    "pair": "RICH/USDT",
                    "initial_price_usdt": "0.10",
                    "verification_status": "verified",
                    "evidence_ids": ["official-1"],
                    "segments": [
                        {
                            "kind": "sell_zone",
                            "min_price_usdt": "0.10",
                            "max_price_usdt": "0.30",
                            "token_amount": "1000000",
                            "quote_amount_usdt": "0",
                            "verification_status": "verified",
                            "evidence_ids": ["official-1"],
                        }
                    ],
                },
                "supply": {
                    "total_supply": "1000000000",
                    "initial_float": "100000000",
                    "allocations": [
                        {
                            "role": "airdrop",
                            "percent": "1",
                            "verification_status": "unverified",
                            "evidence_ids": ["social-1"],
                        }
                    ],
                    "cross_chain": [
                        {
                            "chain": "ethereum",
                            "inventory": "200000000",
                            "bridge_state": "open",
                            "verification_status": "unverified",
                            "evidence_ids": ["social-1"],
                        }
                    ],
                },
                "venues": {
                    "cex": [
                        {
                            "venue": "Binance",
                            "market": "alpha",
                            "deposit_state": "open",
                            "verification_status": "verified",
                            "evidence_ids": ["official-1"],
                        }
                    ]
                },
                "actors": {
                    "market_makers": [
                        {
                            "address": "0x" + "2" * 40,
                            "role": "candidate",
                            "verification_status": "unverified",
                            "evidence_ids": ["social-1"],
                        }
                    ]
                },
                "opening_forecast": {
                    "buy_quote_usdt": "300000",
                    "bribe_quote_usdt": "200000",
                    "predicted_fill_avg_usdt": "0.46",
                    "verification_status": "unverified",
                    "evidence_ids": ["social-1"],
                },
                "opening_actual": {
                    "buy_quote_usdt": "280000",
                    "bribe_quote_usdt": "180000",
                    "weighted_avg_price_usdt": "0.44",
                    "confirmed_sell_quote_usdt": "100000",
                    "verification_status": "verified",
                    "evidence_ids": ["official-1"],
                },
                "sniper_curve": [
                    {
                        "buy_pressure_usdt": "100000",
                        "token_out": "500000",
                        "avg_price_usdt": "0.20",
                        "end_price_usdt": "0.24",
                        "verification_status": "verified",
                        "evidence_ids": ["official-1"],
                    }
                ],
                "valuation": {
                    "anchors": [
                        {
                            "kind": "premarket",
                            "price_usdt": "0.18",
                            "fdv_usd": "180000000",
                            "verification_status": "unverified",
                            "evidence_ids": ["social-1"],
                        }
                    ],
                    "prediction_markets": [
                        {
                            "source": "predict_fun",
                            "target_fdv_usd": "200000000",
                            "probability": "0.60",
                            "liquidity_usd": "10000",
                            "verification_status": "unverified",
                            "evidence_ids": ["social-1"],
                        }
                    ],
                },
                "sell_pressure_scenarios": [
                    {
                        "scenario": "stress",
                        "expected_effect": "空投与跨链库存同时释放",
                        "action": "Observe",
                        "verification_status": "unverified",
                        "evidence_ids": ["social-1"],
                    }
                ],
                "decision": {
                    "action": "Observe",
                    "summary": "等待链上承接确认",
                },
                "missing_fields": [],
                "conflicts": [],
            },
        }

        events = prelaunch.build_events(
            {"items": [item]},
            datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["research_status"], "ready")
        text = prelaunch.telegram_text(events)
        for label in (
            "时间轴",
            "池子",
            "筹码/跨链",
            "CEX/MM",
            "狙击预测",
            "开盘实绩",
            "狙击曲线",
            "估值",
            "卖压情景",
            "证据",
            "冲突",
        ):
            self.assertIn(label, text)
        self.assertIn("[V]", text)
        self.assertIn("[U]", text)
        self.assertIn("买压300000U", text)
        self.assertIn("实际均价0.44U", text)
        report = prelaunch.render_report(
            {
                "generated_at": "2026-07-30T08:00:00+00:00",
                "events": events,
            }
        )
        self.assertIn("Evidence / Sources", report)
        self.assertIn("official-1", report)
        self.assertIn("https://example.com/official", report)
        self.assertIn("airdrop_claim", report)
        self.assertNotIn("；+1", report)
        self.assertIn("；+1", text)

    def test_prelaunch_consumer_blocks_invalid_supplied_research(
        self,
    ) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        normalized = prelaunch.prepare_prelaunch_research(
            {
                "prelaunch_research": {
                    "schema_version": "wrong",
                    "research_status": "ready",
                    "evidence": [
                        {
                            "evidence_id": "source-row",
                            "source_ref": "",
                        }
                    ],
                    "identity": {
                        "verification_status": "verified",
                        "evidence_ids": ["missing"],
                    },
                    "timeline": 1,
                    "sniper_curve": 2,
                    "valuation": 3,
                    "missing_fields": [],
                    "conflicts": [],
                }
            }
        )

        self.assertEqual(normalized["research_status"], "blocked")
        paths = {row["path"] for row in normalized["conflicts"]}
        self.assertIn("schema_version", paths)
        self.assertIn("evidence[0].source_ref", paths)
        self.assertIn("identity.evidence_ids", paths)
        self.assertIn("timeline", paths)
        self.assertIn("sniper_curve", paths)
        self.assertIn("valuation", paths)

    def test_prelaunch_telegram_batches_preserve_every_event(self) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        events = [
            {
                "display_name": f"PROJECT-{index}",
                "phase": "T_MINUS_1H",
                "time_utc8": "2026-07-30 20:00",
                "research_status": "partial",
                "alert_key": f"key-{index}",
                "prelaunch_research": {
                    "missing_fields": (
                        ["x" * 8100] if index == 3 else []
                    ),
                    "conflicts": [],
                },
            }
            for index in range(1, 5)
        ]

        messages = prelaunch.telegram_messages(events)
        combined = "\n".join(messages)

        self.assertTrue(
            all(f"PROJECT-{index}" in combined for index in range(1, 5))
        )
        self.assertTrue(
            all(
                len(message) <= prelaunch.TELEGRAM_LIMIT
                for message in messages
            )
        )
        self.assertGreater(len(messages), len(events))

    def test_prelaunch_seen_advances_only_after_whole_event_delivery(
        self,
    ) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        events = [
            {
                "display_name": f"PROJECT-{index}",
                "phase": "T_MINUS_1H",
                "time_utc8": "2026-07-30 20:00",
                "research_status": "partial",
                "alert_key": f"key-{index}",
                "prelaunch_research": {
                    "missing_fields": [],
                    "conflicts": [],
                },
            }
            for index in range(1, 4)
        ]
        seen_order: list[str] = []
        with (
            mock.patch.object(
                prelaunch,
                "send_telegram",
                side_effect=[
                    {"ok": True},
                    {"ok": False, "reason": "fixture_failure"},
                ],
            ) as send,
            mock.patch.object(
                prelaunch,
                "write_seen_keys",
            ) as write_seen,
        ):
            result = prelaunch.push_new_events(
                events,
                seen_order,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["delivered_event_count"], 1)
        self.assertEqual(seen_order, ["key-1"])
        self.assertEqual(send.call_count, 2)
        write_seen.assert_called_once_with(["key-1"])

    def test_prelaunch_research_fingerprint_ignores_observation_timestamps(
        self,
    ) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        base = {
            "schema_version": "alpha_prelaunch_research.v1",
            "observed_at": "2026-07-30T01:00:00+00:00",
            "evidence": [
                {
                    "evidence_id": "market-1",
                    "observed_at": "2026-07-30T01:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
            "pool": {
                "initial_price_usdt": "0.10",
                "verification_status": "verified",
            },
        }
        refreshed = json.loads(json.dumps(base))
        refreshed["observed_at"] = "2026-07-30T02:00:00+00:00"
        refreshed["evidence"][0]["observed_at"] = (
            "2026-07-30T02:00:00+00:00"
        )
        revised = json.loads(json.dumps(refreshed))
        revised["pool"]["initial_price_usdt"] = "0.11"

        self.assertEqual(
            prelaunch.research_fingerprint(base),
            prelaunch.research_fingerprint(refreshed),
        )
        self.assertNotEqual(
            prelaunch.research_fingerprint(base),
            prelaunch.research_fingerprint(revised),
        )
        item = {
            "symbol": "FINGERPRINT",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "4" * 40}
            ],
        }
        start = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        base_key = prelaunch.alert_key(
            item,
            start,
            "T_MINUS_6H",
            prelaunch.research_fingerprint(base),
        )
        refreshed_key = prelaunch.alert_key(
            item,
            start,
            "T_MINUS_6H",
            prelaunch.research_fingerprint(refreshed),
        )
        revised_key = prelaunch.alert_key(
            item,
            start,
            "T_MINUS_6H",
            prelaunch.research_fingerprint(revised),
        )
        self.assertEqual(base_key, refreshed_key)
        self.assertNotEqual(base_key, revised_key)

    def test_prelaunch_missing_research_is_explicit_partial(self) -> None:
        import scripts.alpha_prelaunch_watch as prelaunch

        events = prelaunch.build_events(
            {
                "items": [
                    {
                        "symbol": "THIN",
                        "priority": "P1_MONITOR",
                        "contracts": [
                            {
                                "chain": "bsc",
                                "address": "0x" + "3" * 40,
                            }
                        ],
                        "known_times": [{"time": "2026-07-30 20:00"}],
                    }
                ]
            },
            datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(events[0]["research_status"], "partial")
        self.assertIn(
            "prelaunch_research",
            events[0]["prelaunch_research"]["missing_fields"],
        )
        text = prelaunch.telegram_text(events)
        self.assertIn("partial", text)
        self.assertIn("缺口", text)

    def test_grvt_tracked_research_is_blocked_and_schema_consistent(
        self,
    ) -> None:
        payload = json.loads(
            (
                ROOT / "config" / "current_alpha_watchlist.json"
            ).read_text(encoding="utf-8")
        )
        item = next(
            row
            for row in payload["items"]
            if row.get("symbol") == "GRVT"
        )
        research = item["prelaunch_research"]

        self.assertEqual(research["research_status"], "blocked")
        self.assertTrue(research["conflicts"])
        self.assertTrue(
            all(
                row.get("time_utc8")
                and row.get("time_precision")
                and row.get("authority")
                for row in research["timeline"]
            )
        )
        self.assertTrue(
            all(
                row.get("projection_policy")
                == "reference_only_do_not_sum"
                and row.get("derived_from")
                for row in item["event_distributions"]
            )
        )

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

    def test_perp_trend_rejects_days_old_baseline(self) -> None:
        import scripts.perp_oi_funding_watch as perp

        current_at = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        baseline_at = current_at - timedelta(days=3)
        history = [
            {
                "generated_at": baseline_at.isoformat(),
                "rows": [
                    {
                        "symbol": "AEON",
                        "perp_symbol": "AEONUSDT",
                        "status": "ok",
                        "oi_event_time_ms": int(
                            (
                                baseline_at - timedelta(seconds=30)
                            ).timestamp()
                            * 1000
                        ),
                        "open_interest_usd": "100",
                        "mark_price": "1",
                        "last_funding_rate": "0",
                    }
                ],
            }
        ]
        current = {
            "symbol": "AEON",
            "perp_symbol": "AEONUSDT",
            "status": "ok",
            "oi_event_time_ms": int(
                (current_at - timedelta(seconds=30)).timestamp() * 1000
            ),
            "open_interest_usd": "91.21",
            "mark_price": "1",
            "last_funding_rate": "0",
        }

        with mock.patch.dict(
            os.environ,
            {
                "PERP_WATCH_TREND_MIN_AGE_MINUTES": "10",
                "PERP_WATCH_TREND_MAX_AGE_MINUTES": "120",
                "PERP_WATCH_CURRENT_EVENT_MAX_AGE_SECONDS": "300",
            },
        ):
            trend = perp.trend_for_symbol(
                history,
                "AEON",
                current,
                current_at.isoformat(),
            )

        self.assertEqual(trend["trend_status"], "no_eligible_baseline")
        self.assertEqual(trend["trend_hint"], "观察")
        self.assertNotIn("oi_usd_delta_pct", trend)
        self.assertEqual(
            trend["baseline_rejection_counts"][
                "baseline_interval_too_long"
            ],
            1,
        )

    def test_perp_trend_accepts_fresh_sixty_minute_baseline(self) -> None:
        import scripts.perp_oi_funding_watch as perp

        current_at = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        current_event_at = current_at - timedelta(seconds=30)
        baseline_event_at = current_event_at - timedelta(minutes=60)
        history = [
            {
                "generated_at": (
                    baseline_event_at + timedelta(seconds=30)
                ).isoformat(),
                "rows": [
                    {
                        "symbol": "AEON",
                        "perp_symbol": "AEONUSDT",
                        "status": "ok",
                        "oi_event_time_ms": int(
                            baseline_event_at.timestamp() * 1000
                        ),
                        "open_interest_usd": "100",
                        "mark_price": "1",
                        "last_funding_rate": "0",
                    }
                ],
            }
        ]
        current = {
            "symbol": "AEON",
            "perp_symbol": "AEONUSDT",
            "status": "ok",
            "oi_event_time_ms": int(
                current_event_at.timestamp() * 1000
            ),
            "open_interest_usd": "91.21",
            "mark_price": "0.99",
            "last_funding_rate": "0",
        }

        with mock.patch.dict(
            os.environ,
            {
                "PERP_WATCH_TREND_MIN_AGE_MINUTES": "10",
                "PERP_WATCH_TREND_MAX_AGE_MINUTES": "120",
                "PERP_WATCH_CURRENT_EVENT_MAX_AGE_SECONDS": "300",
            },
        ):
            trend = perp.trend_for_symbol(
                history,
                "AEON",
                current,
                current_at.isoformat(),
            )

        self.assertEqual(trend["trend_status"], "ok")
        self.assertEqual(trend["baseline_age_minutes"], "60")
        self.assertEqual(trend["oi_usd_delta_pct"], "-8.7900")
        self.assertEqual(trend["trend_hint"], "降杠杆")
        self.assertEqual(trend["current_oi_event_freshness"], "fresh")

    def test_perp_trend_rejects_stale_current_event_time(self) -> None:
        import scripts.perp_oi_funding_watch as perp

        current_at = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        current = {
            "symbol": "AEON",
            "perp_symbol": "AEONUSDT",
            "status": "ok",
            "oi_event_time_ms": int(
                (current_at - timedelta(hours=1)).timestamp() * 1000
            ),
            "open_interest_usd": "91.21",
            "mark_price": "0.99",
            "last_funding_rate": "0",
        }

        with mock.patch.dict(
            os.environ,
            {"PERP_WATCH_CURRENT_EVENT_MAX_AGE_SECONDS": "300"},
        ):
            trend = perp.trend_for_symbol(
                [],
                "AEON",
                current,
                current_at.isoformat(),
            )

        self.assertEqual(trend["trend_status"], "current_sample_stale")
        self.assertEqual(trend["trend_hint"], "观察")
        self.assertNotIn("oi_usd_delta_pct", trend)
        self.assertEqual(
            trend["current_oi_event_age_seconds"],
            3600,
        )

    def test_perp_alert_rejects_stale_current_oi_event(self) -> None:
        import scripts.perp_oi_funding_watch as perp

        row = {
            "status": "ok",
            "current_oi_event_freshness": "stale",
            "direction_hint": "拥挤",
            "funding_history_state": "sustained_long_crowding",
            "depth_state": "thin_depth",
        }

        self.assertFalse(perp.row_has_actionable_perp_alert(row))
        row["current_oi_event_freshness"] = "fresh"
        self.assertTrue(perp.row_has_actionable_perp_alert(row))
        row.pop("current_oi_event_freshness")
        self.assertFalse(perp.row_has_actionable_perp_alert(row))

    def test_price_context_sanitizes_stale_current_oi_event(
        self,
    ) -> None:
        import scripts.alpha_price_momentum_watch as price

        current = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "perp.json"
            path.write_text(
                json.dumps(
                    {
                        "generated_at": current.isoformat(),
                        "rows": [
                            {
                                "symbol": "AEON",
                                "status": "ok",
                                "perp_state": "crowded_funding",
                                "direction_hint": "拥挤",
                                "action": "多头拥挤",
                                "trend_status": "current_sample_stale",
                                "trend_hint": "观察",
                                "current_oi_event_freshness": "stale",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(price, "PERP_WATCH_PATH", path),
                mock.patch.object(price, "now_utc", return_value=current),
            ):
                context = price.latest_perp_context("AEON")

        self.assertEqual(context["snapshot_status"], "stale")
        self.assertEqual(context["perp_state"], "stale_oi_event")
        self.assertEqual(context["direction_hint"], "观察")
        self.assertNotIn("多头拥挤", context["action"])
        self.assertIn("事件时间", context["action"])
        self.assertEqual(
            price.perp_action_summary(context),
            "合约快照过期，只作背景",
        )
        self.assertNotIn("多头拥挤", price.perp_summary(context))
        self.assertFalse(
            any(
                key.startswith("perp_trend|")
                for key in price.event_alert_keys(
                    {
                        "symbol": "AEON",
                        "analysis": {
                            "perp_context": context,
                            "window_15m": {},
                            "window_backfill": {},
                        },
                    }
                )
            )
        )

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

    def test_production_health_fails_when_curated_focus_config_is_missing(
        self,
    ) -> None:
        import scripts.runtime_health_watch as health

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_path = root / "runtime.json"
            runtime_path.write_text(
                json.dumps({"items": []}),
                encoding="utf-8",
            )
            with mock.patch.object(health, "ROOT", root):
                focus, detail = health.monitoring_focus_scope(
                    root,
                    runtime_path,
                )

        self.assertEqual(focus, set())
        self.assertIn("policy is missing", detail)

    def test_health_requires_focus_when_catalog_contains_only_other_candidates(
        self,
    ) -> None:
        import scripts.binance_alpha_catalog_watch as catalog
        from scripts.runtime_health_watch import alpha_coverage_issues

        grvt_address = "0x" + "1" * 40
        aeon_address = "0x" + "2" * 40
        policy = {"mode": "exclusive_symbols", "symbols": ["GRVT"]}
        watchlist = {
            "monitoring_policy": policy,
            "monitoring_policy_fingerprint": (
                catalog.monitoring_policy_fingerprint(policy)
            ),
            "items": [
                {
                    "symbol": "GRVT",
                    "active_monitoring": True,
                    "contracts": [
                        {"chain": "bsc", "address": grvt_address}
                    ],
                },
                {
                    "symbol": "AEON",
                    "active_monitoring": False,
                    "contracts": [
                        {"chain": "bsc", "address": aeon_address}
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def write(relative: str, payload: dict[str, object]) -> None:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")

            static = copy.deepcopy(watchlist)
            static.pop("monitoring_policy_fingerprint")
            write("config/current_alpha_watchlist.json", static)
            write(
                "output/binance_alpha_catalog_watch/current_watchlist.json",
                watchlist,
            )
            write(
                "output/binance_alpha_catalog_watch/latest.json",
                {
                    "status": "pass",
                    "monitoring_policy": policy,
                    "selected": [
                        {
                            "symbol": "AEON",
                            "chain": "bsc",
                            "contract": aeon_address,
                            "active_monitoring": False,
                        }
                    ],
                    "unsupported_count": 1,
                    "unsupported": [
                        {"symbol": "AEON", "chain": "base"}
                    ],
                    "registry_pending": [
                        {"symbol": "AEON", "reasons": ["fixture"]}
                    ],
                },
            )

            issues = alpha_coverage_issues(root)

        self.assertTrue(
            any(
                row["kind"] == "alpha_catalog_focus_missing"
                and row["name"] == "GRVT"
                for row in issues
            ),
            issues,
        )
        self.assertFalse(any(row.get("name") == "AEON" for row in issues))

    def test_health_fails_when_recent_official_token_has_no_runtime_coverage(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_focus_config(
                root,
                "AEON",
                contract="0x277add739c6e0477616948357af9e79fe1ec9b80",
                listing_time_utc="2026-07-27T10:00:00+00:00",
            )
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
            self.write_focus_config(root, "DROP")
            path = root / "output" / "binance_alpha_catalog_watch" / "latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "dropped_count": 2,
                        "dropped": [
                            {"symbol": "DROP", "chain": "bsc", "contract": "0x" + "1" * 40},
                            {"symbol": "OTHER", "chain": "bsc", "contract": "0x" + "2" * 40},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            issues = alpha_coverage_issues(root)

        self.assertTrue(
            any(row["kind"] == "alpha_catalog_budget_exceeded" for row in issues),
            issues,
        )

    def test_health_reports_static_official_launch_time_conflict(
        self,
    ) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_focus_config(root, "GRVT")
            path = (
                root
                / "output"
                / "binance_alpha_catalog_watch"
                / "latest.json"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "static_time_conflict_count": 1,
                        "static_time_conflicts": [
                            {
                                "symbol": "GRVT",
                                "static_opening_times_utc8": [
                                    "2026-07-30 20:00"
                                ],
                                "official_listing_time_utc8": (
                                    "2026-07-30 21:00"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            issues = alpha_coverage_issues(root)

        conflict = next(
            row for row in issues if row["kind"] == "alpha_static_time_conflict"
        )
        self.assertEqual(conflict["name"], "GRVT")

    def test_health_rejects_static_time_conflict_summary_mismatch(
        self,
    ) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_focus_config(root, "GRVT")
            path = (
                root
                / "output"
                / "binance_alpha_catalog_watch"
                / "latest.json"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "static_time_conflict_count": 1,
                        "static_time_conflicts": [],
                    }
                ),
                encoding="utf-8",
            )

            issues = alpha_coverage_issues(root)

        self.assertTrue(
            any(
                row["kind"] == "alpha_static_time_conflict_summary_invalid"
                for row in issues
            ),
            issues,
        )

    def test_legacy_prelaunch_receipt_gap_is_explicit_warning_only(self) -> None:
        from scripts.runtime_health_watch import (
            PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT,
            legacy_prelaunch_delivery_warning,
        )

        detail = "historical prelaunch Telegram delivery receipt missing"
        warning = legacy_prelaunch_delivery_warning(
            {
                "chain": "bsc",
                "contract": (
                    "0x277add739c6e0477616948357af9e79fe1ec9b80"
                ),
                "listing_time_utc": "2026-07-27T10:00:00+00:00",
                "lifecycle_first_seen_at": "2026-07-26T07:11:00+00:00",
            },
            detail,
        )
        self.assertIn("delivery_unverified", warning)
        self.assertIn("not evidence of delivery", warning)
        self.assertEqual(
            legacy_prelaunch_delivery_warning(
                {
                    "chain": "bsc",
                    "contract": (
                        "0x277add739c6e0477616948357af9e79fe1ec9b80"
                    ),
                    "listing_time_utc": PRELAUNCH_RECEIPT_POLICY_ENFORCED_AT.isoformat(),
                    "lifecycle_first_seen_at": "2026-07-26T07:11:00+00:00",
                },
                detail,
            ),
            "",
        )
        self.assertEqual(
            legacy_prelaunch_delivery_warning(
                {
                    "symbol": "OTHER",
                    "chain": "bsc",
                    "contract": "0x" + "9" * 40,
                    "listing_time_utc": "2026-07-27T10:00:00+00:00",
                    "lifecycle_first_seen_at": (
                        "2026-07-26T07:11:00+00:00"
                    ),
                },
                detail,
            ),
            "",
        )
        self.assertEqual(
            legacy_prelaunch_delivery_warning(
                {"listing_time_utc": "2026-07-27T10:00:00+00:00"},
                detail,
            ),
            "",
        )

    def test_health_reports_recent_unsupported_chain_item(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_focus_config(root, "BASEONLY")
            path = root / "output" / "binance_alpha_catalog_watch" / "latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "unsupported_count": 1,
                        "unsupported": [
                            {"symbol": "BASEONLY", "chain": "base"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            issues = alpha_coverage_issues(root)

        unsupported = next(
            row for row in issues if row["kind"] == "alpha_unsupported_chain"
        )
        self.assertIn("BASEONLY@base", unsupported["detail"])

    def test_health_reports_unready_launch_candidate(self) -> None:
        from scripts.runtime_health_watch import alpha_coverage_issues

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_focus_config(root, "GRVT")
            path = root / "output" / "binance_alpha_catalog_watch" / "latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "selected": [],
                        "registry_pending": [
                            {
                                "symbol": "GRVT",
                                "project_key": "symbol:GRVT",
                                "reasons": [
                                    "missing_exact_opening_time",
                                    "missing_receipt_verified_alpha_pool",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            issues = alpha_coverage_issues(root)

        gap = next(
            row for row in issues if row["kind"] == "alpha_launch_candidate_gap"
        )
        self.assertEqual(gap["name"], "GRVT")
        self.assertIn("missing_exact_opening_time", gap["detail"])

    def test_prelaunch_health_requires_successful_delivery_receipt(self) -> None:
        from scripts.runtime_health_watch import prelaunch_delivery_issue

        rows = [
            {"alert_key": "GRVT|contract|2026-07-30T12:00:00+00:00|T_MINUS_24H"},
            {"alert_key": "GRVT|contract|2026-07-30T12:00:00+00:00|T_MINUS_1H"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIn("receipt missing", prelaunch_delivery_issue(root, rows))
            seen_path = root / "output" / "alpha_prelaunch_watch" / "seen_alerts.json"
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text(
                json.dumps({"keys": [rows[0]["alert_key"]]}),
                encoding="utf-8",
            )
            self.assertIn("receipt missing", prelaunch_delivery_issue(root, rows))
            seen_path.write_text(
                json.dumps({"keys": [row["alert_key"] for row in rows]}),
                encoding="utf-8",
            )
            self.assertEqual(prelaunch_delivery_issue(root, rows), "")

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
                    "opening_cohort_coverage_complete": True,
                    "opening_liquidity_coverage_complete": True,
                    "opening_buyer_scope_complete": True,
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
            "coverage_complete": True,
            "contracts": [
                {
                    **complete_project_contract("0x" + "1" * 40),
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

    def test_health_fails_closed_on_missing_project_coverage_or_balance_error(self) -> None:
        from scripts.runtime_health_watch import output_row_coverage_issue

        target = "0x" + "1" * 40
        self.assertEqual(
            output_row_coverage_issue(
                "project",
                {"contracts": [{"address": target}]},
                target_contract=target,
            ),
            "project coverage incomplete",
        )
        invalid_balance = complete_project_contract(target)
        invalid_balance["balances"] = [{"address": target, "error": "rpc"}]
        self.assertEqual(
            output_row_coverage_issue(
                "project",
                {
                    "coverage_complete": True,
                    "contracts": [invalid_balance],
                },
                target_contract=target,
            ),
            "project contract coverage metadata invalid",
        )
        missing_balance = complete_project_contract(target)
        missing_balance.update(
            {
                "watch_address_count": 1,
                "balance_target_count": 1,
                "watch_addresses": [{"address": "0x" + "2" * 40}],
                "balances": [],
            }
        )
        self.assertEqual(
            output_row_coverage_issue(
                "project",
                {
                    "coverage_complete": True,
                    "contracts": [missing_balance],
                },
                target_contract=target,
            ),
            "project contract coverage metadata invalid",
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
                    "blockHash": "0x" + "a" * 64,
                    "transactionHash": "0x" + query["address"][2:].rjust(64, "0"),
                    "logIndex": "0x0",
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
                    first: {
                        "role": "pool_manager",
                        "label": "first",
                        "source": "event_config",
                        "v4_validation_status": "pool_key_verified",
                        "v4_manager_type": "cl",
                    },
                    second: {
                        "role": "pool_manager",
                        "label": "second",
                        "source": "event_config",
                        "v4_validation_status": "pool_key_verified",
                        "v4_manager_type": "cl",
                    },
                },
            )

        self.assertEqual(calls, [(first, 5000), (second, 5000)])
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["risk"], "lp_activity_unattributed")
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["label"], "second")

    def test_liquidity_events_and_alert_key_use_global_latest_order(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        newer_pool = "0x" + "3" * 40
        older_pool = "0x" + "4" * 40
        newer_tx = "0x" + "5" * 64
        older_tx = "0x" + "6" * 64

        def burn(address: str, block: int, tx_hash: str) -> dict[str, object]:
            return {
                "address": address,
                "blockNumber": hex(block),
                "blockHash": "0x" + f"{block:064x}",
                "transactionHash": tx_hash,
                "logIndex": "0x0",
                "topics": [opening.V3_BURN_TOPIC],
                "data": "0x" + "".join(
                    f"{value:064x}" for value in (1, 200000, 1)
                ),
            }

        newer_add = burn(newer_pool, 300, newer_tx)
        newer_add["topics"] = [opening.V3_MINT_TOPIC]
        newer_add["data"] = "0x" + "".join(
            f"{value:064x}" for value in (0, 1, 200000, 1)
        )
        logs = {
            newer_pool: [newer_add],
            older_pool: [burn(older_pool, 200, older_tx)],
        }
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            side_effect=lambda _event, query, *_args: logs[query["address"]],
        ):
            result = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                    "quote": {"address": quote, "decimals": 0},
                },
                100,
                400,
                {
                    newer_pool: {
                        "role": "pool",
                        "token0": token,
                        "token1": quote,
                    },
                    older_pool: {
                        "role": "pool",
                        "token0": token,
                        "token1": quote,
                    },
                },
            )

        self.assertEqual(result["events"][-1]["tx"], newer_tx)
        alert_keys = [
            key
            for key in opening.event_alert_keys(
                {
                    "status": "opened",
                    "symbol": "TEST",
                    "opening_block": 100,
                    "pool_id": "",
                    "analysis": {
                        "liquidity_flow_risk": "lp_activity_unattributed"
                    },
                    "liquidity_flow": {
                        "liquidity_events": result["events"],
                        "latest_actionable_remove_key": result[
                            "latest_actionable_remove_key"
                        ],
                    },
                    "rows": [],
                }
            )
            if key.startswith("liquidity_flow|")
        ]
        self.assertEqual(len(alert_keys), 1)
        self.assertTrue(
            alert_keys[0].endswith(
                opening.liquidity_activity_key(older_pool, older_tx)
            )
        )

    def test_liquidity_event_scan_skips_unmatchable_managers(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        explicit_pool = "0x" + "1" * 40
        position_manager = "0x" + "2" * 40
        pool_manager = "0x" + "3" * 40
        event = {
            "chain": "bsc",
            "pool_id": "not-a-bytes32-pool-id",
            "lp_position_ids": [],
        }
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            return_value=[],
        ) as fetch:
            result = opening.scan_liquidity_events(
                event,
                100,
                200,
                {
                    explicit_pool: {
                        "role": "pool",
                        "label": "pool",
                    },
                    position_manager: {
                        "role": "lp_position_manager",
                        "label": "position-manager",
                    },
                    pool_manager: {
                        "role": "pool_manager",
                        "label": "pool-manager",
                    },
                },
            )

        self.assertEqual(result["rows"], 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(
            fetch.call_args.args[1]["address"],
            explicit_pool,
        )
        self.assertTrue(result["coverage_complete"])

    def test_liquidity_manager_scope_without_identity_fails_closed(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        watch = {
            "0x" + "3" * 40: {
                "role": "pool_manager",
                "label": "pool-manager",
                "watch_quote": "false",
            }
        }
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "pool_id": "not-a-bytes32-pool-id",
            "lp_position_ids": [],
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
        }
        with (
            mock.patch.object(
                opening,
                "liquidity_watch_addresses",
                return_value=watch,
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "factory_matrix_unavailable",
                    "complete": False,
                    "pools": [],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                return_value=[],
            ) as fetch,
        ):
            result = opening.scan_key_liquidity_flows(
                event,
                200,
            )

        self.assertEqual(fetch.call_count, 0)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(
            result["coverage_status"],
            "unattributable_liquidity_manager_scope",
        )
        self.assertEqual(
            result["risk"],
            "unknown_incomplete_coverage",
        )

    def test_v3_factory_matrix_requires_complete_membership(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        wbnb = "0x" + "3" * 40
        factory = "0x" + "4" * 40
        wrong_factory = "0x" + "5" * 40
        pool = "0x" + "6" * 40
        event = {
            "chain": "bsc",
            "seconds_until_start": -100,
            "token": {"address": token},
            "quote": {"address": quote},
        }
        labels = {
            quote: {"class": "quote_token"},
            wbnb: {"class": "quote_token"},
            factory: {
                "class": "v3_factory",
                "protocol": "test_v3",
                "fee_tiers": [100],
            },
        }
        mode = {"value": "good"}
        block_calls: dict[str, int] = {}

        def address_result(value: str) -> str:
            return "0x" + "0" * 24 + value[2:]

        def rpc(
            _chain: str,
            method: str,
            params: list[object],
            **_kwargs: object,
        ) -> str:
            call = params[0]
            if method == "eth_getBlockByNumber":
                current_mode = mode["value"]
                block_calls[current_mode] = (
                    block_calls.get(current_mode, 0) + 1
                )
                suffix = (
                    "b"
                    if current_mode == "block_flip"
                    and block_calls[current_mode] > 1
                    else "a"
                )
                return {"hash": "0x" + suffix * 64}
            if method == "eth_getCode":
                return {
                    "code_none": None,
                    "code_zero": "0x00",
                    "code_malformed": "not-hex",
                }.get(mode["value"], "0x6000")
            self.assertEqual(method, "eth_call")
            self.assertIsInstance(call, dict)
            to = str(call["to"])
            data = str(call["data"])
            if to == factory:
                if mode["value"] == "abi_malformed":
                    return address_result(pool) + "00"
                counterasset = "0x" + data[98:138]
                if mode["value"] == "missing_cached_pool":
                    return "0x" + "0" * 64
                if mode["value"] == "mixed" and counterasset == wbnb:
                    raise RuntimeError("provider unavailable")
                return (
                    address_result(pool)
                    if counterasset == quote
                    else "0x" + "0" * 64
                )
            if data == "0x0dfe1681":
                return address_result(token)
            if data == "0xd21220a7":
                return address_result(quote)
            if data == "0xc45a0155":
                return address_result(
                    wrong_factory
                    if mode["value"] == "mismatch"
                    else factory
                )
            return "0x" + f"{100:064x}"

        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value=labels,
            ),
            mock.patch.object(opening, "rpc_call", side_effect=rpc),
        ):
            good = opening.supported_v3_pool_scope(event, 200)
            mode["value"] = "mismatch"
            mismatch = opening.supported_v3_pool_scope(event, 200)
            mode["value"] = "mixed"
            mixed = opening.supported_v3_pool_scope(event, 200)
            invalid_code_results = []
            for value in (
                "code_none",
                "code_zero",
                "code_malformed",
            ):
                mode["value"] = value
                invalid_code_results.append(
                    opening.supported_v3_pool_scope(event, 200)
                )
            mode["value"] = "abi_malformed"
            malformed_abi = opening.supported_v3_pool_scope(event, 200)
            mode["value"] = "block_flip"
            incoherent_block = opening.supported_v3_pool_scope(event, 200)
            event["opening_v3_pool_scope"] = copy.deepcopy(good)
            mode["value"] = "missing_cached_pool"
            scope_conflict = opening.supported_v3_pool_scope(event, 401)
            event["opening_v3_pool_scope"] = copy.deepcopy(scope_conflict)
            scope_conflict_again = opening.supported_v3_pool_scope(
                event, 602
            )

        self.assertTrue(good["complete"])
        self.assertEqual(good["expected_query_count"], 2)
        self.assertEqual(good["attempted_query_count"], 2)
        self.assertEqual(good["pools"][0]["address"], pool)
        self.assertFalse(mismatch["complete"])
        self.assertEqual(mismatch["pools"], [])
        self.assertEqual(mismatch["validation_error_count"], 1)
        self.assertFalse(mixed["complete"])
        self.assertEqual(mixed["pools"][0]["address"], pool)
        self.assertEqual(mixed["validation_error_count"], 1)
        for result in invalid_code_results:
            self.assertFalse(result["complete"])
            self.assertEqual(result["pools"], [])
        self.assertFalse(malformed_abi["complete"])
        self.assertEqual(malformed_abi["pools"], [])
        self.assertFalse(incoherent_block["complete"])
        self.assertFalse(incoherent_block["snapshot_coherent"])
        self.assertEqual(incoherent_block["pools"], [])
        self.assertFalse(scope_conflict["complete"])
        self.assertEqual(
            scope_conflict["status"],
            "factory_matrix_scope_conflict",
        )
        self.assertEqual(scope_conflict["scope_conflict_count"], 1)
        self.assertEqual(scope_conflict["pools"], [])
        self.assertEqual(
            scope_conflict_again["status"],
            "factory_matrix_scope_conflict",
        )
        self.assertFalse(scope_conflict_again["complete"])
        self.assertEqual(scope_conflict_again["pools"], [])

    def test_v3_factory_matrix_cache_binds_inputs_and_block_hash(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        factory = "0x" + "3" * 40
        pool = "0x" + "4" * 40
        labels = {
            quote: {"class": "quote_token"},
            factory: {
                "class": "v3_factory",
                "protocol": "test_v3",
                "fee_tiers": [100],
            },
        }
        block_hashes = {
            200: "0x" + "a" * 64,
            300: "0x" + "b" * 64,
        }
        get_pool_calls: list[int] = []

        def address_result(value: str) -> str:
            return "0x" + "0" * 24 + value[2:]

        def rpc(
            _chain: str,
            method: str,
            params: list[object],
            **_kwargs: object,
        ) -> object:
            if method == "eth_getBlockByNumber":
                block = int(str(params[0]), 16)
                return {"hash": block_hashes[block]}
            if method == "eth_getCode":
                return "0x6000"
            call = params[0]
            self.assertIsInstance(call, dict)
            to = str(call["to"])
            data = str(call["data"])
            if to == factory:
                fee = int(data[-64:], 16)
                get_pool_calls.append(fee)
                return (
                    address_result(pool)
                    if fee == 100
                    else "0x" + "0" * 64
                )
            if data == "0x0dfe1681":
                return address_result(token)
            if data == "0xd21220a7":
                return address_result(quote)
            if data == "0xc45a0155":
                return address_result(factory)
            return "0x" + f"{100:064x}"

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token},
            "quote": {"address": quote},
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS": "101",
                    "ALPHA_OPENING_V3_SCOPE_REFRESH_BLOCKS": "200",
                },
            ),
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value=labels,
            ),
            mock.patch.object(opening, "rpc_call", side_effect=rpc),
        ):
            first = opening.supported_v3_pool_scope(event, 200)
            event["opening_v3_pool_scope"] = copy.deepcopy(first)
            cached = opening.supported_v3_pool_scope(event, 300)
            block_hashes[200] = "0x" + "c" * 64
            reorg_refreshed = opening.supported_v3_pool_scope(event, 300)
            labels[factory]["fee_tiers"] = [100, 500]
            refreshed = opening.supported_v3_pool_scope(event, 300)

        self.assertTrue(first["complete"])
        self.assertEqual(cached["as_of_block"], 200)
        self.assertEqual(reorg_refreshed["as_of_block"], 300)
        self.assertEqual(get_pool_calls, [100, 100, 100, 500])
        self.assertNotEqual(
            first["configuration_hash"],
            refreshed["configuration_hash"],
        )
        self.assertEqual(refreshed["expected_query_count"], 2)
        self.assertTrue(refreshed["complete"])

    def test_v3_factory_matrix_caches_complete_empty_scope(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        factory = "0x" + "3" * 40
        block_hash = "0x" + "a" * 64
        get_pool_calls = 0

        def rpc(
            _chain: str,
            method: str,
            params: list[object],
            **_kwargs: object,
        ) -> object:
            nonlocal get_pool_calls
            if method == "eth_getBlockByNumber":
                return {"hash": block_hash}
            self.assertEqual(method, "eth_call")
            self.assertEqual(str(params[0]["to"]), factory)
            get_pool_calls += 1
            return "0x" + "0" * 64

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token},
            "quote": {"address": quote},
        }
        labels = {
            quote: {"class": "quote_token"},
            factory: {
                "class": "v3_factory",
                "fee_tiers": [100],
            },
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS": "101",
                    "ALPHA_OPENING_V3_SCOPE_REFRESH_BLOCKS": "200",
                },
            ),
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value=labels,
            ),
            mock.patch.object(opening, "rpc_call", side_effect=rpc),
        ):
            first = opening.supported_v3_pool_scope(event, 200)
            event["opening_v3_pool_scope"] = copy.deepcopy(first)
            cached = opening.supported_v3_pool_scope(event, 300)

        self.assertTrue(first["complete"])
        self.assertEqual(first["pools"], [])
        self.assertEqual(cached["as_of_block"], 200)
        self.assertEqual(get_pool_calls, 1)

    def test_v3_factory_matrix_refreshes_stale_complete_scope(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        factory = "0x" + "3" * 40
        get_pool_calls = 0

        def rpc(
            _chain: str,
            method: str,
            params: list[object],
            **_kwargs: object,
        ) -> object:
            nonlocal get_pool_calls
            if method == "eth_getBlockByNumber":
                block = int(str(params[0]), 16)
                return {"hash": "0x" + f"{block:064x}"}
            self.assertEqual(method, "eth_call")
            get_pool_calls += 1
            return "0x" + "0" * 64

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "token": {"address": token},
            "quote": {"address": quote},
        }
        labels = {
            quote: {"class": "quote_token"},
            factory: {
                "class": "v3_factory",
                "fee_tiers": [100],
            },
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_LIQUIDITY_TRACE_BLOCKS": "101",
                    "ALPHA_OPENING_V3_SCOPE_REFRESH_BLOCKS": "50",
                },
            ),
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value=labels,
            ),
            mock.patch.object(opening, "rpc_call", side_effect=rpc),
        ):
            first = opening.supported_v3_pool_scope(event, 200)
            event["opening_v3_pool_scope"] = copy.deepcopy(first)
            cached = opening.supported_v3_pool_scope(event, 249)
            refreshed = opening.supported_v3_pool_scope(event, 250)

        self.assertEqual(cached["as_of_block"], 200)
        self.assertEqual(refreshed["as_of_block"], 250)
        self.assertEqual(get_pool_calls, 2)

    def test_bsc_uniswap_v3_factory_matrix_includes_fee_3000(self) -> None:
        from sniper_engine.address_labels import global_address_labels

        labels = global_address_labels("bsc")
        factory = labels[
            "0xdb1d10011ad0ff90774d0c6bb92e5c5c8b4461f7"
        ]
        manager = labels[
            "0x7b8a01b39d58278b5de7e48c8449c9f4f5170613"
        ]

        self.assertEqual(factory["class"], "v3_factory")
        self.assertEqual(factory["protocol"], "uniswap_v3")
        self.assertIn(3000, factory["fee_tiers"])
        self.assertEqual(manager["class"], "lp_position_manager")

    def test_v3_factory_matrix_reserves_event_budget(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        factory = "0x" + "3" * 40
        deadlines: list[float] = []

        def rpc(
            _chain: str,
            method: str,
            _params: list[object],
            **kwargs: object,
        ) -> object:
            deadlines.append(float(kwargs["deadline"]))
            if method == "eth_getBlockByNumber":
                return {"hash": "0x" + "a" * 64}
            return "0x" + "0" * 64

        labels = {
            quote: {"class": "quote_token"},
            factory: {
                "class": "v3_factory",
                "fee_tiers": [100],
            },
        }
        previous_deadline = opening.TRACE_DEADLINE_AT
        opening.TRACE_DEADLINE_AT = 105.0
        try:
            with (
                mock.patch.object(
                    opening,
                    "global_address_labels",
                    return_value=labels,
                ),
                mock.patch.object(opening.time, "monotonic", return_value=100.0),
                mock.patch.object(opening, "rpc_call", side_effect=rpc),
            ):
                result = opening.supported_v3_pool_scope(
                    {
                        "chain": "bsc",
                        "seconds_until_start": -100,
                        "token": {"address": token},
                        "quote": {"address": quote},
                    },
                    200,
                )
        finally:
            opening.TRACE_DEADLINE_AT = previous_deadline

        self.assertTrue(result["complete"])
        self.assertTrue(deadlines)
        self.assertLessEqual(max(deadlines), 101.25)

    def test_manager_only_liquidity_scope_scans_filtered_events(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        manager = "0x" + "3" * 40
        pool_id = "0x" + "a" * 64
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {
                    "address": manager,
                    "role": "pool_manager",
                    "protocol": "pancakeswap_infinity_cl",
                }
            ],
            "pool_id": pool_id,
            "lp_position_ids": [],
        }
        queries: list[dict[str, object]] = []

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            queries.append(dict(query))
            if query["topics"][0] == opening.V4_SWAP_TOPIC:
                return []
            return [
                {
                    "address": manager,
                    "blockNumber": "0x64",
                    "blockHash": "0x" + "a" * 64,
                    "transactionHash": "0x" + "5" * 64,
                    "logIndex": "0x0",
                    "topics": [opening.DECREASE_LIQUIDITY_TOPIC, pool_id],
                    "data": (
                        "0x"
                        + f"{0:064x}"
                        + f"{200000:064x}"
                        + f"{0:064x}"
                    ),
                }
            ]

        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "verified",
                    "pools": [],
                },
            ),
            mock.patch.object(
                opening,
                "supported_v4_manager_scope",
                return_value={
                    "status": "complete",
                    "complete": True,
                    "configuration_hash": "v4-verified",
                    "pools": [
                        {
                            "address": manager,
                            "role": "pool_manager",
                            "pool_id": pool_id,
                            "token0": token,
                            "token1": quote,
                            "fee": 100,
                            "v4_manager_type": "cl",
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["risk"], "lp_activity_unattributed")
        self.assertTrue(result["watch_scope_hash"])
        self.assertEqual(len(queries), 2)
        lp_query = next(
            query
            for query in queries
            if isinstance(query["topics"][0], list)
        )
        self.assertEqual(lp_query["address"], manager)
        self.assertEqual(lp_query["topics"][1], pool_id)

    def test_position_manager_query_filters_indexed_token_ids(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        manager = "0x" + "3" * 40
        queries: list[dict[str, object]] = []

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            queries.append(dict(query))
            return []

        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            side_effect=fetch,
        ):
            result = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "lp_position_ids": [7, "9"],
                },
                100,
                200,
                {
                    manager: {
                        "role": "lp_position_manager",
                        "label": "position manager",
                    }
                },
            )

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(len(queries), 1)
        self.assertEqual(
            queries[0]["topics"][1],
            ["0x" + f"{7:064x}", "0x" + f"{9:064x}"],
        )

    def test_v4_manager_scope_validates_pool_key_snapshot(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        manager = "0x" + "3" * 40
        pool_id = "0x" + "a" * 64
        block_calls = 0

        def address_word(value: str) -> str:
            return value[2:].rjust(64, "0")

        pool_key = (
            "0x"
            + address_word(token)
            + address_word(quote)
            + address_word(opening.ZERO)
            + address_word(manager)
            + f"{100:064x}"
            + "b" * 64
        )

        def rpc(
            _chain: str,
            method: str,
            params: list[object],
            **_kwargs: object,
        ) -> object:
            nonlocal block_calls
            if method == "eth_getBlockByNumber":
                block_calls += 1
                return {"hash": "0x" + "c" * 64}
            if method == "eth_getCode":
                return "0x6000"
            self.assertEqual(method, "eth_call")
            self.assertEqual(
                params[0]["data"],
                opening.V4_POOL_ID_TO_KEY_SELECTOR + pool_id[2:],
            )
            return pool_key

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "pool_id": pool_id,
            "token": {"address": token},
            "quote": {"address": quote},
        }
        watch = {
            manager: {
                "role": "pool_manager",
                "source": "event_config",
                "label": "Infinity CLPoolManager",
                "protocol": "pancakeswap_infinity_cl",
            }
        }
        with mock.patch.object(opening, "rpc_call", side_effect=rpc):
            result = opening.supported_v4_manager_scope(
                event,
                200,
                watch,
            )

        self.assertTrue(result["complete"])
        self.assertTrue(result["snapshot_coherent"])
        self.assertEqual(block_calls, 2)
        self.assertEqual(result["pools"][0]["token0"], token)
        self.assertEqual(result["pools"][0]["pool_manager"], manager)

    def test_v4_pool_id_auto_probes_canonical_cl_manager(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        manager = opening.PANCAKE_INFINITY_CL_POOL_MANAGER
        pool_id = "0x" + "a" * 64

        def address_word(value: str) -> str:
            return value[2:].rjust(64, "0")

        pool_key = (
            "0x"
            + address_word(token)
            + address_word(quote)
            + address_word(opening.ZERO)
            + address_word(manager)
            + f"{100:064x}"
            + "b" * 64
        )

        def rpc(
            _chain: str,
            method: str,
            _params: list[object],
            **_kwargs: object,
        ) -> object:
            if method == "eth_getBlockByNumber":
                return {"hash": "0x" + "c" * 64}
            if method == "eth_getCode":
                return "0x6000"
            if method == "eth_call":
                return pool_key
            raise AssertionError(method)

        with mock.patch.object(opening, "rpc_call", side_effect=rpc):
            result = opening.supported_v4_manager_scope(
                {
                    "chain": "bsc",
                    "opening_block": 100,
                    "pool_id": pool_id,
                    "token": {"address": token},
                    "quote": {"address": quote},
                },
                200,
                {
                    manager: {
                        "role": "pool_manager",
                        "source": "global_label",
                        "protocol": "pancakeswap_infinity_cl",
                    }
                },
            )

        self.assertTrue(result["complete"])
        self.assertEqual(result["expected_query_count"], 1)
        self.assertEqual(
            result["pools"][0]["source"],
            "canonical_pool_id_probe",
        )
        missing = opening.supported_v4_manager_scope(
            {
                "chain": "bsc",
                "opening_block": 100,
                "pool_id": pool_id,
                "token": {"address": token},
                "quote": {"address": quote},
            },
            200,
            {},
        )
        self.assertFalse(missing["complete"])
        self.assertEqual(
            missing["status"],
            "manager_discovery_unavailable",
        )

    def test_v4_bin_manager_scope_fails_closed_as_unsupported(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        manager = opening.PANCAKE_INFINITY_BIN_POOL_MANAGER
        pool_id = "0x" + "a" * 64
        methods: list[str] = []
        self.assertEqual(
            opening.v4_manager_type(
                manager,
                {"protocol": "pancakeswap_infinity_cl"},
            ),
            "bin",
        )

        def rpc(
            _chain: str,
            method: str,
            _params: list[object],
            **_kwargs: object,
        ) -> object:
            methods.append(method)
            if method == "eth_getBlockByNumber":
                return {"hash": "0x" + "c" * 64}
            raise AssertionError(f"unsupported manager probed with {method}")

        with mock.patch.object(opening, "rpc_call", side_effect=rpc):
            result = opening.supported_v4_manager_scope(
                {
                    "chain": "bsc",
                    "opening_block": 100,
                    "seconds_until_start": -100,
                    "pool_id": pool_id,
                    "token": {"address": token},
                    "quote": {"address": quote},
                },
                200,
                {
                    manager: {
                        "role": "pool_manager",
                        "source": "event_config",
                        "protocol": "pancakeswap_infinity_bin",
                    }
                },
            )

        self.assertFalse(result["complete"])
        self.assertEqual(result["status"], "unsupported_manager_abi")
        self.assertEqual(result["unsupported_manager_count"], 1)
        self.assertEqual(methods, ["eth_getBlockByNumber", "eth_getBlockByNumber"])

    def test_v4_manager_swap_confirms_pool_sell(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        manager = "0x" + "3" * 40
        pool_id = "0x" + "a" * 64
        tx_hash = "0x" + "5" * 64

        def signed_word(value: int) -> str:
            return f"{(value if value >= 0 else 2**256 + value):064x}"

        swap = {
            "address": manager,
            "blockNumber": "0x65",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x2",
            "topics": [
                opening.V4_SWAP_TOPIC,
                pool_id,
                opening.address_topic("0x" + "4" * 40),
            ],
            "data": (
                "0x"
                + signed_word(-200000)
                + signed_word(20000)
                + f"{1:064x}" * 5
            ),
        }

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            return (
                [swap]
                if query["topics"] == [opening.V4_SWAP_TOPIC, pool_id]
                else []
            )

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {
                    "address": manager,
                    "role": "pool_manager",
                    "protocol": "pancakeswap_infinity_cl",
                }
            ],
            "pool_id": pool_id,
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "configuration_hash": "v3",
                    "pools": [],
                },
            ),
            mock.patch.object(
                opening,
                "supported_v4_manager_scope",
                return_value={
                    "status": "complete",
                    "complete": True,
                    "configuration_hash": "v4",
                    "pools": [
                        {
                            "address": manager,
                            "role": "pool_manager",
                            "pool_id": pool_id,
                            "token0": token,
                            "token1": quote,
                            "pool_manager": manager,
                            "fee": 100,
                            "v4_manager_type": "cl",
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)
            buy_event = copy.deepcopy(event)
            swap["data"] = (
                "0x"
                + signed_word(200000)
                + signed_word(-20000)
                + f"{1:064x}" * 5
            )
            buy_result = opening.scan_key_liquidity_flows(buy_event, 200)
            invalid_event = copy.deepcopy(event)
            swap["address"] = "0x" + "9" * 40
            invalid_result = opening.scan_key_liquidity_flows(
                invalid_event,
                200,
            )

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["risk"], "pool_token_in")
        self.assertEqual(result["pool_token_in"], "200000")
        self.assertEqual(result["pool_token_in_quote"], "20000")
        self.assertEqual(
            result["pool_swap_evidence_keys"],
            [opening.liquidity_activity_key(manager, tx_hash)],
        )
        self.assertEqual(buy_result["risk"], "none")
        self.assertEqual(buy_result["pool_token_out"], "200000")
        self.assertEqual(buy_result["pool_token_in"], "0")
        self.assertFalse(invalid_result["coverage_complete"])
        self.assertEqual(
            invalid_result["risk"],
            "unknown_incomplete_coverage",
        )
        self.assertEqual(invalid_result["pool_token_in"], "0")

    def test_unverified_explicit_pool_fails_closed_without_logs(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        bogus_pool = "0x" + "3" * 40
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {"address": bogus_pool, "role": "pool"}
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "configuration_hash": "verified",
                    "pools": [],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                return_value=[],
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertFalse(result["scope_complete"])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["risk"], "unknown_incomplete_coverage")
        self.assertEqual(
            result["coverage_status"],
            "explicit_liquidity_scope_unverified",
        )

    def test_short_modify_liquidity_event_fails_closed(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        manager = "0x" + "3" * 40
        pool_id = "0x" + "a" * 64
        malformed = {
            "address": manager,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "5" * 64,
            "logIndex": "0x0",
            "topics": [opening.MODIFY_LIQUIDITY_TOPIC, pool_id],
            "data": "0x" + "0" * 192,
        }
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            return_value=[malformed],
        ):
            result = opening.scan_liquidity_events(
                {"chain": "bsc", "pool_id": pool_id},
                100,
                200,
                {
                    manager: {
                        "role": "pool_manager",
                        "source": "event_config",
                        "v4_validation_status": "pool_key_verified",
                        "v4_manager_type": "cl",
                    }
                },
            )

        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["decode_error_count"], 1)

    def test_rpc_log_identity_rejects_wrong_emitter_topic_and_tx(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        pool = "0x" + "3" * 40
        query = {
            "address": pool,
            "fromBlock": "0x64",
            "toBlock": "0xc8",
            "topics": [opening.V3_SWAP_TOPIC],
        }
        valid = {
            "address": pool,
            "blockNumber": "0x65",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "5" * 64,
            "logIndex": "0x0",
            "topics": [opening.V3_SWAP_TOPIC],
        }
        self.assertIsNotNone(opening.strict_rpc_log_identity(valid, query))
        for mutation in (
            {"address": "0x" + "4" * 40},
            {"topics": [opening.V4_SWAP_TOPIC]},
            {"transactionHash": ""},
            {"blockHash": ""},
            {"blockNumber": "0xc9"},
            {"removed": True},
            {"removed": "true"},
            {"removed": 1},
        ):
            with self.subTest(mutation=mutation):
                self.assertIsNone(
                    opening.strict_rpc_log_identity(
                        {**valid, **mutation},
                        query,
                    )
                )

        seen: dict[tuple[str, str, int], str] = {}
        identity = opening.strict_rpc_log_identity(valid, query)
        assert identity is not None
        self.assertEqual(
            opening.rpc_log_duplicate_state(valid, query, identity, seen),
            "new",
        )
        self.assertEqual(
            opening.rpc_log_duplicate_state(valid, query, identity, seen),
            "duplicate",
        )
        self.assertEqual(
            opening.rpc_log_duplicate_state(
                {**valid, "data": "0x" + "1" * 64},
                query,
                identity,
                seen,
            ),
            "conflict",
        )

    def test_pool_sell_alert_evidence_uses_latest_sell_only(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        old_sell_tx = "0x" + "f" * 64
        new_sell_tx = "0x" + "1" * 64
        newer_buy_tx = "0x" + "e" * 64

        def words(*values: int) -> str:
            return "0x" + "".join(
                f"{(value if value >= 0 else 2**256 + value):064x}"
                for value in values
            )

        swaps = [
            {
                "address": pool,
                "blockNumber": block,
                "blockHash": "0x" + block[2:].rjust(64, "0"),
                "transactionHash": tx,
                "logIndex": "0x1",
                "topics": [opening.V3_SWAP_TOPIC],
                "data": words(amount, -amount, 1, 1, 1),
            }
            for block, tx, amount in (
                ("0x64", old_sell_tx, 200000),
                ("0x65", new_sell_tx, 200000),
                ("0x66", newer_buy_tx, -100000),
            )
        ]

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            return swaps if query["topics"] == [opening.V3_SWAP_TOPIC] else []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [{"address": pool, "role": "pool"}],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "configuration_hash": "verified",
                    "pools": [
                        {
                            "address": pool,
                            "token0": token,
                            "token1": quote,
                            "factory": "0x" + "9" * 40,
                            "fee": 100,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        old_key = opening.liquidity_activity_key(pool, old_sell_tx)
        new_key = opening.liquidity_activity_key(pool, new_sell_tx)
        buy_key = opening.liquidity_activity_key(pool, newer_buy_tx)
        self.assertEqual(
            result["pool_swap_evidence_keys"],
            [old_key, new_key],
        )
        self.assertNotIn(buy_key, result["pool_swap_evidence_keys"])
        alert_event = {
            "symbol": "TEST",
            "status": "opened",
            "opening_block": 100,
            "pool_id": "",
            "analysis": {"liquidity_flow_risk": "pool_token_in"},
            "liquidity_flow": result,
            "rows": [],
        }
        alert_key = next(
            key
            for key in opening.event_alert_keys(alert_event)
            if key.startswith("liquidity_flow|")
        )
        self.assertTrue(alert_key.endswith(new_key))

    def test_hook_only_scope_does_not_skip_factory_discovery(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "hook": "0x" + "3" * 40,
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "factory_matrix_partial",
                    "complete": False,
                    "expected_query_count": 1,
                    "configuration_hash": "scope",
                    "pools": [],
                },
            ) as discover,
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                return_value=[],
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        discover.assert_called_once()
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["risk"], "unknown_incomplete_coverage")

    def test_missing_required_factory_config_fails_closed(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {
                "address": "0x" + "1" * 40,
                "symbol": "TEST",
                "decimals": 18,
            },
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "watch_addresses": [
                {"address": "0x" + "3" * 40, "role": "pool"}
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                return_value=[],
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertFalse(result["scope_complete"])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["risk"], "unknown_incomplete_coverage")

    def test_explicit_pool_metadata_wins_over_operator_alias(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        pool = "0x" + "3" * 40
        with mock.patch.object(
            opening,
            "global_address_labels",
            return_value={},
        ):
            watch = opening.liquidity_watch_addresses(
                {
                    "chain": "bsc",
                    "watch_addresses": [
                        {
                            "address": pool,
                            "role": "pool",
                            "watch_quote": True,
                        }
                    ],
                    "operator": pool,
                }
            )

        self.assertEqual(watch[pool]["role"], "pool")
        self.assertEqual(watch[pool]["watch_quote"], "true")

    def test_unverified_explicit_pool_cannot_claim_confirmed_swap(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        bogus_pool = "0x" + "3" * 40
        valid_pool = "0x" + "4" * 40
        trader = "0x" + "5" * 40
        tx_hash = "0x" + "6" * 64
        transfer = {
            "address": token,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x0",
            "topics": [
                opening.TRANSFER_TOPIC,
                opening.address_topic(trader),
                opening.address_topic(bogus_pool),
            ],
            "data": "0x" + f"{200000:064x}",
        }

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            topics = query["topics"]
            if query["address"] == token and len(topics) >= 3:
                if topics[2] == opening.address_topic(bogus_pool):
                    return [transfer]
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {
                    "address": bogus_pool,
                    "role": "pool",
                    "token0": token,
                    "token1": quote,
                }
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "verified",
                    "pools": [
                        {
                            "address": valid_pool,
                            "token0": token,
                            "token1": quote,
                            "factory": "0x" + "9" * 40,
                            "fee": 100,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertEqual(result["pool_token_in"], "0")
        self.assertEqual(result["pool_token_in_unconfirmed"], "200000")
        self.assertEqual(result["risk"], "unknown_incomplete_coverage")

    def test_liquidity_signal_survives_empty_opening_cohort(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        result = opening.analyze_opened(
            {
                "symbol": "TEST",
                "quote": {"symbol": "USDT"},
                "market_context": {},
                "liquidity_flow": {
                    "risk": "pool_token_in",
                    "summary": "Swap确认卖入池 200K TEST",
                },
            },
            [],
            allow_rpc=False,
        )

        self.assertEqual(result["liquidity_flow_risk"], "pool_token_in")
        self.assertIn("池内大额卖入", result["trade_signal"])
        self.assertNotIn("没有真实成交", result["trade_signal"])

    def test_liquidity_alert_upgrade_is_not_swallowed_by_legacy_key(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        def alert(amount: str, tx_suffix: str) -> str:
            event = {
                "symbol": "TEST",
                "status": "opened",
                "opening_block": 100,
                "pool_id": "",
                "analysis": {
                    "liquidity_flow_risk": "pool_token_in",
                },
                "liquidity_flow": {
                    "pool_token_in": amount,
                    "pool_swap_evidence_keys": [
                        "0x" + "3" * 40 + ":0x" + tx_suffix * 64
                    ],
                },
                "rows": [],
            }
            return next(
                key
                for key in opening.event_alert_keys(event)
                if key.startswith("liquidity_flow|")
            )

        first = alert("200000", "5")
        upgraded = alert("500000", "6")
        legacy = {"liquidity_flow|TEST|100|pool_token_in"}
        self.assertNotEqual(first, upgraded)
        self.assertFalse(opening.alert_key_seen(first, legacy))
        self.assertFalse(opening.alert_key_seen(upgraded, legacy))
        self.assertTrue(opening.alert_key_seen(first, {first}))

    def test_confirmed_pool_sell_has_critical_readable_telegram_evidence(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "symbol": "TEST",
            "status": "opened",
            "opening_block": 100,
            "pool_id": "",
            "priority": "P1",
            "token": {"symbol": "TEST"},
            "quote": {"symbol": "USDT"},
            "analysis": {
                "liquidity_flow_risk": "pool_token_in",
                "trade_signal": "降低风险；池内大额卖入",
                "direction": "偏空",
            },
            "liquidity_flow": {
                "pool_token_in": "200000",
                "pool_swap_evidence_keys": [
                    "0x" + "3" * 40 + ":0x" + "5" * 64
                ],
            },
            "rows": [],
        }
        self.assertEqual(opening.telegram_event_rank(event)[0], 0)
        self.assertIn(
            "Swap确认卖入200K TEST",
            opening.telegram_event_evidence(event),
        )

        lp_event = copy.deepcopy(event)
        lp_event["analysis"] = {
            "liquidity_flow_risk": "lp_activity_unattributed",
            "trade_signal": "观察；LP 活动未归因",
            "direction": "观察",
        }
        lp_event["liquidity_flow"] = {"liquidity_events": []}
        self.assertEqual(opening.telegram_event_rank(lp_event)[0], 2)
        self.assertIn(
            "LP活动未归因",
            opening.telegram_event_evidence(lp_event),
        )

    def test_liquidity_flow_keeps_mm_and_excludes_generic_manager(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        mm = "0x" + "4" * 40
        manager = "0x" + "5" * 40
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 18},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 18},
            "watch_addresses": [
                {"address": pool, "role": "pool"},
                {"address": mm, "role": "market_maker", "watch_quote": True},
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        labels = {
            manager: {"class": "pool_manager", "label": "generic manager"}
        }
        queries: list[dict[str, object]] = []

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            queries.append(dict(query))
            return []

        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value=labels,
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "verified",
                    "pools": [
                        {
                            "address": pool,
                            "token0": token,
                            "token1": quote,
                            "factory": "0x" + "9" * 40,
                            "fee": 100,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        topics = {
            topic
            for query in queries
            for topic in query.get("topics", [])
            if isinstance(topic, str)
        }
        self.assertTrue(result["coverage_complete"])
        self.assertIn(opening.address_topic(pool), topics)
        self.assertIn(opening.address_topic(mm), topics)
        self.assertNotIn(opening.address_topic(manager), topics)

    def test_pool_buy_is_context_and_pool_sell_is_risk(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        trader = "0x" + "4" * 40
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {
                    "address": pool,
                    "role": "pool",
                    "token0": token,
                    "token1": quote,
                }
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }

        def transfer(sender: str, recipient: str) -> dict[str, object]:
            return {
                "address": token,
                "blockNumber": "0x64",
                "blockHash": "0x" + "a" * 64,
                "transactionHash": "0x" + "5" * 64,
                "logIndex": "0x0",
                "topics": [
                    opening.TRANSFER_TOPIC,
                    opening.address_topic(sender),
                    opening.address_topic(recipient),
                ],
                "data": "0x" + f"{200000:064x}",
            }

        def words(*values: int) -> str:
            return "0x" + "".join(
                f"{(value if value >= 0 else 2**256 + value):064x}"
                for value in values
            )

        def scan(
            log: dict[str, object],
            swap_amount: int | None,
            liquidity_logs: list[dict[str, object]] | None = None,
        ) -> dict[str, object]:
            def fetch(
                _event: dict[str, object],
                query: dict[str, object],
                *_args: object,
            ) -> list[dict[str, object]]:
                topics = query["topics"]
                if topics == [opening.V3_SWAP_TOPIC]:
                    if swap_amount is None:
                        return []
                    return [
                        {
                            "address": pool,
                            "blockNumber": "0x64",
                            "blockHash": "0x" + "a" * 64,
                            "transactionHash": log["transactionHash"],
                            "logIndex": "0x1",
                            "topics": [opening.V3_SWAP_TOPIC],
                            "data": words(
                                swap_amount,
                                -swap_amount,
                                1,
                                1,
                                1,
                            ),
                        }
                    ]
                if topics and isinstance(topics[0], list):
                    return list(liquidity_logs or [])
                if len(topics) < 3:
                    return []
                return [log] if all(
                    expected is None or expected == actual
                    for expected, actual in zip(topics[1:3], log["topics"][1:3])
                ) else []

            with (
                mock.patch.object(
                    opening,
                    "global_address_labels",
                    return_value={},
                ),
                mock.patch.object(
                    opening,
                    "supported_v3_pool_scope",
                    return_value={
                        "status": "complete_tracked_factory_matrix",
                        "complete": True,
                        "expected_query_count": 1,
                        "configuration_hash": "verified",
                        "pools": [
                            {
                                "address": pool,
                                "token0": token,
                                "token1": quote,
                                "factory": "0x" + "9" * 40,
                                "fee": 100,
                            }
                        ],
                    },
                ),
                mock.patch.object(
                    opening,
                    "snapshot_cached_get_logs",
                    side_effect=fetch,
                ),
            ):
                return opening.scan_key_liquidity_flows(
                    copy.deepcopy(event),
                    200,
                )

        buy = scan(transfer(pool, trader), -200000)
        sell = scan(transfer(trader, pool), 200000)
        bare_transfer = scan(transfer(trader, pool), None)
        partial_swap = scan(transfer(trader, pool), 1)
        mint_log = {
            "address": pool,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "5" * 64,
            "logIndex": "0x2",
            "topics": [opening.V3_MINT_TOPIC],
            "data": words(0, 1, 200000, 1),
        }
        liquidity_add = scan(
            transfer(trader, pool),
            None,
            [mint_log],
        )
        large_burn = {
            "address": pool,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "6" * 64,
            "logIndex": "0x2",
            "topics": [opening.V3_BURN_TOPIC],
            "data": words(1, 200000, 1),
        }
        sell_with_lp_observation = scan(
            transfer(trader, pool),
            200000,
            [large_burn],
        )
        self.assertEqual(buy["risk"], "none")
        self.assertEqual(buy["pool_token_out"], "200000")
        self.assertEqual(sell["risk"], "pool_token_in")
        self.assertEqual(sell["pool_token_in"], "200000")
        self.assertEqual(bare_transfer["risk"], "unknown_incomplete_coverage")
        self.assertEqual(
            bare_transfer["pool_token_in_unconfirmed"],
            "200000",
        )
        self.assertFalse(bare_transfer["coverage_complete"])
        self.assertEqual(partial_swap["pool_token_in"], "1")
        self.assertEqual(
            partial_swap["pool_token_in_unconfirmed"],
            "199999",
        )
        self.assertEqual(
            partial_swap["risk"],
            "unknown_incomplete_coverage",
        )
        self.assertEqual(liquidity_add["risk"], "none")
        self.assertEqual(liquidity_add["pool_token_in"], "0")
        self.assertEqual(
            liquidity_add["pool_token_in_unconfirmed"],
            "0",
        )
        self.assertEqual(
            sell_with_lp_observation["risk"],
            "pool_token_in",
        )

    def test_v3_swap_tracks_non_event_quote_pool(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        event_quote = "0x" + "2" * 40
        counterasset = "0x" + "3" * 40
        pool = "0x" + "4" * 40
        trader = "0x" + "5" * 40
        tx_hash = "0x" + "6" * 64

        def words(*values: int) -> str:
            return "0x" + "".join(
                f"{(value if value >= 0 else 2**256 + value):064x}"
                for value in values
            )

        transfer = {
            "address": token,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x0",
            "topics": [
                opening.TRANSFER_TOPIC,
                opening.address_topic(trader),
                opening.address_topic(pool),
            ],
            "data": "0x" + f"{200000:064x}",
        }
        swap = {
            "address": pool,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x1",
            "topics": [opening.V3_SWAP_TOPIC],
            "data": words(200000, -10, 1, 1, 1),
        }

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            topics = query["topics"]
            if topics == [opening.V3_SWAP_TOPIC]:
                return [swap]
            if topics and isinstance(topics[0], list):
                return []
            if len(topics) >= 3 and topics[2] == opening.address_topic(pool):
                return [transfer]
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {
                "address": event_quote,
                "symbol": "USDT",
                "decimals": 0,
            },
            "watch_addresses": [
                {
                    "address": pool,
                    "role": "pool",
                    "token0": token,
                    "token1": counterasset,
                }
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "verified",
                    "pools": [
                        {
                            "address": pool,
                            "token0": token,
                            "token1": counterasset,
                            "factory": "0x" + "9" * 40,
                            "fee": 100,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertEqual(result["risk"], "pool_token_in")
        self.assertEqual(result["pool_token_in"], "200000")

    def test_v3_pool_sell_threshold_prefers_quote_value(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        tx_hash = "0x" + "4" * 64

        def words(*values: int) -> str:
            return "0x" + "".join(
                f"{(value if value >= 0 else 2**256 + value):064x}"
                for value in values
            )

        swap = {
            "address": pool,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x0",
            "topics": [opening.V3_SWAP_TOPIC],
            "data": "",
        }
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "pool_id": "",
            "lp_position_ids": [],
        }

        def run(amounts: list[tuple[int, int]]) -> dict[str, object]:
            swap_rows = [
                {
                    **swap,
                    "logIndex": hex(index),
                    "data": words(
                        amount_token,
                        -amount_quote,
                        1,
                        1,
                        1,
                    ),
                }
                for index, (amount_token, amount_quote) in enumerate(amounts)
            ]

            def fetch(
                _event: dict[str, object],
                query: dict[str, object],
                *_args: object,
            ) -> list[dict[str, object]]:
                return (
                    swap_rows
                    if query["topics"] == [opening.V3_SWAP_TOPIC]
                    else []
                )

            with (
                mock.patch.object(opening, "global_address_labels", return_value={}),
                mock.patch.object(
                    opening,
                    "supported_v3_pool_scope",
                    return_value={
                        "status": "complete_tracked_factory_matrix",
                        "complete": True,
                        "configuration_hash": "verified",
                        "pools": [
                            {
                                "address": pool,
                                "token0": token,
                                "token1": quote,
                                "factory": "0x" + "9" * 40,
                                "fee": 100,
                            }
                        ],
                    },
                ),
                mock.patch.object(
                    opening,
                    "snapshot_cached_get_logs",
                    side_effect=fetch,
                ),
            ):
                return opening.scan_key_liquidity_flows(
                    copy.deepcopy(event),
                    200,
                )

        low_value = run([(200000, 10)])
        high_value = run([(5, 20000)])
        quote_negative_roundtrip = run(
            [(200000, 20000), (-50000, -30000)]
        )

        self.assertEqual(low_value["risk"], "none")
        self.assertEqual(low_value["pool_token_in"], "200000")
        self.assertEqual(low_value["pool_token_in_quote"], "10")
        self.assertEqual(high_value["risk"], "pool_token_in")
        self.assertEqual(high_value["pool_token_in"], "5")
        self.assertEqual(high_value["pool_token_in_quote"], "20000")
        self.assertEqual(quote_negative_roundtrip["risk"], "none")
        self.assertEqual(
            quote_negative_roundtrip["pool_token_in"],
            "150000",
        )
        self.assertEqual(
            quote_negative_roundtrip["pool_token_in_quote"],
            "0",
        )

    def test_v3_same_transaction_roundtrip_uses_net_swap_delta(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        trader = "0x" + "4" * 40
        tx_hash = "0x" + "5" * 64

        def words(*values: int) -> str:
            return "0x" + "".join(
                f"{(value if value >= 0 else 2**256 + value):064x}"
                for value in values
            )

        def transfer(sender: str, recipient: str) -> dict[str, object]:
            return {
                "address": token,
                "blockNumber": "0x64",
                "blockHash": "0x" + "a" * 64,
                "transactionHash": tx_hash,
                "logIndex": "0x0",
                "topics": [
                    opening.TRANSFER_TOPIC,
                    opening.address_topic(sender),
                    opening.address_topic(recipient),
                ],
                "data": "0x" + f"{200000:064x}",
            }

        inbound = transfer(trader, pool)
        outbound = transfer(pool, trader)
        swaps = [
            {
                "address": pool,
                "blockNumber": "0x64",
                "blockHash": "0x" + "a" * 64,
                "transactionHash": tx_hash,
                "logIndex": hex(index + 1),
                "topics": [opening.V3_SWAP_TOPIC],
                "data": words(amount, -amount, 1, 1, 1),
            }
            for index, amount in enumerate((200000, -200000))
        ]

        def fetch(
            _event: dict[str, object],
            query: dict[str, object],
            *_args: object,
        ) -> list[dict[str, object]]:
            topics = query["topics"]
            if topics == [opening.V3_SWAP_TOPIC]:
                return swaps
            if topics and isinstance(topics[0], list):
                return []
            if topics[1] == opening.address_topic(pool):
                return [outbound]
            if topics[2] == opening.address_topic(pool):
                return [inbound]
            return []

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "seconds_until_start": -100,
            "token": {"address": token, "symbol": "TEST", "decimals": 0},
            "quote": {"address": quote, "symbol": "USDT", "decimals": 0},
            "watch_addresses": [
                {
                    "address": pool,
                    "role": "pool",
                    "token0": token,
                    "token1": quote,
                }
            ],
            "pool_id": "",
            "lp_position_ids": [],
        }
        with (
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                opening,
                "supported_v3_pool_scope",
                return_value={
                    "status": "complete_tracked_factory_matrix",
                    "complete": True,
                    "expected_query_count": 1,
                    "configuration_hash": "verified",
                    "pools": [
                        {
                            "address": pool,
                            "token0": token,
                            "token1": quote,
                            "factory": "0x" + "9" * 40,
                            "fee": 100,
                        }
                    ],
                },
            ),
            mock.patch.object(
                opening,
                "snapshot_cached_get_logs",
                side_effect=fetch,
            ),
        ):
            result = opening.scan_key_liquidity_flows(event, 200)

        self.assertEqual(result["risk"], "none")
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["pool_token_in"], "0")
        self.assertEqual(result["pool_token_out"], "0")
        self.assertEqual(result["pool_token_in_unconfirmed"], "0")
        self.assertEqual(result["pool_token_out_unconfirmed"], "0")

    def test_v3_rebalance_is_not_sell_signal(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool = "0x" + "3" * 40

        def words(*values: int) -> str:
            return "0x" + "".join(f"{value:064x}" for value in values)

        logs = [
            {
                "address": pool,
                "blockNumber": "0x64",
                "blockHash": "0x" + "a" * 64,
                "transactionHash": "0x" + "5" * 64,
                "logIndex": "0x0",
                "topics": [opening.V3_BURN_TOPIC],
                "data": words(4, 5, 6),
            },
            {
                "address": pool,
                "blockNumber": "0x64",
                "blockHash": "0x" + "a" * 64,
                "transactionHash": "0x" + "5" * 64,
                "logIndex": "0x1",
                "topics": [opening.V3_MINT_TOPIC],
                "data": words(0, 10, 20, 30),
            },
        ]
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            side_effect=[logs, [logs[0]]],
        ):
            rebalance = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {
                    pool: {
                        "role": "pool",
                        "label": "V3 pool",
                        "token0": token,
                        "token1": quote,
                    }
                },
            )
            removal = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {
                    pool: {
                        "role": "pool",
                        "label": "V3 pool",
                        "token0": token,
                        "token1": quote,
                    }
                },
            )

        self.assertEqual(rebalance["risk"], "none")
        self.assertEqual(
            [row["event"] for row in rebalance["events"]],
            ["V3Burn", "V3Mint"],
        )
        self.assertEqual(removal["risk"], "none")

        large_burn = dict(logs[0])
        large_burn["data"] = words(4, 200000, 6)
        equal_mint = dict(logs[1])
        equal_mint["data"] = words(0, 1, 200000, 1)
        dust_mint = dict(logs[1])
        dust_mint["data"] = words(0, 1, 1, 1)
        collect = {
            "address": pool,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "5" * 64,
            "logIndex": "0x2",
            "topics": [opening.V3_COLLECT_TOPIC],
            "data": words(0, 200000, 1),
        }
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            side_effect=[
                [large_burn, equal_mint],
                [large_burn, collect, equal_mint],
                [large_burn, dust_mint],
            ],
        ):
            equal_rebalance = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {
                    pool: {
                        "role": "pool",
                        "label": "V3 pool",
                        "token0": token,
                        "token1": quote,
                    }
                },
            )
            burn_collect_rebalance = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {
                    pool: {
                        "role": "pool",
                        "label": "V3 pool",
                        "token0": token,
                        "token1": quote,
                    }
                },
            )
            large_rebalance = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {
                    pool: {
                        "role": "pool",
                        "label": "V3 pool",
                        "token0": token,
                        "token1": quote,
                    }
                },
            )
        self.assertEqual(equal_rebalance["risk"], "none")
        self.assertEqual(burn_collect_rebalance["risk"], "none")
        self.assertEqual(
            large_rebalance["risk"],
            "lp_activity_unattributed",
        )

    def test_cross_pool_migration_is_not_same_pool_rebalance(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        pool_a = "0x" + "3" * 40
        pool_b = "0x" + "4" * 40
        tx_hash = "0x" + "5" * 64

        def words(*values: int) -> str:
            return "0x" + "".join(f"{value:064x}" for value in values)

        burn = {
            "address": pool_a,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x0",
            "topics": [opening.V3_BURN_TOPIC],
            "data": words(1, 200000, 1),
        }
        mint = {
            "address": pool_b,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": tx_hash,
            "logIndex": "0x1",
            "topics": [opening.V3_MINT_TOPIC],
            "data": words(0, 1, 200000, 1),
        }
        meta = {
            "role": "pool",
            "token0": token,
            "token1": quote,
        }
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            side_effect=[[burn], [mint]],
        ):
            result = opening.scan_liquidity_events(
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "token": {"address": token, "decimals": 0},
                },
                100,
                200,
                {pool_a: dict(meta), pool_b: dict(meta)},
            )

        self.assertEqual(result["risk"], "lp_activity_unattributed")
        self.assertNotIn("同交易再平衡", result["summary"])

    def test_malformed_liquidity_event_fails_coverage_closed(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        pool = "0x" + "3" * 40
        with mock.patch.object(
            opening,
            "snapshot_cached_get_logs",
            return_value=[
                {
                    "address": pool,
                    "blockNumber": "0x64",
                    "blockHash": "0x" + "a" * 64,
                    "transactionHash": "0x" + "5" * 64,
                    "logIndex": "0x0",
                    "topics": [opening.V3_BURN_TOPIC],
                    "data": "0x01",
                }
            ],
        ):
            result = opening.scan_liquidity_events(
                {"chain": "bsc", "pool_id": ""},
                100,
                200,
                {pool: {"role": "pool"}},
            )

        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["coverage_status"], "event_decode_incomplete")
        self.assertEqual(result["decode_error_count"], 1)

    def test_liquidity_scope_hash_includes_pool_and_positions(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        watch = {
            "0x" + "3" * 40: {
                "role": "pool_manager",
                "watch_quote": "false",
            }
        }
        base = opening.liquidity_watch_scope_hash(
            watch,
            {"pool_id": "", "lp_position_ids": []},
        )
        with_pool = opening.liquidity_watch_scope_hash(
            watch,
            {
                "pool_id": "0x" + "a" * 64,
                "lp_position_ids": [],
            },
        )
        with_position = opening.liquidity_watch_scope_hash(
            watch,
            {"pool_id": "", "lp_position_ids": [7]},
        )

        self.assertNotEqual(base, with_pool)
        self.assertNotEqual(base, with_position)

        topics_without_collect = set(opening.LIQUIDITY_EVENT_TOPICS)
        topics_without_collect.remove(opening.V3_COLLECT_TOPIC)
        with mock.patch.object(
            opening,
            "LIQUIDITY_EVENT_TOPICS",
            topics_without_collect,
        ):
            previous_semantics = opening.liquidity_watch_scope_hash(
                watch,
                {"pool_id": "", "lp_position_ids": []},
            )
        self.assertNotEqual(base, previous_semantics)

    def test_snapshot_log_cache_is_success_only_and_returns_copies(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        query = {
            "address": "0x" + "1" * 40,
            "fromBlock": "0x64",
            "toBlock": "0xc8",
            "topics": [opening.TRANSFER_TOPIC],
        }
        shared_cache: dict[object, object] = {}
        first_event = {
            "chain": "bsc",
            "_opening_snapshot_log_cache": shared_cache,
        }
        second_event = {
            "chain": "bsc",
            "_opening_snapshot_log_cache": shared_cache,
        }
        source_rows = [{"transactionHash": "0x" + "2" * 64}]
        with mock.patch.object(
            opening,
            "get_logs_quick",
            return_value=source_rows,
        ) as fetch:
            first = opening.snapshot_cached_get_logs(
                first_event,
                query,
                5000,
                5000,
                3,
            )
            first.append({"transactionHash": "mutated"})
            second = opening.snapshot_cached_get_logs(
                second_event,
                query,
                5000,
                5000,
                3,
            )

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(second, source_rows)
        with mock.patch.object(
            opening,
            "ensure_trace_deadline",
            side_effect=opening.OpeningTraceDeadlineExceeded(),
        ):
            with self.assertRaises(
                opening.OpeningTraceDeadlineExceeded
            ):
                opening.snapshot_cached_get_logs(
                    second_event,
                    query,
                    5000,
                    5000,
                    3,
                )

        failed_cache: dict[object, object] = {}
        failed_event = {
            "chain": "bsc",
            "_opening_snapshot_log_cache": failed_cache,
        }
        with mock.patch.object(
            opening,
            "get_logs_quick",
            side_effect=[
                opening.OpeningTraceDeadlineExceeded(),
                [],
            ],
        ) as fetch:
            with self.assertRaises(
                opening.OpeningTraceDeadlineExceeded
            ):
                opening.snapshot_cached_get_logs(
                    failed_event,
                    query,
                    5000,
                    5000,
                    3,
                )
            recovered = opening.snapshot_cached_get_logs(
                failed_event,
                query,
                5000,
                5000,
                3,
            )

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(recovered, [])
        self.assertEqual(len(failed_cache), 1)

    def test_snapshot_log_cache_separates_indexed_manager_scope(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        manager = "0x" + "1" * 40
        first_pool = "0x" + "a" * 64
        second_pool = "0x" + "b" * 64
        shared_cache: dict[object, object] = {}
        watch = {
            manager: {
                "role": "pool_manager",
                "label": "manager",
                "source": "event_config",
                "v4_validation_status": "pool_key_verified",
                "v4_manager_type": "cl",
            }
        }
        raw_log = {
            "address": manager,
            "blockNumber": "0x64",
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "2" * 64,
            "logIndex": "0x0",
            "topics": [
                opening.DECREASE_LIQUIDITY_TOPIC,
                second_pool,
            ],
            "data": "0x" + "0" * 192,
        }
        first_event = {
            "chain": "bsc",
            "pool_id": first_pool,
            "_opening_snapshot_log_cache": shared_cache,
        }
        second_event = {
            "chain": "bsc",
            "pool_id": second_pool,
            "_opening_snapshot_log_cache": shared_cache,
        }
        with mock.patch.object(
            opening,
            "get_logs_quick",
            return_value=[raw_log],
        ) as fetch:
            first = opening.scan_liquidity_events(
                first_event,
                100,
                200,
                watch,
            )
            second = opening.scan_liquidity_events(
                second_event,
                100,
                200,
                watch,
            )

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first["rows"], 0)
        self.assertEqual(first["risk"], "none")
        self.assertFalse(first["coverage_complete"])
        self.assertEqual(second["rows"], 1)
        self.assertEqual(second["risk"], "lp_activity_unattributed")

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

    def test_v3_swap_emitter_is_excluded_when_executor_is_not_the_seller(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        executor = "0x" + "3" * 40
        seller = "0x" + "4" * 40
        router = "0x" + "5" * 40
        pool = "0x4f28db6fdc5d85b5936ac202e59b4f8e4a64ad6c"
        tx_hash = "0x" + "6" * 64
        event = {
            "chain": "bsc",
            "token": {"address": token, "decimals": 8},
            "quote": {"address": quote, "decimals": 18},
        }
        transfers = [
            {
                "tx": tx_hash,
                "log_index": 1,
                "token": token,
                "from": seller,
                "to": router,
                "amount": opening.Decimal("1000"),
            },
            {
                "tx": tx_hash,
                "log_index": 2,
                "token": quote,
                "from": pool,
                "to": router,
                "amount": opening.Decimal("600"),
            },
            {
                "tx": tx_hash,
                "log_index": 3,
                "token": token,
                "from": router,
                "to": pool,
                "amount": opening.Decimal("1000"),
            },
            {
                "tx": tx_hash,
                "log_index": 4,
                "token": quote,
                "from": router,
                "to": seller,
                "amount": opening.Decimal("600"),
            },
        ]
        receipt = {
            "status": "0x1",
            "from": executor,
            "blockNumber": "0x64",
            "transactionIndex": "0x1",
            "logs": [
                {
                    "address": pool,
                    "topics": [opening.V3_SWAP_TOPIC],
                }
            ],
        }
        nets = opening.net_by_address(transfers, token, quote)
        swap_emitters = opening.receipt_swap_emitters(receipt)
        self.assertEqual(swap_emitters, {pool})
        self.assertEqual(
            opening.best_buyer(event, nets, executor, swap_emitters),
            ("", opening.Decimal(0), opening.Decimal(0)),
        )
        self.assertEqual(
            opening.receipt_direction_buyer_exclusion_reason(
                nets,
                pool,
                executor,
                swap_emitters,
            ),
            "receipt_swap_emitter_counterparty",
        )

        with (
            mock.patch.object(
                opening,
                "quick_rpc_call",
                side_effect=[
                    {"from": executor, "to": router, "input": "0x12345678"},
                    receipt,
                ],
            ),
            mock.patch.object(
                opening,
                "receipt_transfers_from_receipt",
                return_value=transfers,
            ),
            mock.patch.object(
                opening,
                "largest_internal_native",
                return_value={"amount": "0"},
            ),
        ):
            opening_row = opening.summarize_tx(event, tx_hash)
        self.assertEqual(opening_row["buyer"], "")
        self.assertEqual(
            opening_row["buyer_exclusion_reason"],
            "receipt_swap_emitter_counterparty",
        )

        previous = {
            "as_of_block": "100",
            "coverage_complete": True,
            "confirmed_sell_quote_received": "600",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [
                {
                    "tx": tx_hash,
                    "log_index": 2,
                    "quote_received": "600",
                    "route": "direct",
                    "recipient": pool,
                }
            ],
        }
        with (
            mock.patch.object(opening, "quick_rpc_call", return_value=receipt),
            mock.patch.object(
                opening,
                "receipt_transfers_from_receipt",
                return_value=transfers,
            ),
            mock.patch.object(opening, "token_balance") as token_balance,
            mock.patch.object(opening, "get_logs_quick") as get_logs,
        ):
            refreshed = opening.trace_buyer(
                event,
                pool,
                100,
                100,
                opening.Decimal("1000"),
                previous,
                tx_hash,
            )
        token_balance.assert_not_called()
        get_logs.assert_not_called()
        self.assertEqual(refreshed["status"], "excluded_non_cohort_subject")
        self.assertEqual(refreshed["confirmed_sell_quote_received"], "0")
        self.assertEqual(refreshed["confirmed_sell_evidence"], [])
        self.assertEqual(
            refreshed["subject_exclusion_reason"],
            "receipt_swap_emitter_counterparty",
        )

    def test_pool_counterparty_is_not_buyer_or_confirmed_seller(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        initiator = "0x" + "3" * 40
        pool = "0x4f28db6fdc5d85b5936ac202e59b4f8e4a64ad6c"
        event = {
            "chain": "bsc",
            "token": {"address": token, "decimals": 8},
            "quote": {"address": quote, "decimals": 18},
        }
        buy_tx = "0x" + "6" * 64
        buy_transfers = [
            {"tx": buy_tx, "log_index": 1, "token": quote, "from": initiator, "to": pool, "amount": opening.Decimal("600")},
            {"tx": buy_tx, "log_index": 2, "token": token, "from": pool, "to": initiator, "amount": opening.Decimal("1000")},
        ]
        sell_tx = "0x" + "7" * 64
        sell_transfers = [
            {"tx": sell_tx, "log_index": 1, "token": token, "from": initiator, "to": pool, "amount": opening.Decimal("1000")},
            {"tx": sell_tx, "log_index": 2, "token": quote, "from": pool, "to": initiator, "amount": opening.Decimal("500")},
        ]
        self.assertEqual(
            opening.best_buyer(
                event,
                opening.net_by_address(buy_transfers, token, quote),
                initiator,
            ),
            (initiator, opening.Decimal("1000"), opening.Decimal("600")),
        )
        sell_nets = opening.net_by_address(sell_transfers, token, quote)
        self.assertEqual(
            opening.best_buyer(event, sell_nets, initiator),
            ("", opening.Decimal(0), opening.Decimal(0)),
        )
        with (
            mock.patch.object(
                opening,
                "quick_rpc_call",
                side_effect=[
                    {"from": initiator, "to": pool, "input": "0x12345678"},
                    {"status": "0x1", "from": initiator, "blockNumber": "0x64", "transactionIndex": "0x1", "logs": []},
                ],
            ),
            mock.patch.object(opening, "receipt_transfers_from_receipt", return_value=sell_transfers),
            mock.patch.object(opening, "largest_internal_native", return_value={"amount": "0"}),
        ):
            opening_row = opening.summarize_tx(event, sell_tx)
        self.assertEqual(opening_row["buyer"], "")
        self.assertEqual(
            opening_row["buyer_exclusion_reason"],
            "receipt_direction_counterparty_to_initiator_sell",
        )

        def classify(actor, tx_hash, transfers, tx_initiator=initiator):
            token_leg = next(row for row in transfers if row["token"] == token)
            with (
                mock.patch.object(opening, "quick_rpc_call", return_value={"status": "0x1", "from": tx_initiator, "logs": []}),
                mock.patch.object(opening, "receipt_transfers_from_receipt", return_value=transfers),
            ):
                return opening.classify_outgoing_tx(
                    event,
                    actor,
                    tx_hash,
                    [{**token_leg, "block": 100}],
                    100,
                )

        pool_buy = classify(pool, buy_tx, buy_transfers)
        self.assertEqual(pool_buy["quote_received"], opening.Decimal(0))
        self.assertEqual(
            pool_buy["confirmed_sell_exclusion_reason"],
            "receipt_direction_counterparty_to_initiator_buy",
        )
        eoa_sell = classify(initiator, sell_tx, sell_transfers)
        self.assertEqual(eoa_sell["quote_received"], opening.Decimal("500"))
        self.assertEqual(eoa_sell["confirmed_sell_count"], 1)

        contract_seller = "0x" + "4" * 40
        executor = "0x" + "5" * 40
        contract_sell_tx = "0x" + "8" * 64
        contract_sell_transfers = [
            {"tx": contract_sell_tx, "log_index": 1, "token": token, "from": contract_seller, "to": pool, "amount": opening.Decimal("1000")},
            {"tx": contract_sell_tx, "log_index": 2, "token": quote, "from": pool, "to": contract_seller, "amount": opening.Decimal("500")},
        ]
        with mock.patch.object(opening, "has_contract_code", return_value=True):
            contract_sell = classify(
                contract_seller,
                contract_sell_tx,
                contract_sell_transfers,
                executor,
            )
        self.assertEqual(contract_sell["quote_received"], opening.Decimal("500"))
        self.assertEqual(contract_sell["confirmed_sell_count"], 1)
        self.assertEqual(contract_sell["confirmed_sell_exclusion_reason"], "")

        previous = {
            "as_of_block": "100",
            "coverage_complete": True,
            "confirmed_sell_quote_received": "600",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [
                {"tx": buy_tx, "log_index": 1, "quote_received": "600", "route": "direct", "recipient": pool}
            ],
        }
        with (
            mock.patch.object(
                opening,
                "quick_rpc_call",
                return_value={"status": "0x1", "from": initiator, "logs": []},
            ),
            mock.patch.object(
                opening,
                "receipt_transfers_from_receipt",
                return_value=sell_transfers,
            ),
            mock.patch.object(opening, "token_balance") as token_balance,
            mock.patch.object(opening, "get_logs_quick") as get_logs,
        ):
            refreshed = opening.trace_buyer(
                event,
                pool,
                100,
                100,
                opening.Decimal("1000"),
                previous,
                sell_tx,
            )
        token_balance.assert_not_called()
        get_logs.assert_not_called()
        self.assertEqual(refreshed["status"], "excluded_non_cohort_subject")
        self.assertEqual(refreshed["confirmed_sell_quote_received"], "0")
        self.assertEqual(refreshed["confirmed_sell_evidence"], [])
        self.assertEqual(
            refreshed["subject_exclusion_reason"],
            "receipt_direction_counterparty_to_initiator_sell",
        )
        self.assertEqual(
            opening.trace_sell_lower_bound(previous, refreshed),
            refreshed,
        )
        self.assertEqual(
            opening.meaningful_buy_rows(
                [{"token_bought": "1000", "spent_quote": "600", "buyer_trace": refreshed}]
            ),
            [],
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

    def test_next_hop_span_truncation_is_partial_coverage(self) -> None:
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
                    "ALPHA_OPENING_NEXT_HOP_MAX_BLOCKS": "50000",
                    "ALPHA_OPENING_NEXT_HOP_FULL_MAX_BLOCKS": "250000",
                },
            ),
            mock.patch.object(
                opening,
                "get_logs_quick",
                return_value=[],
            ) as get_logs,
        ):
            result = opening.trace_next_hop_from_recipient(
                event,
                "0x" + "3" * 40,
                "0x" + "4" * 40,
                100,
                300000,
            )

        self.assertEqual(
            int(get_logs.call_args.args[1]["fromBlock"], 16),
            50000,
        )
        self.assertFalse(result["coverage_complete"])

    def test_next_hop_classification_caps_are_partial_coverage(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "opening_next_hop_classify_txs": 6,
            "opening_next_hop_recipients": 8,
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
                "ALPHA_OPENING_CLASSIFY_OUT_TXS": "2",
                "ALPHA_OPENING_NEXT_HOP_RECIPIENTS": "1",
                "ALPHA_OPENING_NEXT_HOP_CLASSIFY_TXS": "2",
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
            self.assertEqual(
                capped_event_int_setting(
                    {"opening_classify_out_txs": 8},
                    "opening_classify_out_txs",
                    "ALPHA_OPENING_CLASSIFY_OUT_TXS",
                    3,
                ),
                2,
            )
            self.assertEqual(
                capped_event_int_setting(
                    {"opening_next_hop_recipients": 8},
                    "opening_next_hop_recipients",
                    "ALPHA_OPENING_NEXT_HOP_RECIPIENTS",
                    2,
                ),
                1,
            )
            self.assertEqual(
                capped_event_int_setting(
                    {"opening_next_hop_classify_txs": 6},
                    "opening_next_hop_classify_txs",
                    "ALPHA_OPENING_NEXT_HOP_CLASSIFY_TXS",
                    2,
                ),
                2,
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

    def test_fast_cycle_incrementally_refreshes_dynamic_buyer_trace(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        contract = "0x" + "1" * 40
        row = {
            "tx": "0x" + "2" * 64,
            "buyer": "0x" + "3" * 40,
            "block": 100,
            "token_bought": "7177604.7",
            "spent_quote": "600000",
            "buyer_trace": {
                "status": "mostly_exited_or_transferred",
                "coverage_complete": True,
                "as_of_block": "120",
                "confirmed_sell_quote_received": "37331.42",
            },
        }
        event = {
            "chain": "bsc",
            "token": {"address": contract, "symbol": "AEON", "decimals": 8},
            "quote": {
                "address": "0x" + "4" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "opening_block": 100,
            "latest_block": 140,
        }
        previous = {
            "status": "opened",
            "scan_to_block": 130,
            "transfer_logs": 3907,
            "relevant_tx_count": 8,
            "rows": [row],
            "liquidity_flow": {"summary": "cached", "risk": "none", "rows": 0},
            "opening_v4_pool_scope": {"configuration_hash": "old-v4"},
        }

        refreshed_trace = {
            **row["buyer_trace"],
            "as_of_block": "140",
            "confirmed_sell_quote_received": "38000",
        }

        def refresh_liquidity(
            target_event: dict[str, object],
            _latest: int,
        ) -> dict[str, object]:
            target_event["opening_v4_pool_scope"] = {
                "configuration_hash": "new-v4"
            }
            return {
                "summary": "fresh",
                "risk": "none",
                "rows": 0,
                "coverage_complete": True,
                "coverage_status": "complete_recent_window",
            }

        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                side_effect=refresh_liquidity,
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                return_value=refreshed_trace,
            ) as trace_buyer,
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={"buyer_trace_summary": "incremental"},
            ),
        ):
            refreshed = opening.incremental_opened_event(
                event,
                previous,
                "2026-07-28T11:25:44+00:00",
            )

        self.assertEqual(refreshed["refresh_status"], "incremental_refresh")
        self.assertEqual(refreshed["deep_trace_as_of_block"], "140")
        self.assertEqual(
            refreshed["rows"][0]["buyer_trace"]["confirmed_sell_quote_received"],
            "38000",
        )
        self.assertEqual(previous["rows"][0]["buyer_trace"]["as_of_block"], "120")
        self.assertEqual(
            refreshed["opening_v4_pool_scope"]["configuration_hash"],
            "new-v4",
        )
        self.assertEqual(
            trace_buyer.call_args.args[-1]["confirmed_sell_quote_received"],
            "37331.42",
        )

    def test_build_snapshot_fast_cycle_uses_incremental_refresh(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        contract = "0x" + "1" * 40
        quote = "0x" + "4" * 40
        current = {
            "symbol": "AEON",
            "chain": "bsc",
            "token": {"address": contract},
            "quote": {"address": quote},
            "opening_block": 100,
            "latest_block": 140,
            "start_time_utc": "2026-07-27T10:00:00+00:00",
            "pool_id": "0x" + "5" * 64,
        }
        previous_event = {
            **current,
            "latest_block": 120,
            "status": "opened",
            "rows": [
                {
                    "tx": "0x" + "2" * 64,
                    "buyer_trace": {
                        "status": "mostly_exited_or_transferred",
                        "coverage_complete": True,
                        "as_of_block": "120",
                    },
                }
            ],
        }
        previous_snapshot = {
            "generated_at": "2026-07-28T11:25:44+00:00",
            "events": [previous_event],
        }

        def fake_read_json(path, default):
            if path == opening.LATEST_PATH:
                return previous_snapshot
            return default

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_REUSE_OPENED_CACHE": "1"},
            ),
            mock.patch.object(opening, "read_json", side_effect=fake_read_json),
            mock.patch.object(opening, "build_events", return_value=[current]),
            mock.patch.object(
                opening,
                "previous_opened_event_needs_full_retry",
                return_value=False,
            ),
            mock.patch.object(
                opening,
                "incremental_opened_event",
                return_value={
                    "status": "opened",
                    "refresh_status": "incremental_refresh",
                    "rows": [],
                    "analysis": {},
                },
            ) as incremental_event,
            mock.patch.object(
                opening,
                "build_opened_event",
                side_effect=AssertionError("deep refresh must be skipped"),
            ),
            mock.patch.object(opening, "event_alert_keys", return_value=[]),
        ):
            snapshot = opening.build_snapshot()

        self.assertEqual(snapshot["event_count"], 1)
        self.assertEqual(
            snapshot["events"][0]["refresh_status"],
            "incremental_refresh",
        )
        incremental_event.assert_called_once()

    def test_partial_opening_trace_is_a_health_warning(self) -> None:
        from scripts.runtime_health_watch import output_row_coverage_warning

        self.assertEqual(
            output_row_coverage_warning(
                "opening",
                {
                    "status": "opened",
                    "refresh_status": "partial_trace_deadline",
                    "rows": [
                        {
                            "buyer_trace": {
                                "status": "unknown_incomplete_coverage",
                                "coverage_complete": False,
                            }
                        }
                    ],
                },
            ),
            (
                "opening buyer trace coverage incomplete; "
                "opening buyer trace deadline reached"
            ),
        )

    def test_trace_deadline_preserves_confirmed_sell_lower_bound(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        partial = opening.deadline_partial_trace(
            {
                "status": "mostly_exited_or_transferred",
                "coverage_complete": True,
                "current_balance": "0",
                "confirmed_sell_quote_received": "37331.42",
                "confirmed_sell_count": "16",
                "as_of_block": "120",
            }
        )

        self.assertEqual(partial["status"], "confirmed_sell_partial_coverage")
        self.assertFalse(partial["coverage_complete"])
        self.assertEqual(partial["coverage_status"], "partial")
        self.assertEqual(
            partial["confirmed_sell_quote_received"],
            "37331.42",
        )
        self.assertEqual(partial["current_balance"], "")
        self.assertTrue(partial["trace_deadline_exceeded"])

    def test_deadline_snapshot_fallback_does_not_issue_more_rpc(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        previous = {
            "generated_at": "2026-07-28T11:00:00+00:00",
            "events": [
                {
                    "status": "opened",
                    "symbol": "AEON",
                    "opening_block": 100,
                    "quote": {
                        "address": "0x" + "2" * 40,
                        "symbol": "USDT",
                        "decimals": 18,
                    },
                    "token": {
                        "address": "0x" + "1" * 40,
                        "symbol": "AEON",
                        "decimals": 8,
                    },
                    "rows": [
                        {
                            "tx": "0x" + "6" * 64,
                            "buyer": "0x" + "3" * 40,
                            "block": 100,
                            "token_bought": "1000",
                            "spent_quote": "20000",
                            "buyer_trace": {
                                "status": (
                                    "confirmed_sell_partial_coverage"
                                ),
                                "coverage_complete": False,
                                "confirmed_sell_quote_received": (
                                    "37331.42"
                                ),
                                "confirmed_sell_count": "16",
                                "out_after_buy": "1000",
                                "as_of_block": "120",
                            },
                        }
                    ],
                    "analysis": {},
                }
            ],
        }
        opening.CONTRACT_SAFETY_CACHE.clear()
        with (
            mock.patch.object(
                opening,
                "TRACE_DEADLINE_AT",
                time.monotonic() - 1,
            ),
            mock.patch.object(
                opening,
                "quick_rpc_call",
                side_effect=AssertionError("unexpected rpc"),
            ) as quick_rpc,
            mock.patch.object(opening, "read_json", return_value=[]),
        ):
            snapshot = opening.deadline_snapshot_from_previous(previous)

        quick_rpc.assert_not_called()
        event = snapshot["events"][0]
        self.assertEqual(event["refresh_status"], "partial_trace_deadline")
        self.assertEqual(
            event["rows"][0]["buyer_trace"][
                "confirmed_sell_quote_received"
            ],
            "37331.42",
        )
        self.assertEqual(
            event["analysis"]["cohort_confirmed_sell_quote"],
            "37331.42",
        )

    def test_outgoing_tx_cap_marks_buyer_trace_partial(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "opening_classify_out_txs": 8,
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
                "block": 110,
                "log_index": 0,
                "to": "0x" + "4" * 40,
                "amount": opening.Decimal("1"),
            }

        classified = {
            "classes": {"eoa_or_unlabeled"},
            "quote_received": opening.Decimal(0),
            "direct_quote_received": opening.Decimal(0),
            "next_hop_quote_received": opening.Decimal(0),
            "confirmed_sell_count": 0,
            "next_hop_count": 0,
            "next_hop_coverage_complete": True,
            "classification_coverage_complete": True,
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_CLASSIFY_OUT_TXS": "2"},
            ),
            mock.patch.object(opening, "token_balance", return_value=opening.Decimal("1")),
            mock.patch.object(opening, "get_logs_quick", return_value=raw_logs),
            mock.patch.object(opening, "transfer_log", side_effect=parse_log),
            mock.patch.object(
                opening,
                "classify_outgoing_tx",
                return_value=classified,
            ) as classify_outgoing,
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
                120,
                opening.Decimal("10"),
            )

        self.assertFalse(trace["coverage_complete"])
        self.assertEqual(trace["status"], "unknown_incomplete_coverage")
        self.assertEqual(classify_outgoing.call_count, 2)

    def test_incremental_trace_adds_only_new_block_evidence(self) -> None:
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
        previous = {
            "status": "mostly_exited_or_transferred",
            "position_status": "mostly_exited_or_transferred",
            "coverage_complete": True,
            "covered_block_ranges": [{"from": 100, "to": 120}],
            "uncovered_block_ranges": [],
            "current_balance": "0",
            "out_after_buy": "10",
            "out_transfer_count": "1",
            "out_destination_classes": "dex_sell_to_quote",
            "confirmed_sell_quote_received": "37331.42",
            "direct_sell_quote_received": "932.41",
            "next_hop_sell_quote_received": "36399.01",
            "confirmed_sell_count": "16",
            "next_hop_count": "1",
            "next_hop_coverage_complete": True,
            "same_receipt_confirmed_sell": True,
            "as_of_block": "120",
        }
        raw_log = {"transactionHash": "0x" + "6" * 64}

        def parse_log(row, decimals):
            return {
                "tx": row["transactionHash"],
                "block": 122,
                "log_index": 0,
                "to": "0x" + "4" * 40,
                "amount": opening.Decimal("2"),
            }

        classified = {
            "classes": {"dex_sell_to_quote"},
            "quote_received": opening.Decimal("1000"),
            "direct_quote_received": opening.Decimal("1000"),
            "next_hop_quote_received": opening.Decimal(0),
            "confirmed_sell_count": 1,
            "confirmed_sell_evidence": [
                {
                    "id": f"{raw_log['transactionHash']}:7",
                    "tx": raw_log["transactionHash"],
                    "log_index": 7,
                    "quote_received": "1000",
                    "route": "direct",
                    "recipient": "0x" + "3" * 40,
                }
            ],
            "next_hop_count": 0,
            "next_hop_coverage_complete": True,
            "classification_coverage_complete": True,
        }
        with (
            mock.patch.object(opening, "token_balance", return_value=opening.Decimal("0")),
            mock.patch.object(opening, "get_logs_quick", return_value=[raw_log]) as get_logs,
            mock.patch.object(opening, "transfer_log", side_effect=parse_log),
            mock.patch.object(opening, "classify_outgoing_tx", return_value=classified),
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
                123,
                opening.Decimal("10"),
                previous,
            )

        self.assertEqual(int(get_logs.call_args.args[1]["fromBlock"], 16), 121)
        self.assertEqual(trace["as_of_block"], "123")
        self.assertTrue(trace["coverage_complete"])
        self.assertEqual(
            trace["confirmed_sell_quote_received"],
            "38331.42",
        )
        self.assertEqual(trace["confirmed_sell_count"], "17")

    def test_incremental_next_hop_sell_is_caught_once_across_overlap(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        buyer = "0x" + "3" * 40
        recipient = "0x" + "4" * 40
        sell_tx = "0x" + "7" * 64
        evidence = {
            "id": f"{sell_tx}:9",
            "tx": sell_tx,
            "log_index": 9,
            "quote_received": "500",
            "route": "next_hop",
            "recipient": recipient,
        }
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
        previous = {
            "status": "partially_moved",
            "position_status": "partially_moved",
            "coverage_complete": True,
            "covered_block_ranges": [{"from": 100, "to": 120}],
            "uncovered_block_ranges": [],
            "current_balance": "5",
            "out_after_buy": "5",
            "out_transfer_count": "1",
            "out_destination_classes": "eoa_or_unlabeled",
            "confirmed_sell_quote_received": "0",
            "direct_sell_quote_received": "0",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "0",
            "next_hop_count": "1",
            "next_hop_coverage_complete": True,
            "next_hop_watch_recipients": [
                {"address": recipient, "as_of_block": 120}
            ],
            "as_of_block": "120",
        }
        raw_log = {"transactionHash": "0x" + "6" * 64}

        def parse_log(row, decimals):
            return {
                "tx": row["transactionHash"],
                "block": 122,
                "log_index": 0,
                "to": recipient,
                "amount": opening.Decimal("1"),
            }

        next_hop = {
            "classes": {"next_hop_dex_sell_to_quote"},
            "quote_received": opening.Decimal("500"),
            "confirmed_sell_count": 1,
            "confirmed_sell_evidence": [evidence],
            "recipient_count": 1,
            "coverage_complete": True,
        }
        classified = {
            "classes": {
                "eoa_or_unlabeled",
                "next_hop_dex_sell_to_quote",
            },
            "quote_received": opening.Decimal("500"),
            "direct_quote_received": opening.Decimal(0),
            "next_hop_quote_received": opening.Decimal("500"),
            "confirmed_sell_count": 1,
            "confirmed_sell_evidence": [evidence],
            "next_hop_count": 1,
            "next_hop_coverage_complete": True,
            "classification_coverage_complete": True,
            "next_hop_watch_recipients": [
                {"address": recipient, "as_of_block": 123}
            ],
        }
        with (
            mock.patch.object(
                opening,
                "token_balance",
                return_value=opening.Decimal("4"),
            ),
            mock.patch.object(
                opening,
                "get_logs_quick",
                return_value=[raw_log],
            ),
            mock.patch.object(
                opening,
                "transfer_log",
                side_effect=parse_log,
            ),
            mock.patch.object(
                opening,
                "trace_next_hop_from_recipient",
                return_value=next_hop,
            ) as trace_next_hop,
            mock.patch.object(
                opening,
                "classify_outgoing_tx",
                return_value=classified,
            ),
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
                buyer,
                100,
                123,
                opening.Decimal("10"),
                previous,
            )

        self.assertEqual(trace_next_hop.call_args.args[3:5], (121, 123))
        self.assertEqual(trace["confirmed_sell_quote_received"], "500")
        self.assertEqual(trace["next_hop_sell_quote_received"], "500")
        self.assertEqual(trace["confirmed_sell_count"], "1")
        self.assertEqual(len(trace["confirmed_sell_evidence"]), 1)
        self.assertEqual(
            trace["next_hop_watch_recipients"][0]["as_of_block"],
            123,
        )

    def test_sell_evidence_uses_receipt_log_identity(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        recipient = "0x" + "4" * 40
        tx_hash = "0x" + "7" * 64
        event = {
            "quote": {
                "address": "0x" + "2" * 40,
            },
        }
        transfers = [
            {
                "tx": tx_hash,
                "log_index": 8,
                "token": event["quote"]["address"],
                "to": recipient,
                "amount": opening.Decimal("300"),
            },
            {
                "tx": tx_hash,
                "log_index": 9,
                "token": event["quote"]["address"],
                "to": recipient,
                "amount": opening.Decimal("200"),
            },
        ]

        evidence = opening.receipt_confirmed_sell_evidence(
            transfers,
            event,
            recipient,
            tx_hash,
            "next_hop",
        )
        merged = opening.merge_confirmed_sell_evidence(
            evidence,
            [dict(evidence[0])],
        )
        summary = opening.confirmed_sell_evidence_summary(merged)

        self.assertEqual(len(merged), 2)
        self.assertEqual(summary["quote_received"], opening.Decimal("500"))
        self.assertEqual(summary["confirmed_sell_count"], 1)

    def test_route_legacy_ambiguity_keeps_full_retry_partial(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        tx_hash = "0x" + "7" * 64
        previous = {
            "coverage_complete": True,
            "confirmed_sell_quote_received": "100",
            "direct_sell_quote_received": "100",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [],
            "next_hop_watch_recipients": [],
        }
        refreshed = {
            "status": "mostly_exited_or_transferred",
            "coverage_complete": True,
            "confirmed_sell_quote_received": "100",
            "direct_sell_quote_received": "0",
            "next_hop_sell_quote_received": "100",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [
                {
                    "id": f"{tx_hash}:9",
                    "tx": tx_hash,
                    "log_index": 9,
                    "quote_received": "100",
                    "route": "next_hop",
                    "recipient": "0x" + "4" * 40,
                }
            ],
            "next_hop_watch_recipients": [],
        }

        merged = opening.trace_sell_lower_bound(previous, refreshed)

        self.assertEqual(merged["confirmed_sell_quote_received"], "100")
        self.assertEqual(merged["legacy_confirmed_sell_quote_received"], "0")
        self.assertEqual(merged["legacy_direct_sell_quote_received"], "100")
        self.assertFalse(merged["coverage_complete"])
        self.assertEqual(
            merged["status"],
            "confirmed_sell_partial_coverage",
        )

    def test_count_legacy_ambiguity_keeps_full_retry_partial(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        tx_hash = "0x" + "7" * 64
        evidence = {
            "id": f"{tx_hash}:9",
            "tx": tx_hash,
            "log_index": 9,
            "quote_received": "100",
            "route": "direct",
            "recipient": "0x" + "3" * 40,
        }
        previous = {
            "coverage_complete": True,
            "confirmed_sell_quote_received": "100",
            "direct_sell_quote_received": "100",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "2",
            "confirmed_sell_evidence": [],
            "next_hop_watch_recipients": [],
        }
        refreshed = {
            "status": "mostly_exited_or_transferred",
            "coverage_complete": True,
            "confirmed_sell_quote_received": "100",
            "direct_sell_quote_received": "100",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [evidence],
            "next_hop_watch_recipients": [],
        }

        merged = opening.trace_sell_lower_bound(previous, refreshed)

        self.assertEqual(merged["legacy_confirmed_sell_count"], "1")
        self.assertFalse(merged["coverage_complete"])

    def test_trace_alert_bucket_upgrade_is_not_suppressed(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        legacy = "trace|AEON|buyer|partially_moved|dex_router"
        old_bucket = f"{legacy}|30000"
        new_bucket = f"{legacy}|630000"
        zero_bucket = f"{legacy}|0"

        self.assertTrue(opening.alert_key_seen(zero_bucket, {legacy}))
        self.assertFalse(opening.alert_key_seen(new_bucket, {legacy}))
        self.assertFalse(opening.alert_key_seen(new_bucket, {old_bucket}))

    def test_malformed_receipt_transfer_is_incomplete_coverage(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        buyer = "0x" + "3" * 40
        recipient = "0x" + "4" * 40
        tx_hash = "0x" + "7" * 64
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
        base_log = {
            "address": event["quote"]["address"],
            "topics": [
                opening.TRANSFER_TOPIC,
                opening.address_topic("0x" + "5" * 40),
                opening.address_topic(recipient),
            ],
            "data": "0x1",
            "transactionHash": tx_hash,
        }
        malformed_receipts = [
            {"status": "0x1", "logs": [{**base_log}]},
            {
                "status": "0x1",
                "logs": [
                    {
                        **base_log,
                        "logIndex": "0x1",
                        "data": "not-hex",
                    }
                ],
            },
            {
                "status": "0x1",
                "logs": [
                    {
                        **base_log,
                        "topics": [opening.TRANSFER_TOPIC],
                        "logIndex": "0x1",
                    }
                ],
            },
        ]

        for receipt in malformed_receipts:
            with (
                self.subTest(receipt=receipt),
                mock.patch.object(
                    opening,
                    "quick_rpc_call",
                    return_value=receipt,
                ),
            ):
                next_hop = opening.classify_recipient_next_hop_tx(
                    event,
                    recipient,
                    tx_hash,
                    [],
                )
                direct = opening.classify_outgoing_tx(
                    event,
                    buyer,
                    tx_hash,
                    [],
                    123,
                )
            self.assertFalse(next_hop["receipt_coverage_complete"])
            self.assertFalse(direct["receipt_coverage_complete"])
            self.assertFalse(direct["classification_coverage_complete"])

    def test_failed_next_hop_receipt_keeps_watch_cursor_for_retry(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        buyer = "0x" + "3" * 40
        recipient = "0x" + "4" * 40
        sell_tx = "0x" + "7" * 64
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
        raw_log = {"transactionHash": sell_tx}

        def parse_log(row, decimals):
            return {
                "tx": row["transactionHash"],
                "block": 122,
                "log_index": 0,
                "to": "0x" + "5" * 40,
                "amount": opening.Decimal("1"),
            }

        with (
            mock.patch.object(
                opening,
                "get_logs_quick",
                return_value=[raw_log],
            ),
            mock.patch.object(
                opening,
                "transfer_log",
                side_effect=parse_log,
            ),
            mock.patch.object(
                opening,
                "quick_rpc_call",
                return_value=None,
            ),
        ):
            failed_slice = opening.trace_next_hop_from_recipient(
                event,
                buyer,
                recipient,
                121,
                123,
            )
        self.assertFalse(failed_slice["coverage_complete"])

        previous = {
            "status": "partially_moved",
            "position_status": "partially_moved",
            "coverage_complete": True,
            "covered_block_ranges": [{"from": 100, "to": 120}],
            "uncovered_block_ranges": [],
            "current_balance": "5",
            "out_after_buy": "5",
            "out_transfer_count": "1",
            "out_destination_classes": "eoa_or_unlabeled",
            "confirmed_sell_quote_received": "0",
            "direct_sell_quote_received": "0",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "0",
            "next_hop_count": "1",
            "next_hop_coverage_complete": True,
            "next_hop_watch_recipients": [
                {"address": recipient, "as_of_block": 120}
            ],
            "as_of_block": "120",
        }
        with (
            mock.patch.object(
                opening,
                "token_balance",
                return_value=opening.Decimal("4"),
            ),
            mock.patch.object(opening, "get_logs_quick", return_value=[]),
            mock.patch.object(
                opening,
                "trace_next_hop_from_recipient",
                return_value=failed_slice,
            ),
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
            failed_trace = opening.trace_buyer(
                event,
                buyer,
                100,
                123,
                opening.Decimal("10"),
                previous,
            )
        self.assertFalse(failed_trace["coverage_complete"])
        self.assertEqual(
            failed_trace["next_hop_watch_recipients"][0]["as_of_block"],
            120,
        )

        evidence = {
            "id": f"{sell_tx}:9",
            "tx": sell_tx,
            "log_index": 9,
            "quote_received": "500",
            "route": "next_hop",
            "recipient": recipient,
        }
        successful_slice = {
            **failed_slice,
            "quote_received": opening.Decimal("500"),
            "confirmed_sell_count": 1,
            "confirmed_sell_evidence": [evidence],
            "coverage_complete": True,
        }
        with (
            mock.patch.object(
                opening,
                "token_balance",
                return_value=opening.Decimal("4"),
            ),
            mock.patch.object(opening, "get_logs_quick", return_value=[]),
            mock.patch.object(
                opening,
                "trace_next_hop_from_recipient",
                return_value=successful_slice,
            ) as retry_slice,
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
            successful_trace = opening.trace_buyer(
                event,
                buyer,
                100,
                123,
                opening.Decimal("10"),
                failed_trace,
            )
        self.assertEqual(retry_slice.call_args.args[3:5], (121, 123))
        self.assertEqual(
            successful_trace["confirmed_sell_quote_received"],
            "500",
        )
        self.assertEqual(
            successful_trace["next_hop_watch_recipients"][0][
                "as_of_block"
            ],
            123,
        )

    def test_incremental_trace_error_preserves_confirmed_lower_bound(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        tx_hash = "0x" + "6" * 64
        recipient = "0x" + "4" * 40
        evidence = {
            "id": f"{tx_hash}:9",
            "tx": tx_hash,
            "log_index": 9,
            "quote_received": "500",
            "route": "next_hop",
            "recipient": recipient,
        }
        previous_trace = {
            "status": "confirmed_sell_partial_coverage",
            "coverage_complete": False,
            "confirmed_sell_quote_received": "37331.42",
            "legacy_confirmed_sell_quote_received": "36831.42",
            "confirmed_sell_count": "16",
            "confirmed_sell_evidence": [evidence],
            "next_hop_watch_recipients": [
                {"address": recipient, "as_of_block": 120}
            ],
            "as_of_block": "120",
        }
        previous = {
            "last_full_trace_attempt_at": "2026-07-28T11:00:00+00:00",
            "rows": [
                {
                    "tx": tx_hash,
                    "buyer": "0x" + "3" * 40,
                    "block": 100,
                    "token_bought": "1000",
                    "spent_quote": "20000",
                    "buyer_trace": previous_trace,
                }
            ],
        }
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 123,
        }
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                side_effect=RuntimeError("temporary"),
            ),
            mock.patch.object(opening, "analyze_opened", return_value={}),
        ):
            refreshed = opening.incremental_opened_event(
                event,
                previous,
                "2026-07-28T11:05:00+00:00",
            )

        trace = refreshed["rows"][0]["buyer_trace"]
        self.assertEqual(refreshed["refresh_status"], "partial_trace_error")
        self.assertEqual(
            trace["confirmed_sell_quote_received"],
            "37331.42",
        )
        self.assertEqual(trace["confirmed_sell_evidence"], [evidence])
        self.assertEqual(
            trace["next_hop_watch_recipients"][0]["as_of_block"],
            120,
        )
        self.assertFalse(trace["coverage_complete"])

    def test_full_retry_reuses_rows_and_preserves_sell_lower_bound(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        tx_hash = "0x" + "6" * 64
        previous = {
            "status": "opened",
            "opening_buyer_scope_complete": True,
            "scan_to_block": 340,
            "transfer_logs": 3907,
            "relevant_tx_count": 8,
            "immutable_opening_generated_at": (
                "2026-07-27T10:00:00+00:00"
            ),
            "rows": [
                {
                    "tx": tx_hash,
                    "buyer": "0x" + "3" * 40,
                    "block": 100,
                    "token_bought": "1000",
                    "spent_quote": "20000",
                    "buyer_trace": {
                        "status": "confirmed_sell_partial_coverage",
                        "coverage_complete": False,
                        "confirmed_sell_quote_received": "37331.42",
                        "confirmed_sell_count": "16",
                        "as_of_block": "120",
                    },
                }
            ],
        }
        fresh_evidence = {
            "id": f"{tx_hash}:9",
            "tx": tx_hash,
            "log_index": 9,
            "quote_received": "100",
            "route": "direct",
            "recipient": "0x" + "3" * 40,
        }
        fresh_trace = {
            "status": "mostly_exited_or_transferred",
            "position_status": "mostly_exited_or_transferred",
            "coverage_complete": True,
            "coverage_status": "complete",
            "confirmed_sell_quote_received": "100",
            "direct_sell_quote_received": "100",
            "next_hop_sell_quote_received": "0",
            "confirmed_sell_count": "1",
            "confirmed_sell_evidence": [fresh_evidence],
            "next_hop_watch_recipients": [],
            "out_after_buy": "1000",
            "out_transfer_count": "1",
            "out_destination_classes": "dex_sell_to_quote",
            "next_hop_count": "0",
            "as_of_block": "123",
        }
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 123,
        }
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "opening_transfer_logs",
            ) as opening_logs,
            mock.patch.object(
                opening,
                "trace_buyer",
                return_value=fresh_trace,
            ),
            mock.patch.object(opening, "analyze_opened", return_value={}),
        ):
            refreshed = opening.build_opened_event(event, previous)

        opening_logs.assert_not_called()
        self.assertEqual(refreshed["rows"][0]["tx"], tx_hash)
        self.assertEqual(refreshed["transfer_logs"], 3907)
        self.assertEqual(
            refreshed["rows"][0]["buyer_trace"][
                "confirmed_sell_quote_received"
            ],
            "37331.42",
        )
        self.assertEqual(
            refreshed["rows"][0]["buyer_trace"][
                "legacy_confirmed_sell_quote_received"
            ],
            "37231.42",
        )
        self.assertFalse(
            refreshed["rows"][0]["buyer_trace"]["coverage_complete"]
        )

    def test_partial_trace_retry_is_bounded_and_not_permanent(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        previous = {
            "opening_cohort_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_liquidity_coverage_complete": True,
            "opening_buyer_scope_complete": True,
            "deep_trace_generated_at": "2026-07-28T11:00:00+00:00",
            "last_full_trace_attempt_at": "2026-07-28T11:00:00+00:00",
            "rows": [
                {
                    "tx": "0x" + "6" * 64,
                    "buyer": "0x" + "3" * 40,
                    "block": 100,
                    "token_bought": "1",
                    "buyer_trace": {
                        "status": "unknown_incomplete_coverage",
                        "coverage_complete": False,
                    }
                }
            ],
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_PARTIAL_RETRY_SECONDS": "900"},
            ),
            mock.patch.object(
                opening,
                "now_utc",
                return_value=datetime(2026, 7, 28, 11, 10, tzinfo=timezone.utc),
            ),
        ):
            self.assertFalse(
                opening.previous_opened_event_needs_full_retry(
                    previous,
                    "2026-07-28T11:00:00+00:00",
                )
            )

        event = {
            "chain": "bsc",
            "opening_block": 100,
            "latest_block": 120,
        }
        partial_trace = {
            "status": "unknown_incomplete_coverage",
            "coverage_complete": False,
        }
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                return_value=partial_trace,
            ),
            mock.patch.object(opening, "analyze_opened", return_value={}),
            mock.patch.object(
                opening,
                "now_iso",
                return_value="2026-07-28T11:05:00+00:00",
            ),
        ):
            first_incremental = opening.incremental_opened_event(
                event,
                previous,
                "2026-07-28T11:00:00+00:00",
            )
        event["latest_block"] = 121
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                return_value=partial_trace,
            ),
            mock.patch.object(opening, "analyze_opened", return_value={}),
            mock.patch.object(
                opening,
                "now_iso",
                return_value="2026-07-28T11:10:00+00:00",
            ),
        ):
            second_incremental = opening.incremental_opened_event(
                event,
                first_incremental,
                "2026-07-28T11:05:00+00:00",
            )
        self.assertEqual(
            first_incremental["last_full_trace_attempt_at"],
            "2026-07-28T11:00:00+00:00",
        )
        self.assertEqual(
            second_incremental["last_full_trace_attempt_at"],
            "2026-07-28T11:00:00+00:00",
        )
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_PARTIAL_RETRY_SECONDS": "900"},
            ),
            mock.patch.object(
                opening,
                "now_utc",
                return_value=datetime(
                    2026,
                    7,
                    28,
                    11,
                    16,
                    tzinfo=timezone.utc,
                ),
            ),
        ):
            self.assertTrue(
                opening.previous_opened_event_needs_full_retry(
                    second_incremental,
                    "2026-07-28T11:10:00+00:00",
                )
            )
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_PARTIAL_RETRY_SECONDS": "900"},
            ),
            mock.patch.object(
                opening,
                "now_utc",
                return_value=datetime(2026, 7, 28, 11, 16, tzinfo=timezone.utc),
            ),
        ):
            self.assertTrue(
                opening.previous_opened_event_needs_full_retry(
                    previous,
                    "2026-07-28T11:00:00+00:00",
                )
            )

    def test_opening_cache_identity_survives_metadata_drift(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        base = {
            "chain": "bsc",
            "token": {"address": "0x" + "1" * 40},
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "USDT",
            },
            "opening_block": 100,
            "start_time_utc": "2026-07-27T10:00:00+00:00",
            "pool_id": "0x" + "3" * 64,
        }
        changed_metadata = {
            **base,
            "quote": {
                "address": "0x" + "2" * 40,
                "symbol": "BSC-USD",
            },
            "start_time_utc": "2026-07-27T10:00:01+00:00",
            "pool_id": "0x" + "5" * 64,
        }

        self.assertEqual(
            opening.opening_event_identity(base),
            opening.opening_event_identity(changed_metadata),
        )
        self.assertNotEqual(
            opening.opening_event_identity(base),
            opening.opening_event_identity(
                {
                    **base,
                    "opening_block": 101,
                }
            ),
        )
        self.assertNotEqual(
            opening.opening_event_identity(base),
            opening.opening_event_identity(
                {
                    **base,
                    "token": {"address": "0x" + "6" * 40},
                }
            ),
        )
        self.assertEqual(
            opening.opening_event_metadata_conflict(
                changed_metadata,
                base,
            ),
            "",
        )
        self.assertEqual(
            opening.opening_event_metadata_conflict(
                {
                    **base,
                    "quote": {"address": "0x" + "7" * 40},
                },
                base,
            ),
            "quote_address_changed",
        )
        for current_quote, previous_quote in (
            ("", "0x" + "2" * 40),
            ("0x" + "2" * 40, ""),
            ("", ""),
        ):
            self.assertEqual(
                opening.opening_event_metadata_conflict(
                    {
                        **base,
                        "quote": {"address": current_quote},
                    },
                    {
                        **base,
                        "quote": {"address": previous_quote},
                    },
                ),
                "quote_address_missing",
            )

    def test_metadata_drift_reuses_opening_sell_evidence(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        tx_hash = "0x" + "3" * 64
        evidence = {
            "id": f"{tx_hash}:7",
            "tx": tx_hash,
            "log_index": 7,
            "quote_received": "37331.42",
            "route": "direct",
            "recipient": "0x" + "4" * 40,
        }
        previous_event = {
            "symbol": "AEON",
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": quote, "symbol": "USDT"},
            "opening_block": 100,
            "start_time_utc": "2026-07-27T10:00:00+00:00",
            "pool_id": "old-pool",
            "status": "opened",
            "opening_log_required_windows_complete": True,
            "opening_liquidity_coverage_complete": True,
            "opening_buyer_scope_complete": True,
            "rows": [
                {
                    "tx": tx_hash,
                    "buyer": "0x" + "5" * 40,
                    "block": 100,
                    "token_bought": "1000",
                    "buyer_trace": {
                        "status": "mostly_exited_or_transferred",
                        "coverage_complete": True,
                        "coverage_status": "complete",
                        "confirmed_sell_quote_received": "37331.42",
                        "confirmed_sell_count": "1",
                        "confirmed_sell_evidence": [evidence],
                        "next_hop_watch_recipients": [],
                        "as_of_block": "120",
                    },
                }
            ],
            "transfer_logs": 100,
            "relevant_tx_count": 1,
            "immutable_opening_generated_at": (
                "2026-07-27T10:00:00+00:00"
            ),
            "deep_trace_generated_at": "2026-07-28T10:00:00+00:00",
            "last_full_trace_attempt_at": "2026-07-28T10:00:00+00:00",
            "last_full_trace_success_at": "2026-07-28T10:00:00+00:00",
            "analysis": {
                "cohort_confirmed_sell_quote": "37331.42",
            },
        }
        current_event = {
            **previous_event,
            "quote": {"address": quote, "symbol": "BSC-USD"},
            "latest_block": 121,
            "rows": [],
            "analysis": {},
        }
        previous_snapshot = {
            "generated_at": "2026-07-28T10:00:00+00:00",
            "events": [previous_event],
        }

        def read(path, default):
            if path == opening.LATEST_PATH:
                return previous_snapshot
            return default

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_OPENING_REUSE_OPENED_CACHE": "1"},
            ),
            mock.patch.object(opening, "read_json", side_effect=read),
            mock.patch.object(
                opening,
                "build_events",
                return_value=[current_event],
            ),
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                side_effect=lambda *args, **kwargs: args[5],
            ),
            mock.patch.object(opening, "analyze_opened", return_value={}),
            mock.patch.object(opening, "opening_transfer_logs") as logs,
        ):
            snapshot = opening.build_snapshot()

        logs.assert_not_called()
        event = snapshot["events"][0]
        self.assertEqual(event["cache_identity_status"], "stable_match")
        trace = event["rows"][0]["buyer_trace"]
        self.assertEqual(
            trace["confirmed_sell_quote_received"],
            "37331.42",
        )
        self.assertEqual(trace["confirmed_sell_evidence"], [evidence])

    def test_opening_cache_identity_rejects_ambiguous_fallback(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        base = {
            "chain": "bsc",
            "token": {"address": "0x" + "1" * 40},
            "quote": {"address": "0x" + "2" * 40},
            "opening_block": 100,
            "start_time_utc": "2026-07-27T10:00:00+00:00",
            "pool_id": "pool-current",
        }
        first = {
            **base,
            "start_time_utc": "2026-07-27T09:59:58+00:00",
            "pool_id": "pool-one",
        }
        second = {
            **base,
            "start_time_utc": "2026-07-27T09:59:59+00:00",
            "pool_id": "pool-two",
        }
        previous, conflict = opening.select_previous_opened_event(
            base,
            [first, second],
        )
        self.assertIsNone(previous)
        self.assertEqual(conflict, "pool_or_time_identity_changed")

        previous, conflict = opening.select_previous_opened_event(
            first,
            [first, second],
        )
        self.assertIs(previous, first)
        self.assertEqual(conflict, "")

        previous, conflict = opening.select_previous_opened_event(
            second,
            [first],
        )
        self.assertIsNone(previous)
        self.assertEqual(conflict, "pool_or_time_identity_changed")

        missing_quote = {
            **first,
            "quote": {"address": ""},
        }
        previous, conflict = opening.select_previous_opened_event(
            missing_quote,
            [missing_quote],
        )
        self.assertIsNone(previous)
        self.assertEqual(conflict, "quote_address_missing")

    def test_quote_conflict_forces_fresh_opening_evidence(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        previous_event = {
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": "0x" + "2" * 40},
            "opening_block": 100,
            "status": "opened",
            "rows": [{"buyer_trace": {"confirmed_sell_quote_received": "9"}}],
        }
        current_event = {
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": "0x" + "7" * 40},
            "opening_block": 100,
            "latest_block": 120,
        }
        previous_snapshot = {
            "generated_at": "2026-07-28T10:00:00+00:00",
            "events": [previous_event],
        }

        def read(path, default):
            if path == opening.LATEST_PATH:
                return previous_snapshot
            return default

        with (
            mock.patch.object(opening, "read_json", side_effect=read),
            mock.patch.object(
                opening,
                "build_events",
                return_value=[current_event],
            ),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                return_value={
                    "rows": [],
                    "selected_hashes": [],
                    "transfer_logs": 0,
                    "relevant_tx_count": 0,
                },
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                return_value={
                    "status": "opened",
                    "refresh_status": "full_refresh",
                    "scan_to_block": 120,
                    "transfer_logs": 0,
                    "rows": [],
                    "analysis": {},
                },
            ) as rebuild,
        ):
            snapshot = opening.build_snapshot()

        self.assertIs(rebuild.call_args.args[0], current_event)
        self.assertIsNone(rebuild.call_args.args[1])
        event = snapshot["events"][0]
        self.assertEqual(
            event["cache_identity_status"],
            "metadata_conflict_rebuilt",
        )
        self.assertEqual(
            event["cache_identity_conflict"],
            "quote_address_changed",
        )
        self.assertEqual(event["rows"], [])

        self.assertFalse(
            opening.identity_conflict_refresh_complete(
                {
                    "opening_block": 100,
                    "refresh_status": "full_refresh",
                }
            )
        )

    def test_duplicate_current_opening_identity_stays_unresolved(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        event = {
            "chain": "bsc",
            "symbol": "AEON",
            "token": {"address": "0x" + "1" * 40},
            "quote": {"address": "0x" + "2" * 40},
            "opening_block": 100,
            "latest_block": 120,
        }
        with (
            mock.patch.object(opening, "read_json", return_value={}),
            mock.patch.object(
                opening,
                "build_events",
                return_value=[event.copy(), event.copy()],
            ),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                return_value={
                    "rows": [],
                    "selected_hashes": [],
                    "transfer_logs": 0,
                    "relevant_tx_count": 0,
                },
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                return_value={
                    "status": "opened",
                    "refresh_status": "full_refresh",
                    "scan_to_block": 120,
                    "transfer_logs": 0,
                    "rows": [],
                    "analysis": {},
                },
            ),
        ):
            snapshot = opening.build_snapshot()

        self.assertEqual(
            [
                row["cache_identity_status"]
                for row in snapshot["events"]
            ],
            [
                "metadata_conflict_unresolved",
                "metadata_conflict_unresolved",
            ],
        )
        self.assertEqual(
            {
                row["cache_identity_conflict"]
                for row in snapshot["events"]
            },
            {"duplicate_current_identity"},
        )

    def test_distinct_current_opening_pool_identities_are_independent(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        base_event = {
            "chain": "bsc",
            "symbol": "GRVT",
            "token": {"address": "0x" + "1" * 40},
            "quote": {"address": "0x" + "2" * 40},
            "opening_block": 100,
            "latest_block": 120,
            "start_time_utc": "2026-07-30T12:00:00+00:00",
        }
        events = [
            {**base_event, "pool_id": "0x" + "a" * 64},
            {**base_event, "pool_id": "0x" + "b" * 64},
        ]
        with (
            mock.patch.object(opening, "read_json", return_value={}),
            mock.patch.object(opening, "build_events", return_value=events),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                return_value={
                    "rows": [],
                    "selected_hashes": [],
                    "transfer_logs": 0,
                    "relevant_tx_count": 0,
                },
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                return_value={
                    "status": "opened",
                    "refresh_status": "full_refresh",
                    "scan_to_block": 120,
                    "transfer_logs": 0,
                    "rows": [],
                    "analysis": {},
                },
            ) as build_opened,
        ):
            snapshot = opening.build_snapshot()

        self.assertEqual(build_opened.call_count, 2)
        self.assertEqual(
            [row["cache_identity_status"] for row in snapshot["events"]],
            ["new_event", "new_event"],
        )
        self.assertTrue(
            all(
                "cache_identity_conflict" not in row
                for row in snapshot["events"]
            )
        )

    def test_new_pool_never_reuses_previous_pool_rows(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        base = {
            "chain": "bsc",
            "symbol": "GRVT",
            "token": {"address": "0x" + "1" * 40},
            "quote": {"address": "0x" + "2" * 40},
            "opening_block": 100,
            "latest_block": 120,
            "start_time_utc": "2026-07-30T12:00:00+00:00",
        }
        previous = {
            **base,
            "pool_id": "pool-a",
            "status": "opened",
            "opening_buyer_scope_complete": True,
            "rows": [{"tx": "pool-a-row"}],
        }
        current = {**base, "pool_id": "pool-b"}

        def read(path: Path, default: object) -> object:
            if path == opening.LATEST_PATH:
                return {
                    "generated_at": "2026-07-30T12:01:00+00:00",
                    "events": [previous],
                }
            return default

        with (
            mock.patch.object(opening, "read_json", side_effect=read),
            mock.patch.object(
                opening,
                "build_events",
                return_value=[current],
            ),
            mock.patch.object(
                opening,
                "prepare_opening_scope",
                return_value={
                    "rows": [],
                    "selected_hashes": [],
                    "transfer_logs": 0,
                    "relevant_tx_count": 0,
                },
            ),
            mock.patch.object(
                opening,
                "build_opened_event",
                return_value={
                    "status": "opened",
                    "refresh_status": "full_refresh",
                    "scan_to_block": 120,
                    "transfer_logs": 1,
                    "rows": [{"tx": "pool-b-row"}],
                    "analysis": {},
                },
            ) as build_opened,
        ):
            snapshot = opening.build_snapshot()

        self.assertIsNone(build_opened.call_args.args[1])
        event = snapshot["events"][0]
        self.assertEqual(event["rows"][0]["tx"], "pool-b-row")
        self.assertEqual(
            event["cache_identity_status"],
            "metadata_conflict_rebuilt",
        )
        self.assertEqual(
            event["cache_identity_conflict"],
            "pool_or_time_identity_changed",
        )

    def test_opening_bounded_bootstrap_keeps_complete_cohort(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        def fetch(
            _chain: str,
            query: dict[str, object],
            _chunk_blocks: int,
            _max_logs: int,
            _timeout: int,
            _deadline: bool,
        ) -> list[dict[str, object]]:
            start = int(str(query["fromBlock"]), 16)
            end = int(str(query["toBlock"]), 16)
            if start == 100:
                return [
                    {
                        "blockNumber": hex(100),
                        "transactionIndex": "0x0",
                        "logIndex": "0x0",
                        "transactionHash": "0x" + "1" * 64,
                    }
                ]
            if end - start + 1 > 100:
                raise opening.OpeningLogCoverageTruncated("fixture cap")
            return [
                {
                    "blockNumber": hex(end),
                    "transactionIndex": "0x0",
                    "logIndex": "0x1",
                    "transactionHash": "0x" + "2" * 64,
                }
            ]

        event = {
            "chain": "bsc",
            "token": {"address": "0x" + "3" * 40},
            "opening_block": 100,
        }
        with (
            mock.patch.object(opening, "get_logs_quick", side_effect=fetch),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_RECENT_MIN_BLOCKS": "16",
                    "ALPHA_OPENING_RECENT_MAX_ATTEMPTS": "6",
                },
            ),
        ):
            rows = opening.bounded_bootstrap_opening_transfer_logs(
                event,
                latest=1000,
                scan_blocks=240,
                recent_blocks=1200,
                max_logs=5000,
                chunk_blocks=200,
                timeout=5,
            )

        self.assertEqual(len(rows), 2)
        self.assertTrue(event["opening_cohort_coverage_complete"])
        self.assertTrue(
            event["opening_recent_tail_selected_window_complete"]
        )
        self.assertFalse(event["opening_recent_tail_coverage_complete"])
        self.assertEqual(
            event["opening_log_coverage_status"],
            "opening_complete_recent_tail_partial",
        )

    def test_opening_scope_covers_all_transfer_recipients_when_receipts_are_sampled(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        sender = "0x" + "3" * 40
        recipients = ["0x" + f"{index:040x}" for index in range(10, 40)]
        logs = [
            {
                "address": token,
                "blockNumber": hex(100 + index),
                "transactionIndex": "0x0",
                "logIndex": "0x0",
                "transactionHash": "0x" + f"{index + 1:064x}",
                "topics": [
                    opening.TRANSFER_TOPIC,
                    opening.address_topic(sender),
                    opening.address_topic(recipient),
                ],
                "data": hex(1000 + index),
            }
            for index, recipient in enumerate(recipients)
        ]
        event = {
            "chain": "bsc",
            "symbol": "SCOPE",
            "token": {
                "address": token,
                "symbol": "SCOPE",
                "decimals": 18,
            },
            "quote": {
                "address": quote,
                "symbol": "USDT",
                "decimals": 18,
            },
            "opening_block": 100,
            "latest_block": 200,
            "seconds_until_start": -60,
            "opening_max_txs": 25,
        }

        def summary(_event: dict[str, object], tx_hash: str) -> dict[str, object]:
            index = int(tx_hash, 16) - 1
            return {
                "tx": tx_hash,
                "block": 100 + index,
                "tx_index": 0,
                "buyer": recipients[index],
                "buyer_exclusion_reason": "",
                "token_bought": "1000",
                "spent_quote": "10000",
                "largest_internal_native": {"amount": "0"},
            }

        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={
                    "coverage_complete": True,
                    "coverage_status": "complete_historical_opening_window",
                },
            ),
            mock.patch.object(
                opening,
                "opening_transfer_logs",
                side_effect=lambda current, _latest: (
                    current.update(
                        {
                            "opening_cohort_coverage_complete": True,
                            "opening_recent_tail_coverage_complete": True,
                            "opening_log_required_windows_complete": True,
                            "opening_log_contiguous_coverage_complete": True,
                            "opening_cohort_to_block": 340,
                            "opening_log_covered_to_block": 200,
                        }
                    )
                    or logs
                ),
            ),
            mock.patch.object(
                opening,
                "summarize_tx",
                side_effect=summary,
            ),
            mock.patch.object(
                opening,
                "trace_buyer",
                return_value={"status": "unknown"},
            ),
            mock.patch.object(
                opening,
                "analyze_opened",
                return_value={"attention": ""},
            ),
            mock.patch.object(
                opening,
                "global_address_labels",
                return_value={},
            ),
        ):
            result = opening.build_opened_event(event)

        self.assertEqual(event["opening_cohort_unique_tx_count"], 30)
        self.assertEqual(event["opening_receipt_selected_tx_count"], 25)
        self.assertFalse(event["opening_receipt_classification_complete"])
        self.assertTrue(event["opening_buyer_scope_complete"])
        self.assertEqual(
            set(event["opening_buyer_scope_addresses"]),
            set(recipients),
        )
        self.assertIn("sampled_receipts_25_of_30", result["analysis"]["opening_receipt_scope"])

    def test_opening_scope_rejects_malformed_topic_and_excludes_infrastructure(
        self,
    ) -> None:
        import scripts.alpha_opening_block_watch as opening
        from scripts.runtime_health_watch import output_row_coverage_issue

        token = "0x" + "1" * 40
        quote = "0x" + "2" * 40
        sender = "0x" + "3" * 40
        buyer = "0x" + "4" * 40
        pool = "0x" + "5" * 40
        event = {
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": quote},
            "opening_block": 100,
            "opening_cohort_to_block": 340,
            "opening_cohort_coverage_complete": True,
            "watch_addresses": [
                {
                    "address": pool,
                    "role": "pool",
                    "control_scope": "pool",
                }
            ],
        }
        logs = [
            {
                "blockNumber": "0x64",
                "transactionHash": "0x" + "6" * 64,
                "topics": [
                    opening.TRANSFER_TOPIC,
                    opening.address_topic(sender),
                    opening.address_topic(pool),
                ],
            },
            {
                "blockNumber": "0x65",
                "transactionHash": "0x" + "7" * 64,
                "topics": [
                    opening.TRANSFER_TOPIC,
                    opening.address_topic(pool),
                    opening.address_topic(buyer),
                ],
            },
            {
                "blockNumber": "0x66",
                "transactionHash": "0x" + "8" * 64,
                "topics": [opening.TRANSFER_TOPIC],
            },
        ]
        with mock.patch.object(
            opening,
            "global_address_labels",
            return_value={},
        ):
            _, evidence = opening.opening_buyer_scope_from_transfer_logs(
                event,
                logs,
            )

        self.assertEqual(evidence["opening_buyer_scope_addresses"], [buyer])
        self.assertFalse(evidence["opening_buyer_scope_complete"])
        self.assertEqual(
            output_row_coverage_issue(
                "opening",
                {
                    "status": "opened",
                    "opening_cohort_coverage_complete": True,
                    "opening_buyer_scope_complete": False,
                },
            ),
            "opening buyer address scope incomplete",
        )

    def test_health_rejects_opening_quote_identity_conflict(self) -> None:
        from scripts.runtime_health_watch import (
            matching_rows_coverage_issue,
            output_row_coverage_issue,
        )

        self.assertEqual(
            output_row_coverage_issue(
                "opening",
                {
                    "status": "opened",
                    "opening_cohort_coverage_complete": True,
                    "opening_liquidity_coverage_complete": True,
                    "opening_buyer_scope_complete": True,
                    "cache_identity_status": "metadata_conflict_unresolved",
                    "cache_identity_conflict": "quote_address_changed",
                },
            ),
            (
                "opening stable identity metadata conflict="
                "quote_address_changed"
            ),
        )
        self.assertEqual(
            output_row_coverage_issue(
                "opening",
                {
                    "status": "opened",
                    "opening_cohort_coverage_complete": True,
                    "opening_liquidity_coverage_complete": True,
                    "opening_buyer_scope_complete": True,
                    "cache_identity_status": "metadata_conflict_rebuilt",
                    "cache_identity_conflict": "quote_address_changed",
                    "rows": [],
                },
            ),
            "",
        )
        self.assertIn(
            "quote_address_changed",
            matching_rows_coverage_issue(
                "opening",
                [
                    {
                        "status": "opened",
                        "opening_cohort_coverage_complete": True,
                        "opening_liquidity_coverage_complete": True,
                        "opening_buyer_scope_complete": True,
                        "cache_identity_status": "stable_match",
                        "rows": [],
                    },
                    {
                        "status": "opened",
                        "opening_cohort_coverage_complete": True,
                        "opening_liquidity_coverage_complete": True,
                        "opening_buyer_scope_complete": True,
                        "cache_identity_status": (
                            "metadata_conflict_unresolved"
                        ),
                        "cache_identity_conflict": (
                            "quote_address_changed"
                        ),
                    },
                ],
            ),
        )

    def test_health_blocks_opening_cohort_gap_and_warns_on_tail(self) -> None:
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
        )

        self.assertEqual(
            output_row_coverage_issue(
                "opening",
                {
                    "status": "opened",
                    "opening_cohort_coverage_complete": False,
                    "rows": [],
                },
            ),
            "opening cohort transfer coverage incomplete",
        )
        warning = output_row_coverage_warning(
            "opening",
            {
                "status": "opened",
                "opening_cohort_coverage_complete": True,
                "opening_liquidity_coverage_complete": True,
                "opening_recent_tail_coverage_complete": False,
                "rows": [],
            },
        )
        self.assertIn("recent transfer tail uses a bounded window", warning)
        import scripts.alpha_opening_block_watch as opening

        scoped = {
            "status": "opened",
            "opening_cohort_coverage_complete": True,
            "opening_liquidity_coverage_complete": True,
            "opening_buyer_scope_complete": True,
            "opening_recent_tail_coverage_complete": True,
            "opening_log_required_windows_complete": True,
            "opening_log_contiguous_coverage_complete": False,
            "rows": [],
        }
        self.assertTrue(opening.opening_coverage_complete(scoped))
        self.assertIn(
            "middle history belongs to intraday/holder stages",
            output_row_coverage_warning("opening", scoped),
        )
        sampled = {
            **scoped,
            "opening_receipt_classification_complete": False,
        }
        self.assertIn(
            "opening receipt attribution sampled",
            output_row_coverage_warning("opening", sampled),
        )

    def test_rpc_deadline_stops_multi_endpoint_retry(self) -> None:
        from sniper_engine import rpc

        deadline = time.monotonic() + 0.03

        def slow_failure(url, method, params, timeout):
            time.sleep(timeout)
            raise RuntimeError("rpc transport error")

        started = time.monotonic()
        with (
            mock.patch.object(rpc, "rpc_urls", return_value=["first", "second"]),
            mock.patch.object(rpc, "rpc_call_url", side_effect=slow_failure),
            self.assertRaises(rpc.RpcDeadlineExceeded),
        ):
            rpc.rpc_call(
                "bsc",
                "eth_blockNumber",
                [],
                timeout=1,
                deadline=deadline,
            )

        self.assertLess(time.monotonic() - started, 0.2)

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

        def fetch(chain, query, chunk_blocks, max_logs, timeout, enforce_deadline):
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
            mock.patch.object(opening, "get_logs_quick", side_effect=fetch),
        ):
            rows = opening.opening_transfer_logs(event, 1000)

        self.assertEqual(rows, [])
        self.assertEqual(calls, [(100, 1000, 1000)])

    def test_opening_transfer_default_budget_covers_dense_cohort(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        rows = [
            {
                "transactionHash": "0x" + f"{index:064x}",
                "logIndex": hex(index),
            }
            for index in range(5001)
        ]
        event = {
            "chain": "bsc",
            "opening_block": 100,
            "token": {"address": "0x" + "1" * 40},
        }
        with (
            mock.patch.object(
                opening,
                "quick_rpc_call",
                return_value=rows,
            ) as fetch,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            result = opening.opening_transfer_logs(event, 200)

        self.assertEqual(len(result), 5001)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(event["opening_cohort_coverage_complete"])

    def test_opening_transfer_budget_cannot_hide_a_second_range(self) -> None:
        import scripts.alpha_opening_block_watch as opening

        calls: list[tuple[int, int, int]] = []

        def fetch(chain, query, chunk_blocks, max_logs, timeout, enforce_deadline):
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
            mock.patch.object(opening, "get_logs_quick", side_effect=fetch),
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

    def test_project_metadata_scope_and_balance_fail_closed(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        contract = {"chain": "bsc", "address": token}
        base_item = {
            "symbol": "TEST",
            "contracts": [contract],
            "watch_addresses": [{"chain": "bsc", "address": watched}],
        }
        for patchers in (
            (mock.patch.object(project, "token_decimals", side_effect=RuntimeError("rpc")),),
            (
                mock.patch.object(project, "token_decimals", return_value=18),
                mock.patch.object(project, "token_total_supply", side_effect=RuntimeError("rpc")),
            ),
        ):
            with self.subTest(patch_count=len(patchers)), ExitStack() as stack:
                for patcher in patchers:
                    stack.enter_context(patcher)
                result = project.build_project(base_item, {}, {}, 0, 10)
            self.assertFalse(result["coverage_complete"])
            self.assertEqual(result["contracts"][0]["scan_status"], "error")

        owner_item = {
            "symbol": "TEST",
            "contracts": [contract],
            "project_operator_probe": "owner",
        }
        with (
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "project_rpc_call",
                side_effect=RuntimeError("rpc"),
            ),
        ):
            result = project.build_project(owner_item, {}, {}, 0, 10)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["contracts"][0]["scan_status"], "error")

        target_hash = "0x" + "a" * 64
        watch_scope = [
            {
                "chain": "bsc",
                "address": watched,
                "watch_quote": False,
                "control_scope": "token",
                "identity_status": "verified",
            }
        ]

        def complete_logs(*_args, on_chunk_complete=None, **_kwargs):
            on_chunk_complete(0, 10, [])
            return [], []

        with (
            mock.patch.object(project, "latest_block", return_value=10),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "effective_watch_addresses",
                return_value=(watch_scope, "verified_token_controller"),
            ),
            mock.patch.object(project, "canonical_block_hash", return_value=target_hash),
            mock.patch.object(project, "get_transfer_logs", side_effect=complete_logs),
            mock.patch.object(
                project,
                "build_balances",
                return_value=[{"address": watched, "error": "rpc"}],
            ),
        ):
            balance_result = project.build_contract(
                "TEST",
                contract,
                base_item,
                {},
                {},
                finality=0,
                lookback=20,
            )
        self.assertFalse(balance_result["coverage_complete"])
        self.assertEqual(balance_result["scan_status"], "balance_scan_pending")
        self.assertEqual(balance_result["latest_block"], 0)
        self.assertEqual(balance_result["log_error_count"], 1)

        with (
            mock.patch.object(project, "latest_block", return_value=10),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "effective_watch_addresses",
                return_value=(watch_scope, "verified_token_controller"),
            ),
            mock.patch.object(project, "canonical_block_hash", return_value=target_hash),
            mock.patch.object(project, "get_transfer_logs", side_effect=complete_logs),
            mock.patch.object(project, "build_balances", return_value=[]),
        ):
            empty_balance_result = project.build_contract(
                "TEST",
                contract,
                base_item,
                {},
                {},
                finality=0,
                lookback=20,
            )
        self.assertFalse(empty_balance_result["coverage_complete"])
        self.assertEqual(
            empty_balance_result["scan_status"],
            "balance_scan_pending",
        )

    def test_project_checkpoint_continuity_has_no_gap_and_reorg_blocks(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        checkpoint_hash = "0x" + "a" * 64
        replacement_hash = "0x" + "b" * 64
        target_hash = "0x" + "c" * 64
        watch_scope = [{"chain": "bsc", "address": watched}]

        def run(
            previous_chain_hash: str,
            stored_hash: str | None = checkpoint_hash,
        ) -> tuple[dict[str, object], list[tuple[int, int, int]]]:
            ranges: list[tuple[int, int, int]] = []

            def canonical(_chain: str, block: int) -> str:
                return previous_chain_hash if block == 100 else target_hash

            def complete_logs(
                _chain,
                _token,
                _watched,
                from_block,
                to_block,
                *,
                resume_from_block=None,
                on_chunk_complete=None,
            ):
                ranges.append((from_block, to_block, resume_from_block))
                on_chunk_complete(from_block, to_block, [])
                return [], []

            with (
                mock.patch.object(project, "latest_block", return_value=1000),
                mock.patch.object(project, "token_decimals", return_value=18),
                mock.patch.object(project, "token_total_supply", return_value="1000"),
                mock.patch.object(
                    project,
                    "effective_watch_addresses",
                    return_value=(watch_scope, "configured"),
                ),
                mock.patch.object(project, "canonical_block_hash", side_effect=canonical),
                mock.patch.object(project, "get_transfer_logs", side_effect=complete_logs),
                mock.patch.object(
                    project,
                    "build_balances",
                    return_value=[
                        {
                            "address": watched,
                            "balance_token_address": token,
                            "balance": "0",
                        }
                    ],
                ),
                mock.patch.object(project, "build_contract_alerts", return_value=[]),
            ):
                result = project.build_contract(
                    "TEST",
                    {"chain": "bsc", "address": token},
                    {},
                    {("TEST", "bsc", token): 100},
                    {},
                    finality=0,
                    lookback=100,
                    previous_hashes=(
                        {("TEST", "bsc", token): stored_hash}
                        if stored_hash
                        else {}
                    ),
                )
            return result, ranges

        continuous, continuous_ranges = run(checkpoint_hash)
        self.assertTrue(continuous["coverage_complete"])
        self.assertEqual(continuous["requested_from_block"], 101)
        self.assertEqual(continuous_ranges, [(101, 1000, 101)])

        blocked, blocked_ranges = run(replacement_hash)
        self.assertFalse(blocked["coverage_complete"])
        self.assertEqual(blocked["scan_status"], "previous_checkpoint_reorg")
        self.assertEqual(blocked["latest_block"], 100)
        self.assertEqual(blocked_ranges, [])

        unverifiable, unverifiable_ranges = run(checkpoint_hash, None)
        self.assertFalse(unverifiable["coverage_complete"])
        self.assertEqual(
            unverifiable["scan_status"],
            "previous_checkpoint_unverifiable",
        )
        self.assertEqual(unverifiable["latest_block"], 100)
        self.assertEqual(unverifiable_ranges, [])

    def test_project_log_gap_keeps_previous_checkpoint_and_balances(self) -> None:
        from decimal import Decimal

        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        calls: list[tuple[int, int]] = []

        def fetch(chain, method, params):
            if method == "eth_getBlockByNumber":
                return {"hash": "0x" + "a" * 64}
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
                    "address": token,
                    "blockHash": "0x" + f"{bounds[0]:064x}",
                    "blockNumber": hex(bounds[0]),
                    "data": "0x" + f"{1:064x}",
                    "removed": False,
                    "topics": [
                        project.TRANSFER_TOPIC,
                        project.topic_address(watched),
                        project.topic_address(watched),
                    ],
                    "transactionHash": "0x" + "3" * 64,
                    "transactionIndex": "0x0",
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
                previous_hashes={
                    ("AEON", "bsc", token): "0x" + "a" * 64,
                },
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

    def test_project_log_row_cap_splits_and_single_block_fails_closed(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        calls: list[tuple[int, int]] = []

        def row(block: int) -> dict[str, object]:
            return {
                "address": token,
                "blockHash": "0x" + f"{block:064x}",
                "blockNumber": hex(block),
                "data": "0x" + f"{1:064x}",
                "removed": False,
                "topics": [
                    project.TRANSFER_TOPIC,
                    project.topic_address(watched),
                    project.topic_address(watched),
                ],
                "transactionHash": "0x" + f"{block:064x}",
                "transactionIndex": "0x0",
                "logIndex": "0x0",
            }

        def split_fetch(chain, method, params):
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            start = int(query["fromBlock"], 16)
            end = int(query["toBlock"], 16)
            calls.append((start, end))
            if (start, end) in {(1, 4), (1, 2), (3, 4)}:
                return [row(start), row(end)]
            return [row(start)]

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_PROJECT_LOG_CHUNK_BLOCKS": "4",
                    "ALPHA_PROJECT_PROVIDER_MAX_ROWS_PER_QUERY": "2",
                },
            ),
            mock.patch.object(project, "rpc_call", side_effect=split_fetch),
        ):
            rows, errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                1,
                4,
            )

        self.assertEqual(errors, [])
        self.assertEqual([project.block_number(item) for item in rows], [1, 2, 3, 4])
        self.assertIn((1, 2), calls)
        self.assertIn((3, 4), calls)

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_PROJECT_PROVIDER_MAX_ROWS_PER_QUERY": "2"},
            ),
            mock.patch.object(project, "rpc_call", return_value=[row(5), row(5)]),
        ):
            capped_rows, capped_errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                5,
                5,
            )

        self.assertEqual(capped_rows, [])
        self.assertEqual(capped_errors, ["eth_getLogs coverage truncated for 5-5"])
        failed = project.build_contract_error(
            {"chain": "bsc", "address": token},
            RuntimeError("rpc failed"),
            previous_tip=77,
        )
        self.assertEqual(failed["latest_block"], 77)
        self.assertEqual(failed["from_block"], 78)

        base = row(6)
        normalized_duplicate = {
            **base,
            "address": str(base["address"]).upper(),
            "blockHash": str(base["blockHash"]).upper(),
            "blockNumber": "0x06",
            "data": str(base["data"]).upper(),
            "topics": [str(topic).upper() for topic in base["topics"]],
            "transactionHash": str(base["transactionHash"]).upper(),
            "transactionIndex": "0x00",
            "logIndex": "0x00",
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_PROJECT_PROVIDER_MAX_ROWS_PER_QUERY": "128"},
            ),
            mock.patch.object(
                project,
                "rpc_call",
                side_effect=[[base], [normalized_duplicate]],
            ),
        ):
            normalized_rows, normalized_errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                6,
                6,
            )
        self.assertEqual(normalized_errors, [])
        self.assertEqual(len(normalized_rows), 1)

        for field, value in (
            ("blockHash", "0x" + "f" * 64),
            ("data", "0x" + f"{2:064x}"),
        ):
            conflicting = {**base, field: value}
            with mock.patch.object(
                project,
                "rpc_call",
                side_effect=[[base], [conflicting]],
            ):
                conflict_rows, conflict_errors = project.get_transfer_logs(
                    "bsc",
                    token,
                    [watched],
                    6,
                    6,
                )
            self.assertEqual(conflict_rows, [])
            self.assertEqual(
                conflict_errors,
                ["eth_getLogs conflicting duplicate for 6-6"],
            )

        malformed = {**base, "transactionHash": ""}
        with mock.patch.object(project, "rpc_call", return_value=[malformed]):
            malformed_rows, malformed_errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                6,
                6,
            )
        self.assertEqual(malformed_rows, [])
        self.assertEqual(
            malformed_errors,
            ["eth_getLogs malformed identity for 6-6"],
        )

        for invalid_row in (
            row(7),
            {
                **base,
                "topics": [
                    project.TRANSFER_TOPIC,
                    project.topic_address("0x" + "9" * 40),
                    project.topic_address(watched),
                ],
            },
        ):
            with mock.patch.object(project, "rpc_call", return_value=[invalid_row]):
                invalid_rows, invalid_errors = project.get_transfer_logs(
                    "bsc",
                    token,
                    [watched],
                    6,
                    6,
                )
            self.assertEqual(invalid_rows, [])
            self.assertEqual(
                invalid_errors,
                ["eth_getLogs result outside query for 6-6"],
            )

        conflicting = {**base, "data": "0x" + f"{2:064x}"}
        with (
            mock.patch.object(project, "latest_block", return_value=6),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "canonical_block_hash",
                return_value="0x" + "a" * 64,
            ),
            mock.patch.object(
                project,
                "rpc_call",
                side_effect=[[base], [conflicting]],
            ),
            mock.patch.object(
                project,
                "build_balances",
                side_effect=AssertionError("conflicting logs must not advance"),
            ),
        ):
            conflict_result = project.build_contract(
                "TEST",
                {"chain": "bsc", "address": token},
                {
                    "watch_addresses": [
                        {"chain": "bsc", "address": watched}
                    ]
                },
                {("TEST", "bsc", token): 5},
                {},
                finality=0,
                lookback=10,
                previous_hashes={
                    ("TEST", "bsc", token): "0x" + "a" * 64,
                },
            )
        self.assertEqual(conflict_result["latest_block"], 5)
        self.assertEqual(conflict_result["log_error_count"], 1)

    def test_project_progress_resumes_completed_prefix_and_next_cycle_cursor(
        self,
    ) -> None:
        import scripts.alpha_project_watch as project

        token_a = "0x" + "1" * 40
        token_b = "0x" + "2" * 40
        config = {
            "items": [
                {
                    "symbol": "FIRST",
                    "priority": "P1_MONITOR",
                    "contracts": [{"chain": "bsc", "address": token_a}],
                },
                {
                    "symbol": "SECOND",
                    "priority": "P1_MONITOR",
                    "contracts": [{"chain": "bsc", "address": token_b}],
                },
            ]
        }
        calls: list[tuple[str, int]] = []
        interrupt_second = True

        def build_contract(
            symbol,
            contract,
            item,
            previous_tips,
            previous_balance_map,
            finality,
            lookback,
            **_kwargs,
        ):
            nonlocal interrupt_second
            previous_tip = previous_tips.get(
                (symbol, contract["chain"], contract["address"]),
                0,
            )
            calls.append((symbol, previous_tip))
            if symbol == "SECOND" and interrupt_second:
                interrupt_second = False
                raise SystemExit(124)
            return {
                "chain": contract["chain"],
                "address": contract["address"],
                "raw_latest_block": previous_tip + 100,
                "latest_block": previous_tip + 100,
                "previous_latest_block": previous_tip,
                "requested_from_block": previous_tip + 1,
                "target_latest_block": previous_tip + 100,
                "target_latest_block_hash": "0x" + "a" * 64,
                "covered_through_block": previous_tip + 100,
                "next_from_block": previous_tip + 101,
                "coverage_complete": True,
                "transfer_coverage_complete": True,
                "scan_status": "complete",
                "decimals": 18,
                "total_supply": "1000",
                "watch_address_count": 0,
                "balance_target_count": 0,
                "watch_addresses": [],
                "operator_attribution_state": "unresolved",
                "log_error_count": 0,
                "balances": [],
                "recent_transfers": [],
                "alerts": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "watchlist.json"
            latest_path = root / "latest.json"
            report_path = root / "latest.md"
            progress_path = root / "progress.json"
            pending_path = root / "pending.json"
            pending_report_path = root / "pending.md"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with (
                mock.patch.object(project, "CONFIG_PATH", config_path),
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "PENDING_PATH", pending_path),
                mock.patch.object(
                    project,
                    "PENDING_REPORT_PATH",
                    pending_report_path,
                ),
                mock.patch.object(project, "build_contract", side_effect=build_contract),
                self.assertRaises(SystemExit),
            ):
                project.build_snapshot()

            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(len(progress["completed_projects"]), 1)
            self.assertIsNone(progress["active_project"])
            config["generated_at"] = "2026-08-01T01:02:03+00:00"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with (
                mock.patch.object(project, "CONFIG_PATH", config_path),
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "PENDING_PATH", pending_path),
                mock.patch.object(
                    project,
                    "PENDING_REPORT_PATH",
                    pending_report_path,
                ),
                mock.patch.object(project, "build_contract", side_effect=build_contract),
            ):
                resumed = project.build_snapshot()
                self.assertTrue(resumed["resumed_from_progress"])
                with mock.patch.object(project, "maybe_send_telegram"):
                    project.publish_snapshot(resumed)

            self.assertEqual(calls, [("FIRST", 0), ("SECOND", 0), ("SECOND", 0)])
            self.assertFalse(progress_path.exists())

            with (
                mock.patch.object(project, "CONFIG_PATH", config_path),
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "build_contract", side_effect=build_contract),
            ):
                next_cycle = project.build_snapshot()

            self.assertFalse(next_cycle["resumed_from_progress"])
            self.assertEqual(calls[-2:], [("FIRST", 100), ("SECOND", 100)])

    def test_project_contract_cursor_resumes_after_completed_chunk(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        target_hash = "0x" + "a" * 64
        calls: list[tuple[int, int, str]] = []
        fail_after_first_chunk = True

        def fake_rpc(_chain, method, params):
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            start = int(query["fromBlock"], 16)
            end = int(query["toBlock"], 16)
            direction = "from" if query["topics"][1] is not None else "to"
            calls.append((start, end, direction))
            if fail_after_first_chunk and start >= 8:
                raise project.RpcDeadlineExceeded("deadline")
            return []

        checkpoints: list[dict[str, object]] = []
        watch_scope = [
            {
                "chain": "bsc",
                "address": watched,
                "label": "controller",
                "role": "token_controller",
                "level": "HIGH",
                "watch_quote": False,
                "watch_quote_tokens": [],
                "control_scope": "token",
                "identity_status": "verified",
                "attribution": "fixture",
            }
        ]
        common_patches = (
            mock.patch.object(project, "latest_block", return_value=10),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(
                project,
                "token_total_supply",
                return_value="1000",
            ),
            mock.patch.object(
                project,
                "effective_watch_addresses",
                return_value=(watch_scope, "verified_token_controller"),
            ),
            mock.patch.object(
                project,
                "canonical_block_hash",
                return_value=target_hash,
            ),
            mock.patch.object(project, "project_rpc_call", side_effect=fake_rpc),
            mock.patch.object(
                project,
                "build_balances",
                return_value=[
                    {
                        "address": watched,
                        "balance_token_address": token,
                        "balance": "0",
                    }
                ],
            ),
            mock.patch.object(project, "build_contract_alerts", return_value=[]),
            mock.patch.dict(
                os.environ,
                {"ALPHA_PROJECT_LOG_CHUNK_BLOCKS": "2"},
            ),
        )
        with ExitStack() as stack:
            for patcher in common_patches:
                stack.enter_context(patcher)
            first = project.build_contract(
                "TEST",
                {"chain": "bsc", "address": token},
                {},
                {("TEST", "bsc", token): 5},
                {},
                finality=0,
                lookback=4,
                previous_hashes={
                    ("TEST", "bsc", token): target_hash,
                },
                on_progress=lambda row: checkpoints.append(copy.deepcopy(row)),
            )

        self.assertFalse(first["coverage_complete"])
        self.assertEqual(first["latest_block"], 5)
        self.assertEqual(checkpoints[-1]["covered_through_block"], 7)
        self.assertEqual(checkpoints[-1]["next_from_block"], 8)
        self.assertEqual(
            calls[:3],
            [(6, 7, "from"), (6, 7, "to"), (8, 9, "from")],
        )

        resumed_progress = copy.deepcopy(checkpoints[-1])
        calls.clear()
        fail_after_first_chunk = False
        with ExitStack() as stack:
            for patcher in (
                mock.patch.object(project, "latest_block", return_value=99),
                mock.patch.object(project, "token_decimals", return_value=18),
                mock.patch.object(
                    project,
                    "token_total_supply",
                    return_value="1000",
                ),
                mock.patch.object(
                    project,
                    "effective_watch_addresses",
                    return_value=(watch_scope, "verified_token_controller"),
                ),
                mock.patch.object(
                    project,
                    "canonical_block_hash",
                    return_value=target_hash,
                ),
                mock.patch.object(
                    project,
                    "project_rpc_call",
                    side_effect=fake_rpc,
                ),
                mock.patch.object(
                    project,
                    "build_balances",
                    return_value=[
                        {
                            "address": watched,
                            "balance_token_address": token,
                            "balance": "0",
                        }
                    ],
                ),
                mock.patch.object(
                    project,
                    "build_contract_alerts",
                    return_value=[],
                ),
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_PROJECT_LOG_CHUNK_BLOCKS": "2"},
                ),
            ):
                stack.enter_context(patcher)
            second = project.build_contract(
                "TEST",
                {"chain": "bsc", "address": token},
                {},
                {("TEST", "bsc", token): 5},
                {},
                finality=0,
                lookback=4,
                previous_hashes={
                    ("TEST", "bsc", token): target_hash,
                },
                resumed_progress=resumed_progress,
            )

        self.assertTrue(second["coverage_complete"])
        self.assertEqual(second["latest_block"], 10)
        self.assertEqual(second["covered_through_block"], 10)
        self.assertEqual(second["next_from_block"], 11)
        self.assertEqual(calls[0], (8, 9, "from"))
        self.assertNotIn((6, 7, "from"), calls)

    def test_project_second_direction_failure_does_not_advance_chunk(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        calls: list[str] = []
        checkpoints: list[tuple[int, int]] = []

        def fail_second(_chain, _method, params):
            direction = "from" if params[0]["topics"][1] is not None else "to"
            calls.append(direction)
            if direction == "to":
                raise RuntimeError("fixture failure")
            return []

        with mock.patch.object(
            project,
            "project_rpc_call",
            side_effect=fail_second,
        ):
            rows, errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                6,
                7,
                on_chunk_complete=lambda start, end, _rows: checkpoints.append(
                    (start, end)
                ),
            )

        self.assertEqual(rows, [])
        self.assertTrue(errors)
        self.assertEqual(calls, ["from", "to"])
        self.assertEqual(checkpoints, [])

        calls.clear()
        with mock.patch.object(project, "project_rpc_call", return_value=[]):
            rows, errors = project.get_transfer_logs(
                "bsc",
                token,
                [watched],
                6,
                7,
                on_chunk_complete=lambda start, end, _rows: checkpoints.append(
                    (start, end)
                ),
            )
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])
        self.assertEqual(checkpoints, [(6, 7)])

    def test_project_250001_block_bootstrap_resumes_without_coverage_gaps(
        self,
    ) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        target_hash = "0x" + "a" * 64
        progress: dict[str, object] = {}
        accepted_ranges: list[tuple[int, int]] = []
        successful_queries: list[tuple[int, int]] = []
        covered_through = 49999
        completed = None
        watch_scope = [
            {
                "chain": "bsc",
                "address": watched,
                "role": "token_controller",
                "watch_quote": False,
                "control_scope": "token",
                "identity_status": "verified",
            }
        ]

        for _cycle in range(10):
            successful_directions = 0

            def fake_rpc(_chain, _method, params):
                nonlocal successful_directions
                query = params[0]
                start = int(query["fromBlock"], 16)
                end = int(query["toBlock"], 16)
                if successful_directions >= 6:
                    raise project.RpcDeadlineExceeded("fixture deadline")
                successful_directions += 1
                successful_queries.append((start, end))
                return []

            def checkpoint(row):
                nonlocal progress, covered_through
                progress = copy.deepcopy(row)
                if "covered_through_block" not in row:
                    return
                current_covered = int(row["covered_through_block"])
                if current_covered > covered_through:
                    accepted_ranges.append(
                        (covered_through + 1, current_covered)
                    )
                    covered_through = current_covered

            with (
                mock.patch.object(project, "latest_block", return_value=300000),
                mock.patch.object(project, "token_decimals", return_value=18),
                mock.patch.object(
                    project,
                    "token_total_supply",
                    return_value="1000",
                ),
                mock.patch.object(
                    project,
                    "effective_watch_addresses",
                    return_value=(watch_scope, "verified_token_controller"),
                ),
                mock.patch.object(
                    project,
                    "canonical_block_hash",
                    return_value=target_hash,
                ),
                mock.patch.object(
                    project,
                    "project_rpc_call",
                    side_effect=fake_rpc,
                ),
                mock.patch.object(
                    project,
                    "build_balances",
                    return_value=[
                        {
                            "address": watched,
                            "balance_token_address": token,
                            "balance": "0",
                        }
                    ],
                ),
                mock.patch.object(
                    project,
                    "build_contract_alerts",
                    return_value=[],
                ),
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_PROJECT_LOG_CHUNK_BLOCKS": "10000"},
                ),
            ):
                completed = project.build_contract(
                    "TEST",
                    {"chain": "bsc", "address": token},
                    {"project_lookback_blocks": 250000},
                    {},
                    {},
                    finality=0,
                    lookback=50000,
                    resumed_progress=progress,
                    on_progress=checkpoint,
                )
            if completed["coverage_complete"]:
                break
            self.assertEqual(completed["latest_block"], 0)

        self.assertIsNotNone(completed)
        self.assertTrue(completed["coverage_complete"])
        self.assertEqual(completed["requested_from_block"], 50000)
        self.assertEqual(completed["latest_block"], 300000)
        self.assertEqual(accepted_ranges[0], (50000, 59999))
        self.assertEqual(accepted_ranges[-1], (300000, 300000))
        self.assertEqual(
            sum(end - start + 1 for start, end in accepted_ranges),
            250001,
        )
        self.assertTrue(
            all(
                left[1] + 1 == right[0]
                for left, right in zip(
                    accepted_ranges,
                    accepted_ranges[1:],
                )
            )
        )
        self.assertTrue(
            all(
                successful_queries.count(bounds) == 2
                for bounds in set(successful_queries)
            )
        )

    def test_project_scan_fingerprint_ignores_previous_report_fields(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        item = {
            "symbol": "TEST",
            "priority": "P1_MONITOR",
            "contracts": [{"chain": "bsc", "address": token}],
            "watch_addresses": [{"chain": "bsc", "address": watched}],
        }
        previous = {
            "generated_at": "first",
            "projects": [
                {
                    "symbol": "TEST",
                    "analysis": {"volatile": "first"},
                    "alerts": [{"type": "fixture"}],
                    "contracts": [
                        {
                            "chain": "bsc",
                            "address": token,
                            "latest_block": 100,
                            "balances": [
                                {
                                    "address": watched,
                                    "balance_token_address": token,
                                    "balance": "12.5",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        refreshed = copy.deepcopy(previous)
        refreshed["generated_at"] = "second"
        refreshed["projects"][0]["analysis"] = {"volatile": "second"}
        refreshed["projects"][0]["alerts"] = []
        first = project.project_scan_fingerprint([item], previous, 20, 250000)
        second = project.project_scan_fingerprint([item], refreshed, 20, 250000)
        self.assertEqual(first, second)

        changed_scope = copy.deepcopy(item)
        changed_scope["watch_addresses"][0]["address"] = "0x" + "4" * 40
        self.assertNotEqual(
            first,
            project.project_scan_fingerprint(
                [changed_scope],
                previous,
                20,
                250000,
            ),
        )
        self.assertNotEqual(
            first,
            project.project_scan_fingerprint([item], previous, 21, 250000),
        )
        self.assertNotEqual(
            first,
            project.project_scan_fingerprint([item], previous, 20, 50000),
        )

        refreshed["projects"][0]["contracts"][0]["latest_block"] = 101
        self.assertNotEqual(
            first,
            project.project_scan_fingerprint([item], refreshed, 20, 250000),
        )

    def test_project_target_hash_change_resets_completed_transfer_window(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        checkpoints: list[dict[str, object]] = []
        old_hash = "0x" + "a" * 64
        new_hash = "0x" + "b" * 64
        with (
            mock.patch.object(project, "latest_block", return_value=10),
            mock.patch.object(project, "token_decimals", return_value=18),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "effective_watch_addresses",
                return_value=([], "unresolved"),
            ),
            mock.patch.object(
                project,
                "canonical_block_hash",
                side_effect=[old_hash, old_hash, new_hash],
            ),
        ):
            result = project.build_contract(
                "TEST",
                {"chain": "bsc", "address": token},
                {},
                {("TEST", "bsc", token): 5},
                {},
                finality=0,
                lookback=4,
                previous_hashes={
                    ("TEST", "bsc", token): old_hash,
                },
                on_progress=lambda row: checkpoints.append(copy.deepcopy(row)),
            )

        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["scan_status"], "target_reorg_retry")
        self.assertEqual(result["latest_block"], 5)
        self.assertEqual(checkpoints[-1]["next_from_block"], 6)
        self.assertEqual(checkpoints[-1]["covered_through_block"], 5)
        self.assertEqual(checkpoints[-1]["recent_transfers"], [])

    def test_project_progress_is_a_runtime_health_blocker(self) -> None:
        import scripts.runtime_health_watch as health

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            progress_path = (
                root / "output" / "alpha_project_watch" / "progress.json"
            )
            progress_path.parent.mkdir(parents=True)
            progress_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "completed_projects": [],
                        "active_project": {
                            "contract_progress": {
                                "previous_latest_block": 5,
                                "requested_from_block": 6,
                                "target_latest_block": 10,
                                "target_latest_block_hash": "0x" + "a" * 64,
                                "next_from_block": 8,
                                "covered_through_block": 7,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            issues = health.project_scan_progress_issues(root)

        self.assertEqual(len(issues), 1)
        self.assertIn("project catchup pending", issues[0]["detail"])
        self.assertEqual(
            health.output_row_coverage_issue(
                "project",
                {"coverage_complete": False, "contracts": []},
            ),
            "project coverage incomplete",
        )

    def test_project_transfer_alert_key_includes_log_index(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        tx_hash = "0x" + "3" * 64
        transfers = [
            {
                "block": 6,
                "tx": tx_hash,
                "log_index": index,
                "from": watched,
                "to": "0x" + "4" * 40,
                "amount": "100000",
            }
            for index in (0, 1)
        ]
        with mock.patch.dict(
            os.environ,
            {"ALPHA_PROJECT_MIN_TRANSFER_ALERT": "1"},
        ):
            alerts = project.build_contract_alerts(
                "TEST",
                "bsc",
                token,
                5,
                transfers,
                [],
                [
                    {
                        "address": watched,
                        "role": "token_controller",
                        "control_scope": "token",
                        "identity_status": "verified",
                    }
                ],
            )

        self.assertEqual(len(alerts), 2)
        self.assertEqual(len(project.alert_keys(alerts)), 2)

    def test_project_early_chunk_alert_survives_recent_transfer_window(self) -> None:
        import scripts.alpha_project_watch as project

        token = "0x" + "1" * 40
        watched = "0x" + "2" * 40
        receiver = "0x" + "3" * 40
        target_hash = "0x" + "a" * 64

        def raw_transfer(block: int, index: int, amount: int):
            return {
                "address": token,
                "blockHash": "0x" + f"{block:064x}",
                "blockNumber": hex(block),
                "data": "0x" + f"{amount:064x}",
                "removed": False,
                "topics": [
                    project.TRANSFER_TOPIC,
                    project.topic_address(watched),
                    project.topic_address(receiver),
                ],
                "transactionHash": "0x" + f"{index + 1:064x}",
                "transactionIndex": "0x0",
                "logIndex": hex(index),
            }

        high = raw_transfer(6, 0, 1000)
        later = [
            raw_transfer(min(6 + index, 50), index, 1)
            for index in range(1, 46)
        ]

        def fake_logs(
            _chain,
            _token,
            _watched,
            _from,
            _to,
            *,
            resume_from_block=None,
            on_chunk_complete=None,
        ):
            self.assertEqual(resume_from_block, 6)
            on_chunk_complete(6, 6, [high])
            on_chunk_complete(7, 50, [high, *later])
            return [high, *later], []

        with (
            mock.patch.object(project, "latest_block", return_value=50),
            mock.patch.object(project, "token_decimals", return_value=0),
            mock.patch.object(project, "token_total_supply", return_value="1000"),
            mock.patch.object(
                project,
                "effective_watch_addresses",
                return_value=(
                    [
                        {
                            "chain": "bsc",
                            "address": watched,
                            "role": "token_controller",
                            "watch_quote": False,
                            "control_scope": "token",
                            "identity_status": "verified",
                        }
                    ],
                    "verified_token_controller",
                ),
            ),
            mock.patch.object(
                project,
                "canonical_block_hash",
                return_value=target_hash,
            ),
            mock.patch.object(
                project,
                "get_transfer_logs",
                side_effect=fake_logs,
            ),
            mock.patch.object(
                project,
                "build_balances",
                return_value=[
                    {
                        "address": watched,
                        "balance_token_address": token,
                        "balance": "0",
                    }
                ],
            ),
            mock.patch.dict(
                os.environ,
                {"ALPHA_PROJECT_MIN_TRANSFER_ALERT": "100"},
            ),
        ):
            result = project.build_contract(
                "TEST",
                {"chain": "bsc", "address": token},
                {},
                {("TEST", "bsc", token): 5},
                {},
                finality=0,
                lookback=50,
                previous_hashes={
                    ("TEST", "bsc", token): target_hash,
                },
            )

        self.assertTrue(result["coverage_complete"])
        self.assertEqual(len(result["recent_transfers"]), 40)
        self.assertNotIn(
            high["transactionHash"],
            {row["tx"] for row in result["recent_transfers"]},
        )
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["tx"], high["transactionHash"])
        self.assertEqual(len(project.alert_keys(result["alerts"])), 1)

    def test_project_publish_keeps_progress_until_delivery_succeeds(self) -> None:
        import scripts.alpha_project_watch as project

        snapshot = {
            "generated_at": "2026-08-01T00:00:00+00:00",
            "project_count": 0,
            "alert_count": 0,
            "coverage_complete": True,
            "skipped": [],
            "projects": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest_path = root / "latest.json"
            report_path = root / "latest.md"
            progress_path = root / "progress.json"
            pending_path = root / "pending.json"
            pending_report_path = root / "pending.md"
            latest_path.write_text('{"old": true}', encoding="utf-8")
            progress_path.write_text('{"partial": true}', encoding="utf-8")

            with (
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "PENDING_PATH", pending_path),
                mock.patch.object(
                    project,
                    "PENDING_REPORT_PATH",
                    pending_report_path,
                ),
                mock.patch.object(
                    project,
                    "maybe_send_telegram",
                    side_effect=RuntimeError("delivery failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "delivery failed"),
            ):
                project.publish_snapshot(snapshot)

            self.assertEqual(
                json.loads(latest_path.read_text(encoding="utf-8")),
                {"old": True},
            )
            self.assertTrue(progress_path.exists())
            self.assertFalse(report_path.exists())

            with (
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "PENDING_PATH", pending_path),
                mock.patch.object(
                    project,
                    "PENDING_REPORT_PATH",
                    pending_report_path,
                ),
                mock.patch.object(project, "maybe_send_telegram"),
            ):
                project.publish_snapshot(snapshot)

            self.assertEqual(
                json.loads(latest_path.read_text(encoding="utf-8")),
                snapshot,
            )
            self.assertFalse(progress_path.exists())

    def test_project_pending_publish_skips_telegram_and_preserves_baseline(
        self,
    ) -> None:
        import scripts.alpha_project_watch as project

        pending_snapshot = {
            "generated_at": "2026-08-01T00:00:00+00:00",
            "project_count": 1,
            "alert_count": 1,
            "coverage_complete": False,
            "skipped": [],
            "projects": [
                {
                    "symbol": "TEST",
                    "priority": "P1_MONITOR",
                    "analysis": {},
                    "alerts": [
                        {
                            "type": "LAUNCH_WINDOW",
                            "symbol": "TEST",
                            "stage": "PRE_1H",
                            "pool_id": "1",
                            "start_time_utc8": "2026-08-01 08:00:00",
                        }
                    ],
                }
            ],
        }
        empty_snapshot = {
            **pending_snapshot,
            "project_count": 0,
            "alert_count": 0,
            "projects": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest_path = root / "latest.json"
            report_path = root / "latest.md"
            progress_path = root / "progress.json"
            pending_path = root / "pending.json"
            pending_report_path = root / "pending.md"
            seen_path = root / "seen.json"
            latest_path.write_text('{"old": true}', encoding="utf-8")
            progress_path.write_text('{"partial": true}', encoding="utf-8")
            env = {
                "ALPHA_PROJECT_WATCH_TELEGRAM": "1",
                "ALPHA_PROJECT_WATCH_FORCE_TELEGRAM": "0",
                "TELEGRAM_BOT_TOKEN": "",
                "TELEGRAM_CHAT_ID": "",
            }
            with (
                mock.patch.object(project, "LATEST_PATH", latest_path),
                mock.patch.object(project, "REPORT_PATH", report_path),
                mock.patch.object(project, "PROGRESS_PATH", progress_path),
                mock.patch.object(project, "PENDING_PATH", pending_path),
                mock.patch.object(
                    project,
                    "PENDING_REPORT_PATH",
                    pending_report_path,
                ),
                mock.patch.object(project, "SEEN_PATH", seen_path),
                mock.patch.dict(os.environ, env),
                mock.patch.object(
                    project,
                    "maybe_send_telegram",
                    side_effect=AssertionError(
                        "pending snapshot must not send"
                    ),
                ),
            ):
                project.publish_snapshot(pending_snapshot)

            self.assertEqual(
                json.loads(latest_path.read_text(encoding="utf-8")),
                {"old": True},
            )
            self.assertTrue(progress_path.exists())
            self.assertFalse(report_path.exists())
            self.assertEqual(
                json.loads(pending_path.read_text(encoding="utf-8")),
                pending_snapshot,
            )
            self.assertTrue(pending_report_path.exists())
            self.assertFalse(seen_path.exists())

            with (
                mock.patch.object(project, "SEEN_PATH", seen_path),
                mock.patch.dict(os.environ, env),
            ):
                self.assertTrue(project.maybe_send_telegram(empty_snapshot))
                with mock.patch.dict(
                    os.environ,
                    {**env, "ALPHA_PROJECT_WATCH_FORCE_TELEGRAM": "1"},
                ):
                    self.assertFalse(
                        project.maybe_send_telegram(empty_snapshot)
                    )

    def test_project_new_transfer_key_bypasses_repeat_signature_suppression(
        self,
    ) -> None:
        import scripts.alpha_project_watch as project

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok":true,"result":{"message_id":1}}'

        def snapshot(tx_hash: str) -> dict[str, object]:
            alert = {
                "type": "TOKEN_TRANSFER",
                "symbol": "TEST",
                "chain": "bsc",
                "token": "0x" + "1" * 40,
                "tx": tx_hash,
                "amount": "100",
                "level": "HIGH",
            }
            return {
                "generated_at": "2026-08-01T00:00:00+00:00",
                "project_count": 1,
                "alert_count": 1,
                "projects": [
                    {
                        "symbol": "TEST",
                        "priority": "P1_MONITOR",
                        "analysis": {
                            "conclusion": "transfer",
                            "spot_action": "observe",
                            "perp_action": "wait",
                        },
                        "alerts": [alert],
                    }
                ],
            }

        first = snapshot("0x" + "2" * 64)
        second = snapshot("0x" + "3" * 64)
        self.assertEqual(
            project.project_push_signature(first),
            project.project_push_signature(second),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seen_path = root / "seen.json"
            last_push_path = root / "last_push.json"
            with (
                mock.patch.object(project, "SEEN_PATH", seen_path),
                mock.patch.object(project, "LAST_PUSH_PATH", last_push_path),
                mock.patch.dict(
                    os.environ,
                    {
                        "ALPHA_PROJECT_WATCH_TELEGRAM": "1",
                        "ALPHA_PROJECT_WATCH_FORCE_TELEGRAM": "0",
                        "TELEGRAM_BOT_TOKEN": "fixture-token",
                        "TELEGRAM_CHAT_ID": "fixture-chat",
                    },
                ),
                mock.patch.object(
                    project.urllib.request,
                    "urlopen",
                    side_effect=[Response(), Response()],
                ) as urlopen,
            ):
                self.assertTrue(project.maybe_send_telegram(first))
                self.assertTrue(project.maybe_send_telegram(second))

            self.assertEqual(urlopen.call_count, 2)
            self.assertEqual(
                set(json.loads(seen_path.read_text(encoding="utf-8"))),
                set(project.alert_keys(first["projects"][0]["alerts"]))
                | set(project.alert_keys(second["projects"][0]["alerts"])),
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

    def test_cex_gas_priming_scan_stops_at_deadline(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        target = "0x" + "7" * 40
        with (
            mock.patch.object(
                intraday.time,
                "monotonic",
                return_value=10.0,
            ),
            mock.patch.object(
                intraday,
                "block_transactions",
            ) as block_transactions,
        ):
            rows, limited = intraday.cex_gas_priming_transfers(
                {"chain": "bsc"},
                {target},
                100,
                deadline=9.0,
            )

        self.assertEqual(rows, [])
        self.assertTrue(limited)
        block_transactions.assert_not_called()

    def test_cex_gas_priming_budget_covers_multi_endpoint_retry(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        target = "0x" + "7" * 40
        observed_timeouts: list[float] = []

        def fetch_block(
            chain: str,
            block_number: int,
            timeout: float,
        ) -> list[dict[str, object]]:
            observed_timeouts.append(timeout)
            return []

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS": "2"},
            ),
            mock.patch.object(
                intraday.time,
                "monotonic",
                side_effect=[10.0, 15.0],
            ),
            mock.patch.object(
                intraday.opening,
                "rpc_urls",
                return_value=["rpc-1", "rpc-2"],
            ),
            mock.patch.object(
                intraday,
                "block_transactions",
                side_effect=fetch_block,
            ),
        ):
            rows, limited = intraday.cex_gas_priming_transfers(
                {"chain": "bsc"},
                {target},
                100,
                deadline=14.0,
            )

        self.assertEqual(rows, [])
        self.assertTrue(limited)
        self.assertEqual(observed_timeouts, [2.0])

    def test_limited_gas_scan_keeps_positive_cex_evidence(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday
        from scripts.runtime_health_watch import output_row_coverage_warning

        analysis = intraday.analyze_rows(
            {"quote": {"symbol": "USDT"}},
            [
                {
                    "cex_token_deposit": "300000",
                    "cex_quote_estimate": "15000",
                    "cex_deposit_count": 1,
                    "cex_gas_priming_count": 1,
                    "cex_gas_priming_bnb": "0.002",
                    "cex_gas_priming_scan_limited": True,
                }
            ],
            100,
            200,
            1,
            1,
        )

        self.assertEqual(analysis["cex_token_deposit"], "300000")
        self.assertEqual(analysis["cex_gas_priming_count"], 1)
        self.assertTrue(analysis["cex_gas_priming_scan_limited"])
        self.assertIn(
            "gas-priming scan time-limited",
            output_row_coverage_warning(
                "intraday",
                {
                    "status": "scanned",
                    "analysis": analysis,
                },
            ),
        )

    def test_intraday_watcher_budget_emits_explicit_incomplete_rows(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        events = [
            {
                "symbol": symbol,
                "chain": "bsc",
                "token": {"address": "0x" + digit * 40},
            }
            for symbol, digit in (("ONE", "1"), ("TWO", "2"))
        ]
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_INTRADAY_WATCHER_BUDGET_SECONDS": "420"},
            ),
            mock.patch.object(
                intraday.time,
                "monotonic",
                side_effect=[0.0, 421.0, 421.0],
            ),
            mock.patch.object(
                intraday,
                "build_events",
                return_value=events,
            ),
            mock.patch.object(intraday, "scan_event") as scan_event,
        ):
            snapshot = intraday.build_snapshot()

        self.assertEqual(snapshot["budget_exhausted_count"], 2)
        self.assertEqual(
            [row["status"] for row in snapshot["events"]],
            ["budget_exhausted", "budget_exhausted"],
        )
        scan_event.assert_not_called()

    def test_intraday_watcher_budget_is_hard_capped(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        with mock.patch.dict(
            os.environ,
            {"ALPHA_INTRADAY_WATCHER_BUDGET_SECONDS": "600"},
        ):
            self.assertEqual(
                intraday.watcher_budget_seconds(),
                intraday.DEFAULT_WATCHER_BUDGET_SECONDS,
            )

    def test_intraday_hard_alarm_interrupts_slow_rpc_shape(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        started = time.monotonic()

        def slow_rpc_shape() -> None:
            try:
                time.sleep(1)
            except Exception:
                self.fail("watcher alarm must not be swallowed by RPC fallback")

        with self.assertRaises(intraday.WatcherBudgetExceeded):
            intraday.run_with_watcher_alarm(slow_rpc_shape, 0.05)

        self.assertLess(time.monotonic() - started, 0.5)

    def test_intraday_main_writes_incomplete_rows_after_hard_alarm(self) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        spec = {
            "item": {},
            "pool": {"start_time_utc8": "2026-07-30 20:00"},
            "start": datetime(
                2026,
                7,
                30,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            "symbol": "BUDGET",
            "priority": "P1_MONITOR",
            "token_address": "0x" + "1" * 40,
            "quote_address": "0x" + "2" * 40,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "intraday"
            latest_path = out_dir / "latest.json"
            report_path = out_dir / "latest.md"
            history_saw_latest: list[bool] = []
            with (
                mock.patch.object(intraday, "OUT_DIR", out_dir),
                mock.patch.object(
                    intraday,
                    "LATEST_PATH",
                    latest_path,
                ),
                mock.patch.object(
                    intraday,
                    "REPORT_PATH",
                    report_path,
                ),
                mock.patch.object(
                    intraday,
                    "build_event_specs",
                    return_value=[spec],
                ),
                mock.patch.object(
                    intraday,
                    "run_with_watcher_alarm",
                    side_effect=intraday.WatcherBudgetExceeded(),
                ),
                mock.patch.object(
                    intraday,
                    "atomic_write_json",
                    wraps=intraday.atomic_write_json,
                ) as atomic_latest_write,
                mock.patch.object(
                    intraday,
                    "record_cex_micro_gas_candidate_history",
                    side_effect=lambda _snapshot: history_saw_latest.append(
                        latest_path.exists()
                    ),
                ),
                mock.patch.object(
                    intraday,
                    "record_withdrawal_candidate_history",
                ),
                mock.patch.object(
                    intraday,
                    "maybe_send_telegram",
                ),
            ):
                self.assertEqual(intraday.main(), 0)

            payload = json.loads(
                latest_path.read_text(encoding="utf-8")
            )
            atomic_latest_write.assert_called_once_with(latest_path, mock.ANY)

        self.assertEqual(history_saw_latest, [True])
        self.assertEqual(payload["budget_exhausted_count"], 1)
        self.assertEqual(
            payload["events"][0]["status"],
            "budget_exhausted",
        )

    def test_required_only_intraday_keeps_full_snapshot_intact(
        self,
    ) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        snapshot = {
            "generated_at": "2026-07-30T12:00:00+00:00",
            "refresh_scope": "required_only_refresh",
            "event_count": 0,
            "alert_count": 0,
            "events": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "intraday"
            out_dir.mkdir()
            latest_path = out_dir / "latest.json"
            required_path = out_dir / "required_only_latest.json"
            required_report = out_dir / "required_only_latest.md"
            latest_path.write_text(
                json.dumps({"scope": "full_snapshot"}),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_INTRADAY_REQUIRED_ONLY": "1"},
                ),
                mock.patch.object(intraday, "OUT_DIR", out_dir),
                mock.patch.object(intraday, "LATEST_PATH", latest_path),
                mock.patch.object(
                    intraday,
                    "REQUIRED_ONLY_LATEST_PATH",
                    required_path,
                ),
                mock.patch.object(
                    intraday,
                    "REQUIRED_ONLY_REPORT_PATH",
                    required_report,
                ),
                mock.patch.object(
                    intraday,
                    "build_event_specs",
                    return_value=[],
                ),
                mock.patch.object(
                    intraday,
                    "run_with_watcher_alarm",
                    return_value=snapshot,
                ),
                mock.patch.object(
                    intraday,
                    "record_cex_micro_gas_candidate_history",
                ) as micro_history,
                mock.patch.object(
                    intraday,
                    "record_withdrawal_candidate_history",
                ) as withdrawal_history,
                mock.patch.object(intraday, "maybe_send_telegram"),
            ):
                self.assertEqual(intraday.main(), 0)

            self.assertEqual(
                json.loads(latest_path.read_text(encoding="utf-8")),
                {"scope": "full_snapshot"},
            )
            self.assertEqual(
                json.loads(required_path.read_text(encoding="utf-8")),
                snapshot,
            )
            self.assertTrue(required_report.exists())
            micro_history.assert_not_called()
            withdrawal_history.assert_not_called()

    def test_health_does_not_fall_back_when_new_required_only_omits_target(
        self,
    ) -> None:
        import scripts.binance_alpha_catalog_watch as catalog
        from scripts.runtime_health_watch import alpha_coverage_issues

        contract = "0x" + "a" * 40
        current = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        listing = current - timedelta(hours=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy, focus_item = self.write_focus_config(
                root,
                "TARGET",
                contract=contract,
                listing_time_utc=listing.isoformat(),
            )

            def write(relative: str, payload: dict[str, object]) -> Path:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
                return path

            write(
                "output/binance_alpha_catalog_watch/latest.json",
                {
                    "status": "pass",
                    "selected": [
                        {
                            "symbol": "TARGET",
                            "chain": "bsc",
                            "contract": contract,
                            "listing_time_utc": listing.isoformat(),
                            "lifecycle_first_seen_at": (
                                listing + timedelta(minutes=45)
                            ).isoformat(),
                        }
                    ],
                },
            )
            write(
                "output/binance_alpha_catalog_watch/current_watchlist.json",
                {
                    "monitoring_policy": policy,
                    "monitoring_policy_fingerprint": (
                        catalog.monitoring_policy_fingerprint(policy)
                    ),
                    "items": [focus_item],
                },
            )
            write(
                "output/alpha_project_watch/latest.json",
                {
                    "projects": [
                        {
                            "symbol": "TARGET",
                            "contracts": [
                                {
                                    "chain": "bsc",
                                    "address": contract,
                                    "log_error_count": 0,
                                    "operator_attribution_state": (
                                        "owner_renounced"
                                    ),
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
                            "symbol": "TARGET",
                            "chain": "bsc",
                            "token": {"address": contract},
                            "status": "opened",
                            "opening_cohort_coverage_complete": True,
                            "opening_liquidity_coverage_complete": True,
                            "opening_buyer_scope_complete": True,
                            "rows": [],
                        }
                    ]
                },
            )
            write(
                "output/alpha_price_momentum_watch/latest.json",
                {
                    "events": [
                        {
                            "symbol": "TARGET",
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
                            "symbol": "TARGET",
                            "chain": "bsc",
                            "address": contract,
                            "log_error_count": 0,
                            "truncated": False,
                            "incremental_catchup": {
                                "applicable": False,
                            },
                        }
                    ]
                },
            )
            full_path = write(
                "output/alpha_intraday_flow_watch/latest.json",
                {
                    "events": [
                        {
                            "symbol": "TARGET",
                            "chain": "bsc",
                            "token": {"address": contract},
                            "status": "scanned",
                            "transfer_coverage": {
                                "state": "requested_window_complete",
                                "complete": True,
                            },
                            "analysis": {"scan_limited": False},
                        }
                    ]
                },
            )
            required_path = write(
                (
                    "output/alpha_intraday_flow_watch/"
                    "required_only_latest.json"
                ),
                {"events": []},
            )
            os.utime(full_path, (100, 100))
            os.utime(required_path, (200, 200))

            issues = alpha_coverage_issues(root, current=current)

        self.assertTrue(
            any(
                row["detail"]
                == "TARGET intraday output does not match official contract"
                for row in issues
            ),
            issues,
        )

    def test_health_warns_when_cex_gas_scan_is_time_limited(self) -> None:
        from scripts.runtime_health_watch import output_row_coverage_warning

        detail = output_row_coverage_warning(
            "intraday",
            {
                "status": "scanned",
                "analysis": {
                    "scan_limited": False,
                    "cex_gas_priming_scan_limited": True,
                },
            },
        )

        self.assertEqual(
            detail,
            "intraday CEX gas-priming scan time-limited; transfer risk retained",
        )

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
        self.assertEqual(
            output_row_coverage_issue("intraday", row),
            "intraday receipt coverage limited",
        )
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
            [dict(quiet_analysis), dict(quiet_analysis), quiet_analysis]
        )
        tx_hash = "0x" + "3" * 64
        other_tx_hash = "0x" + "4" * 64
        transfer_rows = [
            {
                "token": event["token"]["address"],
                "from": "0x" + "5" * 40,
                "to": "0x" + "6" * 40,
                "amount": intraday.Decimal("100"),
                "block": 150,
                "transaction_index": 1,
                "log_index": 0,
                "tx": tx_hash,
            },
            {
                "token": event["token"]["address"],
                "from": "0x" + "7" * 40,
                "to": "0x" + "8" * 40,
                "amount": intraday.Decimal("50"),
                "block": 151,
                "transaction_index": 1,
                "log_index": 1,
                "tx": other_tx_hash,
            },
        ]
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS": "0",
                    "ALPHA_INTRADAY_MAX_RECEIPTS": "1",
                },
            ),
            mock.patch.object(
                intraday,
                "token_transfer_logs_with_coverage",
                return_value=(
                    transfer_rows,
                    {
                        "state": "requested_window_complete",
                        "complete": True,
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

        self.assertFalse(capped["analysis"]["scan_limited"])
        self.assertTrue(
            capped["analysis"]["optional_market_scan_limited"]
        )
        self.assertEqual(capped["analysis"]["selected_receipts"], 1)
        self.assertEqual(capped["analysis"]["sampled_receipts"], 1)
        self.assertEqual(capped["analysis"]["receipt_errors"], 0)
        self.assertEqual(
            capped["analysis"]["receipt_coverage"]["reasons"],
            [],
        )
        self.assertEqual(
            capped["analysis"]["receipt_coverage"][
                "optional_market_sample"
            ]["reasons"],
            ["candidate_selection_limit"],
        )
        self.assertEqual(intraday.event_alert_keys(capped), [])
        self.assertFalse(missing["analysis"]["scan_limited"])
        self.assertTrue(
            missing["analysis"]["optional_market_scan_limited"]
        )
        self.assertEqual(missing["analysis"]["sampled_receipts"], 0)
        self.assertEqual(missing["analysis"]["receipt_errors"], 1)
        self.assertEqual(
            missing["analysis"]["receipt_coverage"]["reasons"],
            [],
        )
        self.assertEqual(
            missing["analysis"]["receipt_coverage"][
                "optional_market_sample"
            ]["reasons"],
            ["candidate_selection_limit", "receipt_error"],
        )
        self.assertEqual(intraday.event_alert_keys(missing), [])
        self.assertFalse(failed_transaction["analysis"]["scan_limited"])
        self.assertTrue(
            failed_transaction["analysis"]["optional_market_scan_limited"]
        )
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
            },
            {
                "token": token,
                "from": "0x" + "6" * 40,
                "to": "0x" + "7" * 40,
                "amount": intraday.Decimal("100"),
                "block": 151,
                "log_index": 1,
                "tx": "0x" + "8" * 64,
            },
        ]
        transfer_coverage = {
            "state": "requested_window_complete",
            "complete": True,
            "requested_from_block": 100,
            "requested_to_block": 200,
            "covered_through_block": 200,
            "max_logs": 100,
            "returned_log_count": 2,
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
                {
                    "ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS": "0",
                    "ALPHA_INTRADAY_MAX_RECEIPTS": "0",
                },
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

        self.assertFalse(result["analysis"]["scan_limited"])
        self.assertTrue(
            result["analysis"]["optional_market_scan_limited"]
        )
        self.assertEqual(
            result["analysis"]["alert_policy"],
            (
                "required_receipt_gate_complete_"
                "optional_market_sample_report_only"
            ),
        )
        self.assertEqual(result["configured_cex_inflow_aggregate_rows"], [])
        self.assertEqual(result["analysis"]["cex_token_deposit"], "120000")
        self.assertTrue(intraday.event_alert_keys(result))

    def test_intraday_receipts_require_verified_opening_buyers_only(
        self,
    ) -> None:
        import scripts.alpha_intraday_flow_watch as intraday

        token = "0x" + "1" * 40
        cohort_recipient = "0x" + "2" * 40
        verified_buyer = "0x" + "3" * 40
        payload = {
            "events": [
                {
                    "symbol": "TEST",
                    "chain": "bsc",
                    "token": {"address": token},
                    "opening_block": 100,
                    "opening_buyer_scope_complete": True,
                    "opening_buyer_scope_addresses": [
                        cohort_recipient,
                    ],
                    "rows": [
                        {
                            "buyer": verified_buyer,
                            "token_bought": "100",
                        }
                    ],
                }
            ]
        }

        full_scope = intraday.opening_buyer_addresses_from_context(
            payload,
            "TEST",
            "bsc",
            token,
            100,
        )
        verified_scope = (
            intraday.opening_buyer_addresses_from_context(
                payload,
                "TEST",
                "bsc",
                token,
                100,
                verified_only=True,
            )
        )

        self.assertEqual(
            full_scope,
            sorted([cohort_recipient, verified_buyer]),
        )
        self.assertEqual(verified_scope, [verified_buyer])
        receipt_scope = intraday.required_receipt_address_scope(
            {
                "opening_buyer_addresses": full_scope,
                "opening_verified_buyer_addresses": verified_scope,
            },
            {},
        )
        self.assertNotIn(cohort_recipient, receipt_scope)
        self.assertEqual(
            receipt_scope[verified_buyer],
            {"opening_buyer"},
        )

        outsider = "0x" + "4" * 40
        incoming_tx = "0x" + "5" * 64
        outgoing_tx = "0x" + "6" * 64
        verified_tx = "0x" + "7" * 64
        verified_outgoing_tx = "0x" + "8" * 64
        required_txs, required_scope = (
            intraday.required_receipt_transactions(
                {
                    "symbol": "TEST",
                    "chain": "bsc",
                    "token": {"address": token},
                    "opening_block": 100,
                    "opening_buyer_addresses": full_scope,
                    "opening_verified_buyer_addresses": verified_scope,
                },
                [
                    {
                        "from": outsider,
                        "to": cohort_recipient,
                        "tx": incoming_tx,
                        "block": 101,
                        "transaction_index": 0,
                        "log_index": 0,
                    },
                    {
                        "from": cohort_recipient,
                        "to": outsider,
                        "tx": outgoing_tx,
                        "block": 102,
                        "transaction_index": 0,
                        "log_index": 0,
                    },
                    {
                        "from": outsider,
                        "to": verified_buyer,
                        "tx": verified_tx,
                        "block": 103,
                        "transaction_index": 0,
                        "log_index": 0,
                    },
                    {
                        "from": verified_buyer,
                        "to": outsider,
                        "tx": verified_outgoing_tx,
                        "block": 104,
                        "transaction_index": 0,
                        "log_index": 0,
                    },
                ],
                {},
            )
        )
        self.assertNotIn(incoming_tx, required_txs)
        self.assertIn(outgoing_tx, required_txs)
        self.assertIn(verified_tx, required_txs)
        self.assertIn(verified_outgoing_tx, required_txs)
        self.assertEqual(
            required_scope["tx_counts_by_category"][
                "opening_cohort_outflow"
            ],
            1,
        )
        self.assertEqual(
            required_scope["tx_counts_by_category"][
                "opening_buyer"
            ],
            2,
        )

    def test_required_opening_cohort_outflow_receipt_gap_blocks_signal(
        self,
    ) -> None:
        import scripts.alpha_intraday_flow_watch as intraday
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
        )

        token = "0x" + "1" * 40
        buyer = "0x" + "2" * 40
        recipient = "0x" + "3" * 40
        tx_hash = "0x" + "4" * 64
        event = {
            "symbol": "AEON",
            "chain": "bsc",
            "token": {"address": token, "decimals": 18},
            "quote": {
                "address": "0x" + "5" * 40,
                "symbol": "USDT",
                "decimals": 18,
            },
            "latest_block": 200,
            "opening_block": 100,
            "opening_buyer_addresses": [buyer],
            "opening_verified_buyer_addresses": [],
        }
        transfer_rows = [
            {
                "token": token,
                "from": buyer,
                "to": recipient,
                "amount": intraday.Decimal("100"),
                "block": 150,
                "transaction_index": 1,
                "log_index": 0,
                "tx": tx_hash,
            }
        ]
        coverage = {
            "state": "requested_window_complete",
            "complete": True,
            "returned_log_count": 1,
        }
        quiet = {
            "direction": "观察",
            "trade_signal": "fixture",
            "spot_action": "观察",
            "perp_action": "观察",
            "net_buy_quote": "0",
            "net_sell_quote": "0",
            "cex_quote_estimate": "0",
            "cex_token_deposit": "0",
            "cex_deposit_count": 0,
            "cex_gas_priming_count": 0,
        }

        def analysis_for_rows(
            _event: dict[str, object],
            rows: list[dict[str, object]],
            *_args: object,
        ) -> dict[str, object]:
            sell_quote = "30000" if rows else "0"
            return {
                **quiet,
                "direction": "大额卖出" if rows else "观察",
                "trade_signal": (
                    "开盘地址确认卖出" if rows else "fixture"
                ),
                "net_sell_quote": sell_quote,
            }

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_INTRADAY_SCAN_TIMEOUT_SECONDS": "0"},
            ),
            mock.patch.object(
                intraday,
                "token_transfer_logs_with_coverage",
                return_value=(transfer_rows, coverage),
            ),
            mock.patch.object(
                intraday,
                "aggregate_candidate_txs",
                return_value=([], 1, 1),
            ),
            mock.patch.object(
                intraday,
                "runtime_cex_deposit_candidates",
                return_value={},
            ),
            mock.patch.object(
                intraday,
                "collect_report_only_cex_micro_gas_samples",
                return_value={},
            ),
            mock.patch.object(
                intraday,
                "cex_withdrawal_cluster",
                return_value={},
            ),
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
                intraday,
                "summarize_flow_tx",
                return_value={
                    "seller": buyer,
                    "sold_token": "100",
                    "got_quote": "30000",
                },
            ),
            mock.patch.object(
                intraday,
                "analyze_rows",
                side_effect=analysis_for_rows,
            ),
        ):
            with mock.patch.object(
                intraday.opening,
                "quick_rpc_call",
                return_value=None,
            ):
                missing = intraday.scan_event(event)
            with mock.patch.object(
                intraday.opening,
                "quick_rpc_call",
                return_value={"status": "0x0", "logs": []},
            ):
                complete = intraday.scan_event(event)
            with mock.patch.object(
                intraday.opening,
                "quick_rpc_call",
                return_value={"status": "0x1", "logs": []},
            ):
                alerted = intraday.scan_event(event)

        self.assertTrue(
            missing["analysis"]["scan_limited"],
            missing["analysis"]["receipt_coverage"],
        )
        self.assertEqual(intraday.event_alert_keys(missing), [])
        self.assertEqual(
            output_row_coverage_issue("intraday", missing),
            "intraday receipt coverage limited",
        )
        self.assertEqual(
            missing["analysis"]["receipt_coverage"]["reasons"],
            ["receipt_error"],
        )
        self.assertEqual(
            missing["analysis"]["receipt_coverage"][
                "required_tx_counts_by_category"
            ]["opening_cohort_outflow"],
            1,
        )
        self.assertFalse(complete["analysis"]["scan_limited"])
        self.assertTrue(
            complete["analysis"]["receipt_coverage"]["complete"]
        )
        self.assertFalse(alerted["analysis"]["scan_limited"])
        self.assertTrue(intraday.event_alert_keys(alerted))

    def test_health_requires_intraday_to_import_opening_buyers(self) -> None:
        from scripts.runtime_health_watch import (
            intraday_opening_buyer_scope_issue,
        )

        contract = "0x" + "1" * 40
        buyer = "0x" + "2" * 40
        excluded = "0x" + "3" * 40
        scope_buyer = "0x" + "4" * 40
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opening.json"
            path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "chain": "bsc",
                                "token": {"address": contract},
                                "opening_buyer_scope_addresses": [
                                    scope_buyer
                                ],
                                "rows": [
                                    {
                                        "buyer": buyer,
                                        "token_bought": "100",
                                    },
                                    {
                                        "buyer": excluded,
                                        "token_bought": "100",
                                        "buyer_exclusion_reason": "fixture",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                intraday_opening_buyer_scope_issue(
                    path,
                    ("bsc", contract),
                    [],
                ),
                "intraday opening-buyer scope missing 2 address(es)",
            )
            self.assertEqual(
                intraday_opening_buyer_scope_issue(
                    path,
                    ("bsc", contract),
                    [
                        {
                            "opening_buyer_addresses": [
                                buyer,
                                scope_buyer,
                            ]
                        }
                    ],
                ),
                "",
            )

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
                    "from_utc8": "2026-07-28 00:45",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }
        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                27,
                17,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            keys = [
                key
                for key, _legacy in price.event_alert_key_pairs(event)
            ]
        self.assertTrue(any(key.startswith("alpha_peak_drawdown|AEON|") for key in keys))

    def test_peak_drawdown_alerts_are_scoped_to_an_hour(self) -> None:
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
                        "from_utc8": (
                            datetime.strptime(
                                value,
                                "%Y-%m-%d %H:%M",
                            )
                            - timedelta(minutes=15)
                        ).strftime("%Y-%m-%d %H:%M"),
                        "to_utc8": value,
                    },
                },
            }

        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                27,
                17,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            first = price.event_alert_keys(
                event_at("2026-07-28 01:00")
            )[0]
        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                28,
                17,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            second = price.event_alert_keys(
                event_at("2026-07-29 01:00")
            )[0]
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
                    "from_utc8": "2026-07-28 00:45",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }

        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                27,
                17,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            text = price.telegram_text(
                {
                    "events": [event],
                    "alert_count": 1,
                    "new_alert_count": 1,
                    "_telegram_new_alert_keys": (
                        price.event_alert_keys(event)
                    ),
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
                    "from_utc8": "2026-07-28 00:45",
                    "to_utc8": "2026-07-28 01:00",
                },
            },
        }

        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                27,
                17,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            signature = price.push_signature(
                {"events": quiet + [aeon]}
            )
        self.assertIn("AEON", signature)

    def test_late_first_observation_does_not_emit_historical_peak_alert(
        self,
    ) -> None:
        import scripts.alpha_price_momentum_watch as price

        event = {
            "symbol": "LATE",
            "analysis": {
                "window_15m": {
                    "quote_volume": "0",
                    "to_utc8": "2026-07-30 16:00",
                },
                "window_backfill": {
                    "high": "1",
                    "close": "0.5",
                    "peak_drawdown_pct": "50",
                    "from_utc8": "2026-07-30 14:00",
                    "to_utc8": "2026-07-30 16:00",
                },
                "previous_peak_drawdown_pct": None,
            },
        }
        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                30,
                8,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            self.assertFalse(
                any(
                    key.startswith("alpha_peak_drawdown|")
                    for key in price.event_alert_keys(event)
                )
            )
            event["analysis"]["previous_peak_drawdown_pct"] = "44"
            self.assertTrue(
                any(
                    key.startswith("alpha_peak_drawdown|")
                    for key in price.event_alert_keys(event)
                )
            )

    def test_old_market_window_cannot_emit_price_alerts(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        event = {
            "symbol": "STALE",
            "analysis": {
                "window_15m": {
                    "high_pct": "0",
                    "low_pct": "-25",
                    "close_pct": "-20",
                    "quote_volume": "1000",
                    "from_utc8": "2026-07-20 15:45",
                    "to_utc8": "2026-07-20 16:00",
                },
                "window_backfill": {
                    "high": "1",
                    "close": "0.5",
                    "peak_drawdown_pct": "50",
                    "from_utc8": "2026-07-20 15:45",
                    "to_utc8": "2026-07-20 16:00",
                },
            },
        }
        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                30,
                8,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            self.assertEqual(price.event_alert_keys(event), [])

    def test_price_telegram_only_displays_new_trigger_scope(self) -> None:
        import scripts.alpha_price_momentum_watch as price

        def event(symbol: str, close: str) -> dict[str, object]:
            return {
                "symbol": symbol,
                "priority": "P1_MONITOR",
                "analysis": {
                    "direction": "快速下跌",
                    "spot_action": "降风险",
                    "venue": {"venue_class": "ALPHA_DOMINANT"},
                    "window_15m": {
                        "from_utc8": "2026-07-30 15:45",
                        "to_utc8": "2026-07-30 16:00",
                        "high_pct": "0",
                        "low_pct": "-20",
                        "close_pct": close,
                        "quote_volume": "1000",
                    },
                    "window_backfill": {},
                },
            }

        mars = event("MARSCOIN", "-20")
        aeon = event("AEON", "-15")
        with mock.patch.object(
            price,
            "now_utc",
            return_value=datetime(
                2026,
                7,
                30,
                8,
                5,
                tzinfo=timezone.utc,
            ),
        ):
            mars_key = next(
                key
                for key in price.event_alert_keys(mars)
                if key.startswith("alpha_extreme_drop|")
            )
            text = price.telegram_text(
                {
                    "events": [mars, aeon],
                    "_telegram_new_alert_keys": [mars_key],
                }
            )
        self.assertIn("MARSCOIN", text)
        self.assertNotIn("AEON", text)
        self.assertIn("新增1｜触发1", text)
        self.assertIn("15:45-16:00", text)

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
                    "ALPHA_HOLDER_FINALITY_BLOCKS": "2",
                    "ALPHA_HOLDER_LOG_CHUNK_BLOCKS": "2",
                    "ALPHA_HOLDER_MAX_LOGS_PER_TOKEN": "100",
                },
            ),
            mock.patch.object(holder, "latest_block", return_value=106),
            mock.patch.object(holder, "rpc_call", side_effect=fetch),
            mock.patch.object(holder, "token_total_supply_raw", return_value=1000),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={"source": "none", "status": "not_configured"},
            ),
            mock.patch.object(
                holder,
                "build_token_liquidity_retention",
                wraps=holder.build_token_liquidity_retention,
            ) as liquidity_builder,
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
        self.assertEqual(result["raw_latest_block"], 106)
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
        self.assertEqual(liquidity_builder.call_args.kwargs["tip"], 106)

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

    def test_fresh_holder_bootstrap_shrinks_only_after_truncation(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _token: str,
            from_block: int,
            to_block: int,
        ) -> tuple[list[dict[str, object]], list[str], bool]:
            calls.append((from_block, to_block))
            if to_block - from_block + 1 > 100:
                return [], [], True
            return [
                {
                    "blockNumber": hex(from_block),
                    "logIndex": "0x0",
                }
            ], [], False

        with (
            mock.patch.object(holder, "transfer_logs", side_effect=fetch),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_BOOTSTRAP_MAX_BLOCKS": "240",
                    "ALPHA_HOLDER_BOOTSTRAP_MIN_BLOCKS": "16",
                    "ALPHA_HOLDER_BOOTSTRAP_MAX_ATTEMPTS": "7",
                },
            ),
        ):
            logs, errors, truncated, selected_from, evidence = (
                holder.bounded_bootstrap_transfer_logs(
                    "bsc",
                    "0x" + "1" * 40,
                    requested_from_block=1,
                    to_block=400,
                )
            )

        self.assertEqual(calls, [(161, 400), (281, 400), (341, 400)])
        self.assertEqual(selected_from, 341)
        self.assertEqual(len(logs), 1)
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertTrue(evidence["complete_selected_window"])
        self.assertEqual(evidence["attempt_count"], 3)

    def test_incremental_holder_catchup_advances_a_complete_prefix(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _token: str,
            from_block: int,
            to_block: int,
        ) -> tuple[list[dict[str, object]], list[str], bool]:
            calls.append((from_block, to_block))
            if to_block - from_block + 1 > 100:
                return [], [], True
            return [
                {
                    "blockNumber": hex(from_block),
                    "logIndex": "0x0",
                }
            ], [], False

        with (
            mock.patch.object(holder, "transfer_logs", side_effect=fetch),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_CATCHUP_MAX_BLOCKS": "400",
                    "ALPHA_HOLDER_CATCHUP_MIN_BLOCKS": "16",
                    "ALPHA_HOLDER_CATCHUP_MAX_ATTEMPTS": "7",
                },
            ),
        ):
            logs, errors, truncated, selected_to, evidence = (
                holder.bounded_incremental_transfer_logs(
                    "bsc",
                    "0x" + "1" * 40,
                    from_block=101,
                    requested_to_block=500,
                )
            )

        self.assertEqual(calls, [(101, 500), (101, 300), (101, 200)])
        self.assertEqual(selected_to, 200)
        self.assertEqual(len(logs), 1)
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertTrue(evidence["applicable"])
        self.assertTrue(evidence["active"])
        self.assertTrue(evidence["complete_selected_window"])
        self.assertFalse(evidence["complete_requested_window"])

    def test_targeted_retention_logs_use_indexed_topics_and_dedupe(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        actor = "0x" + "2" * 40
        cex = "0x" + "3" * 40
        row = {
            "address": token,
            "blockNumber": hex(105),
            "logIndex": hex(7),
            "transactionHash": "0x" + "a" * 64,
            "topics": [
                holder.TRANSFER_TOPIC,
                holder.topic_address(actor),
                holder.topic_address(cex),
            ],
            "data": "0x" + hex(10**18)[2:].rjust(64, "0"),
        }
        queries: list[dict[str, object]] = []

        def fetch(
            _chain: str,
            method: str,
            params: list[object],
        ) -> list[dict[str, object]]:
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            assert isinstance(query, dict)
            queries.append(query)
            return [dict(row)]

        with mock.patch.object(
            holder,
            "rpc_call",
            side_effect=fetch,
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_transfer_logs(
                    "bsc",
                    token,
                    101,
                    110,
                    {
                        actor: {
                            "kinds": {"opening_buyer"},
                            "roles": {"opening_buyer"},
                            "sources": {"opening"},
                        }
                    },
                    {
                        cex: {
                            "kind": "cex",
                            "role": "cex_deposit",
                            "source": "fixture",
                        }
                    },
                )
            )

        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(logs, [row])
        self.assertEqual(len(queries), 2)
        self.assertEqual(
            queries[0]["topics"],
            [
                holder.TRANSFER_TOPIC,
                holder.topic_address(actor),
            ],
        )
        self.assertEqual(
            queries[1]["topics"],
            [
                holder.TRANSFER_TOPIC,
                None,
                holder.topic_address(cex),
            ],
        )
        self.assertTrue(metadata["query_scope_complete"])
        self.assertEqual(metadata["query_count"], 2)

    def test_targeted_retention_batches_dense_opening_scope(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        actors = {
            "0x" + f"{index:040x}": {
                "kinds": {"opening_cohort_recipient"},
                "roles": {"opening_cohort_recipient"},
                "sources": {"opening"},
            }
            for index in range(1, 515)
        }
        cex_addresses = {
            "0x" + f"{index:040x}": {
                "kind": "cex",
                "role": "cex_deposit",
                "source": "fixture",
            }
            for index in range(1001, 1003)
        }
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                holder,
                "rpc_call",
                return_value=[],
            ) as fetch,
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_transfer_logs(
                    "bsc",
                    "0x" + "f" * 40,
                    101,
                    110,
                    actors,
                    cex_addresses,
                )
            )

        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(fetch.call_count, 6)
        self.assertEqual(metadata["topic_batch_size"], 128)
        self.assertEqual(metadata["scope_batch_count"], 6)
        self.assertEqual(metadata["query_count"], 6)
        self.assertEqual(metadata["expected_query_count"], 6)
        self.assertTrue(metadata["query_scope_complete"])

    def test_holder_rpc_budget_is_bounded_and_forwarded(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        initial_deadline = holder.HOLDER_DEADLINE_AT
        self.addCleanup(
            setattr,
            holder,
            "HOLDER_DEADLINE_AT",
            initial_deadline,
        )
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_WATCHER_BUDGET_SECONDS": "999"},
            ),
            mock.patch.object(
                holder.time,
                "monotonic",
                return_value=100.0,
            ),
        ):
            holder.configure_holder_deadline()

        self.assertEqual(holder.HOLDER_DEADLINE_AT, 320.0)
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value="0x1",
        ) as rpc:
            result = holder.holder_rpc_call(
                "bsc",
                "eth_blockNumber",
                [],
            )

        self.assertEqual(result, "0x1")
        rpc.assert_called_once_with(
            "bsc",
            "eth_blockNumber",
            [],
            deadline=320.0,
        )

    def test_holder_snapshot_restores_outer_deadline(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        initial_deadline = holder.HOLDER_DEADLINE_AT
        self.addCleanup(
            setattr,
            holder,
            "HOLDER_DEADLINE_AT",
            initial_deadline,
        )
        holder.HOLDER_DEADLINE_AT = 50.0

        def configure() -> None:
            holder.HOLDER_DEADLINE_AT = 100.0

        observed: list[float | None] = []
        with (
            mock.patch.object(
                holder,
                "configure_holder_deadline",
                side_effect=configure,
            ),
            mock.patch.object(
                holder,
                "build_snapshot_within_deadline",
                side_effect=lambda: observed.append(
                    holder.HOLDER_DEADLINE_AT
                )
                or {},
            ),
        ):
            result = holder.build_snapshot()

        self.assertEqual(result, {})
        self.assertEqual(observed, [100.0])
        self.assertEqual(holder.HOLDER_DEADLINE_AT, 50.0)

    def test_targeted_retention_logs_reject_cross_scope_rows(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        actor = "0x" + "2" * 40
        wrong_sender = "0x" + "3" * 40
        row = {
            "address": token,
            "blockNumber": hex(105),
            "logIndex": hex(1),
            "transactionHash": "0x" + "a" * 64,
            "topics": [
                holder.TRANSFER_TOPIC,
                holder.topic_address(wrong_sender),
                holder.topic_address("0x" + "4" * 40),
            ],
            "data": "0x" + hex(10**18)[2:].rjust(64, "0"),
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[row],
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_transfer_logs(
                    "bsc",
                    token,
                    101,
                    110,
                    {
                        actor: {
                            "kinds": {"opening_buyer"},
                            "roles": {"opening_buyer"},
                            "sources": {"opening"},
                        }
                    },
                    {},
                )
            )

        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)
        self.assertFalse(metadata["query_scope_complete"])

    def test_targeted_retention_logs_reject_malformed_rpc_identity(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        actor = "0x" + "2" * 40
        base_row = {
            "address": token,
            "blockNumber": hex(105),
            "logIndex": hex(1),
            "transactionHash": "0x" + "a" * 64,
            "topics": [
                holder.TRANSFER_TOPIC,
                holder.topic_address(actor),
                holder.topic_address("0x" + "4" * 40),
            ],
            "data": "0x" + hex(10**18)[2:].rjust(64, "0"),
        }
        malformed_rows = {
            "removed_null": {**base_row, "removed": None},
            "removed_string": {**base_row, "removed": "false"},
            "removed_numeric": {**base_row, "removed": 0},
            "missing_log_index": {
                key: value
                for key, value in base_row.items()
                if key != "logIndex"
            },
            "noncanonical_log_index": {
                **base_row,
                "logIndex": "0x01",
            },
            "missing_block_number": {
                key: value
                for key, value in base_row.items()
                if key != "blockNumber"
            },
        }

        for label, malformed in malformed_rows.items():
            with (
                self.subTest(label=label),
                mock.patch.object(
                    holder,
                    "rpc_call",
                    return_value=[malformed],
                ),
            ):
                logs, errors, truncated, metadata = (
                    holder.targeted_retention_transfer_logs(
                        "bsc",
                        token,
                        101,
                        110,
                        {
                            actor: {
                                "kinds": {"opening_buyer"},
                                "roles": {"opening_buyer"},
                                "sources": {"opening"},
                            }
                        },
                        {},
                    )
                )

            self.assertEqual(logs, [])
            self.assertTrue(errors)
            self.assertFalse(truncated)
            self.assertFalse(metadata["query_scope_complete"])

    def test_bounded_targeted_retention_advances_complete_prefix(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _token: str,
            from_block: int,
            to_block: int,
            _actors: dict[str, object],
            _cex: dict[str, object],
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            dict[str, object],
        ]:
            calls.append((from_block, to_block))
            truncated = to_block - from_block + 1 > 100
            return (
                [],
                [],
                truncated,
                {
                    "query_scope_complete": not truncated,
                    "query_count": 1,
                    "scope_kind_count": 1,
                    "scope_batch_count": 1,
                },
            )

        with (
            mock.patch.object(
                holder,
                "targeted_retention_transfer_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_CATCHUP_MAX_BLOCKS": "400",
                    "ALPHA_RETENTION_CATCHUP_MIN_BLOCKS": "16",
                    "ALPHA_RETENTION_CATCHUP_MAX_ATTEMPTS": "7",
                },
            ),
        ):
            (
                logs,
                errors,
                truncated,
                selected_to,
                metadata,
            ) = holder.bounded_targeted_retention_logs(
                "bsc",
                "0x" + "1" * 40,
                101,
                500,
                {},
                {"0x" + "2" * 40: {}},
            )

        self.assertEqual(
            calls,
            [(101, 500), (101, 300), (101, 200)],
        )
        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(selected_to, 200)
        self.assertTrue(metadata["active"])
        self.assertTrue(metadata["complete_selected_window"])
        self.assertFalse(metadata["complete_requested_window"])

    def test_retention_events_split_historical_catchup_from_live_tail(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        actor = "0x" + "2" * 40
        recipient = "0x" + "3" * 40

        def row(block: int, index: int) -> dict[str, object]:
            return {
                "blockNumber": hex(block),
                "logIndex": hex(index),
                "transactionHash": "0x" + f"{index:x}" * 64,
                "topics": [
                    holder.TRANSFER_TOPIC,
                    holder.topic_address(actor),
                    holder.topic_address(recipient),
                ],
                "data": hex(10**18),
            }

        events, matched = holder.retention_transfer_events(
            [row(100, 1), row(200, 2)],
            18,
            10**24,
            {
                actor: {
                    "kinds": {"opening_buyer"},
                    "roles": {"opening_buyer"},
                    "sources": {"opening"},
                }
            },
            {},
            {},
            alert_from_block=150,
        )

        self.assertEqual(matched, 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0]["historical_catchup"])
        self.assertFalse(events[0]["alert_eligible"])
        self.assertFalse(events[1]["historical_catchup"])
        self.assertTrue(events[1]["alert_eligible"])

    def test_opening_retention_scope_keeps_complete_recipient_superset(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        verified_buyer = "0x" + "2" * 40
        cohort_recipient = "0x" + "3" * 40
        actors, evidence, metadata = (
            holder.opening_retention_scope(
                {
                    "events": [
                        {
                            "symbol": "TEST",
                            "chain": "bsc",
                            "token": {"address": token},
                            "opening_buyer_scope_complete": True,
                            "opening_buyer_scope_addresses": [
                                verified_buyer,
                                cohort_recipient,
                            ],
                            "rows": [
                                {
                                    "buyer": verified_buyer,
                                    "token_bought": "100",
                                    "buyer_trace": {},
                                }
                            ],
                        }
                    ]
                },
                "TEST",
                "bsc",
                token,
            )
        )

        self.assertEqual(evidence, {})
        self.assertTrue(metadata["complete"])
        self.assertIn(
            "opening_buyer",
            actors[verified_buyer]["kinds"],
        )
        self.assertIn(
            "opening_cohort_recipient",
            actors[cohort_recipient]["kinds"],
        )
        events, _ = holder.retention_transfer_events(
            [
                {
                    "blockNumber": hex(200),
                    "logIndex": hex(1),
                    "transactionHash": "0x" + "a" * 64,
                    "topics": [
                        holder.TRANSFER_TOPIC,
                        holder.topic_address(cohort_recipient),
                        holder.topic_address("0x" + "4" * 40),
                    ],
                    "data": hex(10**18),
                }
            ],
            18,
            10**24,
            actors,
            {},
            evidence,
        )
        self.assertEqual(
            events[0]["type"],
            "opening_cohort_recipient_outflow_transfer_risk",
        )
        self.assertEqual(
            events[0]["evidence_level"],
            "opening_recipient_transfer_only",
        )
        persisted_project = {
            "0x" + "5" * 40: {
                "kinds": {"verified_project"},
                "roles": {"market_maker"},
                "sources": {"project"},
            }
        }
        resolved_actors, _, _, current_incomplete = (
            holder.retention_evidence_scope(
                {"watch_addresses": []},
                "TEST",
                "bsc",
                token,
                {
                    "opening": {
                        "events": [
                            {
                                "symbol": "TEST",
                                "chain": "bsc",
                                "token": {"address": token},
                                "opening_buyer_scope_complete": False,
                                "rows": [],
                            }
                        ]
                    },
                    "project": {"projects": []},
                },
                persisted_actors=persisted_project,
                persisted_opening_scope_complete=True,
            )
        )
        self.assertFalse(
            current_incomplete["opening_scope_complete"]
        )
        self.assertNotIn(
            "0x" + "5" * 40,
            resolved_actors,
        )

    def test_unreliable_holder_uses_targeted_retention_only(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            retention_flow_coverage_issue,
        )

        token = "0x" + "7" * 40
        key = f"bsc:{token}"
        fixed_now = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        opening = fixed_now - timedelta(days=4)
        config_item = {
            "symbol": "TEST",
            "name": "TEST",
            "priority": "P1_MONITOR",
            "active_monitoring": True,
            "contracts": [
                {"chain": "bsc", "address": token},
            ],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": opening
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }
        state = {
            "tokens": {
                key: {
                    "symbol": "TEST",
                    "chain": "bsc",
                    "address": token,
                    "decimals": 18,
                    "basis_from_block": 1,
                    "latest_block": 100,
                    "last_metrics": {},
                    "balances_raw": {},
                    "holder_baseline_status": (
                        holder.BOUNDED_BOOTSTRAP_UNRELIABLE
                    ),
                    "retention_flow": {
                        "latest_block": 100,
                    },
                }
            }
        }
        targeted_metadata = {
            "coverage_mode": "targeted_indexed_topics",
            "query_scope_complete": True,
            "query_count": 2,
            "tracked_actor_count": 1,
            "cex_address_count": 1,
            "scope_kind_count": 2,
            "scope_batch_count": 2,
            "query_chunk_count": 1,
            "expected_query_count": 2,
            "applicable": True,
            "active": False,
            "requested_to_block": 500,
            "selected_to_block": 500,
            "attempt_count": 1,
            "complete_selected_window": True,
            "complete_requested_window": True,
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "now_utc", return_value=fixed_now),
            mock.patch.object(
                holder,
                "latest_block",
                side_effect=[500, 510],
            ),
            mock.patch.object(
                holder,
                "bounded_incremental_transfer_logs",
            ) as full_scan,
            mock.patch.object(
                holder,
                "retention_evidence_scope",
                return_value=(
                    {
                        "0x" + "2" * 40: {
                            "kinds": {"opening_buyer"},
                            "roles": {"opening_buyer"},
                            "sources": {"opening"},
                        }
                    },
                    {
                        "0x" + "3" * 40: {
                            "kind": "cex",
                            "role": "cex_deposit",
                            "source": "fixture",
                        }
                    },
                    {},
                    {
                        "matching_event_count": 1,
                        "opening_scope_complete": True,
                        "opening_actor_count": 1,
                        "opening_actor_scope_hash": "b" * 64,
                        "scope_state_schema_version": 1,
                        "scope_hash": "a" * 64,
                    },
                ),
            ),
            mock.patch.object(
                holder,
                "bounded_targeted_retention_logs",
                side_effect=[
                    (
                        [],
                        [],
                        False,
                        500,
                        targeted_metadata,
                    ),
                    (
                        [],
                        [],
                        False,
                        510,
                        {
                            **targeted_metadata,
                            "requested_to_block": 510,
                            "selected_to_block": 510,
                        },
                    ),
                ],
            ) as targeted_scan,
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
        ):
            result = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                {
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )
            second = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                {
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )

        full_scan.assert_not_called()
        self.assertEqual(targeted_scan.call_count, 2)
        self.assertEqual(
            result["holder_scan_status"],
            "skipped_unreliable_baseline",
        )
        self.assertFalse(
            result["incremental_catchup"]["applicable"]
        )
        self.assertEqual(result["latest_block"], 100)
        self.assertEqual(
            result["retention_flow"]["latest_block"],
            500,
        )
        self.assertTrue(result["retention_flow"]["complete"])
        self.assertEqual(
            result["retention_flow"]["coverage_mode"],
            "targeted_indexed_topics",
        )
        self.assertEqual(state["tokens"][key]["latest_block"], 100)
        self.assertEqual(
            state["tokens"][key]["retention_flow"]["latest_block"],
            510,
        )
        self.assertTrue(result["retention_flow"]["scope_rebaseline"])
        self.assertFalse(second["retention_flow"]["scope_rebaseline"])
        self.assertEqual(
            second["retention_flow"]["previous_scope_hash"],
            "a" * 64,
        )
        self.assertEqual(
            state["tokens"][key]["retention_flow"]["scope_hash"],
            "a" * 64,
        )
        self.assertTrue(
            state["tokens"][key]["retention_flow"][
                "opening_scope_complete"
            ]
        )
        event = {
            "type": "cex_inflow_transfer_risk",
            "level": "HIGH",
            "sample_tx": "0x" + "b" * 64,
            "sample_log_index": 1,
            "historical_catchup": False,
            "alert_eligible": True,
        }
        self.assertEqual(
            holder.retention_alert_events(
                {
                    **result,
                    "retention_flow": {
                        **result["retention_flow"],
                        "events": [event],
                    },
                }
            ),
            [],
        )
        self.assertEqual(
            holder.retention_alert_events(
                {
                    **second,
                    "retention_flow": {
                        **second["retention_flow"],
                        "events": [event],
                    },
                }
            ),
            [event],
        )
        self.assertEqual(output_row_coverage_issue("holder", result), "")
        self.assertEqual(retention_flow_coverage_issue(result), "")

    def test_holder_baseline_checkpoint_is_independent_of_retention(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "6" * 40
        key = f"bsc:{token}"
        state: dict[str, object] = {"tokens": {}}
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "latest_block", return_value=1000),
            mock.patch.object(
                holder,
                "transfer_logs",
                return_value=([], [], True),
            ),
            mock.patch.object(
                holder,
                "bounded_bootstrap_transfer_logs",
                return_value=(
                    [],
                    [],
                    False,
                    900,
                    {
                        "active": True,
                        "requested_from_block": 0,
                        "selected_from_block": 900,
                        "attempt_count": 1,
                        "complete_selected_window": True,
                    },
                ),
            ),
            mock.patch.object(
                holder,
                "token_decimals",
                return_value=18,
            ),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "build_retention_flow",
                return_value={
                    "status": "active",
                    "complete": False,
                    "selected_window_complete": False,
                    "events": [],
                },
            ),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
        ):
            result = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )

        self.assertEqual(
            result["holder_baseline_status"],
            holder.BOUNDED_BOOTSTRAP_UNRELIABLE,
        )
        self.assertEqual(state["tokens"][key]["latest_block"], 1000)
        self.assertEqual(
            state["tokens"][key]["holder_baseline_status"],
            holder.BOUNDED_BOOTSTRAP_UNRELIABLE,
        )
        self.assertNotIn(
            "retention_flow",
            state["tokens"][key],
        )

    def test_opening_scope_persists_before_opening(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "6" * 40
        cohort = "0x" + "7" * 40
        key = f"bsc:{token}"
        fixed_now = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        opening = fixed_now + timedelta(days=1)
        config_item = {
            "symbol": "TEST",
            "name": "TEST",
            "priority": "P1_MONITOR",
            "active_monitoring": True,
            "contracts": [
                {"chain": "bsc", "address": token},
            ],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": opening
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }
        state = {
            "tokens": {
                key: {
                    "latest_block": 100,
                    "basis_from_block": 1,
                    "decimals": 18,
                    "last_metrics": {},
                    "balances_raw": {},
                    "holder_baseline_status": (
                        holder.BOUNDED_BOOTSTRAP_UNRELIABLE
                    ),
                }
            }
        }
        opening_context = {
            "opening": {
                "events": [
                    {
                        "symbol": "TEST",
                        "chain": "bsc",
                        "token": {"address": token},
                        "opening_buyer_scope_complete": True,
                        "opening_buyer_scope_addresses": [cohort],
                        "rows": [],
                    }
                ]
            },
            "project": {"projects": []},
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "now_utc", return_value=fixed_now),
            mock.patch.object(holder, "latest_block", return_value=500),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
        ):
            holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                opening_context,
            )

        saved_scope = state["tokens"][key]["retention_flow"]
        self.assertTrue(saved_scope["opening_scope_complete"])
        self.assertEqual(saved_scope["opening_actor_count"], 1)
        self.assertIn(cohort, saved_scope["actor_scope"])
        self.assertNotIn("latest_block", saved_scope)

        catchup_metadata = {
            "coverage_mode": "targeted_indexed_topics",
            "query_scope_complete": True,
            "query_count": 3,
            "scope_kind_count": 2,
            "scope_batch_count": 3,
            "query_chunk_count": 1,
            "expected_query_count": 3,
            "applicable": True,
            "active": False,
            "requested_to_block": 600,
            "selected_to_block": 600,
            "attempt_count": 1,
            "complete_selected_window": True,
            "complete_requested_window": True,
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(
                holder,
                "now_utc",
                return_value=fixed_now + timedelta(days=2),
            ),
            mock.patch.object(holder, "latest_block", return_value=600),
            mock.patch.object(
                holder,
                "bounded_targeted_retention_logs",
                return_value=(
                    [],
                    [],
                    False,
                    600,
                    catchup_metadata,
                ),
            ),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
        ):
            active = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                {
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )

        self.assertTrue(active["retention_flow"]["complete"])
        self.assertTrue(
            active["retention_flow"]["scope_rebaseline"]
        )
        self.assertEqual(
            state["tokens"][key]["retention_flow"]["latest_block"],
            600,
        )

    def test_retention_flow_is_active_during_intraday_window(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        fixed_now = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        opening = fixed_now - timedelta(hours=1)
        item = {
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": opening
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ]
        }

        with mock.patch.object(
            holder,
            "now_utc",
            return_value=fixed_now,
        ):
            window = holder.retention_window(item, "bsc")

        self.assertEqual(window["status"], "active")
        self.assertEqual(
            window["reason"],
            "opening_to_30d_retention",
        )

    def test_incomplete_scope_query_does_not_commit_rebaseline(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "6" * 40
        opening_actor = "0x" + "7" * 40
        project_actor = "0x" + "8" * 40
        key = f"bsc:{token}"
        fixed_now = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        opening = fixed_now - timedelta(days=4)
        persisted_actors = {
            opening_actor: {
                "kinds": {"opening_buyer"},
                "roles": {"opening_buyer"},
                "sources": {"opening"},
            }
        }
        current_actors = {
            **persisted_actors,
            project_actor: {
                "kinds": {"verified_project"},
                "roles": {"market_maker"},
                "sources": {"project"},
            },
        }
        old_scope_hash = "a" * 64
        new_scope_hash = "b" * 64
        state = {
            "tokens": {
                key: {
                    "latest_block": 100,
                    "basis_from_block": 1,
                    "decimals": 18,
                    "last_metrics": {},
                    "balances_raw": {},
                    "holder_baseline_status": (
                        holder.BOUNDED_BOOTSTRAP_UNRELIABLE
                    ),
                    "retention_flow": {
                        "latest_block": 100,
                        "scope_coverage_from_block": 50,
                        "scope_hash": old_scope_hash,
                        "actor_scope": (
                            holder.serialize_retention_actors(
                                persisted_actors
                            )
                        ),
                        "opening_scope_complete": True,
                        "opening_actor_count": 1,
                        "opening_actor_scope_hash": (
                            holder.opening_actor_scope_hash(
                                persisted_actors
                            )
                        ),
                        "scope_state_schema_version": 1,
                    },
                }
            }
        }
        config_item = {
            "symbol": "TEST",
            "name": "TEST",
            "priority": "P1_MONITOR",
            "active_monitoring": True,
            "contracts": [
                {"chain": "bsc", "address": token},
            ],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": opening
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }

        def failed_scan(
            _chain: str,
            _token: str,
            from_block: int,
            requested_to_block: int,
            _actors: dict[str, object],
            _cex_addresses: dict[str, object],
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            int,
            dict[str, object],
        ]:
            return (
                [],
                [],
                False,
                from_block,
                {
                    "coverage_mode": "targeted_indexed_topics",
                    "query_scope_complete": False,
                    "query_count": 1,
                    "scope_kind_count": 2,
                    "scope_batch_count": 2,
                    "query_chunk_count": 1,
                    "expected_query_count": 2,
                    "applicable": True,
                    "active": True,
                    "requested_to_block": requested_to_block,
                    "selected_to_block": from_block,
                    "attempt_count": 1,
                    "complete_selected_window": False,
                    "complete_requested_window": False,
                },
            )

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "now_utc", return_value=fixed_now),
            mock.patch.object(
                holder,
                "latest_block",
                side_effect=[500, 510],
            ),
            mock.patch.object(
                holder,
                "retention_evidence_scope",
                return_value=(
                    current_actors,
                    {
                        "0x" + "9" * 40: {
                            "kind": "cex",
                            "role": "cex_deposit",
                            "source": "fixture",
                        }
                    },
                    {},
                    {
                        "matching_event_count": 1,
                        "opening_scope_complete": True,
                        "opening_actor_count": 1,
                        "opening_actor_scope_hash": (
                            holder.opening_actor_scope_hash(
                                persisted_actors
                            )
                        ),
                        "scope_state_schema_version": 1,
                        "scope_hash": new_scope_hash,
                    },
                ),
            ),
            mock.patch.object(
                holder,
                "bounded_targeted_retention_logs",
                side_effect=failed_scan,
            ) as targeted_scan,
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
        ):
            first = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                {
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )
            second = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": [config_item]},
                state,
                {
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )

        self.assertTrue(first["retention_flow"]["scope_rebaseline"])
        self.assertTrue(second["retention_flow"]["scope_rebaseline"])
        self.assertEqual(targeted_scan.call_count, 2)
        self.assertEqual(
            state["tokens"][key]["retention_flow"]["scope_hash"],
            old_scope_hash,
        )
        self.assertEqual(
            state["tokens"][key]["retention_flow"][
                "scope_coverage_from_block"
            ],
            50,
        )

    def test_health_blocks_holder_while_incremental_catchup_is_pending(
        self,
    ) -> None:
        import scripts.runtime_health_watch as health

        detail = health.output_row_coverage_issue(
            "holder",
            {
                "log_error_count": 0,
                "truncated": False,
                "scan_to_block": 200,
                "target_latest_block": 500,
                "incremental_catchup": {
                    "applicable": True,
                    "active": True,
                    "requested_to_block": 500,
                    "selected_to_block": 200,
                    "complete_selected_window": True,
                    "complete_requested_window": False,
                },
            },
        )

        self.assertEqual(detail, "holder incremental catch-up pending")

    def test_health_rejects_missing_or_contradictory_holder_catchup_metadata(
        self,
    ) -> None:
        import scripts.runtime_health_watch as health

        missing = health.output_row_coverage_issue(
            "holder",
            {"log_error_count": 0, "truncated": False},
        )
        contradictory = health.output_row_coverage_issue(
            "holder",
            {
                "log_error_count": 0,
                "truncated": False,
                "scan_to_block": 200,
                "target_latest_block": 500,
                "incremental_catchup": {
                    "applicable": True,
                    "active": False,
                    "requested_to_block": 500,
                    "selected_to_block": 200,
                    "complete_selected_window": True,
                    "complete_requested_window": False,
                },
            },
        )

        self.assertEqual(
            missing,
            "holder incremental catch-up metadata missing",
        )
        self.assertEqual(
            contradictory,
            "holder incremental catch-up metadata invalid",
        )

    def test_holder_catchup_checkpoint_stops_at_complete_prefix(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "7" * 40
        key = f"bsc:{token}"
        state = {
            "tokens": {
                key: {
                    "symbol": "TEST",
                    "chain": "bsc",
                    "address": token,
                    "decimals": 18,
                    "basis_from_block": 1,
                    "latest_block": 100,
                    "last_metrics": {},
                    "balances_raw": {},
                }
            }
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "latest_block", return_value=500),
            mock.patch.object(
                holder,
                "bounded_incremental_transfer_logs",
                return_value=(
                    [],
                    [],
                    False,
                    200,
                    {
                        "applicable": True,
                        "active": True,
                        "requested_to_block": 500,
                        "selected_to_block": 200,
                        "attempt_count": 1,
                        "complete_selected_window": True,
                        "complete_requested_window": False,
                    },
                ),
            ),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "build_retention_flow",
                return_value={
                    "status": "inactive",
                    "selected_window_complete": True,
                },
            ),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={"source": "none", "status": "not_configured"},
            ),
        ):
            result = holder.build_token_snapshot(
                {
                    "symbol": "TEST",
                    "name": "TEST",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )

        self.assertEqual(result["latest_block"], 200)
        self.assertEqual(result["scan_to_block"], 200)
        self.assertEqual(result["target_latest_block"], 500)
        self.assertEqual(state["tokens"][key]["latest_block"], 200)
        self.assertEqual(
            state["tokens"][key]["retention_flow"]["latest_block"],
            200,
        )
        self.assertEqual(result["signal"]["level"], "INFO")
        self.assertEqual(holder.alert_keys({"projects": [result]}), [])

    def test_holder_catchup_preserves_full_baseline_and_archives_old_events(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "8" * 40
        key = f"bsc:{token}"
        state = {
            "tokens": {
                key: {
                    "symbol": "TEST",
                    "chain": "bsc",
                    "address": token,
                    "decimals": 18,
                    "basis_from_block": 1,
                    "latest_block": 100,
                    "last_metrics": {
                        "raw_top10_pct": "10",
                        "effective_top10_pct": "10",
                        "raw_top10_infra_pct": "0",
                    },
                    "balances_raw": {},
                    "retention_flow": {"latest_block": 100},
                }
            }
        }
        old_event = {
            "type": "retained_seller_out",
            "level": "HIGH",
            "sample_tx": "0xold",
            "sample_log_index": 1,
        }
        current_event = {
            "type": "retained_seller_out",
            "level": "HIGH",
            "sample_tx": "0xcurrent",
            "sample_log_index": 2,
        }
        comparisons: list[
            tuple[dict[str, object], dict[str, object] | None]
        ] = []

        def classify(
            metrics: dict[str, object],
            previous: dict[str, object] | None,
        ) -> dict[str, object]:
            comparisons.append(
                (
                    dict(metrics),
                    dict(previous) if previous else None,
                )
            )
            return {
                "direction": "deconcentration",
                "level": "HIGH",
                "action": "降低风险",
                "reason": "测试",
            }

        catchup_rows = [
            (
                [],
                [],
                False,
                200,
                {
                    "applicable": True,
                    "active": True,
                    "requested_to_block": 500,
                    "selected_to_block": 200,
                    "attempt_count": 1,
                    "complete_selected_window": True,
                    "complete_requested_window": False,
                },
            ),
            (
                [],
                [],
                False,
                500,
                {
                    "applicable": True,
                    "active": False,
                    "requested_to_block": 500,
                    "selected_to_block": 500,
                    "attempt_count": 1,
                    "complete_selected_window": True,
                    "complete_requested_window": True,
                },
            ),
        ]
        retention_rows = [
            {
                "status": "active",
                "complete": True,
                "selected_window_complete": True,
                "latest_block": 200,
                "events": [old_event],
            },
            {
                "status": "active",
                "complete": True,
                "selected_window_complete": True,
                "latest_block": 500,
                "events": [current_event],
            },
        ]
        item = {
            "symbol": "TEST",
            "name": "TEST",
            "priority": "P1_MONITOR",
            "chain": "bsc",
            "address": token,
        }
        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_HOLDER_FINALITY_BLOCKS": "0"},
            ),
            mock.patch.object(holder, "latest_block", return_value=500),
            mock.patch.object(
                holder,
                "bounded_incremental_transfer_logs",
                side_effect=catchup_rows,
            ),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(holder, "top_rows", return_value=[]),
            mock.patch.object(
                holder,
                "pct_sum",
                side_effect=[
                    holder.Decimal("9.4"),
                    holder.Decimal("9.4"),
                    holder.Decimal("8.8"),
                    holder.Decimal("8.8"),
                ],
            ),
            mock.patch.object(
                holder,
                "raw_top10_infra_pct",
                return_value=holder.Decimal("0"),
            ),
            mock.patch.object(
                holder,
                "classify_signal",
                side_effect=classify,
            ),
            mock.patch.object(
                holder,
                "build_retention_flow",
                side_effect=retention_rows,
            ),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={"source": "none", "status": "not_configured"},
            ),
        ):
            first = holder.build_token_snapshot(
                item,
                {"items": []},
                state,
            )
            pending_metrics = dict(
                state["tokens"][key]["last_metrics"]
            )
            second = holder.build_token_snapshot(
                item,
                {"items": []},
                state,
            )

        self.assertEqual(first["signal"]["level"], "INFO")
        self.assertEqual(
            pending_metrics["effective_top10_pct"],
            "10",
        )
        self.assertEqual(
            state["tokens"][key]["last_metrics"][
                "effective_top10_pct"
            ],
            "8.8",
        )
        self.assertEqual(
            comparisons[1][1]["effective_top10_pct"],
            "10",
        )
        self.assertEqual(
            comparisons[1][0]["effective_top10_delta_pct"],
            "-1.2",
        )
        historical = [
            event
            for event in second["retention_flow"]["events"]
            if event.get("historical_catchup")
        ]
        self.assertEqual(
            [event["sample_tx"] for event in historical],
            ["0xold"],
        )
        self.assertEqual(
            [
                event["sample_tx"]
                for event in holder.retention_alert_events(second)
            ],
            ["0xcurrent"],
        )
        self.assertEqual(
            state["tokens"][key]["retention_flow"][
                "pending_alert_events"
            ],
            [],
        )

    def test_bounded_holder_baseline_never_emits_directional_delta(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        account_a = "0x" + "2" * 40
        account_b = "0x" + "3" * 40
        state: dict[str, object] = {"tokens": {}}
        apply_calls = 0

        def apply(
            _balances: dict[str, int],
            _logs: list[dict[str, object]],
        ) -> dict[str, int]:
            nonlocal apply_calls
            apply_calls += 1
            return (
                {account_a: -100, account_b: 100}
                if apply_calls == 1
                else {}
            )

        def rows(
            balances: dict[str, int],
            *_args: object,
            **_kwargs: object,
        ) -> list[dict[str, object]]:
            return (
                [{"pct": "10", "class": "wallet"}]
                if balances
                else []
            )

        with (
            mock.patch.object(
                holder,
                "latest_block",
                side_effect=[1000, 1001],
            ),
            mock.patch.object(
                holder,
                "transfer_logs",
                side_effect=[
                    ([], [], True),
                    ([{"blockNumber": "0x3e9"}], [], False),
                ],
            ),
            mock.patch.object(
                holder,
                "bounded_bootstrap_transfer_logs",
                return_value=(
                    [{"blockNumber": "0x3e8"}],
                    [],
                    False,
                    900,
                    {
                        "active": True,
                        "requested_from_block": 0,
                        "selected_from_block": 900,
                        "attempt_count": 1,
                        "complete_selected_window": True,
                    },
                ),
            ),
            mock.patch.object(
                holder,
                "apply_transfers",
                side_effect=apply,
            ),
            mock.patch.object(
                holder,
                "token_decimals",
                return_value=18,
            ),
            mock.patch.object(
                holder,
                "token_total_supply_raw",
                return_value=1000,
            ),
            mock.patch.object(
                holder,
                "top_rows",
                side_effect=rows,
            ),
            mock.patch.object(
                holder,
                "build_retention_flow",
                return_value={
                    "status": "active",
                    "complete": True,
                    "latest_block": 1001,
                    "events": [],
                },
            ),
            mock.patch.object(
                holder,
                "full_holder_source_status",
                return_value={
                    "source": "none",
                    "status": "not_configured",
                },
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_FINALITY_BLOCKS": "0",
                    "ALPHA_HOLDER_LOOKBACK_BLOCKS": "50000",
                },
            ),
        ):
            first = holder.build_token_snapshot(
                {
                    "symbol": "TAIL",
                    "name": "TAIL",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )
            second = holder.build_token_snapshot(
                {
                    "symbol": "TAIL",
                    "name": "TAIL",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": token,
                },
                {"items": []},
                state,
            )

        key = f"bsc:{token}"
        self.assertEqual(
            first["holder_baseline_status"],
            holder.BOUNDED_BOOTSTRAP_UNRELIABLE,
        )
        self.assertEqual(
            second["signal"]["direction"],
            "baseline_unavailable",
        )
        self.assertEqual(second["signal"]["level"], "INFO")
        self.assertNotIn(
            "effective_top10_delta_pct",
            second["metrics"],
        )
        self.assertEqual(holder.holder_signal_key(second), "")
        self.assertEqual(state["tokens"][key]["latest_block"], 1000)
        self.assertEqual(
            second["holder_scan_status"],
            "skipped_unreliable_baseline",
        )
        self.assertEqual(state["tokens"][key]["last_metrics"], {})
        retention_project = {
            **second,
            "retention_flow": {
                "status": "active",
                "coverage_mode": "full_transfer_stream",
                "complete": True,
                "selected_window_complete": True,
                "log_error_count": 0,
                "truncated": False,
                "events_truncated": False,
                "coverage_mode": "targeted_indexed_topics",
                "query_scope_complete": True,
                "query_count": 1,
                "query_chunk_count": 1,
                "expected_query_count": 1,
                "scope_kind_count": 1,
                "scope_batch_count": 1,
                "cex_address_count": 1,
                "opening_scope_complete": True,
                "opening_actor_count": 0,
                "opening_actor_scope_hash": "b" * 64,
                "scope_state_schema_version": 1,
                "scope_hash": "a" * 64,
                "previous_scope_hash": "a" * 64,
                "scope_rebaseline": False,
                "previous_catchup_active": False,
                "scan_from_block": 1001,
                "scan_to_block": 1001,
                "previous_latest_block": 1000,
                "latest_block": 1001,
                "target_latest_block": 1001,
                "continuous": True,
                "incremental_catchup": {
                    "applicable": True,
                    "active": False,
                    "requested_to_block": 1001,
                    "selected_to_block": 1001,
                    "complete_selected_window": True,
                    "complete_requested_window": True,
                },
                "events": [
                    {
                        "type": "cex_inflow_transfer_risk",
                        "level": "HIGH",
                        "sample_tx": "0x" + "4" * 64,
                    }
                ],
            },
        }
        self.assertTrue(holder.alert_keys({"projects": [retention_project]}))
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
        )

        self.assertEqual(
            output_row_coverage_issue("holder", second),
            "",
        )
        self.assertIn(
            "baseline unavailable",
            output_row_coverage_warning("holder", second),
        )
        self.assertIn(
            "unreliable baseline",
            output_row_coverage_issue(
                "holder",
                {
                    **second,
                    "signal": {
                        "level": "CRITICAL",
                        "direction": "effective_top10_down",
                    },
                },
            ),
        )

    def test_holder_retention_flow_covers_sniper_project_and_cex_transfers(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        buyer = "0x" + "2" * 40
        controller = "0x" + "3" * 40
        cex = "0x" + "4" * 40
        recipient = "0x" + "5" * 40
        fixed_now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        item = {
            "symbol": "TAIL",
            "contracts": [{"chain": "bsc", "address": token}],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": (
                        fixed_now - timedelta(days=4)
                    )
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
            "cex_deposit_addresses": [cex],
        }

        def raw_log(
            sender: str,
            receiver: str,
            tx_hash: str,
            index: int,
        ) -> dict[str, object]:
            return {
                "blockNumber": hex(100 + index),
                "logIndex": hex(index),
                "transactionHash": tx_hash,
                "topics": [
                    holder.TRANSFER_TOPIC,
                    holder.topic_address(sender),
                    holder.topic_address(receiver),
                ],
                "data": hex(10**18),
            }

        logs = [
            raw_log(buyer, recipient, "0x" + "a" * 64, 1),
            raw_log(controller, recipient, "0x" + "b" * 64, 2),
            raw_log(recipient, cex, "0x" + "c" * 64, 3),
        ]
        context = {
            "opening": {
                "events": [
                    {
                        "symbol": "TAIL",
                        "chain": "bsc",
                        "token": {"address": token},
                        "rows": [
                            {
                                "buyer": buyer,
                                "token_bought": "100",
                                "buyer_trace": {},
                            }
                        ],
                    }
                ]
            },
            "project": {
                "projects": [
                    {
                        "symbol": "TAIL",
                        "contracts": [
                            {
                                "chain": "bsc",
                                "address": token,
                                "watch_addresses": [
                                    {
                                        "address": controller,
                                        "role": "token_controller",
                                        "identity_status": "verified",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }
        with mock.patch.object(holder, "now_utc", return_value=fixed_now):
            flow = holder.build_retention_flow(
                item=item,
                symbol="TAIL",
                chain="bsc",
                token=token,
                logs=logs,
                errors=[],
                truncated=False,
                decimals=18,
                supply_raw=10**21,
                scan_from_block=100,
                scan_to_block=103,
                previous_latest_block=99,
                holder_previous_latest_block=99,
                context=context,
            )

        self.assertEqual(flow["status"], "active")
        self.assertTrue(flow["complete"])
        self.assertEqual(flow["latest_block"], 103)
        self.assertEqual(
            {event["type"] for event in flow["events"]},
            {
                "opening_buyer_outflow_transfer_risk",
                "project_or_mm_outflow_transfer_risk",
                "cex_inflow_transfer_risk",
            },
        )
        self.assertTrue(
            all(
                event["evidence_level"] == "transfer_only"
                for event in flow["events"]
            )
        )

    def test_holder_retention_realized_sell_requires_cached_receipt_evidence(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = "0x" + "1" * 40
        buyer = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        tx_hash = "0x" + "d" * 64
        fixed_now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        item = {
            "symbol": "TAIL",
            "contracts": [{"chain": "bsc", "address": token}],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": (
                        fixed_now - timedelta(days=4)
                    )
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }
        log = {
            "blockNumber": hex(101),
            "logIndex": hex(7),
            "transactionHash": tx_hash,
            "topics": [
                holder.TRANSFER_TOPIC,
                holder.topic_address(buyer),
                holder.topic_address(pool),
            ],
            "data": hex(2 * 10**18),
        }
        context = {
            "opening": {
                "events": [
                    {
                        "symbol": "TAIL",
                        "chain": "bsc",
                        "token": {"address": token},
                        "rows": [
                            {
                                "buyer": buyer,
                                "token_bought": "100",
                                "buyer_trace": {
                                    "confirmed_sell_evidence": [
                                        {
                                            "tx": tx_hash,
                                            "log_index": 7,
                                            "route": "direct",
                                            "recipient": buyer,
                                            "quote_received": "500",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
            "project": {"projects": []},
        }
        with mock.patch.object(holder, "now_utc", return_value=fixed_now):
            flow = holder.build_retention_flow(
                item=item,
                symbol="TAIL",
                chain="bsc",
                token=token,
                logs=[log],
                errors=[],
                truncated=False,
                decimals=18,
                supply_raw=10**24,
                scan_from_block=100,
                scan_to_block=101,
                previous_latest_block=99,
                holder_previous_latest_block=99,
                context=context,
            )

        self.assertEqual(flow["events"][0]["type"], "realized_sell")
        self.assertEqual(
            flow["events"][0]["evidence_level"],
            "receipt_quote_recovery",
        )
        self.assertEqual(
            flow["events"][0]["receipt_evidence"][0]["quote_received"],
            "500",
        )

    def test_holder_retention_cex_threshold_uses_cycle_aggregate(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        cex = "0x" + "4" * 40
        supply_raw = 10**21

        def raw_log(index: int) -> dict[str, object]:
            return {
                "blockNumber": hex(100 + index),
                "logIndex": hex(index),
                "transactionHash": "0x" + f"{index:x}" * 64,
                "topics": [
                    holder.TRANSFER_TOPIC,
                    holder.topic_address("0x" + f"{index + 5:x}" * 40),
                    holder.topic_address(cex),
                ],
                "data": hex(3 * 10**17),
            }

        events, matched_count = holder.retention_transfer_events(
            [raw_log(1), raw_log(2)],
            18,
            supply_raw,
            {},
            {
                cex: {
                    "kind": "cex",
                    "role": "cex_deposit",
                    "source": "fixture",
                }
            },
            {},
        )

        self.assertEqual(matched_count, 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["transfer_count"], 2)
        self.assertEqual(events[0]["amount"], "0.6")
        self.assertEqual(events[0]["summary_scope"], "risk_type_scan_window")
        self.assertEqual(len(events[0]["samples"]), 2)

    def test_holder_retention_active_bootstrap_is_scoped_by_first_seen(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        from scripts.runtime_health_watch import (
            retention_flow_coverage_issue,
        )

        fixed_now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        opening = fixed_now - timedelta(days=4)
        base_item = {
            "symbol": "TAIL",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "1" * 40}
            ],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": opening
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }

        def build(
            item: dict[str, object],
            *,
            holder_previous_latest_block: int = 0,
        ) -> dict[str, object]:
            with mock.patch.object(holder, "now_utc", return_value=fixed_now):
                return holder.build_retention_flow(
                    item=item,
                    symbol="TAIL",
                    chain="bsc",
                    token="0x" + "1" * 40,
                    logs=[],
                    errors=[],
                    truncated=False,
                    decimals=18,
                    supply_raw=10**21,
                    scan_from_block=100,
                    scan_to_block=110,
                    previous_latest_block=0,
                    holder_previous_latest_block=holder_previous_latest_block,
                    context={
                        "opening": {"events": []},
                        "project": {"projects": []},
                    },
                )

        early = {
            **base_item,
            "facts": {
                "lifecycle_first_seen_at": (
                    opening - timedelta(hours=1)
                ).isoformat()
            },
        }
        early_flow = build(early)
        self.assertFalse(early_flow["complete"])
        self.assertEqual(
            early_flow["coverage_scope"],
            "historical_backfill_required",
        )
        self.assertIn(
            "incomplete",
            retention_flow_coverage_issue(
                {"retention_flow": early_flow}
            ),
        )

        late = {
            **base_item,
            "facts": {
                "lifecycle_first_seen_at": (
                    opening + timedelta(hours=80)
                ).isoformat()
            },
        }
        late_flow = build(late)
        self.assertTrue(late_flow["complete"])
        self.assertTrue(late_flow["late_discovery_bootstrap"])
        self.assertEqual(
            late_flow["coverage_scope"],
            "first_success_bounded_baseline",
        )
        self.assertEqual(
            retention_flow_coverage_issue(
                {"retention_flow": late_flow}
            ),
            "",
        )

        late_with_existing_holder_state = build(
            late,
            holder_previous_latest_block=99,
        )
        self.assertFalse(late_with_existing_holder_state["complete"])
        self.assertFalse(
            late_with_existing_holder_state["late_discovery_bootstrap"]
        )
        self.assertEqual(
            late_with_existing_holder_state["coverage_scope"],
            "historical_backfill_required",
        )
        self.assertIn(
            "incomplete",
            retention_flow_coverage_issue(
                {"retention_flow": late_with_existing_holder_state}
            ),
        )

    def test_holder_retention_checkpoint_gap_fails_closed(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        fixed_now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        item = {
            "symbol": "TAIL",
            "contracts": [
                {"chain": "bsc", "address": "0x" + "1" * 40}
            ],
            "pool_ids": [
                {
                    "chain": "bsc",
                    "start_time_utc8": (
                        fixed_now - timedelta(days=4)
                    )
                    .astimezone(timezone(timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M"),
                }
            ],
        }
        with mock.patch.object(holder, "now_utc", return_value=fixed_now):
            flow = holder.build_retention_flow(
                item=item,
                symbol="TAIL",
                chain="bsc",
                token="0x" + "1" * 40,
                logs=[],
                errors=[],
                truncated=False,
                decimals=18,
                supply_raw=10**24,
                scan_from_block=102,
                scan_to_block=110,
                previous_latest_block=100,
                holder_previous_latest_block=100,
                context={
                    "opening": {"events": []},
                    "project": {"projects": []},
                },
            )

        self.assertFalse(flow["continuous"])
        self.assertFalse(flow["complete"])
        self.assertEqual(flow["latest_block"], 100)

    def test_retention_flow_health_requires_continuous_complete_checkpoint(
        self,
    ) -> None:
        from scripts.runtime_health_watch import (
            retention_flow_coverage_issue,
            retention_flow_required,
        )

        current = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(
            retention_flow_required(
                current + timedelta(hours=1),
                current,
            )
        )
        self.assertTrue(
            retention_flow_required(
                current - timedelta(hours=1),
                current,
            )
        )
        row = {
            "retention_flow": {
                "status": "active",
                "coverage_mode": "full_transfer_stream",
                "complete": True,
                "scan_from_block": 101,
                "scan_to_block": 120,
                "previous_latest_block": 100,
                "latest_block": 120,
                "log_error_count": 0,
                "truncated": False,
                "events_truncated": False,
                "continuous": True,
            }
        }
        self.assertEqual(retention_flow_coverage_issue(row), "")
        row["retention_flow"]["scan_from_block"] = 102
        self.assertIn(
            "continue previous checkpoint",
            retention_flow_coverage_issue(row),
        )

    def test_retention_health_rejects_malformed_numeric_metadata(
        self,
    ) -> None:
        from scripts.runtime_health_watch import (
            retention_flow_coverage_issue,
        )

        full_stream = {
            "retention_flow": {
                "status": "active",
                "coverage_mode": "full_transfer_stream",
                "complete": True,
                "scan_from_block": "invalid",
                "scan_to_block": 120,
                "previous_latest_block": 100,
                "latest_block": 120,
                "log_error_count": 0,
                "truncated": False,
                "events_truncated": False,
                "continuous": True,
            }
        }
        targeted = {
            "retention_flow": {
                "status": "active",
                "coverage_mode": "targeted_indexed_topics",
                "complete": True,
                "selected_window_complete": True,
                "query_scope_complete": True,
                "opening_scope_complete": True,
                "scope_hash": "a" * 64,
                "scope_kind_count": 1,
                "scope_batch_count": 1,
                "query_count": 1,
                "query_chunk_count": 1,
                "expected_query_count": 1,
                "cex_address_count": 1,
                "opening_actor_count": 0,
                "opening_actor_scope_hash": "b" * 64,
                "scope_state_schema_version": "invalid",
                "log_error_count": 0,
                "truncated": False,
                "events_truncated": False,
            }
        }

        self.assertEqual(
            retention_flow_coverage_issue(full_stream),
            "retention flow block metadata invalid",
        )
        self.assertEqual(
            retention_flow_coverage_issue(targeted),
            "retention flow indexed query metadata invalid",
        )

    def test_holder_retention_flow_generates_deduped_telegram_signal(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        project = {
            "symbol": "TAIL",
            "priority": "P1_MONITOR",
            "chain": "bsc",
            "address": "0x" + "1" * 40,
            "log_error_count": 0,
            "truncated": False,
            "incremental_catchup": {"applicable": False},
            "metrics": {},
            "signal": {"level": "INFO", "direction": "flat"},
            "retention_flow": {
                "status": "active",
                "complete": True,
                "log_error_count": 0,
                "truncated": False,
                "events_truncated": False,
                "events": [
                    {
                        "type": "cex_inflow_transfer_risk",
                        "level": "HIGH",
                        "evidence_level": "transfer_only",
                        "amount": "1000",
                        "from": "0x" + "2" * 40,
                        "to": "0x" + "3" * 40,
                        "tx": "0x" + "a" * 64,
                        "log_index": 7,
                    }
                ],
            },
        }
        snapshot = {
            "alert_count": 1,
            "projects": [project],
        }
        keys = holder.alert_keys(snapshot)
        self.assertEqual(len(keys), 1)
        self.assertIn("cex_inflow_transfer_risk", keys[0])
        text = holder.telegram_text(snapshot)
        self.assertIn("30天流向", text)
        self.assertIn("CEX 入金风险", text)
        self.assertIn("transfer_only", text)

    def test_holder_telegram_batches_mark_only_rendered_signal_keys(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        projects = []
        event_types = [
            "cex_inflow_transfer_risk",
            "opening_buyer_outflow_transfer_risk",
            "project_or_mm_outflow_transfer_risk",
        ]
        for index, event_type in enumerate(event_types, start=1):
            projects.append(
                {
                    "symbol": f"TAIL{index}",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "address": "0x" + f"{index:x}" * 40,
                    "log_error_count": 0,
                    "truncated": False,
                    "incremental_catchup": {
                        "applicable": False,
                    },
                    "metrics": {},
                    "signal": {"level": "INFO", "direction": "flat"},
                    "retention_flow": {
                        "status": "active",
                        "complete": True,
                        "log_error_count": 0,
                        "truncated": False,
                        "events_truncated": False,
                        "events": [
                            {
                                "type": event_type,
                                "level": "HIGH",
                                "evidence_level": "transfer_only",
                                "amount": str(index * 1000),
                                "transfer_count": index,
                                "sample_from": "0x" + "a" * 40,
                                "sample_to": "0x" + "b" * 40,
                                "sample_tx": "0x" + f"{index:x}" * 64,
                                "sample_log_index": index,
                            }
                        ],
                    },
                }
            )
        snapshot = {
            "alert_count": len(projects),
            "projects": projects,
        }
        rendered_batches: list[tuple[str, list[str]]] = []

        def fake_send(
            text: str,
            batch_keys: list[str],
            **kwargs: object,
        ) -> None:
            rendered_batches.append((text, list(batch_keys)))
            seen = kwargs["seen"]
            assert isinstance(seen, set)
            seen.update(batch_keys)

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_HOLDER_TELEGRAM": "1",
                    "TELEGRAM_BOT_TOKEN": "fixture",
                    "TELEGRAM_CHAT_ID": "fixture",
                    "DISABLE_TELEGRAM": "0",
                },
            ),
            mock.patch.object(holder, "read_json", return_value=[]),
            mock.patch.object(
                holder,
                "send_telegram_batch",
                side_effect=fake_send,
            ),
        ):
            self.assertTrue(holder.maybe_send_telegram(snapshot))

        rendered_keys = {
            key
            for _, batch_keys in rendered_batches
            for key in batch_keys
        }
        self.assertEqual(rendered_keys, set(holder.alert_keys(snapshot)))
        self.assertEqual(len(rendered_batches), 3)
        self.assertTrue(
            all("样本" in text for text, _ in rendered_batches)
        )

    def test_holder_checkpoint_commits_only_after_signal_delivery(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = {
            "generated_at": "2026-07-30T12:00:00+00:00",
            "project_count": 0,
            "alert_count": 1,
            "projects": [],
            "_next_state": {"tokens": {"checkpoint": {"latest_block": 120}}},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            state_path = out_dir / "state.json"
            with (
                mock.patch.object(holder, "OUT_DIR", out_dir),
                mock.patch.object(holder, "LATEST_PATH", out_dir / "latest.json"),
                mock.patch.object(holder, "REPORT_PATH", out_dir / "latest.md"),
                mock.patch.object(holder, "STATE_PATH", state_path),
                mock.patch.object(
                    holder,
                    "build_snapshot",
                    return_value=dict(payload),
                ),
                mock.patch.object(
                    holder,
                    "maybe_send_telegram",
                    return_value=False,
                ),
            ):
                self.assertEqual(holder.main(), 1)
            self.assertFalse(state_path.exists())

            with (
                mock.patch.object(holder, "OUT_DIR", out_dir),
                mock.patch.object(holder, "LATEST_PATH", out_dir / "latest.json"),
                mock.patch.object(holder, "REPORT_PATH", out_dir / "latest.md"),
                mock.patch.object(holder, "STATE_PATH", state_path),
                mock.patch.object(
                    holder,
                    "build_snapshot",
                    return_value=dict(payload),
                ),
                mock.patch.object(
                    holder,
                    "maybe_send_telegram",
                    return_value=True,
                ),
            ):
                self.assertEqual(holder.main(), 0)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                payload["_next_state"],
            )

    def test_health_matches_the_target_project_contract_only(self) -> None:
        from scripts.runtime_health_watch import (
            output_row_coverage_issue,
            output_row_coverage_warning,
            row_contract_addresses,
        )

        target = "0x" + "2" * 40
        row = {
            "coverage_complete": True,
            "contracts": [
                {
                    "address": "0x" + "1" * 40,
                    "log_error_count": 1,
                    "operator_attribution_state": "contract_error",
                },
                {
                    **complete_project_contract(target),
                },
            ]
        }
        self.assertIn(target, row_contract_addresses(row, "project"))
        self.assertEqual(
            output_row_coverage_issue("project", row, target_contract=target),
            "",
        )
        unresolved = {
            "coverage_complete": True,
            "contracts": [
                {
                    **complete_project_contract(
                        target,
                        operator_state="owner_unresolved",
                    ),
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

    def test_alpha_lifecycle_outputs_follow_the_health_wall_clock(self) -> None:
        from scripts.runtime_health_watch import alpha_required_outputs

        current = datetime(
            2026,
            7,
            30,
            6,
            0,
            tzinfo=timezone.utc,
        )
        self.assertNotIn(
            "prelaunch",
            alpha_required_outputs(
                "bsc",
                current + timedelta(hours=49),
                current,
            ),
        )
        self.assertIn(
            "prelaunch",
            alpha_required_outputs(
                "bsc",
                current + timedelta(hours=47),
                current,
            ),
        )
        opened = alpha_required_outputs(
            "bsc",
            current - timedelta(seconds=1),
            current,
        )
        self.assertIn("intraday", opened)
        self.assertIn("price", opened)
        retained = alpha_required_outputs(
            "bsc",
            current - timedelta(hours=73),
            current,
        )
        self.assertNotIn("intraday", retained)
        self.assertIn("price", retained)

    def test_post_open_health_retains_prelaunch_delivery_audit(self) -> None:
        from scripts.runtime_health_watch import (
            historical_prelaunch_delivery_issue,
        )

        contract = "0x" + "2" * 40
        listing = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        row = {
            "symbol": "GRVT",
            "contract": contract,
            "listing_time_utc": listing.isoformat(),
            "lifecycle_first_seen_at": (
                listing - timedelta(hours=30)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIn(
                "historical",
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=1),
                ),
            )
            seen_path = (
                root
                / "output"
                / "alpha_prelaunch_watch"
                / "seen_alerts.json"
            )
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text(
                json.dumps(
                    {
                        "keys": [
                            (
                                f"GRVT|{contract}|{listing.isoformat()}"
                                "|T_MINUS_24H"
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=1),
                ),
                "",
            )

    def test_late_discovery_accepts_live_window_delivery(self) -> None:
        from scripts.runtime_health_watch import (
            historical_prelaunch_delivery_issue,
        )

        contract = "0x" + "3" * 40
        listing = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        row = {
            "symbol": "LATE",
            "contract": contract,
            "listing_time_utc": listing.isoformat(),
            "lifecycle_first_seen_at": (
                listing - timedelta(seconds=5)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seen_path = (
                root
                / "output"
                / "alpha_prelaunch_watch"
                / "seen_alerts.json"
            )
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text(
                json.dumps(
                    {
                        "keys": [
                            (
                                f"LATE|{contract}|{listing.isoformat()}"
                                "|LIVE_WINDOW"
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=1),
                ),
                "",
            )

    def test_post_open_discovery_requires_live_window_delivery(self) -> None:
        from scripts.runtime_health_watch import (
            historical_prelaunch_delivery_issue,
        )

        contract = "0x" + "4" * 40
        listing = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        row = {
            "symbol": "POSTOPEN",
            "contract": contract,
            "listing_time_utc": listing.isoformat(),
            "lifecycle_first_seen_at": (
                listing + timedelta(minutes=5)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIn(
                "historical",
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=6),
                ),
            )
            seen_path = (
                root
                / "output"
                / "alpha_prelaunch_watch"
                / "seen_alerts.json"
            )
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text(
                json.dumps(
                    {
                        "keys": [
                            (
                                f"POSTOPEN|{contract}|{listing.isoformat()}"
                                "|LIVE_WINDOW"
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=6),
                ),
                "",
            )

            wrong_contract = dict(row)
            wrong_contract["contract"] = "0x" + "5" * 40
            self.assertIn(
                "historical",
                historical_prelaunch_delivery_issue(
                    root,
                    wrong_contract,
                    listing + timedelta(minutes=6),
                ),
            )

    def test_discovery_after_live_window_has_no_prelaunch_obligation(self) -> None:
        from scripts.runtime_health_watch import (
            historical_prelaunch_delivery_issue,
        )

        listing = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        row = {
            "symbol": "TOO_LATE",
            "contract": "0x" + "6" * 40,
            "listing_time_utc": listing.isoformat(),
            "lifecycle_first_seen_at": (
                listing + timedelta(minutes=31)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                historical_prelaunch_delivery_issue(
                    Path(temp_dir),
                    row,
                    listing + timedelta(minutes=32),
                ),
                "",
            )

    def test_early_discovery_does_not_accept_live_window_only(self) -> None:
        from scripts.runtime_health_watch import (
            historical_prelaunch_delivery_issue,
        )

        contract = "0x" + "7" * 40
        listing = datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        )
        row = {
            "symbol": "EARLY",
            "contract": contract,
            "listing_time_utc": listing.isoformat(),
            "lifecycle_first_seen_at": (
                listing - timedelta(minutes=11)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seen_path = (
                root
                / "output"
                / "alpha_prelaunch_watch"
                / "seen_alerts.json"
            )
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text(
                json.dumps(
                    {
                        "keys": [
                            (
                                f"EARLY|{contract}|{listing.isoformat()}"
                                "|LIVE_WINDOW"
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertIn(
                "historical",
                historical_prelaunch_delivery_issue(
                    root,
                    row,
                    listing + timedelta(minutes=1),
                ),
            )

    def test_catalog_item_beyond_48h_does_not_require_prelaunch_output(self) -> None:
        import scripts.binance_alpha_catalog_watch as catalog
        from scripts.runtime_health_watch import alpha_coverage_issues

        contract = "0x" + "2" * 40
        listing_time = "2099-07-28T10:00:00+00:00"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy, focus_item = self.write_focus_config(
                root,
                "AEON",
                contract=contract,
                listing_time_utc=listing_time,
            )

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
                            "listing_time_utc": listing_time,
                        }
                    ],
                },
            )
            write(
                "output/binance_alpha_catalog_watch/current_watchlist.json",
                {
                    "monitoring_policy": policy,
                    "monitoring_policy_fingerprint": (
                        catalog.monitoring_policy_fingerprint(policy)
                    ),
                    "items": [focus_item],
                },
            )
            write(
                "output/alpha_project_watch/latest.json",
                {
                    "projects": [
                        {
                            "symbol": "LEGACYAEON",
                            "coverage_complete": True,
                            "contracts": [
                                complete_project_contract(contract)
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
                            "incremental_catchup": {
                                "applicable": False,
                            },
                        }
                    ]
                },
            )
            write("output/alpha_prelaunch_watch/latest.json", {"events": []})

            issues = alpha_coverage_issues(
                root,
                current=datetime(
                    2026,
                    7,
                    30,
                    6,
                    0,
                    tzinfo=timezone.utc,
                ),
            )

        self.assertEqual(issues, [])

    def test_post_72h_catalog_item_requires_retention_flow_health(self) -> None:
        import scripts.binance_alpha_catalog_watch as catalog
        from scripts.runtime_health_watch import alpha_coverage_issues

        contract = "0x" + "8" * 40
        current = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        listing = current - timedelta(days=4)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy, focus_item = self.write_focus_config(
                root,
                "TAIL",
                contract=contract,
                listing_time_utc=listing.isoformat(),
            )

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
                            "symbol": "TAIL",
                            "chain": "bsc",
                            "contract": contract,
                            "listing_time_utc": listing.isoformat(),
                            "lifecycle_first_seen_at": (
                                listing + timedelta(hours=1)
                            ).isoformat(),
                        }
                    ],
                },
            )
            write(
                "output/binance_alpha_catalog_watch/current_watchlist.json",
                {
                    "monitoring_policy": policy,
                    "monitoring_policy_fingerprint": (
                        catalog.monitoring_policy_fingerprint(policy)
                    ),
                    "items": [focus_item],
                },
            )
            write(
                "output/alpha_project_watch/latest.json",
                {
                    "projects": [
                        {
                            "symbol": "TAIL",
                            "coverage_complete": True,
                            "contracts": [
                                complete_project_contract(contract)
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
                            "symbol": "TAIL",
                            "chain": "bsc",
                            "token": {"address": contract},
                            "status": "opened",
                            "opening_cohort_coverage_complete": True,
                            "opening_liquidity_coverage_complete": True,
                            "opening_buyer_scope_complete": True,
                            "rows": [],
                        }
                    ]
                },
            )
            write(
                "output/alpha_price_momentum_watch/latest.json",
                {
                    "events": [
                        {
                            "symbol": "TAIL",
                            "chain": "bsc",
                            "contract": contract,
                            "analysis": {"direction": "观察"},
                        }
                    ]
                },
            )
            holder_path = (
                "output/alpha_holder_concentration_watch/latest.json"
            )
            write(
                holder_path,
                {
                    "projects": [
                        {
                            "symbol": "TAIL",
                            "chain": "bsc",
                            "address": contract,
                            "log_error_count": 0,
                            "truncated": False,
                            "incremental_catchup": {
                                "applicable": False,
                            },
                        }
                    ]
                },
            )
            issues = alpha_coverage_issues(root, current=current)
            self.assertTrue(
                any("retention flow status=missing" in row["detail"] for row in issues),
                issues,
            )

            write(
                holder_path,
                {
                    "projects": [
                        {
                            "symbol": "TAIL",
                            "chain": "bsc",
                            "address": contract,
                            "log_error_count": 0,
                            "truncated": False,
                            "incremental_catchup": {
                                "applicable": False,
                            },
                            "retention_flow": {
                                "status": "active",
                                "coverage_mode": "full_transfer_stream",
                                "complete": True,
                                "scan_from_block": 101,
                                "scan_to_block": 120,
                                "previous_latest_block": 100,
                                "latest_block": 120,
                                "log_error_count": 0,
                                "truncated": False,
                                "events_truncated": False,
                                "continuous": True,
                                "bounded_bootstrap": False,
                            },
                        }
                    ]
                },
            )
            self.assertEqual(
                alpha_coverage_issues(root, current=current),
                [],
            )


class ContinuousLiquidityRetentionRegressionTests(unittest.TestCase):
    @staticmethod
    def _address(digit: str) -> str:
        return "0x" + digit * 40

    @staticmethod
    def _hash(digit: str) -> str:
        return "0x" + digit * 64

    @staticmethod
    def _word(value: int, bits: int = 256) -> str:
        if value < 0:
            low = (1 << bits) + value
            if bits < 256:
                low |= ((1 << (256 - bits)) - 1) << bits
            value = low
        return f"{value:064x}"

    @classmethod
    def _data(cls, *values: tuple[int, int] | int) -> str:
        words = []
        for value in values:
            if isinstance(value, tuple):
                words.append(cls._word(value[0], value[1]))
            else:
                words.append(cls._word(value))
        return "0x" + "".join(words)

    @classmethod
    def _opening_payload(cls) -> dict[str, object]:
        token = cls._address("1")
        quote = cls._address("2")
        v3_pool = cls._address("3")
        factory = cls._address("4")
        manager = cls._address("5")
        pool_id = cls._hash("6")
        return {
            "events": [
                {
                    "status": "opened",
                    "symbol": "TEST",
                    "chain": "bsc",
                    "token": {"address": token},
                    "quote": {
                        "address": quote,
                        "decimals": 18,
                        "symbol": "WBNB",
                    },
                    "opening_liquidity_scope_complete": True,
                    "opening_liquidity_watch_scope_hash": "7" * 64,
                    "opening_v3_pool_scope": {
                        "schema": "opening_v3_factory_matrix.v2",
                        "complete": True,
                        "snapshot_coherent": True,
                        "configuration_hash": "8" * 64,
                        "as_of_block": 100,
                        "as_of_block_hash": cls._hash("9"),
                        "pools": [
                            {
                                "address": v3_pool,
                                "factory": factory,
                                "token0": token,
                                "token1": quote,
                                "fee": 2500,
                            }
                        ],
                    },
                    "opening_v4_pool_scope": {
                        "schema": "opening_v4_manager_scope.v2",
                        "applicable": True,
                        "complete": True,
                        "snapshot_coherent": True,
                        "configuration_hash": "a" * 64,
                        "as_of_block": 100,
                        "as_of_block_hash": cls._hash("b"),
                        "pools": [
                            {
                                "address": manager,
                                "pool_manager": manager,
                                "pool_id": pool_id,
                                "v4_manager_type": "cl",
                                "token0": token,
                                "token1": quote,
                                "fee": 500,
                            }
                        ],
                    },
                }
            ]
        }

    @classmethod
    def _event_row(
        cls,
        *,
        pool: dict[str, object],
        event_kind: str,
        topic: str,
        data: str,
        tx_digit: str,
        block: int,
        index: int,
    ) -> dict[str, object]:
        return {
            "address": pool["address"],
            "blockNumber": hex(block),
            "blockHash": cls._hash("f"),
            "logIndex": hex(index),
            "transactionHash": cls._hash(tx_digit),
            "topics": [topic],
            "data": data,
            "removed": False,
            "_retention_pool": pool,
            "_retention_event_kind": event_kind,
        }

    def test_opening_verified_pool_scope_supports_multiple_quote_tokens(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        event = payload["events"][0]
        token = self._address("1")
        second_quote = self._address("c")
        event["opening_v3_pool_scope"]["pools"].append(
            {
                "address": self._address("d"),
                "factory": self._address("4"),
                "token0": token,
                "token1": second_quote,
                "fee": 10000,
                "quote_token": second_quote,
                "quote_decimals": 18,
                "quote_symbol": "WBNB",
            }
        )

        scope = holder.opening_verified_pool_scope(
            payload,
            "TEST",
            "bsc",
            token,
        )

        self.assertTrue(scope["complete"])
        self.assertEqual(scope["pool_count"], 3)
        self.assertEqual(scope["v3_pool_count"], 2)
        self.assertEqual(
            {
                row["quote_token"]
                for row in scope["pool_scope"]
                if row["protocol"] == "v3"
            },
            {self._address("2"), second_quote},
        )
        from scripts.runtime_health_watch import (
            opening_has_verified_liquidity_pool_scope,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            opening_path = Path(temp_dir) / "opening.json"
            opening_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            self.assertTrue(
                opening_has_verified_liquidity_pool_scope(
                    opening_path,
                    ("bsc", token),
                )
            )

    def test_opening_verified_pool_scope_is_stable_and_fail_closed(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        token = self._address("1")
        scope = holder.opening_verified_pool_scope(
            payload,
            "TEST",
            "bsc",
            token,
        )
        self.assertTrue(scope["complete"])
        self.assertEqual(scope["pool_count"], 2)
        self.assertEqual(scope["v3_pool_count"], 1)
        self.assertEqual(scope["v4_pool_count"], 1)

        refreshed = copy.deepcopy(payload)
        event = refreshed["events"][0]
        event["opening_v3_pool_scope"]["as_of_block"] = 200
        event["opening_v3_pool_scope"]["as_of_block_hash"] = self._hash("c")
        event["opening_v4_pool_scope"]["as_of_block"] = 200
        event["opening_v4_pool_scope"]["as_of_block_hash"] = self._hash("d")
        self.assertEqual(
            holder.opening_verified_pool_scope(
                refreshed,
                "TEST",
                "bsc",
                token,
            )["scope_hash"],
            scope["scope_hash"],
        )

        persisted = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": scope["scope_hash"],
            "pool_scope": scope["pool_scope"],
        }
        fallback = holder.opening_verified_pool_scope(
            {"events": []},
            "TEST",
            "bsc",
            token,
            persisted_scope=persisted,
        )
        self.assertEqual(fallback["source"], "state")
        self.assertEqual(fallback["pool_scope"], scope["pool_scope"])

        flow_incomplete = copy.deepcopy(payload)
        flow_event = flow_incomplete["events"][0]
        flow_event["opening_liquidity_scope_complete"] = False
        flow_event["opening_liquidity_scope_status"] = "deadline_exceeded"
        flow_event["opening_liquidity_coverage_complete"] = False
        flow_event["opening_liquidity_coverage_status"] = "deadline_exceeded"
        del flow_event["opening_liquidity_watch_scope_hash"]
        independently_verified = holder.opening_verified_pool_scope(
            flow_incomplete,
            "TEST",
            "bsc",
            token,
            persisted_scope=persisted,
        )
        self.assertTrue(independently_verified["complete"])
        self.assertEqual(independently_verified["pool_count"], 2)

        identity_incomplete = copy.deepcopy(flow_incomplete)
        identity_incomplete["events"][0]["opening_v3_pool_scope"][
            "complete"
        ] = False
        rejected = holder.opening_verified_pool_scope(
            identity_incomplete,
            "TEST",
            "bsc",
            token,
            persisted_scope=persisted,
        )
        self.assertFalse(rejected["complete"])
        self.assertEqual(rejected["pool_scope"], [])

        malformed_identity = copy.deepcopy(payload)
        malformed_identity["events"][0]["token"] = {}
        rejected_identity = holder.opening_verified_pool_scope(
            malformed_identity,
            "TEST",
            "bsc",
            token,
            persisted_scope=persisted,
        )
        self.assertFalse(rejected_identity["complete"])
        self.assertEqual(rejected_identity["source"], "opening")

        missing_quote_symbol = copy.deepcopy(payload)
        del missing_quote_symbol["events"][0]["quote"]["symbol"]
        rejected_quote = holder.opening_verified_pool_scope(
            missing_quote_symbol,
            "TEST",
            "bsc",
            token,
            persisted_scope=persisted,
        )
        self.assertFalse(rejected_quote["complete"])
        self.assertEqual(rejected_quote["source"], "opening")

        blank_quote_symbol = copy.deepcopy(payload)
        blank_quote_symbol["events"][0]["quote"]["symbol"] = "   "
        self.assertFalse(
            holder.opening_verified_pool_scope(
                blank_quote_symbol,
                "TEST",
                "bsc",
                token,
            )["complete"]
        )

        conflicting_events = copy.deepcopy(payload)
        conflicting_event = copy.deepcopy(conflicting_events["events"][0])
        conflicting_event["quote"]["symbol"] = "BNB"
        conflicting_events["events"].append(conflicting_event)
        rejected_conflict = holder.opening_verified_pool_scope(
            conflicting_events,
            "TEST",
            "bsc",
            token,
        )
        self.assertFalse(rejected_conflict["complete"])
        self.assertEqual(
            rejected_conflict["status"],
            "current_opening_scope_invalid",
        )

        for malformed_events in ("corrupt", {}, [123]):
            rejected_payload = holder.opening_verified_pool_scope(
                {"events": malformed_events},
                "TEST",
                "bsc",
                token,
                persisted_scope=persisted,
            )
            self.assertFalse(rejected_payload["complete"])
            self.assertEqual(
                rejected_payload["status"],
                "current_opening_payload_invalid",
            )
            self.assertEqual(rejected_payload["source"], "opening")

        for malformed_pools in ("not-a-list", [{}], ["not-a-pool"]):
            malformed = copy.deepcopy(payload)
            malformed["events"][0]["opening_v3_pool_scope"]["pools"] = (
                malformed_pools
            )
            result = holder.opening_verified_pool_scope(
                malformed,
                "TEST",
                "bsc",
                token,
                persisted_scope=persisted,
            )
            self.assertFalse(result["complete"])
            self.assertEqual(result["pool_scope"], [])

        spoofed_bin = copy.deepcopy(payload)
        spoofed_v4 = spoofed_bin["events"][0]["opening_v4_pool_scope"]
        spoofed_v4["pools"][0]["address"] = (
            holder.PANCAKE_INFINITY_BIN_POOL_MANAGER
        )
        spoofed_v4["pools"][0]["pool_manager"] = (
            holder.PANCAKE_INFINITY_BIN_POOL_MANAGER
        )
        spoofed_v4["pools"][0]["v4_manager_type"] = "cl"
        rejected_bin = holder.opening_verified_pool_scope(
            spoofed_bin,
            "TEST",
            "bsc",
            token,
        )
        self.assertFalse(rejected_bin["complete"])
        self.assertEqual(rejected_bin["pool_scope"], [])

    def test_health_requires_independently_verified_pool_identity(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        from scripts.runtime_health_watch import (
            matching_opening_nonhistorical_coverage_issue,
            opening_liquidity_gap_is_historical_only,
            opening_has_verified_liquidity_pool_scope,
        )

        payload = self._opening_payload()
        event = payload["events"][0]
        event["opening_liquidity_scope_complete"] = False
        event["opening_liquidity_scope_status"] = "deadline_exceeded"
        event["opening_liquidity_coverage_complete"] = False
        event["opening_liquidity_coverage_status"] = "deadline_exceeded"
        del event["opening_liquidity_watch_scope_hash"]
        with tempfile.TemporaryDirectory() as temp_dir:
            opening_path = Path(temp_dir) / "opening.json"
            opening_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            self.assertTrue(
                opening_has_verified_liquidity_pool_scope(
                    opening_path,
                    ("bsc", self._address("1")),
                )
            )
            self.assertTrue(
                opening_liquidity_gap_is_historical_only(
                    opening_path,
                    ("bsc", self._address("1")),
                    "opening liquidity flow coverage incomplete",
                )
            )
            self.assertFalse(
                opening_liquidity_gap_is_historical_only(
                    opening_path,
                    ("bsc", self._address("1")),
                    "opening cohort transfer coverage incomplete",
                )
            )

            conflicted = copy.deepcopy(payload["events"][0])
            conflicted["opening_cohort_coverage_complete"] = True
            conflicted["opening_buyer_scope_complete"] = True
            conflicted["opening_liquidity_coverage_complete"] = False
            conflicted["opening_v3_pool_scope"]["complete"] = True
            conflicted["opening_v4_pool_scope"]["complete"] = True
            conflicted["cache_identity_status"] = (
                "metadata_conflict_unresolved"
            )
            conflicted["cache_identity_conflict"] = "contract"
            self.assertIn(
                "metadata conflict",
                matching_opening_nonhistorical_coverage_issue([conflicted]),
            )

            bin_payload = self._opening_payload()
            bin_event = bin_payload["events"][0]
            bin_event["opening_v3_pool_scope"]["pools"] = []
            bin_pool = bin_event["opening_v4_pool_scope"]["pools"][0]
            bin_pool["address"] = holder.PANCAKE_INFINITY_BIN_POOL_MANAGER
            bin_pool["pool_manager"] = (
                holder.PANCAKE_INFINITY_BIN_POOL_MANAGER
            )
            bin_pool["v4_manager_type"] = "cl"
            opening_path.write_text(
                json.dumps(bin_payload),
                encoding="utf-8",
            )
            self.assertFalse(
                opening_has_verified_liquidity_pool_scope(
                    opening_path,
                    ("bsc", self._address("1")),
                )
            )

            event["opening_v3_pool_scope"]["complete"] = False
            event["opening_v4_pool_scope"]["complete"] = False
            opening_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            self.assertFalse(
                opening_has_verified_liquidity_pool_scope(
                    opening_path,
                    ("bsc", self._address("1")),
                )
            )
            self.assertFalse(
                opening_liquidity_gap_is_historical_only(
                    opening_path,
                    ("bsc", self._address("1")),
                    "opening liquidity flow coverage incomplete",
                )
            )

    def test_liquidity_log_queries_use_exact_topics_and_dedupe(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        scope = holder.opening_verified_pool_scope(
            self._opening_payload(),
            "TEST",
            "bsc",
            self._address("1"),
        )
        queries: list[dict[str, object]] = []

        def fetch(
            _chain: str,
            method: str,
            params: list[object],
        ) -> list[dict[str, object]]:
            self.assertEqual(method, "eth_getLogs")
            query = copy.deepcopy(params[0])
            assert isinstance(query, dict)
            queries.append(query)
            allowed_topics = query["topics"][0]
            assert isinstance(allowed_topics, list)
            rows = []
            for offset, topic0 in enumerate(allowed_topics, start=1):
                word_count = {
                    holder.V3_SWAP_TOPIC: 5,
                    holder.V3_MINT_TOPIC: 4,
                    holder.V3_BURN_TOPIC: 3,
                    holder.V3_COLLECT_TOPIC: 3,
                    holder.V4_SWAP_TOPIC: 7,
                    holder.MODIFY_LIQUIDITY_TOPIC: 4,
                }[topic0]
                topic_count = (
                    3
                    if topic0
                    in {
                        holder.V3_SWAP_TOPIC,
                        holder.V4_SWAP_TOPIC,
                        holder.MODIFY_LIQUIDITY_TOPIC,
                    }
                    else 4
                )
                topics = [topic0]
                if topic0 in {
                    holder.V4_SWAP_TOPIC,
                    holder.MODIFY_LIQUIDITY_TOPIC,
                }:
                    pool_ids = query["topics"][1]
                    topics.append(
                        pool_ids[0]
                        if isinstance(pool_ids, list)
                        else pool_ids
                    )
                    topics.append(holder.topic_address(self._address("e")))
                elif topic0 == holder.V3_SWAP_TOPIC:
                    topics.extend(
                        [
                            holder.topic_address(self._address("d")),
                            holder.topic_address(self._address("e")),
                        ]
                    )
                else:
                    topics.extend(
                        [
                            holder.topic_address(self._address("d")),
                            self._hash("0"),
                            self._hash("0"),
                        ]
                    )
                self.assertEqual(len(topics), topic_count)
                index = len(queries) * 10 + offset
                rows.append(
                    {
                        "address": (
                            query["address"][0]
                            if isinstance(query["address"], list)
                            else query["address"]
                        ),
                        "blockNumber": hex(105),
                        "blockHash": self._hash("f"),
                        "logIndex": hex(index),
                        "transactionHash": "0x" + f"{index:064x}",
                        "topics": topics,
                        "data": (
                            self._data(1, -1, 0, 0, 0)
                            if topic0 == holder.V3_SWAP_TOPIC
                            else self._data(
                                (-1, 128),
                                (1, 128),
                                0,
                                0,
                                0,
                                0,
                                0,
                            )
                            if topic0 == holder.V4_SWAP_TOPIC
                            else "0x" + "0" * (word_count * 64)
                        ),
                        "removed": False,
                    }
                )
            if len(queries) == 1:
                rows.append(dict(rows[0]))
            return rows

        with mock.patch.object(holder, "rpc_call", side_effect=fetch):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "bsc",
                    scope["pool_scope"],
                    101,
                    110,
                )
            )

        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(len(logs), 6)
        self.assertEqual(len(queries), 2)
        self.assertEqual(
            queries[0]["topics"],
            [
                sorted(
                    {
                        holder.V3_SWAP_TOPIC,
                        holder.V3_MINT_TOPIC,
                        holder.V3_BURN_TOPIC,
                        holder.V3_COLLECT_TOPIC,
                    }
                )
            ],
        )
        self.assertEqual(
            queries[1]["topics"],
            [
                sorted(
                    {
                        holder.V4_SWAP_TOPIC,
                        holder.MODIFY_LIQUIDITY_TOPIC,
                    }
                ),
                self._hash("6"),
            ],
        )
        self.assertTrue(metadata["query_scope_complete"])
        self.assertEqual(metadata["expected_query_count"], 2)

        second_v3 = {
            **scope["pool_scope"][0],
            "address": self._address("c"),
        }
        second_v4 = {
            **scope["pool_scope"][1],
            "pool_id": self._hash("d"),
        }
        batched = holder.retention_liquidity_query_scopes(
            [*scope["pool_scope"], second_v3, second_v4]
        )
        self.assertEqual(len(batched), 2)
        self.assertEqual(
            batched[0]["address"],
            sorted([self._address("3"), self._address("c")]),
        )
        self.assertEqual(
            batched[1]["topics"][1],
            sorted([self._hash("6"), self._hash("d")]),
        )

    def test_base_liquidity_queries_cap_chunks_at_two_thousand_blocks(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": self._address("1"),
            "token1": self._address("2"),
            "fee": 2500,
        }
        queries = []

        def fetch(
            _chain: str,
            _method: str,
            params: list[object],
        ) -> list[object]:
            queries.append(params[0])
            return []

        with (
            mock.patch.dict(
                os.environ,
                {"ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS": "8000"},
            ),
            mock.patch.object(holder, "rpc_call", side_effect=fetch),
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "base", [pool], 1, 4001
                )
            )
        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(len(queries), 3)
        self.assertEqual(metadata["query_chunk_blocks"], 2000)
        self.assertEqual(metadata["expected_query_count"], 3)

    def test_six_pool_liquidity_queries_avoid_provider_row_cap_with_eight_block_chunks(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        pools = [
            {
                "protocol": "v3",
                "address": self._address(digit),
                "factory": self._address("4"),
                "token0": token,
                "token1": quote,
                "fee": 3000,
            }
            for digit in ("3", "a", "b", "c", "d", "e")
        ]
        queries: list[dict[str, object]] = []

        def fetch(
            _chain: str,
            _method: str,
            params: list[object],
        ) -> list[object]:
            query = params[0]
            assert isinstance(query, dict)
            queries.append(query)
            span = int(str(query["toBlock"]), 16) - int(
                str(query["fromBlock"]), 16
            ) + 1
            return [{}] * 128 if span > 8 else []

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS": "8",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "512",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
            mock.patch.object(holder, "rpc_call", side_effect=fetch),
        ):
            logs, errors, truncated, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc", pools, 1, 512
                )
            )

        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(selected_to, 512)
        self.assertEqual(len(queries), 64)
        self.assertEqual(metadata["query_count"], 64)
        self.assertEqual(metadata["successful_window_blocks"], 512)
        self.assertTrue(metadata["complete_requested_window"])
        self.assertEqual(
            queries[0]["address"],
            sorted(pool["address"] for pool in pools),
        )

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS": "1",
                    "ALPHA_RETENTION_LIQUIDITY_PROVIDER_MAX_ROWS_PER_QUERY": "128",
                },
            ),
            mock.patch.object(holder, "rpc_call", return_value=[{}] * 128),
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", pools, 1, 1
                )
            )
        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertTrue(truncated)
        self.assertFalse(metadata["query_scope_complete"])

    def test_bounded_liquidity_event_overflow_shrinks_and_catches_up(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": self._address("2"),
            "fee": 2500,
        }

        def fetch(
            _chain: str,
            _pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
        ) -> tuple[list[dict[str, object]], list[str], bool, dict[str, object]]:
            rows = [
                {
                    "address": pool["address"],
                    "blockNumber": hex(block),
                    "blockHash": self._hash("f"),
                    "logIndex": "0x0",
                    "transactionHash": "0x" + f"{block:064x}",
                    "topics": [holder.V3_SWAP_TOPIC],
                    "data": self._data(100, -1, 0, 0, 0),
                    "removed": False,
                    "_retention_pool": pool,
                    "_retention_event_kind": "v3_swap",
                }
                for block in range(from_block, to_block + 1)
            ]
            return rows, [], False, {"query_scope_complete": True}

        cursor = 0
        scan_ranges: list[tuple[int, int]] = []
        shrink_count = 0
        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_MAX_EVENTS": "4",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "16",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
        ):
            while cursor < 16:
                scan_from = cursor + 1
                logs, errors, truncated, selected_to, metadata = (
                    holder.bounded_retention_liquidity_logs(
                        "bsc",
                        [pool],
                        scan_from,
                        16,
                        token=token,
                        decimals=0,
                        supply_raw=10_000,
                    )
                )
                self.assertEqual(errors, [])
                self.assertFalse(truncated)
                self.assertLessEqual(len(logs), 4)
                self.assertGreaterEqual(selected_to, scan_from)
                scan_ranges.append((scan_from, selected_to))
                shrink_count += int(
                    metadata.get("derived_event_shrink_count") or 0
                )
                cursor = selected_to

        self.assertEqual(scan_ranges[0][0], 1)
        self.assertTrue(
            all(
                current[0] == previous[1] + 1
                for previous, current in zip(
                    scan_ranges,
                    scan_ranges[1:],
                )
            )
        )
        self.assertEqual(cursor, 16)
        self.assertGreater(shrink_count, 0)

        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_MAX_EVENTS": "1",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "4",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_ATTEMPTS": "1",
                },
            ),
        ):
            _, errors, truncated, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    1,
                    4,
                    token=token,
                    decimals=0,
                    supply_raw=10_000,
                )
            )
        self.assertEqual(errors, [])
        self.assertTrue(truncated)

        self.assertEqual(selected_to, 4)
        self.assertFalse(metadata["complete_selected_window"])

    def test_bounded_liquidity_rpc_error_shrinks_to_successful_window(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": self._address("1"),
            "token1": self._address("2"),
            "fee": 2500,
        }
        ranges: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            dict[str, object],
        ]:
            ranges.append((from_block, to_block))
            if to_block - from_block + 1 > 4:
                return (
                    [],
                    ["coverage failed"],
                    False,
                    {"range_shrink_retryable": True},
                )
            return [], [], False, {"query_scope_complete": True}

        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "16",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
        ):
            logs, errors, truncated, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    1,
                    16,
                )
            )

        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(selected_to, 4)
        self.assertEqual(ranges, [(1, 16), (1, 8), (1, 4)])
        self.assertEqual(metadata["rpc_error_shrink_count"], 2)
        self.assertEqual(metadata["successful_window_blocks"], 4)
        self.assertEqual(metadata["next_window_blocks"], 8)

        ranges.clear()
        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                return_value=(
                    [],
                    ["duplicate identity conflict"],
                    False,
                    {"range_shrink_retryable": False},
                ),
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "16",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
        ):
            _, errors, _, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    1,
                    16,
                )
            )
        self.assertEqual(errors, ["duplicate identity conflict"])
        self.assertEqual(selected_to, 16)
        self.assertEqual(metadata["attempt_count"], 1)
        self.assertEqual(metadata["rpc_error_shrink_count"], 0)

    def test_liquidity_deadline_preserves_checkpoint_and_retries_smaller_window(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        token = self._address("1")
        scope = holder.opening_verified_pool_scope(
            payload,
            "TEST",
            "bsc",
            token,
        )
        reconciliation = {
            "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
            "pending": [],
            "completed": [],
            "deferred_events": [],
        }
        state = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": scope["scope_hash"],
            "pool_scope": scope["pool_scope"],
            "pool_count": scope["pool_count"],
            "scope_coverage_from_block": 100,
            "latest_block": 120,
            "latest_block_hash": self._hash("a"),
            "catchup_active": True,
            "catchup_live_from_block": 121,
            "next_catchup_window_blocks": 16,
            "reconciliation": reconciliation,
        }
        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "age_hours": 1,
        }

        def deadline(
            _chain: str,
            pools: list[dict[str, object]],
            from_block: int,
            requested_to: int,
            **_kwargs: object,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            int,
            dict[str, object],
        ]:
            scope_count = len(
                holder.retention_liquidity_query_scopes(pools)
            )
            return (
                [],
                ["liquidity retention RPC deadline exceeded"],
                False,
                requested_to,
                {
                    "query_scope_complete": False,
                    "query_count": 1,
                    "scope_batch_count": scope_count,
                    "query_chunk_count": 1,
                    "expected_query_count": scope_count,
                    "v4_manager_count": 1,
                    "event_filter_count": 6,
                    "applicable": True,
                    "active": False,
                    "requested_to_block": requested_to,
                    "selected_to_block": requested_to,
                    "attempt_count": 1,
                    "retry_window_blocks": 8,
                    "deadline_exceeded": True,
                    "complete_selected_window": False,
                    "complete_requested_window": False,
                },
            )

        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=deadline,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                return_value=self._hash("a"),
            ),
            mock.patch.dict(
                os.environ,
                {"ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0"},
            ),
        ):
            flow, next_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=130,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=state,
            )

        self.assertFalse(flow["selected_window_complete"])
        self.assertTrue(flow["incremental_catchup"]["deadline_exceeded"])
        self.assertIsNotNone(next_state)
        assert next_state is not None
        self.assertEqual(next_state["latest_block"], 120)
        self.assertEqual(next_state["latest_block_hash"], self._hash("a"))
        self.assertEqual(next_state["next_catchup_window_blocks"], 8)
        self.assertEqual(next_state["reconciliation"], reconciliation)

    def test_bounded_liquidity_default_reaches_eight_block_window(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": self._address("1"),
            "token1": self._address("2"),
            "fee": 3000,
        }
        ranges: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            dict[str, object],
        ]:
            ranges.append((from_block, to_block))
            return (
                [],
                [],
                to_block - from_block + 1 > 8,
                {"query_scope_complete": True},
            )

        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "32",
                },
            ),
        ):
            os.environ.pop(
                "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS",
                None,
            )
            _, errors, truncated, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc", [pool], 1, 32
                )
            )

        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(selected_to, 8)
        self.assertEqual(ranges, [(1, 32), (1, 16), (1, 8)])
        self.assertEqual(metadata["raw_truncation_shrink_count"], 2)

    def test_historical_liquidity_overflow_does_not_throttle_coverage(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": self._address("2"),
            "fee": 2500,
        }

        def fetch(
            _chain: str,
            _pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            dict[str, object],
        ]:
            return (
                [
                    {
                        "address": pool["address"],
                        "blockNumber": hex(block),
                        "blockHash": self._hash("f"),
                        "logIndex": "0x0",
                        "transactionHash": "0x" + f"{block:064x}",
                        "topics": [holder.V3_SWAP_TOPIC],
                        "data": self._data(100, -1, 0, 0, 0),
                        "removed": False,
                        "_retention_pool": pool,
                        "_retention_event_kind": "v3_swap",
                    }
                    for block in range(from_block, to_block + 1)
                ],
                [],
                False,
                {"query_scope_complete": True},
            )

        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_MAX_EVENTS": "4",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "16",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
        ):
            logs, errors, truncated, selected_to, metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    1,
                    16,
                    token=token,
                    decimals=0,
                    supply_raw=10_000,
                    alert_from_block=17,
                )
            )

        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(len(logs), 16)
        self.assertEqual(selected_to, 16)
        self.assertEqual(metadata["attempt_count"], 1)
        self.assertEqual(metadata["historical_event_count"], 16)
        self.assertTrue(metadata["historical_events_truncated"])
        self.assertFalse(metadata["alert_events_truncated"])
        self.assertTrue(metadata["complete_requested_window"])

    def test_liquidity_catchup_reuses_last_successful_window(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": self._address("2"),
            "fee": 2500,
        }
        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            _pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            dict[str, object],
        ]:
            calls.append((from_block, to_block))
            return (
                [
                    {
                        "address": pool["address"],
                        "blockNumber": hex(block),
                        "blockHash": self._hash("f"),
                        "logIndex": "0x0",
                        "transactionHash": "0x" + f"{block:064x}",
                        "topics": [holder.V3_SWAP_TOPIC],
                        "data": self._data(100, -1, 0, 0, 0),
                        "removed": False,
                        "_retention_pool": pool,
                        "_retention_event_kind": "v3_swap",
                    }
                    for block in range(from_block, to_block + 1)
                ],
                [],
                False,
                {"query_scope_complete": True},
            )

        with (
            mock.patch.object(
                holder,
                "targeted_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_MAX_EVENTS": "4",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MAX_BLOCKS": "16",
                    "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS": "1",
                },
            ),
        ):
            _, _, _, first_to, first_metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    1,
                    16,
                    token=token,
                    decimals=0,
                    supply_raw=10_000,
                    alert_from_block=1,
                )
            )
            calls.clear()
            _, _, _, second_to, second_metadata = (
                holder.bounded_retention_liquidity_logs(
                    "bsc",
                    [pool],
                    first_to + 1,
                    16,
                    token=token,
                    decimals=0,
                    supply_raw=10_000,
                    alert_from_block=1,
                    preferred_window_blocks=first_metadata[
                        "next_window_blocks"
                    ],
                )
            )

        self.assertEqual(first_to, 4)
        self.assertEqual(first_metadata["next_window_blocks"], 8)
        self.assertEqual(calls, [(5, 12), (5, 8)])
        self.assertEqual(second_to, 8)
        self.assertEqual(second_metadata["attempt_count"], 2)
        self.assertEqual(second_metadata["next_window_blocks"], 8)

    def test_liquidity_log_identity_errors_and_provider_cap_fail_closed(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": self._address("1"),
            "token1": self._address("2"),
            "fee": 2500,
        }
        base = {
            "address": pool["address"],
            "blockNumber": hex(105),
            "blockHash": self._hash("f"),
            "logIndex": hex(1),
            "transactionHash": self._hash("a"),
            "topics": [
                holder.V3_SWAP_TOPIC,
                holder.topic_address(self._address("b")),
                holder.topic_address(self._address("c")),
            ],
            "data": self._data(1, -1, 0, 0, 0),
            "removed": False,
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[{**base, "removed": "false"}],
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)
        self.assertFalse(metadata["range_shrink_retryable"])

        with mock.patch.object(
            holder,
            "rpc_call",
            side_effect=RuntimeError("provider unavailable"),
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)
        self.assertTrue(metadata["range_shrink_retryable"])

        conflicting_block_hash = {
            **base,
            "blockHash": self._hash("e"),
            "logIndex": hex(2),
            "transactionHash": self._hash("b"),
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[base, conflicting_block_hash],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(
            any("block hash conflict" in error for error in errors)
        )
        self.assertFalse(truncated)

        bare_quantity = {
            **base,
            "blockNumber": "105",
            "logIndex": "1",
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[bare_quantity],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 0x100, 0x110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)

        overflow_static = {
            **base,
            "data": self._data(1, -1, 2**200, 0, 0),
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[overflow_static],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)

        conflict = {**base, "data": "0x" + "1" + "0" * (5 * 64 - 1)}
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[base, conflict],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_PROVIDER_MAX_ROWS_PER_QUERY": "1"
                },
            ),
            mock.patch.object(holder, "rpc_call", return_value=[base]),
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertTrue(truncated)

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_PROVIDER_MAX_ROWS_PER_QUERY": "10000"
                },
            ),
            mock.patch.object(holder, "rpc_call", return_value=[]),
        ):
            logs, errors, truncated, metadata = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(
            metadata["provider_row_limit"],
            holder.LIQUIDITY_PROVIDER_ROW_LIMIT_HARD_CAP,
        )

        v4_pool = {
            "protocol": "v4_cl",
            "address": self._address("5"),
            "pool_id": self._hash("6"),
            "v4_manager_type": "cl",
            "token0": self._address("1"),
            "token1": self._address("2"),
        }
        malformed_v4 = {
            **base,
            "address": v4_pool["address"],
            "topics": [
                holder.V4_SWAP_TOPIC,
                v4_pool["pool_id"],
                holder.topic_address(self._address("c")),
            ],
            "data": (
                "0x"
                + f"{(1 << 128) - 1:064x}"
                + self._word(1, 128)
                + "0" * (5 * 64)
            ),
        }
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[malformed_v4],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [v4_pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)

        wrong_pool_id = copy.deepcopy(malformed_v4)
        wrong_pool_id["topics"][1] = self._hash("d")
        wrong_pool_id["data"] = self._data(
            (-1, 128),
            (1, 128),
            0,
            0,
            0,
            0,
            0,
        )
        with mock.patch.object(
            holder,
            "rpc_call",
            return_value=[wrong_pool_id],
        ):
            logs, errors, truncated, _ = (
                holder.targeted_retention_liquidity_logs(
                    "bsc", [v4_pool], 101, 110
                )
            )
        self.assertEqual(logs, [])
        self.assertTrue(errors)
        self.assertFalse(truncated)

    def test_v3_and_v4_swap_signs_emit_only_verified_sell_pressure(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        v3 = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": quote,
            "fee": 2500,
        }
        v4 = {
            "protocol": "v4_cl",
            "address": self._address("5"),
            "pool_id": self._hash("6"),
            "v4_manager_type": "cl",
            "token0": token,
            "token1": quote,
        }
        logs = [
            self._event_row(
                pool=v3,
                event_kind="v3_swap",
                topic=holder.V3_SWAP_TOPIC,
                data=self._data(1000, -100, 0, 0, 0),
                tx_digit="a",
                block=101,
                index=1,
            ),
            self._event_row(
                pool=v3,
                event_kind="v3_swap",
                topic=holder.V3_SWAP_TOPIC,
                data=self._data(-1000, 100, 0, 0, 0),
                tx_digit="b",
                block=102,
                index=2,
            ),
            self._event_row(
                pool=v4,
                event_kind="v4_swap",
                topic=holder.V4_SWAP_TOPIC,
                data=self._data((-1000, 128), (100, 128), 0, 0, 0, 0, 0),
                tx_digit="c",
                block=103,
                index=3,
            ),
            self._event_row(
                pool=v4,
                event_kind="v4_swap",
                topic=holder.V4_SWAP_TOPIC,
                data=self._data((1000, 128), (-100, 128), 0, 0, 0, 0, 0),
                tx_digit="d",
                block=104,
                index=4,
            ),
        ]
        events, count, truncated = holder.retention_liquidity_events(
            logs,
            token,
            0,
            1_000_000,
        )
        self.assertFalse(truncated)
        self.assertEqual(count, 2)
        self.assertEqual(
            [event["protocol"] for event in events],
            ["v3", "v4_cl"],
        )
        self.assertTrue(
            all(
                event["type"] == "verified_pool_sell_pressure"
                and event["direction"] == "verified_pool_sell"
                for event in events
            )
        )

    def test_v3_burn_nets_mint_and_collect_stays_observation(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": self._address("2"),
            "quote_token": self._address("2"),
            "quote_decimals": 0,
            "quote_symbol": "USDT",
            "fee": 2500,
        }
        rows = [
            self._event_row(
                pool=pool,
                event_kind="v3_swap",
                topic=holder.V3_SWAP_TOPIC,
                data=self._data(100, -10, 0, 0, 0),
                tx_digit="a",
                block=101,
                index=1,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_mint",
                topic=holder.V3_MINT_TOPIC,
                data=self._data(0, 0, 100, 20_000),
                tx_digit="a",
                block=101,
                index=2,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 600, 0),
                tx_digit="a",
                block=101,
                index=3,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 600, 100_000),
                tx_digit="a",
                block=101,
                index=4,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 600, 0),
                tx_digit="b",
                block=102,
                index=5,
            ),
        ]
        events, _, _ = holder.retention_liquidity_events(
            rows,
            token,
            0,
            10_000,
        )
        self.assertEqual(
            [event["type"] for event in events],
            ["liquidity_rebalance_with_sell", "lp_collect_observation"],
        )
        self.assertEqual(events[0]["amount"], "100")
        self.assertEqual(events[0]["lp_removed_amount"], "500")
        self.assertEqual(events[0]["level"], "HIGH")
        self.assertEqual(
            events[0]["evidence_level"],
            "verified_pool_swap_and_v3_mint_burn_rebalance_same_tx",
        )
        self.assertEqual(events[0]["quote_collected_amount"], "100000")
        self.assertIn(
            "100000.0000 USDT",
            holder.retention_event_amount_text(events[0]),
        )
        self.assertEqual(events[1]["level"], "INFO")

    def test_v3_quote_only_removal_collect_and_rebalance_are_visible(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": quote,
            "quote_token": quote,
            "quote_decimals": 0,
            "quote_symbol": "USDT",
            "fee": 2500,
        }
        rows = [
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="a",
                block=101,
                index=1,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="a",
                block=101,
                index=2,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="b",
                block=102,
                index=3,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_mint",
                topic=holder.V3_MINT_TOPIC,
                data=self._data(0, 0, 0, 200),
                tx_digit="c",
                block=103,
                index=4,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="c",
                block=103,
                index=5,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="c",
                block=103,
                index=6,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 1, 0),
                tx_digit="d",
                block=104,
                index=7,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_collect",
                topic=holder.V3_COLLECT_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="d",
                block=104,
                index=8,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_mint",
                topic=holder.V3_MINT_TOPIC,
                data=self._data(0, 0, 100, 50),
                tx_digit="e",
                block=105,
                index=9,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="e",
                block=105,
                index=10,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_mint",
                topic=holder.V3_MINT_TOPIC,
                data=self._data(0, 0, 0, 1),
                tx_digit="f",
                block=106,
                index=11,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_burn",
                topic=holder.V3_BURN_TOPIC,
                data=self._data(0, 0, 200),
                tx_digit="f",
                block=106,
                index=12,
            ),
        ]
        with mock.patch.dict(
            os.environ,
            {"ALPHA_RETENTION_LIQUIDITY_QUOTE_MIN_AMOUNT": "100"},
        ):
            events, _, _ = holder.retention_liquidity_events(
                rows,
                token,
                0,
                10_000,
            )

        self.assertEqual(
            [event["type"] for event in events],
            [
                "lp_remove_observation",
                "lp_collect_observation",
                "lp_rebalance_collect_observation",
                "lp_collect_observation",
                "lp_rebalance_observation",
                "lp_partial_remove_observation",
            ],
        )
        self.assertEqual(events[0]["amount"], "")
        self.assertEqual(events[0]["quote_removed_amount"], "200")
        self.assertEqual(events[0]["level"], "HIGH")
        self.assertIn(
            "200.0000 USDT",
            holder.retention_event_amount_text(events[0]),
        )
        self.assertEqual(events[1]["quote_collected_amount"], "200")
        self.assertEqual(
            events[2]["direction"],
            "liquidity_rebalance_collect",
        )
        self.assertEqual(events[3]["quote_collected_amount"], "200")
        self.assertEqual(events[4]["level"], "INFO")
        self.assertEqual(
            events[4]["direction"],
            "liquidity_rebalance",
        )
        self.assertEqual(events[5]["level"], "HIGH")
        self.assertEqual(
            events[5]["direction"],
            "liquidity_partial_remove",
        )
        self.assertEqual(events[5]["quote_removed_amount"], "199")

    def test_v3_positions_do_not_net_across_owner_and_tick_range(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": quote,
            "quote_token": quote,
            "quote_decimals": 0,
            "quote_symbol": "USDT",
            "fee": 3000,
        }
        owner_one = self._address("5")
        owner_two = self._address("6")

        def position_row(
            event_kind: str,
            owner: str,
            data: str,
            index: int,
        ) -> dict[str, object]:
            topic = {
                "v3_mint": holder.V3_MINT_TOPIC,
                "v3_burn": holder.V3_BURN_TOPIC,
            }[event_kind]
            row = self._event_row(
                pool=pool,
                event_kind=event_kind,
                topic=topic,
                data=data,
                tx_digit="a",
                block=101,
                index=index,
            )
            row["topics"] = [
                topic,
                holder.topic_address(owner),
                "0x" + self._word(-100, 24),
                "0x" + self._word(100, 24),
            ]
            return row

        rows = [
            position_row(
                "v3_burn",
                owner_one,
                self._data(1, 100, 20_000),
                1,
            ),
            position_row(
                "v3_mint",
                owner_one,
                self._data(0, 1, 100, 20_000),
                2,
            ),
            position_row(
                "v3_burn",
                owner_two,
                self._data(1, 100, 20_000),
                3,
            ),
        ]
        events, _, _ = holder.retention_liquidity_events(
            rows,
            token,
            0,
            10_000,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "lp_remove_observation")
        self.assertEqual(events[0]["amount"], "100")
        self.assertEqual(events[0]["lp_owner"], owner_two)
        self.assertEqual(events[0]["tick_lower"], -100)
        self.assertEqual(events[0]["tick_upper"], 100)

    def test_v3_small_mint_is_reconciliation_candidate(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        owner = self._address("5")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": quote,
            "quote_token": quote,
            "quote_decimals": 0,
            "quote_symbol": "USDT",
            "fee": 3000,
        }
        row = self._event_row(
            pool=pool,
            event_kind="v3_mint",
            topic=holder.V3_MINT_TOPIC,
            data=self._data(0, 1, 1, 1),
            tx_digit="a",
            block=101,
            index=1,
        )
        row["topics"] = [
            holder.V3_MINT_TOPIC,
            holder.topic_address(owner),
            "0x" + self._word(-100, 24),
            "0x" + self._word(100, 24),
        ]
        events, _, _ = holder.retention_liquidity_events(
            [row], token, 0, 1_000_000
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "lp_add_observation")
        self.assertEqual(events[0]["lp_added_amount_raw"], "1")
        self.assertEqual(events[0]["lp_owner"], owner)

    def test_v3_operator_rpc_failure_is_explicit(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        direct_owner_event = {
            "protocol": "v3",
            "pool": self._address("3"),
            "tx": self._hash("b"),
            "log_index": 1,
            "block": 100,
            "type": "lp_remove_observation",
            "lp_owner": self._address("5"),
            "historical_catchup": False,
        }
        with mock.patch.object(
            holder,
            "holder_rpc_call",
            return_value="0x",
        ):
            direct, direct_errors = (
                holder.annotate_liquidity_event_operators(
                    "bsc", [direct_owner_event]
                )
            )
        self.assertEqual(direct_errors, 0)
        self.assertEqual(
            direct[0]["liquidity_operator_basis"],
            "pool_event_owner_eoa",
        )

        position_manager = (
            "0x7b8a01b39d58278b5de7e48c8449c9f4f5170613"
        )
        event = {
            "protocol": "v3",
            "pool": self._address("3"),
            "tx": self._hash("a"),
            "log_index": 1,
            "type": "lp_remove_observation",
            "lp_owner": position_manager,
            "historical_catchup": False,
        }
        with mock.patch.object(
            holder,
            "holder_rpc_call",
            side_effect=RuntimeError("provider unavailable"),
        ):
            annotated, error_count = (
                holder.annotate_liquidity_event_operators(
                    "bsc", [event]
                )
            )

        self.assertEqual(error_count, 1)
        self.assertEqual(
            annotated[0]["liquidity_operator_basis"],
            "unattributed",
        )
        self.assertEqual(annotated[0]["liquidity_operator"], "")

    def test_v3_reconciliation_migrates_then_expires_net_removal(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        source_pool = self._address("3")
        destination_pool = self._address("4")
        operator = self._address("5")
        quote = self._address("2")
        started = datetime(2026, 8, 4, tzinfo=timezone.utc)

        removal = {
            "protocol": "v3",
            "pool": source_pool,
            "tx": self._hash("a"),
            "log_index": 1,
            "block": 101,
            "type": "lp_remove_observation",
            "level": "HIGH",
            "lp_owner": self._address("6"),
            "tick_lower": -100,
            "tick_upper": 100,
            "liquidity_operator": operator,
            "liquidity_operator_basis": "transaction_sender_eoa",
            "liquidity_operator_confidence": "high",
            "liquidity_operator_class": "unlabeled_address",
            "quote_token": quote,
            "quote_symbol": "USDT",
            "quote_decimals": 0,
            "lp_removed_amount_raw": "100",
            "quote_removed_amount_raw": "20000",
            "historical_catchup": False,
            "alert_eligible": True,
        }
        add = {
            **removal,
            "pool": destination_pool,
            "tx": self._hash("b"),
            "log_index": 2,
            "block": 102,
            "type": "lp_add_observation",
            "level": "INFO",
            "lp_added_amount_raw": "100",
            "quote_added_amount_raw": "20000",
        }
        first_events, first_state, first_metadata = (
            holder.reconcile_liquidity_events(
                [removal], {}, token_decimals=0, observed_at=started
            )
        )
        historical_add = {
            **add,
            "block": 100,
            "historical_catchup": True,
        }
        historical_events, historical_state, _ = (
            holder.reconcile_liquidity_events(
                [historical_add],
                first_state,
                token_decimals=0,
                observed_at=started + timedelta(minutes=2),
            )
        )
        self.assertEqual(
            historical_state["pending"][0]["added_target_raw"],
            0,
        )
        self.assertFalse(historical_events[0]["alert_eligible"])
        second_events, second_state, _ = holder.reconcile_liquidity_events(
            [add],
            historical_state,
            token_decimals=0,
            observed_at=started + timedelta(minutes=4),
        )
        provisional_events, provisional_state, provisional_metadata = (
            holder.reconcile_liquidity_events(
                [],
                second_state,
                token_decimals=0,
                observed_at=started + timedelta(minutes=6),
            )
        )

        self.assertFalse(first_events[0]["alert_eligible"])
        self.assertEqual(first_metadata["pending_count"], 1)
        self.assertEqual(second_events[0]["type"], "lp_add_observation")
        self.assertFalse(second_events[0]["alert_eligible"])
        self.assertEqual(provisional_events, [])
        self.assertEqual(provisional_metadata["pending_count"], 1)
        final_events, final_state, final_metadata = (
            holder.reconcile_liquidity_events(
                [],
                provisional_state,
                token_decimals=0,
                observed_at=started + timedelta(minutes=15),
            )
        )
        self.assertEqual(final_events[0]["classification"], "migrated")
        self.assertEqual(
            final_events[0]["destination_pool"], destination_pool
        )
        self.assertEqual(final_events[0]["level"], "INFO")
        self.assertTrue(final_events[0]["notify"])
        self.assertEqual(final_metadata["pending_count"], 0)
        self.assertEqual(final_state["pending"], [])

        expired_events, expired_state, _ = (
            holder.reconcile_liquidity_events(
                [
                    {
                        **removal,
                        "tx": self._hash("c"),
                        "log_index": 3,
                    }
                ],
                {},
                token_decimals=0,
                observed_at=started,
            )
        )
        self.assertFalse(expired_events[0]["alert_eligible"])
        blocked_events, blocked_state, blocked_metadata = (
            holder.reconcile_liquidity_events(
                [],
                expired_state,
                token_decimals=0,
                observed_at=started + timedelta(minutes=15),
                coverage_complete=False,
            )
        )
        self.assertEqual(blocked_events, [])
        self.assertEqual(len(blocked_state["pending"]), 1)
        self.assertFalse(blocked_metadata["finalization_eligible"])
        net_events, _, _ = holder.reconcile_liquidity_events(
            [],
            blocked_state,
            token_decimals=0,
            observed_at=started + timedelta(minutes=15),
        )
        self.assertEqual(net_events[0]["classification"], "net_removed")
        self.assertEqual(net_events[0]["level"], "HIGH")

        _, partial_state, _ = holder.reconcile_liquidity_events(
            [
                {
                    **removal,
                    "tx": self._hash("e"),
                    "log_index": 5,
                }
            ],
            {},
            token_decimals=0,
            observed_at=started,
        )
        _, partial_state, _ = holder.reconcile_liquidity_events(
            [
                {
                    **add,
                    "tx": self._hash("f"),
                    "log_index": 6,
                    "lp_added_amount_raw": "100",
                    "quote_added_amount_raw": "0",
                }
            ],
            partial_state,
            token_decimals=0,
            observed_at=started + timedelta(minutes=4),
        )
        partial_events, _, _ = holder.reconcile_liquidity_events(
            [],
            partial_state,
            token_decimals=0,
            observed_at=started + timedelta(minutes=15),
        )
        self.assertEqual(
            partial_events[0]["classification"], "net_removed"
        )
        self.assertEqual(partial_events[0]["restored_ratio"], "0")

        sold_events, _, _ = holder.reconcile_liquidity_events(
            [
                {
                    **removal,
                    "tx": self._hash("d"),
                    "log_index": 4,
                    "type": "liquidity_exit_with_sell",
                }
            ],
            {},
            token_decimals=0,
            observed_at=started,
        )
        self.assertEqual(
            sold_events[0]["classification"],
            "removed_plus_sold",
        )

    def test_v4_modify_is_unattributed_or_combined_with_verified_sell(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        pool = {
            "protocol": "v4_cl",
            "address": self._address("5"),
            "pool_id": self._hash("6"),
            "v4_manager_type": "cl",
            "token0": token,
            "token1": self._address("2"),
        }
        rows = [
            self._event_row(
                pool=pool,
                event_kind="v4_swap",
                topic=holder.V4_SWAP_TOPIC,
                data=self._data((-1000, 128), (100, 128), 0, 0, 0, 0, 0),
                tx_digit="a",
                block=101,
                index=1,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, -5, 0),
                tx_digit="a",
                block=101,
                index=2,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, 5, 0),
                tx_digit="a",
                block=101,
                index=3,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, -7, 0),
                tx_digit="b",
                block=102,
                index=4,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, 7, 0),
                tx_digit="c",
                block=103,
                index=5,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, -100_000, 0),
                tx_digit="d",
                block=104,
                index=6,
            ),
            self._event_row(
                pool=pool,
                event_kind="v4_modify_liquidity",
                topic=holder.MODIFY_LIQUIDITY_TOPIC,
                data=self._data(0, 0, 1, 0),
                tx_digit="d",
                block=104,
                index=7,
            ),
        ]
        events, _, _ = holder.retention_liquidity_events(
            rows,
            token,
            0,
            1_000_000,
        )
        self.assertEqual(events[0]["type"], "liquidity_rebalance_with_sell")
        self.assertEqual(events[0]["level"], "HIGH")
        self.assertEqual(
            events[0]["direction"],
            "liquidity_rebalance_and_sell",
        )
        self.assertEqual(events[1]["type"], "lp_remove_observation")
        self.assertEqual(events[1]["level"], "INFO")
        self.assertEqual(events[1]["amount"], "")
        self.assertEqual(events[2]["type"], "lp_partial_remove_observation")
        self.assertEqual(events[2]["liquidity_delta"], "-99999")
        self.assertEqual(events[2]["liquidity_added"], "1")
        self.assertNotIn("dealer", json.dumps(events).lower())

    def test_liquidity_cursor_rebaseline_then_advances_previous_plus_one(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        token = self._address("1")
        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
            **_event_scope: object,
        ) -> tuple[list[dict[str, object]], list[str], bool, int, dict[str, object]]:
            calls.append((from_block, to_block))
            scope_count = len(holder.retention_liquidity_query_scopes(pools))
            return (
                [],
                [],
                False,
                to_block,
                {
                    "query_scope_complete": True,
                    "query_count": scope_count,
                    "scope_batch_count": scope_count,
                    "query_chunk_count": 1,
                    "expected_query_count": scope_count,
                    "v4_manager_count": len(
                        {
                            pool["address"]
                            for pool in pools
                            if pool.get("protocol") == "v4_cl"
                        }
                    ),
                    "event_filter_count": sum(
                        4 if pool.get("protocol") == "v3" else 2
                        for pool in pools
                    ),
                    "applicable": True,
                    "active": False,
                    "requested_to_block": to_block,
                    "selected_to_block": to_block,
                    "attempt_count": 1,
                    "complete_selected_window": True,
                    "complete_requested_window": True,
                },
            )

        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "opening_time_utc": "2026-07-30T00:00:00+00:00",
            "age_hours": 1,
        }
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                return_value=self._hash("e"),
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_BOOTSTRAP_BLOCKS": "10",
                    "ALPHA_RETENTION_LIQUIDITY_SCOPE_CHANGE_RESCAN_BLOCKS": "10",
                    "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0",
                },
            ),
        ):
            first, first_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=120,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state={},
            )
            assert first_state is not None
            second, second_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=130,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=first_state,
            )
            assert second_state is not None
            payload["events"][0]["opening_v3_pool_scope"][
                "pools"
            ].append(
                {
                    "address": self._address("d"),
                    "factory": self._address("4"),
                    "token0": token,
                    "token1": self._address("2"),
                    "fee": 3000,
                }
            )
            third, third_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=1000,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=second_state,
            )
            assert third_state is not None
            payload["events"][0]["opening_v3_pool_scope"][
                "pools"
            ].pop()
            shrink, shrink_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=1010,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=third_state,
            )

        self.assertEqual(calls, [(111, 120), (121, 130), (991, 1000)])
        self.assertTrue(first["scope_rebaseline"])
        self.assertFalse(first["continuous"])
        self.assertFalse(second["scope_rebaseline"])
        self.assertTrue(second["continuous"])
        self.assertEqual(second["previous_latest_block"], 120)
        self.assertEqual(second["latest_block"], 130)
        self.assertEqual(second["latest_block_hash"], self._hash("e"))
        self.assertIsNotNone(second_state)
        self.assertTrue(third["scope_rebaseline"])
        self.assertTrue(third["scope_changed"])
        self.assertEqual(third["scan_from_block"], 991)
        self.assertEqual(third["alert_from_block"], 991)
        self.assertIsNotNone(third_state)
        self.assertEqual(shrink["status"], "coverage_gap")
        self.assertEqual(
            shrink["reason"],
            "liquidity_scope_not_strict_expansion",
        )
        self.assertIsNone(shrink_state)

    def test_selected_catchup_window_can_deliver_only_live_events(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        token = self._address("1")
        quote = self._address("2")
        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": token,
            "token1": quote,
            "quote_token": quote,
            "quote_decimals": 18,
            "quote_symbol": "WBNB",
            "fee": 2500,
        }
        logs = [
            self._event_row(
                pool=pool,
                event_kind="v3_swap",
                topic=holder.V3_SWAP_TOPIC,
                data=self._data(100, -1, 0, 0, 0),
                tx_digit="a",
                block=100,
                index=1,
            ),
            self._event_row(
                pool=pool,
                event_kind="v3_swap",
                topic=holder.V3_SWAP_TOPIC,
                data=self._data(100, -1, 0, 0, 0),
                tx_digit="b",
                block=106,
                index=2,
            ),
        ]
        coverage = {
            "query_scope_complete": True,
            "query_count": 1,
            "scope_batch_count": 1,
            "query_chunk_count": 1,
            "expected_query_count": 1,
            "v4_manager_count": 0,
            "event_filter_count": 4,
            "applicable": True,
            "active": True,
            "requested_to_block": 110,
            "selected_to_block": 108,
            "attempt_count": 1,
            "complete_selected_window": True,
            "complete_requested_window": False,
        }
        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "age_hours": 1,
        }
        with mock.patch.object(
            holder,
            "retention_window",
            return_value=active,
        ):
            flow = holder.build_liquidity_retention(
                item={"chain": "bsc"},
                token=token,
                pools=[pool],
                scope_hash="c" * 64,
                previous_scope_hash="c" * 64,
                scope_rebaseline=False,
                previous_catchup_active=True,
                scope_coverage_from_block=1,
                logs=logs,
                errors=[],
                truncated=False,
                decimals=0,
                supply_raw=10_000,
                scan_from_block=100,
                scan_to_block=108,
                target_scan_to_block=110,
                previous_latest_block=99,
                coverage_metadata=coverage,
                alert_from_block=105,
            )
        flow.update(
            {
                "observed_latest_block": 112,
                "confirmation_blocks": 2,
                "latest_block_hash": self._hash("f"),
            }
        )
        project = {
            "retention_flow": {"liquidity_retention": flow}
        }

        self.assertFalse(flow["complete"])
        self.assertFalse(
            holder.liquidity_retention_alert_coverage_complete(project)
        )
        self.assertTrue(
            holder.liquidity_selected_window_alert_coverage_complete(
                project
            )
        )
        self.assertTrue(flow["events"][0]["historical_catchup"])
        self.assertFalse(flow["events"][1]["historical_catchup"])
        alerts = holder.retention_alert_events(project)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["block"], 106)

    def test_existing_catchup_migrates_and_persists_live_watermark(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        token = self._address("1")
        scope = holder.opening_verified_pool_scope(
            payload,
            "TEST",
            "bsc",
            token,
        )
        state = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": scope["scope_hash"],
            "pool_scope": scope["pool_scope"],
            "pool_count": scope["pool_count"],
            "scope_coverage_from_block": 100,
            "latest_block": 120,
            "latest_block_hash": self._hash("f"),
            "catchup_active": True,
        }
        calls: list[tuple[int, int]] = []

        def bounded(
            _chain: str,
            pools: list[dict[str, object]],
            from_block: int,
            requested_to: int,
            **kwargs: object,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            int,
            dict[str, object],
        ]:
            calls.append(
                (
                    int(kwargs["alert_from_block"]),
                    int(kwargs["preferred_window_blocks"]),
                )
            )
            selected_to = min(requested_to, from_block + 3)
            scope_count = len(
                holder.retention_liquidity_query_scopes(pools)
            )
            return (
                [],
                [],
                False,
                selected_to,
                {
                    "query_scope_complete": True,
                    "query_count": scope_count,
                    "scope_batch_count": scope_count,
                    "query_chunk_count": 1,
                    "expected_query_count": scope_count,
                    "v4_manager_count": 1,
                    "event_filter_count": 6,
                    "applicable": True,
                    "active": selected_to < requested_to,
                    "requested_to_block": requested_to,
                    "selected_to_block": selected_to,
                    "attempt_count": 1,
                    "next_window_blocks": 4,
                    "complete_selected_window": True,
                    "complete_requested_window": (
                        selected_to == requested_to
                    ),
                },
            )

        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "age_hours": 1,
        }
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=bounded,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                return_value=self._hash("f"),
            ),
            mock.patch.dict(
                os.environ,
                {"ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0"},
            ),
        ):
            first, first_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=130,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=state,
            )
            assert first_state is not None
            second, second_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=140,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=first_state,
            )

        self.assertEqual(calls, [(131, 0), (131, 4)])
        self.assertTrue(first["alert_watermark_reinitialized"])
        self.assertFalse(second["alert_watermark_reinitialized"])
        self.assertEqual(first_state["catchup_live_from_block"], 131)
        self.assertEqual(first_state["next_catchup_window_blocks"], 4)
        self.assertIsNotNone(second_state)

    def test_liquidity_checkpoint_hash_change_rescans_overlap(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        payload = self._opening_payload()
        token = self._address("1")
        scope = holder.opening_verified_pool_scope(
            payload,
            "TEST",
            "bsc",
            token,
        )
        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
            **_event_scope: object,
        ) -> tuple[list[dict[str, object]], list[str], bool, int, dict[str, object]]:
            calls.append((from_block, to_block))
            scope_count = len(holder.retention_liquidity_query_scopes(pools))
            return (
                [],
                [],
                False,
                to_block,
                {
                    "query_scope_complete": True,
                    "query_count": scope_count,
                    "scope_batch_count": scope_count,
                    "query_chunk_count": 1,
                    "expected_query_count": scope_count,
                    "v4_manager_count": 1,
                    "event_filter_count": 6,
                    "applicable": True,
                    "active": False,
                    "requested_to_block": to_block,
                    "selected_to_block": to_block,
                    "attempt_count": 1,
                    "complete_selected_window": True,
                    "complete_requested_window": True,
                },
            )

        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "opening_time_utc": "2026-07-30T00:00:00+00:00",
            "age_hours": 1,
        }
        state = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": scope["scope_hash"],
            "pool_scope": scope["pool_scope"],
            "scope_coverage_from_block": 100,
            "latest_block": 120,
            "latest_block_hash": self._hash("a"),
            "catchup_active": False,
        }
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=[
                    self._hash("b"),
                    self._hash("c"),
                    self._hash("c"),
                ],
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0",
                    "ALPHA_RETENTION_LIQUIDITY_REORG_RESCAN_BLOCKS": "10",
                },
            ),
        ):
            flow, next_state = holder.build_token_liquidity_retention(
                item={"chain": "bsc"},
                symbol="TEST",
                chain="bsc",
                token=token,
                tip=130,
                decimals=18,
                supply_raw=10**24,
                opening_payload=payload,
                liquidity_state=state,
            )

        self.assertEqual(calls, [(111, 130)])
        self.assertTrue(flow["checkpoint_reorg_recovery"])
        self.assertTrue(flow["continuous"])
        self.assertEqual(flow["previous_latest_block"], 110)
        self.assertEqual(flow["alert_from_block"], 111)
        self.assertEqual(flow["latest_block_hash"], self._hash("c"))
        self.assertIsNotNone(next_state)
        assert next_state is not None
        self.assertEqual(next_state["latest_block_hash"], self._hash("c"))

        pending_reorg_state = {
            **state,
            "scope_coverage_from_block": 90,
            "reconciliation": {
                "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
                "pending": [{"source_block": 100}],
                "completed": [],
                "deferred_events": [],
            },
        }
        calls.clear()
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=[
                    self._hash("b"),
                    self._hash("c"),
                    self._hash("c"),
                ],
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0",
                    "ALPHA_RETENTION_LIQUIDITY_REORG_RESCAN_BLOCKS": "10",
                },
            ),
        ):
            pending_reorg_flow, pending_reorg_next_state = (
                holder.build_token_liquidity_retention(
                    item={"chain": "bsc"},
                    symbol="TEST",
                    chain="bsc",
                    token=token,
                    tip=130,
                    decimals=18,
                    supply_raw=10**24,
                    opening_payload=payload,
                    liquidity_state=pending_reorg_state,
                )
            )
        self.assertEqual(calls, [(100, 130)])
        self.assertTrue(pending_reorg_flow["checkpoint_reorg_recovery"])
        self.assertIsNotNone(pending_reorg_next_state)
        assert pending_reorg_next_state is not None
        self.assertEqual(
            pending_reorg_next_state["reconciliation"]["pending"],
            [],
        )

        catchup_state = {
            **state,
            "catchup_active": True,
            "catchup_live_from_block": 119,
        }
        calls.clear()
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=[
                    self._hash("b"),
                    self._hash("c"),
                    self._hash("c"),
                ],
            ),
            mock.patch.dict(
                os.environ,
                {
                    "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0",
                    "ALPHA_RETENTION_LIQUIDITY_REORG_RESCAN_BLOCKS": "10",
                },
            ),
        ):
            catchup_reorg_flow, _ = (
                holder.build_token_liquidity_retention(
                    item={"chain": "bsc"},
                    symbol="TEST",
                    chain="bsc",
                    token=token,
                    tip=130,
                    decimals=18,
                    supply_raw=10**24,
                    opening_payload=payload,
                    liquidity_state=catchup_state,
                )
            )
        self.assertEqual(calls, [(111, 130)])
        self.assertEqual(catchup_reorg_flow["alert_from_block"], 119)

        calls.clear()
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=[
                    self._hash("a"),
                    self._hash("c"),
                    self._hash("c"),
                    self._hash("b"),
                ],
            ),
            mock.patch.dict(
                os.environ,
                {"ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0"},
            ),
        ):
            raced_flow, raced_state = (
                holder.build_token_liquidity_retention(
                    item={"chain": "bsc"},
                    symbol="TEST",
                    chain="bsc",
                    token=token,
                    tip=130,
                    decimals=18,
                    supply_raw=10**24,
                    opening_payload=payload,
                    liquidity_state=state,
                )
            )
        self.assertEqual(calls, [(121, 130)])
        self.assertFalse(raced_flow["selected_window_complete"])
        self.assertTrue(
            any(
                "changed during scan" in error
                for error in raced_flow["log_errors"]
            )
        )
        self.assertIsNone(raced_state)

        calls.clear()
        with (
            mock.patch.object(holder, "retention_window", return_value=active),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=fetch,
            ),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=[
                    self._hash("a"),
                    self._hash("d"),
                    self._hash("c"),
                    self._hash("a"),
                ],
            ),
            mock.patch.dict(
                os.environ,
                {"ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0"},
            ),
        ):
            tip_raced_flow, tip_raced_state = (
                holder.build_token_liquidity_retention(
                    item={"chain": "bsc"},
                    symbol="TEST",
                    chain="bsc",
                    token=token,
                    tip=130,
                    decimals=18,
                    supply_raw=10**24,
                    opening_payload=payload,
                    liquidity_state=state,
                )
            )
        self.assertEqual(calls, [(121, 130)])
        self.assertFalse(tip_raced_flow["selected_window_complete"])
        self.assertIn(
            "liquidity confirmed tip changed during scan",
            tip_raced_flow["log_errors"],
        )
        self.assertIsNone(tip_raced_state)

    def test_liquidity_alert_and_health_gates_are_independent(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        from scripts.runtime_health_watch import (
            liquidity_retention_coverage_issue,
            liquidity_retention_coverage_warning,
            retention_flow_required,
        )

        pool = {
            "protocol": "v3",
            "address": self._address("3"),
            "factory": self._address("4"),
            "token0": self._address("1"),
            "token1": self._address("2"),
            "fee": 2500,
        }
        metadata = {
            "query_scope_complete": True,
            "query_count": 1,
            "scope_batch_count": 1,
            "query_chunk_count": 1,
            "expected_query_count": 1,
            "v4_manager_count": 0,
            "event_filter_count": 4,
            "applicable": True,
            "active": False,
            "requested_to_block": 120,
            "selected_to_block": 120,
            "attempt_count": 1,
            "complete_selected_window": True,
            "complete_requested_window": True,
        }
        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "opening_time_utc": "2026-07-30T00:00:00+00:00",
            "age_hours": 1,
        }
        with mock.patch.object(holder, "retention_window", return_value=active):
            flow = holder.build_liquidity_retention(
                item={"chain": "bsc"},
                token=self._address("1"),
                pools=[pool],
                scope_hash="a" * 64,
                previous_scope_hash="a" * 64,
                scope_rebaseline=False,
                previous_catchup_active=False,
                scope_coverage_from_block=100,
                logs=[],
                errors=[],
                truncated=False,
                decimals=18,
                supply_raw=10**24,
                scan_from_block=101,
                scan_to_block=120,
                target_scan_to_block=120,
                previous_latest_block=100,
                coverage_metadata=metadata,
                alert_from_block=101,
            )
        flow.update(
            {
                "observed_latest_block": 120,
                "confirmation_blocks": 0,
                "latest_block_hash": self._hash("f"),
                "checkpoint_reorg_recovery": False,
            }
        )
        event = {
            "type": "verified_pool_sell_pressure",
            "level": "HIGH",
            "pool": pool["address"],
            "tx": self._hash("a"),
            "log_index": 1,
            "historical_catchup": False,
            "alert_eligible": True,
        }
        project = {
            "chain": "bsc",
            "address": self._address("1"),
            "retention_flow": {
                "status": "coverage_gap",
                "events": [],
                "liquidity_retention": {**flow, "events": [event]},
            },
        }
        self.assertTrue(
            holder.liquidity_retention_alert_coverage_complete(project)
        )
        self.assertEqual(holder.retention_alert_events(project), [event])
        self.assertEqual(liquidity_retention_coverage_issue(project), "")
        self.assertEqual(liquidity_retention_coverage_warning(project), "")

        rebaseline = copy.deepcopy(project)
        rebaseline_flow = rebaseline["retention_flow"][
            "liquidity_retention"
        ]
        rebaseline_flow["scope_rebaseline"] = True
        rebaseline_flow["continuous"] = False
        rebaseline_flow["previous_scope_hash"] = "b" * 64
        rebaseline_flow["scope_coverage_from_block"] = 101
        self.assertEqual(
            liquidity_retention_coverage_issue(rebaseline),
            "",
        )
        self.assertIn(
            "baselined",
            liquidity_retention_coverage_warning(rebaseline),
        )

        broken = copy.deepcopy(project)
        broken["retention_flow"]["liquidity_retention"]["query_count"] = 0
        self.assertIn(
            "query count",
            liquidity_retention_coverage_issue(broken),
        )
        current = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.assertFalse(
            retention_flow_required(current + timedelta(seconds=1), current)
        )
        self.assertTrue(
            retention_flow_required(current - timedelta(days=30), current)
        )
        self.assertFalse(
            retention_flow_required(
                current - timedelta(days=30, seconds=1),
                current,
            )
        )

    def test_retention_telegram_batches_only_ack_rendered_events(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder

        project = {
            "symbol": "TEST",
            "priority": "P1_MONITOR",
            "chain": "bsc",
            "address": self._address("1"),
        }
        events = [
            {
                "type": "verified_pool_sell_pressure",
                "level": "HIGH",
                "pool": self._address("3"),
                "tx": "0x" + f"{index:064x}",
                "log_index": index,
                "amount": str(index + 1),
                "evidence_level": "verified_pool_swap_" + "x" * 160,
            }
            for index in range(80)
        ]
        batches = holder.retention_telegram_batches(project, events)

        self.assertGreater(len(batches), 1)
        rendered_events = []
        for text, batch_events in batches:
            self.assertLessEqual(len(text), holder.TELEGRAM_LIMIT)
            self.assertTrue(batch_events)
            rendered_events.extend(batch_events)
            for event in batch_events:
                self.assertIn(holder.short_addr(event["tx"]), text)
        self.assertEqual(rendered_events, events)
        self.assertEqual(
            {
                holder.retention_event_key(project, event)
                for _text, batch_events in batches
                for event in batch_events
            },
            {
                holder.retention_event_key(project, event)
                for event in events
            },
        )

class LiquidityFastLaneRegressionTests(unittest.TestCase):
    @staticmethod
    def _address(digit: str) -> str:
        return "0x" + digit * 40

    @staticmethod
    def _hash(digit: str) -> str:
        return "0x" + digit * 64

    @staticmethod
    def _word(value: int, bits: int = 256) -> str:
        if value < 0:
            value = (1 << bits) + value
            if bits < 256:
                value |= ((1 << (256 - bits)) - 1) << bits
        return f"{value:064x}"

    @classmethod
    def _data(cls, *values: tuple[int, int] | int) -> str:
        return "0x" + "".join(
            cls._word(value[0], value[1])
            if isinstance(value, tuple)
            else cls._word(value)
            for value in values
        )

    @classmethod
    def _opening_payload(cls) -> dict[str, object]:
        return ContinuousLiquidityRetentionRegressionTests._opening_payload()

    @classmethod
    def _event_row(
        cls,
        pool: dict[str, object],
        *,
        block: int,
        tx_digit: str,
    ) -> dict[str, object]:
        return {
            "address": pool["address"],
            "blockNumber": hex(block),
            "blockHash": cls._hash("f"),
            "logIndex": "0x1",
            "transactionHash": cls._hash(tx_digit),
            "topics": [
                "0x"
                + "c42079f94a6350d7e6235f291749249f2d8f"
                "d3f74fc63b6b8f37b6e146156c01"
            ],
            "data": cls._data(100_000, -10, 1, 1, 0),
            "removed": False,
            "_retention_pool": pool,
            "_retention_event_kind": "v3_swap",
        }

    @staticmethod
    def _coverage_metadata(
        holder: object,
        pools: list[dict[str, object]],
        to_block: int,
    ) -> dict[str, object]:
        scope_count = len(holder.retention_liquidity_query_scopes(pools))
        return {
            "query_scope_complete": True,
            "query_count": scope_count,
            "scope_batch_count": scope_count,
            "query_chunk_count": 1,
            "expected_query_count": scope_count,
            "v4_manager_count": len(
                {
                    pool["address"]
                    for pool in pools
                    if pool.get("protocol") == "v4_cl"
                }
            ),
            "event_filter_count": sum(
                4 if pool.get("protocol") == "v3" else 2
                for pool in pools
            ),
            "applicable": True,
            "active": False,
            "requested_to_block": to_block,
            "selected_to_block": to_block,
            "attempt_count": 1,
            "complete_selected_window": True,
            "complete_requested_window": True,
        }

    def test_fast_liquidity_bootstrap_suppresses_history_then_advances(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        payload = self._opening_payload()
        item = {
            "symbol": "TEST",
            "name": "Test",
            "priority": "P1_MONITOR",
            "chain": "bsc",
            "address": self._address("1"),
        }
        active = {
            "status": "active",
            "reason": "opening_to_30d_retention",
            "opening_time_utc": "2026-07-30T00:00:00+00:00",
            "age_hours": 1,
        }
        calls: list[tuple[int, int]] = []

        def fetch(
            _chain: str,
            pools: list[dict[str, object]],
            from_block: int,
            to_block: int,
            **_kwargs: object,
        ) -> tuple[
            list[dict[str, object]],
            list[str],
            bool,
            int,
            dict[str, object],
        ]:
            calls.append((from_block, to_block))
            pool = next(
                row for row in pools if row.get("protocol") == "v3"
            )
            block = 115 if from_block <= 115 <= to_block else 125
            rows = [
                self._event_row(
                    pool,
                    block=block,
                    tx_digit="a" if block == 115 else "b",
                )
            ]
            return (
                rows,
                [],
                False,
                to_block,
                self._coverage_metadata(holder, pools, to_block),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            state_path = temp / "fast_state.json"
            holder_state_path = temp / "holder_state.json"
            config_path.write_text('{"items": []}', encoding="utf-8")
            opening_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", state_path),
                mock.patch.object(holder, "STATE_PATH", holder_state_path),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    fast,
                    "eligible_contract_items",
                    return_value=([item], []),
                ),
                mock.patch.object(
                    holder,
                    "config_item_for_contract",
                    return_value={"chain": "bsc"},
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value=active,
                ),
                mock.patch.object(
                    fast,
                    "strict_token_metadata",
                    return_value=(0, 1_000_000),
                ),
                mock.patch.object(
                    holder,
                    "latest_block",
                    side_effect=[120, 130],
                ),
                mock.patch.object(
                    holder,
                    "bounded_retention_liquidity_logs",
                    side_effect=fetch,
                ),
                mock.patch.object(
                    holder,
                    "liquidity_checkpoint_block_hash",
                    return_value=self._hash("f"),
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "ALPHA_RETENTION_LIQUIDITY_BOOTSTRAP_BLOCKS": "10",
                        "ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "0",
                    },
                ),
            ):
                first = fast.build_snapshot()
                pending_id = "d" * 64
                token_key = f"bsc:{item['address']}"
                first_liquidity_state = first["_next_state"]["tokens"][
                    token_key
                ]["liquidity"]
                first_liquidity_state["reconciliation"] = {
                    "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
                    "pending": [
                        {
                            "reconcile_id": pending_id,
                            "first_seen_at": holder.now_iso(),
                            "source_event": {
                                "pool": self._address("3"),
                                "tx": self._hash("d"),
                            },
                            "source_pool": self._address("3"),
                            "quote_token": self._address("2"),
                            "removed_target_raw": 100,
                            "removed_quote_raw": 200,
                            "added_target_raw": 0,
                            "added_quote_raw": 0,
                        }
                    ],
                    "completed": [],
                    "updated_at": holder.now_iso(),
                }
                holder.atomic_write_json(
                    state_path,
                    first["_next_state"],
                )
                second = fast.build_snapshot()

            self.assertFalse(holder_state_path.exists())

        self.assertEqual(calls, [(111, 120), (121, 130)])
        self.assertEqual(first["alert_count"], 0)
        self.assertEqual(first["alert_ready_count"], 0)
        self.assertEqual(second["alert_count"], 1)
        self.assertEqual(second["alert_ready_count"], 1)
        second_flow = second["projects"][0]["retention_flow"][
            "liquidity_retention"
        ]
        self.assertEqual(second_flow["previous_latest_block"], 120)
        self.assertEqual(second_flow["scan_from_block"], 121)
        self.assertTrue(second_flow["continuous"])
        second_liquidity_state = second["_next_state"]["tokens"][
            token_key
        ]["liquidity"]
        self.assertEqual(
            second_liquidity_state["reconciliation"]["pending"][0][
                "reconcile_id"
            ],
            pending_id,
        )

    def test_fast_liquidity_caches_tip_once_per_chain(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        items = [
            {
                "symbol": symbol,
                "priority": "P1_MONITOR",
                "chain": "bsc",
                "address": self._address(digit),
            }
            for symbol, digit in (("ONE", "1"), ("TWO", "2"))
        ]
        flow = {
            "status": "active",
            "coverage_mode": "verified_pool_indexed_topics",
            "scope_complete": True,
            "complete": True,
            "selected_window_complete": True,
            "query_scope_complete": True,
            "pool_count": 1,
            "log_error_count": 0,
            "truncated": False,
            "events_truncated": False,
            "events": [],
        }
        next_liquidity = {
            "pool_scope": [{"protocol": "v3"}],
            "latest_block": 120,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            config_path.write_text('{"items": []}', encoding="utf-8")
            opening_path.write_text('{"events": []}', encoding="utf-8")
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", temp / "state.json"),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    fast,
                    "eligible_contract_items",
                    return_value=(items, []),
                ),
                mock.patch.object(
                    holder,
                    "config_item_for_contract",
                    return_value={"chain": "bsc"},
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value={"status": "active"},
                ),
                mock.patch.object(
                    fast,
                    "matching_opened_event",
                    return_value=True,
                ),
                mock.patch.object(
                    holder,
                    "opening_verified_pool_scope",
                    return_value={"complete": True, "pool_scope": [{}]},
                ),
                mock.patch.object(
                    fast,
                    "strict_token_metadata",
                    return_value=(18, 10**24),
                ),
                mock.patch.object(
                    holder,
                    "latest_block",
                    return_value=120,
                ) as latest,
                mock.patch.object(
                    holder,
                    "build_token_liquidity_retention",
                    return_value=(flow, next_liquidity),
                ),
                mock.patch.object(
                    holder,
                    "liquidity_retention_alert_coverage_complete",
                    return_value=False,
                ),
            ):
                snapshot = fast.build_snapshot()

        self.assertEqual(latest.call_count, 1)
        self.assertEqual(snapshot["chain_tip_query_count"], 1)
        self.assertEqual(snapshot["required_count"], 2)
        self.assertEqual(snapshot["complete_count"], 2)

    def test_fast_liquidity_enumerates_all_supported_contract_identities(
        self,
    ) -> None:
        import scripts.alpha_liquidity_retention_watch as fast

        items = []
        for index in range(9):
            contracts = [
                {
                    "chain": "bsc",
                    "address": "0x" + f"{index + 1:040x}",
                }
            ]
            if index == 0:
                contracts.append(
                    {
                        "chain": "base",
                        "address": self._address("f"),
                    }
                )
            items.append(
                {
                    "symbol": f"TOKEN{index}",
                    "priority": "P1_MONITOR",
                    "active_monitoring": True,
                    "contracts": contracts,
                }
            )
        config = {"items": items}
        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_MAX_PROJECTS": "1"},
        ):
            rows, issues = fast.eligible_contract_items(config)

        self.assertEqual(issues, [])
        self.assertEqual(len(rows), 10)
        self.assertEqual(
            {(row["chain"], row["address"]) for row in rows},
            {
                (
                    str(contract["chain"]),
                    str(contract["address"]),
                )
                for item in items
                for contract in item["contracts"]
            },
        )
        self.assertEqual(
            fast.stable_identity_hash(rows),
            fast.stable_identity_hash(list(reversed(rows))),
        )

    def test_opened_liquidity_missing_time_fails_closed_until_expired(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        item = {
            "symbol": "TEST",
            "priority": "P1_MONITOR",
            "chain": "bsc",
            "address": self._address("1"),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            state_path = temp / "state.json"
            config_path.write_text('{"items": []}', encoding="utf-8")
            opening_path.write_text(
                json.dumps(self._opening_payload()),
                encoding="utf-8",
            )
            common = (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", state_path),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    fast,
                    "eligible_contract_items",
                    return_value=([item], []),
                ),
                mock.patch.object(
                    holder,
                    "config_item_for_contract",
                    return_value={"chain": "bsc"},
                ),
            )
            with ExitStack() as stack:
                for patcher in common:
                    stack.enter_context(patcher)
                stack.enter_context(
                    mock.patch.object(
                        holder,
                        "retention_window",
                        return_value={
                            "status": "not_required",
                            "reason": "opening_time_unavailable",
                            "age_hours": None,
                        },
                    )
                )
                missing_time = fast.build_snapshot()
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", state_path),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    fast,
                    "eligible_contract_items",
                    return_value=([item], []),
                ),
                mock.patch.object(
                    holder,
                    "config_item_for_contract",
                    return_value={"chain": "bsc"},
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value={
                        "status": "not_required",
                        "reason": "retention_window_expired",
                        "age_hours": 721,
                    },
                ),
            ):
                expired = fast.build_snapshot()
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", state_path),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    fast,
                    "eligible_contract_items",
                    return_value=([item], []),
                ),
                mock.patch.object(
                    holder,
                    "config_item_for_contract",
                    return_value={},
                ),
            ):
                missing_config = fast.build_snapshot()

        self.assertEqual(missing_time["required_count"], 1)
        self.assertEqual(missing_time["complete_count"], 0)
        self.assertEqual(missing_time["status"], "unhealthy")
        self.assertEqual(expired["required_count"], 0)
        self.assertEqual(expired["status"], "healthy")
        self.assertEqual(missing_config["required_count"], 1)
        self.assertEqual(missing_config["status"], "unhealthy")
        self.assertEqual(
            missing_config["issues"][0]["detail"],
            "invalid_runtime_metadata",
        )

    def test_fast_liquidity_uses_contract_identity_across_symbol_alias(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        token = self._address("1")
        config = {
            "items": [
                {
                    "symbol": "ALIAS",
                    "priority": "P1_MONITOR",
                    "active_monitoring": True,
                    "contracts": [{"chain": "bsc", "address": token}],
                }
            ]
        }
        complete_flow = {
            "status": "active",
            "coverage_mode": "verified_pool_indexed_topics",
            "scope_complete": True,
            "complete": True,
            "selected_window_complete": True,
            "query_scope_complete": True,
            "pool_count": 1,
            "log_error_count": 0,
            "truncated": False,
            "events_truncated": False,
            "events": [],
        }
        observed_symbols = []

        def build_flow(**kwargs):
            observed_symbols.append(kwargs["symbol"])
            return complete_flow, {"pool_scope": [{"protocol": "v3"}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            opening_path.write_text(
                json.dumps(self._opening_payload()),
                encoding="utf-8",
            )
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", temp / "state.json"),
                mock.patch.object(holder, "STATE_PATH", temp / "holder.json"),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value={"status": "active", "age_hours": 24},
                ),
                mock.patch.object(
                    fast,
                    "strict_token_metadata",
                    return_value=(18, 10**24),
                ),
                mock.patch.object(holder, "latest_block", return_value=130),
                mock.patch.object(
                    holder,
                    "build_token_liquidity_retention",
                    side_effect=build_flow,
                ),
            ):
                snapshot = fast.build_snapshot()

        self.assertEqual(snapshot["status"], "healthy")
        self.assertEqual(snapshot["required_count"], 1)
        self.assertEqual(snapshot["complete_count"], 1)
        self.assertEqual(snapshot["projects"][0]["symbol"], "ALIAS")
        self.assertEqual(snapshot["projects"][0]["opening_symbol"], "TEST")
        self.assertEqual(observed_symbols, ["TEST"])

    def test_fast_liquidity_active_window_without_scope_fails_closed(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        token = self._address("1")
        config = {
            "items": [
                {
                    "symbol": "TEST",
                    "priority": "P1_MONITOR",
                    "active_monitoring": True,
                    "contracts": [{"chain": "bsc", "address": token}],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            opening_path.write_text('{"events": []}', encoding="utf-8")
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", temp / "state.json"),
                mock.patch.object(holder, "STATE_PATH", temp / "holder.json"),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value={"status": "active", "age_hours": 123},
                ),
            ):
                snapshot = fast.build_snapshot()

        self.assertEqual(snapshot["required_count"], 1)
        self.assertEqual(snapshot["complete_count"], 0)
        self.assertEqual(snapshot["status"], "unhealthy")
        self.assertEqual(
            snapshot["projects"][0]["retention_flow"][
                "liquidity_retention"
            ]["status"],
            "coverage_gap",
        )

    def test_fast_liquidity_seeds_verified_holder_checkpoint_continuously(
        self,
    ) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast

        token = self._address("1")
        scope = holder.opening_verified_pool_scope(
            self._opening_payload(),
            "TEST",
            "bsc",
            token,
        )
        seed = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": scope["scope_hash"],
            "pool_scope": scope["pool_scope"],
            "pool_count": scope["pool_count"],
            "scope_coverage_from_block": 101,
            "latest_block": 120,
            "latest_block_hash": self._hash("f"),
            "catchup_active": False,
        }
        config = {
            "items": [
                {
                    "symbol": "TEST",
                    "priority": "P1_MONITOR",
                    "active_monitoring": True,
                    "contracts": [{"chain": "bsc", "address": token}],
                }
            ]
        }

        def fetch(_chain, pools, from_block, to_block, **_kwargs):
            self.assertEqual((from_block, to_block), (121, 128))
            return (
                [],
                [],
                False,
                to_block,
                self._coverage_metadata(holder, pools, to_block),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "watchlist.json"
            opening_path = temp / "opening.json"
            holder_state_path = temp / "holder.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            opening_path.write_text('{"events": []}', encoding="utf-8")
            holder_state_path.write_text(
                json.dumps(
                    {
                        "tokens": {
                            f"bsc:{token}": {
                                "decimals": 18,
                                "retention_flow": {"liquidity": seed},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(fast, "CONFIG_PATH", config_path),
                mock.patch.object(fast, "STATE_PATH", temp / "state.json"),
                mock.patch.object(holder, "STATE_PATH", holder_state_path),
                mock.patch.object(
                    holder,
                    "OPENING_CONTEXT_PATH",
                    opening_path,
                ),
                mock.patch.object(
                    holder,
                    "retention_window",
                    return_value={"status": "active", "age_hours": 123},
                ),
                mock.patch.object(
                    fast,
                    "strict_token_metadata",
                    return_value=(18, 10**24),
                ),
                mock.patch.object(holder, "latest_block", return_value=130),
                mock.patch.object(
                    holder,
                    "bounded_retention_liquidity_logs",
                    side_effect=fetch,
                ),
                mock.patch.object(
                    holder,
                    "liquidity_checkpoint_block_hash",
                    return_value=self._hash("f"),
                ),
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_RETENTION_LIQUIDITY_CONFIRMATION_BLOCKS": "2"},
                ),
            ):
                snapshot = fast.build_snapshot()

        flow = snapshot["projects"][0]["retention_flow"][
            "liquidity_retention"
        ]
        self.assertEqual(snapshot["status"], "healthy")
        self.assertEqual(snapshot["required_count"], 1)
        self.assertEqual(snapshot["complete_count"], 1)
        self.assertEqual(snapshot["projects"][0]["scope_seed_source"], "holder")
        self.assertEqual(flow["previous_latest_block"], 120)
        self.assertEqual(flow["scan_from_block"], 121)
        self.assertEqual(flow["latest_block"], 128)
        self.assertTrue(flow["continuous"])

    def test_fast_liquidity_delivery_failure_retains_checkpoint(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast
        import scripts.fast_lane_health as health

        next_state = {
            "schema": fast.STATE_SCHEMA,
            "tokens": {"bsc:fixture": {"liquidity": {"latest_block": 120}}},
        }
        snapshot = {
            "schema": fast.SNAPSHOT_SCHEMA,
            "generated_at": "2026-08-01T00:00:00+00:00",
            "status": "healthy",
            "issue_count": 0,
            "issues": [],
            "project_count": 0,
            "expected_count": 0,
            "processed_count": 0,
            "dropped_count": 0,
            "expected_identity_hash": fast.stable_identity_hash([]),
            "processed_identity_hash": fast.stable_identity_hash([]),
            "required_count": 0,
            "complete_count": 0,
            "alert_ready_count": 0,
            "alert_count": 0,
            "projects": [],
            "_next_state": next_state,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            latest_path = temp / "latest.json"
            state_path = temp / "state.json"
            failure_path = temp / "failures.tsv"
            failure_path.write_text(
                "1\t40\tpython3 scripts/alpha_liquidity_retention_watch.py\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(fast, "OUT_DIR", temp),
                mock.patch.object(fast, "LATEST_PATH", latest_path),
                mock.patch.object(fast, "REPORT_PATH", temp / "latest.md"),
                mock.patch.object(fast, "STATE_PATH", state_path),
                mock.patch.object(
                    fast,
                    "build_snapshot",
                    return_value=copy.deepcopy(snapshot),
                ),
                mock.patch.object(
                    holder,
                    "maybe_send_telegram",
                    return_value=False,
                ),
            ):
                self.assertEqual(fast.run_once(), 1)

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertFalse(state_path.exists())
            self.assertEqual(latest["delivery_status"], "failed")
            self.assertEqual(latest["status"], "unhealthy")
            self.assertIn("unhealthy", health.liquidity_output_issue(latest_path))
            failures = health.read_failures(failure_path)
            self.assertEqual(failures[0]["kind"], "step_failed")
            self.assertIn("alpha_liquidity", failures[0]["command"])

    def test_holder_and_fast_processes_share_locked_seen_ledger(self) -> None:
        snapshot = {"projects": [{}]}
        worker_code = r"""
import json
import os
import sys
from pathlib import Path
import scripts.alpha_holder_concentration_watch as holder

snapshot = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
seen_path = Path(sys.argv[2])
lock_path = Path(sys.argv[3])
counter_path = Path(sys.argv[4])
last_push_path = Path(sys.argv[5])
holder.alert_keys = lambda _snapshot: ['shared-event-key']
holder.retention_alert_events = lambda _project: [{'type': 'fixture'}]
holder.retention_event_key = lambda _project, _event: 'shared-event-key'
holder.retention_telegram_batches = lambda _project, events: [('fixture', events)]
holder.holder_signal_key = lambda _project: ''
def fake_send(_text, batch_keys, **kwargs):
    with counter_path.open('a', encoding='utf-8') as stream:
        stream.write('sent\n')
        stream.flush()
        os.fsync(stream.fileno())
    seen = kwargs['seen']
    seen.update(batch_keys)
    holder.atomic_write_json(kwargs['seen_path'], sorted(seen))
holder.send_telegram_batch = fake_send
ok = holder.maybe_send_telegram(
    snapshot,
    seen_path=seen_path,
    last_push_path=last_push_path,
    lock_path=lock_path,
)
raise SystemExit(0 if ok else 1)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            snapshot_path = temp / "snapshot.json"
            seen_path = temp / "seen.json"
            lock_path = temp / "alerts.lock"
            counter_path = temp / "send_count.txt"
            last_push_path = temp / "last_push.json"
            snapshot_path.write_text(
                json.dumps(snapshot),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "ALPHA_HOLDER_TELEGRAM": "1",
                "TELEGRAM_BOT_TOKEN": "fixture",
                "TELEGRAM_CHAT_ID": "fixture",
                "DISABLE_TELEGRAM": "0",
            }
            commands = [
                sys.executable,
                "-c",
                worker_code,
                str(snapshot_path),
                str(seen_path),
                str(lock_path),
                str(counter_path),
                str(last_push_path),
            ]
            workers = [
                subprocess.Popen(
                    commands,
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            results = [worker.communicate(timeout=10) for worker in workers]

            self.assertEqual([worker.returncode for worker in workers], [0, 0], results)
            self.assertEqual(
                counter_path.read_text(encoding="utf-8").splitlines(),
                ["sent"],
            )
            self.assertEqual(
                json.loads(seen_path.read_text(encoding="utf-8")),
                ["shared-event-key"],
            )

    def test_fast_liquidity_disable_and_health_contract(self) -> None:
        import scripts.alpha_holder_concentration_watch as holder
        import scripts.alpha_liquidity_retention_watch as fast
        import scripts.fast_lane_health as fast_health
        from scripts.runtime_health_watch import (
            liquidity_retention_required,
            standalone_liquidity_snapshot_issue,
        )

        with mock.patch.dict(
            os.environ,
            {
                "DISABLE_TELEGRAM": "1",
                "ALPHA_HOLDER_TELEGRAM": "1",
            },
        ):
            self.assertTrue(holder.maybe_send_telegram({"projects": []}))

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest.json"
            payload = {
                "schema": "alpha_liquidity_retention_watch.v1",
                "status": "healthy",
                "delivery_status": "complete",
                "issue_count": 0,
                "required_count": 1,
                "complete_count": 1,
                "expected_count": 1,
                "processed_count": 1,
                "dropped_count": 0,
                "expected_identity_hash": fast.stable_identity_hash(
                    [{"chain": "bsc", "address": self._address("1")}]
                ),
                "processed_identity_hash": fast.stable_identity_hash(
                    [{"chain": "bsc", "address": self._address("1")}]
                ),
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(fast_health.liquidity_output_issue(path), "")
            self.assertEqual(standalone_liquidity_snapshot_issue(path), "")
            payload["delivery_status"] = "failed"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn(
                "delivery",
                fast_health.liquidity_output_issue(path),
            )
            self.assertIn(
                "delivery",
                standalone_liquidity_snapshot_issue(path),
            )

            opening_path = Path(temp_dir) / "opening.json"
            opening_path.write_text(
                json.dumps(self._opening_payload()),
                encoding="utf-8",
            )
            identity = ("bsc", self._address("1"))
            current = datetime(2026, 8, 1, tzinfo=timezone.utc)
            self.assertTrue(
                liquidity_retention_required(
                    opening_path,
                    identity,
                    None,
                    current,
                )
            )
            self.assertFalse(
                liquidity_retention_required(
                    opening_path,
                    identity,
                    current - timedelta(days=31),
                    current,
                )
            )

        issue = fast.liquidity_operational_issue(
            {
                "status": "active",
                "pool_count": 6,
                "complete": False,
                "selected_window_complete": False,
                "query_scope_complete": False,
                "log_error_count": 0,
                "truncated": True,
            },
            required=True,
            next_state=None,
        )
        self.assertEqual(issue, "indexed log result truncated")

        opening_scope = holder.opening_verified_pool_scope(
            self._opening_payload(),
            "TEST",
            "bsc",
            self._address("1"),
        )
        invalid_seed = fast.validated_liquidity_seed(
            {
                "scope_state_schema_version": (
                    holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
                ),
                "scope_hash": opening_scope["scope_hash"],
                "pool_scope": opening_scope["pool_scope"],
                "reconciliation": {
                    "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
                    "pending": [{"reconcile_id": "a" * 64}],
                    "completed": [],
                },
            },
            self._address("1"),
        )
        self.assertTrue(invalid_seed["reconciliation_state_invalid"])
        self.assertNotIn("reconciliation", invalid_seed)
        self.assertEqual(
            fast.safe_error_message(
                fast.ReconciliationStateInvalid("invalid")
            ),
            "liquidity_reconciliation_state_invalid",
        )

        fast_source = (ROOT / "scripts" / "server_fast_lane.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("FAST_ALPHA_LIQUIDITY_TIMEOUT_SECONDS:-40", fast_source)
        self.assertIn("alpha_liquidity_retention_watch.py", fast_source)
        self.assertIn("liquidity_pid=$!", fast_source)
        self.assertIn('wait "$liquidity_pid"', fast_source)
        self.assertIn("ALPHA_HOLDER_TELEGRAM=0", fast_source)
        self.assertIn(
            "ALPHA_RETENTION_LIQUIDITY_LOG_CHUNK_BLOCKS=8",
            fast_source,
        )
        self.assertIn(
            "ALPHA_RETENTION_LIQUIDITY_CATCHUP_MIN_BLOCKS=1",
            fast_source,
        )

    def test_fast_health_identity_hash_matches_exclusive_grvt_focus(
        self,
    ) -> None:
        import scripts.alpha_liquidity_retention_watch as fast
        import scripts.binance_alpha_catalog_watch as catalog
        import scripts.fast_lane_health as health

        grvt_address = self._address("1")
        policy = {"mode": "exclusive_symbols", "symbols": ["GRVT"]}
        watchlist = {
            "monitoring_policy": policy,
            "monitoring_policy_fingerprint": (
                catalog.monitoring_policy_fingerprint(policy)
            ),
            "items": [
                {
                    "symbol": "GRVT",
                    "priority": "P0_DEEP_REVIEW",
                    "active_monitoring": True,
                    "contracts": [
                        {"chain": "bsc", "address": grvt_address}
                    ],
                },
                {
                    "symbol": "AEON",
                    "priority": "P1_MONITOR",
                    "active_monitoring": False,
                    "contracts": [
                        {"chain": "bsc", "address": self._address("2")}
                    ],
                },
            ],
        }
        expected_hash = fast.stable_identity_hash(
            [{"chain": "bsc", "address": grvt_address}]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watchlist_path = root / "watchlist.json"
            liquidity_path = root / "liquidity.json"
            watchlist_path.write_text(
                json.dumps(watchlist),
                encoding="utf-8",
            )
            liquidity_path.write_text(
                json.dumps({"expected_identity_hash": expected_hash}),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"ALPHA_WATCHLIST_PATH": str(watchlist_path)},
            ):
                self.assertEqual(
                    health.monitoring_scope_issue(liquidity_path),
                    "",
                )
                watchlist["items"][1]["active_monitoring"] = True
                watchlist_path.write_text(
                    json.dumps(watchlist),
                    encoding="utf-8",
                )
                self.assertIn(
                    "curated focus",
                    health.monitoring_scope_issue(liquidity_path),
                )
                wrong_policy = {
                    "mode": "exclusive_symbols",
                    "symbols": ["AEON"],
                }
                watchlist["monitoring_policy"] = wrong_policy
                watchlist["monitoring_policy_fingerprint"] = (
                    catalog.monitoring_policy_fingerprint(wrong_policy)
                )
                watchlist["items"][0]["active_monitoring"] = False
                watchlist["items"][1]["active_monitoring"] = True
                watchlist_path.write_text(
                    json.dumps(watchlist),
                    encoding="utf-8",
                )
                liquidity_path.write_text(
                    json.dumps(
                        {
                            "expected_identity_hash": fast.stable_identity_hash(
                                [
                                    {
                                        "chain": "bsc",
                                        "address": self._address("2"),
                                    }
                                ]
                            )
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertIn(
                    "curated focus",
                    health.monitoring_scope_issue(liquidity_path),
                )


if __name__ == "__main__":
    unittest.main()
