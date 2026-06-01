# ============================================================
# ORION — Skill Toggle (turn-based cooldown)
# ============================================================
# - แต่ละสกิลมี cooldown_turns (admin/player ตั้งได้ผ่าน edit)
# - Player ใช้ /สกิลใช้ → list สกิล + cd ที่เหลือ → กดใช้
# - กดใช้ → cd_remaining = cooldown_turns + tick CD ของสกิลอื่น -1
# - บอทประกาศการใช้สกิลในห้องสาธารณะ
# ============================================================

import sys
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_skill_toggle ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_orion_players   = _orion_bot_mod.load_orion_players
save_orion_players   = _orion_bot_mod.save_orion_players
_parse_int           = _orion_bot_mod._parse_int
make_menu_embed      = _orion_bot_mod.make_menu_embed


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="✨"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


# ── Helpers ──────────────────────────────────────────────────
def _tick_cooldowns(uid: str, exclude_idx: int = None):
    """ลด cd_remaining ทุกสกิลของ uid -1 (ยกเว้น exclude_idx)"""
    data = load_orion_players()
    skills = data.get(uid, {}).get("skills", [])
    changed = False
    for i, sk in enumerate(skills):
        if i == exclude_idx:
            continue
        cd = int(sk.get("cd_remaining", 0))
        if cd > 0:
            sk["cd_remaining"] = cd - 1
            changed = True
    if changed:
        save_orion_players(data)


# ── Player view ──────────────────────────────────────────────
def _skill_use_embed(uid: str, author) -> discord.Embed:
    skills = load_orion_players().get(uid, {}).get("skills", [])
    sections = []
    if not skills:
        sections.append("_ยังไม่มีสกิล — ใช้ `/orion` สร้างสกิลแรก_")
    else:
        ready_count = sum(1 for s in skills if int(s.get("cd_remaining", 0)) <= 0)
        sections.append(f"_สกิลทั้งหมด_  `{len(skills)}`  ·  _พร้อมใช้_  `{ready_count}`")
        for sk in skills[:15]:
            cd = int(sk.get("cd_remaining", 0))
            max_cd = int(sk.get("cooldown_turns", 0))
            status = "🟢 พร้อมใช้" if cd <= 0 else f"⏳ คูลดาวน์ {cd}/{max_cd} เทิร์น"
            sections.append((
                f"{sk.get('emoji','✨')} {sk.get('name','?')}",
                f"{sk.get('context','')[:120]}\n{status}"
            ))
    return make_menu_embed(f"Skills — {author.display_name}", sections, color=0xfdcb6e)


