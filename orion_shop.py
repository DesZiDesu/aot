# ============================================================
# ORION — Shop / Black Market System
# ============================================================
# - ตั้งร้านในห้อง / เธรด / ฟอรั่ม (admin ตั้ง channel_id)
# - ของในร้านเป็น JSON แก้ตรงๆ ได้ (มีปุ่ม download / อัปโหลด)
# - ระบบ coupon (% off, เลือกหมวดได้)
# - ระบบ gift — ซื้อให้คนอื่น (UserSelect)
# - หมวดหมู่ของในร้านตั้งได้
# - ถ้าซื้อแล้วของไม่มีใน catalog → auto-create
# ============================================================

import io
import sys
import time
import json
import discord

# ── dependencies ──────────────────────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_shop ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_currency_cfg    = _orion_bot_mod.load_currency_cfg
money_str            = _orion_bot_mod.money_str
get_wallet           = _orion_bot_mod.get_wallet
add_money            = _orion_bot_mod.add_money
_parse_int           = _orion_bot_mod._parse_int

import orion_items


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="📦"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


SHOP_CFG_FILE     = f"{ORION_DATA_DIR}/shop_config.json"
SHOP_CATALOG_FILE = f"{ORION_DATA_DIR}/shop_catalog.json"
COUPONS_FILE      = f"{ORION_DATA_DIR}/shop_coupons.json"


# ── Default content (sample items + coupons) ─────────────────
DEFAULT_SHOP_CFG = {
    "shop_channel_id": 0,        # 0 = ใช้ได้ทุกห้อง
    "allowed_role_ids": [],      # role ที่จัดการร้านได้ (นอกจาก admin)
}

DEFAULT_SHOP_CATALOG = {
    "categories": [
        {"id": "consumable", "name": "ของกินใช้",  "emoji": "🧪"},
        {"id": "equipment",  "name": "อุปกรณ์",   "emoji": "⚔️"},
        {"id": "material",   "name": "วัตถุดิบ",  "emoji": "🪨"},
        {"id": "rare",       "name": "ของหายาก", "emoji": "💎"},
    ],
    "items": [
        {
            "shop_id": "small_potion",
            "item_id": "small_potion",
            "name": "Small Potion",
            "emoji": "🧪",
            "image_url": "",
            "description": "ยาฟื้นพลังขนาดเล็ก — กดใช้เพื่อฟื้นพลังกายเล็กน้อย",
            "price": 50,
            "stock": -1,
            "category": "consumable",
            "item_type": "usable",
            "use_effect": "ฟื้นพลังกาย +10 (เล่าเป็นบทบาท)",
        },
        {
            "shop_id": "iron_sword",
            "item_id": "iron_sword",
            "name": "Iron Sword",
            "emoji": "⚔️",
            "image_url": "",
            "description": "ดาบเหล็กกล้าธรรมดา ใช้ในการต่อสู้ระยะประชิด",
            "price": 250,
            "stock": 5,
            "category": "equipment",
            "item_type": "resource",
        },
        {
            "shop_id": "map_fragment",
            "item_id": "map_fragment",
            "name": "Map Fragment",
            "emoji": "🗺️",
            "image_url": "",
            "description": "เศษแผนที่เก่าๆ พบในซากปรักหักพัง",
            "price": 30,
            "stock": -1,
            "category": "material",
            "item_type": "resource",
        },
        {
            "shop_id": "phoenix_feather",
            "item_id": "phoenix_feather",
            "name": "Phoenix Feather",
            "emoji": "🪶",
            "image_url": "",
            "description": "ขนนกฟีนิกซ์ที่หาได้ยากยิ่ง ใช้คราฟไอเทมระดับสูง",
            "price": 1500,
            "stock": 1,
            "category": "rare",
            "item_type": "resource",
        },
    ],
}

DEFAULT_COUPONS = {
    "WELCOME10": {
        "code": "WELCOME10",
        "discount_pct": 10,
        "categories": [],          # ว่าง = ทุกหมวด
        "uses_left": 100,          # -1 = ไม่จำกัด
        "expires_at": 0,           # 0 = ไม่หมดอายุ
        "description": "ลด 10% ทุกหมวด สำหรับสมาชิกใหม่"
    },
    "POTION50": {
        "code": "POTION50",
        "discount_pct": 50,
        "categories": ["consumable"],
        "uses_left": 30,
        "expires_at": 0,
        "description": "ลด 50% เฉพาะหมวดของกินใช้"
    }
}


# ── Storage ──────────────────────────────────────────────────
def load_shop_cfg() -> dict:
    cfg = load_json(SHOP_CFG_FILE, {})
    changed = False
    for k, v in DEFAULT_SHOP_CFG.items():
        if k not in cfg:
            cfg[k] = v; changed = True
    if changed:
        save_shop_cfg(cfg)
    return cfg


