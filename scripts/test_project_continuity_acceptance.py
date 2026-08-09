#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from project_continuity_acceptance import (
    DEPLOY_PARITY_PATHS,
    REMOTE_PROBE,
    build_remote_command,
    evaluate,
    path_matches_any,
    render_markdown,
    run_json,
)

HISTORICAL_SCOPE_RECONCILE_IDS = (
    "2889857dc0b23b492d8949eae9e59049f937783af86ea6ae40822d5744bc2a8f",
    "b58cec136e8bdfc76e7739f9c5789bd4f60abafcbf5589a2cd6a671e37b5758e",
    "21e9f32ff27150b7d5241e90279327e37a37fd79b8e1f493deb45d94142b5b32",
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def remote_probe_fixture(root: Path) -> tuple[dict[str, str], Path]:
    expected_hashes: dict[str, str] = {}
    for index, relative_path in enumerate(DEPLOY_PARITY_PATHS):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture-{index}\n", encoding="utf-8")
        expected_hashes[relative_path] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    write_json(
        root / "output/runtime_health/last_cycle.json",
        {
            "schema": "runtime_health.v1",
            "status": "healthy",
            "generated_at": "2026-08-07T00:00:00+00:00",
            "issue_count": 0,
            "issues": [],
        },
    )
    verification = root / "output/sniper_engine/verification_report.md"
    verification.parent.mkdir(parents=True, exist_ok=True)
    verification.write_text("| fixture | PASS | ok |\n", encoding="utf-8")
    write_json(
        root / "config/current_alpha_watchlist.json",
        {
            "items": [
                {
                    "symbol": "GRVT",
                    "contracts": [
                        {
                            "chain": "bsc",
                            "address": "0x" + "a" * 40,
                            "confidence": "high",
                        }
                    ],
                }
            ]
        },
    )
    watchlist_path = root / "config/current_alpha_watchlist.json"
    if "config/current_alpha_watchlist.json" in expected_hashes:
        expected_hashes["config/current_alpha_watchlist.json"] = (
            hashlib.sha256(watchlist_path.read_bytes()).hexdigest()
        )
    write_json(
        root / "output/alpha_liquidity_retention_watch/latest.json",
        {
            "status": "healthy",
            "issue_count": 0,
            "complete_count": 1,
            "alert_ready_count": 1,
            "projects": [
                {
                    "symbol": "GRVT",
                    "retention_flow": {
                        "liquidity_retention": {
                            "continuous": True,
                            "latest_block": 1,
                            "target_latest_block": 1,
                        }
                    },
                }
            ],
        },
    )
    write_json(
        root / "output/alpha_liquidity_retention_watch/state.json",
        {"tokens": {}},
    )
    write_json(
        root / "output/alpha_holder_concentration_watch/latest.json",
        {"projects": []},
    )
    write_json(
        root / "output/alpha_holder_concentration_watch/seen_alerts.json",
        [],
    )
    write_json(
        root / "output/alpha_liquidity_retention_watch/last_push.json",
        {},
    )
    write_json(
        root / "output/alpha_intraday_flow_watch/latest.json",
        {"generated_at": "2026-08-09T00:00:00+00:00", "event_count": 0, "alert_count": 0},
    )
    write_json(
        root / "output/alpha_intraday_flow_watch/cex_micro_gas_candidate_history.json",
        {
            "schema": "cex_micro_gas_candidate_history.v1",
            "candidate_count": 0,
            "candidates": [],
        },
    )
    write_json(
        root / "output/alpha_intraday_flow_watch/withdrawal_candidate_history.json",
        {"schema_version": 1, "candidate_count": 0, "candidates": []},
    )
    replay_path = (
        root / "output/grvt_liquidity_replay_acceptance/latest.json"
    )
    write_json(
        replay_path,
        {
            "schema": "grvt_liquidity_replay_acceptance.v1",
            "status": "pass",
            "issues": [],
            "generated_at": "2026-08-07T00:00:00+00:00",
            "receipt_count": 2,
            "elapsed_seconds": 80,
            "classification": "range_repositioned",
            "range_changed": True,
            "source_pool_equals_destination_pool": True,
            "operator_basis": "transaction_sender_eoa",
            "quote_boundary_complete": True,
            "relative_materiality_proven": True,
            "raw_removal_alert_eligible": False,
            "pending_count": 0,
            "normal_replay_dedup_pass": True,
            "first_send_count": 1,
            "replay_duplicate_send_count": 0,
            "code_hashes": expected_hashes,
        },
    )
    return expected_hashes, replay_path


def run_remote_probe(root: Path, expected_hashes: dict[str, str]) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            REMOTE_PROBE,
            str(root),
            "1200",
            json.dumps(expected_hashes, sort_keys=True),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def write_reconciliation_fixture(
    root: Path,
    *,
    pending: list[dict] | None = None,
    completed: list[dict] | None = None,
    sent_reconcile_ids: list[str] | None = None,
) -> None:
    chain = "bsc"
    token = "0x" + "a" * 40
    write_json(
        root / "output/alpha_liquidity_retention_watch/state.json",
        {
            "tokens": {
                f"{chain}:{token}": {
                    "liquidity": {
                        "reconciliation": {
                            "pending": pending or [],
                            "completed": completed or [],
                        }
                    }
                }
            }
        },
    )
    write_json(
        root / "output/alpha_holder_concentration_watch/seen_alerts.json",
        [
            "|".join(
                (chain, token, "liquidity_reconciliation", reconcile_id)
            )
            for reconcile_id in (sent_reconcile_ids or [])
        ],
    )


def v2_scope_final(reconcile_id: str = "1" * 64) -> dict:
    return {
        "reconcile_id": reconcile_id,
        "verdict_coverage_contract_version": (
            "liquidity_verdict_coverage.v2"
        ),
        "classification": "range_repositioned",
        "completed_at": "2026-08-09T13:00:00+00:00",
        "first_seen_at": "2026-08-09T12:45:00+00:00",
        "source_event_utc": "2026-08-09T12:45:00+00:00",
        "source_block": 101,
        "reconciliation_window_seconds": 900,
        "observation_age_seconds": 900,
        "chain_age_seconds": 900,
        "evidence_level": (
            "core_receipt_canonical_next_hop_observed_partial"
        ),
        "source_receipt_canonical": True,
        "active_range_vs_spot": "active",
        "spot_tick": 0,
        "pool_liquidity_before": "1000",
        "pool_liquidity_after": "900",
        "price_reaction_5m_pct": "-1.25",
        "price_reaction_15m_pct": "-3.5",
        "verdict_coverage_complete": True,
        "enrichment_coverage_complete": False,
        "evidence_coverage_issues": [
            "recipient_next_hop_scope_exceeded"
        ],
        "recipient_next_hop": {
            "status": "high_activity_unattributed",
            "coverage_complete": False,
            "attribution_complete": False,
            "existence_complete": True,
            "enumeration_complete": False,
            "recipient_count": 1,
            "canonical_transaction_count": 16,
            "observed_transaction_count_lower_bound": 17,
            "scope_limit": 16,
        },
    }


def v2_full_final(reconcile_id: str = "2" * 64) -> dict:
    row = v2_scope_final(reconcile_id)
    row.update(
        {
            "enrichment_coverage_complete": True,
            "evidence_coverage_issues": [],
            "evidence_level": "receipt_canonical_bounded_15m",
            "recipient_next_hop": {
                "status": "no_outbound_observed",
                "coverage_complete": True,
                "attribution_complete": False,
                "existence_complete": True,
                "enumeration_complete": True,
                "recipient_count": 1,
                "canonical_transaction_count": 0,
                "observed_transaction_count_lower_bound": 0,
                "scope_limit": 16,
            },
        }
    )
    return row


def healthy_snapshot() -> dict:
    return {
        "schema": "sniper_project_continuity_acceptance.v1",
        "generated_at": "2026-07-10T00:00:00+00:00",
        "project_id": "sniper-monitor",
        "continuity": {
            "severity": "healthy",
            "reasons": [],
            "conversation_id": "test-conversation",
            "checkpoint_id": "test-checkpoint",
            "checkpoint_hash_valid": True,
            "checkpoint_git_head": "abc123",
            "checkpoint_matches_head": True,
            "audit_status": "pass",
            "audit_failed_count": 0,
        },
        "repository": {
            "head": "abc123",
            "branch": "main",
            "dirty": False,
            "status_lines": [],
            "missing_tracked_required": [],
            "tracked_denied_paths": [],
            "context_boundary_violations": [],
        },
        "local_runtime": {
            "runtime_status": "healthy",
            "runtime_generated_at": "2026-07-10T00:00:00+00:00",
            "runtime_age_seconds": 10,
            "runtime_issue_count": 0,
            "verification_exists": True,
            "verification_fail_count": 0,
            "watchlist_item_count": 3,
        },
        "remote_runtime": {"status": "not_requested"},
        "command_errors": [],
    }


class ProjectContinuityAcceptanceTests(unittest.TestCase):
    def test_denied_globs_cover_secret_and_session_paths(self) -> None:
        patterns = [".deploy/**", ".env", ".env.*", "**/*.pem", "**/*.key", "**/*.session"]
        self.assertTrue(path_matches_any(".deploy/server_key", patterns))
        self.assertTrue(path_matches_any("nested/private.pem", patterns))
        self.assertTrue(path_matches_any("state/user.session", patterns))
        self.assertTrue(path_matches_any(".env.local", patterns))
        self.assertFalse(path_matches_any("docs/server_runbook.md", patterns))

    def test_healthy_local_acceptance_passes(self) -> None:
        payload = evaluate(healthy_snapshot(), allow_dirty=False, remote_required=False)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["issues"], [])

    def test_stale_checkpoint_and_tracked_secret_fail(self) -> None:
        snapshot = healthy_snapshot()
        snapshot["continuity"]["checkpoint_matches_head"] = False
        snapshot["repository"]["tracked_denied_paths"] = [".env.local"]
        payload = evaluate(snapshot, allow_dirty=False, remote_required=False)
        codes = {row["code"] for row in payload["issues"]}
        self.assertEqual(payload["status"], "fail")
        self.assertIn("checkpoint_stale", codes)
        self.assertIn("denied_path_tracked", codes)

    def test_remote_acceptance_is_required_when_requested(self) -> None:
        snapshot = healthy_snapshot()
        snapshot["remote_runtime"] = {"status": "fail"}
        payload = evaluate(snapshot, allow_dirty=False, remote_required=True)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("remote_runtime_failed", {row["code"] for row in payload["issues"]})

    def test_remote_payload_is_allowlisted_before_persistence(self) -> None:
        marker = "sensitive-connection-material"
        snapshot = healthy_snapshot()
        snapshot["remote_runtime"] = {
            "status": "pass",
            "secret_free_text": marker,
        }
        payload = evaluate(snapshot, allow_dirty=False, remote_required=True)
        self.assertEqual(payload["status"], "fail")
        self.assertIn(
            "remote_runtime_failed",
            {row["code"] for row in payload["issues"]},
        )
        self.assertNotIn(marker, json.dumps(payload, sort_keys=True))
        self.assertEqual(
            payload["remote_runtime"],
            {
                "schema": "sniper_remote_health_acceptance.v1",
                "status": "error",
            },
        )

    def test_valid_remote_probe_survives_outer_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            remote_payload = run_remote_probe(root, expected_hashes)
        snapshot = healthy_snapshot()
        snapshot["remote_runtime"] = remote_payload
        payload = evaluate(snapshot, allow_dirty=False, remote_required=True)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["issues"], [])
        self.assertEqual(
            payload["remote_runtime"]["schema"],
            "sniper_remote_health_acceptance.v1",
        )

    def test_remote_nested_free_text_never_persists(self) -> None:
        marker = "synthetic_secret_api_key_abc123"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            remote_payload = run_remote_probe(root, expected_hashes)

        holder_payload = json.loads(json.dumps(remote_payload))
        holder_payload["grvt_holder"]["error_code"] = marker
        holder_snapshot = healthy_snapshot()
        holder_snapshot["remote_runtime"] = holder_payload
        holder_result = evaluate(
            holder_snapshot,
            allow_dirty=False,
            remote_required=True,
        )
        self.assertEqual(holder_result["status"], "fail")
        self.assertNotIn(marker, json.dumps(holder_result, sort_keys=True))

        issue_payload = json.loads(json.dumps(remote_payload))
        issue_payload["status"] = "fail"
        issue_payload["runtime_issue_count"] = 1
        issue_payload["runtime_issue_codes"] = [marker]
        issue_payload["runtime_issue_summaries"] = [
            {
                "kind": marker,
                "name_hash": "0" * 16,
                "fingerprint_hash": "2" * 16,
                "scope": "",
                "reason": "",
                "error_code": "",
                "contract_hash": "4" * 16,
            }
        ]
        issue_payload["grvt_replay_acceptance"]["status"] = "fail"
        issue_payload["grvt_replay_acceptance"]["issues"] = [marker]
        issue_snapshot = healthy_snapshot()
        issue_snapshot["remote_runtime"] = issue_payload
        issue_result = evaluate(
            issue_snapshot,
            allow_dirty=False,
            remote_required=True,
        )
        self.assertEqual(issue_result["status"], "fail")
        rendered = json.dumps(issue_result, sort_keys=True)
        self.assertNotIn(marker, rendered)
        self.assertIn("issue_present", rendered)

        recognized_payload = json.loads(json.dumps(remote_payload))
        recognized_payload["status"] = "fail"
        recognized_payload["runtime_issue_count"] = 1
        recognized_payload["runtime_issue_codes"] = ["alpha_coverage_gap"]
        recognized_payload["runtime_issue_summaries"] = [
            {
                "kind": "alpha_coverage_gap",
                "name_hash": "1" * 16,
                "fingerprint_hash": "3" * 16,
                "scope": "holder",
                "reason": "",
                "error_code": "",
                "contract_hash": "5" * 16,
            }
        ]
        recognized_snapshot = healthy_snapshot()
        recognized_snapshot["remote_runtime"] = recognized_payload
        recognized_result = evaluate(
            recognized_snapshot,
            allow_dirty=False,
            remote_required=True,
        )
        self.assertEqual(
            recognized_result["remote_runtime"]["runtime_issue_codes"],
            ["alpha_coverage_gap"],
        )

    def test_outer_remote_contract_rejects_forged_typed_fields(self) -> None:
        marker = "synthetic_private_key_material"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            remote_payload = run_remote_probe(root, expected_hashes)

        mutations = {
            "runtime_age": lambda row: row.update(
                {"runtime_age_seconds": 1201}
            ),
            "parity_count": lambda row: row.update(
                {
                    "deployed_hash_expected_count": 1,
                    "deployed_hash_parity_count": 1,
                }
            ),
            "activation_time": lambda row: row["grvt_liquidity"][
                "verdict_coverage_contract"
            ].update({"activated_at_utc": "2030-01-01T00:00:00+00:00"}),
            "optional_int": lambda row: row["grvt_liquidity"].update(
                {"alert_count": marker}
            ),
            "holder_int": lambda row: row["grvt_holder"].update(
                {"latest_block": {"value": marker}}
            ),
            "timestamp_overflow": lambda row: row.update(
                {"runtime_generated_at": "0001-01-01T00:00:00+14:00"}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = json.loads(json.dumps(remote_payload))
                mutate(candidate)
                snapshot = healthy_snapshot()
                snapshot["remote_runtime"] = candidate
                result = evaluate(
                    snapshot,
                    allow_dirty=False,
                    remote_required=True,
                )
                self.assertEqual(result["status"], "fail")
                self.assertNotIn(
                    marker,
                    json.dumps(result, sort_keys=True),
                )

    def test_outer_remote_runtime_age_uses_policy_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            remote_payload = run_remote_probe(root, expected_hashes)
        remote_payload["runtime_age_seconds"] = 11
        snapshot = healthy_snapshot()
        snapshot["remote_runtime"] = remote_payload
        payload = evaluate(
            snapshot,
            allow_dirty=False,
            remote_required=True,
            remote_max_age_seconds=10,
        )
        self.assertEqual(payload["status"], "fail")

    def test_outer_accepts_old_replay_when_contract_hashes_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, replay_path = remote_probe_fixture(root)
            stale = time.time() - 86400
            os.utime(replay_path, (stale, stale))
            remote_payload = run_remote_probe(root, expected_hashes)
        self.assertGreater(
            remote_payload["grvt_replay_acceptance"]["age_seconds"],
            1200,
        )
        snapshot = healthy_snapshot()
        snapshot["remote_runtime"] = remote_payload
        payload = evaluate(snapshot, allow_dirty=False, remote_required=True)
        self.assertEqual(payload["status"], "pass")

    def test_missing_local_verification_fails(self) -> None:
        snapshot = healthy_snapshot()
        snapshot["local_runtime"]["verification_exists"] = False
        payload = evaluate(snapshot, allow_dirty=False, remote_required=False)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("local_verification_missing", {row["code"] for row in payload["issues"]})

    def test_remote_command_uses_fixed_probe_without_file_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = Path(temporary) / "config"
            deploy_dir = Path(temporary) / ".deploy"
            config_dir.mkdir()
            deploy_dir.mkdir()
            (deploy_dir / "identity").write_text("test", encoding="utf-8")
            (deploy_dir / "known_hosts").write_text("test", encoding="utf-8")
            command = build_remote_command(
                config_dir / "project_continuity.json",
                {
                    "host": "user@example.test",
                    "project_root": "/srv/sniper",
                    "identity_file": "../.deploy/identity",
                    "known_hosts_file": "../.deploy/known_hosts",
                    "max_cycle_age_seconds": 1200,
                },
            )
        rendered = " ".join(command)
        self.assertIn("StrictHostKeyChecking=yes", rendered)
        self.assertIn("runtime_health", rendered)
        self.assertIn("reconciliation_events_since_enriched_deploy", rendered)
        self.assertIn("2026-08-06T15:33:40+00:00", rendered)
        self.assertIn("seen_alerts.json", rendered)
        self.assertIn("last_push.json", rendered)
        self.assertIn("evidence_coverage_issues", rendered)
        self.assertIn("source_chain_timestamp_basis", rendered)
        self.assertIn("natural_evidence_watch", rendered)
        self.assertIn("cex_micro_gas_candidate_history", rendered)
        self.assertIn("withdrawal_candidate_history", rendered)
        self.assertIn("liquidity_verdict_coverage.v2", rendered)
        self.assertIn("v2_invalid_or_unsent_final_count", rendered)
        self.assertNotIn("source_tx_prefix", rendered)
        self.assertNotIn("find ", rendered)
        self.assertNotIn("rg ", rendered)
        self.assertNotIn("cat ", rendered)

    def test_remote_probe_requires_fresh_complete_grvt_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            payload = run_remote_probe(root, expected_hashes)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["grvt_replay_acceptance"]["contract_pass"])
        self.assertTrue(
            payload["natural_evidence_watch"]
            ["cex_micro_gas_candidate_history"]["valid"]
        )
        self.assertEqual(
            payload["natural_evidence_watch"]
            ["cex_withdrawal_candidate_history"]["candidate_count"],
            0,
        )
        self.assertEqual(
            payload["natural_evidence_watch"]["intraday_event_count"], 0
        )
        self.assertEqual(
            payload["grvt_liquidity"]["verdict_coverage_contract"],
            {
                "version": "liquidity_verdict_coverage.v2",
                "activated_at_utc": "2026-08-09T12:41:07+00:00",
                "historical_unversioned_scope_count": 0,
                "v2_scope_pending_count": 0,
                "v2_scope_unresolved_count": 0,
                "v2_scope_legal_final_count": 0,
                "v2_full_final_count": 0,
                "v2_invalid_or_unsent_final_count": 0,
                "v2_invalid_pending_count": 0,
                "missing_contract_version_count": 0,
                "unsupported_contract_version_count": 0,
                "reconciliation_shape_invalid_count": 0,
                "pass": True,
            },
        )

    def test_remote_probe_ignores_three_historical_unversioned_scope_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            historical = [
                {
                    "reconcile_id": reconcile_id,
                    "classification": "unresolved_coverage",
                    "completed_at": f"2026-08-08T0{index}:00:00+00:00",
                    "evidence_coverage_issues": [
                        "recipient_next_hop_scope_exceeded"
                    ],
                }
                for index, reconcile_id in enumerate(
                    HISTORICAL_SCOPE_RECONCILE_IDS
                )
            ]
            write_reconciliation_fixture(root, completed=historical)
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(contract["historical_unversioned_scope_count"], 3)
        self.assertEqual(contract["v2_scope_unresolved_count"], 0)
        self.assertTrue(contract["pass"])

    def test_remote_probe_rejects_historical_scope_row_with_extra_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = {
                "reconcile_id": HISTORICAL_SCOPE_RECONCILE_IDS[0],
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-08T01:00:00+00:00",
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded",
                    "recipient_next_hop_receipt_invalid",
                ],
            }
            write_reconciliation_fixture(root, completed=[row])
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["historical_unversioned_scope_count"], 0)
        self.assertEqual(contract["missing_contract_version_count"], 1)

    def test_remote_probe_rejects_historical_scope_prefix_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = {
                "reconcile_id": "2889857dc0b2" + "0" * 52,
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-08T01:00:00+00:00",
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            write_reconciliation_fixture(root, completed=[row])
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["historical_unversioned_scope_count"], 0)
        self.assertEqual(contract["missing_contract_version_count"], 1)

    def test_remote_probe_rejects_duplicate_historical_scope_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = {
                "reconcile_id": HISTORICAL_SCOPE_RECONCILE_IDS[0],
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-08T01:00:00+00:00",
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            write_reconciliation_fixture(
                root,
                completed=[dict(row), dict(row)],
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["historical_unversioned_scope_count"], 0)
        self.assertEqual(contract["missing_contract_version_count"], 2)

    def test_remote_probe_rejects_historical_id_reused_by_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            reconcile_id = HISTORICAL_SCOPE_RECONCILE_IDS[0]
            completed = {
                "reconcile_id": reconcile_id,
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-08T01:00:00+00:00",
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            pending = {
                "reconcile_id": reconcile_id,
                "verdict_coverage_contract_version": (
                    "liquidity_verdict_coverage.v2"
                ),
                "first_seen_at": "2026-08-09T13:00:00+00:00",
                "evidence_coverage_issues": [],
            }
            write_reconciliation_fixture(
                root,
                pending=[pending],
                completed=[completed],
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["historical_unversioned_scope_count"], 0)
        self.assertEqual(contract["missing_contract_version_count"], 1)

    def test_remote_probe_rejects_historical_id_outside_grvt_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = {
                "reconcile_id": HISTORICAL_SCOPE_RECONCILE_IDS[0],
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-08T01:00:00+00:00",
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            write_json(
                root / "output/alpha_liquidity_retention_watch/state.json",
                {
                    "tokens": {
                        "ethereum:0x" + "b" * 40: {
                            "liquidity": {
                                "reconciliation": {
                                    "pending": [],
                                    "completed": [row],
                                }
                            }
                        }
                    }
                },
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["historical_unversioned_scope_count"], 0)
        self.assertEqual(contract["missing_contract_version_count"], 1)

    def test_remote_probe_accepts_sent_v2_high_activity_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = v2_scope_final()
            write_reconciliation_fixture(
                root,
                completed=[row],
                sent_reconcile_ids=[row["reconcile_id"]],
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(contract["v2_scope_legal_final_count"], 1)
        self.assertEqual(contract["v2_invalid_or_unsent_final_count"], 0)
        self.assertTrue(contract["pass"])
        event = payload["grvt_liquidity"][
            "reconciliation_events_since_enriched_deploy"
        ][0]
        self.assertNotIn("source_tx", event)
        self.assertNotIn("source_tx_prefix", event)

    def test_remote_probe_accepts_v2_full_final_with_empty_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = v2_full_final()
            write_reconciliation_fixture(
                root,
                completed=[row],
                sent_reconcile_ids=[row["reconcile_id"]],
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(contract["v2_full_final_count"], 1)
        self.assertTrue(contract["pass"])

    def test_remote_probe_rejects_v2_scope_pending_and_unresolved_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            pending = {
                "reconcile_id": "3" * 64,
                "first_seen_at": "2026-08-09T01:00:00+00:00",
                "verdict_coverage_contract_version": (
                    "liquidity_verdict_coverage.v2"
                ),
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            unresolved = {
                "reconcile_id": "4" * 64,
                "classification": "unresolved_coverage",
                "completed_at": "2026-08-09T01:15:00+00:00",
                "verdict_coverage_contract_version": (
                    "liquidity_verdict_coverage.v2"
                ),
                "evidence_coverage_issues": [
                    "recipient_next_hop_scope_exceeded"
                ],
            }
            write_reconciliation_fixture(
                root,
                pending=[pending],
                completed=[unresolved],
            )
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["v2_scope_pending_count"], 1)
        self.assertEqual(contract["v2_scope_unresolved_count"], 1)
        self.assertFalse(contract["pass"])

    def test_remote_probe_rejects_invalid_or_unsent_v2_scope_final(self) -> None:
        cases = (
            ("unsent", False, None),
            ("invalid", True, ("enumeration_complete", True)),
        )
        for index, (name, sent, mutation) in enumerate(cases, start=5):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expected_hashes, _ = remote_probe_fixture(root)
                row = v2_scope_final(f"{index:x}" * 64)
                if mutation is not None:
                    field, value = mutation
                    row["recipient_next_hop"][field] = value
                write_reconciliation_fixture(
                    root,
                    completed=[row],
                    sent_reconcile_ids=(
                        [row["reconcile_id"]] if sent else []
                    ),
                )
                payload = run_remote_probe(root, expected_hashes)
            contract = payload["grvt_liquidity"][
                "verdict_coverage_contract"
            ]
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(
                contract["v2_invalid_or_unsent_final_count"], 1
            )
            self.assertFalse(contract["pass"])

    def test_remote_probe_rejects_unknown_scope_contract_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            row = v2_scope_final("7" * 64)
            row["verdict_coverage_contract_version"] = (
                "liquidity_verdict_coverage.v3"
            )
            write_reconciliation_fixture(root, completed=[row])
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["unsupported_contract_version_count"], 1)
        self.assertFalse(contract["pass"])

    def test_remote_probe_rejects_v2_other_issue_or_invalid_recipient_count(self) -> None:
        cases = ("other_issue", "recipient_count_zero", "recipient_count_high")
        for index, name in enumerate(cases, start=8):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expected_hashes, _ = remote_probe_fixture(root)
                row = v2_scope_final(f"{index:x}" * 64)
                if name == "other_issue":
                    row["evidence_coverage_issues"] = [
                        "price_reaction_coverage_incomplete"
                    ]
                else:
                    row["recipient_next_hop"]["recipient_count"] = (
                        0 if name == "recipient_count_zero" else 9
                    )
                write_reconciliation_fixture(
                    root,
                    completed=[row],
                    sent_reconcile_ids=[row["reconcile_id"]],
                )
                payload = run_remote_probe(root, expected_hashes)
            contract = payload["grvt_liquidity"][
                "verdict_coverage_contract"
            ]
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(
                contract["v2_invalid_or_unsent_final_count"], 1
            )
            self.assertFalse(contract["pass"])

    def test_remote_probe_rejects_incomplete_v2_full_and_partial_contracts(self) -> None:
        cases = (
            ("full_missing_receipt", "full", "source_receipt_canonical", None),
            ("full_nan_price", "full", "price_reaction_5m_pct", "NaN"),
            ("full_status_count", "full", "recipient_status", "outbound_observed"),
            ("partial_missing_level", "partial", "evidence_level", None),
            ("partial_missing_pool", "partial", "pool_liquidity_before", None),
            ("partial_infinite_price", "partial", "price_reaction_15m_pct", "Infinity"),
            ("full_missing_completed", "full", "completed_at", None),
            ("partial_missing_first_seen", "partial", "first_seen_at", None),
            ("full_missing_source_block", "full", "source_block", None),
            ("partial_wrong_window", "partial", "reconciliation_window_seconds", 901),
        )
        for name, kind, field, value in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expected_hashes, _ = remote_probe_fixture(root)
                row = (
                    v2_full_final(hashlib.sha256(name.encode()).hexdigest())
                    if kind == "full"
                    else v2_scope_final(hashlib.sha256(name.encode()).hexdigest())
                )
                if field == "recipient_status":
                    row["recipient_next_hop"]["status"] = value
                elif value is None:
                    row.pop(field)
                else:
                    row[field] = value
                write_reconciliation_fixture(
                    root,
                    completed=[row],
                    sent_reconcile_ids=[row["reconcile_id"]],
                )
                payload = run_remote_probe(root, expected_hashes)
            contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(contract["v2_invalid_or_unsent_final_count"], 1)

    def test_remote_probe_rejects_unsent_full_and_v2_pending_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            full = v2_full_final("d" * 64)
            pending = {
                "reconcile_id": "e" * 64,
                "first_seen_at": "2026-08-09T12:42:00+00:00",
                "verdict_coverage_contract_version": "liquidity_verdict_coverage.v2",
                "evidence_coverage_issues": ["recipient_next_hop_receipt_invalid"],
            }
            write_reconciliation_fixture(root, pending=[pending], completed=[full])
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["v2_invalid_or_unsent_final_count"], 1)
        self.assertEqual(contract["v2_invalid_pending_count"], 1)

    def test_remote_probe_rejects_unversioned_or_unsanitizable_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            pending = [
                {
                    "reconcile_id": "a" * 64,
                    "first_seen_at": "2026-08-08T00:00:00+00:00",
                    "evidence_coverage_issues": [],
                },
                {
                    "reconcile_id": "b" * 64,
                    "first_seen_at": "2026-08-09T12:42:00+00:00",
                    "verdict_coverage_contract_version": (
                        "liquidity_verdict_coverage.v2"
                    ),
                    "evidence_coverage_issues": ["not/a/code"],
                },
                {
                    "reconcile_id": "c" * 64,
                    "verdict_coverage_contract_version": (
                        "liquidity_verdict_coverage.v2"
                    ),
                    "evidence_coverage_issues": [],
                },
            ]
            write_reconciliation_fixture(root, pending=pending)
            payload = run_remote_probe(root, expected_hashes)
        contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(contract["missing_contract_version_count"], 1)
        self.assertEqual(contract["v2_invalid_pending_count"], 2)

    def test_remote_probe_rejects_future_missing_or_any_unknown_contract(self) -> None:
        cases = ("missing", "unknown_full")
        for name in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expected_hashes, _ = remote_probe_fixture(root)
                row = v2_full_final(hashlib.sha256(name.encode()).hexdigest())
                if name == "missing":
                    row.pop("verdict_coverage_contract_version")
                    row["completed_at"] = "2026-08-09T08:00:00-05:00"
                else:
                    row["verdict_coverage_contract_version"] = (
                        "liquidity_verdict_coverage.v3"
                    )
                write_reconciliation_fixture(
                    root,
                    completed=[row],
                    sent_reconcile_ids=[row["reconcile_id"]],
                )
                payload = run_remote_probe(root, expected_hashes)
            contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
            self.assertEqual(payload["status"], "fail")
            expected_field = (
                "missing_contract_version_count"
                if name == "missing"
                else "unsupported_contract_version_count"
            )
            self.assertEqual(contract[expected_field], 1)

    def test_remote_probe_rejects_invalid_reconciliation_shapes(self) -> None:
        cases = (
            {"pending": "invalid", "completed": []},
            {"pending": [], "completed": "invalid"},
            {"pending": ["invalid"], "completed": []},
            {"pending": [], "completed": ["invalid"]},
        )
        for reconciliation in cases:
            with self.subTest(reconciliation=reconciliation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                expected_hashes, _ = remote_probe_fixture(root)
                write_json(
                    root / "output/alpha_liquidity_retention_watch/state.json",
                    {
                        "tokens": {
                            "bsc:fixture-token": {
                                "liquidity": {
                                    "reconciliation": reconciliation
                                }
                            }
                        }
                    },
                )
                payload = run_remote_probe(root, expected_hashes)
            contract = payload["grvt_liquidity"]["verdict_coverage_contract"]
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(contract["reconciliation_shape_invalid_count"], 1)

    def test_remote_probe_does_not_echo_runtime_or_holder_free_text(self) -> None:
        sensitive_values = (
            "192.0.2.10",
            "/private/tmp/.deploy/identity",
            "user@example.test",
            "https://example.test/secret",
            "0xdeadbeef",
            "0x" + "a" * 64,
        )
        injected = " ".join(sensitive_values)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            write_json(
                root / "output/runtime_health/last_cycle.json",
                {
                    "schema": "runtime_health.v1",
                    "status": "healthy",
                    "generated_at": "2026-08-09T00:00:00+00:00",
                    "issue_count": 1,
                    "issues": [{"kind": "192.0.2.10", "name": injected, "detail": injected}],
                },
            )
            write_json(
                root / "output/alpha_holder_concentration_watch/latest.json",
                {
                    "projects": [{
                        "symbol": "GRVT",
                        "error": injected,
                        "coverage_note": injected,
                        "scan_from_block": sensitive_values[1],
                    }]
                },
            )
            liquidity_path = (
                root / "output/alpha_liquidity_retention_watch/latest.json"
            )
            liquidity = json.loads(liquidity_path.read_text(encoding="utf-8"))
            liquidity["alert_count"] = sensitive_values[1]
            write_json(liquidity_path, liquidity)
            write_reconciliation_fixture(
                root,
                pending=[{
                    "reconcile_id": "f" * 64,
                    "first_seen_at": "2026-08-09T12:42:00+00:00",
                    "verdict_coverage_contract_version": (
                        "liquidity_verdict_coverage.v2"
                    ),
                    "evidence_coverage_issues": [sensitive_values[-1]],
                }],
            )
            payload = run_remote_probe(root, expected_hashes)
        rendered = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["status"], "fail")
        for value in sensitive_values:
            self.assertNotIn(value, rendered)

    def test_run_json_never_returns_subprocess_stderr(self) -> None:
        sensitive = "user@example.test 192.0.2.10 /private/tmp/.deploy/identity"
        result = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=255,
            stdout="",
            stderr=sensitive,
        )
        with mock.patch("subprocess.run", return_value=result):
            payload, error = run_json(["ssh"], Path("/tmp"))
        self.assertEqual(payload, {})
        self.assertEqual(error, "exit_nonzero_255")
        self.assertNotIn(sensitive, error)
        snapshot = healthy_snapshot()
        snapshot["command_errors"] = [sensitive]
        evaluated = evaluate(
            snapshot,
            allow_dirty=False,
            remote_required=False,
        )
        self.assertEqual(evaluated["issues"][0]["detail"], "operation_failed")
        self.assertNotIn(sensitive, json.dumps(evaluated))

    def test_remote_probe_rejects_malformed_natural_candidate_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, _ = remote_probe_fixture(root)
            write_json(
                root / "output/alpha_intraday_flow_watch/cex_micro_gas_candidate_history.json",
                {
                    "schema": "cex_micro_gas_candidate_history.v1",
                    "candidate_count": 2,
                    "candidates": [{}],
                },
            )
            payload = run_remote_probe(root, expected_hashes)
        self.assertEqual(payload["status"], "fail")
        self.assertFalse(
            payload["natural_evidence_watch"]
            ["cex_micro_gas_candidate_history"]["valid"]
        )

    def test_remote_probe_rejects_false_grvt_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, replay_path = remote_probe_fixture(root)
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            replay["range_changed"] = False
            write_json(replay_path, replay)
            payload = run_remote_probe(root, expected_hashes)
        self.assertEqual(payload["status"], "fail")
        self.assertFalse(payload["grvt_replay_acceptance"]["contract_pass"])

    def test_remote_probe_accepts_old_grvt_artifact_with_matching_contract_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, replay_path = remote_probe_fixture(root)
            stale = time.time() - 1201
            os.utime(replay_path, (stale, stale))
            payload = run_remote_probe(root, expected_hashes)
        self.assertEqual(payload["status"], "pass")
        self.assertGreater(
            payload["grvt_replay_acceptance"]["age_seconds"], 1200
        )

    def test_remote_probe_rejects_old_grvt_artifact_with_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_hashes, replay_path = remote_probe_fixture(root)
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            replay["code_hashes"][
                "scripts/alpha_holder_concentration_watch.py"
            ] = "0" * 64
            write_json(replay_path, replay)
            stale = time.time() - 1201
            os.utime(replay_path, (stale, stale))
            payload = run_remote_probe(root, expected_hashes)
        self.assertEqual(payload["status"], "fail")
        self.assertFalse(payload["grvt_replay_acceptance"]["code_hash_parity"])

    def test_deploy_gate_requires_healthy_cycle_and_new_replay(self) -> None:
        deploy = (
            Path(__file__).resolve().parent / "deploy_to_server.sh"
        ).read_text(encoding="utf-8")
        required_contracts = {
            "healthy cycle": 'health_status_after" != "healthy',
            "fresh replay": "replay_artifact_not_refreshed=1",
            "full-cycle overlap retry": "SNIPER_OVERLAP_SKIP_EXIT_CODE=75",
            "bounded overlap attempts": "overlap_attempt_limit=12",
            "project-only cycle limit": "project_only_cycle_limit=",
            "project-only mode": "ALPHA_PROJECT_ONLY=1",
            "project-only no-send": "DISABLE_TELEGRAM=1 ALPHA_PROJECT_ONLY=1",
            "bounded project-only cycles": (
                "ALPHA_PROJECT_ONLY_CYCLES=$project_only_cycle_limit"
            ),
            "full-cycle project preflight reuse": (
                "ALPHA_PROJECT_WATCH_PREFLIGHT_COMPLETE=1"
            ),
            "shared full-cycle lock": (
                "SNIPER_PROJECT_ONLY_RUN_LOCK_FILE=/tmp/sniper_server_run_once.lock"
            ),
            "incomplete project scan gate": "project_watch_incomplete=1",
        }
        for label, marker in required_contracts.items():
            self.assertTrue(
                marker in deploy,
                f"missing deployment contract: {label}",
            )
        self.assertLess(
            deploy.index("ALPHA_PROJECT_ONLY=1"),
            deploy.index("RUN_GRVT_LIQUIDITY_REPLAY_ACCEPTANCE="),
        )
        server_run = (
            Path(__file__).resolve().parent / "server_run_once.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('SNIPER_OVERLAP_SKIP_EXIT_CODE:-0', server_run)
        self.assertIn('ALPHA_PROJECT_WATCH_PREFLIGHT_COMPLETE:-0', server_run)
        self.assertIn("project preflight progress still present", server_run)

    def test_markdown_reports_machine_result(self) -> None:
        payload = evaluate(healthy_snapshot(), allow_dirty=False, remote_required=False)
        report = render_markdown(payload)
        self.assertIn("Status: **PASS**", report)
        self.assertIn("Tracked denied paths | 0", report)


if __name__ == "__main__":
    unittest.main()
