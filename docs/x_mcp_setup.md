# X MCP Setup

更新日期：2026-06-30

X Developers 在 2026-06-30 发布 hosted X MCP。官方文档给出两个 MCP 入口：

- X API MCP：`https://api.x.com/mcp`
- X Docs MCP：`https://docs.x.com/mcp`

参考：

- X Developers 公告：`https://x.com/xdevelopers/status/2071752389183647758`
- 官方 MCP 文档：`https://docs.x.com/tools/mcp.md`
- 官方 llms 索引：`https://docs.x.com/llms.txt`

## 我们怎么用

X MCP 是外部发现源，不直接产生买卖信号。

它进入系统后的职责：

1. 读取 KOL、项目方、交易所、X Developers 等公开信息。
2. 抽取项目名、ticker、合约、上线时间、Alpha / CEX / Booster / 空投信息。
3. 写入项目档案，和 Telegram、手动消息共用去重逻辑。
4. 触发链上验证、价格动量、开盘块、首批买家和分发钱包监控。

买卖结论仍由链上证据、价格动量、CEX/Alpha venue 分类、首批 cohort 当前持仓、confirmed sell、空投/Booster 日历共同决定。

## 本地 readiness 检查

```bash
python3 scripts/x_mcp_readiness.py
```

输出位置：

```text
output/x_mcp_readiness/latest.json
output/x_mcp_readiness/latest.md
```

离线验收：

```bash
python3 scripts/x_mcp_readiness.py --no-network --skip-xurl
```

这个脚本不会打印密钥。它只检查：

- 官方 X MCP 文档是否可达。
- `node` / `pnpm` / `@xdevplatform/xurl` 是否可用。
- 环境变量里是否存在 X bearer 或 OAuth client 配置。

## 凭证方式

### 方式一：App-only Bearer

适合只读采集。

服务器环境变量任选一个：

```bash
export X_BEARER_TOKEN="..."
```

或：

```bash
export X_API_BEARER_TOKEN="..."
```

### 方式二：OAuth bridge

适合通过官方 `xurl mcp` 桥接。

官方示例使用：

```bash
npx -y @xdevplatform/xurl mcp https://api.x.com/mcp
```

服务器环境变量：

```bash
export CLIENT_ID="..."
export CLIENT_SECRET="..."
```

X Developer app 的 OAuth redirect URI 按官方默认填：

```text
http://localhost:8080/callback
```

## 当前注意

- 本地 `pnpm dlx @xdevplatform/xurl version` 可运行。
- 当前 `@xdevplatform/xurl` 帮助输出里 MCP 子命令表现可能不稳定，所以 readiness 会把它标成 `xurl_installed_mcp_ambiguous`，直到实际凭证和 bridge 跑通。
- X MCP 来源接入前，继续使用 Telegram 用户 API、Telegram bot、手动 X 链接和链上监控作为主线。
- 任何 X 来源线索都必须经过项目去重和链上验证后再进入动作建议。

## 给用户的注册清单

1. 打开 `https://developer.x.com/`。
2. 创建一个只读用途的 X Developer app。
3. 如果走 OAuth bridge，开启 OAuth 2.0，填 redirect URI：`http://localhost:8080/callback`。
4. 如果走 app-only，只拿 bearer token。
5. 把凭证放到服务器 `.env.local`，不要发在聊天里。
6. 运行 `python3 scripts/x_mcp_readiness.py` 看状态。
