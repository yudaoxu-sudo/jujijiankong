# Alpha 项目监控标准流程

适用范围：所有已发现、即将上线、开盘中和上线后的 Binance Alpha 项目。

## 生命周期

| 阶段 | 进入条件 | 系统动作 | 通过证据 |
| --- | --- | --- | --- |
| 发现 | 官方目录、官方公告、Telegram user/bot、人工导入或链上 Hook 出现项目线索 | 写入 project registry；P0/P1 推送线索 | registry 项目键、消息审计、推送结果 |
| 身份核验 | 获得候选 ticker、链、合约、交易和 pool | 核对 receipt、token 元数据和 quote token | receipt 成功；项目合约与 pool token 一致；BSC quote 为 USDT |
| 监控接管 | 身份核验通过，并有唯一精确开盘时间 | 自动加入 runtime watchlist | `registry_selected` 和 runtime 合约身份一致 |
| 上线前 | 开盘时间进入 48 小时窗口 | 推送分阶段提醒，准备开盘块、首批买家、bribe 和承接检查 | prelaunch event 与 `seen_alerts` 发送回执 |
| 开盘 | 到达开盘窗口 | 跟踪 pool、交易顺序、首批买家和项目/做市地址 | opening 输出匹配同一 chain+contract |
| 上线后 | 开盘完成 | 持续跟踪价格、holder、盘中流向、狙击手退出、项目/做市出货 | project/opening/intraday/price/holder 输出均匹配身份 |
| 持续观察 | 超出 72 小时盘中核心窗口仍在 30 天保留期 | 复用 holder 连续增量日志，跟踪首批狙击地址转出、项目/做市地址外流、CEX 入金和价格 | retention flow checkpoint 与健康检查 |

## 安全门禁

- social discovery 可以触发提醒和候选记录。
- 自动进入 runtime watchlist 需要 P0/P1、Binance Alpha 语境、唯一 token/USDT 身份、pool、交易和精确开盘时间；pool、交易、时间必须来自同一条 signal artifact，交易 receipt 负责核验 pool/token 身份。
- project registry 的跨消息聚合只能生成候选缺口，不能证明时间与 pool 的绑定关系。
- Telegram user、Telegram bot 和人工导入使用固定的非递归 artifact 入口，每个入口最多读取最近 400 个 JSON。
- 缺合约、缺 receipt、缺 pool、时间歧义或不支持的链保持候选状态，并由 runtime health 报准备缺口。
- 同一合约的单条证据出现不同开盘时间时 fail-closed，等待人工核定。
- 官方 Alpha `listingTime` 与同合约 signal 开盘时间冲突时保留官方基础监控并阻断 signal 增强；项目 TGE/空投释放时间单独记录，不能替代 Alpha 开盘时间。
- `context_only` 来源不进入候选、canonical registry、watchlist、prediction、交易动作或二次 Telegram 推送。
- 同 ticker 以 `chain+contract` 区分，禁止仅按 symbol 合并。
- 每个 lifecycle target 持久化 `lifecycle_first_seen_at`；若项目在开盘至少 10 分钟前被发现，开盘后仍核验至少一条历史预上线 Telegram 送达回执；SLA 内及开盘后 30 分钟内发现的项目可由同身份 `LIVE_WINDOW` 回执补证。

## 健康与验收

- official catalog、receipt-verified signal target 和已有 static identity 使用同一覆盖门禁。
- 任一 active lifecycle target 始终需要 runtime、project、holder；BSC 项目始终需要 opening。
- 距开盘 48 小时内需要 prelaunch；开盘后需要 price；开盘后 72 小时核心窗口内额外需要完整 receipt intraday。
- 72 小时至 30 天由 holder 本轮已读取的 Transfer logs 生成 `retention_flow`，不得增加重复全量 RPC；区块必须从上一 checkpoint 连续推进，RPC error、截断、事件截断或 block gap 均阻断健康和 checkpoint。
- 长尾 Transfer 命中先推送转移风险；只有同交易 direct quote-recovery 收据证据存在时才升级为已实现卖出。
- 未知地址向 CEX 的单笔转账先按本轮扫描窗口聚合，合计达到流通量 5 bps 才提醒；已知狙击手、项目或做市来源的命中不受该阈值抑制。推送展示风险类型合计笔数、合计数量和有限样本路径。
- 长尾快照先原子落盘，Telegram 新信号送达后才原子提交 holder/retention checkpoint；发送失败保留旧 checkpoint，下一轮重试。
- 首次发现时间已晚于 72 小时核心窗口且没有既有 holder checkpoint 的项目，只能以首次成功的有限扫描建立长尾基线并生成明确 warning；`lifecycle_first_seen_at` 仅用于证明允许晚发现基线，更早历史明确留在监控范围外。在核心窗口内已知或已有 holder checkpoint 却缺少 retention checkpoint 的项目要求历史回填，健康保持 fail-closed。
- intraday 的 transfer 或 receipt 覆盖不完整均阻断健康；CEX gas 辅助回溯受限会保留已确认转账风险并生成覆盖 warning。
- intraday 单轮总预算硬封顶 420 秒，并由进程级绝对截止中断慢 RPC；预算耗尽的对象写入显式 incomplete 行，由 runtime health 报错，服务器 480 秒外层限制仍留有落盘余量。
- 上线前提醒只有 alert key 出现在 `alpha_prelaunch_watch/seen_alerts.json` 后才视为送达。
- 完成改动需通过定向回归、全量 verifier、正常服务器 cycle、远端 runtime health 和 continuity acceptance。
