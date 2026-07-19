# AKE Alpha Proxy/Custody Next-Hop and Retention Review

Date: 2026-07-19

## 结论

三笔唯一链上候选的目标地址 24h/72h AKE 收支已经按一份全局 tx/log 账本闭合。主公共 RPC 的 228 个方向分片全部完成，10,185 个事件各自对应 10,185 笔成功 receipt，receipt 内的 AKE Transfer 与 `(txHash, logIndex)` 全部一致。Nodies 的 18 个独立 50-block 抽样全部逐字段一致；1RPC 另有 2 个一致样本和 16 个不可用样本，没有发现冲突样本。

历史 `balanceOf` 也闭合了六个窗口的账本等式。最早根事件前的地址库存是 5463979755.126102411767076499 AKE，数量可核验，来源保持 unknown。整个并集窗口总出账是 5451529191.4669272063 AKE；按一份跨窗口 FIFO，这个 unknown opening lot 到并集结束仍剩 12450563.659175205467076499 AKE。因此三笔根 lot 在各自 24h/72h 内的 FIFO 可归因出账均为 0，FIFO 可归因留存均为 100%。FIFO 是可审计的库存记账假设，不证明同质化代币的物理批次或经济所有权。

三笔入账后的地址级最早出账都去了 tracked `Binance Alpha 2.0 Router`。这些出账发生在高频混合库存中，金额与根入账不相等，FIFO 也没有消费对应根 lot，所以不能写成三笔资金的下一跳、卖出或供给风险。分类继续保持 `alpha_custody_movement_unresolved / direction=unknown / runtime_effect=none / report_only`，Telegram 与交易执行边界不变。

## 窗口账本

所有窗口左闭右开。表内金额单位均为 AKE；窗口重叠，行列不可相加。

| 根入账 | 根金额 | 24h 开始余额 | 24h 入 / 出 / 净 | 24h FIFO 留存 | 72h 开始余额 | 72h 入 / 出 / 净 | 72h FIFO 留存 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `0x288e360d...8f87` 2026-07-04T10:58:07.650Z | 670000000 | 5463979755.126102411767076499 | 3132200440.389220696368035976 / 1797171651.04609589 / 1335028789.343124806368035976 | 670000000 | 5463979755.126102411767076499 | 6182305204.450814828053421461 / 3838598054.9706516963 / 2343707149.480163131753421461 | 670000000 |
| `0x4b2d3173...5af8` 2026-07-05T10:25:35.250Z | 822989955 | 5976446170.273295778135112475 | 883552783.149564747288656994 / 346437611.74936619 / 537115171.400198557288656994 | 822989955 | 5976446170.273295778135112475 | 8832338009.473789978020601051 / 3352903081.2225917763 / 5479434928.251198201720601051 | 822989955 |
| `0x7321a5f8...1727` 2026-07-07T08:46:34.150Z | 972540250 | 7851912595.775280176778878698 | 5073183907.365994418665018546 / 2100906814.6282065363 / 2972277092.737787882365018546 | 972540250 | 7851912595.775280176778878698 | 6119173412.12857904261341476 / 2715368081.0804335963 / 3403805331.04814544631341476 | 972540250 |

窗口边界：

- `0x288e360dc637295457af65ba3515108e4bf6342f7d2fb9efa40393540c3f8f87`：24h `[2026-07-04T10:58:07.650Z, 2026-07-05T10:58:07.650Z)` UTC；72h `[2026-07-04T10:58:07.650Z, 2026-07-07T10:58:07.650Z)` UTC。北京时间起点为 `2026-07-04T18:58:07.650+08:00`。
- `0x4b2d3173498afd9b056a41347276ca32fad9494eeece7e01384a755099615af8`：24h `[2026-07-05T10:25:35.250Z, 2026-07-06T10:25:35.250Z)` UTC；72h `[2026-07-05T10:25:35.250Z, 2026-07-08T10:25:35.250Z)` UTC。北京时间起点为 `2026-07-05T18:25:35.250+08:00`。
- `0x7321a5f87f0709502c7ed8c27bcb398bef779599cee5c090190f405fae871727`：24h `[2026-07-07T08:46:34.150Z, 2026-07-08T08:46:34.150Z)` UTC；72h `[2026-07-07T08:46:34.150Z, 2026-07-10T08:46:34.150Z)` UTC。北京时间起点为 `2026-07-07T16:46:34.150+08:00`。

## 地址级最早出账

