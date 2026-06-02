"""Admin panel — roles, lists, bloodlines, shifter access, language, player management."""
import discord
from discord import app_commands

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, save_config, load_players, save_players,
    select_options_from_list, cv2_dm, log_event, assign_roles, remove_old_roles,
)


def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


def _check_admin(ix: discord.Interaction) -> bool:
    m = ix.guild.get_member(ix.user.id) if ix.guild else None
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild))


# ── Embed helpers ─────────────────────────────────────────────────────────────

def _admin_embed(gid):
    cfg = load_config(gid)
    lang = "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"
    fac_str = ", ".join(cfg.get("factions", [])[:5]) + ("…" if len(cfg.get("factions", [])) > 5 else "") or "—"
    embed = discord.Embed(title=t(gid, "admin_title"), description=t(gid, "admin_desc"), color=0x2f3136)
    embed.add_field(name="Factions", value=fac_str, inline=True)
    embed.add_field(name="Ranks", value=", ".join(cfg.get("ranks", [])[:5]) or "—", inline=True)
    embed.add_field(name="Common Bloodlines", value=", ".join(cfg.get("bloodlines_common", [])) or "—", inline=True)
    embed.add_field(name="Special Bloodlines", value=", ".join(cfg.get("bloodlines_special", [])) or "—", inline=True)
    embed.add_field(name="Language", value=lang, inline=True)
    return embed


def _role_map_embed(gid, rtype):
    cfg = load_config(gid); mappings = cfg["roles"].get(rtype, {})
    items = {
        "faction":   cfg.get("factions", []),
        "rank":      cfg.get("ranks", []),
        "shifter":   cfg.get("shifters", []),
        "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", []),
    }[rtype]
    lines = [f"**{i}** → {'<@&'+str(mappings[i])+'>' if i in mappings else '*not set*'}" for i in items]
    embed = discord.Embed(title=f"{rtype.title()} Role Mapping", color=0x3498db)
    embed.description = "\n".join(lines) if lines else "*(no items)*"
    return embed


def _list_embed(gid, key):
    items = load_config(gid).get(key, [])
    embed = discord.Embed(title=f"Manage {key.replace('_', ' ').title()}", color=0x3498db)
    embed.description = "\n".join(f"• {i}" for i in items) if items else "*None*"
    return embed


def _bl_embed(gid):
    cfg = load_config(gid)
    embed = discord.Embed(title="Manage Bloodlines", color=0x3498db)
    embed.add_field(name="Common", value="\n".join(f"• {b}" for b in cfg.get("bloodlines_common", [])) or "—", inline=True)
    embed.add_field(name="Special", value="\n".join(f"• {b}" for b in cfg.get("bloodlines_special", [])) or "—", inline=True)
    return embed


def _grant_bl_embed(gid):
    cfg = load_config(gid); acc = cfg.get("special_access", {})
    grants = "\n".join(f"<@{uid}>: {', '.join(bls)}" for uid, bls in acc.items()) or "—"
    embed = discord.Embed(title=t(gid, "grant_bloodline_btn"), color=0x3498db)
    embed.add_field(name="Special Bloodlines", value=", ".join(cfg.get("bloodlines_special", [])) or "—", inline=False)
    embed.add_field(name="Current Grants", value=grants[:1024], inline=False)
    return embed


def _grant_sh_embed(gid):
    cfg = load_config(gid); acc = cfg.get("shifter_access", [])
    users = "\n".join(f"<@{uid}>" for uid in acc) or "—"
    embed = discord.Embed(title=t(gid, "grant_shifter_btn"), color=0x3498db)
    embed.add_field(name="Titans", value=", ".join(cfg.get("shifters", [])) or "—", inline=False)
    embed.add_field(name="Users with access", value=users[:1024], inline=False)
    return embed


