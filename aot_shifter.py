"""Shifter system — /shifter group, abilities, moveset, stamina, 13-year timer."""
import time, uuid
import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import (LayoutView, Container, TextDisplay, Separator, ActionRow,
                        Button, Select, Modal, TextInput, MediaGallery)
from discord.components import MediaGalleryItem

from aot_bot_instance import bot
from aot_shared import (
    t, load_players, save_players, load_config, save_config,
    select_options_from_list, has_shifter_access, cv2_dm, is_url,
)


# ── Stamina helpers ───────────────────────────────────────────────────────────

def _regen_stamina(player: dict, cfg: dict) -> dict:
    now = time.time()
    interval_secs = cfg.get("stamina_regen_interval_minutes", 5) * 60
    last = player.get("stamina_last_regen", now - interval_secs)
    if now - last < interval_secs:
        return player
    amount = cfg.get("stamina_regen_amount", 5)
    player["stamina"] = min(
        player.get("max_stamina", 100),
        player.get("stamina", 0) + amount,
    )
    player["stamina_last_regen"] = now
    return player

def _stamina_bar(stamina: int, max_st: int) -> str:
    filled = int((stamina / max_st) * 10) if max_st else 0
    return f"{'▓'*filled}{'░'*(10-filled)} {stamina}/{max_st}"


# ── Abilities panel text ──────────────────────────────────────────────────────

def _abilities_text(gid, player, titan_name, power):
    stamina   = player.get("stamina", 100)
    max_st    = player.get("max_stamina", 100)
    abilities = (power or {}).get("abilities", [])
    cooldowns = player.get("ability_cooldowns", {})
    now       = time.time()

    lines = [
        f"**⚔️ {titan_name}**", "",
        f"**{t(gid,'stamina_label')}** — {_stamina_bar(stamina, max_st)}", "",
        f"**{t(gid,'abilities_title')}**", "",
    ]
    if abilities:
        for ab in abilities:
            if not ab.get("confirmed", True):
                lines.append(f"**{ab['name']}** — ⚙️ *Pending admin configuration*")
                lines.append("")
                continue
            cd_key  = f"{titan_name}:{ab['name']}"
            cd_exp  = cooldowns.get(cd_key, 0)
            cd_left = max(0, int((cd_exp - now) / 60))
            status  = f"⏳ {cd_left}m" if cd_left > 0 else "✅ Ready"
            lines.append(f"**{ab['name']}** — {ab.get('description','')[:60]}")
            lines.append(f"Cost: {ab.get('stamina_cost',0)} | CD: {ab.get('cooldown_minutes',0)}m | {status}")
            lines.append("")
    else:
        lines.append("*No abilities configured.*")
    return "\n".join(lines)


# ── CV2 public channel announcements ──────────────────────────────────────────

async def _send_transform_cv2(channel, gid, hide_name, uid, titan_name):
    if hide_name:
        text = t(gid, "transform_hidden")
    else:
        text = t(gid, "transform_public", name=f"<@{uid}>", titan=titan_name)
    v = LayoutView(timeout=None)
    v.add_item(Container(TextDisplay(text)))
    try:
        await channel.send(view=v)
    except Exception:
        pass

async def _send_deform_cv2(channel, gid, hide_name, uid):
    if hide_name:
        text = t(gid, "detransform_hidden")
    else:
        text = t(gid, "detransform_public", name=f"<@{uid}>")
    v = LayoutView(timeout=None)
    v.add_item(Container(TextDisplay(text)))
    try:
        await channel.send(view=v)
    except Exception:
        pass

async def _send_ability_cv2(channel, gid, hide_name, uid, ability, stamina, max_st):
    ab_name = ability["name"]
    ab_desc = ability.get("description", "")
    img_url = ability.get("image_url", "")
    bar     = _stamina_bar(stamina, max_st)

    if hide_name:
        header = t(gid, "ability_used_hidden", ability=ab_name)
    else:
        header = t(gid, "ability_used", name=f"<@{uid}>", ability=ab_name)

    lines = [header]
    if ab_desc:
        lines += ["", f"*{ab_desc}*"]
    lines += ["", f"**{t(gid,'stamina_label')}** — {bar}"]

    v = LayoutView(timeout=None)
    children = [TextDisplay("\n".join(lines))]
    if img_url and is_url(img_url):
        children.append(Separator())
        children.append(MediaGallery(MediaGalleryItem(media=img_url)))
    v.add_item(Container(*children))
    try:
        await channel.send(view=v)
    except Exception:
        pass


