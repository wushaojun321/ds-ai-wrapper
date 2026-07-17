# ds-ai-wrapper

A Discord bot that bridges [Claude Code](https://claude.ai/code) CLI to Discord channels — chat with Claude directly in Discord, with per-channel workspace directory mapping and full session management.

**[中文文档](README.zh.md)**

---

## Features

- **Direct conversation** — send any message in a channel and Claude replies, no prefix needed
- **Per-channel workspace** — each Discord channel automatically maps to a local directory (`BASE_DIR/channel-name`); Claude runs in that context
- **Manual workspace binding** — use `/workspace bind <path>` to point a channel at any directory
- **Session management** — `/new`, `/continue`, `/resume`, `/fork`, `/back`, `/sessions` to control conversation history
- **Message history** — `/messages` to review the current session's recent turns
- **Git helpers** — `/pull` and `/push` run git commands in the channel's workspace
- **Channel cleanup** — `/purge` to bulk-delete messages
- **Self-restart** — `/restart` triggers `systemctl --user restart discord-bot`
- **Auto-deploy** — `setup.sh` installs a user-level systemd service with one command

---

## Requirements

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) installed and authenticated (`claude` or `claude-internal` in PATH)
- A Discord bot token ([create one here](https://discord.com/developers/applications))
- Linux server with systemd (for `setup.sh` auto-deploy; manual run works on macOS too)

---

## Quick Start

```bash
git clone https://github.com/wushaojun321/ds-ai-wrapper.git
cd ds-ai-wrapper

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — fill in DISCORD_TOKEN and BASE_DIR

# Run
python bot.py
```

### Auto-deploy with systemd (Linux)

```bash
./setup.sh

# Manage the service
systemctl --user status discord-bot
systemctl --user restart discord-bot
journalctl --user -u discord-bot -f
```

---

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Your Discord bot token |
| `DISCORD_GUILD_ID` | Optional | Guild ID for faster slash command sync (recommended) |
| `CLAUDE_CMD` | Optional | Claude CLI command name (default: `claude-internal`) |
| `BASE_DIR` | Optional | Root directory for workspace auto-mapping (default: `$HOME`) |
| `COMMAND_TIMEOUT` | Optional | Max seconds to wait for Claude response (default: `300`) |

---

## Workspace Mapping

Each Discord channel maps to a working directory automatically:

```
Channel #my-project  →  BASE_DIR/my-project/
Channel #notes       →  BASE_DIR/notes/
```

Override with a slash command:

```
/workspace bind /absolute/path/to/repo   # bind to a specific directory
/workspace status                         # show current mapping
/workspace unbind                         # revert to auto-mapping
/workspace list                           # list all manual bindings
```

---

## Slash Commands

### Claude Sessions

| Command | Description |
|---------|-------------|
| `/new [question]` | Start a new session (optionally with a first message) |
| `/clear [question]` | Alias for `/new` |
| `/continue [question]` | Continue the most recent session |
| `/resume <session_id> [question]` | Resume a specific session by ID |
| `/fork <question>` | Fork the current session into a new branch |
| `/back [n]` | Step back `n` sessions in history (default: 1) |
| `/sessions` | List recent sessions with a dropdown to switch |
| `/messages [count]` | Show the last N turns of the current session |

### Workspace & Utilities

| Command | Description |
|---------|-------------|
| `/workspace <action>` | Manage channel-to-directory bindings |
| `/pull` | Run `git pull` in the channel's workspace |
| `/push` | Run `git push` in the channel's workspace |
| `/purge [count]` | Delete messages in the channel |
| `/restart` | Restart the bot via systemd |
| `/help` | Show all available commands |

---

## Project Structure

```
.
├── bot.py                  # Entry point: bot setup, on_message handler
├── claude_cli.py           # Async wrapper around the Claude CLI subprocess
├── session_manager.py      # Per-channel session stack (new / resume / back / fork)
├── workspace_manager.py    # Channel → directory mapping with manual overrides
├── views.py                # Discord UI components (session select dropdown)
├── cogs/
│   ├── claude_commands.py  # /new /continue /resume /fork /clear
│   └── custom_commands.py  # /workspace /help /back /sessions /pull /push /purge /restart /messages
├── discord-bot.service     # systemd service template
├── setup.sh                # One-command deploy script (conda + systemd)
├── .env.example
└── requirements.txt
```

---

## License

MIT
