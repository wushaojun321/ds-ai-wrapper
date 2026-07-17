# ds-ai-wrapper

将 [Claude Code](https://claude.ai/code) CLI 桥接到 Discord 的机器人——在 Discord 频道里直接和 Claude 对话，支持按频道映射工作目录和完整的会话管理。

**[English Documentation](README.md)**

---

## 功能特性

- **直接对话** — 在频道发消息即可与 Claude 对话，无需任何前缀
- **按频道映射工作目录** — 每个 Discord 频道自动对应本地一个目录（`BASE_DIR/频道名`），Claude 在对应目录下运行
- **手动绑定目录** — 用 `/workspace bind <路径>` 将频道绑定到任意目录
- **会话管理** — `/new`、`/continue`、`/resume`、`/fork`、`/back`、`/sessions` 全面管理对话历史
- **查看消息历史** — `/messages` 回顾当前会话的最近对话
- **Git 快捷操作** — `/pull` 和 `/push` 在频道工作目录下执行 git 命令
- **清理频道** — `/purge` 批量删除消息
- **自动重启** — `/restart` 触发 `systemctl --user restart discord-bot`
- **一键部署** — `setup.sh` 自动安装用户级 systemd 服务

---

## 环境要求

- Python 3.11+
- 已安装并登录的 [Claude Code CLI](https://claude.ai/code)（`claude` 或 `claude-internal` 需在 PATH 中）
- Discord Bot Token（[在这里创建](https://discord.com/developers/applications)）
- Linux 服务器（使用 `setup.sh` 自动部署需要 systemd；macOS 可手动运行）

---

## 快速开始

```bash
git clone https://github.com/wushaojun321/ds-ai-wrapper.git
cd ds-ai-wrapper

# 安装依赖
pip install -r requirements.txt

# 配置
cp .env.example .env
# 编辑 .env，填入 DISCORD_TOKEN 和 BASE_DIR

# 运行
python bot.py
```

### Linux systemd 自动部署

```bash
./setup.sh

# 服务管理
systemctl --user status discord-bot
systemctl --user restart discord-bot
journalctl --user -u discord-bot -f   # 实时日志
```

---

## 配置说明

| 变量名 | 是否必填 | 说明 |
|--------|---------|------|
| `DISCORD_TOKEN` | ✅ | Discord Bot Token |
| `DISCORD_GUILD_ID` | 可选 | Guild ID，用于加速 Slash 命令同步（推荐填写）|
| `CLAUDE_CMD` | 可选 | Claude CLI 命令名（默认：`claude-internal`）|
| `BASE_DIR` | 可选 | 工作目录自动映射的根目录（默认：`$HOME`）|
| `COMMAND_TIMEOUT` | 可选 | 等待 Claude 响应的最长秒数（默认：`300`）|

---

## 工作目录映射规则

每个 Discord 频道自动对应一个本地目录：

```
频道 #my-project  →  BASE_DIR/my-project/
频道 #notes       →  BASE_DIR/notes/
```

也可以手动绑定到任意路径：

```
/workspace bind /绝对路径/到/项目目录   # 将此频道绑定到指定目录
/workspace status                       # 查看当前映射
/workspace unbind                       # 解除手动绑定，恢复自动映射
/workspace list                         # 查看所有手动绑定
```

---

## Slash 命令一览

### Claude 会话命令

| 命令 | 说明 |
|------|------|
| `/new [问题]` | 新建会话（可附带第一条消息）|
| `/clear [问题]` | 同 `/new` |
| `/continue [问题]` | 继续最近的会话 |
| `/resume <session_id> [问题]` | 通过 ID 恢复指定历史会话 |
| `/fork <问题>` | 将当前会话 Fork 为新分支 |
| `/back [n]` | 在历史会话中后退 n 步（默认 1）|
| `/sessions` | 列出最近会话，下拉菜单切换 |
| `/messages [数量]` | 查看当前会话最近 N 轮对话 |

### 工作目录 & 工具命令

| 命令 | 说明 |
|------|------|
| `/workspace <操作>` | 管理频道与目录的绑定 |
| `/pull` | 在频道工作目录执行 `git pull` |
| `/push` | 在频道工作目录执行 `git push` |
| `/purge [数量]` | 删除频道消息 |
| `/restart` | 通过 systemd 重启 Bot |
| `/help` | 显示所有命令帮助 |

---

## 项目结构

```
.
├── bot.py                  # 入口：Bot 初始化、on_message 处理
├── claude_cli.py           # Claude CLI 子进程的异步封装
├── session_manager.py      # 按频道管理会话栈（new / resume / back / fork）
├── workspace_manager.py    # 频道 → 目录映射，支持手动覆盖
├── views.py                # Discord UI 组件（会话切换下拉菜单）
├── cogs/
│   ├── claude_commands.py  # /new /continue /resume /fork /clear
│   └── custom_commands.py  # /workspace /help /back /sessions /pull /push /purge /restart /messages
├── discord-bot.service     # systemd 服务模板
├── setup.sh                # 一键部署脚本（conda + systemd）
├── .env.example
└── requirements.txt
```

---

## License

MIT
