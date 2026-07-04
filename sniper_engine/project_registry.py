from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path(os.environ.get("PROJECT_REGISTRY_PATH", ROOT / "output" / "project_registry" / "project_registry.json"))
SUMMARY_PATH = Path(os.environ.get("PROJECT_REGISTRY_SUMMARY_PATH", ROOT / "output" / "project_registry" / "project_registry.md"))
GENERIC_SYMBOLS = {"", "UNKNOWN", "LP", "POOL", "TOKEN", "V3", "V4", "BN", "BSC", "ALPHA"}
NON_PROJECT_CONTRACT_MARKERS = {"quote_token", "tx_related", "pool_hook", "hook", "operator"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def merge_signal(parsed: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = read_json(REGISTRY_PATH, {"generated_at": now_iso(), "projects": []})
    projects = registry.setdefault("projects", [])
    idx = find_project_index(projects, parsed)
    created = idx is None
    if created:
        project = new_project(parsed)
        projects.append(project)
        idx = len(projects) - 1
    project = projects[idx]

    before = fingerprint_project(project)
    merge_into_project(project, parsed, source or {})
    after = fingerprint_project(project)
    added = diff_fingerprints(before, after)
    project["updated_at"] = now_iso()
    project["last_priority"] = max_priority(project.get("last_priority", ""), parsed.get("priority", ""))
    registry["generated_at"] = now_iso()
    write_json(REGISTRY_PATH, registry)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(render_registry_markdown(registry), encoding="utf-8")

    if created:
        status = "new_project"
    elif added:
        status = "updated_project"
    else:
        status = "duplicate_signal"

    return {
        "status": status,
        "project_key": project.get("project_key"),
        "symbol": project.get("symbol"),
        "added": added,
        "known": known_counts(project),
        "registry_path": str(REGISTRY_PATH),
        "summary_path": str(SUMMARY_PATH),
    }


def new_project(parsed: dict[str, Any]) -> dict[str, Any]:
    symbol = str(parsed.get("symbol") or "UNKNOWN").upper()
    key = project_key(parsed)
    return {
        "project_key": key,
        "symbol": symbol,
        "aliases": alias_candidates(parsed, symbol),
        "titles": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "last_priority": parsed.get("priority", ""),
        "contracts": [],
        "addresses": [],
        "txs": [],
        "blocks": [],
        "times": [],
        "pool_ids": [],
        "pool_links": [],
        "urls": [],
        "prediction_urls": [],
        "prices": {},
        "facts": {},
        "chain_enrichment": [],
        "sources": [],
    }


def project_key(parsed: dict[str, Any]) -> str:
    contracts = sorted(address_key(row.get("address")) for row in project_contract_rows(parsed) if row.get("address"))
    if contracts:
        return "contract:" + contracts[0]
    pool_ids = sorted(str(item).lower() for item in parsed.get("pool_ids", []))
    if pool_ids:
        return "pool:" + pool_ids[0]
    symbol = str(parsed.get("symbol") or "UNKNOWN").upper()
    if symbol != "UNKNOWN":
        return "symbol:" + symbol
    digest = hashlib.sha256(json.dumps(parsed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return "unknown:" + digest


def find_project_index(projects: list[dict[str, Any]], parsed: dict[str, Any]) -> int | None:
    parsed_contracts = {address_key(row.get("address")) for row in project_contract_rows(parsed) if row.get("address")}
    parsed_pools = {str(item).lower() for item in parsed.get("pool_ids", [])}
    parsed_txs = {str(item).lower() for item in parsed.get("txs", [])}
    symbol = str(parsed.get("symbol") or "").upper()

    for idx, project in enumerate(projects):
        contracts = {address_key(row.get("address")) for row in project_contract_rows(project) if row.get("address")}
        if parsed_contracts and contracts and parsed_contracts & contracts:
            return idx
        pools = {str(item).lower() for item in project.get("pool_ids", [])}
        if parsed_pools and pools and parsed_pools & pools:
            return idx
        txs = {str(item).lower() for item in project.get("txs", [])}
        if parsed_txs and txs and parsed_txs & txs:
            return idx

    if symbol:
        for idx, project in enumerate(projects):
            if str(project.get("symbol") or "").upper() == symbol:
                return idx
            aliases = {str(item).upper() for item in project.get("aliases", [])}
            if symbol in aliases:
                return idx
    return None


def merge_into_project(project: dict[str, Any], parsed: dict[str, Any], source: dict[str, Any]) -> None:
    symbol = str(parsed.get("symbol") or "").upper()
    if symbol and symbol != "UNKNOWN":
        current_symbol = str(project.get("symbol") or "").upper()
        if current_symbol in GENERIC_SYMBOLS:
            project["symbol"] = symbol
        elif project.get("symbol") != symbol:
            project["aliases"] = merge_scalars(project.get("aliases", []), [symbol])
    project["aliases"] = merge_scalars(project.get("aliases", []), alias_candidates(parsed, project.get("symbol")))

    project["titles"] = merge_scalars(project.get("titles", []), [parsed.get("title")])
    project["addresses"] = merge_dicts(project.get("addresses", []), parsed.get("addresses", []), ["chain", "address", "label_hint"])
    project["contracts"] = merge_dicts(project.get("contracts", []), project_contract_rows({"contracts": parsed.get("watchlist_proposal", {}).get("contracts", [])}), ["chain", "address", "confidence"])
    project["txs"] = merge_scalars(project.get("txs", []), parsed.get("txs", []))
    project["blocks"] = merge_scalars(project.get("blocks", []), parsed.get("blocks", []))
    project["times"] = merge_scalars(project.get("times", []), parsed.get("times", []))
    project["pool_ids"] = merge_scalars(project.get("pool_ids", []), parsed.get("pool_ids", []))
    project["pool_links"] = merge_dicts(project.get("pool_links", []), parsed.get("pool_links", []), ["dex", "chain", "pool_id", "url"])
    project["urls"] = merge_scalars(project.get("urls", []), parsed.get("urls", []))
    project["prediction_urls"] = merge_scalars(project.get("prediction_urls", []), parsed.get("prediction_urls", []))
    project["prices"] = merge_map(project.get("prices", {}), parsed.get("prices", {}))
    project["facts"] = merge_facts(project.get("facts", {}), merged_project_facts(parsed))
    project["chain_enrichment"] = merge_dicts(
        project.get("chain_enrichment", []),
        parsed.get("chain_enrichment", []),
        ["chain", "tx_hash", "block", "tx_index", "pool_id", "price_summary"],
    )
    if source:
        source = dict(source)
        source["source_hash"] = signal_hash(parsed, source)
        project["sources"] = merge_dicts(project.get("sources", []), [source], ["source_hash"])
    project["project_key"] = canonical_project_key(project)


def merge_scalars(left: list[Any], right: list[Any]) -> list[Any]:
    out = list(left or [])
    seen = {scalar_key(item) for item in out if item not in (None, "")}
    for item in right or []:
        if item in (None, ""):
            continue
        key = scalar_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def merge_dicts(left: list[dict[str, Any]], right: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    out = list(left or [])
    seen = {dict_key(item, key_fields) for item in out}
    for item in right or []:
        if not isinstance(item, dict):
            continue
        key = dict_key(item, key_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def merge_map(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    out = dict(left or {})
    for key, value in (right or {}).items():
        if value in (None, ""):
            continue
        if key not in out:
            out[key] = value
        elif out[key] != value:
            out[key] = merge_scalars(out[key] if isinstance(out[key], list) else [out[key]], [value])
    return out


def merge_facts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    out = dict(left or {})
    for key, value in (right or {}).items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            out[key] = merge_dicts(out.get(key, []), value, sorted(value[0].keys()) if value and isinstance(value[0], dict) else ["value"]) if value and isinstance(value[0], dict) else merge_scalars(out.get(key, []), value)
        elif key not in out:
            out[key] = value
        elif out[key] != value:
            out[key] = merge_scalars(out[key] if isinstance(out[key], list) else [out[key]], [value])
    return out


def fingerprint_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "aliases": len(project.get("aliases", [])),
        "titles": len(project.get("titles", [])),
        "addresses": len(project.get("addresses", [])),
        "contracts": len(project.get("contracts", [])),
        "txs": len(project.get("txs", [])),
        "blocks": len(project.get("blocks", [])),
        "times": len(project.get("times", [])),
        "pool_ids": len(project.get("pool_ids", [])),
        "pool_links": len(project.get("pool_links", [])),
        "urls": len(project.get("urls", [])),
        "prediction_urls": len(project.get("prediction_urls", [])),
        "prices": map_size(project.get("prices", {})),
        "facts": map_size(project.get("facts", {})),
        "chain_enrichment": len(project.get("chain_enrichment", [])),
    }


def diff_fingerprints(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    added = []
    labels = {
        "aliases": "别名",
        "titles": "标题",
        "addresses": "地址",
        "contracts": "合约",
        "txs": "交易",
        "blocks": "区块",
        "times": "时间",
        "pool_ids": "PoolId",
        "pool_links": "池子链接",
        "urls": "链接",
        "prediction_urls": "预测市场",
        "prices": "价格锚点",
        "facts": "项目资料",
        "chain_enrichment": "链上还原",
    }
    for key, label in labels.items():
        if after.get(key, 0) > before.get(key, 0):
            added.append(label)
    return added


def known_counts(project: dict[str, Any]) -> dict[str, int]:
    return {
        "aliases": len(project.get("aliases", [])),
        "addresses": len(project.get("addresses", [])),
        "txs": len(project.get("txs", [])),
        "blocks": len(project.get("blocks", [])),
        "times": len(project.get("times", [])),
        "pool_ids": len(project.get("pool_ids", [])),
        "prediction_urls": len(project.get("prediction_urls", [])),
        "sources": len(project.get("sources", [])),
    }


def map_size(value: dict[str, Any]) -> int:
    total = 0
    for item in (value or {}).values():
        total += len(item) if isinstance(item, list) else 1
    return total


def render_registry_markdown(registry: dict[str, Any]) -> str:
    lines = ["# Project Registry", "", f"- generated_at: `{registry.get('generated_at')}`", f"- project_count: `{len(registry.get('projects', []))}`", ""]
    for project in registry.get("projects", []):
        lines.extend(
            [
                f"## {project.get('symbol') or 'UNKNOWN'}",
                "",
                f"- key: `{project.get('project_key')}`",
                f"- priority: `{project.get('last_priority', '')}`",
                f"- titles: {', '.join(project.get('titles', [])[:3])}",
                f"- aliases: {', '.join(project.get('aliases', [])[:8]) or '-'}",
                f"- contracts: `{len(project.get('contracts', []))}`",
                f"- txs: `{len(project.get('txs', []))}`",
                f"- blocks: `{len(project.get('blocks', []))}`",
                f"- times: {', '.join(str(item) for item in project.get('times', [])[:5]) or '-'}",
                f"- pool_ids: `{len(project.get('pool_ids', []))}`",
                f"- sources: `{len(project.get('sources', []))}`",
                "",
            ]
        )
    return "\n".join(lines)


def signal_hash(parsed: dict[str, Any], source: dict[str, Any]) -> str:
    payload = {
        "source": source,
        "symbol": parsed.get("symbol"),
        "title": parsed.get("title"),
        "txs": parsed.get("txs", []),
        "pool_ids": parsed.get("pool_ids", []),
        "urls": parsed.get("urls", []),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def address_key(value: Any) -> str:
    return str(value or "").lower()


def scalar_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


def dict_key(value: dict[str, Any], fields: list[str]) -> str:
    if len(fields) == 1 and fields[0] == "source_hash":
        return str(value.get("source_hash") or "").lower()
    parts = [str(value.get(field, "")).lower() for field in fields]
    return "|".join(parts)


def project_contract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in payload.get("contracts", []):
        if not isinstance(row, dict):
            continue
        if not is_project_contract_row(row):
            continue
        if row.get("address"):
            rows.append(row)
    proposal = payload.get("watchlist_proposal") or {}
    if isinstance(proposal, dict):
        for row in proposal.get("contracts", []):
            if isinstance(row, dict) and row.get("address") and is_project_contract_row(row):
                rows.append(row)
    for row in payload.get("addresses", []):
        if not isinstance(row, dict):
            continue
        if row.get("label_hint") != "token_contract":
            continue
        if row.get("address"):
            rows.append(row)
    return rows


def alias_candidates(parsed: dict[str, Any], primary_symbol: Any = "") -> list[str]:
    primary = str(primary_symbol or "").upper()
    candidates: list[str] = []
    candidates.extend(str(item) for item in parsed.get("symbols", []))
    token_alias = parsed.get("token_alias") or {}
    if isinstance(token_alias, dict):
        candidates.append(str(token_alias.get("display_symbol") or ""))
        candidates.append(str(token_alias.get("raw_symbol") or ""))
        candidates.extend(str(item) for item in token_alias.get("aliases", []))
    proposal = parsed.get("watchlist_proposal") or {}
    if isinstance(proposal, dict):
        candidates.extend(str(item) for item in proposal.get("aliases", []))
    out = []
    for item in candidates:
        symbol = str(item or "").upper()
        if not symbol or symbol in GENERIC_SYMBOLS or symbol == primary:
            continue
        out.append(symbol)
    return merge_scalars([], out)


def merged_project_facts(parsed: dict[str, Any]) -> dict[str, Any]:
    facts = dict(parsed.get("facts") or {})
    proposal = parsed.get("watchlist_proposal") or {}
    if isinstance(proposal, dict) and isinstance(proposal.get("facts"), dict):
        facts = merge_facts(facts, proposal.get("facts", {}))
    token_alias = parsed.get("token_alias") or {}
    if isinstance(token_alias, dict):
        if token_alias.get("project_name"):
            facts.setdefault("project_name", token_alias.get("project_name"))
        if token_alias.get("raw_symbol"):
            facts.setdefault("raw_symbol", token_alias.get("raw_symbol"))
        if token_alias.get("display_symbol"):
            facts.setdefault("display_symbol", token_alias.get("display_symbol"))
    return facts


def is_project_contract_row(row: dict[str, Any]) -> bool:
    label = str(row.get("label_hint") or "").lower()
    confidence = str(row.get("confidence") or "").lower()
    combined = f"{label} {confidence}"
    if any(marker in combined for marker in NON_PROJECT_CONTRACT_MARKERS):
        return False
    if label == "token_contract":
        return True
    if "token_contract" in confidence:
        return True
    return bool(row.get("address") and not label and not confidence)


def canonical_project_key(project: dict[str, Any]) -> str:
    contracts = sorted(address_key(row.get("address")) for row in project_contract_rows(project) if row.get("address"))
    if contracts:
        return "contract:" + contracts[0]
    pools = sorted(str(item).lower() for item in project.get("pool_ids", []))
    if pools:
        return "pool:" + pools[0]
    symbol = str(project.get("symbol") or "UNKNOWN").upper()
    if symbol != "UNKNOWN":
        return "symbol:" + symbol
    return str(project.get("project_key") or "unknown")


def max_priority(left: str, right: str) -> str:
    order = {"P0_DEEP_REVIEW": 4, "P1_MONITOR": 3, "P2_PAPER_TRADE": 2, "P3_BACKLOG": 1, "P4_CONTEXT": 0, "": 0}
    return left if order.get(left, 0) >= order.get(right, 0) else right
