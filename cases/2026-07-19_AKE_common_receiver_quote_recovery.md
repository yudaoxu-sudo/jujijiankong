# AKE 共同接收地址 quote recovery 与收益去向

- Case ID: `ake_common_receiver_quote_recovery_2026_07_19`
- Chain: BSC (`chain_id=56`)
- Token: `0x2c3a8ee94ddd97244a93bc48298f97d2c412f7db`
- Common receiver: `0x85401508c777321eed3018390408ad0ab2e087e5`
- Sell window: 2026-07-07 11:50:33–12:44:22 UTC
- Runtime effect: `none`; alert policy: `report_only`; deployment required: `false`

## 一句话判断

共同接收地址在 3,229 秒内通过 126 笔同模板交易确认卖出 `3,334,531,833 AKE`，所有 quote recovery 均直接回到该地址；随后 24 小时内回收资产几乎全部离开，主要去向为未标记 EOA `0x1929…5109`，共同控制与最终收益归属继续 unresolved。

## Receipt 级卖出核验

126/126 笔均满足以下 fail-closed 条件：

- receipt `status=1`；
- canonical AKE Transfer identity 唯一；
- AKE 从共同接收地址转出；
- USDT、USDC 或 WBNB 在同一 receipt 转入共同接收地址；
- transaction.from 为共同接收地址；
- transaction.to 为 `0x62cc…7dc`；
- quote token recipient 全部为共同接收地址。

Router 调用、余额下降与内部搬运没有被单独计为卖出。

## 卖出与回收汇总

| 项目 | 结果 |
| --- | ---: |
| confirmed sell tx | 126 |
| AKE sold | 3,334,531,833 |
| USDT recovered in sell receipts | 654,762.728839630414058477 |
| USDC recovered in sell receipts | 13.836135160552786937 |
| WBNB recovered in sell receipts | 0.25191193515094247 |
| weighted stable units / AKE | 0.0001963623674228666350972616430859546093 |
| median tx stable units / AKE | 0.0001985521928888073252275 |

`stable units / AKE` 只合并链上 USDT 与 USDC 单位。USD peg 与 WBNB/USD 价格没有独立市场证据，USD 隐含成交价保持 null。

## Metadata 与 dust

三个 quote token 的 `symbol()` 与 `decimals()` 均由公开 RPC `eth_call` 核验：USDT、USDC、WBNB 均为 18 decimals。USDT 是主回收资产；USDC 与 WBNB 作为 receipt 内伴随 dust 单列，没有按美元折算。

## 执行模板与节奏

- 126 笔 confirmed sells 的 selector 均为 `0xf2c42696`，transaction target 均为 `0x62cc…7dc`。
- sell nonce 覆盖 1–132 中的 126 个唯一值，按 canonical transaction order 严格递增。
- 缺少的 nonce 为 15、16、36、70、75、121：其中 1 笔 WBNB approval、4 笔 `0x01617fab` router 调用、1 笔失败的相同 sell selector。
- 相邻 confirmed sell 的时间间隔：最小 0 秒、中位 15 秒、最大 274 秒。
- 以上是地址级执行时钟、模板与分批事实，只支持 coordination evidence；所有权保持 unresolved。

## Quote 资产 24h/72h 去向

首笔 recovery 前三个 quote token 的 opening inventory 均为 0。24h 与 72h 余额核对结果相同：

| Token | 窗口总入 | 窗口总出 | 72h 留存 |
| --- | ---: | ---: | ---: |
| USDT | 654,912.505667795202899599 | 654,912.504551452698348149 | 0.00111634250455145 |
| USDC | 13.836135160552786937 | 13.836135160552786937 | 0 |
| WBNB | 0.25191193515094247 | 0.25191193515094247 | 0 |

窗口 USDT 入账比 126 笔卖出 receipt 的 USDT recovery 多 `149.776828164788841122 USDT`，来自后续非 AKE-sell transfer；窗口账与卖出 proceeds 分账。

七个 outbound canonical events：

- `0.017 WBNB` 分四笔经 `0x62cc…7dc` 进入未标记合约 `0x0b5f…9a48`。
- `0.23491193515094247 WBNB` 经 `0x62cc…7dc` 进入未标记合约 `0x33d2…db5b`。
- `13.836135160552786937 USDC` 经 `0x62cc…7dc` 进入未标记合约 `0xaa86…2b43`。
- `654,912.504551452698348149 USDT` 由共同接收地址直接调用 USDT `transfer`，发送至未标记 EOA `0x1929…5109`。

没有 quote outbound 到 reviewed senders、Alpha custody、tracked Alpha Router、OKX Router custody 或 configured CEX。四个目的地缺少独立实体归属；`0x1929…5109` 的再下一跳位于下一安全工作范围。

## Coverage

- 公开地址页：10/10 token pages、3/3 normal pages。
- token-page 唯一 tx：168；token ∪ normal 唯一 tx：174。
- 173 个成功 receipts、1 个失败 receipt。
- receipt 内共解析全部 Transfer logs，并重建 906 个触及共同接收地址的 canonical events；duplicate=0。
- 126/126 confirmed sell receipts 完整核验。
- quote asset ledger 从首笔 recovery 起包含 228 个 canonical events；其中 outbound 7 个。
- 24h boundary block `108782760`；72h boundary block `109166631`。
- 三个 token 的 opening/end historical balances 与窗口事件全部 reconciliation PASS。
- 未缓存 RPC 单次最多尝试三次；null result 计失败。

## 系统 gap analysis

现有 intraday receipt 逻辑能够识别一笔 configured-quote 的同 receipt 卖出。当前 AKE 不在 active watchlist，generic monitor 不会构建 AKE event。即使显式回放，默认最近 1,800 blocks、最多 120 receipts、20 秒 sampling budget 也不能保证覆盖 126 笔完整 batch；opening watch 默认 25 tx、4 buyers、每个 buyer 最近 3 笔 outgoing，同样无法重建整批。

现有 withdrawal cluster 面向 CEX fan-out，没有任意 sender fan-in → common receiver → quote recovery 的持久路径。该缺口真实存在；当前只有本案一组正向 fixture，普通零售汇入、custody/internal routing、无 quote recovery 转移、partial coverage 等反向 fixture 尚缺，因此本单元不修改运行逻辑或 verifier guard，也不更新 celue 规则。完整 gap 见 `input/ake_common_receiver_monitor_gap_analysis_2026-07-19.json`。

## 未解决项与下一安全工作

- `0x1929…5109` 接收主要 USDT proceeds 后的 24h/72h 下一跳与余额。
- 三个合约型 dust destination 的协议角色与资产用途。
- explorer `OKX: DEX Router 2` 标签的官方实体映射。
- 共同接收地址、senders 与收益接收方的所有权或共同控制。
- USD peg 与 WBNB/USD 同期价格。
- future runtime rule 所需正反 fixture 集。

## Evidence artifacts

- `input/ake_common_receiver_quote_recovery_2026-07-19.json`
- `input/ake_common_receiver_quote_recovery_ledger_2026-07-19.csv`
- `input/ake_common_receiver_quote_asset_events_2026-07-19.csv`
- `input/ake_common_receiver_quote_recovery_verification_2026-07-19.json`
- `input/ake_common_receiver_monitor_gap_analysis_2026-07-19.json`
