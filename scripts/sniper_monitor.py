#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
import sys
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.rpc import rpc_call


getcontext().prec = 80

CONFIG_PATH = ROOT / "config" / "monitored_wallets.json"
OUT_DIR = ROOT / "output" / "monitoring"
LATEST_SNAPSHOT = OUT_DIR / "latest_snapshot.json"
DEFAULT_LOOKBACK_BLOCKS = 5_000
DEFAULT_FINALITY_BLOCKS = 20
DEFAULT_MAX_TRANSFER_PAGES = 8
DEFAULT_MAX_TRANSFER_ROWS = 8_000
DEFAULT_MIN_ALERT_USD = "10000"
TELEGRAM_LIMIT = 3900
TELEGRAM_SEEN_PATH = OUT_DIR / "telegram_seen_alerts.json"
TELEGRAM_LAST_SENT_PATH = OUT_DIR / "telegram_last_sent_at.txt"
QUOTE_TOKENS = {
    "0x55d398326f99059ff775485246999027b3197955": "USDT",
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": "WBNB",
    "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
}


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def decimal_amount(raw: int, decimals: int = 18) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def fmt_dec(value: Decimal, places: int = 6) -> str:
    quant = Decimal(10) ** -places
    return f"{value.quantize(quant):f}"


def encode_balance_of(addr: str) -> str:
    return "0x70a08231" + "0" * 24 + norm(addr)[2:]


def current_balance(chain: str, token_contract: str, addr: str) -> Decimal:
    result = rpc_call(chain, "eth_call", [{"to": token_contract, "data": encode_balance_of(addr)}, "latest"])
    return decimal_amount(int(result, 16))


def latest_block(chain: str) -> int:
    return int(rpc_call(chain, "eth_blockNumber", []), 16)


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    disabled = disabled_projects()
    if not disabled:
        return config
    wallets = []
    for wallet in config.get("wallets", []):
        keys = {
            str(wallet.get("project", "")).strip().upper(),
            str(wallet.get("symbol", "")).strip().upper(),
        }
        if keys & disabled:
            continue
        wallets.append(wallet)
    config["wallets"] = wallets
    config["disabled_projects"] = sorted(disabled)
    return config


def disabled_projects() -> set[str]:
    raw = os.environ.get("MONITOR_DISABLED_PROJECTS", "")
    return {item.strip().upper() for item in raw.replace(";", ",").split(",") if item.strip()}


