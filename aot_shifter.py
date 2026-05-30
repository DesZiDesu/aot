"""Shifter system — transform, abilities, moveset, stamina, 13-year timer."""
import time, uuid, asyncio
import discord
from discord.ext import tasks
from discord.ui import View, Button, Select, Modal, TextInput

from aot_bot_instance import bot
from aot_shared import (
    t, load_players, save_players, load_config, save_config,
    ui_box, select_options_from_list,
)


# ── Stamina helpers ───────────────────────────────────────────────────────────

def _regen_stamina(player: dict, cfg: dict) -> dict:
    """Calculate stamina regenerated since last update."""
    now = time.time()
    last = player.get("stamina_last_update", now)
    elapsed_mins = (now - last) / 60
    regen = cfg.get("stamina_regen_per_minute", 1)
    player["stamina"] = min(
        player.get("max_stamina", 100),
        player.get("stamina", 100) + int(elapsed_mins * regen)
    )
    player["stamina_last_update"] = now
    return player

def _stamina_bar(stamina: int, max_st: int) -> str:
    filled = int((stamina / max_st) * 10) if max_st else 0
    return f"{'▓'*filled}{'░'*(10-filled)} {stamina}/{max_st}"


# ── Transform View ────────────────────────────────────────────────────────────

class TransformView(View):
    def __init__(self, uid: int, gid: int, profile_view):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.profile_view = profile_view
        self.hide_name = False; self.sel_titan = None; self._build()

    def _build(self):
        self.clear_items()
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        powers  = player.get("titan_powers", [])

        opts = [discord.SelectOption(label=p["titan"], value=p["titan"]) for p in powers] or \
               [discord.SelectOption(label="—", value="__none__")]
        s = Select(placeholder="Select Titan form", options=opts, row=0)
        s.callback = self._titan_cb
        self.add_item(s)

        hide_lbl = t(self.gid, "show_username_btn") if self.hide_name else t(self.gid, "hide_username_btn")
        hb = Button(label=hide_lbl, style=discord.ButtonStyle.secondary, row=1)
        hb.callback = self._toggle_hide
        self.add_item(hb)

        tb = Button(label="⚔️ Transform!", style=discord.ButtonStyle.danger, row=1)
        tb.callback = self._do_transform
        self.add_item(tb)

        bb = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=2)
        bb.callback = self._back
        self.add_item(bb)

    async def _titan_cb(self, ix):
        self.sel_titan = ix.data["values"][0]
        self._build(); await ix.response.edit_message(view=self)

    async def _toggle_hide(self, ix):
        self.hide_name = not self.hide_name
        self._build(); await ix.response.edit_message(view=self)

    async def _do_transform(self, ix: discord.Interaction):
        if not self.sel_titan or self.sel_titan == "__none__":
            await ix.response.send_message("Select a Titan form first.", ephemeral=True); return

        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        cfg     = load_config(self.gid)
        player  = _regen_stamina(player, cfg)

        if player.get("stamina", 100) < 10:
            await ix.response.send_message(t(self.gid, "stamina_low"), ephemeral=True); return

        player["transformed"] = True
        players[str(self.uid)] = player
        save_players(self.gid, players)

        name = ix.user.display_name
        if self.hide_name:
            pub = t(self.gid, "transform_hidden")
        else:
            pub = t(self.gid, "transform_public", name=name, titan=self.sel_titan)

        try: await ix.channel.send(pub)
        except Exception: pass

        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        view = TitanAbilitiesView(self.uid, self.gid, self.sel_titan, power, self.profile_view)
        await ix.response.edit_message(
            content=_abilities_text(self.gid, player, self.sel_titan, power),
            view=view)

    async def _back(self, ix):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        from aot_shared import format_profile_text
        from aot_profile import ProfileView
        await ix.response.edit_message(
            content=format_profile_text(player, ix.user.display_name, self.gid),
            view=self.profile_view)


# ── Titan Abilities View ──────────────────────────────────────────────────────

def _abilities_text(gid, player, titan_name, power):
    stamina = player.get("stamina", 100)
    max_st  = player.get("max_stamina", 100)
    abilities = (power or {}).get("abilities", [])
    cooldowns = player.get("ability_cooldowns", {})
    now = time.time()

    lines = [
        f"**{t(gid,'stamina_label')}** — {_stamina_bar(stamina, max_st)}",
        "",
        f"**{t(gid,'abilities_title')} — {titan_name}**",
        "",
    ]
    if abilities:
        for ab in abilities:
            cd_key = f"{titan_name}:{ab['name']}"
            cd_exp = cooldowns.get(cd_key, 0)
            cd_left = max(0, int((cd_exp - now) / 60))
            status = f"⏳ {cd_left}m" if cd_left > 0 else "✅ Ready"
            lines.append(f"  **{ab['name']}** — {ab.get('description','')[:60]}")
            lines.append(f"    Cost: {ab.get('stamina_cost',0)} stamina | CD: {ab.get('cooldown_minutes',0)}m | {status}")
    else:
        lines.append("  *No abilities configured.*")

    return ui_box(f"⚔️ {titan_name}", lines)


