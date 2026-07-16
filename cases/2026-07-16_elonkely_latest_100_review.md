# ElonKely Latest-100 Review

Date: 2026-07-16

## 结论

最近 100 条帖子已逐条核对。83 条落在 2026-07-07 的既有 500 帖复盘窗口内，真正新增 17 条。新增内容继续强化 CEX 路径、钱包集群、OI/funding、刷量辨识和跟进时钟，没有提供可直接改变交易方向的已验证证据。

本次采用四项长期控制：结果分母去重、当前市场期望值、供应生命周期、来源事件时间校验。刷量保持 report-only 候选。运行时新增跨场所 Total OI 变化字段；主场趋势、动作、Telegram 告警均保持原口径。

结构化证据保存在 `input/elonkely_latest_100_review_2026-07-16.json`。

## 样本边界

- 来源：`https://x.com/elonkely_`。
- 覆盖：`100/100`，唯一 ID `100`，转推 `0`，引用帖 `18`。
- 时间：`2026-06-12T06:31:11Z` 至 `2026-07-16T13:11:12Z`。
- 媒体：91 条帖子、135 个附件；新增 17 条中的 24 个附件已人工检查。
- 原始抓取 SHA-256：`adb69a00239fe6481de29adfade237cd0701e39c875a394cf7fe92b473b49f25`。
- 15 个引用帖指向本批内部帖子；初始信号、跟进、庆祝和失败说明必须合并为一个案例。

## 证据分层

- `official`：本次没有官方信息推动实时动作。
- `onchain`：仅引用项目内已验证的 PARTI 集群证据；帖子截图和地址标签仍属 `social`。
- `market`：仅引用项目内固定窗口的 PARTI、B2 复盘；帖子中的价格和 OI 截图仍属 `social`。
- `social`：账号帖子、截图、钱包标签、路线、收益和市场状态表述。
- `inference`：本次加入的检查项、字段和延后实现决策。

## 关键反例

### PARTI：集群成立，方向失败

- 初始帖：`https://x.com/ElonKely_/status/2074859463027408945`。
- 跟进帖：`https://x.com/ElonKely_/status/2075915168996118791`。
- 本地独立证据：`cases/2026-07-13_miles082510_wallet_cluster_review.md`。

项目内的独立 PARTI 回放已确认真实 CEX fan-out，随后最大上涨 `+7.24%`、最大下跌 `-36.50%`、期末 `-33.92%`。该回放锚定同日另一条公开信号，不能充当 ElonKely 初始帖的精确 24h/72h/7d 收益。它支持“集群真实、方向仍可能失败”这一反例；ElonKely 根信号的固定窗口结果保持 unresolved。

### EVAA：证据与价格响应冲突

来源：`https://x.com/ElonKely_/status/2075164060409270485`。

帖子同时描述链上吸筹、合约多头增加和价格持续下跌。该组合要求记录 `signal_price_divergence`；关于“洗杠杆”和操盘动机的解释留在 `inference`。

## 采用的改进

1. `outcome_ledger`：每个原始信号使用 `root_signal_id`，自我引用和结果更新合并；固定记录 24h/72h/7d、MFE、MAE、期末收益、失效、退出可行性和 unresolved。
2. `regime_expectancy`：用当前流动性、MC/FDV、跨场所 Total OI、场所政策和资金集中度重算目标、分段止盈及 time stop。
3. `supply_lifecycle`：补充 mint、reissue、retirement、compensation、snapshot、migration，并验证相对流通量、首个接收方、锁定和 CEX/LP 去向。
4. `source_time_sanity`：发布时间、声称事件时间或引用上下文冲突时维持待证。
5. `flow_recycling_candidate`：记录 gross buy/sell、net-to-gross、往返地址和 quote recovery；当前 `runtime_effect=none`。
6. Total OI 趋势：只有当前与基线的场所集合一致时计算跨场所变化；原主场 OI 趋势继续决定现有趋势标签。

时间冲突样本：`https://x.com/ElonKely_/status/2069768362297856076` 发布于 `2026-06-24`，正文却使用“将于 2023 年”的未来式表述。原始引用上下文未恢复，记录为 `event_time_sanity=mismatch`，不升级事实层。

## 延后项

- 多签、vesting、unlock、staking 分发源扩展：需要项目内明确 tracked 地址和正反夹具。
- 自动刷量检测器：需要往返地址、真实净流和 quote recovery 夹具。
- DEXE 与历史安全事件类比：需要官方事件和完整链路，当前仅提高人工检查优先级。

这些延后项不阻塞现有系统运行。
