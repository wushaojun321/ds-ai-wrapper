"""Run the agent for a Discord channel with a live-updating progress message."""

import asyncio
import logging
import tempfile
import time
import uuid
from pathlib import Path

import discord

from pi_agent import PiAgent, Progress, RunResult

logger = logging.getLogger("discord_bot")

MAX_MSG_LEN = 1900  # Discord limit is 2000, leave margin
EDIT_INTERVAL = 1.5  # seconds between progress edits (Discord rate limits edits)
MAX_ATTACHMENT = 5 * 1024 * 1024
UPLOAD_DIR = Path(tempfile.gettempdir()) / "dsbot-uploads"

TOOL_ICONS = {
    "bash": "💻", "read": "📖", "write": "📝", "grep": "🔍", "find": "🔍", "ls": "📂",
    "edit": "✏️", "replace": "✏️", "replace_match": "✏️", "insert": "✏️",
    "copy": "📋", "move": "📦", "undo_last_change": "↩️",
    "web_search": "🌐", "fetch_content": "🌐", "get_search_content": "🌐", "source_check": "🌐",
}


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
    return _balance_code_fences(chunks)


def _balance_code_fences(chunks: list[str]) -> list[str]:
    """Close a ``` block at the end of a chunk and reopen it in the next one."""
    out, carry = [], ""
    for c in chunks:
        c = carry + c
        carry = ""
        if c.count("```") % 2 == 1:
            c += "\n```"
            carry = "```\n"
        out.append(c)
    return out


def render_progress(p: Progress, started: float) -> str:
    lines = []
    for s in p.steps[-8:]:
        mark = "❌" if s.error else ("✅" if s.done else "⏳")
        icon = TOOL_ICONS.get(s.tool, "🔧")
        lines.append(f"{mark} {icon} `{s.tool}` {('`' + s.summary.replace('`', 'ˋ') + '`') if s.summary else ''}")
    if len(p.steps) > 8:
        lines.insert(0, f"-# …前面还有 {len(p.steps) - 8} 步")
    status = "🧠 思考中…" if p.thinking else ("🗜️ 压缩上下文…" if p.compacting else "✍️ 生成中…")
    if p.retry:
        status = f"🔁 {p.retry}"
    lines.append(f"{status} · {int(time.time() - started)}s")
    if p.text:
        tail = p.text[-900:]
        lines.append("\n" + ("…" if len(p.text) > 900 else "") + tail)
    text = "\n".join(lines)
    return text[-MAX_MSG_LEN:]


def render_footer(r: RunResult, elapsed: float) -> str:
    model = r.model.split("/")[-1]
    parts = [model, f"{int(elapsed)}s"]
    if r.steps:
        parts.append(f"{r.steps} 步工具")
    if r.cost:
        parts.append(f"${r.cost:.4f}")
    if r.context_tokens:
        parts.append(f"ctx {r.context_tokens / 1000:.1f}k")
    if r.session_id:
        parts.append(f"`{r.session_id[:8]}`")
    return "-# " + " · ".join(parts)