# ── Admin stamina notification ────────────────────────────────────────────────

async def _notify_admins_stamina(guild, uid, player, gid):
    if not guild: return
    member = guild.get_member(int(uid))
    name   = member.display_name if member else str(uid)
    msg    = t(gid, "admin_stamina_warn", name=name,
               stamina=player.get("stamina", 0), max=player.get("max_stamina", 100))
    for m in guild.members:
        if m.guild_permissions.administrator:
            await cv2_dm(m, msg)


# ── Shifter admin view ────────────────────────────────────────────────────────

class ShifterAdminView(LayoutView):
    def __init__(self, gid, guild=None):
        super().__init__(timeout=300)
        self.gid = gid; self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        cfg    = load_config(self.gid)
        titans = cfg.get("shifters", [])
        access = cfg.get("shifter_access", [])
        text   = (f"**{t(self.gid, 'shifter_admin_title')}**\n\n"
                  f"**Titans:** {', '.join(titans) or '*None*'}\n"
                  f"**Users with access:** {len(access)}")
        grant_btn   = Button(label=t(self.gid, "grant_btn"),   style=discord.ButtonStyle.green,     custom_id="sad_grant")
        revoke_btn  = Button(label=t(self.gid, "revoke_btn"),  style=discord.ButtonStyle.danger,    custom_id="sad_revoke")
        tracker_btn = Button(label=t(self.gid, "tracker_btn"), style=discord.ButtonStyle.secondary, custom_id="sad_track")
        done_btn    = Button(label=t(self.gid, "done_btn"),    style=discord.ButtonStyle.danger,    custom_id="sad_done")
        grant_btn.callback   = self._grant
        revoke_btn.callback  = self._revoke
        tracker_btn.callback = self._tracker
        done_btn.callback    = self._done
        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(grant_btn, revoke_btn),
            ActionRow(tracker_btn),
            ActionRow(done_btn),
        ))

    async def _grant(self, ix):
        from aot_admin import GrantShifterView
        await ix.response.edit_message(view=GrantShifterView(self.gid, self))

    async def _revoke(self, ix):
        from aot_admin import RevokeShView
        await ix.response.edit_message(view=RevokeShView(self.gid, self))

    async def _tracker(self, ix):
        from aot_admin import ShifterTrackerView
        await ix.response.edit_message(view=ShifterTrackerView(self.gid, self, ix.guild))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid, 'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── /shifter command group ────────────────────────────────────────────────────

shifter_group = app_commands.Group(
    name="shifter",
    description="Titan shifter commands",
    description_localizations={"th": "คำสั่งผู้ถือพลังไทแทน"},
)

@shifter_group.command(name="open", description="Open your titan shifter panel",
                       description_localizations={"th": "เปิดแผงผู้ถือพลังไทแทน"})
