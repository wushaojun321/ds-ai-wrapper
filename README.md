# ds-ai-wrapper

A Discord bot that bridges the [pi](https://pi.dev) coding agent to Discord channels — talk to your projects from your phone. Each channel maps to a working directory, and you see what the agent is doing in real time.

**[中文文档](README.zh.md)**

---

## Features

- **Direct conversation** — just send a message; images and files can be attached
- **Live progress** — one message updates in place: running tools (💻 bash / 📖 read / ✏️ edit…), thinking state, streaming output
- **⏹ Stop anytime** — button on the progress message, or `/stop`
- **Queueing** — messages sent while the channel is busy are queued (⏳ reaction)
- **Result footer** — model · time · tool steps · cost · context size · session ID
- **Per-channel model / thinking level** — `/model`, `/thinking`
- **Per-channel workspace** — `#foo` → `BASE_DIR/foo` (case-insensitive), or `/workspace bind`
- **Session management** — `/new` `/continue` `/resume` `/fork` `/back` `/sessions` `/messages`
- **Docker deployment** — bot + optional mihomo proxy (only Discord / GitHub use the proxy; model APIs go direct)

---

## Deploy (Docker, recommended)

Host layout (all paths configurable in `.env`):

```
<root>/
├── workspaces/
│   ├── ds-ai-wrapper/      # this repo (docker-compose.yml + .env)
│   └── <other projects>/   # one per Discord channel
├── data/                   # sessions, logs, pi config (auto-created)
└── mihomo/config.yaml      # Clash/mihomo config (if Discord needs a proxy)
```

```bash
mkdir -p <root>/workspaces && cd <root>/workspaces
git clone https://github.com/wushaojun321/ds-ai-wrapper.git
git clone <your other projects>
cd ds-ai-wrapper
cp .env.example .env   # fill in DISCORD_TOKEN, OPENROUTER_API_KEY, ...
docker compose up -d --build
docker compose logs -f bot
```

If the host can reach Discord directly, remove the `mihomo` service from `docker-compose.yml` and leave `DISCORD_PROXY` unset.

### Run locally

Requires Python 3.11+, Node 22+, and `npm i -g @earendil-works/pi-coding-agent`:

```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

---

## Configuration

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | ✅ Discord bot token |
| `DISCORD_GUILD_ID` | Optional; respond only in this guild and sync commands faster |
| `DISCORD_PROXY` | Optional proxy for the Discord connection only, e.g. `http://mihomo:7890` |
| `OPENROUTER_API_KEY` | ✅ when using OpenRouter (pi supports other providers' keys too) |
| `PI_PROVIDER` / `PI_MODEL` | Default `openrouter` / `deepseek/deepseek-v4.1-flash` |
| `PI_THINKING` | Optional default thinking level: `off` `low` `medium` `high` |
| `COMMAND_TIMEOUT` | Max seconds per run (default `1800`) |
| `GITHUB_TOKEN` / `GIT_PROXY` / `GIT_USER_NAME` / `GIT_USER_EMAIL` | Optional git credentials, proxy (github.com only) and identity inside the container |

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/new [question]` `/clear [question]` | Start a new session |
| `/continue <question>` | Continue the latest session in this workspace |
| `/resume <id> [question]` | Resume a session (ID prefix is enough) |
| `/fork <question>` | Fork the current session |
| `/back [n]` `/sessions` | Go back / pick a session from a dropdown |
| `/messages [count]` | Show current session history |
| `/stop` | Stop the running task |
| `/model` `/thinking` | Per-channel model / thinking level |
| `/workspace <action>` | Channel ↔ directory binding |
| `/pull` `/push` | Run git in the workspace |
| `/purge [count]` | Delete channel messages |
| `/restart` | Restart the bot (container restarts it; code changes take effect) |
| `/help` | Help |

---

## Project Structure

```
.
├── bot.py                  # entry: config, services, on_message
├── pi_agent.py             # pi CLI (JSON event stream) wrapper + session file reading
├── runner.py               # per-channel serialization, live progress message, stop button
├── session_manager.py      # per-channel session stack (new / back / switch)
├── workspace_manager.py    # channel → directory mapping
├── channel_settings.py     # per-channel model / thinking level
├── views.py                # session switch dropdown
├── cogs/
│   ├── agent_commands.py   # /new /continue /resume /fork /stop /model /thinking
│   └── custom_commands.py  # /workspace /help /back /sessions /pull /push /purge /restart /messages
├── Dockerfile
├── docker-compose.yml
└── deploy/entrypoint.sh    # configures git at container start
```

---

## License

MIT
