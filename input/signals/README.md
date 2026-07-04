# Alpha Signal Inbox

把外部频道、KOL、官方公告、预测市场、池子监控消息保存成 `.txt` 或 `.md` 放在这里。

运行：

```bash
python3 scripts/ingest_alpha_signal.py
```

输出：

```text
output/signals/index.json
output/signals/<file>.json
output/signals/<file>.md
```

需要把提案合并进当前配置时运行：

```bash
python3 scripts/ingest_alpha_signal.py --apply
```

安全边界：

- 只解析公开文本。
- 不保存密钥。
- 不签名。
- 不下单。
- `--apply` 只改 watchlist 和 prediction config。