async def shifter_open(ix: discord.Interaction):
    gid = ix.guild_id; uid = ix.user.id
    if not has_shifter_access(gid, uid):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(gid, "no_permission"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    players = load_players(gid)
    player  = players.get(str(uid), {})
    if not player.get("titan_powers"):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(gid, "no_titan_power"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(view=ShifterMainView(uid, gid), ephemeral=True)

@shifter_group.command(name="admin", description="Shifter admin panel",
                       description_localizations={"th": "แผงผู้ดูแลระบบผู้ถือพลัง"})
async def shifter_admin(ix: discord.Interaction):
    if not ix.guild: return
    m = ix.guild.get_member(ix.user.id)
    if not m or not (m.guild_permissions.administrator or m.guild_permissions.manage_guild):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(ix.guild_id, "admin_only"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(view=ShifterAdminView(ix.guild_id, ix.guild), ephemeral=True)

bot.tree.add_command(shifter_group)


# ── ShifterMainView ───────────────────────────────────────────────────────────

class ShifterMainView(LayoutView):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid
        self.hide_name = False; self.sel_titan = None; self.sel_ability = None
        self._build()

    def _build(self):
        self.clear_items()
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        powers  = player.get("titan_powers", [])

        if not powers:
            self.add_item(Container(TextDisplay(t(self.gid, "no_titan_power"))))
            return

        if not self.sel_titan or not any(p["titan"] == self.sel_titan for p in powers):
            self.sel_titan = powers[0]["titan"]

        power = next((p for p in powers if p["titan"] == self.sel_titan), powers[0])

        if player.get("transformed"):
            self._build_transformed(player, power)
        else:
            self._build_untransformed(player, power)

    def _build_untransformed(self, player, power):
        gid        = self.gid
        powers     = player.get("titan_powers", [])
        titan_name = power.get("titan", "?")
        stamina    = player.get("stamina", 100)
        max_st     = player.get("max_stamina", 100)
        bar        = _stamina_bar(stamina, max_st)
        now        = time.time()
        days_left  = max(0, int((power.get("expires_at", 0) - now) / 86400))

        cooldown_until  = player.get("transform_cooldown_until", 0)
        in_cooldown     = cooldown_until > now
        transform_disabled = in_cooldown

        text_parts = [
            f"**⚔️ {titan_name}**", "",
            f"**{t(gid,'stamina_label')}** — {bar}",
            f"**{t(gid,'time_left_label')}** — {days_left}d",
        ]
        if in_cooldown:
            mins_left = int((cooldown_until - now) / 60) + 1
            text_parts.append(f"**⏳ Transform Cooldown:** {mins_left}m")

        container_children = [TextDisplay("\n".join(text_parts)), Separator()]

        if len(powers) > 1:
            opts = [discord.SelectOption(label=p["titan"], value=p["titan"],
                                          default=(p["titan"] == titan_name)) for p in powers]
            ts = Select(placeholder="Select Titan form", options=opts)
            ts.callback = self._titan_cb
            container_children.append(ActionRow(ts))

        hide_lbl    = t(gid, "show_username_btn") if self.hide_name else t(gid, "hide_username_btn")
        hide_btn    = Button(label=hide_lbl,                   style=discord.ButtonStyle.secondary, custom_id="sh_hide")
        transform_b = Button(label="⚔️ Transform!",            style=discord.ButtonStyle.danger,    custom_id="sh_transform", disabled=transform_disabled)
        moveset_b   = Button(label=t(gid, "edit_moveset_btn"), style=discord.ButtonStyle.secondary, custom_id="sh_moveset")
        refresh_b   = Button(label="🔄 Refresh",               style=discord.ButtonStyle.secondary, custom_id="sh_refresh")
        hide_btn.callback    = self._toggle_hide
        transform_b.callback = self._transform
        moveset_b.callback   = self._open_moveset
        refresh_b.callback   = self._refresh

        container_children.append(ActionRow(hide_btn, transform_b))
        container_children.append(ActionRow(moveset_b, refresh_b))
        self.add_item(Container(*container_children))

    def _build_transformed(self, player, power):
        gid        = self.gid
        titan_name = power.get("titan", "?")
        abilities  = power.get("abilities", [])
        text       = _abilities_text(gid, player, titan_name, power)

        cooldowns = player.get("ability_cooldowns", {})
        now       = time.time()
        opts = ([discord.SelectOption(
                    label=ab["name"][:100], value=ab["name"],
                    description=(
                        "⚙️ Pending config" if not ab.get("confirmed", True)
                        else f"Cost:{ab.get('stamina_cost',0)} CD:{ab.get('cooldown_minutes',0)}m"
                    )[:100],
                    default=(ab["name"] == self.sel_ability))
                 for ab in abilities[:25]]
                or [discord.SelectOption(label="No abilities", value="__none__")])

        sel = Select(placeholder="Select ability", options=opts)
        sel.callback = self._sel_ab

        use_b     = Button(label=t(gid, "use_ability_btn"),  style=discord.ButtonStyle.danger,    custom_id="sh_use")
        moveset_b = Button(label=t(gid, "edit_moveset_btn"), style=discord.ButtonStyle.secondary, custom_id="sh_moveset2")
        deform_b  = Button(label=t(gid, "detransform_btn"),  style=discord.ButtonStyle.secondary, custom_id="sh_deform")
        refresh_b = Button(label="🔄 Refresh",               style=discord.ButtonStyle.secondary, custom_id="sh_refresh2")
        use_b.callback     = self._use
        moveset_b.callback = self._open_moveset
        deform_b.callback  = self._deform
        refresh_b.callback = self._refresh

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(sel),
            ActionRow(use_b, moveset_b),
            ActionRow(deform_b, refresh_b),
        ))

    async def _titan_cb(self, ix):
        self.sel_titan   = ix.data["values"][0]
        self.sel_ability = None
        self._build()
        await ix.response.edit_message(view=self)

    async def _sel_ab(self, ix):
        self.sel_ability = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _toggle_hide(self, ix):
        self.hide_name = not self.hide_name
        self._build()
        await ix.response.edit_message(view=self)

    async def _refresh(self, ix):
        self._build()
        await ix.response.edit_message(view=self)

    async def _transform(self, ix: discord.Interaction):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        cfg     = load_config(self.gid);  player  = _regen_stamina(player, cfg)
        now     = time.time()

        cooldown_until = player.get("transform_cooldown_until", 0)
        if cooldown_until > now:
            mins_left = int((cooldown_until - now) / 60) + 1
            await ix.response.send_message(
                t(self.gid, "transform_cooldown_msg", mins=mins_left), ephemeral=True); return

        min_st = cfg.get("transform_min_stamina", 30)
        if player.get("stamina", 100) < min_st:
            await ix.response.send_message(t(self.gid, "stamina_low"), ephemeral=True); return

        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            await ix.response.send_message(t(self.gid, "no_titan_power"), ephemeral=True); return

        player["transformed"] = True
        players[str(self.uid)] = player
        save_players(self.gid, players)
        self._build()
        await ix.response.edit_message(view=self)
        await _send_transform_cv2(ix.channel, self.gid, self.hide_name, self.uid, self.sel_titan)

    async def _deform(self, ix: discord.Interaction):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        player["transformed"] = False
        player.pop("transform_cooldown_until", None)
        players[str(self.uid)] = player
        save_players(self.gid, players)
        self._build()
        await ix.response.edit_message(view=self)
        await _send_deform_cv2(ix.channel, self.gid, self.hide_name, self.uid)

    async def _use(self, ix: discord.Interaction):
        if not self.sel_ability or self.sel_ability == "__none__":
            await ix.response.send_message("Select an ability first.", ephemeral=True); return

        players = load_players(self.gid); player = players.get(str(self.uid), {})
        cfg     = load_config(self.gid);  player  = _regen_stamina(player, cfg)
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            await ix.response.send_message(t(self.gid, "no_titan_power"), ephemeral=True); return

        ability = next((a for a in power.get("abilities", []) if a["name"] == self.sel_ability), None)
        if not ability:
            await ix.response.send_message("Ability not found.", ephemeral=True); return

        if not ability.get("confirmed", True):
            await ix.response.send_message(t(self.gid, "ability_pending_config"), ephemeral=True); return

        cd_key    = f"{self.sel_titan}:{ability['name']}"
        cooldowns = player.get("ability_cooldowns", {})
        now       = time.time()

        if cooldowns.get(cd_key, 0) > now:
            mins_left = int((cooldowns[cd_key] - now) / 60) + 1
            await ix.response.send_message(
                t(self.gid, "cooldown_remaining", mins=mins_left), ephemeral=True); return

        cost = ability.get("stamina_cost", 0)
        if player.get("stamina", 100) < cost:
            await ix.response.send_message(t(self.gid, "stamina_low"), ephemeral=True)
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid); return

        player["stamina"]            = max(0, player.get("stamina", 100) - cost)
        cooldowns[cd_key]            = now + ability.get("cooldown_minutes", 0) * 60
        player["ability_cooldowns"]  = cooldowns

        auto_deformed = False
        if player["stamina"] <= 0:
            player["transformed"]            = False
            cd_mins                          = cfg.get("auto_deform_cooldown_minutes", 60)
            player["transform_cooldown_until"] = now + cd_mins * 60
            auto_deformed                    = True

        players[str(self.uid)] = player
        save_players(self.gid, players)

        self._build()
        await ix.response.edit_message(view=self)
        await _send_ability_cv2(ix.channel, self.gid, self.hide_name, self.uid,
                                 ability, player["stamina"], player.get("max_stamina", 100))
        if auto_deformed:
            await cv2_dm(ix.user, t(self.gid, "stamina_empty"))
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid)

    async def _open_moveset(self, ix: discord.Interaction):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            await ix.response.send_message(t(self.gid, "no_titan_power"), ephemeral=True); return
        await ix.response.edit_message(view=MovesetEditorView(self.uid, self.gid, self.sel_titan, power, self))


