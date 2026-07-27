#!/usr/bin/env python3
"""Pure-offline synthetic fixtures for the deferred wash-volume review.

These fixtures are test assets only. They do not import runtime modules, emit
alerts, or enable a wash-volume classifier.
"""
from __future__ import annotations

import socket
import unittest
from collections import defaultdict
from decimal import Decimal


FIXTURE_POLICY = {
    "synthetic": True,
    "runtime_effect": "none",
    "alert_policy": "report_only",
    "calibration_count_eligible": False,
}

GROSS_NET_FIXTURES = {
    "high_churn_low_net": [
        {"receipt": "r1", "asset": "TOKEN", "from": "A", "to": "B", "amount": "100"},
        {"receipt": "r2", "asset": "TOKEN", "from": "B", "to": "A", "amount": "99"},
    ],
    "one_way_transfer": [
        {"receipt": "r3", "asset": "TOKEN", "from": "A", "to": "B", "amount": "100"},
    ],
}

ROUND_TRIP_FIXTURES = {
    "closed_loop": [
        {"receipt": "r4", "asset": "TOKEN", "from": "A", "to": "B", "amount": "10"},
        {"receipt": "r5", "asset": "TOKEN", "from": "B", "to": "C", "amount": "9"},
        {"receipt": "r6", "asset": "TOKEN", "from": "C", "to": "A", "amount": "8"},
    ],
    "open_path": [
        {"receipt": "r7", "asset": "TOKEN", "from": "A", "to": "B", "amount": "10"},
        {"receipt": "r8", "asset": "TOKEN", "from": "B", "to": "C", "amount": "9"},
        {"receipt": "r9", "asset": "TOKEN", "from": "C", "to": "D", "amount": "8"},
    ],
}

QUOTE_RECOVERY_FIXTURES = {
    "same_receipt": [
        {"receipt": "sale-1", "asset": "TOKEN", "from": "A", "to": "POOL", "amount": "50"},
        {"receipt": "sale-1", "asset": "QUOTE", "from": "POOL", "to": "A", "amount": "5"},
    ],
    "different_receipts": [
        {"receipt": "sale-2", "asset": "TOKEN", "from": "A", "to": "POOL", "amount": "50"},
        {"receipt": "unrelated-1", "asset": "QUOTE", "from": "POOL", "to": "A", "amount": "5"},
    ],
    "wrong_recipient": [
        {"receipt": "sale-3", "asset": "TOKEN", "from": "A", "to": "POOL", "amount": "50"},
        {"receipt": "sale-3", "asset": "QUOTE", "from": "POOL", "to": "B", "amount": "5"},
    ],
}


def gross_to_terminal_net_ratio(transfers: list[dict[str, str]], asset: str) -> Decimal:
    """Return gross movement divided by terminal imbalance for one asset."""
    balances: defaultdict[str, Decimal] = defaultdict(Decimal)
    gross = Decimal(0)
    for row in transfers:
        if row["asset"] != asset:
            continue
        amount = Decimal(row["amount"])
        if amount <= 0:
            raise ValueError("synthetic transfer amount must be positive")
        gross += amount
        balances[row["from"]] -= amount
        balances[row["to"]] += amount
    terminal_net = sum(abs(value) for value in balances.values()) / 2
    if gross == 0:
        return Decimal(0)
    if terminal_net == 0:
        return Decimal("Infinity")
    return gross / terminal_net


def has_address_round_trip(transfers: list[dict[str, str]], asset: str) -> bool:
    graph: defaultdict[str, set[str]] = defaultdict(set)
    for row in transfers:
        if row["asset"] == asset and Decimal(row["amount"]) > 0:
            graph[row["from"]].add(row["to"])

    def reaches(start: str, current: str, seen: set[str]) -> bool:
        for target in graph.get(current, ()):
            if target == start:
                return True
            if target not in seen and reaches(start, target, seen | {target}):
                return True
        return False

    return any(reaches(start, start, {start}) for start in tuple(graph))


def same_receipt_quote_recovery(
    transfers: list[dict[str, str]],
    *,
    subject: str,
    token: str,
    quote: str,
) -> bool:
    by_receipt: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in transfers:
        by_receipt[row["receipt"]].append(row)
    for rows in by_receipt.values():
        token_legs = [
            row
            for row in rows
            if row["asset"] == token and row["from"] == subject
        ]
        quote_legs = [
            row
            for row in rows
            if row["asset"] == quote and row["to"] == subject
        ]
        if any(
            token_leg["to"] == quote_leg["from"]
            for token_leg in token_legs
            for quote_leg in quote_legs
        ):
            return True
    return False


_REAL_SOCKET = socket.socket
_REAL_CREATE_CONNECTION = socket.create_connection


def _blocked_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("wash-volume fixture test attempted network access")


def setUpModule() -> None:
    socket.socket = _blocked_network  # type: ignore[assignment]
    socket.create_connection = _blocked_network


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[assignment]
    socket.create_connection = _REAL_CREATE_CONNECTION


class WashVolumeFixtureTests(unittest.TestCase):
    def test_policy_keeps_fixtures_out_of_runtime_and_calibration(self) -> None:
        self.assertEqual(
            FIXTURE_POLICY,
            {
                "synthetic": True,
                "runtime_effect": "none",
                "alert_policy": "report_only",
                "calibration_count_eligible": False,
            },
        )

    def test_high_gross_low_net_positive_and_one_way_negative(self) -> None:
        positive = gross_to_terminal_net_ratio(
            GROSS_NET_FIXTURES["high_churn_low_net"], "TOKEN"
        )
        negative = gross_to_terminal_net_ratio(
            GROSS_NET_FIXTURES["one_way_transfer"], "TOKEN"
        )
        self.assertEqual(positive, Decimal(199))
        self.assertEqual(negative, Decimal(1))
        self.assertGreater(positive, negative)

    def test_round_trip_positive_and_open_path_negative(self) -> None:
        self.assertTrue(has_address_round_trip(ROUND_TRIP_FIXTURES["closed_loop"], "TOKEN"))
        self.assertFalse(has_address_round_trip(ROUND_TRIP_FIXTURES["open_path"], "TOKEN"))

    def test_same_receipt_quote_recovery_positive(self) -> None:
        self.assertTrue(
            same_receipt_quote_recovery(
                QUOTE_RECOVERY_FIXTURES["same_receipt"],
                subject="A",
                token="TOKEN",
                quote="QUOTE",
            )
        )

    def test_cross_receipt_and_wrong_recipient_are_negative(self) -> None:
        for name in ("different_receipts", "wrong_recipient"):
            with self.subTest(name=name):
                self.assertFalse(
                    same_receipt_quote_recovery(
                        QUOTE_RECOVERY_FIXTURES[name],
                        subject="A",
                        token="TOKEN",
                        quote="QUOTE",
                    )
                )


if __name__ == "__main__":
    unittest.main()
