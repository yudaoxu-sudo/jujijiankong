#!/usr/bin/env python3
from __future__ import annotations

import copy
import fcntl
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
import scripts.finalize_alpha_liquidity_recovery as finalizer
import scripts.migrate_alpha_liquidity_seed as recovery
import scripts.prepare_alpha_liquidity_recovery_enrichment as enrichment
import scripts.test_alpha_liquidity_seed_recovery as recovery_tests


class CandidateARecoveryPreparationTests(unittest.TestCase):
    OBSERVED_AT = datetime(2100, 1, 1, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.fixture = recovery_tests.AlphaLiquiditySeedRecoveryTests()
        self.fixture.setUp()
        self.fixture._install_real_distribution()
        self.paths = self.fixture.paths
        self.lock_paths = finalizer.RecoveryLockPaths(
            *(self.fixture.root / "locks" / name for name in (
                "main.lock",
                "fast.lock",
                "project.lock",
                "liquidity.lock",
            ))
        )
        for path in (
            self.lock_paths.main,
            self.lock_paths.fast,
            self.lock_paths.project,
            self.lock_paths.liquidity,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.bundle = self._bundle()
        self.sidecar_path = (
            self.fixture.root
            / "work/alpha_liquidity_recovery_enrichment/sidecar.json"
        )
        self.sidecar = self._ready_sidecar(self.bundle)
        self.sidecar_sha256 = enrichment.atomic_cas_write(
            self.sidecar_path,
            self.sidecar,
            None,
        )
        self.sidecar_lock = self.sidecar_path.with_suffix(
            self.sidecar_path.suffix + ".lock"
        )
        self.sidecar_lock.touch()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _bundle(self) -> recovery.RecoveryBundle:
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.fixture.current_scope),
        ):
            return recovery.build_recovery_bundle(
                self.paths,
                checkpoint_hash_reader=self.fixture._canonical_hash,
            )

    @staticmethod
    def _ready_sidecar(
        bundle: recovery.RecoveryBundle,
    ) -> dict[str, object]:
        sidecar = enrichment.initialize_sidecar(bundle)
        events = bundle.standalone_seed["reconciliation"]["deferred_events"]
        sender = recovery_tests.address("c")
        for event in events:
            block_core = {
                "number": event["block"],
                "hash": holder.norm(event["block_hash"]),
                "timestamp": 1_700_000_000 + event["block"],
            }
            sidecar["rpc_cache"]["blocks"][
                enrichment._block_key(event)
            ] = enrichment._record("block", block_core)
            if enrichment._production_operator_skip(event):
                continue
            transaction_core = {
                "hash": holder.norm(event["tx"]),
                "from": sender,
                "block": event["block"],
                "block_hash": holder.norm(event["block_hash"]),
            }
            sidecar["rpc_cache"]["transactions"][
                enrichment._tx_key(event)
            ] = enrichment._record("transaction", transaction_core)
            for address in (holder.norm(event.get("lp_owner")), sender):
                code_core = {
                    "chain": "bsc",
                    "address": address,
                    "block": event["block"],
                    "block_hash": holder.norm(event["block_hash"]),
                    "code": "0x",
                }
                sidecar["rpc_cache"]["codes"][
                    enrichment._code_key(address, event)
                ] = enrichment._record("code", code_core)
        return sidecar

    @contextmanager
    def _runtime_patches(self):
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.fixture.current_scope),
            ),
            mock.patch.object(holder, "global_address_labels", return_value={}),
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

    def _prepare(self) -> dict[str, object]:
        with self._runtime_patches():
            return finalizer.prepare_candidate_a(
                self.paths,
                self.sidecar_path,
                self.sidecar_sha256,
                self.lock_paths,
                observed_at=self.OBSERVED_AT,
                checkpoint_hash_reader=self.fixture._canonical_hash,
            )

    def _verify(
        self,
        plan_hash: str,
        *,
        checkpoint_hash_reader=None,
    ) -> dict[str, object]:
        with self._runtime_patches():
            return finalizer.verify_prepared_candidate_a(
                self.paths,
                self.sidecar_path,
                self.sidecar_sha256,
                self.lock_paths,
                plan_hash=plan_hash,
                checkpoint_hash_reader=(
                    checkpoint_hash_reader or self.fixture._canonical_hash
                ),
            )

    def _candidate(self) -> finalizer.CandidateA:
        with mock.patch.object(holder, "global_address_labels", return_value={}):
            return finalizer.build_candidate_a(
                self.bundle,
                self.sidecar,
                expected_sidecar_sha256=self.sidecar_sha256,
                observed_at=self.OBSERVED_AT,
            )

    def _archive_root(self) -> Path:
        return (
            self.fixture.root
            / "output/alpha_liquidity_seed_recovery/archive"
        )

    @staticmethod
    def _rewrite_prepared_plan(directory: Path, plan: dict) -> str:
        core = {key: value for key, value in plan.items() if key != "plan_hash"}
        plan["plan_hash"] = recovery.digest(core)
        forged_directory = directory.parent / plan["plan_hash"]
        directory.rename(forged_directory)
        plan_bytes = recovery.json_bytes(plan, pretty=True)
        payloads = {
            forged_directory / "plan.json": plan_bytes,
            forged_directory / "prepared.json": recovery.json_bytes(
                finalizer._prepared(plan, plan_bytes), pretty=True
            ),
        }
        for path, payload in payloads.items():
            path.chmod(0o644)
            path.write_bytes(payload)
            path.chmod(0o444)
        return plan["plan_hash"]

    def test_candidate_a_is_exact_54_6_0_typed_and_silent(self) -> None:
        candidate = self._candidate()
        self.assertEqual(
            finalizer._counts(candidate.seed),
            {"pending": 54, "completed": 6, "deferred_events": 0},
        )
        self.assertEqual(
            candidate.accounting["transition_counts"],
            finalizer.EXPECTED_TRANSITIONS,
        )
        self.assertTrue(finalizer._clean_accounting(candidate.accounting))
        recovery_ids = {
            holder.liquidity_reconciliation_id(row)
            for row in self.bundle.standalone_seed["reconciliation"][
                "deferred_events"
            ]
        }
        recovery_pending = [
            row
            for row in candidate.seed["reconciliation"]["pending"]
            if row["reconcile_id"] in recovery_ids
        ]
        self.assertEqual(len(recovery_pending), 54)
        self.assertTrue(
            all(
                row.get("notification_policy")
                == holder.LIQUIDITY_RECOVERY_NOTIFICATION_POLICY
                for row in recovery_pending
            )
        )

    def test_candidate_hard_gates_shape_transition_and_alert(self) -> None:
        with mock.patch.object(finalizer, "EXPECTED_COUNTS", {
            "pending": 55, "completed": 6, "deferred_events": 0,
        }):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                self._candidate()
        self.assertEqual(caught.exception.code, "candidate_a_shape_changed")

        original = holder.reconcile_liquidity_events

        def alerting(*args, **kwargs):
            events, state, metadata = original(*args, **kwargs)
            events[0]["historical_catchup"] = False
            events[0]["alert_eligible"] = True
            return events, state, metadata

        with (
            mock.patch.object(
                holder,
                "global_address_labels",
                return_value={},
            ),
            mock.patch.object(
                holder,
                "reconcile_liquidity_events",
                side_effect=alerting,
            ),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                finalizer.build_candidate_a(
                    self.bundle,
                    self.sidecar,
                    expected_sidecar_sha256=self.sidecar_sha256,
                    observed_at=self.OBSERVED_AT,
                )
        self.assertEqual(caught.exception.code, "candidate_a_alert_pending")

        changed = copy.deepcopy(self.sidecar)
        changed["rpc_cache"]["blocks"].pop(
            next(iter(changed["rpc_cache"]["blocks"]))
        )
        changed_sha = recovery.digest(recovery.json_bytes(changed, pretty=True))
        with mock.patch.object(holder, "global_address_labels", return_value={}):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                finalizer.build_candidate_a(
                    self.bundle,
                    changed,
                    expected_sidecar_sha256=changed_sha,
                    observed_at=self.OBSERVED_AT,
                )
        self.assertEqual(caught.exception.code, "sidecar_incomplete")

    def test_four_locks_are_acquired_in_order_and_busy_fails_closed(self) -> None:
        observed: list[Path] = []
        real_open = os.open

        def record_open(path, *args, **kwargs):
            observed.append(Path(path))
            return real_open(path, *args, **kwargs)

        with mock.patch.object(finalizer.os, "open", side_effect=record_open):
            with finalizer.recovery_locks(
                self.lock_paths, self.sidecar_path
            ):
                pass
        self.assertEqual(observed, [
            self.lock_paths.main,
            self.lock_paths.fast,
            self.lock_paths.project,
            self.lock_paths.liquidity,
            self.sidecar_lock,
        ])

        for busy_path in (self.lock_paths.main, self.sidecar_lock):
            with self.subTest(busy_path=busy_path.name):
                descriptor = os.open(busy_path, os.O_RDWR)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        with finalizer.recovery_locks(
                            self.lock_paths, self.sidecar_path
                        ):
                            self.fail("busy lock must not be entered")
                    self.assertEqual(caught.exception.code, "recovery_lock_busy")
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                    os.close(descriptor)

    def test_prepare_keeps_target_before_and_writes_only_immutable_artifacts(
        self,
    ) -> None:
        protected_paths = (
            self.paths.config,
            self.paths.holder_state,
            self.paths.opening,
            self.paths.replay,
            self.fixture.root / "output/x/last_push.json",
            self.sidecar_path,
        )
        before = {path: recovery.file_hash(path) for path in protected_paths}
        target_before = recovery.file_hash(self.paths.standalone_state)
        replacements: list[tuple[Path, Path]] = []
        real_replace = os.replace

        def record_replace(source, target):
            replacements.append((Path(source), Path(target)))
            return real_replace(source, target)

        with mock.patch.object(finalizer.os, "replace", side_effect=record_replace):
            receipt = self._prepare()
        self.assertEqual(receipt["status"], "candidate_a_prepared")
        self.assertEqual(
            before,
            {path: recovery.file_hash(path) for path in protected_paths},
        )
        self.assertEqual(replacements, [])
        self.assertEqual(
            recovery.file_hash(self.paths.standalone_state), target_before
        )
        plan_hash = receipt["plan_hash"]
        directory = self._archive_root() / plan_hash
        self.assertEqual(
            {path.name for path in directory.iterdir()},
            set(finalizer.ARTIFACTS)
            | {"plan.json", "prepared.json"},
        )
        self.assertTrue(
            all(
                path.stat().st_mode & 0o222 == 0
                for path in directory.iterdir()
            )
        )
        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["schema"], finalizer.PLAN_SCHEMA)
        self.assertEqual(receipt["schema"], finalizer.PREPARED_SCHEMA)
        self.assertEqual(plan["target_state_sha256"], target_before)
        self.assertNotEqual(plan["candidate_a_state_sha256"], target_before)
        self.assertTrue(plan["checkpoint_checks"])
        self.assertEqual(
            receipt["target_write_status"],
            "forbidden_until_candidate_b",
        )
        self.assertEqual(receipt["candidate_b_status"], "not_implemented")
        self.assertEqual(receipt["rollback_status"], "not_implemented")

    def test_verify_prepared_is_read_only_and_idempotent(self) -> None:
        receipt = self._prepare()
        plan_hash = receipt["plan_hash"]
        before = recovery.file_hash(self.paths.standalone_state)
        directory = self._archive_root() / plan_hash
        artifact_hashes = {
            path.name: recovery.file_hash(path) for path in directory.iterdir()
        }
        self.assertEqual(self._verify(plan_hash), receipt)
        self.assertEqual(self._verify(plan_hash), receipt)
        self.assertEqual(recovery.file_hash(self.paths.standalone_state), before)
        self.assertEqual(
            artifact_hashes,
            {path.name: recovery.file_hash(path) for path in directory.iterdir()},
        )

    def test_verify_rejects_self_consistent_semantic_escalation(self) -> None:
        receipt = self._prepare()
        directory = self._archive_root() / receipt["plan_hash"]
        plan_path = directory / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan.update({
            "phase": "candidate_a_applied",
            "target_write_status": "candidate_a_applied",
            "candidate_b_status": "complete",
            "candidate_a_counts": {
                "pending": 0, "completed": 0, "deferred_events": 0,
            },
            "transition_accounting": {},
        })
        plan_hash = self._rewrite_prepared_plan(directory, plan)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._verify(plan_hash)
        self.assertEqual(caught.exception.code, "prepared_plan_invalid")

    def test_verify_rebuild_rejects_self_consistent_bogus_candidate(self) -> None:
        receipt = self._prepare()
        directory = self._archive_root() / receipt["plan_hash"]
        candidate_path = directory / "candidate_a_state.json"
        bogus = recovery.json_bytes({"schema": "bogus", "tokens": {}}, pretty=True)
        candidate_path.chmod(0o644)
        candidate_path.write_bytes(bogus)
        candidate_path.chmod(0o444)
        plan = json.loads(
            (directory / "plan.json").read_text(encoding="utf-8")
        )
        plan["candidate_a_state_sha256"] = recovery.digest(bogus)
        plan_hash = self._rewrite_prepared_plan(directory, plan)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._verify(plan_hash)
        self.assertEqual(caught.exception.code, "prepared_plan_invalid")

    def test_resume_blocks_input_protected_and_sidecar_drift(self) -> None:
        cases = ("input", "protected", "sidecar")
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                plan_hash = self._prepare()["plan_hash"]
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
                else:
                    self.sidecar_path.write_bytes(
                        self.sidecar_path.read_bytes() + b"\n"
                    )
                    expected = "sidecar_hash_mismatch"
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    self._verify(plan_hash)
                self.assertEqual(caught.exception.code, expected)

    def test_verify_blocks_canonical_checkpoint_drift(self) -> None:
        plan_hash = self._prepare()["plan_hash"]
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._verify(
                plan_hash,
                checkpoint_hash_reader=lambda _chain, _block: (
                    recovery_tests.hash32("d")
                ),
            )
        self.assertEqual(caught.exception.code, "checkpoint_hash_mismatch")

    def test_verify_never_accepts_candidate_a_as_target(self) -> None:
        receipt = self._prepare()
        directory = self._archive_root() / receipt["plan_hash"]
        candidate = directory / "candidate_a_state.json"
        self.paths.standalone_state.write_bytes(candidate.read_bytes())
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._verify(receipt["plan_hash"])
        self.assertEqual(caught.exception.code, "target_state_changed")

    def test_target_parent_symlink_outside_root_blocks_without_write(self) -> None:
        parent = self.paths.standalone_state.parent
        saved = parent.with_name(parent.name + ".saved")
        with tempfile.TemporaryDirectory() as external_name:
            external = Path(external_name)
            external_state = external / "state.json"
            external_state.write_bytes(self.paths.standalone_state.read_bytes())
            before = recovery.file_hash(external_state)
            parent.rename(saved)
            parent.symlink_to(external, target_is_directory=True)
            try:
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    self._prepare()
                self.assertEqual(caught.exception.code, "target_path_invalid")
                self.assertEqual(recovery.file_hash(external_state), before)
                self.assertFalse(self._archive_root().exists())
            finally:
                parent.unlink()
                saved.rename(parent)

    def test_resume_rejects_tampered_immutable_artifact(self) -> None:
        plan_hash = self._prepare()["plan_hash"]
        candidate = self._archive_root() / plan_hash / "candidate_a_state.json"
        candidate.chmod(0o644)
        candidate.write_bytes(candidate.read_bytes() + b"\n")
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._verify(plan_hash)
        self.assertEqual(caught.exception.code, "prepared_artifact_invalid")

    def test_sidecar_hash_is_checked_before_candidate_or_artifact_write(self) -> None:
        wrong = "f" * 64
        before = recovery.file_hash(self.paths.standalone_state)
        with self._runtime_patches():
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                finalizer.prepare_candidate_a(
                    self.paths,
                    self.sidecar_path,
                    wrong,
                    self.lock_paths,
                    observed_at=self.OBSERVED_AT,
                    checkpoint_hash_reader=self.fixture._canonical_hash,
                )
        self.assertEqual(caught.exception.code, "sidecar_hash_mismatch")
        self.assertEqual(recovery.file_hash(self.paths.standalone_state), before)
        self.assertFalse(self._archive_root().exists())


if __name__ == "__main__":
    unittest.main()
