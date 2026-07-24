# CEX micro-gas 校准语料身份门（2026-07-24）

## 结论

- 已为现有校准语料定义 canonical independence key 与 observation key。
- 当前计数保持 positive roots `1/3`、positive tokens `1/2`、complete negatives `3/3`。
- 两条 Bitget 6 正例分支共享同一 token、root operator、exchange entity 和事件窗，因此只计一个正例 root。
- 三条负例的 token、root operator、exchange entity 和事件窗互相独立，继续计为三个 complete negatives。
- blocked、observation-only、correlated 与 synthetic 记录不进入 `counted_units`。
- 本单元只增加离线证据 gate；runtime、阈值、动作、告警和 Telegram 均未改变。

## 身份规则

- Independence key：`chain_id + token_contract + root_operator + exchange_entity + event_window_start_utc + event_window_end_utc`。
- Observation key：`chain_id + native_tx_hash + token_or_execution_tx_hash + token_log_index`。
- 每个计数单元必须绑定一个 Git tracked 源记录。
- 每个 independence key 与 observation key 在计数语料中必须唯一。
- 地址和 token contract 使用 chain 56 小写 canonical 地址。

## 当前边界

语料身份和去重规则已经闭合。阈值升级仍需两个额外独立 positive roots，并覆盖至少一个额外 token；自然候选仍需完整 receipts、log identity、exact label provenance、严格时序与唯一配对。

机器证据：`input/cex_micro_gas_calibration_corpus_2026-07-24.json`