class TitanAbilitiesView(View):
    def __init__(self, uid, gid, titan_name, power, profile_view):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.titan_name = titan_name
        self.power = power or {}; self.profile_view = profile_view
        self.sel_ability = None; self._build()

    def _build(self):
        self.clear_items()
        abilities = self.power.get("abilities", [])
        opts = [discord.SelectOption(
            label=ab["name"][:100],
            value=ab["name"],
            description=f"Cost:{ab.get('stamina_cost',0)} CD:{ab.get('cooldown_minutes',0)}m"[:100]
        ) for ab in abilities[:25]] or [discord.SelectOption(label="No abilities", value="__none__")]

        s = Select(placeholder="Select ability", options=opts, row=0)
        s.callback = self._sel_ab; self.add_item(s)

        for lbl, cb, style, row in [
            (t(self.gid, "use_ability_btn"),   self._use,     discord.ButtonStyle.danger,     1),
            (t(self.gid, "edit_moveset_btn"),  self._moveset, discord.ButtonStyle.secondary,  1),
            (t(self.gid, "detransform_btn"),   self._deform,  discord.ButtonStyle.secondary,  2),
            (t(self.gid, "back_btn"),          self._back,    discord.ButtonStyle.secondary,  2),
        ]:
            b = Button(label=lbl, style=style, row=row); b.callback = cb; self.add_item(b)

    async def _sel_ab(self, ix):
        self.sel_ability = ix.data["values"][0]
        self._build(); await ix.response.edit_message(view=self)

    async def _use(self, ix: discord.Interaction):
        if not self.sel_ability or self.sel_ability == "__none__":
            await ix.response.send_message("Select an ability first.", ephemeral=True); return

        players = load_players(self.gid); player = players.get(str(self.uid), {})
        cfg = load_config(self.gid); player = _regen_stamina(player, cfg)
        ability = next((a for a in self.power.get("abilities", []) if a["name"] == self.sel_ability), None)
        if not ability: await ix.response.send_message("Ability not found.", ephemeral=True); return

        cd_key = f"{self.titan_name}:{ability['name']}"
        cooldowns = player.get("ability_cooldowns", {})
        now = time.time()

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
            try: await ix.user.send(t(self.gid, "stamina_empty"))
            except Exception: pass
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid)
            from aot_profile import ProfileView
            from aot_shared import format_profile_text
            await ix.response.edit_message(content=format_profile_text(player, ix.user.display_name, self.gid), view=self.profile_view)
            return

        await ix.response.edit_message(
            content=_abilities_text(self.gid, player, self.titan_name, self.power),
            view=self)

    async def _moveset(self, ix: discord.Interaction):
        view = MovesetEditorView(self.uid, self.gid, self.titan_name, self.power, self)
        await ix.response.edit_message(
            content=ui_box(t(self.gid, "edit_moveset_btn"), ["Select an ability to edit or add new."]),
            view=view)

    async def _deform(self, ix: discord.Interaction):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        player["transformed"] = False; players[str(self.uid)] = player; save_players(self.gid, players)
        try: await ix.channel.send(t(self.gid, "detransform_public", name=ix.user.display_name))
        except Exception: pass
        from aot_profile import ProfileView
        from aot_shared import format_profile_text
        await ix.response.edit_message(
            content=format_profile_text(player, ix.user.display_name, self.gid),
            view=self.profile_view)

    async def _back(self, ix):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        from aot_shared import format_profile_text
        from aot_profile import ProfileView
        await ix.response.edit_message(
            content=format_profile_text(player, ix.user.display_name, self.gid),
            view=self.profile_view)


async def _notify_admins_stamina(guild, uid, player, gid):
    if not guild: return
    name = (guild.get_member(int(uid)) or type("x",[],{"display_name":str(uid)})()).display_name
    msg = t(gid, "admin_stamina_warn", name=name,
            stamina=player.get("stamina",0), max=player.get("max_stamina",100))
    for m in guild.members:
        if m.guild_permissions.administrator:
            try: await m.send(msg)
            except Exception: pass


# ── Moveset Editor ────────────────────────────────────────────────────────────

