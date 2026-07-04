# Alpha Sniper Daily Report

- date_cn: `2026-07-01`
- watchlist_generated_at: `2026-07-01T05:59:01+00:00`
- verification: `PASS`
- monitored_wallets: `0`
- monitor_alerts: `0`

## Priority Queue

| Priority | Symbol | Name | Time | Chain | Contracts | First check |
| --- | --- | --- | --- | --- | --- | --- |
| P1_MONITOR | `RE` | Re | - | unknown | 待确认 | official_contract |
| P0_DEEP_REVIEW | `ARX` | Arcium | - | bsc | bsc: `0xd5f6ef...1ca715` | watch_pool_start_block |
| P2_PAPER_TRADE | `GRAM` | GRAM | - | unknown | 待确认 | official_contract |
| P0_DEEP_REVIEW | `NES` | Nesa | - | bsc | bsc: `0x3131f6...ac3fb5` | pool_id_match_confirmation |
| P1_MONITOR | `CAP` | CAP | - | bsc | bsc: `0x99991c...9b9999` | watch_pool_start_block |
| P2_PAPER_TRADE | `ESPORTS` | ESPORTS | - | unknown | 待确认 | official_contract |
| P2_PAPER_TRADE | `VELVET` | VELVET | - | bsc/base | bsc: `0x8b1943...8c1488`, base: `0xbf927b...887cdd` | official_contract |
| P3_BACKLOG | `NIGHT` | NIGHT | - | unknown | 待确认 | boost_rules |
| P0_DEEP_REVIEW | `WDATAIP` | 🟦 [BN Alpha 新Hook] 设置/更新池子开盘时间 | 2026-07-02 16:00 | bsc | unknown: `0xa37ede...56afb2`, bsc: `0xa37ede...56afb2` | official_contract |

## Archived Cases

- `O`: User has no O position and paused active O1 wallet monitoring on 2026-06-22. Keep as historical training case only.

## Prelaunch Schedule

| Phase | Time UTC+8 | Project | Action |
| --- | --- | --- | --- |
| T_MINUS_24H | 2026-07-02 16:00 | DATA/WDATAIP · Data Network | 进入上线前监控；重点看是否追加池子、桥、交易所活动 |

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

- opening_conclusion: ARX 首批买入 `5` 笔，其中 `4` 笔买后转出或余额接近0，且小额确认换出约 `410.2281` USDT，未达卖出阈值。
- opening_spot_action: 不追；已有仓位先降风险
- opening_perp_action: 只做观察；若价格冲高且外流扩大，再等可交易合约和深度
- launch_conclusion: ARX 活动分发合约累计释放约 2548246.92 ARX，属于后续抛压线索。
- launch_spot_action: 空仓观察；涨幅已大，等分发外流结束或回踩承接
- launch_perp_action: 合约未确认；只记录偏空条件，看到分发筹码进交易所且价格走弱再执行

## Top Watched Balances

| Balance | Address | Label | Level |
| ---: | --- | --- | --- |

## Prediction Markets

- No prediction markets configured.

## Perp / OI / Funding

