# Alpha Sniper Daily Report

- date_cn: `2026-07-17`
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

- No upcoming P0/P1 launch windows in prelaunch watch output.

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

| Symbol | Perp | Venues | State | Main OI | Total OI | OI Δ | Price Δ | Funding 8h | Funding 24h | 24h Vol | 24h Chg | Trend | Action |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| `ARX` | `ARXUSDT` | binance_usdm,okx_swap,bybit_linear | listed_quiet / 观察 | 2862323.97 | 4507577.34 | -5.72% | -11.07% | 0.0100% | neutral_funding / avg8h 0.0096% / cum 0.0337% | 24712869.91 | -3.26% | 降杠杆 | 合约已上线，暂未出现明显OI/资金费率信号；盘口±50bps bid≈7884.27 ask≈22439.65 spread≈6.25bps，合约盘口薄; OI收缩，合约资金撤退，价格信号需要现货成交确认 |

## Alpha Price Momentum

| Symbol | Signal | Spot action | 15m high/low/close | 15m quote | Venue | Book | Reason |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| `ARX` | 无价格异动 | 观察 | +0.12%/-0.25%/-0.25% | 17699707.37 | UNKNOWN / PRICE_ONLY | crossed_or_stale | 未触发价格/成交额阈值；盘口结构: 盘口交叉或快照异常，盘口结构不下方向 |
| `CAP` | 无价格异动 | 观察 | +0.41%/-0.11%/-0.00% | 4504.83 | INSUFFICIENT_DATA / NO_DIRECTION | normal | 未触发价格/成交额阈值；当前 +5% 卖盘约 31,674.97 USDT，盘口偏薄；盘口结构: 卖盘重复数量梯队(4219.24 x10)，买盘重复数量梯队(4219.24 x9) |
| `NES` | 无价格异动 | 观察 | +1.03%/-0.14%/+0.85% | 2174572.25 | UNKNOWN / PRICE_ONLY | crossed_or_stale | 未触发价格/成交额阈值；盘口结构: 盘口交叉或快照异常，盘口结构不下方向 |
| `VELVET` | 无价格异动 | 观察 | +1.71%/-0.91%/+0.66% | 10636.80 | INSUFFICIENT_DATA / NO_DIRECTION | normal | 未触发价格/成交额阈值；盘口结构: 卖盘重复数量梯队(194.13 x5)，买盘重复数量梯队(194.58 x5)；合约层可观察，合约成交活跃，可配合链上出流和价格结构判断；盘口±50bps bid≈14517.77 ask≈19781.69 spread≈3.88bps，合约盘口薄；其他场地 bybit_linear 可观察 OI≈2702263.47 funding8h 0.0100% |
| `WDATAIP` | 无价格异动 | 观察 | 0.00%/0.00%/0.00% | 0.00 | INSUFFICIENT_DATA / NO_DIRECTION | normal | 未触发价格/成交额阈值；当前 +5% 卖盘约 75.48 USDT，盘口偏薄；盘口结构: 买盘集中在少数档位，承接质量需看成交，卖盘集中在少数档位，卖压判断需看撤挂和成交，价差偏宽(1.45%) |

- Alpha 价格层只给动作提醒和注意力排序，跟随口径仍需要链上成交、首批去向、活动分发和可售性共同确认。

## CEX Wallet Flow

- No verified CEX inflow, internal aggregation, or withdrawal-cluster observation in the latest intraday snapshot.
- `+归集` 先核验 receipt 与 CEX 目标；未标记来源进入供给风险候选，CEX/Alpha 内部路径保持 report-only，来源实体和出售意图继续 unresolved。
- Internal gross turnover 是内部路径 Transfer 毛额；同一批代币经过多跳时可能重复出现，不作为净经济流。

## Holder Concentration

| Symbol | Action | 联动判断 | 排除托管后前十 | 窗口重建前十 | 交易所/托管/池子 | 外部全量Top10 | Coverage |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `NES` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 0.29%；增加 0.00 个百分点 | 0.29%；增加 0.00 个百分点 | 0.00% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |
| `CAP` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 24.93%；增加 0.03 个百分点 | 31.69%；增加 0.09 个百分点 | 7.03% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |
| `WDATAIP` | 观察；筹码集中度未给出新方向 | 观察；holder只作辅助 | 8.50%；减少 0.11 个百分点 | 20.31%；减少 0.13 个百分点 | 12.08% | 未接入；当前显示窗口重建口径 | window_or_incremental_reconstruction |

