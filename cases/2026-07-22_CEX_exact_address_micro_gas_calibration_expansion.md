# CEX exact-address 与 micro-gas 校准扩充（2026-07-22）

## 结论

- 从 tracked 候选语料中只选择 `3` 个候选；外部来源均未超过 `3` 次重试。
- 新增 `2` 个独立完整负对照：Bybit-funded `0x771c...2497` 与 Gate-funded `0xad7d...1a14` 都在原生币入账后由目标地址主动完成 DEX 交易并收到代币，证明 CEX 来源原生币不能独立建立 CEX custody 或动作语义。
- Gate -> `0x9c94...e442` -> Binance 近额转发路径为 `blocked`：canonical path 完整，account ownership、custody purpose、common control 与 ultimate beneficiary 未解，不计正例或负例。
- 更新后的门槛为：独立正样本 roots `1/3`、正样本 tokens `1/2`、独立完整负对照 `2/3`。决策仍为 `calibration_gap_no_runtime_change`；runtime、verifier、celue 与部署均不变。

## 证据分层

| 状态 | 类型 | 候选 | 公开标签/链上事实 | 结论 |
|---|---|---|---|---|
| verified | onchain + inference | `0x771c...2497` | Bybit Hot Wallet 转入 `0.38077165 BNB`；`216s` 后目标主动执行成功交易，投入 `0.37 BNB` 并收到 `Crocodile` | 独立非托管负对照 |
| verified | onchain + inference | `0xad7d...1a14` | Gate 1 转入 `0.0145971 BNB`；`206s` 后目标调用 `OKX: DEX Router 2`，投入 `0.007 BNB` 并收到另一代币 | 独立非托管负对照 |
| blocked | onchain + inference | `0x9c94...e442` | Gate 1 转入 `0.486198 BNB`；`446s` 后向 Binance 51 转出 `0.48616045925 BNB` | CEX-to-CEX route 已验证，经济归因未解 |

本轮没有 official 或 social 证据；market 数据与样本分类无关。exact-address BscScan 页面只用于标签绑定，canonical transaction、receipt、block timestamp 与 ERC-20 Transfer log 由公开 BSC JSON-RPC 复核。

## 独立性

两条 verified negatives 的 exchange、root/operator、event window 与 received token 均不同。`0x9c94...e442` 不进入统计分母。它们也不与 AKE/USDT/Bitget 正样本共享 root、窗口或 exchange。

## 适用边界

两条负例的 CEX 原生币入账金额均高于 runtime 默认 `0.001 BNB`，因此能验证 source-class/custody semantics guard，不能估计 micro-gas threshold 的 FPR，也不能补充低于阈值的独立正样本。micro-gas 继续只作 corroboration，必须与 exact-address CEX 标签、后续 token ingress、canonical receipts、严格时序和完整事件窗口证据组合；单独不得产生买卖、跟随、减仓或其他动作语义。

## 产物

- 机器证据：`input/cex_exact_address_micro_gas_calibration_expansion_2026-07-22.json`
- 基线：`input/cex_exact_address_micro_gas_calibration_2026-07-22.json`
- tracked 候选源：`input/cex_sweep_manual_review_2026-07-08.json`

本轮为纯证据更新，不部署。
