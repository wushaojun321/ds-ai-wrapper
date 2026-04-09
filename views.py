"""Discord UI components (Select menus, etc.)."""

import datetime
import logging
import math

import discord

logger = logging.getLogger("discord_bot")

PAGE_SIZE = 25  # Discord Select max options


class SessionSelectView(discord.ui.View):
    """A paginated dropdown menu for selecting and switching sessions."""

    def __init__(self, sessions: list[dict], session_manager, channel_id: int):
        super().__init__(timeout=120)
        self._sm = session_manager
        self._channel_id = channel_id
        self._sessions = sessions
        self._sessions_lookup = {s["session_id"]: s for s in sessions}
        self._page = 0
        self._total_pages = max(1, math.ceil(len(sessions) / PAGE_SIZE))

        self._rebuild_select()
        self._update_buttons()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_options(self, page: int) -> list[discord.SelectOption]:
        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        options = []
        for s in self._sessions[start:end]:
            sid = s["session_id"]
            display = (s.get("display") or "(unknown)")[:80] or "(empty)"
            ts = s.get("timestamp") or s.get("created_at", 0)
            if ts:
                time_str = datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
            else:
                time_str = "?"
            options.append(discord.SelectOption(
                label=display,
                value=sid,
                description=f"{time_str} · {sid[:8]}",
            ))
        return options

    def _rebuild_select(self):
        options = self._build_options(self._page)
        self.select_menu.options = options
        page_label = f"第 {self._page + 1}/{self._total_pages} 页" if self._total_pages > 1 else "选择一个会话来切换…"
        self.select_menu.placeholder = page_label

    def _update_buttons(self):
        show_buttons = self._total_pages > 1
        self.btn_prev.disabled = self._page <= 0
        self.btn_next.disabled = self._page >= self._total_pages - 1
        # Hide pagination buttons if only 1 page
        if not show_buttons:
            self.btn_prev.style = discord.ButtonStyle.secondary
            self.btn_next.style = discord.ButtonStyle.secondary
            self.remove_item(self.btn_prev)
            self.remove_item(self.btn_next)

    # ------------------------------------------------------------------
    # Select callback
    # ------------------------------------------------------------------
    @discord.ui.select(placeholder="选择一个会话来切换…")
    async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            selected_id = select.values[0]
            ok = self._sm.switch_to(self._channel_id, selected_id)
            if not ok:
                info = self._sessions_lookup.get(selected_id, {})
                display = info.get("display", "(restored)")
                self._sm.push_new(self._channel_id, selected_id, display)
                ok = True
            if ok:
                await interaction.response.send_message(
                    f"✅ 已切换到会话 `{selected_id[:8]}…`", ephemeral=True
                )
        except Exception as e:
            logger.error("Session select failed: %s", e, exc_info=True)
            try:
                await interaction.response.send_message(
                    f"❌ 切换失败: {e}", ephemeral=True
                )
            except Exception:
                pass
        self.stop()

    # ------------------------------------------------------------------
    # Pagination buttons
    # ------------------------------------------------------------------
    @discord.ui.button(label="◀ 上一页", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._page = max(0, self._page - 1)
        self._rebuild_select()
        self.btn_prev.disabled = self._page <= 0
        self.btn_next.disabled = self._page >= self._total_pages - 1
        await interaction.response.edit_message(
            content=f"📋 选择要切换的会话（第 {self._page + 1}/{self._total_pages} 页）：",
            view=self,
        )

    @discord.ui.button(label="下一页 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._page = min(self._total_pages - 1, self._page + 1)
        self._rebuild_select()
        self.btn_prev.disabled = self._page <= 0
        self.btn_next.disabled = self._page >= self._total_pages - 1
        await interaction.response.edit_message(
            content=f"📋 选择要切换的会话（第 {self._page + 1}/{self._total_pages} 页）：",
            view=self,
        )

    async def on_timeout(self):
        """Disable the view after timeout."""
        for item in self.children:
            item.disabled = True

