"""Item admin panel — categories, items, give/remove."""
import discord
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

from aot_bot_instance import bot
from aot_shared import (
    t, load_players, save_players, load_items, save_items,
    ui_box, select_options_from_list, slugify, is_url,
)


def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


def _panel_text(gid):
    db = load_items(gid)
    return ui_box(t(gid,"item_admin_title"),[
        f"**Categories:** {len(db.get('categories',{}))}",
        f"**Items:** {len(db.get('items',{}))}",
    ])

def _cats_text(gid):
    db=load_items(gid); cats=db.get("categories",{}); order=db.get("category_order",[])
    lines=[f"`{c}` {cats[c].get('emoji','📦')} **{cats[c].get('name',c)}** (pos {i+1})"
           for i,c in enumerate(order) if c in cats]
    return ui_box("Categories", lines or ["*No categories*"])


class ItemAdminMainView(View):
    def __init__(self,gid): super().__init__(timeout=300); self.gid=gid; self._build()
    def _build(self):
        self.clear_items()
        for lbl,cb,row in [("Categories",self._cats,0),("Create Item",self._create,0),("Edit Item",self._edit,0),
                            ("Give Items",self._give,1),("Remove Items",self._remove,1),("View Item",self._view,1)]:
            b=Button(label=lbl,style=discord.ButtonStyle.secondary,row=row); b.callback=cb; self.add_item(b)
        d=Button(label=t(self.gid,"done_btn"),style=discord.ButtonStyle.danger,row=2); d.callback=self._done; self.add_item(d)
    async def _cats(self,ix):   await ix.response.edit_message(content=_cats_text(self.gid),view=CategoriesView(self.gid,self))
    async def _create(self,ix): await ix.response.send_modal(CreateItemModal(self.gid,None,self))
    async def _edit(self,ix):   await ix.response.edit_message(content="Select item to edit:",view=EditItemView(self.gid,self))
    async def _give(self,ix):   await ix.response.edit_message(content="## Give Items",view=GiveRemoveView(self.gid,"give",self))
    async def _remove(self,ix): await ix.response.edit_message(content="## Remove Items",view=GiveRemoveView(self.gid,"remove",self))
    async def _view(self,ix):   await ix.response.edit_message(content="Select item to view:",view=ViewItemView(self.gid,self))
    async def _done(self,ix):   await ix.response.edit_message(content=t(self.gid,"panel_closed"),view=None)


# ── Categories ────────────────────────────────────────────────────────────────

class AddCatModal(Modal, title="Add Category"):
    name  = TextInput(label="Name",  max_length=60)
    emoji = TextInput(label="Emoji (optional)", max_length=20, required=False)
    def __init__(self,gid,parent): super().__init__(); self.gid=gid; self.parent=parent
    async def on_submit(self,ix):
        db=load_items(self.gid); cid=slugify(self.name.value.strip())
        if cid and cid not in db["categories"]:
            db["categories"][cid]={"name":self.name.value.strip(),"emoji":(self.emoji.value or "📦").strip()}
            db["category_order"].append(cid); save_items(self.gid,db)
        await ix.response.edit_message(content=_cats_text(self.gid),view=self.parent)

class CategoriesView(View):
    def __init__(self,gid,parent,sel=None):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self.sel=sel; self._build()
    def _build(self):
        self.clear_items()
        db=load_items(self.gid); cats=db.get("categories",{}); order=db.get("category_order",[])
        opts=[discord.SelectOption(label=f"{cats[c].get('emoji','📦')} {cats[c].get('name',c)}",value=c,default=(c==self.sel)) for c in order if c in cats] or [discord.SelectOption(label="—",value="__none__")]
        s=Select(placeholder="Select category",options=opts,row=0); s.callback=self._sel; self.add_item(s)
        for lbl,cb,style,row in [("Add",self._add,discord.ButtonStyle.green,1),("Delete",self._del,discord.ButtonStyle.danger,1),
                                  ("▲ Up",self._up,discord.ButtonStyle.secondary,2),("▼ Down",self._dn,discord.ButtonStyle.secondary,2),
                                  (t(self.gid,"back_btn"),self._back,discord.ButtonStyle.secondary,3)]:
            b=Button(label=lbl,style=style,row=row); b.callback=cb; self.add_item(b)
    async def _sel(self,ix): v=ix.data["values"][0]; self.sel=v if v!="__none__" else None; self._build(); await ix.response.edit_message(view=self)
    async def _add(self,ix): await ix.response.send_modal(AddCatModal(self.gid,self))
    async def _del(self,ix):
        if not self.sel: await ix.response.send_message("Select a category first.",ephemeral=True); return
        db=load_items(self.gid); db["categories"].pop(self.sel,None)
        order=db["category_order"];order.remove(self.sel) if self.sel in order else None
        self.sel=None; save_items(self.gid,db); self._build(); await ix.response.edit_message(content=_cats_text(self.gid),view=self)
    async def _up(self,ix):
        if not self.sel: await ix.response.send_message("Select first.",ephemeral=True); return
        db=load_items(self.gid); o=db["category_order"]
        i=o.index(self.sel) if self.sel in o else -1
        if i>0: o[i],o[i-1]=o[i-1],o[i]; save_items(self.gid,db)
        self._build(); await ix.response.edit_message(content=_cats_text(self.gid),view=self)
    async def _dn(self,ix):
        if not self.sel: await ix.response.send_message("Select first.",ephemeral=True); return
        db=load_items(self.gid); o=db["category_order"]
        i=o.index(self.sel) if self.sel in o else -1
        if 0<=i<len(o)-1: o[i],o[i+1]=o[i+1],o[i]; save_items(self.gid,db)
        self._build(); await ix.response.edit_message(content=_cats_text(self.gid),view=self)
    async def _back(self,ix): await ix.response.edit_message(content=_panel_text(self.gid),view=self.parent)


