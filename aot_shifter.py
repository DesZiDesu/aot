"""Shifter system — /shifter command, abilities, moveset, stamina, 13-year timer."""
import time, uuid
import discord
from discord.ext import tasks
from discord.ui import LayoutView, Container, TextDisplay, Separator, ActionRow, Button, Select, Modal, TextInput

from aot_bot_instance import bot
from aot_shared import (
    t, load_players, save_players, load_config, save_config,
    select_options_from_list, has_shifter_access, cv2_dm,
)


# ── Stamina helpers ───────────────────────────────────────────────────────────

def _regen_stamina(player: dict, cfg: dict) -> dict:
    now = time.time()
    last = player.get("stamina_last_update", now)
    elapsed_mins = (now - last) / 60
    regen = cfg.get("stamina_regen_per_minute", 1)
    player["stamina"] = min(
        player.get("max_stamina", 100),
        player.get("stamina", 100) + int(elapsed_mins * regen),
    )
    player["stamina_last_update"] = now
    return player

def _stamina_bar(stamina: int, max_st: int) -> str:
    filled = int((stamina / max_st) * 10) if max_st else 0
    return f"{'▓'*filled}{'░'*(10-filled)} {stamina}/{max_st}"


# ── Abilities text ────────────────────────────────────────────────────────────

def _abilities_text(gid, player, titan_name, power):
    stamina   = player.get("stamina", 100)
    max_st    = player.get("max_stamina", 100)
    abilities = (power or {}).get("abilities", [])
    cooldowns = player.get("ability_cooldowns", {})
    now = time.time()

    lines = [
        f"**⚔️ {titan_name}**",
        "",
        f"**{t(gid,'stamina_label')}** — {_stamina_bar(stamina, max_st)}",
        "",
        f"**{t(gid,'abilities_title')}**",
        "",
    ]
    if abilities:
        for ab in abilities:
            cd_key  = f"{titan_name}:{ab['name']}"
            cd_exp  = cooldowns.get(cd_key, 0)
            cd_left = max(0, int((cd_exp - now) / 60))
            status  = f"⏳ {cd_left}m" if cd_left > 0 else "✅ Ready"
            lines.append(f"**{ab['name']}** — {ab.get('description','')[:60]}")
            lines.append(f"Cost: {ab.get('stamina_cost',0)} stamina | CD: {ab.get('cooldown_minutes',0)}m | {status}")
            lines.append("")
    else:
        lines.append("*No abilities configured.*")

    return "\n".join(lines)


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


# ── /shifter command ──────────────────────────────────────────────────────────

