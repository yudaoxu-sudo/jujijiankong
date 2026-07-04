#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "current_prediction_markets.json"
OUT_DIR = ROOT / "output" / "prediction_markets"
LATEST_JSON = OUT_DIR / "latest_prediction_markets.json"
REPORT_MD = OUT_DIR / "prediction_markets.md"
POLY_GAMMA = "https://gamma-api.polymarket.com"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "sniper-prediction-watch/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    if "event" in parts:
        idx = parts.index("event")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    if "market" in parts:
        idx = parts.index("market")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    return parts[-1]


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_jsonish(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def fetch_polymarket(item: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = item.get("source_type", "")
    slug = item.get("slug") or extract_slug(item.get("url", ""))
    if not slug:
        return [base_row(item, "failed", "missing polymarket slug")]

    endpoint_kind = "markets" if "market" in source_type else "events"
    url = f"{POLY_GAMMA}/{endpoint_kind}/slug/{quote(slug)}"
    payload = http_json(url)
    markets = payload.get("markets") if isinstance(payload, dict) else None
    if not isinstance(markets, list):
        markets = [payload] if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for market in markets:
        rows.extend(rows_from_market(item, market, slug, url))
    if not rows:
        return [base_row(item, "failed", "no markets returned")]
    return rows


def rows_from_market(item: dict[str, Any], market: dict[str, Any], slug: str, api_url: str) -> list[dict[str, Any]]:
    outcomes = [str(value) for value in parse_jsonish(market.get("outcomes"))]
    prices = [str(value) for value in parse_jsonish(market.get("outcomePrices"))]
    price_by_outcome = {
        outcome: prices[idx]
        for idx, outcome in enumerate(outcomes)
        if idx < len(prices)
    }
    targets = item.get("targets") or [{"label": "default_yes", "outcome": "Yes"}]
    rows: list[dict[str, Any]] = []
    for target in targets:
        question_filter = str(target.get("question_contains", "")).lower()
        question = str(market.get("question") or market.get("title") or "")
        if question_filter and question_filter not in question.lower():
            continue
        outcome = target.get("outcome") or "Yes"
        probability = decimal_or_none(price_by_outcome.get(outcome))
        row = base_row(item, "ok" if probability is not None else "missing_price", "")
        row.update(
            {
                "source": "polymarket",
                "source_type": item.get("source_type", ""),
                "slug": slug,
                "api_url": api_url,
                "market_id": market.get("id", ""),
                "market_slug": market.get("slug", ""),
                "question": question,
                "outcome": outcome,
                "outcomes": outcomes,
                "outcome_prices": price_by_outcome,
                "probability": str(probability) if probability is not None else "",
                "target_label": target.get("label", ""),
                "target_fdv_usd": str(target.get("target_fdv_usd", "")),
                "implied_token_price": implied_price(target.get("target_fdv_usd"), item.get("total_supply")),
                "liquidity": str(market.get("liquidity", "")),
                "volume": str(market.get("volume", "")),
                "end_date": market.get("endDate") or market.get("end_date") or "",
            }
        )
        rows.append(row)
    return rows


def manual_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for target in item.get("targets", []):
        row = base_row(item, "ok", "")
        row.update(
            {
                "source": item.get("source", "manual"),
                "source_type": "manual",
                "question": item.get("question", ""),
                "outcome": target.get("outcome", ""),
                "probability": str(target.get("probability", "")),
                "target_label": target.get("label", ""),
                "target_fdv_usd": str(target.get("target_fdv_usd", "")),
                "implied_token_price": implied_price(target.get("target_fdv_usd"), item.get("total_supply")),
            }
        )
        rows.append(row)
    return rows or [base_row(item, "skipped", "manual item has no targets")]


def implied_price(fdv: Any, total_supply: Any) -> str:
    fdv_dec = decimal_or_none(fdv)
    supply_dec = decimal_or_none(total_supply)
    if fdv_dec is None or supply_dec in (None, Decimal(0)):
        return ""
    return str((fdv_dec / supply_dec).quantize(Decimal("0.00000001")))


def base_row(item: dict[str, Any], status: str, error: str) -> dict[str, Any]:
    return {
        "symbol": item.get("symbol", ""),
        "project": item.get("project", ""),
        "source": item.get("source", ""),
        "source_type": item.get("source_type", ""),
        "url": item.get("url", ""),
        "status": status,
        "error": error,
        "total_supply": str(item.get("total_supply", "")),
        "float_supply": str(item.get("float_supply", "")),
        "notes": item.get("notes", ""),
    }


def build_snapshot() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, {"items": []})
    rows: list[dict[str, Any]] = []
    for item in config.get("items", []):
        try:
            if item.get("source") == "polymarket":
                rows.extend(fetch_polymarket(item))
            else:
                rows.extend(manual_rows(item))
        except Exception as exc:
            rows.append(base_row(item, "failed", str(exc)))
    return {
        "generated_at": now_iso(),
        "schema_version": "prediction_markets.v1",
        "item_count": len(config.get("items", [])),
        "rows": rows,
    }


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Prediction Market Watch",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- item_count: `{snapshot['item_count']}`",
        f"- row_count: `{len(snapshot['rows'])}`",
        "",
    ]
    if not snapshot["rows"]:
        lines.append("- No prediction markets configured.")
        lines.append("")
        return "\n".join(lines)
    lines.extend(
        [
            "| Status | Symbol | Source | Target | Probability | Target FDV | Implied Price | Question |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in snapshot["rows"]:
        lines.append(
            f"| {clean(row.get('status'))} | `{clean(row.get('symbol'))}` | {clean(row.get('source'))} | "
            f"{clean(row.get('target_label')) or clean(row.get('outcome'))} | {clean(row.get('probability'))} | "
            f"{clean(row.get('target_fdv_usd'))} | {clean(row.get('implied_token_price'))} | "
            f"{clean(row.get('question'))[:120]} |"
        )
    lines.append("")
    return "\n".join(lines)


def clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    LATEST_JSON.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(snapshot), encoding="utf-8")
    print(LATEST_JSON)
    print(REPORT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
