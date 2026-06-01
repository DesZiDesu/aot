# ============================================================
# ORION — Scavenge / Gathering System (separate module)
# ============================================================
# Pool หาของแบ่งเป็นหมวด (พืช / ปลา / แร่ / เห็ด / ฯลฯ) แต่ละหมวด:
#   - มี subset ของ minigames ที่ใช้สุ่มได้
#   - มี items[] (จาก catalog) พร้อม weight + rarity
# ผู้เล่นใช้ /หาของ → เลือกหมวด → สุ่มมินิเกม → ผ่าน → สุ่มไอเทม (weighted)
# Admin /หาของแอดมิน → จัดการหมวด + เลือกไอเทมจาก dropdown
# ============================================================

import re
import sys
import time
import random as _rand
import discord

# ── dependencies ──────────────────────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_scavenge ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
_parse_int           = _orion_bot_mod._parse_int
MINIGAME_LABELS      = _orion_bot_mod.MINIGAME_LABELS
MINIGAME_KEYS        = _orion_bot_mod.MINIGAME_KEYS
_run_minigame        = _orion_bot_mod._run_minigame

# ใช้ helper จาก orion_items
import orion_items
load_items_catalog = orion_items.load_items_catalog
add_player_item    = orion_items.add_player_item


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="📦"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


SCAVENGE_FILE  = f"{ORION_DATA_DIR}/scavenge_pools.json"
CHANNELS_FILE  = f"{ORION_DATA_DIR}/scavenge_channels.json"

# Rarity → label + emoji
RARITY = {
    "common":     {"label": "common",    "emoji": "⚪", "color": 0xbdc3c7},
    "uncommon":   {"label": "uncommon",  "emoji": "🟢", "color": 0x2ecc71},
    "rare":       {"label": "rare",      "emoji": "🔵", "color": 0x3498db},
    "epic":       {"label": "epic",      "emoji": "🟣", "color": 0x9b59b6},
    "legendary":  {"label": "legendary", "emoji": "🟡", "color": 0xf1c40f},
}
RARITY_KEYS = list(RARITY.keys())


def load_pools() -> dict:
    return load_json(SCAVENGE_FILE, {})


def save_pools(d: dict):
    save_json(SCAVENGE_FILE, d)


# ── per-channel resource config ──────────────────────────────
# Schema:
# {
#   "<channel_id>": {
#     "pools": {
#       "<pool_id>": ["item_id1", "item_id2", ...]  # ไอเทมที่อนุญาตให้ดรอปในห้องนี้
#     }
#   }
# }
def load_channels() -> dict:
    return load_json(CHANNELS_FILE, {})


def save_channels(d: dict):
    save_json(CHANNELS_FILE, d)


def get_channel_pools(channel_id) -> dict:
    """คืน effective pools สำหรับห้องนี้ — กรองด้วย channel config
    ถ้าห้องไม่มี config → คืน {} (ไม่มีของให้หาในห้องนี้)"""
    pools = load_pools()
    ch_cfg = load_channels().get(str(channel_id), {})
    ch_pools = ch_cfg.get("pools", {})
    if not ch_pools:
        return {}
    effective = {}
    for pid, p in pools.items():
        enabled_ids = ch_pools.get(pid, [])
        if not enabled_ids:
            continue
        filtered_items = [it for it in p.get("items", []) if it["item_id"] in enabled_ids]
        if not filtered_items:
            continue
        effective[pid] = {**p, "items": filtered_items}
    return effective


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w฀-๿]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or f"pool_{int(time.time())}"


def _norm_icon(s: str):
    s = (s or "").strip()
    if s.lower().startswith(("http://", "https://")):
        return ("🗺️", s)
    return (s or "🗺️", "")


