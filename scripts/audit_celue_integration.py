#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_SKILL = Path("/Users/xuyufan/Documents/蒸馏技能/celue")
DEFAULT_INSTALLED_SKILL = Path("/Users/xuyufan/.codex/skills/celue")
DEFAULT_OUT_DIR = ROOT / "output" / "celue_integration_audit"

REQUIRED_REFERENCES = [
    "elonkely-review-2026-07-07.md",
    "lab-native-address-review-2026-07-07.md",
    "aliideez-alpha-opening-review-2026-07-07.md",
    "crypto-max-market-structure-review-2026-07-07.md",
    "miles082510-wallet-cluster-review-2026-07-13.md",
    "system-logic.md",
    "update-protocol.md",
]

REQUIRED_SYSTEM_LOGIC_PHRASES = [
    "Unified Rule Stack",
    "Project Runtime Evidence",
    "output/runtime_health/last_cycle.json",
    "Treat monitor silence as healthy only",
    "24h cumulative funding",
    "ElonKely-Derived Checks",
    "LAB-Derived Checks",
    "aLiiDeez-Derived Checks",
    "0xcrypto_max-Derived Checks",
    "Miles082510-Derived Checks",
    "root_signal_id",
    "regime_expectancy",
    "supply lifecycle",
    "official",
    "On-chain source",
    "market",
    "social",
    "inference",
    "cex_internal_aggregation",
    "unlabeled_to_cex_inflow_candidate",
]

REQUIRED_UPDATE_PROTOCOL_PHRASES = [
    "Required Integration Points",
    "Update Decision",
    "A dedicated `references/*.md`",
    "/Users/xuyufan/Documents/Codex/projects/sniper-monitor.md",
]

REQUIRED_PROJECT_FILES = [
    "docs/project_analysis_template.md",
    "docs/kol_strategy_intake_prompt.md",
    "scripts/build_alpha_daily_report.py",
    "scripts/backfill_elonkely_exact_anchor_replay.py",
    "scripts/test_elonkely_exact_anchor_replay.py",
    "scripts/fixtures/elonkely_exact_anchor_replay_synthetic.json",
    "scripts/verify_sniper_engine.py",
    "scripts/runtime_health_watch.py",
    "output/aliideez_x_research/analysis/method_index.csv",
    "output/0xcrypto_max_x_research/analysis/method_index.csv",
    "input/miles082510_wallet_cluster_review_2026-07-13.json",
    "cases/2026-07-13_miles082510_wallet_cluster_review.md",
    "input/elonkely_latest_100_review_2026-07-16.json",
    "input/elonkely_exact_anchor_replay_2026-07-29.json",
    "cases/2026-07-16_elonkely_latest_100_review.md",
    "input/binance_alpha_cex_wallet_aggregation_review_2026-07-17.json",
    "cases/2026-07-17_binance_alpha_cex_wallet_aggregation.md",
]