class StopView(discord.ui.View):
    def __init__(self, agent: PiAgent, channel_id: int):
        super().__init__(timeout=None)
        self._agent = agent
        self._channel_id = channel_id

    @discord.ui.button(label="停止", emoji="⏹", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = self._agent.stop(self._channel_id)
        await interaction.response.send_message("⏹ 已停止" if ok else "没有正在运行的任务", ephemeral=True)


class ChannelRunner:
    """Serializes runs per channel and renders their progress into Discord."""

    def __init__(self, agent: PiAgent, session_manager, workspace_manager, settings):
        self.agent = agent
        self.sm = session_manager
        self.ws = workspace_manager
        self.settings = settings
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, channel_id: int) -> asyncio.Lock:
        return self._locks.setdefault(channel_id, asyncio.Lock())

    def is_busy(self, channel_id: int) -> bool:
        return self._lock(channel_id).locked()

    async def save_attachments(self, message: discord.Message) -> list[str]:
        paths = []
        for a in message.attachments:
            if a.size > MAX_ATTACHMENT:
                continue
            d = UPLOAD_DIR / str(message.id)
            d.mkdir(parents=True, exist_ok=True)
            p = d / Path(a.filename).name
            await a.save(p)
            paths.append(str(p))
        return paths

    async def run(
        self,
        channel: discord.abc.Messageable,
        prompt: str,
        *,
        mode: str = "auto",  # auto | new | resume | fork | continue
        session_id: str | None = None,
        reply_to: discord.Message | None = None,
        files: list[str] | None = None,
        header: str = "",
    ) -> RunResult | None:
        channel_id = channel.id
        cwd = self.ws.get_path(channel_id, channel.name)
        lock = self._lock(channel_id)

        if lock.locked() and reply_to:
            try:
                await reply_to.add_reaction("⏳")
            except discord.HTTPException:
                pass

        async with lock:
            if reply_to:
                try:
                    await reply_to.remove_reaction("⏳", reply_to.guild.me)
                except (discord.HTTPException, AttributeError):
                    pass

            current = self.sm.get_current(channel_id)
            kwargs: dict = {}
            new_sid = None
            if mode == "fork":
                kwargs["fork_from"] = session_id or current
            elif mode == "continue":
                kwargs["continue_latest"] = True
            elif mode == "resume":
                kwargs["session_id"] = session_id
            elif mode == "auto" and current:
                kwargs["session_id"] = current
            else:  # new
                new_sid = str(uuid.uuid4())
                kwargs["session_id"] = new_sid

            started = time.time()
            view = StopView(self.agent, channel_id)
            initial = (header + "\n" if header else "") + "🚀 开始处理…"
            if reply_to:
                status = await reply_to.reply(initial, view=view, mention_author=False)
            else:
                status = await channel.send(initial, view=view)

            latest: dict = {"p": None, "dirty": False}

            async def on_progress(p: Progress):
                latest["p"], latest["dirty"] = p, True

            async def ticker():
                while True:
                    await asyncio.sleep(EDIT_INTERVAL)
                    if latest["dirty"] and latest["p"]:
                        latest["dirty"] = False
                        body = render_progress(latest["p"], started)
                        try:
                            await status.edit(content=((header + "\n") if header else "") + body)
                        except discord.HTTPException as e:
                            logger.debug("progress edit failed: %s", e)

            tick = asyncio.create_task(ticker())
            try:
                result = await self.agent.run(
                    prompt,
                    cwd=cwd,
                    channel_id=channel_id,
                    model=self.settings.get(channel_id, "model"),
                    thinking=self.settings.get(channel_id, "thinking"),
                    files=files,
                    on_progress=on_progress,
                    **kwargs,
                )
            except Exception as e:
                logger.error("[ch:%s] agent run failed: %s", channel_id, e, exc_info=True)
                tick.cancel()
                await status.edit(content=f"⚠️ 运行失败: {e}", view=None)
                return None
            finally:
                tick.cancel()

            # Track the session in the channel's stack
            sid = result.session_id
            if sid and sid != current:
                label = ("[fork] " if mode == "fork" else "") + prompt
                if not self.sm.switch_to(channel_id, sid):
                    self.sm.push_new(channel_id, sid, label)

            await self._deliver(channel, status, result, header, time.time() - started)
            return result

    async def _deliver(self, channel, status: discord.Message, r: RunResult, header: str, elapsed: float):
        if r.aborted:
            body = (r.text + "\n\n" if r.text else "") + "⏹ 已停止"
        elif r.error and not r.text:
            body = f"⚠️ 出错了:\n```\n{r.error[:1500]}\n```"
        else:
            body = r.text + (f"\n\n⚠️ {r.error[:300]}" if r.error else "")
        body = ((header + "\n\n") if header else "") + body + "\n" + render_footer(r, elapsed)
        chunks = split_message(body)
        await status.edit(content=chunks[0], view=None)
        for chunk in chunks[1:]:
            await channel.send(chunk)
