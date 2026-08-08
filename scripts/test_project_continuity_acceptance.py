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

from project_continuity_acceptance import (
    REMOTE_PROBE,
    build_remote_command,
    evaluate,
    path_matches_any,
    render_markdown,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def remote_probe_fixture(root: Path) -> tuple[dict[str, str], Path]:
    parity_paths = (
        "scripts/alpha_holder_concentration_watch.py",
        "scripts/grvt_liquidity_replay_acceptance.py",
        "scripts/fixtures/grvt_v3_quote_only_removal_receipt_2026-08-07.json",
    )
    expected_hashes: dict[str, str] = {}
    for index, relative_path in enumerate(parity_paths):
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
        {"items": [{"symbol": "GRVT"}]},
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
        self.assertIn('health_status_after" != "healthy', deploy)
        self.assertIn("replay_artifact_not_refreshed=1", deploy)
        self.assertIn("SNIPER_OVERLAP_SKIP_EXIT_CODE=75", deploy)
        self.assertIn("overlap_attempt_limit=12", deploy)
        server_run = (
            Path(__file__).resolve().parent / "server_run_once.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('SNIPER_OVERLAP_SKIP_EXIT_CODE:-0', server_run)

    def test_markdown_reports_machine_result(self) -> None:
        payload = evaluate(healthy_snapshot(), allow_dirty=False, remote_required=False)
        report = render_markdown(payload)
        self.assertIn("Status: **PASS**", report)
        self.assertIn("Tracked denied paths | 0", report)


if __name__ == "__main__":
    unittest.main()
