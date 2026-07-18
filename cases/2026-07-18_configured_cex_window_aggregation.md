# Configured CEX Window Aggregation

Date: 2026-07-18

## 结论

已关闭一个明确的盘中 CEX 流入漏报边界：同一完整扫描窗口内，多笔转账分别低于单笔 token/quote 门槛，直接进入已配置 CEX deposit 或 hot wallet 时，窗口合计现在会进入既有 CEX 风险门槛。

结构化验证证据保存在 `input/configured_cex_window_aggregation_verification_2026-07-18.json`。

## 漏报复现

旧数据流只把抽样 receipt row 和 runtime-candidate FIFO 聚合送入 `analyze_rows`。`summarize_flow_tx` 会在每个 tx 内单独检查 CEX 门槛，因此跨 tx 的 `60,000 + 60,000` token 均被过滤；即使完整窗口合计 `120,000` token 已超过 `100,000` token 门槛，窗口分析仍看不到这批流入。

验证先引用缺失的新聚合入口，旧实现按预期失败；实现完成后，同一 fixture 在完整 coverage 下得到 `120,000` token、2 个唯一日志、2 个 tx，并触发既有 CEX 风险判断。

## 最小实现

1. `token_transfer_logs_with_coverage` 返回后，窗口日志先按 `(transactionHash, logIndex)` 中央去重。
2. runtime candidate、withdrawal cluster、直达配置 CEX 聚合和 forward evidence 共用唯一日志集。
3. 缺失 tx/log 身份或同一锚点内容冲突时，本窗口 coverage 关闭，所有窗口聚合风险贡献归零。
4. `configured_cex_inflow_aggregate_rows` 复用现有 CEX 路径分类，只接收 `runtime_effect=cex_inflow_risk` 的直达配置 CEX 路径。
5. 已由 receipt row 计入 CEX 的 tx 整笔排除，防止大额单笔再次被窗口日志累计。
6. coverage 必须与本次扫描的起止块完全吻合、覆盖到窗口末端、未到日志上限，且日志身份有效。
7. coverage 不完整时保留 observed amount/count，风险 amount/quote/count 固定为零。

## 去重与归因边界

- 同一 tx 的不同 `logIndex` 都保留。
- 完全相同的 `(tx, logIndex)` 只计一次。
- 同一锚点内容冲突时 fail closed。
- `external -> runtime candidate` 继续属于 `aggregate_only`。
- `runtime candidate -> configured CEX` 继续属于 `cex_internal_aggregation`。
- runtime candidate 的风险金额继续只来自有序 FIFO 消耗的窗口内外部入账。
- `cex_deposit/hot -> cex_deposit/hot` 和 Alpha custody 路径继续中性、report-only。

## 回归矩阵

| 场景 | 预期结果 |
| --- | --- |
| 完整 coverage、跨块两笔 60k | 合计 120k，2 logs / 2 tx，触发 token 门槛 |
| 不完整 coverage | observed 保留；风险 amount/count 为 0；无 Telegram alert key |
| 重复 tx/log | 重复日志只计一次；同 tx 不同 log 保留 |
| 缺失或冲突日志身份 | coverage invalid；窗口风险贡献归零 |
| 150k receipt + 120k residual | 精确合计 270k、count 3 |
| 跨块两笔内部 CEX 搬运 | 风险为 0；保持 report-only |
| runtime candidate 80k + direct 120k，且 candidate logs 重复 | 中央去重后合计 200k、count 3、candidate count 1 |
| Telegram | 只出现一条既有 CEX 精简摘要；无地址、coverage 或聚合诊断字段 |

## 验收

- 定向验证：旧实现失败，新实现通过。
- 完整 sniper verifier：`190 PASS / 0 FAIL`。
- celue integration audit：`101 PASS / 0 FAIL`。
- `git diff --check`：通过。

## 安全与剩余边界

- 系统保持只读、无签名、无交易执行。
- Telegram 不增加地址、tx 或 coverage 明细。
- 窗口开始前库存继续未知。
- 仍需等待首个自然出现的多笔直达配置 CEX 小额聚合样本。
- Binance Alpha Hot Wallet 的三条 UI 记录仍需用户从 App 提供精确 TXID。
