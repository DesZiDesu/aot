"""Admin panel — roles, lists, bloodlines, shifter access, language."""
import time as _time

import discord
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

from core.instance import bot
from core.shared import (
    t,
    load_config,
    save_config,
    load_players,
    save_players,
    select_options_from_list,
    send_dm,
    EMBED_COLOR,
)

# ── Permission check ──────────────────────────────────────────────────────────

def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild:
            return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (
            m.guild_permissions.administrator or m.guild_permissions.manage_guild
        )
    return app_commands.check(pred)


# ── DM helper ─────────────────────────────────────────────────────────────────

async def _dm(user, text: str):
    """Send a plain-text DM; silently ignore failures."""
    try:
        await send_dm(user, content=text)
    except Exception:
        pass


# ── Embed builders ────────────────────────────────────────────────────────────

def _main_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    lang = "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"
    factions = cfg.get("factions", [])
    fac_str = ", ".join(factions[:5]) + ("…" if len(factions) > 5 else "")
    embed = discord.Embed(
        title=t(gid, "admin_title"),
        description=t(gid, "admin_desc"),
        color=EMBED_COLOR,
    )
    embed.add_field(name="Factions", value=fac_str or "—", inline=True)
    embed.add_field(name="Ranks", value=", ".join(cfg.get("ranks", [])[:5]) or "—", inline=True)
    embed.add_field(
        name="Bloodlines",
        value=(
            f"Common: {', '.join(cfg.get('bloodlines_common', []))}\n"
            f"Special: {', '.join(cfg.get('bloodlines_special', []))}"
        ),
        inline=False,
    )
    embed.add_field(name="Language", value=lang, inline=True)
    return embed


def _role_map_embed(gid: int, rtype: str) -> discord.Embed:
    cfg = load_config(gid)
    mappings = cfg["roles"].get(rtype, {})
    items_map = {
        "faction":   cfg.get("factions", []),
        "rank":      cfg.get("ranks", []),
        "shifter":   cfg.get("shifters", []),
        "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", []),
    }
    items = items_map.get(rtype, [])
    lines = [
        f"**{i}** — {'<@&' + str(mappings[i]) + '>' if i in mappings else '*not set*'}"
        for i in items
    ]
    embed = discord.Embed(
        title=f"{rtype.title()} Role Mappings",
        description="\n".join(lines) if lines else "—",
        color=EMBED_COLOR,
    )
    return embed


def _list_embed(gid: int, key: str) -> discord.Embed:
    items = load_config(gid).get(key, [])
    embed = discord.Embed(
        title=f"Manage {key.title()}",
        description="\n".join(f"- {i}" for i in items) if items else "*None*",
        color=EMBED_COLOR,
    )
    return embed


def _bl_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    common  = "\n".join(f"  - {b}" for b in cfg.get("bloodlines_common",  [])) or "  *None*"
    special = "\n".join(f"  - {b}" for b in cfg.get("bloodlines_special", [])) or "  *None*"
    embed = discord.Embed(title="Manage Bloodlines", color=EMBED_COLOR)
    embed.add_field(name="Common", value=common, inline=False)
    embed.add_field(name="Special", value=special, inline=False)
    return embed


def _grant_bl_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    acc = cfg.get("special_access", {})
    grants = "\n".join(
        f"<@{uid}>: {', '.join(bls)}" for uid, bls in acc.items()
    ) or "*None*"
    embed = discord.Embed(
        title=t(gid, "grant_bloodline_btn"),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Special Bloodlines",
        value=", ".join(cfg.get("bloodlines_special", [])) or "—",
        inline=False,
    )
    embed.add_field(name="Current Grants", value=grants, inline=False)
    return embed


def _grant_sh_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    acc = cfg.get("shifter_access", [])
    users = "\n".join(f"<@{uid}>" for uid in acc) or "*None*"
    embed = discord.Embed(
        title=t(gid, "grant_shifter_btn"),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Available Titans",
        value=", ".join(cfg.get("shifters", [])) or "—",
        inline=False,
    )
    embed.add_field(name="Users with Access", value=users, inline=False)
    return embed


