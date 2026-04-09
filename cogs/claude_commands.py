"""Slash commands for Claude CLI operations: /new /continue /resume /fork /clear."""

import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("discord_bot")


class ClaudeCommands(commands.Cog):
    """Claude CLI slash commands."""

    def __init__(self, bot):
        self.bot = bot

    def _cwd(self, interaction: discord.Interaction) -> str:
        """Resolve workspace directory for this channel."""
        return self.bot.workspace_manager.get_path(
            interaction.channel_id, interaction.channel.name
        )

    @app_commands.command(name="new", description="新建会话（可直接附带问题）")
    @app_commands.describe(question="要发送的问题（可选）")
    async def new_session(self, interaction: discord.Interaction, question: str | None = None):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager
        cli = self.bot.claude_cli
        cwd = self._cwd(interaction)

        if question:
            await interaction.response.defer()
            new_id = str(uuid.uuid4())
            response, sid = await cli.new_session(question, new_id, cwd=cwd)
            sm.push_new(channel_id, sid, question)
            chunks = self.bot.split_message(response)
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.channel.send(chunk)
        else:
            sm.clear(channel_id)
            await interaction.response.send_message("🔄 会话已重置，下条消息将开启新对话。")
            logger.info("[ch:%s] Session cleared via /new", channel_id)

    @app_commands.command(name="continue", description="继续最近的会话")
    @app_commands.describe(question="要发送的问题（可选）")
    async def continue_session(self, interaction: discord.Interaction, question: str | None = None):
        await interaction.response.defer()
        cli = self.bot.claude_cli
        cwd = self._cwd(interaction)
        response = await cli.continue_latest(question, cwd=cwd)
        chunks = self.bot.split_message(response)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.channel.send(chunk)

    @app_commands.command(name="resume", description="恢复指定会话")
    @app_commands.describe(
        session_id="会话 ID（完整 UUID）",
        question="要发送的问题（可选）",
    )
    async def resume_session(
        self,
        interaction: discord.Interaction,
        session_id: str,
        question: str | None = None,
    ):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager
        cli = self.bot.claude_cli
        cwd = self._cwd(interaction)

        if not question:
            sm.push_new(channel_id, session_id, "(resumed)")
            await interaction.response.send_message(
                f"✅ 已恢复会话 `{session_id[:8]}…`，发送消息即可继续对话。"
            )
            return

        await interaction.response.defer()
        response = await cli.resume_session(question, session_id, cwd=cwd)
        sm.push_new(channel_id, session_id, question)
        chunks = self.bot.split_message(response)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.channel.send(chunk)

    @app_commands.command(name="fork", description="Fork 当前会话为新分支")
    @app_commands.describe(question="要发送的问题")
    async def fork_session(self, interaction: discord.Interaction, question: str):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager
        cli = self.bot.claude_cli
        cwd = self._cwd(interaction)

        current_sid = sm.get_current(channel_id)
        if not current_sid:
            await interaction.response.send_message("❌ 当前频道没有活跃会话，无法 fork。")
            return

        await interaction.response.defer()
        response, new_sid = await cli.fork_session(question, current_sid, cwd=cwd)
        if new_sid:
            sm.push_new(channel_id, new_sid, f"[fork] {question}")
            prefix = f"🔀 已 Fork 新会话 `{new_sid[:8]}…`\n\n"
        else:
            prefix = "🔀 Fork 完成（未能获取新会话 ID）\n\n"

        chunks = self.bot.split_message(prefix + response)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.channel.send(chunk)

    @app_commands.command(name="clear", description="清空当前会话，重新开始（同 /new）")
    @app_commands.describe(question="要发送的问题（可选）")
    async def clear_session(self, interaction: discord.Interaction, question: str | None = None):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager
        cli = self.bot.claude_cli
        cwd = self._cwd(interaction)

        if question:
            await interaction.response.defer()
            new_id = str(uuid.uuid4())
            response, sid = await cli.new_session(question, new_id, cwd=cwd)
            sm.push_new(channel_id, sid, question)
            chunks = self.bot.split_message(response)
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.channel.send(chunk)
        else:
            sm.clear(channel_id)
            await interaction.response.send_message("🔄 会话已重置，下条消息将开启新对话。")
            logger.info("[ch:%s] Session cleared via /clear", channel_id)


async def setup(bot):
    await bot.add_cog(ClaudeCommands(bot))
