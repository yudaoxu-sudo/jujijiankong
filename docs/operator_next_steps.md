# Operator Next Steps

更新日期：2026-06-21

这份文档只写用户需要怎么操作。

## 当前状态

- 腾讯云服务器每 5 分钟自动运行一次。
- 已经覆盖 O1 钱包监控、Telegram bot 收件、预测市场只读采集、地址归因、日报、验收报告。
- Telegram bot 能处理私聊、bot 可见群、bot 管理员频道。
- Telegram 用户 API 采集器已经部署，当前还缺频道来源和一次性登录。
- X 官方 hosted MCP 已发布，项目已加入 readiness 检查；当前等待 X Developer app 凭证后接入只读发现源。
- Pancake pool + BscScan tx 链接已经能做链上还原。QAIT 样例已验证：`1 QAIT ≈ 0.002 USDT; 1 USDT ≈ 500 QAIT`。
- 私密频道 `https://t.me/+...` 不能用公开 Web Preview 读取消息内容。稳定读取需要 Telegram 用户 session。
- 项目级去重档案已经接入。Telegram bot、用户 API 频道采集、手动文本解析都会写入 `output/project_registry/project_registry.json`。

## 你现在要做

1. 准备一个 Telegram 采集小号。
2. 用这个小号加入你想监听的 Alpha / 池子 / KOL / 公告频道。
3. 打开 `https://my.telegram.org`。
4. 用采集小号登录。
5. 进入 `API development tools`。
6. 创建 app，名称填 `sniper-monitor`。
7. 拿到 `api_id` 和 `api_hash`。
8. 把频道链接发给 Codex，例如 `https://t.me/example_channel`。
9. 如需 X MCP 自动读取 X 线索，准备一个只读 X Developer app；详细步骤看 `docs/x_mcp_setup.md`。

验证码和 2FA 密码在腾讯云终端里输入。不要发在聊天里。

## 新标的从哪里发

最快入口：发给 Telegram bot。

- 转发 Alpha 频道消息给 `@opbnb_alpha_jack_bot`。
- 发送 Pancake pool 链接、BscScan tx、合约地址、项目公告链接。
- 发送 X 推文链接，系统会抽取项目线索并进入同项目去重档案。
- bot 会自动解析，能链上还原的会直接给出 PoolId、token、block、txIndex、初始价格。

深度入口：发在 Codex 当前对话。

- 需要我解释截图。
- 需要我复盘项目方/狙击手行为。
- 需要我新增监控脚本、修规则、部署服务器。
- 需要我给结论之外的完整投研报告。

默认流程：

1. 飞机 bot 负责第一时间收线索和推送。
2. 服务器负责每 5 分钟自动采集、链上还原、钱包监控。
3. Codex 对话负责深度解释、改程序、补数据源。

## 同项目去重规则

同一个项目只保留一个档案。系统按这个顺序合并：

1. 项目合约地址。
2. Pancake PoolId。
3. 交易哈希。
4. 代币符号。

每条新消息进入后会出现三种状态：

- `新项目，已建档`：第一次看到这个项目，会推送分析。
- `同项目补充，已去重合并`：同项目出现了新区块、tx、代币分配、价格锚点、预测市场、池子链接等信息，会推送新增字段。
- `重复线索，已归档`：没有新增可用字段，只保存来源，不再刷屏。

例子：

- 频道 A 先发 `$BTC 即将上线` 和区块，系统建 BTC 档案。
- 频道 B 再发 `$BTC 总量、团队、流动性`，系统补充到 BTC 档案。
- 你再把 BTC 发给 bot 或 Codex，我会先查已有 BTC 档案，再补缺口和给判断。

项目档案位置：

```text
output/project_registry/project_registry.json
output/project_registry/project_registry.md
```

更安全的登录方式：

```bash
cd /home/ubuntu/sniper
set -a
. ./.env.local
set +a
python3 scripts/telegram_user_login.py --qr
```

命令会生成 QR 登录链接或二维码文件。用 Telegram 手机端进入 `Settings -> Devices -> Link Desktop Device` 扫码。验证码不要发在聊天里。

如果频道是 `https://t.me/+...` 这种私密邀请链接：

- bot 不能自己通过邀请链接加入。
- 公开网页采集读不到里面内容。
- 可行办法是手动转发重点消息给 bot，或完成 Telegram 用户 API 登录后由服务器读取你账号已加入的频道。

## 我来做

