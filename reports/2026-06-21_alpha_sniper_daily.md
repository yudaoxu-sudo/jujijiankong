# Alpha Sniper Daily Report

- date_cn: `2026-06-21`
- watchlist_generated_at: `2026-06-21T04:44:35+00:00`
- verification: `PASS`
- monitored_wallets: `32`
- monitor_alerts: `9`

## Priority Queue

| Priority | Symbol | Name | Chain | Contracts | First check |
| --- | --- | --- | --- | --- | --- |
| P0_DEEP_REVIEW | `O` | o1 exchange | bsc | bsc: `0x500A02...3bd1C4`, base: `0x500A02...3bd1C4`, base: `0x182fa6...4620b2` | block_transaction_order |
| P1_MONITOR | `RE` | Re | unknown | 待确认 | official_contract |
| P0_DEEP_REVIEW | `ARX` | Arcium | bsc | bsc: `0xd5f6ef...1ca715` | watch_pool_start_block |
| P2_PAPER_TRADE | `GRAM` | GRAM | unknown | 待确认 | official_contract |
| P2_PAPER_TRADE | `ESPORTS` | ESPORTS | unknown | 待确认 | official_contract |
| P2_PAPER_TRADE | `VELVET` | VELVET | bsc/base | bsc: `0x8b1943...8c1488`, base: `0xbf927b...887cdd` | official_contract |
| P3_BACKLOG | `NIGHT` | NIGHT | unknown | 待确认 | boost_rules |

## O1 Case State

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

## O1 Monitor

- `bsc` `0x500a02...3bd1c4` blocks `105473011` -> `105478011`: `2208/2864` relevant transfers
- alert count: `9`

## Top Watched Balances

| Balance | Address | Label | Level |
| ---: | --- | --- | --- |
| 7480000.00 | `0x35aac8...333b76` | O-分发中-35aac | HIGH |
| 5395790.61 | `0xbd1dbe...a8c652` | O-潜伏-bd1db | HIGH |
| 4412465.98 | `0x73d8bd...4946db` | O-分发中-73d8b | HIGH |
| 3107283.46 | `0xc26e70...4544ed` | O-庄家-c26e7 | HIGH |
| 2499778.00 | `0x84c6b8...ed9f90` | O-分发中-84c6b | HIGH |
| 2347401.41 | `0x1a9b68...fe2e56` | O-分发中-1a9b6 | HIGH |
| 551356.26 | `0xe269f9...636879` | O-庄家-e269f | HIGH |
| 494163.28 | `0x07321f...e6aaee` | O-庄家-7321f | HIGH |

## Prediction Markets

- No prediction markets configured.

## Action Queue

1. O1: 继续跑钱包监控，重点看潜伏钱包、分发钱包、池子地址的转出和拆分。
2. ARX: 优先确认官方合约、Wormhole/bridge 事件和 OKX Boost 钱包。
3. RE: 做 Alpha 到 CEX 承接复盘，重点看 Prime Sale、充值地址、现货/永续价差。
4. VELVET/ESPORTS: 先看交易赛带来的真实成交质量和活动钱包。
5. NIGHT/GRAM: 作为 OKX Boost/衍生品结构样本，等链上合约确认后上调。

## Sources

- Binance New Cryptocurrency Listing: https://www.binance.com/en/support/announcement/list/48
- OKX New listings: https://www.okx.com/help/section/announcements-new-listings
- OKX NIGHT Boost: https://www.okx.com/en-us/learn/trade-dex-night-boost
- Local verification: `output/sniper_engine/verification_report.md`
- Local monitor: `output/monitoring/alerts.md`
