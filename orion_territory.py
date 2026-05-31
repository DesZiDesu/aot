# ============================================================
# ORION — Territory / Guild War System
# ============================================================
# - Admin สร้าง zones
# - Guild ยึดเขตได้ (owner_guild_id)
# - Player ใน guild ขอสงครามชิงเขต
# - Admin judge: win/lose/draw + มอบ rewards
# - แพ้ → block ขอสงครามชั่วคราว
# ============================================================

import sys
import time
import uuid as _uuid
import datetime
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_territory ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_orion_players   = _orion_bot_mod.load_orion_players
load_currency_cfg    = _orion_bot_mod.load_currency_cfg
money_str            = _orion_bot_mod.money_str
add_money            = _orion_bot_mod.add_money
_parse_int           = _orion_bot_mod._parse_int
make_menu_embed      = _orion_bot_mod.make_menu_embed
get_player_guild     = _orion_bot_mod.get_player_guild
load_guilds          = _orion_bot_mod.load_guilds
grant_skill_slot     = _orion_bot_mod.grant_skill_slot

import orion_items


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


TERRITORY_FILE = f"{ORION_DATA_DIR}/territories.json"

DEFAULT_TERRITORY = {
    "zones": [],
    "wars": [],
    "war_blocks": {},   # guild_id → unblock timestamp
    "config": {
        "block_duration_sec": 24 * 3600,  # 1 day
    },
}


def load_territory() -> dict:
    data = load_json(TERRITORY_FILE, None)
    if not data:
        data = dict(DEFAULT_TERRITORY)
        data["zones"] = []
        data["wars"] = []
        data["war_blocks"] = {}
        data["config"] = dict(DEFAULT_TERRITORY["config"])
        save_territory(data)
    # backfill missing keys
    for k, v in DEFAULT_TERRITORY.items():
        if k not in data:
            data[k] = v
    if "config" not in data:
        data["config"] = dict(DEFAULT_TERRITORY["config"])
    return data


def save_territory(d: dict):
    save_json(TERRITORY_FILE, d)


def _get_zone(zid: str):
    data = load_territory()
    return next((z for z in data.get("zones", []) if z["id"] == zid), None)


def _is_blocked(gid: str) -> int:
    """คืน seconds ที่ยังถูก block — 0 ถ้าไม่บล็อก"""
    data = load_territory()
    blocks = data.get("war_blocks", {})
    end = int(blocks.get(gid, 0))
    return max(0, end - int(time.time()))


# ── Embeds ──────────────────────────────────────────────────
def _zones_embed() -> discord.Embed:
    data = load_territory()
    zones = data.get("zones", [])
    guilds = load_guilds()
    sections = [f"_เขตทั้งหมด_  `{len(zones)}` _เขต_"]
    for z in zones[:15]:
        owner_gid = z.get("owner_guild_id", "")
        owner_name = guilds.get(owner_gid, {}).get("name", "—") if owner_gid else "_(ไม่มีเจ้าของ)_"
        sections.append((
            f"{z.get('emoji','🗺️')} {z.get('name','?')}",
            f"{z.get('description','')[:120]}\n_เจ้าของ:_ **{owner_name}**"
        ))
    return make_menu_embed("Territory", sections, color=0x16a085)


