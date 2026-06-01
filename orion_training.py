# ============================================================
# ORION — Skill Training System (separate module)
# ============================================================
# Pool ทักษะแบ่งเป็นหมวดหมู่ (Technique / Magic / etc.) แต่ละหมวด:
#   - มี minigame
#   - มี pool ของสกิลที่จะสุ่มแจกถ้าผู้เล่นผ่าน
# Admin แก้ได้ผ่าน /ฝึกแอดมิน
# ============================================================

import re
import sys
import time
import random as _rand
import asyncio
import discord

# ── ดึง dependencies จาก orion_bot ────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_training ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_orion_players   = _orion_bot_mod.load_orion_players
save_orion_players   = _orion_bot_mod.save_orion_players
_parse_int           = _orion_bot_mod._parse_int
MINIGAME_LABELS      = _orion_bot_mod.MINIGAME_LABELS
_run_minigame        = _orion_bot_mod._run_minigame


def _safe_emoji(s, default="✨"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


TRAINING_FILE = f"{ORION_DATA_DIR}/training_pools.json"


# ── Storage ──────────────────────────────────────────────────
def load_pools() -> dict:
    return load_json(TRAINING_FILE, {})


def save_pools(d: dict):
    save_json(TRAINING_FILE, d)


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w฀-๿]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or f"cat_{int(time.time())}"


def _norm_icon(icon_input: str):
    """คืน (emoji, icon_url) — เหมือนใน orion_items"""
    s = (icon_input or "").strip()
    if s.lower().startswith(("http://", "https://")):
        return ("✨", s)
    return (s or "✨", "")


# ── Embeds ───────────────────────────────────────────────────
def _categories_embed() -> discord.Embed:
    pools = load_pools()
    embed = discord.Embed(
        title="🎓  ระบบฝึกฝน — Orion",
        description=(
            "เลือกหมวดหมู่ที่อยากเรียนจาก dropdown ด้านล่าง\n"
            "ผ่านมินิเกม → สุ่มรับสกิลจาก pool ของหมวดนั้น"
        ),
        color=0xfdcb6e,
    )
    if not pools:
        embed.add_field(name="​", value="_ยังไม่มีหมวดหมู่ — รอแอดมินเพิ่ม_", inline=False)
    else:
        for cid, cat in list(pools.items())[:20]:
            embed.add_field(
                name=f"{cat.get('emoji','✨')} {cat.get('name','?')} ({len(cat.get('pool',[]))} สกิล)",
                value=(cat.get("description","")[:200] or "_ไม่มีคำอธิบาย_"),
                inline=False,
            )
    embed.set_footer(text="Orion · Training")
    return embed


def _category_detail_embed(cid: str, cat: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{cat.get('emoji','✨')}  {cat.get('name','?')}",
        description=cat.get("description") or "_ไม่มีคำอธิบาย_",
        color=0xfdcb6e,
    )
    if cat.get("icon_url"):
        embed.set_thumbnail(url=cat["icon_url"])
    embed.add_field(name="🎮 มินิเกม", value=MINIGAME_LABELS.get(cat.get("minigame",""), "—"), inline=True)
    embed.add_field(name="📚 สกิลใน Pool", value=f"**{len(cat.get('pool',[]))}** สกิล", inline=True)
    embed.add_field(name="🆔 ID", value=f"`{cid}`", inline=True)
    pool = cat.get("pool", [])
    if pool:
        lines = [f"{s.get('emoji','✨')} **{s.get('name','?')}**" for s in pool[:15]]
        embed.add_field(name="📋 รายการสกิล", value="\n".join(lines), inline=False)
    embed.set_footer(text="Orion · Training Pool")
    return embed


# ── helpers exposed from orion_bot ───────────────────────────
cooldown_remaining = getattr(_orion_bot_mod, "cooldown_remaining", None)
set_cooldown       = getattr(_orion_bot_mod, "set_cooldown", None)
format_cooldown    = getattr(_orion_bot_mod, "format_cooldown", lambda s: f"{s}s")