- Holder 层用于判断筹码集中/分散；联动判断会结合价格动量和盘中链上大额流。排除托管后前十已剔除 CEX、Alpha 托管、LP、桥和 Pancake 基础设施。外部全量Top10字段会标明是否已接入 App 式全量 holder 源。

## Surf Auxiliary Market

| Symbol | Venues | Spot last | DEX last | Basis | Spot 4h high | DEX 24h high | Listings | Authority |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `RE` | binance,bitget,okx / perp:binance,bybit,okx | 0.585000 | 0.000000 | 0.00% | 0.592200 | - | 2 | `context_only` |
| `ARX` | bitget,bybit,kucoin,mexc,upbit / perp:binance,bitget,bybit,gate,htx,kucoin,mexc,okx | 0.180100 | 0.180503 | -0.22% | 0.182400 | 0.184629 | 1 | `context_only` |
| `GRAM` | binance,bitget,bybit,gate,htx,kucoin,mexc,okx,upbit / perp:binance,bitget,bitmex,bybit,gate,htx,kucoin,mexc,okx | 1.622000 | 0.000000 | 0.00% | 1.631000 | - | 10 | `context_only` |
| `NES` | bitget,gate,htx,kucoin,mexc,okx / perp:gate,htx,kucoin,mexc,okx | 0.270500 | 0.269342 | 0.43% | 0.277300 | 0.286269 | 1 | `context_only` |
| `CAP` | bybit,htx,kucoin,mexc / perp:binance,bitget,bybit,gate,htx,kucoin,mexc,okx | 0.021892 | 0.021802 | 0.41% | 0.022318 | 0.023290 | 11 | `context_only` |
| `ESPORTS` | gate,kucoin,mexc / perp:binance,bitget,bybit,gate,kucoin,mexc | 0.026390 | 0.000000 | 0.00% | 0.027600 | - | 0 | `context_only` |
| `VELVET` | bitget,gate,kucoin,mexc / perp:binance,bitget,bybit,gate,htx,kucoin,mexc | 0.518690 | 0.517817 | 0.17% | 0.520640 | 0.532956 | 0 | `context_only` |
| `WDATAIP` | - | 0.000000 | 0.283135 | 0.00% | - | 0.283579 | 0 | `context_only` |

- Surf 只用于外部市场背景，不能单独触发买卖动作。

## External Auxiliary Sources

| Source | Category | Status | Authority | Next step |
| --- | --- | --- | --- | --- |
| CoinGlass API | derivatives_market_data | `needs_credentials` | `context_only` | configure COINGLASS_API_KEY |
| CoinAnk OpenAPI | derivatives_market_data | `needs_credentials` | `context_only` | configure COINANK_API_KEY |
| GMGN.AI | onchain_smart_money | `needs_credentials` | `context_only` | configure GMGN_API_KEY |
| AskSurf Surf Skill | multi_source_crypto_data | `ready_for_live_probe` | `context_only` | run a small live probe and set validation env only after output matches local rules |
| DeBot AI | onchain_bot_alerts | `manual_context_only` | `context_only` | use screenshots_exports_or_forwarded_alerts_as_context; keep out of direct action rules |

### External Aux Live Probe

| Source | Status | HTTP | Validation | Next step |
| --- | --- | ---: | --- | --- |
| CoinGlass API | `needs_credentials` |  | `AUX_SOURCE_VALIDATED_COINGLASS` | Configure COINGLASS_API_KEY in server .env.local, then rerun this probe. |
| CoinAnk OpenAPI | `needs_credentials` |  | `AUX_SOURCE_VALIDATED_COINANK` | Configure COINANK_API_KEY in server .env.local, then rerun this probe. |
| GMGN.AI | `needs_credentials` |  | `AUX_SOURCE_VALIDATED_GMGN` | Configure GMGN_API_KEY in server .env.local, then rerun this probe. |
| AskSurf Surf Skill | `handled_by_surf_aux_market_watch` |  | `AUX_SOURCE_VALIDATED_SURF` | Use SURF_AUX_MAX_PROJECTS=1 python3 scripts/surf_aux_market_watch.py for a paid/credit-aware live check. |

