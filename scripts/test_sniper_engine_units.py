#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with patch("sniper_engine.env.load_local_env"):
    from sniper_engine import rpc
from sniper_engine import env as sniper_env
from sniper_engine.project_registry import merge_facts

RPC_ENV_KEYS = (
    "BSC_RPC_URL",
    "NODEREAL_API_KEY",
    "BSC_RPC_FALLBACK_URLS",
    "RPC_429_BACKOFF_SECONDS",
)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _RawResponse:
    """Response whose 200 body is raw non-JSON bytes (e.g. an HTML block page)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, *args: object) -> bytes:
        return self._body

    def __enter__(self) -> "_RawResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _ReadTimeoutResponse:
    """Response whose body read stalls and times out mid-transfer."""

    def read(self, *args: object) -> bytes:
        raise TimeoutError("timed out")

    def __enter__(self) -> "_ReadTimeoutResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class RpcFailoverTests(unittest.TestCase):
    """rpc_call must keep walking the URL list captured at call start, even when
    a mid-call auth failure shrinks what rpc_urls() would return next time."""

    def setUp(self) -> None:
        self._saved_env = {key: os.environ.get(key) for key in RPC_ENV_KEYS}
        self._saved_urlopen = urllib.request.urlopen
        self._saved_disabled = rpc.DISABLED_NODE_REAL
        for key in RPC_ENV_KEYS:
            os.environ.pop(key, None)
        rpc.DISABLED_NODE_REAL = False

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        urllib.request.urlopen = self._saved_urlopen
        rpc.DISABLED_NODE_REAL = self._saved_disabled

    def test_nodereal_auth_failure_fails_over_to_next_url(self) -> None:
        os.environ["NODEREAL_API_KEY"] = "regression-test-key"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            calls.append(url)
            if "nodereal" in url:
                raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b""))
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x10"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x10")
        self.assertEqual(len(calls), 2, f"expected nodereal then fallback, got {calls}")
        self.assertIn("nodereal", calls[0])
        self.assertNotIn("nodereal", calls[1])
        self.assertTrue(rpc.DISABLED_NODE_REAL)

    def test_custom_auth_failure_does_not_disable_healthy_nodereal(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["NODEREAL_API_KEY"] = "regression-test-key"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                raise HTTPError(req.full_url, 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b""))
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x11"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x11")
        self.assertEqual(len(calls), 2, calls)
        self.assertIn("nodereal", calls[1])
        self.assertFalse(rpc.DISABLED_NODE_REAL)
        self.assertTrue(any("nodereal" in url for url in rpc.rpc_urls("bsc")))

    def test_server_error_fails_over_to_fallback_url(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            calls.append(url)
            if "primary.invalid" in url:
                raise HTTPError(url, 503, "Service Unavailable", hdrs=None, fp=io.BytesIO(b""))
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x1"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x1")
        self.assertEqual(calls[0], "https://primary.invalid/rpc")
        self.assertEqual(calls[1], "https://fallback.invalid/rpc")

    def test_null_receipt_result_raises_runtime_error(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"

        def fake_urlopen(req, timeout=30):
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": None})

        urllib.request.urlopen = fake_urlopen
        with self.assertRaises(RuntimeError):
            rpc.get_transaction_receipt("bsc", "0x" + "ab" * 32)

    def test_null_result_fails_over_to_next_url(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": None})
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x12"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x12")
        self.assertEqual(calls, ["https://primary.invalid/rpc", "https://fallback.invalid/rpc"])

    def test_all_failures_do_not_leak_endpoint_urls(self) -> None:
        sentinel = "credential-sentinel"
        os.environ["BSC_RPC_URL"] = f"https://primary.invalid/{sentinel}"
        os.environ["BSC_RPC_FALLBACK_URLS"] = f"https://fallback.invalid/{sentinel}"

        def fake_urlopen(req, timeout=30):
            raise HTTPError(req.full_url, 503, "Service Unavailable", hdrs=None, fp=io.BytesIO(b""))

        urllib.request.urlopen = fake_urlopen
        with self.assertRaises(RuntimeError) as raised:
            rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertNotIn("primary.invalid", str(raised.exception))
        self.assertNotIn("fallback.invalid", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("primary.invalid", rendered)
        self.assertNotIn("fallback.invalid", rendered)

    def test_read_timeout_fails_over_to_fallback_url(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                return _ReadTimeoutResponse()
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x2"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x2")
        self.assertEqual(calls, ["https://primary.invalid/rpc", "https://fallback.invalid/rpc"])

    def test_non_json_response_fails_over_to_fallback_url(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                return _RawResponse(b"<html>rate limited</html>")
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x3"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x3")
        self.assertEqual(calls, ["https://primary.invalid/rpc", "https://fallback.invalid/rpc"])

    def test_malformed_primary_url_fails_over_without_leaking_url(self) -> None:
        sentinel = "credential-sentinel"
        os.environ["BSC_RPC_URL"] = f"://{sentinel}"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x4"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x4")
        self.assertEqual(calls, ["https://fallback.invalid/rpc"])

        with self.assertRaises(RuntimeError) as raised:
            rpc.rpc_call_url(f"://{sentinel}", "eth_blockNumber", [])
        self.assertEqual(str(raised.exception), "rpc transport error")
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_non_object_json_response_is_retryable_and_sanitized(self) -> None:
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                return _FakeResponse(["credential-sentinel"])
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x5"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x5")
        self.assertEqual(calls, ["https://primary.invalid/rpc", "https://fallback.invalid/rpc"])

        for payload in (None, "credential-sentinel", ["credential-sentinel"]):
            with self.subTest(payload=payload):
                urllib.request.urlopen = lambda req, timeout=30, value=payload: _FakeResponse(value)
                with self.assertRaises(RuntimeError) as raised:
                    rpc.rpc_call_url("https://primary.invalid/rpc", "eth_blockNumber", [])
                self.assertEqual(str(raised.exception), "rpc response shape error")
                self.assertNotIn("credential-sentinel", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)

    def test_json_rpc_error_is_retryable_and_sanitized(self) -> None:
        sentinel = "credential-sentinel"
        os.environ["BSC_RPC_URL"] = "https://primary.invalid/rpc"
        os.environ["BSC_RPC_FALLBACK_URLS"] = "https://fallback.invalid/rpc"
        calls: list[str] = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if "primary.invalid" in req.full_url:
                return _FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32000, "message": sentinel},
                    }
                )
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "0x6"})

        urllib.request.urlopen = fake_urlopen
        result = rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertEqual(result, "0x6")
        self.assertEqual(calls, ["https://primary.invalid/rpc", "https://fallback.invalid/rpc"])

        urllib.request.urlopen = lambda req, timeout=30: _FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": sentinel},
            }
        )
        with self.assertRaises(RuntimeError) as raised:
            rpc.rpc_call_url("https://primary.invalid/rpc", "eth_blockNumber", [])
        self.assertEqual(str(raised.exception), "rpc response error")
        self.assertNotIn(sentinel, str(raised.exception))
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(sentinel, rendered)

    def test_transport_errors_on_all_urls_raise_sanitized_error(self) -> None:
        sentinel = "credential-sentinel"
        os.environ["BSC_RPC_URL"] = f"https://primary.invalid/{sentinel}"
        os.environ["BSC_RPC_FALLBACK_URLS"] = f"https://fallback.invalid/{sentinel}"

        def fake_urlopen(req, timeout=30):
            return _ReadTimeoutResponse()

        urllib.request.urlopen = fake_urlopen
        with self.assertRaises(RuntimeError) as raised:
            rpc.rpc_call("bsc", "eth_blockNumber", [])
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertNotIn("primary.invalid", str(raised.exception))
        self.assertNotIn("fallback.invalid", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)


class MergeFactsTests(unittest.TestCase):
    """A fact key that first arrives as a scalar must survive a later list-shaped
    arrival for the same key without crashing or exploding into characters."""

    def test_scalar_then_dict_list_merges_without_crash(self) -> None:
        first = merge_facts({}, {"team": "unknown"})
        merged = merge_facts(first, {"team": [{"name": "alice", "role": "dev"}]})
        value = merged["team"]
        self.assertIsInstance(value, list)
        self.assertIn("unknown", value)
        self.assertIn({"name": "alice", "role": "dev"}, value)

    def test_scalar_then_scalar_list_keeps_scalar_intact(self) -> None:
        merged = merge_facts({"team": "unknown"}, {"team": ["alice"]})
        self.assertEqual(merged["team"], ["unknown", "alice"])

    def test_dict_list_then_dict_list_still_dedupes(self) -> None:
        left = {"partners": [{"name": "a"}]}
        merged = merge_facts(left, {"partners": [{"name": "a"}, {"name": "b"}]})
        self.assertEqual(merged["partners"], [{"name": "a"}, {"name": "b"}])

    def test_scalar_then_equal_scalar_stays_scalar(self) -> None:
        merged = merge_facts({"team": "unknown"}, {"team": "unknown"})
        self.assertEqual(merged["team"], "unknown")

    def test_none_then_scalar_list_drops_empty_placeholder(self) -> None:
        merged = merge_facts({"team": None}, {"team": ["alice"]})
        self.assertEqual(merged["team"], ["alice"])

    def test_empty_string_then_scalar_list_drops_empty_placeholder(self) -> None:
        merged = merge_facts({"team": ""}, {"team": ["alice"]})
        self.assertEqual(merged["team"], ["alice"])

    def test_none_then_scalar_replaces_empty_placeholder(self) -> None:
        merged = merge_facts({"team": None}, {"team": "alice"})
        self.assertEqual(merged["team"], "alice")

    def test_empty_string_then_scalar_replaces_empty_placeholder(self) -> None:
        merged = merge_facts({"team": ""}, {"team": "alice"})
        self.assertEqual(merged["team"], "alice")

    def test_empty_list_then_scalar_replaces_empty_placeholder(self) -> None:
        merged = merge_facts({"team": []}, {"team": "alice"})
        self.assertEqual(merged["team"], "alice")

    def test_mixed_incoming_list_keeps_non_dict_items(self) -> None:
        merged = merge_facts({}, {"team": [{"name": "a"}, "bob"]})
        self.assertIn({"name": "a"}, merged["team"])
        self.assertIn("bob", merged["team"])

    def test_dict_list_then_mixed_incoming_list_keeps_scalar(self) -> None:
        merged = merge_facts({"team": [{"name": "b"}]}, {"team": [{"name": "a"}, "carol"]})
        self.assertIn({"name": "b"}, merged["team"])
        self.assertIn({"name": "a"}, merged["team"])
        self.assertIn("carol", merged["team"])

    def test_heterogeneous_dict_lists_do_not_false_dedupe(self) -> None:
        merged = merge_facts({"partners": [{"b": "1"}]}, {"partners": [{"a": "2"}, {"b": "3"}]})
        self.assertEqual(merged["partners"], [{"b": "1"}, {"a": "2"}, {"b": "3"}])


ROUNDTRIP_SCRIPT = ROOT / "scripts" / "simulate_pancake_v4_roundtrip_call.py"


def load_roundtrip_module():
    spec = importlib.util.spec_from_file_location(
        "simulate_pancake_v4_roundtrip_call_under_test",
        ROUNDTRIP_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    with patch("sniper_engine.env.load_local_env"):
        spec.loader.exec_module(module)
    return module


class PancakeV4RoundtripSyntheticBoundaryTests(unittest.TestCase):
    """Pure in-memory sell-leg boundaries. These are synthetic regression
    fixtures only and cannot trigger an RPC, action, alert, or runtime change."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_roundtrip_module()

    @staticmethod
    def recovery_args() -> SimpleNamespace:
        return SimpleNamespace(
            buy_amount=1_000,
            recovery_high_raw=1_000,
            recovery_iterations=16,
        )

    def estimate(self, *, sell_amount: int, block_tag: str, rpc_probe) -> dict[str, object]:
        def synthetic_calldata(
            args,
            sell_amount,
            pool_key,
            buy_zero_for_one,
            sell_amount_out_minimum=None,
        ):
            return {
                "calldata": json.dumps(
                    {
                        "synthetic": True,
                        "sell_amount": sell_amount,
                        "sell_amount_out_minimum": sell_amount_out_minimum,
                    },
                    sort_keys=True,
                )
            }

        with (
            patch.object(self.module, "build_roundtrip_calldata", side_effect=synthetic_calldata),
            patch.object(self.module, "rpc_call", side_effect=rpc_probe),
        ):
            return self.module.estimate_quote_recovery(
                self.recovery_args(),
                sell_amount,
                {"synthetic": True},
                True,
                "synthetic-holder",
                "synthetic-router",
                block_tag,
                {"synthetic": True},
            )

    def gate_for(self, recovery: dict[str, object]) -> dict[str, object]:
        return self.module.sellability_gate(
            "roundtrip_eth_call_success_with_recovery_rate",
            {
                "status": "success",
                "recovery_rate": recovery["recovery_rate"],
                "quote_recovered_raw": recovery["quote_recovered_raw"],
                "minimum_recovery_rate": "0.80",
            },
            {"status": "skipped"},
        )

    def test_delayed_blacklist_degrades_recovery_and_blocks_follow(self) -> None:
        buy_block = 100
        blacklist_delay_blocks = 5

        def delayed_blacklist_rpc(chain, method, params):
            self.assertEqual((chain, method), ("bsc", "eth_call"))
            current_block = int(params[1], 16)
            if current_block >= buy_block + blacklist_delay_blocks:
                raise RuntimeError("synthetic delayed blacklist sell-leg revert")
            return "0x"

        before = self.estimate(
            sell_amount=100,
            block_tag=hex(buy_block + blacklist_delay_blocks - 1),
            rpc_probe=delayed_blacklist_rpc,
        )
        after = self.estimate(
            sell_amount=100,
            block_tag=hex(buy_block + blacklist_delay_blocks),
            rpc_probe=delayed_blacklist_rpc,
        )

        self.assertEqual(before["quote_recovered_raw"], "1000")
        self.assertEqual(before["recovery_rate"], "1")
        self.assertEqual(after["quote_recovered_raw"], "0")
        self.assertEqual(after["recovery_rate"], "0")
        self.assertIn("synthetic delayed blacklist", str(after["last_failure"]))
        gate = self.gate_for(after)
        self.assertEqual(gate["gate"], "blocked_infinity_low_recovery")
        self.assertIs(gate["can_follow"], False)
        self.assertIs(gate["can_sell_proven"], False)

    def test_max_tx_sell_limit_blocks_large_leg_and_preserves_normal_recovery(self) -> None:
        max_sell_amount = 100
        recoverable_quote = 900

        def max_tx_rpc(chain, method, params):
            self.assertEqual((chain, method), ("bsc", "eth_call"))
            synthetic_call = json.loads(params[0]["data"])
            if synthetic_call["sell_amount"] > max_sell_amount:
                raise RuntimeError("synthetic max-tx sell-leg revert")
            if synthetic_call["sell_amount_out_minimum"] > recoverable_quote:
                raise RuntimeError("synthetic quote minimum exceeds recovery")
            return "0x"

        within_limit = self.estimate(
            sell_amount=max_sell_amount,
            block_tag=hex(200),
            rpc_probe=max_tx_rpc,
        )
        oversized = self.estimate(
            sell_amount=max_sell_amount + 1,
            block_tag=hex(200),
            rpc_probe=max_tx_rpc,
        )

        self.assertEqual(within_limit["quote_recovered_raw"], str(recoverable_quote))
        self.assertEqual(within_limit["recovery_rate"], "0.9")
        self.assertIs(self.gate_for(within_limit)["can_follow"], True)
        self.assertEqual(oversized["quote_recovered_raw"], "0")
        self.assertEqual(oversized["recovery_rate"], "0")
        self.assertIn("synthetic max-tx", str(oversized["last_failure"]))
        gate = self.gate_for(oversized)
        self.assertEqual(gate["gate"], "blocked_infinity_low_recovery")
        self.assertIs(gate["can_follow"], False)
        self.assertIs(gate["can_sell_proven"], False)


