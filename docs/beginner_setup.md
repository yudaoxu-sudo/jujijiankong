# Beginner Setup

更新日期：2026-06-19

你不需要手动设置环境变量。

## 第一步：注册 NodeReal / MegaNode

注册链接：

- `https://nodereal.io/`

注册后创建 BNB Chain / BSC Mainnet API key。

## 第二步：保存 key

在终端里运行：

```bash
cd /Users/xuyufan/Documents/狙击手进程
bash scripts/setup_local_env.sh
```

脚本会问你：

```text
Paste NodeReal / MegaNode API key. Press Enter to skip.
```

把 key 粘进去，按回车。

脚本会写入：

```text
/Users/xuyufan/Documents/狙击手进程/.env.local
```

这个文件已经加入 `.gitignore`。

## 第三步：运行验证器

```bash
python3 scripts/o1_block_verifier.py
```

输出：

```text
output/o1_block_verifier/o1_block_report.md
```

## 检查系统

```bash
python3 scripts/verify_sniper_engine.py
```

如果要手动编译检查，用这条：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/sniper_pycache python3 -m py_compile sniper_engine/*.py scripts/o1_block_verifier.py scripts/verify_sniper_engine.py scripts/sniper_score_local.py
```

## 注意

- `.env.local` 不发给别人。
- API key 不粘贴到公开聊天。
- 私钥、助记词、交易所密码不放进任何脚本。
