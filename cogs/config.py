"""Configuration panel — /config (6 pages, Embed + View only, no Components V2)."""
import discord
from discord import app_commands
from discord.ext import commands

from core.instance import bot
from core.shared import (
    t, load_config, save_config,
    select_options_from_list,
    format_currency,
    get_faction_names, get_all_rank_names,
    EMBED_COLOR,
)

TOTAL_PAGES = 6


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


# ── Modals ────────────────────────────────────────────────────────────────────

class CurrencyModal(discord.ui.Modal, title="Configure Currency"):
    f_name  = discord.ui.TextInput(label="Currency Name",        max_length=30,  default="Coins")
    f_emoji = discord.ui.TextInput(label="Emoji (optional)",     max_length=100, required=False)
    f_img   = discord.ui.TextInput(label="Image URL (optional)", max_length=300, required=False)

    def __init__(self, gid: int, parent: "ConfigMainView"):
        super().__init__()
        self.gid = gid
        self.parent = parent
        cfg = load_config(gid)
        self.f_name.default  = cfg.get("currency_name",  "Coins")
        self.f_emoji.default = cfg.get("currency_emoji", "")
        self.f_img.default   = cfg.get("currency_image",  "")

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["currency_name"]  = self.f_name.value.strip() or "Coins"
        cfg["currency_emoji"] = (self.f_emoji.value or "").strip()
        cfg["currency_image"] = (self.f_img.value or "").strip()
        save_config(self.gid, cfg)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class SquadSystemModal(discord.ui.Modal, title="Squad Settings"):
    f_max   = discord.ui.TextInput(label="Squad Max Members",                  max_length=5,  default="6")
    f_ranks = discord.ui.TextInput(label="Squad Creator Ranks (comma-sep)",   max_length=300, required=False)

    def __init__(self, gid: int, parent: "ConfigMainView"):
        super().__init__()
        self.gid = gid
        self.parent = parent
        cfg = load_config(gid)
        self.f_max.default   = str(cfg.get("squad_max_members", 6))
        self.f_ranks.default = ", ".join(cfg.get("squad_creator_ranks", []))

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        try:
            cfg["squad_max_members"] = max(1, int(self.f_max.value.strip()))
        except ValueError:
            cfg["squad_max_members"] = 6
        ranks_raw = self.f_ranks.value or ""
        cfg["squad_creator_ranks"] = [r.strip() for r in ranks_raw.split(",") if r.strip()]
        save_config(self.gid, cfg)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class InheritanceModal(discord.ui.Modal, title="Inheritance Races"):
    f_races = discord.ui.TextInput(
        label="Races (comma-separated)", max_length=500, required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, gid: int, parent: "ConfigMainView"):
        super().__init__()
        self.gid = gid
        self.parent = parent
        cfg = load_config(gid)
        self.f_races.default = ", ".join(cfg.get("inheritance_races", []))

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        raw = self.f_races.value or ""
        cfg["inheritance_races"] = [r.strip() for r in raw.split(",") if r.strip()]
        save_config(self.gid, cfg)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class MindlessItemsModal(discord.ui.Modal, title="Mindless Titan Items"):
    f_syringe = discord.ui.TextInput(label="Mindless Syringe Item Name", max_length=100, required=False)
    f_fluid   = discord.ui.TextInput(label="Mindless Fluid Item Name",   max_length=100, required=False)

    def __init__(self, gid: int, parent: "ConfigMainView"):
        super().__init__()
        self.gid = gid
        self.parent = parent
        cfg = load_config(gid)
        self.f_syringe.default = cfg.get("mindless_syringe_item", "")
        self.f_fluid.default   = cfg.get("mindless_fluid_item",   "")

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["mindless_syringe_item"] = (self.f_syringe.value or "").strip()
        cfg["mindless_fluid_item"]   = (self.f_fluid.value   or "").strip()
        save_config(self.gid, cfg)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


# ── Role mapping sub-view ─────────────────────────────────────────────────────

