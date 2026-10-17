# ds-ai-wrapper

把 [pi](https://pi.dev) coding agent 接到 Discord 的机器人——在手机上直接和你的项目对话。每个频道对应一个工作目录，实时显示 agent 正在做什么。

**[English Documentation](README.md)**

---

## 功能特性

- **直接对话** — 在频道发消息即可，支持附带图片/文件
- **实时进度** — 一条消息实时刷新：正在执行的工具（💻 bash / 📖 read / ✏️ edit…）、思考状态、流式输出
- **⏹ 随时停止** — 进度消息上的按钮或 `/stop`
- **排队** — 频道忙时新消息自动排队（⏳ 表情提示）
- **结果脚注** — 模型 · 耗时 · 工具步数 · 花费 · 上下文大小 · 会话 ID
- **按频道切换模型 / 思考深度** — `/model`、`/thinking`
- **按频道映射工作目录** — `#foo` → `BASE_DIR/foo`（大小写不敏感），或 `/workspace bind`
- **会话管理** — `/new` `/continue` `/resume` `/fork` `/back` `/sessions` `/messages`
- **Docker 部署** — bot + mihomo 代理（仅 Discord / GitHub 走代理，模型 API 直连）

---

## 部署（Docker，推荐）

宿主机目录约定（都可在 `.env` 里改）：

```
<root>/
├── workspaces/
│   ├── ds-ai-wrapper/      # 本仓库（docker-compose.yml + .env）
│   └── <其他项目>/          # 每个项目对应一个 Discord 频道
├── data/                   # 会话、日志、pi 配置（自动创建）
└── mihomo/config.yaml      # Clash/mihomo 配置（需要代理访问 Discord 时）
```

```bash
mkdir -p <root>/workspaces && cd <root>/workspaces
git clone https://github.com/wushaojun321/ds-ai-wrapper.git
git clone <你的其他项目>
cd ds-ai-wrapper
cp .env.example .env   # 填 DISCORD_TOKEN、OPENROUTER_API_KEY 等
docker compose up -d --build
docker compose logs -f bot
```

服务器能直连 Discord 的话，删掉 `docker-compose.yml` 里的 `mihomo` 服务，并且不设置 `DISCORD_PROXY`。

### 本地运行

需要 Python 3.11+、Node 22+、`npm i -g @earendil-works/pi-coding-agent`：

```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

---

## 配置说明

| 变量名 | 说明 |
|--------|------|
| `DISCORD_TOKEN` | ✅ Discord Bot Token |
| `DISCORD_GUILD_ID` | 可选，只响应该服务器，并加速命令同步 |
| `DISCORD_PROXY` | 可选，仅 Discord 连接使用的代理，如 `http://mihomo:7890` |
| `OPENROUTER_API_KEY` | ✅（用 OpenRouter 时）pi 也支持其他 provider 对应的 key |
| `PI_PROVIDER` / `PI_MODEL` | 默认 `openrouter` / `deepseek/deepseek-v4.1-flash` |
| `PI_THINKING` | 可选默认思考深度：`off` `low` `medium` `high` |
| `COMMAND_TIMEOUT` | 单次任务最长秒数（默认 `1800`）|
| `GITHUB_TOKEN` / `GIT_PROXY` / `GIT_USER_NAME` / `GIT_USER_EMAIL` | 可选，容器内 git 的凭据、代理（只对 github.com 生效）和身份 |

---

## Slash 命令一览

| 命令 | 说明 |
|------|------|
| `/new [问题]` `/clear [问题]` | 新建会话 |
| `/continue <问题>` | 继续此目录下最近的会话 |
| `/resume <id> [问题]` | 恢复会话（ID 可只填前几位）|
| `/fork <问题>` | 从当前会话分叉 |
| `/back [n]` `/sessions` | 回退 / 下拉切换会话 |
| `/messages [数量]` | 查看当前会话历史 |
| `/stop` | 停止当前任务 |
| `/model` `/thinking` | 当前频道的模型 / 思考深度 |
| `/workspace <操作>` | 频道 ↔ 目录绑定 |
| `/pull` `/push` | 在工作目录执行 git |
| `/purge [数量]` | 删除频道消息 |
| `/restart` | 重启 bot（容器自动拉起，代码改动生效）|
| `/help` | 帮助 |

---

## 项目结构

```
.
├── bot.py                  # 入口：配置、服务初始化、on_message
├── pi_agent.py             # pi CLI（JSON 事件流）封装 + 会话文件读取
├── runner.py               # 每频道串行执行、实时进度消息、停止按钮
├── session_manager.py      # 每频道会话栈（new / back / switch）
├── workspace_manager.py    # 频道 → 目录映射
├── channel_settings.py     # 每频道模型 / 思考深度
├── views.py                # 会话切换下拉菜单
├── cogs/
│   ├── agent_commands.py   # /new /continue /resume /fork /stop /model /thinking
│   └── custom_commands.py  # /workspace /help /back /sessions /pull /push /purge /restart /messages
├── Dockerfile
├── docker-compose.yml
└── deploy/entrypoint.sh    # 容器启动时配置 git
```

---

## License

MIT
