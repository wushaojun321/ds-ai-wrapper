"""Slash commands for agent sessions: /new /continue /resume /fork /clear /stop /model /thinking."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("discord_bot")

MODEL_CHOICES = [
    app_commands.Choice(name="DeepSeek V4.1 Flash（默认，快且便宜，能看图）", value="deepseek/deepseek-v4.1-flash"),
    app_commands.Choice(name="DeepSeek V4 Pro（复杂任务）", value="deepseek/deepseek-v4-pro"),
    app_commands.Choice(name="恢复默认", value="default"),
]

THINKING_CHOICES = [
    app_commands.Choice(name=n, value=n) for n in ("off", "low", "medium", "high", "default")
]


class AgentCommands(commands.Cog):
    """Agent session slash commands."""

    def __init__(self, bot):
        self.bot = bot

    async def _start(self, interaction: discord.Interaction, question: str, **kwargs):
        """Acknowledge the interaction, then stream the run as normal channel messages
        (interaction followups expire after 15 minutes, runs can take longer)."""
        await interaction.response.send_message(f"▶️ {question[:1800]}")
        await self.bot.runner.run(interaction.channel, question, **kwargs)

    def _reset(self, interaction: discord.Interaction) -> None:
        self.bot.session_manager.clear(interaction.channel_id)
        logger.info("[ch:%s] Session cleared", interaction.channel_id)

    @app_commands.command(name="new", description="新建会话（可直接附带问题）")
    @app_commands.describe(question="要发送的问题（可选）")
    async def new_session(self, interaction: discord.Interaction, question: str | None = None):
        if question:
            await self._start(interaction, question, mode="new")
        else:
            self._reset(interaction)
            await interaction.response.send_message("🔄 会话已重置，下条消息将开启新对话。")

    @app_commands.command(name="clear", description="清空当前会话，重新开始（同 /new）")
    @app_commands.describe(question="要发送的问题（可选）")
    async def clear_session(self, interaction: discord.Interaction, question: str | None = None):
        await self.new_session.callback(self, interaction, question)

    @app_commands.command(name="continue", description="继续此工作目录下最近的会话")
    @app_commands.describe(question="要发送的问题")
    async def continue_session(self, interaction: discord.Interaction, question: str):
        await self._start(interaction, question, mode="continue")

    @app_commands.command(name="resume", description="恢复指定会话")
    @app_commands.describe(
        session_id="会话 ID（可只填前几位）",
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
        cwd = self.bot.workspace_manager.get_path(channel_id, interaction.channel.name)
        f = self.bot.agent.find_session_file(cwd, session_id)
        if not f:
            await interaction.response.send_message(
                f"❌ 当前工作目录下找不到会话 `{session_id}`，用 /sessions 查看。", ephemeral=True
            )
            return
        full_id = f.stem.split("_", 1)[1]
        if not sm.switch_to(channel_id, full_id):
            sm.push_new(channel_id, full_id, "(resumed)")

        if question:
            await self._start(interaction, question, mode="resume", session_id=full_id)
        else:
            await interaction.response.send_message(
                f"✅ 已恢复会话 `{full_id[:8]}…`，发送消息即可继续对话。"
            )

    @app_commands.command(name="fork", description="Fork 当前会话为新分支")
    @app_commands.describe(question="要发送的问题")
    async def fork_session(self, interaction: discord.Interaction, question: str):
        if not self.bot.session_manager.get_current(interaction.channel_id):
            await interaction.response.send_message("❌ 当前频道没有活跃会话，无法 fork。", ephemeral=True)
            return
        await interaction.response.send_message(f"🔀 Fork: {question[:1800]}")
        await self.bot.runner.run(interaction.channel, question, mode="fork")

    @app_commands.command(name="stop", description="停止当前频道正在运行的任务")
    async def stop_task(self, interaction: discord.Interaction):
        ok = self.bot.agent.stop(interaction.channel_id)
        await interaction.response.send_message("⏹ 已停止" if ok else "没有正在运行的任务", ephemeral=not ok)

    @app_commands.command(name="model", description="切换当前频道使用的模型")
    @app_commands.describe(preset="常用模型", custom="自定义 OpenRouter 模型 ID，如 anthropic/claude-sonnet-4.5")
    @app_commands.choices(preset=MODEL_CHOICES)
    async def model_command(
        self,
        interaction: discord.Interaction,
        preset: app_commands.Choice[str] | None = None,
        custom: str | None = None,
    ):
        cs = self.bot.channel_settings
        value = custom or (preset.value if preset else None)
        if value:
            cs.set(interaction.channel_id, "model", None if value == "default" else value)
        current = cs.get(interaction.channel_id, "model") or f"{self.bot.agent.default_model}（默认）"
        await interaction.response.send_message(f"🤖 当前模型: `{current}`")

    @app_commands.command(name="thinking", description="设置当前频道的思考深度")
    @app_commands.choices(level=THINKING_CHOICES)
    async def thinking_command(self, interaction: discord.Interaction, level: app_commands.Choice[str]):
        cs = self.bot.channel_settings
        cs.set(interaction.channel_id, "thinking", None if level.value == "default" else level.value)
        current = cs.get(interaction.channel_id, "thinking") or "默认"
        await interaction.response.send_message(f"🧠 思考深度: `{current}`")


async def setup(bot):
    await bot.add_cog(AgentCommands(bot))