class RoleMapView(discord.ui.View):
    """Select a faction/rank/shifter/bloodline then pick a Discord role for it."""

    def __init__(self, gid: int, rtype: str, items: list, parent: "ConfigMainView"):
        super().__init__(timeout=300)
        self.gid    = gid
        self.rtype  = rtype
        self.items  = items
        self.parent = parent
        self.sel    = None
        self._build_items()

    def _build_items(self):
        self.clear_items()

        # Value selector
        val_sel = discord.ui.Select(
            placeholder=f"Select {self.rtype}",
            options=select_options_from_list(self.items, self.sel),
            custom_id="rm_val",
        )
        val_sel.callback = self._val_cb
        self.add_item(val_sel)

        # Role selector
        rs = discord.ui.RoleSelect(placeholder="Assign Discord role", custom_id="rm_role")
        rs.callback = self._role_cb
        self.add_item(rs)

        # Back button
        bk = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rm_bk",
        )
        bk.callback = self._back
        self.add_item(bk)

    def _make_embed(self) -> discord.Embed:
        cfg = load_config(self.gid)
        mappings = cfg.get("roles", {}).get(self.rtype, {})
        embed = discord.Embed(
            title=f"{self.rtype.title()} Role Mapping",
            color=EMBED_COLOR,
        )
        for item in self.items[:20]:
            rid = mappings.get(item)
            embed.add_field(
                name=item,
                value=f"<@&{rid}>" if rid else "*not set*",
                inline=True,
            )
        return embed

    async def _val_cb(self, ix: discord.Interaction):
        self.sel = ix.data["values"][0]
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _role_cb(self, ix: discord.Interaction):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["roles"].setdefault(self.rtype, {})[self.sel] = ix.data["values"][0]
        save_config(self.gid, cfg)
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _back(self, ix: discord.Interaction):
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


# ── Bloodline eligibility sub-view ────────────────────────────────────────────

class BloodlineEligibilityView(discord.ui.View):
    """Configure per-bloodline eligibility for mindless/shifter conversion."""

    def __init__(self, gid: int, mode: str, parent: "ConfigMainView"):
        super().__init__(timeout=300)
        self.gid    = gid
        # mode = "mindless" or "shifter"
        self.mode   = mode
        self.parent = parent
        self.sel_bl = None
        self._build_items()

    @property
    def _cfg_key(self) -> str:
        return "bloodline_mindless_eligible" if self.mode == "mindless" else "bloodline_shifter_eligible"

    def _all_bloodlines(self) -> list:
        cfg = load_config(self.gid)
        return cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])

    def _make_embed(self) -> discord.Embed:
        cfg      = load_config(self.gid)
        elig     = cfg.get(self._cfg_key, {})
        bls      = self._all_bloodlines()
        noun     = "Mindless Titan" if self.mode == "mindless" else "Shifter"
        embed    = discord.Embed(
            title=f"Bloodline → {noun} Eligibility",
            description="Configure which bloodlines can/cannot transform.",
            color=EMBED_COLOR,
        )
        for bl in bls:
            if bl in elig:
                val = "✅ Eligible" if elig[bl] else "❌ Ineligible"
            else:
                val = "*(default)*"
            embed.add_field(name=bl, value=val, inline=True)
        return embed

    def _build_items(self):
        self.clear_items()
        bls = self._all_bloodlines()

        bl_sel = discord.ui.Select(
            placeholder="Select bloodline",
            options=select_options_from_list(bls, self.sel_bl),
            custom_id="ble_bl",
        )
        bl_sel.callback = self._bl_cb
        self.add_item(bl_sel)

        yes_btn = discord.ui.Button(
            label="Set Eligible", style=discord.ButtonStyle.green, custom_id="ble_yes",
        )
        yes_btn.callback = self._set_yes
        self.add_item(yes_btn)

        no_btn = discord.ui.Button(
            label="Set Ineligible", style=discord.ButtonStyle.danger, custom_id="ble_no",
        )
        no_btn.callback = self._set_no
        self.add_item(no_btn)

        reset_btn = discord.ui.Button(
            label="Reset to Default", style=discord.ButtonStyle.secondary, custom_id="ble_reset",
        )
        reset_btn.callback = self._reset
        self.add_item(reset_btn)

        bk = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="ble_bk",
        )
        bk.callback = self._back
        self.add_item(bk)

    async def _bl_cb(self, ix: discord.Interaction):
        self.sel_bl = ix.data["values"][0]
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _set_yes(self, ix: discord.Interaction):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg.setdefault(self._cfg_key, {})[self.sel_bl] = True
        save_config(self.gid, cfg)
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _set_no(self, ix: discord.Interaction):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg.setdefault(self._cfg_key, {})[self.sel_bl] = False
        save_config(self.gid, cfg)
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _reset(self, ix: discord.Interaction):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg.setdefault(self._cfg_key, {}).pop(self.sel_bl, None)
        save_config(self.gid, cfg)
        self._build_items()
        await ix.response.edit_message(embed=self._make_embed(), view=self)

    async def _back(self, ix: discord.Interaction):
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


