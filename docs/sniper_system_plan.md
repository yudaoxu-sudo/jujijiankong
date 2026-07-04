# Sniper System Plan

更新日期：2026-06-19

目标：把推文经验、链上证据、监控脚本、评分规则合成一套服务器自动运行的系统。

## 当前该做什么

先做只读情报引擎：

1. 发现新项目线索。
2. 抽取合约、地址、tx、block、LP position。
3. 判断证据强弱。
4. 生成下一步链上检查。
5. 输出监控优先级。
6. 保存纸面交易记录。

交易执行排在后面。执行模块需要钱包隔离、授权规则、失败保护、RPC 和排序路径，且需要单独确认。

## 最终系统模块

```text
sources
  X / Telegram / Alpha / CEX / explorer / RPC
        |
normalizer
  token, chain, contract, address, tx, block, LP
        |
evidence engine
  holder, tokenomics, bridge, LP range, opening block, bribe
        |
score engine
  opportunity score, risk gaps, next checks
        |
alert engine
  Telegram/Discord/console/dashboard
        |
paper trade
  plan, entry, exit, invalidation, result
        |
execution research
  manual first, signed automation after explicit approval
```

## 第一版已经落地

- `sniper_engine/scoring.py`：只读评分规则。
- `sniper_engine/local_sources.py`：读取本地推文方法库。
- `scripts/sniper_score_local.py`：输出本地信号评分。
- `output/sniper_engine/signal_scores.csv`：机器可读结果。
- `output/sniper_engine/signal_scores.md`：人工复盘结果。

## 下一版要接的数据源

1. BscScan/BaseScan API：tx、internal tx、token holder、contract read。
2. RPC：block、transactionIndex、logs、event filter。
3. DEX：PancakeSwap V3/V4、Aerodrome、Uniswap LP position。
4. Alpha/Boost 页面：新项目和开始时间。
5. CEX 公告：Binance、OKX、Coinbase、Kraken、Gate、Kucoin。
6. X/Telegram：KOL 线索和项目方公告。

## 评分维度

加分项：

- 有 tx/block/LP/address。
- 有 Alpha/CEX/Boost 催化。
- 有 V3 区间和可买深度。
- 有跨链提前量。
- 有 tokenomics 和 holder 对照。
- 有开盘块和 internal bribe 证据。
- 有庄/控盘地址。

扣分项：

- 缺少合约或地址。
- 只有文本线索。
- 缺少 LP position。
- 缺少开盘块。
- bundle/bribe 说法缺少链上证据。
- 庄判断缺少地址。

## 运行方式

```bash
cd /Users/xuyufan/Documents/狙击手进程
python3 scripts/sniper_score_local.py
```

输出：

```text
output/sniper_engine/signal_scores.csv
output/sniper_engine/signal_scores.md
```

## 服务器化路线

1. 用 cron/systemd 每 1-5 分钟运行只读采集器。
2. SQLite 保存项目、地址、tx、LP、评分、告警。
3. 评分变化触发 Telegram 通知。
4. 纸面交易记录进入同库。
5. 命中率稳定后再研究手动下单助手。
6. 签名自动化需要专门测试钱包和单独授权。

