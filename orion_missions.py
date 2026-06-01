# ============================================================
# ORION — Mission Board System (ระบบภารกิจ)
# ============================================================
# Commands:
#   /ภารกิจ          — ดูภารกิจที่เปิดรับ, เข้าร่วม, ออกจากภารกิจ
#   /ภารกิจแอดมิน   — Admin CRUD + รางวัลไอเทม + ตั้งค่า
# ============================================================

import sys
import time
import uuid
import discord

# ── pull references from orion_bot ──────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_missions ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                       = _orion_bot_mod.bot
ORION_GUILD_ID            = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ          = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR            = _orion_bot_mod.ORION_DATA_DIR
load_json                 = _orion_bot_mod.load_json
save_json                 = _orion_bot_mod.save_json
ensure_orion_player       = _orion_bot_mod.ensure_orion_player
load_orion_players        = _orion_bot_mod.load_orion_players
save_orion_players        = _orion_bot_mod.save_orion_players
add_money                 = _orion_bot_mod.add_money
money_str                 = _orion_bot_mod.money_str

import orion_items
add_player_item    = orion_items.add_player_item
load_items_catalog = orion_items.load_items_catalog

# ── constants ────────────────────────────────────────────────
MISSIONS_FILE        = f"{ORION_DATA_DIR}/missions.json"
MISSIONS_CONFIG_FILE = f"{ORION_DATA_DIR}/missions_config.json"
_PER_PAGE            = 6

DIFF_EMOJIS = {
    "E": "⬜", "D": "🟩", "C": "🟦",
    "B": "🟪", "A": "🟧", "S": "🟥", "EX": "🌟",
}
DIFF_COLORS = {
    "E": 0xffffff, "D": 0x57f287, "C": 0x5865f2,
    "B": 0x9b59b6, "A": 0xe67e22, "S": 0xe74c3c, "EX": 0xf1c40f,
}
VALID_DIFFS = list(DIFF_EMOJIS.keys())


# ── data helpers ─────────────────────────────────────────────
def load_missions() -> dict:
    return load_json(MISSIONS_FILE, {})


def save_missions(d: dict):
    save_json(MISSIONS_FILE, d)


def load_missions_config() -> dict:
    d = load_json(MISSIONS_CONFIG_FILE, {})
    d.setdefault("board_channel_ids", [])
    d.setdefault("admin_role_ids", [])
    return d


def save_missions_config(d: dict):
    save_json(MISSIONS_CONFIG_FILE, d)


def _is_admin(member: discord.Member) -> bool:
    return (member.guild_permissions.administrator or
            member.guild_permissions.manage_guild)


# ── embed helper ─────────────────────────────────────────────
def _mission_embed(mid: str, m: dict) -> discord.Embed:
    diff    = m.get("difficulty", "E")
    emoji   = DIFF_EMOJIS.get(diff, "⬜")
    color   = DIFF_COLORS.get(diff, 0xffffff)
    players = m.get("players", [])
    max_p   = m.get("max_players", 0)
    max_str = str(max_p) if max_p > 0 else "∞"

    embed = discord.Embed(
        title=f"{emoji} {m.get('title', '?')}",
        description=m.get("description", ""),
        color=color,
    )

    embed.add_field(name="ระดับความยาก", value=f"{emoji} {diff}", inline=True)
    embed.add_field(name="ผู้เล่น", value=f"{len(players)}/{max_str}", inline=True)

    # reward field
    catalog     = load_items_catalog()
    reward_parts = []
    reward_money = m.get("reward_money", 0)
    if reward_money > 0:
        reward_parts.append(f"💰 {money_str(reward_money)}")
    for r in m.get("reward_items", []):
        iid  = r.get("item_id", "")
        qty  = r.get("qty", 1)
        item = catalog.get(iid, {})
        name = item.get("name", iid)
        em   = item.get("emoji", "📦")
        reward_parts.append(f"{em} {name} ×{qty}")
    embed.add_field(
        name="รางวัล",
        value=", ".join(reward_parts) if reward_parts else "—",
        inline=False,
    )

    status = m.get("status", "open")
    status_str = {"open": "🟢 เปิด", "completed": "✅ สำเร็จ", "cancelled": "❌ ยกเลิก"}.get(status, status)
    embed.add_field(name="สถานะ", value=status_str, inline=True)

    image_url = m.get("image_url", "")
    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"ID: {mid} · Use /ภารกิจ to view all")
    return embed