# ── Moveset Editor ────────────────────────────────────────────────────────────

class MovesetEditorView(LayoutView):
    def __init__(self, uid, gid, titan_name, power, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.titan_name = titan_name
        self.power = power or {}; self.parent = parent; self.sel = None
        self._build()

    def _build(self):
        self.clear_items()
        abilities = self.power.get("abilities", [])
        opts = [discord.SelectOption(
                    label=f"{a['name'][:90]} {'⚙️' if not a.get('confirmed', True) else ''}",
                    value=a["name"])
                for a in abilities[:24]]
        opts.append(discord.SelectOption(label="+ Add New Ability", value="__new__"))

        sel = Select(placeholder="Select ability", options=opts)
        sel.callback = self._sel

        ed  = Button(label=t(self.gid, "edit_ability_btn"),   style=discord.ButtonStyle.primary,   custom_id="me_ed")
        dlt = Button(label=t(self.gid, "delete_ability_btn"), style=discord.ButtonStyle.danger,    custom_id="me_dlt")
        bk  = Button(label=t(self.gid, "back_btn"),           style=discord.ButtonStyle.secondary, custom_id="me_bk")
        ed.callback  = self._edit
        dlt.callback = self._delete
        bk.callback  = self._back

        self.add_item(Container(
            TextDisplay(f"**{t(self.gid,'edit_moveset_btn')}**\n\nSelect an ability to edit, or choose *+ Add New Ability*.\n*(⚙️ = pending admin configuration)*"),
            Separator(),
            ActionRow(sel),
            ActionRow(ed, dlt),
            ActionRow(bk),
        ))

    async def _sel(self, ix):
        self.sel = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _edit(self, ix: discord.Interaction):
        if not self.sel: await ix.response.send_message("Select an ability first.", ephemeral=True); return
        prefill = {} if self.sel == "__new__" else next(
            (a for a in self.power.get("abilities", []) if a["name"] == self.sel), {})
        await ix.response.send_modal(
            EditAbilityModal(self.uid, self.gid, self.titan_name, self.power, self, prefill, is_new=(self.sel == "__new__")))

    async def _delete(self, ix: discord.Interaction):
        if not self.sel or self.sel == "__new__":
            await ix.response.send_message("Select an existing ability.", ephemeral=True); return
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Only admins can delete abilities.", ephemeral=True); return
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        for pw in player.get("titan_powers", []):
            if pw["titan"] == self.titan_name:
                pw["abilities"] = [a for a in pw.get("abilities", []) if a["name"] != self.sel]
                self.power = pw
        save_players(self.gid, players)
        self.sel = None; self._build()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.titan_name), self.power)
        if hasattr(self.parent, "power"):
            self.parent.power = power
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Edit Ability Modal (simplified: name, desc, image only) ──────────────────

