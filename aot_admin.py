"""Admin panel — roles, lists, bloodlines, shifter access, language."""
import discord
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput

from aot_bot_instance import bot
from aot_shared import (
    t, load_config, save_config, ui_box, select_options_from_list,
)


def is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


def _admin_text(gid):
    cfg = load_config(gid)
    lang = "Thai 🇹🇭" if cfg.get("language","th") == "th" else "English 🇬🇧"
    return ui_box(t(gid, "admin_title"), [
        t(gid, "admin_desc"), "",
        f"**Factions:** {', '.join(cfg.get('factions',[])[:5])}{'…' if len(cfg.get('factions',[]))>5 else ''}",
        f"**Ranks:** {', '.join(cfg.get('ranks',[])[:5])}",
        f"**Common BL:** {', '.join(cfg.get('bloodlines_common',[]))}",
        f"**Special BL:** {', '.join(cfg.get('bloodlines_special',[]))}",
        f"**Language:** {lang}",
    ])


class AdminMainView(View):
    def __init__(self, gid):
        super().__init__(timeout=300); self.gid = gid; self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid
        row0 = [("faction_roles_btn","faction"),("rank_roles_btn","rank"),
                ("shifter_roles_btn","shifter"),("bloodline_roles_btn","bloodline")]
        for key, rtype in row0:
            b = Button(label=t(gid,key), style=discord.ButtonStyle.secondary, row=0)
            b.callback = self._make_role_cb(rtype)
            self.add_item(b)
        row1 = [("manage_factions_btn","factions"),("manage_ranks_btn","ranks"),("manage_shifters_btn","shifters")]
        for key, list_key in row1:
            b = Button(label=t(gid,key), style=discord.ButtonStyle.secondary, row=1)
            b.callback = self._make_list_cb(list_key)
            self.add_item(b)
        for key, cb in [("manage_bloodlines_btn", self._bloodlines),
                        ("grant_bloodline_btn",   self._grant_bl),
                        ("grant_shifter_btn",      self._grant_sh)]:
            b = Button(label=t(gid,key), style=discord.ButtonStyle.secondary, row=2)
            b.callback = cb; self.add_item(b)
        for key, cb in [("shifter_tracker_btn", self._tracker),
                        ("language_btn",         self._language)]:
            b = Button(label=t(gid,key), style=discord.ButtonStyle.secondary, row=3)
            b.callback = cb; self.add_item(b)
        done = Button(label=t(gid,"done_btn"), style=discord.ButtonStyle.danger, row=4)
        done.callback = self._done; self.add_item(done)

    def _make_role_cb(self, rtype):
        async def cb(ix):
            v = RoleMappingView(self.gid, rtype, self)
            await ix.response.edit_message(content=_role_map_text(self.gid, rtype), view=v)
        return cb

    def _make_list_cb(self, list_key):
        async def cb(ix):
            v = ManageListView(self.gid, list_key, self)
            await ix.response.edit_message(content=_list_text(self.gid, list_key), view=v)
        return cb

    async def _bloodlines(self, ix): await ix.response.edit_message(content=_bl_text(self.gid), view=ManageBloodlinesView(self.gid, self))
    async def _grant_bl(self, ix):   await ix.response.edit_message(content=_grant_bl_text(self.gid), view=GrantBloodlineView(self.gid, self))
    async def _grant_sh(self, ix):   await ix.response.edit_message(content=_grant_sh_text(self.gid), view=GrantShifterView(self.gid, self))
    async def _tracker(self, ix):    await ix.response.edit_message(content=_tracker_text(self.gid, ix.guild), view=ShifterTrackerView(self.gid, self))
    async def _language(self, ix):   await ix.response.edit_message(content=_lang_text(self.gid), view=LanguageView(self.gid, self))
    async def _done(self, ix):       await ix.response.edit_message(content=t(self.gid,"panel_closed"), view=None)


