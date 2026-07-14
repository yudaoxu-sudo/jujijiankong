# Miles082510 Wallet-Cluster Review

Date: 2026-07-13

## Conclusion

The 400-post review adds two durable controls to the sniper strategy:

1. Quantify near-equal CEX fan-out into fresh-wallet candidates with amount dispersion, recipient count, wallet freshness, source-label quality, market-cap share, and next-hop evidence.
2. Evaluate related clusters at operator level. Verified distribution in one sibling cluster blocks follow language from another cluster's accumulation signal.

The reusable evidence is preserved in `input/miles082510_wallet_cluster_review_2026-07-13.json`. Full research artifacts are under `output/miles082510_x_research/`.

## Sample Boundary

- Source: `https://x.com/miles082510`.
- Fetched: `400` posts across `20` cursor pages.
- Deduped: `393`; `7` retweets removed.
- Coverage: `2025-07-30T03:23:40Z` through `2026-07-13T09:53:13Z`.
- Media: `190` media posts and `211` media items; `17` method-bearing images were downloaded and manually reviewed.
- Full OCR of all media was not completed. The post text corpus was processed in full.
- Source confidence: `sampled social`. Local chain and market checks are recorded separately.

## Evidence Separation

- `official`: no official source promoted a live trading action in this review.
- `onchain`: BSC transfer rows, token-contract resolution, and wallet-label results from Surf.
- `market`: DEX-pool-weighted OHLCV; zero-volume future carry-forward bars were excluded.
- `social`: KOL posts, screenshots, cluster-role claims, personal entries, and profit descriptions.
- `inference`: the two durable controls, field proposals, and runtime integration constraints.

## Verified Cases

### PARTI: signal was real, direction failed

Source: `https://x.com/Miles082510/status/2074772990227865911`.

Before the 2026-07-08 08:30 UTC post, the verified OKX hot wallet `0xa042...77da3` sent PARTI to `34` recipients. `24` transfer rows were worth `$20K-$35K`, and total priced outflow was `$609,604.52`. This supports the reported “20+ wallets, about $27K each” pattern at discovery level.

From the first post-signal hourly bar, replay upside reached `+7.24%`, downside reached `-36.50%`, and the latest real close in the selected window was `-33.92%`. The same account later described cluster distribution and stopped participating.

Operating lesson: equal-tranche fan-out raises priority. It does not clear next-hop, operator-phase, capacity, or distribution-conflict gates.

### BLUAI: clean test-then-large-withdrawal case

Source: `https://x.com/Miles082510/status/2067242926292504858`.

The verified Gate hot wallet sent `963.2 BLUAI` to the posted address at 09:06 UTC, then sent `86,815,347.6572 BLUAI` worth `$1,306,515.03` at 13:00 UTC. The public post arrived at 13:48 UTC. Market replay peaked at `+29.88%` and ended at `+13.48%` in the selected window.

Operating lesson: a tiny route test followed by a much larger same-route withdrawal is a strong discovery pattern. Recipient freshness and next hop still decide promotion.

### B2: forward case, interim refresh

Source: `https://x.com/Miles082510/status/2076605860793770334`.

The frozen social post claims about `$1.4M` of B2 withdrawals to `28` addresses during the recent week, including `19` new wallets. A pre-signal Surf warehouse query from July 7 through `2026-07-13T09:53:13Z` independently finds `44` Gate-hot transfer rows into exactly `28` recipients. Pricing covers only `9` rows and `7` recipients for `$232,961.29`; warehouse token amounts have unusable decimal normalization. The pre-signal window total is unknown. The full claimed dollar amount and full-wallet freshness count remain unverified.

As a post-signal follow-up, the July 13 full-day cohort contains `18` recipients with individually priced B2 receipts of at least `$20K`, totaling `$1,279,979.34`. All `18` had no earlier B2 receipt in the queried June 1-July 12 window, which supports only a `new-to-B2` label. No B2 outbound from that cohort appears in the queried daily warehouse through July 14. This is a coverage-window non-observation and does not establish holding, accumulation, or unsold status. The shared Gate-hot first hop verifies only a common source address; common control, entity linkage, operator identity, full wallet freshness, and live next hop remain unresolved.

The first `18` closed, nonzero-volume hourly bars after the post reached `+0.36%`, drew down `-4.70%`, and ended `-2.11%` on `$976,718.51` aggregate volume. This is an under-24-hour interim replay without price confirmation.

Operating lesson: the fan-out count is independently supported while the strategy remains `Observe`. Preserve `forward_case_pending` until the 24-hour replay and later next-hop evidence mature.

## Dashboard Fields Worth Reusing

The screenshot provides a useful evidence layout:

- price chart with time-aligned accumulation, distribution, and anomaly markers;
- event log with role, amount, value, and timestamp;
- role-tagged holder rows with period inflow/outflow;
- cluster inventory, balance delta, and balance sparkline;
- estimated cost basis with a visible methodology/confidence field;
- cluster bubble size, role, inventory, period netflow, and last-active time.

Every cell needs a source pointer and confidence. Visual role names remain `unknown` until address linkage and behavior validate them.

## Runtime Integration

`scripts/alpha_intraday_flow_watch.py` now emits a report-only `cex_withdrawal_cluster` object from the fetched full-window token-transfer logs. The first gate accepts only tracked global `cex_hot_wallet` sources, at least eight unlabeled recipients, a maximum 1,200-block span, recipient-total CV no greater than 0.20, and an estimated 10,000 quote units when context price exists; 100,000 token units is used only when price is unavailable. The object fixes `direction=unknown`, `action=Observe`, leaves freshness, exact elapsed time, log-window completeness, common gas, next hop, redeposit, DEX execution, quote recovery, and operator conflict unresolved, and does not enter the existing trade-signal or Telegram-alert path.

Regression fixtures cover equal-tranche fan-out, ordinary unequal retail withdrawals, known exchange/router internal routing, `cex_deposit` source exclusion, and preservation of an existing bearish CEX-inflow signal when both paths appear. Remaining runtime gaps are persistent role-weighted cluster inventory in `scripts/alpha_holder_concentration_watch.py`, position holding/time-stop derivation, exact block-time enrichment, unknown-contract filtering, and independently verified coverage for additional CEX hot-wallet labels.

## Rejected Shortcuts

- CEX withdrawal count as an entry rule.
- One cluster's accumulation as an operator-wide bullish state.
- Fixed 10-20% take-profit as a global setting.
- Private-chat timing as public leading evidence.
- Screenshot-derived role labels without address-level reconstruction.
- Win-rate estimation from selected public outcomes.
