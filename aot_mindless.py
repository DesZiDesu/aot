"""Mindless Titan system — /mindless, /mindless-inject with embed UI and multi-target injection."""
import time
import asyncio
import discord
from discord import app_commands

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, load_players, save_players,
    has_shifter_access, cv2_dm, log_event, is_url,
)


def _is_mindless(gid: int, uid: int) -> bool:
    return load_players(gid).get(str(uid), {}).get("mindless_titan", False)


def _is_admin_or_manage(member) -> bool:
    return member and (member.guild_permissions.administrator
                       or member.guild_permissions.manage_guild)


def _is_immune_to_mindless(gid: int, uid: int) -> bool:
    """Returns True if this player cannot become mindless (shifter or immune bloodline)."""
    cfg    = load_config(gid)
    player = load_players(gid).get(str(uid), {})

    # Shifters are immune
    if player.get("titan_powers") and has_shifter_access(gid, uid):
        return True

    # Ackerman bloodline check (always immune)
    bloodline = (player.get("bloodline") or "").lower()
    if "ackerman" in bloodline:
        return True

    # Admin-configured immune bloodlines
    immune_bloodlines = [b.lower() for b in cfg.get("bloodlines_immune_mindless", [])]
    if immune_bloodlines and bloodline in immune_bloodlines:
        return True

    return False


def _pub_embed(text: str, color: int = 0x2f3136) -> discord.Embed:
    return discord.Embed(description=text, color=color)


