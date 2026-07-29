#!/usr/bin/env python3
"""Backfill exact-anchor ElonKely market replays from public Binance Alpha klines.

This script is research-only. It does not import monitor code, send alerts, or
change trading decisions. A horizon is calculated only when every expected
closed 1-minute candle is present; missing candles are reported without
interpolation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


KLINES_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/klines"
TOKEN_LIST_URL = (
    "https://www.binance.com/bapi/defi/v1/public/"
    "wallet-direct/buw/wallet/cex/alpha/all/token/list"
)
EXCHANGE_INFO_URL = (
    "https://www.binance.com/bapi/defi/v1/public/alpha-trade/get-exchange-info"
)
DOCS_URL = "https://developers.binance.com/docs/alpha/market-data/rest-api/klines"
INTERVAL_MS = 60_000
HORIZONS = {"24h": 24 * 60, "72h": 72 * 60, "7d": 7 * 24 * 60}
ARCHIVE_SCHEMA = "binance_alpha_1m_series.v1"
ARCHIVE_FIELD_ORDER = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)
CASES = (
    {
        "root_signal_id": "ELON-2074859463027408945",
        "symbol": "PARTI",
        "alpha_id": "ALPHA_127",
        "pair": "ALPHA_127USDT",
        "signal_time_utc": "2026-07-08T14:13:39Z",
    },
    {
        "root_signal_id": "ELON-2075164060409270485",
        "symbol": "EVAA",
        "alpha_id": "ALPHA_409",
        "pair": "ALPHA_409USDT",
        "signal_time_utc": "2026-07-09T10:24:01Z",
    },
)


class PublicMarketDataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamp must include an offset")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def first_strict_post_signal_minute(signal_time: datetime) -> datetime:
    minute = signal_time.replace(second=0, microsecond=0)
    return minute + timedelta(minutes=1)


def http_json(url: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    full_url = url
    if params:
        full_url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("public endpoint returned a non-object response")
    return payload


def successful_data(payload: dict[str, Any]) -> Any:
    code = str(payload.get("code") or "")
    if code != "000000":
        raise PublicMarketDataError(code or "unknown", str(payload.get("message") or "unknown error"))
    return payload.get("data")


def public_registry_state(alpha_id: str, pair: str, timeout: int) -> dict[str, Any]:
    token_rows = successful_data(http_json(TOKEN_LIST_URL, timeout=timeout)) or []
    exchange_data = successful_data(http_json(EXCHANGE_INFO_URL, timeout=timeout)) or {}
    exchange_rows = exchange_data.get("symbols") if isinstance(exchange_data, dict) else []
    token = next(
        (row for row in token_rows if isinstance(row, dict) and row.get("alphaId") == alpha_id),
        None,
    )
    exchange_symbol = next(
        (row for row in exchange_rows or [] if isinstance(row, dict) and row.get("symbol") == pair),
        None,
    )
    return {
        "token_list_present": token is not None,
        "token_list_symbol": token.get("symbol") if token else None,
        "exchange_info_present": exchange_symbol is not None,
        "exchange_info_status": exchange_symbol.get("status") if exchange_symbol else None,
    }


def fetch_exact_klines(
    pair: str,
    start_ms: int,
    end_exclusive_ms: int,
    *,
    timeout: int,
) -> tuple[list[list[Any]], dict[str, Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms
    request_count = 0
    while cursor < end_exclusive_ms:
        remaining = (end_exclusive_ms - cursor) // INTERVAL_MS
        page_limit = min(1500, max(1, remaining))
        payload = http_json(
            KLINES_URL,
            {
                "symbol": pair,
                "interval": "1m",
                "startTime": cursor,
                "endTime": end_exclusive_ms - 1,
                "limit": page_limit,
            },
            timeout=timeout,
        )
        request_count += 1
        page = successful_data(payload) or []
        if not page:
            break
        page_open_times: list[int] = []
        for row in page:
            if not isinstance(row, list) or len(row) < 12:
                raise ValueError("invalid Binance Alpha kline row")
            open_time = int(row[0])
            if start_ms <= open_time < end_exclusive_ms:
                rows.append(row)
            page_open_times.append(open_time)
        newest = max(page_open_times)
        next_cursor = newest + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Binance Alpha kline cursor did not advance")
        cursor = next_cursor
        if len(page) < page_limit:
            break
    rows.sort(
        key=lambda row: (
            int(row[0]),
            json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        )
    )
    return rows, {"request_count": request_count, "last_cursor_ms": cursor}


def missing_ranges(
    present_open_times: set[int],
    start_ms: int,
    end_exclusive_ms: int,
) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    range_start: int | None = None
    cursor = start_ms
    while cursor < end_exclusive_ms:
        if cursor not in present_open_times and range_start is None:
            range_start = cursor
        if cursor in present_open_times and range_start is not None:
            ranges.append(format_missing_range(range_start, cursor))
            range_start = None
        cursor += INTERVAL_MS
    if range_start is not None:
        ranges.append(format_missing_range(range_start, end_exclusive_ms))
    return ranges


def format_missing_range(start_ms: int, end_exclusive_ms: int) -> dict[str, Any]:
    return {
        "start_utc": iso_utc(datetime.fromtimestamp(start_ms / 1000, timezone.utc)),
        "end_exclusive_utc": iso_utc(
            datetime.fromtimestamp(end_exclusive_ms / 1000, timezone.utc)
        ),
        "minute_count": (end_exclusive_ms - start_ms) // INTERVAL_MS,
    }


def canonical_series_sha256(rows: list[list[Any]]) -> str:
    canonical_rows = sorted(
        rows,
        key=lambda row: (
            int(row[0]),
            json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    encoded = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_series_archive(
    case: dict[str, str],
    rows: list[list[Any]],
    *,
    fetched_at_utc: str,
) -> dict[str, Any]:
    signal_time = parse_utc(case["signal_time_utc"])
    anchor = first_strict_post_signal_minute(signal_time)
    start_ms = int(anchor.timestamp() * 1000)
    end_exclusive_ms = start_ms + HORIZONS["7d"] * INTERVAL_MS
    canonical_rows = sorted(
        rows,
        key=lambda row: (
            int(row[0]),
            json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return {
        "schema": ARCHIVE_SCHEMA,
        "venue": "Binance Alpha",
        "pair": case["pair"],
        "interval": "1m",
        "start_time_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "fetched_at_utc": fetched_at_utc,
        "field_order": list(ARCHIVE_FIELD_ORDER),
        "row_count": len(canonical_rows),
        "series_sha256": canonical_series_sha256(canonical_rows),
        "rows": canonical_rows,
    }


def write_series_archive(path: Path, archive: dict[str, Any]) -> None:
    """Write Git-auditable JSON with one compact kline per line."""
    rows = archive.get("rows")
    if not isinstance(rows, list):
        raise ValueError("series archive rows must be a list")
    header = {key: value for key, value in archive.items() if key != "rows"}
    lines = ["{"]
    for key, value in header.items():
        lines.append(
            "  "
            + json.dumps(key, ensure_ascii=False)
            + ": "
            + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            + ","
        )
    lines.append('  "rows": [')
    for index, row in enumerate(rows):
        suffix = "," if index + 1 < len(rows) else ""
        lines.append(
            "    "
            + json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            + suffix
        )
    lines.extend(["  ]", "}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_series_archive(path: Path) -> dict[str, Any]:
    archive = json.loads(path.read_text(encoding="utf-8"))
    if archive.get("schema") != ARCHIVE_SCHEMA:
        raise ValueError("unexpected series archive schema")
    if archive.get("field_order") != list(ARCHIVE_FIELD_ORDER):
        raise ValueError("unexpected series archive field order")
    rows = archive.get("rows")
    if not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != len(ARCHIVE_FIELD_ORDER)
        for row in rows
    ):
        raise ValueError("invalid series archive rows")
    if archive.get("row_count") != len(rows):
        raise ValueError("series archive row count mismatch")
    if archive.get("series_sha256") != canonical_series_sha256(rows):
        raise ValueError("series archive sha256 mismatch")
    return archive


def pct(value: Decimal, base: Decimal) -> str:
    result = ((value / base) - Decimal(1)) * Decimal(100)
    return format(result.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP), "f")


def replay_horizon(
    rows_by_open_time: dict[int, list[Any]],
    anchor_ms: int,
    minute_count: int,
    *,
    duplicate_open_times: set[int] | None = None,
    conflicting_open_times: set[int] | None = None,
) -> dict[str, Any]:
    end_exclusive_ms = anchor_ms + minute_count * INTERVAL_MS
    expected = set(range(anchor_ms, end_exclusive_ms, INTERVAL_MS))
    present = expected & set(rows_by_open_time)
    missing = missing_ranges(present, anchor_ms, end_exclusive_ms)
    duplicate_open_times = duplicate_open_times or set()
    conflicting_open_times = conflicting_open_times or set()
    duplicate_count = len(expected & duplicate_open_times)
    conflict_count = len(expected & conflicting_open_times)
    coverage = {
        "expected_candle_count": minute_count,
        "observed_candle_count": len(present),
        "missing_candle_count": minute_count - len(present),
        "duplicate_open_time_count": duplicate_count,
        "conflicting_open_time_count": conflict_count,
        "missing_ranges": missing,
    }
    if missing or duplicate_count or conflict_count:
        return {"status": "blocked_incomplete_series", "coverage": coverage, "metrics": None}

    rows = [rows_by_open_time[open_time] for open_time in sorted(expected)]
    base_open = Decimal(str(rows[0][1]))
    high_row = max(rows, key=lambda row: Decimal(str(row[2])))
    low_row = min(rows, key=lambda row: Decimal(str(row[3])))
    end_row = rows[-1]
    metrics = {
        "base_open": str(rows[0][1]),
        "mfe_pct": pct(Decimal(str(high_row[2])), base_open),
        "mfe_at_utc": iso_utc(
            datetime.fromtimestamp(int(high_row[0]) / 1000, timezone.utc)
        ),
        "mae_pct": pct(Decimal(str(low_row[3])), base_open),
        "mae_at_utc": iso_utc(
            datetime.fromtimestamp(int(low_row[0]) / 1000, timezone.utc)
        ),
        "end_close": str(end_row[4]),
        "end_return_pct": pct(Decimal(str(end_row[4])), base_open),
        "end_candle_open_utc": iso_utc(
            datetime.fromtimestamp(int(end_row[0]) / 1000, timezone.utc)
        ),
        "end_exclusive_utc": iso_utc(
            datetime.fromtimestamp(end_exclusive_ms / 1000, timezone.utc)
        ),
        "quote_volume": format(
            sum((Decimal(str(row[7])) for row in rows), Decimal(0)),
            "f",
        ),
    }
    return {"status": "complete", "coverage": coverage, "metrics": metrics}


def build_case_result(
    case: dict[str, str],
    rows: list[list[Any]],
    *,
    registry_state: dict[str, Any],
    fetch_state: dict[str, Any],
    api_error: PublicMarketDataError | None = None,
    horizons: dict[str, int] = HORIZONS,
    queried_at_utc: str | None = None,
) -> dict[str, Any]:
    signal_time = parse_utc(case["signal_time_utc"])
    anchor = first_strict_post_signal_minute(signal_time)
    anchor_ms = int(anchor.timestamp() * 1000)
    maximum_minutes = max(horizons.values())
    end_exclusive_ms = anchor_ms + maximum_minutes * INTERVAL_MS
    in_range_rows = [
        row for row in rows if anchor_ms <= int(row[0]) < end_exclusive_ms
    ]
    grouped_rows: dict[int, list[list[Any]]] = defaultdict(list)
    for row in in_range_rows:
        grouped_rows[int(row[0])].append(row)
    duplicate_open_times = {
        open_time for open_time, grouped in grouped_rows.items() if len(grouped) > 1
    }
    conflicting_open_times = {
        open_time
        for open_time, grouped in grouped_rows.items()
        if len(
            {
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in grouped
            }
        )
        > 1
    }
    rows_by_open_time = {
        open_time: grouped[0]
        for open_time, grouped in grouped_rows.items()
        if len(grouped) == 1
        and int(grouped[0][6]) == open_time + INTERVAL_MS - 1
    }
    case_horizons = {
        label: replay_horizon(
            rows_by_open_time,
            anchor_ms,
            minutes,
            duplicate_open_times=duplicate_open_times,
            conflicting_open_times=conflicting_open_times,
        )
        for label, minutes in horizons.items()
    }
    present = set(rows_by_open_time)
    missing = missing_ranges(present, anchor_ms, end_exclusive_ms)
    complete = not missing and not duplicate_open_times and all(
        row["status"] == "complete" for row in case_horizons.values()
    )
    result = {
        **case,
        "venue": "Binance Alpha",
        "quote_asset": "USDT",
        "interval": "1m",
        "anchor_time_utc": iso_utc(anchor),
        "requested_end_exclusive_utc": iso_utc(
            datetime.fromtimestamp(end_exclusive_ms / 1000, timezone.utc)
        ),
        "status": "complete" if complete else "blocked_incomplete_series",
        "query": {
            "queried_at_utc": queried_at_utc,
            "symbol": case["pair"],
            "interval": "1m",
            "start_time_ms": anchor_ms,
            "end_time_ms": end_exclusive_ms - 1,
            "maximum_page_limit": 1500,
            "pagination": "forward_by_last_open_time_plus_60000ms",
        },
        "registry_state": registry_state,
        "api_result": {
            "code": api_error.code if api_error else "000000",
            "message": api_error.message if api_error else "",
        },
        "fetch_state": fetch_state,
        "coverage": {
            "expected_candle_count": maximum_minutes,
            "source_row_count": len(rows),
            "observed_candle_count": len(present),
            "missing_candle_count": maximum_minutes - len(present),
            "duplicate_open_time_count": len(duplicate_open_times),
            "conflicting_open_time_count": len(conflicting_open_times),
            "invalid_close_time_count": sum(
                int(row[6]) != int(row[0]) + INTERVAL_MS - 1
                for row in in_range_rows
            ),
            "missing_ranges": missing,
        },
        "series_sha256": canonical_series_sha256(rows) if rows else None,
        "horizons": case_horizons,
    }
    return result


def archived_case_matches_summary(
    summary_case: dict[str, Any],
    archive: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    rows = archive["rows"]
    expected_start_ms = summary_case.get("query", {}).get("start_time_ms")
    expected_end_exclusive_ms = (
        summary_case.get("query", {}).get("end_time_ms", -1) + 1
    )
    if archive.get("pair") != summary_case.get("pair"):
        raise ValueError("series archive pair mismatch")
    if archive.get("interval") != summary_case.get("interval"):
        raise ValueError("series archive interval mismatch")
    if archive.get("start_time_ms") != expected_start_ms:
        raise ValueError("series archive start mismatch")
    if archive.get("end_exclusive_ms") != expected_end_exclusive_ms:
        raise ValueError("series archive end mismatch")
    rebuilt = build_case_result(
        {
            key: summary_case[key]
            for key in (
                "root_signal_id",
                "symbol",
                "alpha_id",
                "pair",
                "signal_time_utc",
            )
        },
        rows,
        registry_state=summary_case.get("registry_state", {}),
        fetch_state=summary_case.get("fetch_state", {}),
        queried_at_utc=summary_case.get("query", {}).get("queried_at_utc"),
    )
    keys = (
        "anchor_time_utc",
        "requested_end_exclusive_utc",
        "status",
        "coverage",
        "series_sha256",
        "horizons",
    )
    return all(rebuilt.get(key) == summary_case.get(key) for key in keys), rebuilt


def run_live(
    timeout: int,
    *,
    archive_output: Path | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in CASES:
        signal = parse_utc(case["signal_time_utc"])
        anchor = first_strict_post_signal_minute(signal)
        start_ms = int(anchor.timestamp() * 1000)
        end_ms = start_ms + HORIZONS["7d"] * INTERVAL_MS
        registry = public_registry_state(case["alpha_id"], case["pair"], timeout)
        rows: list[list[Any]] = []
        fetch_state: dict[str, Any] = {"request_count": 0, "last_cursor_ms": start_ms}
        api_error: PublicMarketDataError | None = None
        try:
            rows, fetch_state = fetch_exact_klines(
                case["pair"],
                start_ms,
                end_ms,
                timeout=timeout,
            )
        except PublicMarketDataError as exc:
            api_error = exc
            fetch_state = {"request_count": 1, "last_cursor_ms": start_ms}
        result = build_case_result(
            case,
            rows,
            registry_state=registry,
            fetch_state=fetch_state,
            api_error=api_error,
            queried_at_utc=iso_utc(
                datetime.now(timezone.utc).replace(microsecond=0)
            ),
        )
        if archive_output is not None and case["symbol"] == "EVAA" and result["status"] == "complete":
            fetched_at_utc = result["query"]["queried_at_utc"]
            archive = build_series_archive(
                case,
                rows,
                fetched_at_utc=fetched_at_utc,
            )
            write_series_archive(archive_output, archive)
            result["series_archive_ref"] = str(archive_output)
        results.append(result)

    return {
        "schema": "exact_anchor_market_replay.v1",
        "generated_at_utc": iso_utc(datetime.now(timezone.utc).replace(microsecond=0)),
        "purpose": "research_only_outcome_ledger_backfill",
        "runtime_effect": "none",
        "alert_effect": "none",
        "trade_action_effect": "none",
        "provenance": {
            "venue": "Binance Alpha",
            "official_docs_url": DOCS_URL,
            "authentication": "none",
            "interval": "1m",
        },
        "methodology": {
            "anchor_rule": (
                "First 1-minute candle whose open time is strictly after the "
                "signal timestamp; its open price is the replay base."
            ),
            "window_rule": (
                "Each horizon is [anchor, anchor+horizon); MFE uses candle highs, "
                "MAE uses candle lows, and end return uses the final candle close."
            ),
            "closed_candles_only": True,
            "interpolation": "forbidden",
            "completion_rule": (
                "A horizon is complete only when every expected 1-minute candle "
                "is present exactly once by open time."
            ),
        },
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-output", type=Path)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    payload = run_live(args.timeout, archive_output=args.archive_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
