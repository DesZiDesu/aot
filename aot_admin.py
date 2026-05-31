"""Admin panel — roles, lists, bloodlines, shifter access, language."""
import discord
from discord import app_commands
from discord.ui import LayoutView, Container, TextDisplay, Separator, ActionRow, Button, Select, Modal, TextInput

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, save_config, load_players, save_players,
    select_options_from_list, cv2_dm,
)


def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Text helpers ──────────────────────────────────────────────────────────────

def _admin_text(gid):
    cfg = load_config(gid)
    lang = "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"
    factions = cfg.get("factions", [])
    fac_str = ", ".join(factions[:5]) + ("…" if len(factions) > 5 else "")
    return "\n".join([
        f"**{t(gid,'admin_title')}**", "",
        t(gid, "admin_desc"), "",
        f"**Factions:** {fac_str}",
        f"**Ranks:** {', '.join(cfg.get('ranks',[])[:5])}",
        f"**Common BL:** {', '.join(cfg.get('bloodlines_common',[]))}",
        f"**Special BL:** {', '.join(cfg.get('bloodlines_special',[]))}",
        f"**Language:** {lang}",
    ])

def _role_map_text(gid, rtype):
    cfg = load_config(gid); mappings = cfg["roles"].get(rtype, {})
    items = {"faction": cfg.get("factions", []), "rank": cfg.get("ranks", []),
             "shifter": cfg.get("shifters", []),
             "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])}[rtype]
    lines = [f"**{i}** — {'<@&'+str(mappings[i])+'>' if i in mappings else '*not set*'}" for i in items]
    return f"**{rtype.title()} Roles**\n\n" + "\n".join(lines or ["—"])

def _list_text(gid, key):
    items = load_config(gid).get(key, [])
    return f"**Manage {key.title()}**\n\n" + "\n".join([f"- {i}" for i in items] or ["*None*"])

def _bl_text(gid):
    cfg = load_config(gid)
    common  = "\n".join(f"  - {b}" for b in cfg.get("bloodlines_common",  [])) or "  *None*"
    special = "\n".join(f"  - {b}" for b in cfg.get("bloodlines_special", [])) or "  *None*"
    return f"**Manage Bloodlines**\n\n**Common:**\n{common}\n\n**Special:**\n{special}"

def _grant_bl_text(gid):
    cfg = load_config(gid); acc = cfg.get("special_access", {})
    grants = "\n".join(f"  <@{uid}>: {', '.join(bls)}" for uid, bls in acc.items()) or "  *None*"
    return (f"**{t(gid,'grant_bloodline_btn')}**\n\n"
            f"**Special BL:** {', '.join(cfg.get('bloodlines_special',[]))}\n\n"
            f"**Current Grants:**\n{grants}")

def _grant_sh_text(gid):
    cfg = load_config(gid); acc = cfg.get("shifter_access", [])
    users = "\n".join(f"  <@{uid}>" for uid in acc) or "  *None*"
    return (f"**{t(gid,'grant_shifter_btn')}**\n\n"
            f"**Titans:** {', '.join(cfg.get('shifters',[]))}\n\n"
            f"**Users with access:**\n{users}")

def _tracker_text(gid, guild):
    import time as _t
    from aot_shared import load_players
    players = load_players(gid); lines = []
    for uid, p in players.items():
        powers = p.get("titan_powers", [])
        if not powers: continue
        member = guild.get_member(int(uid)) if guild else None
        name = member.display_name if member else f"<@{uid}>"
        exp = powers[0].get("expires_at", 0); secs = max(0, int(exp - _t.time()))
        days = secs // 86400; titan_names = ", ".join(pw["titan"] for pw in powers)
        lines.append(f"**{name}** — {titan_names} — {days}d left")
    return f"**{t(gid,'shifter_tracker_btn')}**\n\n" + ("\n".join(lines) if lines else "*No active shifters*")

def _lang_text(gid):
    cfg = load_config(gid); lang = cfg.get("language", "th")
    return f"**{t(gid,'language_btn')}**\n\nCurrent: {'Thai 🇹🇭' if lang=='th' else 'English 🇬🇧'}"


# ── Admin main view ───────────────────────────────────────────────────────────

class AdminMainView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _b(label_key, cb, cid):
            b = Button(label=t(gid, label_key), style=discord.ButtonStyle.secondary, custom_id=cid)
            b.callback = cb
            return b

        done = Button(label=t(gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="adm_done")
        done.callback = self._done

        self.add_item(Container(
            TextDisplay(_admin_text(gid)),
            Separator(),
            ActionRow(
                _b("faction_roles_btn",   self._make_role_cb("faction"),   "adm_rfac"),
                _b("rank_roles_btn",      self._make_role_cb("rank"),      "adm_rrank"),
                _b("shifter_roles_btn",   self._make_role_cb("shifter"),   "adm_rshift"),
                _b("bloodline_roles_btn", self._make_role_cb("bloodline"), "adm_rbl"),
            ),
            ActionRow(
                _b("manage_factions_btn", self._make_list_cb("factions"), "adm_mfac"),
                _b("manage_ranks_btn",    self._make_list_cb("ranks"),    "adm_mrank"),
                _b("manage_shifters_btn", self._make_list_cb("shifters"), "adm_mshift"),
            ),
            ActionRow(
                _b("manage_bloodlines_btn", self._bloodlines, "adm_mbl"),
                _b("grant_bloodline_btn",   self._grant_bl,  "adm_gbl"),
                _b("grant_shifter_btn",     self._grant_sh,  "adm_gsh"),
            ),
            ActionRow(
                _b("shifter_tracker_btn", self._tracker,  "adm_track"),
                _b("language_btn",        self._language, "adm_lang"),
            ),
            ActionRow(done),
        ))

    def _make_role_cb(self, rtype):
        async def cb(ix): await ix.response.edit_message(view=RoleMappingView(self.gid, rtype, self))
        return cb

    def _make_list_cb(self, list_key):
        async def cb(ix): await ix.response.edit_message(view=ManageListView(self.gid, list_key, self))
        return cb

    async def _bloodlines(self, ix): await ix.response.edit_message(view=ManageBloodlinesView(self.gid, self))
    async def _grant_bl(self, ix):   await ix.response.edit_message(view=GrantBloodlineView(self.gid, self))
    async def _grant_sh(self, ix):   await ix.response.edit_message(view=GrantShifterView(self.gid, self))
    async def _tracker(self, ix):    await ix.response.edit_message(view=ShifterTrackerView(self.gid, self, ix.guild))
    async def _language(self, ix):   await ix.response.edit_message(view=LanguageView(self.gid, self))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── Role mapping ──────────────────────────────────────────────────────────────

class RoleMappingView(LayoutView):
    def __init__(self, gid, rtype, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.rtype = rtype; self.parent = parent; self.sel = None
        self._build()

    def _items(self):
        cfg = load_config(self.gid)
        return {"faction": cfg.get("factions", []), "rank": cfg.get("ranks", []),
                "shifter": cfg.get("shifters", []),
                "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])}[self.rtype]

    def _build(self):
        self.clear_items()
        val_sel = Select(placeholder=f"Select {self.rtype}",
                         options=select_options_from_list(self._items(), self.sel))
        val_sel.callback = self._val_cb

        rs = discord.ui.RoleSelect(placeholder="Assign role")
        rs.callback = self._role_cb

        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rm_back")
        back.callback = self._back

        self.add_item(Container(
            TextDisplay(_role_map_text(self.gid, self.rtype)),
            Separator(),
            ActionRow(val_sel),
            ActionRow(rs),
            ActionRow(back),
        ))

    async def _val_cb(self, ix):
        self.sel = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _role_cb(self, ix):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid)
        cfg["roles"][self.rtype][self.sel] = ix.data["values"][0]
        save_config(self.gid, cfg)
        self._build()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Manage list ───────────────────────────────────────────────────────────────

class _AddModal(Modal):
    val = TextInput(label="Name", max_length=60)
    def __init__(self, gid, key, parent):
        super().__init__(title=f"Add to {key}")
        self.gid = gid; self.key = key; self.parent = parent

    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.val.value.strip()
        if v and v not in cfg.get(self.key, []):
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class ManageListView(LayoutView):
    def __init__(self, gid, key, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.key = key; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        add  = Button(label="Add",    style=discord.ButtonStyle.green,     custom_id="ml_add")
        rem  = Button(label="Remove", style=discord.ButtonStyle.danger,    custom_id="ml_remove")
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="ml_back")
        add.callback  = self._add
        rem.callback  = self._remove
        back.callback = self._back
        self.add_item(Container(
            TextDisplay(_list_text(self.gid, self.key)),
            Separator(),
            ActionRow(add, rem),
            ActionRow(back),
        ))

    async def _add(self, ix): await ix.response.send_modal(_AddModal(self.gid, self.key, self))

    async def _remove(self, ix):
        items = load_config(self.gid).get(self.key, [])
        await ix.response.edit_message(view=_RemoveSelectView(self.gid, self.key, items, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class _RemoveSelectView(LayoutView):
    def __init__(self, gid, key, items, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.key = key; self.parent = parent
        sel  = Select(placeholder="Select to remove", options=select_options_from_list(items))
        sel.callback = self._cb
        back = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rsv_back")
        back.callback = self._back
        self.add_item(Container(
            TextDisplay(f"**Remove from {key.title()}**\n\nSelect an item to remove:"),
            Separator(),
            ActionRow(sel),
            ActionRow(back),
        ))

    async def _cb(self, ix):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            lst = cfg.get(self.key, [])
            if v in lst: lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Bloodlines ────────────────────────────────────────────────────────────────

class _BlModal(Modal):
    name = TextInput(label="Bloodline Name", max_length=60)
    def __init__(self, gid, key, parent):
        super().__init__(title=f"Add {'Special' if 'special' in key else 'Common'} Bloodline")
        self.gid = gid; self.key = key; self.parent = parent

    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.name.value.strip()
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if v and v not in all_bl:
            cfg.setdefault(self.key, []).append(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class ManageBloodlinesView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        ac = Button(label="Add Common",  style=discord.ButtonStyle.green,     custom_id="mbl_ac")
        as_ = Button(label="Add Special", style=discord.ButtonStyle.green,    custom_id="mbl_as")
        rm  = Button(label="Remove",      style=discord.ButtonStyle.danger,   custom_id="mbl_rm")
        bk  = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="mbl_bk")
        ac.callback  = self._make_cb("bloodlines_common")
        as_.callback = self._make_cb("bloodlines_special")
        rm.callback  = self._make_cb(None)
        bk.callback  = self._back
        self.add_item(Container(
            TextDisplay(_bl_text(self.gid)),
            Separator(),
            ActionRow(ac, as_, rm),
            ActionRow(bk),
        ))

    def _make_cb(self, key):
        async def cb(ix):
            if key:
                await ix.response.send_modal(_BlModal(self.gid, key, self))
            else:
                cfg = load_config(self.gid)
                all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
                await ix.response.edit_message(view=_RemoveBlView(self.gid, all_bl, self))
        return cb

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class _RemoveBlView(LayoutView):
    def __init__(self, gid, items, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        sel  = Select(placeholder="Select bloodline to remove", options=select_options_from_list(items))
        sel.callback = self._cb
        back = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rbl_back")
        back.callback = self._back
        self.add_item(Container(
            TextDisplay("**Remove Bloodline**\n\nSelect bloodline to remove:"),
            Separator(),
            ActionRow(sel),
            ActionRow(back),
        ))

    async def _cb(self, ix):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            for k in ("bloodlines_common", "bloodlines_special"):
                lst = cfg.get(k, [])
                if v in lst: lst.remove(v)
            save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Grant special bloodline ───────────────────────────────────────────────────

class GrantBloodlineView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_bl = None; self.sel_users = []; self.sel_role = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])
        sel = Select(placeholder="Choose bloodline",
                     options=select_options_from_list(special, self.sel_bl))
        sel.callback = self._bl_cb

        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25)
        us.callback = self._user_cb

        rs = discord.ui.RoleSelect(placeholder="Grant via role")
        rs.callback = self._role_cb

        gu = Button(label="Grant Users",    style=discord.ButtonStyle.green,     custom_id="gbl_gu")
        gr = Button(label="Grant via Role", style=discord.ButtonStyle.green,     custom_id="gbl_gr")
        rv = Button(label="Revoke",         style=discord.ButtonStyle.danger,    custom_id="gbl_rv")
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gbl_bk")
        gu.callback = self._grant_users
        gr.callback = self._grant_role
        rv.callback = self._revoke
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay(_grant_bl_text(self.gid)),
            Separator(),
            ActionRow(sel),
            ActionRow(us),
            ActionRow(rs),
            ActionRow(gu, gr),
            ActionRow(rv, bk),
        ))

    async def _bl_cb(self, ix):
        self.sel_bl = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

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
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(uid))
                await cv2_dm(user, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(view=self)

    async def _grant_role(self, ix):
        if not self.sel_bl or not self.sel_role:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        role = ix.guild.get_role(int(self.sel_role))
        if not role: await ix.response.send_message("Role not found.", ephemeral=True); return
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
        await ix.response.edit_message(view=self)

    async def _revoke(self, ix):
        await ix.response.edit_message(view=RevokeBlView(self.gid, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class RevokeBlView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_users = []; self.sel_bl = None
        self._build()

    def _build(self):
        self.clear_items()
        special = load_config(self.gid).get("bloodlines_special", [])
        us  = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25)
        sel = Select(placeholder="Bloodline to revoke",
                     options=select_options_from_list(special, self.sel_bl))
        rv  = Button(label="Revoke",  style=discord.ButtonStyle.danger,    custom_id="rvbl_do")
        bk  = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rvbl_bk")
        us.callback  = self._user_cb
        sel.callback = self._bl_cb
        rv.callback  = self._do
        bk.callback  = self._back
        self.add_item(Container(
            TextDisplay("**Revoke Special Bloodline**\n\nSelect users and bloodline to revoke:"),
            Separator(),
            ActionRow(us),
            ActionRow(sel),
            ActionRow(rv, bk),
        ))

    async def _user_cb(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _bl_cb(self, ix):
        self.sel_bl = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _do(self, ix):
        cfg = load_config(self.gid); acc = cfg.get("special_access", {})
        for uid in self.sel_users:
            lst = acc.get(uid, [])
            if self.sel_bl in lst: lst.remove(self.sel_bl)
            if not lst: acc.pop(uid, None)
        save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Grant shifter access ──────────────────────────────────────────────────────

class GrantShifterView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_titan = None; self.sel_users = []
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.gid)
        titans = cfg.get("shifters", [])

        titan_sel = Select(placeholder="Select Titan to assign",
                           options=select_options_from_list(titans, self.sel_titan))
        titan_sel.callback = self._titan_cb

        us = discord.ui.UserSelect(placeholder="Select users to grant", min_values=1, max_values=25)
        us.callback = self._user_cb

        gu = Button(label="Grant",        style=discord.ButtonStyle.green,     custom_id="gsh_gu")
        rv = Button(label="Revoke Users", style=discord.ButtonStyle.danger,    custom_id="gsh_rv")
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gsh_bk")
        gu.callback = self._grant_u
        rv.callback = self._revoke
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay(_grant_sh_text(self.gid)),
            Separator(),
            ActionRow(titan_sel),
            ActionRow(us),
            ActionRow(gu, rv, bk),
        ))

    async def _titan_cb(self, ix):
        self.sel_titan = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _user_cb(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _grant_u(self, ix):
        import time as _t
        if not self.sel_titan or self.sel_titan == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        if not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid)
        acc = cfg.setdefault("shifter_access", [])
        players = load_players(self.gid)
        titan_days = cfg.get("titan_time_days", 4745)
        now = _t.time()
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
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(uid))
                await cv2_dm(user, t(self.gid, "got_titan_dm", titan=self.sel_titan))
            except Exception:
                pass
        self._build()
        await ix.response.edit_message(view=self)

    async def _revoke(self, ix):
        await ix.response.edit_message(view=RevokeShView(self.gid, self))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class RevokeShView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.sel_users = []
        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25)
        rv = Button(label="Revoke",  style=discord.ButtonStyle.danger,    custom_id="rvsh_do")
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rvsh_bk")
        us.callback = self._uc
        rv.callback = self._do
        bk.callback = self._back
        self.add_item(Container(
            TextDisplay("**Revoke Shifter Access**\n\nSelect users to revoke shifter access from:"),
            Separator(),
            ActionRow(us),
            ActionRow(rv, bk),
        ))

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
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Shifter tracker ───────────────────────────────────────────────────────────

