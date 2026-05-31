"""Shop system — /shop-setup, /shop-config, /shop + restock background task."""
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.instance import bot
from core.shared import (
    t,
    load_config, load_players, save_players,
    load_shops, save_shops,
    format_currency, slugify,
    EMBED_COLOR,
)


# ── Admin check ───────────────────────────────────────────────────────────────

def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild:
            return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (
            m.guild_permissions.administrator or m.guild_permissions.manage_guild
        )
    return app_commands.check(pred)


# ── Restock background task ───────────────────────────────────────────────────

@tasks.loop(seconds=60)
async def restock_task():
    now = time.time()
    for guild in bot.guilds:
        gid     = guild.id
        db      = load_shops(gid)
        changed = False
        for shop in db.get("shops", {}).values():
            for item in shop.get("items", {}).values():
                interval  = item.get("restock_interval", 0)
                max_stock = item.get("max_stock", -1)
                if interval <= 0 or max_stock < 0:
                    continue
                last = item.get("last_restock", 0)
                if now - last >= interval * 60:
                    item["stock"]        = max_stock
                    item["last_restock"] = now
                    changed = True
        if changed:
            save_shops(gid, db)


def start_shop_tasks():
    if not restock_task.is_running():
        restock_task.start()


# ── Modals ────────────────────────────────────────────────────────────────────

class ShopCreateModal(discord.ui.Modal, title="Create New Shop"):
    f_name  = discord.ui.TextInput(label="Shop Name",              max_length=60)
    f_owner = discord.ui.TextInput(label="Owner",                  max_length=60)
    f_desc  = discord.ui.TextInput(
        label="Description",
        max_length=300,
        style=discord.TextStyle.paragraph,
    )
    f_img   = discord.ui.TextInput(
        label="Image URL (optional)",
        max_length=300,
        required=False,
    )

    def __init__(self, gid: int, parent: "ShopSetupView"):
        super().__init__()
        self.gid    = gid
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        db      = load_shops(self.gid)
        shop_id = str(uuid.uuid4())[:8]
        db["shops"][shop_id] = {
            "name":        self.f_name.value.strip(),
            "owner":       self.f_owner.value.strip(),
            "description": self.f_desc.value.strip(),
            "image_url":   (self.f_img.value or "").strip(),
            "items":       {},
            "message_id":  None,
        }
        save_shops(self.gid, db)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(
            t(self.gid, "shop_created", name=self.f_name.value.strip()),
            ephemeral=True,
        )


