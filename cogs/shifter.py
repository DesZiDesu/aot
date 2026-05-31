"""Shifter system — /shifter group, abilities, moveset, stamina, 13-year timer."""
import time
import uuid
import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import Button, Select, Modal, TextInput

from core.instance import bot
from core.shared import (
    t, load_players, save_players, load_config, save_config,
    has_shifter_access, send_dm, log_event, is_url,
    format_currency, EMBED_COLOR,
)


# ── Stamina helpers ────────────────────────────────────────────────────────────

def _regen_stamina(player: dict, cfg: dict) -> dict:
    now           = time.time()
    interval_secs = cfg.get("stamina_regen_interval_minutes", 5) * 60
    last          = player.get("stamina_last_regen", now - interval_secs)
    if now - last < interval_secs:
        return player
    amount        = cfg.get("stamina_regen_amount", 5)
    player["stamina"] = min(
        player.get("max_stamina", 100),
        player.get("stamina", 0) + amount,
    )
    player["stamina_last_regen"] = now
    return player


def _stamina_bar(stamina: int, max_st: int) -> str:
    filled = int((stamina / max_st) * 10) if max_st else 0
    return f"{'▓' * filled}{'░' * (10 - filled)} {stamina}/{max_st}"


# ── Embed announce helpers ─────────────────────────────────────────────────────

async def _send_transform_embed(channel, gid: int, hide_name: bool, uid: int,
                                titan_name: str, power: dict = None) -> None:
    if hide_name:
        title = t(gid, "transform_hidden")
        desc  = None
    else:
        display = (power or {}).get("display_name") or titan_name if power else titan_name
        title   = t(gid, "transform_public", name=f"<@{uid}>", titan=display)
        desc    = (power or {}).get("custom_desc", "") or None

    embed = discord.Embed(title=title, description=desc, color=EMBED_COLOR)
    custom_image = (power or {}).get("custom_image", "")
    if custom_image and is_url(custom_image):
        embed.set_image(url=custom_image)

    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _send_deform_embed(channel, gid: int, hide_name: bool, uid: int) -> None:
    if hide_name:
        title = t(gid, "detransform_hidden")
    else:
        title = t(gid, "detransform_public", name=f"<@{uid}>")
    embed = discord.Embed(title=title, color=EMBED_COLOR)
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _send_ability_embed(channel, gid: int, hide_name: bool, uid: int,
                              ability: dict, stamina: int, max_st: int) -> None:
    ab_name = ability["name"]
    ab_desc = ability.get("description", "")
    img_url = ability.get("image_url", "")
    bar     = _stamina_bar(stamina, max_st)

    if hide_name:
        title = t(gid, "ability_used_hidden", ability=ab_name)
    else:
        title = t(gid, "ability_used", name=f"<@{uid}>", ability=ab_name)

    embed = discord.Embed(title=title, color=EMBED_COLOR)
    if ab_desc:
        embed.description = f"*{ab_desc}*"
    embed.add_field(name=t(gid, "stamina_label"), value=bar, inline=False)
    if img_url and is_url(img_url):
        embed.set_image(url=img_url)

    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _send_grab_embed(channel, gid: int, name: str, target_name: str) -> None:
    embed = discord.Embed(
        title=t(gid, "shifter_grab_msg", name=name, target=target_name),
        color=EMBED_COLOR,
    )
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _send_eat_embed(channel, gid: int, eater_name: str,
                          target_name: str, got_titan: str = None) -> None:
    if got_titan:
        title = t(gid, "shifter_ate_shifter_msg",
                  eater=eater_name, target=target_name, titan=got_titan)
    else:
        title = t(gid, "shifter_ate_normal_msg", eater=eater_name, target=target_name)
    embed = discord.Embed(title=title, color=EMBED_COLOR)
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


# ── Admin stamina notification ─────────────────────────────────────────────────

async def _notify_admins_stamina(guild, uid: int, player: dict, gid: int) -> None:
    if not guild:
        return
    member = guild.get_member(int(uid))
    name   = member.display_name if member else str(uid)
    msg    = t(gid, "admin_stamina_warn",
               name=name, stamina=player.get("stamina", 0),
               max=player.get("max_stamina", 100))
    for m in guild.members:
        if m.guild_permissions.administrator:
            await send_dm(m, content=msg)


# ── Shifter Admin View ─────────────────────────────────────────────────────────

class ShifterAdminView(discord.ui.View):
    def __init__(self, gid: int, guild=None):
        super().__init__(timeout=300)
        self.gid   = gid
        self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        cfg    = load_config(self.gid)
        titans = cfg.get("shifters", [])
        access = cfg.get("shifter_access", [])

        grant_btn   = Button(label=t(self.gid, "grant_btn"),   style=discord.ButtonStyle.green,     row=0)
        revoke_btn  = Button(label=t(self.gid, "revoke_btn"),  style=discord.ButtonStyle.danger,    row=0)
        tracker_btn = Button(label=t(self.gid, "tracker_btn"), style=discord.ButtonStyle.secondary, row=1)
        done_btn    = Button(label=t(self.gid, "done_btn"),    style=discord.ButtonStyle.danger,    row=2)

        grant_btn.callback   = self._grant
        revoke_btn.callback  = self._revoke
        tracker_btn.callback = self._tracker
        done_btn.callback    = self._done

        self.add_item(grant_btn)
        self.add_item(revoke_btn)
        self.add_item(tracker_btn)
        self.add_item(done_btn)

        self._embed = discord.Embed(
            title=t(self.gid, "shifter_admin_title"),
            color=EMBED_COLOR,
        )
        self._embed.add_field(name="Titans",            value=", ".join(titans) or "*None*", inline=False)
        self._embed.add_field(name="Users with access", value=str(len(access)),              inline=False)

    async def _grant(self, ix: discord.Interaction):
        try:
            from cogs.aot_admin import GrantShifterView  # type: ignore
            await ix.response.edit_message(view=GrantShifterView(self.gid, self))
        except ImportError:
            await ix.response.send_message("Grant view not available.", ephemeral=True)

    async def _revoke(self, ix: discord.Interaction):
        try:
            from cogs.aot_admin import RevokeShView  # type: ignore
            await ix.response.edit_message(view=RevokeShView(self.gid, self))
        except ImportError:
            await ix.response.send_message("Revoke view not available.", ephemeral=True)

    async def _tracker(self, ix: discord.Interaction):
        try:
            from cogs.aot_admin import ShifterTrackerView  # type: ignore
            await ix.response.edit_message(view=ShifterTrackerView(self.gid, self, ix.guild))
        except ImportError:
            await ix.response.send_message("Tracker not available.", ephemeral=True)

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=self)


