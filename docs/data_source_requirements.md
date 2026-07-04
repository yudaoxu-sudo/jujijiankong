# Data Source Requirements

更新日期：2026-06-19

这份清单说明后续需要注册或购买的东西。当前代码能用公开 RPC 做历史复盘，实时监控和 internal tx 需要更稳定的数据源。

## 已验证

- 公开 BSC RPC 可以拉 block `104769548`，并拿到 `121` 笔交易。
- 公开 BSC RPC 可以逐笔拉 receipt。
- O1 验证器已经输出块内顺序表。

## 当前缺口

### BNB Chain internal tx

普通 JSON-RPC 可以拿到交易、receipt、logs。internal tx / trace 类数据需要额外数据源。

当前公开测试结果：

- 旧 BscScan V1 endpoint 返回弃用提示。
- Etherscan V2 对 BNB Chain free tier 不开放。
- BNB Chain 官方迁移文章建议使用 BSCTrace / MegaNode。

参考来源：

- BNB Chain migration guide: `https://www.bnbchain.org/en/blog/migration-guide-bscscan-api-to-bsctrace-api-via-meganode`
- Etherscan supported chains: `https://docs.etherscan.io/supported-chains`
- Etherscan V2 migration: `https://docs.etherscan.io/v2-migration`

## 需要准备

### 第零优先级：外部发现源

用途：

- 发现 Alpha / Boost / CEX / 空投 / 池子初始化。
- 捕捉 KOL 投研和人工监控信号。
- 给 watchlist 提供项目名、合约、时间、tx、pool id。

当前可用：

- Telegram bot 自动收件：bot 私聊、bot 可见群、bot 管理员频道。
- Telegram 用户 API 采集器：读取采集小号已加入且配置过的频道。
- X 官方 hosted MCP：已建立 readiness 检查，等待 X app 凭证后接入只读发现源。
- Codex / 服务器抽取字段后写入 watchlist 提案。
- 服务器做链上验证和中文解释推送。

后续可自动化：

- Telegram 用户 API 客户端读取指定公开频道或采集小号已加入频道。
- X MCP 读取公开 X 线索，采集 KOL、项目方、交易所、X Developers 相关公告。
- 采集字段：source、message_id、time、text、links、contract、tx、block、pool_id、price。

需要：

- Telegram API ID / API Hash。
- 专门的只读采集 Telegram 小号。
- 不使用主号和资产号。
- X Developer app 的 app-only bearer 或 OAuth client。

代码已支持：

```bash
python3 scripts/telegram_signal_collector.py
python3 scripts/telegram_user_signal_collector.py
python3 scripts/x_mcp_readiness.py
```

X MCP 接入说明：

```text
docs/x_mcp_setup.md
```

### 第一优先级：MegaNode / NodeReal

用途：

- BSC 稳定 RPC。
- BSCTrace 增强 API。
- internal / asset transfer 类数据。

需要：

- 注册 MegaNode / NodeReal。
- 创建 BNB Chain API key。
- 把 key 给到运行环境变量 `NODEREAL_API_KEY`。

代码已支持：

```bash
export NODEREAL_API_KEY="..."
python3 scripts/o1_block_verifier.py
```

### 第二优先级：Telegram Bot

用途：

- 服务器监控后推送 P0/P1 信号。

需要：

- 创建 Telegram bot。
- 获取 `TELEGRAM_BOT_TOKEN`。
- 获取 `TELEGRAM_CHAT_ID`。

### 第三优先级：服务器

购买时机：

- O1 验证器稳定。
- watchlist 监控脚本能跑。
- Telegram 告警能发。

建议规格：

- 2 vCPU。
- 4 GB RAM。
- 40 GB SSD。
- Ubuntu 22.04 或 24.04。
- 香港、新加坡、日本节点都可以。

用途：

- 1 分钟级别只读监控。
- SQLite 存信号和评分。
- Telegram 推送。

### 第四优先级：Etherscan paid API

用途：

- 多链 explorer 数据。
- BNB/Base chain coverage。

当前阶段先用 MegaNode 方案评估成本。

### 第五优先级：预测市场 / 盘前价格源

用途：

- 估算 TGE 后 FDV。
- 对比池子价、盘前价、Alpha 估值。
- 识别开盘错位和接盘空间。

需要采集：

- Polymarket event / market URL。
- Polymarket slug、outcome、outcome price、liquidity、volume、endDate。
- Predict 市场链接。
- 目标 FDV。
- 概率。
- 结算时间。
- 当前盘前价。

当前已支持：

- `scripts/prediction_market_watch.py` 读取 `config/current_prediction_markets.json`。
- Polymarket Gamma API 只读采集。
- Predict / 其他预测源先用 manual 方式录入。
- 输出到 `output/prediction_markets/`，并进入 Alpha daily report。

### 第六优先级：外部辅助行情 / 链上工具

用途：

- 辅助确认现货价格动量、合约持仓、资金费率、爆仓、交易所成交和链上聪明钱。
- 覆盖 Binance Alpha 内成交、CEX 可见价格、Pancake 链上成交之间的错位。
- 给 “追 / 不追 / 减仓 / 观察” 提供交叉证据。

接入规则：

- 能稳定 API 化的源进入程序和日报，例如 Coinglass、CoinAnk、GMGN。
- 只能网页查看或机器人推送的源先作为人工证据，例如 DeBot AI、GMGN 页面、第三方群推送截图。
- 未完成 live probe 验证前，任何外部源只能补充上下文，不能单独触发买入、卖出或加仓建议。
- 与本地链上规则冲突时，输出为 `需要人工复核`，不自动升级动作。

当前已登记：

- Coinglass：OI、funding、liquidation、long/short、spot / derivatives cross-check。
- CoinAnk：OI、funding、liquidation、order flow、whale activity。
- GMGN：smart money、holder、top trader、insider / bundled wallet 交叉验证。
- DeBot AI：bot alert / manual evidence，先不进入自动动作规则。

代码已支持：

```bash
python3 scripts/external_aux_source_readiness.py
```

输出位置：

```text
output/external_aux_sources/latest.json
output/external_aux_sources/latest.md
```

需要：

- Coinglass API key：环境变量 `COINGLASS_API_KEY`。
- CoinAnk API key：环境变量 `COINANK_API_KEY`。
- GMGN API key：环境变量 `GMGN_API_KEY`。
- 每个源完成一笔小样本 live probe 后，再设置对应 `AUX_SOURCE_VALIDATED_*` 开关。

## 当前不用准备

- 私钥。
- 助记词。
- 自动交易服务器。
- 付费 MEV / bundle 服务。
