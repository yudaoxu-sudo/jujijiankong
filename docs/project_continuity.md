# Project Continuity

This project uses the global `project-continuity` skill to keep Codex task logs bounded and make fresh conversations resume from verified project state.

## Managed State

- Tracked config: `config/project_continuity.json`
- Runtime database: `/Users/xuyufan/Documents/Codex/runtime/project-continuity/sniper-monitor/continuity.sqlite3`
- Latest check: `/Users/xuyufan/Documents/Codex/runtime/project-continuity/sniper-monitor/alerts/latest.*`
- Latest resume packet: `/Users/xuyufan/Documents/Codex/runtime/project-continuity/sniper-monitor/handoff/latest.*`
- Generated Wiki context: `/Users/xuyufan/Documents/Codex/runtime/project-continuity/sniper-monitor/wiki/project-state.md`
- Cross-project registry: `/Users/xuyufan/Documents/Codex/agent/project-continuity-projects.json`

The database stores task metrics, paths, hashes, checkpoints, lineage edges, audits, and notification history. It does not copy raw conversation text.

## Thresholds

| Metric | Warning | Rotate required |
| --- | ---: | ---: |
| Rollout log | 50 MiB | 100 MiB |
| `tokens_used` | 150,000,000 | 300,000,000 |
| Context compactions | 6 | 10 |
| Turns | 120 | 200 |

Warnings create a compact checkpoint and are deduplicated for 12 hours. `rotate_required` means finish the current safe unit, create and audit a checkpoint, then open a completely new Codex conversation.

## Commands

```bash
python3 scripts/project_continuity_local.py init --config config/project_continuity.json
python3 scripts/project_continuity_local.py check --config config/project_continuity.json
python3 scripts/project_continuity_local.py checkpoint --config config/project_continuity.json --reason manual
python3 scripts/project_continuity_local.py resume --config config/project_continuity.json
python3 scripts/project_continuity_local.py audit --config config/project_continuity.json
```

Register this project for scheduled checks:

```bash
python3 scripts/project_continuity_local.py register \
  --config config/project_continuity.json \
  --registry /Users/xuyufan/Documents/Codex/agent/project-continuity-projects.json
```

## Conversation Rotation

1. Complete or safely stop the active command; do not transfer a live shell process.
2. Run `checkpoint` and `audit`.
3. Open a completely new Codex conversation in the same project directory.
4. Ask Codex to run `resume --config config/project_continuity.json`.
5. Verify Git status, current runtime health, project memory, and open items.
6. Continue from the checkpoint without copying the old conversation or replaying completed work.
7. Archive the old conversation after the new conversation verifies the checkpoint hash.

Native Codex handoff must not be used when it would copy a large old rollout into the new conversation.

## Data Deletion

Preview conversation-scoped runtime deletion:

```bash
python3 scripts/project_continuity_local.py purge-plan \
  --config config/project_continuity.json \
  --scope conversation \
  --conversation-id <conversation-id>
```

The plan returns an exact confirmation token. The `purge` command accepts only that token. Project runtime purge disables the registry entry before deleting its managed SQLite, handoff, Wiki, alert, and audit files.

The purge command does not delete this source repository, OpenAI-retained chats, Saved Memory, uploaded files, GitHub, Tencent Cloud, or backups. Those scopes require separate explicit actions.
