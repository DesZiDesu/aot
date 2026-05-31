# ============================================================
# ORION — Gacha System
# ============================================================
# - Admin สร้างตู้กาชา + กำหนด pool + rarity + qty range
# - Player ใช้ตั๋ว (item ใน catalog) → roll ในตู้ที่เลือก
# - JSON import/export
# ============================================================

import io
import sys
import time
import json
import random as _rand
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_gacha ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
_parse_int           = _orion_bot_mod._parse_int
make_menu_embed      = _orion_bot_mod.make_menu_embed

import orion_items


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="🎁"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


GACHA_FILE = f"{ORION_DATA_DIR}/gacha_boxes.json"

DEFAULT_GACHA = {
    "boxes": [
        {
            "id": "starter_box",
            "name": "กล่องเริ่มต้น",
            "emoji": "📦",
            "icon_url": "",
            "description": "กล่องสุ่มของเล็กๆ น้อยๆ สำหรัผู้เล่นใหม่",
            "ticket_item_id": "starter_ticket",
            "rolls_per_use": 3,
            "qty_min": 1,
            "qty_max": 2,
            "pool": [
                {"item_id": "stone", "weight": 50, "rarity": "common"},
                {"item_id": "wood",  "weight": 50, "rarity": "common"},
                {"item_id": "herb",  "weight": 20, "rarity": "uncommon"},
                {"item_id": "iron_ore", "weight": 5, "rarity": "rare"},
            ],
        }
    ]
}

RARITY = {
    "common":     {"emoji": "⚪", "color": 0xbdc3c7},
    "uncommon":   {"emoji": "🟢", "color": 0x2ecc71},
    "rare":       {"emoji": "🔵", "color": 0x3498db},
    "epic":       {"emoji": "🟣", "color": 0x9b59b6},
    "legendary":  {"emoji": "🟡", "color": 0xf1c40f},
}


def load_gacha() -> dict:
    data = load_json(GACHA_FILE, None)
    if not data:
        data = json.loads(json.dumps(DEFAULT_GACHA))
        save_gacha(data)
    return data


def save_gacha(d: dict):
    save_json(GACHA_FILE, d)


def get_box(bid: str) -> dict:
    for b in load_gacha().get("boxes", []):
        if b.get("id") == bid:
            return b
    return {}


def _weighted_pick(pool: list) -> dict:
    weights = [max(1, int(p.get("weight", 1))) for p in pool]
    return _rand.choices(pool, weights=weights, k=1)[0]


# ── Embeds ────────────────────────────────────────────
def _boxes_embed(uid: str = None) -> discord.Embed:
    data = load_gacha()
    boxes = data.get("boxes", [])
    sections = [f"_ตู้กาชาในระบบ_  `{len(boxes)}` _ตู้_"]
    for b in boxes[:10]:
        ticket_iid = b.get("ticket_item_id", "")
        have = orion_items.player_qty(uid, ticket_iid) if uid else 0
        ticket_item = orion_items.get_item(ticket_iid)
        ticket_name = ticket_item.get("name", ticket_iid) if ticket_item else ticket_iid
        sections.append((
            f"{b.get('emoji','📦')} {b.get('name','?')}",
            f"{b.get('description','')[:120]}\n_ตั๋ว:_ `{ticket_name}` ({have} ใบ) · _ต่อครั้ง:_ `{b.get('rolls_per_use',1)}` ของ · `{b.get('qty_min',1)}-{b.get('qty_max',1)}` ชิ้น/ของ"
        ))
    return make_menu_embed("Gacha", sections, color=0xe91e63)


