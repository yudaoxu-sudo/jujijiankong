#!/usr/bin/env python3
"""Offline synthetic boundary and negative-sample tests for CEX micro-gas calibration.

Security queue task 3, independent part. Every input is synthetic and declared so in
scripts/fixtures/micro_gas_boundary_synthetic_fixtures.json; nothing here is a chain
observation and nothing here may ever enter calibration counted_units.

Hard offline guarantees enforced by this file:
- SNIPER_OFFLINE=1 is set before any repo import, so sniper_engine.env.load_local_env
  never opens .env.local (no credential reads).
- socket.connect / socket.create_connection / urllib.request.urlopen are replaced with
  tripwires that raise, so any network or RPC attempt fails the run loudly.
- input/cex_micro_gas_calibration_corpus_2026-07-24.json is opened read-only and its
  sha256 is asserted unchanged after the run.
- No runtime code, env thresholds, alert paths, or history files are touched; the
  functions under test are report-only collectors exercised against in-memory fixtures.

Covered boundaries:
- 0.001 BNB micro-gas threshold: at-threshold, above-by-one-wei, zero, one wei.
- Timing negative sample: native gas credited 28 seconds after the token egress.
- Partial coverage (native scan RPC error, token window incomplete, expired budget)
  always fails closed and never yields a unique pairing.
- Detector label ambiguity (multiple candidates, exchange mismatch) and expiry
  (stale provenance, declassified label).
- Missing native receipt fails closed.
- Synthetic samples never enter calibration positive/negative root counts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import time
import unittest
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

# Must happen before any sniper_engine import: keeps load_local_env() from reading
# .env.local credentials when sniper_engine.rpc is imported at module load.
os.environ["SNIPER_OFFLINE"] = "1"

WATCH_SCRIPT = ROOT / "scripts" / "alpha_intraday_flow_watch.py"
FIXTURES_PATH = ROOT / "scripts" / "fixtures" / "micro_gas_boundary_synthetic_fixtures.json"
CORPUS_PATH = ROOT / "input" / "cex_micro_gas_calibration_corpus_2026-07-24.json"

FIXTURES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
ADDR = FIXTURES["synthetic_addresses"]
HASHES = FIXTURES["synthetic_hashes"]
GEOMETRY = FIXTURES["synthetic_geometry"]

CHAIN = FIXTURES["chain"]
TOKEN = ADDR["token_contract"]
QUOTE = ADDR["quote_contract"]
RECIPIENT = ADDR["recipient"]
HOT_A = ADDR["hot_wallet_synthex_a"]
HOT_B = ADDR["hot_wallet_synthex_b"]
UNLABELED = ADDR["unlabeled_source"]

GAS_TX = HASHES["gas_tx_at_threshold"]
GAS_ABOVE_TX = HASHES["gas_tx_above_threshold_by_one"]
GAS_ZERO_TX = HASHES["gas_tx_zero_value"]
GAS_ONE_WEI_TX = HASHES["gas_tx_one_wei"]
GAS_UNLABELED_TX = HASHES["gas_tx_unlabeled_source"]
GAS_SAME_BLOCK_TX = HASHES["gas_tx_same_block"]
GAS_SECOND_TX = HASHES["gas_tx_second_candidate"]
TOKEN_TX = HASHES["token_egress_tx"]
GAS_BLOCK_HASH = HASHES["gas_block_hash"]
TOKEN_BLOCK_HASH = HASHES["token_block_hash"]

GAS_BLOCK = int(GEOMETRY["gas_block"])
TOKEN_BLOCK = int(GEOMETRY["token_block"])
GAS_TX_INDEX = int(GEOMETRY["gas_transaction_index"])
TOKEN_TX_INDEX = int(GEOMETRY["token_transaction_index"])
TOKEN_LOG_INDEX = int(GEOMETRY["token_log_index"])
TOKEN_AMOUNT_RAW = int(GEOMETRY["token_amount_raw"])

CONTROL_GAS_UTC = FIXTURES["timing_negative"]["control_gas_arrival_utc"]
TOKEN_EGRESS_UTC = FIXTURES["timing_negative"]["token_egress_utc"]
LATE_GAS_UTC = FIXTURES["timing_negative"]["late_gas_arrival_utc"]
LATE_BY_SECONDS = int(FIXTURES["timing_negative"]["gas_arrival_after_token_egress_seconds"])

MODULE = None
CORPUS_SHA_BEFORE = None


class NetworkAccessAttempted(AssertionError):
    pass


def _forbid_network(*args, **kwargs):
    raise NetworkAccessAttempted("synthetic offline test attempted network access")


_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_CREATE_CONNECTION = socket.create_connection
_REAL_URLOPEN = urllib.request.urlopen


def setUpModule():
    global MODULE, CORPUS_SHA_BEFORE
    socket.socket.connect = _forbid_network
    socket.create_connection = _forbid_network
    urllib.request.urlopen = _forbid_network
    CORPUS_SHA_BEFORE = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(
        "alpha_intraday_flow_watch_micro_gas_boundaries", WATCH_SCRIPT
    )
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)


def tearDownModule():
    socket.socket.connect = _REAL_SOCKET_CONNECT
    socket.create_connection = _REAL_CREATE_CONNECTION
    urllib.request.urlopen = _REAL_URLOPEN
    if hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest() != CORPUS_SHA_BEFORE:
        raise AssertionError("calibration corpus bytes changed during offline test run")


# Reference implementation of the corpus identity gate used only by these tests.
# Mirrors input/cex_micro_gas_calibration_corpus_2026-07-24.json identity_model.rules:
# blocked, observation-only, correlated, and synthetic rows do not enter counted_units,
# and every counted unit must bind to one tracked source record under input/.
COUNTABLE_OUTCOMES = {"complete_positive_root", "complete_independent_negative"}
EXCLUDED_STATUSES = {"blocked", "observation_only", "correlated"}


def countable_calibration_unit(row) -> bool:
    if not isinstance(row, dict):
        return False
    unit_id = str(row.get("unit_id") or "")
    source_path = str(row.get("source_path") or "")
    if row.get("synthetic") is True:
        return False
    if unit_id.startswith("synthetic:") or "synthetic" in unit_id:
        return False
    if "synthetic" in source_path or not source_path.startswith("input/"):
        return False
    if not row.get("source_bucket") or not row.get("source_record_id"):
        return False
    if str(row.get("status") or "") in EXCLUDED_STATUSES:
        return False
    if row.get("outcome") not in COUNTABLE_OUTCOMES:
        return False
    if not isinstance(row.get("identity"), dict) or not row.get("observations"):
        return False
    return True


def independence_key(row, fields) -> tuple:
    return tuple(str(row["identity"].get(field)) for field in fields)


def observation_keys(row, fields) -> list[tuple]:
    keys = []
    for observation in row.get("observations", []):
        merged = {"chain_id": row["identity"].get("chain_id"), **observation}
        keys.append(tuple(str(merged.get(field)) for field in fields))
    return keys


def recount(rows, independence_fields) -> dict:
    positives = [row for row in rows if row.get("outcome") == "complete_positive_root"]
    negatives = [row for row in rows if row.get("outcome") == "complete_independent_negative"]
    return {
        "independent_complete_positive_roots": len(
            {independence_key(row, independence_fields) for row in positives}
        ),
        "distinct_complete_positive_tokens": len(
            {str(row["identity"].get("token_contract")) for row in positives}
        ),
        "independent_complete_negative_controls": len(negatives),
        "positive_branch_observations": sum(len(row.get("observations", [])) for row in positives),
    }


class MicroGasBoundaryHarness(unittest.TestCase):
    """Shared in-memory fixture harness; every collaborator with I/O is replaced."""

    maxDiff = None
    ENV_KEYS = (
        "ALPHA_INTRADAY_GAS_LOOKBACK_BLOCKS",
        "ALPHA_INTRADAY_GAS_PRIMING_MIN_BNB",
        "ALPHA_INTRADAY_GAS_PRIMING_MAX_HITS",
        "ALPHA_INTRADAY_RPC_TIMEOUT",
    )

    def setUp(self):
        self.module = MODULE
        saved_env = {key: os.environ.get(key) for key in self.ENV_KEYS}
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)

        def restore_env():
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore_env)

        self.labels = {
            HOT_A: {
                "address": HOT_A,
                "class": "cex_hot_wallet",
                "exchange": "SynthExA",
                "label": "Synthetic Hot Wallet A",
                "confidence": "high",
                "evidence": "synthetic offline fixture label",
            },
            HOT_B: {
                "address": HOT_B,
                "class": "cex_hot_wallet",
                "exchange": "SynthExB",
                "label": "Synthetic Hot Wallet B",
                "confidence": "high",
                "evidence": "synthetic offline fixture label",
            },
        }
        self.blocks = {GAS_BLOCK: [self.gas_tx()]}
        self.error_blocks = set()
        self.timestamps = {
            (GAS_BLOCK, GAS_BLOCK_HASH): CONTROL_GAS_UTC,
            (TOKEN_BLOCK, TOKEN_BLOCK_HASH): TOKEN_EGRESS_UTC,
        }
        self.receipts = {
            GAS_TX: self.gas_receipt(),
            TOKEN_TX: self.token_receipt(),
        }

        module = self.module
        patches = (
            (module, "report_only_block_transactions", self._fixture_block_transactions),
            (module, "block_timestamp_utc", self._fixture_block_timestamp),
            (module.opening, "quick_rpc_call", self._fixture_quick_rpc),
            (module.opening, "global_address_label", self._fixture_label),
            (module.opening, "global_address_labels", self._fixture_labels),
            (module.opening, "has_contract_code", lambda chain, address: False),
            (module.opening, "rpc_urls", lambda chain: ["offline://synthetic-fixture"]),
        )
        for target, name, replacement in patches:
            original = getattr(target, name)
            setattr(target, name, replacement)
            self.addCleanup(setattr, target, name, original)
        module.BLOCK_TX_CACHE.clear()
        module.BLOCK_TIME_CACHE.clear()

    def _fixture_block_transactions(self, chain, block_number, timeout):
        self.assertEqual(chain, CHAIN)
        if block_number in self.error_blocks:
            raise ValueError("partial_rpc_error: synthetic fixture rpc failure")
        return [dict(tx) for tx in self.blocks.get(block_number, [])]

    def _fixture_block_timestamp(self, chain, block_number, block_hash, timeout):
        return self.timestamps.get((block_number, str(block_hash or "").lower()))

    def _fixture_quick_rpc(self, chain, method, params, timeout):
        if method == "eth_getTransactionReceipt" and params and params[0] in self.receipts:
            value = self.receipts[params[0]]
            if isinstance(value, Exception):
                raise value
            return json.loads(json.dumps(value)) if isinstance(value, dict) else value
        raise NetworkAccessAttempted(f"unexpected rpc in offline fixture: {method} {params!r}")

    def _fixture_label(self, chain, address):
        row = self.labels.get(self.module.norm(address))
        return dict(row) if row else None

    def _fixture_labels(self, chain):
        return {address: dict(row) for address, row in self.labels.items()}

    def gas_tx(self, *, value_wei=None, tx_hash=GAS_TX, index=GAS_TX_INDEX, source=HOT_A,
               block=GAS_BLOCK, block_hash=GAS_BLOCK_HASH):
        if value_wei is None:
            value_wei = int(FIXTURES["threshold_boundary"]["wei_at_threshold"])
        return {
            "from": source,
            "to": RECIPIENT,
            "value": hex(int(value_wei)),
            "hash": tx_hash,
            "blockNumber": hex(block),
            "blockHash": block_hash,
            "transactionIndex": hex(index),
        }

    def gas_receipt(self, *, tx_hash=GAS_TX, index=GAS_TX_INDEX, source=HOT_A):
        return {
            "transactionHash": tx_hash,
            "blockNumber": hex(GAS_BLOCK),
            "blockHash": GAS_BLOCK_HASH,
            "transactionIndex": hex(index),
            "status": "0x1",
            "from": source,
            "to": RECIPIENT,
        }

    def token_receipt(self, *, destination=HOT_A):
        return {
            "transactionHash": TOKEN_TX,
            "blockNumber": hex(TOKEN_BLOCK),
            "blockHash": TOKEN_BLOCK_HASH,
            "transactionIndex": hex(TOKEN_TX_INDEX),
            "status": "0x1",
            "logs": [
                {
                    "address": TOKEN,
                    "blockNumber": hex(TOKEN_BLOCK),
                    "transactionHash": TOKEN_TX,
                    "logIndex": hex(TOKEN_LOG_INDEX),
                    "topics": [
                        self.module.opening.TRANSFER_TOPIC,
                        "0x" + "0" * 24 + RECIPIENT[2:],
                        "0x" + "0" * 24 + destination[2:],
                    ],
                    "data": hex(TOKEN_AMOUNT_RAW),
                }
            ],
        }

    def event(self):
        return {
            "symbol": "SYNTH",
            "chain": CHAIN,
            "token": {"address": TOKEN, "symbol": "SYNTH", "decimals": 18},
            "quote": {"address": QUOTE, "symbol": "USDT", "decimals": 18},
            "market_context": {},
            "known_contracts": [],
            "cex_deposit_addresses": [],
            "cex_addresses": [],
        }

    def token_transfer(self, *, destination=HOT_A):
        return {
            "token": TOKEN,
            "from": RECIPIENT,
            "to": destination,
            "amount_raw": str(TOKEN_AMOUNT_RAW),
            "decimals": 18,
            "amount": Decimal(TOKEN_AMOUNT_RAW) / (Decimal(10) ** 18),
            "block": TOKEN_BLOCK,
            "block_hash": TOKEN_BLOCK_HASH,
            "transaction_index": TOKEN_TX_INDEX,
            "log_index": TOKEN_LOG_INDEX,
            "tx": TOKEN_TX,
        }

    def complete_transfer_coverage(self):
        return {
            "state": "requested_window_complete",
            "complete": True,
            "requested_from_block": 100,
            "requested_to_block": 200,
            "covered_through_block": 200,
            "returned_log_count": 1,
            "max_logs": 12000,
        }

    def collect(self, *, transfer=None, coverage=None):
        bundle = self.module.collect_report_only_cex_micro_gas_samples(
            self.event(),
            [transfer if transfer is not None else self.token_transfer()],
            coverage if coverage is not None else self.complete_transfer_coverage(),
            {},
        )
        self.assertEqual(bundle["schema"], "report_only_cex_micro_gas_samples.v1")
        self.assertEqual(bundle["alert_policy"], "report_only")
        self.assertEqual(bundle["runtime_effect"], "none")
        self.assertEqual(bundle["action_guard"], "no_runtime_action_mutation")
        return bundle

    def sole_candidate(self, bundle):
        self.assertEqual(bundle["candidate_count"], 1, bundle)
        candidate = bundle["candidates"][0]
        self.assertEqual(candidate["status"], "blocked", candidate)
        self.assertEqual(candidate["classification"], "candidate", candidate)
        self.assertEqual(candidate["alert_policy"], "report_only", candidate)
        self.assertEqual(candidate["runtime_effect"], "none", candidate)
        self.assertEqual(candidate["action_guard"], "no_runtime_action_mutation", candidate)
        self.assertIs(candidate["independence"]["independence_eligible"], False, candidate)
        return candidate

    def scan_rows(self, *, deadline=None):
        return self.module.native_micro_gas_rows(
            self.event(),
            RECIPIENT,
            TOKEN_BLOCK,
            TOKEN_TX_INDEX,
            time.monotonic() + 5 if deadline is None else deadline,
        )


class GoldenControlTests(MicroGasBoundaryHarness):
    """The control fixture must be perfect so every negative test isolates one axis."""

    def test_control_candidate_is_unique_but_still_blocked_and_count_ineligible(self):
        bundle = self.collect()
        candidate = self.sole_candidate(bundle)
        self.assertEqual(candidate["native_gas"]["tx"], GAS_TX, candidate)
        self.assertEqual(
            candidate["native_gas"]["value_wei"],
            FIXTURES["threshold_boundary"]["wei_at_threshold"],
            candidate,
        )
        self.assertEqual(candidate["native_gas"]["receipt_status"], 1, candidate)
        self.assertEqual(candidate["token_ingress"]["tx"], TOKEN_TX, candidate)
        self.assertIs(candidate["token_ingress"]["amount_equation_valid"], True, candidate)
        self.assertEqual(candidate["pairing"]["gas_before_token_seconds"], 3, candidate)
        self.assertIs(candidate["pairing"]["strict_order"], True, candidate)
        self.assertIs(candidate["pairing"]["exchange_entity_match"], True, candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], True, candidate)
        self.assertEqual(candidate["pairing"]["ambiguity_reasons"], [], candidate)
        self.assertIs(candidate["coverage"]["coverage_complete"], True, candidate)
        self.assertEqual(
            candidate["unresolved_fields"],
            ["independent_positive_root_review", "root_operator_linkage"],
            candidate,
        )
        self.assertEqual(
            candidate["independence"]["event_window_start_utc"], CONTROL_GAS_UTC, candidate
        )
        self.assertEqual(
            candidate["independence"]["event_window_end_utc"], TOKEN_EGRESS_UTC, candidate
        )
        self.assertTrue(candidate["candidate_id"].startswith("cex_micro_gas_"), candidate)
        repeat = self.collect()
        self.assertEqual(repeat["candidates"][0]["candidate_id"], candidate["candidate_id"])


class ThresholdBoundaryTests(MicroGasBoundaryHarness):
    """0.001 BNB default threshold: 0 < amount <= 0.001, exact wei arithmetic."""

    def test_default_threshold_env_is_untouched(self):
        self.assertIsNone(os.environ.get("ALPHA_INTRADAY_GAS_PRIMING_MIN_BNB"))

    def test_boundary_values_at_above_zero_and_one_wei(self):
        boundary = FIXTURES["threshold_boundary"]
        self.blocks[GAS_BLOCK] = [
            self.gas_tx(value_wei=int(boundary["wei_at_threshold"])),
            self.gas_tx(value_wei=int(boundary["wei_above_threshold_by_one"]), tx_hash=GAS_ABOVE_TX, index=0),
            self.gas_tx(value_wei=int(boundary["wei_zero"]), tx_hash=GAS_ZERO_TX, index=1),
            self.gas_tx(value_wei=int(boundary["wei_one"]), tx_hash=GAS_ONE_WEI_TX, index=2),
            self.gas_tx(value_wei=10**14, tx_hash=GAS_UNLABELED_TX, index=5, source=UNLABELED),
        ]
        rows, coverage = self.scan_rows()
        self.assertEqual(
            [(row["tx"], row["value_wei"]) for row in rows],
            [(GAS_TX, boundary["wei_at_threshold"]), (GAS_ONE_WEI_TX, boundary["wei_one"])],
            rows,
        )
        self.assertEqual(Decimal(rows[0]["value_native"]), Decimal(boundary["default_min_bnb"]))
        self.assertIs(coverage["complete"], True, coverage)
        self.assertEqual(coverage["state"], "requested_window_complete", coverage)
        self.assertEqual(coverage["requested_from_block"], 0, coverage)
        self.assertEqual(coverage["requested_block_count"], TOKEN_BLOCK + 1, coverage)

    def test_same_block_after_or_equal_gas_is_excluded_but_flagged(self):
        self.blocks[TOKEN_BLOCK] = [
            self.gas_tx(
                tx_hash=GAS_SAME_BLOCK_TX,
                index=TOKEN_TX_INDEX,
                block=TOKEN_BLOCK,
                block_hash=TOKEN_BLOCK_HASH,
            )
        ]
        rows, coverage = self.scan_rows()
        self.assertEqual([row["tx"] for row in rows], [GAS_TX], rows)
        self.assertEqual(coverage["after_or_equal_transaction_count"], 1, coverage)
        candidate = self.sole_candidate(self.collect())
        self.assertIn(
            "same_block_after_or_equal_native_transfer_observed",
            candidate["pairing"]["ambiguity_reasons"],
            candidate,
        )


class TimingNegativeTests(MicroGasBoundaryHarness):
    """Gas credited 28 seconds after the token egress can never pair."""

    def test_gas_arriving_28_seconds_after_token_egress_fails_closed(self):
        self.timestamps[(GAS_BLOCK, GAS_BLOCK_HASH)] = LATE_GAS_UTC
        candidate = self.sole_candidate(self.collect())
        self.assertEqual(
            candidate["pairing"]["gas_before_token_seconds"], -LATE_BY_SECONDS, candidate
        )
        self.assertIs(candidate["pairing"]["strict_order"], True, candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
        self.assertIn("strict_gas_before_token_order", candidate["unresolved_fields"], candidate)
        self.assertIn("unique_gas_to_token_pairing", candidate["unresolved_fields"], candidate)

    def test_control_timestamps_do_not_trip_the_timing_gate(self):
        candidate = self.sole_candidate(self.collect())
        self.assertEqual(candidate["pairing"]["gas_before_token_seconds"], 3, candidate)
        self.assertNotIn("strict_gas_before_token_order", candidate["unresolved_fields"], candidate)

    def test_missing_gas_timestamp_fails_closed(self):
        del self.timestamps[(GAS_BLOCK, GAS_BLOCK_HASH)]
        candidate = self.sole_candidate(self.collect())
        self.assertIsNone(candidate["pairing"]["gas_before_token_seconds"], candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
        self.assertIn("strict_gas_before_token_order", candidate["unresolved_fields"], candidate)


class PartialCoverageFailClosedTests(MicroGasBoundaryHarness):
    """Any incomplete scan window must fail closed, never fabricate completeness."""

    def test_native_scan_rpc_error_marks_candidate_ambiguous(self):
        self.error_blocks.add(GAS_BLOCK - 9)
        rows, coverage = self.scan_rows()
        self.assertEqual([row["tx"] for row in rows], [GAS_TX], rows)
        self.assertEqual(coverage["state"], "partial_rpc_error", coverage)
        self.assertIs(coverage["complete"], False, coverage)
        self.assertEqual(coverage["scan_error"], "rpc_error", coverage)
        self.assertEqual(coverage["completed_block_count"], 10, coverage)
        bundle = self.collect()
        candidate = self.sole_candidate(bundle)
        self.assertIn(
            "native_scan_coverage_incomplete", candidate["pairing"]["ambiguity_reasons"], candidate
        )
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
        self.assertIs(candidate["coverage"]["coverage_complete"], False, candidate)
        self.assertIn("unique_gas_to_token_pairing", candidate["unresolved_fields"], candidate)
        self.assertEqual(
            bundle["window_reviews"][0]["native_scan_coverage"]["scan_error"], "rpc_error", bundle
        )

    def test_incomplete_token_transfer_window_marks_candidate_ambiguous(self):
        coverage = {
            **self.complete_transfer_coverage(),
            "state": "partial_rpc_error",
            "complete": False,
        }
        candidate = self.sole_candidate(self.collect(coverage=coverage))
        self.assertIn(
            "token_transfer_window_coverage_incomplete",
            candidate["pairing"]["ambiguity_reasons"],
            candidate,
        )
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
        self.assertIs(candidate["coverage"]["coverage_complete"], False, candidate)
        self.assertIn("unique_gas_to_token_pairing", candidate["unresolved_fields"], candidate)

    def test_expired_time_budget_returns_no_rows_at_all(self):
        rows, coverage = self.scan_rows(deadline=time.monotonic() - 1)
        self.assertEqual(rows, [])
        self.assertEqual(coverage["state"], "partial_time_budget", coverage)
        self.assertIs(coverage["complete"], False, coverage)
        self.assertEqual(coverage["completed_block_count"], 0, coverage)
        self.assertEqual(coverage["scan_error"], "time_budget_exhausted", coverage)


class DetectorLabelTests(MicroGasBoundaryHarness):
    """Label ambiguity or expiry must block pairing or drop the row entirely."""

    def test_multiple_prior_candidates_are_mutually_ambiguous(self):
        self.blocks[GAS_BLOCK] = [
            self.gas_tx(),
            self.gas_tx(tx_hash=GAS_SECOND_TX, index=2),
        ]
        self.receipts[GAS_SECOND_TX] = self.gas_receipt(tx_hash=GAS_SECOND_TX, index=2)
        bundle = self.collect()
        self.assertEqual(bundle["candidate_count"], 2, bundle)
        for candidate in bundle["candidates"]:
            self.assertEqual(candidate["status"], "blocked", candidate)
            self.assertIn(
                "multiple_prior_micro_gas_candidates",
                candidate["pairing"]["ambiguity_reasons"],
                candidate,
            )
            self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
            self.assertEqual(len(candidate["pairing"]["all_candidate_gas_identities"]), 2, candidate)

    def test_exchange_entity_mismatch_stays_unresolved(self):
        self.receipts[TOKEN_TX] = self.token_receipt(destination=HOT_B)
        candidate = self.sole_candidate(
            self.collect(transfer=self.token_transfer(destination=HOT_B))
        )
        self.assertIs(candidate["pairing"]["exchange_entity_match"], False, candidate)
        self.assertIn("exchange_entity_match", candidate["unresolved_fields"], candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], True, candidate)

    def test_expired_label_provenance_stays_unresolved(self):
        for row in self.labels.values():
            row["confidence"] = None
        candidate = self.sole_candidate(self.collect())
        self.assertIn("cex_source_exact_label_provenance", candidate["unresolved_fields"], candidate)
        self.assertIn(
            "cex_destination_exact_label_provenance", candidate["unresolved_fields"], candidate
        )
        self.assertIsNone(candidate["native_gas"]["source_label"]["confidence"], candidate)

    def test_declassified_source_label_drops_gas_rows(self):
        self.labels.clear()
        rows, coverage = self.scan_rows()
        self.assertEqual(rows, [])
        self.assertIs(coverage["complete"], True, coverage)

    def test_declassified_destination_label_leaves_no_eligible_window(self):
        self.labels.clear()
        bundle = self.collect()
        self.assertEqual(bundle["status"], "bounded_observation_no_candidate", bundle)
        self.assertEqual(bundle["eligible_token_ingress_window_count"], 0, bundle)
        self.assertEqual(bundle["candidate_count"], 0, bundle)


class NativeReceiptMissingTests(MicroGasBoundaryHarness):
    """A native gas receipt that cannot be fetched must fail closed."""

    def test_null_native_receipt_blocks_pairing(self):
        self.receipts[GAS_TX] = None
        candidate = self.sole_candidate(self.collect())
        self.assertIsNone(candidate["native_gas"]["receipt_status"], candidate)
        self.assertIs(candidate["native_gas"]["receipt_identity_match"], False, candidate)
        self.assertIn("native_receipt_success_and_identity", candidate["unresolved_fields"], candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)
        self.assertIn("unique_gas_to_token_pairing", candidate["unresolved_fields"], candidate)

    def test_native_receipt_rpc_failure_blocks_pairing(self):
        self.receipts[GAS_TX] = RuntimeError("synthetic fixture receipt failure")
        candidate = self.sole_candidate(self.collect())
        self.assertIsNone(candidate["native_gas"]["receipt_status"], candidate)
        self.assertIn("native_receipt_success_and_identity", candidate["unresolved_fields"], candidate)
        self.assertIs(candidate["pairing"]["unique_pairing"], False, candidate)


class SyntheticNeverCountedTests(MicroGasBoundaryHarness):
    """Synthetic samples must never enter calibration positive/negative root counts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        cls.independence_fields = cls.corpus["identity_model"]["independence_key_fields"]
        cls.observation_fields = cls.corpus["identity_model"]["observation_key_fields"]
        cls.probe_rows = FIXTURES["corpus_exclusion_probe_rows"]

    def test_corpus_declares_the_synthetic_exclusion_rule(self):
        self.assertEqual(self.corpus["schema"], "cex_micro_gas_calibration_corpus.v1")
        self.assertTrue(
            any("synthetic" in rule for rule in self.corpus["identity_model"]["rules"]),
            self.corpus["identity_model"]["rules"],
        )
        self.assertEqual(self.corpus["gate"]["runtime_effect"], "none")
        self.assertIs(self.corpus["scope"]["runtime_changed"], False)

    def test_corpus_counts_recompute_exactly_from_counted_units(self):
        counted = self.corpus["counted_units"]
        self.assertTrue(all(countable_calibration_unit(row) for row in counted), counted)
        self.assertEqual(recount(counted, self.independence_fields), self.corpus["counts"])
        independence = [independence_key(row, self.independence_fields) for row in counted]
        self.assertEqual(len(independence), len(set(independence)), independence)
        observations = [
            key for row in counted for key in observation_keys(row, self.observation_fields)
        ]
        self.assertEqual(len(observations), len(set(observations)), observations)

    def test_corpus_gate_requirements_flag_is_consistent(self):
        counts = self.corpus["counts"]
        minimums = self.corpus["minimum_runtime_change_requirements"]
        met = (
            counts["independent_complete_positive_roots"]
            >= minimums["independent_complete_positive_roots"]
            and counts["distinct_complete_positive_tokens"]
            >= minimums["distinct_complete_positive_tokens"]
            and counts["independent_complete_negative_controls"]
            >= minimums["independent_complete_negative_controls"]
        )
        self.assertIs(self.corpus["gate"]["runtime_change_requirements_met"], met)
        self.assertIs(met, False)

    def test_every_synthetic_probe_row_is_labeled_and_rejected(self):
        for row in self.probe_rows:
            with self.subTest(unit_id=row["unit_id"]):
                self.assertIs(row["synthetic"], True, row)
                self.assertIs(row["counted_unit_eligible"], False, row)
                self.assertTrue(row["unit_id"].startswith("synthetic:"), row)
                self.assertFalse(countable_calibration_unit(row), row)

    def test_appending_synthetic_rows_never_changes_root_counts(self):
        counted = self.corpus["counted_units"]
        augmented = counted + list(self.probe_rows)
        gated = [row for row in augmented if countable_calibration_unit(row)]
        self.assertEqual(gated, counted)
        self.assertEqual(recount(gated, self.independence_fields), self.corpus["counts"])

    def test_each_exclusion_reason_rejects_independently(self):
        template = json.loads(json.dumps(self.corpus["counted_units"][0]))
        self.assertTrue(countable_calibration_unit(template))
        by_synthetic_flag = {**template, "synthetic": True}
        by_unit_id = {**template, "unit_id": "synthetic:" + template["unit_id"]}
        by_source_path = {
            **template,
            "source_path": "scripts/fixtures/micro_gas_boundary_synthetic_fixtures.json",
        }
        by_blocked_status = {**template, "status": "blocked"}
        by_observation_only = {**template, "status": "observation_only"}
        by_correlated = {**template, "status": "correlated"}
        by_outcome = {**template, "outcome": "candidate"}
        for name, row in (
            ("synthetic_flag", by_synthetic_flag),
            ("unit_id_prefix", by_unit_id),
            ("untracked_source_path", by_source_path),
            ("blocked_status", by_blocked_status),
            ("observation_only_status", by_observation_only),
            ("correlated_status", by_correlated),
            ("non_countable_outcome", by_outcome),
        ):
            with self.subTest(reason=name):
                self.assertFalse(countable_calibration_unit(row), row)

    def test_synthetic_identities_never_collide_with_corpus_observations(self):
        corpus_hashes = {
            value
            for row in self.corpus["counted_units"]
            for observation in row["observations"]
            for value in (observation["native_tx_hash"], observation["token_or_execution_tx_hash"])
        }
        self.assertFalse(set(HASHES.values()) & corpus_hashes)
        corpus_addresses = {
            row["identity"][field]
            for row in self.corpus["counted_units"]
            for field in ("token_contract", "root_operator")
        }
        self.assertFalse(set(ADDR.values()) & corpus_addresses)

    def test_collector_candidates_can_never_become_counted_units(self):
        candidate = self.sole_candidate(self.collect())
        as_unit = {
            "unit_id": "synthetic:collector_candidate",
            "synthetic": True,
            "outcome": candidate["classification"],
            "status": candidate["status"],
            "source_path": "scripts/fixtures/micro_gas_boundary_synthetic_fixtures.json",
            "source_bucket": "collector_output",
            "source_record_id": candidate["candidate_id"],
            "identity": {
                "chain_id": FIXTURES["chain_id"],
                "token_contract": candidate["independence"]["token_contract"],
                "root_operator": candidate["independence"]["root_operator_id"],
                "exchange_entity": candidate["independence"]["exchange_entity"],
                "event_window_start_utc": candidate["independence"]["event_window_start_utc"],
                "event_window_end_utc": candidate["independence"]["event_window_end_utc"],
            },
            "observations": [
                {
                    "native_tx_hash": candidate["native_gas"]["tx"],
                    "token_or_execution_tx_hash": candidate["token_ingress"]["tx"],
                    "token_log_index": candidate["token_ingress"]["log_index"],
                }
            ],
        }
        self.assertFalse(countable_calibration_unit(as_unit), as_unit)
        self.assertEqual(candidate["status"], "blocked", candidate)
        self.assertIs(candidate["independence"]["independence_eligible"], False, candidate)
        counted = self.corpus["counted_units"]
        gated = [row for row in counted + [as_unit] if countable_calibration_unit(row)]
        self.assertEqual(recount(gated, self.independence_fields), self.corpus["counts"])


if __name__ == "__main__":
    unittest.main()
