#!/usr/bin/env python3
from __future__ import annotations

import copy
import fcntl
import json
import multiprocessing
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


os.environ.setdefault("SNIPER_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import fast_lane_health as health
from scripts import ingest_alpha_signal as ingest
from sniper_engine import project_registry as registry
from sniper_engine.project_registry import find_project_index


def contract(chain: str, digit: str) -> dict[str, str]:
    return {"chain": chain, "address": "0x" + digit * 40}


def apply_proposal_process(
    watchlist_path: str,
    prediction_path: str,
    lock_path: str,
    ready_path: str,
    release_path: str,
    proposal: dict[str, object],
) -> None:
    ingest.WATCHLIST_PATH = Path(watchlist_path)
    ingest.PREDICTION_PATH = Path(prediction_path)
    ingest.APPLY_LOCK_PATH = Path(lock_path)
    Path(ready_path).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 5
    while not Path(release_path).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("auto-apply file barrier timed out")
        time.sleep(0.005)
    ingest.apply_proposals(
        {
            "source_policy": {"context_only": False},
            "watchlist_proposal": proposal,
            "prediction_proposals": [],
        }
    )


def merge_registry_process(
    registry_path: str,
    summary_path: str,
    lock_path: str,
    ready_path: str,
    release_path: str,
    parsed: dict[str, object],
) -> None:
    from sniper_engine import project_registry as child_registry

    child_registry.REGISTRY_PATH = Path(registry_path)
    child_registry.SUMMARY_PATH = Path(summary_path)
    child_registry.LOCK_PATH = Path(lock_path)
    Path(ready_path).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 5
    while not Path(release_path).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("registry file barrier timed out")
        time.sleep(0.005)
    child_registry.merge_signal(parsed, {"collector": "concurrency_test"})


class ProjectRegistryIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projects = [
            {
                "symbol": "SAME",
                "aliases": ["SHARED"],
                "contracts": [contract("bsc", "1")],
                "pool_ids": [],
                "txs": [],
            },
            {
                "symbol": "SAME",
                "aliases": ["SHARED"],
                "contracts": [contract("base", "2")],
                "pool_ids": [],
                "txs": [],
            },
        ]

    def test_explicit_identity_uses_exact_chain_and_contract(self) -> None:
        cases = (
            ("different contract", "SAME", contract("bsc", "3"), None),
            ("different chain", "SAME", contract("base", "1"), None),
            ("same identity renamed", "RENAMED", contract("bsc", "1"), 0),
        )
        for label, symbol, identity, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    find_project_index(
                        self.projects,
                        {"symbol": symbol, "contracts": [identity]},
                    ),
                    expected,
                )

    def test_alias_fallback_requires_one_single_identity_candidate(self) -> None:
        project = dict(self.projects[0])
        project["contracts"] = [
            contract("bsc", "1"),
            contract("base", "2"),
        ]
        cases = (
            ("two candidates", self.projects, None),
            ("one identity", self.projects[:1], 0),
            ("one multi-identity candidate", [project], None),
        )
        for label, projects, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    find_project_index(projects, {"symbol": "SHARED"}),
                    expected,
                )


