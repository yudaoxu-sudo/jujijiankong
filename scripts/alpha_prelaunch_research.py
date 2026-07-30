#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "alpha_prelaunch_research.v1"
NUMBER = r"[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:万|亿|[kKmMbB])?"
FULL_TIME_PATTERNS = (
    re.compile(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
        r"(\d{1,2})[:：](\d{2})"
    ),
    re.compile(
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s+"
        r"(\d{1,2})[:：](\d{2})"
    ),
)
CLOCK_RE = re.compile(r"(?<!\d)((?:[01]?\d|2[0-3])[:：]\d{2})(?!\d)")
FORECAST_TERMS = (
    r"(?:预计|预估|估计|预测|大概|可能|或于|"
    r"\b(?:expected|estimat(?:e|ed|es|ing)|forecast(?:s|ed|ing)?|"
    r"predict(?:s|ed|ing)?|prediction|project(?:ed|ing)|projection)\b)"
)
FORECAST_RE = re.compile(FORECAST_TERMS, re.I)
FORECAST_BLOCK_HEADER_RE = re.compile(
    r"(?:预计|预估|预测).{0,12}(?:如下|情景|假设|明细)|"
    r"\b(?:forecast|prediction|projection).{0,20}"
    r"(?:below|details?|scenario)\b",
    re.I,
)
ACTUAL_BLOCK_HEADER_RE = re.compile(
    r"^(?:#+\s*)?(?:(?:实际|实盘|已确认|官方确认|链上回执)"
    r"(?:如下|数据|结果|[:：\s]|$)|"
    r"(?:actual|confirmed|receipt)\b)",
    re.I,
)
EVENT_MARKERS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "alpha_open",
        "Binance Alpha",
        re.compile(r"币安\s*Alpha|Binance\s*Alpha|BN\s*Alpha", re.I),
    ),
    ("booster", "Binance Booster", re.compile(r"booster|助推", re.I)),
    (
        "airdrop_claim",
        "",
        re.compile(r"空投|领取|claim|airdrop", re.I),
    ),
    (
        "cex_trade",
        "",
        re.compile(
            r"Coinbase|Binance|OKX|Bybit|Bitget|Gate|MEXC|KuCoin|HTX|"
            r"多\s*CEX|交易所",
            re.I,
        ),
    ),
    ("tge", "", re.compile(r"\bTGE\b|代币生成", re.I)),
)
POOL_REVISION_RE = re.compile(
    rf"(?:池子价|池价|初始价(?:格)?)\D{{0,16}}({NUMBER})\s*"
    rf"(?:→|->|改为|调整为|降至|升至|到)\s*({NUMBER})",
    re.I,
)
POOL_PRICE_RE = re.compile(
    rf"(?:池子价|池价|初始价(?:格)?)\D{{0,16}}({NUMBER})",
    re.I,
)
RANGE_RE = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*(?:-|~|—|–|至)\s*"
    r"([0-9]+(?:\.[0-9]+)?)"
)
AMOUNT_ASSET_RE = re.compile(
    rf"({NUMBER})\s*(USDT|USDC|USD|U|[A-Z][A-Z0-9]{{1,15}})\b",
    re.I,
)
UTC8 = timezone(timedelta(hours=8))
EVIDENCE_KINDS = {"official", "onchain", "market", "social", "inference", "manual"}
EVIDENCE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$"
)
RESEARCH_CONTAINER_TYPES: tuple[
    tuple[tuple[str, ...], type],
    ...,
] = (
    (("conflicts",), list),
    (("missing_fields",), list),
    (("identity",), dict),
    (("timeline",), list),
    (("pool",), dict),
    (("pool", "segments"), list),
    (("pool", "price_revisions"), list),
    (("supply",), dict),
    (("supply", "allocations"), list),
    (("supply", "cross_chain"), list),
    (("venues",), dict),
    (("venues", "cex"), list),
    (("actors",), dict),
    (("actors", "market_makers"), list),
    (("opening_forecast",), dict),
    (("opening_actual",), dict),
    (("sniper_curve",), list),
    (("valuation",), dict),
    (("valuation", "anchors"), list),
    (("valuation", "prediction_markets"), list),
    (("sell_pressure_scenarios",), list),
    (("decision",), dict),
    (("market_context",), dict),
    (("event_distributions",), list),
)
RESEARCH_ROW_LIST_PATHS = {
    path
    for path, expected_type in RESEARCH_CONTAINER_TYPES
    if expected_type is list
    and path not in {("conflicts",), ("missing_fields",)}
}
REQUIRED_RESEARCH_PATHS = (
    ("evidence",),
    ("timeline",),
    ("pool", "segments"),
    ("supply", "allocations"),
    ("supply", "cross_chain"),
    ("venues", "cex"),
    ("actors", "market_makers"),
    ("sniper_curve",),
    ("valuation", "anchors"),
    ("sell_pressure_scenarios",),
)
RESEARCH_ROW_REQUIRED_KEY_GROUPS: dict[
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
] = {
    ("timeline",): (
        ("event", "event_type", "label", "kind"),
        ("time_utc", "time_utc8", "time_text"),
    ),
    ("pool", "segments"): (
        ("kind", "label", "position_id"),
    ),
    ("pool", "price_revisions"): (
        ("current_price_usdt", "predicted_price_usdt"),
    ),
    ("supply", "allocations"): (
        ("bucket_id", "role", "name", "label"),
    ),
    ("supply", "cross_chain"): (("chain",),),
    ("venues", "cex"): (("venue",),),
    ("actors", "market_makers"): (("address", "name"),),
    ("sniper_curve",): (
        ("buy_pressure_usdt", "snipe_amount_usdt"),
    ),
    ("valuation", "anchors"): (
        ("kind", "source"),
        ("price_usdt", "fdv_usd", "price_or_fdv"),
    ),
    ("valuation", "prediction_markets"): (
        ("source",),
        ("target_fdv_usd", "target_price_usdt"),
    ),
    ("sell_pressure_scenarios",): (
        ("scenario", "name"),
    ),
    ("event_distributions",): (("name", "label"),),
}
VALID_TIME_PRECISIONS = {
    "exact",
    "estimated",
    "time_only",
    "unknown",
}