def _tracker_embed(gid: int, guild) -> discord.Embed:
    players = load_players(gid)
    lines = []
    for uid, p in players.items():
        powers = p.get("titan_powers", [])
        if not powers:
            continue
        member = guild.get_member(int(uid)) if guild else None
        name = member.display_name if member else f"<@{uid}>"
        exp = powers[0].get("expires_at", 0)
        secs = max(0, int(exp - _time.time()))
        days = secs // 86400
        titan_names = ", ".join(pw["titan"] for pw in powers)
        lines.append(f"**{name}** — {titan_names} — {days}d left")
    embed = discord.Embed(
        title=t(gid, "shifter_tracker_btn"),
        description="\n".join(lines) if lines else "*No active shifters*",
        color=EMBED_COLOR,
    )
    return embed


def _lang_embed(gid: int) -> discord.Embed:
    cfg = load_config(gid)
    lang = cfg.get("language", "th")
    embed = discord.Embed(
        title=t(gid, "language_btn"),
        description=f"Current: {'Thai 🇹🇭' if lang == 'th' else 'English 🇬🇧'}",
        color=EMBED_COLOR,
    )
    return embed


# ── Admin main view ───────────────────────────────────────────────────────────

class AdminMainView(View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _btn(label_key, cb, cid, style=discord.ButtonStyle.secondary, row=0):
            b = Button(label=t(gid, label_key), style=style, custom_id=cid, row=row)
            b.callback = cb
            return b

        # Row 0 — Role mappings
        self.add_item(_btn("faction_roles_btn",   self._make_role_cb("faction"),   "adm_rfac",   row=0))
        self.add_item(_btn("rank_roles_btn",       self._make_role_cb("rank"),      "adm_rrank",  row=0))
        self.add_item(_btn("shifter_roles_btn",    self._make_role_cb("shifter"),   "adm_rshift", row=0))
        self.add_item(_btn("bloodline_roles_btn",  self._make_role_cb("bloodline"), "adm_rbl",    row=0))

        # Row 1 — Manage lists
        self.add_item(_btn("manage_factions_btn",    self._make_list_cb("factions"),   "adm_mfac",   row=1))
        self.add_item(_btn("manage_ranks_btn",        self._make_list_cb("ranks"),      "adm_mrank",  row=1))
        self.add_item(_btn("manage_shifters_btn",     self._make_list_cb("shifters"),   "adm_mshift", row=1))
        self.add_item(_btn("manage_bloodlines_btn",   self._bloodlines,                 "adm_mbl",    row=1))

        # Row 2 — Grant & tracker
        self.add_item(_btn("grant_bloodline_btn",  self._grant_bl,  "adm_gbl",   row=2))
        self.add_item(_btn("grant_shifter_btn",    self._grant_sh,  "adm_gsh",   row=2))
        self.add_item(_btn("shifter_tracker_btn",  self._tracker,   "adm_track", row=2))
        self.add_item(_btn("language_btn",         self._language,  "adm_lang",  row=2))

        # Row 3 — Done
        done = Button(label=t(gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="adm_done", row=3)
        done.callback = self._done
        self.add_item(done)

    def _make_role_cb(self, rtype: str):
        async def cb(ix: discord.Interaction):
            v = RoleMappingView(self.gid, rtype, self)
            await ix.response.edit_message(embed=_role_map_embed(self.gid, rtype), view=v)
        return cb

    def _make_list_cb(self, key: str):
        async def cb(ix: discord.Interaction):
            v = ManageListView(self.gid, key, self)
            await ix.response.edit_message(embed=_list_embed(self.gid, key), view=v)
        return cb

    async def _bloodlines(self, ix: discord.Interaction):
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=ManageBloodlinesView(self.gid, self))

    async def _grant_bl(self, ix: discord.Interaction):
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=GrantBloodlineView(self.gid, self))

    async def _grant_sh(self, ix: discord.Interaction):
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=GrantShifterView(self.gid, self))

    async def _tracker(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=_tracker_embed(self.gid, ix.guild),
            view=ShifterTrackerView(self.gid, self, ix.guild),
        )

    async def _language(self, ix: discord.Interaction):
        await ix.response.edit_message(embed=_lang_embed(self.gid), view=LanguageView(self.gid, self))

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=self)


# ── Role mapping ──────────────────────────────────────────────────────────────