class ShopEditModal(discord.ui.Modal, title="Edit Shop"):
    f_name  = discord.ui.TextInput(label="Shop Name",              max_length=60)
    f_owner = discord.ui.TextInput(label="Owner",                  max_length=60)
    f_desc  = discord.ui.TextInput(
        label="Description",
        max_length=300,
        style=discord.TextStyle.paragraph,
    )
    f_img   = discord.ui.TextInput(
        label="Image URL (optional)",
        max_length=300,
        required=False,
    )

    def __init__(self, gid: int, shop_id: str, parent: "ShopConfigView"):
        super().__init__()
        self.gid     = gid
        self.shop_id = shop_id
        self.parent  = parent
        db   = load_shops(gid)
        shop = db.get("shops", {}).get(shop_id, {})
        self.f_name.default  = shop.get("name",        "")
        self.f_owner.default = shop.get("owner",       "")
        self.f_desc.default  = shop.get("description", "")
        self.f_img.default   = shop.get("image_url",   "")

    async def on_submit(self, ix: discord.Interaction):
        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.shop_id)
        if shop:
            shop["name"]        = self.f_name.value.strip()
            shop["owner"]       = self.f_owner.value.strip()
            shop["description"] = self.f_desc.value.strip()
            shop["image_url"]   = (self.f_img.value or "").strip()
            save_shops(self.gid, db)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class AddItemModal(discord.ui.Modal, title="Add Item to Shop"):
    f_name     = discord.ui.TextInput(label="Item Name",                  max_length=60)
    f_emoji    = discord.ui.TextInput(label="Emoji (optional)",           max_length=100, required=False)
    f_price    = discord.ui.TextInput(label="Price",                      max_length=12,  default="100")
    f_stock    = discord.ui.TextInput(label="Stock (-1 = unlimited)",     max_length=12,  default="-1")
    f_restock  = discord.ui.TextInput(
        label="Restock interval (minutes, 0 = never)",
        max_length=10,
        default="0",
        required=False,
    )

    def __init__(self, gid: int, shop_id: str, parent: "ShopConfigView"):
        super().__init__()
        self.gid     = gid
        self.shop_id = shop_id
        self.parent  = parent

    async def on_submit(self, ix: discord.Interaction):
        try:
            price = max(0, int(self.f_price.value.strip()))
        except ValueError:
            price = 0
        try:
            stock = int(self.f_stock.value.strip())
        except ValueError:
            stock = -1
        try:
            restock = max(0, int((self.f_restock.value or "0").strip()))
        except ValueError:
            restock = 0

        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.shop_id)
        if not shop:
            await ix.response.send_message("Shop not found.", ephemeral=True)
            return

        key = slugify(self.f_name.value.strip()) or str(uuid.uuid4())[:8]
        shop.setdefault("items", {})[key] = {
            "name":             self.f_name.value.strip(),
            "emoji":            (self.f_emoji.value or "").strip() or "📦",
            "price":            price,
            "stock":            stock,
            "max_stock":        stock,
            "restock_interval": restock,
            "last_restock":     time.time(),
            "description":      "",
        }
        save_shops(self.gid, db)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class AddItemDescModal(discord.ui.Modal, title="Item Description"):
    f_desc = discord.ui.TextInput(
        label="Description",
        max_length=300,
        style=discord.TextStyle.paragraph,
        required=False,
    )

    def __init__(self, gid: int, shop_id: str, item_id: str, parent: "ShopConfigView"):
        super().__init__()
        self.gid     = gid
        self.shop_id = shop_id
        self.item_id = item_id
        self.parent  = parent
        db = load_shops(gid)
        item = db.get("shops", {}).get(shop_id, {}).get("items", {}).get(item_id, {})
        self.f_desc.default = item.get("description", "")

    async def on_submit(self, ix: discord.Interaction):
        db   = load_shops(self.gid)
        item = db.get("shops", {}).get(self.shop_id, {}).get("items", {}).get(self.item_id)
        if item:
            item["description"] = (self.f_desc.value or "").strip()
            save_shops(self.gid, db)
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


# ── /shop-setup ───────────────────────────────────────────────────────────────

class ShopSetupView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    def _build(self) -> tuple[discord.Embed, "ShopSetupView"]:
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})

        embed = discord.Embed(
            title=t(self.gid, "shop_setup_title"),
            color=EMBED_COLOR,
        )
        if shops:
            shop_lines = []
            for sid, s in list(shops.items())[:20]:
                shop_lines.append(f"• **{s['name']}** (`{sid}`) — {s.get('description','')[:40]}")
            embed.description = "\n".join(shop_lines)
        else:
            embed.description = t(self.gid, "no_shops")

        new_btn = discord.ui.Button(
            label="Create New Shop",
            style=discord.ButtonStyle.green,
            custom_id="ssu_new",
        )
        new_btn.callback = self._new
        self.add_item(new_btn)

        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ssu_done",
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

        return embed, self

    async def _new(self, ix: discord.Interaction):
        await ix.response.send_modal(ShopCreateModal(self.gid, self))

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        embed = discord.Embed(description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=self)


@bot.tree.command(
    name="shop-setup",
    description="Create and manage shops (admin)",
    description_localizations={"th": "สร้างและจัดการร้านค้า (แอดมิน)"},
)
@_is_admin()
async def shop_setup_cmd(ix: discord.Interaction):
    view        = ShopSetupView(ix.guild_id)
    embed, view = view._build()
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@shop_setup_cmd.error
async def shop_setup_error(ix: discord.Interaction, error):
    if not ix.response.is_done():
        await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)


# ── /shop-config ──────────────────────────────────────────────────────────────