class SkillUseSelect(discord.ui.Select):
    def __init__(self, uid: str, author):
        self.uid = uid
        self.author = author
        skills = load_orion_players().get(uid, {}).get("skills", [])[:25]
        options = []
        for i, sk in enumerate(skills):
            cd = int(sk.get("cd_remaining", 0))
            label_suffix = f" (CD {cd})" if cd > 0 else ""
            options.append(discord.SelectOption(
                label=(sk.get("name","?") + label_suffix)[:100],
                value=str(i),
                description=(sk.get("context","")[:80] or "—"),
                emoji=_safe_emoji(sk.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิล", value="none")]
        super().__init__(placeholder="เลือกสกิลที่จะใช้...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        idx = int(self.values[0])
        data = load_orion_players()
        skills = data.get(self.uid, {}).get("skills", [])
        if idx >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        sk = skills[idx]
        cd = int(sk.get("cd_remaining", 0))
        if cd > 0:
            await ix.response.send_message(f"❌ สกิลนี้คูลดาวน์อยู่ ({cd} เทิร์น)", ephemeral=True); return
        # ใช้สกิล: set cd + tick others
        cooldown_turns = int(sk.get("cooldown_turns", 0))
        sk["cd_remaining"] = cooldown_turns
        save_orion_players(data)
        _tick_cooldowns(self.uid, exclude_idx=idx)
        # ประกาศสาธารณะ
        embed = discord.Embed(
            title=f"{sk.get('emoji','✨')} ใช้สกิล: {sk.get('name','?')}",
            description=sk.get("context") or "_ไม่มีคำอธิบาย_",
            color=0xfdcb6e,
        )
        if sk.get("icon_url"):
            embed.set_thumbnail(url=sk["icon_url"])
        embed.set_author(name=self.author.display_name, icon_url=self.author.display_avatar.url)
        if cooldown_turns > 0:
            embed.add_field(name="คูลดาวน์", value=f"{cooldown_turns} เทิร์น", inline=True)
        embed.set_footer(text="Orion · Skill Used")
        try:
            await ix.channel.send(embed=embed)
            await ix.response.send_message(f"✅ ใช้ **{sk.get('name','?')}** แล้ว (แสดงในห้อง)", ephemeral=True)
        except Exception:
            await ix.response.send_message(embed=embed, ephemeral=False)


class SkillUseView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=300)
        self.uid = uid
        self.author = author
        self.add_item(SkillUseSelect(uid, author))

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=1)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="รีเซ็ตคูลดาวน์ทั้งหมด", style=discord.ButtonStyle.danger, row=1)
    async def b_reset(self, ix, _b):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        data = load_orion_players()
        for sk in data.get(self.uid, {}).get("skills", []):
            sk["cd_remaining"] = 0
        save_orion_players(data)
        await ix.response.edit_message(
            embed=_skill_use_embed(self.uid, self.author),
            view=SkillUseView(self.uid, self.author),
        )


# ── Set cooldown (admin or owner) ────────────────────────────
class SetCooldownModal(discord.ui.Modal, title="ตั้งคูลดาวน์สกิล (เทิร์น)"):
    f_cd = discord.ui.TextInput(label="คูลดาวน์ (เทิร์น)", placeholder="3", max_length=4)

    def __init__(self, uid: str, idx: int):
        super().__init__()
        self.uid = uid
        self.idx = idx
        sk = load_orion_players().get(uid, {}).get("skills", [])[idx]
        self.f_cd.default = str(sk.get("cooldown_turns", 0))

    async def on_submit(self, ix):
        data = load_orion_players()
        skills = data.get(self.uid, {}).get("skills", [])
        if self.idx >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        skills[self.idx]["cooldown_turns"] = max(0, _parse_int(self.f_cd.value, 0) or 0)
        save_orion_players(data)
        await ix.response.send_message(
            f"✅ ตั้งคูลดาวน์ **{skills[self.idx].get('name','?')}** = `{skills[self.idx]['cooldown_turns']}` เทิร์น",
            ephemeral=True,
        )


class SetCooldownSelect(discord.ui.Select):
    def __init__(self, uid: str):
        self.uid = uid
        skills = load_orion_players().get(uid, {}).get("skills", [])[:25]
        options = []
        for i, sk in enumerate(skills):
            cd = int(sk.get("cooldown_turns", 0))
            options.append(discord.SelectOption(
                label=f"{sk.get('name','?')} (CD {cd}t)"[:100],
                value=str(i),
                emoji=_safe_emoji(sk.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิล", value="none")]
        super().__init__(placeholder="เลือกสกิลเพื่อตั้ง CD...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(SetCooldownModal(self.uid, int(self.values[0])))


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="สกิลใช้", description="เปิดเมนูใช้สกิล (มี cooldown เทิร์น)", guild=_ORION_GUILD_OBJ)
async def cmd_skill_use(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    await interaction.response.send_message(
        embed=_skill_use_embed(uid, interaction.user),
        view=SkillUseView(uid, interaction.user),
        ephemeral=True,
    )


@bot.tree.command(name="สกิลตั้งคูลดาวน์", description="ตั้งคูลดาวน์ของสกิลตัวเอง (เทิร์น)", guild=_ORION_GUILD_OBJ)
async def cmd_skill_set_cd(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    view = discord.ui.View(timeout=300)
    view.add_item(SetCooldownSelect(uid))
    embed = make_menu_embed(
        "ตั้งคูลดาวน์สกิล",
        [("วิธีใช้", "เลือกสกิล → ใส่จำนวนเทิร์นที่ต้องรอหลังใช้")],
        color=0xfdcb6e,
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="สกิลตั้งคูลดาวน์ผู้เล่น", description="[Admin] ตั้ง CD ของสกิลผู้เล่นคนอื่น", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(target="ผู้เล่นที่จะตั้ง CD")
async def cmd_skill_set_cd_admin(interaction: discord.Interaction, target: discord.Member):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    uid = str(target.id)
    ensure_orion_player(uid)
    view = discord.ui.View(timeout=300)
    view.add_item(SetCooldownSelect(uid))
    await interaction.response.send_message(
        f"ตั้ง CD สกิลของ **{target.display_name}** ↓",
        view=view, ephemeral=True,
    )
