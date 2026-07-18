# Server Runbook

更新日期：2026-07-10

当前版本已经覆盖本地推文评分、Telegram/项目线索摄取、Alpha 项目级监控、预发布窗口、Alpha 开盘首批买家回溯、首批买家 funding source、Alpha 官方价格动量、Alpha 盘中大额流监控、holder 集中度、合约 OI/funding/盘口/强平、Surf 外部市场辅助层、外部辅助源 readiness、预测市场、日报、系统自检和失败才推送的运行健康告警。

## 本地验证

```bash
cd /Users/xuyufan/Documents/狙击手进程
python3 scripts/sniper_score_local.py
python3 scripts/build_monitored_wallets.py
MONITOR_LOOKBACK_BLOCKS=5000 python3 scripts/sniper_monitor.py
python3 scripts/alpha_project_watch.py
python3 scripts/alpha_prelaunch_watch.py
python3 scripts/alpha_opening_block_watch.py
python3 scripts/review_opening_cohort_funders.py --lookback-blocks 0 --max-scan-seconds 25
python3 scripts/alpha_intraday_flow_watch.py
python3 scripts/perp_oi_funding_watch.py
python3 scripts/alpha_price_momentum_watch.py
python3 scripts/alpha_holder_concentration_watch.py
SURF_AUX_MAX_PROJECTS=2 python3 scripts/surf_aux_market_watch.py
python3 scripts/prediction_market_watch.py
python3 scripts/external_aux_source_readiness.py
python3 scripts/external_aux_live_probe.py --source surf
python3 scripts/position_cost_watch.py
python3 scripts/runtime_health_watch.py --mode cycle --no-telegram
python3 scripts/x_mcp_readiness.py --no-network --skip-xurl
python3 scripts/simulate_pancake_v4_roundtrip_call.py --pin-block --sell-quote-share-bps 10000 --recovery-iterations 40
python3 scripts/o1_address_attribution.py
python3 scripts/build_alpha_daily_report.py
python3 scripts/verify_sniper_engine.py
```

输出：

```text
output/sniper_engine/signal_scores.csv
output/sniper_engine/signal_scores.md
config/monitored_wallets.json
output/monitored_wallets.md
output/monitoring/latest_snapshot.json
output/monitoring/wallet_snapshot.csv
output/monitoring/alerts.md
output/monitoring/telegram_payload.txt
output/project_registry/project_registry.json
output/project_registry/project_registry.md
output/alpha_prelaunch_watch/latest.md
output/alpha_opening_block_watch/latest.json
output/alpha_opening_block_watch/latest.md
output/opening_cohort_funders/latest.json
output/opening_cohort_funders/latest.md
output/alpha_intraday_flow_watch/latest.json
output/alpha_intraday_flow_watch/latest.md
output/perp_oi_funding_watch/latest.json
output/perp_oi_funding_watch/latest.md
output/alpha_price_momentum_watch/latest.json
output/alpha_price_momentum_watch/latest.md
output/alpha_holder_concentration_watch/latest.json
output/alpha_holder_concentration_watch/latest.md
output/o1_address_attribution/address_attribution.csv
output/o1_address_attribution/o1_address_attribution.md
output/surf_aux_market_watch/latest.json
output/surf_aux_market_watch/latest.md
output/prediction_markets/latest_prediction_markets.json
output/prediction_markets/prediction_markets.md
output/external_aux_sources/latest.json
output/external_aux_sources/latest.md
output/external_aux_live_probe/latest.json
output/external_aux_live_probe/latest.md
output/position_cost_watch/latest.json
output/position_cost_watch/latest.md
output/runtime_health/latest.json
output/runtime_health/latest.md
output/runtime_health/last_cycle.json
output/x_mcp_readiness/latest.json
output/x_mcp_readiness/latest.md
output/pancake_v4_roundtrip_call/latest.json
output/pancake_v4_roundtrip_call/latest.md
reports/YYYY-MM-DD_alpha_sniper_daily.md
output/sniper_engine/verification_report.md
```

## 当前服务器部署

```text
/home/ubuntu/sniper/
  scripts/
  config/
  output/
  reports/
  logs/
```

当前运行入口：

```bash
cd /home/ubuntu/sniper
bash scripts/server_run_once.sh
```

