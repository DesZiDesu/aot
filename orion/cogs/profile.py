"""Orion — character profile, forum-based creation, and character reset."""
import time
import uuid
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR, RANKS,
    load_players, save_players, load_config, save_config,
    load_pending, save_pending, default_stats,
    rank_index, progress_bar, overall_rank,
    ATTRIBUTES, ATTR_LABELS, money_str,
)

POWER_TYPES = ["Aura", "False Magic", "Artifact"]


# ── Profile embed helpers ─────────────────────────────────────────────────────

def _profile_embed(uid: int, player: dict, gid: int) -> discord.Embed:
    name   = player.get("name") or "Unknown"
    status = player.get("status", "active")
    color  = EMBED_COLOR if status == "active" else 0x808080
    embed  = discord.Embed(title=name, color=color)
    if player.get("image"):
        embed.set_thumbnail(url=player["image"])

    embed.add_field(name="ชื่อ",        value=player.get("name",   "?"), inline=True)
    embed.add_field(name="อายุ",        value=player.get("age",    "?"), inline=True)
    embed.add_field(name="เพศ",         value=player.get("gender", "?"), inline=True)
    embed.add_field(name="เผ่าพันธุ์",  value=player.get("race",   "?"), inline=True)
    embed.add_field(name="บทบาท",       value=player.get("role",   "?"), inline=True)

    pt = ", ".join(player.get("power_types", [])) or "—"
    embed.add_field(name="ประเภทพลัง", value=pt, inline=True)

    rank = player.get("power_rank", "E-")
    stats = player.get("stats", default_stats())
    ov = overall_rank(stats)
    embed.add_field(name="Power Rank",   value=rank, inline=True)
    embed.add_field(name="Stats Overall", value=ov, inline=True)

    bal = player.get("balance", 0)
    embed.add_field(name="เงิน", value=money_str(bal, gid), inline=True)

    embed.set_footer(text=f"ID: {uid}")
    return embed


def _stats_embed(uid: int, player: dict) -> discord.Embed:
    stats = player.get("stats", default_stats())
    embed = discord.Embed(title="📊 Stats", color=EMBED_COLOR)
    for attr in ATTRIBUTES:
        s    = stats.get(attr, {"rank": "E-", "xp": 0})
        rank = s.get("rank", "E-")
        xp   = s.get("xp", 0)
        bar  = progress_bar(xp)
        embed.add_field(
            name=f"{ATTR_LABELS[attr]} [{rank}]",
            value=f"`{bar}` {xp}/{100} XP",
            inline=False,
        )
    embed.add_field(name="Overall", value=overall_rank(stats), inline=False)
    return embed


def _skills_embed(player: dict) -> discord.Embed:
    skills = player.get("skills", [])
    embed  = discord.Embed(title="✨ Skills", color=EMBED_COLOR)
    if not skills:
        embed.description = "ยังไม่มีสกิล"
        return embed
    for i, sk in enumerate(skills, 1):
        transferable = "🔄" if sk.get("transferable") else ""
        embed.add_field(
            name=f"{i}. {sk.get('name','?')} {transferable}",
            value=(
                f"ประเภท: {sk.get('type','—')} | Rank: {sk.get('rank','—')}\n"
                f"{sk.get('description','')[:100]}"
            ),
            inline=False,
        )
    return embed


def _inventory_embed(player: dict, gid: int) -> discord.Embed:
    inv   = player.get("inventory", {})
    embed = discord.Embed(title="🎒 Inventory", color=EMBED_COLOR)
    if not inv:
        embed.description = "กระเป๋าว่างเปล่า"
        return embed
    for item_id, qty in inv.items():
        embed.add_field(name=item_id, value=f"x{qty}", inline=True)
    return embed


# ── Character creation — multi-step modals ────────────────────────────────────

