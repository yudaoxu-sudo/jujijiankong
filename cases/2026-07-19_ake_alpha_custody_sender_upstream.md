# AKE Alpha Custody Sender Upstream and Funding Review

Date: 2026-07-19

## 结论

三笔锚点的发送方均为 root block 前后和 latest 状态下无代码的地址。三笔交易 `transaction.from` 与 AKE `Transfer.from` 一致，receipt 均成功，AKE 合约为 `0x2c3a...f7db`、18 decimals，精确 `(txHash, logIndex)` 已从官方 BNB RPC receipt 恢复。

三个地址在各自 pre-90d 窗口开始时 AKE 余额均为 0；窗口内净流入分别为 670,000,000、822,989,955、972,540,250 AKE，正好等于锚点前余额。锚点出账后余额均为 0。它们在锚点之前已经多次把 AKE 送到 tracked `0x73d8...46db`：

- `0xb40b...1395`：7 笔，合计 6,804,650,296.040711 AKE。
- `0xd49e...9f04`：15 笔，合计 5,985,746,343.64 AKE。
- `0x6449...5a48`：5 笔，合计 2,990,000,000 AKE。

地址级模式支持“持续收集并派发 AKE”的观察结论。所有权、共同控制者、托管用途和三笔锚点的经济目的继续 unresolved；余额清零与转入 Alpha custody 本身不形成卖出证据。

锚点后仍有新 AKE 活动：`0xb40b...1395` 在 24h 内无新事件，72h 内收到 2.657B、发出 810M、留存 1.847B；`0xd49e...9f04` 在 72h 内收到并发出 1,250,999,956 AKE，终点余额为 0；`0x6449...5a48` 在 24h 内收到并发出 2.084B AKE，终点余额为 0。`0xd49e...9f04` 的后续新库存中有一笔已确认小额 DEX 卖出：`0x82f5...a5aeb` 在同一成功 receipt 中转出 468,122.312108732164712799 AKE、收到 100 BSC USDT，transaction target 是 tracked PancakeSwap Infinity Universal Router。该 sender 在锚点后已为零余额，sender-window FIFO 把该卖出归因给后续可见库存，没有建立它与 822,989,955 AKE 锚点 lot 的链接。本单元依然保持 `runtime_effect=none / report_only`。

## 三笔锚点

| 日期 | 发送方 | TX / log | AKE | 锚点前余额 | 锚点后余额 | code state |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 2026-07-04 10:58:07.650 UTC | `0xb40b...1395` | `0x288e...8f87` / 330 | 670,000,000 | 670,000,000 | 0 | root-1/root/latest 均 empty |
| 2026-07-05 10:25:35.250 UTC | `0xd49e...9f04` | `0x4b2d...5af8` / 420 | 822,989,955 | 822,989,955 | 0 | root-1/root/latest 均 empty |
| 2026-07-07 08:46:34.150 UTC | `0x6449...5a48` | `0x7321...1727` / 218 | 972,540,250 | 972,540,250 | 0 | root-1/root/latest 均 empty |

空 bytecode 仅表示对应状态快照没有合约代码，不提供私钥控制者或实体身份。

## 30d / 90d 与发送后 24h / 72h

窗口左闭右开；root event 单列，pre 窗口在 root order 前结束，post 窗口从 root order 后开始。嵌套窗口不可相加。

| sender | pre-90d 入 / 出 / 净 | pre-30d 入 / 出 / 净 | post-24h 入 / 出 / 净 / 终点 | post-72h 入 / 出 / 净 / 终点 |
| --- | ---: | ---: | ---: | ---: |
| `0xb40b...1395` | 7,474,650,296.040711 / 6,804,650,296.040711 / +670,000,000 | 1,194,816,312.420711 / 524,816,312.420711 / +670,000,000 | 0 / 0 / 0 / 0 | 2,657,000,000 / 810,000,000 / +1,847,000,000 / 1,847,000,000 |
| `0xd49e...9f04` | 6,808,736,298.64 / 5,985,746,343.64 / +822,989,955 | 2,363,989,883 / 1,540,999,928 / +822,989,955 | 0 / 0 / 0 / 0 | 1,250,999,956 / 1,250,999,956 / 0 / 0 |
| `0x6449...5a48` | 3,962,540,250 / 2,990,000,000 / +972,540,250 | 2,962,540,250 / 1,990,000,000 / +972,540,250 | 2,084,000,000 / 2,084,000,000 / 0 / 0 | 2,084,000,000 / 2,084,000,000 / 0 / 0 |

