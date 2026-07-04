# HertzFlow Skill Setup

## Status

- HertzFlow skill is installed at `~/.codex/skills/hertzflow`.
- AskSurf `surf` skill is installed at `~/.codex/skills/surf`.
- Project Python runtime is `.venv/`.
- Surf CLI is installed at `~/.local/bin/surf`.
- Surf API key is loaded from `.env.local` when present.

## Get Surf API Key

1. Open: http://agents.asksurf.ai/?coupon=hertzflow
2. Register or sign in.
3. Go to Dashboard -> API Keys.
4. Copy the key that starts with `sk-`.
5. Run:

```bash
bash scripts/setup_surf_key.sh
```

Then verify:

```bash
bash scripts/hertzflow_preflight.sh
```

Refresh the general Surf data surface:

```bash
surf install
surf sync
surf list-operations
```

Search a ticker:

```bash
bash scripts/search_surf_token.sh VELVET
```

Run a forensic skeleton:

```bash
bash scripts/run_hertzflow_alpha.sh 0xYourContractAddress SYMBOL_chain
```

## Notes

- Store Surf API keys only in `.env.local`.
- `.env.local` is gitignored and must never be committed, copied into reports, or saved in memory.
- Full forensic reports consume Surf credits.
- Use the general `surf` skill as an auxiliary live-data layer for exchange listings/candles/depth/funding, DEX token prices, social posts/mindshare, prediction markets, token holders/transfers, and on-chain SQL.
- Use HertzFlow selectively for confirmed high-priority Binance Alpha CAs; it is a deep forensic workflow, not the default every-message monitor.
- A CA outside HertzFlow's Binance Alpha scope may return `NEVER_ALPHA_OR_GRADUATED` before any paid forensic step.
- If Surf reports `lookup api.asksurf.ai: no such host`, rerun with external network permission; that is a local network/sandbox failure.
- Restart Codex after installing the skill so it appears in the skill list automatically.
