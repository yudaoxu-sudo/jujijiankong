# CEX Wallet Evidence Prompt

用途：让 Manus 或其他外部 agent 收集 BSC 主流交易所充值、归集、热钱包证据，帮助监控系统区分 CEX 入金、做市库存补充、项目方调仓和真实 DEX 派发。

把下面整段复制给外部 agent：

```text
请帮我收集 BNB Chain 上主流 CEX 钱包标签和资金归集证据，用于链上新币监控系统识别 CEX 充值/归集/热钱包。

交易所范围：
- Binance
- OKX
- Bybit
- Gate
- KuCoin
- HTX
- MEXC
- Bitget

目标：
1. 收集高置信 BSC 地址，按 hot_wallet / deposit_wallet / deposit_funder / sweep_wallet 分类。
2. 每个地址必须给出来源证据：BscScan 标签、Arkham 标签、Nansen/DeBank/CoinCarp 页面、或明确链上归集路径。
3. 对 deposit/sweep 类地址，最好给 3-5 条真实 tx，证明它们收到用户充值后归集到同一交易所热钱包。
4. 不要把 DEX router、Binance Alpha Router、项目方 MM 钱包、跨链桥、普通 EOA 混成 CEX 钱包。

输出格式：

第一部分：JSON 数组，字段必须如下：
[
  {
    "chain": "bsc",
    "address": "0x...",
    "exchange": "Binance",
    "type": "hot_wallet | deposit_wallet | deposit_funder | sweep_wallet",
    "confidence": "high | medium | low",
    "evidence": "简短证据说明",
    "source_url": "https://..."
  }
]

第二部分：Markdown 表格：
- exchange
- address
- type
- confidence
- source label
- source url
- sweep path example: user -> deposit -> sweep -> hot wallet
- notes

第三部分：归集链路证据：
- 每个新 deposit/sweep 地址列 3 条 tx hash
- 说明这些 tx 是否把资金归集到已知 hot wallet
- 如果只能证明标签，不能证明归集路径，请明确写 “label_only”

严格排除：
- 地址长度不是 42 位的 0x 地址
- confidence 低于 high 的样本不能混进高置信列表
- router / bridge / token contract / LP pool
- 只凭名字相似、没有来源链接的地址

目标结论：
请明确哪些地址可以直接入高置信 CEX 标签，哪些只能放人工复核队列。
```

本地接收后的处理命令：

```bash
python3 scripts/review_exchange_wallet_labels.py \
  --input /path/to/exchange_wallets_bsc.json
```

如果外部 agent 给的是 deposit/sweep 归集路径证据，使用：

```bash
python3 scripts/review_cex_sweep_patterns.py \
  --input /path/to/cex_sweep_paths_bsc.json
```

脚本只输出审查和 label proposals，不会自动改 `config/global_address_labels.json`。