def save_shop_cfg(cfg):
    save_json(SHOP_CFG_FILE, cfg)


def load_shop_catalog() -> dict:
    data = load_json(SHOP_CATALOG_FILE, None)
    if not data:
        data = json.loads(json.dumps(DEFAULT_SHOP_CATALOG))
        save_shop_catalog(data)
    return data


def save_shop_catalog(data: dict):
    save_json(SHOP_CATALOG_FILE, data)


def load_coupons() -> dict:
    data = load_json(COUPONS_FILE, None)
    if not data:
        data = json.loads(json.dumps(DEFAULT_COUPONS))
        save_coupons(data)
    return data


def save_coupons(data):
    save_json(COUPONS_FILE, data)


# ── Helpers ──────────────────────────────────────────────────
def can_manage_shop(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    cfg = load_shop_cfg()
    allowed = set(cfg.get("allowed_role_ids", []))
    if not allowed:
        return False
    return bool({r.id for r in member.roles} & allowed)


def get_shop_item(shop_id: str) -> dict:
    data = load_shop_catalog()
    for it in data.get("items", []):
        if it.get("shop_id") == shop_id:
            return it
    return {}


def ensure_shop_item_in_catalog(shop_item: dict) -> str:
    """sync shop_item → orion_items catalog; คืน item_id"""
    cat = orion_items.load_items_catalog()
    iid = shop_item.get("item_id") or shop_item.get("shop_id")
    if not iid:
        return ""
    if iid not in cat:
        cat[iid] = {
            "name":        shop_item.get("name", "?"),
            "emoji":       shop_item.get("emoji", "📦"),
            "image_url":   shop_item.get("image_url", ""),
            "description": shop_item.get("description", ""),
            "sell_price":  max(0, int(shop_item.get("price", 0)) // 2),
            "type":        shop_item.get("item_type", "resource"),
            "use_effect":  shop_item.get("use_effect", ""),
        }
        orion_items.save_items_catalog(cat)
    return iid


def apply_coupon(code: str, item_category: str, base_total: int):
    """คืน (final_total, coupon_dict_or_None, error_msg_or_None)"""
    if not code:
        return base_total, None, None
    code = code.strip().upper()
    coupons = load_coupons()
    c = coupons.get(code)
    if not c:
        return base_total, None, f"❌ ไม่พบคูปอง `{code}`"
    uses = int(c.get("uses_left", -1))
    if uses == 0:
        return base_total, None, "❌ คูปองนี้ใช้หมดแล้ว"
    exp = int(c.get("expires_at", 0))
    if exp and time.time() > exp:
        return base_total, None, "❌ คูปองหมดอายุ"
    cats = c.get("categories", [])
    if cats and item_category not in cats:
        return base_total, None, f"❌ คูปองนี้ใช้กับหมวด `{item_category}` ไม่ได้"
    pct = max(0, min(100, int(c.get("discount_pct", 0))))
    new_total = max(0, base_total * (100 - pct) // 100)
    return new_total, c, None


# ── Embeds ───────────────────────────────────────────────────
def _shop_overview_embed(category_id: str = None) -> discord.Embed:
    data = load_shop_catalog()
    categories = data.get("categories", [])
    items = data.get("items", [])
    if category_id:
        items = [it for it in items if it.get("category") == category_id]
        cat_meta = next((c for c in categories if c["id"] == category_id), {})
        title = f"ร้านค้า — {cat_meta.get('name', category_id)}"
    else:
        title = "ร้านค้า"
    embed = discord.Embed(
        title=title,
        description="_เลือกหมวด → เลือกไอเทม → ซื้อให้ตัวเองหรือเป็นของขวัญ_",
        color=0xe67e22,
    )
    if not items:
        embed.add_field(name="​", value="_ไม่มีของในหมวดนี้_", inline=False)
    else:
        lines = []
        for it in items[:15]:
            stock = it.get("stock", -1)
            stock_text = "∞" if stock < 0 else f"×{stock}"
            lines.append(
                f"{it.get('emoji','📦')} **{it.get('name','?')}** — {money_str(it.get('price',0))} · stock `{stock_text}`"
            )
        embed.add_field(name="​", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"{len(data.get('items',[]))} ไอเทม · {len(categories)} หมวด · /คูปอง")
    return embed


def _item_detail_embed(it: dict, qty: int = 1, coupon_code: str = "", gift_recipient: str = "") -> discord.Embed:
    base = int(it.get("price", 0)) * qty
    final, coupon, err = apply_coupon(coupon_code, it.get("category", ""), base)
    embed = discord.Embed(
        title=f"{it.get('emoji','📦')}  {it.get('name','?')}",
        description=it.get("description","")[:600] or "_ไม่มีคำอธิบาย_",
        color=0xe67e22,
    )
    if it.get("image_url"):
        embed.set_image(url=it["image_url"])
    embed.add_field(name="ราคา/ชิ้น", value=money_str(it.get("price",0)), inline=True)
    stock = it.get("stock", -1)
    embed.add_field(name="Stock", value=("∞" if stock < 0 else f"`×{stock}`"), inline=True)
    embed.add_field(name="หมวด", value=f"`{it.get('category','-')}`", inline=True)
    embed.add_field(name="จำนวน", value=f"`×{qty}`", inline=True)
    if coupon and not err:
        embed.add_field(name="คูปอง", value=f"`{coupon['code']}` −{coupon['discount_pct']}%", inline=True)
    elif err:
        embed.add_field(name="คูปอง", value=err, inline=True)
    if gift_recipient:
        embed.add_field(name="ของขวัญให้", value=f"<@{gift_recipient}>", inline=True)
    total_line = (
        f"~~{money_str(base)}~~  →  **{money_str(final)}**"
        if coupon and not err else f"**{money_str(final)}**"
    )
    embed.add_field(name="ยอดรวม", value=total_line, inline=False)
    embed.set_footer(text="กดปุ่มยืนยันด้านล่าง")
    return embed


# ── Buy session view (state-holding) ─────────────────────────
class BuySessionView(discord.ui.View):
    def __init__(self, uid: str, shop_id: str):
        super().__init__(timeout=300)
        self.uid = uid
        self.shop_id = shop_id
        self.qty = 1
        self.coupon_code = ""
        self.gift_recipient = ""   # uid string of recipient, "" = ซื้อให้ตัวเอง
        self.add_item(BuyGiftUserSelect(self))

    async def interaction_check(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    async def refresh(self, ix: discord.Interaction):
        it = get_shop_item(self.shop_id)
        await ix.response.edit_message(
            embed=_item_detail_embed(it, self.qty, self.coupon_code, self.gift_recipient),
            view=self,
        )

    @discord.ui.button(label="−", style=discord.ButtonStyle.secondary, row=1)
    async def b_dec(self, ix, _b):
        self.qty = max(1, self.qty - 1)
        await self.refresh(ix)

    @discord.ui.button(label="+", style=discord.ButtonStyle.secondary, row=1)
    async def b_inc(self, ix, _b):
        it = get_shop_item(self.shop_id)
        stock = int(it.get("stock", -1))
        if stock >= 0 and self.qty + 1 > stock:
            await ix.response.send_message(f"❌ Stock เหลือแค่ {stock}", ephemeral=True); return
        self.qty += 1
        await self.refresh(ix)

    @discord.ui.button(label="x5", style=discord.ButtonStyle.secondary, row=1)
    async def b_x5(self, ix, _b):
        it = get_shop_item(self.shop_id)
        stock = int(it.get("stock", -1))
        new_q = self.qty + 5
        if stock >= 0 and new_q > stock:
            new_q = stock
        self.qty = max(1, new_q)
        await self.refresh(ix)

    @discord.ui.button(label="ใส่คูปอง", style=discord.ButtonStyle.primary, row=2)
    async def b_coupon(self, ix, _b):
        await ix.response.send_modal(CouponInputModal(self))

    @discord.ui.button(label="ยืนยันซื้อ", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def b_buy(self, ix, _b):
        await self._do_purchase(ix)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.danger, row=2)
    async def b_cancel(self, ix, _b):
        await ix.response.edit_message(content="❌ ยกเลิก", embed=None, view=None)

    async def _do_purchase(self, ix: discord.Interaction):
        it = get_shop_item(self.shop_id)
        if not it:
            await ix.response.send_message("❌ ไม่พบไอเทมในร้าน", ephemeral=True); return
        stock = int(it.get("stock", -1))
        if stock >= 0 and self.qty > stock:
            await ix.response.send_message(f"❌ Stock เหลือ {stock} (สั่ง {self.qty})", ephemeral=True); return
        base = int(it.get("price", 0)) * self.qty
        final, coupon, err = apply_coupon(self.coupon_code, it.get("category",""), base)
        if err:
            await ix.response.send_message(err, ephemeral=True); return
        # check เงินผู้ซื้อ
        if get_wallet(self.uid) < final:
            await ix.response.send_message(
                f"❌ เงินไม่พอ ({money_str(get_wallet(self.uid))} / {money_str(final)})",
                ephemeral=True,
            ); return
        # หักเงิน
        add_money(self.uid, -final)
        # ลด stock
        if stock >= 0:
            data = load_shop_catalog()
            for x in data.get("items", []):
                if x.get("shop_id") == self.shop_id:
                    x["stock"] = max(0, int(x.get("stock", 0)) - self.qty)
                    break
            save_shop_catalog(data)
        # decrement coupon
        if coupon and int(coupon.get("uses_left", -1)) > 0:
            coupons = load_coupons()
            coupons[coupon["code"]]["uses_left"] = int(coupons[coupon["code"]]["uses_left"]) - 1
            save_coupons(coupons)
        # add item
        recv_uid = self.gift_recipient or self.uid
        iid = ensure_shop_item_in_catalog(it)
        orion_items.add_player_item(recv_uid, iid, self.qty)
        # ตอบ
        title = "🎁 ส่งของขวัญสำเร็จ" if self.gift_recipient else "🛒 ซื้อสำเร็จ"
        desc = (
            f"{it.get('emoji','📦')} **{it.get('name','?')}** ×{self.qty}\n"
            f"จ่าย: {money_str(final)}"
        )
        if coupon:
            desc += f" _(ใช้คูปอง `{coupon['code']}` -{coupon['discount_pct']}%)_"
        if self.gift_recipient:
            desc += f"\nผู้รับ: <@{self.gift_recipient}>"
        embed = discord.Embed(title=title, description=desc, color=0x2ecc71)
        await ix.response.edit_message(content="", embed=embed, view=None)
        # แจ้ง recipient ถ้าเป็นของขวัญ
        if self.gift_recipient and self.gift_recipient != self.uid:
            try:
                user = await bot.fetch_user(int(self.gift_recipient))
                await user.send(
                    f"🎁 คุณได้รับของขวัญ {it.get('emoji','📦')} **{it.get('name','?')}** ×{self.qty} "
                    f"จาก <@{self.uid}>"
                )
            except Exception:
                pass


class BuyGiftUserSelect(discord.ui.UserSelect):
    def __init__(self, parent: BuySessionView):
        super().__init__(placeholder="🎁 เลือกผู้รับของขวัญ (ว่าง = ซื้อให้ตัวเอง)...", min_values=0, max_values=1, row=0)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        if not self.values:
            self.parent_view.gift_recipient = ""
        else:
            target = self.values[0]
            if target.bot:
                await ix.response.send_message("❌ ให้ของขวัญบอทไม่ได้", ephemeral=True); return
            self.parent_view.gift_recipient = str(target.id)
        await self.parent_view.refresh(ix)


class CouponInputModal(discord.ui.Modal, title="🎫 ใส่คูปอง"):
    f_code = discord.ui.TextInput(label="โค้ดคูปอง", max_length=30)

    def __init__(self, parent: BuySessionView):
        super().__init__()
        self.parent_view = parent

    async def on_submit(self, ix: discord.Interaction):
        self.parent_view.coupon_code = self.f_code.value.strip().upper()
        await self.parent_view.refresh(ix)


# ── Browse view (player) ─────────────────────────────────────
class ShopCategorySelect(discord.ui.Select):
    def __init__(self, uid: str, current: str = None):
        self.uid = uid
        data = load_shop_catalog()
        options = [discord.SelectOption(label="ทุกหมวด", value="__all__", default=(current is None))]
        for c in data.get("categories", [])[:24]:
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                emoji=_safe_emoji(c.get("emoji")),
                default=(c["id"] == current),
            ))
        super().__init__(placeholder="🏷️ เลือกหมวด...", options=options, row=0)

    async def callback(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        cat = self.values[0]
        cat_id = None if cat == "__all__" else cat
        await ix.response.edit_message(
            embed=_shop_overview_embed(cat_id),
            view=ShopBrowseView(self.uid, cat_id),
        )


class ShopItemSelect(discord.ui.Select):
    def __init__(self, uid: str, category: str = None, page: int = 0):
        self.uid = uid
        self.category = category
        self.page = page
        data = load_shop_catalog()
        items = data.get("items", [])
        if category:
            items = [it for it in items if it.get("category") == category]
        items = sorted(items, key=lambda x: x.get("name", "").lower())
        total = len(items)
        page_size = 23
        max_page = max(0, (total - 1) // page_size)
        start = page * page_size
        end = start + page_size
        page_items = items[start:end]
        options = []
        for it in page_items:
            stock = it.get("stock", -1)
            stock_text = "∞" if stock < 0 else f"×{stock}"
            options.append(discord.SelectOption(
                label=f"{it.get('name','?')} — {it.get('price',0):,}"[:100],
                value=it.get("shop_id", "?"),
                description=f"Stock {stock_text} · {it.get('category','-')}"[:80],
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
            options = [discord.SelectOption(label="ไม่มีไอเทมในหมวดนี้", value="none")]
        ph_suffix = f" (หน้า {page+1}/{max_page+1})" if max_page > 0 else ""
        super().__init__(placeholder=f"เลือกไอเทม{ph_suffix}...", options=options[:25], row=1)

    async def callback(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        if self.values[0].startswith("__nextpage__:"):
            new_page = int(self.values[0].split(":", 1)[1])
            await ix.response.edit_message(view=ShopBrowseView(self.uid, self.category, page=new_page))
            return
        shop_id = self.values[0]
        it = get_shop_item(shop_id)
        if not it:
            await ix.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        if it.get("stock", -1) == 0:
            await ix.response.send_message("❌ ไอเทมนี้หมด stock", ephemeral=True); return
        view = BuySessionView(self.uid, shop_id)
        await ix.response.send_message(
            embed=_item_detail_embed(it),
            view=view,
            ephemeral=True,
        )


class ShopBrowseView(discord.ui.View):
    def __init__(self, uid: str, category: str = None, page: int = 0):
        super().__init__(timeout=300)
        self.add_item(ShopCategorySelect(uid, category))
        self.add_item(ShopItemSelect(uid, category, page=page))


# ── Admin: categories ────────────────────────────────────────
class CategoryAddModal(discord.ui.Modal, title="➕ เพิ่มหมวดร้านค้า"):
    f_id    = discord.ui.TextInput(label="ID หมวด (a-z, _)", placeholder="เช่น weapon", max_length=30)
    f_name  = discord.ui.TextInput(label="ชื่อหมวด", max_length=50)
    f_emoji = discord.ui.TextInput(label="Emoji (ไม่บังคับ)", required=False, max_length=10)

    async def on_submit(self, ix: discord.Interaction):
        data = load_shop_catalog()
        cid = self.f_id.value.strip().lower().replace(" ", "_")
        cats = data.setdefault("categories", [])
        if any(c["id"] == cid for c in cats):
            await ix.response.send_message(f"❌ มีหมวด `{cid}` อยู่แล้ว", ephemeral=True); return
        cats.append({
            "id":    cid,
            "name":  self.f_name.value.strip(),
            "emoji": (self.f_emoji.value or "🛒").strip() or "🛒",
        })
        save_shop_catalog(data)
        await ix.response.send_message(f"✅ เพิ่มหมวด `{cid}` แล้ว", ephemeral=True)


class CategoryDeleteSelect(discord.ui.Select):
    def __init__(self):
        data = load_shop_catalog()
        options = []
        for c in data.get("categories", [])[:25]:
            options.append(discord.SelectOption(label=c.get("name","?")[:100], value=c["id"], emoji=_safe_emoji(c.get("emoji"))))
        if not options:
            options = [discord.SelectOption(label="ไม่มีหมวด", value="none")]
        super().__init__(placeholder="🗑️ เลือกหมวดที่จะลบ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cid = self.values[0]
        data = load_shop_catalog()
        data["categories"] = [c for c in data.get("categories", []) if c["id"] != cid]
        # ของในหมวดนั้น → ย้ายเป็น "uncategorized"
        for it in data.get("items", []):
            if it.get("category") == cid:
                it["category"] = "uncategorized"
        save_shop_catalog(data)
        await ix.response.edit_message(content=f"🗑️ ลบหมวด `{cid}` แล้ว (ของในหมวดถูกย้ายเป็น uncategorized)", view=None)


# ── Admin: items ─────────────────────────────────────────────
class ShopItemAddModal(discord.ui.Modal, title="➕ เพิ่มไอเทมในร้าน"):
    f_name   = discord.ui.TextInput(label="ชื่อไอเทม", max_length=60)
    f_icon   = discord.ui.TextInput(label="Icon (emoji หรือ URL)", required=False, max_length=400)
    f_desc   = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, max_length=600)
    f_price  = discord.ui.TextInput(label="ราคา", placeholder="100", max_length=10)
    f_cat    = discord.ui.TextInput(label="Category / Stock / UseEffect",
                                    style=discord.TextStyle.paragraph,
                                    placeholder="3 บรรทัด: หมวด / stock (-1=∞) / use effect\nเช่น:\nconsumable\n-1\nฟื้นพลัง 20",
                                    max_length=600)

    async def on_submit(self, ix: discord.Interaction):
        icon = (self.f_icon.value or "").strip()
        if icon.lower().startswith(("http://","https://")):
            emoji, image_url = "📦", icon
        else:
            emoji, image_url = (icon or "📦"), ""
        parts = (self.f_cat.value or "").split("\n")
        cat_id = (parts[0] if parts else "uncategorized").strip() or "uncategorized"
        stock  = _parse_int(parts[1].strip() if len(parts) > 1 else "-1", -1)
        if stock is None: stock = -1
        use_effect = parts[2].strip() if len(parts) > 2 else ""
        data = load_shop_catalog()
        sid = orion_items._slugify(self.f_name.value)
        existing_ids = {it.get("shop_id") for it in data.get("items", [])}
        if sid in existing_ids:
            sid = f"{sid}_{int(time.time())}"
        new_item = {
            "shop_id":     sid,
            "item_id":     sid,
            "name":        self.f_name.value.strip(),
            "emoji":       emoji,
            "image_url":   image_url,
            "description": self.f_desc.value.strip(),
            "price":       max(0, _parse_int(self.f_price.value, 100) or 100),
            "stock":       stock,
            "category":    cat_id,
            "item_type":   "usable" if use_effect else "resource",
            "use_effect":  use_effect,
        }
        data.setdefault("items", []).append(new_item)
        save_shop_catalog(data)
        # sync ไป catalog
        ensure_shop_item_in_catalog(new_item)
        await ix.response.send_message(f"✅ เพิ่ม **{new_item['name']}** เข้าร้าน (`{sid}`)", ephemeral=True)


class ShopItemDeleteSelect(discord.ui.Select):
    def __init__(self):
        data = load_shop_catalog()
        options = []
        for it in data.get("items", [])[:25]:
            options.append(discord.SelectOption(
                label=it.get("name","?")[:100],
                value=it.get("shop_id","?"),
                description=f"{it.get('category','-')} · {it.get('price',0):,}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีไอเทม", value="none")]
        super().__init__(placeholder="🗑️ เลือกไอเทมจะลบ...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        sid = self.values[0]
        data = load_shop_catalog()
        data["items"] = [it for it in data.get("items", []) if it.get("shop_id") != sid]
        save_shop_catalog(data)
        await ix.response.edit_message(content=f"🗑️ ลบ `{sid}` แล้ว", view=None)


class ShopItemStockSelect(discord.ui.Select):
    def __init__(self):
        data = load_shop_catalog()
        options = []
        for it in data.get("items", [])[:25]:
            stock = it.get("stock", -1)
            stock_text = "♾️" if stock < 0 else f"×{stock}"
            options.append(discord.SelectOption(
                label=it.get("name","?")[:100],
                value=it.get("shop_id","?"),
                description=f"Stock {stock_text} · ราคา {it.get('price',0):,}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีไอเทม", value="none")]
        super().__init__(placeholder="📦 เลือกไอเทมจะปรับ stock/ราคา...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(ShopItemEditModal(self.values[0]))


class ShopItemEditModal(discord.ui.Modal, title="⚙️ แก้ stock / ราคา"):
    f_stock = discord.ui.TextInput(label="Stock (-1 = ไม่จำกัด)", max_length=8)
    f_price = discord.ui.TextInput(label="ราคา", max_length=10)

    def __init__(self, shop_id: str):
        super().__init__()
        self.shop_id = shop_id
        it = get_shop_item(shop_id)
        self.f_stock.default = str(it.get("stock", -1))
        self.f_price.default = str(it.get("price", 0))

    async def on_submit(self, ix):
        data = load_shop_catalog()
        for it in data.get("items", []):
            if it.get("shop_id") == self.shop_id:
                s = _parse_int(self.f_stock.value, -1)
                if s is not None: it["stock"] = s
                p = _parse_int(self.f_price.value, it.get("price", 0))
                if p is not None: it["price"] = max(0, p)
                save_shop_catalog(data)
                await ix.response.send_message(
                    f"✅ อัปเดต `{self.shop_id}` — stock {it['stock']}, ราคา {it['price']}",
                    ephemeral=True,
                ); return
        await ix.response.send_message("❌ ไม่พบไอเทม", ephemeral=True)


# ── Admin: coupons ───────────────────────────────────────────
class CouponAddModal(discord.ui.Modal, title="🎫 เพิ่มคูปอง"):
    f_code  = discord.ui.TextInput(label="โค้ด (ตัวพิมพ์ใหญ่)", max_length=30)
    f_pct   = discord.ui.TextInput(label="% ลด (1-100)", max_length=3)
    f_cats  = discord.ui.TextInput(label="หมวด (คั่นด้วย , ว่าง=ทุกหมวด)", required=False, max_length=200)
    f_uses  = discord.ui.TextInput(label="จำนวนใช้ได้ (-1 = ไม่จำกัด)", max_length=10)
    f_desc  = discord.ui.TextInput(label="คำอธิบาย (ไม่บังคับ)", required=False, max_length=200)

    async def on_submit(self, ix):
        code = self.f_code.value.strip().upper()
        if not code:
            await ix.response.send_message("❌ โค้ดว่าง", ephemeral=True); return
        coupons = load_coupons()
        cats_str = (self.f_cats.value or "").strip()
        cats = [c.strip() for c in cats_str.split(",") if c.strip()] if cats_str else []
        coupons[code] = {
            "code": code,
            "discount_pct": max(0, min(100, _parse_int(self.f_pct.value, 0) or 0)),
            "categories": cats,
            "uses_left": _parse_int(self.f_uses.value, -1) or -1,
            "expires_at": 0,
            "description": (self.f_desc.value or "").strip(),
        }
        save_coupons(coupons)
        await ix.response.send_message(f"✅ เพิ่มคูปอง `{code}` แล้ว", ephemeral=True)


class CouponDeleteSelect(discord.ui.Select):
    def __init__(self):
        coupons = load_coupons()
        options = []
        for code, c in list(coupons.items())[:25]:
            options.append(discord.SelectOption(
                label=code[:100],
                value=code,
                description=f"-{c.get('discount_pct',0)}% · เหลือ {c.get('uses_left',-1)}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีคูปอง", value="none")]
        super().__init__(placeholder="🗑️ เลือกคูปองจะลบ...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        code = self.values[0]
        coupons = load_coupons()
        coupons.pop(code, None)
        save_coupons(coupons)
        await ix.response.edit_message(content=f"🗑️ ลบ `{code}` แล้ว", view=None)


# ── Admin: channel + role ─────────────────────────────────────
class ShopChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📺 เลือกห้อง/เธรด/ฟอรั่มของร้าน...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.public_thread,
                discord.ChannelType.private_thread,
                discord.ChannelType.forum,
            ],
            min_values=0, max_values=1,
        )

    async def callback(self, ix: discord.Interaction):
        cfg = load_shop_cfg()
        if not self.values:
            cfg["shop_channel_id"] = 0
            msg = "✅ ล้างห้องร้าน (ใช้ได้ทุกห้อง)"
        else:
            ch = self.values[0]
            cfg["shop_channel_id"] = ch.id
            msg = f"✅ ตั้งห้องร้านเป็น <#{ch.id}>"
        save_shop_cfg(cfg)
        await ix.response.send_message(msg, ephemeral=True)


class ShopRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="🛡️ role ที่จัดการร้านได้ (นอกจาก admin)...", min_values=0, max_values=10)

    async def callback(self, ix):
        cfg = load_shop_cfg()
        cfg["allowed_role_ids"] = [r.id for r in self.values]
        save_shop_cfg(cfg)
        names = ", ".join(r.mention for r in self.values) or "_(admin only)_"
        await ix.response.send_message(f"✅ ตั้ง role: {names}", ephemeral=True)


# ── Admin main view ──────────────────────────────────────────
class ShopAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ShopChannelSelect())
        self.add_item(ShopRoleSelect())

    async def interaction_check(self, ix):
        if not can_manage_shop(ix.user):
            await ix.response.send_message("❌ ไม่มีสิทธิ์", ephemeral=True); return False
        return True

    @discord.ui.button(label="เพิ่มหมวด", style=discord.ButtonStyle.success, row=2)
    async def b_add_cat(self, ix, _b):
        await ix.response.send_modal(CategoryAddModal())

    @discord.ui.button(label="ลบหมวด", style=discord.ButtonStyle.danger, row=2)
    async def b_del_cat(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CategoryDeleteSelect())
        await ix.response.send_message("🗑️ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="เพิ่มไอเทม", style=discord.ButtonStyle.success, row=3)
    async def b_add_item(self, ix, _b):
        await ix.response.send_modal(ShopItemAddModal())

    @discord.ui.button(label="แก้ stock/ราคา", style=discord.ButtonStyle.primary, row=3)
    async def b_stock(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(ShopItemStockSelect())
        await ix.response.send_message("⚙️ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="ลบไอเทม", style=discord.ButtonStyle.danger, row=3)
    async def b_del_item(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(ShopItemDeleteSelect())
        await ix.response.send_message("🗑️ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="เพิ่มคูปอง", style=discord.ButtonStyle.success, row=4)
    async def b_add_coup(self, ix, _b):
        await ix.response.send_modal(CouponAddModal())

    @discord.ui.button(label="ลบคูปอง", style=discord.ButtonStyle.danger, row=4)
    async def b_del_coup(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CouponDeleteSelect())
        await ix.response.send_message("🗑️ ↓", view=v, ephemeral=True)

    @discord.ui.button(label="📥 ดาวน์โหลด JSON", style=discord.ButtonStyle.secondary, row=4)
    async def b_download(self, ix, _b):
        data = load_shop_catalog()
        s = json.dumps(data, ensure_ascii=False, indent=2)
        fp = io.BytesIO(s.encode("utf-8"))
        file = discord.File(fp, filename="shop_catalog.json")
        await ix.response.send_message(
            "📥 ไฟล์ JSON ของร้าน — แก้ตรงๆ แล้วใช้ `/ร้านอัปโหลด` อัปโหลดกลับ",
            file=file, ephemeral=True,
        )


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="ร้าน", description="เปิดร้านค้า — เลือกหมวด ซื้อ หรือส่งเป็นของขวัญ", guild=_ORION_GUILD_OBJ)
async def cmd_shop(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    cfg = load_shop_cfg()
    shop_ch = cfg.get("shop_channel_id", 0)
    if shop_ch and interaction.channel and interaction.channel.id != shop_ch:
        await interaction.response.send_message(
            f"❌ ร้านเปิดเฉพาะใน <#{shop_ch}>", ephemeral=True,
        ); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    await interaction.response.send_message(
        embed=_shop_overview_embed(),
        view=ShopBrowseView(uid),
        ephemeral=_eph("ร้าน"),
    )


@bot.tree.command(name="ร้านแอดมิน", description="[Admin] จัดการร้านค้า — หมวด/ไอเทม/คูปอง/JSON", guild=_ORION_GUILD_OBJ)
async def cmd_shop_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not can_manage_shop(interaction.user):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์", ephemeral=True); return
    data = load_shop_catalog()
    coupons = load_coupons()
    cfg = load_shop_cfg()
    ch_text = f"<#{cfg['shop_channel_id']}>" if cfg.get("shop_channel_id") else "_(ทุกห้อง)_"
    roles_text = ", ".join(f"<@&{rid}>" for rid in cfg.get("allowed_role_ids", [])) or "_(admin only)_"
    embed = discord.Embed(
        title="🛒  Shop — Admin Panel",
        description=(
            f"**หมวด:** {len(data.get('categories',[]))} · **ไอเทม:** {len(data.get('items',[]))} · **คูปอง:** {len(coupons)}\n"
            f"**ห้องร้าน:** {ch_text}\n"
            f"**Role จัดการได้:** {roles_text}\n\n"
            "**Row 0** — ChannelSelect (ห้องร้าน)\n"
            "**Row 1** — RoleSelect (role จัดการร้าน)\n"
            "**Row 2** — ➕ เพิ่มหมวด · 🗑️ ลบหมวด\n"
            "**Row 3** — ➕ เพิ่มไอเทม · ⚙️ แก้ stock/ราคา · 🗑️ ลบไอเทม\n"
            "**Row 4** — 🎫 เพิ่มคูปอง · 🗑️ ลบคูปอง · 📥 ดาวน์โหลด JSON\n\n"
            "_อัปโหลด JSON ใช้ `/ร้านอัปโหลด` แยกต่างหาก_"
        ),
        color=0xe67e22,
    )
    await interaction.response.send_message(embed=embed, view=ShopAdminView(), ephemeral=True)


@bot.tree.command(name="ร้านอัปโหลด", description="[Admin] อัปโหลด shop_catalog.json (แทนที่ของเดิมทั้งหมด)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(file="ไฟล์ shop_catalog.json (แก้แล้ว)")
async def cmd_shop_upload(interaction: discord.Interaction, file: discord.Attachment):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not can_manage_shop(interaction.user):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์", ephemeral=True); return
    if not file.filename.lower().endswith(".json"):
        await interaction.response.send_message("❌ ต้องเป็นไฟล์ .json", ephemeral=True); return
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        await interaction.response.send_message(f"❌ JSON parse error: `{e}`", ephemeral=True); return
    if not isinstance(data, dict) or "items" not in data:
        await interaction.response.send_message("❌ JSON ต้องมีฟิลด์ `categories` และ `items`", ephemeral=True); return
    # backup เก่า
    backup = load_shop_catalog()
    save_shop_catalog(data)
    # sync items ทั้งหมดเข้า catalog
    synced = 0
    for it in data.get("items", []):
        if ensure_shop_item_in_catalog(it):
            synced += 1
    await interaction.response.send_message(
        f"✅ อัปโหลดสำเร็จ — {len(data.get('items',[]))} ไอเทม, {len(data.get('categories',[]))} หมวด, sync เข้า catalog {synced} อัน",
        ephemeral=True,
    )


@bot.tree.command(name="คูปอง", description="ดูคูปองทั้งหมดที่ใช้ได้", guild=_ORION_GUILD_OBJ)
async def cmd_coupons(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    coupons = load_coupons()
    if not coupons:
        await interaction.response.send_message("_ไม่มีคูปองในระบบ_", ephemeral=True); return
    lines = []
    for code, c in coupons.items():
        uses = c.get("uses_left", -1)
        if uses == 0: continue
        cats = c.get("categories", []) or ["ทุกหมวด"]
        lines.append(
            f"`{code}` — **-{c.get('discount_pct',0)}%** · หมวด: {', '.join(cats)} · "
            f"เหลือ {'♾️' if uses < 0 else uses}"
        )
        if c.get("description"):
            lines.append(f"  _{c['description']}_")
    embed = discord.Embed(
        title="🎫  คูปองที่ใช้ได้",
        description="\n".join(lines)[:3500] or "_หมดทุกตัว_",
        color=0xe67e22,
    )
    await interaction.response.send_message(embed=embed, ephemeral=_eph("คูปอง"))
