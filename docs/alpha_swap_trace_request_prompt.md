# Binance Alpha Swap Trace 采样提示词

用途：让 Manus 或其他外部 agent 帮忙找 Binance Alpha 真实 swap tx，作为我们校准 Alpha 托管 / aggregator / rebalance 地址的输入。

把下面整段复制给外部 agent：

```text
请帮我查找 Binance Alpha 2.0 在 BNB Chain / PancakeSwap 路径上的真实 swap 交易样本，用于链上监控系统校准交易所托管、聚合器、再平衡地址。

目标：
1. 找 5-8 条真实 BSC swap tx。
2. 至少覆盖 3 个不同 Binance Alpha 项目，优先 5 个不同项目。
3. 样本必须是 Binance Alpha 用户成交或 Binance Alpha Router 触发的 swap，不要给普通 Pancake 用户手动 swap、加池、撤池、空投领取、approve、转账。
4. 优先选择 BscScan 上 tx.to / Interacted With 显示 Binance Alpha 2.0 Router 的交易。
5. 每条交易都要能在 receipt token transfers 里看到 Alpha token 与 USDT/USDC/WBNB 等报价资产的流转。

重点验证这些地址是否出现，并说明角色：
- 0x73d8bd54f7cf5fab43fe4ef40a62d390644946db
- 0x6aba0315493b7e6989041c91181337b662fb1b90
- 0xb300000b72deaeb607a12d5f54773d1c19c7028d

输出格式：

第一部分：raw tx hash 列表，一行一个，只包含 tx hash，方便我直接保存成 txs.txt。脚本也能从 Markdown 表格和 BscScan 链接里自动提取 tx hash。

第二部分：Markdown 表格，字段如下：
- 项目 symbol
- token contract
- BscScan tx link
- block
- tx.to / Interacted With
- receipt transfer 摘要
- 上面 3 个目标地址分别是否出现
- 为什么你认为这是 Binance Alpha swap

第三部分：证据说明：
- 如果能打开 internal transactions / state diff / debug trace，请截图或提取调用路径。
- 如果不能提取 debug trace，请明确写“只有 receipt 证据，没有 call trace”。
- 如果某条样本只是疑似 Alpha swap，请放到“低置信样本”区，不要混进 raw tx hash 列表。

判断标准：
- 跨 token 复用的 router / proxy / DEX router 地址是最有价值的证据。
- 单个 token 的多笔交易只能证明该 token 的成交路径，不能证明 Binance Alpha 共享基础设施。
- 不要把项目方加池、项目方调仓、活动空投分发当成 Alpha swap 样本。
```

拿到结果后的本地入口：

```bash
python3 scripts/review_alpha_swap_txs.py \
  --chain bsc \
  --tx-file /path/to/txs.txt \
  --address 0x73d8bd54f7cf5fab43fe4ef40a62d390644946db \
  --address 0x6aba0315493b7e6989041c91181337b662fb1b90 \
  --address 0xb300000b72deaeb607a12d5f54773d1c19c7028d
```

输出会写到：

```text
output/alpha_trace_samples/tx_review/<UTC>/review/latest.md
```

审查原则：

- `exchange_aggregator_suspect_candidate` 可以先用于排除 cohort 污染。
- 正式升级 `exchange_aggregator` 仍需要 call trace 或等价证据确认稳定币腿 / 山寨币腿配对结构。
- Receipt-only 样本不能拿来宣称项目方出货。