class ProjectRegistryConcurrencyTests(unittest.TestCase):
    def merge_concurrently(
        self,
        proposals: tuple[dict[str, object], dict[str, object]],
    ) -> tuple[dict[str, object], str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "project_registry.json"
            summary_path = root / "project_registry.md"
            lock_path = root / "project_registry.lock"
            initial = {
                "generated_at": "2026-08-11T00:00:00+00:00",
                "projects": [],
            }
            original_summary = "# Original Registry\n"
            registry_path.write_text(json.dumps(initial), encoding="utf-8")
            summary_path.write_text(original_summary, encoding="utf-8")
            context = multiprocessing.get_context("fork")
            release_path = root / "workers.release"
            ready_paths = [root / f"worker-{index}.ready" for index in range(2)]
            processes = [
                context.Process(
                    target=merge_registry_process,
                    args=(
                        str(registry_path),
                        str(summary_path),
                        str(lock_path),
                        str(ready_paths[index]),
                        str(release_path),
                        proposal,
                    ),
                )
                for index, proposal in enumerate(proposals)
            ]
            lock_path.touch()
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    for process in processes:
                        process.start()
                    deadline = time.monotonic() + 5
                    while not all(path.exists() for path in ready_paths):
                        if time.monotonic() >= deadline:
                            self.fail("registry workers did not reach file barrier")
                        time.sleep(0.005)
                    release_path.write_text("release", encoding="utf-8")
                    for process in processes:
                        process.join(timeout=0.5)
                    self.assertTrue(
                        all(process.is_alive() for process in processes),
                        "registry merge did not wait for its shared lock",
                    )
                    self.assertEqual(
                        json.loads(registry_path.read_text(encoding="utf-8")),
                        initial,
                    )
                    self.assertEqual(
                        summary_path.read_text(encoding="utf-8"),
                        original_summary,
                    )
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            for _ in range(1000):
                json.loads(registry_path.read_text(encoding="utf-8"))
                summary_path.read_text(encoding="utf-8")
                if not any(process.is_alive() for process in processes):
                    break
                for process in processes:
                    process.join(timeout=0.001)
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                self.assertEqual(process.exitcode, 0)
            return (
                json.loads(registry_path.read_text(encoding="utf-8")),
                summary_path.read_text(encoding="utf-8"),
            )

    @staticmethod
    def proposal(
        symbol: str,
        digit: str,
        tx_digit: str,
    ) -> dict[str, object]:
        identity = contract("bsc", digit)
        return {
            "symbol": symbol,
            "priority": "P1_MONITOR",
            "contracts": [identity],
            "watchlist_proposal": {"contracts": [identity]},
            "txs": ["0x" + tx_digit * 64],
        }

    def test_registry_merge_is_one_cross_process_transaction(self) -> None:
        payload, summary = self.merge_concurrently(
            (
                self.proposal("ONE", "1", "a"),
                self.proposal("TWO", "2", "b"),
            )
        )

        self.assertEqual(
            {project["symbol"] for project in payload["projects"]},
            {"ONE", "TWO"},
        )
        self.assertIn("ONE", summary)
        self.assertIn("TWO", summary)

    def test_registry_concurrent_same_identity_does_not_duplicate(self) -> None:
        payload, summary = self.merge_concurrently(
            (
                self.proposal("SAME", "3", "c"),
                self.proposal("RENAMED", "3", "d"),
            )
        )

        self.assertEqual(len(payload["projects"]), 1)
        project = payload["projects"][0]
        self.assertEqual(set(project["txs"]), {"0x" + "c" * 64, "0x" + "d" * 64})
        self.assertEqual(
            {project["symbol"], *project["aliases"]},
            {"SAME", "RENAMED"},
        )
        self.assertIn(project["symbol"], summary)

    def test_registry_atomic_writers_preserve_original_on_failure(self) -> None:
        failures = (OSError("write failed"), KeyboardInterrupt())
        writers = (
            ("json", registry.write_json, {"projects": [{"symbol": "NEW"}]}),
            ("summary", registry.write_text_atomic, "# New Registry\n"),
        )
        for writer_name, writer, replacement in writers:
            for failure in failures:
                with self.subTest(
                    writer=writer_name,
                    failure=type(failure).__name__,
                ):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        suffix = ".json" if writer_name == "json" else ".md"
                        path = Path(temp_dir) / f"registry{suffix}"
                        original = "{\"projects\": []}" if writer_name == "json" else "# Original\n"
                        path.write_text(original, encoding="utf-8")
                        with mock.patch.object(
                            os,
                            "fsync",
                            side_effect=failure,
                        ):
                            with self.assertRaises(type(failure)):
                                writer(path, replacement)
                        self.assertEqual(
                            path.read_text(encoding="utf-8"),
                            original,
                        )
                        self.assertEqual(
                            [child.name for child in path.parent.iterdir()],
                            [path.name],
                        )

    def test_registry_atomic_writers_preserve_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "registry.json"
            summary_path = root / "registry.md"
            registry_path.write_text("{}", encoding="utf-8")
            summary_path.write_text("# Old\n", encoding="utf-8")
            registry_path.chmod(0o640)
            summary_path.chmod(0o640)

            registry.write_json(registry_path, {"projects": []})
            registry.write_text_atomic(summary_path, "# New\n")

            self.assertEqual(registry_path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(summary_path.stat().st_mode & 0o777, 0o640)

    def test_registry_lock_uses_ignored_output_path(self) -> None:
        self.assertEqual(
            registry.LOCK_PATH,
            ROOT / "output" / "locks" / "project_registry.lock",
        )


class WatchlistIdentityMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            {
                "symbol": "SAME",
                "aliases": ["SHARED"],
                "contracts": [contract("bsc", "1")],
                "catalysts": [],
            },
            {
                "symbol": "SAME",
                "aliases": ["SHARED"],
                "contracts": [contract("base", "2")],
                "catalysts": [],
            },
        ]

    def test_explicit_identity_controls_watchlist_merge(self) -> None:
        cases = (
            ("different contract", "SAME", contract("bsc", "3"), 3),
            ("different chain", "SAME", contract("base", "1"), 3),
            ("same identity renamed", "RENAMED", contract("bsc", "1"), 1),
        )
        for label, symbol, identity, expected_count in cases:
            proposal = {
                "symbol": symbol,
                "contracts": [identity],
                "catalysts": ["new"],
            }
            with self.subTest(label):
                merged = ingest.merge_by_symbol(
                    copy.deepcopy(self.items[:1] if expected_count == 1 else self.items),
                    proposal,
                )
                self.assertEqual(len(merged), expected_count)
                if expected_count == 1:
                    self.assertEqual(merged[0]["catalysts"], ["new"])
                else:
                    self.assertEqual(merged[-1], proposal)

    def test_alias_fallback_rejects_multi_identity_targets(self) -> None:
        item = dict(self.items[0])
        item["contracts"] = [
            contract("bsc", "1"),
            contract("base", "2"),
        ]
        cases = (
            ("two candidates", self.items, 3),
            ("one identity", self.items[:1], 1),
            ("one multi-identity candidate", [item], 2),
        )
        for label, items, expected_count in cases:
            proposal = {
                "symbol": "SHARED",
                "contracts": [],
                "catalysts": ["new"],
            }
            with self.subTest(label):
                merged = ingest.merge_by_symbol(
                    copy.deepcopy(items),
                    proposal,
                )
                self.assertEqual(len(merged), expected_count)
                if expected_count == 1:
                    self.assertEqual(merged[0]["catalysts"], ["new"])
                else:
                    self.assertEqual(merged[-1], proposal)

    def test_same_identity_contract_metadata_does_not_duplicate_row(self) -> None:
        existing = {
            **copy.deepcopy(self.items[0]),
            "contracts": [
                {
                    **contract("bsc", "1"),
                    "confidence": "verified_catalog",
                    "source": "curated",
                }
            ],
        }
        proposal = {
            "symbol": "RENAMED",
            "contracts": [
                {
                    **contract("bnb", "1"),
                    "confidence": "signal_ingest_token_contract",
                    "evidence_id": "signal-1",
                }
            ],
        }

        merged = ingest.merge_by_symbol([existing], proposal)

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["contracts"],
            [
                {
                    **contract("bsc", "1"),
                    "confidence": "verified_catalog",
                    "source": "curated",
                    "evidence_id": "signal-1",
                }
            ],
        )


