"""Orion — mission boards: post notifications, multi-channel, dropdown join, bilingual."""
import time
import uuid
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR,
    load_config, save_config,
    load_missions, save_missions,
    money_str, add_money, load_players, save_players,
    t_orion,
)

_DIFF_COLORS = {
    "E": 0x9B9B9B, "D": 0x4CAF50, "C": 0x2196F3,
    "B": 0x9C27B0, "A": 0xFF9800, "S": 0xFF4444, "EX": 0xFFD700,
}
_DIFF_EMOJIS = {
    "E": "⬜", "D": "🟩", "C": "🟦", "B": "🟪", "A": "🟧", "S": "🟥", "EX": "🌟",
}
_DIFF_LABELS = ["E", "D", "C", "B", "A", "S", "EX"]
_MISSIONS_PER_PAGE = 10


# ── Embed builders ────────────────────────────────────────────────────────────

def _mission_detail_embed(gid: int, mid: str, m: dict) -> discord.Embed:
    """Full detail embed used in the board detail view."""
    color    = _DIFF_COLORS.get(m.get("difficulty", "E"), EMBED_COLOR)
    diff_emo = _DIFF_EMOJIS.get(m.get("difficulty", "E"), "")
    cap      = m.get("max_players", 0)
    cap_str  = t_orion(gid, "mission_unlimited") if cap == 0 else str(cap)
    players  = m.get("players", [])
    embed    = discord.Embed(
        title=f"{diff_emo} {m.get('title', 'Untitled')}",
        color=color,
    )
    embed.add_field(
        name=t_orion(gid, "mission_difficulty"),
        value=m.get("difficulty", "?"),
        inline=True,
    )
    embed.add_field(
        name=t_orion(gid, "mission_players"),
        value=f"{len(players)}/{cap_str}",
        inline=True,
    )
    reward = m.get("reward_money", 0)
    if reward:
        embed.add_field(
            name=t_orion(gid, "mission_reward"),
            value=money_str(reward, gid),
            inline=True,
        )
    reward_items = m.get("reward_items", {})
    if reward_items:
        embed.add_field(
            name="Reward Items / ไอเทมรางวัล",
            value=", ".join(f"{iid} ×{qty}" for iid, qty in reward_items.items())[:200],
            inline=True,
        )
    desc = m.get("description", "").strip()
    if desc:
        embed.add_field(
            name=t_orion(gid, "mission_description"),
            value=desc[:1000],
            inline=False,
        )
    if players:
        embed.add_field(
            name=t_orion(gid, "mission_players"),
            value=" ".join(f"<@{uid}>" for uid in players[:20]),
            inline=False,
        )
    embed.set_footer(text=f"Mission ID: {mid}")
    return embed


def _mission_notif_embed(gid: int, mid: str, m: dict) -> discord.Embed:
    """Rich notification embed posted to board channels when a mission is created."""
    color    = _DIFF_COLORS.get(m.get("difficulty", "E"), EMBED_COLOR)
    diff_emo = _DIFF_EMOJIS.get(m.get("difficulty", "E"), "")
    cap      = m.get("max_players", 0)
    cap_str  = t_orion(gid, "mission_unlimited") if cap == 0 else str(cap)
    players  = m.get("players", [])
    reward   = m.get("reward_money", 0)

    embed = discord.Embed(
        title=t_orion(gid, "mission_new"),
        color=color,
    )
    embed.add_field(
        name="📋 Mission / ภารกิจ",
        value=f"**{diff_emo} {m.get('title', 'Untitled')}**",
        inline=False,
    )
    embed.add_field(
        name=t_orion(gid, "mission_difficulty"),
        value=f"{diff_emo} **{m.get('difficulty', '?')}**",
        inline=True,
    )
    embed.add_field(
        name=t_orion(gid, "mission_players"),
        value=f"**{len(players)}/{cap_str}**",
        inline=True,
    )
    if reward:
        embed.add_field(
            name=t_orion(gid, "mission_reward"),
            value=money_str(reward, gid),
            inline=True,
        )

    desc = m.get("description", "").strip()
    if desc:
        embed.add_field(
            name=t_orion(gid, "mission_description"),
            value=desc[:1000],
            inline=False,
        )

    embed.add_field(
        name=t_orion(gid, "mission_how_to_join"),
        value=t_orion(gid, "mission_join_instr"),
        inline=False,
    )
    embed.set_footer(text=f"ID: {mid}  ·  Use /missions to view all  ·  ใช้ /missions ดูทั้งหมด")
    return embed


