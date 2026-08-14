#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast
import scripts.migrate_alpha_liquidity_seed as recovery


TOKEN = recovery.DOS_TOKEN
KEY = recovery.DOS_KEY


def hash32(character: str) -> str:
    return "0x" + character * 64


def address(character: str) -> str:
    return "0x" + character * 40


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AlphaLiquiditySeedRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = recovery.RecoveryPaths.for_root(self.root)
        self.paths.config.parent.mkdir(parents=True)
        self.paths.standalone_state.parent.mkdir(parents=True)
        self.paths.holder_state.parent.mkdir(parents=True)
        self.paths.opening.parent.mkdir(parents=True)
        self.paths.replay.parent.mkdir(parents=True)
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _pool(self, index: int) -> dict[str, object]:
        return {
            "protocol": "v3",
            "address": address(hex(index + 1)[2:]),
            "factory": address("f"),
            "token0": TOKEN,
            "token1": address("e"),
            "quote_token": address("e"),
            "quote_decimals": 18,
            "quote_symbol": "USDT",
            "fee": 100 + index,
        }

    def _deferred(self, index: int) -> dict[str, object]:
        return {
            "type": "lp_remove_observation",
            "protocol": "v3",
            "pool": self.narrow_pools[index % len(self.narrow_pools)][
                "address"
            ],
            "tx": "0x" + f"{index + 1:064x}",
            "block": 1000 + index,
            "block_hash": hash32("b"),
            "log_index": index,
            "lp_owner": address("a"),
            "tick_lower": -100,
            "tick_upper": 100,
            "lp_removed_amount_raw": 100,
            "quote_removed_amount_raw": 100,
            "quote_token": address("e"),
            "quote_decimals": 18,
            "quote_symbol": "USDT",
        }

    def _seed(
        self,
        pools: list[dict[str, object]],
        *,
        latest: int,
        latest_hash: str,
        coverage_from: int,
        live_from: int,
        next_window: int,
        reconciliation: dict[str, object],
    ) -> dict[str, object]:
        return {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": holder.liquidity_pool_scope_hash(pools),
            "pool_scope": copy.deepcopy(pools),
            "pool_count": len(pools),
            "scope_coverage_from_block": coverage_from,
            "latest_block": latest,
            "latest_block_hash": latest_hash,
            "catchup_active": True,
            "catchup_live_from_block": live_from,
            "next_catchup_window_blocks": next_window,
            "reconciliation": reconciliation,
        }

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def _write_fixture(self) -> None:
        self.narrow_pools = [self._pool(index) for index in range(5)]
        self.expanded_pools = [self._pool(index) for index in range(8)]
        deferred = [self._deferred(index) for index in range(499)]
        overlap_id = holder.liquidity_reconciliation_id(deferred[0])
        completed = [
            {
                "reconcile_id": overlap_id if index == 0 else f"{index:064x}",
                "completed_at": f"2026-08-14T00:0{index}:00+00:00",
                "classification": (
                    "unresolved_coverage" if index == 0 else "restored"
                ),
                "source_block": 1000 + index,
                "source_log_index": 0,
                "source_tx": deferred[index]["tx"],
                "source_pool": address("d"),
            }
            for index in range(5)
        ]
        standalone_reconciliation = {
            "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
            "pending": [],
            "completed": [],
            "deferred_events": deferred,
            "updated_at": "2026-08-14T00:00:00+00:00",
        }
        holder_reconciliation = {
            "schema": holder.LIQUIDITY_RECONCILIATION_SCHEMA,
            "pending": [],
            "completed": completed,
            "deferred_events": [],
            "updated_at": "2026-08-14T01:00:00+00:00",
        }
        self.standalone_seed = self._seed(
            self.narrow_pools,
            latest=1200,
            latest_hash=hash32("1"),
            coverage_from=900,
            live_from=1100,
            next_window=16,
            reconciliation=standalone_reconciliation,
        )
        self.holder_seed = self._seed(
            self.expanded_pools,
            latest=2200,
            latest_hash=hash32("2"),
            coverage_from=1900,
            live_from=2100,
            next_window=32,
            reconciliation=holder_reconciliation,
        )
        self.standalone_state = {
            "schema": fast.STATE_SCHEMA,
            "tokens": {KEY: {"decimals": 18, "liquidity": self.standalone_seed}},
        }
        self.holder_state = {
            "tokens": {
                KEY: {
                    "decimals": 18,
                    "retention_flow": {"liquidity": self.holder_seed},
                }
            }
        }
        self.config = {
            "monitoring_policy": {
                "mode": "exclusive_symbols",
                "symbols": ["DOS"],
            },
            "items": [
                {
                    "symbol": "DOS",
                    "priority": "P0_PRELAUNCH",
                    "active_monitoring": True,
                    "contracts": [{"chain": "bsc", "address": TOKEN}],
                },
                {
                    "symbol": "GRVT",
                    "priority": "P4_ARCHIVED_CASE",
                    "active_monitoring": False,
                    "contracts": [
                        {
                            "chain": "bsc",
                            "address": recovery.GRVT_TOKEN,
                        }
                    ],
                },
            ]
        }
        self.current_scope = {
            "status": "verified_pool_scope",
            "complete": True,
            "source": "opening",
            "matching_event_count": 1,
            "pool_scope": copy.deepcopy(self.expanded_pools),
            "pool_count": len(self.expanded_pools),
            "v3_pool_count": len(self.expanded_pools),
            "v4_pool_count": 0,
            "scope_hash": holder.liquidity_pool_scope_hash(
                self.expanded_pools
            ),
            "snapshot_refs": [
                {"block": 2300, "block_hash": hash32("3")}
            ],
        }
        self._write_json(self.paths.config, self.config)
        self._write_json(self.paths.standalone_state, self.standalone_state)
        self._write_json(self.paths.holder_state, self.holder_state)
        self._write_json(self.paths.opening, {"events": []})
        self._write_json(self.paths.replay, {"status": "historical"})
        notification = self.root / "output" / "x" / "last_push.json"
        self._write_json(notification, {"sent_at": "never"})

    def _canonical_hash(self, _chain: str, block: int) -> str:
        return {
            1200: hash32("1"),
            2200: hash32("2"),
            2300: hash32("3"),
        }.get(block, "")

    def _bundle(self) -> recovery.RecoveryBundle:
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.current_scope),
        ):
            return recovery.build_recovery_bundle(
                self.paths,
                checkpoint_hash_reader=self._canonical_hash,
            )

    def test_plan_is_deterministic_read_only_and_preserves_all_deferred(
        self,
    ) -> None:
        watched = [
            self.paths.config,
            self.paths.standalone_state,
            self.paths.holder_state,
            self.paths.opening,
            self.paths.replay,
        ]
        before = {
            path: (sha256_file(path), path.stat().st_mtime_ns)
            for path in watched
        }
        first = self._bundle()
        second = self._bundle()
        after = {
            path: (sha256_file(path), path.stat().st_mtime_ns)
            for path in watched
        }
        self.assertEqual(before, after)
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.safe_plan, second.safe_plan)
        reconciliation = first.candidate_seed["reconciliation"]
        self.assertEqual(len(reconciliation["pending"]), 0)
        self.assertEqual(len(reconciliation["completed"]), 5)
        self.assertEqual(len(reconciliation["deferred_events"]), 499)
        self.assertEqual(first.safe_plan["ambiguous_overlap_count"], 1)
        self.assertEqual(first.safe_plan["status"], "probe_required")
        safe_output = json.dumps(first.safe_plan, sort_keys=True).lower()
        self.assertNotIn("apply", safe_output)
        self.assertNotIn("rollback", safe_output)
        self.assertTrue(
            fast.liquidity_reconciliation_dominates(
                first.candidate_seed,
                first.standalone_seed,
            )
        )
        self.assertTrue(
            fast.liquidity_reconciliation_dominates(
                first.candidate_seed,
                first.holder_seed,
            )
        )
        self.assertNotIn("deferred_events", first.safe_plan)
        self.assertNotIn("pending", first.safe_plan)
        holder_state = json.loads(
            self.paths.holder_state.read_text(encoding="utf-8")
        )
        holder_state["tokens"][KEY]["retention_flow"]["liquidity"][
            "reconciliation"
        ]["completed"][0]["reconcile_id"] = "9" * 64
        self._write_json(self.paths.holder_state, holder_state)
        no_overlap = self._bundle()
        self.assertEqual(no_overlap.safe_plan["ambiguous_overlap_count"], 0)
        self.assertEqual(no_overlap.safe_plan["status"], "probe_required")
        self.assertFalse(hasattr(recovery, "apply_recovery"))
        self.assertFalse(hasattr(recovery, "rollback_recovery"))

    def test_plan_blocks_canonical_scope_and_capacity_failures(self) -> None:
        cases = []
        bad_scope = copy.deepcopy(self.current_scope)
        bad_scope["pool_scope"][0]["fee"] = 999
        bad_scope["scope_hash"] = holder.liquidity_pool_scope_hash(
            bad_scope["pool_scope"]
        )
        cases.append(
            (
                "opening_holder_scope_mismatch",
                bad_scope,
                self._canonical_hash,
            )
        )
        cases.append(("checkpoint_hash_mismatch", self.current_scope, lambda *_: hash32("9")))
        for reason, scope, reader in cases:
            with self.subTest(reason=reason):
                with mock.patch.object(
                    holder,
                    "opening_verified_pool_scope",
                    return_value=copy.deepcopy(scope),
                ):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        recovery.build_recovery_bundle(
                            self.paths,
                            checkpoint_hash_reader=reader,
                        )
                self.assertEqual(caught.exception.code, reason)

        standalone = json.loads(
            self.paths.standalone_state.read_text(encoding="utf-8")
        )
        standalone["tokens"][KEY]["liquidity"]["reconciliation"][
            "deferred_events"
        ].extend([self._deferred(700), self._deferred(701)])
        self._write_json(self.paths.standalone_state, standalone)
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.current_scope),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                recovery.build_recovery_bundle(
                    self.paths,
                    checkpoint_hash_reader=self._canonical_hash,
                )
        self.assertEqual(caught.exception.code, "standalone_seed_invalid")

    def test_plan_rejects_input_changed_after_json_read(self) -> None:
        changed = False

        def reader(chain: str, block: int) -> str:
            nonlocal changed
            if not changed:
                self.paths.config.write_text(
                    self.paths.config.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                changed = True
            return self._canonical_hash(chain, block)

        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.current_scope),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                recovery.build_recovery_bundle(
                    self.paths,
                    checkpoint_hash_reader=reader,
                )
        self.assertEqual(caught.exception.code, "input_hash_changed")

    def test_plan_requires_exact_dos_only_scope(self) -> None:
        cases = []
        policy = copy.deepcopy(self.config)
        policy["monitoring_policy"]["symbols"].append("GRVT")
        cases.append(("monitoring_policy_scope_invalid", policy))
        extra_contract = copy.deepcopy(self.config)
        extra_contract["items"][0]["contracts"].append(
            {"chain": "base", "address": TOKEN}
        )
        cases.append(("dos_watchlist_scope_invalid", extra_contract))
        extra_active = copy.deepcopy(self.config)
        extra_active["items"].append(
            {"symbol": "OTHER", "active_monitoring": True, "contracts": []}
        )
        cases.append(("non_dos_active_scope_invalid", extra_active))
        for reason, config in cases:
            with self.subTest(reason=reason):
                self._write_json(self.paths.config, config)
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    self._bundle()
                self.assertEqual(caught.exception.code, reason)
                self._write_json(self.paths.config, self.config)

    def test_probe_uses_build_snapshot_and_preserves_protected_files(
        self,
    ) -> None:
        bundle = self._bundle()
        next_state = copy.deepcopy(bundle.candidate_state)
        snapshot = {
            "schema": fast.SNAPSHOT_SCHEMA,
            "status": "healthy",
            "issue_count": 0,
            "expected_count": 1,
            "processed_count": 1,
            "required_count": 1,
            "complete_count": 1,
            "projects": [
                {
                    "symbol": "DOS",
                    "chain": "bsc",
                    "address": TOKEN,
                    "operational_complete": True,
                    "runtime_diagnostic": {
                        "reason_code": "none",
                        "provider_status": "complete",
                        "coverage_status": "complete",
                        "next_state_kind": "checkpoint",
                    },
                }
            ],
            "_next_state": next_state,
        }
        protected_before = recovery.protected_manifest(self.paths)
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.current_scope),
            ),
            mock.patch.object(fast, "build_snapshot", return_value=snapshot) as build,
            mock.patch.object(fast, "run_once", side_effect=AssertionError),
            mock.patch.object(
                holder,
                "maybe_send_telegram",
                side_effect=AssertionError,
            ),
        ):
            result = recovery.probe_recovery(
                self.paths,
                bundle.plan_hash,
                checkpoint_hash_reader=self._canonical_hash,
            )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(build.call_count, 1)
        self.assertEqual(protected_before, recovery.protected_manifest(self.paths))

    def test_probe_rejects_ambiguous_completed_deferred_evidence_loss(self) -> None:
        bundle = self._bundle()
        next_seed = copy.deepcopy(bundle.candidate_seed)
        next_seed["reconciliation"]["deferred_events"] = next_seed[
            "reconciliation"
        ]["deferred_events"][1:]
        self.assertTrue(
            fast.liquidity_reconciliation_dominates(
                next_seed, bundle.candidate_seed
            )
        )
        self.assertFalse(
            recovery.reconciliation_rows_preserved(
                bundle.candidate_seed, next_seed
            )
        )

    def test_reconciliation_rejects_any_original_event_field_mutation(self) -> None:
        bundle = self._bundle()
        for mode in ("deferred", "pending"):
            for field, before, after in (
                ("direction", "out", "in"),
                ("evidence_level", "receipt", "fabricated"),
                ("materiality_basis", "quote_absolute", "unverified"),
                ("pool_id", "0x01", "0x02"),
            ):
                with self.subTest(mode=mode, field=field):
                    previous = copy.deepcopy(bundle.candidate_seed)
                    event = previous["reconciliation"]["deferred_events"][2]
                    event[field] = before
                    candidate = copy.deepcopy(previous)
                    moved = candidate["reconciliation"]["deferred_events"][2]
                    moved[field] = after
                    if mode == "pending":
                        candidate["reconciliation"]["deferred_events"].pop(2)
                        candidate["reconciliation"]["pending"].append(
                            {
                                "reconcile_id": holder.liquidity_reconciliation_id(
                                    event
                                ),
                                "source_event": moved,
                            }
                        )
                    self.assertFalse(
                        recovery.reconciliation_rows_preserved(
                            previous, candidate
                        )
                    )
    def test_completed_transition_accepts_valid_contracts(self) -> None:
        bundle = self._bundle()
        previous = copy.deepcopy(bundle.candidate_seed)
        event = previous["reconciliation"]["deferred_events"][2]
        reconcile_id = holder.liquidity_reconciliation_id(event)
        source = {
            "reconcile_id": reconcile_id,
            "source_block": event["block"],
            "source_log_index": event["log_index"],
            "source_tx": event["tx"],
            "source_pool": event["pool"],
        }
        final = {
            **source,
            "classification": "net_removed",
            "verdict_coverage_contract_version": (
                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            ),
            "source_receipt_canonical": True,
            "verdict_coverage_complete": True,
            "source_event_utc": "2026-08-14T00:00:00+00:00",
            "active_range_vs_spot": "active",
            "spot_tick": 0,
            "pool_liquidity_before": "100",
            "pool_liquidity_after": "90",
            "recipient_next_hop": {
                "status": "no_outbound_observed",
                "coverage_complete": True,
                "attribution_complete": False,
                "enumeration_complete": True,
                "existence_complete": True,
                "recipient_count": 0,
                "canonical_transaction_count": 0,
                "observed_transaction_count_lower_bound": 0,
                "scope_limit": holder.LIQUIDITY_RECIPIENT_NEXT_HOP_TX_LIMIT,
            },
            "price_reaction_5m_pct": "0",
            "price_reaction_15m_pct": "0",
            "evidence_level": "receipt_canonical_bounded_15m",
            "enrichment_coverage_complete": True,
            "evidence_coverage_issues": [],
        }
        unresolved = {
            **source,
            "classification": "unresolved_coverage",
            "notify": False,
            "verdict_coverage_contract_version": (
                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            ),
            "source_receipt_canonical": False,
            "verdict_coverage_complete": False,
            "evidence_level": "coverage_incomplete",
            "coverage_issue_code": "liquidity_reconciliation_expired_incomplete",
            "evidence_coverage_issues": ["liquidity_operator_unavailable"],
        }
        for completed in (final, unresolved):
            candidate = copy.deepcopy(previous)
            candidate["reconciliation"]["deferred_events"].pop(2)
            candidate["reconciliation"]["completed"].append(completed)
            self.assertTrue(
                recovery.reconciliation_rows_preserved(previous, candidate)
            )
        invalid_unresolved = {**unresolved, "verdict_coverage_contract_version": "v1"}
        self.assertFalse(
            recovery.valid_completed_transition(invalid_unresolved)
        )
        candidate = copy.deepcopy(previous)
        candidate["reconciliation"]["deferred_events"].pop(2)
        candidate["reconciliation"]["completed"].append(invalid_unresolved)
        self.assertFalse(
            recovery.reconciliation_rows_preserved(previous, candidate)
        )
        producer_unresolved = copy.deepcopy(unresolved)
        producer_unresolved.pop("source_log_index")
        producer_unresolved.pop("source_pool")
        self.assertTrue(
            recovery.valid_completed_transition(producer_unresolved)
        )
        self.assertFalse(
            recovery.completed_covers_event(producer_unresolved, event)
        )

    def test_completed_transition_requires_final_coverage_contract(self) -> None:
        bundle = self._bundle()
        for source_kind in ("deferred", "pending"):
            for classification in ("forged", "unresolved_coverage", "net_removed"):
                with self.subTest(
                    source_kind=source_kind, classification=classification
                ):
                    previous = copy.deepcopy(bundle.candidate_seed)
                    event = previous["reconciliation"]["deferred_events"].pop(2)
                    reconcile_id = holder.liquidity_reconciliation_id(event)
                    if source_kind == "pending":
                        previous["reconciliation"]["pending"].append(
                            {
                                "reconcile_id": reconcile_id,
                                "source_event": copy.deepcopy(event),
                            }
                        )
                    else:
                        previous["reconciliation"]["deferred_events"].append(event)
                    candidate = copy.deepcopy(previous)
                    if source_kind == "pending":
                        candidate["reconciliation"]["pending"].pop()
                    else:
                        candidate["reconciliation"]["deferred_events"].pop()
                    candidate["reconciliation"]["completed"].append(
                        {
                            "reconcile_id": reconcile_id,
                            "classification": classification,
                            "source_block": event["block"],
                            "source_log_index": event["log_index"],
                            "source_tx": event["tx"],
                            "source_pool": event["pool"],
                            "verdict_coverage_contract_version": (
                                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
                            ),
                            "source_receipt_canonical": True,
                            "verdict_coverage_complete": True,
                            "evidence_level": "receipt_canonical_bounded_15m",
                        }
                    )
                    self.assertFalse(
                        recovery.reconciliation_rows_preserved(
                            previous, candidate
                        )
                    )

    def test_probe_runs_real_build_snapshot_over_499_deferred(self) -> None:
        bundle = self._bundle()
        bounded_calls = []

        def bounded(_chain, pools, from_block, requested_to, **_kwargs):
            bounded_calls.append((len(pools), from_block, requested_to))
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

        canonical = {2200: hash32("2"), 2300: hash32("3")}
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.current_scope),
            ),
            mock.patch.object(
                holder,
                "retention_window",
                return_value={"status": "active", "age_hours": 1},
            ),
            mock.patch.object(fast, "strict_token_metadata", return_value=(18, 10**24)),
            mock.patch.object(holder, "latest_block", return_value=2302),
            mock.patch.object(
                holder,
                "liquidity_checkpoint_block_hash",
                side_effect=lambda _chain, block: canonical.get(block, ""),
            ),
            mock.patch.object(
                holder, "bounded_retention_liquidity_logs", side_effect=bounded
            ),
            mock.patch.object(
                holder,
                "annotate_liquidity_event_operators",
                side_effect=lambda _chain, events: (copy.deepcopy(events), 0),
            ),
            mock.patch.object(
                holder,
                "attach_canonical_liquidity_timestamps",
                side_effect=lambda _chain, events: (copy.deepcopy(events), 0),
            ),
            mock.patch.object(fast, "run_once", side_effect=AssertionError),
            mock.patch.object(holder, "maybe_send_telegram", side_effect=AssertionError),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                recovery.probe_recovery(
                    self.paths,
                    bundle.plan_hash,
                    checkpoint_hash_reader=self._canonical_hash,
                )
        self.assertEqual(
            caught.exception.code,
            "clone_probe_reconciliation_evidence_loss",
        )
        self.assertEqual(bounded_calls, [(8, 2201, 2300)])

    def test_probe_rejects_stale_plan_without_state_write(self) -> None:
        bundle = self._bundle()
        state = json.loads(
            self.paths.holder_state.read_text(encoding="utf-8")
        )
        state["tokens"][KEY]["decimals"] = 17
        self._write_json(self.paths.holder_state, state)
        before = sha256_file(self.paths.standalone_state)
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=copy.deepcopy(self.current_scope),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                recovery.probe_recovery(
                    self.paths,
                    bundle.plan_hash,
                    checkpoint_hash_reader=self._canonical_hash,
                )
        self.assertEqual(caught.exception.code, "plan_hash_mismatch")
        self.assertEqual(sha256_file(self.paths.standalone_state), before)


if __name__ == "__main__":
    unittest.main()