这个脚本会依次执行：

```text
scripts/sniper_monitor.py
scripts/alpha_project_watch.py
scripts/alpha_prelaunch_watch.py
scripts/alpha_opening_sprint.sh
scripts/review_opening_cohort_funders.py
scripts/alpha_intraday_flow_watch.py
scripts/perp_oi_funding_watch.py
scripts/alpha_price_momentum_watch.py
scripts/alpha_holder_concentration_watch.py
scripts/surf_aux_market_watch.py
scripts/arx_opening_sprint.sh 条件执行
scripts/arx_launch_watch.py 条件执行
scripts/telegram_signal_collector.py
scripts/telegram_user_signal_collector.py
scripts/prediction_market_watch.py
scripts/external_aux_source_readiness.py
scripts/external_aux_live_probe.py 条件执行
scripts/o1_address_attribution.py 条件执行
scripts/position_cost_watch.py
scripts/build_alpha_daily_report.py
scripts/verify_sniper_engine.py
scripts/runtime_health_watch.py
```

服务器 cron 通过幂等安装脚本维护：

```bash
cd /home/ubuntu/sniper
bash scripts/install_server_cron.sh
```

安装后有两条独立任务：主循环每 5 分钟运行；watchdog 每 10 分钟检查 `output/runtime_health/last_cycle.json`。主循环会把每个步骤的非零退出码写入本轮临时失败清单，最后检查核心产物新鲜度和 `verification_report.md`。健康状态不发消息；首次故障、故障类型变化、持续故障到提醒周期和故障恢复才发 Telegram。watchdog 可发现主脚本在健康检查前异常退出或主循环心跳超过默认 20 分钟未更新。服务器或 crond 整体离线仍需要外部主机级监控。

## 环境变量

后续接实时链上监控时需要：

```bash
export NODEREAL_API_KEY="..."
export BSC_RPC_URL="..."
export BASE_RPC_URL="..."
export BSCSCAN_API_KEY="..."
export BASESCAN_API_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export SNIPER_MONITOR_TELEGRAM="1"
```

这些值只放在服务器环境或 `.env`，不进 git。

`sniper_monitor.py` 当前使用 NodeReal 的 `nr_getAssetTransfers` 扫 ERC-20 最近转账。服务器上至少需要 `NODEREAL_API_KEY`，或兼容同方法的 BSC RPC。

Telegram 推送默认关闭。设置 `SNIPER_MONITOR_TELEGRAM=1` 后，脚本会读取 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 发送摘要；本地始终会生成 `output/monitoring/telegram_payload.txt`。

常用参数：

```bash
export MONITOR_LOOKBACK_BLOCKS=5000
export MONITOR_FINALITY_BLOCKS=20
export TELEGRAM_MIN_INTERVAL_SECONDS=900
export ALPHA_INTRADAY_WINDOW_BLOCKS=1800
export ALPHA_INTRADAY_BUY_ALERT_QUOTE=20000
export ALPHA_INTRADAY_SELL_ALERT_QUOTE=20000
export ALPHA_INTRADAY_REPEAT_SUPPRESS_MINUTES=30
export ALPHA_PRICE_15M_SPIKE_PCT=15
export ALPHA_PRICE_15M_CLOSE_PCT=8
export ALPHA_PRICE_QUOTE_ALERT=200000
export ALPHA_PRICE_REPEAT_SUPPRESS_MINUTES=30
export ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE=1
export ALPHA_OPENING_INFINITY_RECOVERY_ESTIMATE=1
export ALPHA_OPENING_INFINITY_RECOVERY_ITERATIONS=20
export ALPHA_OPENING_INFINITY_MIN_RECOVERY_RATE=0.80
export ALPHA_OPENING_INFINITY_ROUNDTRIP_SELL_SHARE_BPS=10000
export RUNTIME_HEALTH_TELEGRAM=1
export RUNTIME_HEALTH_SEND_RECOVERY=1
export RUNTIME_HEALTH_MAX_OUTPUT_AGE_SECONDS=1800
export RUNTIME_HEALTH_MAX_CYCLE_AGE_SECONDS=1200
export RUNTIME_HEALTH_REPEAT_MINUTES=360
```

