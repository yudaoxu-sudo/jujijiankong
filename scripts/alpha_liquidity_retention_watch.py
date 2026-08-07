#!/usr/bin/env python3
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.alpha_holder_concentration_watch as holder


CONFIG_PATH = Path(
    os.environ.get(
        "ALPHA_WATCHLIST_PATH",
        ROOT / "config" / "current_alpha_watchlist.json",
    )
)
OUT_DIR = ROOT / "output" / "alpha_liquidity_retention_watch"
LATEST_PATH = OUT_DIR / "latest.json"
REPORT_PATH = OUT_DIR / "latest.md"
STATE_PATH = OUT_DIR / "state.json"
LAST_PUSH_PATH = OUT_DIR / "last_push.json"
RUN_LOCK_PATH = Path(
    os.environ.get(
        "ALPHA_LIQUIDITY_FAST_LOCK_FILE",
        "/tmp/sniper_alpha_liquidity_retention.lock",
    )
)
STATE_SCHEMA = "alpha_liquidity_retention_state.v1"
SNAPSHOT_SCHEMA = "alpha_liquidity_retention_watch.v1"
DEFAULT_BUDGET_SECONDS = 35
MAX_BUDGET_SECONDS = 35


class ReconciliationStateInvalid(ValueError):
    pass


def configured_budget_seconds() -> int:
    try:
        configured = int(
            os.environ.get(
                "ALPHA_LIQUIDITY_FAST_BUDGET_SECONDS",
                str(DEFAULT_BUDGET_SECONDS),
            )
        )
    except ValueError:
        configured = DEFAULT_BUDGET_SECONDS
    return min(MAX_BUDGET_SECONDS, max(1, configured))


