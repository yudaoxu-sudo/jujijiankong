# Agent Reach setup

Last verified: 2026-06-30 23:09 CST

## Installed components

- Agent Reach `v1.5.0`
  - CLI wrapper: `/Users/xuyufan/.local/bin/agent-reach`
  - Python venv: `/Users/xuyufan/.local/share/agent-reach/venv`
  - Codex skill: `/Users/xuyufan/.codex/skills/agent-reach`
- `twitter-cli` installed inside the Agent Reach venv.
- `yt-dlp` installed inside the Agent Reach venv.
- `mcporter` and `@jackwener/opencli` installed through the bundled `pnpm` into `/Users/xuyufan/.local/share/pnpm`.
- Exa MCP configured at `/Users/xuyufan/Documents/狙击手进程/config/mcporter.json`.

## Current channel status

Works now:

- Web via Jina Reader.
- Exa semantic search via `mcporter`.
- YouTube metadata/subtitles via `yt-dlp`.
- V2EX public API.
- RSS/Atom feeds.
- Bilibili basic search API.

Installed but needs explicit login state or one manual browser step:

- Twitter/X: `twitter-cli` is installed. It needs explicit `TWITTER_AUTH_TOKEN` and `TWITTER_CT0`, or another approved login-state route.
- OpenCLI-backed channels: Reddit, Facebook, Instagram, XiaoHongShu. OpenCLI is installed, but the Chrome extension must be installed manually:
  `https://chromewebstore.google.com/detail/opencli/ildkmabpimmkaediidaifkhjpohdnifk`
- Xueqiu needs explicit login cookies.

Missing optional channels:

- LinkedIn MCP.
- Xiaoyuzhou transcription dependencies: `ffmpeg` and a transcription provider key.

## Local safety patches

Two local patches were applied inside the venv because the upstream doctor can touch browser state:

- `agent_reach/channels/xueqiu.py`: browser cookie reading is disabled unless `AGENT_REACH_ALLOW_BROWSER_COOKIES=1`.
- `agent_reach/channels/twitter.py`: when explicit Twitter env credentials are absent, doctor reports `twitter-cli` as installed and skips the slow auth probe.

These patches are local to `/Users/xuyufan/.local/share/agent-reach/venv`; reinstalling Agent Reach can overwrite them.

## Verification commands

```bash
/Users/xuyufan/.local/bin/agent-reach doctor --json
mcporter call 'exa.web_search_exa(query: "Binance Alpha CAP", numResults: 1)'
curl -sL 'https://r.jina.ai/http://example.com'
```