def _board_embed(gid: int, page: int = 0, difficulty: str | None = None) -> discord.Embed:
    """Summary embed for the /missions board view."""
    missions = load_missions(gid)
    active   = {
        mid: m
        for mid, m in missions.items()
        if m.get("status") == "open"
        and (difficulty is None or m.get("difficulty") == difficulty)
    }
    total = len(active)
    pages = max(1, (total + _MISSIONS_PER_PAGE - 1) // _MISSIONS_PER_PAGE)
    page  = max(0, min(page, pages - 1))
    chunk = list(active.items())[page * _MISSIONS_PER_PAGE:(page + 1) * _MISSIONS_PER_PAGE]

    embed = discord.Embed(
        title=t_orion(gid, "mission_board_title"),
        color=EMBED_COLOR,
    )
    embed.set_footer(
        text=t_orion(gid, "mission_footer", page=page + 1, total=pages, count=total)
    )

    if not chunk:
        embed.description = t_orion(gid, "mission_board_empty")
        return embed

    for mid, m in chunk:
        cap      = m.get("max_players", 0)
        cap_str  = t_orion(gid, "mission_unlimited") if cap == 0 else str(cap)
        members  = len(m.get("players", []))
        diff_emo = _DIFF_EMOJIS.get(m.get("difficulty", "E"), "")
        embed.add_field(
            name=f"{diff_emo} [{m.get('difficulty','?')}] {m.get('title','?')[:50]}",
            value=(
                f"👥 {members}/{cap_str}  ·  "
                f"💰 {m.get('reward_money', 0):,}"
                + (f"\n{m.get('description','')[:80]}…" if m.get("description") else "")
            ),
            inline=False,
        )
    return embed


# ── Notification view (posted to board channels) ──────────────────────────────

class MissionNotifView(discord.ui.View):
    """Persistent buttons on the channel notification message."""

    def __init__(self, gid: int, mid: str):
        super().__init__(timeout=None)
        self.gid = gid
        self.mid = mid
        join_btn    = discord.ui.Button(
            label=t_orion(gid, "mission_join_btn"),
            style=discord.ButtonStyle.success,
            custom_id=f"mn_join_{mid}",
            row=0,
        )
        details_btn = discord.ui.Button(
            label=t_orion(gid, "mission_details_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"mn_det_{mid}",
            row=0,
        )
        join_btn.callback    = self._join
        details_btn.callback = self._details
        self.add_item(join_btn)
        self.add_item(details_btn)

    async def _join(self, ix: discord.Interaction):
        gid = self.gid
        mid = self.mid
        uid = str(ix.user.id)

        # Must have a character
        if uid not in load_players(gid):
            await ix.response.send_message(
                embed=discord.Embed(
                    description=t_orion(gid, "mission_no_char"),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        missions = load_missions(gid)
        m        = missions.get(mid)
        if not m or m.get("status") != "open":
            await ix.response.send_message(
                embed=discord.Embed(
                    description=t_orion(gid, "mission_closed"),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        players = m.get("players", [])
        if uid in players:
            await ix.response.send_message(
                embed=discord.Embed(
                    description=t_orion(gid, "mission_already_in"),
                    color=0xF59E0B,
                ),
                ephemeral=True,
            )
            return

        cap = m.get("max_players", 0)
        if cap != 0 and len(players) >= cap:
            await ix.response.send_message(
                embed=discord.Embed(
                    description=t_orion(gid, "mission_full"),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        players.append(uid)
        m["players"] = players
        missions[mid] = m
        save_missions(gid, missions)

        # Update notification message in-place (live player count)
        await ix.response.edit_message(
            embed=_mission_notif_embed(gid, mid, m),
            view=MissionNotifView(gid, mid),
        )
        await ix.followup.send(
            embed=discord.Embed(
                description=t_orion(gid, "mission_joined", title=m.get("title", "?")),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    async def _details(self, ix: discord.Interaction):
        missions = load_missions(self.gid)
        m        = missions.get(self.mid, {})
        embed    = _mission_detail_embed(self.gid, self.mid, m)
        uid      = ix.user.id
        in_mission = str(uid) in m.get("players", [])

        view = _NotifDetailView(uid, self.gid, self.mid)
        view._rebuild(in_mission)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class _NotifDetailView(discord.ui.View):
    """Ephemeral detail view opened from a notification message."""

    def __init__(self, uid: int, gid: int, mid: str):
        super().__init__(timeout=120)
        self.uid = uid
        self.gid = gid
        self.mid = mid

    def _rebuild(self, already_in: bool):
        self.clear_items()
        if already_in:
            leave_btn = discord.ui.Button(
                label=t_orion(self.gid, "mission_leave_btn"),
                style=discord.ButtonStyle.danger,
            )
            leave_btn.callback = self._leave
            self.add_item(leave_btn)
        else:
            join_btn = discord.ui.Button(
                label=t_orion(self.gid, "mission_join_btn"),
                style=discord.ButtonStyle.success,
            )
            join_btn.callback = self._join
            self.add_item(join_btn)

    async def _join(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your session.", ephemeral=True)
            return
        gid = self.gid
        uid = str(self.uid)

        if uid not in load_players(gid):
            await ix.response.send_message(
                t_orion(gid, "mission_no_char"), ephemeral=True
            )
            return

        missions = load_missions(gid)
        m        = missions.get(self.mid)
        if not m or m.get("status") != "open":
            await ix.response.send_message(t_orion(gid, "mission_closed"), ephemeral=True)
            return

        players = m.get("players", [])
        if uid in players:
            await ix.response.send_message(t_orion(gid, "mission_already_in"), ephemeral=True)
            return

        cap = m.get("max_players", 0)
        if cap != 0 and len(players) >= cap:
            await ix.response.send_message(t_orion(gid, "mission_full"), ephemeral=True)
            return

        players.append(uid)
        m["players"] = players
        missions[self.mid] = m
        save_missions(gid, missions)

        self._rebuild(True)
        await ix.response.edit_message(
            embed=_mission_detail_embed(gid, self.mid, m),
            view=self,
        )
        # Also update notification messages in board channels
        await _refresh_notif_messages(ix.guild, gid, self.mid, m)

    async def _leave(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your session.", ephemeral=True)
            return
        gid      = self.gid
        uid      = str(self.uid)
        missions = load_missions(gid)
        m        = missions.get(self.mid, {})
        players  = m.get("players", [])
        if uid in players:
            players.remove(uid)
        m["players"] = players
        missions[self.mid] = m
        save_missions(gid, missions)

        self._rebuild(False)
        await ix.response.edit_message(
            embed=_mission_detail_embed(gid, self.mid, m),
            view=self,
        )
        await _refresh_notif_messages(ix.guild, gid, self.mid, m)


async def _refresh_notif_messages(guild: discord.Guild, gid: int, mid: str, m: dict):
    """Edit all stored notification messages to reflect the latest player count."""
    notif_msgs = m.get("notif_messages", {})
    if not notif_msgs:
        return
    new_embed = _mission_notif_embed(gid, mid, m)
    for ch_id, msg_id in notif_msgs.items():
        try:
            ch  = guild.get_channel(int(ch_id))
            if ch:
                msg = await ch.fetch_message(int(msg_id))
                await msg.edit(embed=new_embed, view=MissionNotifView(gid, mid))
        except Exception:
            pass


# ── Board view (from /missions) ───────────────────────────────────────────────

class MissionBoardView(discord.ui.View):
    def __init__(self, uid: int, gid: int, page: int = 0, difficulty: str | None = None):
        super().__init__(timeout=300)
        self.uid        = uid
        self.gid        = gid
        self.page       = page
        self.difficulty = difficulty
        self._build()

    def _build(self):
        self.clear_items()
        gid      = self.gid
        missions = load_missions(gid)
        active   = [
            (mid, m)
            for mid, m in missions.items()
            if m.get("status") == "open"
            and (self.difficulty is None or m.get("difficulty") == self.difficulty)
        ]
        total = len(active)
        pages = max(1, (total + _MISSIONS_PER_PAGE - 1) // _MISSIONS_PER_PAGE)
        chunk = active[self.page * _MISSIONS_PER_PAGE:(self.page + 1) * _MISSIONS_PER_PAGE]

        # Mission selector
        if chunk:
            opts = [
                discord.SelectOption(
                    label=f"{_DIFF_EMOJIS.get(m.get('difficulty','E'),'')} [{m.get('difficulty','?')}] {m.get('title','?')[:70]}",
                    value=mid,
                    description=(
                        f"{len(m.get('players',[]))}"
                        f"/{m.get('max_players',0) or t_orion(gid,'mission_unlimited')} "
                        f"· 💰 {m.get('reward_money',0):,}"
                    )[:100],
                )
                for mid, m in chunk
            ]
            sel = discord.ui.Select(
                placeholder="เลือกภารกิจ / Select mission…",
                options=opts,
                row=0,
            )
            sel.callback = self._on_select
            self.add_item(sel)

        # Difficulty filter
        diff_all = discord.SelectOption(
            label="All / ทั้งหมด", value="all", default=self.difficulty is None
        )
        diff_opts = [diff_all] + [
            discord.SelectOption(
                label=f"{_DIFF_EMOJIS.get(d,'')} {d}",
                value=d,
                default=self.difficulty == d,
            )
            for d in _DIFF_LABELS
        ]
        diff_sel = discord.ui.Select(
            placeholder="Filter / กรอง…",
            options=diff_opts,
            row=1,
        )
        diff_sel.callback = self._on_diff
        self.add_item(diff_sel)

        # Pagination
        prev_btn = discord.ui.Button(
            label=t_orion(gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
            row=2,
        )
        prev_btn.callback = self._prev
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(
            label=t_orion(gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= pages - 1,
            row=2,
        )
        next_btn.callback = self._next
        self.add_item(next_btn)

        my_btn = discord.ui.Button(
            label="📋 My Missions / ของฉัน",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        my_btn.callback = self._my_missions
        self.add_item(my_btn)

    async def _on_select(self, ix: discord.Interaction):
        mid      = ix.data["values"][0]
        missions = load_missions(self.gid)
        m        = missions.get(mid)
        if not m:
            await ix.response.send_message("Mission not found.", ephemeral=True)
            return
        view = MissionDetailView(self.uid, self.gid, mid, self)
        await ix.response.edit_message(
            embed=_mission_detail_embed(self.gid, mid, m), view=view
        )

    async def _on_diff(self, ix: discord.Interaction):
        val             = ix.data["values"][0]
        self.difficulty = None if val == "all" else val
        self.page       = 0
        self._build()
        await ix.response.edit_message(
            embed=_board_embed(self.gid, self.page, self.difficulty), view=self
        )

    async def _prev(self, ix: discord.Interaction):
        self.page -= 1
        self._build()
        await ix.response.edit_message(
            embed=_board_embed(self.gid, self.page, self.difficulty), view=self
        )

    async def _next(self, ix: discord.Interaction):
        self.page += 1
        self._build()
        await ix.response.edit_message(
            embed=_board_embed(self.gid, self.page, self.difficulty), view=self
        )

    async def _my_missions(self, ix: discord.Interaction):
        missions = load_missions(self.gid)
        mine = {
            mid: m for mid, m in missions.items()
            if str(self.uid) in m.get("players", [])
        }
        if not mine:
            await ix.response.send_message(
                embed=discord.Embed(
                    description="You haven't joined any missions. / ยังไม่ได้เข้าร่วมภารกิจใด",
                    color=0xF59E0B,
                ),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="📋 My Missions / ภารกิจของฉัน",
            color=EMBED_COLOR,
        )
        for mid, m in list(mine.items())[:10]:
            diff_emo = _DIFF_EMOJIS.get(m.get("difficulty", "E"), "")
            embed.add_field(
                name=f"{diff_emo} {m.get('title','?')[:50]}",
                value=(
                    f"Difficulty: {m.get('difficulty','?')}  ·  "
                    f"Status: {t_orion(self.gid, 'mission_' + m.get('status','open'))}"
                ),
                inline=False,
            )
        await ix.response.send_message(embed=embed, ephemeral=True)


class MissionDetailView(discord.ui.View):
    def __init__(self, uid: int, gid: int, mid: str, parent: MissionBoardView | None):
        super().__init__(timeout=120)
        self.uid    = uid
        self.gid    = gid
        self.mid    = mid
        self.parent = parent
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        missions   = load_missions(self.gid)
        m          = missions.get(self.mid, {})
        already_in = str(self.uid) in m.get("players", [])

        if already_in:
            leave_btn = discord.ui.Button(
                label=t_orion(self.gid, "mission_leave_btn"),
                style=discord.ButtonStyle.danger,
                row=0,
            )
            leave_btn.callback = self._leave
            self.add_item(leave_btn)
        else:
            join_btn = discord.ui.Button(
                label=t_orion(self.gid, "mission_join_btn"),
                style=discord.ButtonStyle.success,
                row=0,
            )
            join_btn.callback = self._join
            self.add_item(join_btn)

        if self.parent is not None:
            back_btn = discord.ui.Button(
                label=t_orion(self.gid, "back_btn"),
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            back_btn.callback = self._back
            self.add_item(back_btn)

    async def _join(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your session.", ephemeral=True)
            return
        gid = self.gid
        uid = str(self.uid)

        if uid not in load_players(gid):
            await ix.response.send_message(t_orion(gid, "mission_no_char"), ephemeral=True)
            return

        missions = load_missions(gid)
        m        = missions.get(self.mid)
        if not m or m.get("status") != "open":
            await ix.response.send_message(t_orion(gid, "mission_closed"), ephemeral=True)
            return

        players = m.get("players", [])
        if uid in players:
            await ix.response.send_message(t_orion(gid, "mission_already_in"), ephemeral=True)
            return

        cap = m.get("max_players", 0)
        if cap != 0 and len(players) >= cap:
            await ix.response.send_message(t_orion(gid, "mission_full"), ephemeral=True)
            return

        players.append(uid)
        m["players"] = players
        missions[self.mid] = m
        save_missions(gid, missions)

        self._rebuild()
        await ix.response.edit_message(
            embed=_mission_detail_embed(gid, self.mid, m), view=self
        )
        await _refresh_notif_messages(ix.guild, gid, self.mid, m)

    async def _leave(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your session.", ephemeral=True)
            return
        gid      = self.gid
        uid      = str(self.uid)
        missions = load_missions(gid)
        m        = missions.get(self.mid, {})
        players  = m.get("players", [])
        if uid in players:
            players.remove(uid)
        m["players"] = players
        missions[self.mid] = m
        save_missions(gid, missions)

        self._rebuild()
        await ix.response.edit_message(
            embed=_mission_detail_embed(gid, self.mid, m), view=self
        )
        await _refresh_notif_messages(ix.guild, gid, self.mid, m)

    async def _back(self, ix: discord.Interaction):
        if self.parent:
            self.parent._build()
            await ix.response.edit_message(
                embed=_board_embed(self.gid, self.parent.page, self.parent.difficulty),
                view=self.parent,
            )


# ── /missions slash command ───────────────────────────────────────────────────

@bot.tree.command(
    name="missions",
    description="View Mission Board and join missions",
    description_localizations={"th": "ดูกระดานภารกิจและเข้าร่วมภารกิจ"},
)
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_missions(ix: discord.Interaction):
    gid = ix.guild_id
    cfg = load_config(gid)

    # Channel restriction
    board_channels = cfg.get("mission_channels", [])
    if board_channels and str(ix.channel_id) not in [str(c) for c in board_channels]:
        allowed = " ".join(f"<#{c}>" for c in board_channels)
        await ix.response.send_message(
            embed=discord.Embed(
                description=(
                    f"Use this command in the mission board channel(s): {allowed}\n"
                    f"ใช้คำสั่งในห้อง Mission Board: {allowed}"
                ),
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    # Character check
    players = load_players(gid)
    if str(ix.user.id) not in players:
        await ix.response.send_message(
            embed=discord.Embed(
                description=t_orion(gid, "mission_no_char"),
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    embed = _board_embed(gid)
    view  = MissionBoardView(ix.user.id, gid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── /missions-admin slash command ─────────────────────────────────────────────

@bot.tree.command(
    name="missions-admin",
    description="[Admin] Create and manage missions",
    description_localizations={"th": "[Admin] สร้างและจัดการภารกิจ"},
)
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_missions_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message(t_orion(ix.guild_id, "admin_only"), ephemeral=True)
        return
    view  = MissionsAdminView(ix.guild_id)
    embed = discord.Embed(
        title="⚔️ Missions Admin / จัดการภารกิจ",
        description=(
            "Create, close, and configure missions.\n"
            "สร้าง ปิด และตั้งค่าภารกิจ"
        ),
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class MissionsAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(
        label="➕ New Mission / ภารกิจใหม่",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def create(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(CreateMissionModal(self.gid))

    @discord.ui.button(
        label="📋 List / รายการ",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def list_missions(self, ix: discord.Interaction, _: discord.ui.Button):
        missions = load_missions(self.gid)
        if not missions:
            await ix.response.send_message("No missions. / ไม่มีภารกิจ", ephemeral=True)
            return
        embed = discord.Embed(
            title="📋 All Missions / ทุกภารกิจ",
            color=EMBED_COLOR,
        )
        for mid, m in list(missions.items())[:20]:
            diff_emo  = _DIFF_EMOJIS.get(m.get("difficulty", "E"), "")
            status_th = t_orion(self.gid, "mission_" + m.get("status", "open"))
            embed.add_field(
                name=f"{diff_emo} {m.get('title','?')[:40]}",
                value=(
                    f"ID: `{mid}` | Status: {status_th}\n"
                    f"👥 {len(m.get('players',[]))}/{m.get('max_players',0) or '∞'}"
                ),
                inline=False,
            )
        await ix.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="🏆 Complete / ปิด+รางวัล",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def complete(self, ix: discord.Interaction, _: discord.ui.Button):
        missions = load_missions(self.gid)
        active   = {mid: m for mid, m in missions.items() if m.get("status") == "open"}
        if not active:
            await ix.response.send_message("No open missions. / ไม่มีภารกิจที่เปิด", ephemeral=True)
            return
        opts = [
            discord.SelectOption(
                label=f"[{m.get('difficulty','?')}] {m.get('title','?')[:80]}",
                value=mid,
            )
            for mid, m in active.items()
        ][:25]
        sel = discord.ui.Select(
            placeholder="Select mission to complete… / เลือกภารกิจที่จะปิด…",
            options=opts,
        )
        sel.callback = self._complete_cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    async def _complete_cb(self, ix: discord.Interaction):
        mid      = ix.data["values"][0]
        missions = load_missions(self.gid)
        m        = missions.get(mid)
        if not m:
            await ix.response.send_message("Mission not found.", ephemeral=True)
            return

        gid          = self.gid
        reward_money = m.get("reward_money", 0)
        reward_items = m.get("reward_items", {})
        players      = load_players(gid)

        for uid in m.get("players", []):
            if reward_money:
                add_money(gid, uid, reward_money)
            if reward_items:
                p   = players.get(str(uid), {})
                inv = p.setdefault("inventory", {})
                for iid, qty in reward_items.items():
                    inv[iid] = inv.get(iid, 0) + qty
                players[str(uid)] = p

        if reward_items:
            save_players(gid, players)

        m["status"]       = "completed"
        missions[mid]     = m
        save_missions(gid, missions)

        reward_str = money_str(reward_money, gid) if reward_money else "—"
        count      = len(m.get("players", []))
        await ix.response.send_message(
            embed=discord.Embed(
                description=(
                    f"🏆 Mission **{m.get('title','?')}** completed!\n"
                    f"Rewarded {count} player(s) · 💰 {reward_str}\n\n"
                    f"ปิดภารกิจ **{m.get('title','?')}** แล้ว!\n"
                    f"มอบรางวัลให้ {count} คน · 💰 {reward_str}"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="⚙️ Board Channels / ห้องภารกิจ",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def board_channels(self, ix: discord.Interaction, _: discord.ui.Button):
        view2 = _SetBoardChannelsView(self.gid)
        embed = discord.Embed(
            description=(
                "Select channels to be Mission Boards.\n"
                "เลือกห้องที่จะใช้เป็นกระดานภารกิจ"
            ),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view2, ephemeral=True)

    @discord.ui.button(
        label="🗑️ Delete Mission / ลบภารกิจ",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def delete_mission(self, ix: discord.Interaction, _: discord.ui.Button):
        missions = load_missions(self.gid)
        if not missions:
            await ix.response.send_message("No missions.", ephemeral=True)
            return
        opts = [
            discord.SelectOption(
                label=f"[{m.get('difficulty','?')}] {m.get('title','?')[:80]}",
                value=mid,
            )
            for mid, m in missions.items()
        ][:25]
        sel = discord.ui.Select(
            placeholder="Select mission to delete… / เลือกภารกิจที่จะลบ…",
            options=opts,
        )

        async def _del(ix2: discord.Interaction):
            missions2 = load_missions(self.gid)
            name = missions2.get(ix2.data["values"][0], {}).get("title", "?")
            missions2.pop(ix2.data["values"][0], None)
            save_missions(self.gid, missions2)
            await ix2.response.send_message(
                embed=discord.Embed(
                    description=f"🗑️ Deleted **{name}** / ลบ **{name}** แล้ว",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        sel.callback = _del
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)


class _SetBoardChannelsView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid = gid
        sel = discord.ui.ChannelSelect(
            placeholder="Select Mission Board channels… / เลือกห้อง…",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=10,
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        ch_ids = ix.data["values"]
        cfg    = load_config(self.gid)
        cfg["mission_channels"] = ch_ids
        save_config(self.gid, cfg)
        ch_str = " ".join(f"<#{c}>" for c in ch_ids) or "Any channel / ทุกห้อง"
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ Mission Board channels: {ch_str}",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


# ── Create Mission Modal ───────────────────────────────────────────────────────

class CreateMissionModal(discord.ui.Modal, title="New Mission / ภารกิจใหม่"):
    title_f   = discord.ui.TextInput(
        label="Title / ชื่อภารกิจ",
        max_length=80,
    )
    desc_f    = discord.ui.TextInput(
        label="Description / รายละเอียด",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=False,
    )
    diff_f    = discord.ui.TextInput(
        label="Difficulty / ความยาก  (E D C B A S EX)",
        max_length=3,
    )
    reward_f  = discord.ui.TextInput(
        label="Reward money / รางวัลเงิน  (0 = none)",
        max_length=10,
        required=False,
    )
    max_play_f = discord.ui.TextInput(
        label="Max players / สูงสุด  (0 = unlimited)",
        max_length=5,
        required=False,
    )

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        gid  = self.gid
        diff = self.diff_f.value.strip().upper()
        if diff not in _DIFF_LABELS:
            diff = "E"
        try:
            reward = max(0, int(self.reward_f.value.strip() or "0"))
        except ValueError:
            reward = 0
        try:
            max_p = max(0, int(self.max_play_f.value.strip() or "0"))
        except ValueError:
            max_p = 0

        mid      = str(uuid.uuid4())[:8]
        missions = load_missions(gid)
        missions[mid] = {
            "title":          self.title_f.value.strip(),
            "description":    self.desc_f.value.strip(),
            "difficulty":     diff,
            "reward_money":   reward,
            "reward_items":   {},
            "max_players":    max_p,
            "players":        [],
            "created_by":     str(ix.user.id),
            "created_at":     time.time(),
            "status":         "open",
            "notif_messages": {},
        }
        save_missions(gid, missions)

        cfg            = load_config(gid)
        board_channels = cfg.get("mission_channels", [])

        # Confirm to admin first
        await ix.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ Mission **{missions[mid]['title']}** created! (ID: `{mid}`)\n"
                    f"สร้างภารกิจ **{missions[mid]['title']}** แล้ว!\n\n"
                    f"{'Posting notification to ' + str(len(board_channels)) + ' board channel(s)…' if board_channels else '⚠️ No board channels set — use `/missions-admin` → Board Channels to configure.'}"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

        if not board_channels:
            return

        # Post notification to every board channel
        m         = missions[mid]
        notif_emb = _mission_notif_embed(gid, mid, m)
        notif_view = MissionNotifView(gid, mid)
        notif_msgs: dict[str, str] = {}

        for ch_id in board_channels:
            try:
                ch = ix.guild.get_channel(int(ch_id))
                if ch:
                    msg = await ch.send(embed=notif_emb, view=notif_view)
                    notif_msgs[str(ch_id)] = str(msg.id)
            except Exception:
                pass

        # Store message IDs for live updates
        if notif_msgs:
            missions            = load_missions(gid)
            missions[mid]["notif_messages"] = notif_msgs
            save_missions(gid, missions)
