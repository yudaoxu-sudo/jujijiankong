# CEX exact-address 标签与 micro-gas priming 校准（2026-07-22）

## 结论

- 真实完整独立正例：`1` 个 root；token=`USDT`，exchange entity=`Bitget`。
- AKE 的三条 proceeds 分支按同一 operator/root 合并；其中 `2` 条提供完整正例观察，`62,835.506013 USDT` 分支只作同 root 的 path-only 对照。
- 真实完整独立负例：`0`；真实 observation-only：`6`。
- 最低门槛未满足：正例 root `1/3`、token `1/2`、独立负例 `0/3`。
- 决策：`calibration_gap_no_runtime_change`。纯证据更新，无部署。

## 样本单位与证据门

独立样本单位固定为 `token + root path/operator + event window + exchange entity`。正例要求 native/token canonical identity、两笔 receipt success、token metadata、完整地址标签绑定、先 gas 后 token ingress、direct-native/token coverage 与余额方程全部通过。`internal-native` 继续单列 gap。

Bitget 6 exact-address：`0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23`；标签置信度=`medium`；historical/current code state 均为 `empty`；页面 SHA=`56a02c3efba2c7afe5e91a1f550e67af5b1693bec0834421ac8166f8865e3f0e`；cache meta SHA=`ad4b905f1a364a8498e50619bcb8faadbe463ab01b3b286d0107a917178c4811`。

## AKE root 内正例观察

| branch | USDT ingress | gas BNB | gas 提前秒数 | token identity | native tx |
|---|---:|---:|---:|---|---|
| `ake_sell_proceeds_506483_usdt_second_hop` | `506483` | `0.000003487413` | 31 | `0xd72e692ffaaff0a06c026eab5a5dd19ec701ab04b1634991c6c9a2d7ebbd2cea:121` | `0x460483c798c269400dada8f9cdfed8552f51af23bca450498598e8ccd371b641` |
| `ake_sell_proceeds_85594_usdt_second_hop` | `85594` | `0.00000300262` | 29 | `0xdbdba0fbdff65075d06e5562e2618b9a0b1134c5a426d43758c72ba59f2c0518:378` | `0xa614d7f68b53f3d27fdcdc4c533c52b7111710aa9fd2e89203f2130e5b471439` |

这两条观察共享 token、operator、事件窗口和 Bitget entity，统计分母为 `1`。两笔 gas 均来自 Bitget 6 exact address，receipt success，金额覆盖随后 token call 的 gas paid；两笔 token ingress receipt success、quote recovery 为空，经济闭合依据为 custody ingress。

## 五档阈值 sweep

| threshold BNB | TP | FN | FP | unknown records | root 内 branch recall |
|---:|---:|---:|---:|---:|---:|
| `0.000001` | 1 | 0 | 0 | 6 | 2/2 |
| `0.000003` | 1 | 0 | 0 | 6 | 2/2 |
| `0.00001` | 0 | 1 | 0 | 6 | 0/2 |
| `0.0001` | 0 | 1 | 0 | 6 | 0/2 |
| `0.001` | 0 | 1 | 0 | 6 | 0/2 |

独立负例分母为 `0`，因此不计算 FPR。正例分母为 `1`，只报告整数 TP/FN；branch recall 仅描述同 root 内部，不增加独立样本数。`0.001 BNB` 会漏掉本 root 的 micro-gas corroboration；若 exact-address token path 已成立，gas 缺失不会抹除该 token path。

## 负例与 observation-only

- `micro-gas 后无 token ingress`：已有 native/CEX 混合路径记录缺金额、时序或完整 history，仍为 observation-only。
- `gas 在 ingress 后`：62,835 分支保存一笔 token outbound 后 `28` 秒才到达的 `0.000000001 BNB`，可作为时序 guard 的完整事实；它与 AKE root 相关，不增加独立负例分母。
- `模糊/失效/歧义 explorer 标签`：未找到完整 tracked fixture。
- `非托管地址`：有 CEX native 入账后路由/交易的 manual observations，history 不完整。
- `CEX internal / Alpha custody`：receipt/token 路径可验证，gas pairing 与 custody purpose 不完整，保持 report-only。
- `普通 transfer、无 quote/venue closure`：AKE 62,835 分支路径完整，因同 root 相关性与 opening inventory 混合，不计独立负例。