def _tracker_embed(gid, guild):
    import time as _t
    players = load_players(gid); lines = []
    for uid, p in players.items():
        powers = p.get("titan_powers", [])
        if not powers: continue
        member = guild.get_member(int(uid)) if guild else None
        name = member.display_name if member else f"<@{uid}>"
        exp = powers[0].get("expires_at", 0); secs = max(0, int(exp - _t.time()))
        days = secs // 86400; titan_names = ", ".join(pw["titan"] for pw in powers)
        lines.append(f"**{name}** — {titan_names} — {days}d left")
    embed = discord.Embed(title=t(gid, "shifter_tracker_btn"), color=0x3498db)
    embed.description = "\n".join(lines) if lines else "*No active shifters*"
    return embed


def _lang_embed(gid):
    cfg = load_config(gid)
    lang = cfg.get("language", "th")
    embed = discord.Embed(title=t(gid, "language_btn"), color=0x3498db)
    embed.description = f"Current language: **{'Thai 🇹🇭' if lang == 'th' else 'English 🇬🇧'}**"
    return embed


# ── Admin main view ───────────────────────────────────────────────────────────

class AdminMainView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _b(label_key, cb, row, style=discord.ButtonStyle.secondary):
            b = discord.ui.Button(label=t(gid, label_key), style=style, row=row)
            b.callback = cb
            self.add_item(b)

        _b("faction_roles_btn",   self._make_role_cb("faction"),   row=0)
        _b("rank_roles_btn",      self._make_role_cb("rank"),       row=0)
        _b("shifter_roles_btn",   self._make_role_cb("shifter"),    row=0)
        _b("bloodline_roles_btn", self._make_role_cb("bloodline"),  row=0)

        _b("manage_factions_btn", self._make_list_cb("factions"), row=1)
        _b("manage_ranks_btn",    self._make_list_cb("ranks"),    row=1)
        _b("manage_shifters_btn", self._make_list_cb("shifters"), row=1)

        _b("manage_bloodlines_btn", self._bloodlines, row=2)
        _b("grant_bloodline_btn",   self._grant_bl,  row=2)
        _b("grant_shifter_btn",     self._grant_sh,  row=2)

        _b("shifter_tracker_btn", self._tracker,  row=3)
        _b("language_btn",        self._language, row=3)

        pm_btn = discord.ui.Button(label="Player Management", style=discord.ButtonStyle.primary, row=3)
        pm_btn.callback = self._player_mgmt
        self.add_item(pm_btn)

        done_btn = discord.ui.Button(label=t(gid, "done_btn"), style=discord.ButtonStyle.danger, row=4)
        done_btn.callback = self._done
        self.add_item(done_btn)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not _check_admin(ix):
            await ix.response.send_message("Admin only.", ephemeral=True); return False
        return True

    def _make_role_cb(self, rtype):
        async def cb(ix):
            await ix.response.edit_message(embed=_role_map_embed(self.gid, rtype),
                                           view=RoleMappingView(self.gid, rtype, self))
        return cb

    def _make_list_cb(self, list_key):
        async def cb(ix):
            await ix.response.edit_message(embed=_list_embed(self.gid, list_key),
                                           view=ManageListView(self.gid, list_key, self))
        return cb

    async def _bloodlines(self, ix):
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=ManageBloodlinesView(self.gid, self))

    async def _grant_bl(self, ix):
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=GrantBloodlineView(self.gid, self))

    async def _grant_sh(self, ix):
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=GrantShifterView(self.gid, self))

    async def _tracker(self, ix):
        await ix.response.edit_message(embed=_tracker_embed(self.gid, ix.guild),
                                       view=ShifterTrackerView(self.gid, self, ix.guild))

    async def _language(self, ix):
        await ix.response.edit_message(embed=_lang_embed(self.gid), view=LanguageView(self.gid, self))

    async def _player_mgmt(self, ix: discord.Interaction):
        embed = discord.Embed(
            title="Player Management",
            description="Manage player characters — convert mindless, flag dead, set creation requirements.",
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=PlayerMgmtView(self.gid))

    async def _done(self, ix):
        embed = discord.Embed(description=f"*{t(self.gid, 'panel_closed')}*", color=0x2f3136)
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


