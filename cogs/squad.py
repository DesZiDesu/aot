"""Squad system — /squad command (Embed UI)."""
import time, uuid
import discord
from discord import app_commands
from discord.ext import commands

from core.instance import bot
from core.shared import (
    t, load_config, load_players, save_players,
    load_squads, save_squads, get_player_squad, send_dm, log_event,
    EMBED_COLOR,
)

_MAX_MEMBERS = 6


def _user_squad(gid: int, uid: int):
    return get_player_squad(gid, uid)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _squad_embed(gid: int, sq: dict) -> discord.Embed:
    """Build a rich Embed showing squad details."""
    members = sq.get("members", {})
    max_m   = sq.get("max", _MAX_MEMBERS)

    embed = discord.Embed(
        title=f"⚔️ {sq['name']}",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name=t(gid, "squad_faction_label"),
        value=sq.get("faction", "?"),
        inline=True,
    )
    embed.add_field(
        name=t(gid, "squad_members_label"),
        value=f"{len(members)}/{max_m}",
        inline=True,
    )

    member_lines = []
    for uid, mdata in members.items():
        title = mdata.get("title", "Member")
        member_lines.append(f"<@{uid}> — {title}")
    if member_lines:
        embed.add_field(
            name="​",
            value="\n".join(member_lines[:20]),
            inline=False,
        )

    return embed


def _no_squad_embed(gid: int, uid: int) -> discord.Embed:
    db = load_squads(gid)
    my_invites = [
        (sid, sq)
        for sid, sq in db.get("squads", {}).items()
        if str(uid) in sq.get("invites", {})
    ]

    embed = discord.Embed(
        title=t(gid, "squad_title"),
        description=t(gid, "no_squad"),
        color=EMBED_COLOR,
    )
    if my_invites:
        invite_lines = [
            f"• **{sq['name']}** — <@{sq['leader_id']}>"
            for sid, sq in my_invites[:5]
        ]
        embed.add_field(
            name=t(gid, "squad_pending_invites_btn"),
            value="\n".join(invite_lines),
            inline=False,
        )
    return embed


# ── SquadView ─────────────────────────────────────────────────────────────────