REQUIRED_DAILY_FIELDS = [
    "source_layers",
    "path_stage",
    "cex_wallet_aggregation",
    "cluster_evidence",
    "deposit_status",
    "derivatives_ratio",
    "catalyst_source",
    "identity_label_quality",
    "venue_rotation",
    "supply_lifecycle",
    "outcome_ledger",
    "regime_expectancy",
    "source_time_sanity",
    "flow_recycling_candidate",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit celue skill integration with the sniper-monitor project.")
    parser.add_argument("--source-skill", type=Path, default=DEFAULT_SOURCE_SKILL)
    parser.add_argument("--installed-skill", type=Path, default=DEFAULT_INSTALLED_SKILL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--project-only",
        action="store_true",
        help="Skip local Codex skill directory checks; use this on servers that only deploy the sniper project.",
    )
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    source = args.source_skill
    installed = args.installed_skill

    if not args.project_only:
        add_check(checks, "source skill directory exists", source.is_dir(), str(source))
        add_check(checks, "installed skill directory exists", installed.is_dir(), str(installed))

        source_skill = source / "SKILL.md"
        installed_skill = installed / "SKILL.md"
        source_skill_text = read_text(source_skill)
        installed_skill_text = read_text(installed_skill)

        add_check(checks, "source SKILL.md exists", source_skill.exists(), str(source_skill))
        add_check(checks, "installed SKILL.md exists", installed_skill.exists(), str(installed_skill))
        add_check(
            checks,
            "source and installed SKILL.md match",
            source_skill_text == installed_skill_text and bool(source_skill_text),
            "byte-equivalent" if source_skill_text == installed_skill_text and source_skill_text else "mismatch or missing",
        )

        for ref_name in REQUIRED_REFERENCES:
            ref_link = f"references/{ref_name}"
            source_ref = source / "references" / ref_name
            installed_ref = installed / "references" / ref_name
            source_ref_text = read_text(source_ref)
            installed_ref_text = read_text(installed_ref)
            add_check(checks, f"source reference exists: {ref_name}", source_ref.exists(), ref_link)
            add_check(checks, f"installed reference exists: {ref_name}", installed_ref.exists(), ref_link)
            add_check(checks, f"SKILL.md links reference: {ref_name}", ref_link in source_skill_text, ref_link)
            add_check(
                checks,
                f"source and installed reference match: {ref_name}",
                source_ref_text == installed_ref_text and bool(source_ref_text),
                "byte-equivalent" if source_ref_text == installed_ref_text and source_ref_text else "mismatch or missing",
            )

        system_logic = read_text(source / "references" / "system-logic.md")
        for phrase in REQUIRED_SYSTEM_LOGIC_PHRASES:
            add_check(checks, f"system logic contains: {phrase}", phrase in system_logic, phrase)

        update_protocol = read_text(source / "references" / "update-protocol.md")
        for phrase in REQUIRED_UPDATE_PROTOCOL_PHRASES:
            add_check(checks, f"update protocol contains: {phrase}", phrase in update_protocol, phrase)

    for rel_path in REQUIRED_PROJECT_FILES:
        path = ROOT / rel_path
        add_check(checks, f"project file exists: {rel_path}", path.exists(), rel_path)

    intake_prompt = read_text(ROOT / "docs" / "kol_strategy_intake_prompt.md")
    for phrase in [
        "official / onchain / market / social / inference",
        "method index",
        "case index",
        "integration proposal",
        "outcome ledger",
        "root_signal_id",
        "event_time_sanity",
        "python3 scripts/audit_celue_integration.py",
    ]:
        add_check(checks, f"KOL intake prompt contains: {phrase}", phrase in intake_prompt, phrase)

    report_builder = read_text(ROOT / "scripts" / "build_alpha_daily_report.py")
    add_check(checks, "daily report has celue checklist function", "def celue_strategy_checklist" in report_builder, "")
    for field in REQUIRED_DAILY_FIELDS:
        add_check(checks, f"daily report exposes celue field: {field}", field in report_builder, field)

    elonkely_review_path = ROOT / "input" / "elonkely_latest_100_review_2026-07-16.json"
    exact_replay_path = ROOT / "input" / "elonkely_exact_anchor_replay_2026-07-29.json"
    try:
        elonkely_review = json.loads(read_text(elonkely_review_path))
        exact_replay = json.loads(read_text(exact_replay_path))
        ledger = elonkely_review.get("outcome_ledger", [])
        ledger_by_root = {row.get("root_signal_id"): row for row in ledger}
        replay_by_root = {
            row.get("root_signal_id"): row for row in exact_replay.get("cases", [])
        }
        parti_replay = replay_by_root.get("ELON-2074859463027408945", {})
        evaa_replay = replay_by_root.get("ELON-2075164060409270485", {})
        root_ids = [row.get("root_signal_id") for row in ledger]
        decisions = elonkely_review.get("runtime_decisions", {})
        time_cases = elonkely_review.get("source_time_sanity_cases", [])
        add_check(checks, "ElonKely review schema", elonkely_review.get("schema") == "kol_strategy_review.v1", "")
        add_check(checks, "ElonKely review covers 100 deduped posts", elonkely_review.get("source_scope", {}).get("post_count_deduped") == 100, "")
        add_check(checks, "ElonKely outcome ledger has unique roots", len(root_ids) >= 2 and len(root_ids) == len(set(root_ids)), str(root_ids))
        add_check(checks, "ElonKely outcome ledger has fixed horizons", bool(ledger) and all(row.get("evaluation_horizons") for row in ledger), "")
        add_check(checks, "ElonKely outcome ledger uses valid statuses", bool(ledger) and all(row.get("outcome_status") in {"won", "lost", "mixed", "unresolved"} for row in ledger), "")
        add_check(checks, "ElonKely source-time mismatch is preserved", any(row.get("event_time_sanity") == "mismatch" for row in time_cases), "")
        add_check(checks, "ElonKely review leaves actions unchanged", decisions.get("trade_action_change") is False and decisions.get("telegram_alert_change") is False, "")
        add_check(
            checks,
            "ElonKely exact replay has no runtime effect",
            exact_replay.get("schema") == "exact_anchor_market_replay.v1"
            and exact_replay.get("runtime_effect") == "none"
            and exact_replay.get("alert_effect") == "none"
            and exact_replay.get("trade_action_effect") == "none"
            and exact_replay.get("methodology", {}).get("interpolation") == "forbidden",
            "",
        )
        add_check(
            checks,
            "ElonKely PARTI exact replay preserves blocked boundary",
            parti_replay.get("status") == "blocked_incomplete_series"
            and parti_replay.get("api_result", {}).get("code") == "-1121"
            and parti_replay.get("registry_state", {}).get("token_list_present") is True
            and parti_replay.get("registry_state", {}).get("exchange_info_present") is False
            and parti_replay.get("coverage", {}).get("observed_candle_count") == 0
            and parti_replay.get("coverage", {}).get("missing_candle_count") == 10080
            and parti_replay.get("series_sha256") is None
            and ledger_by_root.get("ELON-2074859463027408945", {}).get("outcome_status")
            == "unresolved",
            str(parti_replay.get("api_result", {})),
        )
        add_check(
            checks,
            "ElonKely EVAA exact replay covers every fixed horizon",
            evaa_replay.get("status") == "complete"
            and evaa_replay.get("coverage", {}).get("observed_candle_count") == 10080
            and evaa_replay.get("coverage", {}).get("missing_candle_count") == 0
            and evaa_replay.get("series_sha256")
            == "43955bb41444a57f775dac1e0801007fe213b7d55ac68d55cb54f771469abeab"
            and all(
                evaa_replay.get("horizons", {}).get(label, {}).get("status") == "complete"
                for label in ("24h", "72h", "7d")
            )
            and evaa_replay.get("horizons", {}).get("24h", {}).get("metrics", {}).get(
                "end_return_pct"
            )
            == "14.8908359048"
            and evaa_replay.get("horizons", {}).get("72h", {}).get("metrics", {}).get(
                "end_return_pct"
            )
            == "-39.2159479990"
            and evaa_replay.get("horizons", {}).get("7d", {}).get("metrics", {}).get(
                "end_return_pct"
            )
            == "-53.1921069765"
            and ledger_by_root.get("ELON-2075164060409270485", {}).get("outcome_status")
            == "mixed"
            and ledger_by_root.get("ELON-2075164060409270485", {})
            .get("market_provenance", {})
            .get("series_sha256")
            == evaa_replay.get("series_sha256"),
            str(evaa_replay.get("series_sha256") or ""),
        )
    except Exception as exc:
        add_check(checks, "ElonKely structured review parses", False, str(exc))

    latest_daily = latest_report(ROOT / "reports")
    latest_daily_text = read_text(latest_daily) if latest_daily else ""
    add_check(
        checks,
        "latest daily report renders celue checklist",
        "Celue 策略校验清单" in latest_daily_text,
        latest_daily.name if latest_daily else "missing daily report",
    )

    failed = [row for row in checks if not row["ok"]]
    payload = {
        "schema": "celue_integration_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_skill": str(source),
        "installed_skill": str(installed),
        "project_only": bool(args.project_only),
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "latest.md").write_text(render_markdown(payload), encoding="utf-8")
    print(args.out_dir / "latest.md")

    return 1 if failed else 0


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def latest_report(reports_dir: Path) -> Path | None:
    reports = sorted(reports_dir.glob("*_alpha_sniper_daily.md"))
    return reports[-1] if reports else None


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Celue Integration Audit",
        "",
        f"- generated_at_utc: `{payload['generated_at_utc']}`",
        f"- source_skill: `{payload['source_skill']}`",
        f"- installed_skill: `{payload['installed_skill']}`",
        f"- project_only: `{payload['project_only']}`",
        f"- failed_count: `{payload['failed_count']}`",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for row in payload["checks"]:
        status = "PASS" if row["ok"] else "FAIL"
        detail = str(row.get("detail") or "").replace("|", "/")
        lines.append(f"| {row['name']} | {status} | {detail} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