Telegram 当前有两层控制：

- `telegram_seen_alerts.json`：按链、代币、地址、告警级别、方向、最后一笔交易哈希去重。
- `TELEGRAM_MIN_INTERVAL_SECONDS`：默认 900 秒，避免高频地址在短时间内连续刷屏。

`MONITOR_FINALITY_BLOCKS` 默认 20，用来等待 NodeReal 的资产转账索引追上最新区块，减少 `blockNum not reached` 这类索引滞后错误。

`review_opening_cohort_funders.py` 在 `alpha_opening_sprint.sh` 之后运行，用于从开盘首批买家里回查最近原生 BNB funding source，并把同源 funding cluster 写到 `output/opening_cohort_funders/latest.*`。默认 `OPENING_COHORT_FUNDER_LOOKBACK_BLOCKS=120`，同时受 `OPENING_COHORT_FUNDER_MAX_SCAN_SECONDS=25` 和 `OPENING_COHORT_FUNDER_TIMEOUT_SECONDS=90` 限制；CEX、router、bridge、quote token 等不安全父节点仍由 clustering guard 排除。

`alpha_price_momentum_watch.py` 用于 Binance Alpha 官方行情层监控，读取公开 token list、K 线、ticker 和当前盘口深度。它补足链上监控看不到的 Alpha 撮合/限价单价格异动，输出在 `output/alpha_price_momentum_watch/`。价格层会同时监控放量上冲、冲高回落和放量下跌；放量收跌默认触发 `卖出/减仓观察`，空仓动作是等待止跌承接。盘口层会额外识别重复数量梯队、top N 可见买卖盘金额比、少数档位集中度和价差；这些字段只用于判断显示盘口质量，不能单独生成买入信号。若 fullDepth 返回交叉盘口或疑似过期快照，脚本会标记 `crossed_or_stale`，盘口结构不参与方向判断。

`surf_aux_market_watch.py` 用于外部市场辅助层，读取 watchlist 后通过 Surf 查询 CEX 现货/合约市场、CEX K 线、DEX 价格和上市事件。它补足 CAP 这类“链上 Pancake 净流不强，但 Alpha/CEX 可见价格已经拉动”的盲区，输出在 `output/surf_aux_market_watch/`。这个层的 `authority` 固定为 `auxiliary_context_only`，只能进入日报和背景判断，不能单独触发买入、卖出或开空建议。

Surf 免费额度耗尽时，脚本会写入 `output/surf_aux_market_watch/quota_state.json`，当天后续运行直接短路成 `surf_quota_exhausted_today`，避免 5 分钟 cron 反复打失败请求。

`perp_oi_funding_watch.py` 读取 Binance USD-M、OKX SWAP、Bybit linear 的公开合约指标。除 OI、funding、24h volume 和趋势外，它会抓取当前永续盘口，计算默认 ±50bps 内 bid/ask 深度、点差和深度偏斜；`thin_depth`、`wide_spread`、`ask_thin`、`bid_thin` 都只作为合约风险上下文，需要和现货承接、链上流向一起判断。历史 funding 从三家公开接口按真实结算时间差推断周期，统一为 8 小时口径，并输出当前预测费率、最新已结算费率、24 小时平均 8h 费率、24 小时累计费率、正负占比和拥挤/翻转状态。历史接口默认缓存 30 分钟，缓存文件为 `output/perp_oi_funding_watch/funding_history_cache.json`；历史费率单独不能生成买入结论。OKX 公开 `liquidation-orders` 可用时会补充近 60 分钟 long/short 强平金额；Binance force-orders 当前需要 API key 或已停维，Bybit liquidation 路由本地返回 404，暂不纳入自动上下文。

`external_aux_live_probe.py` 是 Coinglass / CoinAnk / GMGN 的小样本验收入口。默认服务器 cron 只跑 `external_aux_source_readiness.py`，不会消耗付费 API；设置 `RUN_EXTERNAL_AUX_LIVE_PROBE=1` 后才跑 live probe。Coinglass 使用 `COINGLASS_API_KEY` 和 `CG-API-KEY` header，CoinAnk 使用 `COINANK_API_KEY` 和 `apikey` header，GMGN 默认只检查 `GMGN_API_KEY`，如有只读查询端点再配置 `GMGN_PROBE_URL` 和可选 `GMGN_API_KEY_HEADER`。probe 通过后仍需人工确认字段能和本地规则对齐，再设置对应 `AUX_SOURCE_VALIDATED_*`。

