"""Configuration panel — /config (replaces /admin)."""
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

from aot_bot_instance import bot
from aot_shared import (
    t, load_config, save_config, load_players, save_players,
    select_options_from_list, format_currency,
)


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lang_display(cfg):
    return "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"

def _channels_display(cfg, guild):
    ids = cfg.get("announcement_channels", [])
    if not ids: return "*None configured*"
    names = []
    for cid in ids:
        ch = guild.get_channel(int(cid)) if guild else None
        names.append(f"<#{cid}>" if ch else f"`{cid}`")
    return ", ".join(names[:5]) + ("…" if len(names) > 5 else "")

def _role_preview(cfg, rtype, items, guild):
    mappings = cfg.get("roles", {}).get(rtype, {})
    lines = []
    for item in items[:4]:
        rid = mappings.get(item)
        role_str = f"<@&{rid}>" if rid else "*not set*"
        lines.append(f"**{item}** → {role_str}")
    if len(items) > 4: lines.append(f"*…+{len(items)-4} more*")
    return "\n".join(lines) if lines else "*None*"

def _ann_roles_display(cfg, guild):
    rids = cfg.get("announcement_permitted_roles", [])
    if not rids: return "*Admin only*"
    return ", ".join(f"<@&{r}>" for r in rids[:6])


# ── Currency modal ────────────────────────────────────────────────────────────

class CurrencyModal(Modal, title="Configure Currency"):
    f_name  = TextInput(label="Currency Name",    max_length=30, default="Coins")
    f_emoji = TextInput(label="Emoji (optional)", max_length=60, required=False)
    f_img   = TextInput(label="Image URL (optional)", max_length=300, required=False)

    def __init__(self, gid, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        cfg = load_config(gid)
        self.f_name.default  = cfg.get("currency_name", "Coins")
        self.f_emoji.default = cfg.get("currency_emoji", "")
        self.f_img.default   = cfg.get("currency_image", "")

    async def on_submit(self, ix):
        cfg = load_config(self.gid)
        cfg["currency_name"]  = self.f_name.value.strip() or "Coins"
        cfg["currency_emoji"] = (self.f_emoji.value or "").strip()
        cfg["currency_image"] = (self.f_img.value or "").strip()
        save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Role mapping sub-view ─────────────────────────────────────────────────────

class RoleMapView(LayoutView):
    def __init__(self, gid, rtype, items, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.rtype = rtype; self.items = items
        self.parent = parent; self.sel = None
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.gid)
        mappings = cfg.get("roles", {}).get(self.rtype, {})
        lines = [f"**{self.rtype.title()} Roles**", ""]
        for item in self.items:
            rid = mappings.get(item)
            lines.append(f"**{item}** → {'<@&'+str(rid)+'>' if rid else '*not set*'}")

        val_sel = Select(placeholder=f"Select {self.rtype}",
                         options=select_options_from_list(self.items, self.sel))
        val_sel.callback = self._val_cb

        rs = discord.ui.RoleSelect(placeholder="Assign Discord role")
        rs.callback = self._role_cb

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="rm_bk")
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay("\n".join(lines)), Separator(),
            ActionRow(val_sel), ActionRow(rs), ActionRow(bk),
        ))

    async def _val_cb(self, ix):
        self.sel = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _role_cb(self, ix):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid)
        cfg["roles"].setdefault(self.rtype, {})[self.sel] = ix.data["values"][0]
        save_config(self.gid, cfg); self._build()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── List management sub-view ──────────────────────────────────────────────────