# ── Player flow ──────────────────────────────────────────────
class ZoneViewSelect(discord.ui.Select):
    def __init__(self):
        data = load_territory()
        guilds = load_guilds()
        zones = data.get("zones", [])[:25]
        options = []
        for z in zones:
            owner_gid = z.get("owner_guild_id", "")
            owner_name = guilds.get(owner_gid, {}).get("name", "—") if owner_gid else "—"
            options.append(discord.SelectOption(
                label=z.get("name","?")[:100],
                value=z["id"],
                description=f"เจ้าของ: {owner_name}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีเขต", value="none")]
        super().__init__(placeholder="เลือกเขต...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        z = _get_zone(self.values[0])
        if not z:
            await ix.response.send_message("❌ ไม่พบเขต", ephemeral=True); return
        guilds = load_guilds()
        owner_gid = z.get("owner_guild_id", "")
        owner_name = guilds.get(owner_gid, {}).get("name", "—") if owner_gid else "_(ไม่มีเจ้าของ)_"
        embed = discord.Embed(
            title=f"{z.get('emoji','🗺️')} {z.get('name','?')}",
            description=z.get("description") or "_ไม่มีคำอธิบาย_",
            color=0x16a085,
        )
        embed.add_field(name="เจ้าของ", value=f"**{owner_name}**", inline=True)
        embed.add_field(name="Zone ID", value=f"`{z['id']}`", inline=True)
        if z.get("icon_url"):
            embed.set_thumbnail(url=z["icon_url"])
        # ผู้เล่นใน guild → declare war button
        uid = str(ix.user.id)
        info = get_player_guild(uid)
        view = None
        if info:
            gid, _ = info
            block_left = _is_blocked(gid)
            if owner_gid != gid and block_left == 0:
                view = WarDeclareView(z["id"], gid)
            elif block_left > 0:
                embed.add_field(name="สถานะ", value=f"⛔ กิลด์ของคุณถูกบล็อกอีก `{block_left//60}` นาที", inline=False)
        await ix.response.send_message(embed=embed, view=view, ephemeral=False)


class WarDeclareView(discord.ui.View):
    def __init__(self, zone_id: str, challenger_gid: str):
        super().__init__(timeout=180)
        self.zone_id = zone_id
        self.challenger_gid = challenger_gid

    @discord.ui.button(label="ขอสงคราม", style=discord.ButtonStyle.danger, row=1)
    async def b_war(self, ix, _b):
        data = load_territory()
        z = next((x for x in data.get("zones", []) if x["id"] == self.zone_id), None)
        if not z:
            await ix.response.send_message("❌ ไม่พบเขต", ephemeral=True); return
        defender_gid = z.get("owner_guild_id", "")
        # check existing
        for w in data.get("wars", []):
            if w["zone_id"] == self.zone_id and w["status"] == "pending":
                await ix.response.send_message("❌ มีสงครามค้างของเขตนี้อยู่แล้ว", ephemeral=True); return
        wid = _uuid.uuid4().hex[:8]
        data.setdefault("wars", []).append({
            "id": wid,
            "zone_id": self.zone_id,
            "challenger_guild_id": self.challenger_gid,
            "defender_guild_id": defender_gid,
            "challenger_id": str(ix.user.id),
            "status": "pending",
            "started_at": int(time.time()),
        })
        save_territory(data)
        guilds = load_guilds()
        ch_name = guilds.get(self.challenger_gid, {}).get("name", "?")
        de_name = guilds.get(defender_gid, {}).get("name", "—") if defender_gid else "_(ไม่มีเจ้าของ)_"
        embed = discord.Embed(
            title="⚔️ ประกาศสงครามแย่งเขต",
            description=(
                f"**เขต:** {z.get('emoji','🗺️')} {z.get('name','?')}\n"
                f"**ผู้ท้า:** {ch_name} ({ix.user.mention})\n"
                f"**ฝ่ายตั้งรับ:** {de_name}\n\n"
                f"_รอแอดมินตัดสิน ผ่าน `/สงคราม`_"
            ),
            color=0xe74c3c,
        )
        embed.set_footer(text=f"War ID: {wid}")
        await ix.response.send_message(embed=embed, ephemeral=False)


# ── Admin: Zones CRUD ────────────────────────────────────────
class ZoneAddModal(discord.ui.Modal, title="เพิ่มเขต"):
    f_id   = discord.ui.TextInput(label="Zone ID (a-z,_)", placeholder="north_forest", max_length=40)
    f_name = discord.ui.TextInput(label="ชื่อเขต", max_length=60)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)

    async def on_submit(self, ix):
        zid = self.f_id.value.strip().lower().replace(" ", "_")
        data = load_territory()
        if any(z["id"] == zid for z in data.get("zones", [])):
            await ix.response.send_message(f"❌ มี `{zid}` แล้ว", ephemeral=True); return
        data.setdefault("zones", []).append({
            "id": zid,
            "name": self.f_name.value.strip(),
            "emoji": "🗺️",
            "icon_url": "",
            "description": (self.f_desc.value or "").strip(),
            "owner_guild_id": "",
        })
        save_territory(data)
        await ix.response.send_message(f"✅ เพิ่มเขต `{zid}` แล้ว", ephemeral=True)


