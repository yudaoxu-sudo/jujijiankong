#!/usr/bin/env python3
from __future__ import annotations

import io
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import telegram_signal_collector as collector


KII = "0xeec6574eabba52bac3f0277f2cd5ac7e67197886"
OTHER = "0x1111111111111111111111111111111111111111"


def watchlist_item(
    symbol: str = "KII",
    *,
    contract: str = KII,
    aliases: list[str] | None = None,
    policy: bool = True,
) -> dict[str, object]:
    item: dict[str, object] = {
        "symbol": symbol,
        "aliases": aliases or [],
        "contracts": [{"chain": "bsc", "address": contract}],
    }
    if policy:
        item["proposal_policy"] = {
            "mode": "manual_research_managed",
            "suppress_discovery_proposals": True,
        }
    return item


def parsed_signal(
    *,
    symbol: str = "KII",
    contract: str | None = KII,
    chain: str = "bsc",
    authority: str = "social_discovery",
) -> dict[str, object]:
    contracts = []
    if contract:
        contracts.append({"chain": chain, "address": contract})
    return {
        "symbol": symbol,
        "symbols": [symbol],
        "priority": "P1_MONITOR",
        "title": f"{symbol} discovery",
        "addresses": [],
        "txs": [],
        "blocks": [],
        "pool_ids": [],
        "prediction_urls": [],
        "prices": {},
        "next_checks": [],
        "project_registry": {"status": "new_project"},
        "source_policy": {"authority": authority},
        "watchlist_proposal": {
            "symbol": symbol,
            "chain": chain,
            "contracts": contracts,
        },
    }


class ManualResearchProposalPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watchlist = {"items": [watchlist_item()]}

    def test_exact_chain_contract_suppresses_automatic_discovery_push(self) -> None:
        parsed = parsed_signal()
        decision = collector.proposal_suppression(parsed, self.watchlist)
        self.assertTrue(decision["suppressed"])
        self.assertEqual(decision["match_method"], "chain_contract")
        with mock.patch.object(
            collector,
            "load_current_watchlist",
            return_value=self.watchlist,
        ):
            self.assertFalse(collector.should_push(parsed, private_chat=False))
            self.assertTrue(collector.should_push(parsed, private_chat=True))
            message = collector.analysis_message(parsed, False)
            self.assertIn("已有投研补充: KII", message)
            self.assertIn("人工投研已接管，自动发现提案已跳过", message)

    def test_contract_or_chain_conflict_never_falls_back_to_symbol(self) -> None:
        for parsed in (
            parsed_signal(contract=OTHER),
            parsed_signal(chain="base"),
        ):
            with self.subTest(parsed=parsed["watchlist_proposal"]):
                self.assertFalse(
                    collector.proposal_suppression(parsed, self.watchlist)[
                        "suppressed"
                    ]
                )

        malformed = parsed_signal(contract=None)
        malformed["watchlist_proposal"]["contracts"] = [
            {"chain": "bsc", "address": "0x1234"}
        ]
        self.assertFalse(
            collector.proposal_suppression(malformed, self.watchlist)[
                "suppressed"
            ]
        )

        multiple_contracts = parsed_signal()
        multiple_contracts["watchlist_proposal"]["contracts"].append(
            {"chain": "bsc", "address": OTHER}
        )
        self.assertFalse(
            collector.proposal_suppression(multiple_contracts, self.watchlist)[
                "suppressed"
            ]
        )
        malformed_shape = parsed_signal(contract=None)
        malformed_shape["watchlist_proposal"]["contracts"] = {"address": KII}
        self.assertFalse(
            collector.proposal_suppression(malformed_shape, self.watchlist)[
                "suppressed"
            ]
        )

    def test_symbol_only_requires_unique_alias_and_unique_canonical_identity(self) -> None:
        parsed = parsed_signal(contract=None)
        self.assertEqual(
            collector.proposal_suppression(parsed, self.watchlist)["match_method"],
            "symbol_alias",
        )
        parsed["addresses"] = [{"chain": "bsc", "address": OTHER, "label_hint": "hook"}]
        self.assertEqual(
            collector.proposal_suppression(parsed, self.watchlist)["match_method"],
            "symbol_alias",
        )

        ambiguous = {
            "items": [
                watchlist_item(),
                watchlist_item("OTHER", contract=OTHER, aliases=["KII"]),
            ]
        }
        self.assertFalse(
            collector.proposal_suppression(parsed, ambiguous)["suppressed"]
        )

        multiple_identities = {"items": [watchlist_item()]}
        multiple_identities["items"][0]["contracts"].append(
            {"chain": "base", "address": OTHER}
        )
        self.assertFalse(
            collector.proposal_suppression(parsed, multiple_identities)[
                "suppressed"
            ]
        )

    def test_risk_alerts_remain_push_eligible(self) -> None:
        parsed = parsed_signal(authority="monitoring_risk_alert")
        self.assertFalse(
            collector.proposal_suppression(parsed, self.watchlist)["suppressed"]
        )
        with mock.patch.object(
            collector,
            "load_current_watchlist",
            return_value=self.watchlist,
        ):
            self.assertTrue(collector.should_push(parsed, private_chat=False))

    def test_user_session_secondary_push_uses_automatic_policy_boundary(self) -> None:
        source = (
            collector.ROOT / "scripts/telegram_user_signal_collector.py"
        ).read_text(encoding="utf-8")
        self.assertIn("should_push(parsed, False)", source)
        self.assertLess(source.index("apply_proposals(parsed)"), source.index("should_push(parsed, False)"))

    def test_missing_or_malformed_policy_keeps_proposal_visible(self) -> None:
        parsed = parsed_signal()
        for policy in (
            None,
            {},
            {"mode": "manual_research_managed"},
            {
                "mode": "manual_research_managed",
                "suppress_discovery_proposals": False,
            },
        ):
            item = watchlist_item()
            if policy is None:
                item.pop("proposal_policy")
            else:
                item["proposal_policy"] = policy
            payload = {"items": [item]}
            with self.subTest(policy=policy):
                decision = collector.proposal_suppression(parsed, payload)
                self.assertFalse(decision["suppressed"])
                self.assertEqual(
                    decision["reason"],
                    "manual_research_policy_not_enabled",
                )

    def test_unreadable_watchlist_fails_open_with_observable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "watchlist.json"
            path.write_text("{malformed", encoding="utf-8")
            with mock.patch.object(collector, "WATCHLIST_PATH", path):
                decision = collector.proposal_suppression(parsed_signal())
                self.assertFalse(decision["suppressed"])
                self.assertEqual(
                    decision["reason"],
                    "current_watchlist_unreadable",
                )
                self.assertTrue(
                    collector.should_push(parsed_signal(), private_chat=False)
                )

    def test_flush_rechecks_policy_and_drops_newly_suppressed_pending_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            out_dir.mkdir()
            pending_path = root / "pending.json"
            watchlist_path = root / "watchlist.json"
            artifact = "kii-public.json"
            direct_artifact = "kii-direct.json"
            legacy_artifact = "kii-legacy.json"
            (out_dir / artifact).write_text(
                json.dumps(parsed_signal()),
                encoding="utf-8",
            )
            (out_dir / direct_artifact).write_text(
                json.dumps(parsed_signal()),
                encoding="utf-8",
            )
            (out_dir / legacy_artifact).write_text(
                json.dumps(parsed_signal()),
                encoding="utf-8",
            )
            pending_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "update_id": 7,
                                "analysis_artifact": artifact,
                                "applied": False,
                                "private_chat": False,
                            },
                            {
                                "update_id": 8,
                                "analysis_artifact": direct_artifact,
                                "applied": False,
                                "private_chat": True,
                            },
                            {
                                "update_id": 6,
                                "analysis_artifact": legacy_artifact,
                                "applied": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            watchlist_path.write_text(
                json.dumps(self.watchlist),
                encoding="utf-8",
            )
            sent: list[str] = []
            watchlist_loader = mock.Mock(return_value=self.watchlist)

            with (
                mock.patch.object(collector, "OUT_DIR", out_dir),
                mock.patch.object(collector, "PENDING_PATH", pending_path),
                mock.patch.object(collector, "WATCHLIST_PATH", watchlist_path),
                mock.patch.object(
                    collector,
                    "load_current_watchlist",
                    watchlist_loader,
                ),
                mock.patch.object(
                    collector,
                    "send_message",
                    side_effect=lambda *_args: sent.append("sent") or {"ok": True},
                ),
                mock.patch.dict(
                    collector.os.environ,
                    {"SIGNAL_ANALYSIS_CHAT_ID": "fixture-chat"},
                    clear=False,
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(collector.flush_pending_analysis("token"), 0)

            self.assertEqual(sent, ["sent", "sent"])
            self.assertEqual(json.loads(pending_path.read_text())["items"], [])
            self.assertEqual(json.loads(output.getvalue())["suppressed"], 1)
            watchlist_loader.assert_called_once()

    def test_direct_deferred_reply_keeps_apply_and_trusted_private_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out_dir = root / "out"
            pending_path = root / "pending.json"
            apply = mock.Mock()
            process_parsed = parsed_signal()
            process_parsed["txs"] = ["0x" + "2" * 64]
            update = {
                "update_id": 9,
                "message": {
                    "message_id": 3,
                    "text": "Binance Alpha KII contract",
                    "chat": {"id": 99, "type": "private"},
                },
            }
            with (
                mock.patch.object(collector, "OUT_DIR", out_dir),
                mock.patch.object(collector, "PENDING_PATH", pending_path),
                mock.patch.object(
                    collector,
                    "save_signal",
                    return_value=root / "telegram_9.txt",
                ),
                mock.patch.object(
                    collector,
                    "parse_signal",
                    return_value=copy.deepcopy(process_parsed),
                ),
                mock.patch.object(
                    collector,
                    "maybe_enrich_chain",
                    side_effect=lambda parsed: parsed,
                ),
                mock.patch.object(
                    collector,
                    "merge_signal",
                    return_value={"status": "new_project"},
                ),
                mock.patch.object(collector, "render_markdown", return_value="fixture"),
                mock.patch.object(collector, "apply_proposals", apply),
                mock.patch.object(
                    collector,
                    "load_current_watchlist",
                    return_value=self.watchlist,
                ),
                mock.patch.dict(
                    collector.os.environ,
                    {
                        "SIGNAL_ANALYSIS_CHAT_ID": "fixture-chat",
                        "SIGNAL_AUTO_APPLY": "1",
                    },
                    clear=False,
                ),
            ):
                result = collector.process_update(
                    "token",
                    update,
                    defer_analysis=True,
                )
                collector.append_pending_analysis(
                    [{"update_id": update["update_id"], **result}]
                )
                apply.assert_called_once()
                apply.reset_mock()
                secondary = copy.deepcopy(update)
                secondary["update_id"] = 10
                secondary["message"]["chat"]["type"] = "channel"
                secondary_result = collector.process_update(
                    "token",
                    secondary,
                    defer_analysis=True,
                )
                apply.assert_called_once()

            self.assertTrue(result["applied"])
            self.assertEqual(
                result["proposal_suppression_reason"],
                "manual_research_managed",
            )
            self.assertTrue(result["private_chat"])
            self.assertTrue(result["analysis_deferred"])
            self.assertTrue(secondary_result["applied"])
            self.assertFalse(secondary_result["pushed"])
            self.assertFalse(secondary_result["analysis_deferred"])
            queued = json.loads(pending_path.read_text(encoding="utf-8"))["items"]
            self.assertTrue(queued[0]["private_chat"])

    def test_current_kii_configuration_explicitly_enables_takeover(self) -> None:
        payload = json.loads(
            (collector.ROOT / "config/current_alpha_watchlist.json").read_text(
                encoding="utf-8"
            )
        )
        kii = next(row for row in payload["items"] if row.get("symbol") == "KII")
        self.assertEqual(
            kii.get("proposal_policy"),
            {
                "mode": "manual_research_managed",
                "suppress_discovery_proposals": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
