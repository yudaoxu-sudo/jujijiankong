# DAPPOS / DOS Binance Alpha 盘前研究

As of: 2026-08-10 00:13 UTC+8

## 一句话判断

`Observe`。Binance Wallet 已官方确认 DAPPOS (DOS) 将于 8 月 10 日由 Binance Alpha 首发，并在开盘后开放 Alpha Points 空投；Pancake Infinity canonical PoolKey 已把候选 BSC token、USDT、hook 与 poolId 绑定，初始化回执和首个 position 可复现。当前活动流动性为 0，官方 catalog 合约映射、源码控制项与可卖性尚未闭合，不允许 `Small test` 或自动交易。

## 证据分层

| 类型 | 已验证 | 缺口 |
| --- | --- | --- |
| official | Binance Wallet 官方帖确认 Alpha 首发日期和开盘后 Alpha Points 空投；DAPPOS 官方账号转发；官方 airdrop portal 已开 | 合约、精确时间、交易对、充值/领取细则 |
| onchain | BSC 候选 token 返回 `DAPPOS / DOS / 18 decimals / 45,000,000 supply`；`paused=false`；canonical CLPoolManager 将 poolId 精确映射为 `USDT / DOS / hook`；初始化回执、初始价、position 与 350,000 USDT 单边入池可复现 | 官方 catalog 合约映射、source/proxy、mint/blacklist、开盘时活动深度与可卖性 |
| market | 开盘尚未发生 | 价格、深度、OI、funding、CEX 状态 |
| social | 原帖、回复及时间戳可复现 | 只作发现；Upbit follow 仍为 rumor/unverified |
| inference | 候选 token 与官方项目名称、开盘日期一致 | Binance catalog 尚未发布 DOS 合约，不能把 canonical DEX 绑定升级为官方 venue 合约声明 |

## 链上锨点

- Candidate token: `0xb0f09ea9ae0515c3551080d4a745c8115aa30e37` on BSC.
- Pool manager: `0xb0baa371b899950b4ef6a27c21baf5ef7c434d0f`.
- Setter transaction: `0xa02d27fee945c0263ae1771447635480d8186a0b67289bee11f881f369c29c03`, success, `transactionIndex=38`.
- Calldata selector: `0x70e2af29`; candidate decode `setPoolStartedTimestamp(bytes32,uint256)`.
- PoolId: `0x2e9c6c234e0a93c85979ae939561543186fa6341cb52b00323eb99cfc8d98ac8`.
- Timestamp: `1786352400` = `2026-08-10T09:00:00Z` = `2026-08-10 17:00 UTC+8`.
- Canonical PoolKey: Pancake Infinity CLPoolManager 返回 `USDT / DOS / hook / fee=67 / parameters=0x...0a0045`。
- Initialize: tx `0xece2c54ca2f6d05c6d05b08c78e0793d13bdf19d26b4ef0d7c0654febc887fa4`, block `114894536`, `2026-08-09T08:10:50Z`, initial tick `23027`, initial price `0.1 USDT/DOS`。
- Position `1001030`: ticks `23120..29950`, liquidity `3843813906800987272747984`, receipt 中转入 `350,000 USDT`；在 block `114958833` 当前 tick 仍为 `23027`，active liquidity 严格为 `0`。

## 盘前容量

`100k / 200k / 400k / 1m USD` 四档模拟已列入机器合同，当前结果留空并标记 `blocked_missing_actual_liquidity`。canonical pool、sqrtPrice、tick 与首个 position 已知；该 position 当前在活动区间外，active liquidity 为 0，买深和可卖性仍无法复现。

## 动作与失效条件

- 现货：`Observe`；官方 catalog 合约精确匹配、活动流动性与可卖性成立、四档容量可复现后才重新判断。
- 合约：开盘前无 OI/funding 证据，不做方向推断。
- 仓位：自动交易和签名禁用。
- 失效：官方合约或时间冲突、poolId 不属于 DOS 交易对、不可卖、活动区间被小额买压耗尽、项目/MM 单边卖池、空投/桥接余量压过深度。

## 开盘监控合同

DOS 作为新 active target 加入，GRVT 保留 active，其余历史项目继续 inactive。复用现有 prelaunch/opening/holder/liquidity/intraday/price/perp/position/daily/runtime-health 流程。开盘后核 `transactionIndex`、internal/bribe、failed attempts、bundle/LP-swap coupling、首批买家、sniper 成本与卖出完成、项目/MM 承接或派发、撤池/改区间/单边卖池、CEX 路径、桥接余量、价格/OI/funding。归属证据不足时只记 `address_activity / unknown`。
