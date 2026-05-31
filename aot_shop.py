"""Shop system — /shop-setup, /shop-config, /shop."""
import time, uuid
import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput, MediaGallery)
from discord.components import MediaGalleryItem

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, load_players, save_players,
    load_shops, save_shops, format_currency, slugify,
)


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Restock background task ───────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def restock_task():
    now = time.time()
    for guild in bot.guilds:
        if guild.id != GUILD2_ID: continue
        gid = guild.id
        db  = load_shops(gid); changed = False
        for shop in db.get("shops", {}).values():
            for item in shop.get("items", {}).values():
                interval = item.get("restock_interval", 0)
                max_stock = item.get("max_stock", -1)
                if interval <= 0 or max_stock < 0: continue
                last = item.get("last_restock", 0)
                if now - last >= interval * 60:
                    item["stock"] = max_stock
                    item["last_restock"] = now
                    changed = True
        if changed: save_shops(gid, db)


def start_shop_tasks():
    if not restock_task.is_running(): restock_task.start()


# ── Item creation modals (2-step) ─────────────────────────────────────────────

class ShopItemModal1(Modal, title="Add Shop Item — Basic"):
    f_name  = TextInput(label="Item Name",   max_length=60)
    f_cat   = TextInput(label="Category",    max_length=60)
    f_price = TextInput(label="Price",       max_length=10, default="100")
    f_stock = TextInput(label="Stock (-1 = unlimited)", max_length=10, default="-1")
    f_desc  = TextInput(label="Description", style=discord.TextStyle.paragraph,
                        max_length=300, required=False)

    def __init__(self, gid, shop_id, parent):
        super().__init__()
        self.gid = gid; self.shop_id = shop_id; self.parent = parent

    async def on_submit(self, ix):
        try: price = max(0, int(self.f_price.value.strip()))
        except: price = 0
        try: stock = int(self.f_stock.value.strip())
        except: stock = -1

        pending = {
            "name":       self.f_name.value.strip(),
            "category":   self.f_cat.value.strip(),
            "price":      price,
            "stock":      stock,
            "max_stock":  stock,
            "description": (self.f_desc.value or "").strip(),
        }
        await ix.response.edit_message(
            view=ShopItemStep2View(self.gid, self.shop_id, pending, self.parent))