class ShopConfigView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid      = gid
        self.sel_shop = None
        self.sel_item = None

    def _build(self) -> tuple[discord.Embed, "ShopConfigView"]:
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})

        embed = discord.Embed(
            title=t(self.gid, "shop_config_title"),
            color=EMBED_COLOR,
        )

        # Shop selector
        opts = (
            [
                discord.SelectOption(
                    label=s["name"][:100],
                    value=sid,
                    default=(sid == self.sel_shop),
                )
                for sid, s in list(shops.items())[:25]
            ]
            if shops
            else [discord.SelectOption(label="No shops", value="__none__")]
        )
        shop_sel = discord.ui.Select(
            placeholder="Select shop to configure",
            options=opts,
            custom_id="sc_shop",
        )
        shop_sel.callback = self._sel_shop_cb
        self.add_item(shop_sel)

        if self.sel_shop and self.sel_shop in shops:
            shop  = shops[self.sel_shop]
            items = shop.get("items", {})

            embed.title = f"⚙️ {shop['name']}"
            embed.description = shop.get("description", "")
            embed.add_field(
                name="Owner",
                value=shop.get("owner", "?"),
                inline=True,
            )
            embed.add_field(
                name="Items",
                value=str(len(items)),
                inline=True,
            )
            img = shop.get("image_url", "")
            if img and img.startswith(("http://", "https://")):
                embed.set_thumbnail(url=img)

            # Item list in embed
            if items:
                item_lines = []
                for iid, it in list(items.items())[:10]:
                    stock = it.get("stock", -1)
                    stock_str = t(self.gid, "unlimited_stock") if stock < 0 else str(stock)
                    item_lines.append(
                        f"{it.get('emoji','📦')} **{it['name']}** — {it['price']} | {stock_str}"
                    )
                embed.add_field(name="Items", value="\n".join(item_lines), inline=False)

                # Item selector for removal / description
                item_opts = [
                    discord.SelectOption(
                        label=f"{it.get('emoji','')} {it['name']}"[:100],
                        value=iid,
                        default=(iid == self.sel_item),
                    )
                    for iid, it in list(items.items())[:25]
                ]
                item_sel = discord.ui.Select(
                    placeholder="Select item to edit/remove",
                    options=item_opts,
                    custom_id="sc_item",
                )
                item_sel.callback = self._sel_item_cb
                self.add_item(item_sel)

            # Action buttons
            add_btn = discord.ui.Button(
                label="Add Item",
                style=discord.ButtonStyle.green,
                custom_id="sc_add",
            )
            add_btn.callback = self._add_item
            self.add_item(add_btn)

            edit_btn = discord.ui.Button(
                label="Edit Shop Details",
                style=discord.ButtonStyle.secondary,
                custom_id="sc_edit",
            )
            edit_btn.callback = self._edit_shop
            self.add_item(edit_btn)

            if self.sel_item and self.sel_item in items:
                desc_btn = discord.ui.Button(
                    label="Edit Item Description",
                    style=discord.ButtonStyle.secondary,
                    custom_id="sc_idesc",
                )
                desc_btn.callback = self._edit_item_desc
                self.add_item(desc_btn)

                rem_item_btn = discord.ui.Button(
                    label="Remove Selected Item",
                    style=discord.ButtonStyle.danger,
                    custom_id="sc_irem",
                )
                rem_item_btn.callback = self._remove_item
                self.add_item(rem_item_btn)

            del_btn = discord.ui.Button(
                label="Delete Shop",
                style=discord.ButtonStyle.danger,
                custom_id="sc_del",
            )
            del_btn.callback = self._del_shop
            self.add_item(del_btn)
        else:
            embed.description = t(self.gid, "no_shops") if not shops else "Select a shop above."

        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="sc_done",
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

        return embed, self

    async def _sel_shop_cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        self.sel_shop = v if v != "__none__" else None
        self.sel_item = None
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _sel_item_cb(self, ix: discord.Interaction):
        self.sel_item = ix.data["values"][0]
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _add_item(self, ix: discord.Interaction):
        await ix.response.send_modal(AddItemModal(self.gid, self.sel_shop, self))

    async def _edit_shop(self, ix: discord.Interaction):
        await ix.response.send_modal(ShopEditModal(self.gid, self.sel_shop, self))

    async def _edit_item_desc(self, ix: discord.Interaction):
        await ix.response.send_modal(
            AddItemDescModal(self.gid, self.sel_shop, self.sel_item, self)
        )

    async def _remove_item(self, ix: discord.Interaction):
        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.sel_shop, {})
        shop.get("items", {}).pop(self.sel_item, None)
        save_shops(self.gid, db)
        self.sel_item = None
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _del_shop(self, ix: discord.Interaction):
        db = load_shops(self.gid)
        db["shops"].pop(self.sel_shop, None)
        save_shops(self.gid, db)
        self.sel_shop = None
        self.sel_item = None
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        embed = discord.Embed(description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=self)


@bot.tree.command(
    name="shop-config",
    description="Configure shop items and details (admin)",
    description_localizations={"th": "ตั้งค่าสินค้าและรายละเอียดร้านค้า (แอดมิน)"},
)
@_is_admin()
async def shop_config_cmd(ix: discord.Interaction):
    view        = ShopConfigView(ix.guild_id)
    embed, view = view._build()
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@shop_config_cmd.error
async def shop_config_error(ix: discord.Interaction, error):
    if not ix.response.is_done():
        await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)