class _AddModal(Modal):
    val = TextInput(label="Name", max_length=60)
    def __init__(self, gid, key, parent):
        super().__init__(title=f"Add to {key}")
        self.gid = gid; self.key = key; self.parent = parent
    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.val.value.strip()
        if v and v not in cfg.get(self.key, []):
            cfg.setdefault(self.key, []).append(v); save_config(self.gid, cfg)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class ListManageView(LayoutView):
    def __init__(self, gid, key, label, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.key = key; self.label = label
        self.parent = parent; self.sel = None
        self._build()

    def _build(self):
        self.clear_items()
        items = load_config(self.gid).get(self.key, [])
        lines = [f"**{self.label}**", ""] + [f"- {i}" for i in items] or ["*None*"]

        opts = (select_options_from_list(items, self.sel))
        sel = Select(placeholder="Select to remove", options=opts)
        sel.callback = self._sel

        add = Button(label="Add",    style=discord.ButtonStyle.green,     custom_id="lm_add")
        rem = Button(label="Remove", style=discord.ButtonStyle.danger,    custom_id="lm_rem")
        bk  = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="lm_bk")
        add.callback = self._add; rem.callback = self._rem; bk.callback = self._back

        self.add_item(Container(
            TextDisplay("\n".join(lines)), Separator(),
            ActionRow(sel), ActionRow(add, rem), ActionRow(bk),
        ))

    async def _sel(self, ix):
        self.sel = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _add(self, ix): await ix.response.send_modal(_AddModal(self.gid, self.key, self))

    async def _rem(self, ix):
        if not self.sel or self.sel == "__none__":
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid); lst = cfg.get(self.key, [])
        if self.sel in lst: lst.remove(self.sel)
        save_config(self.gid, cfg); self.sel = None; self._build()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Bloodlines sub-view ───────────────────────────────────────────────────────

class _BlModal(Modal):
    name = TextInput(label="Bloodline Name", max_length=60)
    def __init__(self, gid, key, parent):
        super().__init__(title=f"Add {'Special' if 'special' in key else 'Common'} Bloodline")
        self.gid = gid; self.key = key; self.parent = parent
    async def on_submit(self, ix):
        cfg = load_config(self.gid); v = self.name.value.strip()
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if v and v not in all_bl:
            cfg.setdefault(self.key, []).append(v); save_config(self.gid, cfg)
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class BloodlineManageView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.gid)
        common  = cfg.get("bloodlines_common", [])
        special = cfg.get("bloodlines_special", [])
        all_bl  = common + special
        text = ("**Manage Bloodlines**\n\n"
                f"**Common:** {', '.join(common) or '*None*'}\n"
                f"**Special:** {', '.join(special) or '*None*'}")

        opts = select_options_from_list(all_bl) if all_bl else [discord.SelectOption(label="—", value="__none__")]
        sel = Select(placeholder="Select to remove", options=opts)
        sel.callback = self._rem

        ac  = Button(label="Add Common",   style=discord.ButtonStyle.green,     custom_id="bl_ac")
        as_ = Button(label="Add Special",  style=discord.ButtonStyle.green,     custom_id="bl_as")
        bk  = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="bl_bk")
        ac.callback = lambda ix, k="bloodlines_common":  ix.response.send_modal(_BlModal(self.gid, k, self))
        as_.callback = lambda ix, k="bloodlines_special": ix.response.send_modal(_BlModal(self.gid, k, self))
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(sel), ActionRow(ac, as_), ActionRow(bk),
        ))

    async def _rem(self, ix):
        v = ix.data["values"][0]
        if v != "__none__":
            cfg = load_config(self.gid)
            for k in ("bloodlines_common", "bloodlines_special"):
                lst = cfg.get(k, [])
                if v in lst: lst.remove(v)
            save_config(self.gid, cfg)
        self._build(); await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Bloodline access sub-view ─────────────────────────────────────────────────

