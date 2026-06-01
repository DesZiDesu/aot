"""Mindless Titan system — /mindless, /mindless-inject."""
import time
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

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


# ── /mindless ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="mindless",
                  description="Open mindless titan panel",
                  guild=GUILD2_OBJ)
async def mindless_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if not _is_mindless(ix.guild_id, ix.user.id):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(ix.guild_id, "mindless_no_perm"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(view=MindlessView(ix.guild_id, ix.user.id), ephemeral=True)


class MindlessView(LayoutView):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid
        self._build()

    def _build(self):
        self.clear_items()
        player = load_players(self.gid).get(str(self.uid), {})
        acq    = player.get("mindless_acquired_at", 0)
        ts     = time.strftime("%Y-%m-%d %H:%M", time.localtime(acq)) if acq else "?"
        text   = f"**{t(self.gid,'mindless_title')}**\n\nSince: {ts}"

        grab_btn = Button(label=t(self.gid, "mindless_grab_btn"),
                          style=discord.ButtonStyle.secondary, custom_id="ml_grab")
        eat_btn  = Button(label=t(self.gid, "mindless_eat_btn"),
                          style=discord.ButtonStyle.danger,    custom_id="ml_eat")
        done_btn = Button(label=t(self.gid, "done_btn"),
                          style=discord.ButtonStyle.danger,    custom_id="ml_done")
        grab_btn.callback = self._grab
        eat_btn.callback  = self._eat
        done_btn.callback = self._done

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(grab_btn, eat_btn),
            ActionRow(done_btn),
        ))

    async def _grab(self, ix: discord.Interaction):
        await ix.response.edit_message(view=MindlessTargetView(self.gid, self.uid, "grab", self))

    async def _eat(self, ix: discord.Interaction):
        await ix.response.edit_message(view=MindlessTargetView(self.gid, self.uid, "eat", self))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