# ── Create / Edit Item ────────────────────────────────────────────────────────

class CreateItemModal(Modal, title="Create Item"):
    f_name  = TextInput(label="Item Name",         max_length=60)
    f_cat   = TextInput(label="Category name or ID",max_length=60, required=False)
    f_desc  = TextInput(label="Description",        style=discord.TextStyle.paragraph, max_length=400, required=False)
    f_emoji = TextInput(label="Emoji (optional)",   max_length=20, required=False)
    f_img   = TextInput(label="Image URL (optional)",max_length=400, required=False)

    def __init__(self,gid,item_id,parent,prefill=None):
        super().__init__(); self.gid=gid; self.item_id=item_id; self.parent=parent
        if prefill:
            self.f_name.default=prefill.get("name",""); self.f_cat.default=prefill.get("category","")
            self.f_desc.default=prefill.get("description",""); self.f_emoji.default=prefill.get("emoji","")
            self.f_img.default=prefill.get("image_url","")

    async def on_submit(self,ix):
        name=(self.f_name.value or "").strip(); cat_in=(self.f_cat.value or "").strip()
        db=load_items(self.gid); cats=db.get("categories",{})
        cat_id=cat_in if cat_in in cats else next((k for k,v in cats.items() if v.get("name","").lower()==cat_in.lower()),slugify(cat_in))
        iid=self.item_id or slugify(name)
        if not iid: await ix.response.send_message("Invalid name.",ephemeral=True); return
        db.setdefault("items",{})[iid]={"name":name,"category":cat_id,
            "description":(self.f_desc.value or "").strip(),
            "emoji":(self.f_emoji.value or "📦").strip() or "📦",
            "image_url":(self.f_img.value or "").strip(),
            "sell_price":db.get("items",{}).get(iid,{}).get("sell_price",0)}
        save_items(self.gid,db)
        act="updated" if self.item_id else "created"
        await ix.response.edit_message(content=ui_box("Item",
            [f"✅ **{name}** (`{iid}`) {act}.",""]+_panel_text(self.gid).split("\n")[1:]),view=self.parent)

