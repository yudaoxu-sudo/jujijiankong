# CEX Sweep Manual RPC Review

Date: 2026-07-15

## Result

The four manual candidates in `input/cex_sweep_manual_review_2026-07-08.json` remain `keep_for_manual_review`. Public BSC RPC checks found all `18/18` listed transactions, all receipts succeeded, and all listed direct paths matched the recorded sender and destination. Each reviewed address returned empty runtime code at the latest block.

| Address | Listed paths | RPC result | Decision reason |
| --- | ---: | --- | --- |
| `0x9c94e59f2a6bcb13f48dd0d0483de66aef75e442` | 4 | `4/4` found, successful, direct-match | Mixed CEX inbound and outbound paths do not establish a clean sweep role. |
| `0xad7d539e3a6f491b5ed5602194fd3f98baaf1a14` | 3 | `3/3` found, successful, direct-match | Two Gate-origin native transfers plus router forwarding do not establish a token-deposit role. |
| `0x10a28ad09505030ba67436b4f5fd4e6d400c3aa5` | 6 | `6/6` found, successful, direct-match | Repeated native-BNB transfers to a Bybit hot wallet need a separate native-deposit class or BEP20 sweep evidence. |
| `0x771c0eed71197e898c577191153208e98d392497` | 5 | `5/5` found, successful, direct-match | CEX-origin native funding followed by router use fits gas-source or trading-wallet evidence more closely than a deposit label. |

## Evidence Boundary

- Scope is limited to the transactions explicitly listed in the tracked input; address history is incomplete.
- Successful direct paths prove those transfers occurred. They do not prove entity ownership or a durable wallet role.
- Empty latest-block code supports only `eoa_or_empty_at_latest`; it does not establish historical code state or ownership.
- `auto_promote_allowed=false` remains fixed for every row. The review script returns `needs_manual_review`, and no address-label proposal is generated.
- RPC method names are recorded for reproducibility. Endpoints, credentials, and raw provider errors are excluded.

## Runtime Policy

`scripts/review_cex_sweep_patterns.py` treats `manual_review_only` evidence as a dedicated non-promotable branch. `counterparty` fields in these manually supplied paths cannot expand the automatic BEP20 sweep proposal path. The accepted synthetic BEP20 fixture remains covered separately, preserving the existing promotion rule for independently verified token sweeps.
