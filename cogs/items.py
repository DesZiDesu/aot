"""Item admin panel — categories, items, give/remove; player inventory & item browser."""
import discord
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

from core.instance import bot
from core.shared import (
    t,
    load_players,
    save_players,
    load_items,
    save_items,
    select_options_from_list,
    slugify,
    is_url,
    send_dm,
    EMBED_COLOR,
)


# ── Permission check ──────────────────────────────────────────────────────────

def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild:
            return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (
            m.guild_permissions.administrator or m.guild_permissions.manage_guild
        )
    return app_commands.check(pred)


# ── DM helper ─────────────────────────────────────────────────────────────────

async def _dm(user, text: str):
    try:
        await send_dm(user, content=text)
    except Exception:
        pass


# ── Embed builders ────────────────────────────────────────────────────────────

def _panel_embed(gid: int) -> discord.Embed:
    db = load_items(gid)
    embed = discord.Embed(
        title=t(gid, "item_admin_title"),
        color=EMBED_COLOR,
    )
    embed.add_field(name="Categories", value=str(len(db.get("categories", {}))), inline=True)
    embed.add_field(name="Items",      value=str(len(db.get("items", {}))),      inline=True)
    return embed


def _cats_embed(gid: int) -> discord.Embed:
    db = load_items(gid)
    cats  = db.get("categories", {})
    order = db.get("category_order", [])
    lines = [
        f"`{c}` {cats[c].get('emoji','📦')} **{cats[c].get('name', c)}** (pos {i+1})"
        for i, c in enumerate(order)
        if c in cats
    ]
    embed = discord.Embed(
        title="Categories",
        description="\n".join(lines) if lines else "*No categories*",
        color=EMBED_COLOR,
    )
    return embed


def _item_embed(gid: int, iid: str) -> discord.Embed:
    db   = load_items(gid)
    item = db.get("items", {}).get(iid, {})
    cats = db.get("categories", {})
    cat_name = cats.get(item.get("category", ""), {}).get("name", "*Uncategorized*")
    when_use = item.get("when_use", "")
    tag = t(gid, "usable_tag") if when_use else t(gid, "material_tag")
    embed = discord.Embed(
        title=f"{item.get('emoji','📦')} {item.get('name', iid)}",
        description=item.get("description") or "*No description*",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Category",   value=cat_name,                            inline=True)
    embed.add_field(name="Type",       value=tag,                                 inline=True)
    embed.add_field(name="Sell Price", value=str(item.get("sell_price", 0)),      inline=True)
    embed.add_field(
        name="When Used",
        value=when_use if when_use else "*Material (cannot be used)*",
        inline=False,
    )
    img = item.get("image_url", "")
    if img and is_url(img):
        embed.set_image(url=img)
    return embed


# ── Main item-admin panel ─────────────────────────────────────────────────────

class ItemAdminMainView(View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        def _btn(label: str, cb, cid: str, style=discord.ButtonStyle.secondary, row: int = 0):
            b = Button(label=label, style=style, custom_id=cid, row=row)
            b.callback = cb
            return b

        # Row 0 — Item management
        self.add_item(_btn("Categories",   self._cats,        "ia_cats",   row=0))
        self.add_item(_btn("Create Item",  self._create,      "ia_create", row=0))
        self.add_item(_btn("Edit Item",    self._edit,        "ia_edit",   row=0))
        # Row 1 — Give/Remove/View
        self.add_item(_btn("Give Items",   self._give,        "ia_give",   row=1))
        self.add_item(_btn("Remove Items", self._remove,      "ia_remove", row=1))
        self.add_item(_btn("View Item",    self._view,        "ia_view",   row=1))
        # Row 2 — Delete + Done
        self.add_item(_btn("Delete Item",  self._delete_item, "ia_del",    row=2))
        self.add_item(_btn(t(gid, "done_btn"), self._done, "ia_done", discord.ButtonStyle.danger, row=2))

    async def _cats(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=_cats_embed(self.gid),
            view=CategoriesView(self.gid, self),
        )

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(CreateItemModal(self.gid, None, self))

    async def _edit(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Edit Item", description="Select an item to edit:", color=EMBED_COLOR),
            view=EditItemView(self.gid, self),
        )

    async def _give(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Give Items", color=EMBED_COLOR),
            view=GiveRemoveView(self.gid, "give", self),
        )

    async def _remove(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Remove Items", color=EMBED_COLOR),
            view=GiveRemoveView(self.gid, "remove", self),
        )

    async def _view(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="View Item", description="Select an item to view:", color=EMBED_COLOR),
            view=ViewItemView(self.gid, self),
        )

    async def _delete_item(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(title="Delete Item", description="Select an item to delete:", color=EMBED_COLOR),
            view=DeleteItemView(self.gid, self),
        )

    async def _done(self, ix: discord.Interaction):
        self.clear_items()
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=self)


