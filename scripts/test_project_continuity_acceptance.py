#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_continuity_acceptance import (
    build_remote_command,
    evaluate,
    path_matches_any,
    render_markdown,
)


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
        self.assertNotIn("find ", rendered)
        self.assertNotIn("rg ", rendered)
        self.assertNotIn("cat ", rendered)

    def test_markdown_reports_machine_result(self) -> None:
        payload = evaluate(healthy_snapshot(), allow_dirty=False, remote_required=False)
        report = render_markdown(payload)
        self.assertIn("Status: **PASS**", report)
        self.assertIn("Tracked denied paths | 0", report)


if __name__ == "__main__":
    unittest.main()