`position_cost_watch.py` 是只读仓位/成本/纸面交易台账。真实文件是 `config/user_positions.json`，已加入 `.gitignore`；模板是 `config/user_positions.example.json`。脚本会合并 Alpha 价格、Surf、合约 OI/funding/盘口、盘中链上流和 holder 风险，输出仓位盈亏、止损/止盈触发、减仓观察、持仓天数、独立时间止损状态和纸面交易入场状态。时间止损由每仓位 `opened_at` 与 `time_stop_days` 派生，只提示复核，不改写价格/流向动作。它不读取私钥，不签名，不下单。

可调参数：

```bash
export SURF_AUX_MAX_PROJECTS=8
export SURF_AUX_SPOT_PRICE_LIMIT=3
export SURF_AUX_SWAP_PRICE_LIMIT=2
export SURF_AUX_LISTING_LOOKBACK_DAYS=14
export SURF_AUX_MARKET_TIMEOUT_SECONDS=180
export RUN_EXTERNAL_AUX_LIVE_PROBE=0
export EXTERNAL_AUX_LIVE_PROBE_TIMEOUT_SECONDS=60
export POSITION_COST_TIMEOUT_SECONDS=45
export PERP_WATCH_FUNDING_HISTORY_LIMIT=30
export PERP_WATCH_FUNDING_HISTORY_TTL_SECONDS=1800
export PERP_WATCH_FUNDING_HISTORY_CROWDING_8H=0.0005
export PERP_WATCH_FUNDING_HISTORY_FLIP_8H=0.0001
export PERP_WATCH_FUNDING_HISTORY_SUSTAINED_RATIO=0.75
```

`simulate_pancake_v4_roundtrip_call.py` 是 Pancake v4 / Infinity 可售性验证工具。它用 stateOverride 做同笔 USDT -> token -> USDT Universal Router `eth_call`，再通过提高 sell leg 的 `TAKE_ALL amountMinimum` 做二分估算，输出 quote 回收率。示例：

```bash
python3 scripts/simulate_pancake_v4_roundtrip_call.py \
  --pin-block \
  --sell-quote-share-bps 10000 \
  --recovery-iterations 40
```

开盘监控里对应 `ALPHA_OPENING_INFINITY_*` 参数。回收率通过只代表 v4 可售性 gate 过了，不会覆盖开盘块顺序、首批钱包去向、Alpha/CEX 盘口和活动分发规则。

`alpha_intraday_flow_watch.py` 用于开盘后链上盘中大额流监控。它不推送长地址和 tx，Telegram 只给方向、买卖信号、现货动作、合约动作、净买/净卖；完整地址和 tx 保存在 `output/alpha_intraday_flow_watch/latest.json` 和 `latest.md`。它按地址净额聚合，避免同一地址来回交易被误读为单边买入或单边卖出。

CEX 路径按经济角色拆分：外部地址进入 CEX deposit/hot 或 runtime sweep 候选为 `external_to_cex_inflow`，继续进入既有 CEX 风险门槛；deposit/sweep/hot 之间的后续搬运为 `cex_internal_aggregation`；涉及 Alpha Router/Custody/Rebalance 的路径为 `alpha_custody_movement_unresolved`。后两类固定 `direction=unknown`、`runtime_effect=none`、`alert_policy=report_only`，只写入盘中 JSON、Markdown 和日报，不进入 Telegram。`alpha_custody_movement_unresolved` 也覆盖外部地址进入 Alpha 托管入口，名称不推断内部调仓。`external -> runtime sweep -> hot` 只把按有序 FIFO 归因到后续 CEX 转出的外部入账计入一次，后续内部搬运不重复进入风险金额。`cex_internal_aggregation_token` 和对应 quote estimate 表示内部 Transfer 毛额，多跳时可重复出现同一批代币，仅用于路径审计。