# ── /shop (player) ────────────────────────────────────────────────────────────

class BuyConfirmView(discord.ui.View):
    """Confirm-purchase sub-view shown after player clicks Buy."""

    def __init__(self, gid: int, shop_id: str, item_id: str, uid: int, parent: "ShopItemsView"):
        super().__init__(timeout=120)
        self.gid     = gid
        self.shop_id = shop_id
        self.item_id = item_id
        self.uid     = uid
        self.parent  = parent

    def _make_embed(self) -> discord.Embed:
        db   = load_shops(self.gid)
        cfg  = load_config(self.gid)
        shop = db.get("shops", {}).get(self.shop_id, {})
        it   = shop.get("items", {}).get(self.item_id, {})
        price_str = format_currency(it.get("price", 0), cfg)
        embed = discord.Embed(
            title="Confirm Purchase",
            description=t(self.gid, "buy_confirm", item=it.get("name", "?"), price=price_str),
            color=EMBED_COLOR,
        )
        img = it.get("image_url", "")
        if img and img.startswith(("http://", "https://")):
            embed.set_thumbnail(url=img)
        return embed

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green, custom_id="bc_confirm")
    async def confirm(self, ix: discord.Interaction, _: discord.ui.Button):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return

        db      = load_shops(self.gid)
        shop    = db.get("shops", {}).get(self.shop_id, {})
        it      = shop.get("items", {}).get(self.item_id)
        if not it:
            await ix.response.send_message("Item not found.", ephemeral=True)
            return

        cfg     = load_config(self.gid)
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        balance = player.get("balance", 0)
        price   = it.get("price", 0)
        stock   = it.get("stock", -1)

        if stock == 0:
            await ix.response.send_message(t(self.gid, "out_of_stock_label"), ephemeral=True)
            return
        if balance < price:
            await ix.response.send_message(
                t(self.gid, "insufficient_funds",
                  price=format_currency(price, cfg),
                  balance=format_currency(balance, cfg)),
                ephemeral=True,
            )
            return

        # Deduct balance and add to inventory
        player["balance"] = balance - price
        inv = player.setdefault("inventory", {})
        inv[self.item_id] = inv.get(self.item_id, 0) + 1
        players[str(self.uid)] = player
        save_players(self.gid, players)

        # Decrement stock if finite
        if stock > 0:
            it["stock"] = stock - 1
            save_shops(self.gid, db)

        new_bal = player["balance"]
        result_embed = discord.Embed(
            description=t(
                self.gid, "purchase_success",
                item=it["name"],
                price=format_currency(price, cfg),
                balance=format_currency(new_bal, cfg),
            ),
            color=EMBED_COLOR,
        )

        # Refresh the parent shop view
        self.parent.sel_item = None
        parent_embed, parent_view = self.parent._build()

        await ix.response.edit_message(embed=parent_embed, view=parent_view)
        await ix.followup.send(embed=result_embed, ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, custom_id="bc_cancel")
    async def cancel(self, ix: discord.Interaction, _: discord.ui.Button):
        parent_embed, parent_view = self.parent._build()
        await ix.response.edit_message(embed=parent_embed, view=parent_view)