class BloodlineAccessView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self.sel_bl = None; self.sel_users = []
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.gid)
        acc = cfg.get("special_access", {})
        special = cfg.get("bloodlines_special", [])
        grants = "\n".join(f"  <@{uid}>: {', '.join(bls)}" for uid, bls in acc.items()) or "  *None*"
        text = (f"**Special Bloodline Access**\n\n"
                f"**Special BL:** {', '.join(special) or '*None*'}\n\n"
                f"**Grants:**\n{grants}")

        bl_sel = Select(placeholder="Bloodline",
                        options=select_options_from_list(special, self.sel_bl))
        bl_sel.callback = self._bl_cb

        us = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25)
        us.callback = self._user_cb

        grant  = Button(label="Grant",  style=discord.ButtonStyle.green,     custom_id="bla_gr")
        revoke = Button(label="Revoke", style=discord.ButtonStyle.danger,    custom_id="bla_rv")
        bk     = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="bla_bk")
        grant.callback  = self._grant
        revoke.callback = self._revoke
        bk.callback     = self._back

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(bl_sel), ActionRow(us),
            ActionRow(grant, revoke), ActionRow(bk),
        ))

    async def _bl_cb(self, ix):
        self.sel_bl = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _user_cb(self, ix):
        self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _grant(self, ix):
        if not self.sel_bl or not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid); acc = cfg.setdefault("special_access", {})
        for uid in self.sel_users:
            if self.sel_bl not in acc.get(uid, []):
                acc.setdefault(uid, []).append(self.sel_bl)
        save_config(self.gid, cfg)
        from aot_shared import cv2_dm
        for uid in self.sel_users:
            try:
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(uid))
                await cv2_dm(user, t(self.gid, "got_bloodline_dm", bloodline=self.sel_bl))
            except Exception: pass
        self._build(); await ix.response.edit_message(view=self)

    async def _revoke(self, ix):
        if not self.sel_bl or not self.sel_users:
            await ix.response.send_message(t(self.gid, "select_value_first"), ephemeral=True); return
        cfg = load_config(self.gid); acc = cfg.get("special_access", {})
        for uid in self.sel_users:
            lst = acc.get(uid, [])
            if self.sel_bl in lst: lst.remove(self.sel_bl)
            if not lst: acc.pop(uid, None)
        save_config(self.gid, cfg)
        self._build(); await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Main ConfigView (4 pages) ─────────────────────────────────────────────────