| Symbol | Perp | Venues | State | Main OI | Total OI | OI Δ | Price Δ | Funding | 24h Vol | 24h Chg | Trend | Action |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `RE` | `REUSDT` | binance_usdm,okx_swap,bybit_linear | crowded_funding / 拥挤 | 15626003.23 | 28037454.92 | -0.09% | +0.98% | -0.1647% | 273293239.84 | -15.09% | 费率变化 | 空头拥挤，等价格和链上流向确认；其他场地 okx_swap 拥挤 OI≈5680474.91 funding -0.1374%；bybit_linear 拥挤 OI≈6730976.78 funding -0.2120%; 资金费率变化明显，观察是否形成拥挤方向 |
| `ARX` | `ARXUSDT` | binance_usdm,okx_swap,bybit_linear | listed_quiet / 观察 | 2922230.49 | 6351788.19 | -0.68% | -0.79% | -0.0384% | 27137656.99 | -7.93% | 观察 | 合约已上线，暂未出现明显OI/资金费率信号；其他场地 okx_swap 拥挤 OI≈999228.13 funding -0.0643%; OI和价格变化不足，合约层只作背景 |
| `GRAM` | `GRAMUSDT` | bybit_linear,okx_swap | listed_quiet / 观察 | 13825902.19 | 17865585.86 | - | - | 0.0050% | 9085207.00 | -4.01% | 观察 | Binance USD-M未上；bybit_linear 合约已上线，暂未出现明显OI/资金费率信号; 历史窗口不足 |
| `NES` | `NES-USDT-SWAP` | okx_swap | listed_quiet / 观察 | 1335062.99 | 1335062.99 | -1.55% | -1.36% | 0.0050% | 8501339.41 | -7.20% | 观察 | Binance USD-M未上；okx_swap 合约已上线，暂未出现明显OI/资金费率信号; OI和价格变化不足，合约层只作背景 |
| `CAP` | `CAPUSDT` | binance_usdm,okx_swap,bybit_linear | active_perp_market / 可观察 | 4240493.91 | 8517886.15 | +24.41% | +10.30% | 0.0350% | 83028298.43 | 49.04% | 多头增量 | 合约成交活跃，可配合链上出流和价格结构判断；其他场地 okx_swap 可观察 OI≈2390595.38 funding 0.0050%；bybit_linear 可观察 OI≈1886796.86 funding 0.0236%; OI扩张且价格上涨，重点等现货承接和链上净流确认 |
| `ESPORTS` | `ESPORTSUSDT` | binance_usdm,bybit_linear | listed_quiet / 观察 | 11394076.56 | 16023501.81 | +0.03% | +0.15% | 0.0446% | 17129398.41 | 0.43% | 观察 | 合约已上线，暂未出现明显OI/资金费率信号; OI和价格变化不足，合约层只作背景 |
| `VELVET` | `VELVETUSDT` | binance_usdm,bybit_linear | listed_quiet / 观察 | 51580687.47 | 66999516.96 | +1.07% | +1.21% | 0.0456% | 195539726.09 | -2.64% | 观察 | 合约已上线，暂未出现明显OI/资金费率信号；其他场地 bybit_linear 拥挤 OI≈15418829.49 funding 0.1002%; OI和价格变化不足，合约层只作背景 |

## Surf Auxiliary Market

| Symbol | Venues | Spot last | DEX last | Basis | Spot 4h high | DEX 24h high | Listings | Authority |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `CAP` | mexc / perp:binance | 0.025500 | 0.025496 | 0.01% | 0.027320 | 0.035839 | 11 | `context_only` |

- Surf 只用于外部市场背景，不能单独触发买卖动作。

## External Auxiliary Sources

| Source | Category | Status | Authority | Next step |
| --- | --- | --- | --- | --- |
| CoinGlass API | derivatives_market_data | `needs_credentials` | `context_only` | configure COINGLASS_API_KEY |
| CoinAnk OpenAPI | derivatives_market_data | `needs_credentials` | `context_only` | configure COINANK_API_KEY |
| GMGN.AI | onchain_smart_money | `needs_credentials` | `context_only` | configure GMGN_API_KEY |
| AskSurf Surf Skill | multi_source_crypto_data | `ready_for_live_probe` | `context_only` | run a small live probe and set validation env only after output matches local rules |
| DeBot AI | onchain_bot_alerts | `manual_context_only` | `context_only` | use screenshots_exports_or_forwarded_alerts_as_context; keep out of direct action rules |

## Action Queue

1. ARX: 以开盘块、首批买入、bribe、活动分发和交易所流向作为主线。
2. O1: 已暂停主动钱包监控，只保留历史复盘样本。
3. RE: 做 Alpha 到 CEX 承接复盘，重点看 Prime Sale、充值地址、现货/永续价差。
4. VELVET/ESPORTS: 先看交易赛带来的真实成交质量和活动钱包。
5. NIGHT/GRAM: 作为 OKX Boost/衍生品结构样本，等链上合约确认后上调。
6. External sources: Coinglass/CoinAnk/GMGN 先跑 readiness 和 live probe，再允许进入动作文案。

## Sources

- Binance New Cryptocurrency Listing: https://www.binance.com/en/support/announcement/list/48
- OKX New listings: https://www.okx.com/help/section/announcements-new-listings
- OKX NIGHT Boost: https://www.okx.com/en-us/learn/trade-dex-night-boost
- Local verification: `output/sniper_engine/verification_report.md`
- Local monitor: `output/monitoring/alerts.md`