# ── Main Config View (6 pages) ────────────────────────────────────────────────

class ConfigMainView(discord.ui.View):
    def __init__(self, gid: int, guild: discord.Guild | None = None):
        super().__init__(timeout=300)
        self.gid   = gid
        self.guild = guild
        self.page  = 1

    # ── build returns (embed, view) — caller does edit_message ────────────────

    def _build(self) -> tuple[discord.Embed, "ConfigMainView"]:
        self.clear_items()
        builder = {
            1: self._p1_general,
            2: self._p2_channels,
            3: self._p3_roles,
            4: self._p4_systems,
            5: self._p5_char_creation,
            6: self._p6_bloodline_elig,
        }[self.page]
        embed = builder()
        self._add_nav()
        return embed, self

    # ── Navigation ────────────────────────────────────────────────────────────

    def _add_nav(self):
        prev = discord.ui.Button(
            label=t(self.gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_prev",
            disabled=(self.page == 1),
        )
        nxt = discord.ui.Button(
            label=t(self.gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_next",
            disabled=(self.page == TOTAL_PAGES),
        )
        prev.callback = self._prev
        nxt.callback  = self._next
        self.add_item(prev)
        self.add_item(nxt)

    async def _prev(self, ix: discord.Interaction):
        self.page = max(1, self.page - 1)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _next(self, ix: discord.Interaction):
        self.page = min(TOTAL_PAGES, self.page + 1)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    # ── Page header helper ────────────────────────────────────────────────────

    def _page_title(self, subtitle: str) -> str:
        return f"{t(self.gid, 'config_title')} — {t(self.gid, 'config_page', page=self.page, total=TOTAL_PAGES)} | {subtitle}"

    # ── Page 1 — General ──────────────────────────────────────────────────────

    def _p1_general(self) -> discord.Embed:
        gid = self.gid
        cfg = load_config(gid)
        lang_display = "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"
        cur_name  = cfg.get("currency_name",  "Coins")
        cur_emoji = cfg.get("currency_emoji", "")
        cur_img   = cfg.get("currency_image",  "") or "*none*"
        xp_status = "Enabled ✅" if cfg.get("xp_enabled", True) else "Disabled ❌"

        embed = discord.Embed(
            title=self._page_title(t(gid, "general_page")),
            color=EMBED_COLOR,
        )
        embed.add_field(name=t(gid, "language_section"), value=lang_display, inline=False)
        embed.add_field(
            name=t(gid, "currency_section"),
            value=f"Name: **{cur_name}** | Emoji: {cur_emoji or '*none*'} | Image: {cur_img}",
            inline=False,
        )
        embed.add_field(name="XP System", value=xp_status, inline=False)

        # Language buttons
        th_btn = discord.ui.Button(label="🇹🇭 Thai",    style=discord.ButtonStyle.primary,   custom_id="cfg_th")
        en_btn = discord.ui.Button(label="🇬🇧 English", style=discord.ButtonStyle.primary,   custom_id="cfg_en")
        th_btn.callback = self._set_th
        en_btn.callback = self._set_en
        self.add_item(th_btn)
        self.add_item(en_btn)

        # Currency button
        cc_btn = discord.ui.Button(
            label=t(gid, "configure_btn") + " Currency",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_curr",
        )
        cc_btn.callback = self._currency
        self.add_item(cc_btn)

        # XP toggle
        xp_btn = discord.ui.Button(
            label="Toggle XP",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_xp",
        )
        xp_btn.callback = self._toggle_xp
        self.add_item(xp_btn)

        return embed

    async def _set_th(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["language"] = "th"
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _set_en(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["language"] = "en"
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _currency(self, ix: discord.Interaction):
        await ix.response.send_modal(CurrencyModal(self.gid, self))

    async def _toggle_xp(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["xp_enabled"] = not cfg.get("xp_enabled", True)
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    # ── Page 2 — Channels ─────────────────────────────────────────────────────

    def _p2_channels(self) -> discord.Embed:
        gid = self.gid
        cfg = load_config(gid)

        ann_ids  = cfg.get("announcement_channels", [])
        ann_disp = (", ".join(f"<#{c}>" for c in ann_ids[:5]) + ("…" if len(ann_ids) > 5 else "")) or "*None*"

        ann_role_ids = cfg.get("announcement_permitted_roles", [])
        ann_roles    = (", ".join(f"<@&{r}>" for r in ann_role_ids[:6])) or "*Admin only*"

        err_ch = cfg.get("error_log_channel")
        err_disp = f"<#{err_ch}>" if err_ch else "*None*"

        embed = discord.Embed(
            title=self._page_title("📡 Channels"),
            color=EMBED_COLOR,
        )
        embed.add_field(name=t(gid, "ann_channels_section"), value=ann_disp,  inline=False)
        embed.add_field(name=t(gid, "ann_permitted_roles_section"), value=ann_roles, inline=False)
        embed.add_field(name="Error Log Channel", value=err_disp, inline=False)

        # Announcement channel select (no channel_types filter — accept ALL types)
        ann_ch_sel = discord.ui.ChannelSelect(
            placeholder="Set Announcement Channel(s)",
            custom_id="cfg_ann_ch",
            min_values=1,
            max_values=10,
        )
        ann_ch_sel.callback = self._set_ann_channels
        self.add_item(ann_ch_sel)

        # Announcement roles select
        ann_role_sel = discord.ui.RoleSelect(
            placeholder="Set Announcement Permitted Roles",
            custom_id="cfg_ann_roles",
            min_values=0,
            max_values=10,
        )
        ann_role_sel.callback = self._set_ann_roles
        self.add_item(ann_role_sel)

        # Error log channel select (no filter)
        err_ch_sel = discord.ui.ChannelSelect(
            placeholder="Set Error Log Channel",
            custom_id="cfg_err_ch",
        )
        err_ch_sel.callback = self._set_err_channel
        self.add_item(err_ch_sel)

        return embed

    async def _set_ann_channels(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["announcement_channels"] = [str(v) for v in ix.data["values"]]
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _set_ann_roles(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["announcement_permitted_roles"] = [str(v) for v in ix.data["values"]]
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _set_err_channel(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        vals = ix.data.get("values", [])
        cfg["error_log_channel"] = str(vals[0]) if vals else None
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    # ── Page 3 — Roles ────────────────────────────────────────────────────────

    def _p3_roles(self) -> discord.Embed:
        gid      = self.gid
        cfg      = load_config(gid)
        factions = get_faction_names(gid)
        ranks    = get_all_rank_names(gid)
        shifters = cfg.get("shifters", [])
        bls      = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])

        def _preview(rtype, items):
            mappings = cfg.get("roles", {}).get(rtype, {})
            lines = []
            for item in items[:4]:
                rid = mappings.get(item)
                lines.append(f"**{item}** → {'<@&'+str(rid)+'>' if rid else '*not set*'}")
            if len(items) > 4:
                lines.append(f"*…+{len(items)-4} more*")
            return "\n".join(lines) or "*None*"

        embed = discord.Embed(
            title=self._page_title(t(gid, "roles_page")),
            color=EMBED_COLOR,
        )
        embed.add_field(name="Faction Roles",   value=_preview("faction",   factions), inline=False)
        embed.add_field(name="Rank Roles",      value=_preview("rank",      ranks),    inline=False)
        embed.add_field(name="Shifter Roles",   value=_preview("shifter",   shifters), inline=False)
        embed.add_field(name="Bloodline Roles", value=_preview("bloodline", bls),      inline=False)

        def _role_btn(label, cid, rtype, items):
            b = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=cid)
            async def _cb(ix: discord.Interaction, _rt=rtype, _items=items):
                view = RoleMapView(self.gid, _rt, _items, self)
                await ix.response.edit_message(embed=view._make_embed(), view=view)
            b.callback = _cb
            return b

        self.add_item(_role_btn("Faction Roles",   "cfg_rf", "faction",   factions))
        self.add_item(_role_btn("Rank Roles",      "cfg_rr", "rank",      ranks))
        self.add_item(_role_btn("Shifter Roles",   "cfg_rs", "shifter",   shifters))
        self.add_item(_role_btn("Bloodline Roles", "cfg_rb", "bloodline", bls))

        return embed

    # ── Page 4 — Systems ──────────────────────────────────────────────────────

    def _p4_systems(self) -> discord.Embed:
        gid = self.gid
        cfg = load_config(gid)

        squad_max    = cfg.get("squad_max_members", 6)
        squad_ranks  = ", ".join(cfg.get("squad_creator_ranks", [])) or "*None*"
        inh_races    = ", ".join(cfg.get("inheritance_races", [])) or "*None*"
        syringe_item = cfg.get("mindless_syringe_item", "") or "*not set*"
        fluid_item   = cfg.get("mindless_fluid_item",   "") or "*not set*"

        embed = discord.Embed(
            title=self._page_title("⚙️ Systems"),
            color=EMBED_COLOR,
        )
        embed.add_field(name="Squad Max Members",    value=str(squad_max),   inline=True)
        embed.add_field(name="Squad Creator Ranks",  value=squad_ranks,      inline=False)
        embed.add_field(name="Inheritance Races",    value=inh_races,        inline=False)
        embed.add_field(name="Mindless Syringe Item",value=syringe_item,     inline=True)
        embed.add_field(name="Mindless Fluid Item",  value=fluid_item,       inline=True)

        squad_btn = discord.ui.Button(
            label="Configure Squad Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_squad",
        )
        squad_btn.callback = self._squad_modal

        inh_btn = discord.ui.Button(
            label="Configure Inheritance Races",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_inh",
        )
        inh_btn.callback = self._inh_modal

        ml_btn = discord.ui.Button(
            label="Configure Mindless Items",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_ml",
        )
        ml_btn.callback = self._mindless_modal

        self.add_item(squad_btn)
        self.add_item(inh_btn)
        self.add_item(ml_btn)
        return embed

    async def _squad_modal(self, ix: discord.Interaction):
        await ix.response.send_modal(SquadSystemModal(self.gid, self))

    async def _inh_modal(self, ix: discord.Interaction):
        await ix.response.send_modal(InheritanceModal(self.gid, self))

    async def _mindless_modal(self, ix: discord.Interaction):
        await ix.response.send_modal(MindlessItemsModal(self.gid, self))

    # ── Page 5 — Character Creation ───────────────────────────────────────────

    def _p5_char_creation(self) -> discord.Embed:
        gid = self.gid
        cfg = load_config(gid)
        role_id   = cfg.get("character_creation_role")
        role_disp = f"<@&{role_id}>" if role_id else "*Anyone can create a character*"

        embed = discord.Embed(
            title=self._page_title("🎭 Character Creation"),
            color=EMBED_COLOR,
        )
        embed.add_field(name="Required Role", value=role_disp, inline=False)
        embed.set_footer(text="If a role is set, only members with that role may create a character.")

        role_sel = discord.ui.RoleSelect(
            placeholder="Set Character Creation Required Role",
            custom_id="cfg_cc_role",
        )
        role_sel.callback = self._set_cc_role
        self.add_item(role_sel)

        clear_btn = discord.ui.Button(
            label="Clear Required Role",
            style=discord.ButtonStyle.danger,
            custom_id="cfg_cc_clear",
        )
        clear_btn.callback = self._clear_cc_role
        self.add_item(clear_btn)

        return embed

    async def _set_cc_role(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        vals = ix.data.get("values", [])
        cfg["character_creation_role"] = str(vals[0]) if vals else None
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _clear_cc_role(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["character_creation_role"] = None
        save_config(self.gid, cfg)
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    # ── Page 6 — Bloodline Eligibility ────────────────────────────────────────

    def _p6_bloodline_elig(self) -> discord.Embed:
        gid = self.gid
        cfg = load_config(gid)

        m_elig = cfg.get("bloodline_mindless_eligible", {})
        s_elig = cfg.get("bloodline_shifter_eligible",  {})
        bls    = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])

        def _elig_summary(elig_dict):
            if not bls:
                return "*No bloodlines configured*"
            lines = []
            for bl in bls:
                if bl in elig_dict:
                    mark = "✅" if elig_dict[bl] else "❌"
                else:
                    mark = "*(default)*"
                lines.append(f"{mark} {bl}")
            return "\n".join(lines[:20]) or "*None*"

        embed = discord.Embed(
            title=self._page_title("🧬 Bloodline Eligibility"),
            color=EMBED_COLOR,
        )
        embed.add_field(
            name="Mindless Titan Eligibility",
            value=_elig_summary(m_elig),
            inline=True,
        )
        embed.add_field(
            name="Shifter Eligibility",
            value=_elig_summary(s_elig),
            inline=True,
        )

        mindless_btn = discord.ui.Button(
            label="Configure Mindless Eligibility",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_bl_ml",
        )
        mindless_btn.callback = self._open_mindless_elig

        shifter_btn = discord.ui.Button(
            label="Configure Shifter Eligibility",
            style=discord.ButtonStyle.secondary,
            custom_id="cfg_bl_sh",
        )
        shifter_btn.callback = self._open_shifter_elig

        self.add_item(mindless_btn)
        self.add_item(shifter_btn)
        return embed

    async def _open_mindless_elig(self, ix: discord.Interaction):
        view = BloodlineEligibilityView(self.gid, "mindless", self)
        await ix.response.edit_message(embed=view._make_embed(), view=view)

    async def _open_shifter_elig(self, ix: discord.Interaction):
        view = BloodlineEligibilityView(self.gid, "shifter", self)
        await ix.response.edit_message(embed=view._make_embed(), view=view)


# ── /config command ───────────────────────────────────────────────────────────

@bot.tree.command(
    name="config",
    description="Configure bot settings (admin only)",
    description_localizations={"th": "ตั้งค่าบอท (สำหรับแอดมิน)"},
)
@_is_admin()
async def config_cmd(ix: discord.Interaction):
    view = ConfigMainView(ix.guild_id, ix.guild)
    embed, view = view._build()
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@config_cmd.error
async def config_error(ix: discord.Interaction, error):
    if not ix.response.is_done():
        await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)


# ── Cog loader ────────────────────────────────────────────────────────────────

class ConfigCog(commands.Cog):
    pass


async def setup(b: commands.Bot):
    await b.add_cog(ConfigCog(b))
