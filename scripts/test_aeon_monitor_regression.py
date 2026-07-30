#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


class BinanceAlphaCatalogRegressionTests(unittest.TestCase):
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
        self.assertEqual(item["project_lookback_blocks"], 50000)

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

    def test_health_reports_recent_unsupported_chain_item(self) -> None:
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
                        "unsupported_count": 1,
                        "unsupported": [
                            {"symbol": "BASEONLY", "chain": "base"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            issues = alpha_coverage_issues(root)

        self.assertEqual(issues[0]["kind"], "alpha_unsupported_chain")
        self.assertIn("BASEONLY@base", issues[0]["detail"])

    def test_health_reports_unready_launch_candidate(self) -> None:
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

        self.assertEqual(issues[0]["kind"], "alpha_launch_candidate_gap")
        self.assertEqual(issues[0]["name"], "GRVT")
        self.assertIn("missing_exact_opening_time", issues[0]["detail"])

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
        }

        refreshed_trace = {
            **row["buyer_trace"],
            "as_of_block": "140",
            "confirmed_sell_quote_received": "38000",
        }
        with (
            mock.patch.object(
                opening,
                "scan_key_liquidity_flows",
                return_value={"summary": "fresh", "risk": "none", "rows": 0},
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
            "opening buyer trace coverage incomplete",
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
                return_value={},
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
                return_value={},
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
                return_value={},
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
                return_value={},
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
            "chain": "bsc",
            "token": {"address": token},
            "quote": {"address": quote, "symbol": "USDT"},
            "opening_block": 100,
            "start_time_utc": "2026-07-27T10:00:00+00:00",
            "pool_id": "old-pool",
            "status": "opened",
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
            "start_time_utc": "2026-07-27T10:00:01+00:00",
            "pool_id": "new-pool",
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
                return_value={},
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
        self.assertEqual(conflict, "ambiguous_stable_identity")

        previous, conflict = opening.select_previous_opened_event(
            first,
            [first, second],
        )
        self.assertIs(previous, first)
        self.assertEqual(conflict, "")

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

        rebuild.assert_called_once_with(current_event, None)
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
                        "cache_identity_status": "stable_match",
                        "rows": [],
                    },
                    {
                        "status": "opened",
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