class ConfigMainView(LayoutView):
    def __init__(self, gid, guild=None):
        super().__init__(timeout=300)
        self.gid = gid; self.guild = guild
        self.page = 1; self.total_pages = 4
        self._build()

    def _build(self):
        self.clear_items()
        {1: self._p1_general,
         2: self._p2_roles,
         3: self._p3_lists,
         4: self._p4_permissions}[self.page]()

    def _nav_row(self):
        prev = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
                      custom_id="cfg_prev", disabled=(self.page == 1))
        nxt  = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
                      custom_id="cfg_next", disabled=(self.page == self.total_pages))
        prev.callback = self._prev; nxt.callback = self._next
        return ActionRow(prev, nxt)

    def _prev(self, *_): return None  # overridden below
    def _next(self, *_): return None

    def _p1_general(self):
        gid = self.gid; cfg = load_config(gid)
        cur_lang = "Thai 🇹🇭" if cfg.get("language", "th") == "th" else "English 🇬🇧"
        cur      = format_currency(0, cfg).split(" ", 1)[-1]  # show "0 Coins" style
        channels = _channels_display(cfg, self.guild)

        th_btn = Button(label="🇹🇭 Thai",     style=discord.ButtonStyle.primary,   custom_id="cfg_th")
        en_btn = Button(label="🇬🇧 English",  style=discord.ButtonStyle.primary,   custom_id="cfg_en")
        cc_btn = Button(label=t(gid,"configure_btn"), style=discord.ButtonStyle.secondary, custom_id="cfg_curr")
        add_ch = Button(label="+ Channel",    style=discord.ButtonStyle.green,     custom_id="cfg_addch")
        rem_ch = Button(label="— Channel",    style=discord.ButtonStyle.danger,    custom_id="cfg_remch")
        th_btn.callback = self._set_th; en_btn.callback = self._set_en
        cc_btn.callback = self._currency
        add_ch.callback = self._add_ch;  rem_ch.callback = self._rem_ch

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'config_title')}** — {t(gid,'config_page', page=1, total=4)} | {t(gid,'general_page')}"),
            Separator(),
            TextDisplay(f"**{t(gid,'language_section')}**\nCurrent: {cur_lang}"),
            ActionRow(th_btn, en_btn),
            Separator(),
            TextDisplay(f"**{t(gid,'currency_section')}**\n{cur}"),
            ActionRow(cc_btn),
            Separator(),
            TextDisplay(f"**{t(gid,'ann_channels_section')}**\n{channels}"),
            ActionRow(add_ch, rem_ch),
            Separator(),
            self._nav_row(),
        ))

    def _p2_roles(self):
        gid = self.gid; cfg = load_config(gid)
        factions  = cfg.get("factions", [])
        ranks     = cfg.get("ranks", [])
        bloodlines = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])

        def _role_btn(label, cid, cb):
            b = Button(label=label, style=discord.ButtonStyle.secondary, custom_id=cid)
            b.callback = cb; return b

        rf = _role_btn("Faction Roles",   "cfg_rf",  self._make_role_cb("faction",   factions))
        rr = _role_btn("Rank Roles",      "cfg_rr",  self._make_role_cb("rank",      ranks))
        rs = _role_btn("Shifter Roles",   "cfg_rs",  self._make_role_cb("shifter",   cfg.get("shifters",[])))
        rb = _role_btn("Bloodline Roles", "cfg_rb",  self._make_role_cb("bloodline", bloodlines))

        fac_prev = _role_preview(cfg, "faction",   factions[:3],    self.guild)
        rank_prev = _role_preview(cfg, "rank",     ranks[:3],       self.guild)
        bl_prev  = _role_preview(cfg, "bloodline", bloodlines[:3],  self.guild)

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'config_title')}** — {t(gid,'config_page', page=2, total=4)} | {t(gid,'roles_page')}"),
            Separator(),
            TextDisplay(f"**Faction Roles**\n{fac_prev}"),
            ActionRow(rf),
            Separator(),
            TextDisplay(f"**Rank Roles**\n{rank_prev}"),
            ActionRow(rr),
            Separator(),
            TextDisplay(f"**Bloodline Roles**\n{bl_prev}"),
            ActionRow(rs, rb),
            Separator(),
            self._nav_row(),
        ))

    def _p3_lists(self):
        gid = self.gid; cfg = load_config(gid)
        fac  = ", ".join(cfg.get("factions", [])[:5]) or "*None*"
        rnk  = ", ".join(cfg.get("ranks", [])[:5])    or "*None*"
        tit  = ", ".join(cfg.get("shifters", [])[:5]) or "*None*"

        def _lb(label, cid, cb):
            b = Button(label=label, style=discord.ButtonStyle.secondary, custom_id=cid)
            b.callback = cb; return b

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'config_title')}** — {t(gid,'config_page', page=3, total=4)} | {t(gid,'lists_page')}"),
            Separator(),
            TextDisplay(f"**Factions**\n{fac}"),
            ActionRow(_lb("Manage Factions",  "cfg_mf",  self._make_list_cb("factions",  "Factions"))),
            Separator(),
            TextDisplay(f"**Ranks**\n{rnk}"),
            ActionRow(_lb("Manage Ranks",     "cfg_mr",  self._make_list_cb("ranks",     "Ranks"))),
            Separator(),
            TextDisplay(f"**Titans**\n{tit}"),
            ActionRow(_lb("Manage Titans",    "cfg_mt",  self._make_list_cb("shifters",  "Titans"))),
            Separator(),
            TextDisplay("**Bloodlines** (Common + Special)"),
            ActionRow(_lb("Manage Bloodlines","cfg_mb",  self._bloodlines)),
            Separator(),
            self._nav_row(),
        ))

    def _p4_permissions(self):
        gid = self.gid; cfg = load_config(gid)
        ann_roles = _ann_roles_display(cfg, self.guild)

        add_r = Button(label="+ Announce Role", style=discord.ButtonStyle.green,  custom_id="cfg_arr")
        rem_r = Button(label="— Announce Role", style=discord.ButtonStyle.danger, custom_id="cfg_rrr")
        bl_a  = Button(label="Bloodline Access",style=discord.ButtonStyle.secondary, custom_id="cfg_bla")
        add_r.callback = self._add_ann_role; rem_r.callback = self._rem_ann_role
        bl_a.callback  = self._bl_access

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'config_title')}** — {t(gid,'config_page', page=4, total=4)} | {t(gid,'permissions_page')}"),
            Separator(),
            TextDisplay(f"**{t(gid,'ann_permitted_roles_section')}**\n{ann_roles}"),
            ActionRow(add_r, rem_r),
            Separator(),
            TextDisplay("**Special Bloodline Access**"),
            ActionRow(bl_a),
            Separator(),
            self._nav_row(),
        ))

    # ── navigation ──
    async def _prev(self, ix):
        self.page = max(1, self.page - 1); self._build()
        await ix.response.edit_message(view=self)

    async def _next(self, ix):
        self.page = min(self.total_pages, self.page + 1); self._build()
        await ix.response.edit_message(view=self)

    # ── page 1 callbacks ──
    def _make_lang_cb(self, lang):
        async def cb(ix):
            cfg = load_config(self.gid); cfg["language"] = lang; save_config(self.gid, cfg)
            self._build(); await ix.response.edit_message(view=self)
        return cb

    async def _set_th(self, ix): await self._make_lang_cb("th")(ix)
    async def _set_en(self, ix): await self._make_lang_cb("en")(ix)

    async def _currency(self, ix):
        await ix.response.send_modal(CurrencyModal(self.gid, self))

    async def _add_ch(self, ix):
        await ix.response.edit_message(view=_ChannelSelectView(self.gid, "add", self))

    async def _rem_ch(self, ix):
        await ix.response.edit_message(view=_ChannelSelectView(self.gid, "remove", self))

    # ── page 2 callbacks ──
    def _make_role_cb(self, rtype, items):
        async def cb(ix):
            await ix.response.edit_message(view=RoleMapView(self.gid, rtype, items, self))
        return cb

    # ── page 3 callbacks ──
    def _make_list_cb(self, key, label):
        async def cb(ix):
            await ix.response.edit_message(view=ListManageView(self.gid, key, label, self))
        return cb

    async def _bloodlines(self, ix):
        await ix.response.edit_message(view=BloodlineManageView(self.gid, self))

    # ── page 4 callbacks ──
    async def _add_ann_role(self, ix):
        await ix.response.edit_message(view=_AnnRoleView(self.gid, "add", self))

    async def _rem_ann_role(self, ix):
        await ix.response.edit_message(view=_AnnRoleView(self.gid, "remove", self))

    async def _bl_access(self, ix):
        await ix.response.edit_message(view=BloodlineAccessView(self.gid, self))


