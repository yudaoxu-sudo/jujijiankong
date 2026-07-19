# AKE 共同接收地址下一跳取证

- Case ID: `ake_common_receiver_forensic_2026_07_19`
- Chain: BSC (`chain_id=56`)
- Token: `0x2c3a8ee94ddd97244a93bc48298f97d2c412f7db`
- Address: `0x85401508c777321eed3018390408ad0ab2e087e5`
- Evidence window: anchor 前 30 天、后 24 小时、72 小时、7 天
- Runtime effect: `none`; alert policy: `report_only`; deployment required: `false`

## 结论

三笔锚点 AKE 在 121.5 秒内从 `0x6449…5a48` 与 `0xd49e…9f04` 进入共同接收地址，合计 `3,334,531,833.687891267835287201 AKE`。地址在首笔锚点前的 opening balance 为 0；首个可验证下一跳发生于首笔锚点后 742.25 秒，交易调用 explorer 标记的 `OKX: DEX Router 2`，同一成功 receipt 内转出 AKE 并收回 WBNB 与 BSC USDT。此后 126 笔交易合计转出 `3,334,531,833 AKE`，每笔都满足成功 receipt、精确 AKE log identity 与同 receipt quote recovery，故归类为明确 swap/卖出路径。

7 天窗口结束时 FIFO 可归因留存为 `0.687891267835287201 AKE`。这项 FIFO 是账务归因；经济所有权、地址所有权与共同控制仍为 unresolved。

## 锚点与伴随 BNB

| 来源 | tx / log | 时间 UTC | AKE |
| --- | --- | --- | ---: |
| `0x6449…5a48` | `0x5161…72c9 / 398` | 2026-07-07 11:38:10.750 | 100,000 |
| `0x6449…5a48` | `0x0f6b…62a9 / 372` | 2026-07-07 11:39:29.050 | 2,083,900,000 |
| `0xd49e…9f04` | `0xf5c8…1908 / 187` | 2026-07-07 11:40:12.250 | 1,250,531,833.687891267835287201 |

`0xd49e…9f04` 另有两笔成功的顶层 direct-native BNB 转账进入共同接收地址：11:38:58 的 `0.001 BNB` 与 11:41:10 的 `0.0005 BNB`。两笔均为 `input=0x`、`gasUsed=21000`。Internal-native 地址历史没有完整公共覆盖，保持 coverage gap。

## 窗口与 FIFO

| 窗口 | 入账 AKE | 出账 AKE | 净额 AKE | 余额核对 |
| --- | ---: | ---: | ---: | --- |
| 锚点前 30d | 0 | 0 | 0 | PASS |
| 锚点后 24h | 3,334,531,833.687891267835287201 | 3,334,531,833 | 0.687891267835287201 | PASS |
| 锚点后 72h | 3,334,531,833.687891267835287201 | 3,334,531,833 | 0.687891267835287201 | PASS |
| 锚点后 7d | 3,334,531,833.687891267835287201 | 3,334,531,833 | 0.687891267835287201 | PASS |

Opening inventory 与候选 lot 分账，opening inventory 为 0。FIFO 按链上时间单向消费；后到资金只追加新 lot，没有倒灌早期 outflow。

## 最早下一跳与主要对手方

最早 outbound 为 `0xd324…155a`（block `108590877`，2026-07-07 11:50:33 UTC）。交易目标为 `0x62cc…7dc`；receipt 中共同接收地址累计转出 `30,000,000 AKE`，并收到 `0.029840656100938402 WBNB` 与 `5,445.460401442625336132 BSC USDT`。

AKE outbound 的三个直接 log destination 均为有代码合约：

- `0xdd3d…6e1f`: `2,526,473,810.5304 AKE`，517 events / 126 tx；未进入 tracked labels。
- `0x7a7a…97ff`: `803,698,022.316 AKE`，141 events / 103 tx；未进入 tracked labels。
- `0xaa86…2b43`: `4,360,000.1536 AKE`，4 events / 4 tx；未进入 tracked labels。

所有 126 笔确认 swap 的 transaction target 均为 `0x62cc…7dc`。该地址的 `OKX: DEX Router 2` 名称来自 explorer 页面；tracked global label 尚未独立确认该实体映射。

## 明确目的地检查

在 665 个 canonical AKE events 的覆盖内，没有发现回流到三个 reviewed senders、`0x73d8…46db` Alpha custody、tracked Alpha Router、configured CEX 或零地址。三个 outbound destination 均为未标记合约。余额下降本身没有被用作卖出证据。

## Coverage 与 fail-closed 核对

- BscScan token address pages: 10/10 页，906 rows；其中精确 AKE contract 665 rows。第 4 页使用 agent-reach Jina 页面缓存，其余 9 页为 direct HTML cache。
- BscScan normal transaction pages: 3/3 页，139 个唯一交易。
- 公开 RPC address-topic scan: block `108589242..108598015`，inbound/outbound 各 36 个连续 250-block 分片，完整；665 raw logs / 665 canonical logs。
- Canonical key: `chain_id + token + lower(tx_hash) + log_index`；duplicate=0，identity conflict=0，removed=0。
- 129 个唯一交易 receipt 全部成功；665 个事件逐 log 与 receipt 精确匹配；mismatch=0。
- 5 个二级 receipt 抽样覆盖三笔锚点、第一笔和最后一笔 swap；status、block 与 decoded Transfer logs 全部一致。
- 地址在锚点前、锚点块、7d 后和 latest 的 code state 均为 empty。
- 历史余额锚与四个窗口全部核对通过。
- CSV block timestamp 来自整数秒 RPC block header；scope anchor 保留 explorer 的毫秒时间。窗口归属必须使用报告中的 block boundary，不能用 CSV 时间字符串重新切分；边界时间精度缺口不超过 1 秒。

## 未解决项

- 共同接收地址与两个 sender 的实体所有权、共同控制关系。
- FIFO token unit 的经济所有权。
- Internal-native 与合约内 BNB funding 的完整地址历史。
- `OKX: DEX Router 2` explorer label 的独立官方实体映射。
- quote assets 离开共同接收地址后的用途。

## Evidence artifacts

- `input/ake_common_receiver_forensic_2026-07-19.json`
- `input/ake_common_receiver_events_2026-07-19.csv`
- `input/ake_common_receiver_public_index_2026-07-19.json`
