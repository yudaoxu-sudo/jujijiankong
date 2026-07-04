# Pancake v4 / Infinity Roundtrip Evidence Prompt

用途：让 Manus 或其他外部 agent 帮忙补齐 PancakeSwap v4 / Infinity 的真实 buy->sell 往返模拟证据，用来审查新路由或边界样本。当前本地系统已经实现 Universal Router 同笔往返 `eth_call` 和回收率二分估算；外部材料只作为补充校验，不直接开放 v4 “跟随试探”。

把下面整段复制给外部 agent：

```text
请帮我收集 BNB Chain 上 PancakeSwap v4 / Infinity Universal Router 的真实 swap 证据，用于实现链上新币可售性模拟。重点不是找普通价格图，而是找到能复现 buy->sell 往返或可售性判断的调用材料。

已知合约：
- Pancake Infinity Universal Router: 0xd9C500DfF816a1Da21A48A732d3498Bf09dc9AEB
- Pancake Infinity Vault: 0x238a358808379702088667322f80ac48bad5e6c4
- Pancake Infinity CLPoolManager: 0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b
- Pancake Infinity BinPoolManager: 0xc697d2898e0d09264376196696c51d7abbbaa4a9

目标：
1. 找 5-10 条 BSC 真实交易，必须直接调用 Universal Router 的 execute(bytes,bytes[]) 或 execute(bytes,bytes[],uint256)。
2. 样本要覆盖成功买入、成功卖出、失败交易。优先同一个 token 同时有买入和卖出样本。
3. 优先 Binance Alpha 上线币或新币；普通老币也可以作为 calldata 解码参考，但要标清楚。
4. 每条样本需要给 raw tx hash、block、tx.to、selector、status、token in/out、PoolId/PoolKey、route path。
5. 如果能打开 Phalcon / Tenderly / BlockSec / BscScan debug trace，请给 Invocation Flow 截图或 raw trace 摘要。
6. 对失败交易，必须说明失败原因是否能确认：滑点、流动性不足、hook/transfer revert、参数错误、未知。

输出格式：

第一部分：raw tx hash 列表，一行一个。

第二部分：Markdown 表格：
- token symbol
- token contract
- tx hash link
- block
- selector
- status
- side: buy / sell / failed_buy / failed_sell / unknown
- amount in / amount out
- pool id / pool key
- evidence level: receipt_only / invocation_flow / raw_trace
- why useful for UniversalRouter roundtrip implementation

第三部分：calldata/trace 重点：
- commands bytes
- inputs 数组个数
- 能否解出 v4 swap action / path / pool key
- 是否用 Permit2
- 是否需要先 buy 后 sell 才能通过 token transfer 限制
- 是否存在 fee-on-transfer / blacklist / max-tx / delayed-sell 迹象

严格排除：
- 只给 Quoter 结果的材料
- 只给价格截图
- approve / transfer / add liquidity / remove liquidity
- tx.to 不是 Universal Router 且无法证明由 Universal Router 触发的交易

目标结论：
请明确哪些样本能作为 “buy->sell 同一 execute 往返模拟” 的实现参考，哪些只能作为 route/status fixture。
```

本地接收后的处理原则：

- route/status fixture 只能进入回归样本，不能打开自动跟随。
- 真正可用的 v4 可售性 gate 需要 `execute` 往返、回收率、revert 分类、读回校验。
- 没有 trace 的失败交易不能直接当貔貅证据。