# ── Categories ────────────────────────────────────────────────────────────────

class AddCatModal(Modal, title="Add Category"):
    name  = TextInput(label="Name",             max_length=60)
    emoji = TextInput(label="Emoji (optional)", max_length=100, required=False)

    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        db  = load_items(self.gid)
        cid = slugify(self.name.value.strip())
        if cid and cid not in db["categories"]:
            db["categories"][cid] = {
                "name":  self.name.value.strip(),
                "emoji": (self.emoji.value or "📦").strip() or "📦",
            }
            db["category_order"].append(cid)
            save_items(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(embed=_cats_embed(self.gid), view=self.parent)


class CategoriesView(View):
    def __init__(self, gid: int, parent, sel: str = None):
        super().__init__(timeout=300)
        self.gid = gid
        self.parent = parent
        self.sel = sel
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_items(self.gid)
        cats  = db.get("categories", {})
        order = db.get("category_order", [])
        opts  = (
            [
                discord.SelectOption(
                    label=f"{cats[c].get('emoji','📦')} {cats[c].get('name', c)}",
                    value=c,
                    default=(c == self.sel),
                )
                for c in order
                if c in cats
            ]
            or [discord.SelectOption(label="—", value="__none__")]
        )

        sel = Select(placeholder="Select category", options=opts, custom_id="cat_sel", row=0)
        sel.callback = self._sel
        self.add_item(sel)

        add  = Button(label="Add",    style=discord.ButtonStyle.green,     custom_id="cat_add",  row=1)
        dlt  = Button(label="Delete", style=discord.ButtonStyle.danger,    custom_id="cat_del",  row=1)
        up   = Button(label="▲ Up",   style=discord.ButtonStyle.secondary, custom_id="cat_up",   row=1)
        dn   = Button(label="▼ Down", style=discord.ButtonStyle.secondary, custom_id="cat_dn",   row=1)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="cat_back", row=2)
        add.callback  = self._add
        dlt.callback  = self._del
        up.callback   = self._up
        dn.callback   = self._dn
        back.callback = self._back
        self.add_item(add)
        self.add_item(dlt)
        self.add_item(up)
        self.add_item(dn)
        self.add_item(back)

    async def _sel(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        self.sel = v if v != "__none__" else None
        self._build()
        await ix.response.edit_message(embed=_cats_embed(self.gid), view=self)

    async def _add(self, ix: discord.Interaction):
        await ix.response.send_modal(AddCatModal(self.gid, self))

    async def _del(self, ix: discord.Interaction):
        if not self.sel:
            await ix.response.send_message("Select a category first.", ephemeral=True)
            return
        db = load_items(self.gid)
        db["categories"].pop(self.sel, None)
        order = db["category_order"]
        if self.sel in order:
            order.remove(self.sel)
        self.sel = None
        save_items(self.gid, db)
        self._build()
        await ix.response.edit_message(embed=_cats_embed(self.gid), view=self)

    async def _up(self, ix: discord.Interaction):
        if not self.sel:
            await ix.response.send_message("Select a category first.", ephemeral=True)
            return
        db = load_items(self.gid)
        o  = db["category_order"]
        i  = o.index(self.sel) if self.sel in o else -1
        if i > 0:
            o[i], o[i - 1] = o[i - 1], o[i]
            save_items(self.gid, db)
        self._build()
        await ix.response.edit_message(embed=_cats_embed(self.gid), view=self)

    async def _dn(self, ix: discord.Interaction):
        if not self.sel:
            await ix.response.send_message("Select a category first.", ephemeral=True)
            return
        db = load_items(self.gid)
        o  = db["category_order"]
        i  = o.index(self.sel) if self.sel in o else -1
        if 0 <= i < len(o) - 1:
            o[i], o[i + 1] = o[i + 1], o[i]
            save_items(self.gid, db)
        self._build()
        await ix.response.edit_message(embed=_cats_embed(self.gid), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)


# ── Create / Edit Item ────────────────────────────────────────────────────────

class CreateItemModal(Modal, title="Create / Edit Item"):
    f_name     = TextInput(label="Item Name",                    max_length=60)
    f_cat      = TextInput(label="Category name or ID",          max_length=60,  required=False)
    f_desc     = TextInput(label="Description",                  style=discord.TextStyle.paragraph, max_length=400, required=False)
    f_emoji    = TextInput(label="Emoji (optional)",             max_length=100, required=False)
    f_when_use = TextInput(label="When Used (empty = material)", style=discord.TextStyle.paragraph, max_length=300, required=False)

    def __init__(self, gid: int, item_id, parent, prefill: dict = None):
        super().__init__()
        self.gid     = gid
        self.item_id = item_id
        self.parent  = parent
        if prefill:
            self.f_name.default     = prefill.get("name", "")
            self.f_cat.default      = prefill.get("category", "")
            self.f_desc.default     = prefill.get("description", "")
            self.f_emoji.default    = prefill.get("emoji", "")
            self.f_when_use.default = prefill.get("when_use", "")

    async def on_submit(self, ix: discord.Interaction):
        name   = (self.f_name.value or "").strip()
        cat_in = (self.f_cat.value or "").strip()
        db     = load_items(self.gid)
        cats   = db.get("categories", {})
        cat_id = (
            cat_in
            if cat_in in cats
            else next(
                (k for k, v in cats.items() if v.get("name", "").lower() == cat_in.lower()),
                slugify(cat_in),
            )
        )
        iid = self.item_id or slugify(name)
        if not iid:
            await ix.response.send_message("Invalid name.", ephemeral=True)
            return
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
        await ix.response.edit_message(
            embed=_item_step2_embed(self.gid, iid, data),
            view=ItemStep2View(self.gid, iid, data, self.parent),
        )


def _item_step2_embed(gid: int, iid: str, data: dict) -> discord.Embed:
    name     = data.get("name", "")
    emoji    = data.get("emoji", "📦")
    when_use = data.get("when_use", "")
    img      = data.get("image_url", "")
    price    = data.get("sell_price", 0)
    tag = t(gid, "usable_tag") if when_use else t(gid, "material_tag")
    embed = discord.Embed(
        title=f"{emoji} {name}",
        description=data.get("description") or "*No description*",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Type",       value=f"`{tag}`",           inline=True)
    embed.add_field(name="Sell Price", value=str(price),           inline=True)
    embed.add_field(
        name="When Used",
        value=when_use if when_use else "*Material (cannot be used)*",
        inline=False,
    )
    if img and is_url(img):
        embed.set_image(url=img)
    return embed


class ItemStep2View(View):
    def __init__(self, gid: int, iid: str, data: dict, parent):
        super().__init__(timeout=300)
        self.gid    = gid
        self.iid    = iid
        self.data   = data
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        img_btn   = Button(label=t(self.gid, "add_image_btn"), style=discord.ButtonStyle.secondary, custom_id="s2_img",   row=0)
        price_btn = Button(label="💰 Set Sell Price",           style=discord.ButtonStyle.secondary, custom_id="s2_price", row=0)
        save_btn  = Button(label="💾 Save",                     style=discord.ButtonStyle.green,     custom_id="s2_save",  row=1)
        bk_btn    = Button(label=t(self.gid, "back_btn"),       style=discord.ButtonStyle.secondary, custom_id="s2_bk",    row=1)
        img_btn.callback   = self._set_image
        price_btn.callback = self._set_price
        save_btn.callback  = self._save
        bk_btn.callback    = self._back
        self.add_item(img_btn)
        self.add_item(price_btn)
        self.add_item(save_btn)
        self.add_item(bk_btn)

    async def _set_image(self, ix: discord.Interaction):
        await ix.response.send_modal(_ItemImageModal(self))

    async def _set_price(self, ix: discord.Interaction):
        await ix.response.send_modal(_ItemSellPriceModal(self))

    async def _save(self, ix: discord.Interaction):
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
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)


class _ItemImageModal(Modal, title="Set Item Image URL"):
    url = TextInput(label="Image URL (leave blank to clear)", max_length=500, required=False)

    def __init__(self, parent: ItemStep2View):
        super().__init__()
        self.parent = parent
        self.url.default = parent.data.get("image_url", "")

    async def on_submit(self, ix: discord.Interaction):
        self.parent.data["image_url"] = (self.url.value or "").strip()
        self.parent._build()
        await ix.response.edit_message(
            embed=_item_step2_embed(self.parent.gid, self.parent.iid, self.parent.data),
            view=self.parent,
        )


class _ItemSellPriceModal(Modal, title="Set Sell Price"):
    price = TextInput(label="Sell Price (0 = not sellable)", max_length=10)

    def __init__(self, parent: ItemStep2View):
        super().__init__()
        self.parent = parent
        self.price.default = str(parent.data.get("sell_price", 0))

    async def on_submit(self, ix: discord.Interaction):
        try:
            self.parent.data["sell_price"] = max(0, int((self.price.value or "0").strip()))
        except ValueError:
            pass
        self.parent._build()
        await ix.response.edit_message(
            embed=_item_step2_embed(self.parent.gid, self.parent.iid, self.parent.data),
            view=self.parent,
        )


# ── Edit Item ─────────────────────────────────────────────────────────────────

class EditItemView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid    = gid
        self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_items(self.gid)
        items = db.get("items", {})
        opts  = (
            [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}"[:100],
                    value=iid,
                )
                for iid, d in list(items.items())[:25]
            ]
            or [discord.SelectOption(label="No items", value="__none__")]
        )
        sel  = Select(placeholder="Select item to edit", options=opts, custom_id="ei_sel", row=0)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="ei_back", row=1)
        sel.callback  = self._cb
        back.callback = self._back
        self.add_item(sel)
        self.add_item(back)

    async def _cb(self, ix: discord.Interaction):
        iid = ix.data["values"][0]
        if iid == "__none__":
            await ix.response.send_message("No items.", ephemeral=True)
            return
        it = load_items(self.gid).get("items", {}).get(iid, {})
        await ix.response.send_modal(CreateItemModal(self.gid, iid, self.parent, prefill=it))

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)


