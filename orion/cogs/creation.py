"""Orion — creation system: Blacksmith-exclusive item/skill crafting with admin review."""
import time
import uuid
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR, RANKS,
    load_config, save_config,
    load_json, save_json, get_data_dir,
    load_items_catalog, save_items_catalog,
    load_skill_cats, save_skill_cats,
    load_players, save_players,
)

POWER_TYPES = ["Aura", "False Magic", "Artifact"]


def load_creation_requests(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "creation_requests.json", {})


def save_creation_requests(gid: int, data: dict):
    save_json(get_data_dir(gid) / "creation_requests.json", data)


def _is_blacksmith(ix: discord.Interaction) -> bool:
    gid = ix.guild_id
    cfg = load_config(gid)
    role_id = cfg.get("blacksmith_role_id")
    if not role_id:
        return ix.user.guild_permissions.administrator
    member = ix.guild.get_member(ix.user.id)
    if not member:
        return False
    return any(str(r.id) == str(role_id) for r in member.roles) or \
           member.guild_permissions.administrator


# ── /create command ────────────────────────────────────────────────────────────

@bot.tree.command(name="create", description="[Blacksmith] สร้างไอเทมหรือ Artifact Skill ใหม่")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_create(ix: discord.Interaction):
    if not _is_blacksmith(ix):
        cfg     = load_config(ix.guild_id)
        role_id = cfg.get("blacksmith_role_id")
        role_str = f"<@&{role_id}>" if role_id else "Blacksmith role"
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"ต้องมี {role_str} ถึงจะสร้างได้",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🔨 สร้างสิ่งใหม่",
        description="เลือกประเภทที่ต้องการสร้าง:",
        color=EMBED_COLOR,
    )
    view = CreateTypeView(ix.guild_id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class CreateTypeView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=60)
        self.gid = gid

    @discord.ui.button(label="🎁 Normal Item", style=discord.ButtonStyle.secondary, row=0)
    async def normal_item(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(CreateItemModal(self.gid))

    @discord.ui.button(label="✨ Artifact Skill", style=discord.ButtonStyle.primary, row=0)
    async def artifact_skill(self, ix: discord.Interaction, _: discord.ui.Button):
        view  = ArtifactPowerTypeSelectView(self.gid)
        embed = discord.Embed(
            title="✨ สร้าง Artifact Skill",
            description="เลือกประเภทพลังที่สกิลนี้ใช้:",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)


# ── Normal Item Creation ───────────────────────────────────────────────────────

class CreateItemModal(discord.ui.Modal, title="สร้างไอเทมใหม่"):
    item_name = discord.ui.TextInput(label="ชื่อไอเทม", max_length=80)
    item_desc = discord.ui.TextInput(
        label="คำอธิบาย",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    item_cat  = discord.ui.TextInput(label="หมวดหมู่", max_length=40)
    item_rare = discord.ui.TextInput(label="Rarity (Common/Rare/Epic/Legendary)", max_length=20)
    item_img  = discord.ui.TextInput(label="รูป (URL, ไม่บังคับ)", required=False, max_length=300)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        req_id  = str(uuid.uuid4())[:8]
        request = {
            "type":        "item",
            "name":        self.item_name.value.strip(),
            "description": self.item_desc.value.strip(),
            "category":    self.item_cat.value.strip(),
            "rarity":      self.item_rare.value.strip(),
            "image":       self.item_img.value.strip(),
            "creator_id":  str(ix.user.id),
            "created_at":  time.time(),
            "status":      "pending",
        }
        reqs = load_creation_requests(self.gid)
        reqs[req_id] = request
        save_creation_requests(self.gid, reqs)
        await _notify_review(ix, self.gid, req_id, request)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"📋 ส่งใบสมัครสร้างไอเทม **{request['name']}** แล้ว รอ Admin อนุมัติ",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


# ── Artifact Skill Creation ────────────────────────────────────────────────────

class ArtifactPowerTypeSelectView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid            = gid
        self.selected_types: list[str] = []
        self._build()

    def _build(self):
        self.clear_items()
        for pt in POWER_TYPES:
            selected = pt in self.selected_types
            btn = discord.ui.Button(
                label=("✅ " if selected else "") + pt,
                style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
                row=0,
            )
            btn.callback = self._toggle(pt)
            self.add_item(btn)

        next_btn = discord.ui.Button(
            label="ถัดไป →",
            style=discord.ButtonStyle.primary,
            disabled=not self.selected_types,
            row=1,
        )
        next_btn.callback = self._next
        self.add_item(next_btn)

    def _toggle(self, pt: str):
        async def _cb(ix: discord.Interaction):
            if pt in self.selected_types:
                self.selected_types.remove(pt)
            elif len(self.selected_types) < 3:
                self.selected_types.append(pt)
            self._build()
            await ix.response.edit_message(view=self)
        return _cb

    async def _next(self, ix: discord.Interaction):
        await ix.response.send_modal(
            CreateArtifactSkillModal(self.gid, list(self.selected_types))
        )


class CreateArtifactSkillModal(discord.ui.Modal, title="สร้าง Artifact Skill"):
    skill_name = discord.ui.TextInput(label="ชื่อสกิล", max_length=80)
    skill_desc = discord.ui.TextInput(
        label="คำอธิบายสกิล",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    skill_cd   = discord.ui.TextInput(label="คูลดาวน์", max_length=100)
    drawback   = discord.ui.TextInput(
        label="ผลเสีย (Drawback)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )
    rank_f     = discord.ui.TextInput(label="Rank เริ่มต้น (เช่น E-, D, B+)", max_length=4)

    def __init__(self, gid: int, power_types: list):
        super().__init__()
        self.gid         = gid
        self.power_types = power_types

    async def on_submit(self, ix: discord.Interaction):
        rank = self.rank_f.value.strip().upper()
        if rank not in RANKS:
            rank = "E-"

        req_id  = str(uuid.uuid4())[:8]
        request = {
            "type":          "artifact_skill",
            "name":          self.skill_name.value.strip(),
            "description":   self.skill_desc.value.strip(),
            "power_types":   self.power_types,
            "cooldown":      self.skill_cd.value.strip(),
            "drawback":      self.drawback.value.strip(),
            "rank":          rank,
            "transferable":  True,
            "creator_id":    str(ix.user.id),
            "created_at":    time.time(),
            "status":        "pending",
        }
        reqs = load_creation_requests(self.gid)
        reqs[req_id] = request
        save_creation_requests(self.gid, reqs)
        await _notify_review(ix, self.gid, req_id, request)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"📋 ส่งใบสมัครสร้าง Artifact Skill **{request['name']}** แล้ว รอ Admin อนุมัติ",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


async def _notify_review(ix: discord.Interaction, gid: int, req_id: str, request: dict):
    cfg           = load_config(gid)
    review_ch_id  = cfg.get("admin_review_channel_id")
    if not review_ch_id:
        return
    try:
        review_ch = ix.guild.get_channel(int(review_ch_id))
        if not review_ch:
            return
        pt_str = ", ".join(request.get("power_types", [])) or "—"
        embed  = discord.Embed(
            title=f"🔨 คำขอสร้าง [{request['type']}]: {request['name']}",
            color=0xF59E0B,
        )
        embed.add_field(name="ผู้สร้าง",   value=f"<@{request['creator_id']}>", inline=True)
        embed.add_field(name="ประเภท",     value=request["type"],              inline=True)
        if request.get("power_types"):
            embed.add_field(name="Power Type", value=pt_str, inline=True)
        embed.add_field(name="คำอธิบาย", value=request.get("description","")[:300], inline=False)
        if request.get("rank"):
            embed.add_field(name="Rank", value=request["rank"], inline=True)
        await review_ch.send(embed=embed, view=CreationReviewView(gid, req_id))
    except Exception:
        pass


# ── Admin review for creations ─────────────────────────────────────────────────

class CreationReviewView(discord.ui.View):
    def __init__(self, gid: int, req_id: str):
        super().__init__(timeout=None)
        self.gid    = gid
        self.req_id = req_id

    @discord.ui.button(label="✅ อนุมัติ", style=discord.ButtonStyle.success)
    async def approve(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return
        reqs = load_creation_requests(self.gid)
        req  = reqs.get(self.req_id)
        if not req:
            await ix.response.send_message("คำขอไม่พบ (อาจถูกประมวลผลแล้ว)", ephemeral=True)
            return

        if req["type"] == "item":
            # Add to items catalog
            catalog = load_items_catalog(self.gid)
            iid     = req["name"].lower().replace(" ", "_")[:30]
            catalog[iid] = {
                "name":        req["name"],
                "description": req["description"],
                "category":    req.get("category", ""),
                "rarity":      req.get("rarity", "Common"),
                "image":       req.get("image", ""),
                "creator_id":  req.get("creator_id"),
            }
            save_items_catalog(self.gid, catalog)
            result_msg = f"✅ อนุมัติไอเทม **{req['name']}** → เพิ่มใน Catalog แล้ว"

        elif req["type"] == "artifact_skill":
            # Add to skill categories
            cats = load_skill_cats(self.gid)
            skill_id = req["name"].lower().replace(" ", "_")[:30]
            if "approved_artifacts" not in cats:
                cats["approved_artifacts"] = {
                    "name":         "✨ Artifact Skills",
                    "transferable": True,
                    "skills":       {},
                }
            cats["approved_artifacts"].setdefault("skills", {})[skill_id] = {
                "name":        req["name"],
                "description": req["description"],
                "power_types": req.get("power_types", []),
                "cooldown":    req.get("cooldown", ""),
                "drawback":    req.get("drawback", ""),
                "rank":        req.get("rank", "E-"),
                "transferable": True,
                "creator_id":  req.get("creator_id"),
            }
            save_skill_cats(self.gid, cats)
            result_msg = f"✅ อนุมัติ Artifact Skill **{req['name']}** → เพิ่มใน Skill List แล้ว"
        else:
            result_msg = "✅ อนุมัติแล้ว"

        # DM creator
        creator_id = req.get("creator_id")
        if creator_id:
            try:
                member = ix.guild.get_member(int(creator_id))
                if member:
                    await member.send(
                        embed=discord.Embed(
                            description=f"🎉 คำขอสร้าง **{req['name']}** ได้รับการอนุมัติแล้ว!",
                            color=discord.Color.green(),
                        )
                    )
            except Exception:
                pass

        del reqs[self.req_id]
        save_creation_requests(self.gid, reqs)
        await ix.response.edit_message(
            embed=discord.Embed(description=result_msg, color=discord.Color.green()),
            view=None,
        )

    @discord.ui.button(label="❌ ปฏิเสธ", style=discord.ButtonStyle.danger)
    async def refuse(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return
        await ix.response.send_modal(RefuseCreationModal(self.gid, self.req_id))


class RefuseCreationModal(discord.ui.Modal, title="เหตุผลการปฏิเสธ"):
    reason = discord.ui.TextInput(
        label="เหตุผล",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, gid: int, req_id: str):
        super().__init__()
        self.gid    = gid
        self.req_id = req_id

    async def on_submit(self, ix: discord.Interaction):
        reqs = load_creation_requests(self.gid)
        req  = reqs.get(self.req_id, {})

        creator_id = req.get("creator_id")
        if creator_id:
            try:
                member = ix.guild.get_member(int(creator_id))
                if member:
                    await member.send(
                        embed=discord.Embed(
                            description=(
                                f"❌ คำขอสร้าง **{req.get('name','?')}** ถูกปฏิเสธ\n"
                                + (f"**เหตุผล:** {self.reason.value}" if self.reason.value else "")
                            ),
                            color=discord.Color.red(),
                        )
                    )
            except Exception:
                pass

        reqs.pop(self.req_id, None)
        save_creation_requests(self.gid, reqs)
        await ix.response.send_message(
            embed=discord.Embed(description="❌ ปฏิเสธคำขอแล้ว", color=discord.Color.red()),
            ephemeral=True,
        )


# ── Skill transfer system ──────────────────────────────────────────────────────

@bot.tree.command(name="skill-transfer", description="[Admin] โอนสกิล Artifact ให้ผู้เล่น")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_skill_transfer(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    view = SkillTransferFromView(ix.guild_id)
    embed = discord.Embed(
        title="🔄 โอนสกิล",
        description="เลือกผู้เล่นต้นทาง (ผู้ให้สกิล):",
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class SkillTransferFromView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid = gid
        sel = discord.ui.UserSelect(placeholder="เลือกผู้ให้สกิล…", row=0)
        sel.callback = self._on_from
        self.add_item(sel)

    async def _on_from(self, ix: discord.Interaction):
        from_uid = int(ix.data["values"][0])
        players  = load_players(self.gid)
        player   = players.get(str(from_uid), {})
        skills   = [
            (i, sk)
            for i, sk in enumerate(player.get("skills", []))
            if sk.get("transferable")
        ]
        if not skills:
            await ix.response.send_message(
                "ผู้เล่นนี้ไม่มีสกิล Transferable", ephemeral=True
            )
            return
        opts = [
            discord.SelectOption(
                label=sk.get("name", f"สกิล {i+1}")[:100],
                value=str(i),
                description=f"{sk.get('type','?')} | Rank: {sk.get('rank','?')}",
            )
            for i, sk in skills
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกสกิลที่จะโอน…", options=opts, row=0)

        gid      = self.gid
        from_id  = from_uid

        async def _on_skill(ix2: discord.Interaction):
            skill_idx = int(ix2.data["values"][0])
            view2 = SkillTransferToView(gid, from_id, skill_idx)
            embed = discord.Embed(
                description="เลือกผู้รับสกิล:",
                color=EMBED_COLOR,
            )
            await ix2.response.edit_message(embed=embed, view=view2)

        sel.callback = _on_skill
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.edit_message(
            embed=discord.Embed(description="เลือกสกิลที่จะโอน:", color=EMBED_COLOR),
            view=v,
        )


class SkillTransferToView(discord.ui.View):
    def __init__(self, gid: int, from_uid: int, skill_idx: int):
        super().__init__(timeout=120)
        self.gid       = gid
        self.from_uid  = from_uid
        self.skill_idx = skill_idx
        sel = discord.ui.UserSelect(placeholder="เลือกผู้รับสกิล…", row=0)
        sel.callback = self._on_to
        self.add_item(sel)

    async def _on_to(self, ix: discord.Interaction):
        to_uid  = int(ix.data["values"][0])
        players = load_players(self.gid)

        from_player = players.get(str(self.from_uid), {})
        to_player   = players.get(str(to_uid), {})
        from_skills = from_player.get("skills", [])

        if self.skill_idx >= len(from_skills):
            await ix.response.send_message("ไม่พบสกิลนี้", ephemeral=True)
            return

        skill = from_skills.pop(self.skill_idx)
        from_player["skills"] = from_skills
        to_player.setdefault("skills", []).append(skill)
        players[str(self.from_uid)] = from_player
        players[str(to_uid)]        = to_player
        from core.shared import save_players
        save_players(self.gid, players)

        await ix.response.edit_message(
            embed=discord.Embed(
                description=(
                    f"🔄 โอนสกิล **{skill.get('name','?')}** "
                    f"จาก <@{self.from_uid}> ให้ <@{to_uid}> แล้ว"
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )


# ── /create-config (admin) ────────────────────────────────────────────────────

@bot.tree.command(name="create-config", description="[Admin] ตั้งค่าระบบสร้าง (Blacksmith role, review channel)")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_create_config(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    view = CreateConfigView(ix.guild_id)
    embed = _create_config_embed(ix.guild_id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


def _create_config_embed(gid: int) -> discord.Embed:
    cfg      = load_config(gid)
    role_id  = cfg.get("blacksmith_role_id")
    ch_id    = cfg.get("admin_review_channel_id")
    embed = discord.Embed(title="🔨 Creation Config", color=EMBED_COLOR)
    embed.add_field(
        name="Blacksmith Role",
        value=f"<@&{role_id}>" if role_id else "ไม่ได้ตั้ง",
        inline=True,
    )
    embed.add_field(
        name="Admin Review Channel",
        value=f"<#{ch_id}>" if ch_id else "ไม่ได้ตั้ง",
        inline=True,
    )
    return embed


class CreateConfigView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="🎭 ตั้ง Blacksmith Role", style=discord.ButtonStyle.secondary, row=0)
    async def set_role(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.RoleSelect(placeholder="เลือก Blacksmith Role…", row=0)

        async def _cb(ix2: discord.Interaction):
            role_id = ix2.data["values"][0]
            cfg = load_config(self.gid)
            cfg["blacksmith_role_id"] = role_id
            save_config(self.gid, cfg)
            await ix2.response.edit_message(
                embed=_create_config_embed(self.gid), view=self
            )

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="📋 ตั้ง Review Channel", style=discord.ButtonStyle.secondary, row=0)
    async def set_channel(self, ix: discord.Interaction, _: discord.ui.Button):
        sel = discord.ui.ChannelSelect(
            placeholder="เลือก Review Channel…",
            channel_types=[discord.ChannelType.text],
            row=0,
        )

        async def _cb(ix2: discord.Interaction):
            ch_id = ix2.data["values"][0]
            cfg = load_config(self.gid)
            cfg["admin_review_channel_id"] = ch_id
            save_config(self.gid, cfg)
            await ix2.response.edit_message(
                embed=_create_config_embed(self.gid), view=self
            )

        sel.callback = _cb
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)
