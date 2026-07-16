# KOL Strategy Intake Prompt

用途：让 Codex、Manus 或其他外部 agent 抓取 KOL 帖子、项目案例、交易复盘，并按可验证格式交付给 `$celue`。这个模板只负责采集和蒸馏输入，不直接生成买卖结论。

把下面整段复制给外部 agent：

```text
请帮我抓取并分析指定 X/Twitter 账号或帖子集合，用于链上狙击监控系统的长期策略库。

目标账号或链接：
- <填账号，例如 https://x.com/handle>
- <填帖子链接或搜索条件>

抓取范围：
1. 默认抓最近 300-500 条公开帖子；如果账号历史较短，抓完整可见历史。
2. 去重 retweet、重复转发和无正文引用；保留 quote、thread、图片/OCR、视频摘要和外链。
3. 记录抓取时间、账号、帖子数量、时间覆盖范围、原始文件路径或下载包路径。
4. 不要抓取私信、cookie、验证码、非公开内容、付费墙内容或任何敏感凭证。

输出必须包含五个文件或五个清晰分区：

第一部分：raw source manifest
- account / source url
- fetched_at_utc
- post_count_raw
- post_count_deduped
- time_range_start_utc
- time_range_end_utc
- raw_json_or_csv_path
- media_ocr_path
- tool_name_and_version

第二部分：method index
请用 Markdown 表格输出可复用方法，不要复制长帖原文。字段：
- method_id
- topic: CEX flow / Alpha opening / wallet cluster / OI funding / meme speed / tokenomics / listing event / risk discipline / other
- rule_summary
- source_post_url
- evidence_type: social / official / onchain / market / inference
- required_local_verification
- action_mapping: Avoid / Observe / Reduce / Small test / Follow only after confirmation

第三部分：case index
请用 Markdown 表格输出案例。字段：
- case_id
- token_or_project
- event_time_utc
- source_post_url
- claimed_pattern
- reusable_lesson
- evidence_type
- missing_verification
- why_it_matters

第四部分：outcome ledger
每个原始信号使用唯一 `root_signal_id`，把同作者的 quote、自我跟进和结果帖归并到该信号。字段：
- root_signal_id
- related_update_post_urls
- signal_time_utc
- source_published_at_utc
- claimed_event_at_utc
- event_time_sanity: pass / mismatch / unknown
- entry_window_definition
- invalidation
- evaluation_horizons: 24h / 72h / 7d
- mfe / mae / end_return
- exit_path_verified
- outcome_status: won / lost / mixed / unresolved

第五部分：integration proposal
请明确建议如何进入系统：
- 是否需要新增 `$celue` reference 文件。
- 是否需要更新 `references/system-logic.md` 的全局规则。
- 是否需要更新项目脚本、日报字段、watchlist 字段或只做案例留档。
- 哪些内容只能作为 discovery，不能进入动作规则。
- 哪些链上/RPC/market/official 检查能验证或否定这些经验。
- 当前市场的 `regime_expectancy`：流动性、MC/FDV、全场 OI、场所政策、资金集中度、目标区间、分段止盈和 time stop；历史妖币倍数不能直接作为当前目标。

硬性要求：
- 按 official / onchain / market / social / inference 分层。
- KOL 和社交内容只能进入 discovery，不能直接变成交易动作。
- 利润截图、喊单、情绪词、单次成功案例不能直接作为 durable rule。
- 如果没有原始链接、时间、上下文或可复核路径，请标记为 low_confidence。
- 不要把外部 AI 的推断写成事实。
- quote、自我跟进和庆祝帖不能重复计入胜率分母；`unresolved` 必须留在分母中。
- 帖子发布时间与文中事件时间不一致时，标记 `event_time_sanity=mismatch`，暂停事实升级。
- “刷量”先记为 `wash_volume_candidate`；只有本地 gross buy/sell、net-to-gross、往返地址和 quote recovery 验证后才能升级。
```

本地接收后的处理步骤：

```bash
python3 scripts/audit_celue_integration.py
python3 /Users/xuyufan/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/xuyufan/Documents/蒸馏技能/celue
```

进入 `$celue` 的最小更新顺序：

1. 把可复用经验写入一个新的 `references/<handle-or-case>-review-<date>.md`。
2. 在 `/Users/xuyufan/Documents/蒸馏技能/celue/SKILL.md` 的 Resource Loading 中挂载该 reference。
3. 只有全局长期有效的硬规则才写入 `references/system-logic.md`。
4. 如果规则需要日报或告警展示，再更新项目脚本和 `scripts/verify_sniper_engine.py`。
5. 同步到 `/Users/xuyufan/.codex/skills/celue`，运行 skill validator 和项目验证。

外部 agent 能帮忙的范围：

- 抓公开帖、截图 OCR、链接整理、原始 tx hash 收集、公告链接收集。
- 提供互相冲突的样本，让本地系统判断哪些规则应收紧。
- 收集 CEX 充值、Alpha swap、开盘块、OI/funding、盘口深度和 liquidation 截图或 API 输出。

外部 agent 不能替代的范围：

- 本地代码行为判断。
- RPC、receipt、debug trace、fixture、dry-run 的最终验证。
- 买卖、减仓、追不追的动作结论。
