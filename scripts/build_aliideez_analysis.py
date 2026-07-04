#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from collections import Counter, OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "output" / "aliideez_x_research"
ANALYSIS_DIR = DATA_DIR / "analysis"


STOP_TICKERS = {
    "USD",
    "USDT",
    "USDC",
    "BUSD",
    "BNB",
    "ETH",
    "BTC",
    "FDV",
    "TVL",
    "ATH",
    "ROI",
}


def rx(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


CATEGORY_RULES: list[tuple[str, str, list[re.Pattern[str]]]] = [
    (
        "开盘/狙击/前排",
        "sniping",
        [
            rx(r"狙击|狙到|打新|开盘|抢筹|前排|首块|同区块|第一块|低开|平开|盘前"),
            rx(r"\bsnip(?:e|er|ing)?\b"),
            rx(r"\bbot\b"),
        ],
    ),
    (
        "贿赂/bundle/内部交易",
        "bribe_bundle",
        [
            rx(r"贿赂|块内|同一个区块|内部交易|Internal Transactions?"),
            rx(r"\bbundle\b|\bsend bundle\b|\bbribe\b|\bBlockRazor\b|\bPayment\b"),
            rx(r"\btxIndex\b|\bvalidator\b|\bbuilder\b|\brelay\b"),
        ],
    ),
    (
        "加池/V3/LP区间",
        "liquidity",
        [
            rx(r"加池|池子|流动性|价格区间|池子区间|超出区间|当前价格|最低价格|最高价格"),
            rx(r"\bV3\b|PancakeSwap|Uniswap|Aerodrome|CLPositionManager"),
            rx(r"Add Liquidity|Remove Liquidity|fee tier|Position Token ID|BEP-721|Token ID"),
            rx(r"(?<![A-Za-z])(?:LP|lp)(?![A-Za-z])", 0),
        ],
    ),
    (
        "跨链/桥/多链价差",
        "bridge",
        [
            rx(r"跨链|跨过去|跨过来|跨来|跨到|桥|多链|价差"),
            rx(r"\bbridge\b|\bbridging\b|\bwormhole\b|\bwormholescan\b|\blayerzero\b|\bmultichain\b"),
        ],
    ),
    (
        "筹码/锁仓/tokenomics",
        "tokenomics",
        [
            rx(r"筹码|总量|流通|解锁|锁仓|分配|持仓|持币|归集|空投|融资|估值"),
            rx(r"\btokenomics?\b|\bFDV\b|\bTGE\b|\bvesting\b|\bunlock\b|\bholders?\b"),
            rx(r"Rank\s+Address|Token Holder"),
        ],
    ),
    (
        "地址/监控/工具",
        "address_monitoring",
        [
            rx(r"地址|监控|标记|授权|大额|链上痕迹|查地址|区块|合约地址"),
            rx(r"bscscan|basescan|etherscan|solscan|gmgn|dexscreener|read contract|write contract"),
            rx(r"\btx\b|\bhash\b|\bcontract\b|\bwallet\b|\bapi\b|\bblock\b"),
        ],
    ),
    (
        "CEX/OI/Alpha上新",
        "alpha",
        [
            rx(r"\balpha\b|上alpha|BN Alpha|Binance Alpha|okx|coinbase|kraken|上所|上币|boost"),
            rx(r"\bOI\b|永续|perp|futures|launchpad|IDO"),
        ],
    ),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def evidence_text(row: dict[str, str]) -> str:
    # Use only the author's own tweet and own attached images for classification.
    # Quoted/embedded cards stay in audit fields and do not drive labels.
    parts = [
        row.get("tweet_text", ""),
        row.get("author_ocr_text", ""),
        row.get("raw_notes", ""),
    ]
    return "\n".join(parts)


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
        if "加池/V3/LP区间" not in categories:
            categories.append("加池/V3/LP区间")
            tags.append("liquidity")

    return categories, tags


def extract_symbols(row: dict[str, str]) -> str:
    candidates: OrderedDict[str, None] = OrderedDict()
    source = "\n".join([row.get("tweet_text", ""), row.get("project_or_token", "")])

    for match in re.finditer(r"\$([A-Za-z][A-Za-z0-9_]{0,15})\b", source):
        symbol = match.group(1).upper()
        if symbol not in STOP_TICKERS:
            candidates[f"${symbol}"] = None

    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_. -]{1,40})\(([A-Z0-9]{1,10})\)", source):
        name = norm_space(match.group(1))
        ticker = match.group(2).upper()
        if ticker in STOP_TICKERS or ticker.isdigit():
            continue
        if len(name) > 2:
            candidates[f"{name}({ticker})"] = None

    project_or_token = norm_space(row.get("project_or_token", ""))
    if project_or_token and not re.fullmatch(r"\$?\d+(?:\.\d+)?[KMB]?", project_or_token, re.IGNORECASE):
        candidates[project_or_token] = None

    return "|".join(candidates.keys())


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
    return "|".join(flags)


