"""Item admin panel — categories, items, give/remove; player inventory."""
import discord
from discord import app_commands
from discord.ui import LayoutView, Container, TextDisplay, Separator, ActionRow, Button, Select, Modal, TextInput, MediaGallery
from discord.components import MediaGalleryItem

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_players, save_players, load_items, save_items,
    select_options_from_list, slugify, is_url, cv2_dm,
)


def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Text helpers ──────────────────────────────────────────────────────────────

def _panel_text(gid):
    db = load_items(gid)
    return (f"**{t(gid,'item_admin_title')}**\n\n"
            f"**Categories:** {len(db.get('categories',{}))}\n"
            f"**Items:** {len(db.get('items',{}))}")

def _cats_text(gid):
    db = load_items(gid); cats = db.get("categories", {}); order = db.get("category_order", [])
    lines = [f"`{c}` {cats[c].get('emoji','📦')} **{cats[c].get('name',c)}** (pos {i+1})"
             for i, c in enumerate(order) if c in cats]
    return "**Categories**\n\n" + ("\n".join(lines) if lines else "*No categories*")


# ── Main panel ────────────────────────────────────────────────────────────────

class ItemAdminMainView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _b(label, cb, cid, style=discord.ButtonStyle.secondary):
            b = Button(label=label, style=style, custom_id=cid)
            b.callback = cb
            return b

        done = _b(t(gid, "done_btn"), self._done, "ia_done", discord.ButtonStyle.danger)

        self.add_item(Container(
            TextDisplay(_panel_text(gid)),
            Separator(),
            ActionRow(
                _b("Categories",  self._cats,   "ia_cats"),
                _b("Create Item", self._create, "ia_create"),
                _b("Edit Item",   self._edit,   "ia_edit"),
            ),
            ActionRow(
                _b("Give Items",   self._give,   "ia_give"),
                _b("Remove Items", self._remove, "ia_remove"),
                _b("View Item",    self._view,   "ia_view"),
            ),
            ActionRow(done),
        ))

    async def _cats(self, ix):   await ix.response.edit_message(view=CategoriesView(self.gid, self))
    async def _create(self, ix): await ix.response.send_modal(CreateItemModal(self.gid, None, self))
    async def _edit(self, ix):   await ix.response.edit_message(view=EditItemView(self.gid, self))
    async def _give(self, ix):   await ix.response.edit_message(view=GiveRemoveView(self.gid, "give", self))
    async def _remove(self, ix): await ix.response.edit_message(view=GiveRemoveView(self.gid, "remove", self))
    async def _view(self, ix):   await ix.response.edit_message(view=ViewItemView(self.gid, self))

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── Categories ────────────────────────────────────────────────────────────────