# ── /shifter command group ─────────────────────────────────────────────────────

shifter_group = app_commands.Group(
    name="shifter",
    description="Titan shifter commands",
    description_localizations={"th": "คำสั่งผู้ถือพลังไทแทน"},
)


@shifter_group.command(
    name="open",
    description="Open your titan shifter panel",
    description_localizations={"th": "เปิดแผงผู้ถือพลังไทแทน"},
)
async def shifter_open(ix: discord.Interaction):
    gid = ix.guild_id
    uid = ix.user.id
    if not has_shifter_access(gid, uid):
        embed = discord.Embed(description=t(gid, "no_permission"), color=EMBED_COLOR)
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    players = load_players(gid)
    player  = players.get(str(uid), {})
    if not player.get("titan_powers"):
        embed = discord.Embed(description=t(gid, "no_titan_power"), color=EMBED_COLOR)
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    view  = ShifterMainView(uid, gid)
    embed = view.build_embed()
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@shifter_group.command(
    name="admin",
    description="Shifter admin panel",
    description_localizations={"th": "แผงผู้ดูแลระบบผู้ถือพลัง"},
)
async def shifter_admin(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not m or not (m.guild_permissions.administrator or m.guild_permissions.manage_guild):
        embed = discord.Embed(description=t(ix.guild_id, "admin_only"), color=EMBED_COLOR)
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    view  = ShifterAdminView(ix.guild_id, ix.guild)
    embed = view._embed
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


bot.tree.add_command(shifter_group)


# ── ShifterMainView ────────────────────────────────────────────────────────────

class ShifterMainView(discord.ui.View):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=300)
        self.uid        = uid
        self.gid        = gid
        self.hide_name  = False
        self.sel_titan  = None
        self.sel_ability = None
        self._build()

    # ── embed ──────────────────────────────────────────────────────────────────

    def build_embed(self) -> discord.Embed:
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        powers  = player.get("titan_powers", [])
        if not powers:
            return discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)

        if not self.sel_titan or not any(p["titan"] == self.sel_titan for p in powers):
            self.sel_titan = powers[0]["titan"]
        power = next((p for p in powers if p["titan"] == self.sel_titan), powers[0])

        if player.get("transformed"):
            return self._embed_transformed(player, power)
        else:
            return self._embed_untransformed(player, power)

    def _embed_untransformed(self, player: dict, power: dict) -> discord.Embed:
        gid        = self.gid
        titan_name = power.get("titan", "?")
        display    = power.get("display_name") or titan_name
        stamina    = player.get("stamina", 100)
        max_st     = player.get("max_stamina", 100)
        bar        = _stamina_bar(stamina, max_st)
        now        = time.time()
        days_left  = max(0, int((power.get("expires_at", 0) - now) / 86400))

        embed = discord.Embed(title=f"⚔️ {display}", color=EMBED_COLOR)
        custom_image = power.get("custom_image", "")
        if custom_image and is_url(custom_image):
            embed.set_thumbnail(url=custom_image)

        embed.add_field(name=t(gid, "stamina_label"),   value=bar,              inline=False)
        embed.add_field(name=t(gid, "time_left_label"), value=f"{days_left}d",  inline=True)

        cooldown_until = player.get("transform_cooldown_until", 0)
        if cooldown_until > now:
            mins_left = int((cooldown_until - now) / 60) + 1
            embed.add_field(name="⏳ Transform Cooldown", value=f"{mins_left}m", inline=True)

        if self.hide_name:
            embed.set_footer(text="🎭 Username hidden")
        return embed

    def _embed_transformed(self, player: dict, power: dict) -> discord.Embed:
        gid        = self.gid
        titan_name = power.get("titan", "?")
        display    = power.get("display_name") or titan_name
        stamina    = player.get("stamina", 100)
        max_st     = player.get("max_stamina", 100)
        bar        = _stamina_bar(stamina, max_st)
        abilities  = power.get("abilities", [])
        cooldowns  = player.get("ability_cooldowns", {})
        now        = time.time()

        embed = discord.Embed(title=f"⚡ {display} Form", color=EMBED_COLOR)
        custom_image = power.get("custom_image", "")
        if custom_image and is_url(custom_image):
            embed.set_thumbnail(url=custom_image)

        embed.add_field(name=t(gid, "stamina_label"), value=bar, inline=False)

        if abilities:
            embed.add_field(name=t(gid, "abilities_title"), value="​", inline=False)
            for ab in abilities[:10]:
                if not ab.get("confirmed", True):
                    embed.add_field(
                        name=ab["name"],
                        value="⚙️ *Pending admin configuration*",
                        inline=False,
                    )
                    continue
                cd_key  = f"{titan_name}:{ab['name']}"
                cd_exp  = cooldowns.get(cd_key, 0)
                cd_left = max(0, int((cd_exp - now) / 60))
                status  = f"⏳ {cd_left}m" if cd_left > 0 else "✅ Ready"
                val     = (
                    f"{ab.get('description','')[:80]}\n"
                    f"Cost: **{ab.get('stamina_cost', 0)}** | "
                    f"CD: **{ab.get('cooldown_minutes', 0)}m** | {status}"
                )
                embed.add_field(name=ab["name"], value=val, inline=False)
        else:
            embed.add_field(name=t(gid, "abilities_title"), value="*No abilities configured.*", inline=False)

        if self.hide_name:
            embed.set_footer(text="🎭 Username hidden")
        return embed

    # ── view components ────────────────────────────────────────────────────────

    def _build(self):
        self.clear_items()
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        powers  = player.get("titan_powers", [])

        if not powers:
            return

        if not self.sel_titan or not any(p["titan"] == self.sel_titan for p in powers):
            self.sel_titan = powers[0]["titan"]
        power = next((p for p in powers if p["titan"] == self.sel_titan), powers[0])

        if player.get("transformed"):
            self._build_transformed(player, power, powers)
        else:
            self._build_untransformed(player, power, powers)

    def _build_untransformed(self, player: dict, power: dict, powers: list):
        gid            = self.gid
        titan_name     = power.get("titan", "?")
        now            = time.time()
        cooldown_until = player.get("transform_cooldown_until", 0)
        transform_disabled = cooldown_until > now

        # Titan selector (if multiple powers)
        if len(powers) > 1:
            opts = [discord.SelectOption(
                        label=p["titan"], value=p["titan"],
                        default=(p["titan"] == titan_name))
                    for p in powers]
            titan_sel          = Select(placeholder="Select Titan form", options=opts, row=0)
            titan_sel.callback = self._titan_cb
            self.add_item(titan_sel)

        hide_lbl    = t(gid, "show_username_btn") if self.hide_name else t(gid, "hide_username_btn")
        hide_btn    = Button(label=hide_lbl,                    style=discord.ButtonStyle.secondary, row=1)
        transform_b = Button(label="⚔️ Transform!",             style=discord.ButtonStyle.danger,    row=1,
                             disabled=transform_disabled)
        moveset_b   = Button(label=t(gid, "edit_moveset_btn"),  style=discord.ButtonStyle.secondary, row=2)
        upgrade_b   = Button(label=t(gid, "upgrade_ability_btn"), style=discord.ButtonStyle.secondary, row=2)
        customize_b = Button(label=t(gid, "customize_form_btn"), style=discord.ButtonStyle.secondary, row=3)
        refresh_b   = Button(label="🔄 Refresh",                style=discord.ButtonStyle.secondary, row=3)

        hide_btn.callback    = self._toggle_hide
        transform_b.callback = self._transform
        moveset_b.callback   = self._open_moveset
        upgrade_b.callback   = self._upgrade
        customize_b.callback = self._customize
        refresh_b.callback   = self._refresh

        self.add_item(hide_btn)
        self.add_item(transform_b)
        self.add_item(moveset_b)
        self.add_item(upgrade_b)
        self.add_item(customize_b)
        self.add_item(refresh_b)

    def _build_transformed(self, player: dict, power: dict, powers: list):
        gid       = self.gid
        titan_name = power.get("titan", "?")
        abilities  = power.get("abilities", [])

        # Ability selector
        opts = ([discord.SelectOption(
                    label=ab["name"][:100], value=ab["name"],
                    description=(
                        "⚙️ Pending config" if not ab.get("confirmed", True)
                        else f"Cost:{ab.get('stamina_cost',0)} CD:{ab.get('cooldown_minutes',0)}m"
                    )[:100],
                    default=(ab["name"] == self.sel_ability))
                 for ab in abilities[:25]]
                or [discord.SelectOption(label="No abilities", value="__none__")])

        sel          = Select(placeholder="Select ability", options=opts, row=0)
        sel.callback = self._sel_ab
        self.add_item(sel)

        use_b     = Button(label=t(gid, "use_ability_btn"),  style=discord.ButtonStyle.danger,    row=1)
        moveset_b = Button(label=t(gid, "edit_moveset_btn"), style=discord.ButtonStyle.secondary, row=1)
        grab_b    = Button(label=t(gid, "grab_btn"),         style=discord.ButtonStyle.secondary, row=2)
        eat_b     = Button(label=t(gid, "eat_btn"),          style=discord.ButtonStyle.danger,    row=2)
        deform_b  = Button(label=t(gid, "detransform_btn"),  style=discord.ButtonStyle.secondary, row=3)
        refresh_b = Button(label="🔄 Refresh",               style=discord.ButtonStyle.secondary, row=3)

        use_b.callback     = self._use
        moveset_b.callback = self._open_moveset
        grab_b.callback    = self._grab
        eat_b.callback     = self._eat
        deform_b.callback  = self._deform
        refresh_b.callback = self._refresh

        self.add_item(use_b)
        self.add_item(moveset_b)
        self.add_item(grab_b)
        self.add_item(eat_b)
        self.add_item(deform_b)
        self.add_item(refresh_b)

    # ── callbacks ──────────────────────────────────────────────────────────────

    async def _titan_cb(self, ix: discord.Interaction):
        self.sel_titan   = ix.data["values"][0]
        self.sel_ability = None
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _sel_ab(self, ix: discord.Interaction):
        self.sel_ability = ix.data["values"][0]
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _toggle_hide(self, ix: discord.Interaction):
        self.hide_name = not self.hide_name
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _refresh(self, ix: discord.Interaction):
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _transform(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        cfg     = load_config(self.gid)
        player  = _regen_stamina(player, cfg)
        now     = time.time()

        cooldown_until = player.get("transform_cooldown_until", 0)
        if cooldown_until > now:
            mins_left = int((cooldown_until - now) / 60) + 1
            embed = discord.Embed(
                description=t(self.gid, "transform_cooldown_msg", mins=mins_left),
                color=EMBED_COLOR,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        min_st = cfg.get("transform_min_stamina", 30)
        if player.get("stamina", 100) < min_st:
            embed = discord.Embed(description=t(self.gid, "stamina_low"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            embed = discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        player["transformed"]      = True
        players[str(self.uid)]     = player
        save_players(self.gid, players)
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)
        await _send_transform_embed(ix.channel, self.gid, self.hide_name, self.uid, self.sel_titan, power)

    async def _deform(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["transformed"] = False
        player.pop("transform_cooldown_until", None)
        players[str(self.uid)] = player
        save_players(self.gid, players)
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)
        await _send_deform_embed(ix.channel, self.gid, self.hide_name, self.uid)

    async def _use(self, ix: discord.Interaction):
        if not self.sel_ability or self.sel_ability == "__none__":
            embed = discord.Embed(description="Select an ability first.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        cfg     = load_config(self.gid)
        player  = _regen_stamina(player, cfg)

        power = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            embed = discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        ability = next((a for a in power.get("abilities", []) if a["name"] == self.sel_ability), None)
        if not ability:
            embed = discord.Embed(description="Ability not found.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        if not ability.get("confirmed", True):
            embed = discord.Embed(description=t(self.gid, "ability_pending_config"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        cd_key    = f"{self.sel_titan}:{ability['name']}"
        cooldowns = player.get("ability_cooldowns", {})
        now       = time.time()

        if cooldowns.get(cd_key, 0) > now:
            mins_left = int((cooldowns[cd_key] - now) / 60) + 1
            embed = discord.Embed(
                description=t(self.gid, "cooldown_remaining", mins=mins_left),
                color=EMBED_COLOR,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        cost = ability.get("stamina_cost", 0)
        if player.get("stamina", 100) < cost:
            embed = discord.Embed(description=t(self.gid, "stamina_low"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid)
            return

        player["stamina"]           = max(0, player.get("stamina", 100) - cost)
        cooldowns[cd_key]           = now + ability.get("cooldown_minutes", 0) * 60
        player["ability_cooldowns"] = cooldowns

        auto_deformed = False
        if player["stamina"] <= 0:
            player["transformed"]              = False
            cd_mins                            = cfg.get("auto_deform_cooldown_minutes", 60)
            player["transform_cooldown_until"] = now + cd_mins * 60
            auto_deformed                      = True

        players[str(self.uid)] = player
        save_players(self.gid, players)

        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)
        await _send_ability_embed(
            ix.channel, self.gid, self.hide_name, self.uid,
            ability, player["stamina"], player.get("max_stamina", 100),
        )
        if auto_deformed:
            await send_dm(ix.user, content=t(self.gid, "stamina_empty"))
            await _notify_admins_stamina(ix.guild, self.uid, player, self.gid)

    async def _open_moveset(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            embed = discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = MovesetEditorView(self.uid, self.gid, self.sel_titan, power, self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)

    async def _upgrade(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            embed = discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = UpgradeAbilityView(self.uid, self.gid, self.sel_titan, power, self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)

    async def _customize(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        power   = next((p for p in player.get("titan_powers", []) if p["titan"] == self.sel_titan), None)
        if not power:
            embed = discord.Embed(description=t(self.gid, "no_titan_power"), color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await ix.response.send_modal(CustomizeFormModal(self.uid, self.gid, self.sel_titan, self))

    async def _grab(self, ix: discord.Interaction):
        view  = ShifterTargetView(self.uid, self.gid, "grab", self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)

    async def _eat(self, ix: discord.Interaction):
        view  = ShifterTargetView(self.uid, self.gid, "eat", self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)


# ── Upgrade Ability View ───────────────────────────────────────────────────────

class UpgradeAbilityView(discord.ui.View):
    def __init__(self, uid: int, gid: int, titan_name: str, power: dict, parent):
        super().__init__(timeout=300)
        self.uid        = uid
        self.gid        = gid
        self.titan_name = titan_name
        self.power      = power or {}
        self.parent     = parent
        self.sel        = None
        self._build()

    def build_embed(self) -> discord.Embed:
        abilities = self.power.get("abilities", [])
        embed     = discord.Embed(title=t(self.gid, "upgrade_title"), color=EMBED_COLOR)
        if self.sel:
            ab  = next((a for a in abilities if a["name"] == self.sel), {})
            cfg = load_config(self.gid)
            embed.add_field(name="Selected",      value=f"**{self.sel}**",                       inline=False)
            embed.add_field(name="Cooldown",       value=f"{ab.get('cooldown_minutes', 0)}m",     inline=True)
            embed.add_field(name="Stamina Cost",   value=str(ab.get("stamina_cost", 0)),          inline=True)
            embed.add_field(
                name="Upgrade Costs",
                value=(
                    f"Reduce CD (−5m): **200 {cfg.get('currency_name','Coins')}**\n"
                    f"Reduce Cost (−5): **150 {cfg.get('currency_name','Coins')}**"
                ),
                inline=False,
            )
        else:
            embed.description = "Select an ability to upgrade."
        return embed

    def _build(self):
        self.clear_items()
        abilities = self.power.get("abilities", [])
        opts      = ([discord.SelectOption(label=a["name"][:100], value=a["name"])
                      for a in abilities[:25] if a.get("confirmed", True)]
                     or [discord.SelectOption(label="No abilities", value="__none__")])

        sel          = Select(placeholder="Select ability to upgrade", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)

        cd_btn   = Button(label=t(self.gid, "upgrade_cd_btn"),   style=discord.ButtonStyle.primary,   row=1)
        cost_btn = Button(label=t(self.gid, "upgrade_cost_btn"), style=discord.ButtonStyle.secondary, row=1)
        bk_btn   = Button(label=t(self.gid, "back_btn"),         style=discord.ButtonStyle.secondary, row=2)

        cd_btn.callback   = self._upgrade_cd
        cost_btn.callback = self._upgrade_cost
        bk_btn.callback   = self._back

        self.add_item(cd_btn)
        self.add_item(cost_btn)
        self.add_item(bk_btn)

    async def _sel(self, ix: discord.Interaction):
        val      = ix.data["values"][0]
        self.sel = val if val != "__none__" else None
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _upgrade_cd(self, ix: discord.Interaction):
        if not self.sel:
            embed = discord.Embed(description="Select an ability first.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await self._do_upgrade(ix, "cd", cost=200, amount=5)

    async def _upgrade_cost(self, ix: discord.Interaction):
        if not self.sel:
            embed = discord.Embed(description="Select an ability first.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await self._do_upgrade(ix, "cost", cost=150, amount=5)

    async def _do_upgrade(self, ix: discord.Interaction, kind: str, cost: int, amount: int):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        cfg     = load_config(self.gid)
        balance = player.get("balance", 0)

        if balance < cost:
            embed = discord.Embed(
                description=t(self.gid, "upgrade_not_enough",
                              cost=format_currency(cost, cfg)),
                color=EMBED_COLOR,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        player["balance"] = balance - cost
        for pw in player.get("titan_powers", []):
            if pw["titan"] == self.titan_name:
                for ab in pw.get("abilities", []):
                    if ab["name"] == self.sel:
                        if kind == "cd":
                            ab["cooldown_minutes"] = max(0, ab.get("cooldown_minutes", 0) - amount)
                        else:
                            ab["stamina_cost"] = max(0, ab.get("stamina_cost", 0) - amount)
                        break
        players[str(self.uid)] = player
        save_players(self.gid, players)

        await log_event(bot, self.gid, "shifter",
                        f"<@{self.uid}> upgraded ability '{self.sel}' ({kind})")

        self.power = next(
            (p for p in player.get("titan_powers", []) if p["titan"] == self.titan_name),
            self.power,
        )
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)
        done_embed = discord.Embed(description=t(self.gid, "upgrade_done"), color=EMBED_COLOR)
        await ix.followup.send(embed=done_embed, ephemeral=True)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Customize Form Modal ───────────────────────────────────────────────────────

class CustomizeFormModal(Modal, title="Customize Titan Form"):
    f_name  = TextInput(label="Display Name (empty = titan name)", max_length=60,  required=False)
    f_image = TextInput(label="Image URL (optional)",              max_length=300, required=False)
    f_desc  = TextInput(label="Form Description (optional)",
                        style=discord.TextStyle.paragraph, max_length=300, required=False)

    def __init__(self, uid: int, gid: int, titan_name: str, parent):
        super().__init__()
        self.uid        = uid
        self.gid        = gid
        self.titan_name = titan_name
        self.parent     = parent

        self.f_name.label  = t(gid, "form_display_name_field")
        self.f_image.label = t(gid, "form_image_field")
        self.f_desc.label  = t(gid, "form_desc_field")

        players           = load_players(gid)
        player            = players.get(str(uid), {})
        power             = next((p for p in player.get("titan_powers", [])
                                  if p["titan"] == titan_name), {})
        self.f_name.default  = power.get("display_name", "")
        self.f_image.default = power.get("custom_image", "")
        self.f_desc.default  = power.get("custom_desc", "")

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for pw in player.get("titan_powers", []):
            if pw["titan"] == self.titan_name:
                pw["display_name"] = (self.f_name.value  or "").strip()
                pw["custom_image"] = (self.f_image.value or "").strip()
                pw["custom_desc"]  = (self.f_desc.value  or "").strip()
                break
        save_players(self.gid, players)
        await log_event(bot, self.gid, "shifter",
                        f"<@{self.uid}> customized form for '{self.titan_name}'")
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)
        done_embed = discord.Embed(description=t(self.gid, "form_saved"), color=EMBED_COLOR)
        await ix.followup.send(embed=done_embed, ephemeral=True)


# ── Shifter Grab / Eat Target View ─────────────────────────────────────────────

class ShifterTargetView(discord.ui.View):
    def __init__(self, uid: int, gid: int, action: str, parent):
        super().__init__(timeout=300)
        self.uid    = uid
        self.gid    = gid
        self.action = action
        self.parent = parent

        usr_sel          = discord.ui.UserSelect(placeholder=t(gid, "select_target"), row=0)
        usr_sel.callback = self._pick
        bk               = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        bk.callback      = self._back

        self.add_item(usr_sel)
        self.add_item(bk)

    def build_embed(self) -> discord.Embed:
        return discord.Embed(
            title=f"{'✊ Grab' if self.action == 'grab' else '🦷 Eat'}",
            description=t(self.gid, "select_target"),
            color=EMBED_COLOR,
        )

    async def _pick(self, ix: discord.Interaction):
        target_user = ix.data["resolved"]["users"]
        target_id   = int(ix.data["values"][0])
        eater_name  = ix.user.display_name
        target_name = f"<@{target_id}>"

        if self.action == "grab":
            await _send_grab_embed(ix.channel, self.gid, eater_name, target_name)
            await log_event(bot, self.gid, "shifter", f"{eater_name} grabbed {target_name}")
            self.parent._build()
            embed = self.parent.build_embed()
            await ix.response.edit_message(embed=embed, view=self.parent)
            return

        # ── eat action ──────────────────────────────────────────────────────────
        players       = load_players(self.gid)
        target_player = players.get(str(target_id), {})
        titan_powers  = target_player.get("titan_powers", [])
        has_shift     = has_shifter_access(self.gid, target_id)

        # Resolve target member from guild
        target_member = None
        for g in bot.guilds:
            if g.id == self.gid:
                target_member = g.get_member(target_id)
                break

        if target_member is None:
            # Try fetching
            try:
                target_member = await bot.fetch_user(target_id)
            except Exception:
                pass

        if target_member:
            eat_view = ShifterEatConsentView(
                gid=self.gid,
                eater_uid=self.uid,
                target_uid=target_id,
                channel_id=ix.channel_id,
                has_titan=(bool(titan_powers) and has_shift),
                eater_name=eater_name,
            )
            consent_embed = discord.Embed(
                title="⚔️ A Titan Shifter wants to eat you!",
                description=t(self.gid, "shifter_eat_ask_body", eater=eater_name),
                color=EMBED_COLOR,
            )
            dm_ok = await send_dm(target_member, embed=consent_embed)
            # Also send the view separately (send_dm only sends content/embed,
            # we need to send the view to the DM channel manually)
            if dm_ok:
                try:
                    dm_channel = await target_member.create_dm()
                    await dm_channel.send(view=eat_view)
                except Exception:
                    dm_ok = False

            if not dm_ok:
                err_embed = discord.Embed(
                    description=f"❌ Cannot DM {target_name} — they may have DMs disabled.",
                    color=EMBED_COLOR,
                )
                await ix.response.send_message(embed=err_embed, ephemeral=True)
                return

        # Public announcement of the attempt
        attempt_embed = discord.Embed(
            title="🦷 Eat Attempt",
            description=f"**{eater_name}** is trying to eat {target_name}...",
            color=EMBED_COLOR,
        )
        try:
            await ix.channel.send(embed=attempt_embed)
        except Exception:
            pass

        await log_event(bot, self.gid, "shifter", f"{eater_name} tried to eat {target_name}")
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Eat Consent View (sent via DM to target) ───────────────────────────────────

class ShifterEatConsentView(discord.ui.View):
    def __init__(self, gid: int, eater_uid: int, target_uid: int,
                 channel_id: int, has_titan: bool = False, eater_name: str = ""):
        super().__init__(timeout=86400)
        self.gid        = gid
        self.eater_uid  = eater_uid
        self.target_uid = target_uid
        self.channel_id = channel_id
        self.has_titan  = has_titan
        self.eater_name = eater_name

        accept_btn           = Button(label=t(gid, "mindless_eat_accept_btn"),
                                      style=discord.ButtonStyle.green,  row=0)
        decline_btn          = Button(label=t(gid, "mindless_eat_decline_btn"),
                                      style=discord.ButtonStyle.danger, row=0)
        accept_btn.callback  = self._accept
        decline_btn.callback = self._decline
        self.add_item(accept_btn)
        self.add_item(decline_btn)

    async def _accept(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            embed = discord.Embed(description="This is not for you.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        players       = load_players(self.gid)
        eater_name    = f"<@{self.eater_uid}>"
        target_name   = f"<@{self.target_uid}>"
        target_player = players.get(str(self.target_uid), {})
        titan_powers  = target_player.get("titan_powers", [])
        got_titan     = None

        if self.has_titan and titan_powers:
            cfg          = load_config(self.gid)
            now          = time.time()
            eater_player = players.get(str(self.eater_uid), {})
            if eater_player:
                for power in titan_powers:
                    titan_name = power["titan"]
                    new_power  = {
                        "titan":       titan_name,
                        "acquired_at": now,
                        "expires_at":  now + cfg.get("titan_time_days", 4745) * 86400,
                        "abilities":   power.get("abilities", []),
                    }
                    eater_player.setdefault("titan_powers", []).append(new_power)
                    got_titan = titan_name

                target_player["titan_powers"] = []

                sa = cfg.get("shifter_access", [])
                if str(self.target_uid) in sa:
                    sa.remove(str(self.target_uid))
                if str(self.eater_uid) not in sa:
                    sa.append(str(self.eater_uid))
                cfg["shifter_access"] = sa
                save_config(self.gid, cfg)

                players[str(self.eater_uid)] = eater_player

                # Notify eater of their new power
                try:
                    eater_user = await bot.fetch_user(self.eater_uid)
                    guide_embed = discord.Embed(
                        description=t(self.gid, "mindless_power_guide", titan=got_titan),
                        color=EMBED_COLOR,
                    )
                    await send_dm(eater_user, embed=guide_embed)
                except Exception:
                    pass

        players[str(self.target_uid)] = target_player
        save_players(self.gid, players)

        # Announce result in guild channel
        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    await _send_eat_embed(ch, self.gid, eater_name, target_name, got_titan)
                break

        await log_event(bot, self.gid, "shifter",
                        f"{eater_name} ate {target_name}" +
                        (f" (got {got_titan})" if got_titan else ""))

        extra = " Your titan power was transferred." if got_titan else ""
        result_embed = discord.Embed(
            description=f"You have been eaten.{extra}",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=result_embed, view=self)

    async def _decline(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            embed = discord.Embed(description="This is not for you.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await ix.response.send_modal(
            _ShifterEatRefuseModal(self.gid, self.eater_uid, self.target_uid,
                                   self.channel_id, self)
        )


class _ShifterEatRefuseModal(Modal, title="Refuse"):
    f_reason = TextInput(label="Reason", style=discord.TextStyle.paragraph,
                         max_length=200, required=False)

    def __init__(self, gid: int, eater_uid: int, target_uid: int,
                 channel_id: int, parent):
        super().__init__()
        self.gid        = gid
        self.eater_uid  = eater_uid
        self.target_uid = target_uid
        self.channel_id = channel_id
        self.parent     = parent
        self.f_reason.label = t(gid, "eat_reason_field")

    async def on_submit(self, ix: discord.Interaction):
        reason = self.f_reason.value.strip() or "No reason given"
        msg    = t(self.gid, "mindless_eat_refused",
                   target=f"<@{self.target_uid}>", reason=reason)

        # Announce refusal in guild channel
        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    refuse_embed = discord.Embed(description=msg, color=EMBED_COLOR)
                    try:
                        await ch.send(embed=refuse_embed)
                    except Exception:
                        pass
                break

        refused_embed = discord.Embed(description="Refused.", color=EMBED_COLOR)
        self.parent.clear_items()
        await ix.response.edit_message(embed=refused_embed, view=self.parent)


# ── Moveset Editor ─────────────────────────────────────────────────────────────

class MovesetEditorView(discord.ui.View):
    def __init__(self, uid: int, gid: int, titan_name: str, power: dict, parent):
        super().__init__(timeout=300)
        self.uid        = uid
        self.gid        = gid
        self.titan_name = titan_name
        self.power      = power or {}
        self.parent     = parent
        self.sel        = None
        self._build()

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=t(self.gid, "edit_moveset_btn"),
            description=(
                "Select an ability to edit, or choose *+ Add New Ability*.\n"
                "*(⚙️ = pending admin configuration)*"
            ),
            color=EMBED_COLOR,
        )
        return embed

    def _build(self):
        self.clear_items()
        abilities = self.power.get("abilities", [])
        opts      = [discord.SelectOption(
                         label=f"{a['name'][:90]} {'⚙️' if not a.get('confirmed', True) else ''}",
                         value=a["name"])
                     for a in abilities[:24]]
        opts.append(discord.SelectOption(label="+ Add New Ability", value="__new__"))

        sel          = Select(placeholder="Select ability", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)

        ed  = Button(label=t(self.gid, "edit_ability_btn"),   style=discord.ButtonStyle.primary,   row=1)
        dlt = Button(label=t(self.gid, "delete_ability_btn"), style=discord.ButtonStyle.danger,    row=1)
        bk  = Button(label=t(self.gid, "back_btn"),           style=discord.ButtonStyle.secondary, row=2)

        ed.callback  = self._edit
        dlt.callback = self._delete
        bk.callback  = self._back

        self.add_item(ed)
        self.add_item(dlt)
        self.add_item(bk)

    async def _sel(self, ix: discord.Interaction):
        self.sel = ix.data["values"][0]
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _edit(self, ix: discord.Interaction):
        if not self.sel:
            embed = discord.Embed(description="Select an ability first.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        prefill = {} if self.sel == "__new__" else next(
            (a for a in self.power.get("abilities", []) if a["name"] == self.sel), {}
        )
        await ix.response.send_modal(
            EditAbilityModal(
                self.uid, self.gid, self.titan_name, self.power, self,
                prefill, is_new=(self.sel == "__new__"),
            )
        )

    async def _delete(self, ix: discord.Interaction):
        if not self.sel or self.sel == "__new__":
            embed = discord.Embed(description="Select an existing ability.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(description="Only admins can delete abilities.", color=EMBED_COLOR)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for pw in player.get("titan_powers", []):
            if pw["titan"] == self.titan_name:
                pw["abilities"] = [a for a in pw.get("abilities", []) if a["name"] != self.sel]
                self.power      = pw
        save_players(self.gid, players)
        self.sel = None
        self._build()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _back(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        power   = next((p for p in player.get("titan_powers", [])
                        if p["titan"] == self.titan_name), self.power)
        if hasattr(self.parent, "power"):
            self.parent.power = power
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Edit Ability Modal ─────────────────────────────────────────────────────────

class EditAbilityModal(Modal, title="Edit Ability"):
    f_name  = TextInput(label="Ability Name",         max_length=60)
    f_desc  = TextInput(label="Description",          style=discord.TextStyle.paragraph,
                        max_length=300, required=False)
    f_image = TextInput(label="Image URL (optional)", max_length=500, required=False)

    def __init__(self, uid: int, gid: int, titan_name: str, power: dict,
                 parent, prefill: dict, is_new: bool):
        super().__init__()
        self.uid        = uid
        self.gid        = gid
        self.titan_name = titan_name
        self.power      = power
        self.parent     = parent
        self.is_new     = is_new
        self.prefill    = prefill
        if prefill:
            self.f_name.default  = prefill.get("name",        "")
            self.f_desc.default  = prefill.get("description", "")
            self.f_image.default = prefill.get("image_url",   "")

    async def on_submit(self, ix: discord.Interaction):
        ability_data = {
            "name":        self.f_name.value.strip(),
            "description": (self.f_desc.value  or "").strip(),
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

        pending_embed = discord.Embed(
            title=t(self.gid, "edit_moveset_btn"),
            description=t(self.gid, "moveset_pending"),
            color=EMBED_COLOR,
        )
        self.parent.clear_items()
        await ix.response.edit_message(embed=pending_embed, view=self.parent)


async def _apply_ability_edit(uid, gid: int, titan_name: str,
                              ability: dict, is_new: bool, old_name: str):
    players = load_players(gid)
    player  = players.get(str(uid), {})
    for pw in player.get("titan_powers", []):
        if pw["titan"] == titan_name:
            if is_new:
                pw.setdefault("abilities", []).append(ability)
            else:
                for i, a in enumerate(pw.get("abilities", [])):
                    if a["name"] == old_name:
                        pw["abilities"][i] = ability
                        break
    save_players(gid, players)


async def _notify_admins_moveset(guild, req_id: str, uid: int,
                                 ability_data: dict, gid: int):
    if not guild:
        return
    member = guild.get_member(int(uid))
    name   = member.display_name if member else str(uid)
    for m in guild.members:
        if m.guild_permissions.administrator:
            try:
                view        = MovesetConfigView(gid, req_id, uid, ability_data, name)
                cfg_embed   = view.build_embed()
                dm_channel  = await m.create_dm()
                await dm_channel.send(embed=cfg_embed, view=view)
            except Exception:
                pass


# ── MovesetConfigView — admin DM to set cooldown & stamina cost ────────────────

class MovesetConfigView(discord.ui.View):
    def __init__(self, gid: int, req_id: str, uid: int,
                 ability_data: dict, requester_name: str):
        super().__init__(timeout=86400)
        self.gid            = gid
        self.req_id         = req_id
        self.uid            = uid
        self.ability_data   = dict(ability_data)
        self.requester_name = requester_name
        self.cd_minutes     = 0
        self.stamina_cost   = 0
        self._build()

    def build_embed(self) -> discord.Embed:
        ab    = self.ability_data
        embed = discord.Embed(
            title="⚙️ Ability Configuration",
            description=f"Request from **{self.requester_name}**",
            color=EMBED_COLOR,
        )
        embed.add_field(name="Ability",       value=ab["name"],                            inline=False)
        embed.add_field(name="Description",   value=ab.get("description") or "*None*",     inline=False)
        embed.add_field(name="Cooldown",      value=f"{self.cd_minutes} minutes",          inline=True)
        embed.add_field(name="Stamina Cost",  value=str(self.stamina_cost),               inline=True)
        img_url = ab.get("image_url", "")
        if img_url and is_url(img_url):
            embed.set_image(url=img_url)
        return embed

    def _build(self):
        self.clear_items()

        cd_btn      = Button(label="⏱ Set Cooldown",      style=discord.ButtonStyle.secondary, row=0)
        cost_btn    = Button(label="💪 Set Stamina Cost",  style=discord.ButtonStyle.secondary, row=0)
        confirm_btn = Button(label="✅ Confirm",           style=discord.ButtonStyle.green,     row=1)
        decline_btn = Button(label="❌ Decline",           style=discord.ButtonStyle.danger,    row=1)

        cd_btn.callback      = self._set_cd
        cost_btn.callback    = self._set_cost
        confirm_btn.callback = self._confirm
        decline_btn.callback = self._decline

        self.add_item(cd_btn)
        self.add_item(cost_btn)
        self.add_item(confirm_btn)
        self.add_item(decline_btn)

    async def _set_cd(self, ix: discord.Interaction):
        await ix.response.send_modal(_AbilityCDModal(self))

    async def _set_cost(self, ix: discord.Interaction):
        await ix.response.send_modal(_AbilityCostModal(self))

    async def _confirm(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)

        if req:
            final_ability = {
                "name":             self.ability_data["name"],
                "description":      self.ability_data.get("description", ""),
                "image_url":        self.ability_data.get("image_url",   ""),
                "cooldown_minutes": self.cd_minutes,
                "stamina_cost":     self.stamina_cost,
                "confirmed":        True,
            }
            await _apply_ability_edit(
                req["user_id"], self.gid, req["titan"],
                final_ability, req["is_new"], req["old_name"],
            )
            try:
                user       = await bot.fetch_user(int(req["user_id"]))
                appr_embed = discord.Embed(
                    description=t(self.gid, "moveset_approved",
                                  ability=final_ability["name"]),
                    color=EMBED_COLOR,
                )
                await send_dm(user, embed=appr_embed)
            except Exception:
                pass

        done_embed = discord.Embed(
            description="✅ Ability confirmed and configured.",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=done_embed, view=self)

    async def _decline(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        req = cfg.get("pending_moveset_requests", {}).pop(self.req_id, None)
        save_config(self.gid, cfg)

        if req:
            try:
                user       = await bot.fetch_user(int(req["user_id"]))
                decl_embed = discord.Embed(
                    description=t(self.gid, "moveset_declined",
                                  ability=req["ability"]["name"]),
                    color=EMBED_COLOR,
                )
                await send_dm(user, embed=decl_embed)
            except Exception:
                pass

        done_embed = discord.Embed(
            description="❌ Declined and removed.",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=done_embed, view=self)


class _AbilityCDModal(Modal, title="Set Cooldown"):
    cd = TextInput(label="Cooldown (minutes)", max_length=5)

    def __init__(self, parent):
        super().__init__()
        self.parent   = parent
        self.cd.default = str(parent.cd_minutes)

    async def on_submit(self, ix: discord.Interaction):
        try:
            self.parent.cd_minutes = max(0, int(self.cd.value.strip() or "0"))
        except ValueError:
            pass
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


class _AbilityCostModal(Modal, title="Set Stamina Cost"):
    cost = TextInput(label="Stamina Cost", max_length=5)

    def __init__(self, parent):
        super().__init__()
        self.parent     = parent
        self.cost.default = str(parent.stamina_cost)

    async def on_submit(self, ix: discord.Interaction):
        try:
            self.parent.stamina_cost = max(0, int(self.cost.value.strip() or "0"))
        except ValueError:
            pass
        self.parent._build()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Background tasks ───────────────────────────────────────────────────────────

@tasks.loop(minutes=10)
async def check_titan_expiry():
    import random
    for guild in bot.guilds:
        gid     = guild.id
        cfg     = load_config(gid)
        players = load_players(gid)
        now     = time.time()
        changed = False

        for uid, player in list(players.items()):
            powers = player.get("titan_powers", [])
            if not powers or player.get("deceased"):
                continue
            if powers[0].get("expires_at", float("inf")) > now:
                continue

            titan_names           = [p["titan"] for p in powers]
            player["deceased"]    = True
            player["titan_powers"] = []
            players[uid]          = player
            changed               = True

            eligible              = []
            inheritance_races     = cfg.get("inheritance_races", [])
            for mid, mp in players.items():
                if mid == uid or mp.get("deceased"):
                    continue
                bloodline = mp.get("bloodline", "")
                if inheritance_races:
                    if bloodline not in inheritance_races:
                        continue
                else:
                    if mp.get("faction") not in cfg.get("factions", []):
                        continue
                    all_bloodlines = (cfg.get("bloodlines_common", []) +
                                      cfg.get("bloodlines_special", []))
                    if bloodline not in all_bloodlines:
                        continue
                member = guild.get_member(int(mid))
                if member:
                    eligible.append((mid, mp, member))

            for titan in titan_names:
                new_owner_data = random.choice(eligible) if eligible else None
                old_member     = guild.get_member(int(uid))
                old_name       = old_member.display_name if old_member else uid

                if new_owner_data:
                    new_uid, new_player, new_member = new_owner_data
                    titan_days = cfg.get("titan_time_days", 4745)
                    new_power  = {
                        "titan":       titan,
                        "acquired_at": now,
                        "expires_at":  now + titan_days * 86400,
                        "abilities":   [],
                    }
                    existing = new_player.get("titan_powers", [])
                    if existing:
                        new_power["expires_at"] = existing[0]["expires_at"]
                    new_player.setdefault("titan_powers", []).append(new_power)
                    players[new_uid] = new_player

                    got_embed = discord.Embed(
                        description=t(gid, "got_titan_dm", titan=titan),
                        color=EMBED_COLOR,
                    )
                    await send_dm(new_member, embed=got_embed)

                    new_name = new_member.display_name
                    for m in guild.members:
                        if m.guild_permissions.administrator:
                            admin_embed = discord.Embed(
                                description=t(gid, "admin_got_titan",
                                              new_owner=new_name, titan=titan,
                                              old_owner=old_name),
                                color=EMBED_COLOR,
                            )
                            await send_dm(m, embed=admin_embed)

                    ch_id = cfg.get("titan_announcement_channel")
                    if ch_id:
                        ch = guild.get_channel(int(ch_id))
                        if ch:
                            ann_embed = discord.Embed(
                                description=t(gid, "titan_died",
                                              name=old_name, titan=titan,
                                              new_owner=new_name),
                                color=EMBED_COLOR,
                            )
                            try:
                                await ch.send(embed=ann_embed)
                            except Exception:
                                pass

        if changed:
            save_players(gid, players)


@tasks.loop(minutes=1)
async def regen_stamina_task():
    for guild in bot.guilds:
        gid     = guild.id
        cfg     = load_config(gid)
        players = load_players(gid)
        changed = False
        for uid, player in players.items():
            if player.get("stamina", 100) < player.get("max_stamina", 100):
                old    = player.get("stamina", 100)
                player = _regen_stamina(player, cfg)
                if player["stamina"] != old:
                    players[uid] = player
                    changed      = True
        if changed:
            save_players(gid, players)


def start_tasks():
    if not check_titan_expiry.is_running():
        check_titan_expiry.start()
    if not regen_stamina_task.is_running():
        regen_stamina_task.start()