FIFO 归因只覆盖当前抓取窗口内可见的 Transfer，窗口开始前余额保持未知；候选金额是已观察路径的归因量。窗口 Transfer 先按 `(transactionHash, logIndex)` 中央去重，再供 runtime candidate、withdrawal cluster、配置 CEX 直达聚合和 forward evidence 共用；缺失日志身份或同一锚点内容冲突会关闭本窗口风险贡献。只有 transfer coverage 与本次扫描区间完整吻合且未触发日志上限时，窗口聚合量才进入风险门槛；部分覆盖保留观察字段并固定 `runtime_effect=none_incomplete_coverage`。

`configured_cex_inflow_aggregate_rows` 聚合同窗口内直接进入已配置 CEX deposit/hot wallet 的剩余外部流入，使多笔单笔低于门槛、窗口合计达到门槛的路径进入既有 CEX 风险判断。已由 receipt row 计入的 tx 整笔排除，避免单笔大额与窗口日志重复；runtime candidate 的外部入账继续只由 FIFO 聚合贡献，candidate 到 CEX 的后续腿继续归为内部搬运。CEX 内部和 Alpha 托管路径保持 `direction=unknown`、`runtime_effect=none`、`report_only`。聚合明细只写入 `latest.json`、`latest.md` 与日报，Telegram 沿用既有精简摘要。回归证据见 `input/configured_cex_window_aggregation_verification_2026-07-18.json` 和 `cases/2026-07-18_configured_cex_window_aggregation.md`。

每个已抽样 receipt 的 `cex_path_sample` 在 `latest.json` 保存完整 from/to/角色，`latest.md` 保存对应完整 tx 和路径明细。

Binance Alpha 尽调中心的 `CEX 钱包归集资金动态` 可作为 `official` 发现源。界面中的 `+归集` 不直接映射为吸筹、买入、项目方派发或已确认卖出。取得 TXID 并核对 receipt、token contract、from/to、decimals 和已配置 CEX 目标后，未标记来源进入 `unlabeled_to_cex_inflow_candidate` 供给风险门槛；明确项目、operator、mint 或 token-contract 来源进入 `external_to_cex_inflow`。来源实体、经济外部入金、出售意图和下一跳继续独立标记。无法取得 TXID 或目标地址标签冲突时保持 pending，并进入人工复核。

其中 `cex_withdrawal_cluster` 只生成 `report_only` 候选。提款集群与 runtime CEX 候选链路共用一轮带 coverage 的 Token Transfer 分段抓取；模块原有的主交易抽样查询仍是独立读取。coverage 记录请求区间、完成分段数、最后覆盖块、返回日志数和上限。只有请求区间完整覆盖且未触发日志上限时才移除 `log_window_completeness`。同一批日志会计算每个候选收款地址在首次集群入账前的同币种入账次数；`new_to_token_in_window` 只表示完整扫描窗口内未见更早的同币种入账，不代表新钱包或全链历史完整。

候选通过热钱包来源、收款地址数、金额离散度、价值和区块跨度门槛后，程序读取首末块公共 RPC header，记录 `first_block_time_utc`、`last_block_time_utc`、`window_seconds` 和 `time_window_evidence`。单次进程最多尝试四次 RPC，每次超时限制在一至三秒。RPC 不可用、预算耗尽、时间戳无效或顺序异常时，`exact_time_window` 继续列在 `unresolved_gates`。

`output/alpha_intraday_flow_watch/withdrawal_candidate_history.json` 会复用当轮已经抓取的日志和抽样 receipt，跟踪样本地址在 anchor 之后的普通下一跳、已配置 CEX 回充、已配置 DEX 路径、同 receipt 卖出及 quote 回收。空窗口只记录为有限范围内未观察，不会清除历史正证据。样本收款地址还会在最后一个抽样 anchor block 执行历史 `eth_getCode` 三态核验：`eoa_at_anchor_block`、`contract_at_anchor_block`、`rpc_unresolved`。单进程固定最多四次 RPC、单地址最多两个 endpoint、每次一秒；成功状态跨轮保留，未决地址按历史尝试次数优先级渐进重试。抽样地址全部为 EOA 时，`unknown_contract_filter` 仍保持未决。

上述增强保持 `direction=unknown`、`action=Observe`、交易信号和 Telegram 路径不变。共同原生 Gas 来源仍需低延迟索引数据，实体关联和 operator conflict 仍需独立证据，不能通过逐块原生转账扫描在线推断。