class MindlessTargetView(LayoutView):
    def __init__(self, gid, uid, action, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.action = action; self.parent = parent

        usr_sel = discord.ui.UserSelect(placeholder=t(gid, "select_target"))
        usr_sel.callback = self._pick
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="mtv_bk")
        bk.callback = self._back

        self.add_item(Container(
            ActionRow(bk), Separator(),
            TextDisplay(f"**{action.title()} — select target:**"),
            ActionRow(usr_sel),
        ))

    async def _pick(self, ix: discord.Interaction):
        target_id = int(ix.data["values"][0])
        if target_id == self.uid:
            await ix.response.send_message("You cannot target yourself.", ephemeral=True); return

        eater_name  = ix.user.display_name
        target_name = f"<@{target_id}>"

        if self.action == "grab":
            msg = t(self.gid, "mindless_grab_msg", name=eater_name, target=target_name)
            v   = LayoutView(timeout=None)
            v.add_item(Container(TextDisplay(msg)))
            try:
                await ix.channel.send(view=v)
            except Exception:
                pass
            await log_event(bot, self.gid, "mindless", f"{eater_name} grabbed {target_name}")
            self.parent._build(); await ix.response.edit_message(view=self.parent)

        else:  # eat
            for g in bot.guilds:
                if g.id == self.gid:
                    member = g.get_member(target_id)
                    if member:
                        dm_view = EatConsentView(self.gid, self.uid, target_id, ix.channel_id)
                        try:
                            dm = await member.create_dm()
                            await dm.send(
                                view=dm_view,
                                content=t(self.gid, "mindless_eat_ask_body",
                                          eater=eater_name))
                        except Exception:
                            pass
                    break
            pub_text = f"**{eater_name}** is trying to eat **{target_name}**..."
            v = LayoutView(timeout=None)
            v.add_item(Container(TextDisplay(pub_text)))
            try:
                await ix.channel.send(view=v)
            except Exception:
                pass
            await log_event(bot, self.gid, "mindless",
                            f"{eater_name} tried to eat {target_name}")
            self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class EatConsentView(LayoutView):
    def __init__(self, gid, eater_uid, target_uid, channel_id):
        super().__init__(timeout=86400)
        self.gid = gid; self.eater_uid = eater_uid
        self.target_uid = target_uid; self.channel_id = channel_id

        accept_btn  = Button(label=t(gid, "mindless_eat_accept_btn"),
                             style=discord.ButtonStyle.green,  custom_id="ec_acc")
        decline_btn = Button(label=t(gid, "mindless_eat_decline_btn"),
                             style=discord.ButtonStyle.danger, custom_id="ec_dec")
        accept_btn.callback  = self._accept
        decline_btn.callback = self._decline

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'mindless_title')}**\n\nA Mindless Titan is trying to eat you!"),
            Separator(),
            ActionRow(accept_btn, decline_btn),
        ))

    async def _accept(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            await ix.response.send_message("This is not for you.", ephemeral=True); return

        players      = load_players(self.gid)
        eater_name   = f"<@{self.eater_uid}>"
        target_name  = f"<@{self.target_uid}>"
        target_player = players.get(str(self.target_uid), {})

        titan_powers = target_player.get("titan_powers", [])
        msg_text     = ""

        if titan_powers and has_shifter_access(self.gid, self.target_uid):
            # Transfer titan power to the eater
            cfg  = load_config(self.gid)
            now  = time.time()
            for power in titan_powers:
                titan_name = power["titan"]
                new_power  = {
                    "titan":      titan_name,
                    "acquired_at": now,
                    "expires_at": now + cfg.get("titan_time_days", 4745) * 86400,
                    "abilities":  power.get("abilities", []),
                }
                eater_player = players.get(str(self.eater_uid), {})
                if eater_player:
                    eater_player.setdefault("titan_powers", []).append(new_power)
                    players[str(self.eater_uid)] = eater_player
                    # Remove from target
                    target_player["titan_powers"] = [
                        p for p in titan_powers if p["titan"] != titan_name
                    ]
                    # Remove shifter access from target
                    sa = cfg.get("shifter_access", [])
                    if str(self.target_uid) in sa:
                        sa.remove(str(self.target_uid))
                    if str(self.eater_uid) not in sa:
                        sa.append(str(self.eater_uid))
                    cfg["shifter_access"] = sa
                    from aot_shared import save_config
                    save_config(self.gid, cfg)
                msg_text = t(self.gid, "mindless_ate_shifter_msg",
                              eater=eater_name, target=target_name, titan=titan_name)
                await cv2_dm(ix.user, t(self.gid, "mindless_power_guide", titan=titan_name))
        else:
            msg_text = t(self.gid, "mindless_ate_normal_msg",
                         eater=eater_name, target=target_name)

        target_player["mindless_titan"] = False
        players[str(self.target_uid)] = target_player
        save_players(self.gid, players)

        await log_event(bot, self.gid, "mindless",
                        f"{eater_name} ate {target_name}")

        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    v = LayoutView(timeout=None)
                    v.add_item(Container(TextDisplay(msg_text)))
                    try:
                        await ch.send(view=v)
                    except Exception:
                        pass
                break

        self.clear_items()
        self.add_item(Container(TextDisplay("You have been eaten.")))
        await ix.response.edit_message(view=self)

    async def _decline(self, ix: discord.Interaction):
        if ix.user.id != self.target_uid:
            await ix.response.send_message("This is not for you.", ephemeral=True); return
        await ix.response.send_modal(EatRefuseModal(self.gid, self.eater_uid,
                                                     self.target_uid, self.channel_id, self))


class EatRefuseModal(Modal, title="Refuse"):
    f_reason = TextInput(label="Reason", style=discord.TextStyle.paragraph,
                         max_length=200, required=False)

    def __init__(self, gid, eater_uid, target_uid, channel_id, parent):
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
                    v = LayoutView(timeout=None)
                    v.add_item(Container(TextDisplay(msg)))
                    try:
                        await ch.send(view=v)
                    except Exception:
                        pass
                break
        self.parent.clear_items()
        self.parent.add_item(Container(TextDisplay("Refused.")))
        await ix.response.edit_message(view=self.parent)


# ── /mindless-inject (admin) ──────────────────────────────────────────────────

@bot.tree.command(name="mindless-inject",
                  description="Inject a player to make them a Mindless Titan",
                  guild=GUILD2_OBJ)
@app_commands.describe(target="Target player")
async def mindless_inject_cmd(ix: discord.Interaction, target: discord.Member):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not _is_admin_or_manage(m):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(ix.guild_id, "admin_only"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(
        view=InjectConfirmView(ix.guild_id, ix.user.id, target.id, target.display_name,
                               ix.channel_id),
        ephemeral=True)


class InjectConfirmView(LayoutView):
    def __init__(self, gid, injector_uid, target_uid, target_name, channel_id):
        super().__init__(timeout=120)
        self.gid = gid; self.injector_uid = injector_uid
        self.target_uid = target_uid; self.target_name = target_name
        self.channel_id = channel_id

        text = t(gid, "mindless_inject_confirm_text", target=target_name)
        confirm_btn = Button(label=t(gid, "confirm_btn"), style=discord.ButtonStyle.danger, custom_id="ic_yes")
        cancel_btn  = Button(label=t(gid, "cancel_btn"),  style=discord.ButtonStyle.secondary, custom_id="ic_no")
        confirm_btn.callback = self._confirm
        cancel_btn.callback  = self._cancel
        self.add_item(Container(TextDisplay(text), Separator(), ActionRow(confirm_btn, cancel_btn)))

    async def _confirm(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.target_uid), {})
        if not player:
            await ix.response.send_message("Player not registered.", ephemeral=True); return
        player["mindless_titan"]      = True
        player["mindless_acquired_at"] = time.time()
        players[str(self.target_uid)] = player
        save_players(self.gid, players)

        injector_name = ix.user.display_name
        msg = t(self.gid, "mindless_inject_msg",
                user=self.target_name, injector=injector_name)

        for g in bot.guilds:
            if g.id == self.gid:
                ch = g.get_channel(self.channel_id)
                if ch:
                    v = LayoutView(timeout=None)
                    v.add_item(Container(TextDisplay(msg)))
                    try:
                        await ch.send(view=v)
                    except Exception:
                        pass
                break

        await log_event(bot, self.gid, "mindless",
                        f"{injector_name} injected {self.target_name}")
        self.clear_items()
        self.add_item(Container(TextDisplay(f"✅ {self.target_name} is now a Mindless Titan.")))
        await ix.response.edit_message(view=self)

    async def _cancel(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay("Cancelled.")))
        await ix.response.edit_message(view=self)
