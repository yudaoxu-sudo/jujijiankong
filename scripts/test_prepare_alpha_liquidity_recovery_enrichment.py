#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder
import scripts.migrate_alpha_liquidity_seed as recovery
import scripts.test_alpha_liquidity_seed_recovery as recovery_tests

try:
    import scripts.prepare_alpha_liquidity_recovery_enrichment as enrichment
except ImportError:
    enrichment = None


class Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)
        self.last = 0.0

    def __call__(self) -> float:
        self.last = next(self.values, self.last)
        return self.last


class AlphaLiquidityRecoveryEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        if enrichment is None:
            self.fail("prepare_alpha_liquidity_recovery_enrichment is missing")
        self.fixture = recovery_tests.AlphaLiquiditySeedRecoveryTests()
        self.fixture.setUp()
        self.paths = self.fixture.paths
        self.sidecar_path = (
            self.fixture.root
            / "output/alpha_liquidity_recovery_enrichment/sidecar.json"
        )
        self.expected_sidecar_sha256 = ""

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def bundle(self, reader=None):
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.fixture.current_scope),
        ):
            return recovery.build_recovery_bundle(
                self.paths,
                checkpoint_hash_reader=reader or self.fixture._canonical_hash,
            )

    @staticmethod
    def successful_rpc(
        chain: str, method: str, params: list[object]
    ) -> object:
        del chain
        if method == "eth_getBlockByNumber":
            block = int(str(params[0]), 16)
            return {
                "number": hex(block),
                "hash": recovery_tests.hash32("b"),
                "timestamp": hex(1_700_000_000 + block),
            }
        if method == "eth_getCode":
            return "0x"
        if method == "eth_getTransactionByHash":
            block = 999 + int(str(params[0]), 16)
            return {
                "hash": params[0],
                "from": recovery_tests.address("c"),
                "blockNumber": hex(block),
                "blockHash": recovery_tests.hash32("b"),
            }
        raise AssertionError(method)

    def run_step(self, rpc=None, **kwargs):
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.fixture.current_scope),
            ),
            mock.patch.object(holder, "global_address_labels", return_value={}),
        ):
            kwargs.setdefault(
                "expected_sidecar_sha256", self.expected_sidecar_sha256)
            result = enrichment.run_step(
                self.paths,
                self.sidecar_path,
                rpc_call=rpc or self.successful_rpc,
                checkpoint_hash_reader=self.fixture._canonical_hash,
                **kwargs,
            )
        self.expected_sidecar_sha256 = result["sidecar_sha256"]
        return result

    def read_sidecar(self) -> dict[str, object]:
        return json.loads(self.sidecar_path.read_text(encoding="utf-8"))

    def is_ready(self, sidecar: dict[str, object], index: int) -> bool:
        event = self.bundle().standalone_seed["reconciliation"]["deferred_events"][index]
        return enrichment.entry_raw_ready(
            sidecar["entries"][index], event, sidecar["rpc_cache"])

    def install_single_event(self) -> None:
        state = copy.deepcopy(self.fixture.standalone_state)
        reconciliation = state["tokens"][recovery.DOS_KEY]["liquidity"][
            "reconciliation"
        ]
        reconciliation["deferred_events"] = reconciliation["deferred_events"][:1]
        self.fixture._write_json(self.paths.standalone_state, state)

    def test_step_caps_events_at_32_and_preserves_production_inputs(self) -> None:
        watched = [
            self.paths.config,
            self.paths.standalone_state,
            self.paths.holder_state,
            self.paths.opening,
            self.paths.replay,
            self.fixture.root / "output/x/last_push.json",
        ]
        before = {path: recovery.file_hash(path) for path in watched}
        result = self.run_step(limit=32, budget_seconds=20)
        sidecar = self.read_sidecar()
        self.assertEqual(result["attempted_count"], 32)
        self.assertEqual(result["raw_ready_count"], 32)
        self.assertEqual(sidecar["cursor"]["next_index"], 32)
        self.assertEqual(
            before, {path: recovery.file_hash(path) for path in watched}
        )
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self.run_step(limit=33)
        self.assertEqual(caught.exception.code, "sidecar_step_limit_invalid")

    def test_deadline_stops_before_starting_another_rpc(self) -> None:
        calls: list[str] = []

        def rpc(chain: str, method: str, params: list[object]) -> object:
            calls.append(method)
            return self.successful_rpc(chain, method, params)

        result = self.run_step(
            rpc=rpc,
            limit=32,
            budget_seconds=20,
            monotonic=Clock([0, 0, 0, 0, 21]),
        )
        self.assertTrue(result["deadline_reached"])
        self.assertLess(result["attempted_count"], 32)
        self.assertEqual(calls, ["eth_getBlockByNumber", "eth_getCode"])

    def test_cursor_continues_after_failure_and_resumes_missing_segment(
        self,
    ) -> None:
        failed_once = True
        calls: list[tuple[str, tuple[object, ...]]] = []

        def rpc(chain: str, method: str, params: list[object]) -> object:
            nonlocal failed_once
            calls.append((method, tuple(params)))
            if method == "eth_getCode" and failed_once:
                failed_once = False
                raise TimeoutError("redacted")
            return self.successful_rpc(chain, method, params)

        first = self.run_step(rpc=rpc, limit=2)
        sidecar = self.read_sidecar()
        self.assertEqual(first["attempted_count"], 2)
        self.assertFalse(self.is_ready(sidecar, 0))
        self.assertTrue(self.is_ready(sidecar, 1))
        self.assertIn(enrichment._block_key(
            self.bundle().standalone_seed["reconciliation"]["deferred_events"][0]
        ), sidecar["rpc_cache"]["blocks"])
        cached_block_calls = sum(
            method == "eth_getBlockByNumber" for method, _ in calls
        )
        sidecar["cursor"]["next_index"] = 0
        sidecar["cursor"]["next_reconcile_id"] = sidecar["entries"][0]["reconcile_id"]
        self.expected_sidecar_sha256 = enrichment.atomic_cas_write(
            self.sidecar_path,
            sidecar,
            recovery.file_hash(self.sidecar_path),
        )
        self.run_step(rpc=rpc, limit=1)
        self.assertTrue(self.is_ready(self.read_sidecar(), 0))
        self.assertEqual(
            cached_block_calls,
            sum(method == "eth_getBlockByNumber" for method, _ in calls),
        )

    def test_code_cache_identity_includes_block_and_block_hash(self) -> None:
        code_calls: list[tuple[object, ...]] = []

        def rpc(chain: str, method: str, params: list[object]) -> object:
            if method == "eth_getCode":
                code_calls.append(tuple(params))
            return self.successful_rpc(chain, method, params)

        self.run_step(rpc=rpc, limit=2)
        self.assertEqual(len(code_calls), 4)
        cache = self.read_sidecar()["rpc_cache"]["codes"]
        self.assertEqual(len(cache), 4)
        self.assertEqual(len(set(cache)), 4)

    def test_raw_cache_survives_fresh_label_route_change(self) -> None:
        self.install_single_event()
        self.run_step(limit=1)
        bundle, sidecar = self.bundle(), self.read_sidecar()
        before = recovery.file_hash(self.sidecar_path)
        with mock.patch.object(holder, "global_address_labels", return_value={}):
            owner = enrichment.materialize_ready_events(
                bundle, sidecar, expected_sidecar_sha256=before)[0]
        labels = {recovery_tests.address("a"): {"class": "pool_manager"}}
        with mock.patch.object(holder, "global_address_labels", return_value=labels):
            sender = enrichment.materialize_ready_events(
                bundle, sidecar, expected_sidecar_sha256=before)[0]
        self.assertEqual(owner["liquidity_operator_basis"], "pool_event_owner_eoa")
        self.assertEqual(sender["liquidity_operator_basis"], "transaction_sender_eoa")
        self.assertEqual(sender["liquidity_operator"], recovery_tests.address("c"))
        self.assertEqual(recovery.file_hash(self.sidecar_path), before)

    def test_raw_ready_does_not_claim_materializable_operator(self) -> None:
        self.install_single_event()

        def rpc(chain: str, method: str, params: list[object]) -> object:
            if method == "eth_getCode":
                return "0x6000"
            return self.successful_rpc(chain, method, params)

        result = self.run_step(rpc=rpc, limit=1)
        self.assertEqual(result["status"], "raw_evidence_ready")
        self.assertNotEqual(result["status"], "ready")
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.materialize_ready_events(
                self.bundle(), self.read_sidecar(),
                expected_sidecar_sha256=recovery.file_hash(self.sidecar_path))
        self.assertEqual(caught.exception.code, "sidecar_materialize_incomplete")

    def test_cache_receipt_rejects_valid_shape_timestamp_tamper(self) -> None:
        self.install_single_event()
        self.run_step(limit=1)
        expected_sidecar_sha256 = recovery.file_hash(self.sidecar_path)
        bundle, sidecar = self.bundle(), self.read_sidecar()
        block = next(iter(sidecar["rpc_cache"]["blocks"].values()))
        block["timestamp"] += 123456
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.validate_sidecar(bundle, sidecar, require_raw_ready=True)
        self.assertEqual(caught.exception.code, "sidecar_cache_invalid")

        coordinated = self.read_sidecar()
        block = next(iter(coordinated["rpc_cache"]["blocks"].values()))
        core = {key: block[key] for key in ("number", "hash", "timestamp")}
        core["timestamp"] += 123456
        block.clear()
        block.update(enrichment._record("block", core))
        self.assertEqual(
            enrichment.validate_sidecar(bundle, coordinated, require_raw_ready=True),
            {"raw_ready_count": 1, "event_count": 1},
        )
        enrichment.atomic_cas_write(
            self.sidecar_path, coordinated, expected_sidecar_sha256)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self.run_step(limit=1)
        self.assertEqual(caught.exception.code, "sidecar_hash_mismatch")
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.materialize_ready_events(
                bundle, coordinated,
                expected_sidecar_sha256=expected_sidecar_sha256)
        self.assertEqual(caught.exception.code, "sidecar_hash_mismatch")

    def test_transaction_sender_requires_matching_block_hash(self) -> None:
        def rpc(chain: str, method: str, params: list[object]) -> object:
            if method == "eth_getCode":
                return "0x6000" if params[0] == recovery_tests.address("a") else "0x"
            if method == "eth_getTransactionByHash":
                return {
                    "hash": params[0],
                    "from": recovery_tests.address("c"),
                    "blockNumber": hex(1000),
                    "blockHash": recovery_tests.hash32("9"),
                }
            return self.successful_rpc(chain, method, params)

        result = self.run_step(rpc=rpc, limit=1)
        sidecar = self.read_sidecar()
        entry = sidecar["entries"][0]
        self.assertEqual(result["raw_ready_count"], 0)
        self.assertEqual(entry["last_error_code"], "transaction_not_canonical")
        self.assertEqual(sidecar["rpc_cache"]["transactions"], {})
        sidecar["cursor"]["next_index"] = 0
        sidecar["cursor"]["next_reconcile_id"] = sidecar["entries"][0]["reconcile_id"]
        self.expected_sidecar_sha256 = enrichment.atomic_cas_write(
            self.sidecar_path, sidecar, recovery.file_hash(self.sidecar_path))
        self.run_step(limit=1)
        self.assertTrue(self.is_ready(self.read_sidecar(), 0))

    def test_stable_archive_and_job_id_ignore_holder_drift(self) -> None:
        first = self.bundle()
        first_sidecar = enrichment.initialize_sidecar(first)
        holder_state = json.loads(
            self.paths.holder_state.read_text(encoding="utf-8")
        )
        seed = holder_state["tokens"][recovery.DOS_KEY]["retention_flow"][
            "liquidity"
        ]
        seed["latest_block"] = 2201
        seed["latest_block_hash"] = recovery_tests.hash32("4")
        self.fixture._write_json(self.paths.holder_state, holder_state)

        def canonical(_chain: str, block: int) -> str:
            if block == 2201:
                return recovery_tests.hash32("4")
            return self.fixture._canonical_hash(_chain, block)

        second = self.bundle(reader=canonical)
        second_sidecar = enrichment.initialize_sidecar(second)
        self.assertNotEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(
            enrichment.stable_archive_projection(first),
            enrichment.stable_archive_projection(second),
        )
        self.assertEqual(first_sidecar["job_id"], second_sidecar["job_id"])
        self.assertEqual(
            first_sidecar["source"]["archive_sha256"],
            second_sidecar["source"]["archive_sha256"],
        )
        self.assertEqual(
            enrichment.validate_sidecar(second, first_sidecar),
            {"raw_ready_count": 0, "event_count": 499},
        )

    def test_real_499_distribution_reaches_ready_without_raw_events(self) -> None:
        self.fixture._install_real_distribution()
        for _ in range(16):
            result = self.run_step(limit=32)
        self.assertEqual(result["status"], "raw_evidence_ready")
        self.assertEqual(result["raw_ready_count"], 499)
        sidecar = self.read_sidecar()
        bundle = self.bundle()
        with mock.patch.object(
                holder, "global_address_labels", return_value={}) as labels:
            materialized = enrichment.materialize_ready_events(
                bundle, sidecar,
                expected_sidecar_sha256=recovery.file_hash(self.sidecar_path))
        labels.assert_called_once_with("bsc")
        self.assertEqual(len(materialized), 499)
        historical = [
            index for index, event in enumerate(
                bundle.standalone_seed["reconciliation"]["deferred_events"])
            if event.get("historical_catchup") is True
            and event.get("type") != "lp_add_observation"
        ]
        self.assertEqual(len(historical), 49)
        self.assertTrue(all("liquidity_operator" not in materialized[index]
                            for index in historical))
        self.assertTrue(all(row.get("chain_timestamp_basis") == "canonical_block"
                            for row in materialized))
        serialized = json.dumps(sidecar, sort_keys=True)
        self.assertNotIn('"original_events"', serialized)
        self.assertNotIn('"source_event"', serialized)
        self.assertNotIn("liquidity_operator", serialized)
        self.assertNotIn("liquidity_operator_class", serialized)

    def test_tampered_event_or_cache_blocks_validation_and_materialize(
        self,
    ) -> None:
        bundle = self.bundle()
        sidecar = enrichment.initialize_sidecar(bundle)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.materialize_ready_events(
                bundle, sidecar,
                expected_sidecar_sha256=recovery.digest(
                    recovery.json_bytes(sidecar, pretty=True)))
        self.assertEqual(caught.exception.code, "sidecar_incomplete")
        sidecar["cursor"]["next_reconcile_id"] = "f" * 64
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.validate_sidecar(bundle, sidecar)
        self.assertEqual(caught.exception.code, "sidecar_cursor_invalid")
        sidecar["cursor"]["next_reconcile_id"] = sidecar["entries"][0]["reconcile_id"]
        sidecar["entries"][0]["event_sha256"] = "f" * 64
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            enrichment.validate_sidecar(bundle, sidecar)
        self.assertEqual(caught.exception.code, "sidecar_event_manifest_invalid")

    def test_atomic_cas_failure_preserves_old_complete_json(self) -> None:
        self.sidecar_path.parent.mkdir(parents=True)
        old = {"schema": "old", "value": 1}
        self.sidecar_path.write_text(json.dumps(old), encoding="utf-8")
        old_bytes = self.sidecar_path.read_bytes()
        with mock.patch.object(os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                enrichment.atomic_cas_write(
                    self.sidecar_path,
                    {"schema": "new", "value": 2},
                    recovery.digest(old_bytes),
                )
        self.assertEqual(self.sidecar_path.read_bytes(), old_bytes)
        self.assertEqual(json.loads(self.sidecar_path.read_text()), old)


if __name__ == "__main__":
    unittest.main()
