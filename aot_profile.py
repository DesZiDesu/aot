"""Profile command — registration, display, inventory tab."""
import asyncio
import discord
from discord.ui import View, Button, Select, Modal, TextInput

from aot_bot_instance import bot
from aot_shared import (
    t, load_players, save_players, load_config, load_items,
    ui_box, select_options_from_list, get_available_bloodlines,
    has_shifter_access, assign_roles, remove_old_roles,
    format_profile_text, format_inventory_text,
)


# ── Registration modal (Step 1) ───────────────────────────────────────────────

class RegisterModal(Modal, title="Register"):
    char_name  = TextInput(label="Name",       max_length=60)
    age        = TextInput(label="Age",        max_length=10)
    gender     = TextInput(label="Gender",     max_length=30)
    appearance = TextInput(label="Appearance", style=discord.TextStyle.paragraph, max_length=500)
    image      = TextInput(label="Image (URL or emoji, optional)", max_length=300, required=False)

    def __init__(self, guild_id: int, prefill: dict = None):
        super().__init__()
        self.guild_id = guild_id
        gid = guild_id
        self.char_name.label  = t(gid, "name_field")
        self.age.label        = t(gid, "age_field")
        self.gender.label     = t(gid, "gender_field")
        self.appearance.label = t(gid, "appearance_field")
        self.image.label      = t(gid, "image_field")
        if prefill:
            self.char_name.default  = prefill.get("name", "")
            self.age.default        = prefill.get("age", "")
            self.gender.default     = prefill.get("gender", "")
            self.appearance.default = prefill.get("appearance", "")
            self.image.default      = prefill.get("image", "")

    async def on_submit(self, ix: discord.Interaction):
        gid = self.guild_id
        uid = ix.user.id
        step1 = {
            "name":       self.char_name.value.strip(),
            "age":        self.age.value.strip(),
            "gender":     self.gender.value.strip(),
            "appearance": self.appearance.value.strip(),
            "image":      (self.image.value or "").strip(),
        }
        cfg       = load_config(gid)
        bloodlines = get_available_bloodlines(gid, uid)
        existing  = load_players(gid).get(str(uid), {})
        view = RegisterSelectsView(gid, uid, step1, cfg, bloodlines,
                                   existing_player=existing, is_edit=bool(existing))
        await ix.response.edit_message(
            content=ui_box(t(gid, "profile_title"),
                           [t(gid, "register_step2")]),
            view=view,
        )


# ── Step 2: dropdowns ─────────────────────────────────────────────────────────

class RegisterSelectsView(View):
    def __init__(self, gid, uid, step1, cfg, bloodlines,
                 existing_player=None, is_edit=False):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.step1 = step1
        self.cfg = cfg; self.bloodlines = bloodlines
        self.existing = existing_player or {}; self.is_edit = is_edit

        factions = cfg.get("factions", [])
        ranks    = cfg.get("ranks", [])
        shifters = cfg.get("shifters", [])

        self.sel_faction   = self.existing.get("faction",   factions[0] if factions else "")
        self.sel_rank      = self.existing.get("rank",      ranks[0]    if ranks    else "")
        self.sel_bloodline = self.existing.get("bloodline", bloodlines[0] if bloodlines else "")
        self.sel_shifter   = self.existing.get("shifter",   "None")
        self.show_shifter  = has_shifter_access(gid, uid)
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _sel(placeholder_key, opts, row, cb):
            s = Select(placeholder=t(gid, placeholder_key),
                       options=opts, row=row)
            s.callback = cb
            self.add_item(s)

        _sel("select_faction",   select_options_from_list(self.cfg.get("factions",[]),   self.sel_faction),   0, self._faction_cb)
        _sel("select_rank",      select_options_from_list(self.cfg.get("ranks",[]),      self.sel_rank),      1, self._rank_cb)
        _sel("select_bloodline", select_options_from_list(self.bloodlines,               self.sel_bloodline), 2, self._bloodline_cb)

        if self.show_shifter:
            shifter_opts = select_options_from_list(
                ["None"] + self.cfg.get("shifters", []), self.sel_shifter)
            _sel("select_shifter", shifter_opts, 3, self._shifter_cb)

        btn = Button(label=t(gid, "confirm_btn"), style=discord.ButtonStyle.green, row=4)
        btn.callback = self._confirm
        self.add_item(btn)

    async def _faction_cb(self, ix): self.sel_faction = ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _rank_cb(self, ix):    self.sel_rank    = ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _bloodline_cb(self, ix): self.sel_bloodline = ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _shifter_cb(self, ix): self.sel_shifter = ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)

    async def _confirm(self, ix: discord.Interaction):
        gid, uid = self.gid, self.uid
        players = load_players(gid)
        cfg     = load_config(gid)
        old     = players.get(str(uid), {})

        player = {**self.step1,
                  "faction":   self.sel_faction,
                  "rank":      self.sel_rank,
                  "bloodline": self.sel_bloodline,
                  "shifter":   self.sel_shifter if self.show_shifter else old.get("shifter","None"),
                  "inventory": old.get("inventory", {}),
                  "titan_powers": old.get("titan_powers", []),
                  "stamina":    old.get("stamina", 100),
                  "max_stamina":old.get("max_stamina", 100),
                  "ability_cooldowns": old.get("ability_cooldowns", {}),
                  "transformed": False,
                  "deceased": old.get("deceased", False)}
        players[str(uid)] = player
        save_players(gid, players)

        member = ix.guild.get_member(uid)
        if member:
            if self.is_edit and old:
                await remove_old_roles(member, old, cfg)
            await assign_roles(member, player, cfg)

        name = ix.user.display_name
        profile_text = format_profile_text(player, name, gid)
        from aot_profile import ProfileView
        await ix.response.edit_message(content=profile_text, view=ProfileView(uid, gid))

        action = "updated_msg" if self.is_edit else "registered_msg"
        try:
            msg = await ix.channel.send(t(gid, action, name=name, char=player["name"]))
            await asyncio.sleep(30)
            await msg.delete()
        except Exception: pass
        try:
            dm = await ix.user.create_dm()
            await dm.send(t(gid, "dm_profile", profile=profile_text))
        except Exception: pass