class RoleMappingView(View):
    def __init__(self, gid: int, rtype: str, parent: AdminMainView):
        super().__init__(timeout=300)
        self.gid = gid
        self.rtype = rtype
        self.parent = parent
        self.sel = None
        self._build()

    def _items(self):
        cfg = load_config(self.gid)
        return {
            "faction":   cfg.get("factions", []),
            "rank":      cfg.get("ranks", []),
            "shifter":   cfg.get("shifters", []),
            "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", []),
        }[self.rtype]

    def _build(self):
        self.clear_items()
        val_sel = Select(
            placeholder=f"Select {self.rtype}",
            options=select_options_from_list(self._items(), self.sel),
            custom_id="rm_val",
            row=0,
        )
        val_sel.callback = self._val_cb
        self.add_item(val_sel)

        rs = discord.ui.RoleSelect(placeholder="Assign Discord role", custom_id="rm_role", row=1)
        rs.callback = self._role_cb
        self.add_item(rs)

        back = Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rm_back",
            row=2,
        )
        back.callback = self._back
        self.add_item(back)

    async def _val_cb(self, ix: discord.Interaction):
        self.sel = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(embed=_role_map_embed(self.gid, self.rtype), view=self)

    async def _role_cb(self, ix: discord.Interaction):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["roles"].setdefault(self.rtype, {})[self.sel] = ix.data["values"][0]
        save_config(self.gid, cfg)
        self._build()
        await ix.response.edit_message(embed=_role_map_embed(self.gid, self.rtype), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


# ── Manage list ───────────────────────────────────────────────────────────────

class _AddModal(Modal):
    val = TextInput(label="Name", max_length=60)

    def __init__(self, gid: int, key: str, parent):
        super().__init__(title=f"Add to {key.title()}")
        self.gid = gid
        self.key = key
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        v = self.val.value.strip()
        if v and v not in cfg.get(self.key, []):
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)


class ManageListView(View):
    def __init__(self, gid: int, key: str, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.key = key
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        add  = Button(label="Add",    style=discord.ButtonStyle.green,     custom_id="ml_add",    row=0)
        rem  = Button(label="Remove", style=discord.ButtonStyle.danger,    custom_id="ml_remove", row=0)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="ml_back", row=1)
        add.callback  = self._add
        rem.callback  = self._remove
        back.callback = self._back
        self.add_item(add)
        self.add_item(rem)
        self.add_item(back)

    async def _add(self, ix: discord.Interaction):
        await ix.response.send_modal(_AddModal(self.gid, self.key, self))

    async def _remove(self, ix: discord.Interaction):
        items = load_config(self.gid).get(self.key, [])
        if not items:
            await ix.response.send_message("Nothing to remove.", ephemeral=True)
            return
        await ix.response.edit_message(
            embed=discord.Embed(
                title=f"Remove from {self.key.title()}",
                description="Select an item to remove:",
                color=EMBED_COLOR,
            ),
            view=_RemoveSelectView(self.gid, self.key, items, self),
        )

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


class _RemoveSelectView(View):
    def __init__(self, gid: int, key: str, items: list, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.key = key
        self.parent = parent

        sel = Select(
            placeholder="Select to remove",
            options=select_options_from_list(items),
            custom_id="rsv_sel",
            row=0,
        )
        sel.callback = self._cb
        self.add_item(sel)

        back = Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rsv_back",
            row=1,
        )
        back.callback = self._back
        self.add_item(back)

    async def _cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            lst = cfg.get(self.key, [])
            if v in lst:
                lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)


# ── Bloodlines ────────────────────────────────────────────────────────────────

class _BlModal(Modal):
    name = TextInput(label="Bloodline Name", max_length=60)

    def __init__(self, gid: int, key: str, parent):
        super().__init__(title=f"Add {'Special' if 'special' in key else 'Common'} Bloodline")
        self.gid = gid
        self.key = key
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        v = self.name.value.strip()
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if v and v not in all_bl:
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)