# ── View Item ─────────────────────────────────────────────────────────────────

class ViewItemView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid    = gid
        self.parent = parent
        self._state = "select"
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_items(self.gid)
        items = db.get("items", {})
        opts  = (
            [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}"[:100],
                    value=iid,
                )
                for iid, d in list(items.items())[:25]
            ]
            or [discord.SelectOption(label="No items", value="__none__")]
        )
        sel  = Select(placeholder="Select item to view", options=opts, custom_id="vi_sel", row=0)
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="vi_back", row=1)
        sel.callback  = self._cb
        back.callback = self._back
        self.add_item(sel)
        self.add_item(back)

    async def _cb(self, ix: discord.Interaction):
        iid = ix.data["values"][0]
        if iid == "__none__":
            await ix.response.send_message("No items.", ephemeral=True)
            return
        self.clear_items()
        back = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="vi_back2", row=0)
        back.callback = self._back2
        self.add_item(back)
        await ix.response.edit_message(embed=_item_embed(self.gid, iid), view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)

    async def _back2(self, ix: discord.Interaction):
        self._build()
        await ix.response.edit_message(
            embed=discord.Embed(title="View Item", description="Select an item to view:", color=EMBED_COLOR),
            view=self,
        )


# ── Delete Item ───────────────────────────────────────────────────────────────

