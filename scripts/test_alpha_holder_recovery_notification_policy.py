#!/usr/bin/env python3
from __future__ import annotations

import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder
import scripts.alpha_liquidity_retention_watch as fast


POLICY = "suppress_recovery_replay.v1"


def address(digit: str) -> str:
    return "0x" + digit * 40


def hash32(digit: str) -> str:
    return "0x" + digit * 64


class RecoveryNotificationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.started = datetime(2026, 8, 14, tzinfo=timezone.utc)
        self.removal = {
            "protocol": "v3",
            "pool": address("3"),
            "tx": hash32("a"),
            "log_index": 1,
            "block": 101,
            "block_hash": hash32("f"),
            "type": "lp_remove_observation",
            "lp_owner": address("6"),
            "tick_lower": -100,
            "tick_upper": 100,
            "liquidity_operator": address("5"),
            "liquidity_operator_basis": "transaction_sender_eoa",
            "liquidity_operator_confidence": "high",
            "liquidity_operator_class": "unlabeled_address",
            "quote_token": address("2"),
            "quote_symbol": "USDT",
            "quote_decimals": 0,
            "lp_removed_amount_raw": "100",
            "quote_removed_amount_raw": "200",
            "quote_removed_absolute_material": True,
            "chain_timestamp": self.started.isoformat(),
            "chain_timestamp_basis": "canonical_block",
            "historical_catchup": False,
        }

    def evidence(self) -> dict[str, object]:
        return {
            "coverage_complete": True,
            "verdict_coverage_contract_version": (
                holder.LIQUIDITY_VERDICT_COVERAGE_CONTRACT_VERSION
            ),
            "coverage_issues": [],
            "source_receipt_canonical": True,
            "source_event_utc": self.started.isoformat(),
            "active_range_vs_spot": "active",
            "spot_tick": 0,
            "pool_liquidity_before": "1000",
            "pool_liquidity_after": "900",
            "recipient_next_hop": {
                "status": "no_outbound_observed",
                "coverage_complete": True,
                "attribution_complete": False,
                "enumeration_complete": True,
                "existence_complete": True,
                "recipient_count": 1,
                "canonical_transaction_count": 0,
                "observed_transaction_count_lower_bound": 0,
                "scope_limit": holder.LIQUIDITY_RECIPIENT_NEXT_HOP_TX_LIMIT,
            },
            "price_reaction_5m_pct": "-1",
            "price_reaction_15m_pct": "-2",
            "evidence_level": "receipt_canonical_bounded_15m",
        }

    def reconcile_pending(self, event: dict[str, object]) -> dict[str, object]:
        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MIN_SECONDS": "300",
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MAX_SECONDS": "900",
            },
        ):
            _events, state, _metadata = holder.reconcile_liquidity_events(
                [event],
                {},
                token_decimals=0,
                observed_at=self.started,
                evidence_by_id={},
            )
        return state

    def assert_valid_next_state(
        self,
        reconciliation: dict[str, object],
        collection: str,
    ) -> None:
        migrated = holder.migrate_liquidity_reconciliation_state(
            reconciliation,
            maximum_seconds=900,
        )
        self.assertIsNot(migrated.get("state_invalid"), True)
        self.assertEqual(
            migrated[collection][0]["notification_policy"], POLICY
        )
        token = address("1")
        pool = {
            "protocol": "v3",
            "address": address("3"),
            "factory": address("4"),
            "token0": token,
            "token1": address("2"),
            "quote_token": address("2"),
            "quote_decimals": 0,
            "quote_symbol": "USDT",
            "fee": 3000,
        }
        seed = {
            "scope_state_schema_version": (
                holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
            ),
            "scope_hash": holder.liquidity_pool_scope_hash([pool]),
            "pool_scope": [pool],
            "pool_count": 1,
            "scope_coverage_from_block": 1,
            "latest_block": 101,
            "latest_block_hash": hash32("f"),
            "catchup_active": False,
            "reconciliation": reconciliation,
        }
        validated = fast.validated_liquidity_seed(seed, token)
        self.assertEqual(fast.liquidity_seed_status(seed, validated), "valid")
        self.assertNotIn("reconciliation_state_invalid", validated)
        self.assertEqual(
            validated["reconciliation"][collection][0][
                "notification_policy"
            ],
            POLICY,
        )

    def final_event(
        self,
        state: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        reconcile_id = state["pending"][0]["reconcile_id"]
        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MIN_SECONDS": "300",
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MAX_SECONDS": "900",
            },
        ):
            events, next_state, _metadata = holder.reconcile_liquidity_events(
                [],
                state,
                token_decimals=0,
                observed_at=self.started + timedelta(seconds=900),
                evidence_by_id={reconcile_id: self.evidence()},
            )
        verdicts = [
            event
            for event in events
            if event.get("type") == "liquidity_reconciliation"
        ]
        self.assertEqual(len(verdicts), 1)
        return verdicts[0], next_state

    def alert_keys_for(self, event: dict[str, object]) -> list[str]:
        project = {
            "chain": "bsc",
            "address": address("1"),
            "retention_flow": {
                "events": [],
                "liquidity_retention": {"events": [event]},
            },
        }
        with (
            mock.patch.object(
                holder,
                "retention_alert_coverage_complete",
                return_value=False,
            ),
            mock.patch.object(
                holder,
                "liquidity_selected_window_alert_coverage_complete",
                return_value=True,
            ),
        ):
            return holder.alert_keys({"projects": [project]})

    def test_recovery_policy_persists_and_suppresses_final_alert(self) -> None:
        event = {**self.removal, "notification_policy": POLICY}
        pending_state = self.reconcile_pending(event)
        pending = pending_state["pending"][0]
        self.assertEqual(pending["notification_policy"], POLICY)
        self.assertEqual(
            pending["source_event"]["notification_policy"], POLICY
        )
        self.assert_valid_next_state(pending_state, "pending")

        verdict, final_state = self.final_event(pending_state)
        self.assertEqual(verdict["notification_policy"], POLICY)
        self.assertFalse(verdict["notify"])
        self.assertFalse(verdict["alert_eligible"])
        self.assertTrue(verdict["historical_catchup"])
        completed = final_state["completed"][0]
        self.assertEqual(completed["notification_policy"], POLICY)
        self.assertFalse(completed["notify"])
        self.assertFalse(completed["alert_eligible"])
        self.assertTrue(completed["historical_catchup"])
        self.assert_valid_next_state(final_state, "completed")
        self.assertEqual(self.alert_keys_for(verdict), [])

    def test_recovery_policy_suppresses_unresolved_and_normal_stays_live(
        self,
    ) -> None:
        recovery_state = self.reconcile_pending(
            {**self.removal, "notification_policy": POLICY}
        )
        with mock.patch.dict(
            os.environ,
            {
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MIN_SECONDS": "300",
                "ALPHA_RETENTION_LIQUIDITY_RECONCILE_MAX_SECONDS": "900",
            },
        ):
            events, unresolved_state, _metadata = (
                holder.reconcile_liquidity_events(
                    [],
                    recovery_state,
                    token_decimals=0,
                    observed_at=self.started + timedelta(seconds=3601),
                    evidence_by_id={},
                )
            )
        self.assertEqual(events, [])
        unresolved = unresolved_state["completed"][0]
        self.assertEqual(unresolved["classification"], "unresolved_coverage")
        self.assertEqual(unresolved["notification_policy"], POLICY)
        self.assertFalse(unresolved["notify"])
        self.assertFalse(unresolved["alert_eligible"])
        self.assertTrue(unresolved["historical_catchup"])

        normal_state = self.reconcile_pending(copy.deepcopy(self.removal))
        normal_verdict, normal_final_state = self.final_event(normal_state)
        self.assertNotIn("notification_policy", normal_state["pending"][0])
        self.assertNotIn(
            "notification_policy", normal_final_state["completed"][0]
        )
        self.assertTrue(normal_verdict["notify"])
        self.assertTrue(normal_verdict["alert_eligible"])
        self.assertFalse(normal_verdict["historical_catchup"])
        self.assertEqual(len(self.alert_keys_for(normal_verdict)), 1)

    def test_recovery_policy_suppresses_non_v3_passthrough(self) -> None:
        recovery = {
            **self.removal,
            "protocol": "v4_cl",
            "notification_policy": POLICY,
            "notify": True,
            "alert_eligible": True,
            "level": "HIGH",
        }
        events, state, _metadata = holder.reconcile_liquidity_events(
            [recovery],
            {},
            token_decimals=0,
            observed_at=self.started,
            evidence_by_id={},
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["notification_policy"], POLICY)
        self.assertFalse(event["notify"])
        self.assertFalse(event["alert_eligible"])
        self.assertTrue(event["historical_catchup"])
        self.assertEqual(event["level"], "HIGH")
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["completed"], [])
        self.assertEqual(self.alert_keys_for(event), [])

        normal = {
            **self.removal,
            "protocol": "v4_cl",
            "notify": True,
            "alert_eligible": True,
            "level": "HIGH",
        }
        normal_events, _state, _metadata = holder.reconcile_liquidity_events(
            [normal],
            {},
            token_decimals=0,
            observed_at=self.started,
            evidence_by_id={},
        )
        self.assertNotIn("notification_policy", normal_events[0])
        self.assertTrue(normal_events[0]["notify"])
        self.assertTrue(normal_events[0]["alert_eligible"])
        self.assertEqual(normal_events[0]["level"], "HIGH")
        self.assertFalse(normal_events[0]["historical_catchup"])
        self.assertEqual(len(self.alert_keys_for(normal_events[0])), 1)


if __name__ == "__main__":
    unittest.main()