ALPHA_OPENING_SCRIPT = ROOT / "scripts" / "alpha_opening_block_watch.py"


class AlphaOpeningInfinityParityTests(unittest.TestCase):
    """In-memory parity checks for the production cron entry's recovery gate."""

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location(
            "alpha_opening_block_watch_under_test", ALPHA_OPENING_SCRIPT
        )
        cls.module = importlib.util.module_from_spec(spec)
        with patch("sniper_engine.env.load_local_env"):
            spec.loader.exec_module(cls.module)

    def run_case(
        self,
        *,
        block: int,
        sell_amount: int,
        blacklist_block: int | None = None,
        max_sell_amount: int | None = None,
        recoverable_quote: int = 1000,
    ) -> dict[str, str]:
        def execute(event, holder, override, fixture, timeout):
            if blacklist_block is not None and event["synthetic_block"] >= blacklist_block:
                return False, "synthetic delayed blacklist"
            if max_sell_amount is not None and fixture["sell_amount"] > max_sell_amount:
                return False, "synthetic max-tx"
            if fixture["sell_amount_out_minimum"] > recoverable_quote:
                return False, "synthetic quote minimum exceeds recovery"
            return True, ""

        def fixture(args):
            return {
                "sell_amount": args.sell_amount,
                "sell_amount_out_minimum": args.sell_amount_out_minimum,
            }

        with (
            patch.dict(
                os.environ,
                {
                    "ALPHA_OPENING_INFINITY_RECOVERY_ITERATIONS": "16",
                    "ALPHA_OPENING_INFINITY_RECOVERY_HIGH_RAW": "1000",
                },
            ),
            patch.object(self.module, "build_fixture", side_effect=fixture),
            patch.object(
                self.module, "execute_infinity_roundtrip_call", side_effect=execute
            ),
            patch.object(
                self.module,
                "quick_rpc_call",
                side_effect=AssertionError("production parity test attempted network access"),
            ),
        ):
            return self.module.estimate_infinity_quote_recovery(
                {"synthetic_block": block},
                "synthetic-holder",
                {"synthetic": True},
                SimpleNamespace(sell_amount=sell_amount),
                1000,
                1,
            )

    def assert_follow_blocked(self, recovery: dict[str, str]) -> None:
        self.assertEqual(recovery["recovery_rate"], "0")
        summary = self.module.sell_safety_summary(
            [
                {
                    "buyer_trace": {
                        "transfer_safety_status": "transfer_verified",
                        "dex_quote_status": "infinity_cl_quote_verified",
                        "router_sell_status": "infinity_roundtrip_low_recovery",
                        "router_sell_detail": (
                            f"synthetic recovery_rate={recovery['recovery_rate']}"
                        ),
                    }
                }
            ]
        )
        self.assertEqual(summary["gate"], "blocked_infinity_low_recovery")
        self.assertEqual(summary["status"], "v4往返回收率过低；禁止跟随")

    def test_delayed_blacklist_degrades_recovery_and_blocks_follow(self) -> None:
        blacklist_block = 105
        before = self.run_case(
            block=blacklist_block - 1,
            sell_amount=100,
            blacklist_block=blacklist_block,
        )
        after = self.run_case(
            block=blacklist_block,
            sell_amount=100,
            blacklist_block=blacklist_block,
        )

        self.assertEqual(before["recovery_rate"], "1")
        self.assertIn("synthetic delayed blacklist", after["last_failure"])
        self.assert_follow_blocked(after)

    def test_max_tx_degrades_recovery_and_blocks_follow(self) -> None:
        max_sell_amount = 100
        within_limit = self.run_case(
            block=200,
            sell_amount=max_sell_amount,
            max_sell_amount=max_sell_amount,
            recoverable_quote=900,
        )
        oversized = self.run_case(
            block=200,
            sell_amount=max_sell_amount + 1,
            max_sell_amount=max_sell_amount,
            recoverable_quote=900,
        )

        self.assertEqual(within_limit["recovery_rate"], "0.9")
        self.assertIn("synthetic max-tx", oversized["last_failure"])
        self.assert_follow_blocked(oversized)


