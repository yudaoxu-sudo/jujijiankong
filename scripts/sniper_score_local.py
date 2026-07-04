#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.local_sources import ROOT, read_method_rows
from sniper_engine.scoring import score_candidate


OUT_DIR = ROOT / "output" / "sniper_engine"
CSV_OUT = OUT_DIR / "signal_scores.csv"
MD_OUT = OUT_DIR / "signal_scores.md"

FIELDS = [
    "score",
    "lane",
    "source",
    "published_at",
    "tweet_url",
    "categories",
    "topic_tags",
    "chain",
    "platform",
    "evidence_flags",
    "gaps",
    "next_checks",
    "summary_seed",
]


def main() -> None:
    scored_rows: list[dict[str, str]] = []
    for row in read_method_rows():
        result = score_candidate(row)
        scored_rows.append(
            {
                "score": str(result.score),
                "lane": result.lane,
                "source": row.get("source", ""),
                "published_at": row.get("published_at", ""),
                "tweet_url": row.get("tweet_url", ""),
                "categories": row.get("categories", ""),
                "topic_tags": row.get("topic_tags", ""),
                "chain": row.get("chain", ""),
                "platform": row.get("platform", ""),
                "evidence_flags": row.get("evidence_flags", ""),
                "gaps": "|".join(result.gaps),
                "next_checks": "|".join(result.next_checks),
                "summary_seed": row.get("summary_seed", ""),
            }
        )

    scored_rows.sort(
        key=lambda item: (
            int(item["score"]),
            item["lane"] == "P0_DEEP_REVIEW",
            item["published_at"],
        ),
        reverse=True,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(scored_rows)

    MD_OUT.write_text(render_markdown(scored_rows), encoding="utf-8")
    print(f"wrote {CSV_OUT}")
    print(f"wrote {MD_OUT}")
    print(f"scored {len(scored_rows)} rows")


def render_markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Sniper Signal Scores",
        "",
        "本报告由本地推文库生成，用于决定下一批只读复盘和监控优先级。",
        "",
        "## Lane Counts",
        "",
    ]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["lane"]] = counts.get(row["lane"], 0) + 1
    for lane, count in sorted(counts.items()):
        lines.append(f"- `{lane}`: {count}")

    lines.extend(["", "## Top Signals", ""])
    lines.append("| Score | Lane | Source | Date | Evidence | Categories | Link |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows[:40]:
        date = row["published_at"][:10]
        link = f"[tweet]({row['tweet_url']})" if row["tweet_url"] else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    row["score"],
                    f"`{row['lane']}`",
                    row["source"],
                    date,
                    clean_cell(row["evidence_flags"]),
                    clean_cell(row["categories"]),
                    link,
                ]
            )
            + " |"
        )

    lines.extend(["", "## Next P0 Checks", ""])
    for row in rows:
        if row["lane"] != "P0_DEEP_REVIEW":
            continue
        lines.append(f"- {row['score']} {row['source']} {row['tweet_url']}")
        if row["next_checks"]:
            lines.append(f"  - checks: {row['next_checks']}")
        if row["gaps"]:
            lines.append(f"  - gaps: {row['gaps']}")
    lines.append("")
    return "\n".join(lines)


def clean_cell(value: str) -> str:
    return (value or "").replace("|", "<br>")


if __name__ == "__main__":
    main()