# ── Role mapping ──────────────────────────────────────────────────────────────

def _role_map_text(gid, rtype):
    cfg = load_config(gid); mappings = cfg["roles"].get(rtype,{})
    items = {"faction":cfg.get("factions",[]),"rank":cfg.get("ranks",[]),
             "shifter":cfg.get("shifters",[]),
             "bloodline":cfg.get("bloodlines_common",[])+cfg.get("bloodlines_special",[])}[rtype]
    lines = [f"**{i}** — {'<@&'+str(mappings[i])+'>' if i in mappings else '*not set*'}" for i in items]
    return ui_box(f"{rtype.title()} Roles", lines or ["—"])

class RoleMappingView(View):
    def __init__(self, gid, rtype, parent):
        super().__init__(timeout=300); self.gid=gid; self.rtype=rtype; self.parent=parent; self.sel=None; self._build()

    def _items(self):
        cfg = load_config(self.gid)
        return {"faction":cfg.get("factions",[]),"rank":cfg.get("ranks",[]),
                "shifter":cfg.get("shifters",[]),
                "bloodline":cfg.get("bloodlines_common",[])+cfg.get("bloodlines_special",[])}[self.rtype]

    def _build(self):
        self.clear_items()
        s = Select(placeholder=f"Select {self.rtype}", options=select_options_from_list(self._items(), self.sel), row=0)
        s.callback = self._val_cb; self.add_item(s)
        rs = discord.ui.RoleSelect(placeholder="Assign role", row=1); rs.callback = self._role_cb; self.add_item(rs)
        b = Button(label=t(self.gid,"back_btn"), style=discord.ButtonStyle.secondary, row=2); b.callback = self._back; self.add_item(b)

    async def _val_cb(self, ix): self.sel=ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _role_cb(self, ix):
        if not self.sel or self.sel=="__none__":
            await ix.response.send_message(t(self.gid,"select_value_first"),ephemeral=True); return
        cfg=load_config(self.gid); cfg["roles"][self.rtype][self.sel]=ix.data["values"][0]; save_config(self.gid,cfg)
        self._build(); await ix.response.edit_message(content=_role_map_text(self.gid,self.rtype),view=self)
    async def _back(self, ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)


# ── Manage list ───────────────────────────────────────────────────────────────

def _list_text(gid, key):
    items = load_config(gid).get(key,[])
    return ui_box(f"Manage {key.title()}", [f"- {i}" for i in items] or ["*None*"])

class _AddModal(Modal):
    val = TextInput(label="Name", max_length=60)
    def __init__(self, gid, key, parent):
        super().__init__(title=f"Add to {key}"); self.gid=gid; self.key=key; self.parent=parent
    async def on_submit(self, ix):
        cfg=load_config(self.gid); v=self.val.value.strip()
        if v and v not in cfg.get(self.key,[]): cfg.setdefault(self.key,[]).append(v); save_config(self.gid,cfg)
        await ix.response.edit_message(content=_list_text(self.gid,self.key),view=self.parent)