@bot.tree.command(name="shifter", description="Titan shifter panel")
async def shifter_cmd(ix: discord.Interaction):
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

        text = "\n".join([
            f"**⚔️ {titan_name}**",
            "",
            f"**{t(gid,'stamina_label')}** — {bar}",
            f"**{t(gid,'time_left_label')}** — {days_left}d",
        ])

        container_children = [TextDisplay(text), Separator()]

        if len(powers) > 1:
            opts = [discord.SelectOption(label=p["titan"], value=p["titan"],
                                          default=(p["titan"] == titan_name)) for p in powers]
            ts = Select(placeholder="Select Titan form", options=opts)
            ts.callback = self._titan_cb
            container_children.append(ActionRow(ts))

        hide_lbl    = t(gid, "show_username_btn") if self.hide_name else t(gid, "hide_username_btn")
        hide_btn    = Button(label=hide_lbl,                   style=discord.ButtonStyle.secondary, custom_id="sh_hide")
        transform_b = Button(label="⚔️ Transform!",            style=discord.ButtonStyle.danger,    custom_id="sh_transform")
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

        opts = ([discord.SelectOption(
                    label=ab["name"][:100], value=ab["name"],
                    description=f"Cost:{ab.get('stamina_cost',0)} CD:{ab.get('cooldown_minutes',0)}m"[:100],
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
            TextDisplay(text),
            Separator(),
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
        cfg = load_config(self.gid); player = _regen_stamina(player, cfg)

        if player.get("stamina", 100) < 10:
            await ix.response.send_message(t(self.gid, "stamina_low"), ephemeral=True); return

        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            await ix.response.send_message(t(self.gid, "no_titan_power"), ephemeral=True); return

        player["transformed"] = True; players[str(self.uid)] = player; save_players(self.gid, players)

        name = ix.user.display_name
        pub  = (t(self.gid, "transform_hidden") if self.hide_name
                else t(self.gid, "transform_public", name=name, titan=self.sel_titan))
        try: await ix.channel.send(pub)
        except Exception: pass

        self._build()
        await ix.response.edit_message(view=self)

    async def _deform(self, ix: discord.Interaction):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        player["transformed"] = False; players[str(self.uid)] = player; save_players(self.gid, players)
        try: await ix.channel.send(t(self.gid, "detransform_public", name=ix.user.display_name))
        except Exception: pass
        self._build()
        await ix.response.edit_message(view=self)

    async def _use(self, ix: discord.Interaction):
        if not self.sel_ability or self.sel_ability == "__none__":
            await ix.response.send_message("Select an ability first.", ephemeral=True); return

        players = load_players(self.gid); player = players.get(str(self.uid), {})
        cfg     = load_config(self.gid); player  = _regen_stamina(player, cfg)
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power: await ix.response.send_message(t(self.gid, "no_titan_power"), ephemeral=True); return

        ability = next((a for a in power.get("abilities", []) if a["name"] == self.sel_ability), None)
        if not ability: await ix.response.send_message("Ability not found.", ephemeral=True); return

        cd_key    = f"{self.sel_titan}:{ability['name']}"
        cooldowns = player.get("ability_cooldowns", {})
        now       = time.time()

        if cooldowns.get(cd_key, 0) > now:
            mins_left = int((cooldowns[cd_key] - now) / 60) + 1
            await ix.response.send_message(t(self.gid, "cooldown_remaining", mins=mins_left), ephemeral=True); return

        cost = ability.get("stamina_cost", 0)
        if player.get("stamina", 100) < cost:
            await ix.response.send_message(t(self.gid, "stamina_low"), ephemeral=True)
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid); return

        player["stamina"] = max(0, player.get("stamina", 100) - cost)
        cooldowns[cd_key] = now + ability.get("cooldown_minutes", 0) * 60
        player["ability_cooldowns"] = cooldowns
        players[str(self.uid)] = player
        save_players(self.gid, players)

        try: await ix.channel.send(t(self.gid, "ability_used", name=ix.user.display_name, ability=ability["name"]))
        except Exception: pass

        if player["stamina"] <= 0:
            player["transformed"] = False; players[str(self.uid)] = player; save_players(self.gid, players)
            await cv2_dm(ix.user, t(self.gid, "stamina_empty"))
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid)

        self._build()
        await ix.response.edit_message(view=self)

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
        opts = [discord.SelectOption(label=a["name"][:100], value=a["name"]) for a in abilities[:24]]
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
            TextDisplay(f"**{t(self.gid,'edit_moveset_btn')}**\n\nSelect an ability to edit, or choose *+ Add New Ability*."),
            Separator(),
            ActionRow(sel),
            ActionRow(ed, dlt),
            ActionRow(bk),
        ))

    async def _sel(self, ix):
        self.sel = ix.data["values"][0]; self._build()
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