class DeleteItemView(View):
    def __init__(self, gid: int, parent):
        super().__init__(timeout=300)
        self.gid     = gid
        self.parent  = parent
        self.sel_iid = None
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_items(self.gid)
        items = db.get("items", {})
        opts  = (
            [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}"[:100],
                    value=iid,
                    default=(iid == self.sel_iid),
                )
                for iid, d in list(items.items())[:25]
            ]
            or [discord.SelectOption(label="No items", value="__none__")]
        )
        sel     = Select(placeholder="Select item to delete", options=opts, custom_id="dv_sel", row=0)
        confirm = Button(label="🗑️ Confirm Delete", style=discord.ButtonStyle.danger,    custom_id="dv_conf", row=1)
        back    = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="dv_back", row=1)
        sel.callback     = self._sel_cb
        confirm.callback = self._confirm
        back.callback    = self._back
        self.add_item(sel)
        self.add_item(confirm)
        self.add_item(back)

    async def _sel_cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        self.sel_iid = v if v != "__none__" else None
        self._build()
        await ix.response.edit_message(view=self)

    async def _confirm(self, ix: discord.Interaction):
        if not self.sel_iid:
            await ix.response.send_message("Select an item first.", ephemeral=True)
            return
        db = load_items(self.gid)
        db.get("items", {}).pop(self.sel_iid, None)
        save_items(self.gid, db)
        self.sel_iid = None
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)


# ── Give / Remove ─────────────────────────────────────────────────────────────