## Position / Cost Watch

- No configured real positions. `config/user_positions.json` is git-ignored; fill it locally when needed.
- No paper trade plans configured.

## Celue 策略校验清单

| 字段 | 本地来源 | 使用要求 |
| --- | --- | --- |
| `source_layers` | official / onchain / market / social / inference | 每条交易判断先分离来源类型，再写动作。 |
| `path_stage` | alpha_intraday_flow_watch CEX fields, opening buyer trace, wallet monitor | 标记 source -> CEX cold/hot/deposit -> intermediate wallet -> perp venue treasury/sell venue -> quote recovery。 |
| `cex_wallet_aggregation` | Binance Alpha due-diligence UI plus alpha_intraday_flow_watch receipt paths | 官方 +归集 只作发现；TXID/receipt 核验后区分供给风险候选、CEX 内部归集和 Alpha 托管相关未决路径，内部路径仅报告。 |
| `cluster_evidence` | funding_source_clusters, intraday runtime CEX candidates, gas priming | 记录钱包数量、共同来源、共同时间窗、共同充值端口、共同 gas 来源。 |
| `deposit_status` | exchange announcements, listing calendar, watchlist required_checks | 记录 closed、open、reopened、chain-supported、chain-migrated、unknown。 |
| `derivatives_ratio` | perp_oi_funding_watch plus MC/FDV from market_context or external validated sources | 跟踪 OI/MC、OI/FDV、24h volume/MC 和 funding 方向。 |
| `event_window` | prelaunch, listing, delisting, unlock, deposit reopen, sector rotation | 附上精确事件窗口和下一次检查时间。 |
| `index_or_deposit_policy_event` | exchange announcements, Binance index basket changes, deposit closure/reopen | 记录充值端口、指数篮子、场所支持变化，并作为市场结构事件处理。 |
| `operator_supply` | holder concentration, tokenomics, CEX/pool/custody labels | 拆分 operator、CEX/pool/custody、verified retail、unknown supply。 |
| `catalyst_source` | official links, founder/exchange posts, KOL/social, media, community | 社交输入进入 discovery 层；动作依赖本地证据确认。 |
| `meme_stage` | first-seen time, market cap, liquidity, holder quality, price multiple | 标记 pre-viral、first trigger、post-5x、post-10x、exhausted、unknown。 |
| `tokenomics_catalyst` | tokenomics section, announcements, on-chain execution | 区分 burn、buyback、buyback-to-liquidity、fee donation、foundation、airdrop、initial float、utility change。 |
| `supply_lifecycle` | official tokenomics plus on-chain supply and first-receiver paths | 区分 mint、reissue、retirement、compensation、snapshot、migration，并核对相对流通量、锁定和 CEX/LP 去向。 |
| `identity_label_quality` | global address labels, external label review, custody/MM/foundation checks | 标记 verified official、exchange/custody、market maker、inferred whale、KOL、unknown。 |
| `venue_rotation` | price momentum venue class, CEX listings, Surf context-only market rows | 跟踪 Binance Alpha、Binance spot/perps、Binance Wallet、Coinbase、Korea CEX、SOL/Pump、Base、ASTER、unknown。 |
| `outcome_ledger` | deduped KOL root signal plus fixed-horizon local replay | 同一原始信号的引用更新只计一次；记录 24h/72h/7d、MFE、MAE、期末收益、失效和 unresolved。 |
| `regime_expectancy` | current liquidity, MC/FDV, aggregate OI, venue policy, capital breadth | 按当前市场重算目标、分段止盈和 time stop；历史倍数只作背景。 |
| `source_time_sanity` | source published time, claimed event time, quote context | 时间或引用上下文冲突时保持待证，不升级事实层。 |
| `flow_recycling_candidate` | gross buy/sell, net-to-gross, round-trip addresses, quote recovery | 只作 report-only 候选；本地验证前不改变告警或动作。 |

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