class ManageBloodlinesView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        ac  = Button(label="Add Common",  style=discord.ButtonStyle.green,     custom_id="mbl_ac",  row=0)
        asc = Button(label="Add Special", style=discord.ButtonStyle.green,     custom_id="mbl_as",  row=0)
        rm  = Button(label="Remove",      style=discord.ButtonStyle.danger,    custom_id="mbl_rm",  row=0)
        bk  = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="mbl_bk", row=1)
        ac.callback  = self._make_add_cb("bloodlines_common")
        asc.callback = self._make_add_cb("bloodlines_special")
        rm.callback  = self._remove
        bk.callback  = self._back
        self.add_item(ac)
        self.add_item(asc)
        self.add_item(rm)
        self.add_item(bk)

    def _make_add_cb(self, key: str):
        async def cb(ix: discord.Interaction):
            await ix.response.send_modal(_BlModal(self.gid, key, self))
        return cb

    async def _remove(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if not all_bl:
            await ix.response.send_message("No bloodlines to remove.", ephemeral=True)
            return
        await ix.response.edit_message(
            embed=discord.Embed(
                title="Remove Bloodline",
                description="Select a bloodline to remove:",
                color=EMBED_COLOR,
            ),
            view=_RemoveBlView(self.gid, all_bl, self),
        )

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


class _RemoveBlView(View):
    def __init__(self, gid: int, items: list, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent

        sel = Select(
            placeholder="Select bloodline to remove",
            options=select_options_from_list(items),
            custom_id="rbl_sel",
            row=0,
        )
        sel.callback = self._cb
        self.add_item(sel)

        back = Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rbl_back",
            row=1,
        )
        back.callback = self._back
        self.add_item(back)

    async def _cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            for k in ("bloodlines_common", "bloodlines_special"):
                lst = cfg.get(k, [])
                if v in lst:
                    lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)


# ── Grant special bloodline ───────────────────────────────────────────────────

class GrantBloodlineView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.sel_bl: str | None = None
        self.sel_users: list = []
        self.sel_role: str | None = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])

        sel = Select(
            placeholder="Choose bloodline",
            options=select_options_from_list(special, self.sel_bl),
            custom_id="gbl_sel",
            row=0,
        )
        sel.callback = self._bl_cb
        self.add_item(sel)

        us = discord.ui.UserSelect(
            placeholder="Select users",
            min_values=1,
            max_values=25,
            custom_id="gbl_us",
            row=1,
        )
        us.callback = self._user_cb
        self.add_item(us)

        rs = discord.ui.RoleSelect(
            placeholder="Grant via role",
            custom_id="gbl_rs",
            row=2,
        )
        rs.callback = self._role_cb
        self.add_item(rs)

        gu = Button(label="Grant Users",    style=discord.ButtonStyle.green,     custom_id="gbl_gu", row=3)
        gr = Button(label="Grant via Role", style=discord.ButtonStyle.green,     custom_id="gbl_gr", row=3)
        rv = Button(label="Revoke",         style=discord.ButtonStyle.danger,    custom_id="gbl_rv", row=3)
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gbl_bk", row=3)
        gu.callback = self._grant_users
        gr.callback = self._grant_role
        rv.callback = self._revoke
        bk.callback = self._back
        self.add_item(gu)
        self.add_item(gr)
        self.add_item(rv)
        self.add_item(bk)

    async def _bl_cb(self, ix: discord.Interaction):
        self.sel_bl = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _user_cb(self, ix: discord.Interaction):
        self.sel_users = ix.data["values"]
        await ix.response.defer()

    async def _role_cb(self, ix: discord.Interaction):
        self.sel_role = ix.data["values"][0] if ix.data["values"] else None
        await ix.response.defer()

    async def _grant_users(self, ix: discord.Interaction):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        acc = cfg.setdefault("special_access", {})
        newly_granted = []
        for uid in self.sel_users:
            if self.sel_bl not in acc.get(uid, []):
                acc.setdefault(uid, []).append(self.sel_bl)
                newly_granted.append(uid)
        save_config(self.gid, cfg)
        for uid in newly_granted:
            try:
                user = await bot.fetch_user(int(uid))
                await _dm(user, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _grant_role(self, ix: discord.Interaction):
        if not self.sel_bl or not self.sel_role:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        role = ix.guild.get_role(int(self.sel_role))
        if not role:
            await ix.response.send_message("Role not found.", ephemeral=True)
            return
        cfg = load_config(self.gid)
        acc = cfg.setdefault("special_access", {})
        newly_granted = []
        for m in role.members:
            if self.sel_bl not in acc.get(str(m.id), []):
                acc.setdefault(str(m.id), []).append(self.sel_bl)
                newly_granted.append(m)
        save_config(self.gid, cfg)
        for m in newly_granted:
            await _dm(m, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
        self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _revoke(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(
                title="Revoke Special Bloodline",
                description="Select users and bloodline to revoke:",
                color=EMBED_COLOR,
            ),
            view=RevokeBlView(self.gid, self),
        )

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


class RevokeBlView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.sel_users: list = []
        self.sel_bl: str | None = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])

        us = discord.ui.UserSelect(
            placeholder="Select users",
            min_values=1,
            max_values=25,
            custom_id="rvbl_us",
            row=0,
        )
        us.callback = self._user_cb
        self.add_item(us)

        sel = Select(
            placeholder="Bloodline to revoke",
            options=select_options_from_list(special, self.sel_bl),
            custom_id="rvbl_sel",
            row=1,
        )
        sel.callback = self._bl_cb
        self.add_item(sel)

        rv = Button(label="Revoke",  style=discord.ButtonStyle.danger,    custom_id="rvbl_do", row=2)
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rvbl_bk", row=2)
        rv.callback = self._do
        bk.callback = self._back
        self.add_item(rv)
        self.add_item(bk)

    async def _user_cb(self, ix: discord.Interaction):
        self.sel_users = ix.data["values"]
        await ix.response.defer()

    async def _bl_cb(self, ix: discord.Interaction):
        self.sel_bl = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _do(self, ix: discord.Interaction):
        if not self.sel_users or not self.sel_bl:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        acc = cfg.get("special_access", {})
        for uid in self.sel_users:
            lst = acc.get(uid, [])
            if self.sel_bl in lst:
                lst.remove(self.sel_bl)
            if not lst:
                acc.pop(uid, None)
        save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self.parent)


