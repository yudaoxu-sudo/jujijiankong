# LAB Native CEX-To-Aster Route Case

日期：2026-07-07

## 来源

- X: `https://x.com/ElonKely_/status/2069776065376264525`
- BscScan 展开链接：`https://bscscan.com/token/0x7ec43cf65f1663f820427c62a5780b8f2e25593a?a=0xec01c918e2f700f47332ddc2d216ae9e747bd1a5#transactions`
- LAB BSC token: `0x7ec43cf65f1663f820427c62a5780b8f2e25593a`
- 重点中转地址：`0xec01c918e2f700f47332ddc2d216ae9e747bd1a5`

## 证据分层

| 类型 | 证据 | 可信度 | 还缺什么 |
| --- | --- | --- | --- |
| social | ElonKely LAB 跟进帖和截图，声称 Gate -> d1a5/cb65 -> ASTER 分批卖出 | sampled | cb65 路径和完整上游归因 |
| onchain | 本地 BSC RPC 在区块 `106102800` 到 `106105200` 复核到 `d1a5` 地址 17 条 LAB Transfer | verified | Aster Treasury 标签本地化 |
| market | 原帖给出 FDV `1.7B`、MC `530M`、OI `70M`、funding 约 `-1` | social | 当前可复核 OI/MC、OI/FDV、funding 数据源 |
| official | t.co 展开到 BscScan token holder transaction page | verified link | Bitget deposit reopen 官方公告原文 |
| inference | 这是 `cex_to_perp_venue_sell_route` 加 `derivatives-led high-control token` 案例 | inference | 后续价格、OI 和清算数据 |

## 本地 RPC 复核

- Token metadata: `LAB`, decimals `18`.
- `0xec01c918e2f700f47332ddc2d216ae9e747bd1a5` 在短窗口内多次接收 LAB，又多次向 `0x128463a60784c4d3f46c23af3f65ed859ba87974` 转出。
- 本地标签确认：
  - `0x0d0707963952f2fba59dd06f2b425ace40b492fe`: Gate 1 Hot Wallet.
  - `0x53f78a071d04224b8e254e243fffc6d9f2f3fa23`: KuCoin Hot Wallet 2.
- 截图标签显示：
  - `0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23`: Bitget 6.
  - `0x4982085c9e2f89f2ecb8131eca71afad896e89cb`: MEXC 13.
  - `0x128463a60784c4d3f46c23af3f65ed859ba87974`: Aster Treasury.

## 可复用规则

- CEX -> 中转钱包 -> perp venue treasury 是单独的卖出路径类型，优先级高于普通 CEX outflow。
- 同一个中转地址短时间内接收多个 CEX 来源并近乎同步转出时，先按 operator route 总结，再判断方向。
- 截图标签不能直接写入全局标签库；必须经过 explorer 或本地 label review。
- 负 funding 加主动卖出路径，现货动作偏 `Reduce` 或 `Avoid`；合约空单仍需单独检查清算压力和 funding 成本。
- deposit-port reopen、指数篮子变化、Aster/小所支持变化都要进入 event window。

## 后续系统化

- 给盘中流脚本增加可选 review mode：输入 token、suspect wallet、block range，输出 path_stage、cluster_evidence、label_quality。
- 日报增加 `index_or_deposit_policy_event` 字段，记录充值端口、指数篮子、场所支持变化。
- LAB 这类高控盘妖币进入 dormant monitor；CEX routing、Aster deposit、OI/funding、deposit status 变化时恢复关注。