def make_summary(row: dict[str, str], limit: int = 220) -> str:
    text = norm_space("\n".join([row.get("tweet_text", ""), row.get("author_ocr_text", "")]))
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_method_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
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
    out: list[dict[str, str]] = []
    for row in rows:
        categories, _ = classify(row)
        symbols = extract_symbols(row)
        has_chain_evidence = any(
            row.get(field)
            for field in ("contract_addresses", "tx_hashes", "block_numbers", "lp_token_id")
        )
        has_launch_method = any(
            category in categories
            for category in ("开盘/狙击/前排", "加池/V3/LP区间", "贿赂/bundle/内部交易", "跨链/桥/多链价差")
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
        line = "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |"
        lines.append(line)
        if index == 0:
            lines.append("| " + " | ".join("-" * widths[i] for i in range(len(row))) + " |")
    return "\n".join(lines)


def write_method_library(rows: list[dict[str, str]]) -> None:
    by_category: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for category, _, _ in CATEGORY_RULES:
        by_category[category] = []
    for row in rows:
        for category in split_pipe(row["categories"]):
            by_category.setdefault(category, []).append(row)

    lines = [
        "# aLiiDeez 方法库索引",
        "",
        "来源：本地归档的作者推文正文和作者原帖图片 OCR。引用推文、嵌入卡片图片已单独保留，不参与默认标签判断。",
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
            date = item["published_at"][:10]
            flags = item["evidence_flags"] or "text"
            snippet = item["summary_seed"].replace("|", "/")
            lines.append(f"- {date} [{item['id']}]({item['tweet_url']}) `{flags}` {snippet}")
        lines.append("")

    (ANALYSIS_DIR / "method_library.md").write_text("\n".join(lines), encoding="utf-8")


def write_case_index_md(rows: list[dict[str, str]]) -> None:
    lines = [
        "# aLiiDeez 案例索引",
        "",
        "用途：把新币打新、狙击、加池、跨链、筹码、地址监控相关推文按案例入口汇总。每条仍需回到链上浏览器或 RPC 复核。",
        "",
    ]
    for row in rows:
        date = row["published_at"][:10]
        title = row["symbols_or_projects"] or "未命名案例"
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

    (ANALYSIS_DIR / "case_index.md").write_text("\n".join(lines), encoding="utf-8")


def queue_priority(row: dict[str, str]) -> tuple[int, str]:
    categories = split_pipe(row["method_categories"])
    flags = set(split_pipe(row["evidence_flags"]))
    if "贿赂/bundle/内部交易" in categories and {"tx", "block"} & flags:
        return 0, "P0 bundle/bribe with chain evidence"
    if "开盘/狙击/前排" in categories and ({"tx", "block", "lp_id"} & flags):
        return 1, "P1 sniping/opening with tx/block/LP evidence"
    if "加池/V3/LP区间" in categories and "lp_id" in flags:
        return 1, "P1 LP range with position evidence"
    if "地址/监控/工具" in categories and "address" in flags:
        return 2, "P2 address or contract evidence"
    if any(category in categories for category in ("跨链/桥/多链价差", "筹码/锁仓/tokenomics", "CEX/OI/Alpha上新")):
        return 3, "P3 catalyst/tokenomics/alpha context"
    return 4, "P4 method/opinion context"


def write_review_queue(rows: list[dict[str, str]]) -> None:
    ranked = sorted(rows, key=lambda row: (*queue_priority(row), row["published_at"]), reverse=False)
    lines = [
        "# 复盘队列",
        "",
        "排序规则：先看有 tx、block、LP ID、地址等链上证据的推文，再看纯观点或宏观判断。这个文件不丢弃样本，只给复核顺序。",
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
        lines.append(f"- {row['published_at'][:10]} [{title}]({row['tweet_url']}) `{evidence}` {row['method_categories']}")
    lines.append("")
    (ANALYSIS_DIR / "review_queue.md").write_text("\n".join(lines), encoding="utf-8")


def write_quality_report(
    raw_rows: list[dict[str, str]],
    method_rows: list[dict[str, str]],
    case_rows: list[dict[str, str]],
) -> None:
    media_manifest = read_csv(DATA_DIR / "media_manifest.csv")
    media_scopes = Counter(row.get("media_scope", "unknown") or "unknown" for row in media_manifest)
    embedded_rows = [
        row
        for row in raw_rows
        if row.get("embedded_or_quote_media_files") or row.get("embedded_or_quote_ocr_text")
    ]
    author_image_rows = [row for row in raw_rows if row.get("author_media_files")]
    oembed_rows = [
        row
        for row in raw_rows
        if "supplemental_oembed_candidate" in row.get("why_keep", "")
    ]
    unknown_image_rows = [row for row in raw_rows if row.get("has_image") == "unknown"]
    numeric_symbol_rows = [
        row
        for row in case_rows
        if any(part and part[0] == "$" and len(part) > 1 and part[1].isdigit() for part in split_pipe(row["symbols_or_projects"]))
    ]
    method_by_id = {row["id"]: row for row in method_rows}
    row_206784 = method_by_id.get("2067843840741163388")
    row_206777 = next((row for row in raw_rows if row.get("id") == "2067773586660851797"), None)

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
        "## 图片归属",
        "",
    ]
    for scope, count in sorted(media_scopes.items()):
        lines.append(f"- `{scope}`：{count}")
    lines.extend(
        [
            "",
            "默认分析只使用 `tweet_text`、`author_ocr_text`、链上字段和人工保留字段。`embedded_or_quote_ocr_text` 保留给复核，不参与默认分类。",
            "",
            "oEmbed 补采行只有推文正文、日期、短链和展开后的链上链接；若 `has_image=unknown`，代表原推可能有图，但本地尚未下载作者图片。",
            "",
        ]
    )

    if row_206777:
        author_count = len(split_pipe(row_206777.get("author_media_files", "")))
        embedded_count = len(split_pipe(row_206777.get("embedded_or_quote_media_files", "")))
        lines.extend(
            [
                "## 重点抽查",
                "",
                f"- `2067773586660851797`：作者图片 {author_count} 张，引用/嵌入图片 {embedded_count} 张。引用图已从默认 OCR 分类中分离。",
            ]
        )
    else:
        lines.extend(["## 重点抽查", ""])

    if row_206784:
        lines.append(
            f"- `2067843840741163388`：当前分类为 `{row_206784['categories']}`；已避免把普通小写字符串里的 `lp` 误判成 LP 区间。"
        )
    else:
        lines.append("- `2067843840741163388`：当前没有进入方法索引；已避免把普通小写字符串里的 `lp` 误判成 LP 区间。")

    if numeric_symbol_rows:
        bad_ids = ", ".join(row["id"] for row in numeric_symbol_rows[:10])
        lines.append(f"- 金额型 `$数字` 仍需检查：{bad_ids}")
    else:
        lines.append("- 金额型 `$数字` 已从 `symbols_or_projects` 过滤。")

    lines.extend(
        [
            "",
            "## 后续复核顺序",
            "",
            "1. 先复核带 `tx`、`block`、`lp_id` 的案例。",
            "2. 再复核只有地址或 OCR 的案例，确认地址属于项目方、交易所钱包、锁仓合约、桥合约还是普通钱包。",
            "3. 最后处理纯观点推文，把观点拆成可验证信号和作者推断。",
            "",
        ]
    )
    (ANALYSIS_DIR / "quality_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    raw_rows = read_csv(DATA_DIR / "raw_tweets.csv")

    method_rows = build_method_rows(raw_rows)
    case_rows = build_case_rows(raw_rows)

    write_csv(
        ANALYSIS_DIR / "method_index.csv",
        method_rows,
        [
            "id",
            "tweet_url",
            "published_at",
            "categories",
            "topic_tags",
            "chain",
            "platform",
            "evidence_flags",
            "has_tx",
            "has_addr",
            "has_lp_id",
            "author_media_files",
            "embedded_or_quote_media_files",
            "summary_seed",
        ],
    )
    write_csv(
        ANALYSIS_DIR / "case_index.csv",
        case_rows,
        [
            "id",
            "tweet_url",
            "published_at",
            "symbols_or_projects",
            "chain",
            "platform",
            "contract_addresses",
            "tx_hashes",
            "block_numbers",
            "lp_token_id",
            "method_categories",
            "evidence_flags",
            "needs_verification",
            "summary_seed",
        ],
    )
    write_method_library(method_rows)
    write_case_index_md(case_rows)
    write_review_queue(case_rows)
    write_quality_report(raw_rows, method_rows, case_rows)

    print(f"raw_rows={len(raw_rows)}")
    print(f"method_rows={len(method_rows)}")
    print(f"case_rows={len(case_rows)}")


if __name__ == "__main__":
    main()