class WatchlistAutoApplyScopeTests(unittest.TestCase):
    @staticmethod
    def focused_watchlist() -> dict[str, object]:
        return {
            "monitoring_policy": {
                "mode": "exclusive_symbols",
                "symbols": ["FOCUS"],
            },
            "items": [
                {
                    "symbol": "FOCUS",
                    "name": "Focus",
                    "priority": "P1_MONITOR",
                    "active_monitoring": True,
                    "chain": "bsc",
                    "contracts": [
                        {
                            **contract("bsc", "1"),
                            "confidence": "curated",
                        }
                    ],
                    "known_times": [
                        {
                            "time": "2026-08-11 10:00:00",
                            "reason": "listing_time",
                        }
                    ],
                    "catalysts": [],
                }
            ],
        }

    def apply_proposal(self, proposal: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watchlist_path = root / "watchlist.json"
            prediction_path = root / "predictions.json"
            lock_path = root / ".alpha_signal_apply.lock"
            watchlist_path.write_text(
                json.dumps(self.focused_watchlist()),
                encoding="utf-8",
            )
            prediction_path.write_text(
                json.dumps({"items": []}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    ingest,
                    "WATCHLIST_PATH",
                    watchlist_path,
                ),
                mock.patch.object(
                    ingest,
                    "PREDICTION_PATH",
                    prediction_path,
                ),
                mock.patch.object(
                    ingest,
                    "APPLY_LOCK_PATH",
                    lock_path,
                ),
            ):
                ingest.apply_proposals(
                    {
                        "source_policy": {"context_only": False},
                        "watchlist_proposal": proposal,
                        "prediction_proposals": [],
                    }
                )
            return json.loads(watchlist_path.read_text(encoding="utf-8"))

    def apply_concurrently(
        self,
        proposals: tuple[dict[str, object], dict[str, object]],
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watchlist_path = root / "watchlist.json"
            prediction_path = root / "predictions.json"
            lock_path = root / ".alpha_signal_apply.lock"
            initial = self.focused_watchlist()
            watchlist_path.write_text(
                json.dumps(initial),
                encoding="utf-8",
            )
            prediction_path.write_text(
                json.dumps({"items": []}),
                encoding="utf-8",
            )
            context = multiprocessing.get_context("fork")
            release_path = root / "workers.release"
            ready_paths = [root / f"worker-{index}.ready" for index in range(2)]
            processes = [
                context.Process(
                    target=apply_proposal_process,
                    args=(
                        str(watchlist_path),
                        str(prediction_path),
                        str(lock_path),
                        str(ready_paths[index]),
                        str(release_path),
                        proposal,
                    ),
                )
                for index, proposal in enumerate(proposals)
            ]
            lock_path.touch()
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    for process in processes:
                        process.start()
                    deadline = time.monotonic() + 5
                    while not all(path.exists() for path in ready_paths):
                        if time.monotonic() >= deadline:
                            self.fail("auto-apply workers did not reach file barrier")
                        time.sleep(0.005)
                    release_path.write_text("release", encoding="utf-8")
                    for process in processes:
                        process.join(timeout=0.5)
                    self.assertTrue(
                        all(process.is_alive() for process in processes),
                        "auto-apply did not wait for the shared config lock",
                    )
                    self.assertEqual(
                        json.loads(watchlist_path.read_text(encoding="utf-8")),
                        initial,
                    )
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            for _ in range(1000):
                json.loads(watchlist_path.read_text(encoding="utf-8"))
                json.loads(prediction_path.read_text(encoding="utf-8"))
                if not any(process.is_alive() for process in processes):
                    break
                for process in processes:
                    process.join(timeout=0.001)
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                self.assertEqual(process.exitcode, 0)
            return json.loads(watchlist_path.read_text(encoding="utf-8"))

    def assert_preflight_passes(self, payload: dict[str, object]) -> None:
        from scripts.alpha_onboarding_preflight import validate_watchlist

        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_PRIORITIES": "P0,P1"},
        ):
            self.assertEqual(validate_watchlist(payload)["status"], "pass")

    @staticmethod
    def build_runtime_watchlist(
        static_watchlist: dict[str, object],
        response: dict[str, object] | None = None,
    ) -> dict[str, object]:
        from scripts import binance_alpha_catalog_watch as catalog

        payload, _selected = catalog.build_runtime_watchlist(
            static_watchlist,
            response or {
                "code": "000000",
                "success": True,
                "data": [
                    {
                        "alphaId": "ALPHA_OLD",
                        "symbol": "OLD",
                        "chainId": "56",
                        "contractAddress": "0x" + "9" * 40,
                        "listingTime": 1,
                    }
                ],
            },
            current=datetime(2026, 8, 11, tzinfo=timezone.utc),
            lookback_hours=168,
            lookahead_hours=48,
            retention_days=30,
        )
        return payload

    def test_exclusive_auto_apply_keeps_new_rows_inactive(self) -> None:
        policy = self.focused_watchlist()["monitoring_policy"]
        cases = (
            (
                "unrelated symbol",
                {
                    "symbol": "OTHER",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "contracts": [contract("bsc", "2")],
                },
            ),
            (
                "same ticker different identity",
                {
                    "symbol": "FOCUS",
                    "priority": "P1_MONITOR",
                    "chain": "bsc",
                    "contracts": [contract("bsc", "3")],
                },
            ),
        )
        for label, proposal in cases:
            with self.subTest(label):
                payload = self.apply_proposal(proposal)

                self.assertEqual(payload["monitoring_policy"], policy)
                self.assertEqual(len(payload["items"]), 2)
                self.assertTrue(payload["items"][0]["active_monitoring"])
                self.assertFalse(payload["items"][1]["active_monitoring"])
                self.assert_preflight_passes(payload)

    def test_exclusive_auto_apply_merges_same_identity_without_duplication(
        self,
    ) -> None:
        payload = self.apply_proposal(
            {
                "symbol": "RENAMED",
                "priority": "P1_MONITOR",
                "chain": "bsc",
                "contracts": [
                    {
                        **contract("bnb", "1"),
                        "evidence_id": "signal-1",
                    }
                ],
                "catalysts": ["new metadata"],
            }
        )

        self.assertEqual(
            payload["monitoring_policy"],
            self.focused_watchlist()["monitoring_policy"],
        )
        self.assertEqual(len(payload["items"]), 1)
        self.assertTrue(payload["items"][0]["active_monitoring"])
        self.assertEqual(
            payload["items"][0]["contracts"],
            [
                {
                    **contract("bsc", "1"),
                    "confidence": "curated",
                    "evidence_id": "signal-1",
                }
            ],
        )
        self.assertEqual(payload["items"][0]["catalysts"], ["new metadata"])
        self.assert_preflight_passes(payload)

    def test_exclusive_auto_apply_is_one_cross_process_transaction(self) -> None:
        payload = self.apply_concurrently(
            (
                {
                    "symbol": "NEW2",
                    "priority": "P1_MONITOR",
                    "contracts": [contract("bsc", "2")],
                },
                {
                    "symbol": "NEW3",
                    "priority": "P1_MONITOR",
                    "contracts": [contract("bsc", "3")],
                },
            )
        )

        self.assertEqual(
            {row["symbol"] for row in payload["items"]},
            {"FOCUS", "NEW2", "NEW3"},
        )
        self.assertTrue(payload["items"][0]["active_monitoring"])
        self.assertTrue(
            all(
                row["active_monitoring"] is False
                for row in payload["items"]
                if row["symbol"] != "FOCUS"
            )
        )
        self.assert_preflight_passes(payload)

    def test_cross_process_same_identity_metadata_stays_one_row(self) -> None:
        payload = self.apply_concurrently(
            (
                {
                    "symbol": "FOCUS",
                    "priority": "P1_MONITOR",
                    "contracts": [contract("bsc", "1")],
                    "catalysts": ["first"],
                },
                {
                    "symbol": "FOCUS",
                    "priority": "P1_MONITOR",
                    "contracts": [contract("bsc", "1")],
                    "catalysts": ["second"],
                },
            )
        )

        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(
            set(payload["items"][0]["catalysts"]),
            {"first", "second"},
        )
        self.assertTrue(payload["items"][0]["active_monitoring"])
        self.assert_preflight_passes(payload)

    def test_atomic_config_write_preserves_original_on_failure(self) -> None:
        failures = (OSError("write failed"), KeyboardInterrupt())
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with tempfile.TemporaryDirectory() as temp_dir:
                    path = Path(temp_dir) / "config.json"
                    original = {"items": [{"symbol": "ORIGINAL"}]}
                    path.write_text(json.dumps(original), encoding="utf-8")

                    with mock.patch.object(
                        os,
                        "fsync",
                        side_effect=failure,
                    ):
                        with self.assertRaises(type(failure)):
                            ingest.write_json(
                                path,
                                {"items": [{"symbol": "REPLACEMENT"}]},
                            )

                    self.assertEqual(
                        json.loads(path.read_text(encoding="utf-8")),
                        original,
                    )
                    self.assertEqual(
                        [child.name for child in path.parent.iterdir()],
                        ["config.json"],
                    )

    def test_atomic_config_write_preserves_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"items": []}), encoding="utf-8")
            path.chmod(0o640)

            ingest.write_json(path, {"items": [{"symbol": "UPDATED"}]})

            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"items": [{"symbol": "UPDATED"}]},
            )

    def test_auto_apply_lock_uses_ignored_output_path(self) -> None:
        self.assertEqual(
            ingest.APPLY_LOCK_PATH,
            ROOT / "output" / "locks" / "alpha_signal_apply.lock",
        )
        self.assertFalse((ROOT / "config" / ".alpha_signal_apply.lock").exists())

    def test_catalog_does_not_reactivate_auto_applied_new_identity(self) -> None:
        cases = (
            ("same ticker", "FOCUS", "2"),
            ("unrelated symbol", "OTHER", "3"),
        )
        for label, symbol, digit in cases:
            with self.subTest(label):
                static = self.apply_proposal(
                    {
                        "symbol": symbol,
                        "priority": "P1_MONITOR",
                        "chain": "bsc",
                        "contracts": [contract("bsc", digit)],
                    }
                )
                runtime = self.build_runtime_watchlist(static)
                rows = {
                    row["contracts"][0]["address"]: row
                    for row in runtime["items"]
                }

                self.assertTrue(
                    rows[contract("bsc", "1")["address"]][
                        "active_monitoring"
                    ]
                )
                self.assertFalse(
                    rows[contract("bsc", digit)["address"]][
                        "active_monitoring"
                    ]
                )
                self.assertEqual(runtime["active_monitoring_item_count"], 1)
                self.assertEqual(runtime["active_monitoring_symbols"], ["FOCUS"])
                self.assert_preflight_passes(runtime)

    def test_catalog_keeps_same_identity_auto_apply_merge_active(self) -> None:
        static = self.apply_proposal(
            {
                "symbol": "RENAMED",
                "priority": "P1_MONITOR",
                "chain": "bsc",
                "contracts": [contract("bnb", "1")],
                "catalysts": ["same identity metadata"],
            }
        )

        runtime = self.build_runtime_watchlist(static)

        self.assertEqual(len(runtime["items"]), 1)
        self.assertTrue(runtime["items"][0]["active_monitoring"])
        self.assertEqual(
            runtime["items"][0]["catalysts"],
            ["same identity metadata"],
        )
        self.assert_preflight_passes(runtime)

    def test_catalog_policy_preserves_only_explicit_false(self) -> None:
        from scripts import binance_alpha_catalog_watch as catalog

        scoped = catalog.apply_monitoring_policy(
            [
                {"symbol": "FOCUS", "active_monitoring": False},
                {"symbol": "FOCUS"},
                {"symbol": "FOCUS", "active_monitoring": "pending"},
                {"symbol": "OTHER", "active_monitoring": True},
            ],
            {"mode": "exclusive_symbols", "symbols": ["FOCUS"]},
        )

        self.assertEqual(
            [row["active_monitoring"] for row in scoped],
            [False, True, True, False],
        )

    def test_catalog_summary_keeps_focused_explicit_false_inactive(self) -> None:
        from scripts import binance_alpha_catalog_watch as catalog

        policy = {"mode": "exclusive_symbols", "symbols": ["FOCUS"]}
        summary = catalog.public_summary(
            current=datetime(2026, 8, 11, tzinfo=timezone.utc),
            token_count=1,
            selected=[
                {
                    "symbol": "FOCUS",
                    "active_monitoring": False,
                    "contracts": [contract("bsc", "2")],
                }
            ],
            runtime_watchlist={
                "monitoring_policy": policy,
                "monitoring_policy_fingerprint": (
                    catalog.monitoring_policy_fingerprint(policy)
                ),
            },
            lookback_hours=168,
            lookahead_hours=48,
            max_selected=64,
        )

        self.assertFalse(summary["selected"][0]["active_monitoring"])

    def test_official_catalog_cannot_reactivate_pending_same_ticker_identity(
        self,
    ) -> None:
        pending_contract = contract("bsc", "2")
        static = self.apply_proposal(
            {
                "symbol": "FOCUS",
                "priority": "P1_MONITOR",
                "chain": "bsc",
                "contracts": [pending_contract],
            }
        )
        official_time = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)
        runtime = self.build_runtime_watchlist(
            static,
            {
                "code": "000000",
                "success": True,
                "data": [
                    {
                        "alphaId": "ALPHA_PENDING",
                        "symbol": "FOCUS",
                        "name": "Pending Focus",
                        "chainId": "56",
                        "contractAddress": pending_contract["address"],
                        "listingTime": int(official_time.timestamp() * 1000),
                    }
                ],
            },
        )
        rows = {
            row["contracts"][0]["address"]: row
            for row in runtime["items"]
        }

        self.assertTrue(
            rows[contract("bsc", "1")["address"]]["active_monitoring"]
        )
        self.assertFalse(
            rows[pending_contract["address"]]["active_monitoring"]
        )
        self.assertEqual(runtime["active_monitoring_item_count"], 1)
        self.assert_preflight_passes(runtime)

    def test_official_catalog_still_reactivates_legacy_inactive_item(self) -> None:
        from scripts import binance_alpha_catalog_watch as catalog

        merged = catalog.merge_item(
            {
                "symbol": "LEGACY",
                "active_monitoring": False,
                "contracts": [contract("bsc", "4")],
            },
            {
                "symbol": "LEGACY",
                "active_monitoring": True,
                "contracts": [contract("bsc", "4")],
                "facts": {"catalog_cohort_source": "current_catalog"},
            },
        )

        self.assertTrue(merged["active_monitoring"])
        self.assertEqual(
            merged["facts"]["catalog_active_monitoring_policy"],
            "official_cohort_reactivates_static_item",
        )


