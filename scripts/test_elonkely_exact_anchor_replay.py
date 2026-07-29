#!/usr/bin/env python3
"""Pure-offline tests for the exact-anchor ElonKely market replay."""
from __future__ import annotations

import importlib.util
import json
import socket
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "backfill_elonkely_exact_anchor_replay.py"
FIXTURE_PATH = (
    ROOT / "scripts" / "fixtures" / "elonkely_exact_anchor_replay_synthetic.json"
)
SPEC = importlib.util.spec_from_file_location("elonkely_exact_anchor_replay", MODULE_PATH)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)

_REAL_SOCKET = socket.socket
_REAL_CREATE_CONNECTION = socket.create_connection


def _blocked_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("exact-anchor replay test attempted network access")


def setUpModule() -> None:
    socket.socket = _blocked_network  # type: ignore[assignment]
    socket.create_connection = _blocked_network


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[assignment]
    socket.create_connection = _REAL_CREATE_CONNECTION


class ExactAnchorReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.case = {
            "root_signal_id": "synthetic-root",
            "symbol": "TEST",
            "alpha_id": "ALPHA_TEST",
            "pair": "ALPHA_TESTUSDT",
            "signal_time_utc": cls.fixture["signal_time_utc"],
        }

    def build(self, rows: list[list[str]]) -> dict[str, object]:
        return replay.build_case_result(
            self.case,
            rows,
            registry_state={
                "token_list_present": True,
                "token_list_symbol": "TEST",
                "exchange_info_present": True,
                "exchange_info_status": "TRADING",
            },
            fetch_state={"request_count": 1, "last_cursor_ms": 0},
            horizons=self.fixture["horizons_minutes"],
        )

    def test_strict_post_signal_anchor_and_metrics(self) -> None:
        result = self.build(self.fixture["rows"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["anchor_time_utc"], self.fixture["expected_anchor_time_utc"])
        horizons = result["horizons"]
        self.assertEqual(horizons["2m"]["metrics"]["mfe_pct"], "5.0000000000")
        self.assertEqual(horizons["2m"]["metrics"]["mae_pct"], "-1.0000000000")
        self.assertEqual(horizons["2m"]["metrics"]["end_return_pct"], "4.0000000000")
        self.assertEqual(horizons["4m"]["metrics"]["mae_pct"], "-5.0000000000")
        self.assertEqual(horizons["7m"]["metrics"]["end_return_pct"], "3.0000000000")

    def test_missing_minute_blocks_only_affected_horizons(self) -> None:
        rows = [
            row
            for row in self.fixture["rows"]
            if row[0] != self.fixture["rows"][2][0]
        ]
        result = self.build(rows)
        self.assertEqual(result["status"], "blocked_incomplete_series")
        self.assertEqual(result["horizons"]["2m"]["status"], "complete")
        self.assertEqual(
            result["horizons"]["4m"]["status"],
            "blocked_incomplete_series",
        )
        missing = result["coverage"]["missing_ranges"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["minute_count"], 1)
        self.assertIsNone(result["horizons"]["7m"]["metrics"])

    def test_api_error_preserves_exact_full_gap(self) -> None:
        result = replay.build_case_result(
            self.case,
            [],
            registry_state={
                "token_list_present": True,
                "token_list_symbol": "TEST",
                "exchange_info_present": False,
                "exchange_info_status": None,
            },
            fetch_state={"request_count": 0, "last_cursor_ms": 0},
            api_error=replay.PublicMarketDataError("-1121", "Invalid symbol."),
            horizons=self.fixture["horizons_minutes"],
        )
        self.assertEqual(result["api_result"]["code"], "-1121")
        self.assertEqual(result["coverage"]["missing_candle_count"], 7)
        self.assertEqual(result["coverage"]["missing_ranges"][0]["minute_count"], 7)
        self.assertTrue(all(row["metrics"] is None for row in result["horizons"].values()))

    def test_identical_duplicate_open_time_blocks_completion(self) -> None:
        rows = list(self.fixture["rows"])
        rows.insert(1, list(rows[0]))
        result = self.build(rows)
        self.assertEqual(result["status"], "blocked_incomplete_series")
        self.assertEqual(result["coverage"]["duplicate_open_time_count"], 1)
        self.assertEqual(result["coverage"]["conflicting_open_time_count"], 0)
        self.assertIsNone(result["horizons"]["2m"]["metrics"])

    def test_conflicting_duplicate_open_time_blocks_completion(self) -> None:
        rows = list(self.fixture["rows"])
        conflicting = list(rows[0])
        conflicting[1:5] = ["999", "1000", "998", "999"]
        rows.insert(1, conflicting)
        result = self.build(rows)
        self.assertEqual(result["status"], "blocked_incomplete_series")
        self.assertEqual(result["coverage"]["duplicate_open_time_count"], 1)
        self.assertEqual(result["coverage"]["conflicting_open_time_count"], 1)
        self.assertIsNone(result["horizons"]["2m"]["metrics"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
