"""Orion — shop system with JSON template export and JSON upload import."""
import io
import json
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR,
    load_shop, save_shop, load_config,
    get_wallet, add_money, money_str,
    load_players, save_players,
)

_SHOP_TEMPLATE = {
    "categories": {
        "potions": {"name": "🧪 ยา", "description": "ไอเทมฟื้นฟู"},
        "weapons": {"name": "⚔️ อาวุธ", "description": "อาวุธต่างๆ"},
    },
    "items": {
        "small_potion": {
            "name": "ยาเล็ก",
            "description": "ฟื้นฟูพลังงานเล็กน้อย",
            "category": "potions",
            "price": 50,
            "emoji": "🧪",
            "stock": -1,
            "role_required": None,
        },
        "iron_sword": {
            "name": "ดาบเหล็ก",
            "description": "อาวุธระดับต้น",
            "category": "weapons",
            "price": 200,
            "emoji": "⚔️",
            "stock": -1,
            "role_required": None,
        },
    },
}


# ── Browse View ───────────────────────────────────────────────────────────────

def _shop_overview_embed(gid: int, category: str | None = None) -> discord.Embed:
    shop = load_shop(gid)
    cats = shop.get("categories", {})
    items = shop.get("items", {})
    embed = discord.Embed(title="🏪 ร้านค้า", color=EMBED_COLOR)

    if not cats:
        embed.description = "ร้านค้ายังไม่มีสินค้า"
        return embed

    if category and category in cats:
        cat_info = cats[category]
        embed.title = cat_info.get("name", category)
        embed.description = cat_info.get("description", "")
        cat_items = [
            (iid, it)
            for iid, it in items.items()
            if it.get("category") == category
        ]
        if not cat_items:
            embed.description = "หมวดนี้ยังไม่มีสินค้า"
        for iid, it in cat_items:
            stock = it.get("stock", -1)
            stock_str = "∞" if stock < 0 else str(stock)
            embed.add_field(
                name=f"{it.get('emoji','')} {it.get('name', iid)}",
                value=(
                    f"{it.get('description','')}\n"
                    f"ราคา: **{money_str(it.get('price', 0), gid)}** | สต็อก: {stock_str}"
                ),
                inline=True,
            )
    else:
        embed.description = "เลือกหมวดสินค้า:"
        for cid, cat in cats.items():
            cnt = sum(1 for it in items.values() if it.get("category") == cid)
            embed.add_field(
                name=cat.get("name", cid),
                value=f"{cat.get('description','')} ({cnt} ชิ้น)",
                inline=True,
            )
    return embed


class ShopBrowseView(discord.ui.View):
    def __init__(self, uid: int, gid: int, category: str | None = None):
        super().__init__(timeout=300)
        self.uid      = uid
        self.gid      = gid
        self.category = category
        self._build()

    def _build(self):
        self.clear_items()
        shop = load_shop(self.gid)
        cats = shop.get("categories", {})

        if self.category:
            # Back button
            back = discord.ui.Button(label="◀ กลับ", style=discord.ButtonStyle.secondary, row=0)
            back.callback = self._back
            self.add_item(back)

            # Item dropdown
            items = {
                iid: it
                for iid, it in shop.get("items", {}).items()
                if it.get("category") == self.category
            }
            if items:
                opts = [
                    discord.SelectOption(
                        label=it.get("name", iid)[:100],
                        value=iid,
                        description=f"{money_str(it.get('price', 0), self.gid)}"[:100],
                        emoji=it.get("emoji") or None,
                    )
                    for iid, it in items.items()
                ][:25]
                item_sel = discord.ui.Select(placeholder="เลือกสินค้า…", options=opts, row=1)
                item_sel.callback = self._on_item_select
                self.add_item(item_sel)
        else:
            # Category dropdown
            if cats:
                opts = [
                    discord.SelectOption(
                        label=cat.get("name", cid)[:100],
                        value=cid,
                    )
                    for cid, cat in cats.items()
                ][:25]
                cat_sel = discord.ui.Select(placeholder="เลือกหมวด…", options=opts, row=0)
                cat_sel.callback = self._on_cat_select
                self.add_item(cat_sel)

    async def _back(self, ix: discord.Interaction):
        self.category = None
        self._build()
        await ix.response.edit_message(
            embed=_shop_overview_embed(self.gid), view=self
        )

    async def _on_cat_select(self, ix: discord.Interaction):
        self.category = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(
            embed=_shop_overview_embed(self.gid, self.category), view=self
        )

    async def _on_item_select(self, ix: discord.Interaction):
        item_id = ix.data["values"][0]
        shop    = load_shop(self.gid)
        item    = shop.get("items", {}).get(item_id)
        if not item:
            await ix.response.send_message("ไม่พบสินค้า", ephemeral=True)
            return
        view  = BuyConfirmView(self.uid, self.gid, item_id, item, self)
        embed = _item_embed(item_id, item, self.gid)
        await ix.response.edit_message(embed=embed, view=view)