class ZoneAdminSelect(discord.ui.Select):
    def __init__(self, action: str):
        self.action = action
        zones = load_territory().get("zones", [])[:25]
        options = []
        for z in zones:
            options.append(discord.SelectOption(
                label=z.get("name","?")[:100],
                value=z["id"],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีเขต", value="none")]
        super().__init__(placeholder=f"เลือกเขต...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        zid = self.values[0]
        if self.action == "delete":
            data = load_territory()
            data["zones"] = [z for z in data.get("zones", []) if z["id"] != zid]
            save_territory(data)
            await ix.response.edit_message(content=f"ลบเขต `{zid}` แล้ว", view=None)
        elif self.action == "set_owner":
            await ix.response.send_modal(SetOwnerModal(zid))


class SetOwnerModal(discord.ui.Modal, title="ตั้งเจ้าของเขต (Guild ID)"):
    f_gid = discord.ui.TextInput(label="Guild ID (เว้นว่าง = ไม่มีเจ้าของ)", required=False, max_length=20)

    def __init__(self, zid: str):
        super().__init__()
        self.zid = zid

    async def on_submit(self, ix):
        data = load_territory()
        z = next((x for x in data.get("zones", []) if x["id"] == self.zid), None)
        if not z:
            await ix.response.send_message("❌ ไม่พบเขต", ephemeral=True); return
        gid = (self.f_gid.value or "").strip()
        z["owner_guild_id"] = gid
        save_territory(data)
        guilds = load_guilds()
        owner_name = guilds.get(gid, {}).get("name", "—") if gid else "_(ไม่มี)_"
        await ix.response.send_message(f"✅ ตั้งเจ้าของเขต `{self.zid}` = **{owner_name}**", ephemeral=True)


# ── War judging ──────────────────────────────────────────────
class WarJudgeSelect(discord.ui.Select):
    def __init__(self):
        wars = [w for w in load_territory().get("wars", []) if w["status"] == "pending"][:25]
        guilds = load_guilds()
        options = []
        for w in wars:
            zone = _get_zone(w["zone_id"]) or {}
            ch = guilds.get(w["challenger_guild_id"], {}).get("name", "?")
            options.append(discord.SelectOption(
                label=f"{zone.get('name','?')} ← {ch}"[:100],
                value=w["id"],
                description=f"War {w['id']}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสงครามค้าง", value="none")]
        super().__init__(placeholder="เลือกสงคราม...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        wid = self.values[0]
        data = load_territory()
        w = next((x for x in data.get("wars", []) if x["id"] == wid), None)
        if not w:
            await ix.response.send_message("❌ ไม่พบสงคราม", ephemeral=True); return
        guilds = load_guilds()
        zone = _get_zone(w["zone_id"]) or {}
        ch_name = guilds.get(w["challenger_guild_id"], {}).get("name", "?")
        de_name = guilds.get(w["defender_guild_id"], {}).get("name", "—") if w.get("defender_guild_id") else "_(ไม่มีเจ้าของ)_"
        embed = discord.Embed(
            title=f"⚔️ ตัดสินสงคราม — {zone.get('name','?')}",
            description=(
                f"**ผู้ท้า:** {ch_name}\n"
                f"**ฝ่ายตั้งรับ:** {de_name}\n"
                f"**War ID:** `{wid}`\n\n"
                f"_เลือกผลการตัดสินด้านล่าง_"
            ),
            color=0xe74c3c,
        )
        await ix.response.send_message(embed=embed, view=WarVerdictView(wid), ephemeral=True)


class WarVerdictView(discord.ui.View):
    def __init__(self, wid: str):
        super().__init__(timeout=300)
        self.wid = wid

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    async def _resolve(self, ix, result: str):
        data = load_territory()
        w = next((x for x in data.get("wars", []) if x["id"] == self.wid), None)
        if not w or w["status"] != "pending":
            await ix.response.send_message("❌ ปิดไปแล้ว", ephemeral=True); return
        guilds = load_guilds()
        zone = _get_zone(w["zone_id"])
        if not zone:
            await ix.response.send_message("❌ เขตหายไป", ephemeral=True); return
        cfg = data.get("config", {})
        block_dur = int(cfg.get("block_duration_sec", 86400))
        winner_name = "—"
        if result == "challenger_wins":
            # โอนเขตให้ challenger
            for z in data["zones"]:
                if z["id"] == w["zone_id"]:
                    z["owner_guild_id"] = w["challenger_guild_id"]
                    break
            # block defender จาก war
            if w.get("defender_guild_id"):
                data.setdefault("war_blocks", {})[w["defender_guild_id"]] = int(time.time()) + block_dur
            winner_name = guilds.get(w["challenger_guild_id"], {}).get("name", "?")
        elif result == "defender_wins":
            # block challenger จาก war
            data.setdefault("war_blocks", {})[w["challenger_guild_id"]] = int(time.time()) + block_dur
            winner_name = guilds.get(w.get("defender_guild_id",""), {}).get("name", "ฝ่ายตั้งรับ")
        # draw: ไม่ทำอะไร, war void
        w["status"] = "resolved"
        w["result"] = result
        w["resolved_at"] = int(time.time())
        save_territory(data)
        # Verdict message
        verdict_map = {
            "challenger_wins": f"🏆 **ผู้ท้าชนะ** — เขต **{zone.get('name','?')}** ตกเป็นของ **{winner_name}**",
            "defender_wins":   f"🛡️ **ฝ่ายตั้งรับชนะ** — เขต **{zone.get('name','?')}** ยังเป็นของ **{winner_name}**",
            "draw":            f"🤝 **เสมอ** — สงครามถูกล้าง ไม่มีใครได้อะไร (war void)",
        }
        verdict = verdict_map.get(result, "?")
        await ix.response.send_message(
            content=verdict + (
                f"\n\n_แอดมินสามารถมอบรางวัลเพิ่มเติม:_ `/สงครามรางวัล war_id:{self.wid}`"
                if result == "challenger_wins" else ""
            ),
            embed=None, view=None,
            ephemeral=False,
        )

    @discord.ui.button(label="ผู้ท้าชนะ", style=discord.ButtonStyle.success, row=1)
    async def b_ch(self, ix, _b): await self._resolve(ix, "challenger_wins")

    @discord.ui.button(label="ฝ่ายตั้งรับชนะ", style=discord.ButtonStyle.primary, row=2)
    async def b_de(self, ix, _b): await self._resolve(ix, "defender_wins")

    @discord.ui.button(label="เสมอ (void)", style=discord.ButtonStyle.secondary, row=3)
    async def b_d(self, ix, _b): await self._resolve(ix, "draw")


# ── Reward distribution to winning guild ─────────────────────
class RewardView(discord.ui.View):
    def __init__(self, war_id: str):
        super().__init__(timeout=300)
        self.war_id = war_id

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ให้เงิน", style=discord.ButtonStyle.success, row=1)
    async def b_money(self, ix, _b):
        await ix.response.send_modal(RewardMoneyModal(self.war_id))

    @discord.ui.button(label="ให้ไอเทมจาก catalog", style=discord.ButtonStyle.primary, row=2)
    async def b_item(self, ix, _b):
        await ix.response.send_modal(RewardItemModal(self.war_id))

    @discord.ui.button(label="ให้สิทธิ์สร้างสกิล", style=discord.ButtonStyle.primary, row=3)
    async def b_skill(self, ix, _b):
        await ix.response.send_modal(RewardSkillGrantModal(self.war_id))

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=4)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓ ปิดเมนูรางวัล", embed=None, view=None)


def _winner_members(war_id: str) -> list:
    data = load_territory()
    w = next((x for x in data.get("wars", []) if x["id"] == war_id), None)
    if not w or w.get("result") != "challenger_wins":
        return []
    winner_gid = w["challenger_guild_id"]
    g = load_guilds().get(winner_gid, {})
    return [m["uid"] for m in g.get("members", [])]


class RewardMoneyModal(discord.ui.Modal, title="ให้เงินกิลด์ผู้ชนะ"):
    f_amt = discord.ui.TextInput(label="จำนวน/คน", placeholder="500", max_length=10)

    def __init__(self, war_id: str):
        super().__init__()
        self.war_id = war_id

    async def on_submit(self, ix):
        members = _winner_members(self.war_id)
        if not members:
            await ix.response.send_message("❌ ไม่มีสมาชิกผู้ชนะ", ephemeral=True); return
        amt = max(0, _parse_int(self.f_amt.value, 0) or 0)
        for uid in members:
            add_money(uid, amt)
        await ix.response.send_message(
            f"✅ ให้ {money_str(amt)} กับ {len(members)} คน · รวม {money_str(amt*len(members))}",
            ephemeral=False,
        )


class RewardItemModal(discord.ui.Modal, title="ให้ไอเทมจาก catalog"):
    f_iid = discord.ui.TextInput(label="Item ID", placeholder="stone", max_length=80)
    f_qty = discord.ui.TextInput(label="จำนวน/คน", placeholder="1", max_length=5)

    def __init__(self, war_id: str):
        super().__init__()
        self.war_id = war_id

    async def on_submit(self, ix):
        members = _winner_members(self.war_id)
        if not members:
            await ix.response.send_message("❌ ไม่มีสมาชิกผู้ชนะ", ephemeral=True); return
        iid = self.f_iid.value.strip()
        if iid not in orion_items.load_items_catalog():
            await ix.response.send_message(f"❌ ไม่มี `{iid}` ใน catalog", ephemeral=True); return
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        for uid in members:
            orion_items.add_player_item(uid, iid, qty)
        item = orion_items.get_item(iid)
        await ix.response.send_message(
            f"✅ ให้ {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} กับ {len(members)} คน",
            ephemeral=False,
        )


class RewardSkillGrantModal(discord.ui.Modal, title="ให้สิทธิ์สร้างสกิล"):
    f_cat = discord.ui.TextInput(label="Category ID (any = ทุกหมวด)", placeholder="any", max_length=40)
    f_qty = discord.ui.TextInput(label="จำนวน/คน", placeholder="1", max_length=5)

    def __init__(self, war_id: str):
        super().__init__()
        self.war_id = war_id

    async def on_submit(self, ix):
        members = _winner_members(self.war_id)
        if not members:
            await ix.response.send_message("❌ ไม่มีสมาชิกผู้ชนะ", ephemeral=True); return
        cid = (self.f_cat.value or "any").strip()
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        for uid in members:
            grant_skill_slot(uid, cid, qty)
        await ix.response.send_message(
            f"✅ ให้สิทธิ์สร้างสกิล ×{qty} (หมวด `{cid}`) กับ {len(members)} คน",
            ephemeral=False,
        )


# ── Admin Views ──────────────────────────────────────────────
class TerritoryAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="เพิ่มเขต", style=discord.ButtonStyle.success, row=1)
    async def b_add(self, ix, _b):
        await ix.response.send_modal(ZoneAddModal())

    @discord.ui.button(label="ลบเขต", style=discord.ButtonStyle.danger, row=2)
    async def b_del(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(ZoneAdminSelect("delete"))
        await ix.response.send_message("เลือกเขต ↓", view=v, ephemeral=True)

    @discord.ui.button(label="ตั้งเจ้าของเขต", style=discord.ButtonStyle.primary, row=3)
    async def b_set(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(ZoneAdminSelect("set_owner"))
        await ix.response.send_message("เลือกเขต ↓", view=v, ephemeral=True)

    @discord.ui.button(label="ตั้งระยะเวลา block", style=discord.ButtonStyle.secondary, row=4)
    async def b_cd(self, ix, _b):
        await ix.response.send_modal(BlockConfigModal())


class BlockConfigModal(discord.ui.Modal, title="ตั้งระยะเวลา block สงคราม"):
    f_sec = discord.ui.TextInput(label="วินาที (default 86400 = 1 วัน)", placeholder="86400", max_length=10)

    def __init__(self):
        super().__init__()
        data = load_territory()
        self.f_sec.default = str(data.get("config", {}).get("block_duration_sec", 86400))

    async def on_submit(self, ix):
        sec = max(60, _parse_int(self.f_sec.value, 86400) or 86400)
        data = load_territory()
        data.setdefault("config", {})["block_duration_sec"] = sec
        save_territory(data)
        await ix.response.send_message(f"✅ ตั้ง block duration = {sec} วินาที", ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="พื้นที่", description="ดูเขตในระบบ + เจ้าของ", guild=_ORION_GUILD_OBJ)
async def cmd_territory(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    view = discord.ui.View(timeout=300)
    view.add_item(ZoneViewSelect())
    await interaction.response.send_message(embed=_zones_embed(), view=view, ephemeral=_eph("พื้นที่"))


@bot.tree.command(name="สงคราม", description="[Admin] ตัดสินสงครามที่ค้างอยู่", guild=_ORION_GUILD_OBJ)
async def cmd_wars(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    pending = [w for w in load_territory().get("wars", []) if w["status"] == "pending"]
    embed = make_menu_embed(
        "สงครามที่ค้างอยู่",
        [f"_ค้างรอตัดสิน_  `{len(pending)}` _สงคราม_"],
        color=0xe74c3c,
    )
    view = discord.ui.View(timeout=300)
    view.add_item(WarJudgeSelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="สงครามรางวัล", description="[Admin] มอบรางวัลให้กิลด์ผู้ชนะสงคราม", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(war_id="War ID จาก /สงคราม")
async def cmd_war_reward(interaction: discord.Interaction, war_id: str):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    members = _winner_members(war_id)
    if not members:
        await interaction.response.send_message("❌ ไม่พบสงครามที่ challenger ชนะ", ephemeral=True); return
    embed = make_menu_embed(
        f"มอบรางวัล War `{war_id}`",
        [
            f"_สมาชิกผู้ชนะ_  `{len(members)}` _คน_",
            ("ให้เงิน", "แจกเงินคนละเท่ากัน"),
            ("ให้ไอเทมจาก catalog", "เลือก item_id + จำนวน/คน"),
            ("ให้สิทธิ์สร้างสกิล", "ระบุหมวด (any = ทุกหมวด) + จำนวน/คน"),
        ],
        color=0xf1c40f,
    )
    await interaction.response.send_message(embed=embed, view=RewardView(war_id), ephemeral=True)


@bot.tree.command(name="พื้นที่แอดมิน", description="[Admin] จัดการเขต + ตั้งค่า", guild=_ORION_GUILD_OBJ)
async def cmd_territory_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    data = load_territory()
    embed = make_menu_embed(
        "Territory Admin",
        [
            f"_เขต_  `{len(data.get('zones',[]))}`  ·  _สงครามค้าง_  `{len([w for w in data.get('wars',[]) if w['status']=='pending'])}`",
            ("เพิ่มเขต", "สร้างเขตใหม่ — ตั้งชื่อ + ID + คำอธิบาย"),
            ("ลบเขต", "ลบเขตออกจากแผนที่"),
            ("ตั้งเจ้าของเขต", "ใส่ Guild ID เพื่อมอบเขตให้กิลด์"),
            ("ตั้งระยะเวลา block", "ระยะเวลาที่ฝ่ายแพ้ถูกบล็อกจากการขอสงคราม"),
            ("ตัดสินสงคราม", "ใช้ `/สงคราม` แยก"),
        ],
        color=0x16a085,
    )
    await interaction.response.send_message(embed=embed, view=TerritoryAdminView(), ephemeral=True)