class ShopItemStep2View(LayoutView):
    def __init__(self, gid, shop_id, pending, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.shop_id = shop_id; self.pending = pending; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        img = self.pending.get("image_url", "")
        interval = self.pending.get("restock_interval", 0)
        text = "\n".join([
            f"**Adding: {self.pending['name']}**",
            f"Price: {self.pending['price']} | Stock: {self.pending['stock']}",
            f"Category: {self.pending['category']}",
            f"Image: {img or '*none*'}",
            f"Restock: {interval} min" if interval else "Restock: never",
        ])
        img_btn     = Button(label=t(self.gid, "add_image_btn"), style=discord.ButtonStyle.secondary, custom_id="si2_img")
        restock_btn = Button(label="Set Restock",                 style=discord.ButtonStyle.secondary, custom_id="si2_rs")
        save_btn    = Button(label="Save Item",                   style=discord.ButtonStyle.green,     custom_id="si2_save")
        bk_btn      = Button(label=t(self.gid, "back_btn"),       style=discord.ButtonStyle.secondary, custom_id="si2_bk")
        img_btn.callback     = self._set_img
        restock_btn.callback = self._set_restock
        save_btn.callback    = self._save
        bk_btn.callback      = self._back

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(img_btn, restock_btn),
            ActionRow(save_btn, bk_btn),
        ))

    async def _set_img(self, ix):
        await ix.response.send_modal(_ImageModal(self.gid, self))

    async def _set_restock(self, ix):
        await ix.response.send_modal(_RestockModal(self.gid, self))

    async def _save(self, ix):
        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.shop_id)
        if not shop:
            await ix.response.send_message("Shop not found.", ephemeral=True); return
        key  = slugify(self.pending["name"]) or str(uuid.uuid4())[:8]
        self.pending["last_restock"] = time.time()
        shop.setdefault("items", {})[key] = self.pending
        save_shops(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _ImageModal(Modal, title="Set Image URL"):
    f_url = TextInput(label="Image URL (optional)", max_length=300, required=False)

    def __init__(self, gid, parent):
        super().__init__(); self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        self.parent.pending["image_url"] = (self.f_url.value or "").strip()
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _RestockModal(Modal, title="Set Restock Interval"):
    f_mins = TextInput(label="Restock every N minutes (0 = never)", max_length=10, default="0")

    def __init__(self, gid, parent):
        super().__init__(); self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        try: mins = max(0, int(self.f_mins.value.strip()))
        except: mins = 0
        self.parent.pending["restock_interval"] = mins
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Shop setup wizard ─────────────────────────────────────────────────────────

class ShopBasicModal(Modal, title="Create Shop"):
    f_name  = TextInput(label="Shop Name",        max_length=60)
    f_owner = TextInput(label="Owner",             max_length=60)
    f_desc  = TextInput(label="Description",      style=discord.TextStyle.paragraph, max_length=300)
    f_img   = TextInput(label="Image URL (optional)", max_length=300, required=False)

    def __init__(self, gid, parent):
        super().__init__(); self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        data = {
            "name":        self.f_name.value.strip(),
            "owner":       self.f_owner.value.strip(),
            "description": self.f_desc.value.strip(),
            "image_url":   (self.f_img.value or "").strip(),
        }
        await ix.response.edit_message(view=ShopStyleView(self.gid, data, self.parent))


class ShopStyleView(LayoutView):
    def __init__(self, gid, data, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.data = data; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        ch  = Button(label=t(self.gid, "style_channel"), style=discord.ButtonStyle.primary,   custom_id="ss_ch")
        thr = Button(label=t(self.gid, "style_thread"),  style=discord.ButtonStyle.secondary, custom_id="ss_thr")
        frm = Button(label=t(self.gid, "style_forum"),   style=discord.ButtonStyle.secondary, custom_id="ss_frm")
        bk  = Button(label=t(self.gid, "back_btn"),       style=discord.ButtonStyle.secondary, custom_id="ss_bk")
        ch.callback  = lambda ix: ix.response.edit_message(view=ShopChannelPickView(self.gid, self.data, "channel", self.parent))
        thr.callback = lambda ix: ix.response.edit_message(view=ShopChannelPickView(self.gid, self.data, "thread",  self.parent))
        frm.callback = lambda ix: ix.response.edit_message(view=ShopChannelPickView(self.gid, self.data, "forum",   self.parent))
        bk.callback  = self._back
        self.add_item(Container(
            TextDisplay(f"**{t(self.gid,'shop_setup_title')}**\n**{self.data['name']}**\n\nChoose where the shop will be posted:"),
            Separator(),
            ActionRow(ch, thr, frm),
            ActionRow(bk),
        ))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class ShopChannelPickView(LayoutView):
    def __init__(self, gid, data, style, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.data = {**data, "style": style}; self.parent = parent

        if style == "forum":
            ch_sel = discord.ui.ChannelSelect(
                placeholder="Select forum channel",
                channel_types=[discord.ChannelType.forum],
            )
        else:
            ch_sel = discord.ui.ChannelSelect(
                placeholder="Select text channel",
                channel_types=[discord.ChannelType.text],
            )
        ch_sel.callback = self._ch_cb

        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="scp_bk")
        bk.callback = self._back

        self.add_item(Container(
            TextDisplay(f"**{t(gid,'shop_channel_set')}**"),
            Separator(), ActionRow(ch_sel), ActionRow(bk),
        ))

    async def _ch_cb(self, ix: discord.Interaction):
        cid = str(ix.data["values"][0])
        self.data["channel_id"] = cid
        await self._finalize(ix)

    async def _finalize(self, ix: discord.Interaction):
        db = load_shops(self.gid)
        shop_id = str(uuid.uuid4())[:8]
        shop_data = {**self.data, "items": {}, "message_id": None}
        db["shops"][shop_id] = shop_data
        save_shops(self.gid, db)

        ch = ix.guild.get_channel(int(self.data["channel_id"])) if ix.guild else None
        if ch:
            try: await _post_shop_message(ch, shop_id, shop_data, self.gid)
            except Exception: pass

        self.parent._build()
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(t(self.gid, "shop_created", name=self.data["name"]), ephemeral=True)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


async def _post_shop_message(ch, shop_id, shop_data, gid):
    img = shop_data.get("image_url", "")
    text = "\n".join([
        f"**🏪 {shop_data['name']}**",
        f"*{shop_data['description']}*",
        f"Owner: {shop_data['owner']}",
        "",
        "Use `/shop` to browse and buy items!",
    ])
    v = LayoutView(timeout=None)
    children = [TextDisplay(text)]
    if img and img.startswith(("http://", "https://")):
        children += [Separator(), MediaGallery(MediaGalleryItem(media=img))]
    v.add_item(Container(*children))

    style = shop_data.get("style", "channel")
    if style == "forum" and hasattr(ch, "create_thread"):
        thread_name = shop_data["name"]
        msg = await ch.create_thread(name=thread_name, content=None)
        db = load_shops(gid); db["shops"][shop_id]["thread_id"] = str(msg.id)
        save_shops(gid, db)
    else:
        msg = await ch.send(view=v)
        db = load_shops(gid); db["shops"][shop_id]["message_id"] = str(msg.id)
        save_shops(gid, db)


# ── /shop-setup ───────────────────────────────────────────────────────────────

class ShopSetupMainView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid; self._build()

    def _build(self):
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})
        lines = [f"**{t(self.gid,'shop_setup_title')}**", ""]
        if shops:
            for sid, s in list(shops.items())[:8]:
                lines.append(f"• **{s['name']}** (`{sid}`)")
        else:
            lines.append(t(self.gid, "no_shops"))

        new_btn  = Button(label="Create New Shop", style=discord.ButtonStyle.green,  custom_id="ssu_new")
        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="ssu_done")
        new_btn.callback  = self._new
        done_btn.callback = self._done
        self.add_item(Container(TextDisplay("\n".join(lines)), Separator(), ActionRow(new_btn), ActionRow(done_btn)))

    async def _new(self, ix): await ix.response.send_modal(ShopBasicModal(self.gid, self))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="shop-setup", description="Create and manage shops", guild=GUILD2_OBJ)
