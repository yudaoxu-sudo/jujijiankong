# CEX micro-gas report-only 取证轮转（2026-07-23）

## 结论

- 新增 verified positive roots=`0`，新增 positive tokens=`0`。
- 当前门槛保持 positive roots `1/3`、positive tokens `1/2`、complete negatives `3/3`。
- 远端 fresh latest 在 `2026-07-23T15:25:45Z`、部署后 dry-run `15:59:14Z` 与最终代码生产 cron `16:10:56Z` 均为 `event_count=0`。该结果只覆盖对应 latest 窗口；`2026-07-22` 之后的完整历史覆盖仍不可用。
- 现有采样链存在可测试字段缺口，因此已部署最小 report-only acquisition patch。动作阈值、`analyze_rows`、alert key、Telegram 与交易语义保持原值。

## 证据分层

| 类型 | 结论 | 状态 |
|---|---|---|
| official | runtime 输出中没有新的官方候选 anchor | observation |
| onchain | fresh latest 当前窗口为 0；完整历史未保存 | blocked |
| market | 没有候选 token 窗口 | not_collected |
| social | 没有候选 root | not_collected |
| inference | 本轮不能增加正例分母；后续自然候选需要持久化配对证据 | observation |

## 字段审计

旧路径只持久化 `cex_gas_priming_count / bnb / sources`。gas 逐笔 from/to/value/block/tx 只存在于内存，默认 `0.001 BNB` 动作阈值会过滤真实校准样本中的约 `3e-6 BNB` 微额 top-up；configured aggregate 与 runtime candidate aggregate 也把 gas 字段固定为 0。token ingress 的全量 Transfer 层已有 tx/log/block/normalized amount 与 coverage，raw amount、decimals、receipt、timestamp、严格排序、配对歧义和独立性没有贯通到持久化样本。

## report-only acquisition

新增 event 顶层 `report_only_cex_micro_gas_samples`，候选历史写入：

`output/alpha_intraday_flow_watch/cex_micro_gas_candidate_history.json`

边界如下：

- 每个 event 每轮最多审查 5 个 token-ingress 窗口，全部 RPC 与多 URL 重试共享 4 秒取证预算。
- history 按稳定 `candidate_id` 去重，最多保留 200 条；空轮不清除历史。
- native 保存 tx/from/to/value/block/transactionIndex/time/receipt/source-label provenance。
- token 保存 tx/log/contract/decimals/raw+normalized amount/from/to/block/transactionIndex/time/receipt。
- pairing 保存严格顺序、秒级窗口、全部 gas identities、唯一性、歧义、coverage 与 independence。
- 每条固定 `status=blocked`、`alert_policy=report_only`、`runtime_effect=none`、`action_guard=no_runtime_action_mutation`。
- bounded zero 写为范围内未形成候选，不扩展成链上 absence。

## 回归与部署

- Project verifier：`190 PASS / 0 FAIL`。
- Celue audit：`101 PASS / 0 FAIL`。
- 本地 dry-run：`events=0 alerts=0`。
- 远端 verifier：`0 FAIL`。
- 远端显式禁用 Telegram 的 dry-run：`events=0 alerts=0`。
- 最终代码生产 cron：intraday `16:10:56Z`，runtime health `16:11:04Z`，healthy、0 issues。
- 远端四个部署源文件 SHA 与本地逐一一致；Remote acceptance PASS，0 issues / 0 advisories。
- 没有签名、交易或 Telegram 发送。

## 等待条件

下一次升级正例需要自然 candidate 携带完整 native/token coverage、成功 canonical receipts、exact CEX label provenance、严格 timing、唯一配对与 root operator linkage。剩余目标仍是两个额外独立 positive roots，并覆盖至少一个额外 token。

机器证据：`input/cex_micro_gas_acquisition_rotation_2026-07-23.json`
