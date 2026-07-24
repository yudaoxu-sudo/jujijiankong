# Binance Alpha CEX Wallet Aggregation Review

Date: 2026-07-17

## 结论

币安 Alpha 尽调中心的“CEX 钱包归集资金动态”对系统有帮助，适合作为官方发现入口。它可以补充 CEX 地址线索、历史大额入金和 Alpha 托管路径。

系统接入采用三类经济路径：

- `external_to_cex_inflow`：外部地址进入 CEX deposit、hot wallet 或 runtime sweep 候选，保留既有入金风险门槛。
- `cex_internal_aggregation`：deposit、sweep、hot wallet 之间的后续搬运，固定 `direction=unknown`、`runtime_effect=none`、`report_only`。
- `alpha_custody_movement_unresolved`：Alpha Router、Custody、Rebalance、外部进入托管入口及缺少通用字段词典的 Alpha Hot Wallet 相关搬运，只进入报告层，不预设内部调仓。

这项分类修复了一个真实逻辑缺口：`external -> runtime sweep -> hot` 旧路径会把两跳都计入 CEX 入金；现在只统计第一跳经济流。

`cex_internal_aggregation_token` 保留为内部 Transfer 毛额。多跳归集可能重复出现同一批代币，因此该字段只用于路径审计，不当作净经济流。

结构化证据保存在 `input/binance_alpha_cex_wallet_aggregation_review_2026-07-17.json`；2026-07-23 Gate 批次与 2026-07-24 用户直链补证保存在 `input/ake_gate_cex_wallet_aggregation_batch_2026-07-23.json`。

## 现场链上复核

截图中的两笔 Gate 记录已经重建到精确 BSC 交易：