# ── /mindless ─────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="mindless",
    description="Open mindless titan panel | เปิดแผงไททันไร้จิตสำนึก",
    guild=GUILD2_OBJ,
)
async def mindless_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    if not _is_mindless(ix.guild_id, ix.user.id):
        embed = discord.Embed(
            description=t(ix.guild_id, "mindless_no_perm"),
            color=discord.Color.red(),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    player = load_players(ix.guild_id).get(str(ix.user.id), {})
    embed  = _mindless_embed(ix.guild_id, player)
    await ix.response.send_message(embed=embed, view=MindlessView(ix.guild_id, ix.user.id), ephemeral=True)


def _mindless_embed(gid: int, player: dict) -> discord.Embed:
    acq = player.get("mindless_acquired_at", 0)
    ts  = time.strftime("%Y-%m-%d %H:%M", time.localtime(acq)) if acq else "?"
    embed = discord.Embed(
        title=t(gid, "mindless_title"),
        description=f"Became mindless: **{ts}**",
        color=0xe74c3c,
    )
    return embed


class MindlessView(discord.ui.View):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        btn_grab = discord.ui.Button(
            label=t(self.gid, "mindless_grab_btn"),
            style=discord.ButtonStyle.secondary, row=0,
        )
        btn_eat = discord.ui.Button(
            label=t(self.gid, "mindless_eat_btn"),
            style=discord.ButtonStyle.danger, row=0,
        )
        btn_done = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.secondary, row=1,
        )
        btn_grab.callback = self._grab
        btn_eat.callback  = self._eat
        btn_done.callback = self._done
        self.add_item(btn_grab)
        self.add_item(btn_eat)
        self.add_item(btn_done)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your panel.", ephemeral=True); return False
        return True

    async def _grab(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Grab", description="Select a target:", color=0x7f8c8d),
            view=MindlessTargetView(self.gid, self.uid, "grab", self),
        )

    async def _eat(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Eat", description="Select a target:", color=0xe74c3c),
            view=MindlessTargetView(self.gid, self.uid, "eat", self),
        )

    async def _done(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        embed  = _mindless_embed(self.gid, player)
        embed.set_footer(text=t(self.gid, "panel_closed"))
        await ix.response.edit_message(embed=embed, view=None)


class MindlessTargetView(discord.ui.View):
    def __init__(self, gid: int, uid: int, action: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.action = action; self.parent = parent

        usr_sel = discord.ui.UserSelect(
            placeholder=t(gid, "select_target"),
            min_values=1, max_values=1,
            row=0,
        )
        usr_sel.callback = self._pick
        btn_bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        btn_bk.callback = self._back
        self.add_item(usr_sel)
        self.add_item(btn_bk)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your panel.", ephemeral=True); return False
        return True

    async def _pick(self, ix: discord.Interaction):
        target_id = int(ix.data["values"][0])
        if target_id == self.uid:
            await ix.response.send_message("Cannot target yourself.", ephemeral=True); return

        eater_name  = ix.user.display_name
        target_name = f"<@{target_id}>"

        if self.action == "grab":
            msg = t(self.gid, "mindless_grab_msg", name=eater_name, target=target_name)
            try:
                await ix.channel.send(embed=_pub_embed(msg, 0x7f8c8d))
            except Exception:
                pass
            await log_event(bot, self.gid, "mindless", f"{eater_name} grabbed {target_name}")
            self.parent._rebuild()
            player = load_players(self.gid).get(str(self.uid), {})
            await ix.response.edit_message(embed=_mindless_embed(self.gid, player), view=self.parent)

        else:  # eat
            for g in bot.guilds:
                if g.id == self.gid:
                    member = g.get_member(target_id)
                    if member:
                        consent_view = MindlessEatConsentView(
                            self.gid, self.uid, target_id, ix.channel_id
                        )
                        dm_embed = discord.Embed(
                            title="A Mindless Titan is trying to eat you!",
                            description=f"**{eater_name}** is attempting to eat you. Do you accept?",
                            color=0xe74c3c,
                        )
                        try:
                            dm = await member.create_dm()
                            await dm.send(embed=dm_embed, view=consent_view)
                        except Exception:
                            pass
                    break

            pub_msg = f"**{eater_name}** is trying to eat **{target_name}**..."
            try:
                await ix.channel.send(embed=_pub_embed(pub_msg, 0xe74c3c))
            except Exception:
                pass
            await log_event(bot, self.gid, "mindless", f"{eater_name} tried to eat {target_name}")
            self.parent._rebuild()
            player = load_players(self.gid).get(str(self.uid), {})
            await ix.response.edit_message(embed=_mindless_embed(self.gid, player), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._rebuild()
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.edit_message(embed=_mindless_embed(self.gid, player), view=self.parent)


class MindlessEatConsentView(discord.ui.View):
    def __init__(self, gid: int, eater_uid: int, target_uid: int, channel_id: int):
        super().__init__(timeout=86400)
        self.gid = gid; self.eater_uid = eater_uid
        self.target_uid = target_uid; self.channel_id = channel_id

        btn_acc = discord.ui.Button(
            label=t(gid, "mindless_eat_accept_btn"),
            style=discord.ButtonStyle.green,
        )
        btn_dec = discord.ui.Button(
            label=t(gid, "mindless_eat_decline_btn"),
            style=discord.ButtonStyle.danger,
        )
        btn_acc.callback = self._accept
        btn_dec.callback = self._decline
        self.add_item(btn_acc)
        self.add_item(btn_dec)

    async def _accept(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            await ix.response.send_message("This is not for you.", ephemeral=True); return

        players       = load_players(self.gid)
        eater_name    = f"<@{self.eater_uid}>"
        target_name   = f"<@{self.target_uid}>"
        target_player = players.get(str(self.target_uid), {})
        titan_powers  = target_player.get("titan_powers", [])

        if titan_powers and has_shifter_access(self.gid, self.target_uid):
            cfg = load_config(self.gid)
            now = time.time()
            for power in titan_powers:
                titan_name = power["titan"]
                new_power  = {
                    "titan":       titan_name,
                    "acquired_at": now,
                    "expires_at":  now + cfg.get("titan_time_days", 4745) * 86400,
                    "abilities":   power.get("abilities", []),
                }
                eater_player = players.get(str(self.eater_uid), {})
                if eater_player:
                    eater_player.setdefault("titan_powers", []).append(new_power)
                    players[str(self.eater_uid)] = eater_player
            target_player["titan_powers"] = []
            sa = cfg.get("shifter_access", [])
            if str(self.target_uid) in sa: sa.remove(str(self.target_uid))
            if str(self.eater_uid) not in sa: sa.append(str(self.eater_uid))
            cfg["shifter_access"] = sa
            from aot_shared import save_config
            save_config(self.gid, cfg)
            titan_names = ", ".join(p["titan"] for p in titan_powers)
            msg_text = t(self.gid, "mindless_ate_shifter_msg",
                         eater=eater_name, target=target_name, titan=titan_names)
            try:
                await cv2_dm(ix.user, t(self.gid, "mindless_power_guide", titan=titan_names))
            except Exception:
                pass
        else:
            msg_text = t(self.gid, "mindless_ate_normal_msg", eater=eater_name, target=target_name)

        target_player["mindless_titan"] = False
        players[str(self.target_uid)] = target_player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "mindless", f"{eater_name} ate {target_name}")

        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    try:
                        await ch.send(embed=_pub_embed(msg_text, 0xe74c3c))
                    except Exception:
                        pass
                break

        embed = discord.Embed(description="You have been eaten.", color=discord.Color.red())
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)

    async def _decline(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            await ix.response.send_message("This is not for you.", ephemeral=True); return
        await ix.response.send_modal(
            MindlessEatRefuseModal(self.gid, self.eater_uid, self.target_uid, self.channel_id, self)
        )


class MindlessEatRefuseModal(discord.ui.Modal, title="Refuse"):
    f_reason = discord.ui.TextInput(
        label="Reason (optional)",
        style=discord.TextStyle.paragraph,
        max_length=200, required=False,
    )

    def __init__(self, gid: int, eater_uid: int, target_uid: int, channel_id: int, parent):
        super().__init__()
        self.gid = gid; self.eater_uid = eater_uid
        self.target_uid = target_uid; self.channel_id = channel_id; self.parent = parent
        self.f_reason.label = t(gid, "eat_reason_field")

    async def on_submit(self, ix: discord.Interaction):
        reason = self.f_reason.value.strip() or "No reason given"
        msg    = t(self.gid, "mindless_eat_refused",
                   target=f"<@{self.target_uid}>", reason=reason)
        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    try:
                        await ch.send(embed=_pub_embed(msg, 0x7f8c8d))
                    except Exception:
                        pass
                break
        embed = discord.Embed(description="Refused.", color=discord.Color.orange())
        self.parent.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


# ── /mindless-inject (admin) — multi-target ──────────────────────────────────

@bot.tree.command(
    name="mindless-inject",
    description="[Admin] Inject player(s) to make them Mindless Titans | ฉีดสารให้ผู้เล่น",
    guild=GUILD2_OBJ,
)
async def mindless_inject_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    m = ix.guild.get_member(ix.user.id)
    if not _is_admin_or_manage(m):
        embed = discord.Embed(
            description=t(ix.guild_id, "admin_only"),
            color=discord.Color.red(),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    embed = discord.Embed(
        title="Mindless Titan Injection",
        description="Select players to inject (up to 10 at once).",
        color=0xe74c3c,
    )
    await ix.response.send_message(
        embed=embed,
        view=_MultiInjectView(ix.guild_id, ix.channel_id),
        ephemeral=True,
    )


class _MultiInjectView(discord.ui.View):
    def __init__(self, gid: int, channel_id: int):
        super().__init__(timeout=300)
        self.gid = gid; self.channel_id = channel_id
        self.selected_users: list[int] = []
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        sel = discord.ui.UserSelect(
            placeholder="Select targets (up to 10)",
            min_values=1,
            max_values=10,
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        self.selected_users = [int(v) for v in ix.data["values"]]
        embed = discord.Embed(
            title="Confirm Injection",
            description="**Targets:**\n" + "\n".join(f"• <@{uid}>" for uid in self.selected_users),
            color=0xe74c3c,
        )

        self.clear_items()
        btn_confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger, row=0)
        btn_cancel  = discord.ui.Button(label="Cancel",  style=discord.ButtonStyle.secondary, row=0)
        btn_confirm.callback = self._confirm
        btn_cancel.callback  = self._cancel
        self.add_item(btn_confirm)
        self.add_item(btn_cancel)
        await ix.response.edit_message(embed=embed, view=self)

    async def _confirm(self, ix: discord.Interaction):
        gid = self.gid
        players = load_players(gid)
        cfg     = load_config(gid)
        injected = []
        blocked  = []

        for uid in self.selected_users:
            player = players.get(str(uid), {})
            if not player:
                blocked.append((uid, "not registered"))
                continue
            if _is_immune_to_mindless(gid, uid):
                blocked.append((uid, "immune (shifter or protected bloodline)"))
                continue
            player["mindless_titan"]       = True
            player["mindless_acquired_at"] = time.time()
            players[str(uid)] = player
            injected.append(uid)

        save_players(gid, players)

        injector_name = ix.user.display_name
        for uid in injected:
            msg = t(gid, "mindless_inject_msg",
                    user=f"<@{uid}>", injector=injector_name)
            for g in bot.guilds:
                if g.id == gid:
                    ch = g.get_channel(self.channel_id)
                    if ch:
                        try:
                            await ch.send(embed=_pub_embed(msg, 0xe74c3c))
                        except Exception:
                            pass
                    # DM injected player
                    member = g.get_member(uid)
                    if member:
                        try:
                            dm_embed = discord.Embed(
                                title="You have been injected!",
                                description=(
                                    "You are now a Mindless Titan.\n"
                                    "Use the `/mindless` command to open your titan panel."
                                ),
                                color=0xe74c3c,
                            )
                            await member.send(embed=dm_embed)
                        except Exception:
                            pass
                    break

        await log_event(bot, gid, "mindless",
                        f"{injector_name} injected: {', '.join(f'<@{u}>' for u in injected)}")

        result_lines = []
        if injected:
            result_lines.append(f"**Injected:** {', '.join(f'<@{u}>' for u in injected)}")
        if blocked:
            for uid, reason in blocked:
                result_lines.append(f"**Blocked** <@{uid}>: {reason}")

        embed = discord.Embed(
            title="Injection Results",
            description="\n".join(result_lines) or "No players processed.",
            color=discord.Color.green() if injected else discord.Color.orange(),
        )
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)

    async def _cancel(self, ix: discord.Interaction):
        embed = discord.Embed(description="Cancelled.", color=discord.Color.orange())
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)
