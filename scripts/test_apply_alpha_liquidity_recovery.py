#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
import scripts.apply_alpha_liquidity_recovery as applier
import scripts.finalize_alpha_liquidity_recovery as candidate_a
import scripts.migrate_alpha_liquidity_seed as recovery
import scripts.test_alpha_liquidity_seed_recovery as recovery_tests
import scripts.test_finalize_alpha_liquidity_recovery as candidate_a_tests


class InjectedCrash(RuntimeError):
    pass


class CandidateBRecoveryApplyTests(unittest.TestCase):
    NOW = "2100-01-01T00:01:00+00:00"

    def setUp(self) -> None:
        self.base = candidate_a_tests.CandidateARecoveryPreparationTests()
        self.base.setUp()
        self.paths = self.base.paths
        self.lock_paths = self.base.lock_paths
        self.sidecar_path = self.base.sidecar_path
        self.sidecar_hash = self.base.sidecar_sha256
        self.a_receipt = self.base._prepare()
        self.a_plan_hash = self.a_receipt["plan_hash"]
        self.a_directory = self.base._archive_root() / self.a_plan_hash
        self.a_bytes = (self.a_directory / "candidate_a_state.json").read_bytes()
        self.a_state = json.loads(self.a_bytes)
        self.before_bytes = self.paths.standalone_state.read_bytes()
        self.before_hash = recovery.digest(self.before_bytes)
        self.b_hash = recovery_tests.hash32("3")
        self.bounded_calls: list[tuple[int, int, int]] = []

    def tearDown(self) -> None:
        self.base.tearDown()

    def _canonical(self, chain: str, block: int) -> str:
        if block == 2300:
            return self.b_hash
        return self.base.fixture._canonical_hash(chain, block)

    def _bounded(self, _chain, pools, from_block, requested_to, **_kwargs):
        self.bounded_calls.append((len(pools), from_block, requested_to))
        return [], [], False, requested_to, {
            "query_scope_complete": True,
            "query_count": len(pools),
            "scope_batch_count": len(pools),
            "query_chunk_count": 1,
            "expected_query_count": len(pools),
            "v4_manager_count": 0,
            "event_filter_count": 6,
            "applicable": True,
            "active": False,
            "requested_to_block": requested_to,
            "selected_to_block": requested_to,
            "attempt_count": 1,
            "next_window_blocks": 64,
            "deadline_exceeded": False,
            "complete_selected_window": True,
            "complete_requested_window": True,
        }

    @contextmanager
    def _runtime(self):
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.base.fixture.current_scope),
            ),
            mock.patch.object(holder, "global_address_labels", return_value={}),
            mock.patch.object(
                holder,
                "retention_window",
                return_value={"status": "active", "age_hours": 1},
            ),
            mock.patch.object(
                fast, "strict_token_metadata", return_value=(18, 10**24)
            ),
            mock.patch.object(holder, "latest_block", return_value=2302),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=self._canonical,
            ),
            mock.patch.object(
                holder,
                "bounded_retention_liquidity_logs",
                side_effect=self._bounded,
            ),
            mock.patch.object(holder, "now_iso", return_value=self.NOW),
            mock.patch.object(
                holder,
                "maybe_send_telegram",
                side_effect=AssertionError("Telegram must stay untouched"),
            ),
            mock.patch.object(
                fast,
                "run_once",
                side_effect=AssertionError("fast runtime must not execute"),
            ),
        ):
            yield

    def _apply(self) -> dict[str, object]:
        with self._runtime():
            return applier.apply_candidate_b(
                self.paths,
                self.sidecar_path,
                self.sidecar_hash,
                self.lock_paths,
                candidate_a_plan_hash=self.a_plan_hash,
                checkpoint_hash_reader=self._canonical,
            )

    def _crash(self, phase: str) -> None:
        def hook(actual: str) -> None:
            if actual == phase:
                raise InjectedCrash(phase)

        with mock.patch.object(applier, "_phase_hook", side_effect=hook):
            with self.assertRaises(InjectedCrash):
                self._apply()

    def _prepared_directory(self) -> Path:
        directory = applier._directory(self.paths, self.a_plan_hash, False)
        self.assertTrue(directory.is_dir())
        return directory

    def _baseline_snapshot(self) -> dict[str, object]:
        with self._runtime(), recovery.probe_paths(self.paths, self.a_state):
            return fast.build_snapshot()

    def test_real_fast_builds_healthy_b_and_single_cas_never_writes_a(
        self,
    ) -> None:
        protected = {
            path: recovery.file_hash(path)
            for path in (
                self.paths.config,
                self.paths.holder_state,
                self.paths.opening,
                self.paths.replay,
                self.sidecar_path,
            )
        }
        replacements: list[tuple[Path, Path]] = []
        real_replace = os.replace

        def record_replace(source, target, *args, **kwargs):
            replacements.append((Path(source), Path(target)))
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(applier.os, "replace", side_effect=record_replace):
            receipt = self._apply()

        self.assertEqual(receipt["status"], "candidate_b_applied")
        self.assertEqual(receipt["target_write_status"], "candidate_b_only")
        self.assertEqual(receipt["rollback_status"], "not_implemented")
        self.assertEqual(len(replacements), 1)
        self.assertEqual(replacements[0][1].name, self.paths.standalone_state.name)
        target = self.paths.standalone_state.read_bytes()
        self.assertEqual(recovery.digest(target), receipt["candidate_b_state_sha256"])
        self.assertNotEqual(target, self.a_bytes)
        self.assertNotEqual(target, self.before_bytes)
        state = json.loads(target)
        seed = state["tokens"][recovery.DOS_KEY]["liquidity"]
        self.assertEqual(seed["latest_block"], 2300)
        self.assertEqual(seed["latest_block_hash"], self.b_hash)
        self.assertEqual(self.bounded_calls, [(8, 2201, 2300)])
        self.assertEqual(
            protected,
            {path: recovery.file_hash(path) for path in protected},
        )

    def test_crash_after_prepared_resumes_with_one_b_replace(self) -> None:
        self._crash("after_prepared")
        self.assertEqual(self.paths.standalone_state.read_bytes(), self.before_bytes)
        directory = self._prepared_directory()
        self.assertFalse((directory / "applied.json").exists())
        replacements = 0
        real_replace = os.replace

        def count_replace(source, target, *args, **kwargs):
            nonlocal replacements
            replacements += 1
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(applier.os, "replace", side_effect=count_replace):
            receipt = self._apply()
        self.assertEqual(replacements, 1)
        self.assertEqual(receipt["status"], "candidate_b_applied")
        self.assertNotEqual(self.paths.standalone_state.read_bytes(), self.a_bytes)

    def test_crash_after_replace_resumes_without_second_replace(self) -> None:
        self._crash("after_replace")
        directory = self._prepared_directory()
        self.assertFalse((directory / "applied.json").exists())
        target_after = self.paths.standalone_state.read_bytes()
        self.assertNotEqual(target_after, self.before_bytes)
        self.assertNotEqual(target_after, self.a_bytes)
        with mock.patch.object(
            applier.os,
            "replace",
            side_effect=AssertionError("resume must not replace twice"),
        ):
            receipt = self._apply()
        self.assertEqual(receipt["status"], "candidate_b_applied")
        self.assertEqual(self.paths.standalone_state.read_bytes(), target_after)

    def test_resume_blocks_state_neither_before_nor_candidate_b(self) -> None:
        self._crash("after_prepared")
        self.paths.standalone_state.write_bytes(self.a_bytes)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._apply()
        self.assertEqual(caught.exception.code, "target_state_neither")
        self.assertEqual(self.paths.standalone_state.read_bytes(), self.a_bytes)

    def test_resume_blocks_input_protected_sidecar_and_canonical_drift(self) -> None:
        cases = ("input", "protected", "sidecar", "canonical")
        for case in cases:
            with self.subTest(case=case):
                if case != cases[0]:
                    self.tearDown()
                    self.setUp()
                self._crash("after_prepared")
                if case == "input":
                    self.paths.holder_state.write_bytes(
                        self.paths.holder_state.read_bytes() + b"\n"
                    )
                    expected = "input_hash_changed"
                elif case == "protected":
                    self.paths.replay.write_bytes(
                        self.paths.replay.read_bytes() + b"\n"
                    )
                    expected = "protected_state_changed"
                elif case == "sidecar":
                    self.sidecar_path.write_bytes(
                        self.sidecar_path.read_bytes() + b"\n"
                    )
                    expected = "sidecar_hash_mismatch"
                else:
                    self._canonical = lambda _chain, _block: (
                        recovery_tests.hash32("d")
                    )
                    expected = "checkpoint_hash_mismatch"
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    self._apply()
                self.assertEqual(caught.exception.code, expected)

    def test_double_cas_rejects_target_drift_before_prepare_and_replace(
        self,
    ) -> None:
        for phase, expected_artifacts in (
            ("before_prepared_cas", False),
            ("before_replace_cas", True),
        ):
            with self.subTest(phase=phase):
                if phase != "before_prepared_cas":
                    self.tearDown()
                    self.setUp()

                def drift(actual: str) -> None:
                    if actual == phase:
                        self.paths.standalone_state.write_bytes(self.a_bytes)

                with mock.patch.object(applier, "_phase_hook", side_effect=drift):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        self._apply()
                self.assertEqual(caught.exception.code, "target_state_changed")
                self.assertEqual(
                    applier._directory(
                        self.paths, self.a_plan_hash, False
                    ).exists(),
                    expected_artifacts,
                )
                self.assertEqual(self.paths.standalone_state.read_bytes(), self.a_bytes)

    def test_target_parent_swap_cannot_write_outside_root(self) -> None:
        parent = self.paths.standalone_state.parent
        saved = parent.with_name(parent.name + ".saved")
        with tempfile.TemporaryDirectory() as external_name:
            external = Path(external_name)
            outside = external / self.paths.standalone_state.name
            outside.write_bytes(self.before_bytes)

            def swap(phase: str) -> None:
                if phase == "cas_after_validation":
                    parent.rename(saved)
                    parent.symlink_to(external, target_is_directory=True)

            try:
                with mock.patch.object(applier, "_phase_hook", side_effect=swap):
                    with self.assertRaises(recovery.RecoveryBlocked):
                        self._apply()
                self.assertEqual(outside.read_bytes(), self.before_bytes)
            finally:
                if parent.is_symlink():
                    parent.unlink()
                if saved.exists():
                    saved.rename(parent)

    def test_candidate_b_hard_gates_health_alert_progress_and_state_scope(
        self,
    ) -> None:
        baseline = self._baseline_snapshot()
        cases = (
            ("health", "clone_probe_incomplete"),
            ("alert", "clone_probe_alert_pending"),
            ("ahead", "candidate_b_not_ahead"),
            ("state_scope", "candidate_b_state_scope_changed"),
            ("dominance", "candidate_b_reconciliation_not_dominant"),
            ("policy_row", "candidate_b_notification_policy_regressed"),
            ("policy_source", "candidate_b_notification_policy_regressed"),
        )
        for case, expected in cases:
            with self.subTest(case=case):
                snapshot = copy.deepcopy(baseline)
                seed = snapshot["_next_state"]["tokens"][recovery.DOS_KEY][
                    "liquidity"
                ]
                if case == "health":
                    snapshot["status"] = "unhealthy"
                elif case == "ahead":
                    seed["latest_block"] = 2200
                    seed["latest_block_hash"] = recovery_tests.hash32("2")
                elif case == "state_scope":
                    snapshot["_next_state"]["unexpected"] = True
                elif case == "dominance":
                    seed["reconciliation"]["pending"].pop()
                elif case in {"policy_row", "policy_source"}:
                    row = next(
                        item for item in seed["reconciliation"]["pending"]
                        if item.get("notification_policy")
                        == holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY
                    )
                    target = row if case == "policy_row" else row["source_event"]
                    target.pop("notification_policy", None)
                with (
                    mock.patch.object(fast, "build_snapshot", return_value=snapshot),
                    mock.patch.object(
                        holder,
                        "alert_keys",
                        return_value=["unexpected"] if case == "alert" else [],
                    ),
                ):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        self._apply()
                self.assertEqual(caught.exception.code, expected)

    def test_rejects_raw_seed_extra_field_and_nonzero_alert_count(self) -> None:
        baseline = self._baseline_snapshot()
        for case, expected in (
            ("raw_field", "candidate_b_state_invalid"),
            ("alert_count", "clone_probe_alert_pending"),
        ):
            with self.subTest(case=case):
                if case == "alert_count":
                    self.tearDown()
                    self.setUp()
                snapshot = copy.deepcopy(baseline)
                if case == "raw_field":
                    snapshot["_next_state"]["tokens"][recovery.DOS_KEY][
                        "liquidity"
                    ]["unexpected_unvalidated_field"] = True
                else:
                    snapshot["alert_count"] = 1
                with mock.patch.object(
                    fast, "build_snapshot", return_value=snapshot
                ):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        self._apply()
                self.assertEqual(caught.exception.code, expected)

    def test_preexisting_applied_receipt_requires_target_candidate_b(self) -> None:
        for case in ("exact", "bogus"):
            with self.subTest(case=case):
                if case == "bogus":
                    self.tearDown()
                    self.setUp()
                self._crash("after_prepared")
                directory = self._prepared_directory()
                plan, prepared_bytes, _payloads, _applied = applier._load(
                    self.paths, self.a_plan_hash
                )
                applied = (
                    applier._receipt(plan, True, prepared_bytes)
                    if case == "exact" else {"schema": "bogus"}
                )
                candidate_a._write_once(
                    directory / "applied.json",
                    recovery.json_bytes(applied, pretty=True),
                )
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    self._apply()
                self.assertEqual(caught.exception.code, "applied_receipt_invalid")
                self.assertEqual(
                    self.paths.standalone_state.read_bytes(), self.before_bytes
                )

    def test_new_live_rows_require_window_canonical_hash_and_snapshot_row(
        self,
    ) -> None:
        baseline = self._baseline_snapshot()
        for case, expected in (
            ("window", "candidate_b_live_row_out_of_window"),
            ("canonical", "checkpoint_hash_mismatch"),
            ("snapshot", "candidate_b_live_row_not_in_snapshot"),
            ("binding", "candidate_b_live_row_mismatch"),
            ("provenance", "candidate_b_live_row_mismatch"),
        ):
            with self.subTest(case=case):
                snapshot = copy.deepcopy(baseline)
                seed = snapshot["_next_state"]["tokens"][recovery.DOS_KEY][
                    "liquidity"
                ]
                event = self.base.fixture._real_deferred(999)
                event.update({
                    "block": 2301 if case == "window" else 2250,
                    "block_hash": recovery_tests.hash32(
                        "d" if case == "canonical" else "a"
                    ),
                    "tx": "0x" + "9" * 64,
                    "log_index": 999,
                })
                row = copy.deepcopy(seed["reconciliation"]["pending"][0])
                row.update({
                    "reconcile_id": holder.liquidity_reconciliation_id(event),
                    "source_block": event["block"],
                    "source_block_hash": event["block_hash"],
                    "source_log_index": event["log_index"],
                    "source_pool": event["pool"],
                    "source_event": event,
                })
                if case == "binding":
                    row["source_event"] = copy.deepcopy(
                        seed["reconciliation"]["pending"][0]["source_event"]
                    )
                elif case == "provenance":
                    row["source_event"] = copy.deepcopy(event)
                    row["source_event"]["protocol"] = (
                        "deliberately-different-protocol"
                    )
                seed["reconciliation"]["pending"].append(row)
                if case != "snapshot":
                    snapshot["projects"][0]["retention_flow"][
                        "liquidity_retention"
                    ]["events"].append(copy.deepcopy(event))
                reader = self._canonical
                if case == "canonical":
                    reader = lambda chain, block, original=reader: (
                        recovery_tests.hash32("e")
                        if block == 2250 else original(chain, block)
                    )
                else:
                    reader = lambda chain, block, original=reader: (
                        recovery_tests.hash32("a")
                        if block == 2250 else original(chain, block)
                    )
                with (
                    mock.patch.object(fast, "build_snapshot", return_value=snapshot),
                    self._runtime(),
                ):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        applier.apply_candidate_b(
                            self.paths,
                            self.sidecar_path,
                            self.sidecar_hash,
                            self.lock_paths,
                            candidate_a_plan_hash=self.a_plan_hash,
                            checkpoint_hash_reader=reader,
                        )
                self.assertEqual(caught.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