class EditAbilityModal(Modal, title="Edit Ability"):
    f_name = TextInput(label="Ability Name",        max_length=60)
    f_desc = TextInput(label="Description",         style=discord.TextStyle.paragraph, max_length=300, required=False)
    f_cd   = TextInput(label="Cooldown (minutes)",  max_length=5, default="30")
    f_cost = TextInput(label="Stamina Cost",        max_length=5, default="10")

    def __init__(self, uid, gid, titan_name, power, parent, prefill, is_new):
        super().__init__()
        self.uid = uid; self.gid = gid; self.titan_name = titan_name
        self.power = power; self.parent = parent; self.is_new = is_new; self.prefill = prefill
        if prefill:
            self.f_name.default = prefill.get("name", "")
            self.f_desc.default = prefill.get("description", "")
            self.f_cd.default   = str(prefill.get("cooldown_minutes", 30))
            self.f_cost.default = str(prefill.get("stamina_cost", 10))

    async def on_submit(self, ix: discord.Interaction):
        ability = {
            "name":             self.f_name.value.strip(),
            "description":      (self.f_desc.value or "").strip(),
            "cooldown_minutes": max(0, int(self.f_cd.value.strip() or 0)),
            "stamina_cost":     max(0, int(self.f_cost.value.strip() or 0)),
        }
        if ix.user.guild_permissions.administrator:
            await _apply_ability_edit(self.uid, self.gid, self.titan_name, ability, self.is_new, self.prefill.get("name", ""))
            players = load_players(self.gid); player = players.get(str(self.uid), {})
            power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.titan_name), self.power)
            grandparent = self.parent.parent
            if hasattr(grandparent, "power"):
                grandparent.power = power
            grandparent._build()
            await ix.response.edit_message(view=grandparent)
        else:
            req_id = str(uuid.uuid4())[:8]
            cfg    = load_config(self.gid)
            cfg.setdefault("pending_moveset_requests", {})[req_id] = {
                "user_id":  str(self.uid),
                "titan":    self.titan_name,
                "ability":  ability,
                "is_new":   self.is_new,
                "old_name": self.prefill.get("name", ""),
                "ts":       time.time(),
            }
            save_config(self.gid, cfg)
            await _notify_admins_moveset(ix.guild, req_id, self.uid, ability, self.gid)
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
                    if a["name"] == old_name: pw["abilities"][i] = ability; break
    save_players(gid, players)


async def _notify_admins_moveset(guild, req_id, uid, ability, gid):
    if not guild: return
    member = guild.get_member(int(uid))
    name   = member.display_name if member else str(uid)
    for m in guild.members:
        if m.guild_permissions.administrator:
            try:
                view = MovesetApprovalView(gid, req_id, uid, ability, name)
                dm = await m.create_dm()
                await dm.send(view=view)
            except Exception: pass


class MovesetApprovalView(LayoutView):
    def __init__(self, gid, req_id, uid, ability, requester_name):
        super().__init__(timeout=86400)
        self.gid = gid; self.req_id = req_id; self.uid = uid
        ap = Button(label=t(gid, "approve_btn"), style=discord.ButtonStyle.green, custom_id="mva_ap")
        de = Button(label=t(gid, "decline_btn"), style=discord.ButtonStyle.danger, custom_id="mva_de")
        ap.callback = self._approve
        de.callback = self._decline
        self.add_item(Container(
            TextDisplay(
                f"**📝 Moveset Edit Request** from **{requester_name}**\n\n"
                f"**Ability:** {ability['name']}\n"
                f"**Description:** {ability.get('description','')}\n"
                f"**CD:** {ability.get('cooldown_minutes',0)}m | "
                f"**Cost:** {ability.get('stamina_cost',0)}\n"
                f"**Request ID:** `{req_id}`"
            ),
            Separator(),
            ActionRow(ap, de),
        ))

    async def _approve(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)
        if req:
            await _apply_ability_edit(req["user_id"], self.gid, req["titan"],
                                      req["ability"], req["is_new"], req["old_name"])
            try:
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(req["user_id"]))
                await cv2_dm(user, t(self.gid, "moveset_approved", ability=req["ability"]["name"]))
            except Exception: pass
        self.clear_items()
        self.add_item(Container(TextDisplay("✅ Approved.")))
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
        self.add_item(Container(TextDisplay("❌ Declined.")))
        await ix.response.edit_message(view=self)


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
                old_member = guild.get_member(int(uid))
                old_name   = old_member.display_name if old_member else uid
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


@tasks.loop(minutes=5)
async def regen_stamina_task():
    for guild in bot.guilds:
        gid = guild.id; cfg = load_config(gid)
        players = load_players(gid); changed = False
        for uid, player in players.items():
            if player.get("stamina", 100) < player.get("max_stamina", 100):
                old = player.get("stamina", 100)
                player = _regen_stamina(player, cfg)
                if player["stamina"] != old: players[uid] = player; changed = True
        if changed: save_players(gid, players)


def start_tasks():
    if not check_titan_expiry.is_running(): check_titan_expiry.start()
    if not regen_stamina_task.is_running():  regen_stamina_task.start()