class EditAbilityModal(Modal, title="Edit Ability"):
    f_name  = TextInput(label="Ability Name",           max_length=60)
    f_desc  = TextInput(label="Description",            style=discord.TextStyle.paragraph, max_length=300, required=False)
    f_image = TextInput(label="Image URL (optional)",   max_length=500, required=False)

    def __init__(self, uid, gid, titan_name, power, parent, prefill, is_new):
        super().__init__()
        self.uid = uid; self.gid = gid; self.titan_name = titan_name
        self.power = power; self.parent = parent; self.is_new = is_new; self.prefill = prefill
        if prefill:
            self.f_name.default  = prefill.get("name", "")
            self.f_desc.default  = prefill.get("description", "")
            self.f_image.default = prefill.get("image_url", "")

    async def on_submit(self, ix: discord.Interaction):
        ability_data = {
            "name":        self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "image_url":   (self.f_image.value or "").strip(),
        }
        req_id = str(uuid.uuid4())[:8]
        cfg    = load_config(self.gid)
        cfg.setdefault("pending_moveset_requests", {})[req_id] = {
            "user_id":  str(self.uid),
            "titan":    self.titan_name,
            "ability":  ability_data,
            "is_new":   self.is_new,
            "old_name": self.prefill.get("name", ""),
            "ts":       time.time(),
        }
        save_config(self.gid, cfg)
        await _notify_admins_moveset(ix.guild, req_id, self.uid, ability_data, self.gid)
        self.parent.clear_items()
        self.parent.add_item(Container(
            TextDisplay(f"**{t(self.gid,'edit_moveset_btn')}**\n\n{t(self.gid,'moveset_pending')}"),
        ))
        await ix.response.edit_message(view=self.parent)