def clean_decimal(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize_number(value: Any) -> str:
    text = str(value or "").replace(",", "").replace(" ", "")
    if not text:
        return ""
    multiplier = Decimal(1)
    suffix = text[-1:].lower()
    if suffix in {"k", "m", "b"}:
        text = text[:-1]
        multiplier = {
            "k": Decimal(1_000),
            "m": Decimal(1_000_000),
            "b": Decimal(1_000_000_000),
        }[suffix]
    elif text.endswith("万"):
        text = text[:-1]
        multiplier = Decimal(10_000)
    elif text.endswith("亿"):
        text = text[:-1]
        multiplier = Decimal(100_000_000)
    try:
        return clean_decimal(Decimal(text) * multiplier)
    except (InvalidOperation, ValueError):
        return ""


def forecast_context_lines(text: str) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    active_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            rows.append((line, False))
            continue
        if ACTUAL_BLOCK_HEADER_RE.search(stripped):
            active_block = False
        explicit = bool(FORECAST_RE.search(line))
        is_header = bool(
            FORECAST_BLOCK_HEADER_RE.search(stripped)
            or (
                explicit
                and stripped.endswith((":", "："))
                and not re.search(r"\d", stripped)
            )
        )
        rows.append((line, explicit or active_block or is_header))
        if is_header:
            active_block = True
    return rows


def forecast_context_at(text: str, position: int) -> bool:
    line_index = text.count("\n", 0, max(0, position))
    rows = forecast_context_lines(text)
    return 0 <= line_index < len(rows) and rows[line_index][1]


def evidence_id(source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"signal-{digest}"


def normalize_source_policy(source_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = source_policy if isinstance(source_policy, dict) else {}
    evidence_layer = str(policy.get("evidence_layer") or "social").strip().lower()
    if evidence_layer not in EVIDENCE_KINDS:
        evidence_layer = "social"
    context_value = policy.get("context_only")
    context_only = context_value is True or str(context_value).strip().lower() == "true"
    authority = str(policy.get("authority") or "").strip()
    if context_only:
        authority = "context_only"
    elif not authority:
        authority = (
            "social_discovery"
            if evidence_layer == "social"
            else f"{evidence_layer}_discovery"
        )
    return {
        "evidence_layer": evidence_layer,
        "authority": authority,
        "context_only": context_only,
    }


def source_kind(source_ref: str, default_kind: str) -> str:
    normalized = source_ref.lower()
    if any(value in normalized for value in ("x.com/", "twitter.com/", "t.me/")):
        return "social"
    if any(
        value in normalized
        for value in (
            "etherscan.io/",
            "bscscan.com/",
            "arbiscan.io/",
            "basescan.org/",
            "polygonscan.com/",
            "optimistic.etherscan.io/",
            "solscan.io/",
            "tronscan.org/",
        )
    ):
        return "onchain"
    if any(
        value in normalized
        for value in (
            "polymarket.com/",
            "predict.fun/",
            "dexscreener.com/",
            "coingecko.com/",
            "coinmarketcap.com/",
        )
    ):
        return "market"
    return default_kind


def source_evidence(
    urls: list[str],
    source_path: Path | None,
    observed_at: str,
    *,
    source_policy: dict[str, Any] | None = None,
    source_text: str = "",
) -> list[dict[str, Any]]:
    policy = normalize_source_policy(source_policy)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_ref in urls:
        source_ref = str(source_ref or "").strip()
        if not source_ref or source_ref in seen:
            continue
        seen.add(source_ref)
        rows.append(
            {
                "evidence_id": evidence_id(source_ref),
                "evidence_kind": source_kind(
                    source_ref,
                    policy["evidence_layer"],
                ),
                "evidence_role": "source_reference",
                "source_ref": source_ref,
                "observed_at": observed_at,
                "authority": policy["authority"],
                "context_only": policy["context_only"],
                "verification_status": "unverified",
            }
        )
    envelope_ref = (
        str(source_path)
        if source_path
        else f"inline_signal:{hashlib.sha256(source_text.encode('utf-8')).hexdigest()[:16]}"
    )
    rows.append(
        {
            "evidence_id": evidence_id(envelope_ref),
            "evidence_kind": policy["evidence_layer"],
            "evidence_role": "signal_envelope",
            "source_ref": envelope_ref,
            "observed_at": observed_at,
            "authority": policy["authority"],
            "context_only": policy["context_only"],
            "verification_status": "unverified",
        }
    )
    return rows


def scoped_claim_evidence(
    envelope: dict[str, Any],
    claim_scope: str,
) -> dict[str, Any]:
    source_ref = str(envelope.get("source_ref") or "")
    row = dict(envelope)
    row.update(
        {
            "evidence_id": evidence_id(f"{source_ref}#{claim_scope}"),
            "evidence_role": "claim_source",
            "claim_scope": claim_scope,
        }
    )
    return row


def _line_bounds(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return start, len(text) if end < 0 else end


def _nearest_event(text: str, position: int) -> tuple[str, str]:
    line_start, line_end = _line_bounds(text, position)
    line = text[line_start:line_end]
    local_position = position - line_start
    candidates: list[tuple[int, int, str, str]] = []
    for priority, (event_type, venue, pattern) in enumerate(EVENT_MARKERS):
        for match in pattern.finditer(line):
            distance = min(
                abs(local_position - match.start()),
                abs(local_position - match.end()),
            )
            candidates.append((distance, priority, event_type, venue))
    if not candidates:
        return "unknown_event", ""
    _, _, event_type, venue = min(candidates)
    return event_type, venue


def utc_iso_from_utc8(value: str) -> str:
    if len(value) != 16:
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
            tzinfo=UTC8
        )
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).isoformat()


def extract_event_schedule(
    text: str,
    evidence_ids: list[str],
    *,
    authority: str = "social_discovery",
) -> list[dict[str, Any]]:
    full_occurrences: list[tuple[int, int, str]] = []
    for pattern in FULL_TIME_PATTERNS:
        for match in pattern.finditer(text):
            year, month, day, hour, minute = (int(value) for value in match.groups())
            full_occurrences.append(
                (
                    match.start(),
                    match.end(),
                    f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
                )
            )
    full_occurrences.sort()
    occurrences = list(full_occurrences)
    for match in CLOCK_RE.finditer(text):
        if any(start <= match.start() < end for start, end, _ in full_occurrences):
            continue
        clock = match.group(1).replace("：", ":")
        anchor_date = next(
            (
                value[:10]
                for start, _, value in reversed(full_occurrences)
                if start < match.start()
            ),
            "",
        )
        value = f"{anchor_date} {clock}" if anchor_date else clock
        occurrences.append((match.start(), match.end(), value))
    occurrences.sort()

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start, _, value in occurrences:
        event_type, venue = _nearest_event(text, start)
        if event_type == "unknown_event":
            continue
        precision = "exact" if len(value) == 16 else "time_only"
        if forecast_context_at(text, start):
            precision = "estimated" if len(value) == 16 else "unknown"
        row = {
            "event": event_type,
            "event_type": event_type,
            "venue": venue,
            "time_utc8": value if len(value) == 16 else "",
            "time_utc": utc_iso_from_utc8(value),
            "time_text": value,
            "time_precision": precision,
            "authority": authority,
            "verification_status": "unverified",
            "evidence_ids": evidence_ids,
        }
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def pool_segment_from_line(
    line: str,
    symbol: str,
    evidence_ids: list[str],
) -> dict[str, Any] | None:
    if not re.search(r"池|流动性|区间|range", line, re.I):
        return None
    range_match = RANGE_RE.search(line)
    if not range_match:
        return None
    assets = []
    for amount, asset in AMOUNT_ASSET_RE.findall(line[range_match.end() :]):
        normalized = normalize_number(amount)
        if normalized:
            assets.append(
                {
                    "asset": asset.upper(),
                    "amount": normalized,
                }
            )
    if not assets:
        return None
    quote_amount = next(
        (
            row["amount"]
            for row in assets
            if row["asset"] in {"USDT", "USDC", "USD", "U"}
        ),
        "",
    )
    token_amount = next(
        (
            row["amount"]
            for row in assets
            if row["asset"] == symbol.upper()
        ),
        "",
    )
    return {
        "kind": (
            "two_sided_range"
            if quote_amount and token_amount
            else "buy_support"
            if quote_amount
            else "sell_zone"
        ),
        "min_price_usdt": range_match.group(1),
        "max_price_usdt": range_match.group(2),
        "token_amount": token_amount,
        "quote_amount_usdt": quote_amount,
        "verification_status": "unverified",
        "evidence_ids": evidence_ids,
    }


def extract_pool_research(
    text: str,
    symbol: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    pool: dict[str, Any] = {"segments": [], "price_revisions": []}
    for line, is_forecast in forecast_context_lines(text):
        if is_forecast:
            continue
        revision = POOL_REVISION_RE.search(line)
        if revision and not pool["price_revisions"]:
            pool["price_revisions"].append(
                {
                    "previous_price_usdt": normalize_number(revision.group(1)),
                    "current_price_usdt": normalize_number(revision.group(2)),
                    "verification_status": "unverified",
                    "evidence_ids": evidence_ids,
                }
            )
            pool["initial_price_usdt"] = normalize_number(revision.group(2))
        segment = pool_segment_from_line(line, symbol, evidence_ids)
        if segment is not None:
            pool["segments"].append(segment)
    return pool


def extract_opening_forecast(
    text: str,
    evidence_ids: list[str],
    *,
    authority: str = "social_discovery",
    symbol: str = "",
) -> dict[str, Any]:
    rows = {
        "buy_quote_usdt": re.compile(
            rf"(?:狙击|买入)\D{{0,12}}({NUMBER})",
            re.I,
        ),
        "bribe_quote_usdt": re.compile(
            rf"(?:bribe|贿赂)\D{{0,12}}({NUMBER})",
            re.I,
        ),
        "predicted_fill_avg_usdt": re.compile(
            rf"(?:均价|平均成本|平均价格)\D{{0,12}}({NUMBER})",
            re.I,
        ),
    }
    forecast: dict[str, Any] = {}
    predicted_revisions = []
    predicted_segments = []
    for line, is_forecast in forecast_context_lines(text):
        if not is_forecast:
            continue
        for key, pattern in rows.items():
            if key in forecast:
                continue
            match = pattern.search(line)
            if match:
                forecast[key] = normalize_number(match.group(1))
        revision = POOL_REVISION_RE.search(line)
        if revision:
            predicted_price = normalize_number(revision.group(2))
            predicted_revisions.append(
                {
                    "previous_predicted_price_usdt": normalize_number(
                        revision.group(1)
                    ),
                    "predicted_price_usdt": predicted_price,
                    "verification_status": "unverified",
                    "evidence_ids": evidence_ids,
                }
            )
            forecast["predicted_pool_price_usdt"] = predicted_price
        else:
            pool_price = POOL_PRICE_RE.search(line)
            if pool_price:
                forecast["predicted_pool_price_usdt"] = normalize_number(
                    pool_price.group(1)
                )
        segment = pool_segment_from_line(line, symbol, evidence_ids)
        if segment is not None:
            predicted_segments.append(segment)
    if predicted_revisions:
        forecast["predicted_pool_price_revisions"] = predicted_revisions
    if predicted_segments:
        forecast["predicted_pool_segments"] = predicted_segments
    if forecast:
        forecast.update(
            {
                "evidence_kind": "social",
                "authority": authority,
                "verification_status": "unverified",
                "evidence_ids": evidence_ids,
            }
        )
    return forecast


def bucket_identifier(value: Any, fallback_index: int) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if normalized:
        return normalized
    if raw:
        return f"bucket_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"
    return f"allocation_{fallback_index + 1}"


def build_allocations(
    values: Any,
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    source_rows = values if isinstance(values, list) else []
    rows: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, value in enumerate(source_rows):
        if not isinstance(value, dict):
            continue
        label = str(value.get("label") or value.get("role") or "").strip()
        bucket_id = bucket_identifier(
            value.get("bucket_id") or label,
            index,
        )
        if bucket_id in used_ids:
            bucket_id = f"{bucket_id}_{index + 1}"
        used_ids.add(bucket_id)
        parent_value = (
            value.get("parent_bucket_id")
            or value.get("parent")
            or value.get("parent_label")
            or ""
        )
        parent_bucket_id = (
            bucket_identifier(parent_value, index)
            if str(parent_value or "").strip()
            else ""
        )
        rows.append(
            {
                "bucket_id": bucket_id,
                "parent_bucket_id": parent_bucket_id,
                "aggregation_policy": str(
                    value.get("aggregation_policy") or ""
                ).strip(),
                "role": label,
                "percent": str(value.get("percent") or "").rstrip("%"),
                "verification_status": "unverified",
                "evidence_ids": evidence_ids,
            }
        )
    parent_ids = {
        row["parent_bucket_id"]
        for row in rows
        if row["parent_bucket_id"]
    }
    for row in rows:
        if row["bucket_id"] in parent_ids:
            row["aggregation_policy"] = "parent_not_summed_with_children"
        elif row["parent_bucket_id"]:
            row["aggregation_policy"] = (
                row["aggregation_policy"] or "child_of_parent"
            )
        else:
            row["aggregation_policy"] = (
                row["aggregation_policy"] or "standalone"
            )
    return rows


def build_valuation_anchors(
    prices: dict[str, Any],
    observed_at: str,
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    kind_map = {
        "pool_price": "pool",
        "premarket_price": "premarket",
        "sniper_price": "sniper_forecast",
        "launch_fdv": "launch_forecast",
    }
    rows = []
    for key, value in prices.items():
        normalized = normalize_number(value)
        if not normalized:
            continue
        is_fdv = "fdv" in str(key).lower()
        rows.append(
            {
                "kind": kind_map.get(str(key), str(key)),
                "source_field": str(key),
                "price_usdt": "" if is_fdv else normalized,
                "fdv_usd": normalized if is_fdv else "",
                "as_of": observed_at,
                "verification_status": "unverified",
                "evidence_ids": evidence_ids,
            }
        )
    return rows


def normalize_conflicts(values: Any) -> list[dict[str, str]]:
    source_rows = values if isinstance(values, list) else []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(source_rows):
        if isinstance(value, dict):
            path = str(value.get("path") or f"conflicts[{index}]").strip()
            detail = str(value.get("detail") or "conflict").strip()
        else:
            path = f"conflicts[{index}]"
            detail = str(value or "conflict").strip()
        key = (path, detail)
        if key not in seen:
            seen.add(key)
            rows.append({"path": path, "detail": detail})
    return rows


def normalize_prelaunch_research(research: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(research)
    conflicts = normalize_conflicts(normalized.get("conflicts"))

    def add_conflict(path: str, detail: str) -> None:
        key = (path, detail)
        if any(
            (row.get("path"), row.get("detail")) == key
            for row in conflicts
        ):
            return
        conflicts.append({"path": path, "detail": detail})

    if normalized.get("schema_version") != SCHEMA_VERSION:
        add_conflict(
            "schema_version",
            f"expected {SCHEMA_VERSION}",
        )

    missing_container = object()
    for path_parts, expected_type in RESEARCH_CONTAINER_TYPES:
        value: Any = normalized
        for key in path_parts:
            if not isinstance(value, dict) or key not in value:
                value = missing_container
                break
            value = value[key]
        if value is missing_container:
            continue
        path = ".".join(path_parts)
        if not isinstance(value, expected_type):
            add_conflict(
                path,
                f"expected {expected_type.__name__}",
            )
            continue
        if path_parts in RESEARCH_ROW_LIST_PATHS:
            for index, row in enumerate(value):
                if not isinstance(row, dict):
                    add_conflict(
                        f"{path}[{index}]",
                        "row must be an object",
                    )
                    continue
                for key_group in RESEARCH_ROW_REQUIRED_KEY_GROUPS.get(
                    path_parts,
                    (),
                ):
                    if not any(
                        row.get(key) not in (None, "", [], {})
                        for key in key_group
                    ):
                        add_conflict(
                            f"{path}[{index}]",
                            (
                                "row requires one of "
                                + ",".join(key_group)
                            ),
                        )

    evidence = normalized.get("evidence")
    evidence_rows = evidence if isinstance(evidence, list) else []
    if not evidence_rows:
        add_conflict("evidence", "at least one evidence row is required")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(evidence_rows):
        path = f"evidence[{index}]"
        if not isinstance(row, dict):
            add_conflict(path, "evidence row must be an object")
            continue
        row_id = str(row.get("evidence_id") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        if not row_id:
            add_conflict(f"{path}.evidence_id", "evidence_id is required")
        elif not EVIDENCE_ID_RE.fullmatch(row_id):
            add_conflict(
                f"{path}.evidence_id",
                f"invalid evidence_id {row_id}",
            )
        elif row_id in evidence_by_id:
            add_conflict(f"{path}.evidence_id", f"duplicate evidence_id {row_id}")
        else:
            evidence_by_id[row_id] = row
        if not source_ref:
            add_conflict(f"{path}.source_ref", "source_ref is required")
        elif row_id.startswith("signal-"):
            claim_scope = str(row.get("claim_scope") or "").strip()
            identity_ref = (
                f"{source_ref}#{claim_scope}"
                if claim_scope
                else source_ref
            )
            if row_id != evidence_id(identity_ref):
                add_conflict(
                    f"{path}.evidence_id",
                    "signal evidence_id does not match source_ref",
                )

    def validate_claims(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            if "time_precision" in value:
                precision = str(
                    value.get("time_precision") or ""
                ).strip().lower()
                if precision not in VALID_TIME_PRECISIONS:
                    add_conflict(
                        f"{path}.time_precision".strip("."),
                        f"invalid time_precision {precision or 'empty'}",
                    )
            if str(value.get("verification_status") or "").lower() == "conflicted":
                add_conflict(
                    path or "prelaunch_research",
                    "verification_status is conflicted",
                )
            if "verification_status" in value:
                references = value.get("evidence_ids")
                reference_ids = (
                    [
                        str(item).strip()
                        for item in references
                        if str(item).strip()
                    ]
                    if isinstance(references, list)
                    else []
                )
                if not reference_ids:
                    add_conflict(
                        f"{path}.evidence_ids".strip("."),
                        "claim evidence_ids are required",
                    )
                for reference_id in reference_ids:
                    if reference_id not in evidence_by_id:
                        add_conflict(
                            f"{path}.evidence_ids".strip("."),
                            f"unknown evidence_id {reference_id}",
                        )
            for key, item in value.items():
                if key == "evidence":
                    continue
                child_path = f"{path}.{key}".strip(".")
                validate_claims(item, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                validate_claims(item, f"{path}[{index}]")

    validate_claims(normalized)
    missing_values = (
        {
            str(value).strip()
            for value in normalized.get("missing_fields", [])
            if str(value).strip()
        }
        if isinstance(normalized.get("missing_fields"), list)
        else set()
    )
    for path_parts in REQUIRED_RESEARCH_PATHS:
        value: Any = normalized
        for key in path_parts:
            if not isinstance(value, dict) or key not in value:
                value = missing_container
                break
            value = value[key]
        if (
            value is missing_container
            or value in (None, "", [], {})
        ):
            missing_values.add(".".join(path_parts))
    missing = sorted(missing_values)
    supplied_status = str(normalized.get("research_status") or "").lower()
    if conflicts or supplied_status in {"blocked", "conflicted"}:
        status = "blocked"
    elif missing or supplied_status == "partial":
        status = "partial"
    else:
        status = "ready"
    normalized["evidence"] = evidence_rows
    normalized["conflicts"] = conflicts
    normalized["missing_fields"] = missing
    normalized["research_status"] = status
    return normalized


def build_prelaunch_research(
    *,
    text: str,
    symbol: str,
    urls: list[str],
    addresses: list[dict[str, Any]],
    prices: dict[str, Any],
    facts: dict[str, Any],
    source_path: Path | None,
    observed_at: str,
    source_policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = normalize_source_policy(source_policy)
    source_rows = source_evidence(
        urls,
        source_path,
        observed_at,
        source_policy=policy,
        source_text=text,
    )
    envelope = next(
        row
        for row in source_rows
        if row.get("evidence_role") == "signal_envelope"
    )
    evidence = [
        row
        for row in source_rows
        if row.get("evidence_role") == "source_reference"
    ]
    scoped_ids: dict[str, list[str]] = {}

    def evidence_for(claim_scope: str) -> list[str]:
        if claim_scope not in scoped_ids:
            row = scoped_claim_evidence(envelope, claim_scope)
            evidence.append(row)
            scoped_ids[claim_scope] = [str(row["evidence_id"])]
        return scoped_ids[claim_scope]

    identity_evidence_ids = evidence_for("identity")
    timeline_evidence_ids = evidence_for("timeline")
    pool_evidence_ids = evidence_for("pool")
    supply_evidence_ids = evidence_for("supply")
    venue_evidence_ids = evidence_for("venues")
    forecast_evidence_ids = evidence_for("opening_forecast")
    valuation_evidence_ids = evidence_for("valuation")

    schedule = extract_event_schedule(
        text,
        timeline_evidence_ids,
        authority=policy["authority"],
    )
    pool = extract_pool_research(text, symbol, pool_evidence_ids)
    pool.update(
        {
            "verification_status": "unverified",
            "evidence_ids": pool_evidence_ids,
        }
    )
    forecast = extract_opening_forecast(
        text,
        forecast_evidence_ids,
        authority=policy["authority"],
        symbol=symbol,
    )
    contracts = [
        str(row.get("address") or "").lower()
        for row in addresses
        if row.get("label_hint") == "token_contract"
    ]
    allocations = build_allocations(
        facts.get("allocations"),
        supply_evidence_ids,
    )
    anchors = build_valuation_anchors(
        prices,
        observed_at,
        valuation_evidence_ids,
    )
    alpha_openings = [
        row
        for row in schedule
        if row["event_type"] == "alpha_open"
        and row["time_precision"] == "exact"
        and row.get("time_utc8")
    ]
    missing = []
    if len(contracts) != 1:
        missing.append("identity.contract")
    if len(alpha_openings) != 1:
        missing.append("timeline.alpha_open")
    if not pool.get("segments"):
        missing.append("pool.segments")
    if not allocations:
        missing.append("supply.allocations")
    if not facts.get("total_supply"):
        missing.append("supply.total_supply")
    if not forecast:
        missing.append("opening_forecast")
    if not anchors:
        missing.append("valuation.anchors")
    conflicts = (
        [
            {
                "path": "timeline.alpha_open",
                "detail": "multiple exact Alpha opening times",
            }
        ]
        if len(alpha_openings) > 1
        else []
    )
    total_supply = str(facts.get("total_supply") or "")
    initial_float = str(facts.get("initial_float") or "")
    research = {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "as_of": observed_at,
        "research_status": "blocked" if conflicts else "partial",
        "source_policy": policy,
        "evidence": evidence,
        "identity": {
            "chain": next(
                (
                    str(row.get("chain") or "")
                    for row in addresses
                    if row.get("label_hint") == "token_contract"
                ),
                "",
            ),
            "contract": contracts[0] if len(contracts) == 1 else "",
            "verification_status": "unverified",
            "evidence_ids": identity_evidence_ids,
        },
        "timeline": schedule,
        "pool": pool,
        "supply": {
            "total_supply": total_supply,
            "total_supply_claim": (
                {
                    "amount": total_supply,
                    "verification_status": "unverified",
                    "evidence_ids": supply_evidence_ids,
                }
                if total_supply
                else {}
            ),
            "initial_float": initial_float,
            "initial_float_claim": (
                {
                    "amount": initial_float,
                    "verification_status": "unverified",
                    "evidence_ids": supply_evidence_ids,
                }
                if initial_float
                else {}
            ),
            "allocations": allocations,
            "cross_chain": [],
        },
        "venues": {
            "cex": [
                {
                    "venue": str(venue),
                    "verification_status": "unverified",
                    "evidence_ids": venue_evidence_ids,
                }
                for venue in facts.get("venues", [])
            ]
        },
        "actors": {"market_makers": []},
        "opening_forecast": forecast,
        "opening_actual": {},
        "sniper_curve": [],
        "valuation": {"anchors": anchors, "prediction_markets": []},
        "sell_pressure_scenarios": [],
        "decision": {
            "action": "Observe",
            "summary": "盘前来源信息已结构化，等待官方、链上和市场证据逐项升级",
            "entry_conditions": [],
            "exit_triggers": [],
            "next_checks": missing[:],
        },
        "missing_fields": missing,
        "conflicts": conflicts,
    }
    return normalize_prelaunch_research(research), schedule
