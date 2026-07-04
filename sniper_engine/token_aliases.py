from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "config" / "token_aliases.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_aliases() -> list[dict[str, Any]]:
    data = read_json(ALIASES_PATH, {"tokens": []})
    return [row for row in data.get("tokens", []) if isinstance(row, dict)]


def apply_token_aliases(parsed: dict[str, Any]) -> dict[str, Any]:
    entry = find_alias_entry(parsed)
    if not entry:
        return parsed

    raw_symbol = str(entry.get("raw_symbol") or "").upper()
    display_symbol = str(entry.get("display_symbol") or raw_symbol).upper()
    project_name = str(entry.get("project_name") or "").strip()
    aliases = unique_symbols([display_symbol, raw_symbol] + [str(item) for item in entry.get("aliases", [])])

    parsed["token_alias"] = {
        "display_symbol": display_symbol,
        "raw_symbol": raw_symbol,
        "project_name": project_name,
        "aliases": aliases,
        "address": str(entry.get("address") or "").lower(),
        "chain": str(entry.get("chain") or "").lower(),
        "confidence": str(entry.get("confidence") or ""),
    }
    parsed["symbols"] = unique_symbols(aliases + [str(item) for item in parsed.get("symbols", [])])

    proposal = parsed.get("watchlist_proposal") or {}
    proposal["aliases"] = unique_symbols(list(proposal.get("aliases", [])) + aliases)
    facts = proposal.get("facts") if isinstance(proposal.get("facts"), dict) else {}
    if project_name:
        facts["project_name"] = project_name
    if raw_symbol:
        facts["raw_symbol"] = raw_symbol
    if display_symbol:
        facts["display_symbol"] = display_symbol
    proposal["facts"] = facts
    parsed["watchlist_proposal"] = proposal
    return parsed


def find_alias_entry(parsed: dict[str, Any]) -> dict[str, Any] | None:
    aliases = load_aliases()
    addresses = parsed_addresses(parsed)
    symbols = {str(parsed.get("symbol") or "").upper()}
    symbols.update(str(item).upper() for item in parsed.get("symbols", []))

    for entry in aliases:
        address = str(entry.get("address") or "").lower()
        if address and address in addresses:
            return entry

    for entry in aliases:
        known = set(alias_symbols(entry))
        if known & {item for item in symbols if item}:
            return entry
    return None


def parsed_addresses(parsed: dict[str, Any]) -> set[str]:
    addresses = {str(row.get("address") or "").lower() for row in parsed.get("addresses", []) if isinstance(row, dict)}
    for row in parsed.get("chain_enrichment") or []:
        if not isinstance(row, dict):
            continue
        for token_key in ("token0", "token1"):
            token = row.get(token_key) or {}
            if isinstance(token, dict) and token.get("address"):
                addresses.add(str(token.get("address")).lower())
    return {item for item in addresses if item}


def alias_symbols(entry: dict[str, Any]) -> list[str]:
    return unique_symbols(
        [
            str(entry.get("display_symbol") or ""),
            str(entry.get("raw_symbol") or ""),
        ]
        + [str(item) for item in entry.get("aliases", [])]
    )


def display_alias(parsed: dict[str, Any]) -> str:
    alias = parsed.get("token_alias") or {}
    display_symbol = str(alias.get("display_symbol") or "").upper()
    raw_symbol = str(alias.get("raw_symbol") or "").upper()
    project_name = str(alias.get("project_name") or "").strip()
    if not display_symbol:
        return ""
    symbol_text = display_symbol if not raw_symbol or raw_symbol == display_symbol else f"{display_symbol}/{raw_symbol}"
    return f"{symbol_text} · {project_name}" if project_name else symbol_text


def unique_symbols(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip().upper()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
