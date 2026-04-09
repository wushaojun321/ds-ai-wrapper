#!/usr/bin/env python3
"""Discord Bot that bridges messages to claude-internal CLI.

Entry point: config loading, logging, Cog registration, on_message handler.
Supports per-channel workspace directories via channel name auto-mapping.
"""

import asyncio
import logging
import os
import uuid
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from claude_cli import ClaudeCLI
from session_manager import SessionManager
from workspace_manager import WorkspaceManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).parent
load_dotenv(_BASE_DIR / ".env")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
BASE_DIR = os.getenv("BASE_DIR", str(Path.home()))
MAX_MSG_LEN = 1900  # Discord limit is 2000, leave margin

# ---------------------------------------------------------------------------
# Logging setup — write to log/ with daily rotation
# ---------------------------------------------------------------------------
LOG_DIR = _BASE_DIR / "log"
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
session_manager = SessionManager(_BASE_DIR / "sessions.json")
workspace_manager = WorkspaceManager(BASE_DIR, _BASE_DIR / "workspaces.json")
claude_cli = ClaudeCLI()

# Per-channel locks to prevent concurrent CLI calls
_locks: dict[int, asyncio.Lock] = {}


def get_lock(channel_id: int) -> asyncio.Lock:
    if channel_id not in _locks:
        _locks[channel_id] = asyncio.Lock()
    return _locks[channel_id]


def split_message(text: str) -> list[str]:
    """Split text into chunks that fit within Discord's message limit."""
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, MAX_MSG_LEN)
        if cut == -1 or cut < MAX_MSG_LEN // 2:
            cut = text.rfind(" ", 0, MAX_MSG_LEN)
        if cut == -1 or cut < MAX_MSG_LEN // 2:
            cut = MAX_MSG_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def call_claude_with_tracking(message_text: str, channel: discord.TextChannel) -> str:
    """Call claude CLI via session manager, using per-channel workspace."""
    channel_id = channel.id
    cwd = workspace_manager.get_path(channel_id, channel.name)
    current_sid = session_manager.get_current(channel_id)

    if current_sid:
        logger.info("[ch:%s] Resume session %s (cwd=%s)", channel_id, current_sid, cwd)
        return await claude_cli.resume_session(message_text, current_sid, cwd=cwd)
    else:
        new_id = str(uuid.uuid4())
        logger.info("[ch:%s] New session %s (cwd=%s)", channel_id, new_id, cwd)
        response, sid = await claude_cli.new_session(message_text, new_id, cwd=cwd)
        session_manager.push_new(channel_id, sid, message_text)
        return response


# ---------------------------------------------------------------------------
# Bot setup (commands.Bot includes Client + CommandTree)
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
# Attach services to bot so Cogs can access them
bot.session_manager = session_manager
bot.workspace_manager = workspace_manager
bot.claude_cli = claude_cli
bot.split_message = split_message


@bot.event
async def on_ready():
    logger.info("Bot 已上线: %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Claude CMD : %s", claude_cli.claude_cmd)
    logger.info("BASE_DIR   : %s", BASE_DIR)
    logger.info("Overrides  : %d", len(workspace_manager.all_overrides()))
    logger.info("Timeout    : %ss", claude_cli.timeout)

    # Load cogs
    for cog in ("cogs.claude_commands", "cogs.custom_commands"):
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

    channel = message.channel
    content = message.content.strip()
    if not content:
        return

    logger.info("[ch:%s/%s] %s: %s", channel.id, channel.name, message.author, content[:200])

    # Legacy !new support (backwards compat)
    if content.lower() == "!new":
        session_manager.clear(channel.id)
        logger.info("[ch:%s] Session cleared via !new", channel.id)
        await message.reply("🔄 会话已重置，下条消息将开启新对话。")
        return

    # Regular conversation — route to Claude CLI
    lock = get_lock(channel.id)
    try:
        async with lock:
            async with channel.typing():
                response = await call_claude_with_tracking(content, channel)
    except Exception as e:
        logger.error("[ch:%s] on_message error: %s", channel.id, e, exc_info=True)
        return

    chunks = split_message(response)
    logger.info("[ch:%s] Sending %d chunk(s)", channel.id, len(chunks))
    if chunks:
        await message.reply(chunks[0])
        for chunk in chunks[1:]:
            await channel.send(chunk)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