VERIFY_SCRIPT = ROOT / "scripts" / "verify_sniper_engine.py"


def load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_sniper_engine_under_test", VERIFY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OFFLINE_GUARD_PROBE = r'''
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

script, repo_root, work = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("verify_sniper_engine_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.install_offline_guard(work)

try:
    socket.create_connection(("127.0.0.1", 9), timeout=0.25)
    print("NET_ALLOWED")
except RuntimeError as exc:
    print("NET_BLOCKED" if "sniper-offline-guard" in str(exc) else "NET_OTHER:%r" % (exc,))
except Exception as exc:
    print("NET_OTHER:%r" % (exc,))

direct_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    direct_sock.connect(("127.0.0.1", 9))
    print("NET_DIRECT_ALLOWED")
except RuntimeError as exc:
    print("NET_DIRECT_BLOCKED" if "sniper-offline-guard" in str(exc) else "NET_DIRECT_OTHER:%r" % (exc,))
except Exception as exc:
    print("NET_DIRECT_OTHER:%r" % (exc,))
finally:
    direct_sock.close()

try:
    socket.gethostbyname("localhost")
    print("DNS_ALLOWED")
except RuntimeError as exc:
    print("DNS_BLOCKED" if "sniper-offline-guard" in str(exc) else "DNS_OTHER:%r" % (exc,))
except Exception as exc:
    print("DNS_OTHER:%r" % (exc,))

try:
    handle = open(repo_root / ".env.local", "r", encoding="utf-8")
    handle.close()
    print("ENV_ALLOWED")
except RuntimeError as exc:
    print("ENV_BLOCKED" if "sniper-offline-guard" in str(exc) else "ENV_OTHER:%r" % (exc,))
except Exception as exc:
    print("ENV_OTHER:%r" % (exc,))

try:
    handle = open(repo_root / ".ENV.LOCAL", "r", encoding="utf-8")
    handle.close()
    print("ENV_CASE_ALLOWED")
except RuntimeError as exc:
    print("ENV_CASE_BLOCKED" if "sniper-offline-guard" in str(exc) else "ENV_CASE_OTHER:%r" % (exc,))
except Exception as exc:
    print("ENV_CASE_OTHER:%r" % (exc,))

probe_file = repo_root / "output" / "sniper_engine" / "offline_guard_write_probe.tmp"
try:
    handle = open(probe_file, "w", encoding="utf-8")
    handle.close()
    print("WRITE_ALLOWED")
except RuntimeError as exc:
    print("WRITE_BLOCKED" if "sniper-offline-guard" in str(exc) else "WRITE_OTHER:%r" % (exc,))
except Exception as exc:
    print("WRITE_OTHER:%r" % (exc,))
finally:
    try:
        if probe_file.exists():
            probe_file.unlink()
    except Exception:
        pass

outside_file = repo_root.parent / "offline_guard_outside_write_probe.tmp"
try:
    outside_file.write_text("forbidden", encoding="utf-8")
    print("OUTSIDE_WRITE_ALLOWED")
except RuntimeError as exc:
    print("OUTSIDE_WRITE_BLOCKED" if "sniper-offline-guard" in str(exc) else "OUTSIDE_WRITE_OTHER:%r" % (exc,))
except Exception as exc:
    print("OUTSIDE_WRITE_OTHER:%r" % (exc,))

repo_dir = repo_root / "offline_guard_mkdir_probe"
try:
    repo_dir.mkdir()
    print("MKDIR_ALLOWED")
except RuntimeError as exc:
    print("MKDIR_BLOCKED" if "sniper-offline-guard" in str(exc) else "MKDIR_OTHER:%r" % (exc,))
except Exception as exc:
    print("MKDIR_OTHER:%r" % (exc,))

try:
    subprocess.run(["/bin/sh", "-c", "true"], check=True)
    print("NONPYTHON_ALLOWED")
except RuntimeError as exc:
    print("NONPYTHON_BLOCKED" if "sniper-offline-guard" in str(exc) else "NONPYTHON_OTHER:%r" % (exc,))
except Exception as exc:
    print("NONPYTHON_OTHER:%r" % (exc,))

outside_dir_fd = os.open("/dev", os.O_RDONLY)
try:
    handle = os.open("null", os.O_WRONLY, dir_fd=outside_dir_fd)
    os.close(handle)
    print("DIRFD_WRITE_ALLOWED")
except RuntimeError as exc:
    print("DIRFD_WRITE_BLOCKED" if "sniper-offline-guard" in str(exc) else "DIRFD_WRITE_OTHER:%r" % (exc,))
except Exception as exc:
    print("DIRFD_WRITE_OTHER:%r" % (exc,))
finally:
    os.close(outside_dir_fd)

temp_dir_fd = os.open(work, os.O_RDONLY)
try:
    handle = os.open(
        "dirfd_write_ok.tmp",
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
        dir_fd=temp_dir_fd,
    )
    os.close(handle)
    print("TMP_DIRFD_WRITE_OK")
finally:
    os.close(temp_dir_fd)

try:
    handle = open(repo_root.parent / ".env.guard-probe", "r", encoding="utf-8")
    handle.close()
    print("OUTSIDE_ENV_ALLOWED")
except RuntimeError as exc:
    print("OUTSIDE_ENV_BLOCKED" if "sniper-offline-guard" in str(exc) else "OUTSIDE_ENV_OTHER:%r" % (exc,))
except Exception as exc:
    print("OUTSIDE_ENV_OTHER:%r" % (exc,))

(work / "probe_ok.txt").write_text("ok", encoding="utf-8")
print("TMP_WRITE_OK")

with open(repo_root / ".env.example", "r", encoding="utf-8") as handle:
    handle.read(8)
print("EXAMPLE_READ_OK")
'''


CHILD_ENV_PROPAGATION_PROBE = r'''
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

script = sys.argv[1]
spec = importlib.util.spec_from_file_location("verify_sniper_engine_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

existing_tmp_root = os.environ.get("SNIPER_OFFLINE_TMP_ROOT")
existing_repo_root = os.environ.get("SNIPER_OFFLINE_REPO_ROOT")
if os.environ.get("SNIPER_OFFLINE") == "1" and existing_tmp_root and existing_repo_root:
    offline_root = Path(existing_tmp_root)
else:
    offline_root = module.prepare_offline_environment()
assert os.environ.get("SNIPER_OFFLINE") == "1", os.environ.get("SNIPER_OFFLINE")
assert os.environ.get("SNIPER_OFFLINE_TMP_ROOT") == str(offline_root), os.environ.get("SNIPER_OFFLINE_TMP_ROOT")
assert os.environ.get("SNIPER_OFFLINE_REPO_ROOT") == str(module.ROOT), os.environ.get("SNIPER_OFFLINE_REPO_ROOT")
assert not str(offline_root).startswith(str(module.ROOT)), offline_root
guard_dir = os.environ.get("PYTHONPATH", "").split(os.pathsep)[0]
assert (Path(guard_dir) / "sitecustomize.py").is_file(), guard_dir
assert os.environ.get("PYTHONPYCACHEPREFIX", "").startswith(str(offline_root)), os.environ.get("PYTHONPYCACHEPREFIX")

probe = subprocess.run(
    [sys.executable, "-c", "import socket; socket.create_connection(('127.0.0.1', 9), timeout=0.25)"],
    capture_output=True,
    text=True,
)
assert probe.returncode != 0, probe.stdout + probe.stderr
assert "sniper-offline-guard" in probe.stderr, probe.stderr
print("CHILD_GUARD_OK")

stripped_env = os.environ.copy()
stripped_env.pop("SNIPER_OFFLINE_REPO_ROOT", None)
try:
    stripped = subprocess.run(
        [sys.executable, "-c", "print('unguarded')"],
        capture_output=True,
        text=True,
        env=stripped_env,
    )
except RuntimeError as exc:
    assert "sniper-offline-guard" in str(exc), exc
else:
    assert stripped.returncode != 0, "child with missing guard roots must fail closed: " + stripped.stdout + stripped.stderr
    assert "sniper-offline-guard" in stripped.stderr, stripped.stderr
print("CHILD_FAIL_CLOSED_OK")

import tempfile
tmpdir_env = os.environ.get("TMPDIR", "")
scratch = tempfile.mkdtemp(prefix="offline_probe_scratch_")
if (
    tmpdir_env.startswith(str(offline_root))
    and os.environ.get("TEMP", "") == tmpdir_env
    and os.environ.get("TMP", "") == tmpdir_env
    and scratch.startswith(str(offline_root))
):
    print("CHILD_TMPDIR_OK")
'''


PYTHON_CHILD_BYPASS_PROBE = r'''
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

script = sys.argv[1]
spec = importlib.util.spec_from_file_location("verify_sniper_engine_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

existing_tmp_root = os.environ.get("SNIPER_OFFLINE_TMP_ROOT")
existing_repo_root = os.environ.get("SNIPER_OFFLINE_REPO_ROOT")
if os.environ.get("SNIPER_OFFLINE") == "1" and existing_tmp_root and existing_repo_root:
    offline_root = Path(existing_tmp_root)
else:
    offline_root = module.prepare_offline_environment()
    module.install_offline_guard(offline_root)

normal = subprocess.run(
    [sys.executable, "-c", "print('guarded')"],
    capture_output=True,
    text=True,
)
assert normal.returncode == 0 and normal.stdout.strip() == "guarded", normal.stderr
print("PYTHON_CHILD_GUARDED_OK")

warning_option = subprocess.run(
    [sys.executable, "-Werror::ImportWarning", "-c", "print('guarded-warning-option')"],
    capture_output=True,
    text=True,
)
assert (
    warning_option.returncode == 0
    and warning_option.stdout.strip() == "guarded-warning-option"
), warning_option.stderr
print("PYTHON_CHILD_WARNING_OPTION_OK")

for label, argv, env in (
    ("PYTHON_DASH_S", [sys.executable, "-S", "-c", "print('unguarded')"], None),
    ("PYTHON_CLEAN_ENV", [sys.executable, "-c", "print('unguarded')"], {}),
):
    try:
        subprocess.run(argv, capture_output=True, text=True, env=env)
        print(label + "_ALLOWED")
    except RuntimeError as exc:
        if "sniper-offline-guard" in str(exc):
            print(label + "_BLOCKED")
        else:
            print(label + "_OTHER:" + repr(exc))
'''


CELUE_OFFLINE_PROBE = r'''
import importlib.util
import os
import subprocess
import sys

script = sys.argv[1]
spec = importlib.util.spec_from_file_location("verify_sniper_engine_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

if not (
    os.environ.get("SNIPER_OFFLINE") == "1"
    and os.environ.get("SNIPER_OFFLINE_TMP_ROOT")
    and os.environ.get("SNIPER_OFFLINE_REPO_ROOT")
):
    module.prepare_offline_environment()
result = subprocess.run(
    [sys.executable, "-c", module.CELUE_AUDIT_CODE],
    cwd=module.ROOT,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, "offline celue audit must not depend on out-of-repo state: " + (
    result.stderr or result.stdout
)
print("CELUE_OFFLINE_OK")
'''


class OfflineVerifierGuardTests(unittest.TestCase):
    """--offline must guarantee zero network attempts, no .env.local reads, and
    temp-dir-only outputs for the verifier and every python child it spawns,
    while normal mode keeps its defaults untouched."""

    def run_probe(self, code, *argv):
        return subprocess.run(
            [sys.executable, "-c", code, *argv],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_normal_mode_defaults_stay_unchanged(self) -> None:
        module = load_verify_module()
        self.assertEqual(module.REPORT, ROOT / "output" / "sniper_engine" / "verification_report.md")
        self.assertFalse(module.parse_offline([]))
        self.assertTrue(module.parse_offline(["--offline"]))
        self.assertEqual(module.resolve_report_path(None), module.REPORT)

    def test_offline_report_path_moves_into_temp_root(self) -> None:
        module = load_verify_module()
        with tempfile.TemporaryDirectory() as tmp:
            offline_report = module.resolve_report_path(Path(tmp))
            self.assertEqual(offline_report.name, "verification_report.md")
            self.assertTrue(str(offline_report).startswith(tmp), offline_report)
            self.assertFalse(str(offline_report).startswith(str(ROOT)), offline_report)

    def test_offline_env_flag_makes_local_env_loading_a_noop(self) -> None:
        sentinel_key = "SNIPER_OFFLINE_TEST_SENTINEL"
        saved_flag = os.environ.get("SNIPER_OFFLINE")
        os.environ.pop(sentinel_key, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_file = Path(tmp) / "env_fixture.txt"
                env_file.write_text(sentinel_key + "=loaded\n", encoding="utf-8")
                os.environ.pop("SNIPER_OFFLINE", None)
                sniper_env.load_local_env(env_file)
                self.assertEqual(os.environ.get(sentinel_key), "loaded")
                os.environ.pop(sentinel_key, None)
                os.environ["SNIPER_OFFLINE"] = "1"
                sniper_env.load_local_env(env_file)
                self.assertIsNone(os.environ.get(sentinel_key))
        finally:
            os.environ.pop(sentinel_key, None)
            if saved_flag is None:
                os.environ.pop("SNIPER_OFFLINE", None)
            else:
                os.environ["SNIPER_OFFLINE"] = saved_flag

    def test_offline_guard_blocks_network_env_reads_and_repo_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_probe(OFFLINE_GUARD_PROBE, str(VERIFY_SCRIPT), str(ROOT), tmp)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        lines = result.stdout.splitlines()
        self.assertIn("NET_BLOCKED", lines, result.stdout)
        self.assertIn("NET_DIRECT_BLOCKED", lines, result.stdout)
        self.assertIn("DNS_BLOCKED", lines, result.stdout)
        self.assertIn("ENV_BLOCKED", lines, result.stdout)
        self.assertIn("WRITE_BLOCKED", lines, result.stdout)
        self.assertIn("OUTSIDE_WRITE_BLOCKED", lines, result.stdout)
        self.assertIn("MKDIR_BLOCKED", lines, result.stdout)
        self.assertIn("NONPYTHON_BLOCKED", lines, result.stdout)
        self.assertIn("DIRFD_WRITE_BLOCKED", lines, result.stdout)
        self.assertIn("OUTSIDE_ENV_BLOCKED", lines, result.stdout)
        self.assertIn("TMP_WRITE_OK", lines, result.stdout)
        self.assertIn("TMP_DIRFD_WRITE_OK", lines, result.stdout)
        self.assertIn("EXAMPLE_READ_OK", lines, result.stdout)

    def test_env_file_block_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_probe(OFFLINE_GUARD_PROBE, str(VERIFY_SCRIPT), str(ROOT), tmp)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("ENV_CASE_BLOCKED", result.stdout.splitlines(), result.stdout)

    def test_offline_environment_guards_python_child_processes(self) -> None:
        result = self.run_probe(CHILD_ENV_PROPAGATION_PROBE, str(VERIFY_SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("CHILD_GUARD_OK", result.stdout.splitlines(), result.stdout)

    def test_offline_child_missing_guard_roots_fails_closed(self) -> None:
        result = self.run_probe(CHILD_ENV_PROPAGATION_PROBE, str(VERIFY_SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("CHILD_FAIL_CLOSED_OK", result.stdout.splitlines(), result.stdout)

    def test_offline_child_tempdirs_live_under_offline_root(self) -> None:
        result = self.run_probe(CHILD_ENV_PROPAGATION_PROBE, str(VERIFY_SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("CHILD_TMPDIR_OK", result.stdout.splitlines(), result.stdout)

    def test_offline_parent_rejects_python_guard_bypasses(self) -> None:
        result = self.run_probe(PYTHON_CHILD_BYPASS_PROBE, str(VERIFY_SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        lines = result.stdout.splitlines()
        self.assertIn("PYTHON_CHILD_GUARDED_OK", lines, result.stdout)
        self.assertIn("PYTHON_CHILD_WARNING_OPTION_OK", lines, result.stdout)
        self.assertIn("PYTHON_DASH_S_BLOCKED", lines, result.stdout)
        self.assertIn("PYTHON_CLEAN_ENV_BLOCKED", lines, result.stdout)

    def test_offline_celue_audit_passes_without_out_of_repo_state(self) -> None:
        result = self.run_probe(CELUE_OFFLINE_PROBE, str(VERIFY_SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("CELUE_OFFLINE_OK", result.stdout.splitlines(), result.stdout)


if __name__ == "__main__":
    unittest.main()
