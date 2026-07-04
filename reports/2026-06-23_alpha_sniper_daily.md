# Alpha Sniper Daily Report

- date_cn: `2026-06-23`
- watchlist_generated_at: `2026-06-21T04:44:35+00:00`
- verification: `PASS`
- monitored_wallets: `0`
- monitor_alerts: `0`

## Priority Queue

| Priority | Symbol | Name | Chain | Contracts | First check |
| --- | --- | --- | --- | --- | --- |
| P1_MONITOR | `RE` | Re | unknown | 待确认 | official_contract |
| P0_DEEP_REVIEW | `ARX` | Arcium | bsc | bsc: `0xd5f6ef...1ca715` | watch_pool_start_block |
| P2_PAPER_TRADE | `GRAM` | GRAM | unknown | 待确认 | official_contract |
| P0_DEEP_REVIEW | `NES` | Nesa | bsc | bsc: `0x3131f6...ac3fb5` | pool_id_match_confirmation |
| P2_PAPER_TRADE | `ESPORTS` | ESPORTS | unknown | 待确认 | official_contract |
| P2_PAPER_TRADE | `VELVET` | VELVET | bsc/base | bsc: `0x8b1943...8c1488`, base: `0xbf927b...887cdd` | official_contract |
| P3_BACKLOG | `NIGHT` | NIGHT | unknown | 待确认 | boost_rules |

## Archived Cases

- `O`: User has no O position and paused active O1 wallet monitoring on 2026-06-22. Keep as historical training case only.

## O1 Case State (Historical)

- LP position ID: `6913002`
- pool: `0x1a9b68ca1dcacb106c4b853e2d9c915f0cfe2e56`
- price range: `0.045097 -> 0.359929` USDT/O
- opening swaps: `5`
- opening buy total: `1003251.21` USDT for `9699513.27` O
- opening weighted avg: `0.103433` USDT/O
- front buyers held_or_accumulated: `5/5`
- attribution strong project-side: `5`
- attribution medium project-side: `12`
- failed sniper side addresses: `5`

## Active Wallet Monitor

- alert count: `0`

## ARX Runtime Judgment

- opening_conclusion: ARX 首块出现大额狙击：首笔约 `400000.0000` USDT，均价 `0.202868`，最大 bribe `365.8000` BNB。
- opening_spot_action: 空仓不追；已有仓位按冲高分批止盈，等活动分发和回踩承接
- opening_perp_action: 先设短空预案；等分发筹码进交易所、价格跌破承接位、合约深度够再执行
- launch_conclusion: ARX 已开盘，本窗口没有新的关键分发或大户外流；首批有效买入约 497000.0000 USDT，最大 bribe 约 365.8000 BNB。
- launch_spot_action: 空仓不追；已有仓位按冲高分批止盈，等活动分发和回踩承接
- launch_perp_action: 先设短空预案；等分发筹码进交易所、价格跌破承接位、合约深度够再执行

## Top Watched Balances

| Balance | Address | Label | Level |
| ---: | --- | --- | --- |

## Prediction Markets

- No prediction markets configured.

## Action Queue

1. ARX: 以开盘块、首批买入、bribe、活动分发和交易所流向作为主线。
2. O1: 已暂停主动钱包监控，只保留历史复盘样本。
3. RE: 做 Alpha 到 CEX 承接复盘，重点看 Prime Sale、充值地址、现货/永续价差。
4. VELVET/ESPORTS: 先看交易赛带来的真实成交质量和活动钱包。
5. NIGHT/GRAM: 作为 OKX Boost/衍生品结构样本，等链上合约确认后上调。

## Sources

- Binance New Cryptocurrency Listing: https://www.binance.com/en/support/announcement/list/48
- OKX New listings: https://www.okx.com/help/section/announcements-new-listings
- OKX NIGHT Boost: https://www.okx.com/en-us/learn/trade-dex-night-boost
- Local verification: `output/sniper_engine/verification_report.md`
- Local monitor: `output/monitoring/alerts.md`
