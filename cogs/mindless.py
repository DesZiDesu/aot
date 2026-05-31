"""Mindless Titan system — /mindless, /mindless-inject, /mindless-revert."""
import time
import discord
from discord import app_commands
from discord.ext import commands

from core.instance import bot
from core.shared import (
    t, load_config, save_config, load_players, save_players,
    has_shifter_access, send_dm, log_event, can_become_mindless,
    EMBED_COLOR,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_mindless(gid: int, uid: int) -> bool:
    return load_players(gid).get(str(uid), {}).get("mindless_titan", False)


def _is_admin_or_manage(member: discord.Member) -> bool:
    return member and (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
    )


def _make_embed(title: str, description: str = None, color: int = EMBED_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, color=color)
    if description:
        embed.description = description
    return embed


def _get_guild(gid: int) -> discord.Guild | None:
    return discord.utils.get(bot.guilds, id=gid)


async def _send_channel(channel: discord.abc.Messageable, embed: discord.Embed) -> None:
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


def _build_mindless_panel(gid: int, uid: int) -> tuple[discord.Embed, "MindlessView"]:
    """Build the main mindless titan status embed + view."""
    player = load_players(gid).get(str(uid), {})
    acq = player.get("mindless_acquired_at", 0)
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(acq)) if acq else "?"
    char_name = player.get("name", "?")
    bloodline = player.get("bloodline", "?")
    faction = player.get("faction", "?")

    embed = discord.Embed(title=t(gid, "mindless_title"), color=EMBED_COLOR)
    embed.add_field(name=t(gid, "name_label"),      value=char_name, inline=True)
    embed.add_field(name=t(gid, "bloodline_label"), value=bloodline, inline=True)
    embed.add_field(name=t(gid, "faction_label"),   value=faction,   inline=True)
    embed.add_field(name="🕒 Since",                value=ts,        inline=False)
    embed.set_footer(text="🧟 Mindless Titan Active")

    view = MindlessView(gid, uid)
    return embed, view


