"""Logs & Audit system — /logs-setup, per-guild audit channel, category control."""
import time
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import t, load_config, save_config, load_logs_data


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


CATEGORIES = ["profile", "economy", "items", "shifter", "mission", "job", "squad", "admin", "mindless"]


class LogsSetupView(LayoutView):
    def __init__(self, gid: int, guild):
        super().__init__(timeout=300)
        self.gid = gid; self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        cfg     = load_config(self.gid)
        ch_id   = cfg.get("logs_channel")
        ch_name = "Not configured"
        if ch_id and self.guild:
            ch = self.guild.get_channel(int(ch_id))
            ch_name = f"<#{ch_id}>" if ch else f"Unknown ({ch_id})"

        cats = cfg.get("logs_categories", {})
        cat_lines = []
        for c in CATEGORIES:
            enabled = cats.get(c, True)
            cat_lines.append(f"{'✅' if enabled else '❌'} {c}")

        text = "\n".join([
            f"**{t(self.gid,'logs_setup_title')}**",
            "",
            f"**{t(self.gid,'logs_channel_label')}:** {ch_name}",
            "",
            "**Categories:**",
            *cat_lines,
        ])

        create_btn = Button(label=t(self.gid, "create_logs_channel_btn"),
                            style=discord.ButtonStyle.green, custom_id="ls_create")
        set_btn    = Button(label=t(self.gid, "set_logs_channel_btn"),
                            style=discord.ButtonStyle.secondary, custom_id="ls_set")
        cats_btn   = Button(label=t(self.gid, "logs_categories_btn"),
                            style=discord.ButtonStyle.secondary, custom_id="ls_cats")
        view_btn   = Button(label=t(self.gid, "view_logs_btn"),
                            style=discord.ButtonStyle.secondary, custom_id="ls_view")
        done_btn   = Button(label=t(self.gid, "done_btn"),
                            style=discord.ButtonStyle.danger, custom_id="ls_done")

        create_btn.callback = self._create_channel
        set_btn.callback    = self._set_channel
        cats_btn.callback   = self._categories
        view_btn.callback   = self._view_logs
        done_btn.callback   = self._done

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(create_btn, set_btn),
            ActionRow(cats_btn, view_btn),
            ActionRow(done_btn),
        ))

    async def _create_channel(self, ix: discord.Interaction):
        if not ix.guild:
            await ix.response.send_message("Guild not found.", ephemeral=True); return
        overwrites = {
            ix.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ix.guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for role in ix.guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True)
        try:
            ch = await ix.guild.create_text_channel(
                "server-logs", overwrites=overwrites,
                topic="Bot audit log — admin eyes only"
            )
            cfg = load_config(self.gid)
            cfg["logs_channel"] = str(ch.id)
            save_config(self.gid, cfg)
            self._build()
            await ix.response.edit_message(view=self)
            await ix.followup.send(
                t(self.gid, "logs_channel_created_msg", name=ch.name), ephemeral=True)
        except discord.Forbidden:
            await ix.response.send_message("Missing permissions to create channel.", ephemeral=True)

    async def _set_channel(self, ix: discord.Interaction):
        await ix.response.edit_message(view=_LogsChannelPickView(self.gid, self))

    async def _categories(self, ix: discord.Interaction):
        await ix.response.edit_message(view=LogsCategoriesView(self.gid, self))

    async def _view_logs(self, ix: discord.Interaction):
        await ix.response.edit_message(view=LogsViewView(self.gid, self))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


class _LogsChannelPickView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        ch_sel = discord.ui.ChannelSelect(
            placeholder="Select logs channel",
            channel_types=[discord.ChannelType.text],
        )
        ch_sel.callback = self._pick
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="lcp_bk")
        bk.callback = self._back
        self.add_item(Container(
            TextDisplay(f"**{t(gid,'set_logs_channel_btn')}**"),
            Separator(), ActionRow(ch_sel), ActionRow(bk),
        ))

    async def _pick(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["logs_channel"] = str(ix.data["values"][0])
        save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(t(self.gid, "logs_channel_set_msg"), ephemeral=True)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class LogsCategoriesView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        cfg  = load_config(self.gid)
        cats = cfg.get("logs_categories", {})

        opts = [discord.SelectOption(
                    label=f"{'✅' if cats.get(c, True) else '❌'} {c}",
                    value=c, default=False)
                for c in CATEGORIES]
        sel = Select(placeholder="Toggle category", options=opts)
        sel.callback = self._toggle

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="lca_bk")
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay("**Log Categories** — select to toggle on/off"),
            Separator(), ActionRow(sel), ActionRow(bk),
        ))

    async def _toggle(self, ix):
        cat = ix.data["values"][0]
        cfg = load_config(self.gid)
        cats = cfg.setdefault("logs_categories", {})
        cats[cat] = not cats.get(cat, True)
        save_config(self.gid, cfg)
        self._build()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class LogsViewView(LayoutView):
    def __init__(self, gid, parent, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        data    = load_logs_data(self.gid)
        entries = list(reversed(data.get("entries", [])))
        per_page = 10
        total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        chunk = entries[self.page * per_page:(self.page + 1) * per_page]

        if not chunk:
            body = t(self.gid, "no_logs_entries")
        else:
            lines = []
            for e in chunk:
                ts  = time.strftime("%m/%d %H:%M", time.localtime(e.get("ts", 0)))
                lines.append(f"`{ts}` [{e.get('category','?').upper()}] {e.get('text','')[:100]}")
            body = "\n".join(lines)

        bk_btn   = Button(label=t(self.gid, "back_btn"),  style=discord.ButtonStyle.secondary, custom_id="lv_bk")
        prev_btn = Button(label=t(self.gid, "prev_btn"),  style=discord.ButtonStyle.secondary,
                          custom_id="lv_prev", disabled=(self.page == 0))
        next_btn = Button(label=t(self.gid, "next_btn"),  style=discord.ButtonStyle.secondary,
                          custom_id="lv_next", disabled=(self.page >= total_pages - 1))
        bk_btn.callback   = self._back
        prev_btn.callback = self._prev
        next_btn.callback = self._next

        self.add_item(Container(
            ActionRow(bk_btn),
            Separator(),
            TextDisplay(f"**{t(self.gid,'view_logs_btn')}** — {t(self.gid,'page_label',page=self.page+1,total=total_pages)}\n\n{body}"),
            Separator(),
            ActionRow(prev_btn, next_btn),
        ))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _prev(self, ix):
        self.page -= 1; self._build(); await ix.response.edit_message(view=self)

    async def _next(self, ix):
        self.page += 1; self._build(); await ix.response.edit_message(view=self)


@bot.tree.command(name="logs-setup",
                  description="Configure the audit logging system",
                  guild=GUILD2_OBJ)
@_is_admin()
async def logs_setup_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=LogsSetupView(ix.guild_id, ix.guild), ephemeral=True)

@logs_setup_cmd.error
async def logs_setup_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