class OptionalAirdropHealthTests(unittest.TestCase):
    ABSENT = object()

    @staticmethod
    def write_watchlist(path: Path, event_schedule: object = None) -> None:
        item = {
            "symbol": "PLAIN",
            "priority": "P1_MONITOR",
            "active_monitoring": True,
            "contracts": [contract("bsc", "4")],
        }
        if event_schedule is not None:
            item["event_schedule"] = event_schedule
        path.write_text(json.dumps({"items": [item]}), encoding="utf-8")

    def configured_result(
        self,
        event_schedule: object = ABSENT,
        *,
        raw_payload: dict[str, object] | None = None,
    ) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            watchlist = Path(temp_dir) / "watchlist.json"
            if raw_payload is not None:
                watchlist.write_text(
                    json.dumps(raw_payload),
                    encoding="utf-8",
                )
            elif event_schedule is self.ABSENT:
                self.write_watchlist(watchlist)
            else:
                self.write_watchlist(watchlist, event_schedule)
            with mock.patch.object(
                health,
                "airdrop_watchlist_path",
                return_value=watchlist,
            ):
                return health.configured_airdrop_identity_hash()

    def test_airdrop_schedule_is_optional(self) -> None:
        expected = (health.airdrop_identity_hash([]), "")
        for label, schedule in (
            ("absent", self.ABSENT),
            (
                "launch only",
                [{"event_type": "alpha_open", "event_id": "launch"}],
            ),
        ):
            with self.subTest(label):
                self.assertEqual(self.configured_result(schedule), expected)

    def test_airdrop_event_type_is_trimmed_before_validation(self) -> None:
        expected = health.airdrop_identity_hash(
            [
                {
                    "symbol": "PLAIN",
                    "contract": contract("bsc", "4")["address"],
                    "event_id": "drop-1",
                }
            ]
        )

        self.assertEqual(
            self.configured_result(
                [
                    {
                        "event_type": " airdrop_claim ",
                        "event_id": "drop-1",
                    }
                ]
            ),
            (expected, ""),
        )

    def test_explicit_invalid_airdrop_configuration_fails_closed(self) -> None:
        cases = (
            (
                "malformed watchlist",
                self.ABSENT,
                {},
                "configured airdrop watchlist invalid",
            ),
            (
                "missing event identity",
                [{"event_type": "airdrop_claim"}],
                None,
                "configured airdrop event identity missing",
            ),
            (
                "invalid schedule container",
                {"event_type": "airdrop_claim", "event_id": "drop"},
                None,
                "configured airdrop event schedule invalid",
            ),
            (
                "invalid schedule row",
                [None],
                None,
                "configured airdrop event schedule invalid",
            ),
            (
                "explicit non-airdrop mapping",
                {"event_type": "alpha_open", "event_id": "launch"},
                None,
                "configured airdrop event schedule invalid",
            ),
            (
                "explicit null schedule",
                self.ABSENT,
                {
                    "items": [
                        {
                            "symbol": "PLAIN",
                            "priority": "P1_MONITOR",
                            "active_monitoring": True,
                            "contracts": [contract("bsc", "4")],
                            "event_schedule": None,
                        }
                    ]
                },
                "configured airdrop event schedule invalid",
            ),
            (
                "null contracts for airdrop",
                self.ABSENT,
                {
                    "items": [
                        {
                            "symbol": "PLAIN",
                            "priority": "P1_MONITOR",
                            "active_monitoring": True,
                            "contracts": None,
                            "event_schedule": [
                                {
                                    "event_type": "airdrop_claim",
                                    "event_id": "drop",
                                }
                            ],
                        }
                    ]
                },
                "configured airdrop event identity missing",
            ),
        )
        for label, schedule, raw_payload, expected_detail in cases:
            with self.subTest(label):
                _identity_hash, detail = self.configured_result(
                    schedule,
                    raw_payload=raw_payload,
                )
                self.assertEqual(detail, expected_detail)

    def test_zero_airdrop_prelaunch_output_is_healthy(self) -> None:
        empty_hash = health.airdrop_identity_hash([])
        payload = {
            "schema": "alpha_prelaunch_watch.v2",
            "events": [],
            "airdrop_pressure_events": [],
            "airdrop_pressure_required_count": 0,
            "airdrop_pressure_event_count": 0,
            "airdrop_pressure_expected_identity_hash": empty_hash,
            "airdrop_pressure_processed_identity_hash": empty_hash,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watchlist = root / "watchlist.json"
            output = root / "prelaunch.json"
            self.write_watchlist(watchlist)
            output.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch.object(
                    health,
                    "airdrop_watchlist_path",
                    return_value=watchlist,
                ),
                mock.patch.object(
                    health,
                    "CORE_OUTPUTS",
                    (("prelaunch", output),),
                ),
            ):
                issues, _rows = health.output_checks(60)

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
