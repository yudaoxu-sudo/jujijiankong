from __future__ import annotations

from dataclasses import dataclass
import re


CATEGORY_POINTS = {
    "sniping": 12,
    "liquidity": 14,
    "bribe_bundle": 16,
    "bridge": 10,
    "tokenomics": 12,
    "address_monitoring": 12,
    "alpha": 10,
    "market_maker": 8,
}

EVIDENCE_POINTS = {
    "tx": 18,
    "block": 14,
    "lp_id": 14,
    "address": 10,
    "author_image": 4,
    "oembed": 1,
}


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


@dataclass(frozen=True)
class CandidateScore:
    score: int
    lane: str
    strengths: list[str]
    gaps: list[str]
    next_checks: list[str]


def score_candidate(row: dict[str, str]) -> CandidateScore:
    tags = set(split_pipe(row.get("topic_tags", "")))
    evidence = set(split_pipe(row.get("evidence_flags", "")))
    categories = set(split_pipe(row.get("categories", "")))
    summary = row.get("summary_seed", "")

    score = 0
    strengths: list[str] = []
    gaps: list[str] = []
    next_checks: list[str] = []

    for tag, points in CATEGORY_POINTS.items():
        if tag in tags:
            score += points
            strengths.append(f"{tag}+{points}")

    for flag, points in EVIDENCE_POINTS.items():
        if flag in evidence:
            score += points
            strengths.append(f"{flag}+{points}")

    if "bribe_bundle" in tags and re.search(r"\bBNB\b|贿赂|BlockRazor|Internal", summary, re.IGNORECASE):
        score += 10
        strengths.append("bribe_text+10")

    if "bribe_bundle" in tags and re.search(r"块内|同区块|send bundle|bundle", summary, re.IGNORECASE):
        score += 8
        strengths.append("block_bundle_text+8")

    if re.search(r"项目方.*狙|项目方.*买|低gas|低 gas", summary, re.IGNORECASE):
        score += 8
        strengths.append("project_side_buy_text+8")

    has_tx = row.get("has_tx") == "yes"
    has_addr = row.get("has_addr") == "yes"
    has_lp_id = row.get("has_lp_id") == "yes"
    has_block = "block" in evidence

    if "sniping" in tags and not (has_tx or has_block):
        score -= 10
        gaps.append("缺少开盘 tx/block")
        next_checks.append("补开盘区块和 transactionIndex")

    if "liquidity" in tags and not has_lp_id:
        score -= 8
        gaps.append("缺少 LP position ID")
        next_checks.append("补 V3 position、min price、max price")

    if "bribe_bundle" in tags and not (has_tx or has_block):
        score -= 12
        gaps.append("缺少 bundle/bribe 链上证据")
        next_checks.append("查 internal tx、debug trace、failed tx")

    if {"alpha", "bridge", "tokenomics"} & tags and not has_addr:
        score -= 8
        gaps.append("缺少合约或核心地址")
        next_checks.append("补 token 合约、项目方、桥、Alpha/CEX 地址")

    if "oembed" in evidence and not {"tx", "block", "lp_id", "address"} & evidence:
        score -= 6
        gaps.append("主要来自文本线索")
        next_checks.append("用 explorer 验证合约、地址、池子")

    if "market_maker" in tags and not has_addr:
        score -= 6
        gaps.append("庄/控盘判断缺少地址")
        next_checks.append("补囤货钱包、拉盘钱包、出货钱包")

    if "CEX/Alpha/上新" in categories or "CEX/OI/Alpha上新" in categories:
        next_checks.append("核对官方公告、Alpha/Boost 页面、交易所打币")

    if "bridge" in tags:
        next_checks.append("查跨链开关、bridge 事件、另一条链余量")

    score = max(0, min(score, 100))
    lane = decide_lane(score, has_tx, has_block, has_lp_id, has_addr, tags)
    return CandidateScore(
        score=score,
        lane=lane,
        strengths=dedupe(strengths),
        gaps=dedupe(gaps),
        next_checks=dedupe(next_checks),
    )


def decide_lane(
    score: int,
    has_tx: bool,
    has_block: bool,
    has_lp_id: bool,
    has_addr: bool,
    tags: set[str],
) -> str:
    hard_evidence = has_tx or has_block or has_lp_id
    if score >= 75 and hard_evidence:
        return "P0_DEEP_REVIEW"
    if score >= 62 and (hard_evidence or has_addr):
        return "P1_MONITOR"
    if score >= 48:
        return "P2_PAPER_TRADE"
    if {"sniping", "liquidity", "alpha", "bridge"} & tags:
        return "P3_BACKLOG"
    return "P4_CONTEXT"


def dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