# ── Player flow ───────────────────────────────────────────
class GachaBoxSelect(discord.ui.Select):
    def __init__(self, uid: str):
        self.uid = uid
        boxes = load_gacha().get("boxes", [])[:25]
        options = []
        for b in boxes:
            have = orion_items.player_qty(uid, b.get("ticket_item_id", ""))
            options.append(discord.SelectOption(
                label=f"{b.get('name','?')} ({have} ตั๋ว)"[:100],
                value=b["id"],
                description=f"ใช้ตั๋ว → ได้ {b.get('rolls_per_use',1)} ของ"[:80],
                emoji=_safe_emoji(b.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีตู้กาชา", value="none")]
        super().__init__(placeholder="เลือกตู้กาชา...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        bid = self.values[0]
        box = get_box(bid)
        if not box:
            await ix.response.send_message("❌ ไม่พบตู้", ephemeral=True); return
        await ix.response.send_message(
            embed=_box_detail_embed(box, self.uid),
            view=GachaRollView(self.uid, bid),
            ephemeral=True,
        )


def _box_detail_embed(box: dict, uid: str) -> discord.Embed:
    cat = orion_items.load_items_catalog()
    pool_lines = []
    total_w = sum(max(1, int(p.get("weight", 1))) for p in box.get("pool", []))
    for p in box.get("pool", [])[:15]:
        it = cat.get(p["item_id"], {})
        rarity = p.get("rarity", "common")
        rmeta = RARITY.get(rarity, RARITY["common"])
        pct = max(1, int(p.get("weight",1))) * 100 // total_w
        pool_lines.append(
            f"{rmeta['emoji']} {it.get('emoji','📦')} **{it.get('name','?')}** _{rarity}_ — {pct}%"
        )
    ticket_iid = box.get("ticket_item_id", "")
    ticket_item = cat.get(ticket_iid, {})
    have = orion_items.player_qty(uid, ticket_iid)
    embed = discord.Embed(
        title=f"{box.get('emoji','📦')} {box.get('name','?')}",
        description=box.get("description") or "_ไม่มีคำอธิบาย_",
        color=0xe91e63,
    )
    if box.get("icon_url"):
        embed.set_thumbnail(url=box["icon_url"])
    embed.add_field(name="ตั๋วที่ต้องใช้", value=f"{ticket_item.get('emoji','🎟️')} {ticket_item.get('name', ticket_iid)} (มี `{have}`)", inline=True)
    embed.add_field(name="ต่อครั้ง", value=f"`{box.get('rolls_per_use',1)}` ของ", inline=True)
    embed.add_field(name="จำนวน/ของ", value=f"`{box.get('qty_min',1)}-{box.get('qty_max',1)}`", inline=True)
    embed.add_field(name="Pool", value="\n".join(pool_lines) or "_ว่าง_", inline=False)
    return embed


class GachaRollView(discord.ui.View):
    def __init__(self, uid: str, bid: str):
        super().__init__(timeout=300)
        self.uid = uid
        self.bid = bid

    async def interaction_check(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="Roll!", style=discord.ButtonStyle.success, row=1)
    async def b_roll(self, ix: discord.Interaction, _b):
        box = get_box(self.bid)
        ticket_iid = box.get("ticket_item_id", "")
        have = orion_items.player_qty(self.uid, ticket_iid)
        if have < 1:
            await ix.response.send_message(f"❌ ไม่มีตั๋ว", ephemeral=True); return
        if not box.get("pool"):
            await ix.response.send_message("❌ ตู้ว่าง", ephemeral=True); return
        # ใช้ตั๋ว 1 ใบ
        orion_items.remove_player_item(self.uid, ticket_iid, 1)
        rolls = max(1, int(box.get("rolls_per_use", 1)))
        qty_min = max(1, int(box.get("qty_min", 1)))
        qty_max = max(qty_min, int(box.get("qty_max", 1)))
        results = []
        cat = orion_items.load_items_catalog()
        max_color = 0xbdc3c7
        for _ in range(rolls):
            pick = _weighted_pick(box["pool"])
            qty = _rand.randint(qty_min, qty_max)
            orion_items.add_player_item(self.uid, pick["item_id"], qty)
            it = cat.get(pick["item_id"], {})
            rarity = pick.get("rarity", "common")
            rmeta = RARITY.get(rarity, RARITY["common"])
            if rmeta["color"] != 0xbdc3c7:
                max_color = rmeta["color"]
            results.append(f"{rmeta['emoji']} {it.get('emoji','📦')} **{it.get('name','?')}** ×{qty} _({rarity})_")
        embed = discord.Embed(
            title=f"🎉 {box.get('name','?')} — Roll Result",
            description=(
                f"{ix.user.mention} ใช้ 1 ตั๋ว → ได้ {rolls} ของ:\n\n"
                + "\n".join(results)
            ),
            color=max_color,
        )
        await ix.response.send_message(embed=embed, ephemeral=False)


# ── Admin ──────────────────────────────────────────────
class BoxAddModal(discord.ui.Modal, title="เพิ่มตู้กาชา"):
    f_id     = discord.ui.TextInput(label="Box ID (a-z,_)", placeholder="rare_box", max_length=40)
    f_name   = discord.ui.TextInput(label="ชื่อตู้", max_length=60)
    f_desc   = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)
    f_ticket = discord.ui.TextInput(label="Ticket item ID (item ใน catalog)", placeholder="rare_ticket", max_length=80)
    f_meta   = discord.ui.TextInput(label="rolls/qty_min/qty_max (3 บรรทัด)", placeholder="3\n1\n2", style=discord.TextStyle.paragraph, max_length=50)

    async def on_submit(self, ix):
        bid = self.f_id.value.strip().lower().replace(" ", "_")
        data = load_gacha()
        if any(b["id"] == bid for b in data.get("boxes", [])):
            await ix.response.send_message(f"❌ มี `{bid}` แล้ว", ephemeral=True); return
        parts = (self.f_meta.value or "1\n1\n1").split("\n")
        rolls   = max(1, _parse_int(parts[0].strip() if parts else "1", 1) or 1)
        qty_min = max(1, _parse_int(parts[1].strip() if len(parts) > 1 else "1", 1) or 1)
        qty_max = max(qty_min, _parse_int(parts[2].strip() if len(parts) > 2 else "1", 1) or 1)
        data.setdefault("boxes", []).append({
            "id": bid,
            "name": self.f_name.value.strip(),
            "emoji": "📦",
            "icon_url": "",
            "description": (self.f_desc.value or "").strip(),
            "ticket_item_id": self.f_ticket.value.strip(),
            "rolls_per_use": rolls,
            "qty_min": qty_min,
            "qty_max": qty_max,
            "pool": [],
        })
        save_gacha(data)
        await ix.response.send_message(f"✅ เพิ่มตู้ `{bid}` แล้ว — ใส่ของใน pool ผ่าน 'เพิ่ม pool entry'", ephemeral=True)


class BoxPickSelect(discord.ui.Select):
    def __init__(self, action: str):
        self.action = action
        data = load_gacha()
        boxes = data.get("boxes", [])[:25]
        options = []
        for b in boxes:
            options.append(discord.SelectOption(
                label=b.get("name","?")[:100],
                value=b["id"],
                description=f"{len(b.get('pool',[]))} pool entries"[:80],
                emoji=_safe_emoji(b.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีตู้", value="none")]
        super().__init__(placeholder="เลือกตู้...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        bid = self.values[0]
        if self.action == "delete":
            data = load_gacha()
            data["boxes"] = [b for b in data.get("boxes", []) if b["id"] != bid]
            save_gacha(data)
            await ix.response.edit_message(content=f"ลบ `{bid}`", view=None)
        elif self.action == "add_pool":
            await ix.response.send_modal(PoolEntryAddModal(bid))
        elif self.action == "view":
            box = get_box(bid)
            await ix.response.send_message(embed=_box_detail_embed(box, str(ix.user.id)), ephemeral=True)


class PoolEntryAddModal(discord.ui.Modal, title="เพิ่ม pool entry"):
    f_iid    = discord.ui.TextInput(label="Item ID (จาก catalog)", placeholder="stone", max_length=80)
    f_weight = discord.ui.TextInput(label="Weight", placeholder="10", max_length=4)
    f_rarity = discord.ui.TextInput(label="Rarity (common/uncommon/rare/epic/legendary)", placeholder="common", max_length=20)

    def __init__(self, bid: str):
        super().__init__()
        self.bid = bid

    async def on_submit(self, ix):
        iid = self.f_iid.value.strip()
        if iid not in orion_items.load_items_catalog():
            await ix.response.send_message(f"❌ ไม่มี item `{iid}` ใน catalog", ephemeral=True); return
        rarity = (self.f_rarity.value or "common").strip().lower()
        if rarity not in RARITY:
            await ix.response.send_message(f"❌ rarity ผิด", ephemeral=True); return
        weight = max(1, _parse_int(self.f_weight.value, 10) or 10)
        data = load_gacha()
        box = next((b for b in data.get("boxes", []) if b["id"] == self.bid), None)
        if not box:
            await ix.response.send_message("❌ ไม่พบตู้", ephemeral=True); return
        box.setdefault("pool", []).append({"item_id": iid, "weight": weight, "rarity": rarity})
        save_gacha(data)
        await ix.response.send_message(f"✅ เพิ่ม `{iid}` weight {weight} ({rarity}) เข้า `{self.bid}`", ephemeral=True)


class GachaAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="เพิ่มตู้กาชา", style=discord.ButtonStyle.success, row=1)
    async def b_add(self, ix, _b):
        await ix.response.send_modal(BoxAddModal())

    @discord.ui.button(label="ลบตู้", style=discord.ButtonStyle.danger, row=2)
    async def b_del(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(BoxPickSelect("delete"))
        await ix.response.send_message("เลือกตู้ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="เพิ่ม pool entry", style=discord.ButtonStyle.primary, row=3)
    async def b_pool(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(BoxPickSelect("add_pool"))
        await ix.response.send_message("เลือกตู้ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="ดูตู้/pool", style=discord.ButtonStyle.secondary, row=4)
    async def b_view(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(BoxPickSelect("view"))
        await ix.response.send_message("เลือกตู้ ↓", view=v, ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="กาชา", description="เปิดตู้กาชา — ใช้ตั๋วเพื่อสุ่มของ", guild=_ORION_GUILD_OBJ)
async def cmd_gacha(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    view = discord.ui.View(timeout=300)
    view.add_item(GachaBoxSelect(uid))
    await interaction.response.send_message(
        embed=_boxes_embed(uid),
        view=view,
        ephemeral=_eph("กาชา"),
    )


@bot.tree.command(name="กาชาแอดมิน", description="[Admin] จัดการตู้กาชา", guild=_ORION_GUILD_OBJ)
async def cmd_gacha_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    data = load_gacha()
    embed = make_menu_embed(
        "Gacha Admin",
        [
            f"_ตู้ในระบบ_  `{len(data.get('boxes',[]))}` _ตู้_",
            ("เพิ่ม/ลบ ตู้", "สร้างตู้ใหม่ + ตั้งตั๋ว + rolls + qty range"),
            ("เพิ่ม pool entry", "เพิ่มไอเทมเข้า pool ของตู้ พร้อม weight + rarity"),
            ("JSON I/O", "`/กาชาดาวน์โหลด` ดาวน์โหลด · `/กาชาอัปโหลด` อัปกลับ"),
        ],
        color=0xe91e63,
    )
    await interaction.response.send_message(embed=embed, view=GachaAdminView(), ephemeral=True)


@bot.tree.command(name="กาชาดาวน์โหลด", description="[Admin] ดาวน์โหลด gacha_boxes.json", guild=_ORION_GUILD_OBJ)
async def cmd_gacha_dl(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    s = json.dumps(load_gacha(), ensure_ascii=False, indent=2)
    file = discord.File(io.BytesIO(s.encode("utf-8")), filename="gacha_boxes.json")
    await interaction.response.send_message("📥 ไฟล์ตู้กาชา", file=file, ephemeral=True)


@bot.tree.command(name="กาชาอัปโหลด", description="[Admin] อัปโหลด gacha_boxes.json (replace)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(file="ไฟล์ gacha_boxes.json")
async def cmd_gacha_ul(interaction: discord.Interaction, file: discord.Attachment):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    if not file.filename.lower().endswith(".json"):
        await interaction.response.send_message("❌ ต้องเป็น .json", ephemeral=True); return
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        await interaction.response.send_message(f"❌ JSON error: `{e}`", ephemeral=True); return
    if not isinstance(data, dict) or "boxes" not in data:
        await interaction.response.send_message("❌ JSON ต้องมี `boxes`", ephemeral=True); return
    save_gacha(data)
    await interaction.response.send_message(f"✅ อัปโหลดสำเร็จ — {len(data.get('boxes',[]))} ตู้", ephemeral=True)
