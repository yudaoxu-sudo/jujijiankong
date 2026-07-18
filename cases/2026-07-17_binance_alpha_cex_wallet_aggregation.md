# Binance Alpha CEX Wallet Aggregation Review

Date: 2026-07-17

## 结论

币安 Alpha 尽调中心的“CEX 钱包归集资金动态”对系统有帮助，适合作为官方发现入口。它可以补充 CEX 地址线索、历史大额入金和 Alpha 托管路径。

系统接入采用三类经济路径：

- `external_to_cex_inflow`：外部地址进入 CEX deposit、hot wallet 或 runtime sweep 候选，保留既有入金风险门槛。
- `cex_internal_aggregation`：deposit、sweep、hot wallet 之间的后续搬运，固定 `direction=unknown`、`runtime_effect=none`、`report_only`。
- `alpha_custody_movement_unresolved`：Alpha Router、Custody、Rebalance、外部进入托管入口及截图标签仍未公开逐字映射的 Alpha Hot Wallet 相关搬运，只进入报告层，不预设内部调仓。

这项分类修复了一个真实逻辑缺口：`external -> runtime sweep -> hot` 旧路径会把两跳都计入 CEX 入金；现在只统计第一跳经济流。

`cex_internal_aggregation_token` 保留为内部 Transfer 毛额。多跳归集可能重复出现同一批代币，因此该字段只用于路径审计，不当作净经济流。

结构化证据保存在 `input/binance_alpha_cex_wallet_aggregation_review_2026-07-17.json`。

## 现场链上复核

截图中的两笔 Gate 记录已经重建到精确 BSC 交易：

