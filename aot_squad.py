"""Squad system — /squad command."""
import time, uuid
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, load_players, save_players,
    load_squads, save_squads, get_player_squad, cv2_dm, log_event,
)

_MAX_MEMBERS = 6


def _user_squad(gid: int, uid: int):
    return get_player_squad(gid, uid)


class SquadView(LayoutView):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid
        self._build()

    def _build(self):
        self.clear_items()
        sid, sq = _user_squad(self.gid, self.uid)
        if sq:
            self._build_in_squad(sid, sq)
        else:
            self._build_no_squad()

    def _build_no_squad(self):
        cfg   = load_config(self.gid)
        max_m = cfg.get("squad_max_members", _MAX_MEMBERS)
        ranks = cfg.get("squad_creator_ranks", ["Commander", "General"])
        player = load_players(self.gid).get(str(self.uid), {})
        rank   = player.get("rank", "")

        db = load_squads(self.gid)
        my_invites = []
        for sid, sq in db.get("squads", {}).items():
            if str(self.uid) in sq.get("invites", {}):
                my_invites.append((sid, sq))

        lines = [f"**{t(self.gid,'squad_title')}**", "", t(self.gid, "no_squad")]
        if my_invites:
            lines += ["", f"**{t(self.gid,'squad_pending_invites_btn')}:**"]
            for sid, sq in my_invites[:3]:
                lines.append(f"• {sq['name']} (by <@{sq['leader_id']}>)")

        can_create = (rank in ranks)
        create_btn = Button(label=t(self.gid, "create_squad_btn"),
                            style=discord.ButtonStyle.green,
                            custom_id="sq_create", disabled=not can_create)
        create_btn.callback = self._create

        children = [TextDisplay("\n".join(lines)), Separator(), ActionRow(create_btn)]

        if my_invites:
            inv_opts = [discord.SelectOption(label=sq["name"][:100], value=sid)
                        for sid, sq in my_invites[:25]]
            inv_sel = Select(placeholder="Accept/decline an invite", options=inv_opts)
            inv_sel.callback = self._view_invite
            children.append(ActionRow(inv_sel))

        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="sq_done")
        done_btn.callback = self._done
        children.append(ActionRow(done_btn))
        self.add_item(Container(*children))

    def _build_in_squad(self, sid: str, sq: dict):
        members   = sq.get("members", {})
        is_leader = (sq.get("leader_id") == str(self.uid))

        member_lines = []
        for uid, mdata in members.items():
            title = mdata.get("title", "Member")
            member_lines.append(f"<@{uid}> — {title}")

        lines = [
            f"**⚔️ {sq['name']}**",
            f"*{t(self.gid,'squad_faction_label')}: {sq.get('faction','?')}*",
            "",
            f"**{t(self.gid,'squad_members_label')} ({len(members)}/{sq.get('max',_MAX_MEMBERS)}):**",
            *member_lines[:10],
        ]

        leave_btn = Button(label=t(self.gid, "squad_leave_btn"),
                           style=discord.ButtonStyle.danger, custom_id="sq_leave")
        leave_btn.callback = self._leave

        children = [TextDisplay("\n".join(lines)), Separator(), ActionRow(leave_btn)]

        if is_leader:
            invite_btn  = Button(label=t(self.gid, "squad_invite_btn"),
                                 style=discord.ButtonStyle.primary, custom_id="sq_invite")
            kick_btn    = Button(label=t(self.gid, "squad_kick_btn"),
                                 style=discord.ButtonStyle.secondary, custom_id="sq_kick")
            promote_btn = Button(label=t(self.gid, "squad_promote_btn"),
                                 style=discord.ButtonStyle.secondary, custom_id="sq_promote")
            punish_btn  = Button(label=t(self.gid, "squad_punish_btn"),
                                 style=discord.ButtonStyle.secondary, custom_id="sq_punish")
            disband_btn = Button(label=t(self.gid, "squad_disband_btn"),
                                 style=discord.ButtonStyle.danger, custom_id="sq_disband")
            invite_btn.callback  = self._invite
            kick_btn.callback    = self._kick
            promote_btn.callback = self._promote
            punish_btn.callback  = self._punish
            disband_btn.callback = self._disband
            children += [
                ActionRow(invite_btn, kick_btn),
                ActionRow(promote_btn, punish_btn),
                ActionRow(disband_btn),
            ]

        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="sq_done2")
        done_btn.callback = self._done
        children.append(ActionRow(done_btn))
        self.add_item(Container(*children))

    async def _create(self, ix: discord.Interaction):
        if _user_squad(self.gid, self.uid)[0]:
            await ix.response.send_message(t(self.gid, "squad_already_member"), ephemeral=True); return
        await ix.response.send_modal(CreateSquadModal(self.gid, self.uid, self))

    async def _view_invite(self, ix: discord.Interaction):
        sid = ix.data["values"][0]
        await ix.response.edit_message(view=SquadInviteResponseView(self.gid, self.uid, sid, self))

    async def _leave(self, ix: discord.Interaction):
        sid, sq = _user_squad(self.gid, self.uid)
        if not sq:
            await ix.response.defer(); return
        db = load_squads(self.gid)
        sq = db["squads"].get(sid, {})
        sq.get("members", {}).pop(str(self.uid), None)
        if not sq.get("members"):
            db["squads"].pop(sid, None)
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> left squad '{sq.get('name','?')}'")
        self._build(); await ix.response.edit_message(view=self)

    async def _invite(self, ix: discord.Interaction):
        await ix.response.edit_message(view=SquadInviteView(self.gid, self.uid, self))

    async def _kick(self, ix: discord.Interaction):
        await ix.response.edit_message(view=SquadMemberActionView(self.gid, self.uid, "kick", self))

    async def _promote(self, ix: discord.Interaction):
        await ix.response.edit_message(view=SquadMemberActionView(self.gid, self.uid, "promote", self))

    async def _punish(self, ix: discord.Interaction):
        await ix.response.edit_message(view=SquadMemberActionView(self.gid, self.uid, "punish", self))

    async def _disband(self, ix: discord.Interaction):
        sid, sq = _user_squad(self.gid, self.uid)
        if not sq or sq.get("leader_id") != str(self.uid):
            await ix.response.defer(); return
        db = load_squads(self.gid)
        squad_name = db["squads"].get(sid, {}).get("name", "?")
        db["squads"].pop(sid, None)
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> disbanded squad '{squad_name}'")
        try:
            await ix.channel.send(t(self.gid, "squad_disbanded_msg", squad=squad_name))
        except Exception:
            pass
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── Create Squad Modal ────────────────────────────────────────────────────────