# ── notification refresh ──────────────────────────────────────
async def _refresh_notif(guild: discord.Guild, mid: str, m: dict):
    embed = _mission_embed(mid, m)
    notif = m.get("notif_messages", {})
    to_remove = []
    for ch_id, msg_id in list(notif.items()):
        try:
            channel = guild.get_channel(int(ch_id))
            if channel is None:
                channel = await guild.fetch_channel(int(ch_id))
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
        except Exception:
            to_remove.append(ch_id)
    for ch_id in to_remove:
        notif.pop(ch_id, None)
    db = load_missions()
    if mid in db:
        db[mid]["notif_messages"] = notif
        save_missions(db)


# ── post notification to board channels ──────────────────────
async def _post_notif(guild: discord.Guild, mid: str, m: dict) -> dict:
    """Post embed to all board channels; returns notif_messages dict."""
    cfg   = load_missions_config()
    embed = _mission_embed(mid, m)
    notif = {}
    for ch_id in cfg.get("board_channel_ids", []):
        try:
            channel = guild.get_channel(int(ch_id))
            if channel is None:
                channel = await guild.fetch_channel(int(ch_id))
            msg = await channel.send(embed=embed)
            notif[str(ch_id)] = str(msg.id)
        except Exception:
            pass
    return notif


# ── reward distribution ───────────────────────────────────────
async def _distribute_rewards(guild: discord.Guild, m: dict):
    catalog      = load_items_catalog()
    reward_money = m.get("reward_money", 0)
    reward_items = m.get("reward_items", [])
    for uid in m.get("players", []):
        lines = []
        if reward_money > 0:
            add_money(uid, reward_money)
            lines.append(f"💰 {money_str(reward_money)}")
        for r in reward_items:
            iid = r.get("item_id", "")
            qty = max(1, int(r.get("qty", 1)))
            if not iid:
                continue
            add_player_item(uid, iid, qty)
            item  = catalog.get(iid, {})
            em    = item.get("emoji", "📦")
            name  = item.get("name", iid)
            lines.append(f"{em} {name} ×{qty}")
        if not lines:
            continue
        member = guild.get_member(int(uid))
        if member is None:
            try:
                member = await guild.fetch_member(int(uid))
            except Exception:
                continue
        try:
            await member.send(embed=discord.Embed(
                title=f"🏆 ภารกิจสำเร็จ — {m.get('title', '?')}",
                description="\n".join(lines),
                color=discord.Color.gold(),
            ))
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════
# /ภารกิจ — Player command
# ═════════════════════════════════════════════════════════════

class _MissionListView(discord.ui.View):
    def __init__(self, uid: int, page: int = 0):
        super().__init__(timeout=300)
        self.uid  = uid
        self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db     = load_missions()
        active = [(mid, m) for mid, m in db.items() if m.get("status") == "open"]
        total  = max(1, (len(active) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total - 1))
        chunk  = active[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        for row_i, (mid, m) in enumerate(chunk):
            diff     = m.get("difficulty", "E")
            emoji    = DIFF_EMOJIS.get(diff, "⬜")
            players  = m.get("players", [])
            max_p    = m.get("max_players", 0)
            joined   = str(self.uid) in players
            suffix   = " ✅" if joined else ""
            max_str  = str(max_p) if max_p > 0 else "∞"
            label    = f"{emoji} {m.get('title','?')[:35]} ({len(players)}/{max_str}){suffix}"
            btn = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"ml_v_{mid}",
                row=row_i,
            )
            btn.callback = self._make_detail(mid)
            self.add_item(btn)

        prev_btn = discord.ui.Button(
            label="◀", style=discord.ButtonStyle.secondary,
            custom_id="ml_prev", disabled=(self.page == 0), row=4,
        )
        next_btn = discord.ui.Button(
            label="▶", style=discord.ButtonStyle.secondary,
            custom_id="ml_next", disabled=(self.page >= total - 1), row=4,
        )
        done_btn = discord.ui.Button(
            label="❌ ปิด", style=discord.ButtonStyle.danger,
            custom_id="ml_done", row=4,
        )
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        done_btn.callback = self._done
        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(done_btn)

    def _make_detail(self, mid: str):
        async def _cb(ix: discord.Interaction):
            db = load_missions()
            m  = db.get(mid)
            if not m:
                await ix.response.send_message("ไม่พบภารกิจนี้แล้ว", ephemeral=True)
                return
            uid     = str(self.uid)
            joined  = uid in m.get("players", [])
            max_p   = m.get("max_players", 0)
            full    = (max_p > 0 and len(m.get("players", [])) >= max_p)
            await ix.response.send_message(
                embed=_mission_embed(mid, m),
                view=_MissionDetailView(self.uid, mid, joined, full),
                ephemeral=True,
            )
        return _cb

    async def _prev(self, ix: discord.Interaction):
        self.page -= 1
        self._build()
        await ix.response.edit_message(view=self)

    async def _next(self, ix: discord.Interaction):
        self.page += 1
        self._build()
        await ix.response.edit_message(view=self)

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        await ix.response.edit_message(content="*ปิดแล้ว*", view=self)