# ── Grant shifter access ──────────────────────────────────────────────────────

class GrantShifterView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.sel_titan: str | None = None
        self.sel_users: list = []
        self._build()

    def _build(self):
        self.clear_items()
        titans = load_config(self.gid).get("shifters", [])

        titan_sel = Select(
            placeholder="Select Titan to assign",
            options=select_options_from_list(titans, self.sel_titan),
            custom_id="gsh_tsel",
            row=0,
        )
        titan_sel.callback = self._titan_cb
        self.add_item(titan_sel)

        us = discord.ui.UserSelect(
            placeholder="Select users to grant",
            min_values=1,
            max_values=25,
            custom_id="gsh_us",
            row=1,
        )
        us.callback = self._user_cb
        self.add_item(us)

        gu = Button(label="Grant",        style=discord.ButtonStyle.green,     custom_id="gsh_gu", row=2)
        rv = Button(label="Revoke Users", style=discord.ButtonStyle.danger,    custom_id="gsh_rv", row=2)
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gsh_bk", row=2)
        gu.callback = self._grant_u
        rv.callback = self._revoke
        bk.callback = self._back
        self.add_item(gu)
        self.add_item(rv)
        self.add_item(bk)

    async def _titan_cb(self, ix: discord.Interaction):
        self.sel_titan = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self)

    async def _user_cb(self, ix: discord.Interaction):
        self.sel_users = ix.data["values"]
        await ix.response.defer()

    async def _grant_u(self, ix: discord.Interaction):
        if not self.sel_titan or self.sel_titan == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        acc = cfg.setdefault("shifter_access", [])
        players = load_players(self.gid)
        titan_days = cfg.get("titan_time_days", 4745)
        now = _time.time()
        for uid in self.sel_users:
            if uid not in acc:
                acc.append(uid)
            player = players.setdefault(uid, {})
            new_power = {
                "titan":       self.sel_titan,
                "acquired_at": now,
                "expires_at":  now + titan_days * 86400,
                "abilities":   [],
            }
            player.setdefault("titan_powers", []).append(new_power)
            players[uid] = player
        save_config(self.gid, cfg)
        save_players(self.gid, players)
        for uid in self.sel_users:
            try:
                user = await bot.fetch_user(int(uid))
                await _dm(user, t(self.gid, "got_titan_dm", titan=self.sel_titan))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self)

    async def _revoke(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(
                title="Revoke Shifter Access",
                description="Select users to revoke shifter access from:",
                color=EMBED_COLOR,
            ),
            view=RevokeShView(self.gid, self),
        )

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


