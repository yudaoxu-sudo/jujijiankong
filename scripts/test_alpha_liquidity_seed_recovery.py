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

    def _real_deferred(self, index: int) -> dict[str, object]:
        event = self._deferred(index)
        if index < 390:
            event.update({
                "type": "lp_add_observation",
                "lp_added_amount_raw": 100,
                "quote_added_amount_raw": 100,
                "historical_catchup": index < 168,
            })
        elif index < 439:
            event["historical_catchup"] = True
        elif index < 444:
            event["lp_removed_amount_raw"] = 0
            event["quote_removed_amount_raw"] = 0
        return event

    def _prior_pending(self) -> dict[str, object]:
        event = self._deferred(900)
        return {
            "reconcile_id": holder.liquidity_reconciliation_id(event),
            "verdict_coverage_contract_version": (
                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            ),
            "first_seen_at": "2099-08-14T01:00:00+00:00",
            "last_updated_at": "2099-08-14T01:00:00+00:00",
            "expires_at": "2099-08-14T02:00:00+00:00",
            "operator": "",
            "operator_basis": "unattributed",
            "operator_confidence": "low",
            "operator_class": "",
            "source_pool": event["pool"],
            "source_block": event["block"],
            "source_log_index": event["log_index"],
            "source_block_hash": event["block_hash"],
            "quote_token": event["quote_token"],
            "quote_symbol": event["quote_symbol"],
            "quote_decimals": event["quote_decimals"],
            "removed_target_raw": 100,
            "removed_quote_raw": 100,
            "added_target_raw": 10,
            "added_quote_raw": 0,
            "destination_pools": [],
            "add_transactions": [],
            "materiality_basis": "target_supply",
            "source_ranges": holder.liquidity_event_ranges(event, "source_ranges"),
            "destination_ranges": [],
            "source_chain_timestamp": "2099-08-14T01:00:00+00:00",
            "source_chain_timestamp_basis": "observed_fallback",
            "source_event": event,
        }

    def _install_real_distribution(self) -> None:
        events = [self._real_deferred(index) for index in range(499)]
        overlap = events[-1]
        standalone = copy.deepcopy(self.standalone_state)
        standalone["tokens"][KEY]["liquidity"]["reconciliation"][
            "deferred_events"
        ] = events
        holder_state = copy.deepcopy(self.holder_state)
        reconciliation = holder_state["tokens"][KEY]["retention_flow"][
            "liquidity"
        ]["reconciliation"]
        reconciliation["pending"] = [self._prior_pending()]
        reconciliation["completed"][0] = {
            "reconcile_id": holder.liquidity_reconciliation_id(overlap),
            "completed_at": "2026-08-14T00:00:00+00:00",
            "classification": "unresolved_coverage",
            "source_block": overlap["block"],
            "source_tx": overlap["tx"],
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
        self._write_json(self.paths.standalone_state, standalone)
        self._write_json(self.paths.holder_state, holder_state)

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
        completed[0].pop("source_log_index")
        completed[0].pop("source_pool")
        completed[0].update({
            "notify": False,
            "verdict_coverage_contract_version": (
                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            ),
            "source_receipt_canonical": False,
            "verdict_coverage_complete": False,
            "evidence_level": "coverage_incomplete",
            "coverage_issue_code": "liquidity_reconciliation_expired_incomplete",
            "evidence_coverage_issues": ["liquidity_operator_unavailable"],
        })
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
        self.assertIsInstance(first.archive_bytes, bytes)
        self.assertEqual(
            first.safe_plan["archive_sha256"], recovery.digest(first.archive_bytes)
        )
        self.assertEqual(first.safe_plan["archive_event_count"], 499)
        safe_output = json.dumps(first.safe_plan, sort_keys=True).lower()
        self.assertNotIn("apply", safe_output)
        self.assertNotIn("rollback", safe_output)
        for raw in ("original_events", "standalone_seed", "holder_seed",
                    str(self._deferred(0)["tx"]).lower(),
                    str(self._deferred(4)["pool"]).lower()):
            self.assertNotIn(raw, safe_output)
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

    def test_holder_seed_allows_only_official_reconciliation_normalization(
        self,
    ) -> None:
        raw = copy.deepcopy(
            self.holder_state["tokens"][KEY]["retention_flow"]["liquidity"]
        )
        self.assertNotIn("deferred_events", raw["reconciliation"])
        normalized = recovery.validated_seed(raw, "holder")
        expected = copy.deepcopy(raw)
        expected["reconciliation"] = holder.migrate_liquidity_reconciliation_state(
            raw["reconciliation"], maximum_seconds=900
        )
        self.assertEqual(normalized, expected)
        for field in ("pending", "completed", "deferred_events"):
            with self.subTest(oversize=field):
                oversized = copy.deepcopy(raw)
                if field == "pending":
                    template = self._prior_pending()
                    rows = [
                        {**copy.deepcopy(template), "reconcile_id": f"{index + 1:064x}"}
                        for index in range(501)
                    ]
                elif field == "completed":
                    template = raw["reconciliation"]["completed"][1]
                    rows = [
                        {**copy.deepcopy(template), "reconcile_id": f"{index + 1:064x}"}
                        for index in range(501)
                    ]
                else:
                    rows = [self._deferred(index + 1000) for index in range(501)]
                oversized["reconciliation"][field] = rows
                with self.assertRaises(recovery.RecoveryBlocked) as caught:
                    recovery.validated_seed(oversized, "holder")
                self.assertEqual(caught.exception.code, "holder_seed_invalid")
        other_difference = copy.deepcopy(raw)
        other_difference["unexpected_normalized_field"] = "must_fail"
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            recovery.validated_seed(other_difference, "holder")
        self.assertEqual(caught.exception.code, "holder_seed_invalid")
        standalone = copy.deepcopy(self.standalone_seed)
        standalone["reconciliation"].pop("deferred_events")
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            recovery.validated_seed(standalone, "standalone")
        self.assertEqual(caught.exception.code, "standalone_seed_invalid")

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

    def test_plan_accepts_positive_opening_match_count_only(self) -> None:
        coherent_scope = copy.deepcopy(self.current_scope)
        coherent_scope["matching_event_count"] = 2
        with mock.patch.object(
            holder,
            "opening_verified_pool_scope",
            return_value=coherent_scope,
        ):
            bundle = recovery.build_recovery_bundle(
                self.paths,
                checkpoint_hash_reader=self._canonical_hash,
            )
        self.assertEqual(bundle.safe_plan["status"], "probe_required")

        invalid_scopes = []
        for count in (0, 1.0, "2", True, None):
            scope = copy.deepcopy(self.current_scope)
            scope["matching_event_count"] = count
            invalid_scopes.append((repr(count), scope))
        invalid_helper = copy.deepcopy(coherent_scope)
        invalid_helper["status"] = "incomplete"
        invalid_scopes.append(("helper_invalid", invalid_helper))
        invalid_scopes.extend(
            (f"helper_{type(value).__name__}", value)
            for value in (None, [], "invalid", 2)
        )
        for value in (None, "invalid", 2):
            scope = copy.deepcopy(coherent_scope)
            scope["pool_scope"] = [value]
            invalid_scopes.append((f"pool_row_{type(value).__name__}", scope))
        for label, scope in invalid_scopes:
            with self.subTest(case=label):
                with mock.patch.object(
                    holder,
                    "opening_verified_pool_scope",
                    return_value=scope,
                ):
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        recovery.build_recovery_bundle(
                            self.paths,
                            checkpoint_hash_reader=self._canonical_hash,
                        )
                self.assertEqual(caught.exception.code, "opening_scope_invalid")

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

    def test_plan_rejects_non_integer_deferred_identity_fields(self) -> None:
        original = self.standalone_seed["reconciliation"]["deferred_events"][0]
        for field in ("block", "log_index"):
            value = original[field]
            for bad in (float(value) + 0.9, str(value), False):
                with self.subTest(field=field, bad=bad):
                    state = copy.deepcopy(self.standalone_state)
                    state["tokens"][KEY]["liquidity"]["reconciliation"][
                        "deferred_events"
                    ][0][field] = bad
                    self._write_json(self.paths.standalone_state, state)
                    with self.assertRaises(recovery.RecoveryBlocked) as caught:
                        self._bundle()
                    self.assertEqual(
                        caught.exception.code, "reconciliation_identity_invalid"
                    )
                    self._write_json(
                        self.paths.standalone_state, self.standalone_state
                    )
        state = copy.deepcopy(self.standalone_state)
        state["tokens"][KEY]["liquidity"]["reconciliation"][
            "deferred_events"
        ][0]["pool"] = address("9")
        self._write_json(self.paths.standalone_state, state)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._bundle()
        self.assertEqual(caught.exception.code, "reconciliation_scope_invalid")
        self._write_json(self.paths.standalone_state, self.standalone_state)

    def test_plan_rejects_malformed_prior_pending_source_identity(self) -> None:
        self._install_real_distribution()
        baseline = json.loads(self.paths.holder_state.read_text(encoding="utf-8"))
        for side in ("pending", "source_event"):
            for pending_field, event_field in (
                ("source_block", "block"),
                ("source_log_index", "log_index"),
            ):
                original = baseline["tokens"][KEY]["retention_flow"][
                    "liquidity"
                ]["reconciliation"]["pending"][0][pending_field]
                for bad in (float(original) + 0.9, str(original), False, -1, None):
                    with self.subTest(side=side, field=pending_field, bad=bad):
                        state = copy.deepcopy(baseline)
                        pending = state["tokens"][KEY]["retention_flow"][
                            "liquidity"
                        ]["reconciliation"]["pending"][0]
                        target = pending if side == "pending" else pending["source_event"]
                        field = pending_field if side == "pending" else event_field
                        if bad is None:
                            target.pop(field)
                        else:
                            target[field] = bad
                        self._write_json(self.paths.holder_state, state)
                        with self.assertRaises(recovery.RecoveryBlocked):
                            self._bundle()
        for side, field, bad in (
            ("pending", "reconcile_id", "f" * 64),
            ("pending", "source_pool", address("9")),
            ("pending", "source_pool", ""),
            ("pending", "source_block_hash", hash32("9")),
            ("pending", "source_block_hash", ""),
            ("pending", "source_tx", hash32("9")),
            ("source_event", "pool", address("9")),
            ("source_event", "pool", ""),
            ("source_event", "block_hash", hash32("9")),
            ("source_event", "block_hash", ""),
            ("source_event", "tx", hash32("9")),
        ):
            with self.subTest(side=side, field=field, bad=bad):
                state = copy.deepcopy(baseline)
                pending = state["tokens"][KEY]["retention_flow"]["liquidity"][
                    "reconciliation"
                ]["pending"][0]
                target = pending if side == "pending" else pending["source_event"]
                target[field] = bad
                self._write_json(self.paths.holder_state, state)
                with self.assertRaises(recovery.RecoveryBlocked):
                    self._bundle()
        state = copy.deepcopy(baseline)
        pending = state["tokens"][KEY]["retention_flow"]["liquidity"][
            "reconciliation"
        ]["pending"][0]
        pending["source_pool"] = address("9")
        pending["source_event"]["pool"] = address("9")
        pending["reconcile_id"] = holder.liquidity_reconciliation_id(
            pending["source_event"]
        )
        self._write_json(self.paths.holder_state, state)
        with self.assertRaises(recovery.RecoveryBlocked) as caught:
            self._bundle()
        self.assertEqual(caught.exception.code, "reconciliation_scope_invalid")
        self._write_json(self.paths.holder_state, baseline)

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
        next_state["tokens"][KEY]["liquidity"]["reconciliation"][
            "deferred_events"
        ] = next_state["tokens"][KEY]["liquidity"]["reconciliation"][
            "deferred_events"
        ][1:]
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
            self.assertTrue(recovery.valid_completed_transition(completed))
            self.assertTrue(recovery.completed_covers_event(completed, event))
        invalid_unresolved = {**unresolved, "verdict_coverage_contract_version": "v1"}
        self.assertFalse(
            recovery.valid_completed_transition(invalid_unresolved)
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
        event = bundle.candidate_seed["reconciliation"]["deferred_events"][2]
        for classification in ("forged", "unresolved_coverage", "net_removed"):
            with self.subTest(classification=classification):
                completed = {
                    "reconcile_id": holder.liquidity_reconciliation_id(event),
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
                self.assertFalse(recovery.valid_completed_transition(completed))
                self.assertFalse(recovery.completed_covers_event(completed, event))

    def test_completed_transition_requires_strict_integer_source_identity(
        self,
    ) -> None:
        bundle = self._bundle()
        event = bundle.candidate_seed["reconciliation"]["deferred_events"][0]
        completed = {
            "reconcile_id": holder.liquidity_reconciliation_id(event),
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
            "source_block": event["block"],
            "source_log_index": event["log_index"],
            "source_tx": event["tx"],
            "source_pool": event["pool"],
        }
        self.assertTrue(recovery.completed_covers_event(completed, event))
        for side in ("completed", "event"):
            for completed_field, event_field in (
                ("source_block", "block"),
                ("source_log_index", "log_index"),
            ):
                original = event[event_field]
                for bad in (float(original) + 0.9, str(original), False):
                    with self.subTest(side=side, field=event_field, bad=bad):
                        changed_event = copy.deepcopy(event)
                        changed_completed = copy.deepcopy(completed)
                        if side == "completed":
                            changed_completed[completed_field] = bad
                        else:
                            changed_event[event_field] = bad
                            changed_completed["reconcile_id"] = (
                                holder.liquidity_reconciliation_id(changed_event)
                            )
                        self.assertFalse(recovery.completed_covers_event(
                            changed_completed, changed_event))

    def test_probe_runs_real_build_snapshot_over_499_deferred(self) -> None:
        self._install_real_distribution()
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
            result = recovery.probe_recovery(
                self.paths,
                bundle.plan_hash,
                checkpoint_hash_reader=self._canonical_hash,
            )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["archive_event_count"], 499)
        self.assertEqual(result["transition_counts"], {
            "add_consumed": 390,
            "completed": 0,
            "deferred_exact": 0,
            "historical_removal_suppressed": 49,
            "legacy_unresolved_overlap": 1,
            "pending": 54,
            "zero_material_removal": 5,
        })
        self.assertEqual(result["unaccounted_count"], 0)
        self.assertEqual(result["duplicate_disposition_count"], 0)
        self.assertEqual(result["next_pending_count"], 55)
        self.assertEqual(bounded_calls, [(8, 2201, 2300)])
        probe_output = json.dumps(result, sort_keys=True).lower()
        for raw in ("original_events", "standalone_seed", "holder_seed",
                    str(self._real_deferred(0)["tx"]).lower(),
                    str(self._real_deferred(4)["pool"]).lower()):
            self.assertNotIn(raw, probe_output)

    def test_typed_accounting_rejects_field_loss_and_ambiguous_destination(
        self,
    ) -> None:
        bundle = self._bundle()
        event = bundle.candidate_seed["reconciliation"]["deferred_events"][2]
        key = holder.liquidity_reconciliation_id(event)
        for mode in ("field_loss", "ambiguous"):
            with self.subTest(mode=mode):
                next_seed = copy.deepcopy(bundle.candidate_seed)
                overlap_id = next_seed["reconciliation"]["completed"][0][
                    "reconcile_id"
                ]
                next_seed["reconciliation"]["deferred_events"] = [
                    row for row in next_seed["reconciliation"]["deferred_events"]
                    if holder.liquidity_reconciliation_id(row) != overlap_id
                ]
                if mode == "field_loss":
                    moved = next(
                        row for row in next_seed["reconciliation"]["deferred_events"]
                        if holder.liquidity_reconciliation_id(row) == key
                    )
                    next_seed["reconciliation"]["deferred_events"].remove(moved)
                    moved.pop("pool")
                else:
                    moved = copy.deepcopy(event)
                next_seed["reconciliation"]["pending"].append({
                    "reconcile_id": key,
                    "source_block": event["block"],
                    "source_log_index": event["log_index"],
                    "source_pool": event["pool"],
                    "source_block_hash": event["block_hash"],
                    "source_event": moved,
                })
                accounting = recovery.typed_transition_accounting(
                    bundle, next_seed
                )
                self.assertGreater(
                    accounting[
                        "unaccounted_count"
                        if mode == "field_loss"
                        else "duplicate_disposition_count"
                    ],
                    0,
                )

    def test_typed_accounting_rejects_explicit_legacy_overlap_mismatch(
        self,
    ) -> None:
        bundle = self._bundle()
        for field, value in (
            ("source_pool", address("9")),
            ("source_block_hash", hash32("9")),
        ):
            with self.subTest(field=field):
                next_seed = copy.deepcopy(bundle.candidate_seed)
                overlap = next_seed["reconciliation"]["completed"][0]
                overlap_id = overlap["reconcile_id"]
                next_seed["reconciliation"]["deferred_events"] = [
                    row for row in next_seed["reconciliation"]["deferred_events"]
                    if holder.liquidity_reconciliation_id(row) != overlap_id
                ]
                overlap[field] = value
                accounting = recovery.typed_transition_accounting(bundle, next_seed)
                self.assertEqual(accounting["unaccounted_count"], 1)

    def test_legacy_overlap_requires_strict_integer_archived_event_identity(
        self,
    ) -> None:
        bundle = self._bundle()
        event = bundle.candidate_seed["reconciliation"]["deferred_events"][0]
        completed = bundle.candidate_seed["reconciliation"]["completed"][0]
        self.assertTrue(recovery.legacy_unresolved_covers_event(completed, event))
        for field in ("block", "log_index"):
            value = event[field]
            for bad in (float(value) + 0.9, str(value), False):
                with self.subTest(field=field, bad=bad):
                    changed = copy.deepcopy(event)
                    changed[field] = bad
                    row = copy.deepcopy(completed)
                    row["reconcile_id"] = holder.liquidity_reconciliation_id(
                        changed
                    )
                    self.assertFalse(
                        recovery.legacy_unresolved_covers_event(row, changed)
                    )

    def test_typed_accounting_rejects_new_unresolved_as_legacy_overlap(
        self,
    ) -> None:
        bundle = self._bundle()
        next_seed = copy.deepcopy(bundle.candidate_seed)
        target = next_seed["reconciliation"]["deferred_events"].pop(2)
        template = copy.deepcopy(next_seed["reconciliation"]["completed"][0])
        template.update({
            "reconcile_id": holder.liquidity_reconciliation_id(target),
            "source_block": target["block"],
            "source_tx": target["tx"],
        })
        next_seed["reconciliation"]["completed"].append(template)
        accounting = recovery.typed_transition_accounting(bundle, next_seed)
        self.assertEqual(accounting["unaccounted_count"], 1)

    def test_typed_accounting_rejects_prior_pending_regression(self) -> None:
        self._install_real_distribution()
        bundle = self._bundle()
        before_pending = bundle.candidate_seed["reconciliation"]["pending"][0]
        self.assertTrue(recovery.pending_transition_valid(
            before_pending, copy.deepcopy(before_pending)))
        for field, value in (
            ("added_target_raw", 9),
            ("removed_target_raw", 101),
            ("verdict_coverage_contract_version", "v1"),
            ("reconcile_id", "f" * 64),
            ("source_pool", address("9")),
            ("source_block_hash", hash32("9")),
            ("source_tx", hash32("9")),
            ("forced_classification", "removed_plus_sold"),
            ("last_updated_at", "2099-08-13T01:00:00+00:00"),
            ("last_updated_at", "invalid"),
            ("destination_pools", [address("9"), address("9")]),
        ):
            with self.subTest(field=field, value=value):
                next_seed = copy.deepcopy(bundle.candidate_seed)
                next_seed["reconciliation"]["pending"][0][field] = value
                self.assertFalse(recovery.pending_transition_valid(
                    before_pending, next_seed["reconciliation"]["pending"][0]))
                accounting = recovery.typed_transition_accounting(bundle, next_seed)
                self.assertEqual(accounting["prior_pending_invalid_count"], 1)
        next_seed = copy.deepcopy(bundle.candidate_seed)
        next_seed["reconciliation"]["pending"][0].pop("quote_symbol")
        self.assertFalse(recovery.pending_transition_valid(
            before_pending, next_seed["reconciliation"]["pending"][0]))
        accounting = recovery.typed_transition_accounting(bundle, next_seed)
        self.assertEqual(accounting["prior_pending_invalid_count"], 1)

        holder_state = json.loads(self.paths.holder_state.read_text(encoding="utf-8"))
        prior = holder_state["tokens"][KEY]["retention_flow"]["liquidity"][
            "reconciliation"
        ]["pending"][0]
        prior.update({"pairing_ambiguous": True, "range_changed": True})
        self._write_json(self.paths.holder_state, holder_state)
        sticky_bundle = self._bundle()
        sticky_next = copy.deepcopy(sticky_bundle.candidate_seed)
        sticky = sticky_next["reconciliation"]["pending"][0]
        sticky.update({"pairing_ambiguous": False, "range_changed": False})
        accounting = recovery.typed_transition_accounting(sticky_bundle, sticky_next)
        self.assertEqual(accounting["prior_pending_invalid_count"], 1)

    def test_probe_rejects_snapshot_alert_key(self) -> None:
        bundle = self._bundle()
        snapshot = {
            "schema": fast.SNAPSHOT_SCHEMA,
            "status": "healthy",
            "issue_count": 0,
            "expected_count": 1,
            "processed_count": 1,
            "required_count": 1,
            "complete_count": 1,
            "projects": [{
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
            }],
            "_next_state": copy.deepcopy(bundle.candidate_state),
        }
        with (
            mock.patch.object(
                holder,
                "opening_verified_pool_scope",
                return_value=copy.deepcopy(self.current_scope),
            ),
            mock.patch.object(fast, "build_snapshot", return_value=snapshot),
            mock.patch.object(holder, "alert_keys", return_value=["dos-alert"]),
        ):
            with self.assertRaises(recovery.RecoveryBlocked) as caught:
                recovery.probe_recovery(
                    self.paths,
                    bundle.plan_hash,
                    checkpoint_hash_reader=self._canonical_hash,
                )
        self.assertEqual(caught.exception.code, "clone_probe_alert_pending")

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