| UI 记录 | TXID | UTC | from -> to | 精确数量 | 判定 |
| --- | --- | --- | --- | ---: | --- |
| Gate `+1.85B` | [`0xbd9b...ec28`](https://bscscan.com/tx/0xbd9b2b41d92c7ed59bd22afa376656aabea115755c7295f584d4130ab329ec28) | 2026-07-14 05:11:24 | `0xd5da...7190 -> Gate 1 0x0d07...92fe` | 1,845,034,161.853208889131008 AKE | `unlabeled_to_cex_inflow_candidate` |
| Gate `+1.91B` | [`0xcc96...d619`](https://bscscan.com/tx/0xcc96491ff1dcbf98511a5aba24955ad9629c3ff68d8325a99be7403ac72dd619) | 2026-07-14 05:11:23 | `0x8782...07b3 -> Gate 1 0x0d07...92fe` | 1,914,689,272 AKE | `unlabeled_to_cex_inflow_candidate` |

两笔交易的 receipt 均为成功，均只有一条 AKE `Transfer` log，token contract 与截图合约一致。两笔来源地址在最新状态下均无合约代码；历史区块的代码状态受公共节点 archive 能力限制，保持 unresolved。

这两个样本说明 UI 的 `+` 对应 Gate 目标钱包收到代币。两条来源地址在本次复核中均为未标记 EOA，实体角色和 Gate 内部归集关系尚未验证。链上方向和 CEX 目标已经核验，因此进入 `unlabeled_to_cex_inflow_candidate` 供给风险门槛；该状态不支持项目方派发、经济外部入金或已确认卖出的表述。该结论只覆盖已经重建的两条 Gate 记录。来源关联、出售意图和后续卖出仍需地址标签、下一跳或 quote recovery 才能确认。

## 2026-07-23 Gate 批次与五条 App 直链

2026-07-24 用户从 Binance App 同一模块提供了五条 `TXID` 实际跳转链接。五笔交易均在 BSC 成功执行，receipt 各有一条 AKE `Transfer`，收款方均为 [Gate 1 `0x0d07...92fe`](https://bscscan.com/address/0x0d0707963952f2fba59dd06f2b425ace40b492fe)，UI 两位小数的 `M` 展示与精确数量一致：

| UI 记录 | TXID | BSC `milliTimestamp` UTC | from -> to | 精确数量 |
| --- | --- | --- | --- | ---: |
| Gate `+83.32M` | [`0xd37e...90a6`](https://bscscan.com/tx/0xd37e4a6c36885937206ceec6a100239da94ce018bdd217f355dd1fcff85590a6) | 2026-07-23 18:03:41.550 | `0x9697...b748 -> Gate 1` | 83,318,937.289999999133810688 AKE |
| Gate `+96.88M` | [`0xd425...e0fe`](https://bscscan.com/tx/0xd4255c2574d8238a03e73743a646b759c93ace882b96a789a82c465b11b6e0fe) | 2026-07-23 18:03:40.650 | `0xdd04...5afd -> Gate 1` | 96,877,789.58709 AKE |
| Gate `+100.00M` | [`0x1439...f3a6`](https://bscscan.com/tx/0x14391ef5504ee51c54fd74ec48cf908a4cefc7ebc686e6e2659c2b02ba56f3a6) | 2026-07-23 18:03:39.750 | `0x1f7e...e28c -> Gate 1` | 100,000,000 AKE |
| Gate `+131.84M` | [`0xb750...d120`](https://bscscan.com/tx/0xb750d367f56d0f940367b3f7094f56bc978a9dbd6f3b9f4847bdf2f783dcd120) | 2026-07-23 18:03:37.050 | `0xd5da...7190 -> Gate 1` | 131,841,852.507135962884603904 AKE |
| Gate `+149.85M` | [`0x3702...fd33`](https://bscscan.com/tx/0x3702cee10855560a71832ff6a6668194b44cbf513a018886339eb71eec80fd33) | 2026-07-23 18:03:33.900 | `0xcdcc...9898 -> Gate 1` | 149,845,354.671 AKE |

五条 UI 直链合计 `561,883,934.055225962018414592 AKE`。

为避免只看 App 首屏五条，链上扩查先完整拉取 block `111711300–111711650` 内所有 AKE `Transfer`：36 个最多 10-block 的公共 RPC 分片全部成功，共 `2,596` 条日志，低于系统 `12,000` 条上限，coverage 为 `requested_window_complete`。在同一完整窗口内按 Gate 1 收款 topic 过滤后得到 `47` 笔唯一 `(txHash, logIndex)`、`47` 个来源地址；首笔 block `111711359`、末笔 `111711606`，持续 `111` 秒，精确合计 `6,634,139,634.780252285016825276 AKE`。五条 App 记录是其中子集，其余 `42` 笔合计 `6,072,255,700.725026322998410684 AKE`。

批次前后在同一查询窗口分别有 block `111711300–111711358` 和 `111711607–111711650` 的空白肩部。第一笔、最大一笔和最后一笔又经固定公共 BSC RPC receipt 独立复核。完整 47 行、全窗口 coverage、哈希和逐行 raw amount 位于 `input/ake_gate_cex_wallet_aggregation_batch_2026-07-23.json`。

两个来源地址跨批次复用：`0xd5da...7190` 同时出现在 2026-07-14 的 `1,845,034,161.853208889131008 AKE` 和本批 `131,841,852.507135962884603904 AKE`；`0x8782...07b3` 同时出现在 2026-07-14 的 `1,914,689,272 AKE` 和本批另一笔 `197,050,272 AKE`。快速多来源、单一 CEX 目标及跨日复用支持 `rapid_multi_source_single_cex_destination_sweep_candidate`；除下一段已识别的 Gate 5 行外，其余来源的所有权和实体链接仍未验证。

逐个核查来源地址的公开标签后，`0xc882...f071` 被 BscScan 标记为 `Gate 5`。它在 [`0x8a8a...1f27b`](https://bscscan.com/tx/0x8a8a89d0fdb5818ebdbaaff4fb2ae31feb8bbc5c4c20463a9527c3e6d811f27b) 中向 Gate 1 转入 `2,646,151,218.67276859 AKE`，属于已验证 `cex_internal_aggregation / runtime_effect=none / report_only`。其余 `46` 条合计 `3,987,988,416.107483695016825276 AKE`，来源仍未标记，继续采用 `unlabeled_to_cex_inflow_candidate / bearish_risk_candidate`。该分层防止把整批 `6.634B` 全部算成外部供给压力。

完整 coverage 下，现有窗口逻辑可把未被逐笔 receipt 计入的 46 条风险路径合并为一个 Gate 风险聚合行，并按 tx hash 排除已计入 receipt 的交易。验收器已用 47 条真实记录验证“Gate 5 内部一条剔除、46 条风险路径聚合为 1 条、计入五条 receipt 后只剩 41 条、46 条风险路径全计入后不再生成聚合行”，`historical_real_onchain_replay=pass`。`config/global_address_labels.json` 新增 Gate 5 高置信标签，修复未来同类批次的内部转账重复计数；AKE 当前不在 `config/current_alpha_watchlist.json`，生产自然观察继续 pending。该更新不增加 Telegram 直推，也不产生交易动作。

## Binance Alpha 三笔记录复核

公开链上取证先得到三笔与截图日期、金额舍入区间及 tracked Alpha Proxy/Custody 目标唯一匹配的 BSC 候选。2026-07-24 用户提供三行 App `TXID` 的实际跳转链接后，完整 hash 与三个候选逐字一致，具体截图行到 TXID 的映射已经闭合：

| UI 记录 | 已核验 TXID | BSC `milliTimestamp` UTC / 北京时间 | from -> to | 精确数量 | AKE Transfer 去重键 |
| --- | --- | --- | --- | ---: | --- |
| `+972.54M` | [`0x7321...1727`](https://bscscan.com/tx/0x7321a5f87f0709502c7ed8c27bcb398bef779599cee5c090190f405fae871727) | 2026-07-07 08:46:34.150 / 16:46:34.150 | `0x6449...5a48 -> 0x73d8...46db` | 972,540,250 AKE | `(tx, 218)` |
| `+822.99M` | [`0x4b2d...5af8`](https://bscscan.com/tx/0x4b2d3173498afd9b056a41347276ca32fad9494eeece7e01384a755099615af8) | 2026-07-05 10:25:35.250 / 18:25:35.250 | `0xd49e...9f04 -> 0x73d8...46db` | 822,989,955 AKE | `(tx, 420)` |
| `+670.00M` | [`0x288e...8f87`](https://bscscan.com/tx/0x288e360dc637295457af65ba3515108e4bf6342f7d2fb9efa40393540c3f8f87) | 2026-07-04 10:58:07.650 / 18:58:07.650 | `0xb40b...1395 -> 0x73d8...46db` | 670,000,000 AKE | `(tx, 330)` |

三笔记录均在 BSC chainId 56 成功执行，token 为 AKE 合约，decimals 为 18，原生币 value 为 0。交易调用目标与 Transfer 收款方均为 `0x73d8...46db`；三个发送方在最新状态下均无合约代码，目标地址有合约代码。标准 EVM block timestamp 为整秒；表内毫秒来自同一公共 RPC 的 BSC 扩展字段 `eth_getBlockByNumber.milliTimestamp`。每笔 receipt 各有 2 条日志，其中只有 1 条 AKE `Transfer`。后一条是 `0x73d8...46db` 发出的合约事件，topic0 为 `0xe993...a3a2`，携带相同 token 与 raw amount；AKE `Transfer` 计数仍为 1。

tracked 标签把 `0x73d8...46db` 记为 `Binance Alpha 2.0 Proxy/Custody`、`exchange_aggregator`；[BscScan 地址页](https://bscscan.com/address/0x73d8bd54f7cf5fab43fe4ef40a62d390644946db)显示 `Binance: Alpha 2.0 Router Proxy`。三条 App 直链证明这三个具体 `Binance: Alpha Hot Wallet` 行对应 `0x73d8...46db` 交易；公开资料仍未提供可外推到所有行和所有地址的字段级字典。地址托管用途、发送方归属、经济外部流入、卖出意图和同批代币下一跳均保持 unresolved。

因此三笔记录固定为 `alpha_custody_movement_unresolved / direction=unknown / runtime_effect=none / report_only`。它们不进入供给风险计数，也不进入 Telegram。

## 有界搜索覆盖

搜索把每个 UI 日期的北京时间日历日和 UTC 日历日取并集，区间使用左闭右开。金额按两位小数的 `M` 展示筛选：`670.00M` 对应 `[669,995,000, 670,005,000)`，`822.99M` 对应 `[822,985,000, 822,995,000)`，`972.54M` 对应 `[972,535,000, 972,545,000)`。

| UI 日期 | 合并搜索窗口 UTC | 已检查 Transfer 行 | 金额候选 | 排除 | 覆盖状态 |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-07-04 | 2026-07-03 16:00–2026-07-05 00:00 | 2,952 | 1 | 2,951 | 目标地址过滤内完整 |
| 2026-07-05 | 2026-07-04 16:00–2026-07-06 00:00 | 2,292 | 1 | 2,291 | 目标地址过滤内完整 |
| 2026-07-07 | 2026-07-06 16:00–2026-07-08 00:00 | 3,412 | 1 | 3,411 | 候选之后覆盖至 2026-07-07 12:08:33 UTC |

BscScan 公开 AKE + `0x73d8...46db` 地址过滤页 `480–552` 共 73 页全部成功，每页 100 行，共 7,300 行，时间边界为 2026-07-03 15:36:31 UTC 至 2026-07-07 12:08:33 UTC。iframe 不提供 logIndex，三笔记录均通过 receipt 恢复 logIndex 后按 `(txHash, logIndex)` 去重。

固定公共 BSC RPC `https://bsc-dataseed.binance.org/` 完成了 `chainId`、transaction、receipt、block、`decimals()` 和最新 `eth_getCode` 复核。[BNB Chain 官方文档](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)说明公开主网端点禁用 `eth_getLogs`；本次单区块请求也返回 `-32005 limit exceeded`。普通 token Transfer 列表只暴露最近 100,000 条，无法覆盖目标日期，因此使用地址过滤进行有界恢复。

补充地址扫描保留清晰边界：Alpha Router `0x6aba...1b90` 的可用页深未完整覆盖 2026-07-04；配置中的传统 Binance hot-wallet 地址在首个地址第一页遇到 Cloudflare challenge 后即停止，未尝试绕过。当前证据闭合三笔记录的精确交易、具体截图行直链和中性分类；所有可能截图标签地址的穷尽覆盖继续 unresolved。

三笔记录之后，地址级最早可见 AKE 出账分别为：

- 670M 入账后 3 分 11 秒：[`0xfa05...6f36`](https://bscscan.com/tx/0xfa0557f8e2da6d827f73cec9557ba60f5898737efdc4165646242757059b6f36)，323,089 AKE，`0x73d8...46db -> 0x6aba...1b90`。
- 822.99M 入账后 5 分 9 秒：[`0x68b5...ce62`](https://bscscan.com/tx/0x68b5ee2c7d35455f0d453d0f399ee6d49abd692284e19c9b795ccd1827adce62)，70,322.2219445 AKE，同一路径。
- 972.54M 入账后 6 秒：[`0x62b6...7843`](https://bscscan.com/tx/0x62b6677cc9861ece58fa7525e65197bea58fcfe91a9809bdb88b0d8b030e7843)，479,101.9600125 AKE，同一路径。

这些记录只证明收款地址随后出现 AKE 出账；当前数据无法把任一出账归属于对应入账批次。

## 2026-07-24 公开来源补证

- `official`：[Binance Due Diligence Center 官方公告](https://www.binance.com/en-NG/square/post/326910236602705)说明该页面提供 exchange balances 等客观链上指标，数据按原样供参考。公告没有提供 `CEX wallet aggregation`、`Binance: Alpha Hot Wallet` 的字段词典、地址归属表或 TXID 生成规则。
- `onchain`：三笔 transaction、receipt 和 AKE `Transfer` log 均经核查；receipt 状态成功，token 合约与截图一致，精确数量分别为 `972,540,250`、`822,989,955`、`670,000,000` AKE，收款地址均为 `0x73d8...46db`。
- `explorer_metadata`：[BscScan 地址页](https://bscscan.com/address/0x73d8bd54f7cf5fab43fe4ef40a62d390644946db)显示 public name tag `Binance: Alpha 2.0 Router Proxy`，并描述其 Alpha Router 持币用途。这是第三方 explorer metadata，不能单独证明 Binance App 字段映射、托管性质或交易所归属。
- `market`：本轮没有发现可绑定截图行或解释字段语义的市场证据。
- `social`：Exa 返回第三方 AKE/Binance Alpha 讨论，内容没有绑定三条截图行，未用于提高证据等级。
- `inference`：日期、截图金额舍入区间、代币和目标地址各自对应一个 bounded candidate，用户提供的 App 跳转链接又逐条闭合了具体 UI-TXID 映射。本地 `Proxy/Custody`、`exchange_aggregator` 角色属于既有推断；通用标签词典、截图所指托管角色及经济目的保持 unresolved。运行分类保持 `alpha_custody_movement_unresolved / direction=unknown / runtime_effect=none / report_only`。

公开搜索使用 agent-reach 的 Exa/Jina 网页路径，查询并核查了完整目标地址、截图逐字标签、三个完整交易哈希、Binance Due Diligence Center 官方页面、BscScan 地址页和三个交易页。Exa 免费公共入口在完成上述成功查询后返回 HTTP 429；Jina 的匿名 Google 搜索返回 HTTP 403。搜索未使用登录态、私有 API、挑战绕过或逆向接口。

三条 Binance Alpha App `TXID` 用户动作已于 2026-07-24 完成，本案没有待补的截图行链接。

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
- 多笔直接进入已配置 CEX 地址、单笔均低于门槛的窗口聚合已于 2026-07-18 加入 coverage-gated 实现；2026-07-23 Gate 批次用于真实历史链上回放，生产首个自然样本继续 pending。