# ── Profile view (tabs) ───────────────────────────────────────────────────────

class ProfileView(View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.uid = user_id; self.gid = guild_id
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _btn(key, style, cb, row=0):
            b = Button(label=t(gid, key), style=style, row=row)
            b.callback = cb
            self.add_item(b)

        _btn("profile_btn",   discord.ButtonStyle.primary,   self._profile_tab)
        _btn("inventory_btn", discord.ButtonStyle.secondary, self._inventory_tab)
        _btn("edit_btn",      discord.ButtonStyle.secondary, self._edit)

        # Show transform button only if user has titan powers
        players = load_players(gid)
        player  = players.get(str(self.uid), {})
        if player.get("titan_powers"):
            tb = Button(label=t(gid, "transform_btn"), style=discord.ButtonStyle.danger, row=1)
            tb.callback = self._transform
            self.add_item(tb)

    async def _profile_tab(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.edit_message(
            content=format_profile_text(player, ix.user.display_name, self.gid),
            view=self)

    async def _inventory_tab(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        items  = load_items(self.gid)
        await ix.response.edit_message(
            content=format_inventory_text(player, items, self.gid),
            view=self)

    async def _edit(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(RegisterModal(self.gid, prefill=player))

    async def _transform(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        from aot_shifter import TransformView
        player = load_players(self.gid).get(str(self.uid), {})
        view = TransformView(self.uid, self.gid, self)
        await ix.response.edit_message(
            content=ui_box(t(self.gid, "transform_btn"), ["⚔️"]),
            view=view)


# ── Unregistered view ─────────────────────────────────────────────────────────

class UnregisteredView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.gid = guild_id
        b = Button(label=t(guild_id, "register_btn"), style=discord.ButtonStyle.green)
        b.callback = self._register
        self.add_item(b)

    async def _register(self, ix: discord.Interaction):
        await ix.response.send_modal(RegisterModal(self.gid))


# ── /profile command ──────────────────────────────────────────────────────────

@bot.tree.command(name="profile", description="View or create your character profile")
async def profile_cmd(ix: discord.Interaction):
    gid = ix.guild_id; uid = ix.user.id
    player = load_players(gid).get(str(uid))
    if not player:
        await ix.response.send_message(
            content=ui_box(t(gid, "profile_title"), [t(gid, "not_registered")]),
            view=UnregisteredView(gid), ephemeral=True)
    else:
        await ix.response.send_message(
            content=format_profile_text(player, ix.user.display_name, gid),
            view=ProfileView(uid, gid), ephemeral=True)