class _MissionDetailView(discord.ui.View):
    def __init__(self, uid: int, mid: str, joined: bool, full: bool):
        super().__init__(timeout=300)
        self.uid  = uid
        self.mid  = mid

        join_btn = discord.ui.Button(
            label="✅ เข้าร่วม",
            style=discord.ButtonStyle.green if not joined and not full else discord.ButtonStyle.secondary,
            custom_id="md_join",
            disabled=(joined or full),
            row=0,
        )
        join_btn.callback = self._join
        self.add_item(join_btn)

        if joined:
            leave_btn = discord.ui.Button(
                label="🚪 ออก",
                style=discord.ButtonStyle.danger,
                custom_id="md_leave",
                row=0,
            )
            leave_btn.callback = self._leave
            self.add_item(leave_btn)

    async def _join(self, ix: discord.Interaction):
        db  = load_missions()
        m   = db.get(self.mid)
        if not m or m.get("status") != "open":
            await ix.response.send_message("ภารกิจนี้ปิดรับแล้ว", ephemeral=True)
            return
        uid = str(self.uid)
        players = m.setdefault("players", [])
        if uid in players:
            await ix.response.send_message("คุณเข้าร่วมภารกิจนี้แล้ว", ephemeral=True)
            return
        max_p = m.get("max_players", 0)
        if max_p > 0 and len(players) >= max_p:
            await ix.response.send_message("ภารกิจนี้เต็มแล้ว", ephemeral=True)
            return
        players.append(uid)
        save_missions(db)
        # Refresh notification messages
        if ix.guild:
            await _refresh_notif(ix.guild, self.mid, m)
        # Rebuild view
        joined = True
        full   = (max_p > 0 and len(players) >= max_p)
        self.clear_items()
        join_btn = discord.ui.Button(
            label="✅ เข้าร่วม",
            style=discord.ButtonStyle.secondary,
            custom_id="md_join",
            disabled=True,
            row=0,
        )
        join_btn.callback = self._join
        self.add_item(join_btn)
        leave_btn = discord.ui.Button(
            label="🚪 ออก",
            style=discord.ButtonStyle.danger,
            custom_id="md_leave",
            row=0,
        )
        leave_btn.callback = self._leave
        self.add_item(leave_btn)
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"✅ เข้าร่วมภารกิจ **{m.get('title','?')}** แล้ว!",
                color=discord.Color.green(),
            ),
            view=self,
        )

    async def _leave(self, ix: discord.Interaction):
        db  = load_missions()
        m   = db.get(self.mid)
        if not m:
            await ix.response.send_message("ไม่พบภารกิจ", ephemeral=True)
            return
        uid = str(self.uid)
        players = m.get("players", [])
        if uid in players:
            players.remove(uid)
        save_missions(db)
        if ix.guild:
            await _refresh_notif(ix.guild, self.mid, m)
        self.clear_items()
        max_p = m.get("max_players", 0)
        full  = (max_p > 0 and len(players) >= max_p)
        join_btn = discord.ui.Button(
            label="✅ เข้าร่วม",
            style=discord.ButtonStyle.green,
            custom_id="md_join",
            disabled=False,
            row=0,
        )
        join_btn.callback = self._join
        self.add_item(join_btn)
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"🚪 ออกจากภารกิจ **{m.get('title','?')}** แล้ว",
                color=discord.Color.orange(),
            ),
            view=self,
        )