@_is_admin()
async def shop_setup_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=ShopSetupMainView(ix.guild_id), ephemeral=True)

@shop_setup_cmd.error
async def shop_setup_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)


# ── /shop-config ──────────────────────────────────────────────────────────────

class ShopConfigView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid; self.sel_shop = None; self._build()

    def _build(self):
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})

        opts = ([discord.SelectOption(label=s["name"][:100], value=sid,
                                      default=(sid == self.sel_shop))
                 for sid, s in list(shops.items())[:25]]
                or [discord.SelectOption(label="No shops", value="__none__")])

        sel = Select(placeholder="Select shop to configure", options=opts)
        sel.callback = self._sel

        children = [TextDisplay(f"**{t(self.gid,'shop_config_title')}**"), Separator(), ActionRow(sel)]

        if self.sel_shop and self.sel_shop in shops:
            shop = shops[self.sel_shop]
            items = shop.get("items", {})
            item_lines = [f"**{shop['name']}** — {len(items)} item(s)", ""]
            for iid, it in list(items.items())[:6]:
                stock_str = t(self.gid, "unlimited_stock") if it.get("stock", -1) < 0 else str(it["stock"])
                item_lines.append(f"• {it.get('emoji','📦')} **{it['name']}** — {it['price']} | Stock: {stock_str}")

            add_btn = Button(label="Add Item",    style=discord.ButtonStyle.green,  custom_id="sc_add")
            del_btn = Button(label="Delete Shop", style=discord.ButtonStyle.danger, custom_id="sc_del")
            add_btn.callback = self._add_item; del_btn.callback = self._del_shop
            children += [Separator(), TextDisplay("\n".join(item_lines)), ActionRow(add_btn, del_btn)]

        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="sc_done")
        done_btn.callback = self._done
        children.append(ActionRow(done_btn))
        self.add_item(Container(*children))

    async def _sel(self, ix):
        v = ix.data["values"][0]; self.sel_shop = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _add_item(self, ix):
        await ix.response.send_modal(ShopItemModal1(self.gid, self.sel_shop, self))

    async def _del_shop(self, ix):
        db = load_shops(self.gid)
        db["shops"].pop(self.sel_shop, None)
        save_shops(self.gid, db); self.sel_shop = None
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="shop-config", description="Configure shop items", guild=GUILD2_OBJ)
@_is_admin()
async def shop_config_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=ShopConfigView(ix.guild_id), ephemeral=True)

@shop_config_cmd.error
async def shop_config_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)


# ── /shop (player) ────────────────────────────────────────────────────────────

class ShopListView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid; self._build()

    def _build(self):
        self.clear_items()
        db    = load_shops(self.gid)
        shops = db.get("shops", {})

        if not shops:
            self.add_item(Container(TextDisplay(t(self.gid, "no_shops")))); return

        lines = [f"**{t(self.gid,'shop_title')}**", ""]
        for s in list(shops.values())[:6]:
            lines.append(f"🏪 **{s['name']}** — {s.get('description','')[:60]}")

        opts = [discord.SelectOption(label=s["name"][:100], value=sid)
                for sid, s in list(shops.items())[:25]]
        sel = Select(placeholder="Browse a shop…", options=opts)
        sel.callback = self._sel
        self.add_item(Container(TextDisplay("\n".join(lines)), Separator(), ActionRow(sel)))

    async def _sel(self, ix):
        await ix.response.edit_message(view=ShopItemsView(self.gid, ix.data["values"][0], ix.user.id, self))