12 个窗口均满足 `opening balance + observed net = ending balance`；三个 root block 的 `just-before balance - root amount = just-after balance` 也全部成立。

## 首次可见 AKE 与上游来源

公开地址索引当前页数已完整抓取，以下为该索引中的首次 AKE event：

- `0xb40b...1395`：2026-04-14 13:26:14.900 UTC，`0xa663...0321 -> 0xb40b...1395`，100,000 AKE；来源未命中 tracked label。
- `0xd49e...9f04`：2026-04-11 13:06:11.750 UTC，`Gate 1 Hot Wallet 0x0d07...92fe -> 0xd49e...9f04`，99,151.82 AKE；tracked class 为 `cex_hot_wallet`，证据源为项目 global labels，路径保持 CEX 中性。
- `0x6449...5a48`：2026-04-17 06:45:21.250 UTC，`0xd47b...2a1e -> 0x6449...5a48`，100,000 AKE；来源未命中 tracked label。

pre-90d 聚合没有出现跨两个发送方的精确共同 AKE 来源，没有同一交易向多个发送方分拆 AKE，也没有可比较的共同来源时间同步/近似分拆对。各发送方的完整 source 地址、金额、tx/log identity、role 和 evidence 均保存在结构化 JSON 与 canonical CSV。

未标记来源继续记为 `unlabeled_address`。未观察到 AKE 从 zero address 或 token contract 直接进入三发送方；因此本窗口没有 mint 直达证据。

## 直接 BNB 资金来源

BscScan normal transaction 公共页共 8 页、320/320 行。六笔正值直接入账均由官方 BNB RPC 复核 `from/to/value/input=0x/status=1/gasUsed=21000`：

| recipient | direct funder | BNB | TX | BscScan metadata label |
| --- | --- | ---: | --- | --- |
| `0xb40b...1395` | `0x515b...33c8` | 0.01611376 | `0xa4a5...712f` | Binance: Hot Wallet 12 |
| `0xb40b...1395` | `0xe4cd...128f` | 0.0000001 | `0xdf7c...b993` | unlabeled |
| `0xd49e...9f04` | `0x8894...d4e3` | 0.00299029 | `0x4c7b...20d6` | Binance 51 |
| `0xd49e...9f04` | `0x161b...b645` | 0.00703736 | `0x473c...00e1` | Binance: Hot Wallet 11 |
| `0xd49e...9f04` | `0xe2fc...3ae1` | 0.00293103 | `0xba7d...7d6c` | Binance: Withdrawals 7 |
| `0x6449...5a48` | `0xdccf...a75a` | 0.01498875 | `0x7695...f401` | Binance: Withdrawals 2 |

三个 recipient 的精确 direct-funder 地址交集为空。表内 Binance 名称全部来自 BscScan explorer metadata；官方 Binance 所有权、共同经济实体和用途没有闭合。normal transaction 页不覆盖 Internal Txns/trace，contract-mediated BNB funding 保持 coverage gap。

`0xd49e...9f04` 还在两个 sender 向共同目的地 `0x8540...87e5` 转 AKE 的紧邻时段内，向该目的地直接发送 0.001 BNB（`0x5209...6e89`，11:38:58 UTC）和 0.0005 BNB（`0x5aea...1642`，11:41:10 UTC）。两笔均由官方 BNB RPC 复核 `from/to/value/input=0x/status=1/gasUsed=21000`。

## 后续去向分类