# ── Role mapping ──────────────────────────────────────────────────────────────

class RoleMappingView(discord.ui.View):
    def __init__(self, gid: int, rtype: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.rtype = rtype; self.parent = parent; self.sel = None
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
        val_sel = discord.ui.Select(
            placeholder=f"Select {self.rtype}",
            options=select_options_from_list(self._items(), self.sel),
            row=0,
        )
        val_sel.callback = self._val_cb
        self.add_item(val_sel)

        rs = discord.ui.RoleSelect(placeholder="Assign role", row=1)
        rs.callback = self._role_cb
        self.add_item(rs)

        back = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=2)
        back.callback = self._back
        self.add_item(back)

    async def _val_cb(self, ix):
        self.sel = ix.data["values"][0]; self._build()
        await ix.response.edit_message(embed=_role_map_embed(self.gid, self.rtype), view=self)

    async def _role_cb(self, ix):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid)
        cfg["roles"].setdefault(self.rtype, {})[self.sel] = ix.data["values"][0]
        save_config(self.gid, cfg)
        self._build()
        await ix.response.edit_message(embed=_role_map_embed(self.gid, self.rtype), view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


# ── Manage list ───────────────────────────────────────────────────────────────

class _AddModal(discord.ui.Modal):
    val = discord.ui.TextInput(label="Name", max_length=60)

    def __init__(self, gid: int, key: str, parent):
        super().__init__(title=f"Add to {key}")
        self.gid = gid; self.key = key; self.parent = parent

    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.val.value.strip()
        if v and v not in cfg.get(self.key, []):
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)


class ManageListView(discord.ui.View):
    def __init__(self, gid: int, key: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.key = key; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        add  = discord.ui.Button(label="Add",    style=discord.ButtonStyle.success,   row=0)
        rem  = discord.ui.Button(label="Remove", style=discord.ButtonStyle.danger,    row=0)
        back = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=0)
        add.callback  = self._add
        rem.callback  = self._remove
        back.callback = self._back
        self.add_item(add); self.add_item(rem); self.add_item(back)

    async def _add(self, ix):
        await ix.response.send_modal(_AddModal(self.gid, self.key, self))

    async def _remove(self, ix):
        items = load_config(self.gid).get(self.key, [])
        if not items:
            await ix.response.send_message("Nothing to remove.", ephemeral=True); return
        embed = discord.Embed(title=f"Remove from {self.key.title()}", description="Select item to remove:", color=0xe74c3c)
        await ix.response.edit_message(embed=embed, view=_RemoveSelectView(self.gid, self.key, items, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


class _RemoveSelectView(discord.ui.View):
    def __init__(self, gid: int, key: str, items: list, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.key = key; self.parent = parent
        sel = discord.ui.Select(placeholder="Select to remove", options=select_options_from_list(items), row=0)
        sel.callback = self._cb
        self.add_item(sel)
        back = discord.ui.Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def _cb(self, ix):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            lst = cfg.get(self.key, [])
            if v in lst: lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_list_embed(self.gid, self.key), view=self.parent)


# ── Bloodlines ────────────────────────────────────────────────────────────────

class _BlModal(discord.ui.Modal):
    name = discord.ui.TextInput(label="Bloodline Name", max_length=60)

    def __init__(self, gid: int, key: str, parent):
        super().__init__(title=f"Add {'Special' if 'special' in key else 'Common'} Bloodline")
        self.gid = gid; self.key = key; self.parent = parent

    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.name.value.strip()
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if v and v not in all_bl:
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)


class ManageBloodlinesView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        ac  = discord.ui.Button(label="Add Common",  style=discord.ButtonStyle.success,   row=0)
        as_ = discord.ui.Button(label="Add Special", style=discord.ButtonStyle.success,   row=0)
        rm  = discord.ui.Button(label="Remove",      style=discord.ButtonStyle.danger,    row=0)
        bk  = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=0)
        ac.callback  = self._make_cb("bloodlines_common")
        as_.callback = self._make_cb("bloodlines_special")
        rm.callback  = self._make_cb(None)
        bk.callback  = self._back
        self.add_item(ac); self.add_item(as_); self.add_item(rm); self.add_item(bk)

    def _make_cb(self, key):
        async def cb(ix):
            if key:
                await ix.response.send_modal(_BlModal(self.gid, key, self))
            else:
                cfg = load_config(self.gid)
                all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
                if not all_bl:
                    await ix.response.send_message("No bloodlines to remove.", ephemeral=True); return
                embed = discord.Embed(title="Remove Bloodline", description="Select bloodline to remove:", color=0xe74c3c)
                await ix.response.edit_message(embed=embed, view=_RemoveBlView(self.gid, all_bl, self))
        return cb

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