@bot.tree.command(name="ภารกิจ", description="ดูภารกิจที่เปิดรับและเข้าร่วม", guild=_ORION_GUILD_OBJ)
async def cmd_missions(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    ensure_orion_player(str(ix.user.id))
    db     = load_missions()
    active = [m for m in db.values() if m.get("status") == "open"]
    if not active:
        await ix.response.send_message(
            embed=discord.Embed(
                description="ยังไม่มีภารกิจที่เปิดรับในขณะนี้ 📭",
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )
        return
    await ix.response.send_message(
        view=_MissionListView(ix.user.id),
        ephemeral=True,
    )


# ═════════════════════════════════════════════════════════════
# /ภารกิจแอดมิน — Admin command
# ═════════════════════════════════════════════════════════════

class _MissionAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.sel_mid: str | None = None
        self._build()

    def _build(self):
        self.clear_items()
        db       = load_missions()
        missions = db  # top-level dict is {mid: mission}

        opts = (
            [discord.SelectOption(
                label=f"{DIFF_EMOJIS.get(m.get('difficulty','E'),'⬜')} {m.get('title','?')[:85]} [{m.get('status','open')}]",
                value=mid,
                default=(mid == self.sel_mid),
            ) for mid, m in list(missions.items())[:25]]
            or [discord.SelectOption(label="(ยังไม่มีภารกิจ)", value="__none__")]
        )
        sel = discord.ui.Select(placeholder="เลือกภารกิจ", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)

        if self.sel_mid and self.sel_mid in missions:
            complete_btn = discord.ui.Button(
                label="✅ สำเร็จ", style=discord.ButtonStyle.green,
                custom_id="ma_complete", row=1,
            )
            cancel_btn = discord.ui.Button(
                label="❌ ยกเลิก", style=discord.ButtonStyle.danger,
                custom_id="ma_cancel", row=1,
            )
            items_btn = discord.ui.Button(
                label="🎁 รางวัลไอเทม", style=discord.ButtonStyle.secondary,
                custom_id="ma_items", row=1,
            )
            del_btn = discord.ui.Button(
                label="🗑️ ลบ", style=discord.ButtonStyle.danger,
                custom_id="ma_del", row=2,
            )
            complete_btn.callback = self._complete
            cancel_btn.callback   = self._cancel
            items_btn.callback    = self._edit_items
            del_btn.callback      = self._delete
            for b in (complete_btn, cancel_btn, items_btn, del_btn):
                self.add_item(b)

        create_btn  = discord.ui.Button(
            label="➕ สร้างภารกิจ", style=discord.ButtonStyle.green,
            custom_id="ma_new", row=3,
        )
        config_btn  = discord.ui.Button(
            label="⚙️ ตั้งค่า", style=discord.ButtonStyle.secondary,
            custom_id="ma_cfg", row=3,
        )
        done_btn    = discord.ui.Button(
            label="❌ ปิด", style=discord.ButtonStyle.secondary,
            custom_id="ma_done", row=3,
        )
        create_btn.callback = self._create
        config_btn.callback = self._config
        done_btn.callback   = self._done
        self.add_item(create_btn)
        self.add_item(config_btn)
        self.add_item(done_btn)

    async def _sel(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        self.sel_mid = v if v != "__none__" else None
        self._build()
        await ix.response.edit_message(view=self)

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(_CreateMissionModal(self))

    async def _complete(self, ix: discord.Interaction):
        db = load_missions()
        m  = db.get(self.sel_mid)
        if not m:
            await ix.response.send_message("ไม่พบภารกิจ", ephemeral=True)
            return
        m["status"] = "completed"
        save_missions(db)
        if ix.guild:
            await _distribute_rewards(ix.guild, m)
            await _refresh_notif(ix.guild, self.sel_mid, m)
        self._build()
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"✅ ภารกิจ **{m.get('title','?')}** สำเร็จแล้ว รางวัลถูกแจกจ่ายแล้ว",
                color=discord.Color.green(),
            ),
            view=self,
        )

    async def _cancel(self, ix: discord.Interaction):
        db = load_missions()
        m  = db.get(self.sel_mid)
        if not m:
            await ix.response.send_message("ไม่พบภารกิจ", ephemeral=True)
            return
        m["status"] = "cancelled"
        save_missions(db)
        if ix.guild:
            await _refresh_notif(ix.guild, self.sel_mid, m)
        self._build()
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"❌ ภารกิจ **{m.get('title','?')}** ถูกยกเลิกแล้ว",
                color=discord.Color.red(),
            ),
            view=self,
        )

    async def _edit_items(self, ix: discord.Interaction):
        view = _RewardItemsView(self.sel_mid, self)
        await ix.response.edit_message(embed=view._info_embed(), view=view)

    async def _delete(self, ix: discord.Interaction):
        db = load_missions()
        db.pop(self.sel_mid, None)
        save_missions(db)
        self.sel_mid = None
        self._build()
        await ix.response.edit_message(
            embed=discord.Embed(
                description="🗑️ ลบภารกิจแล้ว",
                color=discord.Color.orange(),
            ),
            view=self,
        )

    async def _config(self, ix: discord.Interaction):
        await ix.response.edit_message(view=_MissionConfigView(self))

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        await ix.response.edit_message(content="*ปิดแล้ว*", view=self)