class RevokeShView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.sel_users: list = []

        us = discord.ui.UserSelect(
            placeholder="Select users",
            min_values=1,
            max_values=25,
            custom_id="rvsh_us",
            row=0,
        )
        us.callback = self._uc
        self.add_item(us)

        rv = Button(label="Revoke",  style=discord.ButtonStyle.danger,    custom_id="rvsh_do", row=1)
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rvsh_bk", row=1)
        rv.callback = self._do
        bk.callback = self._back
        self.add_item(rv)
        self.add_item(bk)

    async def _uc(self, ix: discord.Interaction):
        self.sel_users = ix.data["values"]
        await ix.response.defer()

    async def _do(self, ix: discord.Interaction):
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True)
            return
        cfg = load_config(self.gid)
        acc = cfg.get("shifter_access", [])
        players = load_players(self.gid)
        for uid in self.sel_users:
            if uid in acc:
                acc.remove(uid)
            player = players.get(uid, {})
            player["titan_powers"] = []
            player["transformed"]  = False
            players[uid] = player
        save_config(self.gid, cfg)
        save_players(self.gid, players)
        self.parent._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self.parent)


# ── Shifter tracker ───────────────────────────────────────────────────────────

class ShifterTrackerView(View):
    def __init__(self, gid: int, parent, guild=None):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        bk = Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="tr_bk",
            row=0,
        )
        st = Button(
            label=t(self.gid, "set_shifter_time_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="tr_st",
            row=0,
        )
        bk.callback = self._back
        st.callback = self._set_time
        self.add_item(bk)
        self.add_item(st)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)

    async def _set_time(self, ix: discord.Interaction):
        await ix.response.send_modal(SetShifterTimeModal(self.gid, self))


class SetShifterTimeModal(Modal, title="Set Shifter Time"):
    uid_input  = TextInput(label="User ID",         max_length=25)
    days_input = TextInput(label="Days remaining",  max_length=10)

    def __init__(self, gid: int, parent: ShifterTrackerView):
        super().__init__()
        self.gid = gid
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid  = self.uid_input.value.strip()
            days = int(self.days_input.value.strip())
            players = load_players(self.gid)
            p = players.get(uid, {})
            for pw in p.get("titan_powers", []):
                pw["expires_at"] = _time.time() + days * 86400
            save_players(self.gid, players)
            self.parent.guild = ix.guild
            self.parent._build()
            await ix.response.edit_message(
                embed=_tracker_embed(self.gid, ix.guild),
                view=self.parent,
            )
        except Exception as e:
            await ix.response.send_message(f"Error: {e}", ephemeral=True)


# ── Language ──────────────────────────────────────────────────────────────────

class LanguageView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        th = Button(label=t(self.gid, "language_th"), style=discord.ButtonStyle.primary,   custom_id="lang_th", row=0)
        en = Button(label=t(self.gid, "language_en"), style=discord.ButtonStyle.primary,   custom_id="lang_en", row=0)
        bk = Button(label=t(self.gid, "back_btn"),    style=discord.ButtonStyle.secondary, custom_id="lang_bk", row=1)
        th.callback = self._make_cb("th")
        en.callback = self._make_cb("en")
        bk.callback = self._back
        self.add_item(th)
        self.add_item(en)
        self.add_item(bk)

    def _make_cb(self, lang: str):
        async def cb(ix: discord.Interaction):
            cfg = load_config(self.gid)
            cfg["language"] = lang
            save_config(self.gid, cfg)
            self._build()
            await ix.response.edit_message(embed=_lang_embed(self.gid), view=self)
        return cb

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_main_embed(self.gid), view=self.parent)


# ── /admin command ────────────────────────────────────────────────────────────

@bot.tree.command(
    name="admin",
    description="Admin control panel",
    description_localizations={"th": "แผงควบคุมแอดมิน"},
)
@is_admin()
async def admin_cmd(ix: discord.Interaction):
    gid = ix.guild_id
    view = AdminMainView(gid)
    await ix.response.send_message(embed=_main_embed(gid), view=view, ephemeral=True)


@admin_cmd.error
async def admin_error(ix: discord.Interaction, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