async def _apply_ability_edit(uid, gid, titan_name, ability, is_new, old_name):
    players = load_players(gid); player = players.get(str(uid), {})
    for pw in player.get("titan_powers", []):
        if pw["titan"] == titan_name:
            if is_new:
                pw.setdefault("abilities", []).append(ability)
            else:
                for i, a in enumerate(pw.get("abilities", [])):
                    if a["name"] == old_name:
                        pw["abilities"][i] = ability; break
    save_players(gid, players)


async def _notify_admins_moveset(guild, req_id, uid, ability_data, gid):
    if not guild: return
    member = guild.get_member(int(uid))
    name   = member.display_name if member else str(uid)
    for m in guild.members:
        if m.guild_permissions.administrator:
            try:
                view = MovesetConfigView(gid, req_id, uid, ability_data, name)
                dm   = await m.create_dm()
                await dm.send(view=view)
            except Exception: pass


# ── MovesetConfigView — admin DM to set cooldown & stamina cost ───────────────

class MovesetConfigView(LayoutView):
    def __init__(self, gid, req_id, uid, ability_data, requester_name):
        super().__init__(timeout=86400)
        self.gid = gid; self.req_id = req_id; self.uid = uid
        self.ability_data   = dict(ability_data)
        self.requester_name = requester_name
        self.cd_minutes     = 0
        self.stamina_cost   = 0
        self._build()

    def _build(self):
        self.clear_items()
        ab      = self.ability_data
        img_url = ab.get("image_url", "")
        text    = (
            f"**⚙️ Ability Configuration** — from **{self.requester_name}**\n\n"
            f"**Ability:** {ab['name']}\n"
            f"**Description:** {ab.get('description') or '*None*'}\n\n"
            f"**Cooldown:** {self.cd_minutes} minutes\n"
            f"**Stamina Cost:** {self.stamina_cost}"
        )
        cd_btn      = Button(label="⏱ Set Cooldown",     style=discord.ButtonStyle.secondary, custom_id="mcfg_cd")
        cost_btn    = Button(label="💪 Set Stamina Cost", style=discord.ButtonStyle.secondary, custom_id="mcfg_cost")
        confirm_btn = Button(label="✅ Confirm",          style=discord.ButtonStyle.green,     custom_id="mcfg_ok")
        decline_btn = Button(label="❌ Decline",          style=discord.ButtonStyle.danger,    custom_id="mcfg_no")
        cd_btn.callback      = self._set_cd
        cost_btn.callback    = self._set_cost
        confirm_btn.callback = self._confirm
        decline_btn.callback = self._decline

        children = [TextDisplay(text), Separator()]
        if img_url and is_url(img_url):
            children.append(MediaGallery(MediaGalleryItem(media=img_url)))
            children.append(Separator())
        children.append(ActionRow(cd_btn, cost_btn))
        children.append(ActionRow(confirm_btn, decline_btn))
        self.add_item(Container(*children))

    async def _set_cd(self, ix):   await ix.response.send_modal(_AbilityCDModal(self))
    async def _set_cost(self, ix): await ix.response.send_modal(_AbilityCostModal(self))

    async def _confirm(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)
        if req:
            final_ability = {
                "name":             self.ability_data["name"],
                "description":      self.ability_data.get("description", ""),
                "image_url":        self.ability_data.get("image_url", ""),
                "cooldown_minutes": self.cd_minutes,
                "stamina_cost":     self.stamina_cost,
                "confirmed":        True,
            }
            await _apply_ability_edit(req["user_id"], self.gid, req["titan"],
                                      final_ability, req["is_new"], req["old_name"])
            try:
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(req["user_id"]))
                await cv2_dm(user, t(self.gid, "moveset_approved", ability=final_ability["name"]))
            except Exception: pass
        self.clear_items()
        self.add_item(Container(TextDisplay("✅ Ability confirmed and configured.")))
        await ix.response.edit_message(view=self)

    async def _decline(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)
        if req:
            try:
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(req["user_id"]))
                await cv2_dm(user, t(self.gid, "moveset_declined", ability=req["ability"]["name"]))
            except Exception: pass
        self.clear_items()
        self.add_item(Container(TextDisplay("❌ Declined and removed.")))
        await ix.response.edit_message(view=self)