# ── Channel select helper views ───────────────────────────────────────────────

class _ChannelSelectView(LayoutView):
    def __init__(self, gid, mode, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mode = mode; self.parent = parent
        ch_sel = discord.ui.ChannelSelect(
            placeholder="Select channel",
            channel_types=[discord.ChannelType.text],
        )
        ch_sel.callback = self._cb
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="cs_bk")
        bk.callback = self._back
        label = "Add Announcement Channel" if mode == "add" else "Remove Announcement Channel"
        self.add_item(Container(
            TextDisplay(f"**{label}**"), Separator(),
            ActionRow(ch_sel), ActionRow(bk),
        ))

    async def _cb(self, ix):
        cid = str(ix.data["values"][0])
        cfg = load_config(self.gid)
        channels = cfg.setdefault("announcement_channels", [])
        if self.mode == "add" and cid not in channels:
            channels.append(cid)
        elif self.mode == "remove" and cid in channels:
            channels.remove(cid)
        save_config(self.gid, cfg)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _AnnRoleView(LayoutView):
    def __init__(self, gid, mode, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mode = mode; self.parent = parent
        rs = discord.ui.RoleSelect(placeholder="Select role")
        rs.callback = self._cb
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="ar_bk")
        bk.callback = self._back
        label = "Add" if mode == "add" else "Remove"
        self.add_item(Container(
            TextDisplay(f"**{label} Announcement Permission Role**"), Separator(),
            ActionRow(rs), ActionRow(bk),
        ))

    async def _cb(self, ix):
        rid = str(ix.data["values"][0])
        cfg = load_config(self.gid)
        roles = cfg.setdefault("announcement_permitted_roles", [])
        if self.mode == "add" and rid not in roles: roles.append(rid)
        elif self.mode == "remove" and rid in roles: roles.remove(rid)
        save_config(self.gid, cfg)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── /config command ───────────────────────────────────────────────────────────

@bot.tree.command(name="config", description="Configure bot settings",
                  description_localizations={"th": "ตั้งค่าบอท"})
@_is_admin()
async def config_cmd(ix: discord.Interaction):
    await ix.response.send_message(
        view=ConfigMainView(ix.guild_id, ix.guild), ephemeral=True)

@config_cmd.error
async def config_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