def _item_embed(iid: str, item: dict, gid: int) -> discord.Embed:
    stock     = item.get("stock", -1)
    stock_str = "∞" if stock < 0 else str(stock)
    embed = discord.Embed(
        title=f"{item.get('emoji','🎁')} {item.get('name', iid)}",
        description=item.get("description", ""),
        color=EMBED_COLOR,
    )
    embed.add_field(name="ราคา",   value=money_str(item.get("price", 0), gid), inline=True)
    embed.add_field(name="สต็อก", value=stock_str, inline=True)
    if item.get("role_required"):
        embed.add_field(name="Role ที่ต้องมี", value=f"<@&{item['role_required']}>", inline=True)
    return embed


class BuyConfirmView(discord.ui.View):
    def __init__(self, uid: int, gid: int, item_id: str, item: dict, parent: ShopBrowseView):
        super().__init__(timeout=60)
        self.uid     = uid
        self.gid     = gid
        self.item_id = item_id
        self.item    = item
        self.parent  = parent

    @discord.ui.button(label="✅ ซื้อ", style=discord.ButtonStyle.success)
    async def buy(self, ix: discord.Interaction, _: discord.ui.Button):
        if ix.user.id != self.uid:
            await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
            return
        gid   = self.gid
        price = self.item.get("price", 0)
        bal   = get_wallet(gid, self.uid)

        if bal < price:
            await ix.response.send_message(
                f"เงินไม่พอ (มี {money_str(bal, gid)}, ต้องการ {money_str(price, gid)})",
                ephemeral=True,
            )
            return

        # Check role gate
        role_req = self.item.get("role_required")
        if role_req:
            member = ix.guild.get_member(self.uid)
            if member:
                has_role = any(str(r.id) == str(role_req) for r in member.roles)
                if not has_role:
                    await ix.response.send_message("ไม่มี Role ที่ต้องการ", ephemeral=True)
                    return

        # Check stock
        shop  = load_shop(gid)
        item  = shop.get("items", {}).get(self.item_id, {})
        stock = item.get("stock", -1)
        if stock == 0:
            await ix.response.send_message("สินค้าหมดแล้ว", ephemeral=True)
            return

        # Deduct money + give item
        add_money(gid, self.uid, -price)
        players = load_players(gid)
        p = players.get(str(self.uid), {})
        inv = p.setdefault("inventory", {})
        inv[self.item_id] = inv.get(self.item_id, 0) + 1
        players[str(self.uid)] = p
        save_players(gid, players)

        # Reduce stock
        if stock > 0:
            shop["items"][self.item_id]["stock"] = stock - 1
            save_shop(gid, shop)

        embed = discord.Embed(
            description=f"✅ ซื้อ **{self.item.get('name', self.item_id)}** สำเร็จ!",
            color=discord.Color.green(),
        )
        self.parent._build()
        await ix.response.edit_message(
            embed=_shop_overview_embed(gid, self.parent.category), view=self.parent
        )
        await ix.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="◀ กลับ", style=discord.ButtonStyle.secondary)
    async def back(self, ix: discord.Interaction, _: discord.ui.Button):
        self.parent._build()
        await ix.response.edit_message(
            embed=_shop_overview_embed(self.gid, self.parent.category), view=self.parent
        )


# ── /shop command ─────────────────────────────────────────────────────────────