class ShopItemsView(LayoutView):
    def __init__(self, gid, shop_id, uid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.shop_id = shop_id; self.uid = uid; self.parent = parent
        self.sel_item = None; self._build()

    def _build(self):
        self.clear_items()
        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.shop_id, {})
        cfg  = load_config(self.gid)
        items = shop.get("items", {})

        lines = [f"**🏪 {shop.get('name','Shop')}**", f"*{shop.get('description','')}*", ""]
        opts  = []
        for iid, it in list(items.items())[:25]:
            stock = it.get("stock", -1)
            stock_str = t(self.gid, "unlimited_stock") if stock < 0 else str(stock)
            is_out = (stock == 0)
            price_str = format_currency(it["price"], cfg)
            lines.append(f"{'~~' if is_out else ''}**{it.get('emoji','📦')} {it['name']}** — {price_str} | {stock_str}{'~~' if is_out else ''}")
            label = f"{it['name']} [{price_str}]{' [OUT]' if is_out else ''}"
            opts.append(discord.SelectOption(label=label[:100], value=iid,
                                              default=(iid == self.sel_item)))

        if not opts: opts = [discord.SelectOption(label="No items", value="__none__")]
        sel = Select(placeholder="Select item to buy", options=opts)
        sel.callback = self._sel_item

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="si_bk")
        bk.callback = self._back

        children = [TextDisplay("\n".join(lines)), Separator(), ActionRow(sel)]

        if self.sel_item and self.sel_item in items:
            it = items[self.sel_item]
            stock = it.get("stock", -1)
            is_out = (stock == 0)
            price_str = format_currency(it["price"], cfg)
            detail = [
                f"**{it.get('emoji','📦')} {it['name']}**",
                f"*{it.get('description','')[:200]}*",
                f"Price: {price_str}",
                f"Stock: {t(self.gid,'unlimited_stock') if stock < 0 else stock}",
            ]
            ri = it.get("restock_interval", 0)
            if ri > 0:
                detail.append(f"Restocks every {ri} min")

            children.append(TextDisplay("\n".join(detail)))

            if it.get("image_url","").startswith(("http://","https://")):
                children += [Separator(), MediaGallery(MediaGalleryItem(media=it["image_url"]))]

            buy_btn = Button(label=t(self.gid, "buy_btn"),
                             style=discord.ButtonStyle.green if not is_out else discord.ButtonStyle.secondary,
                             custom_id="si_buy", disabled=is_out)
            buy_btn.callback = self._buy
            children.append(ActionRow(buy_btn))

        children.append(ActionRow(bk))
        self.add_item(Container(*children))

    async def _sel_item(self, ix):
        v = ix.data["values"][0]; self.sel_item = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _buy(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        db   = load_shops(self.gid)
        shop = db.get("shops", {}).get(self.shop_id, {})
        it   = shop.get("items", {}).get(self.sel_item)
        if not it:
            await ix.response.send_message("Item not found.", ephemeral=True); return

        cfg     = load_config(self.gid)
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        balance = player.get("balance", 0)
        price   = it.get("price", 0)
        stock   = it.get("stock", -1)

        if stock == 0:
            await ix.response.send_message(t(self.gid, "out_of_stock_label"), ephemeral=True); return
        if balance < price:
            await ix.response.send_message(
                t(self.gid, "insufficient_funds",
                  price=format_currency(price, cfg),
                  balance=format_currency(balance, cfg)),
                ephemeral=True); return

        player["balance"] = balance - price
        player.setdefault("inventory", {})[self.sel_item] = (
            player["inventory"].get(self.sel_item, 0) + 1
        )
        players[str(self.uid)] = player
        save_players(self.gid, players)

        if stock > 0:
            it["stock"] = stock - 1
            save_shops(self.gid, db)

        new_bal = player["balance"]
        await ix.response.send_message(
            t(self.gid, "purchase_success",
              item=it["name"],
              price=format_currency(price, cfg),
              balance=format_currency(new_bal, cfg)),
            ephemeral=True)
        self._build()
        await ix.edit_original_response(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


@bot.tree.command(name="shop", description="Browse and buy from shops", guild=GUILD2_OBJ)
async def shop_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=ShopListView(ix.guild_id), ephemeral=True)
