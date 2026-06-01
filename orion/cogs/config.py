"""Orion — consolidated /config command with paginated in-place editing."""
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR, RANKS, DEFAULT_CAP,
    load_config, save_config,
    currency_cfg, format_cooldown,
)

_PAGES = [
    "general",
    "channels",
    "character",
    "economy",
    "training",
    "scavenge",
    "missions",
    "creation",
]
_PAGE_TITLES = {
    "general":   "⚙️ General",
    "channels":  "📢 Channels",
    "character": "👤 Character",
    "economy":   "💰 Economy",
    "training":  "🏋️ Training",
    "scavenge":  "🌿 Scavenge",
    "missions":  "⚔️ Missions",
    "creation":  "🔨 Creation",
}


def _page_embed(gid: int, page: str) -> discord.Embed:
    cfg   = load_config(gid)
    embed = discord.Embed(title=_PAGE_TITLES.get(page, page), color=EMBED_COLOR)

    def _ch(key: str) -> str:
        v = cfg.get(key)
        return f"<#{v}>" if v else "*ไม่ได้ตั้ง*"

    def _role(key: str) -> str:
        v = cfg.get(key)
        return f"<@&{v}>" if v else "*ไม่ได้ตั้ง*"

    def _val(key: str, default="*ไม่ได้ตั้ง*") -> str:
        v = cfg.get(key)
        return str(v) if v is not None else default

    if page == "general":
        embed.description = "ตั้งค่าทั่วไปของบอท"
        embed.add_field(name="Prefix", value=cfg.get("prefix", "!"), inline=True)

    elif page == "channels":
        embed.add_field(name="Logs Channel",          value=_ch("logs_channel"),            inline=True)
        embed.add_field(name="Admin Review Channel",  value=_ch("admin_review_channel_id"),  inline=True)
        embed.add_field(name="Character Forum",       value=_ch("character_forum_id"),       inline=True)
        mc = cfg.get("mission_channels", [])
        embed.add_field(
            name="Mission Channels",
            value=" ".join(f"<#{c}>" for c in mc) or "*ไม่ได้ตั้ง*",
            inline=False,
        )

    elif page == "character":
        embed.add_field(name="Character Forum ID", value=_ch("character_forum_id"), inline=True)

    elif page == "economy":
        cc = currency_cfg(gid)
        embed.add_field(name="ชื่อสกุลเงิน", value=cc["name"],  inline=True)
        embed.add_field(name="Emoji",         value=cc["emoji"], inline=True)

    elif page == "training":
        cap      = cfg.get("rank_cap", DEFAULT_CAP)
        cost     = cfg.get("train_cost", 50)
        cd       = cfg.get("train_cooldown", 3600)
        exc_rids = cfg.get("exceed_cap_roles", [])
        exc_str  = ", ".join(f"<@&{r}>" for r in exc_rids) or "—"
        embed.add_field(name="Rank Cap",            value=cap,                 inline=True)
        embed.add_field(name="ค่าฝึก",              value=str(cost),           inline=True)
        embed.add_field(name="คูลดาวน์",            value=format_cooldown(cd), inline=True)
        embed.add_field(name="Exceed-Cap Roles",    value=exc_str,             inline=False)

    elif page == "scavenge":
        cd = cfg.get("scavenge_cooldown", 1800)
        embed.add_field(name="คูลดาวน์หาของ", value=format_cooldown(cd), inline=True)

    elif page == "missions":
        mc = cfg.get("mission_channels", [])
        embed.add_field(
            name="Mission Channels",
            value=" ".join(f"<#{c}>" for c in mc) or "*ไม่ได้ตั้ง*",
            inline=False,
        )

    elif page == "creation":
        embed.add_field(name="Blacksmith Role",   value=_role("blacksmith_role_id"),    inline=True)
        embed.add_field(name="Review Channel",    value=_ch("admin_review_channel_id"),  inline=True)

    return embed