def _visible_pools_for(uid: str) -> dict:
    """filter pools: hidden pools เห็นเฉพาะ VIP"""
    pools = load_pools()
    visible = {}
    for cid, cat in pools.items():
        if cat.get("hidden", False):
            vip_ids = cat.get("vip_user_ids", [])
            if uid not in vip_ids:
                continue
        visible[cid] = cat
    return visible


# ── Player flow ──────────────────────────────────────────────
class TrainingCategorySelect(discord.ui.Select):
    def __init__(self, uid: str):
        self.uid = uid
        pools = _visible_pools_for(uid)
        options = []
        for cid, cat in list(pools.items())[:25]:
            cd_left = cooldown_remaining(uid, f"train:{cid}") if cooldown_remaining else 0
            desc_extra = f" · CD {format_cooldown(cd_left)}" if cd_left > 0 else ""
            hidden_mark = " 🔒" if cat.get("hidden") else ""
            options.append(discord.SelectOption(
                label=(cat.get("name","?") + hidden_mark)[:100],
                value=cid,
                description=f"{len(cat.get('pool',[]))} สกิล · {MINIGAME_LABELS.get(cat.get('minigame',''),'—')}{desc_extra}"[:80],
                emoji=_safe_emoji(cat.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีหมวดหมู่", value="none")]
        super().__init__(placeholder="เลือกหมวดหมู่ที่จะฝึก...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        cid = self.values[0]
        cat = load_pools().get(cid, {})
        if not cat.get("pool"):
            await ix.response.send_message(
                f"❌ หมวด **{cat.get('name','?')}** ยังไม่มีสกิลใน pool",
                ephemeral=True,
            ); return
        # ส่ง embed ยืนยัน + ปุ่มเริ่ม
        await ix.response.send_message(
            embed=_category_detail_embed(cid, cat),
            view=TrainingStartView(self.uid, cid),
            ephemeral=True,
        )


class TrainingMenuView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=300)
        self.add_item(TrainingCategorySelect(uid))


class TrainingStartView(discord.ui.View):
    def __init__(self, uid: str, cid: str):
        super().__init__(timeout=180)
        self.uid = uid
        self.cid = cid

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="เริ่มฝึก", style=discord.ButtonStyle.success)
    async def btn_start(self, ix: discord.Interaction, _b):
        cat = load_pools().get(self.cid, {})
        pool = cat.get("pool", [])
        if not pool:
            await ix.response.send_message("❌ ไม่มีสกิลใน pool", ephemeral=True); return
        # check cooldown
        cd_key = f"train:{self.cid}"
        if cooldown_remaining:
            left = cooldown_remaining(self.uid, cd_key)
            if left > 0:
                await ix.response.send_message(
                    f"⏳ คูลดาวน์: ต้องรอ **{format_cooldown(left)}** ก่อนฝึก {cat.get('name','?')} อีกครั้ง",
                    ephemeral=True,
                ); return
        await ix.response.defer(ephemeral=True)
        minigame = cat.get("minigame", "")
        result = await _run_minigame(ix, minigame)
        if not result:
            # apply fail cooldown
            fail_cd = int(cat.get("fail_cooldown_sec", 0))
            if fail_cd > 0 and set_cooldown:
                set_cooldown(self.uid, cd_key, fail_cd)
                await ix.followup.send(
                    f"💔 ฝึกล้มเหลว — คูลดาวน์ **{format_cooldown(fail_cd)}**",
                    ephemeral=True,
                ); return
            await ix.followup.send("💔 ฝึกล้มเหลว — ลองใหม่ได้", ephemeral=True); return
        # สุ่มสกิล
        choices = list(pool)
        # ตัดสกิลที่ผู้เล่นมีอยู่แล้ว
        ensure_orion_player(self.uid)
        pdata = load_orion_players()
        existing_names = {s.get("name","").lower() for s in pdata[self.uid].get("skills", [])}
        new_pool = [s for s in choices if s.get("name","").lower() not in existing_names]
        if not new_pool:
            await ix.followup.send(
                f"⚠️ ผ่านมินิเกมแล้ว แต่คุณมีสกิลทุกอันใน pool **{cat.get('name','?')}** อยู่แล้ว",
                ephemeral=True,
            ); return
        skill = _rand.choice(new_pool)
        pdata[self.uid].setdefault("skills", []).append({
            "name":     skill.get("name","?"),
            "context":  skill.get("description",""),
            "emoji":    skill.get("emoji","✨"),
            "icon_url": skill.get("icon_url",""),
            "origin_type": cat.get("name", "Training"),
        })
        save_orion_players(pdata)
        embed = discord.Embed(
            title=f"🎉 ฝึกสำเร็จ! ได้สกิลใหม่",
            description=f"{skill.get('emoji','✨')} **{skill.get('name','?')}**\n\n{skill.get('description','')}",
            color=0x2ecc71,
        )
        if skill.get("icon_url"):
            embed.set_thumbnail(url=skill["icon_url"])
        embed.set_footer(text=f"จาก pool: {cat.get('name','?')}")
        await ix.followup.send(embed=embed, ephemeral=True)


# ── Admin flow ───────────────────────────────────────────────
class CategoryAddModal(discord.ui.Modal, title="➕ เพิ่มหมวดหมู่ฝึกฝน"):
    f_name = discord.ui.TextInput(label="ชื่อหมวด (เช่น Technique / Magic)", max_length=50)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL รูป)", placeholder="🥋 หรือ https://...", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=500)

    async def on_submit(self, ix: discord.Interaction):
        pools = load_pools()
        cid = _slug(self.f_name.value)
        if cid in pools:
            cid = f"{cid}_{int(time.time())}"
        emoji, icon_url = _norm_icon(self.f_icon.value)
        pools[cid] = {
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": (self.f_desc.value or "").strip(),
            "minigame": "guess_number",   # default — admin เลือกหลังได้
            "pool": [],
        }
        save_pools(pools)
        await ix.response.send_message(
            f"✅ เพิ่มหมวด `{cid}` — {emoji} **{pools[cid]['name']}** แล้ว\n"
            f"_หมายเหตุ: ตั้งมินิเกมและเพิ่มสกิลผ่าน /ฝึกแอดมิน ต่อ_",
            ephemeral=True,
        )


class CategorySelectAdmin(discord.ui.Select):
    """Dropdown หมวดหมู่สำหรับ admin"""
    def __init__(self, placeholder: str, action: str):
        self.action = action
        pools = load_pools()
        options = []
        for cid, cat in list(pools.items())[:25]:
            options.append(discord.SelectOption(
                label=cat.get("name","?")[:100],
                value=cid,
                description=f"{len(cat.get('pool',[]))} สกิล"[:80],
                emoji=_safe_emoji(cat.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีหมวด", value="none")]
        super().__init__(placeholder=placeholder, options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cid = self.values[0]
        if self.action == "delete":
            pools = load_pools()
            removed = pools.pop(cid, None)
            save_pools(pools)
            await ix.response.edit_message(
                content=f"🗑️ ลบหมวด `{cid}` ({removed.get('name') if removed else '?'}) แล้ว",
                view=None,
            )
        elif self.action == "set_minigame":
            view = discord.ui.View(timeout=120)
            view.add_item(MinigameSetSelect(cid))
            await ix.response.edit_message(
                content=f"🎮 เลือกมินิเกมใหม่สำหรับหมวด `{cid}` ↓",
                view=view,
            )
        elif self.action == "add_skill":
            await ix.response.send_modal(SkillAddModal(cid))
        elif self.action == "view":
            cat = load_pools().get(cid, {})
            await ix.response.send_message(
                embed=_category_detail_embed(cid, cat),
                view=SkillDeleteView(cid),
                ephemeral=True,
            )
        elif self.action == "vip":
            v = discord.ui.View(timeout=300)
            v.add_item(TrainingVipUserSelect(cid))
            await ix.response.send_message(
                f"ติ๊กผู้เล่นที่จะได้สิทธิ์เข้าหมวด `{cid}` (ทับของเดิม) ↓",
                view=v, ephemeral=True,
            )
        elif self.action == "cooldown":
            await ix.response.send_modal(TrainingCooldownModal(cid))


class MinigameSetSelect(discord.ui.Select):
    def __init__(self, cid: str):
        self.cid = cid
        options = [discord.SelectOption(label=label, value=key) for key, label in MINIGAME_LABELS.items()]
        super().__init__(placeholder="🎮 เลือกมินิเกม...", options=options)

    async def callback(self, ix: discord.Interaction):
        pools = load_pools()
        if self.cid not in pools:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        pools[self.cid]["minigame"] = self.values[0]
        save_pools(pools)
        await ix.response.edit_message(
            content=f"✅ ตั้งมินิเกมของ `{self.cid}` เป็น **{MINIGAME_LABELS.get(self.values[0])}**",
            view=None,
        )


class SkillAddModal(discord.ui.Modal, title="✨ เพิ่มสกิลเข้า Pool"):
    f_name = discord.ui.TextInput(label="ชื่อสกิล", max_length=80)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL รูป)", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบายสกิล", style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, cid: str):
        super().__init__()
        self.cid = cid

    async def on_submit(self, ix: discord.Interaction):
        pools = load_pools()
        if self.cid not in pools:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        emoji, icon_url = _norm_icon(self.f_icon.value)
        pools[self.cid].setdefault("pool", []).append({
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": self.f_desc.value.strip(),
        })
        save_pools(pools)
        await ix.response.send_message(
            f"✅ เพิ่ม {emoji} **{self.f_name.value}** เข้า pool `{self.cid}` แล้ว",
            ephemeral=True,
        )


class SkillDeleteView(discord.ui.View):
    def __init__(self, cid: str):
        super().__init__(timeout=300)
        self.cid = cid
        self.add_item(SkillDeleteSelect(cid))


class SkillDeleteSelect(discord.ui.Select):
    def __init__(self, cid: str):
        self.cid = cid
        pool = load_pools().get(cid, {}).get("pool", [])
        options = []
        for i, s in enumerate(pool[:25]):
            options.append(discord.SelectOption(
                label=s.get("name","?")[:100],
                value=str(i),
                description=(s.get("description","")[:80] or "—"),
                emoji=_safe_emoji(s.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิลใน pool", value="none")]
        super().__init__(placeholder="🗑️ เลือกสกิลที่จะลบ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        idx = int(self.values[0])
        pools = load_pools()
        pool = pools.get(self.cid, {}).get("pool", [])
        if idx >= len(pool):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        removed = pool.pop(idx)
        save_pools(pools)
        await ix.response.send_message(
            f"🗑️ ลบสกิล **{removed.get('name')}** ออกจาก pool `{self.cid}` แล้ว",
            ephemeral=True,
        )


class TrainingAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="เพิ่มหมวดหมู่", style=discord.ButtonStyle.success, row=0)
    async def btn_add_cat(self, ix, _b):
        await ix.response.send_modal(CategoryAddModal())

    @discord.ui.button(label="ลบหมวดหมู่", style=discord.ButtonStyle.danger, row=0)
    async def btn_del_cat(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("🗑️ เลือกหมวดที่จะลบ...", action="delete"))
        await ix.response.send_message("🗑️ เลือกหมวดจาก dropdown ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ตั้งมินิเกม", style=discord.ButtonStyle.primary, row=0)
    async def btn_set_mg(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("🎮 เลือกหมวดที่จะตั้งมินิเกม...", action="set_minigame"))
        await ix.response.send_message("🎮 เลือกหมวดจาก dropdown ↓", view=view, ephemeral=True)

    @discord.ui.button(label="เพิ่มสกิลเข้า Pool", style=discord.ButtonStyle.success, row=1)
    async def btn_add_skill(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("✨ เลือกหมวดที่จะเพิ่มสกิล...", action="add_skill"))
        await ix.response.send_message("✨ เลือกหมวดจาก dropdown ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ดู/ลบสกิลใน Pool", style=discord.ButtonStyle.secondary, row=1)
    async def btn_view(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("📚 เลือกหมวดที่จะดู...", action="view"))
        await ix.response.send_message("📚 เลือกหมวดจาก dropdown ↓", view=view, ephemeral=True)

    @discord.ui.button(label="ตั้ง VIP (หมวดซ่อน)", style=discord.ButtonStyle.primary, row=2)
    async def btn_vip(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("เลือกหมวดที่จะตั้ง VIP...", action="vip"))
        await ix.response.send_message("เลือกหมวด ↓ (จะแสดง dropdown ผู้เล่นที่เข้าถึงได้)", view=view, ephemeral=True)

    @discord.ui.button(label="ตั้งคูลดาวน์ตอนแพ้", style=discord.ButtonStyle.primary, row=2)
    async def btn_cd(self, ix, _b):
        view = discord.ui.View(timeout=180)
        view.add_item(CategorySelectAdmin("เลือกหมวดที่จะตั้ง CD...", action="cooldown"))
        await ix.response.send_message("เลือกหมวด ↓", view=view, ephemeral=True)


class TrainingVipUserSelect(discord.ui.UserSelect):
    def __init__(self, cid: str):
        super().__init__(placeholder="ติ๊กผู้เล่น VIP (เลือกได้หลายคน, ทับของเดิม)...", min_values=0, max_values=25)
        self.cid = cid

    async def callback(self, ix: discord.Interaction):
        pools = load_pools()
        if self.cid not in pools:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        uids = [str(u.id) for u in self.values if not u.bot]
        pools[self.cid]["vip_user_ids"] = uids
        pools[self.cid]["hidden"] = bool(uids)   # ถ้ามี VIP = ทำเป็นหมวดซ่อน
        save_pools(pools)
        names = ", ".join(u.display_name for u in self.values[:25]) or "(ไม่มี — หมวดจะเปิดให้ทุกคน)"
        await ix.response.send_message(
            f"✅ ตั้ง VIP ของ `{self.cid}` แล้ว — สมาชิก: {names}",
            ephemeral=True,
        )


class TrainingCooldownModal(discord.ui.Modal, title="ตั้งคูลดาวน์ตอนแพ้"):
    f_sec = discord.ui.TextInput(label="วินาที (0 = ไม่มี CD)", placeholder="300", max_length=8)

    def __init__(self, cid: str):
        super().__init__()
        self.cid = cid
        existing = load_pools().get(cid, {}).get("fail_cooldown_sec", 0)
        self.f_sec.default = str(existing)

    async def on_submit(self, ix: discord.Interaction):
        pools = load_pools()
        if self.cid not in pools:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        sec = max(0, _parse_int(self.f_sec.value, 0) or 0)
        pools[self.cid]["fail_cooldown_sec"] = sec
        save_pools(pools)
        await ix.response.send_message(f"✅ CD เมื่อแพ้ของ `{self.cid}` = {sec} วินาที", ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="ฝึกสกิล", description="ฝึกฝนเพื่อเรียนรู้สกิลใหม่จากหมวดที่เลือก", guild=_ORION_GUILD_OBJ)
async def cmd_training(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    eph = _orion_bot_mod._eph("ฝึกสกิล") if hasattr(_orion_bot_mod, "_eph") else True
    if False: pass   # placeholder for future hook
    uid = str(interaction.user.id)
    await interaction.response.send_message(
        embed=_categories_embed(),
        view=TrainingMenuView(uid),
        ephemeral=eph,
    )


@bot.tree.command(name="ฝึกแอดมิน", description="[Admin] จัดการหมวด/สกิลใน Pool ฝึกฝน", guild=_ORION_GUILD_OBJ)
async def cmd_training_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    pools = load_pools()
    embed = discord.Embed(
        title="🎓  Training — Admin Panel",
        description=(
            f"**หมวดหมู่ในระบบ:** {len(pools)} หมวด\n\n"
            "**Row 0** — ➕ เพิ่มหมวด · 🗑️ ลบหมวด · 🎮 ตั้งมินิเกม\n"
            "**Row 1** — ✨ เพิ่มสกิล · 📚 ดู/ลบสกิล\n\n"
            "_ผู้เล่นใช้ `/ฝึกสกิล` เพื่อฝึก — สุ่มได้สกิลจาก pool ของหมวดที่เลือก_"
        ),
        color=0xfdcb6e,
    )
    await interaction.response.send_message(embed=embed, view=TrainingAdminView(), ephemeral=True)
