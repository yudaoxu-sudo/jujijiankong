#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_alpha_signal import apply_proposals, parse_signal, render_markdown, write_json
from sniper_engine.project_registry import merge_signal
from sniper_engine.token_aliases import apply_token_aliases, display_alias


STATE_PATH = ROOT / "output" / "telegram_signals" / "state.json"
OUT_DIR = ROOT / "output" / "telegram_signals"
SIGNAL_DIR = ROOT / "input" / "signals" / "telegram"
QUOTE_SYMBOLS = {"USDT", "USDC", "BUSD", "FDUSD", "BNB", "WBNB", "ETH", "WETH", "BTCB"}
GENERIC_SYMBOLS = {"", "UNKNOWN", "LP", "POOL", "TOKEN", "V3", "V4", "BN", "BSC", "ALPHA"}
TELEGRAM_LIMIT = 3900


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def telegram_api(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_updates(token: str, offset: int | None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "timeout": 0,
        "limit": 50,
        "allowed_updates": ["message", "channel_post"],
    }
    if offset is not None:
        payload["offset"] = offset
    data = telegram_api(token, "getUpdates", payload)
    if not data.get("ok"):
        raise RuntimeError(data)
    return data.get("result", [])


def send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    if os.environ.get("DISABLE_TELEGRAM") == "1":
        return {"ok": True, "disabled": True}
    payload = {
        "chat_id": chat_id,
        "text": text[:TELEGRAM_LIMIT],
        "disable_web_page_preview": True,
    }
    return telegram_api(token, "sendMessage", payload)


def update_payload(update: dict[str, Any]) -> dict[str, Any] | None:
    return update.get("message") or update.get("channel_post")


def message_text(message: dict[str, Any]) -> str:
    return str(message.get("text") or message.get("caption") or "").strip()


def chat_label(message: dict[str, Any]) -> str:
    chat = message.get("chat", {})
    return str(chat.get("title") or chat.get("username") or chat.get("id") or "")


def source_label(message: dict[str, Any]) -> str:
    forward = message.get("forward_origin") or {}
    if forward.get("type") == "channel":
        chat = forward.get("chat", {})
        return str(chat.get("title") or chat.get("username") or "")
    sender = message.get("from", {})
    return str(sender.get("username") or sender.get("first_name") or "")


def save_signal(update: dict[str, Any], message: dict[str, Any], text: str) -> Path:
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    update_id = update.get("update_id")
    path = SIGNAL_DIR / f"telegram_{update_id}.txt"
    header = [
        f"source_chat: {chat_label(message)}",
        f"source_forward: {source_label(message)}",
        f"telegram_update_id: {update_id}",
        f"telegram_message_id: {message.get('message_id', '')}",
        f"date_utc: {now_iso()}",
        "",
    ]
    path.write_text("\n".join(header) + text + "\n", encoding="utf-8")
    return path


def should_ignore(text: str) -> bool:
    if not text:
        return True
    if text.startswith("/start") or text.startswith("/help"):
        return False
    lowered = text.lower()
    interesting = [
        "$",
        "0x",
        "alpha",
        "boost",
        "pool",
        "poolid",
        "fdv",
        "polymarket",
        "predict.fun",
        "合约",
        "池子",
        "盘前",
        "狙击",
        "上线",
        "空投",
    ]
    return not any(item in lowered for item in interesting)


def should_auto_apply(parsed: dict[str, Any]) -> bool:
    if os.environ.get("SIGNAL_AUTO_APPLY", "0") != "1":
        return False
    priority = parsed.get("priority")
    if priority not in {"P0_DEEP_REVIEW", "P1_MONITOR"}:
        return False
    if not parsed.get("symbol"):
        return False
    return bool(parsed.get("addresses") or parsed.get("txs") or parsed.get("prediction_urls"))


def maybe_enrich_chain(parsed: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("SIGNAL_CHAIN_ENRICH", "1") != "1":
        return parsed
    if not parsed.get("pool_ids") or not parsed.get("txs"):
        return parsed
    try:
        from scripts.analyze_pancake_pool_tx import analyze_tx
    except Exception as exc:
        parsed["chain_enrichment"] = [{"status": "skipped", "reason": f"import_failed: {exc}"}]
        return parsed

    chain = "bsc"
    pool_links = parsed.get("pool_links") or []
    if pool_links:
        chain = pool_links[0].get("chain") or chain
    rows = []
    for tx_hash in parsed.get("txs", [])[:2]:
        try:
            row = analyze_tx(chain, tx_hash)
            rows.append(
                {
                    "status": "ok",
                    "chain": row.get("chain"),
                    "tx_hash": row.get("tx_hash"),
                    "block": row.get("block"),
                    "tx_index": row.get("tx_index"),
                    "pool_id": row.get("pool_id"),
                    "token0": row.get("token0"),
                    "token1": row.get("token1"),
                    "raw_fields": row.get("raw_fields", {}),
                    "price_summary": row.get("price", {}).get("summary"),
                    "token_transfers": row.get("token_transfers", {}),
                }
            )
        except Exception as exc:
            rows.append({"status": "failed", "chain": chain, "tx_hash": tx_hash, "reason": str(exc)})
    parsed["chain_enrichment"] = rows
    refine_symbol_from_chain(parsed)
    return apply_token_aliases(parsed)


def refine_symbol_from_chain(parsed: dict[str, Any]) -> None:
    non_quote_symbols = []
    for row in parsed.get("chain_enrichment") or []:
        if row.get("status") != "ok":
            continue
        for token_key in ("token0", "token1"):
            symbol = str((row.get(token_key) or {}).get("symbol") or "").upper()
            if symbol and symbol not in QUOTE_SYMBOLS and symbol not in GENERIC_SYMBOLS:
                non_quote_symbols.append(symbol)
    non_quote_symbols = unique_symbols(non_quote_symbols)
    if not non_quote_symbols:
        return
    current = str(parsed.get("symbol") or "").upper()
    if current and current not in GENERIC_SYMBOLS:
        return
    preferred = non_quote_symbols[0]
    parsed["symbol"] = preferred
    parsed["symbols"] = unique_symbols([preferred] + [str(item).upper() for item in parsed.get("symbols", [])])
    proposal = parsed.get("watchlist_proposal") or {}
    proposal["symbol"] = preferred
    if not proposal.get("name") or str(proposal.get("name")).upper() in GENERIC_SYMBOLS:
        proposal["name"] = parsed.get("title") or preferred
    parsed["watchlist_proposal"] = proposal
    for item in parsed.get("prediction_proposals") or []:
        item["symbol"] = preferred


def unique_symbols(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        item = str(value or "").upper()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def priority_allowed_for_push(parsed: dict[str, Any]) -> bool:
    raw = os.environ.get("SIGNAL_AUTO_PUSH_PRIORITIES", "").strip()
    if raw.lower() in {"all", "*"}:
        return True
    if not raw:
        raw = "P0_DEEP_REVIEW,P1_MONITOR"
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return str(parsed.get("priority") or "") in allowed


def is_private_chat(message: dict[str, Any]) -> bool:
    chat = message.get("chat", {})
    return chat.get("type") == "private"


def analysis_message(parsed: dict[str, Any], applied: bool) -> str:
    prices = parsed.get("prices", {})
    registry = parsed.get("project_registry") or {}
    runtime = project_runtime_context(parsed)
    lines = [
        f"新线索分析: {display_symbol(parsed)}",
        f"有效总结: {signal_effective_summary(parsed, runtime)}",
        f"分级: {parsed.get('priority')}",
        f"标题: {parsed.get('title')}",
        f"计划时间: {', '.join(str(item) for item in parsed.get('times', [])[:3]) or '待确认'}",
        f"项目档案: {registry_status_text(registry)}",
        f"动作建议: {runtime.get('spot_action') or signal_action(parsed)}",
    ]
    if runtime:
        lines.extend(
            [
                f"系统状态: {runtime.get('conclusion')}",
                f"合约动作: {runtime.get('perp_action')}",
                f"注意: {runtime.get('attention')}",
                f"监控时间: {runtime.get('generated_at')}",
            ]
        )
    lines.extend(
        [
        "",
        f"庄家行为: {runtime.get('operator_behavior') or signal_operator_behavior(parsed)}",
        f"狙击手行为: {runtime.get('sniper_behavior') or signal_sniper_behavior(parsed)}",
        "",
        f"提取: 合约/地址 {len(parsed.get('addresses', []))}，交易线索 {len(parsed.get('txs', []))}，区块线索 {len(parsed.get('blocks', []))}，预测链接 {len(parsed.get('prediction_urls', []))}",
    ]
    )
    if prices:
        lines.append("价格锚点: " + "，".join(f"{key}={value}" for key, value in prices.items()))
    if parsed.get("addresses") or parsed.get("txs") or parsed.get("pool_ids"):
        lines.append("")
        lines.append(
            "链上索引: "
            f"地址{len(parsed.get('addresses', []))}个，"
            f"tx{len(parsed.get('txs', []))}个，"
            f"PoolId{len(parsed.get('pool_ids', []))}个；细节已归档"
        )
    enrich_rows = parsed.get("chain_enrichment") or []
    ok_enrich = [row for row in enrich_rows if row.get("status") == "ok"]
    if ok_enrich:
        lines.append("")
        lines.append("链上还原:")
        for row in ok_enrich[:3]:
            token0 = row.get("token0") or {}
            token1 = row.get("token1") or {}
            pair = f"{token0.get('symbol')}/{token1.get('symbol')}".strip("/")
            lines.append(f"- {pair} 池子价格已还原，块号和交易序号已归档")
            if row.get("price_summary"):
                lines.append(f"  {row.get('price_summary')}")
            transfers = row.get("token_transfers") or {}
            if transfers:
                lines.append(f"  token转账: {transfers.get('interpretation', '')}")
    lines.append("")
    lines.append("判断:")
    lines.append(infer_judgment(parsed))
    lines.append("")
    lines.append("下一步:")
    for check in parsed.get("next_checks", [])[:6]:
        lines.append(f"- {check_label(check)}")
    lines.append("")
    lines.append(f"配置更新: {'已自动合并' if applied else '已生成提案'}")
    return "\n".join(lines)


def signal_effective_summary(parsed: dict[str, Any], runtime: dict[str, str]) -> str:
    if runtime:
        return f"{runtime.get('spot_action')}; {runtime.get('perp_action')}; {runtime.get('attention')}"
    priority = parsed.get("priority")
    if priority == "P0_DEEP_REVIEW":
        return "进入自动深度跟踪；未出链上结论前不追"
    if priority == "P1_MONITOR":
        return "进入监控；等合约、池子、首批买入和筹码去向确认"
    if priority == "P2_PAPER_TRADE":
        return "只纸面跟踪；不进入交易动作"
    return "暂存归档；不进入交易动作"


def check_label(check: str) -> str:
    labels = {
        "official_contract": "确认官方合约",
        "holder_distribution": "看筹码集中和活动分发地址",
        "address_labeling": "给关键地址打标签",
        "tx_receipt": "还原交易是否成功",
        "block_transaction_order": "看开盘块交易顺序",
        "internal_transactions": "看贿赂和内部转账",
        "prediction_market": "补预测市场赔率",
        "liquidity_range": "还原池子区间和深度",
    }
    return labels.get(str(check), str(check).replace("_", " "))


def display_symbol(parsed: dict[str, Any]) -> str:
    alias = display_alias(parsed)
    if alias:
        return alias
    if parsed.get("symbol"):
        return str(parsed["symbol"])
    registry = parsed.get("project_registry") or {}
    return str(registry.get("symbol") or "UNKNOWN")


def project_runtime_context(parsed: dict[str, Any]) -> dict[str, str]:
    if display_symbol(parsed).upper() != "ARX":
        return {}
    path = ROOT / "output" / "arx_opening_block_watch" / "latest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    analysis = payload.get("analysis") or {}
    return {
        "generated_at": str(payload.get("generated_at", "")),
        "conclusion": str(analysis.get("conclusion", "")),
        "spot_action": str(analysis.get("spot_action", "")),
        "perp_action": str(analysis.get("perp_action", "")),
        "attention": str(analysis.get("attention", "")),
        "operator_behavior": str(analysis.get("operator_behavior", "")),
        "sniper_behavior": str(analysis.get("sniper_behavior", "")),
    }


def registry_status_text(registry: dict[str, Any]) -> str:
    status = registry.get("status")
    if not status:
        return "未更新"
    status_map = {
        "new_project": "新项目，已建档",
        "updated_project": "同项目补充，已去重合并",
        "duplicate_signal": "重复线索，已归档",
    }
    added = registry.get("added") or []
    if added:
        return f"{status_map.get(status, status)}；本次新增: {', '.join(added)}"
    return status_map.get(status, status)


def should_push(parsed: dict[str, Any], private_chat: bool) -> bool:
    if private_chat:
        return True
    if not priority_allowed_for_push(parsed):
        return False
    registry = parsed.get("project_registry") or {}
    return registry.get("status") != "duplicate_signal"


def signal_action(parsed: dict[str, Any]) -> str:
    priority = parsed.get("priority")
    enrich_rows = [row for row in parsed.get("chain_enrichment", []) if row.get("status") == "ok"]
    if priority == "P0_DEEP_REVIEW":
        if enrich_rows:
            return "深挖；先确认官方合约、holder、池子深度和开盘块，未确认前只做观察预案"
        return "深挖；证据多但链上还原不足，先补 tx/block"
    if priority == "P1_MONITOR":
        if enrich_rows:
            return "观察；池子已可链上还原，等 holder、资金来源和首批买入顺序"
        return "观察；先补官方合约、池子 tx 和价格锚点"
    if priority == "P2_PAPER_TRADE":
        return "纸面跟踪；先收集合约、池子、上线时间"
    return "暂存；证据不足，不进入买入计划"


def signal_operator_behavior(parsed: dict[str, Any]) -> str:
    enrich_rows = [row for row in parsed.get("chain_enrichment", []) if row.get("status") == "ok"]
    if enrich_rows:
        row = enrich_rows[0]
        token0 = row.get("token0") or {}
        token1 = row.get("token1") or {}
        price = row.get("price_summary") or ""
        pair = f"{token0.get('symbol')}/{token1.get('symbol')}".strip("/")
        transfers = row.get("token_transfers") or {}
        if transfers.get("count", 0) == 0:
            return f"已初始化 {pair} 池子，初始价格可还原：{price}；本 tx 未见 pair token 转账，偏开池参数/时间准备"
        return f"已初始化 {pair} 池子，初始价格可还原：{price}；本 tx 已出现 pair token 转账，需要看是否为真实加池"
    if parsed.get("pool_ids"):
        return "出现 PoolId，项目方或做市方已经进入加池流程"
    if parsed.get("addresses"):
        return "出现合约/地址，等待确认部署、加池、空投和做市钱包"
    return "当前更像消息线索，项目方动作还需要链上字段确认"


def signal_sniper_behavior(parsed: dict[str, Any]) -> str:
    if parsed.get("txs") and parsed.get("pool_ids"):
        return "已能定位池子 tx，下一步看同区块前后买入、gas、bribe 和 txIndex"
    if parsed.get("txs"):
        return "有 tx，可查块内顺序和是否存在前排买入"
    return "暂未看到狙击手买入证据，需要等开盘块或交易 tx"


def infer_judgment(parsed: dict[str, Any]) -> str:
    priority = parsed.get("priority")
    prices = parsed.get("prices", {})
    if priority == "P0_DEEP_REVIEW":
        return "证据足够，已进入自动深度跟踪；当前动作以系统状态和动作建议为准。"
    if priority == "P1_MONITOR":
        if prices.get("pool_price") and prices.get("premarket_price"):
            return "有合约和价格锚点，已进入监控；等待价格、深度和首批买入证据。"
        return "有可验证链上字段，已进入监控；官方合约和持仓结构会继续补齐。"
    if priority == "P2_PAPER_TRADE":
        return "可做纸面跟踪；当前更像线索，需要补合约、tx 或预测市场证据。"
    return "证据不足，暂存待证；需要官方链接、合约、池子 tx 或预测市场链接。"


def process_update(token: str, update: dict[str, Any]) -> dict[str, Any]:
    message = update_payload(update)
    if not message:
        return {"status": "skipped", "reason": "unsupported update"}
    text = message_text(message)
    if text.startswith("/start") or text.startswith("/help"):
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id:
            send_message(token, chat_id, "已启动。把 Alpha/池子/投研/预测市场消息发来，我会自动解析并返回判断。")
        return {"status": "handled", "reason": "help"}
    if should_ignore(text):
        return {"status": "skipped", "reason": "not signal-like"}

    signal_path = save_signal(update, message, text)
    parsed = parse_signal(text, signal_path)
    parsed = maybe_enrich_chain(parsed)
    parsed["project_registry"] = merge_signal(
        parsed,
        {
            "collector": "telegram_bot",
            "source_chat": chat_label(message),
            "source_forward": source_label(message),
            "telegram_update_id": update.get("update_id"),
            "telegram_message_id": message.get("message_id", ""),
            "source_path": str(signal_path),
        },
    )
    if not parsed.get("symbol") and parsed["project_registry"].get("symbol"):
        parsed["symbol"] = parsed["project_registry"]["symbol"]
        parsed["symbols"] = [parsed["symbol"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = signal_path.stem
    write_json(OUT_DIR / f"{stem}.json", parsed)
    (OUT_DIR / f"{stem}.md").write_text(render_markdown(parsed), encoding="utf-8")
    applied = should_auto_apply(parsed)
    if applied:
        apply_proposals(parsed)

    target_chat = os.environ.get("SIGNAL_ANALYSIS_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    pushed = False
    if target_chat and should_push(parsed, is_private_chat(message)):
        result = send_message(token, target_chat, analysis_message(parsed, applied))
        pushed = bool(result.get("ok") and not result.get("disabled"))
    return {"status": "processed", "signal_path": str(signal_path), "applied": applied, "pushed": pushed, "symbol": parsed.get("symbol"), "priority": parsed.get("priority"), "registry_status": parsed.get("project_registry", {}).get("status")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect signal-like Telegram bot updates and send parsed analysis.")
    parser.add_argument("--bootstrap", action="store_true", help="Set offset to the latest pending update without processing old updates.")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        if os.environ.get("DISABLE_TELEGRAM") == "1":
            print(json.dumps({"status": "skipped", "reason": "missing TELEGRAM_BOT_TOKEN and DISABLE_TELEGRAM=1"}, ensure_ascii=False))
            return 0
        raise SystemExit("missing TELEGRAM_BOT_TOKEN")
    state = read_json(STATE_PATH, {"offset": None, "processed": []})
    updates = get_updates(token, state.get("offset"))
    if args.bootstrap:
        max_update_id = max((int(update.get("update_id", 0)) for update in updates), default=None)
        new_state = {
            "updated_at": now_iso(),
            "offset": (max_update_id + 1) if max_update_id is not None else state.get("offset"),
            "processed": [],
            "bootstrap": True,
        }
        write_json(STATE_PATH, new_state)
        print(STATE_PATH)
        print(json.dumps({"bootstrap": True, "pending_seen": len(updates), "offset": new_state["offset"]}, ensure_ascii=False))
        return 0

    processed = []
    max_update_id = state.get("offset", 0) - 1 if state.get("offset") else None
    for update in updates:
        update_id = int(update.get("update_id", 0))
        result = process_update(token, update)
        processed.append({"update_id": update_id, **result})
        max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

    new_state = {
        "updated_at": now_iso(),
        "offset": (max_update_id + 1) if max_update_id is not None else state.get("offset"),
        "processed": processed[-200:],
    }
    write_json(STATE_PATH, new_state)
    print(STATE_PATH)
    print(json.dumps({"updates": len(updates), "processed": processed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