# ── Embeds ───────────────────────────────────────────────────
def _pools_embed(channel_id=None, channel_name: str = "") -> discord.Embed:
    """ถ้า channel_id ให้มา → ใช้ pool ที่ filter ตามห้องนั้น"""
    if channel_id is not None:
        pools = get_channel_pools(channel_id)
        title_suffix = f" — #{channel_name}" if channel_name else ""
        empty_msg = "_ห้องนี้ยังไม่มีของให้หา — admin ตั้งด้วย `/หาของห้อง`_"
    else:
        pools = load_pools()
        title_suffix = " (ทั้งหมด)"
        empty_msg = "_ยังไม่มีหมวด — รอแอดมินเพิ่ม_"

    embed = discord.Embed(
        title=f"ระบบหาของ{title_suffix}",
        description=(
            "_เลือกหมวดจาก dropdown · ผ่านมินิเกมเพื่อรับไอเทม (weighted random)_"
        ),
        color=0x16a085,
    )
    if not pools:
        embed.add_field(name="​", value=empty_msg, inline=False)
    else:
        for pid, p in list(pools.items())[:20]:
            items_count = len(p.get("items", []))
            mg_count    = len(p.get("minigames", []))
            embed.add_field(
                name=f"{p.get('emoji','🗺️')} {p.get('name','?')}",
                value=(
                    f"_{p.get('description','')[:120] or '— ไม่มีคำอธิบาย —'}_\n"
                    f"ไอเทมในห้องนี้ `{items_count}` · มินิเกม `{mg_count}`"
                ),
                inline=False,
            )
    embed.set_footer(text="Scavenge")
    return embed


def _pool_detail_embed(pid: str, p: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{p.get('emoji','🗺️')}  {p.get('name','?')}",
        description=p.get("description") or "_ไม่มีคำอธิบาย_",
        color=0x16a085,
    )
    if p.get("icon_url"):
        embed.set_thumbnail(url=p["icon_url"])
    mgs = p.get("minigames", [])
    mg_text = "\n".join(f"• {MINIGAME_LABELS.get(k, k)}" for k in mgs) or "_ยังไม่ได้ตั้งมินิเกม_"
    embed.add_field(name="🎮 มินิเกมที่ใช้สุ่ม", value=mg_text, inline=False)

    cat = load_items_catalog()
    items = p.get("items", [])
    if items:
        # group by rarity
        by_rarity = {}
        for ent in items:
            r = ent.get("rarity", "common")
            by_rarity.setdefault(r, []).append(ent)
        lines = []
        for r in RARITY_KEYS:
            if r not in by_rarity: continue
            lines.append(f"\n**{RARITY[r]['emoji']} {RARITY[r]['label'].upper()}**")
            for ent in by_rarity[r][:10]:
                it = cat.get(ent["item_id"], {})
                w = ent.get("weight", 1)
                lines.append(f"{it.get('emoji','📦')} {it.get('name', ent['item_id'])} `×weight {w}`")
        embed.add_field(name=f"📦 ไอเทมใน pool ({len(items)})", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="📦 ไอเทมใน pool", value="_ยังไม่มี — admin ต้องเพิ่ม_", inline=False)
    embed.add_field(name="🆔 ID", value=f"`{pid}`", inline=True)
    embed.set_footer(text="Orion · Scavenge Pool")
    return embed


def _weighted_choice(items: list) -> dict:
    """สุ่ม dict จาก list — ใช้ field 'weight'"""
    weights = [max(1, int(it.get("weight", 1))) for it in items]
    return _rand.choices(items, weights=weights, k=1)[0]


