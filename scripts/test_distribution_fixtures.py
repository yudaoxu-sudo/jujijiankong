#!/usr/bin/env python3
"""Pure-offline synthetic fixtures for deferred distribution extensions.

The reference matcher below validates evidence shape only. Nothing is imported
by runtime code and no distribution classification is enabled in production.
"""
from __future__ import annotations

import socket
import unittest


FIXTURE_POLICY = {
    "synthetic": True,
    "runtime_effect": "none",
    "alert_policy": "report_only",
}

POSITIVE_FIXTURES = {
    "multisig_batch": {
        "source_role": "multisig",
        "execution_id": "synthetic-batch-1",
        "required_signers": 2,
        "approved_signers": 3,
        "transfers": [
            {"recipient": "beneficiary-a", "amount": "12"},
            {"recipient": "beneficiary-b", "amount": "18"},
        ],
    },
    "vesting_release": {
        "source_role": "vesting_contract",
        "schedule_id": "synthetic-vesting-1",
        "beneficiary": "beneficiary-a",
        "cliff_reached": True,
        "release_event": True,
        "transfers": [{"recipient": "beneficiary-a", "amount": "25"}],
    },
    "token_unlock": {
        "source_role": "timelock_contract",
        "lock_id": "synthetic-lock-1",
        "unlock_time_reached": True,
        "release_event": True,
        "transfers": [{"recipient": "treasury-a", "amount": "40"}],
    },
    "staking_distribution": {
        "source_role": "staking_rewards_contract",
        "reward_epoch": "synthetic-epoch-1",
        "claim_events": [
            {"position_id": "position-a", "recipient": "staker-a", "amount": "3"},
            {"position_id": "position-b", "recipient": "staker-b", "amount": "4"},
        ],
        "transfers": [
            {"recipient": "staker-a", "amount": "3"},
            {"recipient": "staker-b", "amount": "4"},
        ],
    },
}

CONFUSING_NEGATIVES = {
    "ordinary_batch_airdrop": {
        "source_role": "airdrop_distributor",
        "execution_id": "synthetic-airdrop-1",
        "required_signers": 1,
        "approved_signers": 1,
        "transfers": [
            {"recipient": "wallet-a", "amount": "10"},
            {"recipient": "wallet-b", "amount": "10"},
        ],
    },
    "cex_aggregation_fanout": {
        "source_role": "cex_hot_wallet",
        "transfers": [
            {"recipient": "deposit-a", "amount": "11"},
            {"recipient": "deposit-b", "amount": "13"},
            {"recipient": "deposit-c", "amount": "17"},
        ],
    },
}


def evidence_kind(row: dict[str, object]) -> str | None:
    transfers = row.get("transfers")
    if not isinstance(transfers, list) or not transfers:
        return None
    role = row.get("source_role")
    if (
        role == "multisig"
        and row.get("execution_id")
        and int(row.get("required_signers") or 0) >= 2
        and int(row.get("approved_signers") or 0) >= int(row["required_signers"])
        and len(transfers) >= 2
    ):
        return "multisig_batch"
    if (
        role == "vesting_contract"
        and row.get("schedule_id")
        and row.get("beneficiary")
        and row.get("cliff_reached") is True
        and row.get("release_event") is True
        and all(item.get("recipient") == row["beneficiary"] for item in transfers)
    ):
        return "vesting_release"
    if (
        role == "timelock_contract"
        and row.get("lock_id")
        and row.get("unlock_time_reached") is True
        and row.get("release_event") is True
    ):
        return "token_unlock"
    if role == "staking_rewards_contract" and row.get("reward_epoch"):
        claims = row.get("claim_events")
        if not isinstance(claims, list) or not claims:
            return None
        claimed = {
            (item.get("recipient"), item.get("amount"))
            for item in claims
            if item.get("position_id")
        }
        transferred = {
            (item.get("recipient"), item.get("amount"))
            for item in transfers
        }
        if claimed == transferred:
            return "staking_distribution"
    return None


_REAL_SOCKET = socket.socket
_REAL_CREATE_CONNECTION = socket.create_connection


def _blocked_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("distribution fixture test attempted network access")


def setUpModule() -> None:
    socket.socket = _blocked_network  # type: ignore[assignment]
    socket.create_connection = _blocked_network


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[assignment]
    socket.create_connection = _REAL_CREATE_CONNECTION


class DistributionFixtureTests(unittest.TestCase):
    def test_policy_keeps_fixtures_report_only(self) -> None:
        self.assertEqual(
            FIXTURE_POLICY,
            {
                "synthetic": True,
                "runtime_effect": "none",
                "alert_policy": "report_only",
            },
        )

    def test_all_four_positive_evidence_shapes_are_distinct(self) -> None:
        observed = {name: evidence_kind(row) for name, row in POSITIVE_FIXTURES.items()}
        self.assertEqual(
            observed,
            {
                "multisig_batch": "multisig_batch",
                "vesting_release": "vesting_release",
                "token_unlock": "token_unlock",
                "staking_distribution": "staking_distribution",
            },
        )

    def test_ordinary_batch_airdrop_is_not_multisig_or_unlock(self) -> None:
        self.assertIsNone(evidence_kind(CONFUSING_NEGATIVES["ordinary_batch_airdrop"]))

    def test_cex_aggregation_fanout_is_not_distribution_evidence(self) -> None:
        self.assertIsNone(evidence_kind(CONFUSING_NEGATIVES["cex_aggregation_fanout"]))

    def test_vesting_requires_beneficiary_and_cliff_evidence(self) -> None:
        fixture = dict(POSITIVE_FIXTURES["vesting_release"])
        fixture["cliff_reached"] = False
        self.assertIsNone(evidence_kind(fixture))

    def test_staking_claims_must_match_transfers(self) -> None:
        fixture = dict(POSITIVE_FIXTURES["staking_distribution"])
        fixture["transfers"] = [{"recipient": "staker-a", "amount": "3"}]
        self.assertIsNone(evidence_kind(fixture))


if __name__ == "__main__":
    unittest.main()