| 根入账 | 最早后续出账 | UTC | 数量 | 路径 | 经济关联 |
| --- | --- | --- | ---: | --- | --- |
| `0x288e360d...8f87` | `0xfa0557f8e2da6d827f73cec9557ba60f5898737efdc4165646242757059b6f36` / log 382 | 2026-07-04T11:01:19.000Z | 323089 | `0x73d8...46db -> 0x6aba...1b90` (tracked Alpha Router) | 未验证；report-only |
| `0x4b2d3173...5af8` | `0x68b5ee2c7d35455f0d453d0f399ee6d49abd692284e19c9b795ccd1827adce62` / log 150 | 2026-07-05T10:30:44.000Z | 70322.2219445 | `0x73d8...46db -> 0x6aba...1b90` (tracked Alpha Router) | 未验证；report-only |
| `0x7321a5f8...1727` | `0x62b6677cc9861ece58fa7525e65197bea58fcfe91a9809bdb88b0d8b030e7843` / log 99 | 2026-07-07T08:46:40.000Z | 479101.9600125 | `0x73d8...46db -> 0x6aba...1b90` (tracked Alpha Router) | 未验证；report-only |

## 出账角色分层

- `alpha_router_custody_rebalance_unresolved_report_only`：5742 个事件，2451966631.0640387563 AKE。
- `unlabeled_destination_unresolved`：916 个事件，2999562560.40288845 AKE。
- tracked 地址中没有观察到 CEX、DEX/pool 或零地址目的地；未标记目的地继续保持 unresolved。latest-only code 结果只区分当前是否有代码，不提升实体标签。
- 全部目标地址出账 receipt 中，没有观察到同 receipt 的 tracked quote token 回到目标地址；该检查不覆盖下游地址的后续 quote recovery。

## 标签与证据边界

`0x73d8...46db` 在 `config/global_address_labels.json` 中仍是 `Binance Alpha 2.0 Proxy/Custody`、`exchange_aggregator`。依据是 2026-06-29 Phalcon nested-call review：CLO/RAVE buy 路径把资产 approve/deposit 到该 proxy/custody，KGEN sell 路径从同一结构 pull。此次取证没有把截图的逐字标签 `Binance: Alpha Hot Wallet` 反向写入 tracked label；公开字段级映射、三名发送方归属、经济外部流入和卖出意图继续 unresolved。

## 覆盖与去重

- 并集区块：`108008641–109142105`，共 1,133,465 blocks。
- 主日志源：`https://bsc.rpc.blxrbdn.com`；inbound/outbound 各按最多 10,000 blocks 分片，228/228 complete，缺页 0。
- canonical ledger：10,185 rows，raw duplicates 0，identity conflicts 0，removed logs 0。
- 去重键：`(chainId, token, lower(txHash), logIndex)`；三组重叠窗口只投影同一份 ledger，同一出账只参与一次 FIFO 消耗。
- receipt：官方 BSC public RPC 按 255 个最多 40 tx 的 batch 完成；其中 40 tx 在 batch 失败后逐笔重试并全部成功。最终 10,185/10,185 可用，failed status、missing receipt、receipt/log mismatch 均为 0。
- 二级抽样：Nodies 18/18 相等；1RPC 2/18 相等、16/18 unavailable；相等样本之外没有 mismatch。
- archive state：BlastAPI 提供多数历史 `balanceOf`；一个窗口终点由 1RPC 返回。六个窗口的 `opening + net = ending balance` 全部成立。其它端点的 archive 不支持、header 缺失或 trie 缺失逐项保存在结构化 artifact。

## 证据分层

- `official`：BNB Chain public RPC 只用于 chain/block/receipt/state 复核；没有取得 Binance 对截图精确标签的公开字段映射。
- `onchain`：AKE contract、18 decimals、Transfer logs、receipt success、from/to、历史 balanceOf、目标与下游地址。
- `inference`：FIFO 留存只在有界可见账本与已核验 opening balance 下成立；经济外部流入、托管用途和卖出意图没有被推断。

## Artifact

- Summary: `input/ake_alpha_hot_wallet_next_hop_2026-07-19.json`
- Full canonical event ledger: `input/ake_alpha_hot_wallet_next_hop_events_2026-07-19.csv` (10,185 rows, SHA-256 `bf990b08571b43e017ca2792d208bfc398e73bee9110747d5f4b272e93b645ee`)

本单元只有证据更新，没有规则、运行逻辑、Telegram、签名或交易执行变更，因此无需部署。