def load_previous() -> dict[tuple[str, str, str], Decimal]:
    if not LATEST_SNAPSHOT.exists():
        return {}
    try:
        payload = json.loads(LATEST_SNAPSHOT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[tuple[str, str, str], Decimal] = {}
    for row in payload.get("wallets", []):
        key = (row.get("chain", ""), norm(row.get("token_contract")), norm(row.get("address")))
        try:
            out[key] = Decimal(str(row.get("token_balance", "0")))
        except Exception:
            continue
    return out


def get_asset_transfers(chain: str, token_contract: str, from_block: int, to_block: int) -> list[dict[str, Any]]:
    transfers: list[dict[str, Any]] = []
    page_key = ""
    max_pages = int(os.environ.get("MONITOR_MAX_TRANSFER_PAGES", str(DEFAULT_MAX_TRANSFER_PAGES)))
    max_rows = int(os.environ.get("MONITOR_MAX_TRANSFER_ROWS", str(DEFAULT_MAX_TRANSFER_ROWS)))
    page_count = 0
    while True:
        page_count += 1
        query: dict[str, Any] = {
            "category": ["20"],
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "contractAddresses": [token_contract],
            "order": "asc",
            "maxCount": "0x3e8",
        }
        if page_key:
            query["pageKey"] = page_key
        result = rpc_call(chain, "nr_getAssetTransfers", [query])
        if isinstance(result, dict):
            transfers.extend(result.get("transfers", []))
            page_key = result.get("pageKey") or result.get("PageKey") or ""
        else:
            page_key = ""
        if not page_key or page_count >= max_pages or len(transfers) >= max_rows:
            break
    return transfers


@dataclass
class WatchGroup:
    chain: str
    token_contract: str
    wallets: list[dict[str, Any]]


def group_wallets(wallets: list[dict[str, Any]]) -> list[WatchGroup]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for wallet in wallets:
        key = (wallet.get("chain", "bsc"), norm(wallet.get("token_contract")))
        groups.setdefault(key, []).append(wallet)
    return [WatchGroup(chain=key[0], token_contract=key[1], wallets=value) for key, value in sorted(groups.items())]


def transfer_value(row: dict[str, Any]) -> Decimal:
    value = row.get("value") or "0x0"
    return decimal_amount(int(value, 16))


def block_num(row: dict[str, Any]) -> int:
    raw = row.get("blockNum") or "0x0"
    return int(raw, 16)


def build_snapshot(lookback_blocks: int) -> dict[str, Any]:
    config = load_config()
    previous = load_previous()
    finality_blocks = int(os.environ.get("MONITOR_FINALITY_BLOCKS", str(DEFAULT_FINALITY_BLOCKS)))
    all_rows: list[dict[str, Any]] = []
    all_alerts: list[dict[str, Any]] = []
    groups_meta: list[dict[str, Any]] = []
    wallets = config.get("wallets", [])

    if not wallets:
        return {
            "generated_at": now_iso(),
            "schema_version": "sniper_monitor_snapshot.v1",
            "lookback_blocks": lookback_blocks,
            "groups": [],
            "wallets": [],
            "alerts": [],
            "disabled_projects": config.get("disabled_projects", []),
        }

    for group in group_wallets(wallets):
        raw_tip = latest_block(group.chain)
        tip = max(0, raw_tip - finality_blocks)
        from_block = max(0, tip - lookback_blocks)
        quote_symbol = QUOTE_TOKENS.get(norm(group.token_contract), "")
        quote_scan_blocked = bool(quote_symbol and os.environ.get("MONITOR_ALLOW_QUOTE_TOKEN_TRANSFER_SCAN") != "1")
        transfers = [] if quote_scan_blocked else get_asset_transfers(group.chain, group.token_contract, from_block, tip)
        watched = {norm(wallet.get("address")) for wallet in group.wallets}
        relevant = [
            row for row in transfers
            if norm(row.get("from")) in watched or norm(row.get("to")) in watched
        ]
        groups_meta.append(
            {
                "chain": group.chain,
                "token_contract": group.token_contract,
                "raw_latest_block": raw_tip,
                "latest_block": tip,
                "finality_blocks": finality_blocks,
                "from_block": from_block,
                "transfer_rows": len(transfers),
                "relevant_rows": len(relevant),
                "quote_scan_blocked": quote_scan_blocked,
                "quote_symbol": quote_symbol,
            }
        )

        by_addr: dict[str, dict[str, Any]] = {}
        for wallet in group.wallets:
            addr = norm(wallet.get("address"))
            by_addr[addr] = {
                "incoming_amount": Decimal(0),
                "outgoing_amount": Decimal(0),
                "incoming_count": 0,
                "outgoing_count": 0,
                "last_transfer_block": 0,
                "last_transfer_hash": "",
                "last_transfer_direction": "",
                "last_counterparty": "",
            }

        for transfer in relevant:
            amount = transfer_value(transfer)
            tx_block = block_num(transfer)
            tx_hash = transfer.get("hash", "")
            from_addr = norm(transfer.get("from"))
            to_addr = norm(transfer.get("to"))
            if from_addr in by_addr:
                item = by_addr[from_addr]
                item["outgoing_amount"] += amount
                item["outgoing_count"] += 1
                if tx_block >= item["last_transfer_block"]:
                    item["last_transfer_block"] = tx_block
                    item["last_transfer_hash"] = tx_hash
                    item["last_transfer_direction"] = "out"
                    item["last_counterparty"] = to_addr
            if to_addr in by_addr:
                item = by_addr[to_addr]
                item["incoming_amount"] += amount
                item["incoming_count"] += 1
                if tx_block >= item["last_transfer_block"]:
                    item["last_transfer_block"] = tx_block
                    item["last_transfer_hash"] = tx_hash
                    item["last_transfer_direction"] = "in"
                    item["last_counterparty"] = from_addr

        for wallet in group.wallets:
            addr = norm(wallet.get("address"))
            key = (group.chain, group.token_contract, addr)
            balance = current_balance(group.chain, group.token_contract, addr)
            previous_balance = previous.get(key)
            balance_delta = None if previous_balance is None else balance - previous_balance
            activity = by_addr[addr]
            row = {
                "project": wallet.get("project", ""),
                "symbol": wallet.get("symbol", ""),
                "chain": group.chain,
                "token_contract": group.token_contract,
                "address": addr,
                "label": wallet.get("label", ""),
                "role": wallet.get("role", ""),
                "monitor_level": wallet.get("monitor_level", ""),
                "monitor_score": wallet.get("monitor_score", 0),
                "token_balance": str(balance),
                "previous_token_balance": "" if previous_balance is None else str(previous_balance),
                "balance_delta": "" if balance_delta is None else str(balance_delta),
                "incoming_amount": str(activity["incoming_amount"]),
                "outgoing_amount": str(activity["outgoing_amount"]),
                "incoming_count": activity["incoming_count"],
                "outgoing_count": activity["outgoing_count"],
                "last_transfer_block": activity["last_transfer_block"],
                "last_transfer_hash": activity["last_transfer_hash"],
                "last_transfer_direction": activity["last_transfer_direction"],
                "last_counterparty": activity["last_counterparty"],
                "watch_rules": wallet.get("watch_rules", []),
                "sources": wallet.get("sources", []),
                "estimated_usd": estimated_usd(wallet, activity["outgoing_amount"], activity["incoming_amount"], balance_delta),
                "alert_level": alert_level(wallet, activity["outgoing_amount"], activity["incoming_amount"], balance_delta),
            }
            all_rows.append(row)
            if row["alert_level"]:
                all_alerts.append(row)

    return {
        "generated_at": now_iso(),
        "schema_version": "sniper_monitor_snapshot.v1",
        "lookback_blocks": lookback_blocks,
        "groups": groups_meta,
        "wallets": all_rows,
        "alerts": all_alerts,
    }


def alert_level(wallet: dict[str, Any], outgoing: Decimal, incoming: Decimal, delta: Decimal | None) -> str:
    amount = max(outgoing, incoming, abs(delta or Decimal(0)))
    if amount <= 0:
        return ""
    usd = estimated_usd(wallet, outgoing, incoming, delta)
    if usd is not None and usd < Decimal(os.environ.get("MONITOR_MIN_ALERT_USD", DEFAULT_MIN_ALERT_USD)) and not is_high_signal_wallet(wallet):
        return ""
    if outgoing > 0:
        return "CRITICAL"
    if delta is not None and delta < 0:
        return "CRITICAL"
    if incoming > 0:
        return "INFO"
    if delta is not None and delta > 0:
        return "INFO"
    return ""


def estimated_usd(wallet: dict[str, Any], outgoing: Decimal, incoming: Decimal, delta: Decimal | None) -> str | None:
    raw_price = wallet.get("reference_price_usd") or wallet.get("token_price_usd") or wallet.get("estimated_price_usd")
    if raw_price in (None, ""):
        return None
    try:
        price = Decimal(str(raw_price))
    except Exception:
        return None
    amount = max(outgoing, incoming, abs(delta or Decimal(0)))
    return str((amount * price).quantize(Decimal("0.01")))


def is_high_signal_wallet(wallet: dict[str, Any]) -> bool:
    level = str(wallet.get("monitor_level", "")).upper()
    score = int(wallet.get("monitor_score") or 0)
    text = " ".join(
        str(wallet.get(key, ""))
        for key in ("label", "role", "monitor_role_enum", "monitor_reason")
    )
    keywords = ("分发", "空投", "Boost", "Booster", "Alpha", "MM", "做市", "庄家", "项目", "池子", "桥", "bridge", "cex", "交易所")
    return level == "CRITICAL" or score >= 8 or any(word.lower() in text.lower() for word in keywords)


def write_outputs(snapshot: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_name = "snapshot_" + snapshot["generated_at"].replace(":", "").replace("+", "Z") + ".json"
    snapshot_path = OUT_DIR / snapshot_name
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    LATEST_SNAPSHOT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = OUT_DIR / "wallet_snapshot.csv"
    fields = [
        "project",
        "symbol",
        "chain",
        "address",
        "label",
        "role",
        "monitor_level",
        "monitor_score",
        "token_balance",
        "previous_token_balance",
        "balance_delta",
        "incoming_amount",
        "outgoing_amount",
        "incoming_count",
        "outgoing_count",
        "last_transfer_block",
        "last_transfer_hash",
        "last_transfer_direction",
        "last_counterparty",
        "estimated_usd",
        "alert_level",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in snapshot["wallets"]:
            writer.writerow({key: row.get(key, "") for key in fields})

    (OUT_DIR / "alerts.md").write_text(render_alerts(snapshot), encoding="utf-8")
    digest = render_digest(snapshot)
    digest_path = OUT_DIR / "telegram_payload.txt"
    digest_path.write_text(digest, encoding="utf-8")
    telegram_status = maybe_send_telegram(digest, telegram_alert_keys(snapshot))
    if telegram_status:
        (OUT_DIR / "telegram_status.json").write_text(
            json.dumps(telegram_status, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(LATEST_SNAPSHOT)
    print(csv_path)
    print(OUT_DIR / "alerts.md")
    print(digest_path)


def render_alerts(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Sniper Monitor Alerts",
        "",
        f"- generated_at: `{snapshot['generated_at']}`",
        f"- lookback_blocks: `{snapshot['lookback_blocks']}`",
        f"- wallet_count: `{len(snapshot['wallets'])}`",
        f"- alert_count: `{len(snapshot['alerts'])}`",
        "",
        "## Groups",
        "",
    ]
    for group in snapshot["groups"]:
        lines.append(
            f"- `{group['chain']}` `{group['token_contract']}` blocks `{group['from_block']}` -> `{group['latest_block']}`: "
            f"{group['relevant_rows']}/{group['transfer_rows']} relevant transfers"
        )
    lines.extend(["", "## Alerts", ""])
    if not snapshot["alerts"]:
        lines.append("- No watched-wallet token movement in this lookback window.")
    else:
        lines.append("| Alert | Level | Address | Label | In | Out | Delta | Last tx |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | --- |")
        for row in snapshot["alerts"]:
            delta = row.get("balance_delta") or ""
            last_tx = row.get("last_transfer_hash") or ""
            if last_tx:
                last_tx = f"`{last_tx}`"
            lines.append(
                f"| {row.get('alert_level', '')} | {row.get('monitor_level', '')} | `{row.get('address', '')}` | "
                f"{clean(row.get('label', ''))} | {fmt_dec(Decimal(str(row.get('incoming_amount', '0'))), 4)} | "
                f"{fmt_dec(Decimal(str(row.get('outgoing_amount', '0'))), 4)} | {clean(delta)} | {last_tx} |"
            )
    lines.extend(["", "## Top Balances", ""])
    top = sorted(snapshot["wallets"], key=lambda row: Decimal(str(row.get("token_balance", "0"))), reverse=True)[:12]
    lines.append("| Balance | Address | Label | Role |")
    lines.append("| ---: | --- | --- | --- |")
    for row in top:
        lines.append(
            f"| {fmt_dec(Decimal(str(row.get('token_balance', '0'))), 4)} | `{row.get('address', '')}` | "
            f"{clean(row.get('label', ''))} | {clean(row.get('role', ''))} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_digest(snapshot: dict[str, Any]) -> str:
    summary = analyze_snapshot(snapshot)
    lines = [
        f"链上监控: {summary['project']} / {summary['symbol']}",
        f"有效总结: {monitor_effective_summary(summary)}",
        f"时间: {snapshot['generated_at']}",
        f"结论: {summary['conclusion']}",
        f"现货动作: {summary['spot_action']}",
        f"合约动作: {summary['perp_action']}",
        f"注意: {summary['attention']}",
        f"风险等级: {summary['risk_level']}",
        "",
        f"庄家行为: {summary['operator_behavior']}",
        f"狙击手行为: {summary['sniper_behavior']}",
        "",
        f"监控: {len(snapshot['wallets'])} 个钱包，{len(snapshot['alerts'])} 个告警，窗口 {snapshot['lookback_blocks']} blocks",
        f"规模: 流入 {summary['total_in']}，流出 {summary['total_out']}，净变化 {summary['net_delta']}",
    ]
    for group in snapshot["groups"]:
        lines.append(
            f"链路: {group['chain']} {short_addr(group['token_contract'])}，相关转账 {group['relevant_rows']}/{group['transfer_rows']}，区块 {group['from_block']}->{group['latest_block']}"
        )
        if group.get("quote_scan_blocked"):
            lines.append(f"扫描保护: {group['quote_symbol']} 属于高流量 quote token，本轮只看余额不扫全量转账")
    lines.append("")
    if snapshot["alerts"]:
        lines.append("触发证据:")
        for row in summary["top_alerts"]:
            lines.append(
                f"- {clean(row.get('label', ''))} {short_addr(row.get('address', ''))}: "
                f"{movement_phrase(row)}，最后 {short_addr(row.get('last_transfer_hash', ''))}"
            )
        lines.append("")
        lines.append("我会继续看:")
        for item in summary["next_checks"]:
            lines.append(f"- {item}")
    else:
        lines.append("告警: 暂无监控钱包转账")

    text = "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:
        return text[: TELEGRAM_LIMIT - 40] + "\n...truncated"
    return text


def monitor_effective_summary(summary: dict[str, Any]) -> str:
    if summary.get("risk_level") == "HIGH":
        return f"{summary['spot_action']}；{summary['perp_action']}"
    return f"{summary['spot_action']}；{summary['attention']}"


def analyze_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    alerts = snapshot.get("alerts", [])
    wallets = snapshot.get("wallets", [])
    disabled = snapshot.get("disabled_projects", [])
    first = (alerts or wallets or [{}])[0]
    total_in = sum((dec(row.get("incoming_amount")) for row in alerts), Decimal(0))
    total_out = sum((dec(row.get("outgoing_amount")) for row in alerts), Decimal(0))
    net_delta = sum((dec(row.get("balance_delta")) for row in alerts if row.get("balance_delta") != ""), Decimal(0))
    levels: dict[str, int] = {}
    for row in alerts:
        level = str(row.get("monitor_level") or "UNKNOWN")
        levels[level] = levels.get(level, 0) + 1
    critical_count = levels.get("CRITICAL", 0)
    distribution_count = sum(1 for row in alerts if "分发" in str(row.get("label", "")) or "分完" in str(row.get("label", "")))
    abnormal_count = sum(1 for row in alerts if "异常" in str(row.get("label", "")))
    dealer_count = sum(1 for row in alerts if "庄家" in str(row.get("role", "")) or "潜伏" in str(row.get("role", "")))
    front_buyer_count = sum(1 for row in alerts if "front" in str(row.get("label", "")).lower() or "front" in str(row.get("role", "")).lower())

    if not alerts and disabled:
        conclusion = "当前监控窗口没有关键钱包移动；已暂停项目: " + ", ".join(disabled)
    elif not alerts:
        conclusion = "当前监控窗口没有关键钱包移动"
    elif critical_count >= 3 or abnormal_count >= 2:
        conclusion = "高危钱包正在移动，需要马上看最后几笔 tx 的去向"
    elif distribution_count >= 2 or total_out > 0:
        conclusion = "筹码分发链路有动作，需要跟踪是否流向交易所、池子或新中转钱包"
    else:
        conclusion = "有监控钱包活动，先按普通异动跟踪"

    top_alerts = sorted(
        alerts,
        key=lambda row: abs(dec(row.get("balance_delta"))) + dec(row.get("incoming_amount")) + dec(row.get("outgoing_amount")),
        reverse=True,
    )[:6]

    next_checks = ["打开最后 tx，看 counterparty 是交易所、池子、桥、合约还是新钱包"]
    if total_out > 0:
        next_checks.append("外转地址若继续集中到少数钱包，标记为新分发链路")
    if net_delta < 0:
        next_checks.append("净减少钱包要重点看是否接近清仓或进入卖出路径")
    if distribution_count:
        next_checks.append("分发中/已分完钱包继续动，优先判断项目方筹码管理节奏")

    risk_level = decide_risk_level(alerts, critical_count, distribution_count, abnormal_count, total_out, net_delta)
    spot_action, perp_action, attention = decide_trade_actions(
        risk_level=risk_level,
        alerts=alerts,
        total_out=total_out,
        net_delta=net_delta,
        distribution_count=distribution_count,
        abnormal_count=abnormal_count,
    )
    operator_behavior = infer_operator_behavior(
        alerts=alerts,
        total_in=total_in,
        total_out=total_out,
        net_delta=net_delta,
        distribution_count=distribution_count,
        abnormal_count=abnormal_count,
        dealer_count=dealer_count,
    )
    sniper_behavior = infer_sniper_behavior(alerts, front_buyer_count)

    return {
        "project": clean(first.get("project", "unknown")),
        "symbol": clean(first.get("symbol", "")),
        "total_in": fmt_compact(total_in),
        "total_out": fmt_compact(total_out),
        "net_delta": fmt_signed(net_delta),
        "conclusion": conclusion,
        "spot_action": spot_action,
        "perp_action": perp_action,
        "attention": attention,
        "risk_level": risk_level,
        "operator_behavior": operator_behavior,
        "sniper_behavior": sniper_behavior,
        "top_alerts": top_alerts,
        "next_checks": next_checks[:4],
    }


def decide_risk_level(
    alerts: list[dict[str, Any]],
    critical_count: int,
    distribution_count: int,
    abnormal_count: int,
    total_out: Decimal,
    net_delta: Decimal,
) -> str:
    if not alerts:
        return "LOW"
    if abnormal_count >= 2 or critical_count >= 3:
        return "HIGH"
    if distribution_count >= 2 and (total_out > 0 or net_delta < 0):
        return "HIGH"
    if distribution_count or total_out > 0:
        return "MEDIUM"
    return "LOW"


def decide_trade_actions(
    risk_level: str,
    alerts: list[dict[str, Any]],
    total_out: Decimal,
    net_delta: Decimal,
    distribution_count: int,
    abnormal_count: int,
) -> tuple[str, str, str]:
    if not alerts:
        return (
            "观察；未持仓等新池子/开盘块/关键钱包动作",
            "不开空；缺少筹码外流和价格破位证据",
            "注意下一笔真实转账、池子深度、首批买入地址",
        )
    if risk_level == "HIGH":
        if total_out > 0 or net_delta < 0 or distribution_count or abnormal_count:
            return (
                "不追；已有仓位先降低风险，等最后 tx 去向确认",
                "只做做空预案；确认流向交易所/池子后再考虑",
                "注意 counterparty、是否拆分到新钱包、是否进入交易所或桥",
            )
        return (
            "观察；高危钱包有动作，等下一轮确认",
            "不开空；等方向确认",
            "注意高危钱包下一跳",
        )
    if risk_level == "MEDIUM":
        return (
            "观察；只做小仓预案，等承接、池子深度和外转去向确认",
            "不开空；等持续外流或价格破位",
            "注意是否出现连续外流、分发钱包复用、MM 余额变化",
        )
    return (
        "小仓观察预案；等价格锚点和开盘块确认",
        "不开空；当前偏普通异动",
        "注意买入承接和关键钱包是否继续动",
    )


def infer_operator_behavior(
    alerts: list[dict[str, Any]],
    total_in: Decimal,
    total_out: Decimal,
    net_delta: Decimal,
    distribution_count: int,
    abnormal_count: int,
    dealer_count: int,
) -> str:
    if not alerts:
        return "未看到监控钱包移动"
    if abnormal_count >= 2:
        return "异常大单地址在转移筹码，优先怀疑项目方或关联资金在整理路径"
    if distribution_count >= 2 and total_out > 0:
        return "分发钱包继续流转，像是在换中转地址或测试卖出路径"
    if dealer_count and total_in > total_out:
        return "疑似庄家地址在回收筹码，短线更像控盘整理"
    if total_out > total_in:
        return "监控钱包外流偏强，重点看是否去交易所、池子或桥"
    if net_delta > 0:
        return "监控钱包净增，像是在归集或补仓"
    return "有筹码移动，方向还没定性，需要看 counterparty"


def infer_sniper_behavior(alerts: list[dict[str, Any]], front_buyer_count: int) -> str:
    if not alerts:
        return "当前窗口没有狙击手相关钱包动作"
    if front_buyer_count:
        return "前排买入钱包出现动作，需要看是否卖出、加仓或转入新钱包"
    return "当前告警主要来自监控筹码钱包，暂未看到明确前排狙击手砸盘证据"


def movement_phrase(row: dict[str, Any]) -> str:
    incoming = dec(row.get("incoming_amount"))
    outgoing = dec(row.get("outgoing_amount"))
    delta = row.get("balance_delta")
    parts = [
        f"入 {fmt_compact(incoming)}",
        f"出 {fmt_compact(outgoing)}",
    ]
    if delta != "":
        parts.append(f"余额变动 {fmt_signed(dec(delta))}")
    direction = row.get("last_transfer_direction")
    if direction:
        parts.append(f"最近方向 {direction}")
    return "，".join(parts)


def dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def fmt_compact(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    return f"{value:f}"


def fmt_signed(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:f}"


def telegram_alert_keys(snapshot: dict[str, Any]) -> list[str]:
    keys = []
    for row in snapshot.get("alerts", []):
        tx_hash = row.get("last_transfer_hash", "")
        if tx_hash:
            keys.append(
                "|".join(
                    [
                        row.get("chain", ""),
                        row.get("token_contract", ""),
                        row.get("address", ""),
                        row.get("alert_level", ""),
                        row.get("last_transfer_direction", ""),
                        tx_hash,
                    ]
                )
            )
        else:
            payload = json.dumps(
                {
                    "chain": row.get("chain", ""),
                    "token_contract": row.get("token_contract", ""),
                    "address": row.get("address", ""),
                    "alert_level": row.get("alert_level", ""),
                    "balance_delta": row.get("balance_delta", ""),
                },
                sort_keys=True,
            )
            keys.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return sorted(set(keys))


def load_seen_telegram_keys() -> set[str]:
    if not TELEGRAM_SEEN_PATH.exists():
        return set()
    try:
        payload = json.loads(TELEGRAM_SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, list):
        return set()
    return {str(item) for item in payload}


def write_seen_telegram_keys(keys: set[str]) -> None:
    TELEGRAM_SEEN_PATH.write_text(
        json.dumps(sorted(keys)[-5000:], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def maybe_send_telegram(text: str, alert_keys: list[str]) -> dict[str, Any] | None:
    if os.environ.get("SNIPER_MONITOR_TELEGRAM") != "1":
        return None
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"status": "skipped", "reason": "missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"}
    seen = load_seen_telegram_keys()
    new_keys = [key for key in alert_keys if key not in seen]
    if os.environ.get("SNIPER_MONITOR_FORCE_TELEGRAM") != "1":
        if not new_keys:
            return {"status": "skipped", "reason": "no new telegram alert keys", "alert_key_count": len(alert_keys)}
        cooldown = int(os.environ.get("TELEGRAM_MIN_INTERVAL_SECONDS", "900"))
        if cooldown > 0 and TELEGRAM_LAST_SENT_PATH.exists():
            try:
                last_sent = datetime.fromisoformat(TELEGRAM_LAST_SENT_PATH.read_text(encoding="utf-8").strip())
                age = (datetime.now(timezone.utc) - last_sent).total_seconds()
            except Exception:
                age = cooldown
            if age < cooldown:
                return {
                    "status": "skipped",
                    "reason": "telegram cooldown active",
                    "seconds_since_last_sent": int(age),
                    "cooldown_seconds": cooldown,
                    "new_alert_key_count": len(new_keys),
                    "alert_key_count": len(alert_keys),
                }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            write_seen_telegram_keys(seen | set(alert_keys))
            TELEGRAM_LAST_SENT_PATH.write_text(now_iso() + "\n", encoding="utf-8")
            return {
                "status": "sent",
                "http_status": response.status,
                "new_alert_key_count": len(new_keys),
                "alert_key_count": len(alert_keys),
            }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def short_addr(value: str) -> str:
    text = str(value or "")
    if len(text) <= 14:
        return text
    return text[:8] + "..." + text[-6:]


def clean(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ")


def main() -> int:
    lookback = int(os.environ.get("MONITOR_LOOKBACK_BLOCKS", str(DEFAULT_LOOKBACK_BLOCKS)))
    snapshot = build_snapshot(lookback)
    write_outputs(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