class ConfigView(discord.ui.View):
    def __init__(self, gid: int, page: str = "general"):
        super().__init__(timeout=300)
        self.gid  = gid
        self.page = page
        self._build()

    def _build(self):
        self.clear_items()

        # Page selector
        page_opts = [
            discord.SelectOption(
                label=_PAGE_TITLES.get(p, p),
                value=p,
                default=p == self.page,
            )
            for p in _PAGES
        ]
        page_sel = discord.ui.Select(
            placeholder="เลือกหมวดการตั้งค่า…",
            options=page_opts,
            row=0,
        )
        page_sel.callback = self._on_page
        self.add_item(page_sel)

        # Edit buttons per page
        edit_btn = discord.ui.Button(
            label="✏️ แก้ไขการตั้งค่านี้",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        edit_btn.callback = self._edit
        self.add_item(edit_btn)

        close_btn = discord.ui.Button(
            label="✅ ปิด",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        close_btn.callback = self._close
        self.add_item(close_btn)

    async def _on_page(self, ix: discord.Interaction):
        self.page = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(embed=_page_embed(self.gid, self.page), view=self)

    async def _edit(self, ix: discord.Interaction):
        page = self.page
        if page == "general":
            await ix.response.send_modal(EditGeneralModal(self.gid))
        elif page == "channels":
            await ix.response.send_message(
                embed=discord.Embed(description="แก้ไข Channels:", color=EMBED_COLOR),
                view=EditChannelsView(self.gid, self),
                ephemeral=True,
            )
        elif page == "character":
            await ix.response.send_message(
                embed=discord.Embed(description="เลือก Character Forum:", color=EMBED_COLOR),
                view=EditForumView(self.gid, self),
                ephemeral=True,
            )
        elif page == "economy":
            await ix.response.send_modal(EditEconomyModal(self.gid))
        elif page == "training":
            await ix.response.send_modal(EditTrainingModal(self.gid))
        elif page == "scavenge":
            await ix.response.send_modal(EditScavengeModal(self.gid))
        elif page == "missions":
            await ix.response.send_message(
                embed=discord.Embed(description="เลือก Mission Channels:", color=EMBED_COLOR),
                view=EditMissionChannelsView(self.gid, self),
                ephemeral=True,
            )
        elif page == "creation":
            await ix.response.send_message(
                embed=discord.Embed(description="ตั้งค่า Creation:", color=EMBED_COLOR),
                view=EditCreationView(self.gid, self),
                ephemeral=True,
            )

    async def _close(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(description="ปิด Settings แล้ว", color=EMBED_COLOR),
            view=None,
        )

    async def _refresh(self, ix: discord.Interaction):
        self._build()
        await ix.response.edit_message(embed=_page_embed(self.gid, self.page), view=self)


# ── Edit modals / views per page ──────────────────────────────────────────────

class EditGeneralModal(discord.ui.Modal, title="แก้ไข General"):
    prefix = discord.ui.TextInput(label="Prefix", max_length=5, required=False)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        cfg = load_config(gid)
        self.prefix.default = cfg.get("prefix", "!")

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["prefix"] = self.prefix.value.strip() or "!"
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ บันทึกแล้ว", color=EMBED_COLOR), ephemeral=True
        )


class EditChannelsView(discord.ui.View):
    def __init__(self, gid: int, parent: ConfigView):
        super().__init__(timeout=120)
        self.gid    = gid
        self.parent = parent

    @discord.ui.button(label="📋 Logs Channel", style=discord.ButtonStyle.secondary, row=0)
    async def logs(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Logs Channel…",
            channel_types=[discord.ChannelType.text],
        )

        async def _cb(ix2: discord.Interaction):
            cfg = load_config(self.gid)
            cfg["logs_channel"] = ix2.data["values"][0]
            save_config(self.gid, cfg)
            await ix2.response.send_message("✅ บันทึกแล้ว", ephemeral=True)

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="🔍 Admin Review Channel", style=discord.ButtonStyle.secondary, row=0)
    async def review(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Review Channel…",
            channel_types=[discord.ChannelType.text],
        )

        async def _cb(ix2: discord.Interaction):
            cfg = load_config(self.gid)
            cfg["admin_review_channel_id"] = ix2.data["values"][0]
            save_config(self.gid, cfg)
            await ix2.response.send_message("✅ บันทึกแล้ว", ephemeral=True)

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)


class EditForumView(discord.ui.View):
    def __init__(self, gid: int, parent: ConfigView):
        super().__init__(timeout=120)
        self.gid    = gid
        self.parent = parent
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Forum Channel…",
            channel_types=[discord.ChannelType.forum],
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["character_forum_id"] = ix.data["values"][0]
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ ตั้ง Character Forum แล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )


