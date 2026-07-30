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
| 持续观察 | 超出开盘窗口仍在保留期 | 继续出货、承接和地址迁移监控 | runtime retention 与健康检查 |

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

## 健康与验收

- official catalog、receipt-verified signal target 和已有 static identity 使用同一覆盖门禁。
- 任一 active lifecycle target 缺 runtime、prelaunch、opening、project、intraday、price 或 holder 证据时，runtime health 必须报错。
- 上线前提醒只有 alert key 出现在 `alpha_prelaunch_watch/seen_alerts.json` 后才视为送达。
- 完成改动需通过定向回归、全量 verifier、正常服务器 cycle、远端 runtime health 和 continuity acceptance。
