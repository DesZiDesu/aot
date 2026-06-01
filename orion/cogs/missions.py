"""Orion — mission boards: multi-channel, dropdown join, configurable player cap."""
import time
import uuid
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR,
    load_config, save_config,
    load_missions, save_missions,
    money_str, add_money, load_players,
)

_DIFF_COLORS = {
    "E": 0x9B9B9B, "D": 0x4CAF50, "C": 0x2196F3,
    "B": 0x9C27B0, "A": 0xFF9800, "S": 0xFF4444, "EX": 0xFFD700,
}
_DIFF_LABELS = ["E", "D", "C", "B", "A", "S", "EX"]
_MISSIONS_PER_PAGE = 10


def _mission_embed(mid: str, m: dict) -> discord.Embed:
    color  = _DIFF_COLORS.get(m.get("difficulty", "E"), EMBED_COLOR)
    embed  = discord.Embed(title=m.get("title", "Untitled"), color=color)
    embed.add_field(name="ความยาก", value=m.get("difficulty", "?"), inline=True)
    players_in = m.get("players", [])
    cap        = m.get("max_players", 0)
    cap_str    = "∞" if cap == 0 else str(cap)
    embed.add_field(name="สมาชิก", value=f"{len(players_in)}/{cap_str}", inline=True)
    embed.add_field(name="สถานะ", value=m.get("status", "open"), inline=True)

    desc = m.get("description", "")
    if desc:
        embed.add_field(name="รายละเอียด", value=desc[:1000], inline=False)

    reward_money = m.get("reward_money", 0)
    if reward_money:
        embed.add_field(name="รางวัลเงิน", value=f"{reward_money:,}", inline=True)

    reward_items = m.get("reward_items", {})
    if reward_items:
        items_str = ", ".join(f"{iid} ×{qty}" for iid, qty in reward_items.items())
        embed.add_field(name="รางวัลไอเทม", value=items_str[:200], inline=True)

    if players_in:
        embed.add_field(
            name="ผู้เข้าร่วม",
            value=" ".join(f"<@{uid}>" for uid in players_in[:20]),
            inline=False,
        )
    embed.set_footer(text=f"ID: {mid}")
    return embed