无凭证 BSC 原生历史数据源的验收记录在 `cases/2026-07-15_bsc_native_history_source_review.md`。当前 Etherscan V2 的 chain 56 历史接口需要付费 key，Routescan 官方接口不支持 chain 56，Blockscout PRO 支持表和 Chainscout registry 探针未核实到 BSC mainnet 官方实例。满足带区块边界的完整分页、约四秒总预算及明确成功状态之前，`common_gas_source_ratio` 保持空值，`common_gas_source` 保持未决；禁止用逐块扫描替代索引覆盖。

`sniper_engine/exchange_aggregator.py` 固化 Binance Alpha 托管/聚合器识别边界。交易所聚合器候选必须命中机制指纹：跨 token 复用、稳定币腿/山寨币腿配对结构、共享 Binance Wallet DEX Router。双向高频、合约直连 pool 只作为辅助信号，单独出现时归入 `mm_or_project_suspect`，进入下一跳和资金来源追踪。`confirmed_dex_sell` 对任何主体都保留市场偏空效果；交易所/项目标签只影响 cohort 归类，不能豁免真实 DEX 卖出。

`ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT` 默认 `0`。在 Binance Alpha 成交额远高于 Pancake 链上成交时，`alpha_price_momentum_watch.py` 会把覆盖标记为 `ONCHAIN_NETFLOW_UNRELIABLE`，链上净流层只作注意力背景，不能用“买后持有 / 未见卖出 / 买卖平衡”生成偏多判断。开盘监控也会把 `ALPHA_DOMINANT` 场景降级为观察，直到真实 trace 证明聚合器和再平衡地址可以稳定剔除。

`scripts/verify_alpha_aggregator_trace.py` 是 trace 到手后的只读验证入口。示例：

```bash
python3 scripts/collect_alpha_trace_bundle.py \
  --chain bsc \
  --tx 0xAlphaSwapTx1 \
  --tx 0xAlphaSwapTx2 \
  --tx 0xAlphaSwapTx3
```

采集脚本会输出 `output/alpha_trace_samples/*.json`。每个文件包含交易、receipt、Transfer logs，以及 RPC 支持时的 debug call trace。RPC 不支持 debug 时也会写出错误原因，后续 verifier 会把 router 证据不足作为明确 warning。

```bash
python3 scripts/verify_alpha_aggregator_trace.py \
  --input output/alpha_trace_samples/bsc_..._0xAlpha1.json \
  --token auto \
  --quote 0x55d398326f99059ff775485246999027b3197955 \
  --router 0xRouterCandidate \
  --history output/alpha_trace_samples/bsc_..._0xAlpha2.json output/alpha_trace_samples/bsc_..._0xAlpha3.json
```

脚本只打印候选角色、机制指纹和人工确认队列，不自动写入 allowlist。第一版 allowlist 必须人工过眼。

如果外部 agent 已经给出一批 tx hash，可以直接跑采集+审查一体化入口：

采样要求见 `docs/alpha_swap_trace_request_prompt.md`。优先让外部 agent 返回 raw tx hash 列表和 Markdown 表格；`--tx-file` 也可以直接读取包含 BscScan 链接的 Markdown 报告。

```bash
python3 scripts/review_alpha_swap_txs.py \
  --chain bsc \
  --tx-file /path/to/alpha_swap_txs.txt \
  --address 0x73d8bd54f7cf5fab43fe4ef40a62d390644946db \
  --address 0x6aba0315493b7e6989041c91181337b662fb1b90 \
  --address 0xb300000b72deaeb607a12d5f54773d1c19c7028d
```

输出会落到 `output/alpha_trace_samples/tx_review/<UTC>/review/latest.md`。这个入口会先采集 receipt/debug trace bundle，再调用批量审查器；仍然只出报告，不自动改 `config/global_address_labels.json`。

trace 样本要求：