class EditEconomyModal(discord.ui.Modal, title="แก้ไข Economy"):
    name_f  = discord.ui.TextInput(label="ชื่อสกุลเงิน", max_length=30)
    emoji_f = discord.ui.TextInput(label="Emoji",         max_length=10)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        cc = currency_cfg(gid)
        self.name_f.default  = cc["name"]
        self.emoji_f.default = cc["emoji"]

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["currency_name"]  = self.name_f.value.strip()
        cfg["currency_emoji"] = self.emoji_f.value.strip()
        save_config(self.gid, cfg)
        await ix.response.send_message("✅ บันทึกแล้ว", ephemeral=True)


class EditTrainingModal(discord.ui.Modal, title="แก้ไข Training"):
    cap_f  = discord.ui.TextInput(label="Rank Cap (เช่น B+)", max_length=4)
    cost_f = discord.ui.TextInput(label="ค่าฝึก",              max_length=10)
    cd_f   = discord.ui.TextInput(label="คูลดาวน์ (วินาที)",   max_length=8)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        cfg = load_config(gid)
        self.cap_f.default  = cfg.get("rank_cap", DEFAULT_CAP)
        self.cost_f.default = str(cfg.get("train_cost", 50))
        self.cd_f.default   = str(cfg.get("train_cooldown", 3600))

    async def on_submit(self, ix: discord.Interaction):
        cap = self.cap_f.value.strip().upper()
        if cap not in RANKS:
            await ix.response.send_message(f"Rank ไม่ถูกต้อง: {cap}", ephemeral=True)
            return
        try:
            cost = max(0, int(self.cost_f.value.strip()))
            cd   = max(0, int(self.cd_f.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["rank_cap"]       = cap
        cfg["train_cost"]     = cost
        cfg["train_cooldown"] = cd
        save_config(self.gid, cfg)
        await ix.response.send_message("✅ บันทึกแล้ว", ephemeral=True)


class EditScavengeModal(discord.ui.Modal, title="แก้ไข Scavenge"):
    cd_f = discord.ui.TextInput(label="คูลดาวน์หาของ (วินาที)", max_length=8)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        cfg = load_config(gid)
        self.cd_f.default = str(cfg.get("scavenge_cooldown", 1800))

    async def on_submit(self, ix: discord.Interaction):
        try:
            val = max(0, int(self.cd_f.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["scavenge_cooldown"] = val
        save_config(self.gid, cfg)
        await ix.response.send_message("✅ บันทึกแล้ว", ephemeral=True)


class EditMissionChannelsView(discord.ui.View):
    def __init__(self, gid: int, parent: ConfigView):
        super().__init__(timeout=120)
        self.gid    = gid
        self.parent = parent
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Mission Channels…",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=10,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["mission_channels"] = ix.data["values"]
        save_config(self.gid, cfg)
        await ix.response.send_message("✅ บันทึกแล้ว", ephemeral=True)


class EditCreationView(discord.ui.View):
    def __init__(self, gid: int, parent: ConfigView):
        super().__init__(timeout=120)
        self.gid    = gid
        self.parent = parent

    @discord.ui.button(label="🎭 Blacksmith Role", style=discord.ButtonStyle.secondary, row=0)
    async def set_role(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.RoleSelect(placeholder="เลือก Blacksmith Role…")

        async def _cb(ix2: discord.Interaction):
            cfg = load_config(self.gid)
            cfg["blacksmith_role_id"] = ix2.data["values"][0]
            save_config(self.gid, cfg)
            await ix2.response.send_message("✅ บันทึกแล้ว", ephemeral=True)

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="📋 Review Channel", style=discord.ButtonStyle.secondary, row=0)
    async def set_channel(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Review Channel…",
            channel_types=[discord.ChannelType.text],
        )

        async def _cb(ix2: discord.Interaction):
            cfg = load_config(self.gid)
            cfg["admin_review_channel_id"] = ix2.data["values"][0]
            save_config(self.gid, cfg)
            await ix2.response.send_message("✅ บันทึกแล้ว", ephemeral=True)

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)


# ── /config command ────────────────────────────────────────────────────────────

@bot.tree.command(name="config", description="[Admin] ตั้งค่าทั้งหมดในที่เดียว")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_config(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    gid   = ix.guild_id
    view  = ConfigView(gid)
    embed = _page_embed(gid, "general")
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
