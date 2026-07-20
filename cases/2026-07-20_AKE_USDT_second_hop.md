# AKE sell-out USDT proceeds 第二跳 EOA 有界追踪（2026-07-20）

## 范围与锚点

- 上游：`0x1929fec1f9553dde93aa9ae57a4e4ac033e75109`
- 第二跳：`0xb8210c25df20921538ea35729badc3e0a63520f1`
- 锚点：`0xabcd5cc05c21a088e92d74b5a5bdafa25756b2206bf502472a325e8e2b7471f3:266`，block `108634007`，`2026-07-07T17:14:29+00:00`，`654912.504551 USDT`
- 锚点 receipt success；同 receipt 只有该笔 USDT Transfer；两端在锚点 code state 均为空。
- 硬停止边界：7 天；三个新出现的未标记 EOA 仅保存一层路径。

## USDT 账本与 FIFO

| 窗口 | 入账 USDT | 出账 USDT | ending USDT | proceeds lot remaining raw | 对账 |
|---|---:|---:|---:|---:|---|
| 24h | 654912.504551 | 0 | 654912.504551 | 654912504551000000000000 | PASS |
| 72h | 654912.50776777896013 | 654912.506013 | 0.00175477896013 | 0 | PASS |
| 7d | 654912.50836692496013 | 654912.506013 | 0.00235392496013 | 0 | PASS |

7 天内 target 的 proceeds lot 已按 FIFO 消耗完毕，资金被拆成 3 笔普通 `transfer`：

- `2026-07-10T05:28:38+00:00` `506483 USDT` → `0x3a36713f6a60cb32a66012f923602e9357191ea1` (`0xc53a3a441255fc513e5eaa3c915ef6f1341c92fdd433b31cba7f548315eec28a:276`, class=`unlabeled_eoa`, same-receipt quote=`False`)
- `2026-07-10T09:22:49+00:00` `85594 USDT` → `0x42d2138d26cd9317da1953d069ab305f3bdc7be0` (`0x15db0ea36fe55e0b9fbcf3e5f5463af4290681eadd4e31896b7255b58762c5e7:1266`, class=`unlabeled_eoa`, same-receipt quote=`False`)
- `2026-07-10T10:24:27+00:00` `62835.506013 USDT` → `0x25370535a60d5e1761639009a837e5d0fe0a28df` (`0xafa2633a3a227d0e55d91bbfaea5e330fe53cbc695a079198b07df38bd35f9e8:137`, class=`unlabeled_eoa`, same-receipt quote=`False`)

上述 receipt 未见 quote token 净流入，recipient 均为未标记 EOA，公开 code state 为空。本单元确认的是第二跳路径与拆分事实；经济处置、所有权、共同控制和最终受益人仍为 unresolved。

## Direct BNB 与 dust

- `0x1929fec1f9553dde93aa9ae57a4e4ac033e75109`：锚点前收到 direct BNB top-up；锚点 USDT transfer 的 gas 与 7d 历史余额方程对齐。
- `0xb8210c25df20921538ea35729badc3e0a63520f1`：收到 direct BNB top-up 后，以 nonce 顺序完成三笔 USDT transfer；direct value、gas 与 7d 历史余额方程对齐。
- direct-native 与 internal-native 分账；标准公开 RPC 不提供完整地址级 internal trace，本项保留 coverage gap。
- 固定 dust 阈值为 `0.01 USDT`。上游 dust 22 笔，target dust 62 笔；dust 全部参与余额和 FIFO。
- 78 笔 dust 同时匹配 focal 地址的前后缀，41 笔与对应大额转出呈精确整数缩放模板；时间差、方向、method 与 nonce 已逐笔保存。
- dust 可作为地址模仿或路由残留候选。它不能解释 native gas，也不构成共同控制证据。

## Runtime gap 结论

本单元增加了 proceeds 第二跳拆分正例，以及 pure-transfer/no-quote、dust、direct-native 与 partial internal-native 反例。现有路径与 FIFO 模型能够保存事实，swap guard 也保持 fail-closed。fixture 仍未覆盖 CEX、DEX、bridge、custody 闭合和完整 internal-native 对照，因此保持纯证据更新，不修改 runtime/verifier，不部署。

## Coverage

- USDT 来源：BscScan 全地址 token 页 page 1 短页 + page 2 空页，逐 tx receipt 重建，canonical identity=`chain:token:tx_hash:log_index`。
- Normal tx 来源：两端 BscScan 全地址 normal 页 page 1 短页 + page 2 空页；只对 anchor 前 1h 至 7d 边界内的行做逐 tx/receipt/block-position 核验，范围外行仅保存计数与整组 hash。
- 24h/72h/7d 使用历史 `balanceOf` 与双 FIFO replay；所有窗口对账 PASS。
- provider 相同查询最多三次；missing pages、receipt mismatch、canonical identity conflict 均为 0。
- current code 是任务要求的窗口外补充，只核验上游与 target 两端且不参与 7d FIFO 或路径分类。
- coverage gaps：internal-native；三个新未标记 EOA 之后的递归路径；公开标签不证明所有权。

## Artifacts

- `input/ake_usdt_second_hop_2026-07-20.json`
- `input/ake_usdt_second_hop_ledger_2026-07-20.csv`
- `input/ake_usdt_second_hop_dust_native_2026-07-20.json`
- `input/ake_usdt_second_hop_runtime_gap_2026-07-20.json`
- `input/ake_usdt_second_hop_verification_2026-07-20.json`