class ShopItemsView(discord.ui.View):
    """Browse items in a single shop and buy them."""

    def __init__(self, gid: int, shop_id: str, uid: int, parent: "ShopListView"):
        super().__init__(timeout=300)
        self.gid     = gid
        self.shop_id = shop_id
        self.uid     = uid
        self.parent  = parent
        self.sel_item = None

    def _build(self) -> tuple[discord.Embed, "ShopItemsView"]:
        self.clear_items()
        db   = load_shops(self.gid)
        cfg  = load_config(self.gid)
        shop = db.get("shops", {}).get(self.shop_id, {})
        items = shop.get("items", {})

        embed = discord.Embed(
            title=f"🏪 {shop.get('name', 'Shop')}",
            description=shop.get("description", ""),
            color=EMBED_COLOR,
        )
        embed.set_footer(text=f"Owner: {shop.get('owner','?')}")

        img = shop.get("image_url", "")
        if img and img.startswith(("http://", "https://")):
            embed.set_thumbnail(url=img)

        if not items:
            embed.add_field(name="Items", value="*No items yet.*", inline=False)
        else:
            for iid, it in list(items.items())[:20]:
                stock     = it.get("stock", -1)
                stock_str = t(self.gid, "unlimited_stock") if stock < 0 else str(stock)
                is_out    = (stock == 0)
                price_str = format_currency(it["price"], cfg)
                stock_badge = f" 🔴 {t(self.gid, 'out_of_stock_label')}" if is_out else f" ✅ {stock_str}"
                field_val = f"{price_str}{stock_badge}"
                if it.get("description"):
                    field_val += f"\n*{it['description'][:80]}*"
                embed.add_field(
                    name=f"{it.get('emoji','📦')} {it['name']}",
                    value=field_val,
                    inline=True,
                )

        # Item select
        if items:
            opts = [
                discord.SelectOption(
                    label=f"{it.get('emoji','')} {it['name']}"[:100],
                    value=iid,
                    default=(iid == self.sel_item),
                    description=f"{format_currency(it['price'], cfg)} | {'OUT' if it.get('stock',1)==0 else str(it.get('stock',-1)) + ' left' if it.get('stock',-1)>=0 else 'Unlimited'}",
                )
                for iid, it in list(items.items())[:25]
            ]
            sel = discord.ui.Select(
                placeholder="Select an item…",
                options=opts,
                custom_id="si_sel",
            )
            sel.callback = self._sel_item_cb
            self.add_item(sel)

        # Buy button (shown only when item is selected)
        if self.sel_item and self.sel_item in items:
            it     = items[self.sel_item]
            stock  = it.get("stock", -1)
            is_out = (stock == 0)
            buy_btn = discord.ui.Button(
                label=t(self.gid, "buy_btn"),
                style=discord.ButtonStyle.green if not is_out else discord.ButtonStyle.secondary,
                custom_id="si_buy",
                disabled=is_out,
            )
            buy_btn.callback = self._buy
            self.add_item(buy_btn)

        # Back button
        bk = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="si_bk",
        )
        bk.callback = self._back
        self.add_item(bk)

        return embed, self

    async def _sel_item_cb(self, ix: discord.Interaction):
        self.sel_item = ix.data["values"][0]
        embed, view = self._build()
        await ix.response.edit_message(embed=embed, view=view)

    async def _buy(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return

        confirm_view  = BuyConfirmView(self.gid, self.shop_id, self.sel_item, self.uid, self)
        confirm_embed = confirm_view._make_embed()
        await ix.response.edit_message(embed=confirm_embed, view=confirm_view)

    async def _back(self, ix: discord.Interaction):
        embed, view = self.parent._build()
        await ix.response.edit_message(embed=embed, view=view)


class ShopListView(discord.ui.View):
    """Browse all shops in the guild."""

    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    def _build(self) -> tuple[discord.Embed, "ShopListView"]:
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})

        embed = discord.Embed(
            title=t(self.gid, "shop_title"),
            color=EMBED_COLOR,
        )

        if not shops:
            embed.description = t(self.gid, "no_shops")
            return embed, self

        lines = []
        for s in list(shops.values())[:10]:
            lines.append(f"🏪 **{s['name']}** — {s.get('description','')[:60]}")
        embed.description = "\n".join(lines)

        opts = [
            discord.SelectOption(
                label=s["name"][:100],
                value=sid,
                description=s.get("description", "")[:50],
            )
            for sid, s in list(shops.items())[:25]
        ]
        sel = discord.ui.Select(
            placeholder="Browse a shop…",
            options=opts,
            custom_id="sl_sel",
        )
        sel.callback = self._sel
        self.add_item(sel)
        return embed, self

    async def _sel(self, ix: discord.Interaction):
        shop_id   = ix.data["values"][0]
        items_view = ShopItemsView(self.gid, shop_id, ix.user.id, self)
        embed, view = items_view._build()
        await ix.response.edit_message(embed=embed, view=view)


@bot.tree.command(
    name="shop",
    description="Browse and buy from shops",
    description_localizations={"th": "เข้าดูสินค้าในร้านค้า"},
)
async def shop_cmd(ix: discord.Interaction):
    view        = ShopListView(ix.guild_id)
    embed, view = view._build()
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── Cog loader ────────────────────────────────────────────────────────────────

class ShopCog(commands.Cog):
    def __init__(self, b: commands.Bot):
        super().__init__()
        start_shop_tasks()


async def setup(b: commands.Bot):
    await b.add_cog(ShopCog(b))