class CreateSquadModal(Modal, title="Create Squad"):
    f_name = TextInput(label="Squad Name", max_length=60)

    def __init__(self, gid, uid, parent):
        super().__init__(); self.gid = gid; self.uid = uid; self.parent = parent
        self.f_name.label = t(gid, "squad_name_field")

    async def on_submit(self, ix: discord.Interaction):
        cfg    = load_config(self.gid)
        player = load_players(self.gid).get(str(self.uid), {})
        rank   = player.get("rank", "")
        ranks  = cfg.get("squad_creator_ranks", ["Commander", "General"])
        if rank not in ranks:
            await ix.response.send_message(
                t(self.gid, "squad_no_perm", ranks=", ".join(ranks)), ephemeral=True); return
        max_m   = cfg.get("squad_max_members", _MAX_MEMBERS)
        faction = player.get("faction", "?")
        sid     = str(uuid.uuid4())[:8]
        db      = load_squads(self.gid)
        db["squads"][sid] = {
            "id":       sid,
            "name":     self.f_name.value.strip(),
            "faction":  faction,
            "leader_id": str(self.uid),
            "max":      max_m,
            "members":  {str(self.uid): {"title": "Squad Leader", "joined_at": time.time()}},
            "invites":  {},
            "created_at": time.time(),
        }
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> created squad '{self.f_name.value.strip()}'")
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Invite ────────────────────────────────────────────────────────────────────

