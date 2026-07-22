# CEX micro-gas 正例候选缺口审查（2026-07-22）

## 结论

- 新增 verified positive roots=`0`，新增 positive tokens=`0`。
- 当前门槛保持 positive roots `1/3`、positive tokens `1/2`、complete negatives `3/3`。
- 正式公开发现范围固定为 BSC、`ARX/CAP/NES`、`Bitget/Gate/Bybit`、`2026-06-01T00:00:00Z–2026-07-22T00:00:00Z`。
- Bitget 6 的三笔 micro-gas 已通过 canonical transaction、receipt 和 block timestamp 复核，三条分支共享同一个 Bitget 批次，只计一个 blocked candidate root。
- 该 root 缺少后续 token ingress tx/receipt/log/decimals/amount/receiver 与唯一配对，同时共享现有 AKE 样本的 Bitget exchange entity。
- 决策为 `positive_pairing_gap_no_runtime_change`。runtime、通知与部署均无改动。

## tracked 入口与 exact-address 实体

| 类型 | 条目 | 精确值 | 来源 |
|---|---|---|---|
| token | ARX | `0xd5f6ef5deabe61e6d5cdb49bfb6f156f2c1ca715` | `config/current_alpha_watchlist.json` |
| token | CAP | `0x99991c6aabba5a096f24f250b73580f5179b9999` | `config/current_alpha_watchlist.json` |
| token | NES | `0x3131f6b80c26936ab03f7d9d29eb4ddf36ac3fb5` | `config/current_alpha_watchlist.json` |
| CEX | Bitget 6 | `0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23` | tracked public-title binding，confidence=`medium` |
| CEX | Gate 1 | `0x0d0707963952f2fba59dd06f2b425ace40b492fe` | tracked exact-address binding |
| CEX | Bybit: Hot Wallet | `0xf89d7b9c864f589bbf53a82105107622b35eaa40` | tracked exact-address binding |

Bitget 当前 Jina 页面可用。Gate 与 Bybit 页面本轮未形成可用刷新内容，这是标签刷新覆盖缺口。Exa 后端体检为可用，`mcporter` launcher 未在 PATH，Exa 查询未启动。

## blocked candidate root

| gas tx | recipient | BNB | block/time | canonical receipt | 配对状态 |
|---|---|---:|---|---|---|
| `0xbda66c...049ed` | `0xff4c0e...0c346` | `0.000003485826` | `111020436` / `03:38:03Z` | success | blocked：缺 token ingress |
| `0x4bc1f0...75f83` | `0xdc36c1...19165` | `0.000003002375` | `111020504` / `03:38:33Z` | success | blocked：缺 token ingress |
| `0x5db44f...bde08` | `0x96945c...333f7` | `0.000004600025` | `111020504` / `03:38:33Z` | success | blocked：缺 token ingress |

三笔 gas 金额均小于 `0.001 BNB`，from 均为 Bitget 6，receipt status 均为 `1`。后续复核完整覆盖 block `111020436–111020700`，共 `265/265` 个 block，时间为 `03:38:03Z–03:40:01Z`。限定检查三名 recipient 直接调用 ARX/CAP/NES 合约的 ERC-20 `transfer`，且 calldata receiver 为 Bitget 6，匹配数=`0`。

这个短窗口完整性只适用于上述 direct-call predicate。router/internal call、receipt-log-wide token transfer 与更晚历史保持 unresolved。`0` 匹配不表示链上 absence。

## 排除观察与协调偏差

- BLUAI/Gate tracked deferred lead 已恢复两个 canonical block-transaction hash：`0x18d129...72351` 与 `0xc65497...f4156`。两笔均是 Gate 1 直接调用 BLUAI token 合约向 recipient 转出，它们不提供 micro-gas 后 token ingress 进入 Gate 的路径。该条目不进入正式 token 计数。
- MEXC/KuCoin 的 historical `eth_getLogs` 只读尝试因 public RPC `limit exceeded` 未形成可用覆盖。两者按协调偏差排除，不计入正式 exchange 覆盖、零结果或链上 absence。

## 离线 builder 判断

本轮不实现 candidate builder。现有 anchors 已能穷举三笔 gas 分支；当前缺口是 token tx hash、receipt、Transfer log 和唯一配对。离线枚举器无法从现有输入恢复这些链上字段。

micro-gas 继续只作 corroboration，单独 gas 分支不产生 custody、buy、sell、follow、reduce 或其他动作语义。

## 产物

- 机器证据：`input/cex_micro_gas_positive_gap_2026-07-22.json`
- 新增完整正例：`0`
- 新增 canonical micro-gas branches：`3`
- 新增 blocked candidate roots：`1`
- 验证：project verifier `190 PASS / 0 FAIL`，celue audit `101 PASS / 0 FAIL`