class _RemoveBlView(discord.ui.View):
    def __init__(self, gid: int, items: list, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        sel = discord.ui.Select(placeholder="Select bloodline to remove",
                                options=select_options_from_list(items), row=0)
        sel.callback = self._cb
        self.add_item(sel)
        back = discord.ui.Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def _cb(self, ix):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            for k in ("bloodlines_common", "bloodlines_special"):
                lst = cfg.get(k, [])
                if v in lst: lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_bl_embed(self.gid), view=self.parent)


# ── Grant special bloodline ───────────────────────────────────────────────────

class GrantBloodlineView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_bl = None; self.sel_users = []; self.sel_role = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])
        sel = discord.ui.Select(placeholder="Choose bloodline",
                                options=select_options_from_list(special, self.sel_bl), row=0)
        sel.callback = self._bl_cb
        self.add_item(sel)

        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25, row=1)
        us.callback = self._user_cb
        self.add_item(us)

        rs = discord.ui.RoleSelect(placeholder="Grant via role", row=2)
        rs.callback = self._role_cb
        self.add_item(rs)

        gu = discord.ui.Button(label="Grant Users",    style=discord.ButtonStyle.success,   row=3)
        gr = discord.ui.Button(label="Grant via Role", style=discord.ButtonStyle.success,   row=3)
        gu.callback = self._grant_users
        gr.callback = self._grant_role
        self.add_item(gu); self.add_item(gr)

        rv = discord.ui.Button(label="Revoke",     style=discord.ButtonStyle.danger,    row=4)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=4)
        rv.callback = self._revoke
        bk.callback = self._back
        self.add_item(rv); self.add_item(bk)

    async def _bl_cb(self, ix):
        self.sel_bl = ix.data["values"][0]; self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _user_cb(self, ix):
        self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _role_cb(self, ix):
        self.sel_role = ix.data["values"][0] if ix.data["values"] else None
        await ix.response.defer()

    async def _grant_users(self, ix):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid); acc = cfg.setdefault("special_access", {})
        newly_granted = []
        for uid in self.sel_users:
            if self.sel_bl not in acc.get(uid, []):
                acc.setdefault(uid, []).append(self.sel_bl)
                newly_granted.append(uid)
        save_config(self.gid, cfg)
        for uid in newly_granted:
            try:
                user = await bot.fetch_user(int(uid))
                await cv2_dm(user, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _grant_role(self, ix):
        if not self.sel_bl or not self.sel_role:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        role = ix.guild.get_role(int(self.sel_role))
        if not role:
            await ix.response.send_message("Role not found.", ephemeral=True); return
        cfg = load_config(self.gid); acc = cfg.setdefault("special_access", {})
        newly_granted = []
        for m in role.members:
            if self.sel_bl not in acc.get(str(m.id), []):
                acc.setdefault(str(m.id), []).append(self.sel_bl)
                newly_granted.append(m)
        save_config(self.gid, cfg)
        for m in newly_granted:
            await cv2_dm(m, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
        self._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self)

    async def _revoke(self, ix):
        embed = discord.Embed(title="Revoke Special Bloodline",
                              description="Select users and bloodline to revoke:", color=0xe74c3c)
        await ix.response.edit_message(embed=embed, view=RevokeBlView(self.gid, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


class RevokeBlView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_users = []; self.sel_bl = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])
        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25, row=0)
        sel = discord.ui.Select(placeholder="Bloodline to revoke",
                                options=select_options_from_list(special, self.sel_bl), row=1)
        rv = discord.ui.Button(label="Revoke",  style=discord.ButtonStyle.danger,    row=2)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=2)
        us.callback  = self._user_cb
        sel.callback = self._bl_cb
        rv.callback  = self._do
        bk.callback  = self._back
        self.add_item(us); self.add_item(sel); self.add_item(rv); self.add_item(bk)

    async def _user_cb(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _bl_cb(self, ix):
        self.sel_bl = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _do(self, ix):
        if not self.sel_bl or self.sel_bl == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid); acc = cfg.get("special_access", {})
        for uid in self.sel_users:
            lst = acc.get(uid, [])
            if self.sel_bl in lst: lst.remove(self.sel_bl)
            if not lst: acc.pop(uid, None)
        save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_grant_bl_embed(self.gid), view=self.parent)


