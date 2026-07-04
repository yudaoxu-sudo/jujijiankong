# Pancake v4 / Infinity Roundtrip Simulation Implementation Prompt

用途：让外部 agent 帮忙审查或扩展 PancakeSwap v4 / Infinity Universal Router `buy->sell` 同一笔 `eth_call` 往返模拟。当前本地系统已经实现 stateOverride、读回校验、同笔往返执行和 `TAKE_ALL amountMinimum` 二分回收率估算；这个提示词用于新 route 变体、边界案例或安全复核。

把下面整段复制给外部 agent：

```text
请作为 BNB Chain / PancakeSwap v4 / Universal Router 工程审查员，给出一个可落地的 Python 实现方案，用来在 eth_call 里模拟 Pancake v4/Infinity 新币的 buy->sell 往返。

背景：
我们已有监控系统，但 v4/Infinity 的“跟随试探”信号必须等可售性 gate 通过才能开放。当前系统已有真实样本和 calldata 解码器，但还缺安全的同笔往返模拟。

已知链和合约：
- Chain: BNB Chain
- Pancake Infinity Universal Router: 0xd9C500DfF816a1Da21A48A732d3498Bf09dc9AEB
- Pancake Infinity Vault: 0x238a358808379702088667322f80ac48bad5e6c4
- Pancake Infinity CLPoolManager: 0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b
- Permit2 常见地址如需使用请自行验证

已验证真实 ARX v4 样本：
1. ARX buy:
   tx 0x046673c3b5217b271da8b2be94d892537f9b120865be9bedb49db9959bd582db
   router 0xd9c500dff816a1da21a48a732d3498bf09dc9aeb
   selector 0x3593564c
   commands: 0x10
   actions: 0x06 SWAP_EXACT_IN_SINGLE, 0x0b SETTLE, 0x0e TAKE_ALL
   pool key:
   currency0 USDT 0x55d398326f99059ff775485246999027b3197955
   currency1 ARX  0xd5f6ef5deabe61e6d5cdb49bfb6f156f2c1ca715
   hook 0xb0bb171d333569cfd28a37f5c5dddaaa90ad46af
   pool_manager 0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b
   fee 67
   parameters 0x0000000000000000000000000000000000000000000000000000000000020045
   zero_for_one True
   amount_in 51000000000000000000
   amount_out_minimum 186106672853510527767

2. ARX sell:
   tx 0xdbcf8b8d95418c0d08b16fde926abaa9d2355e340e5d6d1d503a75430848e4e7
   router 0xd9c500dff816a1da21a48a732d3498bf09dc9aeb
   selector 0x3593564c
   commands: 0x10
   actions: 0x06 SWAP_EXACT_IN_SINGLE, 0x0b SETTLE, 0x0e TAKE_ALL
   same pool key as buy
   zero_for_one False
   amount_in 102304216770951440208
   amount_out_minimum 27986423584515330048

当前本地工具：
- `scripts/decode_pancake_v4_execute.py` 已能解出 commands/actions/pool key/amounts。
- BSC RPC 支持 eth_call state override。Pancake V3 已有 router sell simulation，但 v4 still open。

请输出：

第一部分：实现设计
- 如何构造同一笔 Universal Router execute，完成 buy quote token -> token，然后 sell token -> quote token。
- 是否需要 commands 合并成两个 V4_SWAP，还是一个 V4_SWAP 内多个 actions。
- recipient / payer / ADDRESS_THIS / MSG_SENDER / TAKE_ALL 应该如何设置，避免需要提前知道 token 输出量。
- Permit2、allowance、Vault settlement 在模拟里如何处理。
- stateOverride 最小需要 override 哪些余额/allowance/code/storage。

第二部分：Python 最小骨架
- 使用 `requests` 调 RPC，不依赖私钥，不签名，只做 eth_call。
- 输入：chain RPC URL、quote token、target token、pool key、buy amount、block tag。
- 输出：
  - simulation_status: ok / revert / unknown
  - buy_amount_in
  - token_received_estimated 或 decoded
  - quote_recovered
  - recovery_rate
  - estimated_tax_or_loss
  - revert_class: pool_key_error / slippage / transfer_revert / allowance_error / state_override_unsupported / unknown
- 必须把 quote-only 和 real execute 区分开；quote-only 不能产生 can_sell=True。

第三部分：安全审查
- 哪些情况会让模拟假阳性：白名单、延迟开杀、持仓时间限制、按地址限制、maxTx。
- 哪些情况会让模拟假阴性：Permit2/allowance 构造错、recipient 设置错、state override 没读回、PoolKey 参数错。
- 如何做读回校验：override 后先 eth_call `balanceOf` / `allowance`，读回不一致时输出 unknown。

第四部分：回归用例
- 用上面 ARX buy/sell 两笔样本说明如何从真实 calldata 反推出 PoolKey。
- 给出至少 3 个单元测试/干跑测试：
  1. ARX PoolKey 编解码正确；
  2. 构造出的 buy->sell calldata 能被本地 decoder 解出两段方向相反的 swap；
  3. RPC 不支持/参数错时返回 unknown，不返回 can_sell=False。

约束：
- 不要给真实交易发送代码，不要要求私钥。
- 不要把 Quoter 返回当作可售性证明。
- 不要只解释概念，要给可以粘到 Python 文件里改造的代码骨架。
- 如果 Pancake v4 Universal Router ABI/action 编码有不确定项，请标出需要用哪一笔真实 tx 的 calldata 对照验证。
```

本地接收后的处理原则：

- 只接受能解释 ARX 两笔真实 calldata 的实现建议。
- `quote_recovered / buy_amount_in` 必须作为数值输出，不能只输出布尔 can-sell。
- 任何 `unknown` 都会把“跟随试探”降级为观察。
