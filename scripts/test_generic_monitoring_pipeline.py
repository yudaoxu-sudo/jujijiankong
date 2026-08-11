#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


os.environ.setdefault("SNIPER_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import alpha_holder_concentration_watch as holder
from scripts import alpha_intraday_flow_watch as intraday
from scripts import alpha_liquidity_retention_watch as retention
from scripts import alpha_onboarding_preflight as preflight
from scripts import alpha_opening_block_watch as opening
from scripts import alpha_price_momentum_watch as price


TOKEN = "0x" + "7" * 40
USDT = "0x55d398326f99059ff775485246999027b3197955"


def synthetic_watchlist() -> dict[str, object]:
    return {
        "monitoring_profile": "binance_alpha_bsc.v1",
        "monitoring_adapter": "generic_alpha_watchers.v1",
        "monitoring_policy": {
            "mode": "exclusive_symbols",
            "symbols": ["PIPE"],
        },
        "items": [
            {
                "symbol": "PIPE",
                "active_monitoring": True,
                "priority": "P1_MONITOR",
                "contracts": [{"chain": "bsc", "address": TOKEN}],
                "known_times": [
                    {
                        "time": "2026-08-10 17:00",
                        "reason": "binance_alpha_listing_time",
                    }
                ],
                "pool_ids": [],
            }
        ],
    }


class GenericMonitoringPipelineTests(unittest.TestCase):
    def test_preflight_closes_stale_runtime_filters_before_watchers_skip(
        self,
    ) -> None:
        payload = synthetic_watchlist()
        token_by_contract = {TOKEN: {"alphaId": "ALPHA_PIPE"}}
        with (
            mock.patch.object(intraday, "read_json", return_value=payload),
            mock.patch.object(
                intraday,
                "now_utc",
                return_value=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
            ),
            mock.patch.object(price, "read_json", return_value=payload),
            mock.patch.dict(
                os.environ,
                {
                    "SNIPER_OFFLINE": "1",
                    "ALPHA_INTRADAY_REVIEW_SYMBOL": "STALE",
                    "ALPHA_PRICE_REVIEW_SYMBOL": "STALE",
                },
                clear=True,
            ),
        ):
            stale_result = preflight.validate_watchlist(
                payload,
                profile="binance_alpha_bsc.v1",
                holder_capacity=1,
            )
            stale_intraday = intraday.build_event_specs()
            stale_price = price.watchlist_events(token_by_contract)

        self.assertEqual(stale_result["status"], "blocked")
        self.assertIn(
            "runtime_symbol_filter_invalid",
            stale_result["issue_codes"],
        )
        self.assertEqual(stale_intraday, [])
        self.assertEqual(stale_price, [])

        with (
            mock.patch.object(intraday, "read_json", return_value=payload),
            mock.patch.object(
                intraday,
                "now_utc",
                return_value=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
            ),
            mock.patch.object(price, "read_json", return_value=payload),
            mock.patch.dict(
                os.environ,
                {
                    "SNIPER_OFFLINE": "1",
                    "ALPHA_INTRADAY_REVIEW_SYMBOL": "pipe",
                    "ALPHA_PRICE_REVIEW_SYMBOL": "pIpE",
                },
                clear=True,
            ),
        ):
            matching_result = preflight.validate_watchlist(
                payload,
                profile="binance_alpha_bsc.v1",
                holder_capacity=1,
            )
            matching_intraday = intraday.build_event_specs()
            matching_price = price.watchlist_events(token_by_contract)

        self.assertEqual(matching_result["status"], "pass")
        self.assertEqual(len(matching_intraday), 1)
        self.assertEqual(len(matching_price), 1)

    def test_one_watchlist_item_reaches_every_generic_monitoring_scope(self) -> None:
        payload = synthetic_watchlist()
        item = payload["items"][0]

        result = preflight.validate_watchlist(
            payload,
            profile="binance_alpha_bsc.v1",
            holder_capacity=1,
        )
        self.assertEqual(result["status"], "pass")

        opening_rows = opening.opening_pool_rows(item)
        self.assertEqual(len(opening_rows), 1)
        self.assertEqual(opening_rows[0]["source"], "canonical_opening_known_time")
        self.assertEqual(opening_rows[0]["quote_address"], USDT)

        with tempfile.TemporaryDirectory() as temporary:
            watchlist_path = Path(temporary) / "watchlist.json"
            watchlist_path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch.object(intraday, "CONFIG_PATH", watchlist_path),
                mock.patch.object(
                    intraday,
                    "now_utc",
                    return_value=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
                ),
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_INTRADAY_REVIEW_SYMBOL": "PIPE"},
                ),
            ):
                intraday_specs = intraday.build_event_specs()

        self.assertEqual(len(intraday_specs), 1)
        self.assertEqual(intraday_specs[0]["token_address"], TOKEN)
        self.assertEqual(intraday_specs[0]["quote_address"], USDT)

        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_HOLDER_MAX_PROJECTS": "1",
                "ALPHA_HOLDER_PRIORITIES": "P0,P1",
            },
        ):
            holder_rows = holder.contract_items(payload)
            retention_rows, retention_issues = retention.eligible_contract_items(
                payload
            )

        self.assertEqual(retention_issues, [])
        self.assertEqual(len(holder_rows), 1)
        self.assertEqual(len(retention_rows), 1)
        expected_identity = ("bsc", TOKEN)
        self.assertEqual(
            (holder_rows[0]["chain"], holder_rows[0]["address"]),
            expected_identity,
        )
        self.assertEqual(
            (retention_rows[0]["chain"], retention_rows[0]["address"]),
            expected_identity,
        )

    def test_cycle_snapshot_keeps_identity_after_source_replacement(self) -> None:
        original = synthetic_watchlist()
        replacement = synthetic_watchlist()
        replacement["monitoring_policy"]["symbols"] = ["OTHER"]
        replacement["items"][0]["symbol"] = "OTHER"
        replacement["items"][0]["contracts"][0]["address"] = "0x" + "8" * 40

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "current_watchlist.json"
            source.write_text(json.dumps(original), encoding="utf-8")
            snapshot = preflight.materialize_watchlist(
                source,
                root / "runtime_watchlist_cycles",
            )
            source.write_text(json.dumps(replacement), encoding="utf-8")
            snapshotted = json.loads(snapshot.read_text(encoding="utf-8"))

            with (
                mock.patch.object(intraday, "CONFIG_PATH", snapshot),
                mock.patch.object(
                    intraday,
                    "now_utc",
                    return_value=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
                ),
                mock.patch.dict(
                    os.environ,
                    {"ALPHA_INTRADAY_REVIEW_SYMBOL": "PIPE"},
                ),
            ):
                intraday_specs = intraday.build_event_specs()

        self.assertEqual(
            preflight.validate_watchlist(
                snapshotted,
                profile="binance_alpha_bsc.v1",
                holder_capacity=1,
            )["status"],
            "pass",
        )
        self.assertEqual(
            opening.opening_pool_rows(snapshotted["items"][0])[0]["source"],
            "canonical_opening_known_time",
        )
        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_HOLDER_MAX_PROJECTS": "1",
                "ALPHA_HOLDER_PRIORITIES": "P0,P1",
            },
        ):
            holder_rows = holder.contract_items(snapshotted)
            retention_rows, retention_issues = retention.eligible_contract_items(
                snapshotted
            )
        self.assertEqual(retention_issues, [])
        self.assertEqual(intraday_specs[0]["token_address"], TOKEN)
        self.assertEqual(holder_rows[0]["address"], TOKEN)
        self.assertEqual(retention_rows[0]["address"], TOKEN)


if __name__ == "__main__":
    unittest.main()
