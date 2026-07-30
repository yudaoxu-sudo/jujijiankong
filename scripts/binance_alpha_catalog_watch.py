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
PROJECT_REGISTRY_PATH = ROOT / "output" / "project_registry" / "project_registry.json"
TELEGRAM_USER_SIGNAL_DIR = ROOT / "output" / "telegram_user_signals"
TELEGRAM_BOT_SIGNAL_DIR = ROOT / "output" / "telegram_signals"
MANUAL_SIGNAL_DIR = ROOT / "output" / "signals"
SIGNAL_CANDIDATE_DIRS = (
    TELEGRAM_USER_SIGNAL_DIR,
    TELEGRAM_BOT_SIGNAL_DIR,
    MANUAL_SIGNAL_DIR,
)
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
REGISTRY_PENDING_MAX_AGE_DAYS = 7
MAX_SIGNAL_CANDIDATE_FILES = 400
GENERIC_SYMBOLS = {"", "UNKNOWN", "LP", "POOL", "TOKEN", "V3", "V4", "BN", "BSC", "ALPHA"}
TIME_CONFLICT_REASONS = {
    "conflicting_single_signal_opening_times",
    "official_signal_opening_time_conflict",
}


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


def parse_utc8_time(value: Any) -> datetime | None:
    text = str(value or "").replace("UTC+8", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return (
                datetime.strptime(text, fmt)
                .replace(tzinfo=UTC8)
                .astimezone(timezone.utc)
            )
        except ValueError:
            continue
    return None


def monitored_priority(value: Any) -> bool:
    return str(value or "").startswith(("P0", "P1"))


def project_is_alpha_candidate(project: dict[str, Any]) -> bool:
    facts = project.get("facts") if isinstance(project.get("facts"), dict) else {}
    venues = facts.get("venues") if isinstance(facts.get("venues"), list) else []
    if any(str(venue).strip().lower() == "binance alpha" for venue in venues):
        return True
    titles = " ".join(str(title) for title in project.get("titles", []))
    normalized = titles.lower().replace(" ", "")
    return "币安alpha" in normalized or "binancealpha" in normalized or "bnalpha" in normalized


def signal_candidate_project(
    parsed: dict[str, Any],
    *,
    artifact_name: str,
    updated_at: str,
) -> dict[str, Any] | None:
    policy = parsed.get("source_policy")
    proposal = parsed.get("watchlist_proposal")
    enrichment = parsed.get("chain_enrichment")
    if (
        not isinstance(policy, dict)
        or policy.get("context_only") is not False
        or not str(policy.get("authority") or "").strip()
        or policy.get("authority") == "context_only"
        or not isinstance(proposal, dict)
        or not isinstance(enrichment, list)
        or not enrichment
    ):
        return None

    contracts = [
        row for row in proposal.get("contracts", []) if isinstance(row, dict)
    ]
    times = [
        str(value)
        for value in parsed.get("times", [])
        if str(value or "").strip()
    ]
    if not times:
        times = [
            str(row.get("time"))
            for row in proposal.get("known_times", [])
            if isinstance(row, dict) and str(row.get("time") or "").strip()
        ]
    txs = [
        str(value)
        for value in parsed.get("txs", [])
        if str(value or "").strip()
    ]
    if not txs:
        txs = [
            str(row.get("tx"))
            for row in proposal.get("known_txs", [])
            if isinstance(row, dict) and str(row.get("tx") or "").strip()
        ]
    pool_ids = [
        str(value)
        for value in parsed.get("pool_ids", [])
        if str(value or "").strip()
    ]
    if not pool_ids:
        pool_ids = [
            str(row.get("pool_id"))
            for row in proposal.get("pool_ids", [])
            if isinstance(row, dict) and str(row.get("pool_id") or "").strip()
        ]
    return {
        "_candidate_provenance": "single_signal_artifact",
        "project_key": f"signal_artifact:{artifact_name}",
        "symbol": str(parsed.get("symbol") or proposal.get("symbol") or "").upper(),
        "titles": [str(parsed.get("title") or proposal.get("name") or "")],
        "updated_at": str(parsed.get("generated_at") or updated_at),
        "last_priority": str(parsed.get("priority") or proposal.get("priority") or ""),
        "contracts": contracts,
        "addresses": [
            row for row in parsed.get("addresses", []) if isinstance(row, dict)
        ],
        "txs": unique_list(txs),
        "times": unique_list(times),
        "pool_ids": unique_list(pool_ids),
        "facts": parsed.get("facts") if isinstance(parsed.get("facts"), dict) else {},
        "sources": [policy],
        "chain_enrichment": [
            row for row in enrichment if isinstance(row, dict)
        ],
    }


def load_signal_candidate_projects(
    path: Path = TELEGRAM_USER_SIGNAL_DIR,
    *,
    max_files: int = MAX_SIGNAL_CANDIDATE_FILES,
) -> list[dict[str, Any]]:
    if max_files < 1:
        raise ValueError("signal candidate max_files must be positive")
    try:
        files = [
            item
            for item in path.iterdir()
            if item.is_file()
            and item.suffix == ".json"
            and item.name != "state.json"
        ]
    except OSError:
        return []

    def modified(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0

    projects: list[dict[str, Any]] = []
    for artifact in sorted(files, key=modified, reverse=True)[:max_files]:
        parsed = read_json(artifact, {})
        if not isinstance(parsed, dict):
            continue
        mtime = datetime.fromtimestamp(
            modified(artifact), timezone.utc
        ).replace(microsecond=0).isoformat()
        project = signal_candidate_project(
            parsed,
            artifact_name=artifact.name,
            updated_at=mtime,
        )
        if project is not None:
            projects.append(project)
    return projects


def load_all_signal_candidate_projects(
    paths: tuple[Path, ...] = SIGNAL_CANDIDATE_DIRS,
) -> list[dict[str, Any]]:
    return [
        project
        for path in paths
        for project in load_signal_candidate_projects(path)
    ]


def registry_candidate_summary(
    project: dict[str, Any],
    *,
    reasons: list[str],
    opening: datetime | None,
    identities: set[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "symbol": str(project.get("symbol") or "UNKNOWN").upper(),
        "project_key": str(project.get("project_key") or ""),
        "priority": str(project.get("last_priority") or ""),
        "updated_at": str(project.get("updated_at") or ""),
        "opening_time_utc": opening.isoformat() if opening else "",
        "opening_time_utc8": (
            opening.astimezone(UTC8).strftime("%Y-%m-%d %H:%M")
            if opening
            else ""
        ),
        "reasons": reasons,
        "identities": [
            f"{chain}:{contract}"
            for chain, contract in sorted(identities)
        ],
    }


def verified_registry_candidates(
    registry: dict[str, Any],
    *,
    current: datetime,
    retention_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cutoff = current - timedelta(days=retention_days)
    ready: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for project in registry.get("projects", []):
        if not isinstance(project, dict) or not project_is_alpha_candidate(project):
            continue
        if not monitored_priority(project.get("last_priority")):
            continue
        updated = parse_iso_time(project.get("updated_at"))
        times = unique_list(
            [
                parsed.isoformat()
                for parsed in (
                    parse_utc8_time(value) for value in project.get("times", [])
                )
                if parsed is not None
            ]
        )
        openings = [parse_iso_time(value) for value in times]
        openings = [value for value in openings if value is not None]
        opening = openings[0] if len(openings) == 1 else None
        if updated is not None and updated < cutoff and (
            opening is None or opening < cutoff
        ):
            continue

        reasons: list[str] = []
        symbol = str(project.get("symbol") or "").upper()
        if symbol in GENERIC_SYMBOLS:
            reasons.append("missing_project_symbol")
        sources = [
            row for row in project.get("sources", []) if isinstance(row, dict)
        ]
        if any(row.get("context_only") is True for row in sources):
            continue
        if project.get("_candidate_provenance") != "single_signal_artifact":
            reasons.append("unproven_time_pool_binding")
        if not openings:
            reasons.append("missing_exact_opening_time")
        elif len(openings) > 1:
            reasons.append("ambiguous_opening_time")

        project_contracts = {
            (
                str(row.get("chain") or "").lower(),
                normalize_address(row.get("address")),
            )
            for row in project.get("contracts", [])
            if isinstance(row, dict)
            and normalize_address(row.get("address"))
        }
        project_txs = {
            str(value or "").lower() for value in project.get("txs", [])
        }
        project_pools = {
            str(value or "").lower() for value in project.get("pool_ids", [])
        }
        verified: list[dict[str, Any]] = []
        observed_chains: set[str] = set()
        for row in project.get("chain_enrichment", []):
            if not isinstance(row, dict) or row.get("status") != "ok":
                continue
            chain = str(row.get("chain") or "").lower()
            if chain:
                observed_chains.add(chain)
            tx_hash = str(row.get("tx_hash") or "").lower()
            pool_id = str(row.get("pool_id") or "").lower()
            if (
                chain not in SUPPORTED_CHAINS
                or tx_hash not in project_txs
                or pool_id not in project_pools
            ):
                continue
            token_rows = [
                token
                for token in (row.get("token0"), row.get("token1"))
                if isinstance(token, dict)
            ]
            quote_address = USDT_BY_CHAIN.get(chain, "")
            quote = next(
                (
                    token
                    for token in token_rows
                    if normalize_address(token.get("address")) == quote_address
                ),
                None,
            )
            token = next(
                (
                    token
                    for token in token_rows
                    if str(token.get("symbol") or "").upper() == symbol
                    and normalize_address(token.get("address")) != quote_address
                ),
                None,
            )
            contract = normalize_address((token or {}).get("address"))
            if (
                quote is None
                or token is None
                or (chain, contract) not in project_contracts
            ):
                continue
            verified.append(
                {
                    "chain": chain,
                    "contract": contract,
                    "pool_id": pool_id,
                    "tx_hash": tx_hash,
                    "block": row.get("block"),
                    "hook": normalize_address((row.get("raw_fields") or {}).get("hook")),
                }
            )
        if not verified:
            reasons.append("missing_receipt_verified_alpha_pool")
            unsupported_chains = sorted(observed_chains - SUPPORTED_CHAINS)
            if unsupported_chains:
                reasons.append(
                    "unsupported_chain:" + ",".join(unsupported_chains)
                )
        identities = {
            (row["chain"], row["contract"]) for row in verified
        }
        if len(identities) > 1:
            reasons.append("ambiguous_contract_identity")

        if reasons:
            pending_cutoff = current - timedelta(
                days=REGISTRY_PENDING_MAX_AGE_DAYS
            )
            if updated is not None and updated < pending_cutoff and (
                opening is None or opening < current
            ):
                continue
            pending.append(
                registry_candidate_summary(
                    project,
                    reasons=reasons,
                    opening=opening,
                    identities=identities,
                )
            )
            continue

        chain, contract = next(iter(identities))
        start_utc8 = opening.astimezone(UTC8).strftime("%Y-%m-%d %H:%M")
        pool_rows = []
        seen_pools: set[str] = set()
        for row in verified:
            if row["pool_id"] in seen_pools:
                continue
            seen_pools.add(row["pool_id"])
            pool = {
                "chain": chain,
                "pool_id": row["pool_id"],
                "start_time_utc8": start_utc8,
                "source": "telegram_signal_receipt_verified",
                "opening_anchor_status": "verified_prelaunch_pool",
                "quote_address": USDT_BY_CHAIN[chain],
            }
            if row["hook"]:
                pool["hook"] = row["hook"]
            pool_rows.append(pool)
        watch_addresses = []
        for address_row in project.get("addresses", []):
            if not isinstance(address_row, dict):
                continue
            address = normalize_address(address_row.get("address"))
            label = str(address_row.get("label_hint") or "")
            if not address or address == contract or not any(
                marker in label for marker in ("hook", "operator")
            ):
                continue
            watch_addresses.append(
                {
                    "chain": chain,
                    "address": address,
                    "label": label,
                    "role": "pool_hook_or_operator",
                    "level": "HIGH",
                    "watch_quote": True,
                }
            )
        item = {
            "symbol": symbol,
            "name": str(project.get("titles", [symbol])[-1] or symbol),
            "priority": str(project.get("last_priority") or "P1_MONITOR"),
            "chain": chain,
            "active_monitoring": True,
            "contracts": [
                {
                    "chain": chain,
                    "address": contract,
                    "confidence": "telegram_signal_receipt_verified",
                }
            ],
            "catalysts": ["Binance Alpha verified prelaunch pool"],
            "known_times": [
                {"time": start_utc8, "reason": "verified_prelaunch_pool"}
            ],
            "pool_ids": pool_rows,
            "known_blocks": [
                {
                    "chain": chain,
                    "block": int(row["block"]),
                    "reason": "verified_prelaunch_pool",
                }
                for row in verified
                if str(row.get("block") or "").isdigit()
            ],
            "known_txs": [
                {
                    "chain": chain,
                    "tx": row["tx_hash"],
                    "reason": "verified_prelaunch_pool",
                }
                for row in verified
            ],
            "watch_addresses": watch_addresses,
            "opening_max_age_hours": max(72, retention_days * 24),
            "opening_liquidity_max_age_seconds": max(
                72 * 3600, retention_days * 86400
            ),
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
                "source": "telegram_signal_receipt_verified",
                "project_key": str(project.get("project_key") or ""),
                "registry_updated_at": str(project.get("updated_at") or ""),
                "listing_time_utc": opening.isoformat(),
                "listing_time_utc8": start_utc8,
                "opening_anchor_status": "verified_prelaunch_pool",
            },
        }
        ready.append(item)
    ready, conflict_rows = reject_candidate_time_conflicts(ready)
    pending.extend(conflict_rows)
    ready.sort(key=lambda item: item_listing_time(item) or cutoff, reverse=True)
    pending.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return ready, pending


def reject_candidate_time_conflicts(
    ready: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in ready:
        identities = item_contracts(item)
        if len(identities) == 1:
            by_identity.setdefault(next(iter(identities)), []).append(item)
    conflicted = {
        identity
        for identity, items in by_identity.items()
        if len(
            {
                value.isoformat()
                for value in (item_listing_time(item) for item in items)
                if value is not None
            }
        )
        > 1
    }
    if not conflicted:
        return ready, []
    safe = [
        item for item in ready if not (item_contracts(item) & conflicted)
    ]
    pending = []
    for chain, contract in sorted(conflicted):
        items = by_identity[(chain, contract)]
        times = sorted(
            {
                value.isoformat()
                for value in (item_listing_time(item) for item in items)
                if value is not None
            }
        )
        pending.append(
            {
                "symbol": str(items[0].get("symbol") or "UNKNOWN").upper(),
                "project_key": f"identity:{chain}:{contract}",
                "priority": "P0_DEEP_REVIEW",
                "updated_at": max(
                    str((item.get("facts") or {}).get("registry_updated_at") or "")
                    for item in items
                ),
                "opening_time_utc": "",
                "opening_time_utc8": "",
                "reasons": ["conflicting_single_signal_opening_times"],
                "conflicting_opening_times_utc": times,
                "identities": [f"{chain}:{contract}"],
            }
        )
    return safe, pending


def reject_official_signal_time_conflicts(
    official: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    official_by_identity = {
        identity: item
        for item in official
        for identity in item_contracts(item)
    }
    conflicted: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for signal in signals:
        signal_time = item_listing_time(signal)
        if signal_time is None:
            continue
        for identity in item_contracts(signal):
            official_item = official_by_identity.get(identity)
            official_time = item_listing_time(official_item or {})
            if official_time is not None and official_time != signal_time:
                conflicted[identity] = (official_item, signal)
    if not conflicted:
        return signals, []
    conflicted_identities = set(conflicted)
    safe = [
        item
        for item in signals
        if not (item_contracts(item) & conflicted_identities)
    ]
    pending = []
    for (chain, contract), (official_item, signal) in sorted(conflicted.items()):
        official_time = item_listing_time(official_item)
        signal_time = item_listing_time(signal)
        pending.append(
            {
                "symbol": str(signal.get("symbol") or "UNKNOWN").upper(),
                "project_key": f"identity:{chain}:{contract}",
                "priority": "P0_DEEP_REVIEW",
                "updated_at": str(
                    (signal.get("facts") or {}).get("registry_updated_at") or ""
                ),
                "opening_time_utc": "",
                "opening_time_utc8": "",
                "reasons": ["official_signal_opening_time_conflict"],
                "conflicting_opening_times_utc": sorted(
                    {
                        value.isoformat()
                        for value in (official_time, signal_time)
                        if value is not None
                    }
                ),
                "identities": [f"{chain}:{contract}"],
            }
        )
    return safe, pending


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


def unsupported_catalog_items(
    rows: list[dict[str, Any]],
    *,
    current: datetime,
    lookback_hours: int,
    lookahead_hours: int,
) -> list[dict[str, Any]]:
    lower = current - timedelta(hours=max(1, lookback_hours))
    upper = current + timedelta(hours=max(0, lookahead_hours))
    unsupported: list[dict[str, Any]] = []
    for row in rows:
        if row.get("cexOffDisplay") is True:
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        alpha_id = str(row.get("alphaId") or "").strip()
        listing = listing_datetime(row)
        chain = normalize_chain(row)
        if (
            not symbol
            or not alpha_id
            or listing is None
            or listing < lower
            or listing > upper
            or chain in SUPPORTED_CHAINS
        ):
            continue
        unsupported.append(
            {
                "symbol": symbol,
                "alpha_id": alpha_id,
                "chain": chain or str(row.get("chainName") or row.get("chainId") or "unknown"),
                "listing_time_utc": listing.isoformat(),
                "listing_time_utc8": listing.astimezone(UTC8).strftime("%Y-%m-%d %H:%M"),
            }
        )
    unsupported.sort(key=lambda row: str(row["listing_time_utc"]), reverse=True)
    return unsupported


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


def retained_signal_candidates(
    previous_runtime_watchlist: dict[str, Any],
    *,
    current: datetime,
    retention_days: int,
) -> list[dict[str, Any]]:
    cutoff = current - timedelta(days=retention_days)
    retained: list[dict[str, Any]] = []
    for raw_item in previous_runtime_watchlist.get("items", []):
        if not isinstance(raw_item, dict):
            continue
        facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), dict) else {}
        listing = item_listing_time(raw_item)
        if (
            facts.get("source") != "telegram_signal_receipt_verified"
            or listing is None
            or listing < cutoff
            or not item_contracts(raw_item)
        ):
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
        item.setdefault("facts", {})[
            "signal_candidate_cohort_source"
        ] = "retained_previous_runtime"
        retained.append(item)
    return retained


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
        "watch_addresses",
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


def merge_candidate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for candidate in items:
        index = matching_item_index(merged, candidate)
        if index is None:
            merged.append(candidate)
        else:
            merged[index] = merge_item(merged[index], candidate)
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
    project_registry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if max_selected < 1:
        raise ValueError("catalog max_selected must be positive")
    rows = valid_catalog_response(response)
    validate_static_watchlist(static_watchlist)
    unsupported = unsupported_catalog_items(
        rows,
        current=current,
        lookback_hours=lookback_hours,
        lookahead_hours=lookahead_hours,
    )
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
    registry_selected, registry_pending = verified_registry_candidates(
        project_registry or {"projects": []},
        current=current,
        retention_days=retention_days,
    )
    registry_selected.extend(
        retained_signal_candidates(
            previous_runtime_watchlist or {},
            current=current,
            retention_days=retention_days,
        )
    )
    registry_selected, retained_conflicts = reject_candidate_time_conflicts(
        registry_selected
    )
    registry_pending.extend(retained_conflicts)
    registry_selected, official_conflicts = reject_official_signal_time_conflicts(
        selected,
        registry_selected,
    )
    registry_pending.extend(official_conflicts)
    registry_selected = merge_candidate_items(registry_selected)
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
    registry_lifecycle_targets = registry_selected
    for candidate in selected + registry_selected:
        index = matching_item_index(items, candidate)
        if index is None:
            items.append(candidate)
        else:
            items[index] = merge_item(items[index], candidate)
    covered_identities = {
        f"{chain}:{contract}"
        for item in items
        for chain, contract in item_contracts(item)
    }
    covered_symbol_openings = {
        (
            str(item.get("symbol") or "").upper(),
            (item_listing_time(item) or datetime.min.replace(tzinfo=timezone.utc)).isoformat(),
        )
        for item in selected + registry_selected
        if item_listing_time(item) is not None
    }
    registry_pending = [
        row
        for row in registry_pending
        if TIME_CONFLICT_REASONS
        & set(str(value) for value in row.get("reasons", []))
        or (
            not (
                set(str(value) for value in row.get("identities", []))
                & covered_identities
            )
            and (
                str(row.get("symbol") or "").upper(),
                str(row.get("opening_time_utc") or ""),
            )
            not in covered_symbol_openings
        )
    ]
    payload = {
        "generated_at": now_iso(current),
        "runtime_source": "curated_plus_binance_alpha_public_catalog_and_verified_signals",
        "catalog_retention_days": retention_days,
        "catalog_current_eligible_count": len(current_eligible),
        "catalog_retained_eligible_count": retained_eligible_count,
        "catalog_retained_selected_count": retained_selected_count,
        "catalog_retention_expired_count": retention_expired_count,
        "catalog_eligible_count": len(cohort),
        "catalog_selected_count": len(selected),
        "catalog_dropped_count": len(dropped),
        "catalog_dropped": [catalog_summary_row(item) for item in dropped],
        "catalog_unsupported_count": len(unsupported),
        "catalog_unsupported": unsupported,
        "registry_candidate_count": len(registry_lifecycle_targets) + len(registry_pending),
        "registry_selected_count": len(registry_lifecycle_targets),
        "registry_pending_count": len(registry_pending),
        "registry_selected": [
            {
                **catalog_summary_row(item),
                "source": "telegram_signal_receipt_verified",
            }
            for item in registry_lifecycle_targets
        ],
        "registry_pending": registry_pending,
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
        "unsupported_count": int(
            runtime_watchlist.get("catalog_unsupported_count") or 0
        ),
        "unsupported": list(runtime_watchlist.get("catalog_unsupported") or []),
        "registry_candidate_count": int(
            runtime_watchlist.get("registry_candidate_count") or 0
        ),
        "registry_selected_count": int(
            runtime_watchlist.get("registry_selected_count") or 0
        ),
        "registry_pending_count": int(
            runtime_watchlist.get("registry_pending_count") or 0
        ),
        "registry_selected": list(runtime_watchlist.get("registry_selected") or []),
        "registry_pending": list(runtime_watchlist.get("registry_pending") or []),
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
        project_registry = read_json(PROJECT_REGISTRY_PATH, {"projects": []})
        registry_projects = (
            project_registry.get("projects", [])
            if isinstance(project_registry, dict)
            and isinstance(project_registry.get("projects"), list)
            else []
        )
        project_registry = {
            "projects": registry_projects + load_all_signal_candidate_projects()
        }
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
            project_registry=project_registry,
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
