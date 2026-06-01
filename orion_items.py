# ============================================================
# ORION — Item Catalog System (separate module)
# ============================================================
# โหลดผ่าน `import orion_items` จาก orion_bot.py
# ต้องโหลดหลังจาก orion_bot ได้ define ของพวกนี้แล้ว:
#   bot, ORION_GUILD_ID, _ORION_GUILD_OBJ, ORION_DATA_DIR,
#   load_json, save_json,
#   ensure_orion_player, load_orion_players, save_orion_players,
#   load_currency_cfg, money_str, get_wallet, add_money,
#   _orion_parse_user_id, _parse_int, MINIGAME_LABELS
# ============================================================

import re
import sys
import time
import discord

# ── ดึง dependencies จาก orion_bot ผ่าน sys.modules ───────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_items ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_orion_players   = _orion_bot_mod.load_orion_players
save_orion_players   = _orion_bot_mod.save_orion_players
load_currency_cfg    = _orion_bot_mod.load_currency_cfg
money_str            = _orion_bot_mod.money_str
get_wallet           = _orion_bot_mod.get_wallet
add_money            = _orion_bot_mod.add_money
_orion_parse_user_id = _orion_bot_mod._orion_parse_user_id
_parse_int           = _orion_bot_mod._parse_int
MINIGAME_LABELS      = _orion_bot_mod.MINIGAME_LABELS


def _eph(cmd_name: str) -> bool:
    """Proxy ไปยัง orion_bot._eph (อาจยังไม่ถูก define ตอน import — fallback = True)"""
    fn = getattr(_orion_bot_mod, "_eph", None)
    if fn is None:
        return True
    return fn(cmd_name)


def _safe_emoji(s, default="📦"):
    """delegate ไปที่ orion_bot._safe_emoji ถ้ามี; fallback แบบเดียวกัน"""
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    if fn:
        return fn(s, default)
    if not s or not isinstance(s, str):
        return default
    s = s.strip()
    if not s:
        return default
    if any(c.isascii() and c.isalnum() for c in s):
        return default
    if len(s) > 8:
        return default
    return s


ITEMS_FILE        = f"{ORION_DATA_DIR}/items.json"
ITEMS_CONFIG_FILE = f"{ORION_DATA_DIR}/items_config.json"

_search_cooldowns: dict = {}  # uid -> last search timestamp


def _get_search_cooldown() -> int:
    cfg = load_json(ITEMS_CONFIG_FILE, {})
    return max(0, int(cfg.get("search_cooldown_seconds", 0)))

# ── ไอเทมเริ่มต้น 4 อย่าง — หิน / ไม้ / เหล็กดิบ / สมุนไพร ──
DEFAULT_ITEMS = {
    "stone":    {"name": "หิน",      "emoji": "🪨", "image_url": "", "description": "ก้อนหินธรรมดา หาได้ทั่วไปริมทาง",       "sell_price": 5,  "type": "resource"},
    "wood":     {"name": "ไม้",      "emoji": "🪵", "image_url": "", "description": "ท่อนไม้สดจากต้นไม้ในป่าตะวันออก",     "sell_price": 3,  "type": "resource"},
    "iron_ore": {"name": "เหล็กดิบ", "emoji": "⛓️", "image_url": "", "description": "แร่เหล็กดิบยังไม่ผ่านการถลุง แข็งหนัก", "sell_price": 12, "type": "resource"},
    "herb":     {"name": "สมุนไพร",  "emoji": "🌿", "image_url": "", "description": "ใบไม้สมุนไพรหายาก กลิ่นหอม ใช้ทำยา",  "sell_price": 8,  "type": "resource"},
}


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w฀-๿]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or f"item_{int(time.time())}"


def _normalize_icon(icon_input: str):
    """รับ input หนึ่งฟิลด์ — คืน (emoji, image_url)
    ถ้าขึ้นด้วย http/https → ถือเป็น URL รูป
    ถ้าอย่างอื่น → ถือเป็น emoji"""
    s = (icon_input or "").strip()
    if s.lower().startswith(("http://", "https://")):
        return ("📦", s)
    return (s or "📦", "")


TYPE_LABELS = {
    "resource": "🌿 วัตถุดิบ",
    "usable":   "✨ กดใช้ได้",
    "craft":    "🛠️ คราฟ",
}


# ── Storage ──────────────────────────────────────────────────
def load_items_catalog() -> dict:
    cat = load_json(ITEMS_FILE, None)
    if not cat:
        cat = dict(DEFAULT_ITEMS)
        save_items_catalog(cat)
    return cat


def save_items_catalog(cat: dict):
    save_json(ITEMS_FILE, cat)


def get_item(item_id: str) -> dict:
    return load_items_catalog().get(item_id, {})


def get_player_inv(uid: str) -> list:
    ensure_orion_player(uid)
    return load_orion_players().get(uid, {}).get("inv", [])


def player_qty(uid: str, item_id: str) -> int:
    for x in get_player_inv(uid):
        if x.get("item_id") == item_id:
            return int(x.get("qty", 0))
    return 0


def add_player_item(uid: str, item_id: str, qty: int = 1):
    ensure_orion_player(uid)
    data = load_orion_players()
    inv = data[uid].setdefault("inv", [])
    found = next((x for x in inv if x.get("item_id") == item_id), None)
    if found:
        found["qty"] = int(found.get("qty", 0)) + int(qty)
    else:
        inv.append({"item_id": item_id, "qty": int(qty)})
    save_orion_players(data)


def remove_player_item(uid: str, item_id: str, qty: int = 1) -> bool:
    data = load_orion_players()
    inv = data.get(uid, {}).get("inv", [])
    found = next((x for x in inv if x.get("item_id") == item_id), None)
    if not found or int(found.get("qty", 0)) < int(qty):
        return False
    found["qty"] = int(found["qty"]) - int(qty)
    if found["qty"] <= 0:
        inv.remove(found)
    save_orion_players(data)
    return True


def player_has_items(uid: str, ingredients: list) -> bool:
    inv = {x["item_id"]: int(x.get("qty", 0)) for x in get_player_inv(uid)}
    for ing in ingredients:
        if inv.get(ing["item_id"], 0) < int(ing.get("qty", 1)):
            return False
    return True