# ── Grant shifter access ──────────────────────────────────────────────────────

class GrantShifterView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_titan = None; self.sel_users = []
        self._build()

    def _build(self):
        self.clear_items()
        titans = load_config(self.gid).get("shifters", [])
        titan_sel = discord.ui.Select(
            placeholder="Select Titan to assign",
            options=select_options_from_list(titans, self.sel_titan),
            row=0,
        )
        titan_sel.callback = self._titan_cb
        self.add_item(titan_sel)

        us = discord.ui.UserSelect(placeholder="Select users to grant", min_values=1, max_values=25, row=1)
        us.callback = self._user_cb
        self.add_item(us)

        gu = discord.ui.Button(label="Grant",        style=discord.ButtonStyle.success,   row=2)
        rv = discord.ui.Button(label="Revoke Users", style=discord.ButtonStyle.danger,    row=2)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=2)
        gu.callback = self._grant_u
        rv.callback = self._revoke
        bk.callback = self._back
        self.add_item(gu); self.add_item(rv); self.add_item(bk)

    async def _titan_cb(self, ix):
        self.sel_titan = ix.data["values"][0]; self._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self)

    async def _user_cb(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _grant_u(self, ix):
        import time as _t
        if not self.sel_titan or self.sel_titan == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid)
        immune_bls = cfg.get("bloodlines_immune_shifter", [])
        acc = cfg.setdefault("shifter_access", [])
        players = load_players(self.gid)
        titan_days = cfg.get("titan_time_days", 4745)
        now = _t.time()
        skipped = []
        for uid in self.sel_users:
            player = players.get(uid, {})
            if player.get("bloodline", "").lower() in [b.lower() for b in immune_bls]:
                skipped.append(uid); continue
            if uid not in acc:
                acc.append(uid)
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
            if uid in skipped: continue
            try:
                user = await bot.fetch_user(int(uid))
                await cv2_dm(user, t(self.gid, "got_titan_dm", titan=self.sel_titan))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self)
        if skipped:
            skip_msg = f"Granted to {len(self.sel_users) - len(skipped)} player(s). Skipped {len(skipped)} due to immune bloodline."
            await ix.followup.send(skip_msg, ephemeral=True)

    async def _revoke(self, ix):
        embed = discord.Embed(title="Revoke Shifter Access", description="Select users to revoke:", color=0xe74c3c)
        await ix.response.edit_message(embed=embed, view=RevokeShView(self.gid, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


class RevokeShView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.sel_users = []
        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25, row=0)
        rv = discord.ui.Button(label="Revoke",  style=discord.ButtonStyle.danger,    row=1)
        bk = discord.ui.Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        us.callback = self._uc
        rv.callback = self._do
        bk.callback = self._back
        self.add_item(us); self.add_item(rv); self.add_item(bk)

    async def _uc(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _do(self, ix):
        cfg = load_config(self.gid); acc = cfg.get("shifter_access", [])
        players = load_players(self.gid)
        for uid in self.sel_users:
            if uid in acc: acc.remove(uid)
            player = players.get(uid, {})
            player["titan_powers"] = []
            player["transformed"]  = False
            players[uid] = player
        save_config(self.gid, cfg)
        save_players(self.gid, players)
        self.parent._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_grant_sh_embed(self.gid), view=self.parent)


# ── Shifter tracker ───────────────────────────────────────────────────────────

class ShifterTrackerView(discord.ui.View):
    def __init__(self, gid: int, parent, guild=None):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.guild = guild
        bk = discord.ui.Button(label=t(gid, "back_btn"),              style=discord.ButtonStyle.secondary, row=0)
        st = discord.ui.Button(label=t(gid, "set_shifter_time_btn"),  style=discord.ButtonStyle.secondary, row=0)
        bk.callback = self._back
        st.callback = self._set_time
        self.add_item(bk); self.add_item(st)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)

    async def _set_time(self, ix):
        await ix.response.send_modal(SetShifterTimeModal(self.gid, self))