class _SetQtyModal(Modal, title="Set Quantity"):
    qty = TextInput(label="Quantity", max_length=10, default="1")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        try:
            self.parent.qty = max(1, int(self.qty.value.strip()))
        except Exception:
            pass
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class GiveRemoveView(View):
    def __init__(self, gid: int, mode: str, parent):
        super().__init__(timeout=300)
        self.gid      = gid
        self.mode     = mode
        self.parent   = parent
        self.sel_item = None
        self.sel_users: list = []
        self.sel_role = None
        self.qty      = 1
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_items(self.gid)
        items = db.get("items", {})
        opts = (
            [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}"[:100],
                    value=iid,
                    default=(iid == self.sel_item),
                )
                for iid, d in list(items.items())[:25]
            ]
            or [discord.SelectOption(label="No items", value="__none__")]
        )

        sel = Select(placeholder="Select item", options=opts, custom_id="gr_sel", row=0)
        us  = discord.ui.UserSelect(placeholder="Select users", min_values=1, max_values=25, custom_id="gr_us", row=1)
        rs  = discord.ui.RoleSelect(placeholder="Via role", custom_id="gr_rs", row=2)

        la = "Give to Users"       if self.mode == "give" else "Remove from Users"
        lb = "Give via Role"       if self.mode == "give" else "Remove via Role"
        au = Button(label=la,                   style=discord.ButtonStyle.green,     custom_id="gr_au",  row=3)
        ar = Button(label=lb,                   style=discord.ButtonStyle.green,     custom_id="gr_ar",  row=3)
        sq = Button(label=f"Qty: {self.qty}",   style=discord.ButtonStyle.secondary, custom_id="gr_sq",  row=3)
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk", row=4)

        sel.callback = self._item_cb
        us.callback  = self._user_cb
        rs.callback  = self._role_cb
        au.callback  = self._act_users
        ar.callback  = self._act_role
        sq.callback  = self._set_qty
        bk.callback  = self._back

        self.add_item(sel)
        self.add_item(us)
        self.add_item(rs)
        self.add_item(au)
        self.add_item(ar)
        self.add_item(sq)
        self.add_item(bk)

    async def _item_cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        self.sel_item = v if v != "__none__" else None
        self._build()
        await ix.response.edit_message(view=self)

    async def _user_cb(self, ix: discord.Interaction):
        self.sel_users = ix.data["values"]
        await ix.response.defer()

    async def _role_cb(self, ix: discord.Interaction):
        self.sel_role = ix.data["values"][0] if ix.data["values"] else None
        await ix.response.defer()

    async def _set_qty(self, ix: discord.Interaction):
        await ix.response.send_modal(_SetQtyModal(self))

    def _apply(self, players: dict, uid: str, qty: int):
        p   = players.setdefault(uid, {"inventory": {}})
        inv = p.setdefault("inventory", {})
        if self.mode == "give":
            inv[self.sel_item] = inv.get(self.sel_item, 0) + qty
        else:
            inv[self.sel_item] = max(0, inv.get(self.sel_item, 0) - qty)

    async def _act_users(self, ix: discord.Interaction):
        if not self.sel_item or not self.sel_users:
            await ix.response.send_message("Select item and users.", ephemeral=True)
            return
        ps = load_players(self.gid)
        for uid in self.sel_users:
            self._apply(ps, uid, self.qty)
        save_players(self.gid, ps)
        word = "given to" if self.mode == "give" else "removed from"
        self.clear_items()
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk2", row=0)
        bk.callback = self._back
        self.add_item(bk)
        embed = discord.Embed(
            description=f"Item {word} {len(self.sel_users)} user(s).",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=self)

    async def _act_role(self, ix: discord.Interaction):
        if not self.sel_item or not self.sel_role:
            await ix.response.send_message("Select item and role.", ephemeral=True)
            return
        role = ix.guild.get_role(int(self.sel_role))
        if not role:
            await ix.response.send_message("Role not found.", ephemeral=True)
            return
        ps = load_players(self.gid)
        for m in role.members:
            self._apply(ps, str(m.id), self.qty)
        save_players(self.gid, ps)
        word = "given to" if self.mode == "give" else "removed from"
        self.clear_items()
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="gr_bk3", row=0)
        bk.callback = self._back
        self.add_item(bk)
        embed = discord.Embed(
            description=f"Item {word} {len(role.members)} member(s).",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=self)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        await ix.response.edit_message(embed=_panel_embed(self.gid), view=self.parent)


# ── Player InventoryView ──────────────────────────────────────────────────────