class MovesetEditorView(View):
    def __init__(self, uid, gid, titan_name, power, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.titan_name = titan_name
        self.power = power or {}; self.parent = parent; self.sel = None; self._build()

    def _build(self):
        self.clear_items()
        abilities = self.power.get("abilities", [])
        opts = [discord.SelectOption(label=a["name"][:100], value=a["name"]) for a in abilities[:24]]
        opts.append(discord.SelectOption(label="+ Add New Ability", value="__new__"))
        s = Select(placeholder="Select ability", options=opts, row=0)
        s.callback = self._sel; self.add_item(s)

        for lbl, cb, style, row in [
            (t(self.gid, "edit_ability_btn"),   self._edit,   discord.ButtonStyle.primary,   1),
            (t(self.gid, "delete_ability_btn"),  self._delete, discord.ButtonStyle.danger,    1),
            (t(self.gid, "back_btn"),            self._back,   discord.ButtonStyle.secondary, 2),
        ]:
            b = Button(label=lbl, style=style, row=row); b.callback = cb; self.add_item(b)

    async def _sel(self, ix):
        self.sel = ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)

    async def _edit(self, ix: discord.Interaction):
        if not self.sel: await ix.response.send_message("Select an ability first.", ephemeral=True); return
        if self.sel == "__new__": prefill = {}
        else:
            prefill = next((a for a in self.power.get("abilities",[]) if a["name"]==self.sel), {})
        await ix.response.send_modal(EditAbilityModal(self.uid, self.gid, self.titan_name, self.power, self, prefill, is_new=(self.sel=="__new__")))

    async def _delete(self, ix: discord.Interaction):
        if not self.sel or self.sel == "__new__":
            await ix.response.send_message("Select an existing ability.", ephemeral=True); return
        is_admin = ix.user.guild_permissions.administrator
        if not is_admin:
            await ix.response.send_message("Only admins can delete abilities.", ephemeral=True); return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for pw in player.get("titan_powers", []):
            if pw["titan"] == self.titan_name:
                pw["abilities"] = [a for a in pw.get("abilities",[]) if a["name"] != self.sel]
                self.power = pw
        save_players(self.gid, players)
        self.sel = None; self._build()
        await ix.response.edit_message(content=ui_box(t(self.gid,"edit_moveset_btn"),["Ability deleted."]), view=self)

    async def _back(self, ix):
        players = load_players(self.gid); player = players.get(str(self.uid), {})
        await ix.response.edit_message(
            content=_abilities_text(self.gid, player, self.titan_name, self.power),
            view=self.parent)


class EditAbilityModal(Modal, title="Edit Ability"):
    f_name = TextInput(label="Ability Name",   max_length=60)
    f_desc = TextInput(label="Description",    style=discord.TextStyle.paragraph, max_length=300, required=False)
    f_cd   = TextInput(label="Cooldown (minutes)", max_length=5, default="30")
    f_cost = TextInput(label="Stamina Cost",   max_length=5, default="10")

    def __init__(self, uid, gid, titan_name, power, parent, prefill, is_new):
        super().__init__()
        self.uid=uid; self.gid=gid; self.titan_name=titan_name
        self.power=power; self.parent=parent; self.is_new=is_new; self.prefill=prefill
        if prefill:
            self.f_name.default=prefill.get("name","")
            self.f_desc.default=prefill.get("description","")
            self.f_cd.default=str(prefill.get("cooldown_minutes",30))
            self.f_cost.default=str(prefill.get("stamina_cost",10))

    async def on_submit(self, ix: discord.Interaction):
        ability = {
            "name":             self.f_name.value.strip(),
            "description":      (self.f_desc.value or "").strip(),
            "cooldown_minutes": max(0, int(self.f_cd.value.strip() or 0)),
            "stamina_cost":     max(0, int(self.f_cost.value.strip() or 0)),
        }
        is_admin = ix.user.guild_permissions.administrator
        if is_admin:
            await _apply_ability_edit(self.uid, self.gid, self.titan_name, ability, self.is_new, self.prefill.get("name",""))
            players = load_players(self.gid); player = players.get(str(self.uid), {})
            power = next((p for p in player.get("titan_powers",[]) if p["titan"]==self.titan_name), self.power)
            await ix.response.edit_message(
                content=_abilities_text(self.gid, player, self.titan_name, power),
                view=self.parent.parent)
        else:
            req_id = str(uuid.uuid4())[:8]
            cfg = load_config(self.gid)
            cfg.setdefault("pending_moveset_requests", {})[req_id] = {
                "user_id": str(self.uid),
                "titan":   self.titan_name,
                "ability": ability,
                "is_new":  self.is_new,
                "old_name":self.prefill.get("name",""),
                "ts":      time.time(),
            }
            save_config(self.gid, cfg)
            await _notify_admins_moveset(ix.guild, req_id, self.uid, ability, self.gid)
            await ix.response.edit_message(
                content=ui_box(t(self.gid,"edit_moveset_btn"),[t(self.gid,"moveset_pending")]),
                view=self.parent)


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
    name = member.display_name if member else str(uid)
    msg = (f"📝 **Moveset Edit Request** from **{name}**\n"
           f"Ability: **{ability['name']}**\n"
           f"Description: {ability.get('description','')}\n"
           f"CD: {ability.get('cooldown_minutes',0)}m | Cost: {ability.get('stamina_cost',0)}\n"
           f"Request ID: `{req_id}`")
    for m in guild.members:
        if m.guild_permissions.administrator:
            try:
                view = MovesetApprovalView(gid, req_id, uid)
                await m.send(msg, view=view)
            except Exception: pass