def _board_embed(gid: int, page: int = 0, difficulty: str | None = None) -> discord.Embed:
    missions = load_missions(gid)
    active   = {
        mid: m
        for mid, m in missions.items()
        if m.get("status") == "open"
        and (difficulty is None or m.get("difficulty") == difficulty)
    }
    total   = len(active)
    pages   = max(1, (total + _MISSIONS_PER_PAGE - 1) // _MISSIONS_PER_PAGE)
    page    = max(0, min(page, pages - 1))
    chunk   = list(active.items())[page * _MISSIONS_PER_PAGE:(page + 1) * _MISSIONS_PER_PAGE]

    embed = discord.Embed(
        title="⚔️ Mission Board",
        color=EMBED_COLOR,
    )
    embed.set_footer(text=f"หน้า {page+1}/{pages} | ภารกิจทั้งหมด {total}")
    if not chunk:
        embed.description = "ไม่มีภารกิจที่เปิดอยู่"
        return embed

    for mid, m in chunk:
        cap       = m.get("max_players", 0)
        cap_str   = "∞" if cap == 0 else str(cap)
        members   = len(m.get("players", []))
        embed.add_field(
            name=f"[{m.get('difficulty','?')}] {m.get('title','?')[:50]}",
            value=(
                f"{members}/{cap_str} ผู้เล่น | "
                f"รางวัล: {m.get('reward_money',0):,} 💰"
            ),
            inline=False,
        )
    return embed


# ── Mission Join/Leave View ───────────────────────────────────────────────────

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
        missions = load_missions(self.gid)
        active   = [
            (mid, m)
            for mid, m in missions.items()
            if m.get("status") == "open"
            and (self.difficulty is None or m.get("difficulty") == self.difficulty)
        ]
        total = len(active)
        pages = max(1, (total + _MISSIONS_PER_PAGE - 1) // _MISSIONS_PER_PAGE)
        chunk = active[self.page * _MISSIONS_PER_PAGE:(self.page + 1) * _MISSIONS_PER_PAGE]

        if chunk:
            opts = [
                discord.SelectOption(
                    label=f"[{m.get('difficulty','?')}] {m.get('title','?')[:80]}",
                    value=mid,
                    description=(
                        f"{len(m.get('players',[]))}/{m.get('max_players',0) or '∞'} ผู้เล่น | "
                        f"รางวัล {m.get('reward_money',0):,} 💰"
                    )[:100],
                )
                for mid, m in chunk
            ]
            sel = discord.ui.Select(
                placeholder="เลือกภารกิจ…",
                options=opts,
                row=0,
            )
            sel.callback = self._on_select
            self.add_item(sel)

        # Difficulty filter
        diff_opts = [discord.SelectOption(label="ทั้งหมด", value="all", default=self.difficulty is None)]
        for d in _DIFF_LABELS:
            diff_opts.append(
                discord.SelectOption(label=d, value=d, default=self.difficulty == d)
            )
        diff_sel = discord.ui.Select(
            placeholder="กรองความยาก…",
            options=diff_opts,
            row=1,
        )
        diff_sel.callback = self._on_diff
        self.add_item(diff_sel)

        # Pagination
        prev_btn = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
            row=2,
        )
        prev_btn.callback = self._prev
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= pages - 1,
            row=2,
        )
        next_btn.callback = self._next
        self.add_item(next_btn)

        my_btn = discord.ui.Button(
            label="📋 ภารกิจของฉัน",
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
            await ix.response.send_message("ภารกิจนี้ไม่มีอยู่แล้ว", ephemeral=True)
            return
        embed = _mission_embed(mid, m)
        view  = MissionDetailView(self.uid, self.gid, mid, self)
        await ix.response.edit_message(embed=embed, view=view)

    async def _on_diff(self, ix: discord.Interaction):
        val = ix.data["values"][0]
        self.difficulty = None if val == "all" else val
        self.page = 0
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
            await ix.response.send_message("คุณยังไม่ได้เข้าร่วมภารกิจใด", ephemeral=True)
            return
        embed = discord.Embed(title="📋 ภารกิจของฉัน", color=EMBED_COLOR)
        for mid, m in list(mine.items())[:10]:
            embed.add_field(
                name=m.get("title", "?")[:50],
                value=f"ความยาก: {m.get('difficulty','?')} | สถานะ: {m.get('status','?')}",
                inline=False,
            )
        await ix.response.send_message(embed=embed, ephemeral=True)


class MissionDetailView(discord.ui.View):
    def __init__(self, uid: int, gid: int, mid: str, parent: MissionBoardView):
        super().__init__(timeout=120)
        self.uid    = uid
        self.gid    = gid
        self.mid    = mid
        self.parent = parent
        self._build()

    def _build(self):
        missions    = load_missions(self.gid)
        m           = missions.get(self.mid, {})
        already_in  = str(self.uid) in m.get("players", [])

        join_btn = discord.ui.Button(
            label="✅ เข้าร่วม" if not already_in else "❌ ออก",
            style=discord.ButtonStyle.success if not already_in else discord.ButtonStyle.danger,
            row=0,
        )
        join_btn.callback = self._join if not already_in else self._leave
        self.add_item(join_btn)

        back_btn = discord.ui.Button(
            label="◀ กลับ", style=discord.ButtonStyle.secondary, row=0
        )
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _join(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
            return
        missions = load_missions(self.gid)
        m        = missions.get(self.mid)
        if not m:
            await ix.response.send_message("ภารกิจนี้ไม่มีอยู่แล้ว", ephemeral=True)
            return
        cap = m.get("max_players", 0)
        cur = m.get("players", [])
        if cap != 0 and len(cur) >= cap:
            await ix.response.send_message("ภารกิจเต็มแล้ว", ephemeral=True)
            return
        if str(self.uid) in cur:
            await ix.response.send_message("คุณเข้าร่วมแล้ว", ephemeral=True)
            return
        cur.append(str(self.uid))
        m["players"] = cur
        missions[self.mid] = m
        save_missions(self.gid, missions)
        self._build()
        await ix.response.edit_message(embed=_mission_embed(self.mid, m), view=self)

    async def _leave(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
            return
        missions = load_missions(self.gid)
        m        = missions.get(self.mid)
        if not m:
            await ix.response.send_message("ภารกิจนี้ไม่มีอยู่แล้ว", ephemeral=True)
            return
        players = m.get("players", [])
        if str(self.uid) in players:
            players.remove(str(self.uid))
        m["players"] = players
        missions[self.mid] = m
        save_missions(self.gid, missions)
        self._build()
        await ix.response.edit_message(embed=_mission_embed(self.mid, m), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(
            embed=_board_embed(self.gid, self.parent.page, self.parent.difficulty),
            view=self.parent,
        )


# ── /missions command ─────────────────────────────────────────────────────────

@bot.tree.command(name="missions", description="ดู Mission Board — เข้าร่วมภารกิจ")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_missions(ix: discord.Interaction):
    gid = ix.guild_id
    cfg = load_config(gid)

    # Check if this channel is a mission board channel (or no restriction)
    board_channels = cfg.get("mission_channels", [])
    if board_channels and str(ix.channel_id) not in [str(c) for c in board_channels]:
        allowed = " ".join(f"<#{c}>" for c in board_channels)
        await ix.response.send_message(
            f"ใช้คำสั่งนี้ในห้อง Mission Board: {allowed}", ephemeral=True
        )
        return

    # Check player
    players = load_players(gid)
    if str(ix.user.id) not in players:
        await ix.response.send_message(
            embed=discord.Embed(
                description="ต้องสร้างตัวละครก่อน ใช้ `/orion`",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    embed = _board_embed(gid)
    view  = MissionBoardView(ix.user.id, gid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── /missions-admin command ───────────────────────────────────────────────────

@bot.tree.command(name="missions-admin", description="[Admin] สร้าง/จัดการภารกิจ")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_missions_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    view  = MissionsAdminView(ix.guild_id)
    embed = discord.Embed(title="⚔️ Missions Admin", color=EMBED_COLOR)
    embed.description = "สร้าง แก้ไข หรือปิดภารกิจ"
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class MissionsAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="➕ สร้างภารกิจ", style=discord.ButtonStyle.success, row=0)
    async def create(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(CreateMissionModal(self.gid))

    @discord.ui.button(label="📋 รายการภารกิจ", style=discord.ButtonStyle.secondary, row=0)
    async def list_missions(self, ix: discord.Interaction, _: discord.ui.Button):
        missions = load_missions(self.gid)
        if not missions:
            await ix.response.send_message("ไม่มีภารกิจ", ephemeral=True)
            return
        embed = discord.Embed(title="📋 ทุกภารกิจ", color=EMBED_COLOR)
        for mid, m in list(missions.items())[:20]:
            embed.add_field(
                name=m.get("title", "?")[:50],
                value=(
                    f"ID: `{mid}` | ความยาก: {m.get('difficulty','?')}\n"
                    f"สถานะ: {m.get('status','?')} | "
                    f"{len(m.get('players',[]))}/{m.get('max_players',0) or '∞'}"
                ),
                inline=False,
            )
        await ix.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🏆 ปิดภารกิจ (ให้รางวัล)", style=discord.ButtonStyle.primary, row=1)
    async def complete(self, ix: discord.Interaction, _: discord.ui.Button):
        missions = load_missions(self.gid)
        active   = {mid: m for mid, m in missions.items() if m.get("status") == "open"}
        if not active:
            await ix.response.send_message("ไม่มีภารกิจที่เปิดอยู่", ephemeral=True)
            return
        opts = [
            discord.SelectOption(
                label=m.get("title", "?")[:100], value=mid
            )
            for mid, m in active.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกภารกิจที่จะปิด…", options=opts)
        sel.callback = self._complete_cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    async def _complete_cb(self, ix: discord.Interaction):
        mid      = ix.data["values"][0]
        missions = load_missions(self.gid)
        m        = missions.get(mid)
        if not m:
            await ix.response.send_message("ไม่พบภารกิจ", ephemeral=True)
            return
        # Give rewards
        gid          = self.gid
        reward_money = m.get("reward_money", 0)
        reward_items = m.get("reward_items", {})
        players      = load_players(gid)
        rewarded     = []
        for uid in m.get("players", []):
            if reward_money:
                add_money(gid, uid, reward_money)
            if reward_items:
                p = players.get(str(uid), {})
                inv = p.setdefault("inventory", {})
                for iid, qty in reward_items.items():
                    inv[iid] = inv.get(iid, 0) + qty
                players[str(uid)] = p
            rewarded.append(uid)
        if reward_items:
            from core.shared import save_players
            save_players(gid, players)
        m["status"] = "completed"
        missions[mid] = m
        save_missions(gid, missions)
        reward_str = money_str(reward_money, gid) if reward_money else "—"
        await ix.response.send_message(
            embed=discord.Embed(
                description=(
                    f"🏆 ปิดภารกิจ **{m.get('title','?')}** แล้ว\n"
                    f"ผู้ที่ได้รับรางวัล: {len(rewarded)} คน | เงิน: {reward_str}"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="⚙️ ตั้ง Board Channels", style=discord.ButtonStyle.secondary, row=1)
    async def board_channels(self, ix: discord.Interaction, _: discord.ui.Button):
        view2 = SetBoardChannelsView(self.gid)
        embed = discord.Embed(
            description="เลือกห้องที่ใช้เป็น Mission Board:",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view2, ephemeral=True)


class SetBoardChannelsView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid = gid
        sel = discord.ui.ChannelSelect(
            placeholder="เลือกห้อง Mission Board…",
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
        ch_str = " ".join(f"<#{c}>" for c in ch_ids) or "ทุกห้อง"
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ Mission Board channels: {ch_str}", color=EMBED_COLOR
            ),
            ephemeral=True,
        )


class CreateMissionModal(discord.ui.Modal, title="สร้างภารกิจ"):
    title_f    = discord.ui.TextInput(label="ชื่อภารกิจ", max_length=80)
    desc_f     = discord.ui.TextInput(
        label="รายละเอียด",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=False,
    )
    diff_f     = discord.ui.TextInput(label="ความยาก (E/D/C/B/A/S/EX)", max_length=3)
    reward_f   = discord.ui.TextInput(label="รางวัลเงิน", max_length=10, required=False)
    max_play_f = discord.ui.TextInput(
        label="จำนวนผู้เล่นสูงสุด (0 = ไม่จำกัด)",
        max_length=5,
        required=False,
    )

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
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

        mid = str(uuid.uuid4())[:8]
        missions = load_missions(self.gid)
        missions[mid] = {
            "title":        self.title_f.value.strip(),
            "description":  self.desc_f.value.strip(),
            "difficulty":   diff,
            "reward_money": reward,
            "reward_items": {},
            "max_players":  max_p,
            "players":      [],
            "created_by":   str(ix.user.id),
            "created_at":   time.time(),
            "status":       "open",
        }
        save_missions(self.gid, missions)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ สร้างภารกิจ **{self.title_f.value}** แล้ว (ID: `{mid}`)",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