- 至少覆盖 3 个不同 Alpha token；单个 token 的多笔 trace 只能验证本币结构，不能证明共享基础设施。
- `stable_custody_candidates` 是地址集合；币安稳定币托管可能分流到多个地址，不能假设只有一个。
- `leg_summary` 会分开内部托管转账和真实触池腿。`custody_internal_transfer` / `quote_custody_internal_leg` 只说明托管内部流转；`quote_custody_to_router` / `token_router_or_pool_leg` 才是进入 router / pool 的成交路径。
- `pool_or_external_candidates` 会从山寨币托管候选中剔除，避免把 pool 当成托管腿写进 allowlist。
- `--token auto` 会从非报价币 Transfer 里推断本次 Alpha token，并默认排除 USDT/USDC/BUSD/WBNB/BTCB/ETH 这类常见路由资产；如果一个 tx 涉及多个真实 Alpha token，改用显式 `--token 0x...`。
- 候选写入规则：`exchange_aggregator_suspect` 可用于先排除 cohort 污染；升级到正式 `exchange_aggregator` 前，仍需 debug trace 或其他来源确认稳定币腿/山寨币腿配对结构。

## 当前 Cron

```bash
*/5 * * * * /home/ubuntu/sniper/scripts/server_run_once.sh >> /home/ubuntu/sniper/logs/server_run_once.log 2>&1
```

## Telegram 自动收件

入口：

```bash
python3 scripts/telegram_signal_collector.py
```

初始化 offset，跳过历史消息：

```bash
python3 scripts/telegram_signal_collector.py --bootstrap
```

当前覆盖：

- bot 私聊收到的 Alpha / 池子 / 投研 / 预测市场消息。
- bot 可见的群消息。
- bot 作为管理员可见的频道消息。

输出：

```text
input/signals/telegram/
output/telegram_signals/
```

自动判断会推送到 `SIGNAL_ANALYSIS_CHAT_ID`，未设置时使用 `TELEGRAM_CHAT_ID`。

环境开关：

```bash
export SIGNAL_AUTO_APPLY=0
export SIGNAL_AUTO_PUSH_PRIORITIES="P0_DEEP_REVIEW,P1_MONITOR"
```

`SIGNAL_AUTO_APPLY=1` 时，P0/P1 且有合约、tx 或预测市场链接的线索会自动合并到 watchlist / prediction config。

`SIGNAL_AUTO_PUSH_PRIORITIES` 控制自动频道推送范围。默认空值表示全部分级都推送；服务器建议设置成 `P0_DEEP_REVIEW,P1_MONITOR`。私聊直接发给 bot 的线索会返回分析。

```bash
export SIGNAL_CHAIN_ENRICH=1
```

`SIGNAL_CHAIN_ENRICH=1` 时，消息里同时出现 Pancake pool 链接和 BscScan tx 后，会尝试用链上 receipt 还原 PoolId、token0/token1、block、txIndex 和初始价格。

项目级档案：

```text
output/project_registry/project_registry.json
output/project_registry/project_registry.md
```

Telegram bot、Telegram 用户 API 频道采集、手动文本解析都可以写入同一个档案。合并顺序是项目合约、PoolId、tx、symbol。报价币地址不会作为项目主键。自动频道推送会跳过 `duplicate_signal`，只保留来源记录。

手动文本写入项目档案：

```bash
python3 scripts/ingest_alpha_signal.py --registry input/signals/example.txt
```

电脑关机后，服务器上的 cron、链上监控、Telegram 自动收件、规则化中文判断会继续运行。Codex 对话里的临场推理需要打开 Codex 线程后继续。

## Telegram 用户 API 频道采集

用途：

- 读取采集小号已加入的频道。
- 覆盖 bot 看不到的 Telegram 频道。
- 把频道消息解析成 Alpha 线索，再用 bot 发回中文判断。

推送规则：

- 每 5 分钟轮询一次配置频道。
- 没有新消息时只更新状态文件。
- 新消息命中 Alpha/池子/合约/预测市场关键词后进入解析。
- 服务器建议只推送 P0/P1，低优先级线索保存在本地输出目录。
- 同项目重复消息会写入项目档案来源列表，自动推送会跳过；同项目新增字段会推送本次新增内容。
- `https://t.me/+...` 私密邀请链接不能走公开网页采集；bot 也不能自己通过邀请链接加入，需要管理员拉 bot、用户转发消息，或完成 Telegram 用户 API 登录。

配置来源：

```text
config/telegram_user_sources.json
```

脚本：