# ── Player flow ──────────────────────────────────────────────
class ScavengeCategorySelect(discord.ui.Select):
    def __init__(self, uid: str, channel_id):
        self.uid = uid
        self.channel_id = channel_id
        pools = get_channel_pools(channel_id)   # filter ตามห้อง
        options = []
        for pid, p in list(pools.items())[:25]:
            options.append(discord.SelectOption(
                label=p.get("name","?")[:100],
                value=pid,
                description=f"📦 {len(p.get('items',[]))} ไอเทม · 🎮 {len(p.get('minigames',[]))} มินิเกม"[:80],
                emoji=_safe_emoji(p.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ห้องนี้ยังไม่มีของให้หา", value="none")]
        super().__init__(placeholder="🗺️ เลือกหมวดที่จะหา...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        pid = self.values[0]
        ch_pools = get_channel_pools(self.channel_id)
        p = ch_pools.get(pid, {})
        if not p.get("items"):
            await ix.response.send_message("❌ หมวดนี้ไม่มีไอเทมในห้องนี้", ephemeral=True); return
        if not p.get("minigames"):
            await ix.response.send_message("❌ หมวดนี้ยังไม่ได้ตั้งมินิเกม", ephemeral=True); return
        await ix.response.send_message(
            embed=_pool_detail_embed(pid, p),
            view=ScavengeStartView(self.uid, pid, self.channel_id),
            ephemeral=True,
        )


class ScavengeMenuView(discord.ui.View):
    def __init__(self, uid: str, channel_id):
        super().__init__(timeout=300)
        self.add_item(ScavengeCategorySelect(uid, channel_id))


class ScavengeStartView(discord.ui.View):
    def __init__(self, uid: str, pid: str, channel_id):
        super().__init__(timeout=180)
        self.uid = uid
        self.pid = pid
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="เริ่มออกหา", style=discord.ButtonStyle.success)
    async def btn_start(self, ix: discord.Interaction, _b):
        # ดึง pool ที่ filter ตามห้อง ณ เวลานี้
        p = get_channel_pools(self.channel_id).get(self.pid, {})
        if not p.get("items") or not p.get("minigames"):
            await ix.response.send_message("❌ pool ไม่พร้อม (อาจถูก admin ถอดออก)", ephemeral=True); return
        await ix.response.defer(ephemeral=True)
        minigame = _rand.choice(p["minigames"])
        result = await _run_minigame(ix, minigame)
        if not result:
            await ix.followup.send("💔 หาไม่เจออะไรเลยรอบนี้ — ลองใหม่ได้", ephemeral=True); return
        # สุ่มไอเทม (weighted)
        ent = _weighted_choice(p["items"])
        item_id = ent["item_id"]
        cat = load_items_catalog()
        it = cat.get(item_id)
        if not it:
            await ix.followup.send(f"⚠️ ผ่านมินิเกมแล้ว แต่ไอเทม `{item_id}` หายไปจาก catalog", ephemeral=True); return
        qty = max(1, int(ent.get("qty", 1)))
        add_player_item(self.uid, item_id, qty)
        rarity = ent.get("rarity", "common")
        rmeta = RARITY.get(rarity, RARITY["common"])
        embed = discord.Embed(
            title=f"🎉 หาเจอ! {it.get('emoji','📦')} {it.get('name','?')} ×{qty}",
            description=(
                f"{rmeta['emoji']} **{rmeta['label'].upper()}**\n\n"
                f"{it.get('description','')[:500]}"
            ),
            color=rmeta["color"],
        )
        if it.get("image_url"):
            embed.set_thumbnail(url=it["image_url"])
        embed.set_footer(text=f"จาก: {p.get('name','?')} · มินิเกม {MINIGAME_LABELS.get(minigame)}")
        await ix.followup.send(embed=embed, ephemeral=True)


# ── Admin flow ───────────────────────────────────────────────
class PoolAddModal(discord.ui.Modal, title="➕ เพิ่มหมวดหาของ"):
    f_name = discord.ui.TextInput(label="ชื่อหมวด (เช่น พืช / ปลา / แร่)", max_length=50)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL รูป)", placeholder="🌿 หรือ https://...", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=500)

    async def on_submit(self, ix: discord.Interaction):
        pools = load_pools()
        pid = _slug(self.f_name.value)
        if pid in pools:
            pid = f"{pid}_{int(time.time())}"
        emoji, icon_url = _norm_icon(self.f_icon.value)
        pools[pid] = {
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": (self.f_desc.value or "").strip(),
            "minigames": [],
            "items": [],
        }
        save_pools(pools)
        await ix.response.send_message(
            f"✅ เพิ่มหมวด `{pid}` — {emoji} **{pools[pid]['name']}**\n"
            f"_หมายเหตุ: ต้องเลือกมินิเกม + เพิ่มไอเทมต่อจาก admin panel_",
            ephemeral=True,
        )


class PoolSelectAdmin(discord.ui.Select):
    """Dropdown หมวดสำหรับ admin"""
    def __init__(self, placeholder: str, action: str):
        self.action = action
        pools = load_pools()
        options = []
        for pid, p in list(pools.items())[:25]:
            options.append(discord.SelectOption(
                label=p.get("name","?")[:100],
                value=pid,
                description=f"📦 {len(p.get('items',[]))} · 🎮 {len(p.get('minigames',[]))}"[:80],
                emoji=_safe_emoji(p.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีหมวด", value="none")]
        super().__init__(placeholder=placeholder, options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        pid = self.values[0]
        if self.action == "delete":
            pools = load_pools()
            removed = pools.pop(pid, None)
            save_pools(pools)
            await ix.response.edit_message(
                content=f"🗑️ ลบหมวด `{pid}` ({removed.get('name') if removed else '?'}) แล้ว",
                view=None,
            )
        elif self.action == "items":
            await ix.response.edit_message(
                content=f"📦 ติ๊กไอเทมที่จะให้มีใน pool `{pid}` (cap 25 อัน)",
                view=PoolItemsPickerView(pid),
            )
        elif self.action == "minigames":
            await ix.response.edit_message(
                content=f"🎮 ติ๊กมินิเกมที่จะใช้สุ่มใน pool `{pid}`",
                view=PoolMinigamesPickerView(pid),
            )
        elif self.action == "tune":
            p = load_pools().get(pid, {})
            if not p.get("items"):
                await ix.response.send_message("❌ pool นี้ยังไม่มีไอเทม — เพิ่มก่อน", ephemeral=True); return
            await ix.response.edit_message(
                content=f"⚙️ เลือกไอเทมใน pool `{pid}` ที่จะปรับ weight/rarity ↓",
                view=PoolTuneItemView(pid),
            )
        elif self.action == "view":
            p = load_pools().get(pid, {})
            await ix.response.send_message(embed=_pool_detail_embed(pid, p), ephemeral=True)


# ── Items picker (multi-select ของไอเทม catalog) ────────────
class PoolItemsMultiSelect(discord.ui.Select):
    def __init__(self, pid: str):
        self.pid = pid
        cat = load_items_catalog()
        pools = load_pools()
        pool = pools.get(pid, {})
        existing_ids = {ent["item_id"] for ent in pool.get("items", [])}
        items = list(cat.items())[:25]
        options = []
        for iid, it in items:
            options.append(discord.SelectOption(
                label=it.get("name","?")[:100],
                value=iid,
                description=f"{iid} · ราคา {it.get('sell_price',0):,}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
                default=(iid in existing_ids),
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีไอเทมใน catalog", value="none")]
        super().__init__(
            placeholder="📦 ติ๊กไอเทมที่จะอยู่ใน pool...",
            options=options,
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, ix: discord.Interaction):
        pools = load_pools()
        p = pools.get(self.pid)
        if not p:
            await ix.response.send_message("❌ ไม่พบ pool", ephemeral=True); return
        selected = set(self.values) - {"none"}
        # คง weight/rarity เดิม ของที่เคยอยู่; ของใหม่ตั้ง default
        existing = {ent["item_id"]: ent for ent in p.get("items", [])}
        new_items = []
        for iid in selected:
            if iid in existing:
                new_items.append(existing[iid])
            else:
                new_items.append({"item_id": iid, "weight": 5, "rarity": "common", "qty": 1})
        p["items"] = new_items
        save_pools(pools)
        await ix.response.edit_message(
            content=f"✅ อัปเดตไอเทม pool `{self.pid}` — {len(new_items)} ไอเทม",
            view=None,
        )


class PoolItemsPickerView(discord.ui.View):
    def __init__(self, pid: str):
        super().__init__(timeout=300)
        self.add_item(PoolItemsMultiSelect(pid))


# ── Minigames picker (multi-select มินิเกม) ─────────────────
class PoolMinigamesMultiSelect(discord.ui.Select):
    def __init__(self, pid: str):
        self.pid = pid
        pools = load_pools()
        pool = pools.get(pid, {})
        existing = set(pool.get("minigames", []))
        options = []
        for key, label in MINIGAME_LABELS.items():
            options.append(discord.SelectOption(
                label=label[:100],
                value=key,
                default=(key in existing),
            ))
        super().__init__(
            placeholder="🎮 ติ๊กมินิเกมที่จะสุ่มเล่น...",
            options=options,
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, ix: discord.Interaction):
        pools = load_pools()
        p = pools.get(self.pid)
        if not p:
            await ix.response.send_message("❌ ไม่พบ pool", ephemeral=True); return
        p["minigames"] = list(self.values)
        save_pools(pools)
        await ix.response.edit_message(
            content=f"✅ อัปเดตมินิเกม pool `{self.pid}` — {len(p['minigames'])} อัน",
            view=None,
        )


class PoolMinigamesPickerView(discord.ui.View):
    def __init__(self, pid: str):
        super().__init__(timeout=300)
        self.add_item(PoolMinigamesMultiSelect(pid))


# ── ปรับ weight + rarity ของไอเทมใน pool ─────────────────────
class PoolTuneItemSelect(discord.ui.Select):
    def __init__(self, pid: str):
        self.pid = pid
        p = load_pools().get(pid, {})
        cat = load_items_catalog()
        options = []
        for ent in p.get("items", [])[:25]:
            it = cat.get(ent["item_id"], {})
            options.append(discord.SelectOption(
                label=it.get("name", ent["item_id"])[:100],
                value=ent["item_id"],
                description=f"{ent.get('rarity','common')} · weight {ent.get('weight',1)} · qty {ent.get('qty',1)}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีไอเทม", value="none")]
        super().__init__(placeholder="⚙️ เลือกไอเทมที่จะปรับ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(PoolTuneItemModal(self.pid, self.values[0]))


class PoolTuneItemView(discord.ui.View):
    def __init__(self, pid: str):
        super().__init__(timeout=300)
        self.add_item(PoolTuneItemSelect(pid))


class PoolTuneItemModal(discord.ui.Modal, title="⚙️ ปรับ weight / rarity / qty"):
    f_weight = discord.ui.TextInput(label="Weight (น้ำหนักสุ่ม 1-100)", placeholder="5", max_length=4)
    f_qty    = discord.ui.TextInput(label="Qty (จำนวนต่อครั้ง)", placeholder="1", max_length=4)
    f_rarity = discord.ui.TextInput(label="Rarity (common/uncommon/rare/epic/legendary)", placeholder="common", max_length=20)

    def __init__(self, pid: str, item_id: str):
        super().__init__()
        self.pid = pid
        self.item_id = item_id
        p = load_pools().get(pid, {})
        ent = next((e for e in p.get("items", []) if e["item_id"] == item_id), None)
        if ent:
            self.f_weight.default = str(ent.get("weight", 5))
            self.f_qty.default    = str(ent.get("qty", 1))
            self.f_rarity.default = ent.get("rarity", "common")

    async def on_submit(self, ix: discord.Interaction):
        pools = load_pools()
        p = pools.get(self.pid)
        if not p:
            await ix.response.send_message("❌ ไม่พบ pool", ephemeral=True); return
        ent = next((e for e in p.get("items", []) if e["item_id"] == self.item_id), None)
        if not ent:
            await ix.response.send_message("❌ ไม่พบไอเทมใน pool", ephemeral=True); return
        w = _parse_int(self.f_weight.value, 5) or 5
        q = _parse_int(self.f_qty.value, 1) or 1
        r = (self.f_rarity.value or "common").strip().lower()
        if r not in RARITY:
            await ix.response.send_message(f"❌ rarity ต้องเป็น: {', '.join(RARITY_KEYS)}", ephemeral=True); return
        ent["weight"] = max(1, min(100, w))
        ent["qty"]    = max(1, q)
        ent["rarity"] = r
        save_pools(pools)
        await ix.response.send_message(
            f"✅ อัปเดต `{self.item_id}` ใน pool `{self.pid}` — weight {ent['weight']}, qty {ent['qty']}, {ent['rarity']}",
            ephemeral=True,
        )


# ── Admin Panel ──────────────────────────────────────────────
class ScavengeAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="เพิ่มหมวด", style=discord.ButtonStyle.success, row=0)
    async def btn_add(self, ix, _b):
        await ix.response.send_modal(PoolAddModal())

    @discord.ui.button(label="ลบหมวด", style=discord.ButtonStyle.danger, row=0)
    async def btn_del(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(PoolSelectAdmin("🗑️ เลือกหมวดที่จะลบ...", action="delete"))
        await ix.response.send_message("🗑️ เลือกหมวด ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ตั้งไอเทมใน pool", style=discord.ButtonStyle.primary, row=0)
    async def btn_items(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(PoolSelectAdmin("📦 เลือกหมวด...", action="items"))
        await ix.response.send_message("📦 เลือกหมวดที่จะใส่ไอเทม ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ตั้งมินิเกมของ pool", style=discord.ButtonStyle.primary, row=1)
    async def btn_mg(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(PoolSelectAdmin("🎮 เลือกหมวด...", action="minigames"))
        await ix.response.send_message("🎮 เลือกหมวด ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ปรับ weight/rarity", style=discord.ButtonStyle.secondary, row=1)
    async def btn_tune(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(PoolSelectAdmin("⚙️ เลือกหมวด...", action="tune"))
        await ix.response.send_message("⚙️ เลือกหมวด ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ดูรายละเอียด", style=discord.ButtonStyle.secondary, row=1)
    async def btn_view(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(PoolSelectAdmin("📚 เลือกหมวด...", action="view"))
        await ix.response.send_message("📚 เลือกหมวด ↓", view=view, ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="หาของ", description="ออกไปหาของในห้องนี้ — แต่ละห้องมีของไม่เหมือนกัน", guild=_ORION_GUILD_OBJ)
async def cmd_scavenge(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    ch = interaction.channel
    ch_id = ch.id if ch else None
    ch_name = ch.name if ch and hasattr(ch, "name") else ""
    await interaction.response.send_message(
        embed=_pools_embed(ch_id, ch_name),
        view=ScavengeMenuView(uid, ch_id),
        ephemeral=_eph("หาของ"),
    )


# ============================================================
# CHANNEL-LEVEL ADMIN — ตั้งของในแต่ละห้อง
# ============================================================
PAGE_SIZE = 4  # multi-select ต่อหน้า (เหลือ 1 row ให้ปุ่ม)


class ChannelPoolMultiSelect(discord.ui.Select):
    """1 multi-select ต่อ 1 pool — ติ๊กไอเทมที่จะให้หาเจอในห้องนี้"""
    def __init__(self, channel_id: int, pid: str, pool: dict):
        self.channel_id = channel_id
        self.pid = pid
        cat = load_items_catalog()
        ch_pools = load_channels().get(str(channel_id), {}).get("pools", {})
        enabled = set(ch_pools.get(pid, []))
        items = pool.get("items", [])
        options = []
        for ent in items[:25]:
            iid = ent["item_id"]
            it = cat.get(iid, {})
            rarity = ent.get("rarity", "common")
            rmeta = RARITY.get(rarity, RARITY["common"])
            options.append(discord.SelectOption(
                label=it.get("name", iid)[:100],
                value=iid,
                description=f"{rmeta['emoji']} {rarity} · weight {ent.get('weight',1)}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
                default=(iid in enabled),
            ))
        if not options:
            options = [discord.SelectOption(label="(pool นี้ยังไม่มีไอเทม)", value="__empty__")]
            placeholder_extra = " (ว่าง)"
        else:
            placeholder_extra = ""
        super().__init__(
            placeholder=f"{pool.get('emoji','🗺️')} {pool.get('name','?')} — ติ๊กที่ให้เจอในห้องนี้{placeholder_extra}",
            options=options,
            min_values=0,
            max_values=len(options) if options[0].value != "__empty__" else 1,
        )

    async def callback(self, ix: discord.Interaction):
        if "__empty__" in self.values:
            await ix.response.defer(); return
        channels = load_channels()
        ch_cfg = channels.setdefault(str(self.channel_id), {})
        pools_cfg = ch_cfg.setdefault("pools", {})
        pools_cfg[self.pid] = list(self.values)
        if not pools_cfg[self.pid]:
            # ถ้าไม่ติ๊กเลย ลบทิ้งเพื่อความสะอาด
            pools_cfg.pop(self.pid, None)
        save_channels(channels)
        # silent autosave — แค่ ack
        await ix.response.defer()


class CopyFromChannelModal(discord.ui.Modal, title="📋 คัดลอกทรัพยากรจากห้องอื่น"):
    f_src = discord.ui.TextInput(label="Channel ID ต้นทาง", placeholder="เช่น 1234567890", max_length=25)
    f_mode = discord.ui.TextInput(
        label="โหมด (merge / replace)",
        placeholder="merge = รวมกับของเดิม | replace = ทับของเดิมทั้งหมด",
        max_length=10,
    )

    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.f_mode.default = "merge"

    async def on_submit(self, ix: discord.Interaction):
        src_id = "".join(c for c in self.f_src.value if c.isdigit())
        if not src_id:
            await ix.response.send_message("❌ Channel ID ผิด", ephemeral=True); return
        if src_id == str(self.channel_id):
            await ix.response.send_message("❌ ห้องต้นทางต้องไม่ใช่ห้องปลายทาง", ephemeral=True); return
        mode = (self.f_mode.value or "merge").strip().lower()
        if mode not in ("merge", "replace"):
            await ix.response.send_message("❌ โหมดต้องเป็น merge หรือ replace", ephemeral=True); return
        channels = load_channels()
        src_cfg = channels.get(src_id, {})
        src_pools = src_cfg.get("pools", {})
        if not src_pools:
            await ix.response.send_message(f"❌ ห้อง `{src_id}` ไม่มีทรัพยากรตั้งไว้", ephemeral=True); return
        dst_cfg = channels.setdefault(str(self.channel_id), {})
        dst_pools = dst_cfg.setdefault("pools", {})
        if mode == "replace":
            dst_cfg["pools"] = {pid: list(ids) for pid, ids in src_pools.items()}
            changed = len(src_pools)
        else:  # merge
            changed = 0
            for pid, ids in src_pools.items():
                merged = set(dst_pools.get(pid, [])) | set(ids)
                if merged != set(dst_pools.get(pid, [])):
                    dst_pools[pid] = list(merged)
                    changed += 1
        save_channels(channels)
        await ix.response.send_message(
            f"✅ คัดลอกจากห้อง `{src_id}` สำเร็จ — โหมด **{mode}** · มีหมวดที่อัปเดต {changed} หมวด\n"
            f"_เปิด /หาของห้อง ใหม่เพื่อดูผล_",
            ephemeral=True,
        )


class ClearChannelView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=60)
        self.channel_id = channel_id

    @discord.ui.button(label="ยืนยันล้างทั้งหมด", style=discord.ButtonStyle.danger)
    async def btn_yes(self, ix: discord.Interaction, _b):
        channels = load_channels()
        channels.pop(str(self.channel_id), None)
        save_channels(channels)
        await ix.response.edit_message(content="💥 ล้างทรัพยากรของห้องนี้แล้ว", view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def btn_no(self, ix: discord.Interaction, _b):
        await ix.response.edit_message(content="❌ ยกเลิก", view=None)


class ChannelManageNavBtn(discord.ui.Button):
    """ปุ่มเปลี่ยนหน้าใน ChannelManageView"""
    def __init__(self, parent_channel_id: int, channel_name: str, delta: int, label: str, emoji_str: str = None):
        super().__init__(label=label, emoji=emoji_str, style=discord.ButtonStyle.secondary, row=4)
        self.channel_id = parent_channel_id
        self.channel_name = channel_name
        self.delta = delta

    async def callback(self, ix: discord.Interaction):
        v = self.view
        new_page = v.page + self.delta
        new_view = ChannelManageView(self.channel_id, self.channel_name, page=new_page)
        await ix.response.edit_message(
            embed=_channel_manage_embed(self.channel_id, self.channel_name, new_page),
            view=new_view,
        )


class ChannelManageCopyBtn(discord.ui.Button):
    def __init__(self, channel_id: int):
        super().__init__(label="คัดลอกจากห้องอื่น", style=discord.ButtonStyle.primary, row=4)
        self.channel_id = channel_id

    async def callback(self, ix: discord.Interaction):
        await ix.response.send_modal(CopyFromChannelModal(self.channel_id))


class ChannelManageClearBtn(discord.ui.Button):
    def __init__(self, channel_id: int):
        super().__init__(label="ล้างห้องนี้", style=discord.ButtonStyle.danger, row=4)
        self.channel_id = channel_id

    async def callback(self, ix: discord.Interaction):
        await ix.response.send_message(
            "⚠️ ล้างทรัพยากรทั้งหมดของห้องนี้?",
            view=ClearChannelView(self.channel_id),
            ephemeral=True,
        )


def _channel_manage_embed(channel_id: int, channel_name: str, page: int) -> discord.Embed:
    pools = load_pools()
    total = len(pools)
    max_page = max(0, (total - 1) // PAGE_SIZE)
    ch_pools = load_channels().get(str(channel_id), {}).get("pools", {})
    enabled_summary = []
    for pid, ids in ch_pools.items():
        p = pools.get(pid, {})
        enabled_summary.append(f"{p.get('emoji','🗺️')} {p.get('name','?')} ({len(ids)})")
    summary = " · ".join(enabled_summary) or "_ยังไม่ติ๊กหมวดไหน_"
    embed = discord.Embed(
        title=f"🗺️  จัดการทรัพยากรของห้อง: #{channel_name}",
        description=(
            "**ติ๊กที่ต้องการให้เจอ** — บันทึกอัตโนมัติเมื่อเลือก\n"
            f"**หน้า:** {page+1} / {max_page+1}\n\n"
            f"**ตอนนี้:** {summary}"
        ),
        color=0x16a085,
    )
    embed.set_footer(text=f"Channel ID: {channel_id}")
    return embed


class ChannelManageView(discord.ui.View):
    def __init__(self, channel_id: int, channel_name: str, page: int = 0):
        super().__init__(timeout=600)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.page = page
        pools = load_pools()
        pool_items = list(pools.items())
        total = len(pool_items)
        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        for pid, p in pool_items[start:end]:
            self.add_item(ChannelPoolMultiSelect(channel_id, pid, p))
        # nav + extra buttons row
        if page > 0:
            self.add_item(ChannelManageNavBtn(channel_id, channel_name, -1, "หน้าก่อน", "⬅️"))
        if end < total:
            self.add_item(ChannelManageNavBtn(channel_id, channel_name, +1, "หน้าถัดไป", "➡️"))
        self.add_item(ChannelManageCopyBtn(channel_id))
        self.add_item(ChannelManageClearBtn(channel_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True


@bot.tree.command(name="หาของห้อง", description="[Admin] ตั้งทรัพยากรของห้องนี้ (เลือกไอเทมที่ดรอปได้)", guild=_ORION_GUILD_OBJ)
async def cmd_scavenge_channel(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    pools = load_pools()
    if not pools:
        await interaction.response.send_message(
            "❌ ยังไม่มี pool ใน catalog — สร้างก่อนด้วย `/หาของแอดมิน`",
            ephemeral=True,
        ); return
    ch = interaction.channel
    ch_id = ch.id
    ch_name = ch.name if hasattr(ch, "name") else "?"
    await interaction.response.send_message(
        embed=_channel_manage_embed(ch_id, ch_name, 0),
        view=ChannelManageView(ch_id, ch_name, page=0),
        ephemeral=True,
    )


@bot.tree.command(name="หาของแอดมิน", description="[Admin] จัดการหมวด/ไอเทม/มินิเกมของระบบหาของ", guild=_ORION_GUILD_OBJ)
async def cmd_scavenge_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    pools = load_pools()
    embed = discord.Embed(
        title="🗺️  Scavenge — Admin Panel",
        description=(
            f"**หมวดในระบบ:** {len(pools)}\n\n"
            "**Row 0** — ➕ เพิ่ม · 🗑️ ลบ · 📦 ตั้งไอเทม (multi-select)\n"
            "**Row 1** — 🎮 ตั้งมินิเกม · ⚙️ ปรับ weight/rarity · 📚 ดูรายละเอียด\n\n"
            "**ขั้นตอนสร้าง pool ใหม่ (global):**\n"
            "1️⃣ ➕ เพิ่มหมวด\n"
            "2️⃣ 📦 ติ๊กไอเทมจาก catalog (default weight=5, qty=1, rarity=common)\n"
            "3️⃣ 🎮 ติ๊กมินิเกม (สุ่มเล่นเมื่อผู้เล่นมาหาของ)\n"
            "4️⃣ ⚙️ ปรับ weight/rarity ของแต่ละไอเทม (optional)\n\n"
            "**ตั้งของในแต่ละห้อง** — พิมพ์ `/หาของห้อง` ในห้องนั้นๆ\n"
            "(สามารถคัดลอกจากห้องอื่นได้ด้วย Channel ID)"
        ),
        color=0x16a085,
    )
    await interaction.response.send_message(embed=embed, view=ScavengeAdminView(), ephemeral=True)
