# jujijiankong

Alpha Sniper Monitor workspace for Binance Alpha / PancakeSwap new-token monitoring.

This repository contains the reproducible parts of the project:

- `scripts/`: monitors, verification tools, collectors, and deployment helpers
- `sniper_engine/`: shared Python modules for labels, RPC, clustering, and scoring
- `config/`: watchlists, labels, aliases, and source configuration without secrets
- `docs/`: setup, operation, data-source, and analysis notes
- `cases/` and `reports/`: case studies and daily review notes
- `input/`: small sample signals and manually supplied evidence

Runtime outputs are intentionally excluded from git:

- `.env.local`
- `.deploy/`
- `output/`
- Python caches and local virtual environments
- Telegram sessions, databases, private keys, and logs

For a new machine, copy `.env.example` to `.env.local`, fill the required keys locally, then follow `docs/server_runbook.md`.