class AddCatModal(Modal, title="Add Category"):
    name  = TextInput(label="Name",             max_length=60)
    emoji = TextInput(label="Emoji (optional)", max_length=20, required=False)

    def __init__(self, gid, parent):
        super().__init__()
        self.gid = gid; self.parent = parent

    async def on_submit(self, ix):
        db = load_items(self.gid)
        cid = slugify(self.name.value.strip())
        if cid and cid not in db["categories"]:
            db["categories"][cid] = {
                "name":  self.name.value.strip(),
                "emoji": (self.emoji.value or "📦").strip() or "📦",
            }
            db["category_order"].append(cid)
            save_items(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class CategoriesView(LayoutView):
    def __init__(self, gid, parent, sel=None):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent; self.sel = sel
        self._build()

    def _build(self):
        self.clear_items()
        db = load_items(self.gid); cats = db.get("categories", {}); order = db.get("category_order", [])
        opts = ([discord.SelectOption(
                    label=f"{cats[c].get('emoji','📦')} {cats[c].get('name',c)}",
                    value=c, default=(c == self.sel))
                 for c in order if c in cats]
                or [discord.SelectOption(label="—", value="__none__")])

        sel  = Select(placeholder="Select category", options=opts)
        add  = Button(label="Add",    style=discord.ButtonStyle.green,     custom_id="cat_add")
        dlt  = Button(label="Delete", style=discord.ButtonStyle.danger,    custom_id="cat_del")
        up   = Button(label="▲ Up",   style=discord.ButtonStyle.secondary, custom_id="cat_up")
        dn   = Button(label="▼ Down", style=discord.ButtonStyle.secondary, custom_id="cat_dn")
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="cat_back")
        sel.callback  = self._sel
        add.callback  = self._add
        dlt.callback  = self._del
        up.callback   = self._up
        dn.callback   = self._dn
        back.callback = self._back

        self.add_item(Container(
            TextDisplay(_cats_text(self.gid)),
            Separator(),
            ActionRow(sel),
            ActionRow(add, dlt),
            ActionRow(up, dn),
            ActionRow(back),
        ))

    async def _sel(self, ix):
        v = ix.data["values"][0]; self.sel = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _add(self, ix): await ix.response.send_modal(AddCatModal(self.gid, self))

    async def _del(self, ix):
        if not self.sel: await ix.response.send_message("Select a category first.", ephemeral=True); return
        db = load_items(self.gid)
        db["categories"].pop(self.sel, None)
        order = db["category_order"]
        if self.sel in order: order.remove(self.sel)
        self.sel = None; save_items(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _up(self, ix):
        if not self.sel: await ix.response.send_message("Select first.", ephemeral=True); return
        db = load_items(self.gid); o = db["category_order"]
        i = o.index(self.sel) if self.sel in o else -1
        if i > 0: o[i], o[i-1] = o[i-1], o[i]; save_items(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _dn(self, ix):
        if not self.sel: await ix.response.send_message("Select first.", ephemeral=True); return
        db = load_items(self.gid); o = db["category_order"]
        i = o.index(self.sel) if self.sel in o else -1
        if 0 <= i < len(o) - 1: o[i], o[i+1] = o[i+1], o[i]; save_items(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Create / Edit Item (2-step) ───────────────────────────────────────────────

class CreateItemModal(Modal, title="Create / Edit Item"):
    f_name     = TextInput(label="Item Name",                    max_length=60)
    f_cat      = TextInput(label="Category name or ID",          max_length=60,  required=False)
    f_desc     = TextInput(label="Description",                  style=discord.TextStyle.paragraph, max_length=400, required=False)
    f_emoji    = TextInput(label="Emoji (optional)",             max_length=20,  required=False)
    f_when_use = TextInput(label="When Used (empty = material)", style=discord.TextStyle.paragraph, max_length=300, required=False)

    def __init__(self, gid, item_id, parent, prefill=None):
        super().__init__()
        self.gid = gid; self.item_id = item_id; self.parent = parent
        if prefill:
            self.f_name.default     = prefill.get("name", "")
            self.f_cat.default      = prefill.get("category", "")
            self.f_desc.default     = prefill.get("description", "")
            self.f_emoji.default    = prefill.get("emoji", "")
            self.f_when_use.default = prefill.get("when_use", "")

    async def on_submit(self, ix):
        name   = (self.f_name.value or "").strip()
        cat_in = (self.f_cat.value or "").strip()
        db     = load_items(self.gid); cats = db.get("categories", {})
        cat_id = (cat_in if cat_in in cats
                  else next((k for k, v in cats.items() if v.get("name", "").lower() == cat_in.lower()),
                            slugify(cat_in)))
        iid = self.item_id or slugify(name)
        if not iid:
            await ix.response.send_message("Invalid name.", ephemeral=True); return
        existing = db.get("items", {}).get(iid, {})
        data = {
            "name":        name,
            "category":    cat_id,
            "description": (self.f_desc.value or "").strip(),
            "emoji":       (self.f_emoji.value or "📦").strip() or "📦",
            "when_use":    (self.f_when_use.value or "").strip(),
            "image_url":   existing.get("image_url", ""),
            "sell_price":  existing.get("sell_price", 0),
        }
        await ix.response.edit_message(view=ItemStep2View(self.gid, iid, data, self.parent))


class ItemStep2View(LayoutView):
    def __init__(self, gid, iid, data: dict, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.iid = iid; self.data = data; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        name     = self.data.get("name", "")
        emoji    = self.data.get("emoji", "📦")
        when_use = self.data.get("when_use", "")
        img      = self.data.get("image_url", "")
        price    = self.data.get("sell_price", 0)
        tag      = t(self.gid, "usable_tag") if when_use else t(self.gid, "material_tag")
        lines = [
            f"**{emoji} {name}** — `{tag}`",
            "",
            f"**When Used:** {when_use or '*Material item (cannot be used)*'}",
            f"**Image:** {img or '*None*'}",
            f"**Sell Price:** {price}",
        ]
        img_btn   = Button(label=t(self.gid, "add_image_btn"), style=discord.ButtonStyle.secondary, custom_id="s2_img")
        price_btn = Button(label="💰 Set Sell Price",           style=discord.ButtonStyle.secondary, custom_id="s2_price")
        save_btn  = Button(label="💾 Save",                     style=discord.ButtonStyle.green,     custom_id="s2_save")
        bk_btn    = Button(label=t(self.gid, "back_btn"),       style=discord.ButtonStyle.secondary, custom_id="s2_bk")
        img_btn.callback   = self._set_image
        price_btn.callback = self._set_price
        save_btn.callback  = self._save
        bk_btn.callback    = self._back
        children = [TextDisplay("\n".join(lines)), Separator()]
        if img and is_url(img):
            children.append(MediaGallery(MediaGalleryItem(media=img)))
            children.append(Separator())
        children.append(ActionRow(img_btn, price_btn))
        children.append(ActionRow(save_btn, bk_btn))
        self.add_item(Container(*children))

    async def _set_image(self, ix):  await ix.response.send_modal(_ItemImageModal(self))
    async def _set_price(self, ix):  await ix.response.send_modal(_ItemSellPriceModal(self))

    async def _save(self, ix):
        db = load_items(self.gid)
        db.setdefault("items", {})[self.iid] = {
            "name":        self.data["name"],
            "category":    self.data.get("category", ""),
            "description": self.data.get("description", ""),
            "emoji":       self.data.get("emoji", "📦"),
            "when_use":    self.data.get("when_use", ""),
            "image_url":   self.data.get("image_url", ""),
            "sell_price":  self.data.get("sell_price", 0),
        }
        save_items(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class _ItemImageModal(Modal, title="Set Item Image URL"):
    url = TextInput(label="Image URL (leave blank to clear)", max_length=500, required=False)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.url.default = parent.data.get("image_url", "")

    async def on_submit(self, ix):
        self.parent.data["image_url"] = (self.url.value or "").strip()
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class _ItemSellPriceModal(Modal, title="Set Sell Price"):
    price = TextInput(label="Sell Price (0 = not sellable)", max_length=10)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.price.default = str(parent.data.get("sell_price", 0))

    async def on_submit(self, ix):
        try:
            self.parent.data["sell_price"] = max(0, int((self.price.value or "0").strip()))
        except ValueError:
            pass
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class EditItemView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        db = load_items(self.gid); items = db.get("items", {})
        opts = ([discord.SelectOption(label=f"{d.get('emoji','📦')} {d.get('name',iid)}", value=iid)
                 for iid, d in list(items.items())[:25]]
                or [discord.SelectOption(label="No items", value="__none__")])
        sel  = Select(placeholder="Select item to edit", options=opts)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="ei_back")
        sel.callback  = self._cb
        back.callback = self._back
        self.add_item(Container(
            TextDisplay("**Edit Item**\n\nSelect an item to edit:"),
            Separator(),
            ActionRow(sel),
            ActionRow(back),
        ))

    async def _cb(self, ix):
        iid = ix.data["values"][0]
        if iid == "__none__": await ix.response.send_message("No items.", ephemeral=True); return
        it = load_items(self.gid).get("items", {}).get(iid, {})
        await ix.response.send_modal(CreateItemModal(self.gid, iid, self.parent, prefill=it))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class ViewItemView(LayoutView):
    def __init__(self, gid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        db = load_items(self.gid); items = db.get("items", {})
        opts = ([discord.SelectOption(label=f"{d.get('emoji','📦')} {d.get('name',iid)}", value=iid)
                 for iid, d in list(items.items())[:25]]
                or [discord.SelectOption(label="No items", value="__none__")])
        sel  = Select(placeholder="Select item to view", options=opts)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="vi_back")
        sel.callback  = self._cb
        back.callback = self._back
        self.add_item(Container(
            TextDisplay("**View Item**\n\nSelect an item to view:"),
            Separator(),
            ActionRow(sel),
            ActionRow(back),
        ))

    async def _cb(self, ix):
        iid = ix.data["values"][0]
        if iid == "__none__": await ix.response.send_message("No items.", ephemeral=True); return
        db   = load_items(self.gid); it = db.get("items", {}).get(iid, {})
        cats = db.get("categories", {}); cat_name = cats.get(it.get("category", ""), {}).get("name", "*Uncategorized*")
        when_use = it.get("when_use", "")
        tag = t(self.gid, "usable_tag") if when_use else t(self.gid, "material_tag")
        lines = [
            f"**{it.get('emoji','📦')} {it.get('name', iid)}** — `{tag}`",
            "",
            f"**Category:** {cat_name}",
            f"**Description:** {it.get('description') or '*None*'}",
            f"**When Used:** {when_use or '*Material item*'}",
            f"**Sell Price:** {it.get('sell_price', 0)}",
        ]
        if it.get("image_url"): lines.append(f"**Image:** [View]({it['image_url']})")
        self.clear_items()
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="vi_back2")
        back.callback = self._back2
        children = [TextDisplay("\n".join(lines)), Separator()]
        if it.get("image_url") and is_url(it["image_url"]):
            children.append(MediaGallery(MediaGalleryItem(media=it["image_url"])))
            children.append(Separator())
        children.append(ActionRow(back))
        self.add_item(Container(*children))
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back2(self, ix):
        self._build()
        await ix.response.edit_message(view=self)


# ── Give / Remove ─────────────────────────────────────────────────────────────

class _SetQtyModal(Modal, title="Set Quantity"):
    qty = TextInput(label="Quantity", max_length=10, default="1")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, ix):
        try: self.parent.qty = max(1, int(self.qty.value.strip()))
        except: pass
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class GiveRemoveView(LayoutView):
    def __init__(self, gid, mode, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mode = mode; self.parent = parent
        self.sel_item = None; self.sel_users = []; self.sel_role = None; self.qty = 1
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_items(self.gid); items = db.get("items", {})
        opts  = ([discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name',iid)}", value=iid,
                    default=(iid == self.sel_item))
                  for iid, d in list(items.items())[:25]]
                 or [discord.SelectOption(label="No items", value="__none__")])

        sel = Select(placeholder="Select item", options=opts)
        us  = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25)
        rs  = discord.ui.RoleSelect(placeholder="Via role")

        la = "Give to Users"  if self.mode == "give" else "Remove from Users"
        lb = "Give via Role"  if self.mode == "give" else "Remove via Role"
        au = Button(label=la,                 style=discord.ButtonStyle.green,     custom_id="gr_au")
        ar = Button(label=lb,                 style=discord.ButtonStyle.green,     custom_id="gr_ar")
        sq = Button(label=f"Qty: {self.qty}", style=discord.ButtonStyle.secondary, custom_id="gr_sq")
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk")

        sel.callback = self._item_cb
        us.callback  = self._user_cb
        rs.callback  = self._role_cb
        au.callback  = self._act_users
        ar.callback  = self._act_role
        sq.callback  = self._set_qty
        bk.callback  = self._back

        mode_label = "Give Items" if self.mode == "give" else "Remove Items"
        self.add_item(Container(
            TextDisplay(f"**{mode_label}**"),
            Separator(),
            ActionRow(sel),
            ActionRow(us),
            ActionRow(rs),
            ActionRow(au, ar),
            ActionRow(sq, bk),
        ))

    async def _item_cb(self, ix):
        v = ix.data["values"][0]; self.sel_item = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _user_cb(self, ix): self.sel_users = ix.data["values"]; await ix.response.defer()

    async def _role_cb(self, ix):
        self.sel_role = ix.data["values"][0] if ix.data["values"] else None
        await ix.response.defer()

    async def _set_qty(self, ix):
        await ix.response.send_modal(_SetQtyModal(self))

    def _apply(self, players, uid, qty):
        p   = players.setdefault(uid, {"inventory": {}})
        inv = p.setdefault("inventory", {})
        if self.mode == "give":
            inv[self.sel_item] = inv.get(self.sel_item, 0) + qty
        else:
            inv[self.sel_item] = max(0, inv.get(self.sel_item, 0) - qty)

    async def _act_users(self, ix):
        if not self.sel_item or not self.sel_users:
            await ix.response.send_message("Select item and users.", ephemeral=True); return
        ps = load_players(self.gid)
        for uid in self.sel_users: self._apply(ps, uid, self.qty)
        save_players(self.gid, ps)
        word = "given to" if self.mode == "give" else "removed from"
        self.clear_items()
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk2")
        bk.callback = self._back
        self.add_item(Container(
            TextDisplay(f"✅ Item {word} {len(self.sel_users)} user(s)."),
            Separator(), ActionRow(bk)
        ))
        await ix.response.edit_message(view=self)

    async def _act_role(self, ix):
        if not self.sel_item or not self.sel_role:
            await ix.response.send_message("Select item and role.", ephemeral=True); return
        role = ix.guild.get_role(int(self.sel_role))
        if not role: await ix.response.send_message("Role not found.", ephemeral=True); return
        ps = load_players(self.gid)
        for m in role.members: self._apply(ps, str(m.id), self.qty)
        save_players(self.gid, ps)
        word = "given to" if self.mode == "give" else "removed from"
        self.clear_items()
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk3")
        bk.callback = self._back
        self.add_item(Container(
            TextDisplay(f"✅ Item {word} {len(role.members)} member(s)."),
            Separator(), ActionRow(bk)
        ))
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Player InventoryView ──────────────────────────────────────────────────────

class InventoryView(LayoutView):
    def __init__(self, uid: int, gid: int, back_view=None):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.back_view = back_view
        self.sel_cat = None; self.sel_item_id = None
        self._build_categories()

    def _build_categories(self):
        self.clear_items()
        player    = load_players(self.gid).get(str(self.uid), {})
        items_db  = load_items(self.gid)
        inventory = player.get("inventory", {})
        all_items = items_db.get("items", {})
        categories = items_db.get("categories", {})
        cat_order  = items_db.get("category_order", [])

        player_cats: set = set()
        for iid, qty in inventory.items():
            if qty > 0 and iid in all_items:
                cat_id = all_items[iid].get("category", "")
                player_cats.add(cat_id if cat_id else "__uncategorized__")

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk")
        bk.callback = self._back

        if not player_cats:
            self.add_item(Container(
                TextDisplay(f"**🎒 {t(self.gid,'inventory_btn')}**\n\n{t(self.gid,'inventory_empty')}"),
                Separator(), ActionRow(bk),
            ))
            return

        opts = []
        for cat_id in cat_order:
            if cat_id in player_cats and cat_id in categories:
                cat = categories[cat_id]
                opts.append(discord.SelectOption(
                    label=f"{cat.get('emoji','📦')} {cat.get('name', cat_id)}",
                    value=cat_id, default=(cat_id == self.sel_cat),
                ))
        if "__uncategorized__" in player_cats:
            opts.append(discord.SelectOption(label="📦 Other", value="__uncategorized__",
                                              default=("__uncategorized__" == self.sel_cat)))
        if not opts:
            opts = [discord.SelectOption(label="—", value="__none__")]

        sel = Select(placeholder="Select category", options=opts[:25])
        sel.callback = self._cat_cb
        self.add_item(Container(
            TextDisplay(f"**🎒 {t(self.gid,'inventory_btn')}**\n\nSelect a category:"),
            Separator(), ActionRow(sel), ActionRow(bk),
        ))

    async def _cat_cb(self, ix):
        v = ix.data["values"][0]
        if v == "__none__": await ix.response.defer(); return
        self.sel_cat = v
        self._build_items()
        await ix.response.edit_message(view=self)

    def _build_items(self):
        self.clear_items()
        player    = load_players(self.gid).get(str(self.uid), {})
        items_db  = load_items(self.gid)
        inventory = player.get("inventory", {})
        all_items = items_db.get("items", {})
        categories = items_db.get("categories", {})

        cat_name = "Other"
        if self.sel_cat and self.sel_cat != "__uncategorized__":
            cat_name = categories.get(self.sel_cat, {}).get("name", self.sel_cat)

        opts = []
        for iid, qty in inventory.items():
            if qty <= 0 or iid not in all_items: continue
            item = all_items[iid]
            item_cat = item.get("category", "")
            if self.sel_cat == "__uncategorized__":
                if item_cat: continue
            elif item_cat != self.sel_cat:
                continue
            opts.append(discord.SelectOption(
                label=f"{item.get('emoji','📦')} {item.get('name', iid)} ×{qty}",
                value=iid, default=(iid == self.sel_item_id),
            ))
        if not opts:
            opts = [discord.SelectOption(label="—", value="__none__")]

        sel = Select(placeholder="Select item", options=opts[:25])
        sel.callback = self._item_cb
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk2")
        bk.callback = self._back_to_cats
        self.add_item(Container(
            TextDisplay(f"**🎒 {cat_name}**\n\nSelect an item:"),
            Separator(), ActionRow(sel), ActionRow(bk),
        ))

    async def _item_cb(self, ix):
        v = ix.data["values"][0]
        if v == "__none__": await ix.response.defer(); return
        self.sel_item_id = v
        self._build_item_detail()
        await ix.response.edit_message(view=self)

    def _build_item_detail(self):
        self.clear_items()
        player    = load_players(self.gid).get(str(self.uid), {})
        items_db  = load_items(self.gid)
        item      = items_db.get("items", {}).get(self.sel_item_id, {})
        inventory = player.get("inventory", {})

        name        = item.get("name", self.sel_item_id)
        emoji       = item.get("emoji", "📦")
        desc        = item.get("description", "")
        sell_price  = item.get("sell_price", 0)
        img_url     = item.get("image_url", "")
        when_use    = item.get("when_use", "")
        is_material = not bool(when_use)
        qty         = inventory.get(self.sel_item_id, 0)

        tag = t(self.gid, "material_tag") if is_material else t(self.gid, "usable_tag")
        text_lines = [f"**{emoji} {name}** ×{qty}", "", f"**Type:** {tag}"]
        if desc:
            text_lines += ["", f"*{desc}*"]
        if sell_price:
            text_lines.append(f"**{t(self.gid,'balance_label')}:** {sell_price} per item")

        use_btn  = Button(label="✅ Use",                  style=discord.ButtonStyle.green,     custom_id="inv_use",  disabled=is_material)
        give_btn = Button(label="🎁 Give",                 style=discord.ButtonStyle.primary,   custom_id="inv_give")
        sell_btn = Button(label=f"💰 Sell ({sell_price})", style=discord.ButtonStyle.secondary, custom_id="inv_sell")
        bk_btn   = Button(label=t(self.gid, "back_btn"),  style=discord.ButtonStyle.secondary, custom_id="inv_bk3")
        use_btn.callback  = self._use
        give_btn.callback = self._give
        sell_btn.callback = self._sell
        bk_btn.callback   = self._back_to_items

        container_children = [TextDisplay("\n".join(text_lines)), Separator()]
        if img_url and is_url(img_url):
            container_children.append(MediaGallery(MediaGalleryItem(media=img_url)))
            container_children.append(Separator())
        container_children.append(ActionRow(use_btn, give_btn, sell_btn))
        container_children.append(ActionRow(bk_btn))
        self.add_item(Container(*container_children))

    async def _use(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        items_db = load_items(self.gid)
        item     = items_db.get("items", {}).get(self.sel_item_id, {})
        when_use = item.get("when_use", "")
        if not when_use:
            await ix.response.send_message("This item cannot be used (material item).", ephemeral=True); return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        inv     = player.setdefault("inventory", {})
        qty     = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True); return
        inv[self.sel_item_id]  = qty - 1
        players[str(self.uid)] = player
        save_players(self.gid, players)
        item_name = item.get("name", self.sel_item_id)
        item_emoji = item.get("emoji", "📦")
        self._build_categories()
        await ix.response.edit_message(view=self)
        try:
            await ix.channel.send(f"{item_emoji} **{ix.user.display_name}** used **{item_name}**\n\n{when_use}")
        except Exception:
            pass

    async def _give(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        self.clear_items()
        us = discord.ui.UserSelect(placeholder="Select recipient", min_values=1, max_values=1)
        us.callback = self._do_give
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk_give")
        bk.callback = self._back_to_items
        self.add_item(Container(
            TextDisplay("**🎁 Give Item**\n\nSelect a recipient:"),
            Separator(), ActionRow(us), ActionRow(bk),
        ))
        await ix.response.edit_message(view=self)

    async def _do_give(self, ix: discord.Interaction):
        if not ix.data.get("values"):
            await ix.response.defer(); return
        recipient_id = ix.data["values"][0]
        players  = load_players(self.gid)
        giver    = players.get(str(self.uid), {})
        inv      = giver.setdefault("inventory", {})
        qty      = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True); return
        inv[self.sel_item_id] = qty - 1
        recipient = players.setdefault(recipient_id, {"inventory": {}})
        rec_inv   = recipient.setdefault("inventory", {})
        rec_inv[self.sel_item_id] = rec_inv.get(self.sel_item_id, 0) + 1
        players[str(self.uid)] = giver
        players[recipient_id]  = recipient
        save_players(self.gid, players)
        item_name = load_items(self.gid).get("items", {}).get(self.sel_item_id, {}).get("name", self.sel_item_id)
        try:
            from aot_bot_instance import bot as _bot
            rec_user = await _bot.fetch_user(int(recipient_id))
            await cv2_dm(rec_user, t(self.gid, "item_given_msg", sender=ix.user.display_name, item=item_name))
        except Exception:
            pass
        self._build_categories()
        await ix.response.edit_message(view=self)

    async def _sell(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        inv     = player.setdefault("inventory", {})
        qty     = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True); return
        item       = load_items(self.gid).get("items", {}).get(self.sel_item_id, {})
        sell_price = item.get("sell_price", 0)
        item_name  = item.get("name", self.sel_item_id)
        inv[self.sel_item_id]  = qty - 1
        player["balance"]      = player.get("balance", 0) + sell_price
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await cv2_dm(ix.user, t(self.gid, "item_sold_msg", item=item_name, price=sell_price, balance=player["balance"]))
        self._build_categories()
        await ix.response.edit_message(view=self)

    async def _back(self, ix):
        if self.back_view:
            self.back_view._build()
            await ix.response.edit_message(view=self.back_view)
        else:
            self._build_categories()
            await ix.response.edit_message(view=self)

    async def _back_to_cats(self, ix):
        self.sel_item_id = None
        self._build_categories()
        await ix.response.edit_message(view=self)

    async def _back_to_items(self, ix):
        self._build_items()
        await ix.response.edit_message(view=self)


# ── Player items browser ──────────────────────────────────────────────────────

class PlayerItemsView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid; self.sel_cat = None
        self._build_cats()

    def _build_cats(self):
        self.clear_items()
        db        = load_items(self.gid)
        cats      = db.get("categories", {})
        cat_order = db.get("category_order", [])
        all_items = db.get("items", {})

        populated: set = set()
        for it in all_items.values():
            cat_id = it.get("category", "") or "__uncategorized__"
            populated.add(cat_id)

        opts = []
        for cid in cat_order:
            if cid in cats and cid in populated:
                cat = cats[cid]
                opts.append(discord.SelectOption(
                    label=f"{cat.get('emoji','📦')} {cat.get('name', cid)}",
                    value=cid, default=(cid == self.sel_cat)))
        if "__uncategorized__" in populated:
            opts.append(discord.SelectOption(label="📦 Other", value="__uncategorized__",
                                              default=("__uncategorized__" == self.sel_cat)))

        if not opts:
            self.add_item(Container(TextDisplay(f"**{t(self.gid,'items_title')}**\n\n*No items available.*")))
            return

        sel = Select(placeholder="Select category", options=opts[:25])
        sel.callback = self._cat_cb
        self.add_item(Container(
            TextDisplay(f"**{t(self.gid,'items_title')}**\n\nSelect a category:"),
            Separator(), ActionRow(sel),
        ))

    async def _cat_cb(self, ix):
        self.sel_cat = ix.data["values"][0]
        self._build_items()
        await ix.response.edit_message(view=self)

    def _build_items(self):
        self.clear_items()
        db        = load_items(self.gid)
        cats      = db.get("categories", {})
        all_items = db.get("items", {})

        cat_name = "Other" if self.sel_cat == "__uncategorized__" else cats.get(self.sel_cat, {}).get("name", self.sel_cat)
        lines = [f"**📦 {cat_name}**", ""]
        for iid, item in all_items.items():
            item_cat = item.get("category", "") or "__uncategorized__"
            if item_cat != self.sel_cat: continue
            emoji    = item.get("emoji", "📦")
            name     = item.get("name", iid)
            desc     = item.get("description", "")
            when_use = item.get("when_use", "")
            tag      = t(self.gid, "usable_tag") if when_use else t(self.gid, "material_tag")
            lines.append(f"{emoji} **{name}** `[{tag}]`")
            if desc: lines.append(f"  *{desc[:100]}*")
            lines.append("")

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="pi_bk")
        bk.callback = self._back
        self.add_item(Container(TextDisplay("\n".join(lines)), Separator(), ActionRow(bk)))

    async def _back(self, ix):
        self._build_cats()
        await ix.response.edit_message(view=self)


@bot.tree.command(name="items", description="Browse all server items", guild=GUILD2_OBJ)
async def items_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=PlayerItemsView(ix.guild_id), ephemeral=True)


# ── /item-admin ───────────────────────────────────────────────────────────────

@bot.tree.command(name="item-admin", description="Item admin panel", guild=GUILD2_OBJ)
@is_admin()
async def item_admin_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=ItemAdminMainView(ix.guild_id), ephemeral=True)

@item_admin_cmd.error
async def item_admin_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