def stable_identity_hash(items: list[dict[str, Any]]) -> str:
    identities = sorted(
        {
            f"{str(item.get('chain') or '').lower()}:"
            f"{holder.norm(item.get('address'))}"
            for item in items
        }
    )
    encoded = json.dumps(
        identities,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def eligible_contract_items(
    config: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not isinstance(config, dict) or not isinstance(
        config.get("items"),
        list,
    ):
        return [], [
            {
                "kind": "watchlist_invalid",
                "name": "watchlist",
                "detail": "watchlist item list invalid",
            }
        ]
    priorities = tuple(
        part.strip()
        for part in os.environ.get(
            "ALPHA_HOLDER_PRIORITIES",
            "P0,P1",
        ).split(",")
        if part.strip()
    )
    rows_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    issues: list[dict[str, str]] = []
    for config_item in config["items"]:
        if not isinstance(config_item, dict):
            issues.append(
                {
                    "kind": "watchlist_invalid",
                    "name": "watchlist",
                    "detail": "watchlist project item invalid",
                }
            )
            continue
        if config_item.get("active_monitoring") is False:
            continue
        if (
            config_item.get("project_watch_skip_generic")
            and os.environ.get("ALPHA_HOLDER_INCLUDE_SPECIALIZED") != "1"
        ):
            continue
        priority = str(config_item.get("priority") or "")
        if priorities and not priority.startswith(priorities):
            continue
        symbol = str(
            config_item.get("symbol")
            or config_item.get("name")
            or "UNKNOWN"
        ).upper()
        contracts = config_item.get("contracts")
        if not isinstance(contracts, list):
            issues.append(
                {
                    "kind": "watchlist_invalid",
                    "name": symbol,
                    "detail": "watchlist contract list invalid",
                }
            )
            continue
        for contract in contracts:
            if not isinstance(contract, dict):
                issues.append(
                    {
                        "kind": "watchlist_invalid",
                        "name": symbol,
                        "detail": "watchlist contract item invalid",
                    }
                )
                continue
            chain = str(contract.get("chain") or "").lower()
            address = holder.norm(contract.get("address"))
            if chain not in holder.SUPPORTED_CHAINS or not holder.is_address(
                address
            ):
                continue
            identity = (chain, address)
            existing = rows_by_identity.get(identity)
            if existing is not None:
                if existing["symbol"] != symbol:
                    issues.append(
                        {
                            "kind": "watchlist_identity_conflict",
                            "name": symbol,
                            "detail": "contract identity maps to multiple symbols",
                        }
                    )
                continue
            rows_by_identity[identity] = {
                "symbol": symbol,
                "name": str(config_item.get("name") or ""),
                "priority": priority,
                "chain": chain,
                "address": address,
            }
    rows = sorted(
        rows_by_identity.values(),
        key=lambda row: (row["chain"], row["address"], row["symbol"]),
    )
    return rows, issues


def validated_state(payload: Any) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != STATE_SCHEMA
        or not isinstance(payload.get("tokens"), dict)
    ):
        return {"schema": STATE_SCHEMA, "tokens": {}}
    return payload


def config_item_for_identity(
    config: Any,
    chain: str,
    token: str,
) -> dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(
        config.get("items"), list
    ):
        return {}
    matches = []
    for item in config["items"]:
        if not isinstance(item, dict):
            continue
        contracts = item.get("contracts")
        if not isinstance(contracts, list):
            continue
        if any(
            isinstance(contract, dict)
            and str(contract.get("chain") or "").lower() == chain
            and holder.norm(contract.get("address")) == token
            for contract in contracts
        ):
            matches.append(item)
    return matches[0] if len(matches) == 1 else {}


def opened_event_for_identity(
    opening_payload: dict[str, Any],
    chain: str,
    token: str,
) -> dict[str, Any] | None:
    events = opening_payload.get("events")
    if not isinstance(events, list):
        return None
    matches = []
    for event in events:
        if not isinstance(event, dict) or event.get("status") != "opened":
            continue
        token_payload = event.get("token")
        if (
            isinstance(token_payload, dict)
            and str(event.get("chain") or "").lower() == chain
            and holder.norm(token_payload.get("address")) == token
        ):
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


def matching_opened_event(
    opening_payload: dict[str, Any],
    symbol: str,
    chain: str,
    token: str,
) -> bool:
    del symbol
    return opened_event_for_identity(opening_payload, chain, token) is not None


def validated_liquidity_seed(
    payload: Any,
    token: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        schema_version = int(payload.get("scope_state_schema_version") or 0)
    except (TypeError, ValueError):
        return {}
    pools = holder.normalized_verified_liquidity_pools(
        payload.get("pool_scope"),
        token,
    )
    scope_hash = str(payload.get("scope_hash") or "").lower()
    if (
        schema_version != holder.LIQUIDITY_SCOPE_STATE_SCHEMA_VERSION
        or not pools
        or len(scope_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in scope_hash
        )
        or holder.liquidity_pool_scope_hash(pools) != scope_hash
    ):
        return {}
    seed: dict[str, Any] = {
        "scope_state_schema_version": schema_version,
        "scope_hash": scope_hash,
        "pool_scope": pools,
        "pool_count": len(pools),
    }
    raw_reconciliation = payload.get("reconciliation")
    reconciliation = (
        holder.migrate_liquidity_reconciliation_state(
            raw_reconciliation,
            maximum_seconds=900,
        )
        if isinstance(raw_reconciliation, dict)
        and raw_reconciliation.get("schema")
        in {
            holder.LEGACY_LIQUIDITY_RECONCILIATION_SCHEMA,
            holder.LIQUIDITY_RECONCILIATION_SCHEMA,
        }
        else raw_reconciliation
    )
    reconciliation_valid = bool(
        isinstance(reconciliation, dict)
        and reconciliation.get("schema")
        == holder.LIQUIDITY_RECONCILIATION_SCHEMA
        and reconciliation.get("state_invalid") is not True
        and isinstance(reconciliation.get("pending"), list)
        and isinstance(reconciliation.get("completed"), list)
        and isinstance(
            reconciliation.get("deferred_events", []), list
        )
        and len(reconciliation["pending"]) <= 500
        and len(reconciliation["completed"]) <= 500
        and len(reconciliation.get("deferred_events", [])) <= 500
        and all(
            isinstance(row, dict)
            and holder.valid_sha256(row.get("reconcile_id"))
            and holder.parse_iso(row.get("first_seen_at")) is not None
            and isinstance(row.get("source_event"), dict)
            for row in reconciliation["pending"]
        )
        and all(
            isinstance(row, dict)
            and holder.valid_sha256(row.get("reconcile_id"))
            and holder.parse_iso(row.get("completed_at")) is not None
            for row in reconciliation["completed"]
        )
        and all(
            isinstance(row, dict)
            and holder.valid_hash32(row.get("tx"))
            and str(row.get("type") or "")
            in (
                holder.LIQUIDITY_RECONCILIATION_REMOVAL_TYPES
                | {"lp_add_observation"}
            )
            for row in reconciliation.get("deferred_events", [])
        )
    )
    if reconciliation_valid:
        seed["reconciliation"] = copy.deepcopy(reconciliation)
    elif "reconciliation" in payload:
        seed["reconciliation_state_invalid"] = True
    try:
        latest_block = int(payload.get("latest_block") or 0)
        coverage_from = int(payload.get("scope_coverage_from_block") or 0)
    except (TypeError, ValueError):
        return seed
    latest_hash = str(payload.get("latest_block_hash") or "").lower()
    catchup_active = payload.get("catchup_active")
    if (
        latest_block > 0
        and 0 <= coverage_from <= latest_block
        and holder.valid_hash32(latest_hash)
        and int(latest_hash[2:], 16) != 0
        and isinstance(catchup_active, bool)
    ):
        seed.update(
            {
                "scope_coverage_from_block": coverage_from,
                "latest_block": latest_block,
                "latest_block_hash": latest_hash,
                "catchup_active": catchup_active,
            }
        )
        if catchup_active:
            try:
                live_from = int(
                    payload.get("catchup_live_from_block") or 0
                )
                next_window = int(
                    payload.get("next_catchup_window_blocks") or 0
                )
            except (TypeError, ValueError):
                live_from = 0
                next_window = 0
            if live_from >= max(1, coverage_from):
                seed["catchup_live_from_block"] = live_from
            if next_window > 0:
                seed["next_catchup_window_blocks"] = next_window
    return seed


def holder_liquidity_seed(
    holder_state: Any,
    chain: str,
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tokens = (
        holder_state.get("tokens")
        if isinstance(holder_state, dict)
        and isinstance(holder_state.get("tokens"), dict)
        else {}
    )
    token_state = tokens.get(f"{chain}:{token}")
    if not isinstance(token_state, dict):
        return {}, {}
    retention = token_state.get("retention_flow")
    liquidity = (
        retention.get("liquidity")
        if isinstance(retention, dict)
        and isinstance(retention.get("liquidity"), dict)
        else {}
    )
    return validated_liquidity_seed(liquidity, token), token_state


def safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ReconciliationStateInvalid):
        return "liquidity_reconciliation_state_invalid"
    if isinstance(exc, TimeoutError):
        return "deadline_exceeded"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "invalid_runtime_metadata"
    if isinstance(exc, RuntimeError):
        return "runtime_dependency_failed"
    if isinstance(exc, OSError):
        return "runtime_io_failed"
    return "unexpected_runtime_error"


def strict_token_metadata(
    chain: str,
    token: str,
    token_state: dict[str, Any],
) -> tuple[int, int]:
    try:
        decimals = int(token_state.get("decimals"))
    except (TypeError, ValueError):
        decimals = holder.call_uint(chain, token, "0x313ce567")
    if decimals < 0 or decimals > 36:
        raise ValueError("token decimals invalid")
    supply_raw = holder.call_uint(chain, token, "0x18160ddd")
    if supply_raw <= 0:
        raise ValueError("token total supply unavailable")
    return decimals, supply_raw


def liquidity_operational_issue(
    flow: dict[str, Any],
    *,
    required: bool,
    next_state: dict[str, Any] | None,
) -> str:
    if not required:
        return ""
    if flow.get("status") != "active":
        return f"status={flow.get('status', 'missing')}"
    if int(flow.get("pool_count") or 0) <= 0:
        return "verified pool scope empty"
    if int(flow.get("attribution_query_error_count") or 0):
        return "liquidity operator attribution failed"
    if int(flow.get("log_error_count") or 0):
        return "indexed log query failed"
    if flow.get("truncated") or flow.get("events_truncated"):
        return "indexed log result truncated"
    if flow.get("selected_window_complete") is not True:
        return "selected window incomplete"
    if flow.get("query_scope_complete") is not True:
        return "indexed query scope incomplete"
    if flow.get("complete") is not True:
        catchup = flow.get("incremental_catchup") or {}
        if isinstance(catchup, dict) and catchup.get("active") is True:
            return (
                "catchup active "
                f"{catchup.get('selected_to_block', '?')}/"
                f"{catchup.get('requested_to_block', '?')}"
            )
        return "confirmed-tip coverage incomplete"
    if next_state is None:
        return "checkpoint unavailable"
    return ""


def error_flow(reason: str) -> dict[str, Any]:
    return {
        "status": "coverage_gap",
        "reason": reason,
        "coverage_mode": "verified_pool_indexed_topics",
        "scope_complete": False,
        "complete": False,
        "selected_window_complete": False,
        "query_scope_complete": False,
        "pool_count": 0,
        "log_error_count": 1,
        "truncated": False,
        "events_truncated": False,
        "events": [],
    }


def build_snapshot() -> dict[str, Any]:
    config = holder.read_json(CONFIG_PATH, {"items": []})
    opening_payload = holder.read_json(
        holder.OPENING_CONTEXT_PATH,
        {"events": []},
    )
    if not isinstance(opening_payload, dict):
        opening_payload = {"events": []}
    current_state = validated_state(
        holder.read_json(STATE_PATH, {"schema": STATE_SCHEMA, "tokens": {}})
    )
    holder_state = holder.read_json(holder.STATE_PATH, {"tokens": {}})
    current_tokens = current_state["tokens"]
    next_tokens = dict(current_tokens)
    projects: list[dict[str, Any]] = []
    expected_items, enumeration_issues = eligible_contract_items(config)
    issues: list[dict[str, str]] = list(enumeration_issues)
    tip_by_chain: dict[str, int] = {}
    budget_seconds = configured_budget_seconds()
    deadline = time.monotonic() + budget_seconds
    previous_deadline = holder.HOLDER_DEADLINE_AT
    holder.HOLDER_DEADLINE_AT = deadline
    try:
        for item in expected_items:
            symbol = str(item.get("symbol") or "UNKNOWN").upper()
            chain = str(item.get("chain") or "").lower()
            token = holder.norm(item.get("address"))
            key = f"{chain}:{token}"
            token_state = (
                current_tokens.get(key)
                if isinstance(current_tokens.get(key), dict)
                else {}
            )
            raw_persisted_liquidity = (
                token_state.get("liquidity")
                if isinstance(token_state.get("liquidity"), dict)
                else {}
            )
            persisted_liquidity = validated_liquidity_seed(
                raw_persisted_liquidity,
                token,
            )
            holder_seed, holder_token_state = holder_liquidity_seed(
                holder_state,
                chain,
                token,
            )
            seed_source = "standalone" if persisted_liquidity else ""
            if not persisted_liquidity and holder_seed:
                persisted_liquidity = holder_seed
                seed_source = "holder"
                next_tokens[key] = {
                    "decimals": holder_token_state.get("decimals"),
                    "liquidity": holder_seed,
                }
            elif raw_persisted_liquidity and not persisted_liquidity:
                next_tokens.pop(key, None)
            opening_event = opened_event_for_identity(
                opening_payload,
                chain,
                token,
            )
            opening_symbol = str(
                (opening_event or {}).get("symbol") or symbol
            ).upper()
            opened_obligation = matching_opened_event(
                opening_payload,
                symbol,
                chain,
                token,
            )
            persisted_obligation = bool(
                persisted_liquidity.get("pool_scope")
            )
            flow: dict[str, Any]
            next_liquidity_state: dict[str, Any] | None = None
            required = opened_obligation or persisted_obligation
            exception_recorded = False
            try:
                if persisted_liquidity.get(
                    "reconciliation_state_invalid"
                ) is True:
                    raise ReconciliationStateInvalid(
                        "liquidity reconciliation state invalid"
                    )
                config_item = config_item_for_identity(
                    config,
                    chain,
                    token,
                )
                if not config_item:
                    config_item = holder.config_item_for_contract(
                        config,
                        symbol,
                        chain,
                        token,
                    )
                if not config_item:
                    raise ValueError("watchlist contract metadata missing")
                window = holder.retention_window(config_item, chain)
                window_active = window.get("status") == "active"
                scope = holder.opening_verified_pool_scope(
                    opening_payload,
                    opening_symbol,
                    chain,
                    token,
                    persisted_scope=persisted_liquidity,
                )
                try:
                    age_hours = float(window.get("age_hours"))
                except (TypeError, ValueError):
                    age_hours = -1
                verified_expired = bool(
                    window.get("status") == "not_required"
                    and window.get("reason") == "retention_window_expired"
                    and age_hours > holder.RETENTION_FLOW_DAYS * 24
                )
                explicit_no_pool = bool(
                    scope.get("source") == "opening"
                    and scope.get("complete") is True
                    and scope.get("status") == "no_verified_pool"
                    and not scope.get("pool_scope")
                )
                required = bool(
                    not verified_expired
                    and not explicit_no_pool
                    and (
                        window_active
                        or bool(scope.get("pool_scope"))
                        or opened_obligation
                        or persisted_obligation
                        or bool(holder_seed)
                    )
                )
                if window.get("status") != "active" or not scope.get(
                    "pool_scope"
                ):
                    flow, next_liquidity_state = (
                        holder.build_token_liquidity_retention(
                            item=config_item,
                            symbol=opening_symbol,
                            chain=chain,
                            token=token,
                            tip=0,
                            decimals=int(token_state.get("decimals") or 18),
                            supply_raw=0,
                            opening_payload=opening_payload,
                            liquidity_state=persisted_liquidity,
                        )
                    )
                else:
                    decimals, supply_raw = strict_token_metadata(
                        chain,
                        token,
                        token_state or holder_token_state,
                    )
                    if chain not in tip_by_chain:
                        tip_by_chain[chain] = holder.latest_block(chain)
                    flow, next_liquidity_state = (
                        holder.build_token_liquidity_retention(
                            item=config_item,
                            symbol=opening_symbol,
                            chain=chain,
                            token=token,
                            tip=tip_by_chain[chain],
                            decimals=decimals,
                            supply_raw=supply_raw,
                            opening_payload=opening_payload,
                            liquidity_state=persisted_liquidity,
                        )
                    )
                    if next_liquidity_state is not None:
                        next_tokens[key] = {
                            "decimals": decimals,
                            "liquidity": next_liquidity_state,
                        }
            except Exception as exc:
                detail = safe_error_message(exc)
                flow = error_flow(detail)
                if required:
                    issues.append(
                        {
                            "kind": "liquidity_scan_failed",
                            "name": symbol,
                            "detail": detail,
                        }
                    )
                    exception_recorded = True

            detail = liquidity_operational_issue(
                flow,
                required=required,
                next_state=next_liquidity_state,
            )

            project = {
                "symbol": symbol,
                "name": str(item.get("name") or ""),
                "priority": str(item.get("priority") or ""),
                "chain": chain,
                "address": token,
                "required": required,
                "opening_symbol": opening_symbol,
                "scope_seed_source": seed_source,
                "operational_complete": not bool(detail),
                "retention_flow": {
                    "status": flow.get("status"),
                    "events": [],
                    "liquidity_retention": flow,
                },
            }
            projects.append(project)
            if detail and not exception_recorded:
                issues.append(
                    {
                        "kind": "liquidity_coverage_gap",
                        "name": symbol,
                        "detail": detail,
                    }
                )
    finally:
        holder.HOLDER_DEADLINE_AT = previous_deadline

    processed_items = [
        {
            "chain": project.get("chain"),
            "address": project.get("address"),
        }
        for project in projects
    ]
    expected_count = len(expected_items)
    processed_count = len(processed_items)
    dropped_count = max(0, expected_count - processed_count)
    expected_identity_hash = stable_identity_hash(expected_items)
    processed_identity_hash = stable_identity_hash(processed_items)
    if (
        dropped_count
        or processed_count != expected_count
        or processed_identity_hash != expected_identity_hash
    ):
        issues.append(
            {
                "kind": "liquidity_identity_coverage_gap",
                "name": "watchlist",
                "detail": "eligible contract identity set incomplete",
            }
        )
    required_projects = [row for row in projects if row.get("required")]
    alert_count = sum(
        len(holder.retention_alert_events(project)) for project in projects
    )
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_at": holder.now_iso(),
        "config_path": str(CONFIG_PATH),
        "status": "healthy" if not issues else "unhealthy",
        "issue_count": len(issues),
        "issues": issues,
        "project_count": len(projects),
        "expected_count": expected_count,
        "processed_count": processed_count,
        "dropped_count": dropped_count,
        "expected_identity_hash": expected_identity_hash,
        "processed_identity_hash": processed_identity_hash,
        "required_count": len(required_projects),
        "complete_count": sum(
            project.get("operational_complete") is True
            for project in required_projects
        ),
        "alert_ready_count": sum(
            holder.liquidity_retention_alert_coverage_complete(project)
            for project in required_projects
        ),
        "alert_count": alert_count,
        "chain_tip_query_count": len(tip_by_chain),
        "budget_seconds": budget_seconds,
        "projects": projects,
        "_next_state": {
            "schema": STATE_SCHEMA,
            "tokens": next_tokens,
        },
    }


def render(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Alpha Verified Pool Liquidity Fast Lane",
        "",
        f"- generated_at: `{snapshot.get('generated_at', '')}`",
        f"- status: `{snapshot.get('status', '')}`",
        f"- projects: `{snapshot.get('project_count', 0)}`",
        f"- expected: `{snapshot.get('expected_count', 0)}`",
        f"- processed: `{snapshot.get('processed_count', 0)}`",
        f"- dropped: `{snapshot.get('dropped_count', 0)}`",
        f"- required: `{snapshot.get('required_count', 0)}`",
        f"- complete: `{snapshot.get('complete_count', 0)}`",
        f"- alert_ready: `{snapshot.get('alert_ready_count', 0)}`",
        f"- alerts: `{snapshot.get('alert_count', 0)}`",
        "",
    ]
    for issue in snapshot.get("issues", []):
        lines.append(
            f"- issue `{issue.get('kind')}` {issue.get('name')}: "
            f"{issue.get('detail')}"
        )
    return "\n".join(lines) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
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
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run_once() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    next_state = snapshot.pop("_next_state")
    snapshot["delivery_status"] = "pending"
    holder.atomic_write_json(LATEST_PATH, snapshot)
    atomic_write_text(REPORT_PATH, render(snapshot))
    delivered = holder.maybe_send_telegram(
        snapshot,
        seen_path=holder.SEEN_PATH,
        last_push_path=LAST_PUSH_PATH,
    )
    snapshot["delivery_status"] = "complete" if delivered else "failed"
    if not delivered:
        snapshot["issues"].append(
            {
                "kind": "telegram_delivery_failed",
                "name": "liquidity_alerts",
                "detail": "telegram delivery failed",
            }
        )
        snapshot["issue_count"] = len(snapshot["issues"])
        snapshot["status"] = "unhealthy"
    holder.atomic_write_json(LATEST_PATH, snapshot)
    atomic_write_text(REPORT_PATH, render(snapshot))
    if not delivered:
        print(
            "liquidity Telegram delivery unavailable; checkpoint retained",
            file=sys.stderr,
        )
        return 1
    holder.atomic_write_json(STATE_PATH, next_state)
    print(LATEST_PATH)
    print(
        "liquidity_projects="
        f"{snapshot['project_count']} required={snapshot['required_count']} "
        f"complete={snapshot['complete_count']} alerts={snapshot['alert_count']}"
    )
    return 0 if snapshot.get("status") == "healthy" else 1


def main() -> int:
    RUN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOCK_PATH.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            print("alpha liquidity retention skipped: previous run active")
            return 0
        try:
            return run_once()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