class ShifterTrackerView(LayoutView):
    def __init__(self, gid, parent, guild=None):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        text = _tracker_text(self.gid, self.guild)
        bk = Button(label=t(self.gid, "back_btn"),          style=discord.ButtonStyle.secondary, custom_id="tr_bk")
        st = Button(label=t(self.gid, "set_shifter_time_btn"), style=discord.ButtonStyle.secondary, custom_id="tr_st")
        bk.callback = self._back
        st.callback = self._set_time
        self.add_item(Container(
            TextDisplay(text),
            Separator(),
            ActionRow(bk, st),
        ))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _set_time(self, ix):
        await ix.response.send_modal(SetShifterTimeModal(self.gid, self))


class SetShifterTimeModal(Modal, title="Set Shifter Time"):
    uid_input  = TextInput(label="User ID",        max_length=25)
    days_input = TextInput(label="Days remaining", max_length=10)

    def __init__(self, gid, parent):
        super().__init__()
        self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        import time as _t
        from aot_shared import load_players, save_players
        try:
            uid  = self.uid_input.value.strip()
            days = int(self.days_input.value.strip())
            players = load_players(self.gid); p = players.get(uid, {})
            for pw in p.get("titan_powers", []):
                pw["expires_at"] = _t.time() + days * 86400
            save_players(self.gid, players)
            self.parent.guild = ix.guild
            self.parent._build()
            await ix.response.edit_message(view=self.parent)
        except Exception as e:
            await ix.response.send_message(f"Error: {e}", ephemeral=True)


# ── Language ──────────────────────────────────────────────────────────────────

class LanguageView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        th = Button(label=t(self.gid, "language_th"), style=discord.ButtonStyle.primary,   custom_id="lang_th")
        en = Button(label=t(self.gid, "language_en"), style=discord.ButtonStyle.primary,   custom_id="lang_en")
        bk = Button(label=t(self.gid, "back_btn"),    style=discord.ButtonStyle.secondary, custom_id="lang_bk")
        th.callback = self._make_cb("th")
        en.callback = self._make_cb("en")
        bk.callback = self._back
        self.add_item(Container(
            TextDisplay(_lang_text(self.gid)),
            Separator(),
            ActionRow(th, en),
            ActionRow(bk),
        ))

    def _make_cb(self, lang):
        async def cb(ix):
            cfg = load_config(self.gid); cfg["language"] = lang; save_config(self.gid, cfg)
            self._build()
            await ix.response.edit_message(view=self)
        return cb

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