class _CreateMissionModal(discord.ui.Modal, title="➕ สร้างภารกิจใหม่"):
    f_title   = discord.ui.TextInput(label="ชื่อภารกิจ",                            max_length=80)
    f_desc    = discord.ui.TextInput(label="คำอธิบาย",    style=discord.TextStyle.paragraph,
                                     max_length=500, required=False)
    f_diff    = discord.ui.TextInput(label="ระดับ (E/D/C/B/A/S/EX)",                max_length=2,  default="E")
    f_maxp    = discord.ui.TextInput(label="จำนวนผู้เล่นสูงสุด (0=ไม่จำกัด)",      max_length=4,  default="0")
    f_money   = discord.ui.TextInput(label="รางวัลเงิน",                             max_length=10, default="0")

    def __init__(self, parent: "_MissionAdminView"):
        super().__init__()
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        diff = self.f_diff.value.strip().upper()
        if diff not in DIFF_EMOJIS:
            diff = "E"
        try:
            max_p = max(0, int(self.f_maxp.value.strip()))
        except ValueError:
            max_p = 0
        try:
            money = max(0, int(self.f_money.value.strip()))
        except ValueError:
            money = 0

        mid = str(uuid.uuid4())[:8]
        db  = load_missions()
        db[mid] = {
            "title":          self.f_title.value.strip(),
            "description":    (self.f_desc.value or "").strip(),
            "difficulty":     diff,
            "max_players":    max_p,
            "players":        [],
            "reward_money":   money,
            "reward_items":   [],
            "status":         "open",
            "created_by":     str(ix.user.id),
            "created_at":     time.time(),
            "image_url":      "",
            "notif_messages": {},
        }
        save_missions(db)

        # Post to board channels
        if ix.guild:
            notif = await _post_notif(ix.guild, mid, db[mid])
            if notif:
                db[mid]["notif_messages"] = notif
                save_missions(db)

        self.parent.sel_mid = mid
        self.parent._build()
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(
            embed=discord.Embed(
                description=f"✅ สร้างภารกิจ **{self.f_title.value.strip()}** แล้ว (ID: `{mid}`)",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class _RewardItemsView(discord.ui.View):
    def __init__(self, mid: str, parent: _MissionAdminView):
        super().__init__(timeout=300)
        self.mid    = mid
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        catalog = load_items_catalog()
        items   = list(catalog.items())[:25]

        if not items:
            noop = discord.ui.Button(
                label="ยังไม่มีไอเทมใน catalog",
                style=discord.ButtonStyle.secondary,
                custom_id="ri_noop", disabled=True, row=0,
            )
            bk = discord.ui.Button(
                label="◀ กลับ", style=discord.ButtonStyle.secondary,
                custom_id="ri_bk", row=1,
            )
            bk.callback = self._back
            self.add_item(noop)
            self.add_item(bk)
            return

        opts = [discord.SelectOption(
            label=f"{v.get('emoji','📦')} {v.get('name', k)[:80]}",
            value=k,
        ) for k, v in items]

        sel_add = discord.ui.Select(placeholder="➕ เพิ่มไอเทมรางวัล", options=opts, row=0)
        sel_add.callback = self._add_item

        clr_btn = discord.ui.Button(
            label="🗑️ ล้างรางวัลไอเทม", style=discord.ButtonStyle.danger,
            custom_id="ri_clr", row=1,
        )
        bk_btn = discord.ui.Button(
            label="◀ กลับ", style=discord.ButtonStyle.secondary,
            custom_id="ri_bk", row=1,
        )
        clr_btn.callback = self._clear
        bk_btn.callback  = self._back
        self.add_item(sel_add)
        self.add_item(clr_btn)
        self.add_item(bk_btn)

    def _info_embed(self) -> discord.Embed:
        db      = load_missions()
        m       = db.get(self.mid, {})
        catalog = load_items_catalog()

        def _fmt(lst: list) -> str:
            if not lst:
                return "—"
            lines = []
            for r in lst:
                item  = catalog.get(r.get("item_id", ""), {})
                emoji = item.get("emoji", "📦")
                name  = item.get("name", r.get("item_id", "?"))
                lines.append(f"{emoji} **{name}** ×{r.get('qty', 1)}")
            return "\n".join(lines)

        embed = discord.Embed(
            title=f"🎁 รางวัลไอเทม — {m.get('title', '?')}",
            color=discord.Color.purple(),
        )
        embed.add_field(name="ไอเทมรางวัล", value=_fmt(m.get("reward_items", [])), inline=False)
        embed.set_footer(text="qty เริ่มต้นที่ 1")
        return embed

    async def _add_item(self, ix: discord.Interaction):
        iid = ix.data["values"][0]
        db  = load_missions()
        m   = db.get(self.mid, {})
        lst = m.setdefault("reward_items", [])
        if not any(r.get("item_id") == iid for r in lst):
            lst.append({"item_id": iid, "qty": 1})
        save_missions(db)
        await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _clear(self, ix: discord.Interaction):
        db = load_missions()
        if self.mid in db:
            db[self.mid]["reward_items"] = []
        save_missions(db)
        await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=None, view=self.parent)


class _MissionConfigView(discord.ui.View):
    def __init__(self, parent: _MissionAdminView):
        super().__init__(timeout=300)
        self.parent = parent

        ch_sel = discord.ui.ChannelSelect(
            placeholder="เลือกห้องบอร์ดภารกิจ (multi-select)",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=25,
            row=0,
        )
        ch_sel.callback = self._pick_channels

        done_btn = discord.ui.Button(
            label="❌ ปิด", style=discord.ButtonStyle.secondary,
            custom_id="mcfg_done", row=1,
        )
        done_btn.callback = self._done

        self.add_item(ch_sel)
        self.add_item(done_btn)

    async def _pick_channels(self, ix: discord.Interaction):
        cfg = load_missions_config()
        cfg["board_channel_ids"] = [str(v) for v in ix.data["values"]]
        save_missions_config(cfg)
        await ix.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ ตั้งค่าห้องบอร์ดภารกิจแล้ว: "
                    + (", ".join(f"<#{v}>" for v in ix.data["values"]) or "*(ไม่มี)*")
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    async def _done(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


@bot.tree.command(name="ภารกิจแอดมิน", description="[Admin] จัดการระบบภารกิจ", guild=_ORION_GUILD_OBJ)
async def cmd_missions_admin(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    if not _is_admin(ix.user):
        await ix.response.send_message("❌ เฉพาะ Admin เท่านั้น", ephemeral=True)
        return
    await ix.response.send_message(view=_MissionAdminView(), ephemeral=True)
