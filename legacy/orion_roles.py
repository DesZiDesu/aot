# ============================================================
# ORION — Role List System
# ============================================================
# - แอดมินสร้างหมวดบทบาท (เช่น "เทพ", "ผู้กล้า")
# - แต่ละหมวดมีรายชื่อบทบาท (เช่น "Zeus", "Athena")
# - แต่ละบทบาทมี logo/emoji + member list (Discord user IDs)
# - ผู้เล่นใช้ /บทบาท ดู; admin จัดการผ่าน /บทบาทแอดมิน
# ============================================================

import sys
import time
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_roles ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
_parse_int           = _orion_bot_mod._parse_int


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="🏷️"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


ROLES_FILE = f"{ORION_DATA_DIR}/role_list.json"

# schema:
# {
#   "categories": [
#     {
#       "id": "deities",
#       "name": "เทพ",
#       "emoji": "⚡",
#       "icon_url": "",
#       "roles": [
#         {
#           "id": "zeus",
#           "name": "Zeus",
#           "emoji": "⚡",
#           "icon_url": "",
#           "description": "เทพแห่งสายฟ้า",
#           "members": ["uid1", "uid2"]
#         }
#       ]
#     }
#   ]
# }


def load_role_data() -> dict:
    return load_json(ROLES_FILE, {"categories": []})


def save_role_data(d: dict):
    save_json(ROLES_FILE, d)


def _norm_icon(s: str):
    s = (s or "").strip()
    if s.lower().startswith(("http://", "https://")):
        return ("🏷️", s)
    return (s or "🏷️", "")


def _get_cat(cid: str):
    data = load_role_data()
    return next((c for c in data.get("categories", []) if c["id"] == cid), None)


def _get_role(cid: str, rid: str):
    cat = _get_cat(cid)
    if not cat: return None
    return next((r for r in cat.get("roles", []) if r["id"] == rid), None)


# ── Embeds ───────────────────────────────────────────────────
def _categories_embed() -> discord.Embed:
    data = load_role_data()
    cats = data.get("categories", [])
    embed = discord.Embed(
        title="ระบบบทบาท",
        description=f"_หมวดบทบาท **{len(cats)}** หมวด — เลือกจาก dropdown เพื่อดูรายชื่อ_",
        color=0x8e44ad,
    )
    for c in cats[:20]:
        roles = c.get("roles", [])
        total_members = sum(len(r.get("members", [])) for r in roles)
        icon = c.get("emoji", "🏷️")
        embed.add_field(
            name=f"{icon} {c.get('name','?')}",
            value=f"`{len(roles)}` บทบาท · `{total_members}` คน",
            inline=True,
        )
    return embed


def _category_detail_embed(cat: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{cat.get('emoji','🏷️')} {cat.get('name','?')}",
        description=f"_บทบาทในหมวดนี้ {len(cat.get('roles', []))} อัน_",
        color=0x8e44ad,
    )
    if cat.get("icon_url"):
        embed.set_thumbnail(url=cat["icon_url"])
    for r in cat.get("roles", [])[:25]:
        members = r.get("members", [])
        member_str = ", ".join(f"<@{u}>" for u in members[:10])
        if len(members) > 10:
            member_str += f" ... (+{len(members)-10})"
        member_str = member_str or "_(ว่าง)_"
        embed.add_field(
            name=f"{r.get('emoji','🏷️')} {r.get('name','?')} — {len(members)} คน",
            value=f"_{r.get('description','')[:200]}_\n{member_str}",
            inline=False,
        )
    return embed


