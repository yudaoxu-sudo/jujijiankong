#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PLACEHOLDER = "<LLM_NARRATIVE_PLACEHOLDER>"


def count_placeholders(node: Any) -> int:
    if isinstance(node, dict):
        return sum(count_placeholders(v) for v in node.values())
    if isinstance(node, list):
        return sum(count_placeholders(v) for v in node)
    if isinstance(node, str):
        return 1 if node == PLACEHOLDER else 0
    return 0


def money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num) >= 1_000_000:
        return f"${num / 1_000_000:.2f}M"
    if abs(num) >= 1_000:
        return f"${num:,.0f}"
    return f"${num:,.4f}"


def pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: summarize_hertzflow_skeleton.py <skeleton.json> <out.md>")
        return 1

    skeleton_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    data = json.loads(skeleton_path.read_text(encoding="utf-8"))

    meta = data.get("meta", {})
    verdict = data.get("verdict", {})
    screen = data.get("screen_summary", {})
    decision = data.get("decision_action_block", {})
    immediate = decision.get("immediate_action", {})
    stop_loss = decision.get("stop_loss", {})
    surf = data.get("_surf_credits", {})
    monitoring = data.get("monitoring_wallets", [])
    monitoring_dir = skeleton_path.parent / "monitoring"
    importable_wallets = None
    full_wallets = None
    paste_path = monitoring_dir / "monitoring_paste.json"
    full_path = monitoring_dir / "monitoring_wallets_full.json"
    if paste_path.exists():
        try:
            importable_wallets = len(json.loads(paste_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            importable_wallets = None
    if full_path.exists():
        try:
            full_payload = json.loads(full_path.read_text(encoding="utf-8"))
            full_wallets = full_payload.get("n_wallets")
        except (json.JSONDecodeError, AttributeError):
            full_wallets = None

    lines: list[str] = []
    lines.append(f"# HertzFlow Skeleton Summary: {meta.get('symbol', '-')}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Token: `{meta.get('symbol', '-')}` / {meta.get('name', '-')}")
    lines.append(f"- CA: `{meta.get('contract_address', '-')}`")
    lines.append(f"- Chain: {meta.get('chain', '-')} / chainId `{meta.get('chain_id', '-')}`")
    lines.append(f"- Alpha listing date: {meta.get('alpha_listing_date_utc', '-')}")
    lines.append(f"- Price: {money(meta.get('alpha_price_usd'))}")
    lines.append(f"- 24h change: {pct(meta.get('alpha_percent_change_24h'))}")
    lines.append(f"- 24h volume: {money(meta.get('alpha_vol_24h_usd'))}")
    lines.append(f"- Market cap: {money(meta.get('alpha_market_cap_usd'))}")
    lines.append(f"- FDV: {money(meta.get('alpha_fdv_usd'))}")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"- Enum: `{verdict.get('enum', '-')}`")
    lines.append(f"- Label: {verdict.get('cn_label', '-')}")
    lines.append(f"- Baseline: `{verdict.get('baseline', '-')}`")
    lines.append(f"- Next tier: `{verdict.get('next_tier_enum', '-')}` / {verdict.get('next_tier_cn', '-')}")
    lines.append(f"- Screen sentence: {screen.get('one_sentence', '-')}")
    lines.append("")
    lines.append("## Decision Anchors")
    lines.append("")
    lines.append(f"- Immediate action: `{immediate.get('action_enum', '-')}`")
    lines.append(f"- Tranches: {immediate.get('tranches_n', '-')}")
    lines.append(f"- Tranche max: {money(immediate.get('tranche_max_usd'))}")
    lines.append(f"- Horizon: {immediate.get('horizon_hours', '-')} hours")
    lines.append(f"- Slippage cap: {pct(immediate.get('slippage_pct_cap'))}")
    lines.append(f"- Stop price: {money(stop_loss.get('trigger_price_usd'))}")
    lines.append(f"- Current price: {money(stop_loss.get('current_price_usd'))}")
    lines.append(f"- Stop delta: {pct(stop_loss.get('delta_pct'))}")
    lines.append("")
    lines.append("## Screen Dimensions")
    lines.append("")
    for item in screen.get("dimensions", []):
        lines.append(f"- {item.get('name', '-')}: {item.get('label', '-')}")
        evidence = item.get("evidence")
        if evidence:
            lines.append(f"  Evidence: {evidence}")
    lines.append("")
    lines.append("## Monitoring")
    lines.append("")
    lines.append(f"- Skeleton monitoring wallets: {len(monitoring)}")
    if full_wallets is not None:
        lines.append(f"- Full export wallets: {full_wallets}")
    if importable_wallets is not None:
        lines.append(f"- Paste import wallets: {importable_wallets}")
    summary = data.get("monitoring_summary", {})
    if summary.get("level_counts"):
        lines.append(f"- Level counts: {summary.get('level_counts')}")
    lines.append(f"- Placeholder count before render: {count_placeholders(data)}")
    if surf:
        lines.append(f"- Surf credits: {surf}")
    lines.append("")
    lines.append("## Next")
    lines.append("")
    lines.append("- Fill writable narrative slots only after reviewing locked data.")
    lines.append("- Render with `render_report.py` after validator passes.")
    lines.append("- Import monitoring wallets after labels are reviewed.")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
