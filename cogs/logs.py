"""Logs & Audit system — /logs-setup, per-guild audit channel, category control."""
import time
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    t,
    load_config, save_config,
    load_logs_data,
    log_event,
    EMBED_COLOR,
)


# ── Constants ─────────────────────────────────────────────────────────────────

CATEGORIES = [
    "profile",
    "economy",
    "shop",
    "mission",
    "job",
    "squad",
    "mindless",
    "shifter",
    "admin",
]

CATEGORY_EMOJIS = {
    "profile":  "👤",
    "economy":  "💰",
    "shop":     "🏪",
    "mission":  "⚔️",
    "job":      "💼",
    "squad":    "🛡️",
    "mindless": "🧟",
    "shifter":  "⚡",
    "admin":    "🔧",
}


# ── Admin check ───────────────────────────────────────────────────────────────

def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild:
            return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (
            m.guild_permissions.administrator or m.guild_permissions.manage_guild
        )
    return app_commands.check(pred)


# ── Helper: build the main status embed ──────────────────────────────────────

def _main_embed(gid: int, guild) -> discord.Embed:
    cfg = load_config(gid)
    ch_id = cfg.get("logs_channel")
    if ch_id and guild:
        ch = guild.get_channel(int(ch_id))
        ch_display = f"<#{ch_id}>" if ch else f"Unknown ({ch_id})"
    else:
        ch_display = "*Not configured*"

    cats = cfg.get("logs_categories", {})
    cat_lines = []
    for c in CATEGORIES:
        emoji = CATEGORY_EMOJIS.get(c, "•")
        state = "✅" if cats.get(c, True) else "❌"
        cat_lines.append(f"{state} {emoji} **{c}**")

    embed = discord.Embed(
        title=t(gid, "logs_setup_title"),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name=t(gid, "logs_channel_label"),
        value=ch_display,
        inline=False,
    )
    embed.add_field(
        name="Log Categories",
        value="\n".join(cat_lines) or "—",
        inline=False,
    )
    embed.set_footer(text="Use the buttons below to configure logging.")
    return embed


# ── Main Setup View ───────────────────────────────────────────────────────────

