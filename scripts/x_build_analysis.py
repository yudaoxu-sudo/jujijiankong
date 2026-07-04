#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter, OrderedDict
from pathlib import Path

from x_research_common import (
    extract_symbols,
    norm_space,
    read_csv,
    split_pipe,
    write_csv,
)


def rx(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


CATEGORY_RULES: list[tuple[str, str, list[re.Pattern[str]]]] = [
    (
        "开盘/狙击/打新",
        "sniping",
        [rx(r"狙击|打新|开盘|抢筹|前排|首块|同区块|第一块|低开|平开|盘前|冲新币|战壕"), rx(r"\bsnip(?:e|er|ing)?\b")],
    ),
    (
        "贿赂/bundle/MEV",
        "bribe_bundle",
        [rx(r"贿赂|块内|同一个区块|内部交易|Internal Transactions?|MEV"), rx(r"\bbundle\b|\bsend bundle\b|\bbribe\b|\bBlockRazor\b|\bPayment\b|\btxIndex\b")],
    ),
    (
        "加池/流动性/价格区间",
        "liquidity",
        [
            rx(r"加池|池子|流动性|价格区间|池子区间|超出区间|当前价格|最低价格|最高价格|推背感"),
            rx(r"\bV3\b|PancakeSwap|Uniswap|Aerodrome|CLPositionManager|Four\.Meme|four\.meme"),
            rx(r"Add Liquidity|Remove Liquidity|fee tier|Position Token ID|BEP-721|Token ID"),
            rx(r"(?<![A-Za-z])(?:LP|lp)(?![A-Za-z])", 0),
        ],
    ),
    (
        "跨链/桥/多链价差",
        "bridge",
        [rx(r"跨链|跨过去|跨过来|跨来|跨到|桥|多链|价差"), rx(r"\bbridge\b|\bbridging\b|\bwormhole\b|\bhyperlane\b")],
    ),
    (
        "筹码/解锁/tokenomics",
        "tokenomics",
        [rx(r"筹码|总量|流通|解锁|锁仓|分配|持仓|持币|归集|空投|融资|估值|VC|机构"), rx(r"\btokenomics?\b|\bFDV\b|\bTGE\b|\bvesting\b|\bunlock\b|\bholders?\b")],
    ),
    (
        "地址/监控/工具",
        "address_monitoring",
        [rx(r"地址|监控|标记|授权|大额|链上痕迹|查地址|区块|合约地址|聪明钱|链上"), rx(r"bscscan|basescan|etherscan|solscan|gmgn|dexscreener|dextools|read contract|write contract"), rx(r"\btx\b|\bhash\b|\bcontract\b|\bwallet\b|\bapi\b|\bblock\b")],
    ),
    (
        "CEX/Alpha/上新",
        "alpha",
        [rx(r"\balpha\b|上alpha|BN Alpha|Binance Alpha|okx|coinbase|kraken|上所|上币|boost|list"), rx(r"\bOI\b|永续|perp|futures|launchpad|IDO")],
    ),
    (
        "庄/控盘/成本",
        "market_maker",
        [rx(r"庄|抓庄|控盘|成本|拉盘|砸盘|老鼠仓|聪明钱|洗盘|出货|接盘|对手盘")],
    ),
]


def evidence_text(row: dict[str, str]) -> str:
    return "\n".join([row.get("tweet_text", ""), row.get("author_ocr_text", ""), row.get("raw_notes", "")])


def classify(row: dict[str, str]) -> tuple[list[str], list[str]]:
    text = evidence_text(row)
    categories: list[str] = []
    tags: list[str] = []
    for category, tag, patterns in CATEGORY_RULES:
        if any(pattern.search(text) for pattern in patterns):
            categories.append(category)
            tags.append(tag)
    if row.get("tx_hashes") or row.get("block_numbers"):
        if "地址/监控/工具" not in categories:
            categories.append("地址/监控/工具")
            tags.append("address_monitoring")
    if row.get("lp_token_id"):
        if "加池/流动性/价格区间" not in categories:
            categories.append("加池/流动性/价格区间")
            tags.append("liquidity")
    return categories, tags


def evidence_flags(row: dict[str, str]) -> str:
    flags: list[str] = []
    if row.get("contract_addresses"):
        flags.append("address")
    if row.get("tx_hashes"):
        flags.append("tx")
    if row.get("block_numbers"):
        flags.append("block")
    if row.get("lp_token_id"):
        flags.append("lp_id")
    if row.get("author_media_files"):
        flags.append("author_image")
    if row.get("embedded_or_quote_media_files"):
        flags.append("embedded_or_quote_image")
    if "supplemental_oembed_candidate" in row.get("why_keep", ""):
        flags.append("oembed")
    return "|".join(flags)


def make_summary(row: dict[str, str], limit: int = 220) -> str:
    text = norm_space("\n".join([row.get("tweet_text", ""), row.get("author_ocr_text", "")]))
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_method_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        categories, tags = classify(row)
        if not categories:
            continue
        out.append(
            {
                "id": row.get("id", ""),
                "tweet_url": row.get("tweet_url", ""),
                "published_at": row.get("published_at", ""),
                "categories": "|".join(categories),
                "topic_tags": "|".join(tags),
                "chain": row.get("chain", ""),
                "platform": row.get("dex_or_platform", ""),
                "evidence_flags": evidence_flags(row),
                "has_tx": "yes" if row.get("tx_hashes") else "no",
                "has_addr": "yes" if row.get("contract_addresses") else "no",
                "has_lp_id": "yes" if row.get("lp_token_id") else "no",
                "author_media_files": row.get("author_media_files", ""),
                "embedded_or_quote_media_files": row.get("embedded_or_quote_media_files", ""),
                "summary_seed": make_summary(row),
            }
        )
    return out


def build_case_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        categories, _ = classify(row)
        symbols = extract_symbols(row.get("tweet_text", ""), row.get("project_or_token", ""))
        has_chain_evidence = any(row.get(field) for field in ("contract_addresses", "tx_hashes", "block_numbers", "lp_token_id"))
        has_launch_method = any(
            category in categories
            for category in ("开盘/狙击/打新", "加池/流动性/价格区间", "贿赂/bundle/MEV", "跨链/桥/多链价差", "庄/控盘/成本")
        )
        if not (symbols or has_chain_evidence or has_launch_method):
            continue
        out.append(
            {
                "id": row.get("id", ""),
                "tweet_url": row.get("tweet_url", ""),
                "published_at": row.get("published_at", ""),
                "symbols_or_projects": symbols,
                "chain": row.get("chain", ""),
                "platform": row.get("dex_or_platform", ""),
                "contract_addresses": row.get("contract_addresses", ""),
                "tx_hashes": row.get("tx_hashes", ""),
                "block_numbers": row.get("block_numbers", ""),
                "lp_token_id": row.get("lp_token_id", ""),
                "method_categories": "|".join(categories),
                "evidence_flags": evidence_flags(row),
                "needs_verification": "yes" if has_chain_evidence else "manual_context",
                "summary_seed": make_summary(row),
            }
        )
    return out


def md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |")
        if index == 0:
            lines.append("| " + " | ".join("-" * widths[i] for i in range(len(row))) + " |")
    return "\n".join(lines)


def write_method_library(path: Path, rows: list[dict[str, str]], account: str) -> None:
    by_category: OrderedDict[str, list[dict[str, str]]] = OrderedDict((category, []) for category, _, _ in CATEGORY_RULES)
    for row in rows:
        for category in split_pipe(row["categories"]):
            by_category.setdefault(category, []).append(row)
    lines = [
        f"# @{account} 方法库索引",
        "",
        "来源：本地归档的推文正文、作者原帖图片 OCR、oEmbed 补采文本和短链展开结果。引用/嵌入图保留为审计字段。",
        "",
        "## 分类计数",
        "",
    ]
    counts = [[category, str(len(items))] for category, items in by_category.items() if items]
    lines.append(md_table([["方法类目", "推文数"], *counts]))
    lines.append("")
    for category, items in by_category.items():
        if not items:
            continue
        lines.extend([f"## {category}", ""])
        for item in items:
            date = item["published_at"][:10] if item["published_at"] else "unknown"
            flags = item["evidence_flags"] or "text"
            snippet = item["summary_seed"].replace("|", "/")
            lines.append(f"- {date} [{item['id']}]({item['tweet_url']}) `{flags}` {snippet}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_case_index_md(path: Path, rows: list[dict[str, str]], account: str) -> None:
    lines = [
        f"# @{account} 案例索引",
        "",
        "用途：汇总打新、狙击、Alpha、链上监控、抓庄、筹码和流动性相关样本。每条仍需回到原帖或链上浏览器复核。",
        "",
    ]
    for row in rows:
        date = row["published_at"][:10] if row["published_at"] else "unknown"
        title = row["symbols_or_projects"] or row["id"]
        evidence = row["evidence_flags"] or "text"
        lines.append(f"## {title} · {date}")
        lines.append(f"- 推文：[{row['id']}]({row['tweet_url']})")
        lines.append(f"- 方法：{row['method_categories'] or '未标注'}")
        lines.append(f"- 证据：`{evidence}`")
        if row["chain"]:
            lines.append(f"- 链：{row['chain']}")
        if row["platform"]:
            lines.append(f"- 平台：{row['platform']}")
        if row["contract_addresses"]:
            lines.append(f"- 地址：`{row['contract_addresses']}`")
        if row["tx_hashes"]:
            lines.append(f"- Tx：`{row['tx_hashes']}`")
        if row["block_numbers"]:
            lines.append(f"- 区块：`{row['block_numbers']}`")
        if row["lp_token_id"]:
            lines.append(f"- LP/Position ID：`{row['lp_token_id']}`")
        lines.append(f"- 摘要种子：{row['summary_seed']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def queue_priority(row: dict[str, str]) -> tuple[int, str]:
    categories = split_pipe(row["method_categories"])
    flags = set(split_pipe(row["evidence_flags"]))
    if "贿赂/bundle/MEV" in categories and {"tx", "block"} & flags:
        return 0, "P0 bundle/bribe with chain evidence"
    if "开盘/狙击/打新" in categories and ({"tx", "block", "lp_id", "address"} & flags):
        return 1, "P1 launch/sniping with chain evidence"
    if "庄/控盘/成本" in categories and ({"tx", "address"} & flags):
        return 1, "P1 market-maker/control with chain evidence"
    if "加池/流动性/价格区间" in categories and ({"lp_id", "address", "tx"} & flags):
        return 2, "P2 liquidity with evidence"
    if "地址/监控/工具" in categories and "address" in flags:
        return 3, "P3 address or contract evidence"
    if any(category in categories for category in ("筹码/解锁/tokenomics", "CEX/Alpha/上新", "跨链/桥/多链价差")):
        return 4, "P4 catalyst/tokenomics/context"
    return 5, "P5 opinion/context"


def write_review_queue(path: Path, rows: list[dict[str, str]]) -> None:
    ranked = sorted(rows, key=lambda row: (*queue_priority(row), row["published_at"]))
    lines = [
        "# 复盘队列",
        "",
        "排序规则：优先看有 tx、block、地址、LP ID 等证据的推文，再看纯观点或背景判断。这个文件保留所有案例样本。",
        "",
    ]
    current_label = ""
    for row in ranked:
        _, label = queue_priority(row)
        if label != current_label:
            if current_label:
                lines.append("")
            current_label = label
            lines.extend([f"## {label}", ""])
        title = row["symbols_or_projects"] or row["id"]
        evidence = row["evidence_flags"] or "text"
        date = row["published_at"][:10] if row["published_at"] else "unknown"
        lines.append(f"- {date} [{title}]({row['tweet_url']}) `{evidence}` {row['method_categories']}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_quality_report(path: Path, raw_rows: list[dict[str, str]], method_rows: list[dict[str, str]], case_rows: list[dict[str, str]]) -> None:
    oembed_rows = [row for row in raw_rows if "supplemental_oembed_candidate" in row.get("why_keep", "")]
    unknown_image_rows = [row for row in raw_rows if row.get("has_image") == "unknown"]
    author_image_rows = [row for row in raw_rows if row.get("author_media_files")]
    embedded_rows = [row for row in raw_rows if row.get("embedded_or_quote_media_files") or row.get("embedded_or_quote_ocr_text")]
    numeric_symbol_rows = [
        row
        for row in case_rows
        if any(part and part[0] == "$" and len(part) > 1 and part[1].isdigit() for part in split_pipe(row["symbols_or_projects"]))
    ]
    method_counts = Counter()
    for row in method_rows:
        for category in split_pipe(row["categories"]):
            method_counts[category] += 1
    lines = [
        "# 数据质量报告",
        "",
        "## 范围",
        "",
        f"- 原始保留推文：{len(raw_rows)}",
        f"- 方法索引推文：{len(method_rows)}",
        f"- 案例索引推文：{len(case_rows)}",
        f"- 作者原帖含图推文：{len(author_image_rows)}",
        f"- 含引用/嵌入图片推文：{len(embedded_rows)}",
        f"- oEmbed 补采推文：{len(oembed_rows)}",
        f"- 图片状态未知推文：{len(unknown_image_rows)}",
        "",
        "## 方法计数",
        "",
        md_table([["方法类目", "推文数"], *[[k, str(v)] for k, v in method_counts.most_common()]]),
        "",
        "## 注意事项",
        "",
        "- oEmbed 补采行只有推文正文、日期、短链和展开后的链上链接；若 `has_image=unknown`，代表原推可能有图，但本地尚未下载作者图片。",
        "- 引用/嵌入图不参与默认分类，避免把别人推文里的图误当成本作者证据。",
        "- 链上链接只是复核入口，不能直接证明作者推断。",
    ]
    if numeric_symbol_rows:
        lines.append(f"- 金额型 `$数字` 仍需检查：{', '.join(row['id'] for row in numeric_symbol_rows[:10])}")
    else:
        lines.append("- 金额型 `$数字` 已从 `symbols_or_projects` 过滤。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    raw_rows = read_csv(data_dir / "raw_tweets.csv")
    method_rows = build_method_rows(raw_rows)
    case_rows = build_case_rows(raw_rows)

    write_csv(
        analysis_dir / "method_index.csv",
        method_rows,
        ["id", "tweet_url", "published_at", "categories", "topic_tags", "chain", "platform", "evidence_flags", "has_tx", "has_addr", "has_lp_id", "author_media_files", "embedded_or_quote_media_files", "summary_seed"],
    )
    write_csv(
        analysis_dir / "case_index.csv",
        case_rows,
        ["id", "tweet_url", "published_at", "symbols_or_projects", "chain", "platform", "contract_addresses", "tx_hashes", "block_numbers", "lp_token_id", "method_categories", "evidence_flags", "needs_verification", "summary_seed"],
    )
    write_method_library(analysis_dir / "method_library.md", method_rows, args.account.lstrip("@"))
    write_case_index_md(analysis_dir / "case_index.md", case_rows, args.account.lstrip("@"))
    write_review_queue(analysis_dir / "review_queue.md", case_rows)
    write_quality_report(analysis_dir / "quality_report.md", raw_rows, method_rows, case_rows)
    print(f"raw_rows={len(raw_rows)}")
    print(f"method_rows={len(method_rows)}")
    print(f"case_rows={len(case_rows)}")


if __name__ == "__main__":
    main()
