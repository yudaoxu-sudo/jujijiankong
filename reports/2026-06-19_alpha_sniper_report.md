# Alpha / 新币狙击报告

日期：2026-06-19

资料来源：

- Binance 新币公告页：`https://www.binance.com/en/support/announcement/list/48`
- Binance RE 现货公告：`https://www.binance.com/en/support/announcement/detail/4f90bec2f7984f71aaa9465830b1c6a6`
- Binance Wallet O Alpha 信息：`https://x.com/BinanceWallet/status/2067255736867107234`
- OKX 新币公告页：`https://www.okx.com/help/section/announcements-new-listings`
- OKX Boost NIGHT：`https://www.okx.com/en-us/learn/trade-dex-night-boost`
- 本地推文库：`output/aliideez_x_research/analysis/method_library.md`
- 本地评分器：`output/sniper_engine/signal_scores.md`

## 结论

当前最值得做的不是盲冲新项目，首要任务是把最近几个 Alpha/新币样本拆成链上验证器：

1. `O / o1 exchange`：P0 复盘标杆。已出现项目方自买、同区块贿赂失败、V3 区间、跨链监控等完整要素。
2. `RE / Re`：已从 Alpha/Prime Sale 走到 Binance/OKX 现货，首块窗口已过，适合做“Alpha 到 CEX 承接”的结构复盘。
3. `ARX / Arcium`：本地推文库给出 BSC 跨链和 OKX Boost 线索，适合进入提前监控队列。
4. `GRAM`：OKX 已有现货和 Expiry Perp 公告，适合盯跨所价差和开盘深度。
5. `ESPORTS / VELVET`：Binance Alpha 区域交易赛线索，适合做活动钱包、交易量和 Alpha 钱包监控。
6. `NIGHT`：OKX Boost 奖励池，适合做 Boost 规则和交易激励监控，首块狙击属性弱。

## P0：O / o1 exchange

状态：

- Binance Alpha 已在 2026-06-17 22:00 UTC+8 开启 O 交易和空投。
- 本地评分器已把 O1 复盘推文打到 `P0_DEEP_REVIEW`，分数 `90`。
- 已知链上重点：BSC block `104769548`，failed tx 里有 `368.88 BNB` BlockRazor payment，成功前排附近存在低显性费用。

为什么重要：

- 这是“项目方自买”和“外部狙击手贿赂失败”的核心样本。
- 能训练我们看块内顺序、internal tx、failed bribe、LP mint/swap 绑定。
- 能训练判断：低 gas / 低普通 Txn Fee 排前面时，是否存在项目方 bundle。

必须补的链上检查：

1. 拉取 block `104769548` 全部 tx。
2. 按 `transactionIndex` 排序。
3. 标记 LP mint、approve、swap、failed tx。
4. 拉取 internal tx，定位 `368.88 BNB` BlockRazor payment。
5. 对比成功前排买入 tx 的普通 gas、priority、internal payment。
6. 找 LP position ID，补 min price、max price、current price。
7. 追踪前排买入地址后续是否卖出。
8. 追踪加池地址后续是否撤池、续池、改区间。

操作判断：

- 当前不追首块，首块窗口已结束。
- 现在用它训练自动验证器。
- 若同类新 Alpha 出现，O1 规则直接复用：加池地址、同块 swap、internal tx、failed bribe、项目方地址资金来源。

## P1：RE / Re

状态：

- Binance 官方公告显示 RE 于 2026-06-18 14:00 UTC 开放现货交易。
- Binance 公告页显示 RE 相关 Earn、Buy Crypto、Convert、VIP Loan、Margin、Futures 支持。
- OKX 公告页显示 2026-06-18 有 RE 现货和 RE 预市场永续转标准永续，2026-06-19 有 REUSD Expiry Perps。

为什么重要：

- RE 是 Alpha/Prime Sale 到主流 CEX 的新样本。
- 它适合研究：Alpha 积分门槛、Prime Sale、CEX 现货、永续、交易赛之间的资金承接。
- 首块狙击窗口已过，后续价值在二段、做市和抛压节奏。

必须补的链上检查：

1. 找 RE 官方合约和链。
2. 标记 Prime Sale / Alpha / CEX / MM 相关地址。
3. 查现货开放前是否有大额打币到 Binance/OKX。
4. 查 CEX 开盘后链上是否有回流或做市地址变化。
5. 查空投/Prime Sale 领取地址是否进入交易所。
6. 记录 CEX 开盘价、链上价格、永续价格、资金费率。