@bot.tree.command(name="shop", description="เปิดร้านค้า")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_shop(ix: discord.Interaction):
    gid  = ix.guild_id
    view = ShopBrowseView(ix.user.id, gid)
    embed = _shop_overview_embed(gid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── /shop-admin command ────────────────────────────────────────────────────────

@bot.tree.command(name="shop-admin", description="[Admin] จัดการร้านค้า")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_shop_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    view  = ShopAdminView(ix.guild_id)
    embed = discord.Embed(title="🏪 Shop Admin", color=EMBED_COLOR)
    embed.description = "จัดการร้านค้า: เพิ่ม/ลบ หมวด/ไอเทม หรือ Import/Export JSON"
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class ShopAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="➕ เพิ่มหมวด", style=discord.ButtonStyle.success, row=0)
    async def add_cat(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(AddCategoryModal(self.gid))

    @discord.ui.button(label="🗑️ ลบหมวด", style=discord.ButtonStyle.danger, row=0)
    async def del_cat(self, ix: discord.Interaction, _: discord.ui.Button):
        shop = load_shop(self.gid)
        cats = shop.get("categories", {})
        if not cats:
            await ix.response.send_message("ไม่มีหมวด", ephemeral=True)
            return
        opts = [
            discord.SelectOption(
                label=cat.get("name", cid)[:100], value=cid
            )
            for cid, cat in cats.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกหมวดที่จะลบ…", options=opts)
        sel.callback = self._del_cat_cb
        view = discord.ui.View(timeout=60)
        view.add_item(sel)
        await ix.response.send_message(view=view, ephemeral=True)

    async def _del_cat_cb(self, ix: discord.Interaction):
        cid  = ix.data["values"][0]
        shop = load_shop(self.gid)
        shop.get("categories", {}).pop(cid, None)
        # Remove items in this category
        shop["items"] = {
            iid: it
            for iid, it in shop.get("items", {}).items()
            if it.get("category") != cid
        }
        save_shop(self.gid, shop)
        await ix.response.send_message(
            embed=discord.Embed(description=f"🗑️ ลบหมวด `{cid}` แล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )

    @discord.ui.button(label="🛒 เพิ่มสินค้า", style=discord.ButtonStyle.success, row=1)
    async def add_item(self, ix: discord.Interaction, _: discord.ui.Button):
        shop = load_shop(self.gid)
        cats = shop.get("categories", {})
        if not cats:
            await ix.response.send_message("ต้องมีหมวดก่อน", ephemeral=True)
            return
        opts = [
            discord.SelectOption(label=cat.get("name", cid)[:100], value=cid)
            for cid, cat in cats.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกหมวดสินค้า…", options=opts)

        async def on_cat(ix2: discord.Interaction):
            cid = ix2.data["values"][0]
            await ix2.response.send_modal(AddItemModal(self.gid, cid))

        sel.callback = on_cat
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="🗑️ ลบสินค้า", style=discord.ButtonStyle.danger, row=1)
    async def del_item(self, ix: discord.Interaction, _: discord.ui.Button):
        shop  = load_shop(self.gid)
        items = shop.get("items", {})
        if not items:
            await ix.response.send_message("ไม่มีสินค้า", ephemeral=True)
            return
        opts = [
            discord.SelectOption(label=it.get("name", iid)[:100], value=iid)
            for iid, it in items.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกสินค้าที่จะลบ…", options=opts)

        async def on_item(ix2: discord.Interaction):
            iid = ix2.data["values"][0]
            shop2 = load_shop(self.gid)
            name  = shop2.get("items", {}).get(iid, {}).get("name", iid)
            shop2.get("items", {}).pop(iid, None)
            save_shop(self.gid, shop2)
            await ix2.response.send_message(
                embed=discord.Embed(
                    description=f"🗑️ ลบ **{name}** แล้ว", color=EMBED_COLOR
                ),
                ephemeral=True,
            )

        sel.callback = on_item
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="📤 Export JSON", style=discord.ButtonStyle.secondary, row=2)
    async def export_json(self, ix: discord.Interaction, _: discord.ui.Button):
        shop    = load_shop(self.gid)
        content = json.dumps(shop, ensure_ascii=False, indent=2).encode("utf-8")
        f       = discord.File(io.BytesIO(content), filename="shop.json")
        await ix.response.send_message(
            embed=discord.Embed(description="📤 Shop config export", color=EMBED_COLOR),
            file=f,
            ephemeral=True,
        )

    @discord.ui.button(label="📥 Import JSON", style=discord.ButtonStyle.primary, row=2)
    async def import_json(self, ix: discord.Interaction, _: discord.ui.Button):
        embed = discord.Embed(
            title="📥 Import Shop JSON",
            description=(
                "แนบไฟล์ JSON ด้วยคำสั่ง `/shop-import` "
                "หรือ Copy JSON แล้วใช้ปุ่ม Paste ด้านล่าง"
            ),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(
            embed=embed,
            view=PasteImportView(self.gid),
            ephemeral=True,
        )

    @discord.ui.button(label="📋 Template", style=discord.ButtonStyle.secondary, row=2)
    async def template(self, ix: discord.Interaction, _: discord.ui.Button):
        content = json.dumps(_SHOP_TEMPLATE, ensure_ascii=False, indent=2).encode("utf-8")
        f = discord.File(io.BytesIO(content), filename="shop_template.json")
        await ix.response.send_message(
            embed=discord.Embed(
                description="📋 Shop JSON template — แก้ไขแล้ว Import กลับมา",
                color=EMBED_COLOR,
            ),
            file=f,
            ephemeral=True,
        )


class PasteImportView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid = gid

    @discord.ui.button(label="📋 Paste JSON", style=discord.ButtonStyle.primary)
    async def paste(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(ImportShopModal(self.gid))


class ImportShopModal(discord.ui.Modal, title="Paste Shop JSON"):
    json_text = discord.ui.TextInput(
        label="JSON",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        try:
            data = json.loads(self.json_text.value)
            if "categories" not in data or "items" not in data:
                raise ValueError("ต้องมี 'categories' และ 'items'")
            save_shop(self.gid, data)
            item_count = len(data.get("items", {}))
            cat_count  = len(data.get("categories", {}))
            await ix.response.send_message(
                embed=discord.Embed(
                    description=f"✅ Import สำเร็จ! {cat_count} หมวด, {item_count} ไอเทม",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
        except (json.JSONDecodeError, ValueError) as e:
            await ix.response.send_message(
                embed=discord.Embed(
                    description=f"❌ JSON ไม่ถูกต้อง: {e}", color=discord.Color.red()
                ),
                ephemeral=True,
            )


# ── /shop-import command (file upload) ────────────────────────────────────────

@bot.tree.command(
    name="shop-import",
    description="[Admin] Import shop config จากไฟล์ JSON",
)
@app_commands.guilds(*GUILD_OBJECTS)
@app_commands.describe(file="ไฟล์ shop.json")
async def cmd_shop_import(ix: discord.Interaction, file: discord.Attachment):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    if not file.filename.endswith(".json"):
        await ix.response.send_message("ต้องเป็นไฟล์ .json", ephemeral=True)
        return
    await ix.response.defer(ephemeral=True)
    try:
        raw  = await file.read()
        data = json.loads(raw.decode("utf-8"))
        if "categories" not in data or "items" not in data:
            raise ValueError("ต้องมี 'categories' และ 'items'")
        save_shop(ix.guild_id, data)
        item_count = len(data.get("items", {}))
        cat_count  = len(data.get("categories", {}))
        await ix.followup.send(
            embed=discord.Embed(
                description=f"✅ Import สำเร็จ! {cat_count} หมวด, {item_count} ไอเทม",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
    except Exception as e:
        await ix.followup.send(
            embed=discord.Embed(
                description=f"❌ Import ล้มเหลว: {e}", color=discord.Color.red()
            ),
            ephemeral=True,
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

class AddCategoryModal(discord.ui.Modal, title="เพิ่มหมวดสินค้า"):
    cat_id   = discord.ui.TextInput(label="ID (ภาษาอังกฤษ ไม่มีเว้นวรรค)", max_length=30)
    cat_name = discord.ui.TextInput(label="ชื่อหมวด", max_length=60)
    cat_desc = discord.ui.TextInput(label="คำอธิบาย", max_length=200, required=False)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        cid  = self.cat_id.value.strip().replace(" ", "_").lower()
        shop = load_shop(self.gid)
        shop.setdefault("categories", {})[cid] = {
            "name":        self.cat_name.value.strip(),
            "description": self.cat_desc.value.strip(),
        }
        save_shop(self.gid, shop)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ เพิ่มหมวด **{self.cat_name.value}** แล้ว", color=EMBED_COLOR
            ),
            ephemeral=True,
        )


class AddItemModal(discord.ui.Modal, title="เพิ่มสินค้า"):
    item_id   = discord.ui.TextInput(label="Item ID (ภาษาอังกฤษ)", max_length=40)
    item_name = discord.ui.TextInput(label="ชื่อสินค้า", max_length=60)
    item_desc = discord.ui.TextInput(label="คำอธิบาย", max_length=300, required=False)
    item_price = discord.ui.TextInput(label="ราคา", max_length=10)
    item_emoji = discord.ui.TextInput(label="Emoji", max_length=5, required=False)

    def __init__(self, gid: int, category: str):
        super().__init__()
        self.gid      = gid
        self.category = category

    async def on_submit(self, ix: discord.Interaction):
        try:
            price = max(0, int(self.item_price.value.strip()))
        except ValueError:
            await ix.response.send_message("ราคาไม่ถูกต้อง", ephemeral=True)
            return
        iid  = self.item_id.value.strip().replace(" ", "_").lower()
        shop = load_shop(self.gid)
        shop.setdefault("items", {})[iid] = {
            "name":        self.item_name.value.strip(),
            "description": self.item_desc.value.strip(),
            "category":    self.category,
            "price":       price,
            "emoji":       self.item_emoji.value.strip() or "🎁",
            "stock":       -1,
        }
        save_shop(self.gid, shop)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ เพิ่ม **{self.item_name.value}** แล้ว", color=EMBED_COLOR
            ),
            ephemeral=True,
        )
