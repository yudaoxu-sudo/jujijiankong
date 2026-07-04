# Alpha Signal Source Strategy

更新日期：2026-06-20

目标：把外部 Telegram / KOL / 预测市场 / 官方公告变成可验证、可监控、可复盘的信号流。

## 核心判断

外部频道适合做发现层，我们自己的系统负责验证层、解释层、留档层。

原因：

- 外部监控速度快，能补足项目发现和人工投研。
- 外部消息字段经常不完整，合约、时间、价格、池子 tx 需要二次验证。
- 外部频道无法保证覆盖所有项目，也无法保证推送格式稳定。
- 自建链上监控能保存原始证据，便于复盘和训练评分。

## 信号分层

| 层级 | 来源 | 用途 | 处理方式 |
| --- | --- | --- | --- |
| L0 官方 | BinanceWallet、项目方 X、官网、白皮书 | 时间、规则、合约、空投 | 高优先级抓取和验证 |
| L1 监控 | 小C Alpha 池子、alpha news、KOL 监控脚本 | 新池子、新活动、新合约 | 收到后立刻查 tx/block/pool |
| L2 投研 | 凌云、小C、0xcrypto_max、aLiiDeez 等 | 估值、tokenomics、利好利空 | 提取字段，证据不足则标待证 |
| L3 市场 | Predict、Polymarket、盘前、OTC、CEX 盘前 | 市值锚点和情绪 | 转成价格锚点，不单独当结论 |
| L4 链上 | RPC、explorer、DEX、holder、internal tx | 最终证据 | 写入评分、报告、Telegram 解释 |

## 外部频道如何接入

### 当前可执行

- 用户把 Telegram 消息、X 链接、截图、合约发给 Codex。
- Codex 抽取字段，写入 `config/current_alpha_watchlist.json`。
- 服务器开始监控合约、池子、关键地址。
- Telegram 推送中文解释摘要。

### 下一步自动化

Telegram 自动采集有两个可行路径：

- Bot 被加入可控群或频道后，接收消息。
- 使用 Telegram API 客户端读取指定公开频道或用户已加入频道。

需要准备：

- Telegram API ID / API Hash。
- 一个专门用于采集的 Telegram 小号。
- 只读采集脚本，先保存消息文本、链接、时间、来源频道。

安全要求：

- 采集号不放资产。
- 不保存私人聊天。
- 不抓验证码、登录态、敏感材料。
- 原始消息和解析结果分开保存。

## 预测市场怎么用

预测市场是价格锚点，不是交易结论。

记录字段：

| 字段 | 说明 |
| --- | --- |
| source | Predict / Polymarket / manual |
| market_url | Predict 市场链接 |
| slug | Polymarket event 或 market slug |
| target_fdv | 目标 FDV，例如 1 亿 / 2 亿 |
| probability | 市场概率 |
| liquidity | Polymarket 市场流动性 |
| expiry | 结算时间 |
| implied_open_price | 折算 token 价格 |
| comparison | 与池子价、盘前价、Alpha 估算的偏差 |

用法：

- 概率高、池子价低：可能存在开盘错位。
- 概率高、盘前价高：注意接盘空间和流通市值上限。
- 概率分歧大：只作为观察，不提高评分。

Polymarket 接入方式：

- Gamma API 读取 event/market 的 outcomePrices、liquidity、volume、endDate。
- 只读采集，不接交易认证。
- 配置入口：`config/current_prediction_markets.json`。
- 输出入口：`output/prediction_markets/latest_prediction_markets.json` 和 `output/prediction_markets/prediction_markets.md`。

两层联动流程：

1. 外部频道或 KOL 发现项目。
2. 找 Predict / Polymarket / 盘前价作为估值锚点。
3. 把预测市场链接和目标 FDV 写入 prediction config。
4. 链上监控验证合约、池子、tx、地址。
5. 日报合并预测市场和链上证据。
6. Telegram 只推解释摘要。

## Alpha 池子监控怎么用

外部池子监控的关键字段：

| 字段 | 用途 |
| --- | --- |
| token 合约 | 进入 watchlist |
| USDT 合约 | 确认交易对 |
| PoolId | 查池子和价格区间 |
| Tx | 查 add liquidity / initialize |
| Block | 定位开盘块 |
| 初始价格 | 计算隐含 FDV |
| 上线时间 | 安排高频监控窗口 |

收到后立刻做：

1. 查合约和 decimals。
2. 查 PoolId / LP position。
3. 算池子价、FDV、可买深度。
4. 加池地址进监控。
5. 上线前后提高监控频率。
6. 开盘后复盘前排 txIndex 和 internal bribe。

## 我们的推送格式

一条可用推送要包含：

- 发生了什么。
- 为什么重要。
- 哪些地址在动。
- 链上证据是什么。
- 现在还缺什么。
- 下一步要看什么。

粗糙的地址列表只能当原始告警。用户侧应该收到中文解释摘要。

## 当前优先级

1. 继续使用外部频道作为发现层。
2. 把用户转发的消息结构化进 watchlist。
3. 自建链上验证和中文解释推送。
4. 补 Telegram 自动采集脚本。
5. 累积足够样本后训练评分权重。