class SetShifterTimeModal(discord.ui.Modal, title="Set Shifter Time"):
    uid_input  = discord.ui.TextInput(label="User ID",        max_length=25)
    days_input = discord.ui.TextInput(label="Days remaining", max_length=10)

    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        import time as _t
        try:
            uid  = self.uid_input.value.strip()
            days = int(self.days_input.value.strip())
            players = load_players(self.gid); p = players.get(uid, {})
            for pw in p.get("titan_powers", []):
                pw["expires_at"] = _t.time() + days * 86400
            save_players(self.gid, players)
            self.parent.guild = ix.guild
            await ix.response.edit_message(embed=_tracker_embed(self.gid, ix.guild), view=self.parent)
        except Exception as e:
            await ix.response.send_message(f"Error: {e}", ephemeral=True)


# ── Language ──────────────────────────────────────────────────────────────────

class LanguageView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        th = discord.ui.Button(label=t(self.gid, "language_th"), style=discord.ButtonStyle.primary,   row=0)
        en = discord.ui.Button(label=t(self.gid, "language_en"), style=discord.ButtonStyle.primary,   row=0)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"),    style=discord.ButtonStyle.secondary, row=0)
        th.callback = self._make_cb("th")
        en.callback = self._make_cb("en")
        bk.callback = self._back
        self.add_item(th); self.add_item(en); self.add_item(bk)

    def _make_cb(self, lang):
        async def cb(ix):
            cfg = load_config(self.gid); cfg["language"] = lang; save_config(self.gid, cfg)
            self._build()
            await ix.response.edit_message(embed=_lang_embed(self.gid), view=self)
        return cb

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=self.parent)


# ── Player management ─────────────────────────────────────────────────────────

class PlayerMgmtView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not _check_admin(ix):
            await ix.response.send_message("Admin only.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Convert Mindless → Human", style=discord.ButtonStyle.primary, row=0)
    async def btn_mindless_to_human(self, ix: discord.Interaction, _b):
        embed = discord.Embed(title="Convert Mindless → Human",
                              description="Select the player to convert back to human.", color=0x3498db)
        await ix.response.edit_message(embed=embed, view=_MindlessToHumanView(self.gid, self))

    @discord.ui.button(label="Flag Player as Deceased", style=discord.ButtonStyle.danger, row=0)
    async def btn_flag_dead(self, ix: discord.Interaction, _b):
        embed = discord.Embed(title="Flag Player as Deceased",
                              description="This will delete the player's character data. This cannot be undone.",
                              color=discord.Color.red())
        await ix.response.edit_message(embed=embed, view=_FlagDeadView(self.gid, self))

    @discord.ui.button(label="Set Creation Role", style=discord.ButtonStyle.secondary, row=1)
    async def btn_creation_role(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_SetCreationRoleModal(self.gid, self))

    @discord.ui.button(label="Set Review Channel", style=discord.ButtonStyle.secondary, row=1)
    async def btn_review_channel(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_SetReviewChannelModal(self.gid, self))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def btn_back(self, ix: discord.Interaction, _b):
        await ix.response.edit_message(embed=_admin_embed(self.gid), view=AdminMainView(self.gid))