- 把 `api_id` 和 `api_hash` 放进服务器 `.env.local`。
- 在服务器创建 Telegram session。
- 把频道加入 `config/telegram_user_sources.json`。
- 把 X MCP readiness 接入服务器，并在你提供凭证后验证官方 MCP 访问。
- 把外部辅助源 readiness 接入服务器；拿到 Coinglass / CoinAnk / GMGN 凭证后先跑小样本验证。
- 跑 `--bootstrap` 跳过历史旧消息。
- 开启 5 分钟自动采集。
- 每次采集到新线索后，生成中文判断并推送回 Telegram。
- 如果消息里有 Pancake pool 链接和 BscScan tx，我会自动还原 PoolId、token0/token1、block、txIndex 和初始价格。

## 外部辅助工具怎么用

可以辅助，当前分三层：

- Coinglass / CoinAnk：合约 OI、funding、爆仓、多空比、交易量，用来补 CAP 这种 CEX/Alpha 价格先动而链上净流不明显的场景。
- GMGN：链上聪明钱、holder、top trader、insider 钱包，用来交叉验证我们自己的钱包标签和首批 cohort。
- DeBot AI / 其他机器人：先当人工证据源，你转发截图或推送给 bot 后进入项目档案。

你需要准备的东西：

- 有 Coinglass API 就发 key 的环境变量名和额度说明，不要把长期密钥直接贴聊天；我会给你服务器 `.env.local` 写入命令。
- 有 CoinAnk API 就发 API 文档或 key 的获取页面。
- 有 GMGN API / Agent API 权限就发文档和 key 获取入口；如果有只读查询 endpoint，也给出 endpoint 名称，方便配置 `GMGN_PROBE_URL`。
- 暂时没有 key 也可以继续用截图和推送，系统会把它们标成人工证据。

当前检查命令：

```bash
python3 scripts/external_aux_source_readiness.py
```

日报会显示每个外部源当前是 `needs_credentials`、`ready_for_live_probe`、`validated_for_auxiliary_signals`，避免把未验证数据写成买卖建议。

拿到 key 后的验收命令：

```bash
python3 scripts/external_aux_live_probe.py --source coinglass,coinank,gmgn
```

只验证 Surf：

```bash
python3 scripts/external_aux_live_probe.py --source surf
```

## 仓位/成本台账

真实仓位文件：

```text
config/user_positions.json
```

这个文件已被 git 忽略。可以先复制模板：

```bash
cp config/user_positions.example.json config/user_positions.json
```

需要你填的字段：

- `symbol`：项目符号，例如 `ARX`。
- `instrument`：`spot` 或 `perp`。
- `side`：`long` 或 `short`。
- `quantity`：数量。
- `avg_entry`：平均成本。
- `stop_loss`：失效价格。
- `take_profit`：计划止盈价格。
- `max_position_usd`：该标的最大暴露。
- `thesis`：买入理由。
- `invalidation`：什么证据出现就退出。

检查命令：

```bash
python3 scripts/position_cost_watch.py
```

输出：

```text
output/position_cost_watch/latest.json
output/position_cost_watch/latest.md
```

## 你收到推送后怎么看

优先看三行：

- `结论`：当前是观察、深挖、预警、还是等待链上确认。
- `动作建议`：买入观察、持仓减风险、只观察、暂存。
- `仓位口径`：`首批历史开盘买入` 只代表开盘竞争强度，不代表这些钱当前还在；当前判断看 `当前仍在原买入钱包`、`净流出` 和 `已确认换出`。
- `可售性`：v4/Infinity 已接入同笔 Router 往返 `eth_call` 和回收率二分估算；只有回收率通过、转账/报价通过、开盘块/首批钱包/盘口规则也通过时，才允许出现跟随口径。
- `庄家行为`：项目方/做市/高危钱包正在做什么。
- `狙击手行为`：前排买入、砸盘、bribe、txIndex 是否有证据。
- `触发原因`：池子、合约、tx、预测市场、空投、跨链、关键地址。
- `下一步`：我会继续查什么，以及是否需要你补项目链接或截图。

## 电脑关机后的边界

腾讯云服务器会继续跑：

- 链上监控。
- Telegram 自动采集。
- 规则化中文分析。
- 日报和验收报告。

Codex 会话里的深度推理，需要你打开当前线程后继续。

## 安全线

- 只用采集小号。
- 采集小号不放资产。
- 当前系统只读。
- 当前系统不签名。
- 当前系统不下单。
- 私钥、助记词、交易所密码、Telegram 验证码不进聊天。
- 真实钱包账号暂时不需要交给 Codex。后续如果做 dust 级实盘校准，也由你自己在钱包里确认交易，我只给参数、模拟结果和风险判断。
