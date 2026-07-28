#!/usr/bin/env python3
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
STATIC_WATCHLIST_PATH = ROOT / "config" / "current_alpha_watchlist.json"
OUT_DIR = ROOT / "output" / "binance_alpha_catalog_watch"
CURRENT_WATCHLIST_PATH = OUT_DIR / "current_watchlist.json"
LATEST_PATH = OUT_DIR / "latest.json"
STATUS_PATH = OUT_DIR / "status.json"
TOKEN_LIST_URL = (
    "https://www.binance.com/"
    "bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
)
UTC8 = timezone(timedelta(hours=8))
CHAIN_BY_ID = {"56": "bsc", "8453": "base"}
CHAIN_BY_NAME = {"BSC": "bsc", "BNB SMART CHAIN": "bsc", "BASE": "base"}
USDT_BY_CHAIN = {
    "bsc": "0x55d398326f99059ff775485246999027b3197955",
}
SUPPORTED_CHAINS = {"bsc"}
DEFAULT_MAX_SELECTED = 8
DEFAULT_RETENTION_DAYS = 30
DEFAULT_SCHEMA_MIN_RATIO = 0.5


def now_utc() -> datetime:
    override = os.environ.get("BINANCE_ALPHA_CATALOG_NOW_UTC", "").strip()
    if override:
        return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso(current: datetime | None = None) -> str:
    return (current or now_utc()).astimezone(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def validate_static_watchlist(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("static Alpha watchlist must be an object with an items array")
    if any(not isinstance(item, dict) for item in payload["items"]):
        raise ValueError("static Alpha watchlist items must be objects")
    return payload


def read_static_watchlist(path: Path = STATIC_WATCHLIST_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("static Alpha watchlist is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("static Alpha watchlist is unreadable or invalid JSON") from exc
    return validate_static_watchlist(payload)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def fetch_catalog(timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        TOKEN_LIST_URL,
        headers={"User-Agent": "sniper-binance-alpha-catalog-watch/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Binance Alpha token list returned a non-object")
    return value


def normalize_address(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 42 or not text.startswith("0x"):
        return ""
    if any(character not in "0123456789abcdef" for character in text[2:]):
        return ""
    return text


def normalize_chain(row: dict[str, Any]) -> str:
    chain_id = str(row.get("chainId") or "").strip()
    if chain_id in CHAIN_BY_ID:
        return CHAIN_BY_ID[chain_id]
    chain_name = str(row.get("chainName") or "").strip().upper()
    return CHAIN_BY_NAME.get(chain_name, "")


def listing_datetime(row: dict[str, Any]) -> datetime | None:
    try:
        listing_ms = int(row.get("listingTime"))
    except (TypeError, ValueError):
        return None
    if listing_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(listing_ms / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except (TypeError, ValueError):
        return None


def valid_catalog_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("success") is not True or str(response.get("code") or "") != "000000":
        raise ValueError(
            "Binance Alpha token list rejected: "
            f"code={response.get('code')!r}, success={response.get('success')!r}"
        )
    rows = response.get("data")
    if not isinstance(rows, list):
        raise ValueError("Binance Alpha token list data is not an array")
    normalized = [row for row in rows if isinstance(row, dict)]
    if not normalized:
        raise ValueError("Binance Alpha token list data is empty")
    return normalized


def schema_valid_supported_count(rows: list[dict[str, Any]]) -> int:
    contracts: set[tuple[str, str]] = set()
    alpha_ids: set[str] = set()
    count = 0
    for row in rows:
        chain = normalize_chain(row)
        symbol = str(row.get("symbol") or "").strip()
        alpha_id = str(row.get("alphaId") or "").strip()
        contract = normalize_address(row.get("contractAddress"))
        if (
            chain in SUPPORTED_CHAINS
            and symbol
            and alpha_id
            and contract
            and listing_datetime(row) is not None
        ):
            identity = (chain, contract)
            if identity in contracts or alpha_id in alpha_ids:
                continue
            contracts.add(identity)
            alpha_ids.add(alpha_id)
            count += 1
    return count


def validate_schema_continuity(
    rows: list[dict[str, Any]],
    previous_summary: dict[str, Any],
    minimum_ratio: float,
) -> int:
    if not 0 < minimum_ratio <= 1:
        raise ValueError("catalog schema minimum ratio must be within (0, 1]")
    current_count = schema_valid_supported_count(rows)
    if current_count < 1:
        raise ValueError("Binance Alpha catalog has no schema-valid supported-chain rows")
    try:
        previous_count = int(previous_summary.get("supported_schema_count") or 0)
    except (TypeError, ValueError):
        previous_count = 0
    if previous_count > 0 and current_count / previous_count < minimum_ratio:
        raise ValueError(
            "Binance Alpha supported-chain schema count dropped abruptly: "
            f"previous={previous_count}, current={current_count}, "
            f"minimum_ratio={minimum_ratio}"
        )
    return current_count


def catalog_watchlist_item(
    row: dict[str, Any],
    *,
    listing: datetime,
    chain: str,
    contract: str,
    opening_max_age_hours: int,
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").strip().upper()
    name = str(row.get("name") or symbol).strip() or symbol
    alpha_id = str(row.get("alphaId") or "").strip()
    start_utc8 = listing.astimezone(UTC8).strftime("%Y-%m-%d %H:%M")
    pool_row: dict[str, Any] = {
        "chain": chain,
        "pool_id": "",
        "start_time_utc8": start_utc8,
        "source": "binance_alpha_public_catalog",
        "opening_anchor_status": "catalog_listing_candidate",
    }
    quote_address = USDT_BY_CHAIN.get(chain)
    if quote_address:
        pool_row["quote_address"] = quote_address
    return {
        "symbol": symbol,
        "name": name,
        "priority": "P1_MONITOR",
        "chain": chain,
        "active_monitoring": True,
        "contracts": [
            {
                "chain": chain,
                "address": contract,
                "confidence": "binance_alpha_public_catalog",
            }
        ],
        "catalysts": ["Binance Alpha official catalog"],
        "known_times": [
            {
                "time": start_utc8,
                "reason": "binance_alpha_listing_time",
            }
        ],
        "pool_ids": [pool_row],
        "known_blocks": [],
        "known_txs": [],
        "watch_addresses": [],
        "opening_max_age_hours": opening_max_age_hours,
        "opening_liquidity_max_age_seconds": opening_max_age_hours * 3600,
        "opening_max_logs": 5000,
        "opening_trace_buyers": 8,
        "opening_max_txs": 24,
        "opening_classify_out_txs": 8,
        "opening_next_hop_recipients": 8,
        "opening_next_hop_classify_txs": 6,
        "project_operator_probe": "owner",
        "project_lookback_blocks": 250000,
        "required_checks": [
            "opening_block",
            "block_transaction_order",
            "internal_transactions",
            "holder_distribution",
            "project_operator_attribution",
            "sniper_cohort_exit",
        ],
        "facts": {
            "source": "binance_alpha_public_catalog",
            "alpha_id": alpha_id,
            "listing_time_utc": listing.isoformat(),
            "listing_time_utc8": start_utc8,
            "opening_anchor_status": "catalog_listing_candidate",
            "contract_decimals": row.get("decimals"),
            "bn_exclusive_state": bool(row.get("bnExclusiveState", False)),
        },
    }


def unique_list(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def merge_contract_rows(
    existing_rows: list[Any],
    candidate_rows: list[Any],
) -> list[Any]:
    merged = copy.deepcopy(existing_rows)
    index_by_identity: dict[tuple[str, str], int] = {}
    for index, row in enumerate(merged):
        if not isinstance(row, dict):
            continue
        identity = (
            str(row.get("chain") or "").lower(),
            normalize_address(row.get("address")),
        )
        if identity[0] and identity[1] and identity not in index_by_identity:
            index_by_identity[identity] = index
    for candidate in candidate_rows:
        if not isinstance(candidate, dict):
            if candidate not in merged:
                merged.append(copy.deepcopy(candidate))
            continue
        identity = (
            str(candidate.get("chain") or "").lower(),
            normalize_address(candidate.get("address")),
        )
        existing_index = index_by_identity.get(identity)
        if identity[0] and identity[1] and existing_index is not None:
            existing = merged[existing_index]
            merged[existing_index] = {**candidate, **existing}
            continue
        index_by_identity[identity] = len(merged)
        merged.append(copy.deepcopy(candidate))
    return merged


def item_contracts(item: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (
            str(row.get("chain") or item.get("chain") or "").lower(),
            normalize_address(row.get("address")),
        )
        for row in item.get("contracts", [])
        if isinstance(row, dict) and normalize_address(row.get("address"))
    }


def matching_item_index(items: list[dict[str, Any]], candidate: dict[str, Any]) -> int | None:
    candidate_contracts = item_contracts(candidate)
    for index, item in enumerate(items):
        if candidate_contracts & item_contracts(item):
            return index
    candidate_alpha_id = str((candidate.get("facts") or {}).get("alpha_id") or "")
    if candidate_alpha_id:
        for index, item in enumerate(items):
            existing_alpha_id = str((item.get("facts") or {}).get("alpha_id") or "")
            if existing_alpha_id == candidate_alpha_id:
                return index
    return None


def eligible_catalog_items(
    rows: list[dict[str, Any]],
    *,
    current: datetime,
    lookback_hours: int,
    lookahead_hours: int,
    monitor_hours: int = 0,
) -> list[dict[str, Any]]:
    lower = current - timedelta(hours=max(1, lookback_hours))
    upper = current + timedelta(hours=max(0, lookahead_hours))
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if row.get("cexOffDisplay") is True:
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        alpha_id = str(row.get("alphaId") or "").strip()
        chain = normalize_chain(row)
        contract = normalize_address(row.get("contractAddress"))
        listing = listing_datetime(row)
        if (
            not symbol
            or not alpha_id
            or chain not in SUPPORTED_CHAINS
            or not contract
            or listing is None
        ):
            continue
        if listing < lower or listing > upper:
            continue
        eligible.append(
            (
                listing,
                catalog_watchlist_item(
                    row,
                    listing=listing,
                    chain=chain,
                    contract=contract,
                    opening_max_age_hours=max(72, lookback_hours, monitor_hours),
                ),
            )
        )
    eligible.sort(key=lambda value: value[0], reverse=True)
    selected: list[dict[str, Any]] = []
    seen_contracts: set[tuple[str, str]] = set()
    seen_alpha_ids: set[str] = set()
    for _, item in eligible:
        contracts = item_contracts(item)
        alpha_id = str((item.get("facts") or {}).get("alpha_id") or "")
        if contracts & seen_contracts or (alpha_id and alpha_id in seen_alpha_ids):
            continue
        seen_contracts.update(contracts)
        if alpha_id:
            seen_alpha_ids.add(alpha_id)
        facts = item.setdefault("facts", {})
        facts["catalog_cohort_source"] = "current_catalog"
        selected.append(item)
    return selected


def selected_catalog_items(
    rows: list[dict[str, Any]],
    *,
    current: datetime,
    lookback_hours: int,
    lookahead_hours: int,
    max_selected: int,
    monitor_hours: int = 0,
) -> list[dict[str, Any]]:
    if max_selected < 1:
        raise ValueError("catalog max_selected must be positive")
    return eligible_catalog_items(
        rows,
        current=current,
        lookback_hours=lookback_hours,
        lookahead_hours=lookahead_hours,
        monitor_hours=monitor_hours,
    )[:max_selected]


def eligible_catalog_count(
    rows: list[dict[str, Any]],
    *,
    current: datetime,
    lookback_hours: int,
    lookahead_hours: int,
) -> int:
    return len(
        eligible_catalog_items(
            rows,
            current=current,
            lookback_hours=lookback_hours,
            lookahead_hours=lookahead_hours,
        )
    )


def item_listing_time(item: dict[str, Any]) -> datetime | None:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    return parse_iso_time(facts.get("listing_time_utc"))


def retained_catalog_items(
    previous_runtime_watchlist: dict[str, Any],
    *,
    current: datetime,
    retention_days: int,
) -> tuple[list[dict[str, Any]], int]:
    if retention_days < 1:
        raise ValueError("catalog retention_days must be positive")
    cutoff = current - timedelta(days=retention_days)
    retained: list[dict[str, Any]] = []
    expired_count = 0
    for raw_item in previous_runtime_watchlist.get("items", []):
        if not isinstance(raw_item, dict):
            continue
        facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), dict) else {}
        alpha_id = str(facts.get("alpha_id") or "")
        listing = item_listing_time(raw_item)
        if not alpha_id or listing is None or not item_contracts(raw_item):
            continue
        if listing < cutoff:
            expired_count += 1
            continue
        item = copy.deepcopy(raw_item)
        item["active_monitoring"] = True
        item["opening_max_age_hours"] = max(
            int(item.get("opening_max_age_hours") or 0),
            retention_days * 24,
        )
        item["opening_liquidity_max_age_seconds"] = max(
            int(item.get("opening_liquidity_max_age_seconds") or 0),
            retention_days * 86400,
        )
        item_facts = item.setdefault("facts", {})
        item_facts["catalog_cohort_source"] = "retained_previous_cohort"
        item_facts["catalog_retention_days"] = retention_days
        retained.append(item)
    return retained, expired_count


def deduplicate_catalog_cohort(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[datetime, int]:
        listing = item_listing_time(item) or datetime.min.replace(tzinfo=timezone.utc)
        source = str((item.get("facts") or {}).get("catalog_cohort_source") or "")
        return listing, 1 if source == "current_catalog" else 0

    ordered = sorted(items, key=sort_key, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_contracts: set[tuple[str, str]] = set()
    seen_alpha_ids: set[str] = set()
    for item in ordered:
        contracts = item_contracts(item)
        alpha_id = str((item.get("facts") or {}).get("alpha_id") or "")
        if not contracts or contracts & seen_contracts:
            continue
        if alpha_id and alpha_id in seen_alpha_ids:
            continue
        seen_contracts.update(contracts)
        if alpha_id:
            seen_alpha_ids.add(alpha_id)
        selected.append(item)
    return selected


def catalog_summary_row(item: dict[str, Any]) -> dict[str, Any]:
    contracts = [
        row
        for row in item.get("contracts", [])
        if isinstance(row, dict) and normalize_address(row.get("address"))
    ]
    contract = contracts[0] if contracts else {}
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    return {
        "symbol": item.get("symbol"),
        "chain": contract.get("chain") or item.get("chain"),
        "contract": normalize_address(contract.get("address")),
        "listing_time_utc": facts.get("listing_time_utc", ""),
        "listing_time_utc8": facts.get("listing_time_utc8", ""),
        "alpha_id": facts.get("alpha_id", ""),
        "cohort_source": facts.get("catalog_cohort_source", ""),
    }


def merge_item(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(existing)
    existing_contracts = list(merged.get("contracts", []))
    candidate_contracts = list(candidate.get("contracts", []))
    existing_alpha_id = str((existing.get("facts") or {}).get("alpha_id") or "")
    candidate_alpha_id = str((candidate.get("facts") or {}).get("alpha_id") or "")
    contract_migration = bool(
        candidate_alpha_id
        and candidate_alpha_id == existing_alpha_id
        and not (item_contracts(existing) & item_contracts(candidate))
    )
    if contract_migration:
        merged["contracts"] = merge_contract_rows(
            candidate_contracts,
            existing_contracts,
        )
    else:
        merged["contracts"] = merge_contract_rows(
            existing_contracts,
            candidate_contracts,
        )
    for key in (
        "catalysts",
        "known_times",
        "pool_ids",
        "known_blocks",
        "known_txs",
        "required_checks",
    ):
        merged[key] = unique_list(list(merged.get(key, [])) + list(candidate.get(key, [])))
    if contract_migration:
        merged["facts"] = {**merged.get("facts", {}), **candidate.get("facts", {})}
    else:
        merged["facts"] = {**candidate.get("facts", {}), **merged.get("facts", {})}
    if not merged.get("name"):
        merged["name"] = candidate.get("name")
    if str(merged.get("chain") or "").lower() in {"", "unknown"}:
        merged["chain"] = candidate.get("chain")
    if not merged.get("priority") or str(merged.get("priority")).startswith(("P2", "P3", "P4")):
        merged["priority"] = candidate.get("priority")
    merged["opening_max_age_hours"] = max(
        int(merged.get("opening_max_age_hours") or 0),
        int(candidate.get("opening_max_age_hours") or 0),
    )
    for key in (
        "opening_trace_buyers",
        "opening_max_txs",
        "opening_max_logs",
        "opening_classify_out_txs",
        "opening_next_hop_recipients",
        "opening_next_hop_classify_txs",
        "project_lookback_blocks",
        "opening_liquidity_max_age_seconds",
    ):
        merged[key] = max(int(merged.get(key) or 0), int(candidate.get(key) or 0))
    if not merged.get("project_operator_probe"):
        merged["project_operator_probe"] = candidate.get("project_operator_probe")
    reactivated = existing.get("active_monitoring") is False
    merged["active_monitoring"] = True
    if reactivated:
        merged.setdefault("facts", {})[
            "catalog_active_monitoring_policy"
        ] = "official_cohort_reactivates_static_item"
    return merged


def build_runtime_watchlist(
    static_watchlist: dict[str, Any],
    response: dict[str, Any],
    *,
    current: datetime,
    lookback_hours: int,
    lookahead_hours: int,
    max_selected: int = DEFAULT_MAX_SELECTED,
    previous_runtime_watchlist: dict[str, Any] | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if max_selected < 1:
        raise ValueError("catalog max_selected must be positive")
    rows = valid_catalog_response(response)
    validate_static_watchlist(static_watchlist)
    monitor_hours = retention_days * 24
    current_eligible = eligible_catalog_items(
        rows,
        current=current,
        lookback_hours=lookback_hours,
        lookahead_hours=lookahead_hours,
        monitor_hours=monitor_hours,
    )
    retained, retention_expired_count = retained_catalog_items(
        previous_runtime_watchlist or {},
        current=current,
        retention_days=retention_days,
    )
    cohort = deduplicate_catalog_cohort(current_eligible + retained)
    selected = cohort[:max_selected]
    dropped = cohort[max_selected:]
    retained_eligible_count = sum(
        1
        for item in cohort
        if (item.get("facts") or {}).get("catalog_cohort_source")
        == "retained_previous_cohort"
    )
    retained_selected_count = sum(
        1
        for item in selected
        if (item.get("facts") or {}).get("catalog_cohort_source")
        == "retained_previous_cohort"
    )

    items = [
        copy.deepcopy(item)
        for item in static_watchlist.get("items", [])
        if isinstance(item, dict)
    ]
    for candidate in selected:
        index = matching_item_index(items, candidate)
        if index is None:
            items.append(candidate)
        else:
            items[index] = merge_item(items[index], candidate)
    payload = {
        "generated_at": now_iso(current),
        "runtime_source": "curated_plus_binance_alpha_public_catalog",
        "catalog_retention_days": retention_days,
        "catalog_current_eligible_count": len(current_eligible),
        "catalog_retained_eligible_count": retained_eligible_count,
        "catalog_retained_selected_count": retained_selected_count,
        "catalog_retention_expired_count": retention_expired_count,
        "catalog_eligible_count": len(cohort),
        "catalog_selected_count": len(selected),
        "catalog_dropped_count": len(dropped),
        "catalog_dropped": [catalog_summary_row(item) for item in dropped],
        "items": items,
    }
    return payload, selected


def public_summary(
    *,
    current: datetime,
    token_count: int,
    selected: list[dict[str, Any]],
    runtime_watchlist: dict[str, Any],
    lookback_hours: int,
    lookahead_hours: int,
    max_selected: int,
) -> dict[str, Any]:
    return {
        "schema": "binance_alpha_catalog_watch.v1",
        "status": "pass",
        "generated_at": now_iso(current),
        "lookback_hours": lookback_hours,
        "lookahead_hours": lookahead_hours,
        "supported_chains": sorted(SUPPORTED_CHAINS),
        "max_selected": max_selected,
        "official_token_count": token_count,
        "supported_schema_count": int(
            runtime_watchlist.get("catalog_supported_schema_count") or 0
        ),
        "retention_days": int(
            runtime_watchlist.get("catalog_retention_days") or DEFAULT_RETENTION_DAYS
        ),
        "current_eligible_count": int(
            runtime_watchlist.get("catalog_current_eligible_count") or 0
        ),
        "retained_eligible_count": int(
            runtime_watchlist.get("catalog_retained_eligible_count") or 0
        ),
        "retained_selected_count": int(
            runtime_watchlist.get("catalog_retained_selected_count") or 0
        ),
        "retention_expired_count": int(
            runtime_watchlist.get("catalog_retention_expired_count") or 0
        ),
        "eligible_count": int(runtime_watchlist.get("catalog_eligible_count") or 0),
        "selected_count": len(selected),
        "dropped_count": int(runtime_watchlist.get("catalog_dropped_count") or 0),
        "dropped": list(runtime_watchlist.get("catalog_dropped") or []),
        "runtime_watchlist_item_count": len(runtime_watchlist.get("items", [])),
        "selected": [catalog_summary_row(item) for item in selected],
    }


def main() -> int:
    current: datetime | None = None
    try:
        current = now_utc()
        lookback_hours = int(
            os.environ.get("BINANCE_ALPHA_CATALOG_LOOKBACK_HOURS", "168")
        )
        lookahead_hours = int(
            os.environ.get("BINANCE_ALPHA_CATALOG_LOOKAHEAD_HOURS", "48")
        )
        max_selected = int(
            os.environ.get(
                "BINANCE_ALPHA_CATALOG_MAX_SELECTED",
                str(DEFAULT_MAX_SELECTED),
            )
        )
        timeout = int(os.environ.get("BINANCE_ALPHA_CATALOG_HTTP_TIMEOUT", "20"))
        retention_days = int(
            os.environ.get(
                "BINANCE_ALPHA_CATALOG_RETENTION_DAYS",
                str(DEFAULT_RETENTION_DAYS),
            )
        )
        schema_min_ratio = float(
            os.environ.get(
                "BINANCE_ALPHA_CATALOG_SCHEMA_MIN_RATIO",
                str(DEFAULT_SCHEMA_MIN_RATIO),
            )
        )
        if lookback_hours < 1:
            raise ValueError("catalog lookback_hours must be positive")
        if lookahead_hours < 0:
            raise ValueError("catalog lookahead_hours must be non-negative")
        if max_selected < 1:
            raise ValueError("catalog max_selected must be positive")
        if timeout < 1:
            raise ValueError("catalog HTTP timeout must be positive")
        if retention_days < 1:
            raise ValueError("catalog retention_days must be positive")
        static_watchlist = read_static_watchlist()
        previous_runtime_watchlist = read_json(CURRENT_WATCHLIST_PATH, {})
        previous_summary = read_json(LATEST_PATH, {})
        response = fetch_catalog(timeout)
        token_rows = valid_catalog_response(response)
        supported_schema_count = validate_schema_continuity(
            token_rows,
            previous_summary,
            schema_min_ratio,
        )
        runtime_watchlist, selected = build_runtime_watchlist(
            static_watchlist,
            response,
            current=current,
            lookback_hours=lookback_hours,
            lookahead_hours=lookahead_hours,
            max_selected=max_selected,
            previous_runtime_watchlist=previous_runtime_watchlist,
            retention_days=retention_days,
        )
        runtime_watchlist["catalog_supported_schema_count"] = supported_schema_count
        summary = public_summary(
            current=current,
            token_count=len(token_rows),
            selected=selected,
            runtime_watchlist=runtime_watchlist,
            lookback_hours=lookback_hours,
            lookahead_hours=lookahead_hours,
            max_selected=max_selected,
        )
        atomic_write_json(CURRENT_WATCHLIST_PATH, runtime_watchlist)
        atomic_write_json(LATEST_PATH, summary)
        atomic_write_json(STATUS_PATH, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        generated_at = (
            current
            or datetime.now(timezone.utc).replace(microsecond=0)
        ).isoformat()
        status = {
            "schema": "binance_alpha_catalog_watch.v1",
            "status": "fail",
            "generated_at": generated_at,
            "reason": f"{type(exc).__name__}: {exc}",
            "stale_runtime_watchlist_retained": CURRENT_WATCHLIST_PATH.exists(),
        }
        atomic_write_json(STATUS_PATH, status)
        print(json.dumps(status, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