class _MindlessToHumanView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        sel = discord.ui.UserSelect(placeholder="Select player", min_values=1, max_values=1, row=0)
        sel.callback = self._on_select
        self.add_item(sel)
        bk = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        bk.callback = self._back
        self.add_item(bk)

    async def _on_select(self, ix: discord.Interaction):
        target_id = int(ix.data["values"][0])
        players = load_players(self.gid)
        player  = players.get(str(target_id))
        if not player:
            await ix.response.send_message("Player not registered.", ephemeral=True); return
        if not player.get("mindless_titan"):
            await ix.response.send_message("Player is not mindless.", ephemeral=True); return
        player["mindless_titan"] = False
        player.pop("mindless_acquired_at", None)
        players[str(target_id)] = player
        save_players(self.gid, players)
        cfg = load_config(self.gid)
        member = ix.guild.get_member(target_id)
        if member:
            try:
                mindless_role_id = cfg.get("mindless_role_id")
                if mindless_role_id:
                    mindless_role = ix.guild.get_role(int(mindless_role_id))
                    if mindless_role and mindless_role in member.roles:
                        await member.remove_roles(mindless_role)
                await assign_roles(member, player, cfg)
            except Exception: pass
        await log_event(bot, self.gid, "admin",
                        f"<@{ix.user.id}> converted <@{target_id}> from mindless to human")
        embed = discord.Embed(title="Conversion Complete",
                              description=f"<@{target_id}> has been converted back to human.",
                              color=discord.Color.green())
        await ix.response.edit_message(embed=embed, view=None)
        try:
            user = await bot.fetch_user(target_id)
            await user.send(embed=discord.Embed(
                title="You have been restored",
                description="An admin has converted you back from mindless titan to human.",
                color=discord.Color.green(),
            ))
        except Exception: pass

    async def _back(self, ix: discord.Interaction):
        embed = discord.Embed(title="Player Management", color=0x2f3136)
        await ix.response.edit_message(embed=embed, view=self.parent)


