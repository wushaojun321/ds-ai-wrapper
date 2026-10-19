"""Utility slash commands: /help /back /sessions /workspace /pull /push /messages /purge /restart."""

import asyncio
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from views import SessionSelectView

logger = logging.getLogger("discord_bot")


class CustomCommands(commands.Cog):
    """Utility slash commands."""

    def __init__(self, bot):
        self.bot = bot

    def _cwd(self, interaction: discord.Interaction) -> str:
        """Resolve workspace directory for this channel."""
        return self.bot.workspace_manager.get_path(
            interaction.channel_id, interaction.channel.name
        )

    # ------------------------------------------------------------------
    # /workspace — manage channel-to-directory bindings
    # ------------------------------------------------------------------
    @app_commands.command(name="workspace", description="管理频道的工作目录绑定")
    @app_commands.describe(
        action="操作类型",
        directory="目录的绝对路径（仅 bind 需要）",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="status — 查看当前绑定", value="status"),
        app_commands.Choice(name="bind — 绑定目录到此频道", value="bind"),
        app_commands.Choice(name="unbind — 解除绑定（回退到自动映射）", value="unbind"),
        app_commands.Choice(name="list — 查看所有绑定", value="list"),
    ])
    async def workspace_command(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        directory: str | None = None,
    ):
        ws = self.bot.workspace_manager
        channel_id = interaction.channel_id
        channel_name = interaction.channel.name

        if action.value == "status":
            current = ws.get_path(channel_id, channel_name)
            is_override = ws.is_override(channel_id)
            label = "🔗 手动绑定" if is_override else "📁 自动映射"
            await interaction.response.send_message(
                f"{label}: `{current}`", ephemeral=True
            )

        elif action.value == "bind":
            if not directory:
                await interaction.response.send_message(
                    "❌ 请提供 `directory` 参数。", ephemeral=True
                )
                return
            path = Path(directory).expanduser().resolve()
            if not path.is_dir():
                # Auto-create
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    await interaction.response.send_message(
                        f"❌ 无法创建目录 `{path}`: {e}", ephemeral=True
                    )
                    return
            ws.bind(channel_id, str(path))
            await interaction.response.send_message(
                f"✅ 此频道已绑定到: `{path}`"
            )

        elif action.value == "unbind":
            removed = ws.unbind(channel_id)
            if removed:
                auto_path = ws.get_path(channel_id, channel_name)
                await interaction.response.send_message(
                    f"✅ 已解绑，回退到自动映射: `{auto_path}`"
                )
            else:
                await interaction.response.send_message(
                    "ℹ️ 此频道没有手动绑定。", ephemeral=True
                )

        elif action.value == "list":
            overrides = ws.all_overrides()
            lines = []
            if overrides:
                for cid, p in overrides.items():
                    lines.append(f"• <#{cid}> → `{p}` (手动)")
            lines.append(f"\n自动映射规则: `{ws.base_dir}/` + 频道名")
            await interaction.response.send_message(
                "\n".join(lines), ephemeral=True
            )

    # ------------------------------------------------------------------
    # /help
    # ------------------------------------------------------------------
    @app_commands.command(name="help", description="显示所有可用命令")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 命令帮助",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="🤖 Agent 命令",
            value=(
                "`/new [question]` — 新建会话（可附带问题）\n"
                "`/clear [question]` — 清空会话重新开始（同 /new）\n"
                "`/continue [question]` — 继续最近会话\n"
                "`/resume <session_id> [question]` — 恢复指定会话\n"
                "`/fork <question>` — Fork 当前会话为新分支\n"
                "`/stop` — 停止正在运行的任务（也可点消息上的 ⏹）\n"
                "`/model` — 切换模型（默认 DeepSeek V4.1 Flash 1017）\n"
                "`/thinking` — 设置思考深度\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="📁 工作目录",
            value=(
                "`/workspace status` — 查看当前频道的工作目录\n"
                "`/workspace bind <path>` — 手动绑定目录到此频道\n"
                "`/workspace unbind` — 解除手动绑定\n"
                "`/workspace list` — 查看所有绑定\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚙️ 工具命令",
            value=(
                "`/help` — 显示此帮助信息\n"
                "`/back [n]` — 回退 n 个会话（默认 1）\n"
                "`/sessions` — 列出最近会话 + 下拉菜单切换\n"
                "`/messages [count]` — 查看当前会话的最新消息历史\n"
                "`/purge [count]` — 删除频道聊天记录\n"
                "`/pull` — 执行 git pull\n"
                "`/push` — 执行 git push\n"
                "`/restart` — 重启 Bot（容器自动拉起）\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="💬 普通对话",
            value="直接发送消息即可与 Agent 对话，可附带图片/文件。\n"
                  "每个频道自动映射到 `BASE_DIR/频道名` 作为工作目录。",
            inline=False,
        )

        embed.set_footer(text=f"Powered by pi · {self.bot.agent.default_model}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /back
    # ------------------------------------------------------------------
    @app_commands.command(name="back", description="回退到之前的会话")
    @app_commands.describe(n="回退步数（默认 1）")
    async def back_command(self, interaction: discord.Interaction, n: int = 1):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager

        if n < 1:
            await interaction.response.send_message("❌ 回退步数必须大于 0。", ephemeral=True)
            return

        new_sid = sm.back(channel_id, n)
        if new_sid:
            await interaction.response.send_message(
                f"⏪ 已回退 {n} 步，当前会话: `{new_sid[:8]}…`"
            )
        else:
            await interaction.response.send_message(
                f"❌ 无法回退 {n} 步，会话栈中没有足够的历史记录。", ephemeral=True
            )

    # ------------------------------------------------------------------
    # /sessions
    # ------------------------------------------------------------------
    @app_commands.command(name="sessions", description="列出最近会话并可切换")
    async def sessions_command(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager

        sessions = self.bot.agent.list_sessions(self._cwd(interaction), limit=75)

        if not sessions:
            stack = sm.get_stack(channel_id)
            if not stack:
                await interaction.response.send_message(
                    "📭 没有找到任何会话记录。", ephemeral=True
                )
                return
            sessions = stack

        view = SessionSelectView(sessions, sm, channel_id)
        await interaction.response.send_message("📋 选择要切换的会话：", view=view, ephemeral=True)

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------
    async def _run_git(self, interaction: discord.Interaction, *args: str) -> None:
        """Run a git command in the channel's workspace and reply with output."""
        repo_path = self._cwd(interaction)
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        err = stderr.decode().strip()

        if proc.returncode == 0:
            msg = output or "(no output)"
            await interaction.followup.send(f"✅ `git {' '.join(args)}` (`{repo_path}`)\n```\n{msg[:1800]}\n```")
        else:
            msg = err or output or "(unknown error)"
            await interaction.followup.send(f"❌ `git {' '.join(args)}` 失败 (`{repo_path}`)\n```\n{msg[:1800]}\n```")

    @app_commands.command(name="pull", description="执行 git pull 拉取最新代码")
    async def pull_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._run_git(interaction, "pull")

    @app_commands.command(name="push", description="执行 git push 推送到远程")
    async def push_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._run_git(interaction, "push")

    # ------------------------------------------------------------------
    # /purge
    # ------------------------------------------------------------------
    @app_commands.command(name="purge", description="删除当前频道的聊天记录")
    @app_commands.describe(count="要删除的消息数量（默认 100，输入 0 删除全部）")
    async def purge_command(self, interaction: discord.Interaction, count: int = 100):
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.response.send_message(
                "❌ Bot 缺少 `管理消息` 权限，无法删除消息。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            limit = None if count == 0 else count
            deleted = await interaction.channel.purge(limit=limit)
            await interaction.followup.send(
                f"🗑️ 已删除 {len(deleted)} 条消息。", ephemeral=True
            )
        except discord.errors.HTTPException as e:
            await interaction.followup.send(f"❌ 删除失败: {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /messages
    # ------------------------------------------------------------------
    @app_commands.command(name="messages", description="查看当前会话的最新消息历史")
    @app_commands.describe(count="要显示的消息数量（默认 10，最大 50）")
    async def messages_command(self, interaction: discord.Interaction, count: int = 10):
        channel_id = interaction.channel_id
        sm = self.bot.session_manager

        if count < 1:
            await interaction.response.send_message("❌ 消息数量必须大于 0。", ephemeral=True)
            return
        if count > 50:
            count = 50

        current_sid = sm.get_current(channel_id)
        if not current_sid:
            await interaction.response.send_message("❌ 当前频道没有活跃会话。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        history = self.bot.agent.read_messages(self._cwd(interaction), current_sid)
        if history is None:
            await interaction.followup.send(f"❌ 找不到会话文件: `{current_sid[:8]}…`", ephemeral=True)
            return

        messages = []
        for role, text in history:
            if role == "user":
                messages.append(f"👤 **用户**: {text[:300]}")
            else:
                messages.append(f"🤖 **Agent**: {text[:500] + '…' if len(text) > 500 else text}")

        recent_messages = messages[-count:] if messages else []

        if not recent_messages:
            await interaction.followup.send("📭 当前会话没有消息历史。", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"💬 会话消息历史 (最新 {len(recent_messages)} 条)",
            description="\n\n".join(recent_messages)[-4000:],
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"会话ID: {current_sid[:8]}…")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /restart
    # ------------------------------------------------------------------
    @app_commands.command(name="restart", description="自动重启Discord Bot服务")
    async def restart_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🔄 正在重启Discord Bot服务",
            color=discord.Color.orange(),
        )

        repo_path = self._cwd(interaction)

        try:
            proc_status = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )
            stdout_status, _ = await proc_status.communicate()
            git_status = stdout_status.decode().strip()

            if git_status:
                embed.add_field(
                    name="📊 Git状态（未提交的变更）",
                    value=f"```\n{git_status[:500]}\n```",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="📊 Git状态",
                    value="✅ 工作区干净",
                    inline=False,
                )

            proc_log = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", "-5",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )
            stdout_log, _ = await proc_log.communicate()
            git_log = stdout_log.decode().strip()

            if git_log:
                embed.add_field(
                    name="📝 最新提交历史（5条）",
                    value=f"```\n{git_log}\n```",
                    inline=False,
                )
        except Exception as e:
            embed.add_field(name="❌ Git信息获取失败", value=f"错误: {e}", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

        await interaction.channel.send("🔄 正在重启，稍等几秒…")
        logger.info("Restart requested via /restart")
        # Exit and let the container restart policy bring the bot back
        await self.bot.close()
        os._exit(0)


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
