#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_opening_block_watch as opening
import scripts.rebuild_opening_sell_evidence as rebuild
from scripts.runtime_health_watch import output_freshness_timestamp


TOKEN, QUOTE, BUYER, POOL = [
    f"0x{digit * 40}" for digit in "1234"
]
SELL_TX, OLD_TX = [f"0x{digit * 64}" for digit in "57"]


def transfer_log(
    token: str,
    sender: str,
    recipient: str,
    amount: int,
    tx_hash: str,
    index: int,
    block: int = 150,
) -> dict:
    return {
        "address": token,
        "topics": [
            opening.TRANSFER_TOPIC,
            opening.address_topic(sender),
            opening.address_topic(recipient),
        ],
        "data": hex(amount),
        "logIndex": hex(index),
        "transactionHash": tx_hash,
        "blockNumber": hex(block),
    }


def receipt(
    *,
    status: str = "0x1",
    tx_hash: str = SELL_TX,
    log_tx_hash: str = SELL_TX,
    block: int = 150,
    include_token_out: bool = True,
    include_quote: bool = True,
) -> dict:
    logs = []
    if include_token_out:
        logs.append(
            transfer_log(
                TOKEN,
                BUYER,
                POOL,
                1000,
                log_tx_hash,
                1,
                block,
            )
        )
    if include_quote:
        logs.append(
            transfer_log(
                QUOTE,
                POOL,
                BUYER,
                500,
                log_tx_hash,
                2,
                block,
            )
        )
    return {
        "status": status,
        "from": BUYER,
        "transactionHash": tx_hash,
        "blockNumber": hex(block),
        "logs": logs,
    }


def snapshot(
    *,
    complete: bool = True,
    latest: int = 200,
    old_quote: str = "700",
) -> dict:
    evidence = [
        {
            "id": f"{OLD_TX}:1",
            "tx": OLD_TX,
            "log_index": 1,
            "quote_received": old_quote,
            "route": "direct",
            "recipient": BUYER,
        }
    ]
    return {
        "generated_at": "2026-07-29T00:00:00+00:00",
        "event_count": 1,
        "alert_count": 0,
        "new_alert_count": 0,
        "events": [
            {
                "symbol": "AEON",
                "status": "opened",
                "chain": "bsc",
                "opening_block": 100,
                "latest_block": latest,
                "token": {
                    "address": TOKEN,
                    "symbol": "AEON",
                    "decimals": 0,
                },
                "quote": {
                    "address": QUOTE,
                    "symbol": "USDT",
                    "decimals": 0,
                },
                "rows": [
                    {
                        "block": 100,
                        "buyer": BUYER,
                        "token_bought": "1000",
                        "spent_quote": "12000",
                        "largest_internal_native": {"amount": "0"},
                        "buyer_trace": {
                            "status": "held_or_accumulated",
                            "position_status": "held_or_accumulated",
                            "coverage_complete": complete,
                            "confirmed_sell_quote_received": old_quote,
                            "direct_sell_quote_received": old_quote,
                            "next_hop_sell_quote_received": "0",
                            "confirmed_sell_count": "1",
                            "confirmed_sell_evidence": evidence,
                        },
                    }
                ],
                "analysis": {},
            }
        ],
    }


def pages(_chain: str, query: dict) -> dict:
    return {
        "transfers": [
            {
                "from": BUYER,
                "contractAddress": TOKEN,
                "hash": SELL_TX,
            }
        ],
        "pageKey": "" if query.get("pageKey") else "next",
    }


def rebuild_aeon(
    source: dict,
    *,
    max_pages: int = 2,
    max_transactions: int = 10,
    deadline: float | None = None,
    transfer_rpc=pages,
    receipt_rpc=lambda *_: receipt(),
) -> tuple[dict, dict]:
    return rebuild.rebuild_snapshot(
        source,
        "AEON",
        TOKEN,
        100,
        2,
        max_pages,
        max_transactions,
        deadline,
        transfer_rpc,
        receipt_rpc,
    )