class MovesetApprovalView(View):
    def __init__(self, gid, req_id, uid):
        super().__init__(timeout=86400)
        self.gid=gid; self.req_id=req_id; self.uid=uid

        ap = Button(label=t(gid,"approve_btn"), style=discord.ButtonStyle.green)
        ap.callback = self._approve; self.add_item(ap)

        de = Button(label=t(gid,"decline_btn"), style=discord.ButtonStyle.danger)
        de.callback = self._decline; self.add_item(de)

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
                await user.send(t(self.gid, "moveset_approved", ability=req["ability"]["name"]))
            except Exception: pass
        await ix.response.edit_message(content="✅ Approved.", view=None)

    async def _decline(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)
        if req:
            try:
                from aot_bot_instance import bot as _bot
                user = await _bot.fetch_user(int(req["user_id"]))
                await user.send(t(self.gid, "moveset_declined", ability=req["ability"]["name"]))
            except Exception: pass
        await ix.response.edit_message(content="❌ Declined.", view=None)


# ── Background tasks ──────────────────────────────────────────────────────────

@tasks.loop(minutes=10)
async def check_titan_expiry():
    import random
    for guild in bot.guilds:
        gid = guild.id
        cfg = load_config(gid)
        players = load_players(gid)
        now = time.time()
        changed = False
        for uid, player in list(players.items()):
            powers = player.get("titan_powers", [])
            if not powers: continue
            if player.get("deceased"): continue
            first_power = powers[0]
            if first_power.get("expires_at", float("inf")) > now: continue
            # Titan expired
            titan_names = [p["titan"] for p in powers]
            player["deceased"] = True
            player["titan_powers"] = []
            players[uid] = player
            changed = True

            # Find eligible inheritors: Paradis faction, Human/Mixed Blood
            paradis_factions = cfg.get("factions", [])
            eligible = []
            for mid, mp in players.items():
                if mid == uid: continue
                if mp.get("deceased"): continue
                if mp.get("faction") in paradis_factions:
                    if mp.get("bloodline") in (cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])):
                        member = guild.get_member(int(mid))
                        if member: eligible.append((mid, mp, member))

            for titan in titan_names:
                new_owner_data = random.choice(eligible) if eligible else None
                old_member = guild.get_member(int(uid))
                old_name = old_member.display_name if old_member else uid

                if new_owner_data:
                    new_uid, new_player, new_member = new_owner_data
                    titan_days = cfg.get("titan_time_days", 4745)
                    new_power = {"titan": titan, "acquired_at": now,
                                 "expires_at": now + titan_days * 86400, "abilities": []}
                    # Share timer from first power if already has powers
                    existing = new_player.get("titan_powers", [])
                    if existing:
                        new_power["expires_at"] = existing[0]["expires_at"]
                    new_player.setdefault("titan_powers", []).append(new_power)
                    players[new_uid] = new_player
                    try: await new_member.send(t(gid, "got_titan_dm", titan=titan))
                    except Exception: pass
                    new_name = new_member.display_name

                    # Notify admins
                    for m in guild.members:
                        if m.guild_permissions.administrator:
                            try: await m.send(t(gid,"admin_got_titan",new_owner=new_name,titan=titan,old_owner=old_name))
                            except Exception: pass

                    # Announcement channel
                    ch_id = cfg.get("titan_announcement_channel")
                    if ch_id:
                        ch = guild.get_channel(int(ch_id))
                        if ch:
                            try: await ch.send(t(gid,"titan_died",name=old_name,titan=titan,new_owner=new_name))
                            except Exception: pass

        if changed:
            save_players(gid, players)


@tasks.loop(minutes=5)
async def regen_stamina_task():
    for guild in bot.guilds:
        gid = guild.id; cfg = load_config(gid)
        players = load_players(gid); changed = False
        for uid, player in players.items():
            if player.get("stamina", 100) < player.get("max_stamina", 100):
                old = player.get("stamina", 100)
                player = _regen_stamina(player, cfg)
                if player["stamina"] != old:
                    players[uid] = player; changed = True
        if changed: save_players(gid, players)


def start_tasks():
    if not check_titan_expiry.is_running():
        check_titan_expiry.start()
    if not regen_stamina_task.is_running():
        regen_stamina_task.start()