class _FlagDeadView(discord.ui.View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        sel = discord.ui.UserSelect(placeholder="Select player to mark as deceased",
                                    min_values=1, max_values=1, row=0)
        sel.callback = self._on_select
        self.add_item(sel)
        bk = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        bk.callback = self._back
        self.add_item(bk)

    async def _on_select(self, ix: discord.Interaction):
        target_id = int(ix.data["values"][0])
        players = load_players(self.gid)
        player  = players.get(str(target_id))
        if not player:
            await ix.response.send_message("Player not registered.", ephemeral=True); return
        char_name = player.get("name", f"<@{target_id}>")
        embed = discord.Embed(
            title="Confirm Death",
            description=(
                f"Mark **{char_name}** (<@{target_id}>) as deceased?\n\n"
                "This will **delete their character data**. They will need to create a new character."
            ),
            color=discord.Color.red(),
        )
        await ix.response.edit_message(embed=embed, view=_ConfirmDeathView(self.gid, target_id, char_name, self))

    async def _back(self, ix: discord.Interaction):
        embed = discord.Embed(title="Player Management", color=0x2f3136)
        await ix.response.edit_message(embed=embed, view=self.parent)


class _ConfirmDeathView(discord.ui.View):
    def __init__(self, gid: int, target_id: int, char_name: str, parent):
        super().__init__(timeout=120)
        self.gid = gid; self.target_id = target_id; self.char_name = char_name; self.parent = parent

    @discord.ui.button(label="Confirm — Mark as Deceased", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm(self, ix: discord.Interaction, _b):
        players = load_players(self.gid)
        uid_str = str(self.target_id)
        old_player = players.get(uid_str, {})
        if uid_str in players:
            del players[uid_str]
            save_players(self.gid, players)
        cfg = load_config(self.gid)
        member = ix.guild.get_member(self.target_id)
        if member and old_player:
            try:
                await remove_old_roles(member, old_player, cfg)
            except Exception: pass
        await log_event(bot, self.gid, "admin",
                        f"<@{ix.user.id}> flagged <@{self.target_id}> ({self.char_name}) as deceased")
        embed = discord.Embed(
            title="Character Removed",
            description=(
                f"**{self.char_name}** (<@{self.target_id}>) has been marked as deceased. "
                "Their character data has been deleted."
            ),
            color=discord.Color.red(),
        )
        await ix.response.edit_message(embed=embed, view=None)
        try:
            user = await bot.fetch_user(self.target_id)
            await user.send(embed=discord.Embed(
                title="Your character has died",
                description="An admin has marked your character as deceased. Use `/profile` to create a new character.",
                color=discord.Color.red(),
            ))
        except Exception: pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, ix: discord.Interaction, _b):
        embed = discord.Embed(title="Player Management", color=0x2f3136)
        await ix.response.edit_message(embed=embed, view=self.parent)


class _SetCreationRoleModal(discord.ui.Modal, title="Set Required Creation Role"):
    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        cfg = load_config(gid)
        existing = cfg.get("required_creation_role_id", "")
        self.f_role_id = discord.ui.TextInput(
            label="Role ID (leave blank to remove)", max_length=30, required=False,
            default=str(existing) if existing else "",
        )
        self.add_item(self.f_role_id)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        val = self.f_role_id.value.strip()
        if val and val.isdigit():
            cfg["required_creation_role_id"] = int(val)
            role_obj = ix.guild.get_role(int(val))
            role_name = role_obj.name if role_obj else f"ID:{val}"
            msg = f"Required creation role set to **{role_name}**."
        elif not val:
            cfg.pop("required_creation_role_id", None)
            msg = "Required creation role removed. Anyone can create a character."
        else:
            await ix.response.send_message("Invalid role ID.", ephemeral=True); return
        save_config(self.gid, cfg)
        embed = discord.Embed(title="Creation Role Updated", description=msg, color=discord.Color.green())
        await ix.response.edit_message(embed=embed, view=self.parent)


class _SetReviewChannelModal(discord.ui.Modal, title="Set Character Review Channel"):
    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        cfg = load_config(gid)
        existing = cfg.get("char_review_channel_id", "")
        self.f_channel_id = discord.ui.TextInput(
            label="Channel ID (forum or text)", max_length=30,
            default=str(existing) if existing else "",
        )
        self.add_item(self.f_channel_id)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        val = self.f_channel_id.value.strip()
        if val.isdigit():
            cfg["char_review_channel_id"] = int(val)
            ch = ix.guild.get_channel(int(val))
            ch_name = ch.name if ch else f"ID:{val}"
            ch_type = "Forum" if isinstance(ch, discord.ForumChannel) else "Text"
            save_config(self.gid, cfg)
            embed = discord.Embed(
                title="Review Channel Set",
                description=f"Character review channel: **#{ch_name}** ({ch_type})",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(title="Invalid Channel ID", color=discord.Color.red())
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── /paradis-admin command ────────────────────────────────────────────────────

@bot.tree.command(
    name="paradis-admin",
    description="[Admin] Open admin panel | เปิดแผงควบคุมแอดมิน",
    guild=GUILD2_OBJ,
)
@is_admin()
async def paradis_admin_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    await ix.response.send_message(
        embed=_admin_embed(ix.guild_id),
        view=AdminMainView(ix.guild_id),
        ephemeral=True,
    )


@paradis_admin_cmd.error
async def paradis_admin_error(ix: discord.Interaction, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
