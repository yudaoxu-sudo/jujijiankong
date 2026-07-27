#!/usr/bin/env python3
"""Standalone offline recomputation tests for the CEX micro-gas calibration
corpus identity gate.

Contract under test (input/cex_micro_gas_calibration_corpus_2026-07-24.json):
  * every counted independence key and observation key is globally unique;
  * the two Bitget 6 positive branches share one independence key and
    therefore merge into exactly one positive root;
  * blocked, correlated, observation-only, and synthetic rows never enter
    counted_units;
  * current counts are positive roots 1/3, positive tokens 1/2, and
    complete negative controls 3/3, so the runtime-change gate stays closed.

The corpus is a frozen dated evidence artifact: every expectation below is
pinned so that any accidental edit to the file fails this suite.  The tests
read only the corpus file, never import runtime code, and block socket use.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "input" / "cex_micro_gas_calibration_corpus_2026-07-24.json"

CORPUS_SHA256 = "f23049f0b55f57dc9b3820d784f67e550854c89057b2daee0755b933b844409d"

EXPECTED_SCHEMA = "cex_micro_gas_calibration_corpus.v1"
EXPECTED_CASE_ID = "CEX_MICRO_GAS_CALIBRATION_CORPUS_2026_07_24"
EXPECTED_GENERATED_AT = "2026-07-24T09:20:00Z"
EXPECTED_CHAIN_ID = 56

INDEPENDENCE_KEY_FIELDS = (
    "chain_id",
    "token_contract",
    "root_operator",
    "exchange_entity",
    "event_window_start_utc",
    "event_window_end_utc",
)
OBSERVATION_KEY_FIELDS = (
    "chain_id",
    "native_tx_hash",
    "token_or_execution_tx_hash",
    "token_log_index",
)
EXPECTED_RULES = (
    "Every counted unit must bind to one tracked source record.",
    "Positive branches sharing one independence key count as one positive root.",
    "Every counted independence key and observation key must be unique.",
    "Blocked, observation-only, correlated, and synthetic rows do not enter counted_units.",
    "Token and address identities are lowercase canonical chain-56 addresses.",
    "This corpus is an offline evidence gate and cannot change runtime actions, alerts, or thresholds.",
)
EXCLUSION_RULE = EXPECTED_RULES[3]

ALLOWED_OUTCOMES = frozenset({"complete_positive_root", "complete_independent_negative"})
EXCLUDED_ROW_MARKERS = ("blocked", "correlated", "observation_only", "synthetic")

EXPECTED_REQUIREMENTS = {
    "independent_complete_positive_roots": 3,
    "distinct_complete_positive_tokens": 2,
    "independent_complete_negative_controls": 3,
}
EXPECTED_COUNTS = {
    "independent_complete_positive_roots": 1,
    "distinct_complete_positive_tokens": 1,
    "independent_complete_negative_controls": 3,
    "positive_branch_observations": 2,
}
EXPECTED_DECISION = (
    "identity_gate_complete_wait_for_two_positive_roots_and_one_additional_token"
)

BITGET_UNIT_ID = "positive:ake_usdt_bitget6_micro_gas_2026_07_10"
BITGET_IDENTITY_KEY = (
    56,
    "0x55d398326f99059ff775485246999027b3197955",
    "0xb8210c25df20921538ea35729badc3e0a63520f1",
    "Bitget",
    "2026-07-10T05:28:38+00:00",
    "2026-07-17T10:24:27+00:00",
)

EXPECTED_UNIT_IDS = (
    BITGET_UNIT_ID,
    "negative:bybit_funded_771c_noncustodial_negative",
    "negative:gate_funded_ad7d_noncustodial_negative",
    "negative:non_cex_00005_after_ake_ingress",
)
EXPECTED_SOURCE_BINDINGS = {
    BITGET_UNIT_ID: (
        "input/cex_exact_address_micro_gas_calibration_2026-07-22.json",
        "corpus.real_independent_complete_cases",
        "ake_usdt_bitget6_micro_gas_2026_07_10",
    ),
    "negative:bybit_funded_771c_noncustodial_negative": (
        "input/cex_exact_address_micro_gas_calibration_expansion_2026-07-22.json",
        "candidate_results",
        "bybit_funded_771c_noncustodial_negative",
    ),
    "negative:gate_funded_ad7d_noncustodial_negative": (
        "input/cex_exact_address_micro_gas_calibration_expansion_2026-07-22.json",
        "candidate_results",
        "gate_funded_ad7d_noncustodial_negative",
    ),
    "negative:non_cex_00005_after_ake_ingress": (
        "input/cex_micro_gas_low_value_negative_calibration_2026-07-22.json",
        "candidates",
        "non_cex_00005_after_ake_ingress",
    ),
}
EXPECTED_OBSERVATIONS = {
    BITGET_UNIT_ID: (
        (
            "0x460483c798c269400dada8f9cdfed8552f51af23bca450498598e8ccd371b641",
            "0xd72e692ffaaff0a06c026eab5a5dd19ec701ab04b1634991c6c9a2d7ebbd2cea",
            121,
        ),
        (
            "0xa614d7f68b53f3d27fdcdc4c533c52b7111710aa9fd2e89203f2130e5b471439",
            "0xdbdba0fbdff65075d06e5562e2618b9a0b1134c5a426d43758c72ba59f2c0518",
            378,
        ),
    ),
    "negative:bybit_funded_771c_noncustodial_negative": (
        (
            "0x15d13573b71db262f019408add4b1f832897f0b71613713a0413166c1e8d7e11",
            "0xcf9fca77dce03f7c586e180c09f714dc44f041de92313a1617b21a5b37291bf5",
            150,
        ),
    ),
    "negative:gate_funded_ad7d_noncustodial_negative": (
        (
            "0x051a92f204a70b188f4c2841b6a99176d2b6e61c3b62af921290e0d1b5ee779a",
            "0x9ea53eba76e8cf7dc47838f3e3d66c60edf57ff5f2463a1cf65ef461655a2515",
            378,
        ),
    ),
    "negative:non_cex_00005_after_ake_ingress": (
        (
            "0x5aeaf516cfb61a70c97ad1d4c7fd0944769486150968e119c983002d196f1642",
            "0xf5c8332a3ec0e7d0db05df8b8c238987530b5cc4841d3163a596174c00e41908",
            187,
        ),
    ),
}

ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
TX_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")

_saved_socket = None


def setUpModule() -> None:
    """Fail fast if anything in this suite tries to open a network socket."""
    global _saved_socket

    def _blocked_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden in this offline test")

    _saved_socket = socket.socket
    socket.socket = _blocked_socket  # type: ignore[misc,assignment]


def tearDownModule() -> None:
    socket.socket = _saved_socket  # type: ignore[misc]


def _independence_key(unit: dict) -> tuple:
    return tuple(unit["identity"][field] for field in INDEPENDENCE_KEY_FIELDS)


def _observation_keys(unit: dict) -> list[tuple]:
    return [
        (
            unit["identity"]["chain_id"],
            observation["native_tx_hash"],
            observation["token_or_execution_tx_hash"],
            observation["token_log_index"],
        )
        for observation in unit["observations"]
    ]


class MicroGasIdentityGateTests(unittest.TestCase):
    raw: bytes
    doc: dict
    units: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = CORPUS_PATH.read_bytes()
        cls.doc = json.loads(cls.raw.decode("utf-8"))
        cls.units = cls.doc["counted_units"]

    def test_corpus_bytes_are_untouched(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.raw).hexdigest(),
            CORPUS_SHA256,
            "corpus file content changed; the frozen 2026-07-24 evidence "
            "snapshot must not be edited in place",
        )

    def test_schema_scope_and_identity_model_are_pinned(self) -> None:
        self.assertEqual(self.doc["schema"], EXPECTED_SCHEMA)
        self.assertEqual(self.doc["case_id"], EXPECTED_CASE_ID)
        self.assertEqual(self.doc["generated_at_utc"], EXPECTED_GENERATED_AT)
        self.assertEqual(
            self.doc["scope"],
            {
                "chain_id": EXPECTED_CHAIN_ID,
                "mode": "offline_identity_gate",
                "runtime_changed": False,
                "notifications_sent": False,
                "transactions_signed_or_broadcast": False,
            },
        )
        model = self.doc["identity_model"]
        self.assertEqual(tuple(model["independence_key_fields"]), INDEPENDENCE_KEY_FIELDS)
        self.assertEqual(tuple(model["observation_key_fields"]), OBSERVATION_KEY_FIELDS)
        self.assertEqual(tuple(model["rules"]), EXPECTED_RULES)
        self.assertEqual(
            self.doc["minimum_runtime_change_requirements"], EXPECTED_REQUIREMENTS
        )

    def test_counted_units_and_observations_match_pinned_evidence(self) -> None:
        self.assertEqual(tuple(unit["unit_id"] for unit in self.units), EXPECTED_UNIT_IDS)
        for unit in self.units:
            self.assertEqual(
                set(unit),
                {
                    "unit_id",
                    "outcome",
                    "source_path",
                    "source_bucket",
                    "source_record_id",
                    "identity",
                    "observations",
                },
                f"unexpected fields on {unit['unit_id']}",
            )
            self.assertEqual(set(unit["identity"]), set(INDEPENDENCE_KEY_FIELDS))
            self.assertEqual(
                (unit["source_path"], unit["source_bucket"], unit["source_record_id"]),
                EXPECTED_SOURCE_BINDINGS[unit["unit_id"]],
                f"source binding changed for {unit['unit_id']}",
            )
            self.assertTrue(unit["source_path"].startswith("input/"))
            observed = tuple(
                (
                    observation["native_tx_hash"],
                    observation["token_or_execution_tx_hash"],
                    observation["token_log_index"],
                )
                for observation in unit["observations"]
            )
            self.assertEqual(
                observed,
                EXPECTED_OBSERVATIONS[unit["unit_id"]],
                f"observations changed for {unit['unit_id']}",
            )
            for observation in unit["observations"]:
                self.assertEqual(
                    set(observation), set(OBSERVATION_KEY_FIELDS) - {"chain_id"}
                )

    def test_identity_and_observation_keys_are_globally_unique(self) -> None:
        independence_keys = [_independence_key(unit) for unit in self.units]
        self.assertEqual(len(independence_keys), 4)
        self.assertEqual(
            len(set(independence_keys)),
            len(independence_keys),
            "counted units must not share an independence key",
        )
        observation_keys = [
            key for unit in self.units for key in _observation_keys(unit)
        ]
        self.assertEqual(len(observation_keys), 5)
        self.assertEqual(
            len(set(observation_keys)),
            len(observation_keys),
            "counted observations must not share an observation key",
        )

    def test_bitget_branches_merge_into_one_positive_root(self) -> None:
        rows = [
            (_independence_key(unit), key, unit)
            for unit in self.units
            for key in _observation_keys(unit)
        ]
        positive_roots: dict[tuple, list[tuple]] = {}
        for independence_key, observation_key, unit in rows:
            if unit["outcome"] == "complete_positive_root":
                positive_roots.setdefault(independence_key, []).append(observation_key)
        self.assertEqual(
            len(positive_roots),
            1,
            "positive branches must merge into exactly one independence root",
        )
        [(root_key, branches)] = positive_roots.items()
        self.assertEqual(root_key, BITGET_IDENTITY_KEY)
        self.assertEqual(len(branches), 2, "the Bitget root must carry two branches")
        first, second = branches
        self.assertNotEqual(first[1], second[1], "branch native txs must differ")
        self.assertNotEqual(first[2], second[2], "branch token txs must differ")

    def test_excluded_row_classes_are_absent_from_counted_units(self) -> None:
        self.assertIn(EXCLUSION_RULE, self.doc["identity_model"]["rules"])
        outcomes = {unit["outcome"] for unit in self.units}
        self.assertLessEqual(
            outcomes,
            ALLOWED_OUTCOMES,
            "counted_units may only hold complete positive roots and "
            "complete independent negatives",
        )

        def _walk_strings(node: object):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from _walk_strings(value)
            elif isinstance(node, list):
                for value in node:
                    yield from _walk_strings(value)
            elif isinstance(node, str):
                yield node

        for text in _walk_strings(self.units):
            normalized = text.lower().replace("-", "_")
            for marker in EXCLUDED_ROW_MARKERS:
                self.assertNotIn(
                    marker,
                    normalized,
                    f"{marker} row leaked into counted_units via {text!r}",
                )

    def test_counts_match_offline_recomputation_and_gate_ratios(self) -> None:
        positive_units = [
            unit for unit in self.units if unit["outcome"] == "complete_positive_root"
        ]
        negative_units = [
            unit
            for unit in self.units
            if unit["outcome"] == "complete_independent_negative"
        ]
        recomputed = {
            "independent_complete_positive_roots": len(
                {_independence_key(unit) for unit in positive_units}
            ),
            "distinct_complete_positive_tokens": len(
                {unit["identity"]["token_contract"] for unit in positive_units}
            ),
            "independent_complete_negative_controls": len(
                {_independence_key(unit) for unit in negative_units}
            ),
            "positive_branch_observations": sum(
                len(unit["observations"]) for unit in positive_units
            ),
        }
        self.assertEqual(recomputed, EXPECTED_COUNTS)
        self.assertEqual(
            self.doc["counts"],
            recomputed,
            "stored counts diverge from the offline recomputation",
        )

        requirements = self.doc["minimum_runtime_change_requirements"]
        roots = recomputed["independent_complete_positive_roots"]
        tokens = recomputed["distinct_complete_positive_tokens"]
        negatives = recomputed["independent_complete_negative_controls"]
        self.assertEqual(
            (roots, requirements["independent_complete_positive_roots"]), (1, 3)
        )
        self.assertEqual(
            (tokens, requirements["distinct_complete_positive_tokens"]), (1, 2)
        )
        self.assertEqual(
            (negatives, requirements["independent_complete_negative_controls"]), (3, 3)
        )
        requirements_met = (
            roots >= requirements["independent_complete_positive_roots"]
            and tokens >= requirements["distinct_complete_positive_tokens"]
            and negatives >= requirements["independent_complete_negative_controls"]
        )
        self.assertFalse(requirements_met)
        gate = self.doc["gate"]
        self.assertIs(gate["runtime_change_requirements_met"], requirements_met)
        self.assertIs(gate["identity_schema_complete"], True)
        self.assertIs(gate["source_bindings_complete"], True)
        self.assertEqual(gate["runtime_effect"], "none")
        self.assertEqual(gate["decision"], EXPECTED_DECISION)

    def test_identities_use_canonical_formats_and_ordered_windows(self) -> None:
        for unit in self.units:
            identity = unit["identity"]
            self.assertEqual(identity["chain_id"], EXPECTED_CHAIN_ID)
            self.assertRegex(identity["token_contract"], ADDRESS_RE)
            self.assertRegex(identity["root_operator"], ADDRESS_RE)
            self.assertTrue(identity["exchange_entity"])
            start = datetime.fromisoformat(identity["event_window_start_utc"])
            end = datetime.fromisoformat(identity["event_window_end_utc"])
            self.assertIsNotNone(start.tzinfo)
            self.assertIsNotNone(end.tzinfo)
            self.assertLess(start, end, f"window inverted for {unit['unit_id']}")
            for observation in unit["observations"]:
                self.assertRegex(observation["native_tx_hash"], TX_HASH_RE)
                self.assertRegex(observation["token_or_execution_tx_hash"], TX_HASH_RE)
                log_index = observation["token_log_index"]
                self.assertIsInstance(log_index, int)
                self.assertNotIsInstance(log_index, bool)
                self.assertGreaterEqual(log_index, 0)


if __name__ == "__main__":
    unittest.main()