| UI 记录 | TXID | UTC | from -> to | 精确数量 | 判定 |
| --- | --- | --- | --- | ---: | --- |
| Gate `+1.85B` | [`0xbd9b...ec28`](https://bscscan.com/tx/0xbd9b2b41d92c7ed59bd22afa376656aabea115755c7295f584d4130ab329ec28) | 2026-07-14 05:11:24 | `0xd5da...7190 -> Gate 1 0x0d07...92fe` | 1,845,034,161.853208889131008 AKE | `unlabeled_to_cex_inflow_candidate` |
| Gate `+1.91B` | [`0xcc96...d619`](https://bscscan.com/tx/0xcc96491ff1dcbf98511a5aba24955ad9629c3ff68d8325a99be7403ac72dd619) | 2026-07-14 05:11:23 | `0x8782...07b3 -> Gate 1 0x0d07...92fe` | 1,914,689,272 AKE | `unlabeled_to_cex_inflow_candidate` |

两笔交易的 receipt 均为成功，均只有一条 AKE `Transfer` log，token contract 与截图合约一致。两笔来源地址在最新状态下均无合约代码；历史区块的代码状态受公共节点 archive 能力限制，保持 unresolved。

这两个样本说明 UI 的 `+` 对应 Gate 目标钱包收到代币。两条来源地址在本次复核中均为未标记 EOA，实体角色和 Gate 内部归集关系尚未验证。链上方向和 CEX 目标已经核验，因此进入 `unlabeled_to_cex_inflow_candidate` 供给风险门槛；该状态不支持项目方派发、经济外部入金或已确认卖出的表述。该结论只覆盖已经重建的两条 Gate 记录。来源关联、出售意图和后续卖出仍需地址标签、下一跳或 quote recovery 才能确认。

## Binance Alpha 三笔记录复核

公开链上取证得到三笔与截图日期、金额舍入区间及 tracked Alpha Proxy/Custody 目标唯一匹配的 BSC 候选。截图行到 TXID 的直接链接仍需打开 App 中的 TXID 字段闭合：

| UI 记录 | 候选 TXID | BSC `milliTimestamp` UTC / 北京时间 | from -> to | 精确数量 | AKE Transfer 去重键 |
| --- | --- | --- | --- | ---: | --- |
| `+972.54M` | [`0x7321...1727`](https://bscscan.com/tx/0x7321a5f87f0709502c7ed8c27bcb398bef779599cee5c090190f405fae871727) | 2026-07-07 08:46:34.150 / 16:46:34.150 | `0x6449...5a48 -> 0x73d8...46db` | 972,540,250 AKE | `(tx, 218)` |
| `+822.99M` | [`0x4b2d...5af8`](https://bscscan.com/tx/0x4b2d3173498afd9b056a41347276ca32fad9494eeece7e01384a755099615af8) | 2026-07-05 10:25:35.250 / 18:25:35.250 | `0xd49e...9f04 -> 0x73d8...46db` | 822,989,955 AKE | `(tx, 420)` |
| `+670.00M` | [`0x288e...8f87`](https://bscscan.com/tx/0x288e360dc637295457af65ba3515108e4bf6342f7d2fb9efa40393540c3f8f87) | 2026-07-04 10:58:07.650 / 18:58:07.650 | `0xb40b...1395 -> 0x73d8...46db` | 670,000,000 AKE | `(tx, 330)` |

三笔候选均在 BSC chainId 56 成功执行，token 为 AKE 合约，decimals 为 18，原生币 value 为 0。交易调用目标与 Transfer 收款方均为 `0x73d8...46db`；三个发送方在最新状态下均无合约代码，目标地址有合约代码。标准 EVM block timestamp 为整秒；表内毫秒来自同一公共 RPC 的 BSC 扩展字段 `eth_getBlockByNumber.milliTimestamp`。每笔 receipt 各有 2 条日志，其中只有 1 条 AKE `Transfer`。后一条是 `0x73d8...46db` 发出的合约事件，topic0 为 `0xe993...a3a2`，携带相同 token 与 raw amount；AKE `Transfer` 计数仍为 1。

tracked 标签把 `0x73d8...46db` 记为 `Binance Alpha 2.0 Proxy/Custody`、`exchange_aggregator`；[BscScan 地址页](https://bscscan.com/address/0x73d8bd54f7cf5fab43fe4ef40a62d390644946db)显示 `Binance: Alpha 2.0 Router Proxy`。公开资料尚未提供截图逐字标签 `Binance: Alpha Hot Wallet` 到该地址的字段级映射。地址托管用途、发送方归属、经济外部流入、卖出意图和同批代币下一跳均保持 unresolved。

因此三笔候选固定为 `alpha_custody_movement_unresolved / direction=unknown / runtime_effect=none / report_only`。它们不进入供给风险计数，也不进入 Telegram。

## 有界搜索覆盖

搜索把每个 UI 日期的北京时间日历日和 UTC 日历日取并集，区间使用左闭右开。金额按两位小数的 `M` 展示筛选：`670.00M` 对应 `[669,995,000, 670,005,000)`，`822.99M` 对应 `[822,985,000, 822,995,000)`，`972.54M` 对应 `[972,535,000, 972,545,000)`。

| UI 日期 | 合并搜索窗口 UTC | 已检查 Transfer 行 | 金额候选 | 排除 | 覆盖状态 |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-07-04 | 2026-07-03 16:00–2026-07-05 00:00 | 2,952 | 1 | 2,951 | 目标地址过滤内完整 |
| 2026-07-05 | 2026-07-04 16:00–2026-07-06 00:00 | 2,292 | 1 | 2,291 | 目标地址过滤内完整 |
| 2026-07-07 | 2026-07-06 16:00–2026-07-08 00:00 | 3,412 | 1 | 3,411 | 候选之后覆盖至 2026-07-07 12:08:33 UTC |

BscScan 公开 AKE + `0x73d8...46db` 地址过滤页 `480–552` 共 73 页全部成功，每页 100 行，共 7,300 行，时间边界为 2026-07-03 15:36:31 UTC 至 2026-07-07 12:08:33 UTC。iframe 不提供 logIndex，三笔候选均通过 receipt 恢复 logIndex 后按 `(txHash, logIndex)` 去重。

固定公共 BSC RPC `https://bsc-dataseed.binance.org/` 完成了 `chainId`、transaction、receipt、block、`decimals()` 和最新 `eth_getCode` 复核。[BNB Chain 官方文档](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)说明公开主网端点禁用 `eth_getLogs`；本次单区块请求也返回 `-32005 limit exceeded`。普通 token Transfer 列表只暴露最近 100,000 条，无法覆盖目标日期，因此使用地址过滤进行有界恢复。

补充地址扫描保留清晰边界：Alpha Router `0x6aba...1b90` 的可用页深未完整覆盖 2026-07-04；配置中的传统 Binance hot-wallet 地址在首个地址第一页遇到 Cloudflare challenge 后即停止，未尝试绕过。当前证据闭合三笔候选的精确交易细节和中性分类；截图行直接链接与所有可能截图标签地址的穷尽覆盖继续 unresolved。

三笔候选之后，地址级最早可见 AKE 出账分别为：

- 670M 入账后 3 分 11 秒：[`0xfa05...6f36`](https://bscscan.com/tx/0xfa0557f8e2da6d827f73cec9557ba60f5898737efdc4165646242757059b6f36)，323,089 AKE，`0x73d8...46db -> 0x6aba...1b90`。
- 822.99M 入账后 5 分 9 秒：[`0x68b5...ce62`](https://bscscan.com/tx/0x68b5ee2c7d35455f0d453d0f399ee6d49abd692284e19c9b795ccd1827adce62)，70,322.2219445 AKE，同一路径。
- 972.54M 入账后 6 秒：[`0x62b6...7843`](https://bscscan.com/tx/0x62b6677cc9861ece58fa7525e65197bea58fcfe91a9809bdb88b0d8b030e7843)，479,101.9600125 AKE，同一路径。

这些记录只证明收款地址随后出现 AKE 出账；当前数据无法把任一出账归属于对应入账批次。

## 证据分层

- `official`：币安尽调中心界面、[币安尽调中心公告](https://x.com/binancezh/status/2059152880133902573)、[公开 Alpha token list](https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list)、[官方 Alpha API 参考](https://github.com/binance/binance-skills-hub/blob/main/skills/binance/binance/references/alpha.md)。官方资料尚未解释该字段的地址标签来源、正负号定义、归集算法和去重规则。
- `onchain`：BSC 交易、receipt、Transfer log、区块时间、decimals 和目标地址。
- `market`：截图价格只保留为时间点背景，本次不据此改变动作。
- `social`：本次没有把 KOL 或社区说法写入运行时结论。
- `inference`：路径角色和运行时影响建立在 official 与 onchain 分离后。

## 运行边界

- 新字段用于发现与报告，不直接产生买入、吸筹、卖出或自动交易动作。
- TXID、receipt、token、方向和 CEX 目标角色通过后，可进入 `unlabeled_to_cex_inflow_candidate` 供给风险门槛；来源实体和出售意图继续单列 unresolved。
- CEX 内部归集和 Alpha 托管相关未决路径不进入 Telegram。
- 当前系统继续只读，不签名，不执行交易。
- runtime sweep 候选采用窗口内 FIFO 归因；窗口开始前余额继续未知，transfer coverage 不完整时只报告。
- 多笔直接进入已配置 CEX 地址、单笔均低于门槛的窗口聚合已于 2026-07-18 加入 coverage-gated 实现；当前待首个自然样本验收。