class LogsSetupView(discord.ui.View):
    def __init__(self, gid: int, guild):
        super().__init__(timeout=300)
        self.gid = gid
        self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()

        create_btn = discord.ui.Button(
            label=t(self.gid, "create_logs_channel_btn"),
            style=discord.ButtonStyle.green,
            row=0,
        )
        set_btn = discord.ui.Button(
            label=t(self.gid, "set_logs_channel_btn"),
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        cats_btn = discord.ui.Button(
            label=t(self.gid, "logs_categories_btn"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        view_btn = discord.ui.Button(
            label=t(self.gid, "view_logs_btn"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            row=2,
        )

        create_btn.callback = self._create_channel
        set_btn.callback = self._set_channel
        cats_btn.callback = self._categories
        view_btn.callback = self._view_logs
        done_btn.callback = self._done

        for btn in (create_btn, set_btn, cats_btn, view_btn, done_btn):
            self.add_item(btn)

    async def _create_channel(self, ix: discord.Interaction):
        if not ix.guild:
            await ix.response.send_message("Guild not found.", ephemeral=True)
            return

        overwrites = {
            ix.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ix.guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True
            ),
        }
        for role in ix.guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True)

        try:
            ch = await ix.guild.create_text_channel(
                "server-logs",
                overwrites=overwrites,
                topic="Bot audit log — admin eyes only",
            )
            cfg = load_config(self.gid)
            cfg["logs_channel"] = str(ch.id)
            save_config(self.gid, cfg)
            self._build()
            ok_embed = discord.Embed(
                description=t(self.gid, "logs_channel_created_msg", name=ch.name),
                color=EMBED_COLOR,
            )
            await ix.response.edit_message(
                embed=_main_embed(self.gid, ix.guild), view=self
            )
            await ix.followup.send(embed=ok_embed, ephemeral=True)
        except discord.Forbidden:
            err_embed = discord.Embed(
                description="Missing permissions to create channel.",
                color=discord.Color.red(),
            )
            await ix.response.send_message(embed=err_embed, ephemeral=True)

    async def _set_channel(self, ix: discord.Interaction):
        pick_view = _LogsChannelPickView(self.gid, self, ix.guild)
        pick_embed = discord.Embed(
            title=t(self.gid, "set_logs_channel_btn"),
            description="Select an existing text channel to use as the audit log channel.",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=pick_embed, view=pick_view)

    async def _categories(self, ix: discord.Interaction):
        cats_view = LogsCategoriesView(self.gid, self, ix.guild)
        await ix.response.edit_message(
            embed=_categories_embed(self.gid), view=cats_view
        )

    async def _view_logs(self, ix: discord.Interaction):
        logs_view = LogsViewView(self.gid, self, ix.guild, page=0)
        await ix.response.edit_message(
            embed=logs_view.build_embed(), view=logs_view
        )

    async def _done(self, ix: discord.Interaction):
        closed_embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=closed_embed, view=self)


# ── Channel Picker View ───────────────────────────────────────────────────────

class _LogsChannelPickView(discord.ui.View):
    def __init__(self, gid: int, parent: LogsSetupView, guild):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.guild = guild

        ch_sel = discord.ui.ChannelSelect(
            placeholder="Select logs channel…",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        ch_sel.callback = self._pick
        self.add_item(ch_sel)

        back_btn = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _pick(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["logs_channel"] = str(ix.data["values"][0])
        save_config(self.gid, cfg)
        self.parent._build()
        ok_embed = discord.Embed(
            description=t(self.gid, "logs_channel_set_msg"),
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(
            embed=_main_embed(self.gid, ix.guild), view=self.parent
        )
        await ix.followup.send(embed=ok_embed, ephemeral=True)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(
            embed=_main_embed(self.gid, ix.guild), view=self.parent
        )


# ── Categories View ───────────────────────────────────────────────────────────

def _categories_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    cats = cfg.get("logs_categories", {})
    lines = []
    for c in CATEGORIES:
        emoji = CATEGORY_EMOJIS.get(c, "•")
        state = "✅" if cats.get(c, True) else "❌"
        lines.append(f"{state} {emoji} **{c}**")
    embed = discord.Embed(
        title=t(gid, "logs_categories_btn"),
        description="\n".join(lines) or "—",
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Select a category from the dropdown to toggle it on or off.")
    return embed


class LogsCategoriesView(discord.ui.View):
    def __init__(self, gid: int, parent: LogsSetupView, guild):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.gid)
        cats = cfg.get("logs_categories", {})

        options = [
            discord.SelectOption(
                label=f"{'✅' if cats.get(c, True) else '❌'} {CATEGORY_EMOJIS.get(c, '')} {c}",
                value=c,
                description="Currently " + ("enabled" if cats.get(c, True) else "disabled"),
            )
            for c in CATEGORIES
        ]
        sel = discord.ui.Select(
            placeholder="Toggle a log category…",
            options=options,
            row=0,
        )
        sel.callback = self._toggle
        self.add_item(sel)

        back_btn = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _toggle(self, ix: discord.Interaction):
        cat = ix.data["values"][0]
        cfg = load_config(self.gid)
        cats = cfg.setdefault("logs_categories", {})
        cats[cat] = not cats.get(cat, True)
        save_config(self.gid, cfg)
        self._build()
        await ix.response.edit_message(embed=_categories_embed(self.gid), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(
            embed=_main_embed(self.gid, ix.guild), view=self.parent
        )


# ── Log Viewer View ───────────────────────────────────────────────────────────

class LogsViewView(discord.ui.View):
    PER_PAGE = 10

    def __init__(self, gid: int, parent: LogsSetupView, guild, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.guild = guild
        self.page = page

        data = load_logs_data(gid)
        self._entries = list(reversed(data.get("entries", [])))
        self._total_pages = max(
            1, (len(self._entries) + self.PER_PAGE - 1) // self.PER_PAGE
        )
        self.page = max(0, min(page, self._total_pages - 1))
        self._build()

    def build_embed(self) -> discord.Embed:
        chunk = self._entries[
            self.page * self.PER_PAGE : (self.page + 1) * self.PER_PAGE
        ]
        embed = discord.Embed(
            title=t(self.gid, "view_logs_btn"),
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=t(
                self.gid,
                "page_label",
                page=self.page + 1,
                total=self._total_pages,
            )
        )
        if not chunk:
            embed.description = t(self.gid, "no_logs_entries")
            return embed

        lines = []
        for e in chunk:
            ts = time.strftime("%m/%d %H:%M", time.localtime(e.get("ts", 0)))
            cat = e.get("category", "?").upper()
            cat_emoji = CATEGORY_EMOJIS.get(e.get("category", ""), "•")
            text_snippet = e.get("text", "")[:120]
            lines.append(f"`{ts}` {cat_emoji} **{cat}** — {text_snippet}")

        embed.description = "\n".join(lines)
        return embed

    def _build(self):
        self.clear_items()

        back_btn = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        prev_btn = discord.ui.Button(
            label=t(self.gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            disabled=(self.page == 0),
            row=1,
        )
        next_btn = discord.ui.Button(
            label=t(self.gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            disabled=(self.page >= self._total_pages - 1),
            row=1,
        )

        back_btn.callback = self._back
        prev_btn.callback = self._prev
        next_btn.callback = self._next

        for btn in (back_btn, prev_btn, next_btn):
            self.add_item(btn)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(
            embed=_main_embed(self.gid, ix.guild), view=self.parent
        )

    async def _prev(self, ix: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._build()
        await ix.response.edit_message(embed=self.build_embed(), view=self)

    async def _next(self, ix: discord.Interaction):
        self.page = min(self._total_pages - 1, self.page + 1)
        self._build()
        await ix.response.edit_message(embed=self.build_embed(), view=self)


# ── Slash command ─────────────────────────────────────────────────────────────

@bot.tree.command(
    name="logs-setup",
    description="Configure the audit logging system",
    description_localizations={"th": "ตั้งค่าระบบบันทึกการกระทำของเซิร์ฟเวอร์"},
)
@_is_admin()
async def logs_setup_cmd(ix: discord.Interaction):
    view = LogsSetupView(ix.guild_id, ix.guild)
    await ix.response.send_message(
        embed=_main_embed(ix.guild_id, ix.guild),
        view=view,
        ephemeral=True,
    )


@logs_setup_cmd.error
async def logs_setup_error(ix: discord.Interaction, error):
    await ix.response.send_message(
        t(ix.guild_id, "admin_only"), ephemeral=True
    )
