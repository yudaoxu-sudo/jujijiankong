from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

os.environ.setdefault("SNIPER_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import alpha_onboarding_preflight as preflight
from scripts import binance_alpha_catalog_watch as catalog


PROFILE = "binance_alpha_bsc.v1"
ADAPTER = "generic_alpha_watchers.v1"
USDT = "0x55d398326f99059ff775485246999027b3197955"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"


def item(
    symbol: str,
    digit: str,
    *,
    opening: str = "2026-08-10 17:00",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "active_monitoring": True,
        "priority": "P1_MONITOR",
        "contracts": [{"chain": "bsc", "address": "0x" + digit * 40}],
        "known_times": [{"time": opening, "reason": "binance_alpha_listing_time"}],
        "pool_ids": [
            {
                "chain": "bsc",
                "pool_id": "",
                "start_time_utc8": opening,
                "quote_address": USDT,
            }
        ],
    }


def watchlist(*items: dict[str, object]) -> dict[str, object]:
    symbols = [str(row["symbol"]) for row in items]
    return {
        "monitoring_policy": {"mode": "exclusive_symbols", "symbols": symbols},
        "items": list(items),
    }


class AlphaOnboardingPreflightTests(unittest.TestCase):
    def assert_issue(self, payload: dict[str, object], code: str, *, capacity: int = 8) -> None:
        result = preflight.validate_watchlist(payload, profile=PROFILE, holder_capacity=capacity)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(code, result["issue_codes"])

    def test_legacy_policy_gate_accepts_symbol_and_active_only_but_preflight_blocks(self) -> None:
        minimal = {
            "monitoring_policy": {"mode": "exclusive_symbols", "symbols": ["NEW"]},
            "items": [{"symbol": "NEW", "active_monitoring": True}],
        }
        runtime = copy.deepcopy(minimal)
        runtime["monitoring_policy_fingerprint"] = catalog.monitoring_policy_fingerprint(
            minimal["monitoring_policy"]
        )
        self.assertTrue(catalog.watchlist_policy_compatible(runtime, minimal))
        self.assert_issue(minimal, "priority_invalid")
        self.assert_issue(minimal, "contract_count_invalid")
        self.assert_issue(minimal, "opening_anchor_missing")

    def test_valid_profile_is_generic_and_airdrop_is_optional(self) -> None:
        payload = watchlist(item("ONE", "1"), item("TWO", "2"))
        result = preflight.validate_watchlist(payload, profile=PROFILE, holder_capacity=2)
        self.assertEqual(
            result,
            {
                "status": "pass",
                "profile": PROFILE,
                "adapter": ADAPTER,
                "focused_symbol_count": 2,
                "active_item_count": 2,
                "holder_capacity": 2,
                "issue_codes": [],
            },
        )

    def test_runtime_review_symbol_filters_must_match_focused_active_symbol(
        self,
    ) -> None:
        payload = watchlist(item("ONE", "1"))
        cases = (
            ("missing", {}, "pass"),
            (
                "empty",
                {
                    "ALPHA_INTRADAY_REVIEW_SYMBOL": "",
                    "ALPHA_PRICE_REVIEW_SYMBOL": "",
                },
                "pass",
            ),
            (
                "exact",
                {
                    "ALPHA_INTRADAY_REVIEW_SYMBOL": "ONE",
                    "ALPHA_PRICE_REVIEW_SYMBOL": "ONE",
                },
                "pass",
            ),
            (
                "case insensitive",
                {
                    "ALPHA_INTRADAY_REVIEW_SYMBOL": "one",
                    "ALPHA_PRICE_REVIEW_SYMBOL": "oNe",
                },
                "pass",
            ),
            (
                "stale intraday",
                {"ALPHA_INTRADAY_REVIEW_SYMBOL": "STALE"},
                "blocked",
            ),
            (
                "stale price",
                {"ALPHA_PRICE_REVIEW_SYMBOL": "STALE"},
                "blocked",
            ),
            (
                "intraday leading whitespace",
                {"ALPHA_INTRADAY_REVIEW_SYMBOL": " ONE"},
                "blocked",
            ),
            (
                "price trailing whitespace",
                {"ALPHA_PRICE_REVIEW_SYMBOL": "ONE "},
                "blocked",
            ),
        )
        for label, environment, expected_status in cases:
            with self.subTest(label), mock.patch.dict(
                os.environ,
                {"SNIPER_OFFLINE": "1", **environment},
                clear=True,
            ):
                result = preflight.validate_watchlist(
                    payload,
                    profile=PROFILE,
                    holder_capacity=1,
                )

            self.assertEqual(result["status"], expected_status)
            self.assertEqual(
                "runtime_symbol_filter_invalid" in result["issue_codes"],
                expected_status == "blocked",
            )

    def test_current_static_and_runtime_watchlists_are_valid(self) -> None:
        static = json.loads(
            (ROOT / "config/current_alpha_watchlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            preflight.validate_watchlist(static, profile=PROFILE, holder_capacity=8)["status"],
            "pass",
        )
        runtime = copy.deepcopy(static)
        runtime["runtime_source"] = "catalog"
        runtime["monitoring_policy_fingerprint"] = catalog.monitoring_policy_fingerprint(
            runtime["monitoring_policy"]
        )
        self.assertEqual(
            preflight.validate_watchlist(runtime, profile=PROFILE, holder_capacity=8)["status"],
            "pass",
        )

    def test_cycle_snapshot_is_content_addressed_and_source_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "watchlist.json"
            snapshots = root / "runtime_watchlist_cycles"
            original = json.dumps(watchlist(item("ONE", "1")), sort_keys=True).encode(
                "utf-8"
            )
            source.write_bytes(original)

            snapshot = preflight.materialize_watchlist(source, snapshots)
            reused = preflight.materialize_watchlist(source, snapshots)
            source.write_text(
                json.dumps(watchlist(item("TWO", "2"))),
                encoding="utf-8",
            )

            self.assertEqual(snapshot, reused)
            self.assertEqual(snapshot.parent, snapshots)
            self.assertEqual(snapshot.name, hashlib.sha256(original).hexdigest() + ".json")
            self.assertEqual(snapshot.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o444)
            self.assertEqual(
                preflight.validate_watchlist(
                    json.loads(snapshot.read_text(encoding="utf-8")),
                    profile=PROFILE,
                    holder_capacity=1,
                )["status"],
                "pass",
            )

    def test_cycle_selection_snapshots_the_policy_checked_bytes_across_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            curated = root / "curated.json"
            runtime = root / "runtime.json"
            replacement = root / "replacement.json"
            snapshots = root / "runtime_watchlist_cycles"
            static_payload = watchlist(item("ONE", "1"))
            runtime_payload = copy.deepcopy(static_payload)
            runtime_payload["monitoring_policy_fingerprint"] = (
                catalog.monitoring_policy_fingerprint(
                    runtime_payload["monitoring_policy"]
                )
            )
            replacement_payload = watchlist(item("OTHER", "2"))
            curated.write_text(json.dumps(static_payload), encoding="utf-8")
            runtime_bytes = json.dumps(runtime_payload, sort_keys=True).encode("utf-8")
            runtime.write_bytes(runtime_bytes)
            replacement.write_text(json.dumps(replacement_payload), encoding="utf-8")

            policy_checked = threading.Event()
            release_policy_check = threading.Event()
            original_reader = preflight.read_regular_file_once
            original_compatible = catalog.watchlist_policy_compatible
            runtime_reads = 0

            def counting_reader(path: Path):
                nonlocal runtime_reads
                payload, metadata = original_reader(path)
                if Path(path) == runtime:
                    runtime_reads += 1
                return payload, metadata

            def barrier_compatible(runtime_watchlist, static_watchlist):
                compatible = original_compatible(
                    runtime_watchlist,
                    static_watchlist,
                )
                policy_checked.set()
                if not release_policy_check.wait(timeout=5):
                    raise TimeoutError("policy replacement barrier timed out")
                return compatible

            with mock.patch.object(
                preflight,
                "read_regular_file_once",
                side_effect=counting_reader,
            ), mock.patch.object(
                catalog,
                "watchlist_policy_compatible",
                side_effect=barrier_compatible,
            ), ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    preflight.select_and_materialize_watchlist,
                    runtime_path=runtime,
                    static_path=curated,
                    max_age_seconds=60,
                    output_dir=snapshots,
                )
                self.assertTrue(policy_checked.wait(timeout=5))
                try:
                    replacement.replace(runtime)
                finally:
                    release_policy_check.set()
                selected = future.result(timeout=5)

            self.assertEqual(runtime_reads, 1)
            self.assertEqual(selected.read_bytes(), runtime_bytes)
            self.assertNotEqual(selected.read_bytes(), runtime.read_bytes())
            self.assertFalse(
                original_compatible(
                    json.loads(runtime.read_bytes()),
                    static_payload,
                )
            )

    def test_cycle_selection_uses_source_fstat_for_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            curated = root / "curated.json"
            runtime = root / "runtime.json"
            snapshots = root / "runtime_watchlist_cycles"
            static_bytes = json.dumps(watchlist(item("ONE", "1"))).encode("utf-8")
            runtime_payload = watchlist(item("ONE", "1"))
            runtime_payload["monitoring_policy_fingerprint"] = (
                catalog.monitoring_policy_fingerprint(
                    runtime_payload["monitoring_policy"]
                )
            )
            runtime_bytes = json.dumps(runtime_payload).encode("utf-8")
            curated.write_bytes(static_bytes)
            runtime.write_bytes(runtime_bytes)
            stale_time = time.time() - 120
            os.utime(runtime, (stale_time, stale_time))

            selected = preflight.select_and_materialize_watchlist(
                runtime_path=runtime,
                static_path=curated,
                max_age_seconds=60,
                output_dir=snapshots,
            )

            self.assertEqual(selected.read_bytes(), static_bytes)
            self.assertNotEqual(selected.read_bytes(), runtime_bytes)
            self.assertLess(time.time() - selected.stat().st_mtime, 10)
            with self.assertRaisesRegex(ValueError, "stale or violates"):
                preflight.select_and_materialize_watchlist(
                    runtime_path=runtime,
                    static_path=curated,
                    max_age_seconds=60,
                    configured_path=runtime,
                    output_dir=snapshots,
                )

    def test_curated_source_is_read_once_and_snapshots_that_exact_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            curated = root / "curated.json"
            replacement = root / "replacement.json"
            snapshots = root / "runtime_watchlist_cycles"
            static_bytes = json.dumps(watchlist(item("ONE", "1"))).encode("utf-8")
            curated.write_bytes(static_bytes)
            replacement.write_text(
                json.dumps(watchlist(item("OTHER", "2"))),
                encoding="utf-8",
            )
            original_reader = preflight.read_regular_file_once
            curated_reads = 0

            def replacing_reader(path: Path):
                nonlocal curated_reads
                payload, metadata = original_reader(path)
                if Path(path) == curated:
                    curated_reads += 1
                    replacement.replace(curated)
                return payload, metadata

            with mock.patch.object(
                preflight,
                "read_regular_file_once",
                side_effect=replacing_reader,
            ):
                selected = preflight.select_and_materialize_watchlist(
                    runtime_path=curated,
                    static_path=curated,
                    max_age_seconds=60,
                    configured_path=curated,
                    output_dir=snapshots,
                )

            self.assertEqual(curated_reads, 1)
            self.assertEqual(selected.read_bytes(), static_bytes)
            self.assertNotEqual(selected.read_bytes(), curated.read_bytes())

    def test_cycle_snapshot_rejects_existing_conflict_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "watchlist.json"
            snapshots = root / "runtime_watchlist_cycles"
            snapshots.mkdir()
            source_bytes = json.dumps(watchlist(item("ONE", "1"))).encode(
                "utf-8"
            )
            source.write_bytes(source_bytes)
            target = snapshots / (hashlib.sha256(source_bytes).hexdigest() + ".json")
            target.write_text("{}", encoding="utf-8")
            target.chmod(0o444)

            with self.assertRaisesRegex(OSError, "content mismatch"):
                preflight.materialize_watchlist(source, snapshots)

            target.unlink()
            target.symlink_to(source)
            with self.assertRaises(OSError):
                preflight.materialize_watchlist(source, snapshots)

            target.unlink()
            source_link = root / "source-link.json"
            source_link.symlink_to(source)
            with self.assertRaises(OSError):
                preflight.materialize_watchlist(source_link, snapshots)

    def test_focus_requires_one_active_item_and_no_extra_active_items(self) -> None:
        one = item("ONE", "1")
        duplicate = copy.deepcopy(one)
        payload = watchlist(one)
        payload["items"].append(duplicate)
        self.assert_issue(payload, "focused_item_count_invalid")

        payload = watchlist(one)
        payload["items"].append(item("EXTRA", "2"))
        self.assert_issue(payload, "active_scope_mismatch")

        payload = watchlist(one)
        payload["items"][0]["active_monitoring"] = False
        self.assert_issue(payload, "focused_item_inactive")

        for value in (" ONE", "ONE "):
            with self.subTest(item_symbol=value):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["symbol"] = value
                self.assert_issue(payload, "focused_item_count_invalid")

        for value in (" ONE", "ONE ", 1):
            with self.subTest(policy_symbol=value):
                payload = watchlist(item("ONE", "1"))
                payload["monitoring_policy"]["symbols"] = [value]
                self.assert_issue(payload, "monitoring_policy_invalid")

        payload = watchlist(item("one", "1"))
        payload["monitoring_policy"]["symbols"] = ["ONE"]
        self.assertEqual(
            preflight.validate_watchlist(
                payload,
                profile=PROFILE,
                holder_capacity=8,
            )["status"],
            "pass",
        )

    def test_profile_adapter_and_priority_are_bounded(self) -> None:
        payload = watchlist(item("ONE", "1"))
        payload["monitoring_profile"] = "unknown.v1"
        self.assert_issue(payload, "profile_unsupported")

        payload = watchlist(item("ONE", "1"))
        payload["monitoring_adapter"] = "custom.v1"
        self.assert_issue(payload, "adapter_unsupported")

        for field in (
            "project_watch_skip_generic",
            "opening_watch_skip_generic",
        ):
            for value in (True, "true", 1, 0, None):
                with self.subTest(field=field, value=value):
                    payload = watchlist(item("ONE", "1"))
                    payload["items"][0][field] = value
                    self.assert_issue(payload, "adapter_unsupported")

            payload = watchlist(item("ONE", "1"))
            payload["items"][0][field] = False
            self.assertEqual(
                preflight.validate_watchlist(
                    payload,
                    profile=PROFILE,
                    holder_capacity=8,
                )["status"],
                "pass",
            )

        for priority in (
            "P2_PAPER_TRADE",
            "p1_monitor",
            " P1_MONITOR",
        ):
            with self.subTest(priority=priority):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["priority"] = priority
                self.assert_issue(payload, "priority_invalid")

    def test_holder_priority_filter_further_bounds_profile_priorities(self) -> None:
        p1_payload = watchlist(item("ONE", "1"))
        p0_payload = copy.deepcopy(p1_payload)
        p0_payload["items"][0]["priority"] = "P0_DEEP_REVIEW"

        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_PRIORITIES": "P0"},
        ):
            self.assert_issue(p1_payload, "priority_invalid")
            self.assertEqual(
                preflight.validate_watchlist(
                    p0_payload,
                    profile=PROFILE,
                    holder_capacity=8,
                )["status"],
                "pass",
            )

        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_PRIORITIES": "P0,P1"},
        ):
            self.assertEqual(
                preflight.validate_watchlist(
                    p1_payload,
                    profile=PROFILE,
                    holder_capacity=8,
                )["status"],
                "pass",
            )

    def test_contract_identity_must_be_one_valid_unique_bsc_address(self) -> None:
        payload = watchlist(item("ONE", "1"))
        self.assertEqual(
            preflight.validate_watchlist(
                payload,
                profile=PROFILE,
                holder_capacity=8,
            )["status"],
            "pass",
        )

        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["contracts"] = []
        self.assert_issue(payload, "contract_count_invalid")

        for chain in ("base", " bsc"):
            with self.subTest(chain=chain):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["contracts"][0]["chain"] = chain
                self.assert_issue(payload, "contract_chain_invalid")

        for chain in (None, "", 0, False, " bsc"):
            with self.subTest(item_chain=chain):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["chain"] = chain
                self.assert_issue(payload, "contract_chain_invalid")

        payload = watchlist(item("ONE", "1"))
        payload["items"][0].pop("chain", None)
        self.assertEqual(
            preflight.validate_watchlist(
                payload,
                profile=PROFILE,
                holder_capacity=8,
            )["status"],
            "pass",
        )

        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["contracts"][0]["address"] = "leak-marker"
        self.assert_issue(payload, "contract_address_invalid")

        for quote_token in (USDT, WBNB):
            with self.subTest(quote_token=quote_token):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["contracts"][0]["address"] = quote_token
                self.assert_issue(payload, "contract_address_invalid")

        one = item("ONE", "1")
        two = item("TWO", "1")
        self.assert_issue(watchlist(one, two), "contract_identity_duplicate")

    def test_opening_anchor_must_be_unique_and_coherent(self) -> None:
        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["known_times"] = []
        payload["items"][0]["pool_ids"] = []
        self.assert_issue(payload, "opening_anchor_missing")

        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["known_times"].append(
            {
                "time": "2026-08-10 18:00",
                "reason": "binance_alpha_listing_time",
            }
        )
        self.assert_issue(payload, "opening_anchor_ambiguous")

        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["pool_ids"][0]["start_time_utc8"] = "2026-08-10 18:00"
        self.assert_issue(payload, "opening_anchor_conflict")

        payload = watchlist(item("ONE", "1"))
        payload["items"][0]["known_times"][0]["time"] = "not-a-time"
        self.assert_issue(payload, "opening_anchor_invalid")

    def test_non_opening_known_time_does_not_conflict_with_launch_anchor(self) -> None:
        for reason in (
            "airdrop_claim",
            "delisting_time",
            "post_launch_airdrop",
            "opening_to_30d_retention",
        ):
            with self.subTest(reason=reason):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["known_times"].append(
                    {"time": "2026-08-11 09:00", "reason": reason}
                )
                self.assertEqual(
                    preflight.validate_watchlist(
                        payload,
                        profile=PROFILE,
                        holder_capacity=8,
                    )["status"],
                    "pass",
                )

    def test_non_opening_known_time_does_not_synthesize_opening_pool(self) -> None:
        from scripts.alpha_opening_block_watch import opening_pool_rows

        for reason in (
            "airdrop_claim",
            "delisting_time",
            "post_launch_airdrop",
            "opening_to_30d_retention",
        ):
            with self.subTest(reason=reason):
                payload = item("ONE", "1")
                payload["known_times"] = [
                    {"time": "2026-08-11 09:00", "reason": reason}
                ]
                payload["pool_ids"] = []
                self.assertEqual(opening_pool_rows(payload), [])
                self.assert_issue(
                    watchlist(payload),
                    "opening_anchor_missing",
                )

    def test_known_time_only_synthesizes_generic_opening_discovery_row(self) -> None:
        from scripts.alpha_opening_block_watch import opening_pool_rows

        payload = item("ONE", "1")
        payload["pool_ids"] = []
        self.assertEqual(
            opening_pool_rows(payload),
            [
                {
                    "chain": "bsc",
                    "pool_id": "",
                    "start_time_utc8": "2026-08-10 17:00",
                    "source": "canonical_opening_known_time",
                    "opening_anchor_status": "discovery_pending",
                    "quote_address": USDT,
                }
            ],
        )
        self.assertEqual(
            preflight.validate_watchlist(
                watchlist(payload), profile=PROFILE, holder_capacity=8
            )["status"],
            "pass",
        )

    def test_pool_quote_shape_accepts_pair_or_canonical_quote_address(self) -> None:
        payload = watchlist(item("ONE", "1"))
        pool = payload["items"][0]["pool_ids"][0]
        pool.pop("quote_address")
        pool["pair"] = "ONE/USDT"
        self.assertEqual(
            preflight.validate_watchlist(payload, profile=PROFILE, holder_capacity=8)["status"],
            "pass",
        )

        pool["pair"] = "ONE/WBNB"
        self.assert_issue(payload, "pool_quote_invalid")

        for chain in ("base", " bsc"):
            with self.subTest(chain=chain):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["pool_ids"][0]["chain"] = chain
                self.assert_issue(payload, "pool_chain_invalid")

        for pool_id in (None, 0, False, "garbage", "0x" + "1" * 42):
            with self.subTest(pool_id=pool_id):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["pool_ids"][0]["pool_id"] = pool_id
                self.assert_issue(payload, "pool_id_invalid")

        for pool_id in ("", "0x" + "1" * 40, "0x" + "1" * 64):
            with self.subTest(valid_pool_id=pool_id):
                payload = watchlist(item("ONE", "1"))
                payload["items"][0]["pool_ids"][0]["pool_id"] = pool_id
                self.assertEqual(
                    preflight.validate_watchlist(
                        payload,
                        profile=PROFILE,
                        holder_capacity=8,
                    )["status"],
                    "pass",
                )

    def test_active_count_must_fit_holder_capacity(self) -> None:
        from scripts.alpha_holder_concentration_watch import contract_items

        payload = watchlist(item("ONE", "1"), item("TWO", "2"))
        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_MAX_PROJECTS": "2", "ALPHA_HOLDER_PRIORITIES": "P0,P1"},
        ):
            self.assertEqual(len(contract_items(payload)), 2)
        self.assertEqual(
            preflight.validate_watchlist(payload, profile=PROFILE, holder_capacity=2)["status"],
            "pass",
        )
        with mock.patch.dict(
            os.environ,
            {"ALPHA_HOLDER_MAX_PROJECTS": "1", "ALPHA_HOLDER_PRIORITIES": "P0,P1"},
        ):
            self.assertEqual(len(contract_items(payload)), 1)
        self.assert_issue(payload, "holder_capacity_exceeded", capacity=1)

    def test_cli_output_is_allowlisted_and_does_not_echo_addresses(self) -> None:
        payload = watchlist(item("ONE", "1"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watchlist.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/alpha_onboarding_preflight.py"),
                    "--watchlist",
                    str(path),
                    "--profile",
                    PROFILE,
                    "--holder-capacity",
                    "8",
                ],
                cwd=ROOT,
                env={**os.environ, "SNIPER_OFFLINE": "1"},
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(set(output), preflight.RESULT_KEYS)
        self.assertNotIn("0x", completed.stdout.lower())
        self.assertNotIn("ONE", completed.stdout)

        payload["items"][0]["contracts"][0]["address"] = "invalid"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blocked.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            blocked = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/alpha_onboarding_preflight.py"),
                    "--watchlist",
                    str(path),
                ],
                cwd=ROOT,
                env={**os.environ, "SNIPER_OFFLINE": "1"},
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(blocked.returncode, 78, blocked.stderr)
        self.assertEqual(set(json.loads(blocked.stdout)), preflight.RESULT_KEYS)
        self.assertNotIn("leak-marker", blocked.stdout.lower())

        invalid_capacity = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/alpha_onboarding_preflight.py"),
                "--watchlist",
                str(ROOT / "config/current_alpha_watchlist.json"),
                "--holder-capacity",
                "invalid-capacity",
            ],
            cwd=ROOT,
            env={**os.environ, "SNIPER_OFFLINE": "1"},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(invalid_capacity.returncode, 78, invalid_capacity.stderr)
        self.assertEqual(
            json.loads(invalid_capacity.stdout)["issue_codes"],
            ["holder_capacity_invalid"],
        )

    def test_server_runs_preflight_before_any_watcher(self) -> None:
        text = (ROOT / "scripts/server_run_once.sh").read_text(encoding="utf-8")
        marker = "python3 scripts/alpha_onboarding_preflight.py"
        self.assertIn(marker, text)
        self.assertLess(text.index(marker), text.index('python3 scripts/sniper_monitor.py'))
        self.assertLess(
            text.index(marker),
            text.index('if [[ "$REQUESTED_ALPHA_PROJECT_ONLY" == "1" ]]', text.index(marker)),
        )

        fast_text = (ROOT / "scripts/server_fast_lane.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(marker, fast_text)
        fast_marker = fast_text.index(marker)
        selection_marker = "select_and_materialize_watchlist"
        self.assertIn(selection_marker, fast_text)
        self.assertGreater(
            fast_marker,
            fast_text.index(selection_marker),
        )
        self.assertNotIn("watchlist_policy_status", fast_text)
        self.assertNotIn("runtime_policy_status", fast_text)
        self.assertNotIn("configured_policy_status", fast_text)
        for watcher in (
            "python3 scripts/prediction_market_watch.py",
            "python3 scripts/alpha_prelaunch_watch.py",
            "python3 scripts/perp_oi_funding_watch.py",
            "python3 scripts/alpha_liquidity_retention_watch.py",
            "python3 scripts/alpha_price_momentum_watch.py",
        ):
            with self.subTest(watcher=watcher):
                self.assertLess(fast_marker, fast_text.index(watcher))


if __name__ == "__main__":
    unittest.main()