操作判断：

- 当作“Alpha 后段承接”样本。
- 重点看谁在 CEX 上市前拿货，谁在上市后卖。
- 若链上价格低于 CEX/永续隐含价格，才有价差研究价值。

## P1：ARX / Arcium

状态：

- 本地 `@aLiiDeez` 推文库在 2026-06-19 记录：ARX 总量 1B，跨链到 BSC，给 OKX Boost 0.3% 筹码，提到 Wormhole API 可对跨链合约。
- 当前公开源还需要二次验证。

为什么重要：

- 这是更接近“提前蹲”的样本。
- 线索包含：跨链到 BSC、OKX Boost、融资信息、CoinList 成本、潜在 TGE。
- 适合做我们未来的监控样板：桥事件先于公告。

必须补的链上检查：

1. 找 ARX 官方合约。
2. 找 Wormhole / bridge 事件。
3. 对 BSC 合约和源链合约。
4. 标记 OKX Boost 相关筹码地址。
5. 查是否有 Alpha 钱包、CEX 钱包、做市地址。
6. 监控是否出现 add liquidity / approve / LP position。
7. 监控 `bridgingEnabled` 或类似跨链开关。

操作判断：

- 当前进入 watchlist。
- 没有确认合约和池子前，只做监控。
- 一旦出现加池 tx，立刻算初始价、区间、可买深度。

## P2：GRAM

状态：

- OKX 新币公告页显示 2026-06-17 有 GRAM 现货和 GRAMUSD Expiry Perps。

为什么重要：

- 适合看 OKX 现货 + 衍生品同步上线的盘口结构。
- 若链上有同名资产或预市场，可能出现价格锚定和跨市场价差。

必须补的链上检查：

1. 确认 GRAM 官方合约和链。
2. 查 OKX 充值地址是否提前收币。
3. 对比链上价格、OKX 现货价格、Expiry Perp 价格。
4. 查大户地址是否在现货开放前转入交易所。

操作判断：

- 没有链上池子证据前，先作为行情结构样本。
- 适合加入 CEX 公告监控器。

## P2：ESPORTS / VELVET

状态：

- Binance Square 公开信息显示 2026-06-19 到 2026-06-25 有 Balkan-exclusive Binance Alpha Trading Competition，涉及 ESPORTS 和 VELVET。

为什么重要：

- 交易赛会带来短期交易量和做市动作。
- 区域限制会影响真实承接规模。
- 适合观察 Alpha 活动如何制造量、点差、波动和短期抛压。

必须补的链上检查：

1. 找 ESPORTS / VELVET 合约。
2. 标记活动奖励钱包。
3. 监控交易量是否由少数地址刷出。
4. 查是否有新增 LP 或做市地址。
5. 查活动结束前后的抛压。

操作判断：

- 交易赛样本，优先级低于 O、RE、ARX。
- 若出现加池、活动钱包大额转账、Alpha 钱包异动，优先级上调。

## P3：NIGHT

状态：

- OKX Boost 公开页面显示 NIGHT 奖励池，页面更新时间到 2026-06-02。

为什么重要：

- Boost 规则会影响刷量行为。
- 奖励池会带来特定交易对和链上的交易量变化。

必须补的链上检查：

1. 看 Boost 规则对应链和交易对。
2. 查 eligible pairs。
3. 查刷量地址和真实成交地址。
4. 记录奖励前后价格变化。

操作判断：

- 更偏活动套利和刷量监控。
- 狙击首块价值低。

## 今日行动清单

1. 写 `O1 block verifier`，自动验证 block `104769548`。
2. 把 `RE` 加入 CEX/Alpha 后段复盘队列。
3. 把 `ARX` 加入提前监控 watchlist。
4. 建 `current_alpha_watchlist.json`，字段包括 token、链、合约、催化、地址、当前缺口。
5. 监控 Binance announcement、Binance Wallet X、OKX listing、OKX Boost、BscScan/BaseScan。
6. 每个新项目出现后，输出固定格式：
   - 项目
   - 催化
   - 合约
   - tokenomics
   - 加池状态
   - 开盘价格区间
   - 前排 tx
   - bribe/bundle
   - 项目方/狙击手/MM 判断
   - 操作评级

