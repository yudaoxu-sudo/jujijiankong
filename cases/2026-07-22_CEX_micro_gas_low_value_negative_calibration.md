# CEX micro-gas 低额负对照校准（2026-07-22）

## 结论

- 本轮只从 tracked 语料筛选 `5` 个候选。
- 新增一个独立完整低额负对照：`0xd49e...9f04` 先向 `0x8540...87e5` 转入 AKE，`58` 秒后再转入 `0.0005 BNB`。native event 晚于 token ingress，source exact-address 页面无 CEX 标签，同时失败 ordering 与 source-class 两道门。
- 新增一个 verified correlated temporal control：Gate `0.000125 BNB` 在 `654,912.504551452698348149 USDT` ingress 后 `13,552` 秒到达，随后 `320` 秒发生 USDT outbound。该路径属于既有 AKE proceeds 谱系，不增加独立分母。
- 当前门槛为 positive roots `1/3`、positive tokens `1/2`、complete negatives `3/3`。总门槛仍未满足，结论保持 `calibration_gap_no_runtime_change`；runtime、verifier、celue 与部署均不变。

## 状态与证据分层

| 状态 | 候选 | official | onchain | inference |
|---|---|---|---|---|
| verified independent negative | AKE ingress 后 `0.0005 BNB` | 无 | 两笔 canonical successful receipts；严格晚 `58s`；source/target exact-address 无 CEX 标签；tracked token/native pages 完整 | post-ingress 且 non-CEX source，不能成为正例 |
| verified correlated control | USDT ingress 后 Gate `0.000125 BNB` | 无 | 三笔 canonical successful receipts；gas 晚于 ingress `13,552s`；完整 normal pages 与 24h/72h/7d native 方程 | 时序负例成立，与既有 AKE proceeds root 相关，不计独立样本 |
| blocked | `0.001 BNB` 位于多个 AKE ingress 之间 | 无 | 金额、receipts、时序可复核 | 配对不唯一 |
| blocked | `0.0000001 BNB` dust | 无 | canonical tx 可复核 | 无完整短事件窗口与 CEX label |
| observation | `0.000000001 BNB` post-outbound dust | 无 | canonical post-outbound 时序完整 | 与既有 AKE root 相关 |

本轮 market 与 social 层没有影响样本分类的证据。

## 独立性与边界

新增独立负例的 token=`AKE`、operator=`0xd49e...9f04`、event window=`2026-07-07T11:40:12Z–11:41:10Z`、exchange class=`none/unlabeled`，与既有 Bybit/Gate 非托管负例均不同。Gate `0.000125 BNB` 路径沿既有 AKE sell-proceeds 谱系进入后续 USDT/Bitget 分支，因此只作相关时序控制。

负例门槛已经满足；正例仍缺 `2` 个独立 roots，并需至少覆盖另一个 token。没有达到全门槛，不评估 report-only runtime 接入。

## 产物

- `input/cex_micro_gas_low_value_negative_calibration_2026-07-22.json`
- tracked 基线：`input/cex_exact_address_micro_gas_calibration_expansion_2026-07-22.json`

本轮为纯证据更新，不部署。