class SquadView(discord.ui.View):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
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
        ranks = cfg.get("squad_creator_ranks", ["Commander", "General"])
        player = load_players(self.gid).get(str(self.uid), {})
        rank   = player.get("rank", "")

        can_create = rank in ranks
        create_btn = discord.ui.Button(
            label=t(self.gid, "create_squad_btn"),
            style=discord.ButtonStyle.green,
            custom_id="sq_create",
            disabled=not can_create,
            row=0,
        )
        create_btn.callback = self._create
        self.add_item(create_btn)

        db = load_squads(self.gid)
        my_invites = [
            (sid, sq)
            for sid, sq in db.get("squads", {}).items()
            if str(self.uid) in sq.get("invites", {})
        ]
        if my_invites:
            inv_opts = [
                discord.SelectOption(label=sq["name"][:100], value=sid)
                for sid, sq in my_invites[:25]
            ]
            inv_sel = discord.ui.Select(
                placeholder=t(self.gid, "squad_pending_invites_btn"),
                options=inv_opts,
                custom_id="sq_inv_sel",
                row=1,
            )
            inv_sel.callback = self._view_invite
            self.add_item(inv_sel)

        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="sq_done",
            row=2,
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

    def _build_in_squad(self, sid: str, sq: dict):
        is_leader = sq.get("leader_id") == str(self.uid)

        leave_btn = discord.ui.Button(
            label=t(self.gid, "squad_leave_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="sq_leave",
            row=0,
        )
        leave_btn.callback = self._leave
        self.add_item(leave_btn)

        if is_leader:
            invite_btn = discord.ui.Button(
                label=t(self.gid, "squad_invite_btn"),
                style=discord.ButtonStyle.primary,
                custom_id="sq_invite",
                row=1,
            )
            kick_btn = discord.ui.Button(
                label=t(self.gid, "squad_kick_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="sq_kick",
                row=1,
            )
            promote_btn = discord.ui.Button(
                label=t(self.gid, "squad_promote_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="sq_promote",
                row=2,
            )
            punish_btn = discord.ui.Button(
                label=t(self.gid, "squad_punish_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="sq_punish",
                row=2,
            )
            disband_btn = discord.ui.Button(
                label=t(self.gid, "squad_disband_btn"),
                style=discord.ButtonStyle.danger,
                custom_id="sq_disband",
                row=3,
            )
            invite_btn.callback  = self._invite
            kick_btn.callback    = self._kick
            promote_btn.callback = self._promote
            punish_btn.callback  = self._punish
            disband_btn.callback = self._disband
            for btn in (invite_btn, kick_btn, promote_btn, punish_btn, disband_btn):
                self.add_item(btn)

        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="sq_done2",
            row=4,
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

    # ── Callbacks ──────────────────────────────────────────────────────────────

    async def _create(self, ix: discord.Interaction):
        if _user_squad(self.gid, self.uid)[0]:
            await ix.response.send_message(
                t(self.gid, "squad_already_member"), ephemeral=True
            )
            return
        await ix.response.send_modal(CreateSquadModal(self.gid, self.uid, self))

    async def _view_invite(self, ix: discord.Interaction):
        sid = ix.data["values"][0]
        view = SquadInviteResponseView(self.gid, self.uid, sid, self)
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(sid, {})
        embed = discord.Embed(
            title=f"📩 {sq.get('name', '?')}",
            description=(
                f"**{t(self.gid, 'squad_faction_label')}:** {sq.get('faction', '?')}\n"
                f"**{t(self.gid, 'squad_members_label')}:** {len(sq.get('members', {}))}"
            ),
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _leave(self, ix: discord.Interaction):
        sid, sq = _user_squad(self.gid, self.uid)
        if not sq:
            await ix.response.defer()
            return
        db = load_squads(self.gid)
        squad_data = db["squads"].get(sid, {})
        squad_name = squad_data.get("name", "?")
        squad_data.get("members", {}).pop(str(self.uid), None)
        if not squad_data.get("members"):
            db["squads"].pop(sid, None)
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> left squad '{squad_name}'")
        self._build()
        embed = _no_squad_embed(self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self)

    async def _invite(self, ix: discord.Interaction):
        view = SquadInviteView(self.gid, self.uid, self)
        embed = discord.Embed(
            title=t(self.gid, "squad_invite_btn"),
            description="Select a member to invite to your squad.",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _kick(self, ix: discord.Interaction):
        view = SquadMemberActionView(self.gid, self.uid, "kick", self)
        embed = discord.Embed(
            title=t(self.gid, "squad_kick_btn"),
            description="Select a member to kick from your squad.",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _promote(self, ix: discord.Interaction):
        view = SquadMemberActionView(self.gid, self.uid, "promote", self)
        embed = discord.Embed(
            title=t(self.gid, "squad_promote_btn"),
            description="Select a member to promote.",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _punish(self, ix: discord.Interaction):
        view = SquadMemberActionView(self.gid, self.uid, "punish", self)
        embed = discord.Embed(
            title=t(self.gid, "squad_punish_btn"),
            description="Select a member to punish.",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _disband(self, ix: discord.Interaction):
        sid, sq = _user_squad(self.gid, self.uid)
        if not sq or sq.get("leader_id") != str(self.uid):
            await ix.response.defer()
            return
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
        self._build()
        embed = _no_squad_embed(self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self)

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=self)


# ── Create Squad Modal ────────────────────────────────────────────────────────

class CreateSquadModal(discord.ui.Modal, title="Create Squad"):
    f_name = discord.ui.TextInput(label="Squad Name", max_length=60)

    def __init__(self, gid: int, uid: int, parent: SquadView):
        super().__init__()
        self.gid = gid
        self.uid = uid
        self.parent = parent
        self.f_name.label = t(gid, "squad_name_field")

    async def on_submit(self, ix: discord.Interaction):
        cfg    = load_config(self.gid)
        player = load_players(self.gid).get(str(self.uid), {})
        rank   = player.get("rank", "")
        ranks  = cfg.get("squad_creator_ranks", ["Commander", "General"])

        if rank not in ranks:
            await ix.response.send_message(
                t(self.gid, "squad_no_perm", ranks=", ".join(ranks)),
                ephemeral=True,
            )
            return

        max_m   = cfg.get("squad_max_members", _MAX_MEMBERS)
        faction = player.get("faction", "?")
        sid     = str(uuid.uuid4())[:8]
        db      = load_squads(self.gid)
        db["squads"][sid] = {
            "id":         sid,
            "name":       self.f_name.value.strip(),
            "faction":    faction,
            "leader_id":  str(self.uid),
            "max":        max_m,
            "members":    {str(self.uid): {"title": "Squad Leader", "joined_at": time.time()}},
            "invites":    {},
            "created_at": time.time(),
        }
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> created squad '{self.f_name.value.strip()}'")
        self.parent._build()
        _, sq = _user_squad(self.gid, self.uid)
        embed = _squad_embed(self.gid, sq) if sq else _no_squad_embed(self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Invite View ───────────────────────────────────────────────────────────────

class SquadInviteView(discord.ui.View):
    def __init__(self, gid: int, leader_uid: int, parent: SquadView):
        super().__init__(timeout=300)
        self.gid = gid
        self.leader_uid = leader_uid
        self.parent = parent

        usr_sel = discord.ui.UserSelect(
            placeholder="Select member to invite",
            custom_id="siv_usr",
            row=0,
        )
        usr_sel.callback = self._pick
        self.add_item(usr_sel)

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="siv_bk",
            row=1,
        )
        bk.callback = self._back
        self.add_item(bk)

    async def _pick(self, ix: discord.Interaction):
        target_id = ix.data["values"][0]
        sid, sq = _user_squad(self.gid, self.leader_uid)
        if not sq:
            await ix.response.defer()
            return

        cfg   = load_config(self.gid)
        max_m = cfg.get("squad_max_members", _MAX_MEMBERS)
        if len(sq.get("members", {})) >= max_m:
            await ix.response.send_message(
                t(self.gid, "squad_full_msg", max=max_m), ephemeral=True
            )
            return
        if str(target_id) in sq.get("invites", {}):
            await ix.response.send_message(
                t(self.gid, "squad_already_invited"), ephemeral=True
            )
            return

        db = load_squads(self.gid)
        db["squads"][sid].setdefault("invites", {})[str(target_id)] = {
            "invited_at": time.time(),
            "invited_by": str(self.leader_uid),
        }
        save_squads(self.gid, db)

        # DM the invited user with an embed
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(target_id))
                if member:
                    dm_embed = discord.Embed(
                        title=t(self.gid, "squad_invite_btn"),
                        description=t(self.gid, "squad_invite_dm", squad=sq["name"]),
                        color=EMBED_COLOR,
                    )
                    dm_embed.add_field(
                        name=t(self.gid, "squad_faction_label"),
                        value=sq.get("faction", "?"),
                        inline=True,
                    )
                    await send_dm(member, embed=dm_embed)
                break

        await ix.response.send_message(
            t(self.gid, "squad_invite_sent", user=f"<@{target_id}>"),
            ephemeral=True,
        )
        self.parent._build()
        _, sq_updated = _user_squad(self.gid, self.leader_uid)
        embed = _squad_embed(self.gid, sq_updated) if sq_updated else _no_squad_embed(self.gid, self.leader_uid)
        await ix.edit_original_response(embed=embed, view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        _, sq = _user_squad(self.gid, self.leader_uid)
        embed = _squad_embed(self.gid, sq) if sq else _no_squad_embed(self.gid, self.leader_uid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Invite Response View ──────────────────────────────────────────────────────

class SquadInviteResponseView(discord.ui.View):
    def __init__(self, gid: int, uid: int, sid: str, parent: SquadView):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.sid = sid
        self.parent = parent

        accept_btn = discord.ui.Button(
            label=t(gid, "squad_accept_btn"),
            style=discord.ButtonStyle.green,
            custom_id="sir_acc",
            row=0,
        )
        decline_btn = discord.ui.Button(
            label=t(gid, "squad_decline_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="sir_dec",
            row=0,
        )
        bk_btn = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="sir_bk",
            row=1,
        )
        accept_btn.callback  = self._accept
        decline_btn.callback = self._decline
        bk_btn.callback      = self._back
        self.add_item(accept_btn)
        self.add_item(decline_btn)
        self.add_item(bk_btn)

    async def _accept(self, ix: discord.Interaction):
        existing_sid, _ = _user_squad(self.gid, self.uid)
        if existing_sid:
            await ix.response.send_message(
                t(self.gid, "squad_already_member"), ephemeral=True
            )
            return

        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid)
        if not sq:
            await ix.response.send_message("Squad no longer exists.", ephemeral=True)
            return

        cfg   = load_config(self.gid)
        max_m = cfg.get("squad_max_members", _MAX_MEMBERS)
        if len(sq.get("members", {})) >= max_m:
            await ix.response.send_message(
                t(self.gid, "squad_full_msg", max=max_m), ephemeral=True
            )
            return

        player = load_players(self.gid).get(str(self.uid), {})
        if player.get("faction") != sq.get("faction"):
            await ix.response.send_message(
                t(self.gid, "squad_wrong_faction", faction=sq["faction"]),
                ephemeral=True,
            )
            return

        sq.setdefault("members", {})[str(self.uid)] = {
            "title":     "Member",
            "joined_at": time.time(),
        }
        sq.get("invites", {}).pop(str(self.uid), None)
        save_squads(self.gid, db)
        await log_event(bot, self.gid, "squad",
                        f"<@{self.uid}> joined squad '{sq['name']}'")

        try:
            ch = ix.channel
            if ch:
                await ch.send(
                    t(self.gid, "squad_joined_msg",
                      user=ix.user.display_name, squad=sq["name"])
                )
        except Exception:
            pass

        self.parent._build()
        embed = _squad_embed(self.gid, sq)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _decline(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        sq.get("invites", {}).pop(str(self.uid), None)
        save_squads(self.gid, db)
        self.parent._build()
        embed = _no_squad_embed(self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        embed = _no_squad_embed(self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Member Action View (kick / promote / punish) ──────────────────────────────

class SquadMemberActionView(discord.ui.View):
    def __init__(self, gid: int, leader_uid: int, action: str, parent: SquadView):
        super().__init__(timeout=300)
        self.gid        = gid
        self.leader_uid = leader_uid
        self.action     = action
        self.parent     = parent

        sid, sq = _user_squad(gid, leader_uid)
        self.sid = sid
        members = (
            {uid: m for uid, m in sq.get("members", {}).items()
             if uid != str(leader_uid)}
            if sq else {}
        )
        opts = (
            [
                discord.SelectOption(
                    label=f"@{uid} — {m.get('title', 'Member')}"[:100],
                    value=uid,
                )
                for uid, m in list(members.items())[:25]
            ]
            or [discord.SelectOption(label="No other members", value="__none__")]
        )
        sel = discord.ui.Select(
            placeholder=f"Select member to {action}",
            options=opts,
            custom_id="smav_sel",
            row=0,
        )
        sel.callback = self._pick
        self.add_item(sel)

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="smav_bk",
            row=1,
        )
        bk.callback = self._back
        self.add_item(bk)

    async def _pick(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        if uid == "__none__":
            await ix.response.defer()
            return
        if self.action == "kick":
            await self._do_kick(ix, uid)
        elif self.action == "promote":
            await ix.response.send_modal(
                PromoteMemberModal(self.gid, self.sid, uid, self.parent)
            )
        elif self.action == "punish":
            await ix.response.send_modal(
                PunishMemberModal(self.gid, self.sid, uid, self.parent)
            )

    async def _do_kick(self, ix: discord.Interaction, target_uid: str):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        sq.get("members", {}).pop(target_uid, None)
        save_squads(self.gid, db)

        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(target_uid))
                if member:
                    kick_embed = discord.Embed(
                        title=t(self.gid, "squad_kick_btn"),
                        description=t(
                            self.gid, "squad_kicked_msg",
                            user=member.display_name, squad=sq.get("name", "?")
                        ),
                        color=EMBED_COLOR,
                    )
                    await send_dm(member, embed=kick_embed)
                try:
                    await ix.channel.send(
                        t(self.gid, "squad_kicked_msg",
                          user=f"<@{target_uid}>", squad=sq.get("name", "?"))
                    )
                except Exception:
                    pass
                break

        await log_event(
            bot, self.gid, "squad",
            f"<@{target_uid}> was kicked from squad '{sq.get('name','?')}' by <@{self.leader_uid}>"
        )
        self.parent._build()
        _, sq_updated = _user_squad(self.gid, self.leader_uid)
        embed = _squad_embed(self.gid, sq_updated) if sq_updated else _no_squad_embed(self.gid, self.leader_uid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        _, sq = _user_squad(self.gid, self.leader_uid)
        embed = _squad_embed(self.gid, sq) if sq else _no_squad_embed(self.gid, self.leader_uid)
        await ix.response.edit_message(embed=embed, view=self.parent)


class PromoteMemberModal(discord.ui.Modal, title="Promote Member"):
    f_title = discord.ui.TextInput(label="New Title", max_length=60)

    def __init__(self, gid: int, sid: str, target_uid: str, parent: SquadView):
        super().__init__()
        self.gid        = gid
        self.sid        = sid
        self.target_uid = target_uid
        self.parent     = parent
        self.f_title.label = t(gid, "squad_promote_title_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        m  = sq.get("members", {}).get(self.target_uid, {})
        m["title"] = self.f_title.value.strip()
        save_squads(self.gid, db)
        self.parent._build()
        embed = _squad_embed(self.gid, sq)
        await ix.response.edit_message(embed=embed, view=self.parent)


class PunishMemberModal(discord.ui.Modal, title="Punish Member"):
    f_reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        max_length=300,
    )

    def __init__(self, gid: int, sid: str, target_uid: str, parent: SquadView):
        super().__init__()
        self.gid        = gid
        self.sid        = sid
        self.target_uid = target_uid
        self.parent     = parent
        self.f_reason.label = t(gid, "squad_punish_reason_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_squads(self.gid)
        sq = db.get("squads", {}).get(self.sid, {})
        reason = self.f_reason.value.strip()

        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(self.target_uid))
                if member:
                    punish_embed = discord.Embed(
                        title=t(self.gid, "squad_punish_btn"),
                        description=t(
                            self.gid, "squad_punish_msg",
                            user=member.display_name,
                            squad=sq.get("name", "?"),
                            reason=reason,
                        ),
                        color=EMBED_COLOR,
                    )
                    await send_dm(member, embed=punish_embed)
                try:
                    await ix.channel.send(
                        t(self.gid, "squad_punish_msg",
                          user=f"<@{self.target_uid}>",
                          squad=sq.get("name", "?"), reason=reason)
                    )
                except Exception:
                    pass
                break

        await log_event(
            bot, self.gid, "squad",
            f"<@{self.target_uid}> punished in '{sq.get('name','?')}': {reason[:80]}"
        )
        self.parent._build()
        embed = _squad_embed(self.gid, sq)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Cog & Command ─────────────────────────────────────────────────────────────

class SquadCog(commands.Cog):
    def __init__(self, bot_instance: commands.Bot):
        self.bot = bot_instance

    @app_commands.command(
        name="squad",
        description="Manage your squad",
        description_localizations={"th": "จัดการหน่วยรบของคุณ"},
    )
    async def squad_cmd(self, ix: discord.Interaction):
        gid = ix.guild_id
        uid = ix.user.id
        view = SquadView(gid, uid)
        sid, sq = _user_squad(gid, uid)
        embed = _squad_embed(gid, sq) if sq else _no_squad_embed(gid, uid)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot_instance: commands.Bot):
    await bot_instance.add_cog(SquadCog(bot_instance))