class CreateModal1(discord.ui.Modal, title="สร้างตัวละคร (1/3) — ข้อมูลพื้นฐาน"):
    char_name  = discord.ui.TextInput(label="ชื่อตัวละคร",  max_length=60)
    age        = discord.ui.TextInput(label="อายุ",          max_length=10)
    gender     = discord.ui.TextInput(label="เพศ",           max_length=30)
    race       = discord.ui.TextInput(label="เผ่าพันธุ์",    max_length=60)
    appearance = discord.ui.TextInput(
        label="รูปลักษณ์",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )

    async def on_submit(self, ix: discord.Interaction):
        step1 = {
            "name":       self.char_name.value.strip(),
            "age":        self.age.value.strip(),
            "gender":     self.gender.value.strip(),
            "race":       self.race.value.strip(),
            "appearance": self.appearance.value.strip(),
        }
        await ix.response.send_modal(CreateModal2(step1))


class CreateModal2(discord.ui.Modal, title="สร้างตัวละคร (2/3) — ภูมิหลัง"):
    role_field = discord.ui.TextInput(label="บทบาท (Role)", max_length=80)
    backstory  = discord.ui.TextInput(
        label="ประวัติ (Backstory)",
        style=discord.TextStyle.paragraph,
        max_length=1500,
    )

    def __init__(self, step1: dict):
        super().__init__()
        self.step1 = step1

    async def on_submit(self, ix: discord.Interaction):
        step2 = {**self.step1, "role": self.role_field.value.strip(), "backstory": self.backstory.value.strip()}
        view  = PowerTypeSelectView(step2)
        embed = discord.Embed(
            title="สร้างตัวละคร (3/3) — ประเภทพลัง",
            description=(
                "เลือกประเภทพลัง (ได้สูงสุด 3 ประเภท)\n"
                "**Aura** · **False Magic** · **Artifact**\n\n"
                "กด **ถัดไป →** เมื่อเลือกเสร็จ"
            ),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class PowerTypeSelectView(discord.ui.View):
    def __init__(self, step2: dict):
        super().__init__(timeout=300)
        self.step2          = step2
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
            btn.callback = self._make_toggle(pt)
            self.add_item(btn)

        next_btn = discord.ui.Button(
            label="ถัดไป →",
            style=discord.ButtonStyle.primary,
            row=1,
            disabled=len(self.selected_types) == 0,
        )
        next_btn.callback = self._continue
        self.add_item(next_btn)

    def _make_toggle(self, pt: str):
        async def _cb(ix: discord.Interaction):
            if pt in self.selected_types:
                self.selected_types.remove(pt)
            elif len(self.selected_types) < 3:
                self.selected_types.append(pt)
            self._build()
            await ix.response.edit_message(view=self)
        return _cb

    async def _continue(self, ix: discord.Interaction):
        await ix.response.send_modal(CreateModal3(self.step2, list(self.selected_types)))


class CreateModal3(discord.ui.Modal, title="สร้างตัวละคร — รายละเอียดพลัง"):
    power_desc     = discord.ui.TextInput(
        label="คำอธิบายพลัง",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    power_cooldown = discord.ui.TextInput(label="คูลดาวน์พลัง", max_length=100)
    power_drawback = discord.ui.TextInput(
        label="ผลเสียของพลัง (Drawback)",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    image_url = discord.ui.TextInput(
        label="รูปตัวละคร (URL, ไม่บังคับ)",
        required=False,
        max_length=300,
    )

    def __init__(self, step2: dict, power_types: list):
        super().__init__()
        self.step2       = step2
        self.power_types = power_types

    async def on_submit(self, ix: discord.Interaction):
        gid = ix.guild_id
        uid = ix.user.id
        cfg = load_config(gid)

        application = {
            **self.step2,
            "power_types":       self.power_types,
            "power_description": self.power_desc.value.strip(),
            "power_cooldown":    self.power_cooldown.value.strip(),
            "power_drawback":    self.power_drawback.value.strip(),
            "image":             (self.image_url.value or "").strip(),
            "power_rank":        "E-",
            "stats":             default_stats(),
            "balance":           0,
            "inventory":         {},
            "skills":            [],
            "submitter_id":      uid,
            "submitted_at":      time.time(),
            "status":            "pending",
        }

        # Create forum thread if configured
        forum_thread_id = None
        forum_id = cfg.get("character_forum_id")
        if forum_id:
            try:
                forum = ix.guild.get_channel(int(forum_id))
                if isinstance(forum, discord.ForumChannel):
                    pt_str  = ", ".join(self.power_types) or "—"
                    content = (
                        f"**ชื่อ:** {application['name']}\n"
                        f"**อายุ:** {application['age']}\n"
                        f"**เพศ:** {application['gender']}\n"
                        f"**เผ่าพันธุ์:** {application['race']}\n"
                        f"**บทบาท:** {application['role']}\n\n"
                        f"**รูปลักษณ์:**\n{application['appearance']}\n\n"
                        f"**ประวัติ:**\n{application['backstory']}\n\n"
                        f"**ประเภทพลัง:** {pt_str}\n"
                        f"**คำอธิบายพลัง:**\n{application['power_description']}\n"
                        f"**คูลดาวน์:** {application['power_cooldown']}\n"
                        f"**ผลเสีย:** {application['power_drawback']}\n"
                        f"**Power Rank:** {application['power_rank']}"
                    )
                    app_embed = discord.Embed(
                        title=f"📋 {application['name']} — ใบสมัครตัวละคร",
                        description=content[:4000],
                        color=0xF59E0B,
                    )
                    app_embed.set_footer(
                        text=f"ผู้สมัคร: {ix.user.display_name} ({uid})"
                    )
                    if application["image"]:
                        app_embed.set_thumbnail(url=application["image"])

                    thread, _ = await forum.create_thread(
                        name=f"[PENDING] {application['name']} — {ix.user.display_name}",
                        content=f"<@{uid}> ส่งใบสมัครตัวละครแล้ว รอ Admin ตรวจสอบ",
                        embed=app_embed,
                    )
                    forum_thread_id = thread.id
                    application["forum_thread_id"] = forum_thread_id
            except Exception:
                pass

        # Save pending
        pending = load_pending(gid)
        app_id  = str(uid)  # one pending per user
        pending[app_id] = application
        save_pending(gid, pending)

        # Notify admin review channel
        review_ch_id = cfg.get("admin_review_channel_id")
        if review_ch_id:
            try:
                review_ch = ix.guild.get_channel(int(review_ch_id))
                if review_ch:
                    rev_embed = discord.Embed(
                        title=f"📋 ใบสมัครใหม่: {application['name']}",
                        description=(
                            f"**ผู้เล่น:** <@{uid}>\n"
                            f"**เผ่าพันธุ์:** {application['race']}\n"
                            f"**ประเภทพลัง:** {', '.join(self.power_types) or '—'}"
                        ),
                        color=0xF59E0B,
                    )
                    if forum_thread_id:
                        rev_embed.add_field(
                            name="Forum", value=f"<#{forum_thread_id}>", inline=True
                        )
                    await review_ch.send(
                        embed=rev_embed,
                        view=AdminReviewView(gid, str(uid)),
                    )
            except Exception:
                pass

        confirm = discord.Embed(
            title="✅ ส่งใบสมัครสำเร็จ!",
            description=(
                f"ตัวละคร **{application['name']}** ถูกส่งรอตรวจสอบแล้ว\n"
                "คุณจะได้รับแจ้งผลทาง DM"
                + (f"\nForum: <#{forum_thread_id}>" if forum_thread_id else "")
            ),
            color=discord.Color.green(),
        )
        await ix.response.edit_message(embed=confirm, view=None)


# ── Admin review ──────────────────────────────────────────────────────────────

class AdminReviewView(discord.ui.View):
    def __init__(self, gid: int, uid_key: str):
        super().__init__(timeout=None)
        self.gid     = gid
        self.uid_key = uid_key

    @discord.ui.button(label="✅ อนุมัติ", style=discord.ButtonStyle.success, row=0)
    async def btn_approve(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            return await ix.response.send_message("Admin only.", ephemeral=True)
        gid     = self.gid
        pending = load_pending(gid)
        app     = pending.get(self.uid_key)
        if not app:
            return await ix.response.send_message("ไม่พบใบสมัคร (อาจถูกประมวลผลแล้ว)", ephemeral=True)

        uid = int(self.uid_key)

        # Save player
        players = load_players(gid)
        player_data = {k: v for k, v in app.items()
                       if k not in ("submitter_id", "submitted_at", "status")}
        player_data["status"] = "active"
        players[str(uid)] = player_data
        save_players(gid, players)

        # Remove pending
        del pending[self.uid_key]
        save_pending(gid, pending)

        # Rename forum thread
        thread_id = app.get("forum_thread_id")
        if thread_id:
            try:
                thread = ix.guild.get_thread(int(thread_id))
                if thread:
                    await thread.edit(name=thread.name.replace("[PENDING]", "[APPROVED]", 1))
            except Exception:
                pass

        # DM user
        try:
            member = ix.guild.get_member(uid)
            if member:
                dm_embed = discord.Embed(
                    title="🎉 ตัวละครของคุณได้รับการอนุมัติ!",
                    description=f"ตัวละคร **{app.get('name','?')}** ถูกอนุมัติแล้ว\nใช้คำสั่ง `/orion` เพื่อดูโปรไฟล์!",
                    color=discord.Color.green(),
                )
                await member.send(embed=dm_embed)
        except Exception:
            pass

        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"✅ อนุมัติตัวละคร **{app.get('name','?')}** แล้ว",
                color=discord.Color.green(),
            ),
            view=None,
        )

    @discord.ui.button(label="❌ ปฏิเสธ", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            return await ix.response.send_message("Admin only.", ephemeral=True)
        await ix.response.send_modal(DeclineReasonModal(self.gid, self.uid_key))

    @discord.ui.button(label="✏️ แก้ไข", style=discord.ButtonStyle.secondary, row=0)
    async def btn_edit(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            return await ix.response.send_message("Admin only.", ephemeral=True)
        pending = load_pending(self.gid)
        app     = pending.get(self.uid_key)
        if not app:
            return await ix.response.send_message("ไม่พบใบสมัคร", ephemeral=True)
        await ix.response.send_modal(AdminEditAppModal(self.gid, self.uid_key, app))


class DeclineReasonModal(discord.ui.Modal, title="เหตุผลการปฏิเสธ"):
    reason = discord.ui.TextInput(
        label="เหตุผล (จะส่งให้ผู้เล่นทาง DM)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, gid: int, uid_key: str):
        super().__init__()
        self.gid     = gid
        self.uid_key = uid_key

    async def on_submit(self, ix: discord.Interaction):
        pending = load_pending(self.gid)
        app     = pending.get(self.uid_key)
        if not app:
            await ix.response.send_message("ไม่พบใบสมัคร", ephemeral=True)
            return

        uid = int(self.uid_key)

        # DM user
        try:
            member = ix.guild.get_member(uid)
            if member:
                dm_embed = discord.Embed(
                    title="❌ ตัวละครถูกปฏิเสธ",
                    description=(
                        f"ตัวละคร **{app.get('name','?')}** ไม่ผ่านการอนุมัติ\n"
                        + (f"**เหตุผล:** {self.reason.value}" if self.reason.value else "")
                    ),
                    color=discord.Color.red(),
                )
                await member.send(embed=dm_embed)
        except Exception:
            pass

        # Archive forum thread
        thread_id = app.get("forum_thread_id")
        if thread_id:
            try:
                thread = ix.guild.get_thread(int(thread_id))
                if thread:
                    await thread.edit(name=thread.name.replace("[PENDING]", "[DECLINED]", 1))
                    await thread.edit(archived=True)
            except Exception:
                pass

        del pending[self.uid_key]
        save_pending(self.gid, pending)

        await ix.response.send_message(
            embed=discord.Embed(description="❌ ปฏิเสธใบสมัครแล้ว", color=discord.Color.red()),
            ephemeral=True,
        )


class AdminEditAppModal(discord.ui.Modal, title="แก้ไขใบสมัคร"):
    name_f   = discord.ui.TextInput(label="ชื่อ",       max_length=60)
    race_f   = discord.ui.TextInput(label="เผ่าพันธุ์", max_length=60)
    role_f   = discord.ui.TextInput(label="บทบาท",      max_length=80)
    power_f  = discord.ui.TextInput(
        label="ประเภทพลัง (คั่นด้วย , )",
        max_length=60,
    )
    pr_f     = discord.ui.TextInput(label="Power Rank", max_length=10)

    def __init__(self, gid: int, uid_key: str, app: dict):
        super().__init__()
        self.gid     = gid
        self.uid_key = uid_key
        self.name_f.default  = app.get("name", "")
        self.race_f.default  = app.get("race", "")
        self.role_f.default  = app.get("role", "")
        self.power_f.default = ", ".join(app.get("power_types", []))
        self.pr_f.default    = app.get("power_rank", "E-")

    async def on_submit(self, ix: discord.Interaction):
        pending = load_pending(self.gid)
        app     = pending.get(self.uid_key, {})
        app["name"]        = self.name_f.value.strip()
        app["race"]        = self.race_f.value.strip()
        app["role"]        = self.role_f.value.strip()
        app["power_types"] = [p.strip() for p in self.power_f.value.split(",") if p.strip()]
        rank_in = self.pr_f.value.strip().upper()
        from core.shared import RANKS
        if rank_in in RANKS:
            app["power_rank"] = rank_in
        pending[self.uid_key] = app
        save_pending(self.gid, pending)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ แก้ไขใบสมัครแล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )


# ── Profile View (tabbed) ─────────────────────────────────────────────────────

class ProfileView(discord.ui.View):
    def __init__(self, uid: int, gid: int, tab: str = "profile"):
        super().__init__(timeout=300)
        self.uid = uid
        self.gid = gid
        self._tab = tab
        self._rebuild()

    def _rebuild(self):
        self.clear_items()

        tabs = [
            ("📋 โปรไฟล์", "profile"),
            ("📊 Stats",   "stats"),
            ("✨ Skills",  "skills"),
            ("🎒 กระเป๋า", "inventory"),
        ]
        for label, key in tabs:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if self._tab == key else discord.ButtonStyle.secondary,
                row=0,
            )
            btn.callback = self._make_tab_cb(key)
            self.add_item(btn)

        edit_btn = discord.ui.Button(
            label="✏️ แก้ไข", style=discord.ButtonStyle.secondary, row=1
        )
        edit_btn.callback = self._edit
        self.add_item(edit_btn)

        del_btn = discord.ui.Button(
            label="🗑️ ลบตัวละคร", style=discord.ButtonStyle.danger, row=1
        )
        del_btn.callback = self._delete
        self.add_item(del_btn)

    def _make_tab_cb(self, tab: str):
        async def _cb(ix: discord.Interaction):
            if ix.user.id != self.uid:
                await ix.response.send_message("นี่ไม่ใช่โปรไฟล์ของคุณ", ephemeral=True)
                return
            self._tab = tab
            player    = load_players(self.gid).get(str(self.uid), {})
            self._rebuild()
            embed = self._build_embed(player)
            await ix.response.edit_message(embed=embed, view=self)
        return _cb

    def _build_embed(self, player: dict) -> discord.Embed:
        if self._tab == "profile":
            return _profile_embed(self.uid, player, self.gid)
        if self._tab == "stats":
            return _stats_embed(self.uid, player)
        if self._tab == "skills":
            return _skills_embed(player)
        return _inventory_embed(player, self.gid)

    async def _edit(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("นี่ไม่ใช่โปรไฟล์ของคุณ", ephemeral=True)
            return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(EditModal(self.uid, self.gid, player))

    async def _delete(self, ix: discord.Interaction):
        if ix.user.id != self.uid and not ix.user.guild_permissions.administrator:
            await ix.response.send_message("ไม่มีสิทธิ์", ephemeral=True)
            return
        view = DeleteConfirmView(self.uid, self.gid)
        embed = discord.Embed(
            title="⚠️ ยืนยันการลบตัวละคร",
            description="ข้อมูลทั้งหมดจะถูกลบอย่างถาวร\nคุณแน่ใจหรือไม่?",
            color=discord.Color.red(),
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class EditModal(discord.ui.Modal, title="แก้ไขโปรไฟล์"):
    name_f      = discord.ui.TextInput(label="ชื่อ",       max_length=60)
    age_f       = discord.ui.TextInput(label="อายุ",        max_length=10)
    gender_f    = discord.ui.TextInput(label="เพศ",         max_length=30)
    appearance_f = discord.ui.TextInput(
        label="รูปลักษณ์",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    image_f = discord.ui.TextInput(
        label="รูป (URL)", required=False, max_length=300
    )

    def __init__(self, uid: int, gid: int, player: dict):
        super().__init__()
        self.uid = uid
        self.gid = gid
        self.name_f.default       = player.get("name", "")
        self.age_f.default        = player.get("age", "")
        self.gender_f.default     = player.get("gender", "")
        self.appearance_f.default = player.get("appearance", "")
        self.image_f.default      = player.get("image", "")

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        p = players.get(str(self.uid), {})
        p["name"]       = self.name_f.value.strip()
        p["age"]        = self.age_f.value.strip()
        p["gender"]     = self.gender_f.value.strip()
        p["appearance"] = self.appearance_f.value.strip()
        p["image"]      = self.image_f.value.strip()
        players[str(self.uid)] = p
        save_players(self.gid, players)
        view  = ProfileView(self.uid, self.gid)
        embed = _profile_embed(self.uid, p, self.gid)
        await ix.response.edit_message(embed=embed, view=view)


class DeleteConfirmView(discord.ui.View):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=60)
        self.uid = uid
        self.gid = gid

    @discord.ui.button(label="ยืนยัน ลบ", style=discord.ButtonStyle.danger)
    async def confirm(self, ix: discord.Interaction, _: discord.ui.Button):
        if ix.user.id != self.uid and not ix.user.guild_permissions.administrator:
            await ix.response.send_message("ไม่มีสิทธิ์", ephemeral=True)
            return
        players = load_players(self.gid)
        players.pop(str(self.uid), None)
        save_players(self.gid, players)
        # Also clear cooldowns
        from core.shared import load_cooldowns, save_cooldowns
        cds = load_cooldowns(self.gid)
        cds.pop(str(self.uid), None)
        save_cooldowns(self.gid, cds)
        await ix.response.edit_message(
            embed=discord.Embed(description="🗑️ ลบตัวละครเรียบร้อย", color=discord.Color.red()),
            view=None,
        )

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.edit_message(
            embed=discord.Embed(description="ยกเลิกการลบ", color=EMBED_COLOR),
            view=None,
        )


# ── /orion command ─────────────────────────────────────────────────────────────

@bot.tree.command(
    name="orion",
    description="ดูโปรไฟล์ตัวละคร หรือสร้างตัวละครใหม่",
)
@app_commands.guilds(*GUILD_OBJECTS)
@app_commands.describe(member="ดูโปรไฟล์ของผู้เล่นอื่น (ไม่ระบุ = ของตัวเอง)")
async def cmd_orion(ix: discord.Interaction, member: discord.Member | None = None):
    gid     = ix.guild_id
    target  = member or ix.user
    uid     = target.id
    players = load_players(gid)
    player  = players.get(str(uid))

    # Check pending
    pending = load_pending(gid)

    if player is None:
        if member:
            await ix.response.send_message(
                embed=discord.Embed(
                    description=f"<@{uid}> ยังไม่มีตัวละคร",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        if str(uid) in pending:
            await ix.response.send_message(
                embed=discord.Embed(
                    description="📋 ใบสมัครของคุณกำลังรอการตรวจสอบจาก Admin",
                    color=0xF59E0B,
                ),
                ephemeral=True,
            )
            return

        # Start creation
        embed = discord.Embed(
            title="🌟 สร้างตัวละครใหม่",
            description=(
                "ยินดีต้อนรับสู่ Orion!\n\n"
                "กดปุ่มด้านล่างเพื่อเริ่มสร้างตัวละคร\n"
                "ตัวละครจะถูกส่งให้ Admin ตรวจสอบก่อนอนุมัติ"
            ),
            color=EMBED_COLOR,
        )
        view = _CreateStartView()
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    embed = _profile_embed(uid, player, gid)
    view  = ProfileView(uid, gid)
    is_ephemeral = member is None
    await ix.response.send_message(embed=embed, view=view, ephemeral=is_ephemeral)


class _CreateStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="✨ สร้างตัวละคร", style=discord.ButtonStyle.success)
    async def start(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(CreateModal1())


# ── /orion-admin command (admin view/delete any player) ───────────────────────

@bot.tree.command(
    name="orion-admin",
    description="[Admin] จัดการข้อมูลผู้เล่น",
)
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_orion_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    view  = AdminPlayerView(ix.guild_id)
    embed = discord.Embed(title="🔧 Admin — Player Management", color=EMBED_COLOR)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class AdminPlayerView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._add_select()

    def _add_select(self):
        sel = discord.ui.UserSelect(placeholder="เลือกผู้เล่น…", row=0)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        target  = ix.data["values"][0]
        uid     = int(target)
        players = load_players(self.gid)
        player  = players.get(str(uid))
        if not player:
            await ix.response.send_message("ผู้เล่นนี้ยังไม่มีตัวละคร", ephemeral=True)
            return
        embed = _profile_embed(uid, player, self.gid)
        view  = AdminViewPlayerActionView(uid, self.gid)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class AdminViewPlayerActionView(discord.ui.View):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=300)
        self.uid = uid
        self.gid = gid

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary)
    async def btn_stats(self, ix: discord.Interaction, _: discord.ui.Button):
        player = load_players(self.gid).get(str(self.uid), {})
        embed  = _stats_embed(self.uid, player)
        await ix.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ ลบตัวละคร", style=discord.ButtonStyle.danger)
    async def btn_delete(self, ix: discord.Interaction, _: discord.ui.Button):
        players = load_players(self.gid)
        name    = players.get(str(self.uid), {}).get("name", str(self.uid))
        players.pop(str(self.uid), None)
        save_players(self.gid, players)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ ลบตัวละคร **{name}** แล้ว",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="💰 แก้ไขเงิน", style=discord.ButtonStyle.secondary)
    async def btn_money(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(AdminSetMoneyModal(self.uid, self.gid))


class AdminSetMoneyModal(discord.ui.Modal, title="ตั้งค่าเงิน"):
    amount = discord.ui.TextInput(label="จำนวนเงิน (ตั้งค่าตรงๆ)", max_length=12)

    def __init__(self, uid: int, gid: int):
        super().__init__()
        self.uid = uid
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        try:
            val     = max(0, int(self.amount.value.strip()))
            players = load_players(self.gid)
            p = players.get(str(self.uid), {})
            p["balance"] = val
            players[str(self.uid)] = p
            save_players(self.gid, players)
            await ix.response.send_message(
                embed=discord.Embed(
                    description=f"✅ ตั้งเงิน <@{self.uid}> เป็น {val:,}",
                    color=EMBED_COLOR,
                ),
                ephemeral=True,
            )
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