class InventoryView(View):
    """Used by other cogs (e.g. profile) to display a player's inventory."""

    def __init__(self, uid: int, gid: int, back_view=None):
        super().__init__(timeout=300)
        self.uid       = uid
        self.gid       = gid
        self.back_view = back_view
        self.sel_cat   = None
        self.sel_item_id = None
        self._build_categories()

    # ── Category selection ────────────────────────────────────────────────────

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
                cat_id = all_items[iid].get("category", "") or "__uncategorized__"
                player_cats.add(cat_id)

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk", row=1)
        bk.callback = self._back

        if not player_cats:
            self.add_item(bk)
            return

        opts = []
        for cat_id in cat_order:
            if cat_id in player_cats and cat_id in categories:
                cat = categories[cat_id]
                opts.append(discord.SelectOption(
                    label=f"{cat.get('emoji','📦')} {cat.get('name', cat_id)}",
                    value=cat_id,
                    default=(cat_id == self.sel_cat),
                ))
        if "__uncategorized__" in player_cats:
            opts.append(discord.SelectOption(
                label="📦 Other",
                value="__uncategorized__",
                default=("__uncategorized__" == self.sel_cat),
            ))
        if not opts:
            opts = [discord.SelectOption(label="—", value="__none__")]

        sel = Select(placeholder="Select category", options=opts[:25], custom_id="inv_cat", row=0)
        sel.callback = self._cat_cb
        self.add_item(sel)
        self.add_item(bk)

    def _inv_embed(self) -> discord.Embed:
        player    = load_players(self.gid).get(str(self.uid), {})
        inventory = player.get("inventory", {})
        embed = discord.Embed(
            title=f"🎒 {t(self.gid, 'inventory_btn')}",
            color=EMBED_COLOR,
        )
        if not any(q > 0 for q in inventory.values()):
            embed.description = t(self.gid, "inventory_empty")
        return embed

    async def _cat_cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        if v == "__none__":
            await ix.response.defer()
            return
        self.sel_cat = v
        self._build_items()
        await ix.response.edit_message(embed=self._items_embed(), view=self)

    # ── Item selection ────────────────────────────────────────────────────────

    def _build_items(self):
        self.clear_items()
        player    = load_players(self.gid).get(str(self.uid), {})
        items_db  = load_items(self.gid)
        inventory = player.get("inventory", {})
        all_items = items_db.get("items", {})

        opts = []
        for iid, qty in inventory.items():
            if qty <= 0 or iid not in all_items:
                continue
            item     = all_items[iid]
            item_cat = item.get("category", "") or "__uncategorized__"
            if self.sel_cat == "__uncategorized__":
                if item.get("category", ""):
                    continue
            elif item_cat != self.sel_cat:
                continue
            opts.append(discord.SelectOption(
                label=f"{item.get('emoji','📦')} {item.get('name', iid)} ×{qty}"[:100],
                value=iid,
                default=(iid == self.sel_item_id),
            ))
        if not opts:
            opts = [discord.SelectOption(label="—", value="__none__")]

        sel = Select(placeholder="Select item", options=opts[:25], custom_id="inv_isel", row=0)
        sel.callback = self._item_cb
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk2", row=1)
        bk.callback = self._back_to_cats
        self.add_item(sel)
        self.add_item(bk)

    def _items_embed(self) -> discord.Embed:
        items_db  = load_items(self.gid)
        categories = items_db.get("categories", {})
        if self.sel_cat == "__uncategorized__":
            cat_name = "Other"
        else:
            cat_name = categories.get(self.sel_cat, {}).get("name", self.sel_cat or "Items")
        return discord.Embed(title=f"🎒 {cat_name}", description="Select an item:", color=EMBED_COLOR)

    async def _item_cb(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        if v == "__none__":
            await ix.response.defer()
            return
        self.sel_item_id = v
        self._build_item_detail()
        await ix.response.edit_message(embed=self._detail_embed(), view=self)

    # ── Item detail ───────────────────────────────────────────────────────────

    def _build_item_detail(self):
        self.clear_items()
        items_db = load_items(self.gid)
        item     = items_db.get("items", {}).get(self.sel_item_id, {})
        when_use    = item.get("when_use", "")
        is_material = not bool(when_use)
        sell_price  = item.get("sell_price", 0)

        use_btn  = Button(label="✅ Use",                  style=discord.ButtonStyle.green,     custom_id="inv_use",  disabled=is_material, row=0)
        give_btn = Button(label="🎁 Give",                 style=discord.ButtonStyle.primary,   custom_id="inv_give", row=0)
        sell_btn = Button(label=f"💰 Sell ({sell_price})", style=discord.ButtonStyle.secondary, custom_id="inv_sell", row=0)
        bk_btn   = Button(label=t(self.gid, "back_btn"),  style=discord.ButtonStyle.secondary, custom_id="inv_bk3",  row=1)
        use_btn.callback  = self._use
        give_btn.callback = self._give
        sell_btn.callback = self._sell
        bk_btn.callback   = self._back_to_items
        self.add_item(use_btn)
        self.add_item(give_btn)
        self.add_item(sell_btn)
        self.add_item(bk_btn)

    def _detail_embed(self) -> discord.Embed:
        player   = load_players(self.gid).get(str(self.uid), {})
        items_db = load_items(self.gid)
        item     = items_db.get("items", {}).get(self.sel_item_id, {})
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
        embed = discord.Embed(
            title=f"{emoji} {name} ×{qty}",
            description=f"*{desc}*" if desc else None,
            color=EMBED_COLOR,
        )
        embed.add_field(name="Type", value=tag, inline=True)
        if sell_price:
            embed.add_field(name=t(self.gid, "balance_label"), value=f"{sell_price} per item", inline=True)
        if img_url and is_url(img_url):
            embed.set_image(url=img_url)
        return embed

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _use(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return
        items_db = load_items(self.gid)
        item     = items_db.get("items", {}).get(self.sel_item_id, {})
        when_use = item.get("when_use", "")
        if not when_use:
            await ix.response.send_message("This item cannot be used (material item).", ephemeral=True)
            return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        inv     = player.setdefault("inventory", {})
        qty     = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True)
            return
        inv[self.sel_item_id]  = qty - 1
        players[str(self.uid)] = player
        save_players(self.gid, players)
        item_name  = item.get("name", self.sel_item_id)
        item_emoji = item.get("emoji", "📦")
        self._build_categories()
        await ix.response.edit_message(embed=self._inv_embed(), view=self)
        try:
            await ix.channel.send(
                f"{item_emoji} **{ix.user.display_name}** used **{item_name}**\n\n{when_use}"
            )
        except Exception:
            pass

    async def _give(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return
        self.clear_items()
        us = discord.ui.UserSelect(placeholder="Select recipient", min_values=1, max_values=1, custom_id="inv_give_us", row=0)
        us.callback = self._do_give
        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="inv_bk_give", row=1)
        bk.callback = self._back_to_items
        self.add_item(us)
        self.add_item(bk)
        embed = discord.Embed(title="🎁 Give Item", description="Select a recipient:", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=self)

    async def _do_give(self, ix: discord.Interaction):
        if not ix.data.get("values"):
            await ix.response.defer()
            return
        recipient_id = ix.data["values"][0]
        players  = load_players(self.gid)
        giver    = players.get(str(self.uid), {})
        inv      = giver.setdefault("inventory", {})
        qty      = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True)
            return
        inv[self.sel_item_id] = qty - 1
        recipient = players.setdefault(recipient_id, {"inventory": {}})
        rec_inv   = recipient.setdefault("inventory", {})
        rec_inv[self.sel_item_id] = rec_inv.get(self.sel_item_id, 0) + 1
        players[str(self.uid)] = giver
        players[recipient_id]  = recipient
        save_players(self.gid, players)
        item_name = load_items(self.gid).get("items", {}).get(self.sel_item_id, {}).get("name", self.sel_item_id)
        try:
            rec_user = await bot.fetch_user(int(recipient_id))
            await _dm(rec_user, t(self.gid, "item_given_msg", sender=ix.user.display_name, item=item_name))
        except Exception:
            pass
        self._build_categories()
        await ix.response.edit_message(embed=self._inv_embed(), view=self)

    async def _sell(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        inv     = player.setdefault("inventory", {})
        qty     = inv.get(self.sel_item_id, 0)
        if qty <= 0:
            await ix.response.send_message("You don't have this item.", ephemeral=True)
            return
        item       = load_items(self.gid).get("items", {}).get(self.sel_item_id, {})
        sell_price = item.get("sell_price", 0)
        item_name  = item.get("name", self.sel_item_id)
        inv[self.sel_item_id]  = qty - 1
        player["balance"]      = player.get("balance", 0) + sell_price
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await _dm(
            ix.user,
            t(self.gid, "item_sold_msg", item=item_name, price=sell_price, balance=player["balance"]),
        )
        self._build_categories()
        await ix.response.edit_message(embed=self._inv_embed(), view=self)

    # ── Navigation ────────────────────────────────────────────────────────────

    async def _back(self, ix: discord.Interaction):
        if self.back_view:
            self.back_view._build()
            await ix.response.edit_message(view=self.back_view)
        else:
            self._build_categories()
            await ix.response.edit_message(embed=self._inv_embed(), view=self)

    async def _back_to_cats(self, ix: discord.Interaction):
        self.sel_item_id = None
        self._build_categories()
        await ix.response.edit_message(embed=self._inv_embed(), view=self)

    async def _back_to_items(self, ix: discord.Interaction):
        self._build_items()
        await ix.response.edit_message(embed=self._items_embed(), view=self)


# ── Player Items Browser (/items) ─────────────────────────────────────────────

class PlayerItemsView(View):
    """Public browser — shows items organised by category with pagination."""

    ITEMS_PER_PAGE = 8

    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid     = gid
        self.sel_cat = None
        self.page    = 0
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
                    value=cid,
                    default=(cid == self.sel_cat),
                ))
        if "__uncategorized__" in populated:
            opts.append(discord.SelectOption(
                label="📦 Other",
                value="__uncategorized__",
                default=("__uncategorized__" == self.sel_cat),
            ))

        if not opts:
            return

        sel = Select(placeholder="Select category", options=opts[:25], custom_id="pi_cat", row=0)
        sel.callback = self._cat_cb
        self.add_item(sel)

    def _cats_embed(self) -> discord.Embed:
        return discord.Embed(
            title=t(self.gid, "items_title"),
            description="Select a category to browse items:",
            color=EMBED_COLOR,
        )

    async def _cat_cb(self, ix: discord.Interaction):
        self.sel_cat = ix.data["values"][0]
        self.page    = 0
        self._build_items()
        await ix.response.edit_message(embed=self._items_embed(), view=self)

    def _get_cat_items(self) -> list:
        db        = load_items(self.gid)
        all_items = db.get("items", {})
        result = []
        for iid, item in all_items.items():
            item_cat = item.get("category", "") or "__uncategorized__"
            if item_cat == self.sel_cat:
                result.append((iid, item))
        return result

    def _items_embed(self) -> discord.Embed:
        db   = load_items(self.gid)
        cats = db.get("categories", {})
        if self.sel_cat == "__uncategorized__":
            cat_name  = "📦 Other"
            cat_emoji = ""
        else:
            cat_data  = cats.get(self.sel_cat, {})
            cat_name  = cat_data.get("name", self.sel_cat or "")
            cat_emoji = cat_data.get("emoji", "📦")

        cat_items = self._get_cat_items()
        total     = len(cat_items)
        per_page  = self.ITEMS_PER_PAGE
        total_pages = max(1, (total + per_page - 1) // per_page)
        page_items  = cat_items[self.page * per_page: (self.page + 1) * per_page]

        embed = discord.Embed(
            title=f"{cat_emoji} {cat_name}",
            color=EMBED_COLOR,
        )
        if not page_items:
            embed.description = "*No items in this category.*"
        else:
            lines = []
            for iid, item in page_items:
                emoji    = item.get("emoji", "📦")
                name     = item.get("name", iid)
                desc     = item.get("description", "")
                when_use = item.get("when_use", "")
                tag      = t(self.gid, "usable_tag") if when_use else t(self.gid, "material_tag")
                line = f"{emoji} **{name}** — {desc}" if desc else f"{emoji} **{name}**"
                line += f"  `[{tag}]`"
                lines.append(line)
            embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}")
        return embed

    def _build_items(self):
        self.clear_items()
        cat_items   = self._get_cat_items()
        total       = len(cat_items)
        per_page    = self.ITEMS_PER_PAGE
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Category select on row 0
        self._build_cats()

        if total_pages > 1:
            prev = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary, custom_id="pi_prev", row=1, disabled=(self.page == 0))
            nxt  = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary, custom_id="pi_next", row=1, disabled=(self.page >= total_pages - 1))
            prev.callback = self._prev
            nxt.callback  = self._next
            self.add_item(prev)
            self.add_item(nxt)

        bk = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="pi_bk", row=2)
        bk.callback = self._back
        self.add_item(bk)

    async def _prev(self, ix: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._build_items()
        await ix.response.edit_message(embed=self._items_embed(), view=self)

    async def _next(self, ix: discord.Interaction):
        total_pages = max(1, (len(self._get_cat_items()) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        self.page   = min(total_pages - 1, self.page + 1)
        self._build_items()
        await ix.response.edit_message(embed=self._items_embed(), view=self)

    async def _back(self, ix: discord.Interaction):
        self.sel_cat = None
        self.page    = 0
        self._build_cats()
        await ix.response.edit_message(embed=self._cats_embed(), view=self)


# ── Slash commands ────────────────────────────────────────────────────────────

@bot.tree.command(
    name="items",
    description="Browse all server items",
    description_localizations={"th": "ดูรายการไอเทมทั้งหมด"},
)
async def items_cmd(ix: discord.Interaction):
    gid  = ix.guild_id
    view = PlayerItemsView(gid)
    embed = discord.Embed(
        title=t(gid, "items_title"),
        description="Select a category to browse items:",
        color=EMBED_COLOR,
    )
    db = load_items(gid)
    if not db.get("items"):
        embed.description = "*No items available.*"
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(
    name="item-admin",
    description="Item admin panel",
    description_localizations={"th": "แผงจัดการไอเทมสำหรับแอดมิน"},
)
@is_admin()
async def item_admin_cmd(ix: discord.Interaction):
    gid  = ix.guild_id
    view = ItemAdminMainView(gid)
    await ix.response.send_message(embed=_panel_embed(gid), view=view, ephemeral=True)


@item_admin_cmd.error
async def item_admin_error(ix: discord.Interaction, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