- `0xb40b...1395`：锚点后 72h 的唯一 AKE 出账目的地是 tracked `0x73d8...46db`，810M AKE；Alpha custody/report-only。
- `0xd49e...9f04`：锚点后 72h 向未标记 `0x8540...87e5` 转出 1,250,531,833.687891267835287201 AKE；另一笔 468,122.312108732164712799 AKE 出账所在交易命中 tracked PancakeSwap Infinity Universal Router，同 receipt 有 100 BSC USDT 回流，分类为已确认 DEX 卖出。
- `0x6449...5a48`：锚点后 24h 的 AKE 出账去了未标记 `0x8540...87e5`，2.084B AKE；角色 unresolved。

`0x8540...87e5` 是两个发送方的共同后续目的地。`0x6449...5a48` 的两笔 AKE 与 `0xd49e...9f04` 的一笔 AKE 在 121.5 秒内到达，其间和之后还有上述两笔直接 BNB 转账。这组地址级原始证据支持 `coordination_candidate=true`。该地址没有 tracked label，common control 和实体所有权保持 unresolved。其他大额余额减少继续按库存变化记录。

## 标签边界

`0x73d8...46db` 继续使用 `config/global_address_labels.json` 中的 `Binance Alpha 2.0 Proxy/Custody / exchange_aggregator`。依据仍是 2026-06-29 Phalcon nested-call review。此次 BscScan 页面显示 `Binance: Alpha 2.0 Router Proxy`，截图显示 `Binance: Alpha Hot Wallet`；两个 UI 文案均没有写回 tracked role。

三个发送方在 tracked global labels 中均无匹配。BscScan 的 Binance/Gate 文案按 explorer metadata 单列，不承担官方所有权证明。

## 覆盖、分页与去重

- BscScan token pages：9/9 complete；773 条全部 token transfer，101 条精确 AKE contract rows，101 个 unique tx。每页 HTML 精确 `/token/0x2c3a...f7db` 链接的 tx-hash multiset 与 quick export 中 AKE 行完全相等。
- Canonical ledger：101 个事件；identity 为 `(chainId, token, lower(txHash), logIndex)`；重复 0、冲突 0、removed 0。
- Official receipt：101/101 可用，101/101 status success，101/101 from/to/block 与公开行唯一匹配，receipt 内精确 log 恢复完成。
- BscScan 的两行显示金额存在截断/精度丢失；canonical amount 使用 receipt `Transfer.data` 原始整数，两个公开显示差异逐项保存在 summary。
- Secondary logs：Nodies 对三个 root 各做 inbound/outbound 100-block 抽样，6/6 与 canonical ledger 逐字段相等。
- Historical state：三个 root 的 AKE contract code 与 decimals 全部可用；12 个窗口余额和 3 个 root transition 全部闭合。
- BscScan normal pages：8/8 complete，320/320 rows；6 笔正值 direct funding 全部由官方 RPC 复核。
- Internal native traces 未覆盖，明确记录为 partial；未开展重型全链扫描。

## 证据分层与运行边界

- `official`：BNB Chain public RPC 用于 transaction、receipt、block timestamp、contract code、decimals 和 historical state。
- `public explorer`：BscScan 无登录 HTML 只用于完整地址分页与 explorer metadata；tx/log identity、金额和成功状态由 receipt 复核。
- `tracked`：项目 global labels 提供目标 Alpha custody 和 Gate 1 Hot Wallet 的既有角色及证据文本。
- `inference`：持续派发、共同路径和协调候选仅描述已观察到的地址级行为；实体所有权、common control、托管用途和外部经济流入保持 unresolved。小额 DEX 卖出由同 receipt 的 AKE 出账、quote token 回流和 tracked router 闭合，与三笔锚点 lot 分开归因。

本单元只有证据与 case 更新；规则、运行逻辑、Telegram、签名、广播和交易执行均未改变，deployment_required=false。

## Artifacts

- Summary: `input/ake_alpha_custody_sender_upstream_2026-07-19.json`
- Canonical AKE ledger: `input/ake_alpha_custody_sender_upstream_events_2026-07-19.csv`
- Raw public token pages: `input/ake_sender_token_txs_bscscan_2026-07-19.json`
- Raw public normal pages: `input/ake_sender_native_normal_txs_2026-07-19.json`
