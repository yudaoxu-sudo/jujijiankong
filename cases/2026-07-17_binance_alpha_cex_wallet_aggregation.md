# Binance Alpha CEX Wallet Aggregation Review

Date: 2026-07-17

## 结论

币安 Alpha 尽调中心的“CEX 钱包归集资金动态”对系统有帮助，适合作为官方发现入口。它可以补充 CEX 地址线索、历史大额入金和 Alpha 托管路径。

系统接入采用三类经济路径：

- `external_to_cex_inflow`：外部地址进入 CEX deposit、hot wallet 或 runtime sweep 候选，保留既有入金风险门槛。
- `cex_internal_aggregation`：deposit、sweep、hot wallet 之间的后续搬运，固定 `direction=unknown`、`runtime_effect=none`、`report_only`。
- `alpha_custody_movement_unresolved`：Alpha Router、Custody、Rebalance、外部进入托管入口及待核 Alpha Hot Wallet 相关搬运，只进入报告层，不预设内部调仓。

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

## 待核记录

截图中的三条 `Binance: Alpha Hot Wallet` 记录仍缺精确 TXID 和钱包地址：

- 2026-07-07 `+972.54M AKE`
- 2026-07-05 `+822.99M AKE`
- 2026-07-04 `+670.00M AKE`

这三条固定 `pending_txid / runtime_effect=none`。用户在币安 App 点开对应 `TXID` 并提供哈希后，系统再核对 receipt、from/to、钱包角色、内部归集关系和经济流去重。

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
- 多笔直接进入已配置 CEX 地址、单笔均低于门槛的窗口聚合仍是残余缺口。