def args_for(path: Path, *, apply: bool) -> SimpleNamespace:
    return SimpleNamespace(
        input=path,
        symbol="AEON",
        token=TOKEN,
        opening_block=100,
        max_buyers=2,
        max_pages=2,
        max_transactions=10,
        max_seconds=30,
        apply=apply,
    )


def fake_rpc(chain, method, params, **_kwargs):
    if method == "nr_getAssetTransfers":
        return pages(chain, params[0])
    if method == "eth_getTransactionReceipt":
        return receipt()
    raise AssertionError(method)


class RebuildTests(unittest.TestCase):
    def test_dry_run_and_guarded_apply_persist_canonical_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            json_path = Path(temp) / "latest.json"
            markdown_path = Path(temp) / "latest.md"
            original = snapshot()
            json_path.write_text(json.dumps(original))
            markdown_path.write_text("old")
            original_bytes = json_path.read_bytes()

            _, dry = rebuild_aeon(original)
            self.assertFalse(dry["applied"])
            self.assertEqual(json_path.read_bytes(), original_bytes)
            self.assertEqual(markdown_path.read_text(), "old")

            with (
                mock.patch.object(
                    opening,
                    "rpc_call",
                    side_effect=fake_rpc,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "SNIPER_RUN_LOCK_FILE": str(
                            Path(temp) / "server.lock"
                        )
                    },
                ),
            ):
                applied = rebuild.execute(
                    args_for(json_path, apply=True)
                )

            saved = json.loads(json_path.read_text())
            trace = saved["events"][0]["rows"][0]["buyer_trace"]
            self.assertTrue(applied["applied"])
            self.assertEqual(
                trace["confirmed_sell_quote_received"],
                "1200",
            )
            self.assertNotEqual(markdown_path.read_text(), "old")

    def test_rebuild_recomputes_sell_signal_and_alert_count(self):
        updated, summary = rebuild_aeon(
            snapshot(old_quote="9800")
        )
        event = updated["events"][0]
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(
            event["analysis"]["cohort_confirmed_sell_quote"],
            "10300",
        )
        self.assertEqual(event["analysis"]["direction"], "偏空")
        self.assertIn("卖出/减仓", event["analysis"]["trade_signal"])
        self.assertGreater(updated["alert_count"], 0)
        self.assertEqual(
            updated["generated_at"],
            "2026-07-29T00:00:00+00:00",
        )
        self.assertEqual(
            summary["source_generated_at"],
            updated["generated_at"],
        )

    def test_provider_and_receipt_conflicts_fail_closed(self):
        cases = [
            (
                lambda *_: {"transfers": [], "pageKey": "more"},
                lambda *_: receipt(),
                "asset_transfer_page_limit",
            ),
            (
                lambda *_: None,
                lambda *_: self.fail(),
                "asset_transfer_response_invalid",
            ),
            (
                pages,
                lambda *_: receipt(status="0x0"),
                "receipt_execution_failed",
            ),
            (
                pages,
                lambda *_: receipt(tx_hash=OLD_TX),
                "receipt_transaction_mismatch",
            ),
            (
                pages,
                lambda *_: receipt(log_tx_hash=OLD_TX),
                "receipt_log_transaction_mismatch",
            ),
            (
                pages,
                lambda *_: receipt(block=99),
                "receipt_block_out_of_range",
            ),
            (
                pages,
                lambda *_: receipt(include_token_out=False),
                "receipt_direction_missing_token_out",
            ),
        ]
        for transfer_rpc, receipt_rpc, reason in cases:
            with self.subTest(reason=reason):
                updated, summary = rebuild_aeon(
                    snapshot(),
                    max_pages=1,
                    transfer_rpc=transfer_rpc,
                    receipt_rpc=receipt_rpc,
                )
                trace = updated["events"][0]["rows"][0][
                    "buyer_trace"
                ]
                audit = trace["direct_sell_rebuild"]
                self.assertEqual(
                    summary["acquisition_status"],
                    "partial",
                )
                self.assertIn(
                    reason,
                    audit["acquisition_incomplete_reasons"],
                )
                self.assertGreaterEqual(
                    opening.decimal_from(
                        trace["confirmed_sell_quote_received"]
                    ),
                    opening.Decimal("700"),
                )

    def test_deadline_transaction_limit_and_cursor_cycle_stop(self):
        rpc = mock.Mock()
        updated, summary = rebuild_aeon(
            snapshot(),
            deadline=time.monotonic() - 1,
            transfer_rpc=rpc,
        )
        rpc.assert_not_called()
        self.assertEqual(summary["acquisition_status"], "partial")
        self.assertIn(
            "deadline_exceeded",
            updated["events"][0]["rows"][0]["buyer_trace"][
                "direct_sell_rebuild"
            ]["acquisition_incomplete_reasons"],
        )

        two_transactions = lambda *_: {
            "transfers": [
                {
                    "from": BUYER,
                    "contractAddress": TOKEN,
                    "hash": SELL_TX,
                },
                {
                    "from": BUYER,
                    "contractAddress": TOKEN,
                    "hash": OLD_TX,
                },
            ],
            "pageKey": "",
        }
        _, reasons, _ = rebuild.collect(
            dict(snapshot()["events"][0], _buy_block=100),
            BUYER,
            2,
            1,
            None,
            two_transactions,
        )
        self.assertIn("asset_transfer_transaction_limit", reasons)

        repeated_cursor = lambda *_: {
            "transfers": [],
            "pageKey": "same",
        }
        _, reasons, _ = rebuild.collect(
            dict(snapshot()["events"][0], _buy_block=100),
            BUYER,
            3,
            10,
            None,
            repeated_cursor,
        )
        self.assertIn("asset_transfer_page_key_repeated", reasons)

    def test_asset_transfers_are_scanned_in_bounded_block_chunks(self):
        queries = []
        hashes = [f"0x{digit * 64}" for digit in "89a"]

        def chunked(_chain, query):
            start = int(query["fromBlock"], 16)
            end = int(query["toBlock"], 16)
            self.assertLessEqual(
                end - start + 1,
                rebuild.ASSET_TRANSFER_MAX_BLOCK_SPAN,
            )
            queries.append((start, end))
            return {
                "transfers": [
                    {
                        "from": BUYER,
                        "contractAddress": TOKEN,
                        "hash": hashes[len(queries) - 1],
                    }
                ],
                "pageKey": "",
            }

        event = dict(
            snapshot(latest=200_150)["events"][0],
            _buy_block=100,
        )
        transactions, reasons, page_count = rebuild.collect(
            event,
            BUYER,
            3,
            10,
            None,
            chunked,
        )
        self.assertEqual(reasons, set())
        self.assertEqual(page_count, 3)
        self.assertEqual(transactions, hashes)
        self.assertEqual(
            queries,
            [
                (100, 100_099),
                (100_100, 200_099),
                (200_100, 200_150),
            ],
        )

    def test_token_out_without_quote_requires_next_hop_refresh(self):
        updated, summary = rebuild_aeon(
            snapshot(old_quote="0"),
            receipt_rpc=lambda *_: receipt(include_quote=False),
        )
        trace = updated["events"][0]["rows"][0]["buyer_trace"]
        audit = trace["direct_sell_rebuild"]
        self.assertEqual(summary["acquisition_status"], "complete")
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(
            audit["unresolved_outbound_transaction_count"],
            1,
        )
        self.assertIn(
            "next_hop_not_refreshed",
            audit["incomplete_reasons"],
        )
        self.assertFalse(trace["coverage_complete"])

    def test_target_must_match_one_exact_event(self):
        source = snapshot()
        source["events"].append(
            json.loads(json.dumps(source["events"][0]))
        )
        updated, summary = rebuild_aeon(source)
        self.assertEqual(summary["status"], "target_ambiguous")
        self.assertEqual(summary["matching_event_count"], 2)
        self.assertNotIn(
            "direct_sell_rebuild",
            updated["events"][0]["rows"][0]["buyer_trace"],
        )

        _, summary = rebuild.rebuild_snapshot(
            snapshot(),
            "AEON",
            "0x" + "9" * 40,
            100,
            2,
            2,
            10,
            None,
            pages,
            lambda *_: receipt(),
        )
        self.assertEqual(summary["status"], "target_not_found")

    def test_overall_partial_with_complete_acquisition_can_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            json_path = Path(temp) / "latest.json"
            markdown_path = Path(temp) / "latest.md"
            json_path.write_text(json.dumps(snapshot(complete=False)))
            markdown_path.write_text("old")
            with (
                mock.patch.object(
                    opening,
                    "rpc_call",
                    side_effect=fake_rpc,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "SNIPER_RUN_LOCK_FILE": str(
                            Path(temp) / "server.lock"
                        )
                    },
                ),
            ):
                summary = rebuild.execute(
                    args_for(json_path, apply=True)
                )
            self.assertEqual(summary["status"], "partial")
            self.assertEqual(
                summary["acquisition_status"],
                "complete",
            )
            self.assertTrue(summary["applied"])
            self.assertEqual(
                json.loads(json_path.read_text())[
                    "direct_sell_evidence_rebuild"
                ]["status"],
                "partial",
            )

    def test_apply_rejects_changed_or_incomplete_input(self):
        with tempfile.TemporaryDirectory() as temp:
            json_path = Path(temp) / "latest.json"
            markdown_path = Path(temp) / "latest.md"
            json_path.write_text(json.dumps(snapshot()))
            markdown_path.write_text("old")
            current = json.loads(json_path.read_text())
            updated, summary = rebuild_aeon(current)
            json_state = rebuild.file_state(json_path)
            markdown_state = rebuild.file_state(markdown_path)
            changed = snapshot()
            changed["concurrent_marker"] = True
            json_path.write_text(json.dumps(changed))
            with self.assertRaises(rebuild.SnapshotChangedError):
                rebuild.apply_prepared_rebuild(
                    json_path,
                    markdown_path,
                    json_state,
                    markdown_state,
                    updated,
                    summary,
                )
            self.assertTrue(
                json.loads(json_path.read_text())["concurrent_marker"]
            )
            self.assertEqual(markdown_path.read_text(), "old")

            partial_updated, partial = rebuild_aeon(
                snapshot(),
                transfer_rpc=lambda *_: None,
            )
            with self.assertRaises(
                rebuild.IncompleteAcquisitionError
            ):
                rebuild.apply_prepared_rebuild(
                    json_path,
                    markdown_path,
                    rebuild.file_state(json_path),
                    rebuild.file_state(markdown_path),
                    partial_updated,
                    partial,
                )

    def test_pair_replace_rolls_back_and_cli_partial_is_nonzero(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "one"
            second = Path(temp) / "two"
            second.write_text("old-two")
            real_replace = os.replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated")
                return real_replace(source, destination)

            with mock.patch.object(
                rebuild.os,
                "replace",
                side_effect=fail_second,
            ):
                with self.assertRaises(OSError):
                    rebuild.replace_pair(
                        [(first, "new-one"), (second, "new-two")]
                    )
            self.assertFalse(first.exists())
            self.assertEqual(second.read_text(), "old-two")

            json_path = Path(temp) / "latest.json"
            json_path.write_text(json.dumps(snapshot()))
            json_path.with_suffix(".md").write_text("old")
            with (
                mock.patch.object(
                    opening,
                    "rpc_call",
                    return_value=None,
                ),
                mock.patch("sys.stdout"),
            ):
                code = rebuild.main(
                    [
                        "--input",
                        str(json_path),
                        "--symbol",
                        "AEON",
                        "--token",
                        TOKEN,
                        "--opening-block",
                        "100",
                        "--max-pages",
                        "1",
                    ]
                )
            self.assertEqual(code, 2)

    def test_applied_rebuild_does_not_refresh_live_freshness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "latest.json"
            path.write_text(
                json.dumps(
                    {
                        "direct_sell_evidence_rebuild": {
                            "applied": True,
                            "source_generated_at": (
                                "2026-07-20T00:00:00+00:00"
                            ),
                        }
                    }
                )
            )
            os.utime(path, None)
            self.assertLess(
                output_freshness_timestamp("alpha_opening", path),
                path.stat().st_mtime - 3600,
            )


if __name__ == "__main__":
    unittest.main()