```bash
python3 scripts/telegram_user_signal_collector.py
```

初始化频道 offset，跳过历史消息：

```bash
python3 scripts/telegram_user_signal_collector.py --bootstrap
```

需要环境变量：

```bash
export TELEGRAM_API_ID="..."
export TELEGRAM_API_HASH="..."
export TELEGRAM_USER_SESSION="/home/ubuntu/sniper/.secrets/telegram_user.session"
```

用户操作：

1. 打开 `https://my.telegram.org`。
2. 用采集小号手机号登录。
3. 进入 `API development tools`。
4. 创建一个 app，类型随便选，名称可以填 `sniper-monitor`。
5. 复制 `api_id` 和 `api_hash`。
6. 把 `api_id` 和 `api_hash` 发给 Codex 或自己填到服务器 `.env.local`。
7. 第一次运行登录命令时，Telegram 会给采集小号发验证码。

登录命令：

```bash
cd /home/ubuntu/sniper
set -a
. ./.env.local
set +a
python3 scripts/telegram_user_login.py --qr
```

检查登录状态：

```bash
cd /home/ubuntu/sniper
set -a
. ./.env.local
set +a
python3 scripts/telegram_user_login.py --check
```

备用交互登录：

```bash
cd /home/ubuntu/sniper
set -a
. ./.env.local
set +a
python3 scripts/telegram_user_login.py
```

验证码和 2FA 密码只在服务器终端输入，不进聊天。

底层登录片段：

```bash
cd /home/ubuntu/sniper
set -a
. ./.env.local
set +a
python3 - <<'PY'
import asyncio
import os
from pathlib import Path
from telethon import TelegramClient

async def main():
    session = Path(os.environ.get("TELEGRAM_USER_SESSION", "/home/ubuntu/sniper/.secrets/telegram_user.session"))
    session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
    await client.start()
    print("authorized", await client.is_user_authorized())
    await client.disconnect()

asyncio.run(main())
PY
```

频道配置示例：

```json
{
  "generated_at": "2026-06-20",
  "sources": [
    {
      "name": "alpha news",
      "entity": "https://t.me/example_channel",
      "enabled": true,
      "limit": 30
    }
  ]
}
```

安全线：

- 用只读采集小号。
- 不用主号。
- 不放资产。
- 不保存私人聊天。
- 采集器只处理配置里的频道。

查看定时任务：

```bash
crontab -l
tail -n 80 /home/ubuntu/sniper/logs/server_run_once.log
```

## 添加 Telegram 监听频道

用户给出频道名和链接后，可以用脚本写入配置：

```bash
cd /home/ubuntu/sniper
python3 scripts/add_telegram_source.py "alpha news" "https://t.me/example_channel"
python3 scripts/telegram_user_signal_collector.py --bootstrap
```

确认配置：

```bash
cat /home/ubuntu/sniper/config/telegram_user_sources.json
```

## Pancake 池子 Tx 分析

入口：

```bash
python3 scripts/analyze_pancake_pool_tx.py 0x27e250eca29e4ebdd2edba461efd16ba933deb062f8b1cc86132ffdad807074f
```

输出：

```text
output/pancake_pool_tx/<tx_prefix>.json
output/pancake_pool_tx/<tx_prefix>.md
```

QAIT 样例已验证：

```text
1 QAIT ≈ 0.002 USDT; 1 USDT ≈ 500 QAIT
```

## SQLite 表设计草案

```text
projects(id, symbol, name, chain, contract, first_seen_at, status)
addresses(id, project_id, chain, address, label, evidence, first_seen_at)
signals(id, project_id, source, category, raw_text, url, seen_at)
pools(id, project_id, chain, dex, pair, lp_id, min_price, max_price, current_price)
blocks(id, chain, block_number, role, raw_json_path)
scores(id, project_id, score, lane, gaps, next_checks, scored_at)
paper_trades(id, project_id, plan_price, invalidation, result, created_at)
```

## 安全线

- 服务器版先跑只读。
- 监控只读阶段只保存地址、余额、转账和告警文件。
- 自动交易代码单独建模块。
- 私钥不放仓库。
- 测试钱包和主资产钱包分开。
- 授权、下单、bundle 提交都需要单独确认。