# ── Embeds ──────────────────────────────────────────────────
def _build_item_embed(iid: str, item: dict) -> discord.Embed:
    itype = item.get("type", "resource")
    color = {"craft": 0xe67e22, "usable": 0x9b59b6, "resource": 0x3498db}.get(itype, 0x3498db)
    embed = discord.Embed(
        title=f"{item.get('emoji','📦')}  {item.get('name','?')}",
        description=item.get("description") or "_ไม่มีคำอธิบาย_",
        color=color,
    )
    if item.get("image_url"):
        embed.set_image(url=item["image_url"])
    embed.add_field(name="💰 ราคาขาย", value=money_str(item.get("sell_price", 0)), inline=True)
    embed.add_field(name="🏷️ ประเภท", value=TYPE_LABELS.get(itype, itype), inline=True)
    embed.add_field(name="🆔 ID", value=f"`{iid}`", inline=True)
    if itype == "usable" and item.get("use_effect"):
        embed.add_field(name="✨ ผลของการใช้", value=item["use_effect"][:1000], inline=False)
    if itype == "craft":
        recipe = item.get("recipe", {})
        ings = recipe.get("ingredients", [])
        if ings:
            cat = load_items_catalog()
            lines = []
            for ing in ings:
                it = cat.get(ing["item_id"], {})
                lines.append(f"{it.get('emoji','📦')} {it.get('name', ing['item_id'])} ×{ing['qty']}")
            embed.add_field(name="🔨 ส่วนผสม", value="\n".join(lines), inline=False)
        mg = recipe.get("minigame", "")
        if mg:
            embed.add_field(name="🎮 มินิเกม", value=MINIGAME_LABELS.get(mg, mg), inline=True)
    embed.set_footer(text="Orion · Item Catalog")
    return embed


def _items_overview_embed() -> discord.Embed:
    cat = load_items_catalog()
    resources = [(i, it) for i, it in cat.items() if it.get("type") not in ("craft", "usable")]
    usables   = [(i, it) for i, it in cat.items() if it.get("type") == "usable"]
    crafts    = [(i, it) for i, it in cat.items() if it.get("type") == "craft"]
    embed = discord.Embed(
        title="คลังไอเทม",
        description=f"_ไอเทมทั้งหมด **{len(cat)}** รายการ_",
        color=0x3498db,
    )
    if resources:
        embed.add_field(
            name=f"ทรัพยากร — {len(resources)}",
            value="\n".join(f"{it.get('emoji','📦')} **{it.get('name','?')}** · {money_str(it.get('sell_price',0))}" for _, it in resources[:12]) or "_ไม่มี_",
            inline=False,
        )
    if usables:
        embed.add_field(
            name=f"กดใช้ได้ — {len(usables)}",
            value="\n".join(f"{it.get('emoji','📦')} **{it.get('name','?')}** · {money_str(it.get('sell_price',0))}" for _, it in usables[:12]) or "_ไม่มี_",
            inline=False,
        )
    if crafts:
        embed.add_field(
            name=f"คราฟ — {len(crafts)}",
            value="\n".join(f"{it.get('emoji','📦')} **{it.get('name','?')}** · {money_str(it.get('sell_price',0))}" for _, it in crafts[:12]) or "_ไม่มี_",
            inline=False,
        )
    embed.set_footer(text="/ไอเทม กระเป๋าตัวเอง · /คราฟ คราฟไอเทม")
    return embed


def _player_bag_embed(uid: str, author) -> discord.Embed:
    cfg = load_currency_cfg()
    cat = load_items_catalog()
    inv = get_player_inv(uid)
    wallet = get_wallet(uid)
    embed = discord.Embed(
        title=f"กระเป๋า — {author.display_name}",
        description=f"{cfg['emoji']} **{wallet:,}** {cfg['name']}   ·   ไอเทม `{len(inv)}` ชนิด",
        color=0x55efc4,
    )
    if cfg.get("icon_url"):
        embed.set_thumbnail(url=cfg["icon_url"])
    else:
        embed.set_thumbnail(url=author.display_avatar.url)
    if inv:
        lines = []
        for entry in inv[:20]:
            it = cat.get(entry["item_id"], {})
            lines.append(f"{it.get('emoji','📦')} **{it.get('name', entry['item_id'])}** ×{entry.get('qty',1)}")
        embed.add_field(name="​", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="​", value="_— ว่าง —_", inline=False)
    embed.set_footer(text=f"{cfg['name']} Inventory")
    return embed