# ── Player view ────────────────────────────────────────────
class RoleCategorySelect(discord.ui.Select):
    def __init__(self):
        data = load_role_data()
        cats = data.get("categories", [])
        options = []
        for c in cats[:25]:
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                description=f"{len(c.get('roles',[]))} บทบาท"[:80],
                emoji=_safe_emoji(c.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีหมวด", value="none")]
        super().__init__(placeholder="เลือกหมวดบทบาท...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cat = _get_cat(self.values[0])
        if not cat:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        await ix.response.send_message(embed=_category_detail_embed(cat), ephemeral=_eph("บทบาท"))


class RoleBrowseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(RoleCategorySelect())


# ── Admin ────────────────────────────────────────────────
class CatAddModal(discord.ui.Modal, title="เพิ่มหมวดบทบาท"):
    f_id   = discord.ui.TextInput(label="ID (a-z,_)", placeholder="deities", max_length=40)
    f_name = discord.ui.TextInput(label="ชื่อหมวด", max_length=60)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL)", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)

    async def on_submit(self, ix: discord.Interaction):
        cid = self.f_id.value.strip().lower().replace(" ", "_")
        data = load_role_data()
        if any(c["id"] == cid for c in data.get("categories", [])):
            await ix.response.send_message(f"❌ มี `{cid}` แล้ว", ephemeral=True); return
        emoji, icon_url = _norm_icon(self.f_icon.value)
        data.setdefault("categories", []).append({
            "id": cid,
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": (self.f_desc.value or "").strip(),
            "roles": [],
        })
        save_role_data(data)
        await ix.response.send_message(f"✅ เพิ่มหมวด `{cid}` แล้ว", ephemeral=True)


class CatPickSelect(discord.ui.Select):
    def __init__(self, action: str):
        self.action = action
        data = load_role_data()
        options = []
        for c in data.get("categories", [])[:25]:
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                description=f"{len(c.get('roles',[]))} บทบาท"[:80],
                emoji=_safe_emoji(c.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีหมวด", value="none")]
        super().__init__(placeholder="เลือกหมวด...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cid = self.values[0]
        if self.action == "delete":
            data = load_role_data()
            data["categories"] = [c for c in data.get("categories", []) if c["id"] != cid]
            save_role_data(data)
            await ix.response.edit_message(content=f"ลบหมวด `{cid}` แล้ว", view=None)
        elif self.action == "add_role":
            await ix.response.send_modal(RoleAddModal(cid))
        elif self.action == "manage_role":
            await ix.response.edit_message(
                content=f"เลือกบทบาทใน `{cid}` เพื่อจัดการ ↓",
                view=_role_manage_view(cid),
            )
        elif self.action == "view":
            cat = _get_cat(cid)
            await ix.response.send_message(embed=_category_detail_embed(cat), ephemeral=True)


class RoleAddModal(discord.ui.Modal, title="เพิ่มบทบาทใหม่"):
    f_id   = discord.ui.TextInput(label="Role ID (a-z,_)", placeholder="zeus", max_length=40)
    f_name = discord.ui.TextInput(label="ชื่อบทบาท", max_length=60)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL)", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)

    def __init__(self, cid: str):
        super().__init__()
        self.cid = cid

    async def on_submit(self, ix: discord.Interaction):
        rid = self.f_id.value.strip().lower().replace(" ", "_")
        data = load_role_data()
        cat = next((c for c in data.get("categories", []) if c["id"] == self.cid), None)
        if not cat:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        if any(r["id"] == rid for r in cat.get("roles", [])):
            await ix.response.send_message(f"❌ มี `{rid}` แล้ว", ephemeral=True); return
        emoji, icon_url = _norm_icon(self.f_icon.value)
        cat.setdefault("roles", []).append({
            "id": rid,
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": (self.f_desc.value or "").strip(),
            "members": [],
        })
        save_role_data(data)
        await ix.response.send_message(f"✅ เพิ่มบทบาท `{rid}` ใน `{self.cid}`", ephemeral=True)


def _role_manage_view(cid: str):
    v = discord.ui.View(timeout=300)
    v.add_item(RolePickSelect(cid))
    return v


class RolePickSelect(discord.ui.Select):
    def __init__(self, cid: str):
        self.cid = cid
        cat = _get_cat(cid) or {}
        roles = cat.get("roles", [])[:25]
        options = []
        for r in roles:
            options.append(discord.SelectOption(
                label=r.get("name","?")[:100],
                value=r["id"],
                description=f"{len(r.get('members',[]))} คน · {r.get('description','')[:50]}"[:80],
                emoji=_safe_emoji(r.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีบทบาท", value="none")]
        super().__init__(placeholder="เลือกบทบาทที่จะจัดการ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        rid = self.values[0]
        role = _get_role(self.cid, rid)
        embed = discord.Embed(
            title=f"{role.get('emoji','🏷️')} {role.get('name','?')}",
            description=f"_{role.get('description','')}_\n\n**สมาชิก:** {len(role.get('members',[]))} คน",
            color=0x8e44ad,
        )
        if role.get("icon_url"):
            embed.set_thumbnail(url=role["icon_url"])
        members = role.get("members", [])
        if members:
            embed.add_field(
                name="รายชื่อ",
                value=", ".join(f"<@{u}>" for u in members[:25]) or "_(ว่าง)_",
                inline=False,
            )
        await ix.response.edit_message(embed=embed, view=RoleMembersEditView(self.cid, rid))


class RoleMembersEditView(discord.ui.View):
    def __init__(self, cid: str, rid: str):
        super().__init__(timeout=300)
        self.cid = cid
        self.rid = rid
        self.add_item(RoleMembersUserSelect(cid, rid))

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ลบบทบาทนี้", style=discord.ButtonStyle.danger, row=1)
    async def b_delete(self, ix, _b):
        data = load_role_data()
        cat = next((c for c in data.get("categories", []) if c["id"] == self.cid), None)
        if not cat:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        cat["roles"] = [r for r in cat.get("roles", []) if r["id"] != self.rid]
        save_role_data(data)
        await ix.response.edit_message(content=f"ลบบทบาท `{self.rid}` แล้ว", embed=None, view=None)


class RoleMembersUserSelect(discord.ui.UserSelect):
    def __init__(self, cid: str, rid: str):
        super().__init__(placeholder="ติ๊กผู้เล่นที่จะเป็นสมาชิก (ทับของเดิม)...", min_values=0, max_values=25)
        self.cid = cid
        self.rid = rid

    async def callback(self, ix: discord.Interaction):
        data = load_role_data()
        cat = next((c for c in data.get("categories", []) if c["id"] == self.cid), None)
        if not cat:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        role = next((r for r in cat.get("roles", []) if r["id"] == self.rid), None)
        if not role:
            await ix.response.send_message("❌ ไม่พบบทบาท", ephemeral=True); return
        role["members"] = [str(u.id) for u in self.values if not u.bot]
        save_role_data(data)
        names = ", ".join(u.display_name for u in self.values[:25]) or "(ว่าง)"
        await ix.response.send_message(f"✅ อัปเดตสมาชิก `{self.rid}` — {names}", ephemeral=True)


class RoleAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="เพิ่มหมวด", style=discord.ButtonStyle.success, row=0)
    async def b_add_cat(self, ix, _b):
        await ix.response.send_modal(CatAddModal())

    @discord.ui.button(label="ลบหมวด", style=discord.ButtonStyle.danger, row=0)
    async def b_del_cat(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CatPickSelect("delete"))
        await ix.response.send_message("เลือกหมวด ↓", view=v, ephemeral=True)

    @discord.ui.button(label="เพิ่มบทบาทเข้าหมวด", style=discord.ButtonStyle.success, row=1)
    async def b_add_role(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CatPickSelect("add_role"))
        await ix.response.send_message("เลือกหมวด ↓", view=v, ephemeral=True)

    @discord.ui.button(label="จัดการบทบาท/สมาชิก", style=discord.ButtonStyle.primary, row=1)
    async def b_manage(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CatPickSelect("manage_role"))
        await ix.response.send_message("เลือกหมวด ↓", view=v, ephemeral=True)

    @discord.ui.button(label="ดูหมวด", style=discord.ButtonStyle.secondary, row=2)
    async def b_view(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(CatPickSelect("view"))
        await ix.response.send_message("เลือกหมวด ↓", view=v, ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="บทบาท", description="ดูระบบบทบาท", guild=_ORION_GUILD_OBJ)
async def cmd_roles(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    await interaction.response.send_message(
        embed=_categories_embed(),
        view=RoleBrowseView(),
        ephemeral=_eph("บทบาท"),
    )


@bot.tree.command(name="บทบาทแอดมิน", description="[Admin] จัดการระบบบทบาท", guild=_ORION_GUILD_OBJ)
async def cmd_roles_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    data = load_role_data()
    cats = data.get("categories", [])
    total_roles = sum(len(c.get("roles", [])) for c in cats)
    total_members = sum(sum(len(r.get("members", [])) for r in c.get("roles", [])) for c in cats)
    embed = discord.Embed(
        title="Roles — Admin Panel",
        description=(
            f"_หมวด **{len(cats)}** · บทบาท **{total_roles}** · สมาชิกรวม **{total_members}**_\n\n"
            "**Row 0** — เพิ่ม/ลบหมวด\n"
            "**Row 1** — เพิ่มบทบาท · จัดการบทบาท/สมาชิก\n"
            "**Row 2** — ดูหมวด"
        ),
        color=0x8e44ad,
    )
    await interaction.response.send_message(embed=embed, view=RoleAdminView(), ephemeral=True)