class ManageListView(View):
    def __init__(self, gid, key, parent):
        super().__init__(timeout=300); self.gid=gid; self.key=key; self.parent=parent; self._build()
    def _build(self):
        self.clear_items()
        a=Button(label="Add",style=discord.ButtonStyle.green,row=0); a.callback=self._add; self.add_item(a)
        r=Button(label="Remove",style=discord.ButtonStyle.danger,row=0); r.callback=self._remove; self.add_item(r)
        b=Button(label=t(self.gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _add(self, ix): await ix.response.send_modal(_AddModal(self.gid,self.key,self))
    async def _remove(self, ix):
        items=load_config(self.gid).get(self.key,[])
        v=RemoveSelectView(self.gid,self.key,items,self)
        await ix.response.edit_message(content=f"Select to remove from **{self.key}**:",view=v)
    async def _back(self, ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)

class RemoveSelectView(View):
    def __init__(self, gid, key, items, parent):
        super().__init__(timeout=300); self.gid=gid; self.key=key; self.parent=parent
        s=Select(placeholder="Select to remove",options=select_options_from_list(items),row=0); s.callback=self._cb; self.add_item(s)
        b=Button(label=t(gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _cb(self, ix):
        v=ix.data["values"][0]
        if v!="__none__":
            cfg=load_config(self.gid); lst=cfg.get(self.key,[]); lst.remove(v) if v in lst else None; save_config(self.gid,cfg)
        await ix.response.edit_message(content=_list_text(self.gid,self.key),view=self.parent)
    async def _back(self, ix): await ix.response.edit_message(content=_list_text(self.gid,self.key),view=self.parent)


# ── Bloodlines ────────────────────────────────────────────────────────────────

def _bl_text(gid):
    cfg=load_config(gid)
    return ui_box("Manage Bloodlines",[
        "**Common:**"]+[f"  - {b}" for b in cfg.get("bloodlines_common",[])] +
        ["","**Special:**"]+[f"  - {b}" for b in cfg.get("bloodlines_special",[])])

class _BlModal(Modal):
    name=TextInput(label="Bloodline Name",max_length=60)
    def __init__(self,gid,key,parent): super().__init__(title=f"Add {'Special' if 'special' in key else 'Common'} Bloodline"); self.gid=gid; self.key=key; self.parent=parent
    async def on_submit(self,ix):
        cfg=load_config(self.gid); v=self.name.value.strip()
        all_bl=cfg.get("bloodlines_common",[])+cfg.get("bloodlines_special",[])
        if v and v not in all_bl: cfg.setdefault(self.key,[]).append(v); save_config(self.gid,cfg)
        await ix.response.edit_message(content=_bl_text(self.gid),view=self.parent)

class ManageBloodlinesView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self._build()
    def _build(self):
        self.clear_items()
        for lbl,key,style in [("Add Common","bloodlines_common",discord.ButtonStyle.green),
                               ("Add Special","bloodlines_special",discord.ButtonStyle.green),
                               ("Remove",None,discord.ButtonStyle.danger)]:
            b=Button(label=lbl,style=style,row=0); b.callback=self._make_cb(key); self.add_item(b)
        bk=Button(label=t(self.gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); bk.callback=self._back; self.add_item(bk)
    def _make_cb(self,key):
        async def cb(ix):
            if key:
                await ix.response.send_modal(_BlModal(self.gid,key,self))
            else:
                cfg=load_config(self.gid); all_bl=cfg.get("bloodlines_common",[])+cfg.get("bloodlines_special",[])
                await ix.response.edit_message(content="Select bloodline to remove:",view=_RemoveBlView(self.gid,all_bl,self))
        return cb
    async def _back(self,ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)

class _RemoveBlView(View):
    def __init__(self,gid,items,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent
        s=Select(placeholder="Select",options=select_options_from_list(items),row=0); s.callback=self._cb; self.add_item(s)
        b=Button(label=t(gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _cb(self,ix):
        v=ix.data["values"][0]
        if v!="__none__":
            cfg=load_config(self.gid)
            for k in ("bloodlines_common","bloodlines_special"):
                lst=cfg.get(k,[]); lst.remove(v) if v in lst else None
            save_config(self.gid,cfg)
        await ix.response.edit_message(content=_bl_text(self.gid),view=self.parent)
    async def _back(self,ix): await ix.response.edit_message(content=_bl_text(self.gid),view=self.parent)


# ── Grant special bloodline ───────────────────────────────────────────────────

def _grant_bl_text(gid):
    cfg=load_config(gid); acc=cfg.get("special_access",{})
    lines=[f"**Special BL:** {', '.join(cfg.get('bloodlines_special',[]))}","","**Current Grants:**"]
    lines+=([f"  <@{uid}>: {', '.join(bls)}" for uid,bls in acc.items()] if acc else ["  *None*"])
    return ui_box(t(gid,"grant_bloodline_btn"),lines)

class GrantBloodlineView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent
        self.sel_bl=None; self.sel_users=[]; self.sel_role=None; self._build()
    def _build(self):
        self.clear_items()
        special=load_config(self.gid).get("bloodlines_special",[])
        s=Select(placeholder="Choose bloodline",options=select_options_from_list(special,self.sel_bl),row=0); s.callback=self._bl_cb; self.add_item(s)
        us=discord.ui.UserSelect(placeholder="Select users",min_values=1,max_values=25,row=1); us.callback=self._user_cb; self.add_item(us)
        rs=discord.ui.RoleSelect(placeholder="Grant via role",row=2); rs.callback=self._role_cb; self.add_item(rs)
        for lbl,cb,style in [("Grant Users",self._grant_users,discord.ButtonStyle.green),
                              ("Grant via Role",self._grant_role,discord.ButtonStyle.green),
                              ("Revoke",self._revoke,discord.ButtonStyle.danger),
                              (t(self.gid,"back_btn"),self._back,discord.ButtonStyle.secondary)]:
            b=Button(label=lbl,style=style,row=3 if lbl in("Grant Users","Grant via Role") else 4); b.callback=cb; self.add_item(b)
    async def _bl_cb(self,ix): self.sel_bl=ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _user_cb(self,ix): self.sel_users=ix.data["values"]; await ix.response.defer()
    async def _role_cb(self,ix): self.sel_role=ix.data["values"][0] if ix.data["values"] else None; await ix.response.defer()
    async def _grant_users(self,ix):
        if not self.sel_bl or self.sel_bl=="__none__": await ix.response.send_message(t(self.gid,"select_value_first"),ephemeral=True); return
        cfg=load_config(self.gid); acc=cfg.setdefault("special_access",{})
        for uid in self.sel_users: acc.setdefault(uid,[]).append(self.sel_bl) if self.sel_bl not in acc.get(uid,[]) else None
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_bl_text(self.gid),view=self)
    async def _grant_role(self,ix):
        if not self.sel_bl or not self.sel_role: await ix.response.send_message(t(self.gid,"select_value_first"),ephemeral=True); return
        role=ix.guild.get_role(int(self.sel_role))
        if not role: await ix.response.send_message("Role not found.",ephemeral=True); return
        cfg=load_config(self.gid); acc=cfg.setdefault("special_access",{})
        for m in role.members: acc.setdefault(str(m.id),[]).append(self.sel_bl) if self.sel_bl not in acc.get(str(m.id),[]) else None
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_bl_text(self.gid),view=self)
    async def _revoke(self,ix): await ix.response.edit_message(content="Select users to revoke:",view=RevokeBlView(self.gid,self))
    async def _back(self,ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)

class RevokeBlView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self.sel_users=[]; self.sel_bl=None; self._build()
    def _build(self):
        self.clear_items()
        us=discord.ui.UserSelect(placeholder="Select users",min_values=1,max_values=25,row=0); us.callback=self._user_cb; self.add_item(us)
        special=load_config(self.gid).get("bloodlines_special",[])
        s=Select(placeholder="Bloodline",options=select_options_from_list(special,self.sel_bl),row=1); s.callback=self._bl_cb; self.add_item(s)
        rv=Button(label="Revoke",style=discord.ButtonStyle.danger,row=2); rv.callback=self._do; self.add_item(rv)
        b=Button(label=t(self.gid,"back_btn"),style=discord.ButtonStyle.secondary,row=2); b.callback=self._back; self.add_item(b)
    async def _user_cb(self,ix): self.sel_users=ix.data["values"]; await ix.response.defer()
    async def _bl_cb(self,ix): self.sel_bl=ix.data["values"][0]; self._build(); await ix.response.edit_message(view=self)
    async def _do(self,ix):
        cfg=load_config(self.gid); acc=cfg.get("special_access",{})
        for uid in self.sel_users:
            lst=acc.get(uid,[])
            if self.sel_bl in lst: lst.remove(self.sel_bl)
            if not lst: acc.pop(uid,None)
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_bl_text(self.gid),view=self.parent)
    async def _back(self,ix): await ix.response.edit_message(content=_grant_bl_text(self.gid),view=self.parent)


# ── Grant shifter access ──────────────────────────────────────────────────────

def _grant_sh_text(gid):
    cfg=load_config(gid); acc=cfg.get("shifter_access",[])
    lines=[f"**Titans:** {', '.join(cfg.get('shifters',[]))}","",
           "**Users with shifter access:**"]+([f"  <@{uid}>" for uid in acc] if acc else ["  *None*"])
    return ui_box(t(gid,"grant_shifter_btn"),lines)

class GrantShifterView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self.sel_users=[]; self.sel_role=None; self._build()
    def _build(self):
        self.clear_items()
        us=discord.ui.UserSelect(placeholder="Select users",min_values=1,max_values=25,row=0); us.callback=self._user_cb; self.add_item(us)
        rs=discord.ui.RoleSelect(placeholder="Grant via role",row=1); rs.callback=self._role_cb; self.add_item(rs)
        for lbl,cb,style,row in [("Grant Users",self._grant_u,discord.ButtonStyle.green,2),
                                  ("Grant via Role",self._grant_r,discord.ButtonStyle.green,2),
                                  ("Revoke Users",self._revoke,discord.ButtonStyle.danger,3),
                                  (t(self.gid,"back_btn"),self._back,discord.ButtonStyle.secondary,3)]:
            b=Button(label=lbl,style=style,row=row); b.callback=cb; self.add_item(b)
    async def _user_cb(self,ix): self.sel_users=ix.data["values"]; await ix.response.defer()
    async def _role_cb(self,ix): self.sel_role=ix.data["values"][0] if ix.data["values"] else None; await ix.response.defer()
    async def _grant_u(self,ix):
        cfg=load_config(self.gid); acc=cfg.setdefault("shifter_access",[])
        for uid in self.sel_users: acc.append(uid) if uid not in acc else None
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_sh_text(self.gid),view=self)
    async def _grant_r(self,ix):
        if not self.sel_role: await ix.response.send_message(t(self.gid,"select_value_first"),ephemeral=True); return
        role=ix.guild.get_role(int(self.sel_role))
        if not role: await ix.response.send_message("Role not found.",ephemeral=True); return
        cfg=load_config(self.gid); acc=cfg.setdefault("shifter_access",[])
        for m in role.members: acc.append(str(m.id)) if str(m.id) not in acc else None
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_sh_text(self.gid),view=self)
    async def _revoke(self,ix): await ix.response.edit_message(content="Select users to revoke shifter access:",view=RevokeShView(self.gid,self))
    async def _back(self,ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)

class RevokeShView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent; self.sel_users=[]
        us=discord.ui.UserSelect(placeholder="Select users",min_values=1,max_values=25,row=0); us.callback=self._uc; self.add_item(us)
        rv=Button(label="Revoke",style=discord.ButtonStyle.danger,row=1); rv.callback=self._do; self.add_item(rv)
        b=Button(label=t(gid,"back_btn"),style=discord.ButtonStyle.secondary,row=1); b.callback=self._back; self.add_item(b)
    async def _uc(self,ix): self.sel_users=ix.data["values"]; await ix.response.defer()
    async def _do(self,ix):
        cfg=load_config(self.gid); acc=cfg.get("shifter_access",[])
        for uid in self.sel_users: acc.remove(uid) if uid in acc else None
        save_config(self.gid,cfg); await ix.response.edit_message(content=_grant_sh_text(self.gid),view=self.parent)
    async def _back(self,ix): await ix.response.edit_message(content=_grant_sh_text(self.gid),view=self.parent)


# ── Shifter tracker ───────────────────────────────────────────────────────────

def _tracker_text(gid, guild):
    import time as _t
    from aot_shared import load_players
    players=load_players(gid); lines=[]
    for uid, p in players.items():
        powers=p.get("titan_powers",[])
        if not powers: continue
        member=guild.get_member(int(uid)) if guild else None
        name=member.display_name if member else f"<@{uid}>"
        exp=powers[0].get("expires_at",0); secs=max(0,int(exp-_t.time()))
        days=secs//86400; titan_names=", ".join(pw["titan"] for pw in powers)
        lines.append(f"**{name}** — {titan_names} — {days}d left")
    return ui_box(t(gid,"shifter_tracker_btn"), lines or ["*No active shifters*"])

class ShifterTrackerView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent
        b=Button(label=t(gid,"back_btn"),style=discord.ButtonStyle.secondary); b.callback=self._back; self.add_item(b)
        st=Button(label=t(gid,"set_shifter_time_btn"),style=discord.ButtonStyle.secondary); st.callback=self._set_time; self.add_item(st)
    async def _back(self,ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)
    async def _set_time(self,ix): await ix.response.send_modal(SetShifterTimeModal(self.gid,self))

class SetShifterTimeModal(Modal, title="Set Shifter Time"):
    uid_input  = TextInput(label="User ID",      max_length=25)
    days_input = TextInput(label="Days remaining",max_length=10)
    def __init__(self,gid,parent): super().__init__(); self.gid=gid; self.parent=parent
    async def on_submit(self,ix):
        import time as _t
        from aot_shared import load_players, save_players
        try:
            uid=self.uid_input.value.strip(); days=int(self.days_input.value.strip())
            players=load_players(self.gid); p=players.get(uid,{})
            for pw in p.get("titan_powers",[]): pw["expires_at"]=_t.time()+days*86400
            save_players(self.gid,players)
            await ix.response.edit_message(content=_tracker_text(self.gid,ix.guild),view=self.parent)
        except Exception as e:
            await ix.response.send_message(f"Error: {e}",ephemeral=True)


# ── Language ──────────────────────────────────────────────────────────────────

def _lang_text(gid):
    cfg=load_config(gid); lang=cfg.get("language","th")
    return ui_box(t(gid,"language_btn"),[f"Current: {'Thai 🇹🇭' if lang=='th' else 'English 🇬🇧'}"])

class LanguageView(View):
    def __init__(self,gid,parent):
        super().__init__(timeout=300); self.gid=gid; self.parent=parent
        for key,lang in [("language_th","th"),("language_en","en")]:
            b=Button(label=t(gid,key),style=discord.ButtonStyle.primary); b.callback=self._make_cb(lang); self.add_item(b)
        bk=Button(label=t(gid,"back_btn"),style=discord.ButtonStyle.secondary); bk.callback=self._back; self.add_item(bk)
    def _make_cb(self,lang):
        async def cb(ix):
            cfg=load_config(self.gid); cfg["language"]=lang; save_config(self.gid,cfg)
            label="Thai 🇹🇭" if lang=="th" else "English 🇬🇧"
            await ix.response.edit_message(content=ui_box(t(self.gid,"language_btn"),[t(self.gid,"language_set",lang=label)]),view=self)
        return cb
    async def _back(self,ix): await ix.response.edit_message(content=_admin_text(self.gid),view=self.parent)


# ── /admin command ────────────────────────────────────────────────────────────

@bot.tree.command(name="admin", description="Admin panel")
@is_admin()
async def admin_cmd(ix: discord.Interaction):
    gid=ix.guild_id
    await ix.response.send_message(content=_admin_text(gid), view=AdminMainView(gid), ephemeral=True)

@admin_cmd.error
async def admin_error(ix, error):
    await ix.response.send_message(t(ix.guild_id,"admin_only"), ephemeral=True)