现有 verifier 的 `0.002 BNB` configured-CEX synthetic positive 在五档阈值均通过。`0.005 BNB` non-CEX 输入与前一行共享 target，代码先命中 `found_targets`，尚未隔离验证 source-class rejection；它不计 synthetic negative。

## 运行规则影响

运行 gas scan 仍使用 `amount_bnb >= threshold`，默认 `0.001 BNB`。gas 只在显著 CEX token path 后参与措辞、排序与去重，不能单独生成 CEX inflow。当前 gas row 未保存 exact-label provenance，native receipt success 与完整 block coverage也未形成 fail-closed gate。本单元不修改 runtime/verifier，避免用一个相关正例校准全局阈值。

## 验证与来源

Builder SHA-256：`b358a463aee6cb8d17e8991d5fafc7fe7c013415f70bad7c92461606076808b2`。自校验：`PASS`。输入全部为明确 Git tracked evidence；网络请求=`0`，外部重试=`0`。

| tracked source | SHA-256 |
|---|---|
| `input/ake_usdt_506483_branch_2026-07-20.json` | `9b08a2c807142251e2adb7670e1bfcd9e07bb892111c3c704b62479f227dc0bd` |
| `input/ake_usdt_506483_branch_verification_2026-07-20.json` | `f4edd7d5357e5b5ee22ffcc78e99c0a50d62c33d36c046ea44cf13316faa6446` |
| `cases/2026-07-20_AKE_USDT_506483_branch.md` | `3b0d79b83c5925db7bfa301cfa9ee0d0629ae1e40834a7ab4b2a046fde556056` |
| `input/ake_usdt_85594_branch_2026-07-22.json` | `44a6cc48c35bca5d370992f552569c3f02e6a476ba39881d5239a97d8f13d503` |
| `input/ake_usdt_85594_branch_verification_2026-07-22.json` | `c9ff64038779ddc9b63ac89847498b8959975cdd357e5836a87a5902184019ce` |
| `cases/2026-07-22_AKE_USDT_85594_branch.md` | `97ab1eb9690f7bd2c4ae58b6d489f83981477a97506f209ca351baf327474576` |
| `input/ake_usdt_62835_branch_2026-07-22.json` | `fb9abfdfadcc25005c41baa8a103e7c7d81934cea9dfb37f64340acdb25facf9` |
| `input/ake_usdt_62835_branch_verification_2026-07-22.json` | `1f8c7b27ede91ab1fd4db5cc839fa31a73c6413df60694eb8955406fce3b2949` |
| `cases/2026-07-22_AKE_USDT_62835_branch.md` | `b61baf28c622995cc2b20ee55ebad0a9ececb12a625bfc7ae7542ee4b49763c9` |
| `input/cex_sweep_manual_review_2026-07-08.json` | `37e1bc9de1b08b208ff48b2717b1aac722b8d70f46237f651ab22f2414e92742` |
| `input/cex_sweep_paths_2026-07-08.json` | `e41af0cdba785ca278ad7ea1c8fb0b3f7cb40f3f623cc07cb0cdb0ca59b5327c` |
| `input/cex_wallet_labels_2026-07-08.json` | `25c2590be9537648243563900cfb3bf3064d130c37d6cf5ff7553046fc782164` |
| `input/binance_alpha_cex_wallet_aggregation_review_2026-07-17.json` | `2c056ca2f866fc01a6ea661498ed0e4f741e56f6a8a85f86a753992eb31f27c7` |
| `input/configured_cex_window_aggregation_verification_2026-07-18.json` | `785b25921dd8cc8e534f705eda14efba198be6d98091a3aadd1cb11b00c4578d` |
| `input/ake_usdt_second_hop_runtime_gap_2026-07-20.json` | `c94540a04ffe1c66dd73ba6eea439827c1638f7e9f4a2c423493886b794cfd0b` |
| `scripts/alpha_intraday_flow_watch.py` | `6d5f78986b6d03944436c69ef05f30f6e64e7250432db17bac740f6b2bce9fe6` |
| `scripts/verify_sniper_engine.py` | `ddd2861c29f392c63070aa3fddc16ec80c744fc3b8cfae702102525c7d7f9890` |