class EditItemView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self._build()
    def _build(self):
        self.clear_items()
        db=load_items(self.gid); items=db.get("items",{})
        opts=[discord.SelectOption(label=f"{d.get('emoji','📦')} {d.get('name',iid)}",value=iid) for iid,d in list(items.items())[:25]] or [discord.SelectOption(label="No items",value="__none__")]
        s=Select(placeholder="Select item",options=opts,row=0); s.callback=self._cb; self.add_item(s)
        b=Button(label=t(self.gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _cb(self,ix):
        iid=ix.data["values"][0]
        if iid=="__none__": await ix.response.send_message("No items.",ephemeral=True); return
        it=load_items(self.gid).get("items",{}).get(iid,{})
        m=CreateItemModal(self.gid,iid,self.parent,prefill=it); m.title="Edit Item"
        await ix.response.send_modal(m)
    async def _back(self,ix): await ix.response.edit_message(content=_panel_text(self.gid),view=self.parent)

class ViewItemView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self._build()
    def _build(self):
        self.clear_items()
        db=load_items(self.gid); items=db.get("items",{})
        opts=[discord.SelectOption(label=f"{d.get('emoji','📦')} {d.get('name',iid)}",value=iid) for iid,d in list(items.items())[:25]] or [discord.SelectOption(label="No items",value="__none__")]
        s=Select(placeholder="Select item",options=opts,row=0); s.callback=self._cb; self.add_item(s)
        b=Button(label=t(self.gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _cb(self,ix):
        iid=ix.data["values"][0]
        if iid=="__none__": await ix.response.send_message("No items.",ephemeral=True); return
        db=load_items(self.gid); it=db.get("items",{}).get(iid,{}); cats=db.get("categories",{})
        cat_name=cats.get(it.get("category",""),{}).get("name","*Uncategorized*")
        lines=[f"**Category:** {cat_name}",f"**Description:** {it.get('description') or '*None*'}",
               f"**Emoji:** {it.get('emoji','📦')}",f"**Sell Price:** {it.get('sell_price',0)}"]
        if it.get("image_url"): lines.append(f"**Image:** [View]({it['image_url']})")
        self._build()
        await ix.response.edit_message(content=ui_box(f"{it.get('emoji','📦')} {it.get('name',iid)}",lines),view=self)
    async def _back(self,ix): await ix.response.edit_message(content=_panel_text(self.gid),view=self.parent)


# ── Give / Remove ─────────────────────────────────────────────────────────────

class SetQtyModal(Modal, title="Set Quantity"):
    qty = TextInput(label="Quantity", max_length=10, default="1")
    async def on_submit(self,ix): await ix.response.defer()

class GiveRemoveView(View):
    def __init__(self,gid,mode,parent):
        super().__init__(timeout=300); self.gid=gid; self.mode=mode; self.parent=parent
        self.sel_item=None; self.sel_users=[]; self.sel_role=None; self.qty=1; self._build()
    def _build(self):
        self.clear_items()
        db=load_items(self.gid); items=db.get("items",{})
        opts=[discord.SelectOption(label=f"{d.get('emoji','📦')} {d.get('name',iid)}",value=iid,default=(iid==self.sel_item)) for iid,d in list(items.items())[:25]] or [discord.SelectOption(label="No items",value="__none__")]
        s=Select(placeholder="Select item",options=opts,row=0); s.callback=self._item_cb; self.add_item(s)
        us=discord.ui.UserSelect(placeholder="Select users",min_values=1,max_values=25,row=1); us.callback=self._user_cb; self.add_item(us)
        rs=discord.ui.RoleSelect(placeholder="Via role",row=2); rs.callback=self._role_cb; self.add_item(rs)
        la="Give to Users" if self.mode=="give" else "Remove from Users"
        lb="Give via Role" if self.mode=="give" else "Remove via Role"
        for lbl,cb,row in [(la,self._act_users,3),(lb,self._act_role,3),(f"Qty: {self.qty}",self._set_qty,4),(t(self.gid,"back_btn"),self._back,4)]:
            b=Button(label=lbl,style=discord.ButtonStyle.green if "Give" in lbl or "Remove" in lbl and "back" not in lbl.lower() else discord.ButtonStyle.secondary,row=row); b.callback=cb; self.add_item(b)
    async def _item_cb(self,ix): v=ix.data["values"][0]; self.sel_item=v if v!="__none__" else None; self._build(); await ix.response.edit_message(view=self)
    async def _user_cb(self,ix): self.sel_users=ix.data["values"]; await ix.response.defer()
    async def _role_cb(self,ix): self.sel_role=ix.data["values"][0] if ix.data["values"] else None; await ix.response.defer()
    async def _set_qty(self,ix):
        m=SetQtyModal()
        async def on_sub(inter):
            try: self.qty=max(1,int(m.qty.value.strip()))
            except: pass
            self._build(); await inter.response.edit_message(view=self)
        m.on_submit=on_sub; await ix.response.send_modal(m)
    def _apply(self,players,uid,qty):
        p=players.setdefault(uid,{"inventory":{}})
        inv=p.setdefault("inventory",{})
        if self.mode=="give": inv[self.sel_item]=inv.get(self.sel_item,0)+qty
        else: inv[self.sel_item]=max(0,inv.get(self.sel_item,0)-qty)
    async def _act_users(self,ix):
        if not self.sel_item or not self.sel_users: await ix.response.send_message("Select item and users.",ephemeral=True); return
        ps=load_players(self.gid)
        for uid in self.sel_users: self._apply(ps,uid,self.qty)
        save_players(self.gid,ps)
        word="given to" if self.mode=="give" else "removed from"
        await ix.response.edit_message(content=ui_box("✅",[ f"Item {word} {len(self.sel_users)} user(s)."]),view=self.parent)
    async def _act_role(self,ix):
        if not self.sel_item or not self.sel_role: await ix.response.send_message("Select item and role.",ephemeral=True); return
        role=ix.guild.get_role(int(self.sel_role))
        if not role: await ix.response.send_message("Role not found.",ephemeral=True); return
        ps=load_players(self.gid)
        for m in role.members: self._apply(ps,str(m.id),self.qty)
        save_players(self.gid,ps)
        word="given to" if self.mode=="give" else "removed from"
        await ix.response.edit_message(content=ui_box("✅",[f"Item {word} {len(role.members)} member(s)."]),view=self.parent)
    async def _back(self,ix): await ix.response.edit_message(content=_panel_text(self.gid),view=self.parent)


# ── /item-admin ───────────────────────────────────────────────────────────────

@bot.tree.command(name="item-admin", description="Item admin panel")
@is_admin()
async def item_admin_cmd(ix: discord.Interaction):
    await ix.response.send_message(content=_panel_text(ix.guild_id), view=ItemAdminMainView(ix.guild_id), ephemeral=True)

@item_admin_cmd.error
async def item_admin_error(ix, error):
    await ix.response.send_message(t(ix.guild_id,"admin_only"), ephemeral=True)