# ── Views & Selects ──────────────────────────────────────────
class ItemCatalogSelect(discord.ui.Select):
    def __init__(self, page: int = 0):
        self.page = page
        cat = load_items_catalog()
        items = sorted(cat.items(), key=lambda x: x[1].get("name", x[0]).lower())
        total = len(items)
        page_size = 23
        max_page = max(0, (total - 1) // page_size)
        start = page * page_size
        end = start + page_size
        page_items = items[start:end]

        options = []
        for iid, it in page_items:
            options.append(discord.SelectOption(
                label=it.get("name", "?")[:100],
                value=iid,
                description=(it.get("description", "")[:80] or "—"),
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if page < max_page:
            options.append(discord.SelectOption(
                label="→ หน้าถัดไป",
                value=f"__nextpage__:{page+1}",
                description=f"ดูหน้า {page+2}/{max_page+1}",
            ))
        if page > 0:
            options.append(discord.SelectOption(
                label="← หน้าก่อน",
                value=f"__nextpage__:{page-1}",
                description=f"กลับหน้า {page}/{max_page+1}",
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีไอเทม", value="none")]
        ph_suffix = f" (หน้า {page+1}/{max_page+1})" if max_page > 0 else ""
        super().__init__(placeholder=f"เลือกดูไอเทม{ph_suffix}...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        if self.values[0].startswith("__nextpage__:"):
            new_page = int(self.values[0].split(":", 1)[1])
            await interaction.response.edit_message(view=ItemCatalogView(page=new_page))
            return
        iid = self.values[0]
        item = get_item(iid)
        if not item:
            await interaction.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        await interaction.response.send_message(embed=_build_item_embed(iid, item), ephemeral=True)


class ItemCatalogView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.add_item(ItemCatalogSelect(page=page))


# ── PlayerBag (กระเป๋ามีปุ่ม ใช้/โอน/ทิ้ง/ขาย) ───────────────
class PlayerBagSelect(discord.ui.Select):
    def __init__(self, uid: str, author):
        self.uid = uid
        self.author = author
        inv = get_player_inv(uid)[:25]
        cat = load_items_catalog()
        options = []
        for entry in inv:
            it = cat.get(entry["item_id"], {})
            options.append(discord.SelectOption(
                label=f"{it.get('name', entry['item_id'])} (×{entry.get('qty',1)})"[:100],
                value=entry["item_id"],
                description=(it.get("description", "")[:80] or "—"),
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="กระเป๋าว่าง", value="none")]
        super().__init__(placeholder="📦 เลือกไอเทมเพื่อจัดการ...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await interaction.response.defer(); return
        iid = self.values[0]
        item = get_item(iid)
        if not item:
            await interaction.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        qty = player_qty(self.uid, iid)
        embed = _build_item_embed(iid, item)
        embed.add_field(name="🎒 มีในกระเป๋า", value=f"**×{qty}**", inline=True)
        await interaction.response.send_message(
            embed=embed,
            view=ItemActionView(self.uid, self.author, iid),
            ephemeral=True,
        )


class PlayerBagView(discord.ui.View):
    def __init__(self, uid: str, author=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.author = author
        self.add_item(PlayerBagSelect(uid, author))


# ── การกระทำต่อไอเทม (ใช้ / โอน / ทิ้ง / ขาย) ────────────────
class ItemActionView(discord.ui.View):
    def __init__(self, uid: str, author, item_id: str):
        super().__init__(timeout=180)
        self.uid = uid
        self.author = author
        self.item_id = item_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="ใช้ 1 ชิ้น", style=discord.ButtonStyle.primary, row=0)
    async def btn_use(self, ix: discord.Interaction, _b):
        await self._do_use(ix, 1)

    @discord.ui.button(label="ใช้ N ชิ้น", style=discord.ButtonStyle.primary, row=0)
    async def btn_use_n(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(ItemUseQtyModal(self.uid, self.author, self.item_id))

    @discord.ui.button(label="โอน", style=discord.ButtonStyle.success, row=1)
    async def btn_transfer(self, ix: discord.Interaction, _b):
        if player_qty(self.uid, self.item_id) < 1:
            await ix.response.send_message("❌ ไม่มีไอเทมนี้แล้ว", ephemeral=True); return
        await ix.response.send_message(
            f"📤 เลือกผู้รับไอเทม **{get_item(self.item_id).get('name','?')}** ↓",
            view=ItemTransferPickerView(self.uid, self.item_id),
            ephemeral=True,
        )

    @discord.ui.button(label="ขาย", style=discord.ButtonStyle.success, row=1)
    async def btn_sell(self, ix: discord.Interaction, _b):
        item = get_item(self.item_id)
        if player_qty(self.uid, self.item_id) < 1:
            await ix.response.send_message("❌ ไม่มีไอเทมนี้แล้ว", ephemeral=True); return
        price = int(item.get("sell_price", 0))
        await ix.response.send_message(
            f"💰 ขาย {item.get('emoji','📦')} **{item.get('name','?')}** ได้ {money_str(price)}/ชิ้น\nเลือกจำนวนที่จะขาย ↓",
            view=ItemQtyActionView(self.uid, self.item_id, action="sell"),
            ephemeral=True,
        )

    @discord.ui.button(label="ทิ้ง", style=discord.ButtonStyle.danger, row=1)
    async def btn_discard(self, ix: discord.Interaction, _b):
        item = get_item(self.item_id)
        if player_qty(self.uid, self.item_id) < 1:
            await ix.response.send_message("❌ ไม่มีไอเทมนี้แล้ว", ephemeral=True); return
        await ix.response.send_message(
            f"🗑️ ทิ้ง {item.get('emoji','📦')} **{item.get('name','?')}** กี่ชิ้น?",
            view=ItemQtyActionView(self.uid, self.item_id, action="discard"),
            ephemeral=True,
        )

    async def _do_use(self, ix: discord.Interaction, qty: int):
        item = get_item(self.item_id)
        have = player_qty(self.uid, self.item_id)
        if have < qty:
            await ix.response.send_message(f"❌ มีไม่พอ (มี {have}, สั่ง {qty})", ephemeral=True); return
        if item.get("type") != "usable":
            await ix.response.send_message(
                f"❌ **{item.get('name','?')}** ไม่ใช่ไอเทมที่กดใช้ได้ "
                f"(เป็น {TYPE_LABELS.get(item.get('type'),'?')})",
                ephemeral=True,
            ); return
        remove_player_item(self.uid, self.item_id, qty)
        effect = item.get("use_effect") or "_(ไม่มีคำอธิบายผล)_"
        embed = discord.Embed(
            title=f"ใช้ {item.get('emoji','📦')} {item.get('name','?')} ×{qty}",
            description=effect,
            color=0x9b59b6,
        )
        if item.get("image_url"):
            embed.set_thumbnail(url=item["image_url"])
        if self.author is not None:
            embed.set_author(name=self.author.display_name, icon_url=self.author.display_avatar.url)
        try:
            await ix.channel.send(embed=embed)
            await ix.response.send_message(f"✅ ใช้ {item.get('name','?')} ×{qty} แล้ว (แสดงในห้อง)", ephemeral=True)
        except Exception:
            await ix.response.send_message(embed=embed, ephemeral=False)


class ItemUseQtyModal(discord.ui.Modal, title="ใช้หลายชิ้นพร้อมกัน"):
    f_qty = discord.ui.TextInput(label="จำนวนที่จะใช้", placeholder="1", max_length=4)

    def __init__(self, uid: str, author, item_id: str):
        super().__init__()
        self.uid = uid
        self.author = author
        self.item_id = item_id
        have = player_qty(uid, item_id)
        self.f_qty.default = "1"
        self.title = f"ใช้ — มีในกระเป๋า ×{have}"

    async def on_submit(self, ix: discord.Interaction):
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        view = ItemActionView(self.uid, self.author, self.item_id)
        await view._do_use(ix, qty)


# ── เลือกจำนวน (ปุ่ม 1/5/10/all) ──
class ItemQtyActionView(discord.ui.View):
    def __init__(self, uid: str, item_id: str, action: str):
        super().__init__(timeout=120)
        self.uid = uid
        self.item_id = item_id
        self.action = action  # "sell" หรือ "discard"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    async def _do(self, ix: discord.Interaction, qty: int):
        have = player_qty(self.uid, self.item_id)
        if qty == -1:   # all
            qty = have
        if qty <= 0:
            await ix.response.send_message("❌ จำนวนต้องมากกว่า 0", ephemeral=True); return
        if have < qty:
            await ix.response.send_message(f"❌ คุณมีแค่ ×{have}", ephemeral=True); return
        item = get_item(self.item_id)
        remove_player_item(self.uid, self.item_id, qty)
        if self.action == "sell":
            price = int(item.get("sell_price", 0)) * qty
            add_money(self.uid, price)
            await ix.response.edit_message(
                content=f"💰 ขาย {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} ได้ {money_str(price)}",
                view=None,
            )
        else:  # discard
            await ix.response.edit_message(
                content=f"🗑️ ทิ้ง {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} แล้ว",
                view=None,
            )

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def b1(self, ix, _b):  await self._do(ix, 1)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary)
    async def b5(self, ix, _b):  await self._do(ix, 5)

    @discord.ui.button(label="10", style=discord.ButtonStyle.secondary)
    async def b10(self, ix, _b): await self._do(ix, 10)

    @discord.ui.button(label="ทั้งหมด", style=discord.ButtonStyle.danger)
    async def ball(self, ix, _b): await self._do(ix, -1)


# ── โอนของ — ผู้รับ via UserSelect ─────────────────────────────
class ItemTransferUserSelect(discord.ui.UserSelect):
    def __init__(self, uid: str, item_id: str):
        self.uid = uid
        self.item_id = item_id
        super().__init__(placeholder="👤 เลือกผู้รับ...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ โอนให้บอทไม่ได้", ephemeral=True); return
        if target.id == int(self.uid):
            await ix.response.send_message("❌ โอนให้ตัวเองไม่ได้", ephemeral=True); return
        await ix.response.edit_message(
            content=f"📤 จะโอนให้ **{target.display_name}** กี่ชิ้น?",
            view=ItemTransferQtyView(self.uid, str(target.id), target.display_name, self.item_id),
        )


class ItemTransferPickerView(discord.ui.View):
    def __init__(self, uid: str, item_id: str):
        super().__init__(timeout=120)
        self.add_item(ItemTransferUserSelect(uid, item_id))


class ItemTransferQtyView(discord.ui.View):
    def __init__(self, sender_uid: str, recv_uid: str, recv_name: str, item_id: str):
        super().__init__(timeout=120)
        self.sender_uid = sender_uid
        self.recv_uid = recv_uid
        self.recv_name = recv_name
        self.item_id = item_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.sender_uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    async def _do(self, ix: discord.Interaction, qty: int):
        have = player_qty(self.sender_uid, self.item_id)
        if qty == -1: qty = have
        if qty <= 0:
            await ix.response.send_message("❌ จำนวนต้องมากกว่า 0", ephemeral=True); return
        if not remove_player_item(self.sender_uid, self.item_id, qty):
            await ix.response.send_message(f"❌ คุณมีแค่ ×{have}", ephemeral=True); return
        add_player_item(self.recv_uid, self.item_id, qty)
        item = get_item(self.item_id)
        await ix.response.edit_message(
            content=(
                f"✅ โอน {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} "
                f"ให้ **{self.recv_name}** สำเร็จ"
            ),
            view=None,
        )
        # แจ้งผู้รับ
        try:
            user = await bot.fetch_user(int(self.recv_uid))
            await user.send(
                f"📦 คุณได้รับ {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} "
                f"จาก <@{self.sender_uid}>"
            )
        except Exception:
            pass

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def b1(self, ix, _b):  await self._do(ix, 1)

    @discord.ui.button(label="5", style=discord.ButtonStyle.primary)
    async def b5(self, ix, _b):  await self._do(ix, 5)

    @discord.ui.button(label="10", style=discord.ButtonStyle.primary)
    async def b10(self, ix, _b): await self._do(ix, 10)

    @discord.ui.button(label="ทั้งหมด", style=discord.ButtonStyle.success)
    async def ball(self, ix, _b): await self._do(ix, -1)


# ── Admin: เลือกไอเทมจาก dropdown แทน type ID ────────────────
_CATALOG_PAGE_SIZE = 23   # เหลือ 2 ช่อง: optional (ไม่ใช้) + page nav


class _CatalogItemSelect(discord.ui.Select):
    """Dropdown ที่แสดงไอเทมใน catalog (paginated) — ใช้ใน admin views"""
    def __init__(self, placeholder: str, *, include_none: bool = False, page: int = 0):
        self.page = page
        self._placeholder_base = placeholder
        self._include_none = include_none
        cat = load_items_catalog()
        items = sorted(cat.items(), key=lambda x: x[1].get("name", x[0]).lower())
        total = len(items)
        max_page = max(0, (total - 1) // _CATALOG_PAGE_SIZE)
        start = page * _CATALOG_PAGE_SIZE
        end = start + _CATALOG_PAGE_SIZE
        page_items = items[start:end]

        options = []
        if include_none:
            options.append(discord.SelectOption(label="(ไม่ใช้)", value="__none__"))
        for iid, it in page_items:
            options.append(discord.SelectOption(
                label=it.get("name", "?")[:100],
                value=iid,
                description=f"{iid} · {money_str(it.get('sell_price',0))}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if page < max_page:
            options.append(discord.SelectOption(
                label="→ หน้าถัดไป",
                value=f"__nextpage__:{page+1}",
                description=f"ดูไอเทมหน้า {page+2}/{max_page+1}",
            ))
        if page > 0:
            options.append(discord.SelectOption(
                label="← หน้าก่อน",
                value=f"__nextpage__:{page-1}",
                description=f"กลับหน้า {page}/{max_page+1}",
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีไอเทม", value="none")]
        ph_suffix = f" (หน้า {page+1}/{max_page+1})" if max_page > 0 else ""
        super().__init__(
            placeholder=f"{placeholder}{ph_suffix}",
            options=options[:25],
            min_values=1, max_values=1,
        )

    def _make_page(self, new_page: int):
        """Subclass override — คืน instance ใหม่ที่ page เปลี่ยน (args อื่นเหมือนเดิม)"""
        return type(self)(placeholder=self._placeholder_base, include_none=self._include_none, page=new_page)

    async def _handle_pagination(self, ix: discord.Interaction) -> bool:
        """check & handle pagination. คืน True ถ้าได้ handle แล้ว"""
        if self.values and self.values[0].startswith("__nextpage__:"):
            new_page = int(self.values[0].split(":", 1)[1])
            view = self.view
            if view is None:
                await ix.response.defer(); return True
            new_self = self._make_page(new_page)
            for child in list(view.children):
                if child is self:
                    view.remove_item(child)
                    view.add_item(new_self)
                    break
            await ix.response.edit_message(view=view)
            return True
        return False


class ItemEditQuickView(discord.ui.View):
    """แก้ไอเทม: เลือกจาก dropdown → modal"""
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ItemEditDropdown())


class ItemEditDropdown(_CatalogItemSelect):
    def __init__(self, page: int = 0):
        super().__init__("เลือกไอเทมที่จะแก้...", page=page)

    def _make_page(self, new_page: int):
        return ItemEditDropdown(page=new_page)

    async def callback(self, ix: discord.Interaction):
        if await self._handle_pagination(ix):
            return
        iid = self.values[0]
        cat = load_items_catalog()
        if iid not in cat:
            await ix.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        modal = ItemEditModal(iid)
        item = cat[iid]
        icon = item.get("image_url") or item.get("emoji", "")
        modal.f_name.default  = item.get("name", "")
        modal.f_icon.default  = icon
        modal.f_desc.default  = item.get("description", "")[:800]
        modal.f_price.default = str(item.get("sell_price", 0))
        await ix.response.send_modal(modal)


class ItemDeleteQuickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ItemDeleteDropdown())


class ItemDeleteDropdown(_CatalogItemSelect):
    def __init__(self, page: int = 0):
        super().__init__("เลือกไอเทมที่จะลบ...", page=page)

    def _make_page(self, new_page: int):
        return ItemDeleteDropdown(page=new_page)

    async def callback(self, ix: discord.Interaction):
        if await self._handle_pagination(ix):
            return
        iid = self.values[0]
        cat = load_items_catalog()
        if iid not in cat:
            await ix.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        removed = cat.pop(iid)
        save_items_catalog(cat)
        await ix.response.edit_message(content=f"ลบไอเทม `{iid}` ({removed.get('name')}) แล้ว", view=None)


class ItemGiveQuickView(discord.ui.View):
    """ให้ไอเทมผู้เล่น: dropdown ไอเทม + UserSelect (หลายคน) + ปุ่มจำนวน"""
    def __init__(self):
        super().__init__(timeout=300)
        self.target_uids = []
        self.target_names = []
        self.item_id = None
        self.add_item(ItemGiveItemDropdown(self))
        self.add_item(ItemGiveUserSelect(self))
        self.add_item(ItemGiveQtyButton(self, 1))
        self.add_item(ItemGiveQtyButton(self, 5))
        self.add_item(ItemGiveQtyButton(self, 10))
        self.add_item(ItemGiveCustomQtyButton(self))


class ItemGiveItemDropdown(_CatalogItemSelect):
    def __init__(self, parent, page: int = 0):
        super().__init__("เลือกไอเทม...", page=page)
        self.parent_view = parent

    def _make_page(self, new_page: int):
        return ItemGiveItemDropdown(self.parent_view, page=new_page)

    async def callback(self, ix: discord.Interaction):
        if await self._handle_pagination(ix):
            return
        self.parent_view.item_id = self.values[0]
        item = get_item(self.values[0])
        await ix.response.send_message(
            f"✅ เลือก {item.get('emoji','📦')} **{item.get('name','?')}** แล้ว — เลือกผู้รับ + กดปุ่มจำนวน",
            ephemeral=True,
        )


class ItemGiveUserSelect(discord.ui.UserSelect):
    def __init__(self, parent):
        super().__init__(placeholder="👤 เลือกผู้รับ (เลือกได้หลายคน)...", min_values=1, max_values=25)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        targets = [u for u in self.values if not u.bot]
        if not targets:
            await ix.response.send_message("❌ ไม่มีผู้รับที่ใช้ได้", ephemeral=True); return
        self.parent_view.target_uids = [str(u.id) for u in targets]
        self.parent_view.target_names = [u.display_name for u in targets]
        await ix.response.send_message(
            f"✅ ผู้รับ: {', '.join(self.parent_view.target_names[:25])}",
            ephemeral=True,
        )


class ItemGiveQtyButton(discord.ui.Button):
    def __init__(self, parent, qty: int):
        super().__init__(label=f"ให้ ×{qty}", style=discord.ButtonStyle.success, row=4)
        self.parent_view = parent
        self.qty = qty

    async def callback(self, ix: discord.Interaction):
        v = self.parent_view
        if not v.item_id or not v.target_uids:
            await ix.response.send_message("❌ ต้องเลือกไอเทม + ผู้รับก่อน", ephemeral=True); return
        await _do_bulk_give(ix, v, self.qty)


class ItemGiveCustomQtyButton(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="กำหนดเอง...", style=discord.ButtonStyle.primary, row=4)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        v = self.parent_view
        if not v.item_id or not v.target_uids:
            await ix.response.send_message("❌ ต้องเลือกไอเทม + ผู้รับก่อน", ephemeral=True); return
        await ix.response.send_modal(ItemGiveCustomQtyModal(v))


class ItemGiveCustomQtyModal(discord.ui.Modal, title="ระบุจำนวน"):
    f_qty = discord.ui.TextInput(label="จำนวนที่จะให้ (แต่ละคน)", placeholder="เช่น 25", max_length=8)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, ix: discord.Interaction):
        qty = _parse_int(self.f_qty.value, 0) or 0
        if qty <= 0:
            await ix.response.send_message("❌ จำนวนต้องมากกว่า 0", ephemeral=True); return
        await _do_bulk_give(ix, self.parent_view, qty)


async def _do_bulk_give(ix, view, qty: int):
    for uid in view.target_uids:
        add_player_item(uid, view.item_id, qty)
    item = get_item(view.item_id)
    await ix.response.send_message(
        f"✅ ให้ {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} ให้ "
        f"{len(view.target_uids)} คน: {', '.join(view.target_names[:25])}",
        ephemeral=True,
    )


# ── Admin Modals (เพิ่มไอเทม + แก้ไอเทม — ยังต้องเป็น modal เพราะกรอกข้อความ) ──
class ItemAddModal(discord.ui.Modal, title="➕ เพิ่มไอเทมใหม่"):
    f_name   = discord.ui.TextInput(label="ชื่อไอเทม", max_length=60)
    f_icon   = discord.ui.TextInput(label="Icon (emoji หรือ URL)", placeholder="🪨 หรือ https://...", required=False, max_length=400)
    f_desc   = discord.ui.TextInput(label="รายละเอียด", style=discord.TextStyle.paragraph, max_length=800)
    f_price  = discord.ui.TextInput(label="ราคาขาย", placeholder="0", max_length=10)
    f_use    = discord.ui.TextInput(
        label="ผลของการใช้ (ว่าง=วัตถุดิบ)",
        placeholder="ระบุข้อความตอนกดใช้",
        style=discord.TextStyle.paragraph,
        required=False, max_length=800,
    )

    async def on_submit(self, interaction: discord.Interaction):
        price = _parse_int(self.f_price.value, 0) or 0
        cat = load_items_catalog()
        iid = _slugify(self.f_name.value)
        if iid in cat:
            iid = f"{iid}_{int(time.time())}"
        emoji, image_url = _normalize_icon(self.f_icon.value)
        use_effect = (self.f_use.value or "").strip()
        cat[iid] = {
            "name":        self.f_name.value.strip(),
            "emoji":       emoji,
            "image_url":   image_url,
            "description": (self.f_desc.value or "").strip(),
            "sell_price":  max(0, price),
            "type":        "usable" if use_effect else "resource",
            "use_effect":  use_effect,
        }
        save_items_catalog(cat)
        await interaction.response.send_message(
            f"✅ เพิ่มไอเทม `{iid}` — {emoji} **{cat[iid]['name']}** ({TYPE_LABELS.get(cat[iid]['type'])})",
            embed=_build_item_embed(iid, cat[iid]),
            ephemeral=True,
        )


class ItemEditModal(discord.ui.Modal, title="✏️ แก้ไขไอเทม"):
    f_name  = discord.ui.TextInput(label="ชื่อใหม่", max_length=60)
    f_icon  = discord.ui.TextInput(label="Icon (emoji หรือ URL)", required=False, max_length=400)
    f_desc  = discord.ui.TextInput(label="รายละเอียด", style=discord.TextStyle.paragraph, max_length=800)
    f_price = discord.ui.TextInput(label="ราคาขาย", max_length=10)
    f_use   = discord.ui.TextInput(
        label="ผลของการใช้ ('-' = ลบทิ้ง)",
        style=discord.TextStyle.paragraph, required=False, max_length=800,
        placeholder="ว่าง = ไม่เปลี่ยน · '-' = ลบทิ้งกลายเป็นวัตถุดิบ",
    )

    def __init__(self, iid: str):
        super().__init__()
        self.iid = iid

    async def on_submit(self, interaction: discord.Interaction):
        cat = load_items_catalog()
        if self.iid not in cat:
            await interaction.response.send_message(f"❌ ไม่พบไอเทม `{self.iid}`", ephemeral=True); return
        if self.f_name.value.strip():
            cat[self.iid]["name"] = self.f_name.value.strip()
        if self.f_icon.value.strip():
            emoji, image_url = _normalize_icon(self.f_icon.value)
            cat[self.iid]["emoji"] = emoji
            cat[self.iid]["image_url"] = image_url
        if self.f_desc.value.strip():
            cat[self.iid]["description"] = self.f_desc.value.strip()
        if self.f_price.value.strip():
            p = _parse_int(self.f_price.value)
            if p is not None: cat[self.iid]["sell_price"] = max(0, p)
        use_val = (self.f_use.value or "").strip()
        if use_val == "-":
            cat[self.iid]["use_effect"] = ""
            if cat[self.iid].get("type") == "usable":
                cat[self.iid]["type"] = "resource"
        elif use_val:
            cat[self.iid]["use_effect"] = use_val
            if cat[self.iid].get("type") != "craft":
                cat[self.iid]["type"] = "usable"
        save_items_catalog(cat)
        await interaction.response.send_message(
            f"✅ อัปเดต `{self.iid}` แล้ว",
            embed=_build_item_embed(self.iid, cat[self.iid]),
            ephemeral=True,
        )


# ── Admin: ดู + จัดการกระเป๋าผู้เล่น ──────────────────────────
def _admin_player_bag_embed(uid: str, member) -> discord.Embed:
    cat = load_items_catalog()
    inv = get_player_inv(uid)
    wallet = get_wallet(uid)
    cfg = load_currency_cfg()
    embed = discord.Embed(
        title=f"🔧  คลังของ {member.display_name}",
        description=f"{cfg['emoji']} **{wallet:,}** {cfg['name']} · 📦 **{len(inv)}** ชนิด\n_เลือกไอเทมจาก dropdown เพื่อ ลบ/ปรับ qty_",
        color=0xe74c3c,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if inv:
        lines = []
        for entry in inv[:25]:
            it = cat.get(entry["item_id"], {})
            lines.append(f"{it.get('emoji','📦')} **{it.get('name', entry['item_id'])}** ×{entry.get('qty',1)} `{entry['item_id']}`")
        embed.add_field(name="📋 รายการ", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="📋 รายการ", value="_ว่าง_", inline=False)
    embed.set_footer(text=f"User ID: {uid}")
    return embed


class AdminInvPullModal(discord.ui.Modal, title="🔧 ปรับจำนวน / ดึงออก"):
    f_qty = discord.ui.TextInput(label="จำนวน (+ เพิ่ม / − ดึงออก / 0 = ลบทั้งหมด)", placeholder="-1", max_length=8)

    def __init__(self, uid: str, member, item_id: str):
        super().__init__()
        self.uid = uid
        self.member = member
        self.item_id = item_id
        have = next((int(x.get("qty", 0)) for x in get_player_inv(uid) if x.get("item_id") == item_id), 0)
        self.f_qty.default = "-1"
        self.title = f"🔧 ปรับ {item_id} (มี ×{have})"

    async def on_submit(self, ix: discord.Interaction):
        from orion_items import add_player_item as _add, remove_player_item as _rm
        delta = _parse_int(self.f_qty.value, 0) or 0
        item = get_item(self.item_id)
        name = item.get("name", self.item_id)
        if delta == 0:
            # ลบทั้งหมด
            data = load_orion_players()
            inv = data.get(self.uid, {}).get("inv", [])
            data[self.uid]["inv"] = [x for x in inv if x.get("item_id") != self.item_id]
            save_orion_players(data)
            msg = f"🗑️ ลบ **{name}** ทั้งหมดของ **{self.member.display_name}**"
        elif delta > 0:
            _add(self.uid, self.item_id, delta)
            msg = f"➕ เพิ่ม **{name}** ×{delta} ให้ **{self.member.display_name}**"
        else:
            ok = _rm(self.uid, self.item_id, abs(delta))
            if not ok:
                await ix.response.send_message(f"❌ มีไม่พอจะดึงออก {abs(delta)}", ephemeral=True); return
            msg = f"📤 ดึง **{name}** ×{abs(delta)} ออกจาก **{self.member.display_name}**"
        await ix.response.edit_message(
            content=msg,
            embed=_admin_player_bag_embed(self.uid, self.member),
            view=AdminPlayerBagView(self.uid, self.member),
        )


class AdminPlayerBagSelect(discord.ui.Select):
    def __init__(self, uid: str, member):
        self.uid = uid
        self.member = member
        inv = get_player_inv(uid)[:25]
        cat = load_items_catalog()
        options = []
        for entry in inv:
            it = cat.get(entry["item_id"], {})
            options.append(discord.SelectOption(
                label=f"{it.get('name', entry['item_id'])} (×{entry.get('qty',1)})"[:100],
                value=entry["item_id"],
                description=f"item_id: {entry['item_id']}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="กระเป๋าว่าง", value="none")]
        super().__init__(placeholder="🔧 เลือกไอเทมเพื่อปรับ qty / ดึงออก...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(AdminInvPullModal(self.uid, self.member, self.values[0]))


class AdminPlayerBagView(discord.ui.View):
    def __init__(self, uid: str, member):
        super().__init__(timeout=300)
        self.uid = uid
        self.member = member
        self.add_item(AdminPlayerBagSelect(uid, member))

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ให้ไอเทมเพิ่ม", style=discord.ButtonStyle.success, row=1)
    async def b_add(self, ix, _b):
        await ix.response.send_message("📦 เลือกไอเทมจาก catalog ↓", view=AdminAddItemToPlayerView(self.uid, self.member), ephemeral=True)

    @discord.ui.button(label="ล้างกระเป๋าทั้งหมด", style=discord.ButtonStyle.danger, row=1)
    async def b_clear(self, ix, _b):
        view = discord.ui.View(timeout=60)

        class _YesBtn(discord.ui.Button):
            def __init__(this):
                super().__init__(label="ยืนยันล้าง", style=discord.ButtonStyle.danger)
            async def callback(this, ix2):
                data = load_orion_players()
                data.setdefault(self.uid, {})["inv"] = []
                save_orion_players(data)
                await ix2.response.edit_message(content=f"💥 ล้างกระเป๋าของ **{self.member.display_name}** แล้ว", view=None)

        class _NoBtn(discord.ui.Button):
            def __init__(this):
                super().__init__(label="ยกเลิก", style=discord.ButtonStyle.secondary)
            async def callback(this, ix2):
                await ix2.response.edit_message(content="❌ ยกเลิก", view=None)

        view.add_item(_YesBtn()); view.add_item(_NoBtn())
        await ix.response.send_message(
            f"⚠️ ล้างกระเป๋าของ **{self.member.display_name}** ทั้งหมด?", view=view, ephemeral=True,
        )


class AdminAddItemToPlayerView(discord.ui.View):
    def __init__(self, uid: str, member):
        super().__init__(timeout=180)
        self.uid = uid
        self.member = member
        self.add_item(_AdminAddItemSelect(self))


class _AdminAddItemSelect(_CatalogItemSelect):
    def __init__(self, parent, page: int = 0):
        super().__init__("เลือกไอเทมจะให้...", page=page)
        self.parent_view = parent

    def _make_page(self, new_page: int):
        return _AdminAddItemSelect(self.parent_view, page=new_page)

    async def callback(self, ix: discord.Interaction):
        if await self._handle_pagination(ix):
            return
        await ix.response.send_modal(_AdminGiveQtyModal(self.parent_view.uid, self.parent_view.member, self.values[0]))


class _AdminGiveQtyModal(discord.ui.Modal, title="➕ ระบุจำนวน"):
    f_qty = discord.ui.TextInput(label="จำนวน", placeholder="1", max_length=6)

    def __init__(self, uid: str, member, item_id: str):
        super().__init__()
        self.uid = uid
        self.member = member
        self.item_id = item_id
        self.f_qty.default = "1"

    async def on_submit(self, ix: discord.Interaction):
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        add_player_item(self.uid, self.item_id, qty)
        item = get_item(self.item_id)
        await ix.response.edit_message(
            content=f"✅ ให้ {item.get('emoji','📦')} **{item.get('name','?')}** ×{qty} กับ **{self.member.display_name}**",
            embed=_admin_player_bag_embed(self.uid, self.member),
            view=AdminPlayerBagView(self.uid, self.member),
        )


class AdminBagUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="🔧 เลือกผู้เล่นที่จะดู/จัดการคลัง...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ไม่ใช่ผู้เล่น", ephemeral=True); return
        uid = str(target.id)
        ensure_orion_player(uid)
        await ix.response.send_message(
            embed=_admin_player_bag_embed(uid, target),
            view=AdminPlayerBagView(uid, target),
            ephemeral=True,
        )


class AdminBagUserPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(AdminBagUserSelect())


class ItemAdminView(discord.ui.View):
    """ReQuest-style: Main → Catalog/Distribution subviews"""
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def btn_done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="Catalog", style=discord.ButtonStyle.primary, row=1)
    async def btn_catalog(self, ix, _b):
        cat = load_items_catalog()
        embed = discord.Embed(
            title="Item Catalog",
            description=(
                f"_ไอเทมในระบบ_  `{len(cat)}` _รายการ_\n\n"
                "**เพิ่มไอเทม**\n"
                "สร้างไอเทมใหม่ในระบบ — ชื่อ / icon / รายละเอียด / ราคา / use effect\n\n"
                "**แก้ไขไอเทม**\n"
                "เลือกไอเทมจาก dropdown แล้วแก้ค่าต่างๆ\n\n"
                "**ลบไอเทม**\n"
                "ลบไอเทมออกจาก catalog ถาวร\n\n"
                "**ดูคลังไอเทม**\n"
                "แสดงรายการไอเทมทั้งหมด แยกตามประเภท\n\n"
                "**Import / Export JSON**\n"
                "`/ไอเทมดาวน์โหลด` ดาวน์โหลด · `/ไอเทมอัปโหลด` อัปกลับ"
            ),
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=ItemCatalogSubView())

    @discord.ui.button(label="Distribution", style=discord.ButtonStyle.primary, row=2)
    async def btn_dist(self, ix, _b):
        embed = discord.Embed(
            title="Item Distribution",
            description=(
                "**ให้ไอเทม (หลายคน)**\n"
                "เลือกไอเทม + ผู้รับ (สูงสุด 25 คน) + กำหนดจำนวน — แจกพร้อมกัน\n\n"
                "**จัดการคลังผู้เล่น**\n"
                "ดูของในคลังของผู้เล่น · เพิ่ม / ลด / ดึงออก / ล้างทั้งคลัง"
            ),
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=ItemDistSubView())


class ItemCatalogSubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, ix, _b):
        cat = load_items_catalog()
        embed = discord.Embed(
            title="Item Admin — Main Menu",
            description=(
                f"_ไอเทมในระบบ_  `{len(cat)}` _รายการ_\n\n"
                "**Catalog**\nเพิ่ม / แก้ / ลบไอเทมใน catalog · ดูรายการทั้งหมด · นำเข้า JSON\n\n"
                "**Distribution**\nแจกไอเทมให้ผู้เล่น (เลือกหลายคนได้) · ปรับ/ดึงไอเทมในคลังผู้เล่น"
            ),
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=ItemAdminView())

    @discord.ui.button(label="เพิ่มไอเทม", style=discord.ButtonStyle.success, row=1)
    async def b1(self, ix, _b):
        await ix.response.send_modal(ItemAddModal())

    @discord.ui.button(label="แก้ไขไอเทม", style=discord.ButtonStyle.primary, row=2)
    async def b2(self, ix, _b):
        await ix.response.send_message("เลือกไอเทมที่จะแก้จาก dropdown", view=ItemEditQuickView(), ephemeral=True)

    @discord.ui.button(label="ลบไอเทม", style=discord.ButtonStyle.danger, row=3)
    async def b3(self, ix, _b):
        await ix.response.send_message("เลือกไอเทมที่จะลบจาก dropdown", view=ItemDeleteQuickView(), ephemeral=True)

    @discord.ui.button(label="ดูคลังไอเทม", style=discord.ButtonStyle.secondary, row=4)
    async def b4(self, ix, _b):
        await ix.response.send_message(embed=_items_overview_embed(), view=ItemCatalogView(), ephemeral=True)


class ItemDistSubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, ix, _b):
        cat = load_items_catalog()
        embed = discord.Embed(
            title="Item Admin — Main Menu",
            description=(
                f"_ไอเทมในระบบ_  `{len(cat)}` _รายการ_\n\n"
                "**Catalog**\nเพิ่ม / แก้ / ลบไอเทมใน catalog · ดูรายการทั้งหมด · นำเข้า JSON\n\n"
                "**Distribution**\nแจกไอเทมให้ผู้เล่น (เลือกหลายคนได้) · ปรับ/ดึงไอเทมในคลังผู้เล่น"
            ),
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=ItemAdminView())

    @discord.ui.button(label="ให้ไอเทม (หลายคน)", style=discord.ButtonStyle.success, row=1)
    async def b1(self, ix, _b):
        await ix.response.send_message("เลือกไอเทม + ผู้รับ (หลายคนได้) + จำนวน", view=ItemGiveQuickView(), ephemeral=True)

    @discord.ui.button(label="จัดการคลังผู้เล่น", style=discord.ButtonStyle.danger, row=2)
    async def b2(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะดู/จัดการคลัง", view=AdminBagUserPickerView(), ephemeral=True)


# ── Slash Commands ───────────────────────────────────────────
# ── JSON import/export ───────────────────────────────────────
import io as _io
import json as _json


@bot.tree.command(name="ไอเทมดาวน์โหลด", description="[Admin] ดาวน์โหลด items.json", guild=_ORION_GUILD_OBJ)
async def cmd_items_download(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    data = load_items_catalog()
    s = _json.dumps(data, ensure_ascii=False, indent=2)
    fp = _io.BytesIO(s.encode("utf-8"))
    file = discord.File(fp, filename="items.json")
    await interaction.response.send_message(
        "📥 ไฟล์ catalog ไอเทม — แก้ตรงๆ แล้วใช้ `/ไอเทมอัปโหลด` อัปกลับ\n"
        "_schema:_ `{ \"<id>\": {name, emoji, image_url, description, sell_price, type, use_effect} }`",
        file=file, ephemeral=True,
    )


@bot.tree.command(name="ไอเทมอัปโหลด", description="[Admin] อัปโหลด items.json (merge ทับของเดิม)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(file="ไฟล์ items.json", mode="merge = รวมกับของเดิม / replace = ทับทั้งหมด")
async def cmd_items_upload(interaction: discord.Interaction, file: discord.Attachment, mode: str = "merge"):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    if not file.filename.lower().endswith(".json"):
        await interaction.response.send_message("❌ ต้องเป็น .json", ephemeral=True); return
    raw = await file.read()
    try:
        data = _json.loads(raw.decode("utf-8"))
    except Exception as e:
        await interaction.response.send_message(f"❌ JSON parse error: `{e}`", ephemeral=True); return
    if not isinstance(data, dict):
        await interaction.response.send_message("❌ JSON ต้องเป็น dict (`{id: item, ...}`)", ephemeral=True); return
    mode = (mode or "merge").lower()
    if mode == "replace":
        save_items_catalog(data)
        n = len(data)
        msg = f"✅ replace catalog แล้ว — รวม {n} ไอเทม"
    else:
        cat = load_items_catalog()
        added, updated = 0, 0
        for iid, item in data.items():
            if iid in cat:
                cat[iid].update(item)
                updated += 1
            else:
                cat[iid] = item
                added += 1
        save_items_catalog(cat)
        msg = f"✅ merge แล้ว — เพิ่ม {added} · อัปเดต {updated} · รวม {len(cat)}"
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="คลังไอเทม", description="ดูไอเทมทั้งหมดที่มีในเซิร์ฟ", guild=_ORION_GUILD_OBJ)
async def cmd_items_catalog(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    cooldown = _get_search_cooldown()
    if cooldown > 0:
        now = time.time()
        last = _search_cooldowns.get(uid, 0)
        remaining = cooldown - (now - last)
        if remaining > 0:
            mins, secs = divmod(int(remaining), 60)
            cd_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            await interaction.response.send_message(
                f"⏳ รอ **{cd_str}** ก่อนค้นหาอีกครั้ง", ephemeral=True
            ); return
        _search_cooldowns[uid] = now
    await interaction.response.send_message(
        embed=_items_overview_embed(),
        view=ItemCatalogView(),
        ephemeral=_eph("คลังไอเทม"),
    )


@bot.tree.command(name="ไอเทม", description="ดูกระเป๋าเงิน + ไอเทมของคุณ (ใช้/โอน/ทิ้ง/ขายได้)", guild=_ORION_GUILD_OBJ)
async def cmd_my_bag(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    await interaction.response.send_message(
        embed=_player_bag_embed(uid, interaction.user),
        view=PlayerBagView(uid, interaction.user),
        ephemeral=_eph("ไอเทม"),
    )


@bot.tree.command(name="ไอเทมแอดมิน", description="[Admin] จัดการคลังไอเทม", guild=_ORION_GUILD_OBJ)
async def cmd_items_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    cat = load_items_catalog()
    embed = discord.Embed(
        title="Item Admin — Main Menu",
        description=(
            f"_ไอเทมในระบบ_  `{len(cat)}` _รายการ_\n\n"
            "**Catalog**\n"
            "เพิ่ม / แก้ / ลบไอเทมใน catalog · ดูรายการทั้งหมด · นำเข้า JSON\n\n"
            "**Distribution**\n"
            "แจกไอเทมให้ผู้เล่น (เลือกหลายคนได้) · ปรับ/ดึงไอเทมในคลังผู้เล่น"
        ),
        color=0x3498db,
    )
    await interaction.response.send_message(embed=embed, view=ItemAdminView(), ephemeral=True)


# ── เช็คของ / โอนของ ─────────────────────────────────────────
@bot.tree.command(name="เช็คของ", description="ดูไอเทมในกระเป๋าของผู้เล่นคนอื่น (หรือของตัวเอง)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(target="ผู้เล่นที่จะดู — ว่าง = ดูของตัวเอง")
async def cmd_check_items(interaction: discord.Interaction, target: discord.Member = None):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    target = target or interaction.user
    if target.bot:
        await interaction.response.send_message("❌ ดูของบอทไม่ได้", ephemeral=True); return
    await interaction.response.send_message(
        embed=_player_bag_embed(str(target.id), target),
        ephemeral=_eph("เช็คของ"),
    )


@bot.tree.command(name="โอนของ", description="โอนไอเทมให้ผู้เล่นคนอื่น (เลือกผู้รับจาก dropdown)", guild=_ORION_GUILD_OBJ)
async def cmd_transfer_item(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    inv = get_player_inv(uid)
    if not inv:
        await interaction.response.send_message("❌ กระเป๋าว่าง ไม่มีอะไรให้โอน", ephemeral=True); return
    await interaction.response.send_message(
        "📤 เลือกไอเทมที่จะโอนจาก dropdown ↓ (จะถามผู้รับและจำนวนต่อ)",
        view=PlayerBagView(uid, interaction.user),
        ephemeral=_eph("โอนของ"),
    )
