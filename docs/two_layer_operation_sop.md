# Two Layer Operation SOP

更新日期：2026-06-20

目标：外部发现层 + 自建验证层一起跑，减少人工来回指挥。

## 默认输入

系统收到任何一种材料即可启动：

- 项目名 / ticker。
- 合约地址。
- 官方 X / 官网 / 公告。
- Telegram 频道消息截图。
- KOL 投研帖。
- Polymarket / Predict 链接。
- 池子监控消息。

## Codex 默认动作

收到线索后按这个顺序自动推进：

1. `scripts/telegram_signal_collector.py` 从 Telegram bot 可见消息里自动收件。
2. 把原始线索保存到 `input/signals/telegram/`。
3. 运行 `scripts/ingest_alpha_signal.py` 抽取项目名、ticker、链、合约、tx、block、PoolId、价格和预测市场链接。
4. 生成 `output/telegram_signals/<file>.md` 和 `output/signals/<file>.md`。
5. 把中文判断发回 Telegram。
6. 提案可信时合并到 watchlist / prediction config。
7. 抽取项目名、ticker、链、合约、上线时间、来源链接。
8. 写入或更新 `config/current_alpha_watchlist.json`。
9. 搜集价格锚点：池子价、盘前价、Predict、Polymarket、CEX 盘前。
10. 写入或更新 `config/current_prediction_markets.json`。
11. 查合约、decimals、holder、加池 tx、LP position、PoolId。
12. 标记关键地址：部署、加池、团队、空投、做市、跨链、前排买入。
13. 更新监控钱包配置。
14. 跑服务器只读流水线。
15. 输出中文 Telegram 摘要和日报。
16. 开盘后复盘 txIndex、internal bribe、买后持仓、抛压路径。

## 两层分工

| 层 | 负责 | 输出 |
| --- | --- | --- |
| 外部发现层 | Telegram 频道、KOL、官方公告、预测市场 | 线索、时间、合约、价格锚点 |
| 自建验证层 | RPC、explorer、DEX、holder、internal tx | 链上证据、地址标签、监控、中文解释 |

## 推送分级

| 分级 | 条件 | 推送方式 |
| --- | --- | --- |
| P0 | 新池子初始化、开盘块、项目方地址大额移动、预测市场与池子价严重错位 | 立即 Telegram |
| P1 | 官方公告、Alpha/Boost 活动、关键地址授权、跨链开关 | Telegram 摘要 |
| P2 | KOL 投研、预测市场概率变化、盘前价变化 | 日报和观察 |
| P3 | 只含观点、缺少合约、缺少时间 | 暂存待证 |

## 用户需要做的事

最小动作：

- 看到新项目线索就转发给 Codex。
- 收到 P0/P1 推送时看中文结论。
- 要实盘时单独确认风险和执行计划。

更完整的频道自动采集需要：

- Telegram API ID / API Hash。
- 一个只读采集 Telegram 小号。
- 指定要监听的频道列表。

当前自动采集能力：

- Telegram bot 收到的私聊消息。
- Telegram bot 可见的群消息。
- Telegram bot 作为管理员可见的频道消息。

Bot 看不到的频道，需要下一阶段 Telegram 用户 API 采集器。

## 线索收件箱

本地入口：

```bash
python3 scripts/ingest_alpha_signal.py
```

指定文件：

```bash
python3 scripts/ingest_alpha_signal.py input/signals/qait_alpha_example.txt
```

合并提案：

```bash
python3 scripts/ingest_alpha_signal.py --apply
```

输出：

```text
output/signals/index.json
output/signals/<signal>.json
output/signals/<signal>.md
```

`--apply` 只改：

- `config/current_alpha_watchlist.json`
- `config/current_prediction_markets.json`

## 当前安全边界

- 服务器只读。
- 不签名。
- 不下单。
- 不接私钥。
- 预测市场只读概率。
- Telegram token 和 RPC key 只放 `.env.local`。
