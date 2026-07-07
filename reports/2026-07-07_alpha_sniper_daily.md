# Alpha Sniper Daily Report

- date_cn: `2026-07-07`
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

## Alpha Price Momentum

| Symbol | Signal | Spot action | 15m high/low/close | 15m quote | Venue | Book | Reason |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| `ARX` | 无价格异动 | 观察 | +0.56%/-0.02%/+0.37% | 16469622.88 | UNKNOWN / PRICE_ONLY | crossed_or_stale | 未触发价格/成交额阈值；盘口结构: 盘口交叉或快照异常，盘口结构不下方向 |
| `CAP` | 无价格异动 | 观察 | +0.11%/-1.00%/-0.09% | 22919.91 | UNKNOWN / PRICE_ONLY | normal | 未触发价格/成交额阈值；当前 +5% 卖盘约 25,637.64 USDT，盘口偏薄；盘口结构: 卖盘重复数量梯队(3981.13 x12)，买盘重复数量梯队(3981.13 x7) |
| `NES` | 无价格异动 | 观察 | +0.82%/-1.70%/-1.05% | 4367303.47 | UNKNOWN / PRICE_ONLY | crossed_or_stale | 未触发价格/成交额阈值；盘口结构: 盘口交叉或快照异常，盘口结构不下方向 |
| `VELVET` | 无价格异动 | 观察 | +0.59%/-0.88%/+0.59% | 25624.85 | UNKNOWN / PRICE_ONLY | normal | 未触发价格/成交额阈值；当前 +5% 卖盘约 14,822.26 USDT，盘口偏薄 |
| `WDATAIP` | 无价格异动 | 观察 | +1.14%/-1.51%/-0.98% | 4046.75 | INSUFFICIENT_DATA / NO_DIRECTION | normal | 未触发价格/成交额阈值；当前 +5% 卖盘约 7,812.39 USDT，盘口偏薄 |

- Alpha 价格层只给动作提醒和注意力排序，跟随口径仍需要链上成交、首批去向、活动分发和可售性共同确认。

## Holder Concentration

| Symbol | Action | 联动判断 | 排除托管后前十 | 窗口重建前十 | 交易所/托管/池子 | 外部全量Top10 | Coverage |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `NES` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 0.24%；增加 0.02 个百分点 | 0.24%；增加 0.02 个百分点 | 0.01% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |
| `CAP` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 20.91%；增加 0.03 个百分点 | 26.98%；增加 0.10 个百分点 | 6.22% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |
| `WDATAIP` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 9.45%；增加 0.33 个百分点 | 35.10%；增加 0.18 个百分点 | 25.98% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |

- Holder 层用于判断筹码集中/分散；联动判断会结合价格动量和盘中链上大额流。排除托管后前十已剔除 CEX、Alpha 托管、LP、桥和 Pancake 基础设施。外部全量Top10字段会标明是否已接入 App 式全量 holder 源。

## Surf Auxiliary Market

| Symbol | Venues | Spot last | DEX last | Basis | Spot 4h high | DEX 24h high | Listings | Authority |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `CAP` | mexc / perp:binance | 0.025600 | 0.025474 | 0.49% | 0.027090 | 0.035839 | 11 | `context_only` |

- Surf 只用于外部市场背景，不能单独触发买卖动作。

## External Auxiliary Sources

| Source | Category | Status | Authority | Next step |
| --- | --- | --- | --- | --- |
| CoinGlass API | derivatives_market_data | `needs_credentials` | `context_only` | configure COINGLASS_API_KEY |
| CoinAnk OpenAPI | derivatives_market_data | `needs_credentials` | `context_only` | configure COINANK_API_KEY |
| GMGN.AI | onchain_smart_money | `needs_credentials` | `context_only` | configure GMGN_API_KEY |
| AskSurf Surf Skill | multi_source_crypto_data | `ready_for_live_probe` | `context_only` | run a small live probe and set validation env only after output matches local rules |
| DeBot AI | onchain_bot_alerts | `manual_context_only` | `context_only` | use screenshots_exports_or_forwarded_alerts_as_context; keep out of direct action rules |

## Celue 策略校验清单

| 字段 | 本地来源 | 使用要求 |
| --- | --- | --- |
| `source_layers` | official / onchain / market / social / inference | 每条交易判断先分离来源类型，再写动作。 |
| `path_stage` | alpha_intraday_flow_watch CEX fields, opening buyer trace, wallet monitor | 标记 source -> CEX cold/hot/deposit -> intermediate wallet -> perp venue treasury/sell venue -> quote recovery。 |
| `cluster_evidence` | funding_source_clusters, intraday runtime CEX candidates, gas priming | 记录钱包数量、共同来源、共同时间窗、共同充值端口、共同 gas 来源。 |
| `deposit_status` | exchange announcements, listing calendar, watchlist required_checks | 记录 closed、open、reopened、chain-supported、chain-migrated、unknown。 |
| `derivatives_ratio` | perp_oi_funding_watch plus MC/FDV from market_context or external validated sources | 跟踪 OI/MC、OI/FDV、24h volume/MC 和 funding 方向。 |
| `event_window` | prelaunch, listing, delisting, unlock, deposit reopen, sector rotation | 附上精确事件窗口和下一次检查时间。 |
| `index_or_deposit_policy_event` | exchange announcements, Binance index basket changes, deposit closure/reopen | 记录充值端口、指数篮子、场所支持变化，并作为市场结构事件处理。 |
| `operator_supply` | holder concentration, tokenomics, CEX/pool/custody labels | 拆分 operator、CEX/pool/custody、verified retail、unknown supply。 |
| `catalyst_source` | official links, founder/exchange posts, KOL/social, media, community | 社交输入进入 discovery 层；动作依赖本地证据确认。 |
| `meme_stage` | first-seen time, market cap, liquidity, holder quality, price multiple | 标记 pre-viral、first trigger、post-5x、post-10x、exhausted、unknown。 |
| `tokenomics_catalyst` | tokenomics section, announcements, on-chain execution | 区分 burn、buyback、buyback-to-liquidity、fee donation、foundation、airdrop、initial float、utility change。 |
| `identity_label_quality` | global address labels, external label review, custody/MM/foundation checks | 标记 verified official、exchange/custody、market maker、inferred whale、KOL、unknown。 |
| `venue_rotation` | price momentum venue class, CEX listings, Surf context-only market rows | 跟踪 Binance Alpha、Binance spot/perps、Binance Wallet、Coinbase、Korea CEX、SOL/Pump、Base、ASTER、unknown。 |

- 动作标签固定使用：Avoid、Observe、Reduce、Small test、Follow only after confirmation。
- 每条实盘判断都要写止损规则、失效证据、退出触发器和下一次检查时间。

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
