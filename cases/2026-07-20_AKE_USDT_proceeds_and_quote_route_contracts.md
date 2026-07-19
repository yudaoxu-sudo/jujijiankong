# AKE confirmed sell-out USDT proceeds 与 quote-route 合约角色

- Case ID: `ake_usdt_proceeds_and_quote_route_contracts_2026_07_20`
- Chain: BSC (`chain_id=56`)
- Proceeds address: `0x1929fec1f9553dde93aa9ae57a4e4ac033e75109`
- Anchor: `0x97028e895dcfd4444591ac383d602ec46b4af307309484534efa2a2b58394194:182` at `2026-07-07T13:23:17+00:00`
- Runtime effect: `none`; deployment required: `false`

## 一句话判断

`0x8540…87e5` 的 `654,912.504551452698348149 USDT` sell proceeds 已按 receipt、canonical log、历史余额与 FIFO 做 24h/72h/7d 核验。当前 disposition state 为 `partially_retained_or_mixed`；所有权、共同控制与最终受益人保持 unresolved。

## Anchor 核验

- canonical identity: `56:0x55d398326f99059ff775485246999027b3197955:0x97028e895dcfd4444591ac383d602ec46b4af307309484534efa2a2b58394194:182`
- transaction.from: `0x85401508c777321eed3018390408ad0ab2e087e5`
- transaction.to: `0x55d398326f99059ff775485246999027b3197955`
- selector: `0xa9059cbb`
- receipt success: `true`
- same-receipt Transfer count: `1`
- recipient historical/current code: `empty` / `empty`

## USDT 账本与 FIFO

| Horizon | Inbound USDT | Outbound USDT | Ending balance | Proceeds retention | Reconciles |
| --- | ---: | ---: | ---: | ---: | --- |
| 24h | 654912.505798777703809349 | 654912.504551 | 0.001247777703809349 | 6.91234851988437032008008525381810356784153014925310270714509513677175868208904580295678765E-13 | PASS |
| 72h | 654912.505798777703809349 | 654912.504551 | 0.001247777703809349 | 6.91234851988437032008008525381810356784153014925310270714509513677175868208904580295678765E-13 | PASS |
| 7d | 654912.505798777703809349 | 654912.504551 | 0.001247777703809349 | 6.91234851988437032008008525381810356784153014925310270714509513677175868208904580295678765E-13 | PASS |

Opening inventory=`0 USDT`，已由 anchor 前一块历史 `balanceOf` 固定，并与 proceeds lot、后到资金分账。proceeds lot 在三个 horizon 均剩余 `0.000000452698348149 USDT`；后到资金没有倒灌 proceeds FIFO。

## 最早下一跳

`654912.504551 USDT` → `0xb8210c25df20921538ea35729badc3e0a63520f1`，tx/log=`0xabcd5cc05c21a088e92d74b5a5bdafa25756b2206bf502472a325e8e2b7471f3:266`，time=`2026-07-07T17:14:29+00:00`，距 anchor `13872` 秒，receipt_success=`true`，分类 `outbound_unlabeled_eoa`

余额下降本身不升级为兑现。只有 same-receipt quote recovery 或经过核验的场所路径才能扩展经济含义。
`proceeds_disposition_known=false`：本单元确认了直接 EOA 下一跳，尚未确认 CEX、DEX、bridge、custody 或最终受益人。

## 三个 quote-route 合约

- `0x0b5f474ad0e3f7ef629bd10dbf9e4a8fd60d9a48`: `wrapped_native_relayer_unwrap_helper`，confidence=`high_onchain_inference`；BscScan source snapshot name=`None`，verification=`None`，evidence_head=`110942157`，proxy_detected=`False`。
- `0x33d285926c0d6b35bdf61d04cc77de60ce0bd5db`: `pmm_dex_adapter`，confidence=`high_verified_source_and_onchain`；BscScan source snapshot name=`PMMAdapter`，verification=`verified_source_page`，evidence_head=`110942157`，proxy_detected=`False`。
- `0xaa86268030aae432ac471f220080ba3e46b52b43`: `pancakeswap_infinity_hook_adapter`，confidence=`high_verified_source_and_onchain`；BscScan source snapshot name=`PancakeSwapInfinityHookAdapter`，verification=`exact_match`，evidence_head=`110942157`，proxy_detected=`False`。

这三个地址分别承担 wrapped-native relay 或 DEX adapter 角色。当前证据不支持把它们归为 CEX、custody 或最终受益人；adapter 也未被提升为 pool。

## Coverage

- Builder SHA-256: `98b51f18f93c988f398a46dd86e2510814bbc8dcb5dd87ae46632b4b7a94e66a`；tracked labels SHA-256: `ab3d1250052ba9306e48cf0bfdf583814ced28f232868451a5bbcbe145ef9c55`。
- USDT coverage: blocks `108603203`–`109946810`；BscScan 完整地址 token 分页 `2` 页，terminal empty page=`2`，exact USDT rows=`24`，随后逐 receipt 重建 canonical log。
- 8,000-block 与后续 4,999-block shard 均在各自三家 provider 尝试后停止；最终改用 BscScan 完整公开分页并逐 receipt 重建，所有失败尝试保留于结构化 coverage。
- Canonical USDT events: `24`；unique receipts: `24`；receipt mismatch: `0`。
- Historical balance anchors: 24h/72h/7d 全部 reconciliation PASS。
- Contract activity: 计划窗口 blocks `108591799`–`108607757`；首个 50-block shard 三次失败后停止。六个 anchor receipt 内涉及三合约的 canonical Transfer、token metadata/code 与对手方已完整核验；窗口内其他 activity 保留 coverage gap。
- 每个未缓存 RPC 或公开页面最多三次总尝试；缺口与 provider/retry 记录在结构化 artifact。

## Runtime gap 影响

本单元增加了 proceeds-lot 持久追踪正例，并提供 native relay、PMM adapter、Infinity hook adapter 三种角色样本。反向与 partial-coverage fixture 仍不足，因此不修改 runtime、verifier 或 celue 规则，也不部署。

## 未解决项

- proceeds destination 的所有权、共同控制与最终受益人。
- 公共 debug trace 不可用时的内部 selector/完整 internal-native 调用树。
- future production rule 所需普通 pooling、custody/internal routing、no-quote 与 partial-coverage 反 fixture。

## Evidence artifacts

- `input/ake_usdt_proceeds_next_hop_2026-07-20.json`
- `input/ake_usdt_proceeds_events_2026-07-20.csv`
- `input/ake_quote_route_contract_roles_2026-07-20.json`
- `input/ake_proceeds_runtime_gap_analysis_2026-07-20.json`
- `input/ake_usdt_proceeds_verification_2026-07-20.json`