# ── /mindless ──────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="mindless",
    description="Open the Mindless Titan panel",
    description_localizations={"th": "เปิดแผงไทแทนที่ไร้สติ"},
)
async def mindless_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    if not _is_mindless(ix.guild_id, ix.user.id):
        embed = _make_embed(
            t(ix.guild_id, "mindless_title"),
            t(ix.guild_id, "mindless_no_perm"),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    embed, view = _build_mindless_panel(ix.guild_id, ix.user.id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class MindlessView(discord.ui.View):
    """Main panel shown to the mindless titan player."""

    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid

        grab_btn = discord.ui.Button(
            label=t(gid, "mindless_grab_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="ml_grab",
        )
        eat_btn = discord.ui.Button(
            label=t(gid, "mindless_eat_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ml_eat",
        )
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="ml_done",
            row=1,
        )
        grab_btn.callback = self._grab
        eat_btn.callback  = self._eat
        done_btn.callback = self._done

        self.add_item(grab_btn)
        self.add_item(eat_btn)
        self.add_item(done_btn)

    async def _grab(self, ix: discord.Interaction):
        embed = _make_embed(
            t(self.gid, "mindless_title"),
            f"**{t(self.gid, 'mindless_grab_btn')}** — {t(self.gid, 'select_target')}",
        )
        view = MindlessTargetView(self.gid, self.uid, "grab", self)
        await ix.response.edit_message(embed=embed, view=view)

    async def _eat(self, ix: discord.Interaction):
        embed = _make_embed(
            t(self.gid, "mindless_title"),
            f"**{t(self.gid, 'mindless_eat_btn')}** — {t(self.gid, 'select_target')}",
        )
        view = MindlessTargetView(self.gid, self.uid, "eat", self)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = _make_embed(
            t(self.gid, "mindless_title"),
            f"*{t(self.gid, 'panel_closed')}*",
        )
        self.stop()
        await ix.response.edit_message(embed=embed, view=None)


class MindlessTargetView(discord.ui.View):
    """Shown when the player selects Grab or Eat — contains a UserSelect."""

    def __init__(self, gid: int, uid: int, action: str, parent: MindlessView):
        super().__init__(timeout=300)
        self.gid    = gid
        self.uid    = uid
        self.action = action
        self.parent = parent

        select = discord.ui.UserSelect(
            placeholder=t(gid, "select_target"),
            min_values=1,
            max_values=1,
            row=0,
        )
        select.callback = self._pick
        self.add_item(select)

        back_btn = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="mtv_back",
            row=1,
        )
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _pick(self, ix: discord.Interaction):
        target = ix.data["resolved"]["members"]
        # UserSelect values contains user IDs as strings
        target_id = int(ix.data["values"][0])

        if target_id == self.uid:
            err_embed = _make_embed(
                t(self.gid, "mindless_title"),
                "❌ You cannot target yourself.",
            )
            await ix.response.send_message(embed=err_embed, ephemeral=True)
            return

        eater_name     = ix.user.display_name
        target_mention = f"<@{target_id}>"

        if self.action == "grab":
            msg = t(self.gid, "mindless_grab_msg", name=eater_name, target=target_mention)
            pub_embed = _make_embed(t(self.gid, "mindless_title"), msg)
            await _send_channel(ix.channel, pub_embed)
            await log_event(bot, self.gid, "mindless",
                            f"{eater_name} grabbed {target_mention}")

            # Return to main panel
            panel_embed, panel_view = _build_mindless_panel(self.gid, self.uid)
            await ix.response.edit_message(embed=panel_embed, view=panel_view)

        else:  # eat
            # Announce attempt in channel first
            pub_embed = _make_embed(
                t(self.gid, "mindless_title"),
                f"**{eater_name}** is trying to eat **{target_mention}**...",
            )
            await _send_channel(ix.channel, pub_embed)

            # Resolve the actual Member object for DM
            guild  = _get_guild(self.gid)
            member = guild.get_member(target_id) if guild else None
            if member is None:
                # Fallback: fetch from guild
                try:
                    member = await guild.fetch_member(target_id)
                except Exception:
                    member = None

            if member is None:
                err_embed = _make_embed(
                    t(self.gid, "mindless_title"),
                    f"❌ Could not resolve member {target_mention}.",
                )
                await ix.response.send_message(embed=err_embed, ephemeral=True)
                return

            # Build the consent embed
            dm_embed = discord.Embed(
                title=t(self.gid, "mindless_title"),
                description=t(self.gid, "mindless_eat_ask_body", eater=eater_name),
                color=EMBED_COLOR,
            )
            dm_embed.set_footer(text="You have 24 hours to respond.")

            # Build consent view (needs to travel with the embed in the DM)
            consent_view = EatConsentView(
                self.gid, self.uid, target_id, ix.channel_id
            )

            # Send DM — must use create_dm directly because we need to attach a View
            try:
                dm_ch = await member.create_dm()
                await dm_ch.send(embed=dm_embed, view=consent_view)
            except (discord.Forbidden, discord.HTTPException):
                err_embed = _make_embed(
                    t(self.gid, "mindless_title"),
                    f"❌ Could not send DM to {target_mention}. They may have DMs disabled.",
                )
                await ix.response.send_message(embed=err_embed, ephemeral=True)
                return

            await log_event(bot, self.gid, "mindless",
                            f"{eater_name} tried to eat {target_mention}")

            # Return to main panel
            panel_embed, panel_view = _build_mindless_panel(self.gid, self.uid)
            await ix.response.edit_message(embed=panel_embed, view=panel_view)

    async def _back(self, ix: discord.Interaction):
        panel_embed, panel_view = _build_mindless_panel(self.gid, self.uid)
        await ix.response.edit_message(embed=panel_embed, view=panel_view)


# ── Eat consent (sent via DM) ─────────────────────────────────────────────────

class EatConsentView(discord.ui.View):
    """Sent to the target's DM. Accept transfers titan power; Decline opens modal."""

    def __init__(self, gid: int, eater_uid: int, target_uid: int, channel_id: int):
        super().__init__(timeout=86400)
        self.gid        = gid
        self.eater_uid  = eater_uid
        self.target_uid = target_uid
        self.channel_id = channel_id

        accept_btn = discord.ui.Button(
            label=t(gid, "mindless_eat_accept_btn"),
            style=discord.ButtonStyle.green,
            custom_id="ec_accept",
        )
        decline_btn = discord.ui.Button(
            label=t(gid, "mindless_eat_decline_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ec_decline",
        )
        accept_btn.callback  = self._accept
        decline_btn.callback = self._decline
        self.add_item(accept_btn)
        self.add_item(decline_btn)

    async def _accept(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            err = _make_embed("Error", "This consent prompt is not for you.")
            await ix.response.send_message(embed=err, ephemeral=True)
            return

        players        = load_players(self.gid)
        eater_mention  = f"<@{self.eater_uid}>"
        target_mention = f"<@{self.target_uid}>"
        target_player  = players.get(str(self.target_uid), {})
        titan_powers   = target_player.get("titan_powers", [])
        msg_text       = ""

        if titan_powers and has_shifter_access(self.gid, self.target_uid):
            # Transfer every titan power to the eater
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

                    # Strip the power from target
                    target_player["titan_powers"] = [
                        p for p in titan_powers if p["titan"] != titan_name
                    ]

                    # Update shifter_access list in config
                    sa = cfg.get("shifter_access", [])
                    if str(self.target_uid) in sa:
                        sa.remove(str(self.target_uid))
                    if str(self.eater_uid) not in sa:
                        sa.append(str(self.eater_uid))
                    cfg["shifter_access"] = sa
                    save_config(self.gid, cfg)

                # DM the eater about the power gain
                power_embed = discord.Embed(
                    title=t(self.gid, "mindless_title"),
                    description=t(self.gid, "mindless_power_guide", titan=titan_name),
                    color=EMBED_COLOR,
                )
                guild        = _get_guild(self.gid)
                eater_member = guild.get_member(self.eater_uid) if guild else None
                if eater_member:
                    await send_dm(eater_member, embed=power_embed)

                msg_text = t(
                    self.gid, "mindless_ate_shifter_msg",
                    eater=eater_mention, target=target_mention, titan=titan_name,
                )
        else:
            msg_text = t(
                self.gid, "mindless_ate_normal_msg",
                eater=eater_mention, target=target_mention,
            )

        # Clear mindless flag from target
        target_player["mindless_titan"] = False
        players[str(self.target_uid)]   = target_player
        save_players(self.gid, players)

        await log_event(bot, self.gid, "mindless",
                        f"{eater_mention} ate {target_mention}")

        # Announce in the original channel
        guild = _get_guild(self.gid)
        if guild:
            ch = guild.get_channel(self.channel_id)
            if ch:
                pub_embed = _make_embed(t(self.gid, "mindless_title"), msg_text)
                await _send_channel(ch, pub_embed)

        # Update the DM message
        done_embed = _make_embed(
            t(self.gid, "mindless_title"),
            "You have been eaten.",
        )
        self.stop()
        await ix.response.edit_message(embed=done_embed, view=None)

    async def _decline(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            err = _make_embed("Error", "This consent prompt is not for you.")
            await ix.response.send_message(embed=err, ephemeral=True)
            return
        modal = EatRefuseModal(
            self.gid, self.eater_uid, self.target_uid, self.channel_id, self
        )
        await ix.response.send_modal(modal)


class EatRefuseModal(discord.ui.Modal):
    f_reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        max_length=200,
        required=False,
    )

    def __init__(self, gid: int, eater_uid: int, target_uid: int,
                 channel_id: int, parent: EatConsentView):
        super().__init__(title=t(gid, "mindless_eat_decline_btn"))
        self.gid        = gid
        self.eater_uid  = eater_uid
        self.target_uid = target_uid
        self.channel_id = channel_id
        self.parent     = parent
        self.f_reason.label = t(gid, "eat_reason_field")

    async def on_submit(self, ix: discord.Interaction):
        reason = self.f_reason.value.strip() or "No reason given"
        msg    = t(
            self.gid, "mindless_eat_refused",
            target=f"<@{self.target_uid}>",
            reason=reason,
        )

        guild = _get_guild(self.gid)
        if guild:
            ch = guild.get_channel(self.channel_id)
            if ch:
                pub_embed = _make_embed(t(self.gid, "mindless_title"), msg)
                await _send_channel(ch, pub_embed)

        done_embed = _make_embed(t(self.gid, "mindless_title"), "You refused.")
        self.parent.stop()
        await ix.response.edit_message(embed=done_embed, view=None)


# ── /mindless-inject (admin) ──────────────────────────────────────────────────

@bot.tree.command(
    name="mindless-inject",
    description="Inject multiple players to make them Mindless Titans (admin only)",
    description_localizations={
        "th": "ฉีดยาผู้เล่นหลายคนให้กลายเป็นไทแทนที่ไร้สติ (แอดมินเท่านั้น)"
    },
)
async def mindless_inject_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not _is_admin_or_manage(m):
        embed = _make_embed(
            t(ix.guild_id, "mindless_title"),
            t(ix.guild_id, "admin_only"),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return

    embed = _make_embed(
        t(ix.guild_id, "mindless_title"),
        t(ix.guild_id, "mindless_inject_select_btn")
        + " — "
        + t(ix.guild_id, "select_multiple_targets"),
    )
    view = InjectSelectView(ix.guild_id, ix.user.id, ix.channel_id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class InjectUserSelect(discord.ui.UserSelect):
    """Multi-select (up to 5) for injection targets."""

    def __init__(self, gid: int, injector_uid: int, channel_id: int):
        super().__init__(
            placeholder=t(gid, "select_multiple_targets"),
            min_values=1,
            max_values=5,
            row=0,
        )
        self.gid          = gid
        self.injector_uid = injector_uid
        self.channel_id   = channel_id

    async def callback(self, ix: discord.Interaction):
        injector_name = ix.user.display_name
        players       = load_players(self.gid)
        guild         = _get_guild(self.gid)
        ch            = guild.get_channel(self.channel_id) if guild else None

        results:          list[str]            = []
        injected_members: list[discord.Member] = []

        for target in self.values:
            player = players.get(str(target.id), {})
            if not player:
                results.append(f"❌ {target.mention} — not registered.")
                continue

            allowed, reason_key = can_become_mindless(self.gid, player)
            if not allowed:
                if reason_key == "mindless_cannot_inject_bloodline":
                    bloodline = player.get("bloodline", "?")
                    results.append(
                        f"❌ {target.mention} — "
                        + t(self.gid, reason_key, bloodline=bloodline)
                    )
                else:
                    results.append(
                        f"❌ {target.mention} — " + t(self.gid, reason_key)
                    )
                continue

            # Apply injection
            player["mindless_titan"]       = True
            player["mindless_acquired_at"] = time.time()
            players[str(target.id)]        = player
            injected_members.append(target)
            results.append(f"✅ {target.mention}")

        save_players(self.gid, players)

        # DM each successfully injected user and announce in channel
        for member in injected_members:
            dm_embed = discord.Embed(
                title=t(self.gid, "mindless_title"),
                description=t(
                    self.gid, "mindless_injected_notify", injector=injector_name
                ),
                color=EMBED_COLOR,
            )
            dm_embed.set_footer(text="Use /mindless to control yourself.")
            dm_ok = await send_dm(member, embed=dm_embed)
            if not dm_ok:
                results.append(
                    f"⚠️ {member.mention} — DM could not be delivered (DMs disabled)."
                )

            # Announce injection in channel
            if ch:
                pub_embed = _make_embed(
                    t(self.gid, "mindless_title"),
                    t(
                        self.gid, "mindless_inject_msg",
                        user=member.display_name, injector=injector_name,
                    ),
                )
                await _send_channel(ch, pub_embed)

            await log_event(
                bot, self.gid, "mindless",
                f"{injector_name} injected {member.display_name}",
            )

        result_text  = "\n".join(results) or "No targets processed."
        result_embed = _make_embed(t(self.gid, "mindless_title"), result_text)
        await ix.response.edit_message(embed=result_embed, view=None)


class InjectSelectView(discord.ui.View):
    def __init__(self, gid: int, injector_uid: int, channel_id: int):
        super().__init__(timeout=120)
        self.gid = gid
        self.add_item(InjectUserSelect(gid, injector_uid, channel_id))

        cancel_btn = discord.ui.Button(
            label=t(gid, "cancel_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="inj_cancel",
            row=1,
        )
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _cancel(self, ix: discord.Interaction):
        embed = _make_embed(t(self.gid, "mindless_title"), t(self.gid, "panel_closed"))
        self.stop()
        await ix.response.edit_message(embed=embed, view=None)


# ── /mindless-revert (admin) ──────────────────────────────────────────────────

@bot.tree.command(
    name="mindless-revert",
    description="Revert a Mindless Titan back to human form (admin only)",
    description_localizations={
        "th": "คืนสภาพไทแทนไร้สติให้กลับเป็นมนุษย์ (แอดมินเท่านั้น)"
    },
)
async def mindless_revert_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not _is_admin_or_manage(m):
        embed = _make_embed(
            t(ix.guild_id, "mindless_title"),
            t(ix.guild_id, "admin_only"),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return

    embed = _make_embed(
        t(ix.guild_id, "mindless_title"),
        t(ix.guild_id, "mindless_revert_btn")
        + " — "
        + t(ix.guild_id, "select_target"),
    )
    view = RevertSelectView(ix.guild_id, ix.user.id, ix.channel_id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class RevertUserSelect(discord.ui.UserSelect):
    """Single-select for the player to revert from mindless titan."""

    def __init__(self, gid: int, admin_uid: int, channel_id: int):
        super().__init__(
            placeholder=t(gid, "select_target"),
            min_values=1,
            max_values=1,
            row=0,
        )
        self.gid       = gid
        self.admin_uid = admin_uid
        self.channel_id = channel_id

    async def callback(self, ix: discord.Interaction):
        target  = self.values[0]
        players = load_players(self.gid)
        player  = players.get(str(target.id), {})

        if not player:
            err_embed = _make_embed(
                t(self.gid, "mindless_title"),
                "❌ Player not registered.",
            )
            await ix.response.edit_message(embed=err_embed, view=None)
            return

        if not player.get("mindless_titan", False):
            err_embed = _make_embed(
                t(self.gid, "mindless_title"),
                f"❌ {target.mention} is not currently a Mindless Titan.",
            )
            await ix.response.edit_message(embed=err_embed, view=None)
            return

        # Remove mindless flag
        player["mindless_titan"] = False
        player.pop("mindless_acquired_at", None)
        players[str(target.id)] = player
        save_players(self.gid, players)

        player_name = player.get("name") or target.display_name

        # DM the player
        dm_embed = discord.Embed(
            title=t(self.gid, "mindless_title"),
            description=t(self.gid, "mindless_reverted_dm"),
            color=EMBED_COLOR,
        )
        dm_ok = await send_dm(target, embed=dm_embed)

        # Announce in channel
        guild = _get_guild(self.gid)
        if guild:
            ch = guild.get_channel(self.channel_id)
            if ch:
                pub_embed = _make_embed(
                    t(self.gid, "mindless_title"),
                    t(self.gid, "mindless_reverted_msg", name=player_name),
                )
                await _send_channel(ch, pub_embed)

        await log_event(
            bot, self.gid, "mindless",
            f"{ix.user.display_name} reverted {player_name} to human",
        )

        lines = [t(self.gid, "mindless_reverted_msg", name=player_name)]
        if not dm_ok:
            lines.append(
                f"⚠️ DM could not be delivered to {target.mention} (DMs disabled)."
            )

        result_embed = _make_embed(t(self.gid, "mindless_title"), "\n".join(lines))
        await ix.response.edit_message(embed=result_embed, view=None)


class RevertSelectView(discord.ui.View):
    def __init__(self, gid: int, admin_uid: int, channel_id: int):
        super().__init__(timeout=120)
        self.gid = gid
        self.add_item(RevertUserSelect(gid, admin_uid, channel_id))

        cancel_btn = discord.ui.Button(
            label=t(gid, "cancel_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rev_cancel",
            row=1,
        )
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _cancel(self, ix: discord.Interaction):
        embed = _make_embed(t(self.gid, "mindless_title"), t(self.gid, "panel_closed"))
        self.stop()
        await ix.response.edit_message(embed=embed, view=None)
