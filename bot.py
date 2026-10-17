#!/usr/bin/env python3
"""Discord Bot that bridges messages to the pi coding agent.

Entry point: config loading, logging, Cog registration, on_message handler.
Supports per-channel workspace directories via channel name auto-mapping.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from channel_settings import ChannelSettings
from pi_agent import PiAgent
from runner import ChannelRunner, split_message
from session_manager import SessionManager
from workspace_manager import WorkspaceManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).parent
load_dotenv(_BASE_DIR / ".env")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_PROXY = os.getenv("DISCORD_PROXY") or None
BASE_DIR = os.getenv("BASE_DIR", str(Path.home()))
DATA_DIR = Path(os.getenv("DATA_DIR", str(_BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging setup — write to log/ with daily rotation
# ---------------------------------------------------------------------------
LOG_DIR = DATA_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.DEBUG)

_formatter = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

_fh = TimedRotatingFileHandler(
    LOG_DIR / "bot.log", when="midnight", backupCount=30, encoding="utf-8"
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_formatter)
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(_formatter)
logger.addHandler(_ch)

# ---------------------------------------------------------------------------
# Core services
# ---------------------------------------------------------------------------
session_manager = SessionManager(DATA_DIR / "sessions.json")
workspace_manager = WorkspaceManager(BASE_DIR, DATA_DIR / "workspaces.json")
channel_settings = ChannelSettings(DATA_DIR / "channel_settings.json")
agent = PiAgent(DATA_DIR / "pi-sessions")
runner = ChannelRunner(agent, session_manager, workspace_manager, channel_settings)

# ---------------------------------------------------------------------------
# Bot setup (commands.Bot includes Client + CommandTree)
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, proxy=DISCORD_PROXY)
# Attach services to bot so Cogs can access them
bot.session_manager = session_manager
bot.workspace_manager = workspace_manager
bot.channel_settings = channel_settings
bot.agent = agent
bot.runner = runner
bot.split_message = split_message


@bot.event
async def on_ready():
    logger.info("Bot 已上线: %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Agent      : %s %s/%s", agent.cmd, agent.provider, agent.default_model)
    logger.info("BASE_DIR   : %s", BASE_DIR)
    logger.info("DATA_DIR   : %s", DATA_DIR)
    logger.info("Overrides  : %d", len(workspace_manager.all_overrides()))
    logger.info("Timeout    : %ss", agent.timeout)

    # Load cogs (on_ready can fire again after a reconnect)
    for cog in ("cogs.agent_commands", "cogs.custom_commands"):
        if cog in bot.extensions:
            continue
        try:
            await bot.load_extension(cog)
            logger.info("Loaded cog: %s", cog)
        except Exception as e:
            logger.error("Failed to load cog %s: %s", cog, e)

    # Sync slash commands to Discord
    try:
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=int(DISCORD_GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %d slash command(s) to guild %s", len(synced), DISCORD_GUILD_ID)
            # Clear stale global commands
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            logger.info("Cleared global commands")
        else:
            synced = await bot.tree.sync()
            logger.info("Synced %d slash command(s) globally", len(synced))
    except Exception as e:
        logger.error("Failed to sync commands: %s", e)


@bot.event
async def on_message(message: discord.Message):
    # Ignore bots
    if message.author.bot:
        return

    # Only respond in the configured guild
    if DISCORD_GUILD_ID and (not message.guild or str(message.guild.id) != DISCORD_GUILD_ID):
        return
    if not message.guild:
        return

    channel = message.channel
    content = message.content.strip()
    if not content and not message.attachments:
        return

    logger.info("[ch:%s/%s] %s: %s", channel.id, channel.name, message.author, content[:200])

    # Legacy !new support (backwards compat)
    if content.lower() == "!new":
        session_manager.clear(channel.id)
        logger.info("[ch:%s] Session cleared via !new", channel.id)
        await message.reply("🔄 会话已重置，下条消息将开启新对话。")
        return

    files = await runner.save_attachments(message)
    await runner.run(
        channel,
        content or "请查看附件。",
        reply_to=message,
        files=files,
    )


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