class SquadInviteView(LayoutView):
    def __init__(self, gid, leader_uid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.leader_uid = leader_uid; self.parent = parent
        usr_sel = discord.ui.UserSelect(placeholder="Select member to invite")
        usr_sel.callback = self._pick
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="siv_bk")
        bk.callback = self._back
        self.add_item(Container(
            ActionRow(bk), Separator(),
            TextDisplay(f"**{t(gid,'squad_invite_btn')}**"),
            ActionRow(usr_sel),
        ))

    async def _pick(self, ix: discord.Interaction):
        target = ix.data["values"][0]
        sid, sq = _user_squad(self.gid, self.leader_uid)
        if not sq:
            await ix.response.defer(); return
        cfg    = load_config(self.gid)
        max_m  = cfg.get("squad_max_members", _MAX_MEMBERS)
        if len(sq.get("members", {})) >= max_m:
            await ix.response.send_message(t(self.gid, "squad_full_msg", max=max_m), ephemeral=True); return
        if str(target) in sq.get("invites", {}):
            await ix.response.send_message(t(self.gid, "squad_already_invited"), ephemeral=True); return

        db = load_squads(self.gid)
        db["squads"][sid].setdefault("invites", {})[str(target)] = {
            "invited_at": time.time(), "invited_by": str(self.leader_uid)
        }
        save_squads(self.gid, db)

        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(target))
                if member:
                    await cv2_dm(member, t(self.gid, "squad_invite_dm", squad=sq["name"]))
                break

        await ix.response.send_message(
            t(self.gid, "squad_invite_sent", user=f"<@{target}>"), ephemeral=True)
        self.parent._build(); await ix.edit_original_response(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Invite Response ───────────────────────────────────────────────────────────

class SquadInviteResponseView(LayoutView):
    def __init__(self, gid, uid, sid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.sid = sid; self.parent = parent
        db = load_squads(gid)
        sq = db.get("squads", {}).get(sid, {})
        text = f"**Invite to: {sq.get('name','?')}**\n*Faction: {sq.get('faction','?')}*\n*Members: {len(sq.get('members',{}))}*"
        accept_btn  = Button(label=t(gid, "squad_accept_btn"),  style=discord.ButtonStyle.green, custom_id="sir_acc")
        decline_btn = Button(label=t(gid, "squad_decline_btn"), style=discord.ButtonStyle.danger, custom_id="sir_dec")
        bk_btn      = Button(label=t(gid, "back_btn"),           style=discord.ButtonStyle.secondary, custom_id="sir_bk")
        accept_btn.callback  = self._accept
        decline_btn.callback = self._decline
        bk_btn.callback      = self._back
        self.add_item(Container(
            ActionRow(bk_btn), Separator(),
            TextDisplay(text), Separator(),
            ActionRow(accept_btn, decline_btn),
        ))

    async def _accept(self, ix: discord.Interaction):
        existing_sid, _ = _user_squad(self.gid, self.uid)
        if existing_sid:
            await ix.response.send_message(t(self.gid, "squad_already_member"), ephemeral=True); return
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid)
        if not sq:
            await ix.response.send_message("Squad no longer exists.", ephemeral=True); return
        cfg   = load_config(self.gid)
        max_m = cfg.get("squad_max_members", _MAX_MEMBERS)
        if len(sq.get("members", {})) >= max_m:
            await ix.response.send_message(t(self.gid, "squad_full_msg", max=max_m), ephemeral=True); return
        player = load_players(self.gid).get(str(self.uid), {})
        if player.get("faction") != sq.get("faction"):
            await ix.response.send_message(
                t(self.gid, "squad_wrong_faction", faction=sq["faction"]), ephemeral=True); return
        sq.setdefault("members", {})[str(self.uid)] = {"title": "Member", "joined_at": time.time()}
        sq.get("invites", {}).pop(str(self.uid), None)
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> joined squad '{sq['name']}'")
        try:
            for g in bot.guilds:
                if g.id == self.gid:
                    await g.get_channel(ix.channel_id).send(
                        t(self.gid, "squad_joined_msg",
                          user=ix.user.display_name, squad=sq["name"])) if g.get_channel(ix.channel_id) else None
                    break
        except Exception:
            pass
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _decline(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        sq.get("invites", {}).pop(str(self.uid), None)
        save_squads(self.gid, db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Member Action View (kick/promote/punish) ──────────────────────────────────

class SquadMemberActionView(LayoutView):
    def __init__(self, gid, leader_uid, action, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.leader_uid = leader_uid
        self.action = action; self.parent = parent
        sid, sq = _user_squad(gid, leader_uid)
        self.sid = sid
        members = {uid: m for uid, m in sq.get("members", {}).items()
                   if uid != str(leader_uid)} if sq else {}
        opts = ([discord.SelectOption(
                     label=f"<@{uid}> — {m.get('title','Member')}"[:100], value=uid)
                 for uid, m in list(members.items())[:25]]
                or [discord.SelectOption(label="No other members", value="__none__")])
        sel = Select(placeholder=f"Select member to {action}", options=opts)
        sel.callback = self._pick
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="smav_bk")
        bk.callback = self._back
        self.add_item(Container(
            ActionRow(bk), Separator(),
            TextDisplay(f"**{action.title()} member**"),
            ActionRow(sel),
        ))

    async def _pick(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        if uid == "__none__":
            await ix.response.defer(); return
        if self.action == "kick":
            await self._do_kick(ix, uid)
        elif self.action == "promote":
            await ix.response.send_modal(PromoteMemberModal(self.gid, self.sid, uid, self.parent))
        elif self.action == "punish":
            await ix.response.send_modal(PunishMemberModal(self.gid, self.sid, uid, self.parent))

    async def _do_kick(self, ix, target_uid):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        sq.get("members", {}).pop(target_uid, None)
        save_squads(self.gid, db)
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(target_uid))
                if member:
                    await cv2_dm(member, t(self.gid, "squad_kicked_msg",
                                            user=member.display_name, squad=sq.get("name","?")))
                try:
                    await ix.channel.send(t(self.gid, "squad_kicked_msg",
                                            user=f"<@{target_uid}>", squad=sq.get("name","?")))
                except Exception:
                    pass
                break
        await log_event(bot, self.gid, "squad",
                        f"<@{target_uid}> was kicked from squad '{sq.get('name','?')}' by <@{self.leader_uid}>")
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class PromoteMemberModal(Modal, title="Promote Member"):
    f_title = TextInput(label="New Title", max_length=60)

    def __init__(self, gid, sid, target_uid, parent):
        super().__init__(); self.gid = gid; self.sid = sid
        self.target_uid = target_uid; self.parent = parent
        self.f_title.label = t(gid, "squad_promote_title_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        m  = sq.get("members", {}).get(self.target_uid, {})
        m["title"] = self.f_title.value.strip()
        save_squads(self.gid, db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class PunishMemberModal(Modal, title="Punish Member"):
    f_reason = TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=300)

    def __init__(self, gid, sid, target_uid, parent):
        super().__init__(); self.gid = gid; self.sid = sid
        self.target_uid = target_uid; self.parent = parent
        self.f_reason.label = t(gid, "squad_punish_reason_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        reason = self.f_reason.value.strip()
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(self.target_uid))
                if member:
                    await cv2_dm(member, t(self.gid, "squad_punish_msg",
                                            user=member.display_name,
                                            squad=sq.get("name","?"), reason=reason))
                try:
                    await ix.channel.send(t(self.gid, "squad_punish_msg",
                                            user=f"<@{self.target_uid}>",
                                            squad=sq.get("name","?"), reason=reason))
                except Exception:
                    pass
                break
        await log_event(bot, self.gid, "squad",
                        f"<@{self.target_uid}> punished in '{sq.get('name','?')}': {reason[:80]}")
        self.parent._build(); await ix.response.edit_message(view=self.parent)


@bot.tree.command(name="squad",
                  description="Manage your squad",
                  guild=GUILD2_OBJ)
async def squad_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=SquadView(ix.guild_id, ix.user.id), ephemeral=True)