class _AbilityCDModal(Modal, title="Set Cooldown"):
    cd = TextInput(label="Cooldown (minutes)", max_length=5)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.cd.default = str(parent.cd_minutes)
    async def on_submit(self, ix):
        try: self.parent.cd_minutes = max(0, int(self.cd.value.strip() or "0"))
        except ValueError: pass
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class _AbilityCostModal(Modal, title="Set Stamina Cost"):
    cost = TextInput(label="Stamina Cost", max_length=5)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.cost.default = str(parent.stamina_cost)
    async def on_submit(self, ix):
        try: self.parent.stamina_cost = max(0, int(self.cost.value.strip() or "0"))
        except ValueError: pass
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Background tasks ──────────────────────────────────────────────────────────

@tasks.loop(minutes=10)
async def check_titan_expiry():
    import random
    for guild in bot.guilds:
        gid = guild.id; cfg = load_config(gid); players = load_players(gid)
        now = time.time(); changed = False
        for uid, player in list(players.items()):
            powers = player.get("titan_powers", [])
            if not powers or player.get("deceased"): continue
            if powers[0].get("expires_at", float("inf")) > now: continue
            titan_names = [p["titan"] for p in powers]
            player["deceased"] = True; player["titan_powers"] = []
            players[uid] = player; changed = True

            eligible = []
            for mid, mp in players.items():
                if mid == uid or mp.get("deceased"): continue
                if mp.get("faction") in cfg.get("factions", []):
                    if mp.get("bloodline") in (cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])):
                        member = guild.get_member(int(mid))
                        if member: eligible.append((mid, mp, member))

            for titan in titan_names:
                new_owner_data = random.choice(eligible) if eligible else None
                old_member     = guild.get_member(int(uid))
                old_name       = old_member.display_name if old_member else uid
                if new_owner_data:
                    new_uid, new_player, new_member = new_owner_data
                    titan_days = cfg.get("titan_time_days", 4745)
                    new_power  = {"titan": titan, "acquired_at": now,
                                  "expires_at": now + titan_days * 86400, "abilities": []}
                    existing = new_player.get("titan_powers", [])
                    if existing: new_power["expires_at"] = existing[0]["expires_at"]
                    new_player.setdefault("titan_powers", []).append(new_power)
                    players[new_uid] = new_player
                    await cv2_dm(new_member, t(gid, "got_titan_dm", titan=titan))
                    new_name = new_member.display_name
                    for m in guild.members:
                        if m.guild_permissions.administrator:
                            await cv2_dm(m, t(gid, "admin_got_titan", new_owner=new_name, titan=titan, old_owner=old_name))
                    ch_id = cfg.get("titan_announcement_channel")
                    if ch_id:
                        ch = guild.get_channel(int(ch_id))
                        if ch:
                            try: await ch.send(t(gid, "titan_died", name=old_name, titan=titan, new_owner=new_name))
                            except Exception: pass
        if changed: save_players(gid, players)


@tasks.loop(minutes=1)
async def regen_stamina_task():
    for guild in bot.guilds:
        gid = guild.id; cfg = load_config(gid)
        players = load_players(gid); changed = False
        for uid, player in players.items():
            if player.get("stamina", 100) < player.get("max_stamina", 100):
                old    = player.get("stamina", 100)
                player = _regen_stamina(player, cfg)
                if player["stamina"] != old: players[uid] = player; changed = True
        if changed: save_players(gid, players)


def start_tasks():
    if not check_titan_expiry.is_running(): check_titan_expiry.start()
    if not regen_stamina_task.is_running():  regen_stamina_task.start()
