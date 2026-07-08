# Alpha Rotated Address Review

Date: 2026-07-08

## Conclusion

The old system already collected enough Binance Alpha swap samples to cover more than three Alpha tokens. Current config already promotes the two confirmed Alpha infrastructure addresses and keeps the Binance DEX router out of trading cohorts:

- `0x6aba0315493b7e6989041c91181337b662fb1b90`: Binance Alpha 2.0 Router, `exchange_aggregator`.
- `0x73d8bd54f7cf5fab43fe4ef40a62d390644946db`: Binance Alpha 2.0 Proxy/Custody, `exchange_aggregator`.
- `0xb300000b72deaeb607a12d5f54773d1c19c7028d`: Binance DEX Router, `dex_router`.

The source evidence is preserved in `input/alpha_rotated_address_review_2026-07-08.json`.

## Rechecked Old Samples

Current reruns:

- `python3 scripts/review_alpha_swap_samples.py --bundle-dir output/alpha_trace_samples/tx_review/20260629T105929Z/bundles --chain bsc --out-dir output/alpha_trace_samples/rerun_20260708_strong_review`
- `python3 scripts/review_alpha_swap_samples.py --bundle-dir output/alpha_trace_samples/manus_round2_20260629 --chain bsc --out-dir output/alpha_trace_samples/rerun_20260708_manus_round2_review`

Rerun result:

- Strong batch: `6` samples, `5` distinct Alpha token addresses, all receipt-only.
- Manus round 2: `5` samples, `5` distinct Alpha token addresses, all receipt-only.
- Current config now reports `0x6aba...` and `0x73d8...` as `exchange_aggregator`, so they no longer need full trace before promotion.
- Current config reports `0xb300...` as `dex_router`.

## Candidate Pool

The strong rerun also surfaced protocol/router candidates with cross-token transfer reuse:

| Address | Current Class | Transfer Token Count | Hits | Status |
| --- | --- | ---: | ---: | --- |
| `0x1905dbf18c916bf8ec659545de0858d9f20eaeab` | `-` | 4 | 11 | candidate only |
| `0x7977f3e8e063a4ee95b5f396d63485dbdea4515d` | `-` | 3 | 6 | candidate only |
| `0xe2588c219697f520757b82f5b0119d72bddc0e13` | `-` | 3 | 6 | candidate only |
| `0x238a358808379702088667322f80ac48bad5e6c4` | `dex_vault` | 4 | 9 | already configured as vault |

These candidates stay out of config promotion until invocation flow, internal transaction rows, or trace JSON proves the role.

## Operating Rule

Configured Alpha infrastructure is removed from buyer, seller, whale, smart-money, and project/MM cohorts. These labels only clean the evidence; they do not create buy/sell direction. For market action, the system still needs sellability, opening cohort, quote recovery, venue context, OI/funding, and holder flow.
