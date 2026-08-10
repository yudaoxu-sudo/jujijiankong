#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.alpha_prelaunch_research import (
    normalize_prelaunch_research as validate_prelaunch_research,
)


CONFIG_PATH = Path(
    os.environ.get("ALPHA_WATCHLIST_PATH", ROOT / "config" / "current_alpha_watchlist.json")
)
AIRDROP_CONFIG_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "alpha_prelaunch_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
SEEN_PATH = OUT_DIR / "seen_alerts.json"
AIRDROP_SEEN_PATH = OUT_DIR / "seen_airdrop_alerts.json"
UTC8 = timezone(timedelta(hours=8))
TELEGRAM_LIMIT = 4000
RESEARCH_SCHEMA_VERSION = "alpha_prelaunch_research.v1"
FINGERPRINT_IGNORED_KEYS = {
    "as_of",
    "fetched_at",
    "generated_at",
    "last_checked_at",
    "observed_at",
    "research_fingerprint",
    "updated_at",
}
REQUIRED_RESEARCH_SECTIONS = (
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
STATUS_BADGES = {
    "verified": "[V]",
    "unverified": "[U]",
    "conflicted": "[C]",
    "stale": "[S]",
}
AIRDROP_EVENT_TYPES = frozenset({"airdrop_claim", "airdrop_release"})
OFFICIAL_AIRDROP_AUTHORITIES = frozenset(
    {
        "binance_wallet_official",
        "dappos_official",
        "project_official",
        "exchange_official",
    }
)
OFFICIAL_EVIDENCE_KINDS = frozenset({"official", "official_exchange"})
ONCHAIN_RECEIPT_EVIDENCE_KINDS = frozenset({"onchain:receipt"})
VENUE_CANDIDATE_EVIDENCE_KINDS = frozenset(
    {"onchain:receipt", "onchain:sample", "market:coverage"}
)
ONCHAIN_CLOSURE_EVIDENCE_KINDS = frozenset({"onchain:coverage"})
ONCHAIN_ATTRIBUTION_EVIDENCE_KINDS = frozenset(
    {"onchain:receipt", "onchain:coverage"}
)
DOWNSTREAM_VENUE_EVIDENCE_KINDS = {
    "CEX": frozenset({"official_exchange", "market:coverage"}),
    "DEX": frozenset({"onchain:coverage", "market:coverage"}),
}
AIRDROP_REVISION_EVIDENCE_KINDS = frozenset().union(
    OFFICIAL_EVIDENCE_KINDS,
    VENUE_CANDIDATE_EVIDENCE_KINDS,
    ONCHAIN_CLOSURE_EVIDENCE_KINDS,
    ONCHAIN_ATTRIBUTION_EVIDENCE_KINDS,
    *(kinds for kinds in DOWNSTREAM_VENUE_EVIDENCE_KINDS.values()),
)
AIRDROP_CLOSURE_REQUIRED_FLAGS = (
    "claim_closed",
    "distribution_identity_verified",
    "finalized_log_coverage_complete",
    "residual_inventory_closed",
    "recipient_next_hop_complete",
    "downstream_activity_window_complete",
)


def now_utc() -> datetime:
    override = os.environ.get("ALPHA_PRELAUNCH_NOW_UTC", "").strip()
    if override:
        return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_known_time(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("time") or value.get("startedTime") or value.get("start_time")
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("UTC+8", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC8).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def schedule_start(row: dict[str, Any]) -> datetime | None:
    for key in ("claim_start_utc", "release_time_utc", "time_utc"):
        parsed = parse_iso_utc(row.get(key))
        if parsed:
            return parsed
    for key in ("time_utc8", "time"):
        parsed = parse_known_time(row.get(key))
        if parsed:
            return parsed
    return None


def schedule_end(row: dict[str, Any]) -> datetime | None:
    for key in ("claim_end_utc", "end_time_utc"):
        parsed = parse_iso_utc(row.get(key))
        if parsed:
            return parsed
    return parse_known_time(row.get("end_time_utc8"))


def phase_for_delta(delta: timedelta) -> str:
    seconds = delta.total_seconds()
    if seconds < -1800:
        return "expired"
    if seconds <= 0:
        return "LIVE_WINDOW"
    minutes = seconds / 60
    if minutes <= 30:
        return "T_MINUS_30M"
    if minutes <= 120:
        return "T_MINUS_2H"
    if minutes <= 360:
        return "T_MINUS_6H"
    if minutes <= 1440:
        return "T_MINUS_24H"
    return "T_MINUS_48H"


def phase_action(phase: str) -> str:
    actions = {
        "T_MINUS_48H": "进入预备观察；确认官方合约、活动分发、池子参数",
        "T_MINUS_24H": "进入上线前监控；重点看是否追加池子、桥、交易所活动",
        "T_MINUS_6H": "进入冲刺观察；准备开盘块、bribe、首批买入和承接验证",
        "T_MINUS_2H": "开盘前严密盯盘；未见真实加池和首批有效买入前不追",
        "T_MINUS_30M": "进入临战窗口；只接受链上强证据，禁止凭预期追高",
        "LIVE_WINDOW": "开盘窗口；看首块顺序、有效买入、出货和承接",
    }
    return actions.get(phase, "观察")


def short_addr(value: str) -> str:
    if len(value or "") <= 14:
        return value or "-"
    return value[:8] + "..." + value[-6:]


def display_name(item: dict[str, Any]) -> str:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    project = str(facts.get("project_name") or "").strip()
    raw_symbol = str(facts.get("raw_symbol") or item.get("symbol") or "").strip()
    display = str(facts.get("display_symbol") or "").strip()
    if display and raw_symbol and display.upper() != raw_symbol.upper():
        symbol = f"{display}/{raw_symbol}"
    else:
        symbol = raw_symbol or str(item.get("symbol") or "UNKNOWN")
    return f"{symbol} · {project}" if project else symbol


def first_contract(item: dict[str, Any]) -> dict[str, str]:
    for row in item.get("contracts", []):
        if isinstance(row, dict) and row.get("address"):
            return {"chain": str(row.get("chain") or ""), "address": str(row.get("address") or "")}
    return {"chain": "", "address": ""}


def fingerprint_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: fingerprint_payload(item)
            for key, item in sorted(value.items())
            if key not in FINGERPRINT_IGNORED_KEYS
        }
    if isinstance(value, list):
        normalized = [fingerprint_payload(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def research_fingerprint(research: dict[str, Any]) -> str:
    payload = json.dumps(
        fingerprint_payload(research),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def has_conflicted_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        if str(value.get("verification_status") or "").lower() == "conflicted":
            return True
        return any(has_conflicted_evidence(item) for item in value.values())
    if isinstance(value, list):
        return any(has_conflicted_evidence(item) for item in value)
    return False


def prepare_prelaunch_research(item: dict[str, Any]) -> dict[str, Any]:
    supplied = item.get("prelaunch_research")
    has_supplied_research = isinstance(supplied, dict) and bool(supplied)
    research = copy.deepcopy(supplied) if has_supplied_research else {}
    if not has_supplied_research:
        research.update(
            {
                "schema_version": RESEARCH_SCHEMA_VERSION,
                "evidence": [],
                "conflicts": [],
            }
        )

    market_context = item.get("market_context")
    if isinstance(market_context, dict) and market_context:
        research.setdefault("market_context", copy.deepcopy(market_context))
    event_distributions = item.get("event_distributions")
    if isinstance(event_distributions, list) and event_distributions:
        research.setdefault(
            "event_distributions",
            copy.deepcopy(event_distributions),
        )
    if has_supplied_research:
        research = validate_prelaunch_research(research)

    missing = {
        str(value)
        for value in research.get("missing_fields", [])
        if str(value).strip()
    }
    if not has_supplied_research:
        missing.add("prelaunch_research")
    for path in REQUIRED_RESEARCH_SECTIONS:
        value = nested_value(research, path)
        if value in (None, "", [], {}):
            missing.add(".".join(path))

    conflicts = research.get("conflicts")
    blocked = bool(conflicts) or has_conflicted_evidence(research)
    supplied_status = str(research.get("research_status") or "").lower()
    if blocked or supplied_status in {"blocked", "conflicted"}:
        status = "blocked"
    elif missing or supplied_status == "partial":
        status = "partial"
    else:
        status = "ready"
    research["research_status"] = status
    research["missing_fields"] = sorted(missing)
    research["research_fingerprint"] = research_fingerprint(research)
    return research


def airdrop_schedule_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("event_schedule")
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("event_type") or "").lower()
        in AIRDROP_EVENT_TYPES
    ]


def evidence_supports(row: dict[str, Any], support: str) -> bool:
    values = row.get("supports")
    return isinstance(values, list) and support in values


def evidence_kind_key(row: dict[str, Any]) -> str:
    kind = str(row.get("evidence_kind") or "").lower()
    subtype = str(row.get("evidence_subtype") or "").lower()
    return kind + (f":{subtype}" if subtype else "")


def resolve_evidence(
    evidence_ids: Any,
    research: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    ids = (
        [str(value).strip() for value in evidence_ids]
        if isinstance(evidence_ids, list)
        else []
    )
    ids = [value for value in ids if value]
    rows = research_rows(research.get("evidence"))
    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for value in ids:
        matches = [
            row
            for row in rows
            if str(row.get("evidence_id") or "").strip() == value
        ]
        if len(matches) != 1:
            unresolved.append(value)
            continue
        match = matches[0]
        if (
            not str(match.get("source_ref") or "").strip()
            or str(match.get("verification_status") or "").lower()
            not in STATUS_BADGES
            or not str(match.get("evidence_kind") or "").strip()
        ):
            unresolved.append(value)
            continue
        resolved.append(match)
    return ids, resolved, unresolved


def verified_support(
    rows: list[dict[str, Any]],
    support: str,
    kinds: frozenset[str],
) -> bool:
    return any(
        str(row.get("verification_status") or "").lower() == "verified"
        and evidence_kind_key(row) in kinds
        and evidence_supports(row, support)
        for row in rows
    )


def verified_reorg_support(
    rows: list[dict[str, Any]],
    event_id: str,
) -> bool:
    support = f"airdrop_venue_sell_reorg_pending:{event_id}"
    for row in rows:
        block_number = row.get("block_number")
        block_hash = str(row.get("block_hash") or "").lower()
        if (
            str(row.get("verification_status") or "").lower() == "verified"
            and evidence_kind_key(row) in ONCHAIN_RECEIPT_EVIDENCE_KINDS
            and evidence_supports(row, support)
            and row.get("reorg_status") == "pending"
            and isinstance(block_number, int)
            and not isinstance(block_number, bool)
            and block_number >= 0
            and len(block_hash) == 66
            and block_hash.startswith("0x")
            and all(value in "0123456789abcdef" for value in block_hash[2:])
        ):
            return True
    return False


def nested_evidence_ids(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        evidence_ids = value.get("evidence_ids")
        if isinstance(evidence_ids, list):
            values.extend(
                str(evidence_id).strip()
                for evidence_id in evidence_ids
                if str(evidence_id).strip()
            )
        for key, child in value.items():
            if key != "evidence_ids":
                values.extend(nested_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(nested_evidence_ids(child))
    return list(dict.fromkeys(values))


def airdrop_semantic_revision(
    row: dict[str, Any],
    research: dict[str, Any],
    event_id: str,
    *,
    start: datetime | None,
    end: datetime | None,
    start_verified: bool,
    end_verified: bool,
    venue_state: str,
    attribution_state: str,
    closure_verified: bool,
    identity_verified: bool,
    reminder_state: str,
    pressure_state: str,
    clearance_state: str,
) -> str:
    evidence_ids: list[str] = []
    if start_verified or end_verified:
        evidence_ids.extend(nested_evidence_ids({"evidence_ids": row.get("evidence_ids")}))
    if venue_state != "unknown":
        evidence_ids.extend(nested_evidence_ids(row.get("venue_sell_evidence")))
    if attribution_state != "unverified":
        evidence_ids.extend(nested_evidence_ids(row.get("airdrop_attribution")))
    if closure_verified:
        evidence_ids.extend(nested_evidence_ids(row.get("pressure_closure")))
    if identity_verified:
        evidence_ids.extend(nested_evidence_ids(research.get("identity")))
    _ids, resolved, _unresolved = resolve_evidence(
        list(dict.fromkeys(evidence_ids)),
        research,
    )
    exact_supports = {
        f"airdrop_schedule_start:{event_id}",
        f"airdrop_schedule_end:{event_id}",
        f"airdrop_venue_sell:{event_id}",
        f"airdrop_venue_sell_reorg_pending:{event_id}",
        f"airdrop_attribution:{event_id}",
        f"airdrop_asset_identity:{event_id}",
        f"airdrop_claim_closed:{event_id}",
        f"airdrop_pressure_closure:{event_id}",
    }
    downstream_prefix = f"airdrop_downstream_closure:{event_id}:"
    trusted_evidence = sorted(
        (
            evidence
            for evidence in resolved
            if str(evidence.get("verification_status") or "").lower()
            == "verified"
            and evidence_kind_key(evidence) in AIRDROP_REVISION_EVIDENCE_KINDS
            and any(
                support in exact_supports
                or support.startswith(downstream_prefix)
                for support in evidence.get("supports", [])
                if isinstance(support, str)
            )
        ),
        key=lambda evidence: str(evidence.get("evidence_id") or ""),
    )
    schedule_fields = (
        "event_id",
        "event_type",
        "venue",
        "program",
        "time_utc8",
        "claim_start_utc",
        "claim_end_utc",
        "end_time_utc",
        "end_time_utc8",
        "time_precision",
        "authority",
        "verification_status",
        "distribution_identity_status",
        "channel_allocation_status",
        "channel_token_amount",
        "channel_share_of_total",
        "reference_bucket_token_amount",
        "reference_bucket_share_of_total",
        "allocation_overlap_policy",
        "claim_rules",
        "candidate_hard_deadline_utc",
        "candidate_deadline_basis",
        "pool_exhaustion_status",
        "registered_wallet_and_social_accounts_lower_bound",
        "registered_accounts_bound_type",
        "per_wallet_amount_status",
    )
    return research_fingerprint(
        {
            "schedule": {
                key: row.get(key)
                for key in schedule_fields
                if key in row
            },
            "normalized_start": start.isoformat() if start else "",
            "normalized_end": end.isoformat() if end else "",
            "state": {
                "start_verified": start_verified,
                "end_verified": end_verified,
                "venue_sell": venue_state,
                "airdrop_attribution": attribution_state,
                "closure_verified": closure_verified,
                "asset_identity_verified": identity_verified,
                "reminder": reminder_state,
                "pressure": pressure_state,
                "clearance": clearance_state,
            },
            "trusted_evidence": trusted_evidence,
        }
    )


def channel_allocation_verified(row: dict[str, Any]) -> bool:
    if str(row.get("channel_allocation_status") or "") != "verified":
        return False
    return bool(
        str(row.get("channel_token_amount") or "").strip()
        or str(row.get("channel_share_of_total") or "").strip()
    )


def asset_identity_verified(
    row: dict[str, Any],
    research: dict[str, Any],
) -> bool:
    identity = research.get("identity")
    if not isinstance(identity, dict):
        return False
    _ids, resolved, unresolved = resolve_evidence(
        identity.get("evidence_ids"),
        research,
    )
    event_id = str(row.get("event_id") or "").strip()
    return (
        identity.get("verification_status") == "verified"
        and not unresolved
        and verified_support(
            resolved,
            f"airdrop_asset_identity:{event_id}",
            OFFICIAL_EVIDENCE_KINDS,
        )
    )


def valid_coverage(coverage: Any, current: datetime) -> bool:
    if not isinstance(coverage, dict):
        return False
    from_block = coverage.get("from_block")
    to_block = coverage.get("to_block")
    block_hash = str(coverage.get("to_block_hash") or "").lower()
    window_start = parse_iso_utc(coverage.get("window_start_utc"))
    window_end = parse_iso_utc(coverage.get("window_end_utc"))
    return (
        coverage.get("status") == "complete"
        and coverage.get("finalized") is True
        and isinstance(from_block, int)
        and not isinstance(from_block, bool)
        and isinstance(to_block, int)
        and not isinstance(to_block, bool)
        and 0 <= from_block <= to_block
        and len(block_hash) == 66
        and block_hash.startswith("0x")
        and all(value in "0123456789abcdef" for value in block_hash[2:])
        and bool(str(coverage.get("cursor") or "").strip())
        and window_start is not None
        and window_end is not None
        and window_start <= window_end <= current
    )


def downstream_coverage_verified(
    value: Any,
    research: dict[str, Any],
    current: datetime,
    claim_end: datetime,
    event_id: str,
) -> bool:
    if not isinstance(value, dict):
        return False
    window_start = parse_iso_utc(value.get("window_start_utc"))
    window_end = parse_iso_utc(value.get("window_end_utc"))
    venues = value.get("venues")
    providers = value.get("providers")
    bindings = value.get("coverage_bindings")
    if not (
        value.get("status") == "complete"
        and value.get("finalized") is True
        and value.get("issue_codes") == []
        and window_start is not None
        and window_end is not None
        and claim_end <= window_start < window_end <= current
        and isinstance(venues, list)
        and bool(venues)
        and all(isinstance(name, str) and name for name in venues)
        and isinstance(providers, list)
        and bool(providers)
        and all(isinstance(name, str) and name for name in providers)
        and isinstance(bindings, list)
        and bool(bindings)
    ):
        return False
    venue_names = {str(name).strip().upper() for name in venues}
    provider_names = {str(name).strip() for name in providers}
    if venue_names != set(DOWNSTREAM_VENUE_EVIDENCE_KINDS):
        return False
    bound_venues: set[str] = set()
    bound_providers: set[str] = set()
    used_evidence_ids: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        venue = str(binding.get("venue") or "").strip().upper()
        provider = str(binding.get("provider") or "").strip()
        if venue not in venue_names or provider not in provider_names:
            return False
        evidence_ids, resolved, unresolved = resolve_evidence(
            binding.get("evidence_ids"),
            research,
        )
        if (
            not evidence_ids
            or unresolved
            or not used_evidence_ids.isdisjoint(evidence_ids)
            or not verified_support(
                resolved,
                (
                    f"airdrop_downstream_closure:{event_id}:"
                    f"{venue.lower()}:{provider}"
                ),
                DOWNSTREAM_VENUE_EVIDENCE_KINDS[venue],
            )
        ):
            return False
        used_evidence_ids.update(evidence_ids)
        bound_venues.add(venue)
        bound_providers.add(provider)
    return bound_venues == venue_names and bound_providers == provider_names


def pressure_closure_verified(
    row: dict[str, Any],
    research: dict[str, Any],
    current: datetime,
    start: datetime | None,
    end: datetime | None,
    end_verified: bool,
) -> bool:
    closure = row.get("pressure_closure")
    if (
        not isinstance(closure, dict)
        or start is None
        or end is None
        or not end_verified
        or not start < end <= current
        or row.get("distribution_identity_status") != "verified"
        or not channel_allocation_verified(row)
        or not asset_identity_verified(row, research)
        or airdrop_attribution_state(row, research) != "verified"
    ):
        return False
    evidence_ids, resolved, unresolved = resolve_evidence(
        closure.get("evidence_ids"),
        research,
    )
    coverage = closure.get("coverage")
    coverage_start = (
        parse_iso_utc(coverage.get("window_start_utc"))
        if isinstance(coverage, dict)
        else None
    )
    coverage_end = (
        parse_iso_utc(coverage.get("window_end_utc"))
        if isinstance(coverage, dict)
        else None
    )
    event_id = str(row.get("event_id") or "").strip()
    return (
        closure.get("status") == "cleared"
        and closure.get("verification_status") == "verified"
        and all(
            closure.get(key) is True
            for key in AIRDROP_CLOSURE_REQUIRED_FLAGS
        )
        and closure.get("issue_codes") == []
        and bool(evidence_ids)
        and not unresolved
        and valid_coverage(coverage, current)
        and coverage_start is not None
        and coverage_end is not None
        and coverage_start <= start < end <= coverage_end
        and downstream_coverage_verified(
            closure.get("downstream_coverage"),
            research,
            current,
            end,
            event_id,
        )
        and verified_support(
            resolved,
            f"airdrop_claim_closed:{event_id}",
            OFFICIAL_EVIDENCE_KINDS,
        )
        and verified_support(
            resolved,
            f"airdrop_pressure_closure:{event_id}",
            ONCHAIN_CLOSURE_EVIDENCE_KINDS,
        )
    )


def venue_sell_state(
    row: dict[str, Any],
    research: dict[str, Any],
) -> tuple[str, bool]:
    evidence = row.get("venue_sell_evidence")
    if not isinstance(evidence, dict):
        return "unknown", False
    status = str(evidence.get("status") or "unknown")
    _ids, resolved, unresolved = resolve_evidence(
        evidence.get("evidence_ids"),
        research,
    )
    support = f"airdrop_venue_sell:{str(row.get('event_id') or '').strip()}"
    verified = not unresolved and verified_support(
        resolved,
        support,
        ONCHAIN_RECEIPT_EVIDENCE_KINDS,
    )
    reorg_supported = not unresolved and verified_reorg_support(
        resolved,
        str(row.get("event_id") or "").strip(),
    )
    candidate_supported = not unresolved and verified_support(
        resolved,
        support,
        VENUE_CANDIDATE_EVIDENCE_KINDS,
    )
    if status == "reorg_pending" and reorg_supported:
        return "reorg_pending", False
    if status == "receipt_confirmed" and verified:
        if asset_identity_verified(row, research):
            return "receipt_confirmed", True
        return "candidate_asset_receipt_confirmed", True
    if status in {"candidate", "receipt_confirmed"} and candidate_supported:
        return "candidate", False
    return "unknown", False


def airdrop_attribution_state(
    row: dict[str, Any],
    research: dict[str, Any],
) -> str:
    attribution = row.get("airdrop_attribution")
    if not isinstance(attribution, dict):
        return "unverified"
    status = str(attribution.get("status") or "unverified")
    _ids, resolved, unresolved = resolve_evidence(
        attribution.get("evidence_ids"),
        research,
    )
    support = f"airdrop_attribution:{str(row.get('event_id') or '').strip()}"
    if (
        status == "verified"
        and not unresolved
        and verified_support(resolved, support, OFFICIAL_EVIDENCE_KINDS)
        and verified_support(
            resolved,
            support,
            ONCHAIN_ATTRIBUTION_EVIDENCE_KINDS,
        )
    ):
        return "verified"
    candidate_supported = not unresolved and (
        verified_support(resolved, support, OFFICIAL_EVIDENCE_KINDS)
        or verified_support(
            resolved,
            support,
            ONCHAIN_ATTRIBUTION_EVIDENCE_KINDS,
        )
    )
    if status in {"candidate", "verified"} and candidate_supported:
        return "candidate"
    return "unverified"


def airdrop_issue_codes(
    row: dict[str, Any],
    *,
    start: datetime | None,
    end: datetime | None,
    raw_end_present: bool,
    start_verified: bool,
    end_verified: bool,
    authority_trusted: bool,
    evidence_unresolved: list[str],
    event_id_stable: bool,
    duplicate_event_id: bool,
    venue_state: str,
    venue_verified: bool,
    attribution_state: str,
    closure_verified: bool,
) -> list[str]:
    if closure_verified:
        return []
    issues: list[str] = []
    if not event_id_stable:
        issues.append("airdrop_event_id_missing")
    if duplicate_event_id:
        issues.append("airdrop_event_id_duplicate")
    if start is None:
        issues.append("airdrop_schedule_missing")
    elif not start_verified:
        issues.append("airdrop_schedule_unverified")
    if not authority_trusted:
        issues.append("airdrop_authority_untrusted")
    if evidence_unresolved:
        issues.append("airdrop_evidence_unresolved")
    if raw_end_present and end is None:
        issues.append("airdrop_claim_end_invalid")
    elif end is not None and start is not None and end <= start:
        issues.append("airdrop_claim_window_invalid")
    elif end is not None and not end_verified:
        issues.append("airdrop_claim_end_unverified")
    elif end is None:
        issues.append("airdrop_claim_end_unknown")
    if row.get("pool_exhaustion_status") == "unknown":
        issues.append("airdrop_pool_exhaustion_unknown")
    if not channel_allocation_verified(row):
        issues.append("airdrop_allocation_unknown")
    identity_status = str(row.get("distribution_identity_status") or "")
    if not identity_status or identity_status == "missing":
        issues.append("airdrop_distribution_identity_missing")
    elif identity_status != "verified":
        issues.append("airdrop_distribution_identity_unverified")
    if venue_state == "candidate" or (
        venue_state == "receipt_confirmed" and not venue_verified
    ):
        issues.append("airdrop_venue_sell_evidence_unverified")
    venue_evidence = row.get("venue_sell_evidence")
    if (
        isinstance(venue_evidence, dict)
        and venue_evidence.get("status") not in (None, "", "unknown")
        and venue_state == "unknown"
    ):
        issues.append("airdrop_venue_sell_evidence_missing")
    if venue_state == "candidate_asset_receipt_confirmed":
        issues.append("airdrop_asset_identity_unverified")
    if venue_state in {
        "candidate",
        "candidate_asset_receipt_confirmed",
        "receipt_confirmed",
    } and (
        attribution_state != "verified"
    ):
        issues.append("airdrop_sell_attribution_unverified")
    attribution = row.get("airdrop_attribution")
    if (
        isinstance(attribution, dict)
        and attribution.get("status") in {"candidate", "verified"}
        and attribution_state == "unverified"
    ):
        issues.append("airdrop_attribution_evidence_unresolved")
    issues.append("airdrop_pressure_closure_unproven")
    return list(dict.fromkeys(issues))


def airdrop_action(
    reminder_state: str,
    venue_state: str,
    attribution_state: str,
) -> str:
    if venue_state == "candidate_asset_receipt_confirmed":
        return "候选资产卖出已由回执证实；官方代币映射与空投来源未证实，保持 Observe"
    if venue_state == "receipt_confirmed" and attribution_state != "verified":
        return "场所卖出已由回执证实；空投来源未证实，保持 Observe"
    if venue_state == "receipt_confirmed" and attribution_state == "verified":
        return "空投卖出路径已闭合；继续跟踪残余库存与承接"
    return {
        "time_unverified": "空投时间未核验；仅作发现线索，不生成交易动作",
        "not_yet": "空投领取尚未开始；继续核验分发身份、可交易场所和承接",
        "in_window": "空投领取开始时点已到；结束与下游卖压未闭合，保持 Observe",
        "ended_pressure_unresolved": "领取日历已结束；残余库存与下游卖压仍待闭环",
        "passed": "领取与残余卖压闭环已由完整证据核验",
    }.get(reminder_state, "保持 Observe")


def airdrop_allocation_text(row: dict[str, Any], symbol: str) -> str:
    channel_amount = str(row.get("channel_token_amount") or "").strip()
    channel_share = str(row.get("channel_share_of_total") or "").strip().rstrip("%")
    reference_amount = str(
        row.get("reference_bucket_token_amount") or ""
    ).strip()
    reference_share = str(
        row.get("reference_bucket_share_of_total") or ""
    ).strip().rstrip("%")

    def summary(amount: str, share: str) -> str:
        return "/".join(
            value
            for value in (
                f"{amount} {symbol}" if amount else "",
                f"{share}%" if share else "",
            )
            if value
        )

    channel = summary(channel_amount, channel_share)
    reference = summary(reference_amount, reference_share)
    if not channel_allocation_verified(row):
        return (
            "渠道份额未知"
            + (f"；参考总桶 {reference}" if reference else "")
            + "；禁止与渠道传言相加"
        )
    return channel


def airdrop_pressure_event(
    item: dict[str, Any],
    row: dict[str, Any],
    current: datetime,
    research: dict[str, Any],
    *,
    duplicate_event_id: bool = False,
) -> dict[str, Any]:
    start = schedule_start(row)
    raw_end_present = any(
        str(row.get(key) or "").strip()
        for key in ("claim_end_utc", "end_time_utc", "end_time_utc8")
    )
    end = schedule_end(row)
    configured_event_id = str(row.get("event_id") or "").strip()
    event_id_stable = bool(configured_event_id)
    if event_id_stable:
        event_id = configured_event_id
    else:
        basis = "|".join(
            [
                str(item.get("symbol") or "UNKNOWN").upper(),
                str(row.get("event_type") or "airdrop_claim"),
                str(row.get("venue") or "unknown"),
                start.isoformat() if start else "unknown",
            ]
        )
        event_id = "derived-" + hashlib.sha256(
            basis.encode("utf-8")
        ).hexdigest()[:16]
    evidence_ids, resolved, unresolved = resolve_evidence(
        row.get("evidence_ids"),
        research,
    )
    authority_trusted = str(row.get("authority") or "") in (
        OFFICIAL_AIRDROP_AUTHORITIES
    )
    start_verified = (
        start is not None
        and event_id_stable
        and not duplicate_event_id
        and authority_trusted
        and str(row.get("time_precision") or "").lower() == "exact"
        and str(row.get("verification_status") or "").lower() == "verified"
        and bool(evidence_ids)
        and not unresolved
        and verified_support(
            resolved,
            f"airdrop_schedule_start:{event_id}",
            OFFICIAL_EVIDENCE_KINDS,
        )
    )
    end_valid = end is not None and start is not None and end > start
    end_verified = (
        end_valid
        and not unresolved
        and verified_support(
            resolved,
            f"airdrop_schedule_end:{event_id}",
            OFFICIAL_EVIDENCE_KINDS,
        )
    )
    schedule_trusted = start_verified and (
        not raw_end_present or end_verified
    )
    closure_verified = pressure_closure_verified(
        row,
        research,
        current,
        start,
        end,
        end_verified,
    )
    if not start_verified:
        calendar_state = "unverified"
        reminder_state = "time_unverified"
    elif raw_end_present and not end_verified:
        calendar_state = "claim_open_end_unverified"
        reminder_state = "in_window"
    elif current < start:
        calendar_state = "scheduled_not_started"
        reminder_state = "not_yet"
    elif end is None:
        calendar_state = "claim_open_end_unknown"
        reminder_state = "in_window"
    elif current < end:
        calendar_state = "claim_open"
        reminder_state = "in_window"
    else:
        calendar_state = "claim_ended"
        reminder_state = (
            "passed" if closure_verified else "ended_pressure_unresolved"
        )

    venue_state, venue_verified = venue_sell_state(row, research)
    attribution_state = airdrop_attribution_state(row, research)
    if closure_verified:
        pressure_state = "pressure_cleared"
        clearance_state = "verified"
    elif venue_state == "candidate_asset_receipt_confirmed":
        pressure_state = "candidate_asset_sell_receipt_origin_unverified"
        clearance_state = "blocked"
    elif venue_state == "receipt_confirmed" and attribution_state == "verified":
        pressure_state = "confirmed_airdrop_sell_pressure"
        clearance_state = "blocked"
    elif venue_state == "receipt_confirmed":
        pressure_state = "venue_sell_confirmed_airdrop_origin_unverified"
        clearance_state = "blocked"
    elif venue_state == "reorg_pending":
        pressure_state = "reorg_pending"
        clearance_state = "blocked"
    elif venue_state == "candidate":
        pressure_state = "sell_route_candidate"
        clearance_state = "blocked"
    elif calendar_state == "scheduled_not_started":
        pressure_state = "scheduled"
        clearance_state = "blocked"
    elif calendar_state == "claim_ended":
        pressure_state = "post_window_unresolved"
        clearance_state = "blocked"
    else:
        pressure_state = "blocked_missing_evidence"
        clearance_state = "blocked"

    issue_codes = airdrop_issue_codes(
        row,
        start=start,
        end=end,
        raw_end_present=raw_end_present,
        start_verified=start_verified,
        end_verified=end_verified,
        authority_trusted=authority_trusted,
        evidence_unresolved=unresolved,
        event_id_stable=event_id_stable,
        duplicate_event_id=duplicate_event_id,
        venue_state=venue_state,
        venue_verified=venue_verified,
        attribution_state=attribution_state,
        closure_verified=closure_verified,
    )
    contract = first_contract(item)
    schedule_revision = airdrop_semantic_revision(
        row,
        research,
        event_id,
        start=start,
        end=end,
        start_verified=start_verified,
        end_verified=end_verified,
        venue_state=venue_state,
        attribution_state=attribution_state,
        closure_verified=closure_verified,
        identity_verified=asset_identity_verified(row, research),
        reminder_state=reminder_state,
        pressure_state=pressure_state,
        clearance_state=clearance_state,
    )
    alert_key_value = "|".join(
        [
            "airdrop",
            str(item.get("symbol") or "UNKNOWN").upper(),
            contract.get("address", "").lower(),
            event_id,
            reminder_state,
            pressure_state,
            attribution_state,
            schedule_revision,
        ]
    )
    minutes_to_start = (
        int((start - current).total_seconds() // 60) if start else 0
    )
    return {
        "event_kind": "airdrop_pressure",
        "event_id": event_id,
        "event_id_source": "configured" if event_id_stable else "derived",
        "event_type": str(row.get("event_type") or "airdrop_claim"),
        "symbol": str(item.get("symbol") or "UNKNOWN"),
        "display_name": display_name(item),
        "priority": str(item.get("priority") or ""),
        "phase": {
            "time_unverified": "AIRDROP_TIME_UNVERIFIED",
            "not_yet": "AIRDROP_NOT_YET",
            "in_window": "AIRDROP_IN_WINDOW",
            "ended_pressure_unresolved": "AIRDROP_ENDED_UNRESOLVED",
            "passed": "AIRDROP_PASSED",
        }[reminder_state],
        "calendar_state": calendar_state,
        "venue_sell_state": venue_state,
        "airdrop_attribution_state": attribution_state,
        "clearance_state": clearance_state,
        "pressure_state": pressure_state,
        "reminder_state": reminder_state,
        "action": airdrop_action(
            reminder_state,
            venue_state,
            attribution_state,
        ),
        "time_utc8": (
            start.astimezone(UTC8).strftime("%Y-%m-%d %H:%M")
            if start
            else ""
        ),
        "claim_start_utc": start.isoformat() if start else "",
        "claim_end_utc": end.isoformat() if end else "",
        "minutes_to_start": minutes_to_start,
        "venue": str(row.get("venue") or row.get("program") or ""),
        "chain": contract.get("chain") or item.get("chain") or "",
        "contract": contract.get("address") or "",
        "allocation_summary": airdrop_allocation_text(
            row,
            str(item.get("symbol") or "TOKEN"),
        ),
        "issue_codes": issue_codes,
        "evidence_ids": evidence_ids,
        "evidence_resolution_status": (
            "resolved" if not unresolved and evidence_ids else "unresolved"
        ),
        "schedule_evidence_status": (
            "verified" if schedule_trusted else "unverified"
        ),
        "automatic_trading": False,
        "runtime_effect": "risk_advisory" if schedule_trusted else "none",
        "alert_policy": "notify" if schedule_trusted else "report_only",
        "research_status": research.get("research_status", "partial"),
        "research_fingerprint": str(
            research.get("research_fingerprint") or ""
        ),
        "prelaunch_research": copy.deepcopy(research),
        "alert_key": alert_key_value,
    }


def build_events(config: dict[str, Any], current: datetime) -> list[dict[str, Any]]:
    lookahead = timedelta(hours=float(os.environ.get("ALPHA_PRELAUNCH_LOOKAHEAD_HOURS", "48")))
    events: list[dict[str, Any]] = []
    for item in config.get("items", []):
        if item.get("active_monitoring") is False:
            continue
        priority = str(item.get("priority") or "")
        if not priority.startswith(("P0", "P1")):
            continue
        research = prepare_prelaunch_research(item)
        fingerprint = str(research.get("research_fingerprint") or "")
        known_times = item.get("known_times") or item.get("times") or []
        for known in known_times:
            start = parse_known_time(known)
            if not start:
                continue
            delta = start - current
            phase = phase_for_delta(delta)
            if phase == "expired" or delta > lookahead:
                continue
            contract = first_contract(item)
            events.append(
                {
                    "event_kind": "launch_window",
                    "symbol": str(item.get("symbol") or "UNKNOWN"),
                    "display_name": display_name(item),
                    "priority": priority,
                    "phase": phase,
                    "action": phase_action(phase),
                    "time_utc8": start.astimezone(UTC8).strftime("%Y-%m-%d %H:%M"),
                    "minutes_to_start": int(delta.total_seconds() // 60),
                    "chain": contract.get("chain") or item.get("chain") or "",
                    "contract": contract.get("address") or "",
                    "required_checks": item.get("required_checks", [])[:6],
                    "research_status": research.get(
                        "research_status",
                        "partial",
                    ),
                    "research_fingerprint": fingerprint,
                    "prelaunch_research": copy.deepcopy(research),
                    "alert_key": alert_key(
                        item,
                        start,
                        phase,
                        fingerprint,
                    ),
                }
            )
    return sorted(
        events,
        key=lambda row: (
            row["minutes_to_start"],
            row["symbol"],
        ),
    )


def build_airdrop_pressure_events(
    config: dict[str, Any],
    current: datetime,
) -> list[dict[str, Any]]:
    selected: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    event_id_counts: dict[str, int] = {}
    for item in config.get("items", []):
        if not isinstance(item, dict) or item.get("active_monitoring") is False:
            continue
        if not str(item.get("priority") or "").startswith(("P0", "P1")):
            continue
        research = prepare_prelaunch_research(item)
        for row in airdrop_schedule_rows(item):
            selected.append((item, row, research))
            event_id = str(row.get("event_id") or "").strip()
            if event_id:
                event_id_counts[event_id] = event_id_counts.get(event_id, 0) + 1
    events = [
        airdrop_pressure_event(
            item,
            row,
            current,
            research,
            duplicate_event_id=(
                event_id_counts.get(str(row.get("event_id") or "").strip(), 0)
                > 1
            ),
        )
        for item, row, research in selected
    ]
    return sorted(
        events,
        key=lambda event: (
            event.get("claim_start_utc") or "9999",
            event.get("symbol") or "",
            event.get("event_id") or "",
        ),
    )


def airdrop_identity_hash(rows: list[dict[str, str]]) -> str:
    canonical = sorted(
        (
            str(row.get("symbol") or "").upper(),
            str(row.get("contract") or "").lower(),
            str(row.get("event_id") or ""),
        )
        for row in rows
    )
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def expected_airdrop_identities(config: dict[str, Any]) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for item in config.get("items", []):
        if not isinstance(item, dict) or item.get("active_monitoring") is False:
            continue
        if not str(item.get("priority") or "").startswith(("P0", "P1")):
            continue
        contract = first_contract(item).get("address") or ""
        for row in airdrop_schedule_rows(item):
            identities.append(
                {
                    "symbol": str(item.get("symbol") or ""),
                    "contract": contract,
                    "event_id": str(row.get("event_id") or ""),
                }
            )
    return identities


def alert_key(
    item: dict[str, Any],
    start: datetime,
    phase: str,
    fingerprint: str = "",
) -> str:
    contract = first_contract(item).get("address") or ""
    return "|".join(
        [
            str(item.get("symbol") or "UNKNOWN").upper(),
            contract.lower(),
            start.isoformat(),
            phase,
            fingerprint,
        ]
    )


def verification_badge(row: Any) -> str:
    status = (
        str(row.get("verification_status") or "unverified").lower()
        if isinstance(row, dict)
        else "unverified"
    )
    return STATUS_BADGES.get(status, "[U]")


def text_value(value: Any, fallback: str = "-") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def research_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def preview_rows(
    rows: list[dict[str, Any]],
    formatter: Any,
    *,
    limit: int | None = 2,
) -> str:
    if not rows:
        return "待补"
    selected = rows if limit is None else rows[:limit]
    rendered = [formatter(row) for row in selected]
    if limit is not None and len(rows) > limit:
        rendered.append(f"+{len(rows) - limit}")
    return "；".join(rendered)


def timeline_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("timeline"))

    def render(row: dict[str, Any]) -> str:
        event = text_value(
            row.get("event") or row.get("label") or row.get("kind")
        )
        event_time = text_value(row.get("time_utc8"), "")
        if not event_time and row.get("time_utc"):
            try:
                event_time = (
                    datetime.fromisoformat(
                        str(row["time_utc"]).replace("Z", "+00:00")
                    )
                    .astimezone(UTC8)
                    .strftime("%Y-%m-%d %H:%M UTC+8")
                )
            except ValueError:
                event_time = text_value(row.get("time_utc"))
        event_time = event_time or text_value(row.get("time"))
        anchor_status = text_value(
            row.get("runtime_anchor_status"),
            "",
        )
        anchor_suffix = f" {anchor_status}" if anchor_status else ""
        return (
            f"{event}@{event_time} {verification_badge(row)}"
            f"{anchor_suffix}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def pool_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    pool = research.get("pool")
    pool = pool if isinstance(pool, dict) else {}
    context = research.get("market_context")
    context = context if isinstance(context, dict) else {}
    segments = research_rows(pool.get("segments"))
    if not segments:
        segments = research_rows(context.get("pool_zones"))
    details: list[str] = []
    pair = pool.get("pair")
    price = pool.get("initial_price_usdt")
    if pair or price:
        details.append(
            f"{text_value(pair)} 初价{text_value(price)} "
            f"{verification_badge(pool)}"
        )

    def render(row: dict[str, Any]) -> str:
        kind = text_value(
            row.get("kind")
            or row.get("label")
            or row.get("position_id")
        )
        low = row.get("min_price_usdt")
        high = row.get("max_price_usdt")
        if low is not None or high is not None:
            price_range = f"{text_value(low)}-{text_value(high)}"
        else:
            price_range = text_value(
                row.get("price_usdt") or row.get("price")
            )
        amount = row.get("token_amount")
        suffix = f" token={amount}" if amount not in (None, "") else ""
        return (
            f"{kind} {price_range}{suffix} "
            f"{verification_badge(row)}"
        )

    if segments:
        details.append(
            preview_rows(
                segments,
                render,
                limit=2 if compact else None,
            )
        )
    return "；".join(details) if details else "待补"


def supply_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    supply = research.get("supply")
    supply = supply if isinstance(supply, dict) else {}
    allocations = research_rows(supply.get("allocations"))
    if not allocations:
        allocations = research_rows(research.get("event_distributions"))
    cross_chain = research_rows(supply.get("cross_chain"))

    def render_allocation(row: dict[str, Any]) -> str:
        role = text_value(
            row.get("role")
            or row.get("name")
            or row.get("label")
        )
        share = text_value(
            row.get("percent")
            or row.get("share_of_total")
            or row.get("token_amount")
        )
        return f"{role} {share} {verification_badge(row)}"

    def render_cross_chain(row: dict[str, Any]) -> str:
        chain = text_value(row.get("chain"))
        inventory = text_value(
            row.get("inventory")
            or row.get("inventory_amount")
            or (
                f"{row.get('inventory_percent')}%"
                if row.get("inventory_percent") not in (None, "")
                else ""
            )
            or row.get("token_amount")
        )
        bridge = text_value(
            row.get("bridge_state") or row.get("state")
        )
        return (
            f"{chain} 库存{inventory}/桥{bridge} "
            f"{verification_badge(row)}"
        )

    return (
        "分发 "
        + preview_rows(
            allocations,
            render_allocation,
            limit=2 if compact else None,
        )
        + "；跨链 "
        + preview_rows(
            cross_chain,
            render_cross_chain,
            limit=2 if compact else None,
        )
    )


def venue_actor_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    venues = research.get("venues")
    venues = venues if isinstance(venues, dict) else {}
    actors = research.get("actors")
    actors = actors if isinstance(actors, dict) else {}
    cex_rows = research_rows(venues.get("cex"))
    mm_rows = research_rows(actors.get("market_makers"))

    def render_cex(row: dict[str, Any]) -> str:
        venue = text_value(row.get("venue"))
        market = text_value(row.get("market"))
        deposit = text_value(
            row.get("deposit_state") or row.get("state")
        )
        return (
            f"{venue}/{market} 充值{deposit} "
            f"{verification_badge(row)}"
        )

    def render_mm(row: dict[str, Any]) -> str:
        identity = short_addr(
            text_value(row.get("address") or row.get("name"))
        )
        role = text_value(row.get("role"))
        return f"{identity} {role} {verification_badge(row)}"

    return (
        "CEX "
        + preview_rows(
            cex_rows,
            render_cex,
            limit=2 if compact else None,
        )
        + "；MM "
        + preview_rows(
            mm_rows,
            render_mm,
            limit=2 if compact else None,
        )
    )


def sniper_curve_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("sniper_curve"))
    if not rows:
        context = research.get("market_context")
        context = context if isinstance(context, dict) else {}
        rows = research_rows(context.get("sniper_curve"))

    def render(row: dict[str, Any]) -> str:
        pressure = text_value(
            row.get("buy_pressure_usdt") or row.get("snipe_amount_usdt")
        )
        average = text_value(
            row.get("avg_price_usdt") or row.get("average_price_usdt")
        )
        end = text_value(
            row.get("end_price_usdt") or row.get("price_usdt")
        )
        tokens = text_value(
            row.get("token_out") or row.get("token_amount")
        )
        return (
            f"{pressure}U→均{average}/末{end}/得{tokens} "
            f"{verification_badge(row)}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def opening_forecast_text(research: dict[str, Any]) -> str:
    forecast = research.get("opening_forecast")
    if not isinstance(forecast, dict) or not forecast:
        return "待补"
    parts = []
    for label, key, suffix in (
        ("买压", "buy_quote_usdt", "U"),
        ("bribe", "bribe_quote_usdt", "U"),
        ("预计均价", "predicted_fill_avg_usdt", "U"),
    ):
        value = forecast.get(key)
        if value not in (None, ""):
            parts.append(f"{label}{value}{suffix}")
    return (
        " / ".join(parts) + f" {verification_badge(forecast)}"
        if parts
        else "待补"
    )


def opening_actual_text(research: dict[str, Any]) -> str:
    actual = research.get("opening_actual")
    if not isinstance(actual, dict) or not actual:
        return "待开盘回执核验"
    parts = []
    for label, key, suffix in (
        ("实际买入", "buy_quote_usdt", "U"),
        ("实际bribe", "bribe_quote_usdt", "U"),
        ("实际均价", "weighted_avg_price_usdt", "U"),
        ("已确认卖出", "confirmed_sell_quote_usdt", "U"),
    ):
        value = actual.get(key)
        if value not in (None, ""):
            parts.append(f"{label}{value}{suffix}")
    return (
        " / ".join(parts) + f" {verification_badge(actual)}"
        if parts
        else "待开盘回执核验"
    )


def valuation_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    valuation = research.get("valuation")
    valuation = valuation if isinstance(valuation, dict) else {}
    anchors = research_rows(valuation.get("anchors"))
    predictions = research_rows(valuation.get("prediction_markets"))

    def render_anchor(row: dict[str, Any]) -> str:
        kind = text_value(row.get("kind") or row.get("source"))
        price = row.get("price_usdt")
        fdv = row.get("fdv_usd")
        price_or_fdv = row.get("price_or_fdv")
        values = []
        if price not in (None, ""):
            values.append(f"价{text_value(price)}")
        if fdv not in (None, ""):
            values.append(f"FDV{text_value(fdv)}")
        if not values and price_or_fdv not in (None, ""):
            values.append(text_value(price_or_fdv))
        return (
            f"{kind} {'/'.join(values) if values else '-'} "
            f"{verification_badge(row)}"
        )

    def render_prediction(row: dict[str, Any]) -> str:
        source = text_value(row.get("source"))
        target = text_value(row.get("target_fdv_usd"))
        probability = text_value(row.get("probability"))
        return (
            f"{source} FDV>{target}@{probability} "
            f"{verification_badge(row)}"
        )

    rendered = []
    if anchors:
        rendered.append(
            preview_rows(
                anchors,
                render_anchor,
                limit=2 if compact else None,
            )
        )
    if predictions:
        rendered.append(
            preview_rows(
                predictions,
                render_prediction,
                limit=2 if compact else None,
            )
        )
    if rendered:
        return "；".join(rendered)

    context = research.get("market_context")
    context = context if isinstance(context, dict) else {}
    legacy_parts = [
        f"{key}={context[key]}"
        for key in (
            "premarket_reference_price_usdt",
            "public_sale_price_usdt",
            "implied_fdv_usd",
        )
        if context.get(key) not in (None, "")
    ]
    return (
        "；".join(legacy_parts) + (" [U]" if legacy_parts else "")
        if legacy_parts
        else "待补"
    )


def sell_pressure_text(
    research: dict[str, Any],
    *,
    compact: bool = True,
) -> str:
    rows = research_rows(research.get("sell_pressure_scenarios"))

    def render(row: dict[str, Any]) -> str:
        scenario = text_value(row.get("scenario") or row.get("name"))
        effect = text_value(
            row.get("expected_effect") or row.get("summary")
        )
        action = text_value(row.get("action"))
        return (
            f"{scenario}: {effect} / {action} "
            f"{verification_badge(row)}"
        )

    return preview_rows(rows, render, limit=2 if compact else None)


def evidence_text(research: dict[str, Any]) -> str:
    counts = {key: 0 for key in STATUS_BADGES}
    evidence = research_rows(research.get("evidence"))
    for row in evidence:
        status = str(
            row.get("verification_status") or "unverified"
        ).lower()
        counts[status if status in counts else "unverified"] += 1
    claim_conflicts = len(research.get("conflicts") or [])
    if has_conflicted_evidence(research):
        claim_conflicts = max(1, claim_conflicts)
    return (
        f"V{counts['verified']}/U{counts['unverified']}/"
        f"C{counts['conflicted']}/S{counts['stale']}/"
        f"ClaimConflict{claim_conflicts}"
    )


def markdown_value(value: Any, fallback: str = "-") -> str:
    return text_value(value, fallback).replace("\r", " ").replace("\n", " ")


def evidence_detail_lines(research: dict[str, Any]) -> list[str]:
    evidence = research_rows(research.get("evidence"))
    lines = ["### Evidence / Sources", ""]
    if not evidence:
        lines.append("- evidence: 待补")
        return lines
    for row in evidence:
        evidence_id = markdown_value(row.get("evidence_id"))
        kind = markdown_value(
            row.get("evidence_kind") or row.get("kind")
        )
        source_ref = markdown_value(
            row.get("source_ref")
            or row.get("source")
            or row.get("publisher")
        )
        source_url = markdown_value(
            row.get("url")
            or row.get("source_url")
            or row.get("link")
            or (
                row.get("source_ref")
                if str(row.get("source_ref") or "").startswith(
                    ("http://", "https://")
                )
                else ""
            ),
            "",
        )
        lines.extend(
            [
                (
                    f"- evidence_id: `{evidence_id}` · "
                    f"kind: {kind} · {verification_badge(row)}"
                ),
                f"  - source: {source_ref}",
                (
                    f"  - URL: <{source_url}>"
                    if source_url
                    else "  - URL: -"
                ),
            ]
        )
    return lines


def research_section_lines(
    event: dict[str, Any],
    *,
    compact: bool = True,
) -> list[str]:
    research = event.get("prelaunch_research")
    research = research if isinstance(research, dict) else {}
    missing = research.get("missing_fields")
    missing = missing if isinstance(missing, list) else []
    conflicts = research_rows(research.get("conflicts"))
    shown_conflicts = conflicts[:2] if compact else conflicts
    conflict_text = "；".join(
        (
            text_value(row.get("path"))
            + ": "
            + text_value(row.get("detail"))
        )
        for row in shown_conflicts
    )
    return [
        f"时间轴: {timeline_text(research, compact=compact)}",
        f"池子: {pool_text(research, compact=compact)}",
        f"筹码/跨链: {supply_text(research, compact=compact)}",
        f"CEX/MM: {venue_actor_text(research, compact=compact)}",
        f"狙击预测: {opening_forecast_text(research)}",
        f"开盘实绩: {opening_actual_text(research)}",
        f"狙击曲线: {sniper_curve_text(research, compact=compact)}",
        f"估值: {valuation_text(research, compact=compact)}",
        f"卖压情景: {sell_pressure_text(research, compact=compact)}",
        f"证据: {evidence_text(research)}",
        "缺口: " + ("、".join(str(value) for value in missing) if missing else "无"),
        "冲突: " + (conflict_text or "无"),
    ]


def render_report(payload: dict[str, Any]) -> str:
    launch_events = payload.get("events", [])
    airdrop_events = payload.get("airdrop_pressure_events", [])
    lines = [
        "# Alpha Prelaunch Watch",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- events: `{len(launch_events)}`",
        f"- airdrop_pressure_events: `{len(airdrop_events)}`",
        "",
    ]
    if not launch_events and not airdrop_events:
        lines.append("- No upcoming P0/P1 launch windows in configured lookahead.")
        return "\n".join(lines)
    if launch_events:
        lines.extend(
            [
                "| Phase | Time UTC+8 | Project | Action | Contract |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for event in launch_events:
            lines.append(
                f"| {event.get('phase')} | {event.get('time_utc8')} | {event.get('display_name')} | "
                f"{event.get('action')} | `{short_addr(event.get('contract', ''))}` |"
            )
    else:
        lines.append("- No upcoming P0/P1 launch windows in configured lookahead.")
    for event in launch_events:
        research = event.get("prelaunch_research")
        research = research if isinstance(research, dict) else {}
        decision = research.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        lines.extend(
            [
                "",
                f"## {event.get('display_name')} · {event.get('phase')}",
                "",
                f"- research_status: `{event.get('research_status')}`",
                f"- research_fingerprint: `{event.get('research_fingerprint')}`",
                *[
                    f"- {line}"
                    for line in research_section_lines(
                        event,
                        compact=False,
                    )
                ],
                "",
                *evidence_detail_lines(research),
                (
                    "- 决策: "
                    + text_value(
                        decision.get("action") or event.get("action")
                    )
                    + "｜"
                    + text_value(
                        decision.get("summary") or event.get("action")
                    )
                ),
            ]
        )
    if airdrop_events:
        lines.extend(["", "# Airdrop Pressure", ""])
    for event in airdrop_events:
        lines.extend(
            [
                f"## {event.get('display_name')} · {event.get('phase')}",
                "",
                f"- event_id: `{event.get('event_id')}`",
                f"- venue: `{event.get('venue')}`",
                f"- calendar_state: `{event.get('calendar_state')}`",
                f"- venue_sell_state: `{event.get('venue_sell_state')}`",
                "- airdrop_attribution_state: "
                f"`{event.get('airdrop_attribution_state')}`",
                f"- clearance_state: `{event.get('clearance_state')}`",
                f"- pressure_state: `{event.get('pressure_state')}`",
                f"- reminder_state: `{event.get('reminder_state')}`",
                f"- claim_start_utc: `{event.get('claim_start_utc')}`",
                f"- claim_end_utc: `{event.get('claim_end_utc')}`",
                f"- allocation: {event.get('allocation_summary')}",
                "- issue_codes: "
                + ("、".join(event.get("issue_codes", [])) or "无"),
                "- evidence_ids: "
                + ("、".join(event.get("evidence_ids", [])) or "无"),
                f"- 动作: {event.get('action')}",
                "",
            ]
        )
    return "\n".join(lines)


def telegram_event_text(event: dict[str, Any]) -> str:
    if event.get("event_kind") == "airdrop_pressure":
        issue_text = "、".join(event.get("issue_codes", [])) or "无"
        return "\n".join(
            [
                "Alpha 空投抛压时钟",
                "",
                f"{event.get('display_name')}｜{event.get('venue')}",
                f"日历: {event.get('reminder_state')}",
                f"场所卖出: {event.get('venue_sell_state')}",
                f"空投归因: {event.get('airdrop_attribution_state')}",
                f"解除: {event.get('clearance_state')}",
                f"开始: {event.get('time_utc8') or '-'} UTC+8",
                f"结束: {event.get('claim_end_utc') or '未知'}",
                f"分配: {event.get('allocation_summary')}",
                f"证据缺口: {issue_text}",
                f"动作: {event.get('action')}",
            ]
        ).strip()
    lines = ["Alpha 盘前投研", ""]
    research = event.get("prelaunch_research")
    research = research if isinstance(research, dict) else {}
    decision = research.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    lines.extend(
        [
            (
                f"{event.get('display_name')} [{event.get('phase')}]"
                f"｜{event.get('research_status')}"
            ),
            f"时间: {event.get('time_utc8')} UTC+8",
            *research_section_lines(event),
            (
                "动作: "
                + text_value(
                    decision.get("action") or event.get("action")
                )
                + "｜"
                + text_value(
                    decision.get("summary") or event.get("action")
                )
            ),
        ]
    )
    return "\n".join(lines).strip()


def split_telegram_text(
    text: str,
    limit: int = TELEGRAM_LIMIT,
) -> list[str]:
    if limit <= 0:
        raise ValueError("Telegram message limit must be positive")
    remaining = text
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary <= 0:
            boundary = limit
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
        if remaining.startswith("\n"):
            remaining = remaining[1:]
    return chunks


def telegram_messages(new_events: list[dict[str, Any]]) -> list[str]:
    return [
        chunk
        for event in new_events
        if event.get("alert_policy", "notify") == "notify"
        for chunk in split_telegram_text(telegram_event_text(event))
    ]


def telegram_text(new_events: list[dict[str, Any]]) -> str:
    messages = telegram_messages(new_events)
    return messages[0] if messages else "Alpha 盘前投研"


def send_telegram(text: str) -> dict[str, Any]:
    if len(text) > TELEGRAM_LIMIT:
        return {
            "ok": False,
            "reason": "telegram_message_exceeds_limit",
        }
    if os.environ.get("ALPHA_PRELAUNCH_TELEGRAM", "1") == "0" or os.environ.get("DISABLE_TELEGRAM") == "1":
        return {"ok": True, "disabled": True}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "reason": "missing telegram token/chat"}
    payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"telegram_request_failed:{type(exc).__name__}",
        }


def write_seen_keys(seen_order: list[str]) -> None:
    write_json(
        SEEN_PATH,
        {
            "updated_at": now_iso(),
            "keys": seen_order[-500:],
        },
    )


def write_airdrop_seen_keys(seen_order: list[str]) -> None:
    write_json(
        AIRDROP_SEEN_PATH,
        {
            "updated_at": now_iso(),
            "keys": seen_order[-500:],
        },
    )


def push_new_events(
    new_events: list[dict[str, Any]],
    seen_order: list[str],
    *,
    seen_namespace: str = "launch",
) -> dict[str, Any]:
    new_events = [
        event
        for event in new_events
        if event.get("alert_policy", "notify") == "notify"
    ]
    expected_namespaces = {
        "airdrop"
        if event.get("event_kind") == "airdrop_pressure"
        else "launch"
        for event in new_events
    }
    if len(expected_namespaces) > 1 or (
        expected_namespaces and seen_namespace not in expected_namespaces
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "seen_namespace_mismatch",
            "event_count": len(new_events),
            "delivered_event_count": 0,
            "message_count": 0,
            "batches": [],
        }
    result: dict[str, Any] = {
        "ok": True,
        "skipped": not new_events,
        "event_count": len(new_events),
        "delivered_event_count": 0,
        "message_count": 0,
        "batches": [],
    }
    seen_keys = set(seen_order)
    for event in new_events:
        alert_key = str(event.get("alert_key") or "")
        messages = split_telegram_text(telegram_event_text(event))
        event_delivered = True
        event_batches = []
        for index, message in enumerate(messages, start=1):
            batch_result = send_telegram(message)
            result["message_count"] += 1
            event_batches.append(
                {
                    "index": index,
                    "message_count": len(messages),
                    "ok": bool(batch_result.get("ok")),
                    "disabled": bool(batch_result.get("disabled")),
                    "reason": batch_result.get("reason", ""),
                }
            )
            if (
                not batch_result.get("ok")
                or batch_result.get("disabled")
            ):
                event_delivered = False
                result["ok"] = bool(batch_result.get("ok"))
                result["reason"] = batch_result.get("reason", "")
                if batch_result.get("disabled"):
                    result["disabled"] = True
                break
        result["batches"].append(
            {
                "alert_key": alert_key,
                "delivered": event_delivered,
                "messages": event_batches,
            }
        )
        if not event_delivered:
            break
        if alert_key and alert_key not in seen_keys:
            seen_keys.add(alert_key)
            seen_order.append(alert_key)
            if seen_namespace == "airdrop":
                write_airdrop_seen_keys(seen_order)
            else:
                write_seen_keys(seen_order)
        result["delivered_event_count"] += 1
    return result


def main() -> int:
    current = now_utc()
    config = read_json(CONFIG_PATH, {"items": []})
    airdrop_config = read_json(AIRDROP_CONFIG_PATH, {"items": []})
    events = build_events(config, current)
    airdrop_events = build_airdrop_pressure_events(airdrop_config, current)
    seen = read_json(SEEN_PATH, {"keys": []})
    seen_order = list(
        dict.fromkeys(
            str(key)
            for key in seen.get("keys", [])
            if str(key)
        )
    )
    seen_keys = set(seen_order)
    new_events = [
        event
        for event in events
        if event["alert_key"] not in seen_keys
    ]

    airdrop_seen = read_json(AIRDROP_SEEN_PATH, {"keys": []})
    airdrop_seen_order = list(
        dict.fromkeys(
            str(key)
            for key in airdrop_seen.get("keys", [])
            if str(key)
        )
    )
    airdrop_seen_keys = set(airdrop_seen_order)
    new_airdrop_events = [
        event
        for event in airdrop_events
        if event.get("alert_policy") == "notify"
        and event["alert_key"] not in airdrop_seen_keys
    ]

    launch_push_result = push_new_events(new_events, seen_order)
    if launch_push_result.get("ok"):
        airdrop_push_result = push_new_events(
            new_airdrop_events,
            airdrop_seen_order,
            seen_namespace="airdrop",
        )
    else:
        airdrop_push_result = {
            "ok": False,
            "skipped": True,
            "reason": "launch_delivery_failed",
            "event_count": len(new_airdrop_events),
        }
    push_result = {
        "ok": bool(
            launch_push_result.get("ok")
            and airdrop_push_result.get("ok")
        ),
        "launch": launch_push_result,
        "airdrop": airdrop_push_result,
    }

    payload = {
        "schema": "alpha_prelaunch_watch.v2",
        "generated_at": now_iso(),
        "lookahead_hours": os.environ.get("ALPHA_PRELAUNCH_LOOKAHEAD_HOURS", "48"),
        "events": events,
        "airdrop_pressure_events": airdrop_events,
        "airdrop_pressure_required_count": sum(
            len(airdrop_schedule_rows(item))
            for item in airdrop_config.get("items", [])
            if isinstance(item, dict)
            and item.get("active_monitoring") is not False
            and str(item.get("priority") or "").startswith(("P0", "P1"))
        ),
        "airdrop_pressure_event_count": sum(
            event.get("event_kind") == "airdrop_pressure"
            for event in airdrop_events
        ),
        "airdrop_pressure_expected_identity_hash": airdrop_identity_hash(
            expected_airdrop_identities(airdrop_config)
        ),
        "airdrop_pressure_processed_identity_hash": airdrop_identity_hash(
            airdrop_events
        ),
        "new_event_count": len(new_events) + len(new_airdrop_events),
        "launch_new_event_count": len(new_events),
        "airdrop_new_event_count": len(new_airdrop_events),
        "push_result": push_result,
    }
    write_json(LATEST_PATH, payload)
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
    print(REPORT_PATH)
    print(
        json.dumps(
            {
                "events": len(events),
                "airdrop_pressure_events": len(airdrop_events),
                "new_events": len(new_events) + len(new_airdrop_events),
                "push": push_result,
            },
            ensure_ascii=False,
        )
    )
    return 0 if push_result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
